"""命令行入口 ``tandem``。

子命令：
- ``tandem demo``：用临时数据库和假 Agent 跑两个场景，打印状态路径；
- ``tandem status`` / ``show``：列出任务或查看完整记录；
- ``tandem run``：只用假证据驱动本地任务；
- ``tandem submit`` / ``approve`` / ``reject`` / ``cancel``：对任务做相应操作。
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from tandem.core.level import compute_level
from tandem.core.model import (
    ChangeSet,
    Event,
    EventKind,
    Level,
    Policy,
    Review,
    RunMode,
    TaskRecord,
    TaskStatus,
    Verdict,
    VetoReason,
)
from tandem.shell import serde
from tandem.shell.agents.fake import FakeAgent
from tandem.shell.config import load_policy
from tandem.shell.diff_source import DiffSource, FakeDiffSource, GitDiffSource
from tandem.shell.executor import Executor
from tandem.shell.local_run import LocalRun
from tandem.shell.receipt import Receipt, parse_receipt, render_receipt
from tandem.shell.runner import Runner, RunnerError
from tandem.shell.store import Store

DEFAULT_DB = Path("data") / "tandem.sqlite3"


# ---------------------------------------------------------------- 小工具


def _clock() -> datetime:
    return datetime.now(UTC)


def _event(kind: EventKind, task: TaskRecord, **fields: object) -> Event:
    """带版本号的事件：外壳看到的是哪一版，就带上哪一版。"""
    return Event(
        kind=kind,
        task_id=task.task_id,
        state_version=task.state_version,
        **fields,  # type: ignore[arg-type]
    )


def _veto_reasons(args: argparse.Namespace) -> tuple[VetoReason, ...]:
    """把 ``--veto F1=理由`` 解析成逐条理由。"""
    raw = getattr(args, "veto", None)
    if not isinstance(raw, list):
        return ()
    reasons: list[VetoReason] = []
    for item in cast("list[object]", raw):
        text = str(item)
        finding_id, _, reason = text.partition("=")
        reasons.append(VetoReason(finding_id=finding_id.strip(), reason=reason.strip()))
    return tuple(reasons)


def _db_path(args: argparse.Namespace) -> Path:
    value = getattr(args, "db", None)
    return value if isinstance(value, Path) else DEFAULT_DB


def _open(
    db: Path,
    agents: dict[str, FakeAgent] | None = None,
    policy: Policy | None = None,
    diff_source: DiffSource | None = None,
) -> tuple[Store, Runner]:
    store = Store(db)
    executor = Executor(agents=agents if agents is not None else {}, dry_run=True)
    return store, Runner(
        store=store,
        policy=policy if policy is not None else load_policy(),
        executor=executor,
        diff_source=diff_source if diff_source is not None else GitDiffSource(),
        clock=_clock,
    )


def _print_decision(runner: Runner, event: Event) -> bool:
    """处理一个事件并打印结果。返回"内核是否真的改了状态"。"""
    result = runner.handle(event)
    task = result.decision.task
    print(f"{task.task_id}：{task.status.value}")
    if result.decision.changed:
        print(f"  原因：{result.decision.reason}")
    else:
        print(f"  没有生效：{result.decision.reason}")
    for action in result.executed:
        print(f"  动作：{action.message}")
    return result.decision.changed


# ---------------------------------------------------------------- status


def cmd_status(args: argparse.Namespace) -> int:
    db = _db_path(args)
    if not db.exists():
        print(f"还没有数据库：{db}（先跑 tandem demo 或 tandem submit）")
        return 1
    with Store(db) as store:
        tasks = store.list_tasks()
        if not tasks:
            print("还没有任务")
            return 0
        print(f"{'任务':<20}{'状态':<16}{'等级':<6}{'版本':<6}{'提交编号':<12}原因")
        for task in tasks:
            sha = (task.latest_sha or "-")[:8]
            print(
                f"{task.task_id:<20}{task.status.value:<16}{task.level.value:<6}"
                f"{task.state_version:<6}{sha:<12}{task.reason}"
            )
    return 0


# ---------------------------------------------------------------- show


def _print_summary(task: TaskRecord) -> None:
    """把批准前最需要核对的证据放在完整 JSON 之前。"""
    print("批准前请先写下自己的判断，再对照下方 AI 审核意见。")
    # 内核目前只保存布尔绿灯，False 不能单独证明已收到红灯。
    print(f"CI：{'绿（当前提交）' if task.ci_green else '未通过或未知（没有有效绿灯）'}")
    if task.approved_sha is None:
        print("批准的提交：无（尚未批准）")
    else:
        match = "与当前一致" if task.approved_sha == task.latest_sha else "与当前不一致"
        print(f"批准的提交：{task.approved_sha}（{match}）")
    reviews = {item.provider: item for item in task.current_reviews()}
    providers = dict.fromkeys((*task.designated_reviewers, *reviews))
    conclusions = " / ".join(
        f"{provider} {reviews[provider].verdict.value if provider in reviews else '待回应'}"
        for provider in providers
    )
    print(f"本轮审核：{conclusions or '无本轮 AI 审核结论'}")
    print(f"待回应意见：{len(task.open_findings)} 条（复合键见下方完整记录）")
    if task.plan_version == 0:
        print("方案：尚无方案版本")
    else:
        approved = task.approved_plan_version == task.plan_version
        print(f"方案：第 {task.plan_version} 版{'已批准' if approved else '待批准'}")


def cmd_show(args: argparse.Namespace) -> int:
    """完整展示任务与事件，批准前可以核对提交和逐条意见。"""
    db = _db_path(args)
    if not db.exists():
        print(f"还没有数据库：{db}")
        return 1
    with Store(db) as store:
        task = store.load_task(args.task_id)
        if task is None:
            print(f"没有任务 {args.task_id}")
            return 1
        print(f"{task.task_id}：{task.status.value}；等级 {task.level.value}")
        print(f"提交编号：{task.latest_sha or '无'}")
        _print_summary(task)
        print("完整任务记录（含审核历史、待回应意见及其复合键、动作）：")
        print(json.dumps(serde.task_to_dict(task), ensure_ascii=False, indent=2))
        print("历史事件（按发生顺序）：")
        print(
            json.dumps(
                [serde.event_to_dict(event) for event in store.list_events(task.task_id)],
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


# ---------------------------------------------------------------- submit


def _changes_from_args(args: argparse.Namespace) -> ChangeSet:
    paths = tuple(item.strip() for item in (args.paths or "").split(",") if item.strip())
    deleted = tuple(item.strip() for item in (args.deleted or "").split(",") if item.strip())
    return ChangeSet(
        paths=paths,
        deleted_paths=deleted,
        secret_scan_hit=bool(args.secret_scan_hit),
    )


def cmd_submit(args: argparse.Namespace) -> int:
    policy = load_policy()
    if args.mode is not None:
        mode = RunMode.SINGLE_AGENT if args.mode == "single_agent" else RunMode.MULTI_AGENT
        policy = replace(policy, run_mode=mode)
    store, runner = _open(_db_path(args), policy=policy)
    try:
        changes = _changes_from_args(args)
        level = compute_level(changes, runner.policy)
        runner.submit(args.task_id, level)
        print(f"已提交 {args.task_id}：等级 {level.value}")
        print(f"  改动：{', '.join(changes.all_paths) or '不改仓库'}")
        return 0
    except RunnerError as error:
        print(f"提交失败：{error}")
        return 1
    finally:
        store.close()


# ---------------------------------------------------------------- run


def cmd_run(args: argparse.Namespace) -> int:
    db = _db_path(args)
    if not db.is_file():
        print(f"还没有数据库：{db}（请先 submit）")
        return 1
    policy = load_policy()
    agents = {provider: FakeAgent(provider=provider) for provider in policy.writer_providers}
    changes = ChangeSet(
        paths=tuple(path.strip() for path in args.changes.split(",") if path.strip())
    )
    store, runner = _open(
        db, agents=agents, policy=policy, diff_source=FakeDiffSource(changes=changes)
    )
    try:
        return LocalRun(
            runner,
            agents,
            args.agent_script,
            args.review,
            allow_level_drop=args.allow_level_drop,
        ).run(until_idle=args.until_idle, max_rounds=args.max_rounds)
    finally:
        store.close()


# ---------------------------------------------------------------- approve / reject


def cmd_approve(args: argparse.Namespace) -> int:
    store, runner = _open(_db_path(args))
    try:
        task = store.load_task(args.task_id)
        if task is None:
            print(f"没有任务 {args.task_id}")
            return 1
        match task.status:
            case TaskStatus.AWAITING_PLAN_APPROVAL:
                event = _event(EventKind.PLAN_APPROVED, task, sha=args.sha)
            case TaskStatus.AWAITING_YOUR_REVIEW:
                # "待你审核"是你批准 AI 写完的代码，走第 17 条
                event = _event(
                    EventKind.YOUR_APPROVAL,
                    task,
                    sha=args.sha,
                    reason=args.reason,
                    veto_reasons=_veto_reasons(args),
                )
            case TaskStatus.NEEDS_INTERVENTION:
                # "待你介入"是人工审核通过 / 批准你自己的代码，走第 20 条
                event = _event(
                    EventKind.INTERVENTION_APPROVED,
                    task,
                    sha=args.sha,
                    reason=args.reason,
                    veto_reasons=_veto_reasons(args),
                )
            case _:
                print(f"{task.task_id} 在{task.status.value}，现在不需要你批准")
                return 1
        return 0 if _print_decision(runner, event) else 2
    finally:
        store.close()


def cmd_reject(args: argparse.Namespace) -> int:
    store, runner = _open(_db_path(args))
    try:
        task = store.load_task(args.task_id)
        if task is None:
            print(f"没有任务 {args.task_id}")
            return 1
        match task.status:
            case TaskStatus.AWAITING_PLAN_APPROVAL:
                event = _event(EventKind.PLAN_REJECTED, task, reason=args.reason)
            case TaskStatus.AWAITING_YOUR_REVIEW:
                event = _event(EventKind.YOUR_REJECTION, task, reason=args.reason)
            case _:
                print(f"{task.task_id} 在{task.status.value}，现在不能打回")
                return 1
        return 0 if _print_decision(runner, event) else 2
    finally:
        store.close()


# ---------------------------------------------------------------- cancel


def cmd_cancel(args: argparse.Namespace) -> int:
    store, runner = _open(_db_path(args))
    try:
        task = store.load_task(args.task_id)
        if task is None:
            print(f"没有任务 {args.task_id}")
            return 1
        changed = _print_decision(runner, _event(EventKind.CANCEL, task, reason=args.reason))
        return 0 if changed else 2
    finally:
        store.close()


# ---------------------------------------------------------------- demo


def _demo_receipt(task_id: str, attempt: int, conclusion: str) -> str:
    """demo 的回执：只带必填字段。改动由采集器给，回执里写 changes 会被忽略。"""
    return render_receipt(
        conclusion,
        {
            "task_id": task_id,
            "attempt": attempt,
            "sha": f"demo-{task_id}-{attempt}",
        },
    )


def _demo_plan_receipt(task_id: str, attempt: int, plan: str) -> str:
    return render_receipt(
        "PLAN：先交方案，等你批准",
        {
            "task_id": task_id,
            "attempt": attempt,
            "sha": f"demo-{task_id}-plan",
            "plan": plan,
        },
    )


def _print_path(task_id: str, title: str, statuses: list[TaskStatus]) -> None:
    collapsed: list[str] = []
    for status in statuses:
        if not collapsed or collapsed[-1] != status.value:
            collapsed.append(status.value)
    print(f"{title}")
    print(f"  {task_id}：{' → '.join(collapsed)}")


def _demo_policy() -> Policy:
    """demo 的场景 1 需要多 Agent 模式。

    risk.yml 的默认值是 M1 的真实配置（单 Agent 模式），demo 不能靠改默认值来跑，
    而是在这里显式覆盖，免得默认配置为了 demo 而失真。
    """
    return replace(load_policy(), run_mode=RunMode.MULTI_AGENT)


def _expect(ok: bool, message: str) -> bool:
    """场景断言：不符合就打印出来，让 demo 返回非零。"""
    if not ok:
        print(f"场景失败：{message}")
    return ok


def run_demo(policy_: Policy | None = None) -> int:
    """两个场景都跑一遍，用一个临时数据库。返回 0 表示两个场景都走到了预期状态。"""
    demo_policy = policy_ if policy_ is not None else _demo_policy()
    with tempfile.TemporaryDirectory(prefix="tandem-demo-") as directory:
        db = Path(directory) / "tandem.sqlite3"
        claude = FakeAgent(
            provider="claude",
            script=[
                _demo_receipt("demo-c", 1, "DONE：写完了 C 级任务"),
                _demo_plan_receipt("demo-d", 1, "先改 core 里的 decide，再接外壳"),
            ],
        )
        # demo 用假采集器：声称这次真实改动是改了一个外壳文件
        diff_source = FakeDiffSource(changes=ChangeSet(paths=("src/tandem/shell/cli.py",)))
        store, runner = _open(db, {"claude": claude}, demo_policy, diff_source)
        try:
            # 场景 1：C 级任务，多 Agent 模式，走到已合并（dry-run）
            path_c: list[TaskStatus] = [TaskStatus.PENDING]
            runner.submit("demo-c", Level.C)
            started = runner.handle(
                Event(kind=EventKind.ASSIGN, task_id="demo-c", provider="claude")
            )
            path_c.append(started.decision.task.status)
            receipt: Receipt = parse_receipt(started.receipts[0])
            task_c_pending = runner.store.load_task("demo-c")
            if task_c_pending is None:  # pragma: no cover - 刚提交过，不可能没有
                raise RunnerError("场景 1 没有留下任务记录")
            received = runner.handle(runner.code_event(task_c_pending, receipt))
            path_c.append(received.decision.task.status)

            ci = runner.handle(Event(kind=EventKind.CI_GREEN, task_id="demo-c", sha=receipt.sha))
            path_c.append(ci.decision.task.status)
            for reviewer in ci.decision.task.designated_reviewers:
                handed = runner.handle(
                    Event(
                        kind=EventKind.REVIEW,
                        task_id="demo-c",
                        review=Review(
                            reviewer=reviewer,
                            provider=reviewer,
                            verdict=Verdict.PASS,
                            sha=receipt.sha,
                            standard_version=1,
                        ),
                    )
                )
                path_c.append(handed.decision.task.status)
            finished = runner.handle(
                Event(kind=EventKind.MERGED, task_id="demo-c", sha=receipt.sha)
            )
            path_c.append(finished.decision.task.status)
            _print_path("demo-c", "场景 1：C 级任务，多 Agent 模式（合并是 dry-run）", path_c)

            task_c = runner.store.load_task("demo-c")
            ok = _expect(task_c is not None, "场景 1 没有留下任务记录")
            actual_c = task_c.status.value if task_c else "无"
            ok = (
                _expect(
                    task_c is not None and task_c.status is TaskStatus.MERGED,
                    f"场景 1 应该走到已合并，实际是 {actual_c}",
                )
                and ok
            )
            ok = (
                _expect(
                    task_c is not None and task_c.latest_sha == receipt.sha,
                    "场景 1 记录的提交编号应该和回执一致",
                )
                and ok
            )

            # 场景 2：D 级任务，停在"待你批准方案"
            path_d: list[TaskStatus] = [TaskStatus.PENDING]
            runner.submit("demo-d", Level.D)
            begun = runner.handle(Event(kind=EventKind.ASSIGN, task_id="demo-d", provider="claude"))
            path_d.append(begun.decision.task.status)
            plan_receipt = parse_receipt(begun.receipts[0])
            plan = runner.handle(
                Event(
                    kind=EventKind.PLAN_SUBMITTED,
                    task_id="demo-d",
                    sha=plan_receipt.sha,
                    plan=plan_receipt.plan,
                )
            )
            path_d.append(plan.decision.task.status)
            _print_path("demo-d", "场景 2：D 级任务（停在待你批准方案）", path_d)

            task_d = runner.store.load_task("demo-d")
            actual_d = task_d.status.value if task_d else "无"
            ok = (
                _expect(
                    task_d is not None and task_d.status is TaskStatus.AWAITING_PLAN_APPROVAL,
                    f"场景 2 应该停在待你批准方案，实际是 {actual_d}",
                )
                and ok
            )
            ok = (
                _expect(
                    task_d is not None and task_d.latest_sha == plan_receipt.sha,
                    "场景 2 记录的提交编号应该和方案回执一致",
                )
                and ok
            )

            print()
            print("两个场景都用假 Agent，没有调用任何真实 AI。")
            print("合并、关闭 PR、通知这些动作都是 dry-run，只记了日志：")
            for line in runner.executor.log:
                print(f"  {line}")
            return 0 if ok else 1
        finally:
            store.close()


def cmd_demo(_args: argparse.Namespace) -> int:
    return run_demo()


# ---------------------------------------------------------------- 入口


def _positive_rounds(value: str) -> int:
    rounds = int(value)
    if rounds < 1:
        raise argparse.ArgumentTypeError("最大轮数必须大于 0")
    return rounds


def _nonempty_changes(value: str) -> str:
    """不能用空的模拟改动把任务变成无需审核的 A 级。"""
    if not any(path.strip() for path in value.split(",")):
        raise argparse.ArgumentTypeError("--changes 不能为空，必须提供至少一个模拟改动路径")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tandem", description="个人 AI 开发循环系统")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", type=Path, default=None, help=f"数据库路径（默认 {DEFAULT_DB}）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("demo", parents=[common], help="用临时数据库和假 Agent 跑两个场景")

    subparsers.add_parser("status", parents=[common], help="列出任务和当前状态")

    run = subparsers.add_parser("run", parents=[common], help="用假证据推进一轮本地任务")
    run.add_argument("--agent-script", choices=("ok", "ci-red", "refuse"), default="ok")
    run.add_argument(
        "--changes",
        required=True,
        type=_nonempty_changes,
        help="模拟改动路径，逗号分隔，必填且非空（每轮重算等级）",
    )
    run.add_argument(
        "--allow-level-drop",
        action="store_true",
        help="明确允许模拟改动降低任务等级，可能减少审核或人工关口",
    )
    run.add_argument("--review", choices=("pass", "fail"), default="pass", help="模拟 AI 审核结论")
    run.add_argument("--until-idle", action="store_true", help="重复运行直到需要人工处理或无进展")
    run.add_argument(
        "--max-rounds", type=_positive_rounds, default=10, help="最多运行几轮，默认 10"
    )

    show = subparsers.add_parser("show", parents=[common], help="查看完整任务记录和历史事件")
    show.add_argument("task_id", help="任务编号")

    submit = subparsers.add_parser("submit", parents=[common], help="提交一个新任务")
    submit.add_argument("--task-id", required=True, help="任务编号")
    submit.add_argument(
        "--mode",
        choices=("single_agent", "multi_agent"),
        default=None,
        help="此任务的运行模式（默认使用 risk.yml，不修改配置文件）",
    )
    submit.add_argument("--paths", default="", help="改动的文件，逗号分隔")
    submit.add_argument("--deleted", default="", help="删除的文件，逗号分隔")
    submit.add_argument(
        "--secret-scan-hit", action="store_true", help="密钥扫描命中了（直接判 D 级）"
    )

    approve = subparsers.add_parser("approve", parents=[common], help="批准方案或代码")
    approve.add_argument("--task-id", required=True, help="任务编号")
    approve.add_argument(
        "--sha",
        required=True,
        help="你看到的那个提交编号：和你现在看到的不一致时，批准不生效",
    )
    approve.add_argument("--reason", default=None, help="补充说明")
    approve.add_argument(
        "--veto",
        action="append",
        default=None,
        metavar="F1=理由",
        help="否决某一条 AI 意见的理由，可以写多次；有待回应意见时必须逐条给",
    )

    reject = subparsers.add_parser("reject", parents=[common], help="打回方案或代码")
    reject.add_argument("--task-id", required=True, help="任务编号")
    reject.add_argument("--reason", default=None, help="原因")

    cancel = subparsers.add_parser("cancel", parents=[common], help="取消任务")
    cancel.add_argument("--task-id", required=True, help="任务编号")
    cancel.add_argument("--reason", default=None, help="原因")

    return parser


COMMANDS = {
    "demo": cmd_demo,
    "status": cmd_status,
    "show": cmd_show,
    "run": cmd_run,
    "submit": cmd_submit,
    "approve": cmd_approve,
    "reject": cmd_reject,
    "cancel": cmd_cancel,
}


def _configure_utf8_output() -> None:
    """把输出显式设成 UTF-8。

    Windows 上把输出重定向到管道时，Python 会用系统代码页（cp936），中文会乱码；
    外壳以后要读命令行的输出，也会遇到同样的问题。
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    command = str(args.command)
    return COMMANDS[command](args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
