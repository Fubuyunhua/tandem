"""命令行入口 ``tandem``。

子命令：
- ``tandem demo``：用临时数据库和假 Agent 跑两个场景，打印状态路径；
- ``tandem status``：列出任务和当前状态；
- ``tandem submit`` / ``approve`` / ``reject`` / ``cancel``：对任务做相应操作。
"""

from __future__ import annotations

import argparse
import io
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from tandem.core.level import compute_level
from tandem.core.model import (
    ActionKind,
    ActionStatus,
    ChangeSet,
    CheckResult,
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
from tandem.shell.agents.fake import FakeAgent
from tandem.shell.config import load_config, load_policy
from tandem.shell.diff_source import DiffSource, FakeDiffSource, GitDiffSource
from tandem.shell.executor import Executor
from tandem.shell.github import GhGitHub, GitHubError
from tandem.shell.github_events import GitHubEvents
from tandem.shell.receipt import Receipt, parse_receipt, render_receipt
from tandem.shell.runner import Runner, RunnerError
from tandem.shell.store import Store, StoreError

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
    return result.decision.changed and all(
        item.status is not ActionStatus.UNKNOWN
        for item in result.executed
        if item.action.kind in {ActionKind.MERGE, ActionKind.CLOSE_PR}
    )


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
        print(f"{'任务':<20}{'状态':<16}{'等级':<6}{'版本':<6}{'提交编号':<12}原因  标题")
        for task in tasks:
            sha = (task.latest_sha or "-")[:8]
            source = store.github_source(task.task_id)
            title = (
                "-"
                if source is None
                else "".join(
                    character if character.isprintable() else " " for character in source.title
                )
            )
            if len(title) > 80:
                title = title[:79] + "…"
            print(
                f"{task.task_id:<20}{task.status.value:<16}{task.level.value:<6}"
                f"{task.state_version:<6}{sha:<12}{task.reason}  {title}"
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
    store, runner = _open(_db_path(args))
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


# ---------------------------------------------------------------- approve / reject


def cmd_approve(args: argparse.Namespace) -> int:
    store, runner = _open(_db_path(args))
    try:
        _connect_github(args, runner)
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
    except (GitHubError, RunnerError) as error:
        print(f"GitHub 操作失败：{error}")
        return 1
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
        _connect_github(args, runner)
        task = store.load_task(args.task_id)
        if task is None:
            print(f"没有任务 {args.task_id}")
            return 1
        changed = _print_decision(runner, _event(EventKind.CANCEL, task, reason=args.reason))
        return 0 if changed else 2
    except (GitHubError, RunnerError) as error:
        print(f"GitHub 操作失败：{error}")
        return 1
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


def _github_client(repo: str) -> GhGitHub:
    """轮询、核对和合并前复查共用同一份必需检查配置。"""
    return GhGitHub(repo, required_checks=load_config().required_checks)


def cmd_github(args: argparse.Namespace) -> int:
    """拉取或核对一次；live 仅控制 GitHub 写入，不启动真实 Agent。"""
    store, runner = _open(_db_path(args))
    try:
        github = _github_client(str(args.repo))
        runner.executor.github = github
        runner.executor.github_store = store
        runner.executor.github_repo = str(args.repo)
        runner.executor.dry_run = not bool(args.live)
        source = GitHubEvents(runner, github, str(args.repo))
        if args.command == "poll":
            created = source.poll()
            for binding in cast("list[str]", args.bind):
                task_id, separator, number = binding.partition("=")
                if not separator or not number.isdecimal():
                    raise RunnerError("PR 关联格式必须为 gh-编号=PR编号")
                source.bind_pr(task_id, int(number))
            print(f"轮询完成，新建任务：{', '.join(created) or '无'}")
        else:
            if args.pr is not None:
                source.bind_pr(str(args.task_id), int(args.pr))
            result = source.reconcile(str(args.task_id))
            print(f"{args.task_id}：{result.value}")
            if result is CheckResult.NOT_CONFIRMED:
                print(
                    "下一步：请手工核对 PR 状态；CLI 不会自行重发 MERGE。"
                    "若仍待合并，请等待 task-001 的内核重试支持，"
                    "或确认放弃后用 tandem cancel 取消任务。"
                )
        return 0
    except (GitHubError, RunnerError, StoreError) as error:
        print(f"GitHub 操作失败：{error}")
        return 1
    finally:
        store.close()


def _connect_github(args: argparse.Namespace, runner: Runner) -> None:
    """已知 GitHub 来源的批准和取消也走同一个安全执行器。"""
    repo = getattr(args, "repo", None)
    live = bool(getattr(args, "live", False))
    source = runner.store.github_source(str(args.task_id))
    if repo is None and source is not None:
        repo = source.repo
    if live and repo is None:
        raise RunnerError("live 操作需要 GitHub 来源或 --repo")
    if repo is not None:
        runner.executor.github = _github_client(str(repo))
        runner.executor.github_store = runner.store
        runner.executor.github_repo = str(repo)
        runner.executor.dry_run = not live


# ---------------------------------------------------------------- 入口


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tandem", description="个人 AI 开发循环系统")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", type=Path, default=None, help=f"数据库路径（默认 {DEFAULT_DB}）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("demo", parents=[common], help="用临时数据库和假 Agent 跑两个场景")

    subparsers.add_parser("status", parents=[common], help="列出任务和当前状态")

    for name in ("poll", "reconcile"):
        command = subparsers.add_parser(
            name, parents=[common], help="轮询 GitHub" if name == "poll" else "核对异常任务"
        )
        command.add_argument("--repo", required=True, help="仓库 owner/repo")
        command.add_argument("--live", action="store_true", help="显式启用 GitHub 写入")
        if name == "reconcile":
            command.add_argument("task_id", help="任务编号")
            command.add_argument("--pr", type=int, default=None, help="首次核对时明确关联 PR 编号")
        else:
            command.add_argument(
                "--bind", action="append", default=[], help="关联 gh-编号=PR编号，可重复"
            )

    submit = subparsers.add_parser("submit", parents=[common], help="提交一个新任务")
    submit.add_argument("--task-id", required=True, help="任务编号")
    submit.add_argument("--paths", default="", help="改动的文件，逗号分隔")
    submit.add_argument("--deleted", default="", help="删除的文件，逗号分隔")
    submit.add_argument(
        "--secret-scan-hit", action="store_true", help="密钥扫描命中了（直接判 D 级）"
    )

    approve = subparsers.add_parser("approve", parents=[common], help="批准方案或代码")
    approve.add_argument("--task-id", required=True, help="任务编号")
    approve.add_argument("--repo", default=None, help="仓库 owner/repo，默认读取来源")
    approve.add_argument("--live", action="store_true", help="显式启用 GitHub 写入")
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
    cancel.add_argument("--repo", default=None, help="仓库 owner/repo，默认读取来源")
    cancel.add_argument("--live", action="store_true", help="显式启用 GitHub 写入")
    cancel.add_argument("--reason", default=None, help="原因")

    return parser


COMMANDS = {
    "poll": cmd_github,
    "reconcile": cmd_github,
    "demo": cmd_demo,
    "status": cmd_status,
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
