"""本地模拟驱动：只构造假证据，所有裁决仍交给内核。"""

from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass
from hashlib import sha256

from tandem.core.level import compute_level
from tandem.core.model import (
    ActionKind,
    ActionStatus,
    Event,
    EventKind,
    Finding,
    Review,
    TaskRecord,
    TaskStatus,
    Verdict,
)
from tandem.shell.agents.fake import FakeAgent
from tandem.shell.receipt import parse_receipt, render_receipt
from tandem.shell.runner import Runner, RunResult

AUTOMATIC_STATES = frozenset(
    {
        TaskStatus.PENDING,
        TaskStatus.AWAITING_ACCEPTANCE,
        TaskStatus.AWAITING_AI_REVIEW,
        TaskStatus.AWAITING_MERGE,
    }
)


def _quote(value: str) -> str:
    """Windows 提示面向 PowerShell，其他平台使用 POSIX shell 转义。"""
    if sys.platform == "win32":
        return "'" + value.replace("'", "''") + "'"
    return shlex.quote(value)


@dataclass
class LocalRun:
    """一轮中每个任务最多派活一次；退回后等下一轮，不在原地无限重做。"""

    runner: Runner
    agents: dict[str, FakeAgent]
    agent_script: str = "ok"
    review: str = "pass"
    allow_level_drop: bool = False

    def _event(self, task: TaskRecord, kind: EventKind, **fields: object) -> Event:
        return Event(
            kind=kind,
            task_id=task.task_id,
            state_version=task.state_version,
            **fields,  # type: ignore[arg-type]
        )

    def _send(self, task: TaskRecord, event: Event) -> RunResult:
        result = self.runner.handle(event)
        updated = result.decision.task
        print(
            f"{task.task_id}：{task.status.value} → {updated.status.value}"
            f"（{result.decision.reason}）"
        )
        return result

    def _receipt(self, task: TaskRecord) -> str:
        """按下一次尝试构造假回执，方案审批和拒绝修改都服从内核条件。"""
        attempt = task.attempt + 1
        token = f"tandem-simulation:{task.task_id}:{attempt}"
        sha = sha256(token.encode("utf-8")).hexdigest()[:40]
        payload: dict[str, object] = {
            "task_id": task.task_id,
            "attempt": attempt,
            "sha": sha,
        }
        rule = self.runner.policy.rule_for(task.level)
        if rule.requires_plan_approval and task.approved_plan_version != task.plan_version:
            paths = self.runner.diff_source.collect(task.base_sha, sha).changes.all_paths
            changed = ", ".join(paths) or "不改仓库"
            payload["plan"] = f"模拟方案：改动 {changed}；执行模拟 CI 后等待审核。"
            return render_receipt("PLAN：模拟方案，等待你批准", payload)
        if self.agent_script == "refuse" and task.returned_from_review:
            return render_receipt("REFUSE：模拟写手拒绝修改，交给你决定", payload)
        return render_receipt("DONE：模拟写手交回代码", payload)

    def _assign(self, task: TaskRecord) -> TaskRecord:
        # 在派活、产生回执和保存事件前核对，拒绝降级时任务完全不变。
        changes = self.runner.diff_source.collect(task.base_sha, "simulation").changes
        new_level = compute_level(changes, self.runner.policy)
        if new_level.rank < task.level.rank:
            print(
                f"【等级下降{'已允许' if self.allow_level_drop else '已阻止'}】"
                f"{task.task_id}：{task.level.value} → {new_level.value}。"
                "模拟证据不能证明这次真的只改了低风险文件；可能减少审核或人工关口。"
            )
            if not self.allow_level_drop:
                print("  已停止此任务；确认后必须显式传入 --allow-level-drop 才能继续。")
                return task
        provider = self.runner.policy.default_writer
        agent = self.agents[provider]
        # 派活同步完成；被内核拒绝派活时，不把未使用的回执留给别的任务。
        agent.script[:] = [self._receipt(task)]
        started = self._send(task, self._event(task, EventKind.ASSIGN, provider=provider))
        current = started.decision.task
        if current.status is not TaskStatus.WORKING or not started.receipts:
            return current
        receipt = parse_receipt(started.receipts[0])
        if receipt.plan:
            event = self._event(
                current, EventKind.PLAN_SUBMITTED, sha=receipt.sha, plan=receipt.plan
            )
        elif receipt.conclusion.startswith("REFUSE"):
            event = self._event(current, EventKind.REFUSED_TO_FIX, reason=receipt.conclusion)
        else:
            event = self.runner.code_event(current, receipt)
        return self._send(current, event).decision.task

    def _advance(self, task: TaskRecord) -> bool:
        version = task.state_version
        current = self._assign(task) if task.status is TaskStatus.PENDING else task
        if current.status is TaskStatus.AWAITING_ACCEPTANCE:
            red = self.agent_script == "ci-red"
            current = self._send(
                current,
                self._event(
                    current,
                    EventKind.CI_RED if red else EventKind.CI_GREEN,
                    sha=current.latest_sha,
                    reason="模拟 CI 失败" if red else "模拟 CI 通过",
                ),
            ).decision.task
        if current.status is TaskStatus.AWAITING_AI_REVIEW:
            answered = {item.provider for item in current.current_reviews()}
            for provider in current.designated_reviewers:
                if provider in answered:
                    continue
                failing = self.review == "fail"
                review = Review(
                    reviewer=provider,
                    provider=provider,
                    verdict=Verdict.FAIL if failing else Verdict.PASS,
                    sha=current.latest_sha or "",
                    standard_version=current.standard_version,
                    findings=(Finding("SIM-1", "模拟审核意见：请补充异常分支的测试"),)
                    if failing
                    else (),
                )
                current = self._send(
                    current, self._event(current, EventKind.REVIEW, review=review)
                ).decision.task
                if current.status is not TaskStatus.AWAITING_AI_REVIEW:
                    break
        if current.status is TaskStatus.AWAITING_MERGE:
            # Runner 的返回快照仍可能带 SENT；动作表才是执行结果的事实来源。
            saved = self.runner.store.load_task(current.task_id)
            assert saved is not None
            current = saved
            merge = next(
                (action for action in reversed(current.actions) if action.kind is ActionKind.MERGE),
                None,
            )
            if (
                current.approved_sha is not None
                and current.approved_sha == current.latest_sha
                and current.ci_green
                and merge is not None
                and merge.status is ActionStatus.DONE
            ):
                current = self._send(
                    current,
                    self._event(
                        current,
                        EventKind.MERGED,
                        sha=current.approved_sha,
                        reason="模拟合并成功，没有执行真实合并",
                    ),
                ).decision.task
            else:
                print(
                    f"{current.task_id}：缺少当前 SHA 的 CI、批准证据，"
                    "或最近一次 MERGE 动作尚未确认 DONE，不能模拟合并。"
                )
        self._hint(current)
        return current.state_version != version

    def _hint(self, task: TaskRecord) -> None:
        if task.status.is_terminal:
            return
        db = f"--db {_quote(str(self.runner.store.path))}"
        task_id = _quote(task.task_id)
        print(f"  下一步：uv run tandem show {task_id} {db}")
        if task.status in {
            TaskStatus.AWAITING_PLAN_APPROVAL,
            TaskStatus.AWAITING_YOUR_REVIEW,
            TaskStatus.NEEDS_INTERVENTION,
        }:
            plan = task.plan()
            approval_sha = (
                (plan.sha if plan is not None else None)
                if task.status is TaskStatus.AWAITING_PLAN_APPROVAL
                else task.latest_sha
            )
            if approval_sha and (task.status is TaskStatus.AWAITING_PLAN_APPROVAL or task.ci_green):
                vetoes = "".join(
                    f" --veto {_quote(finding.key + '=填写这条意见的理由')}"
                    for finding in task.open_findings
                )
                print(
                    f"  核对后：uv run tandem approve --task-id {task_id} {db}"
                    f" --sha {_quote(approval_sha)}{vetoes}"
                )
            elif task.status is TaskStatus.AWAITING_PLAN_APPROVAL:
                print("  缺少当前方案的提交编号，请先核对方案记录；不能用代码编号代替。")
            else:
                print("  CI 尚未通过，不能批准；本轮未提供介入后的重做命令。")
        elif task.status is TaskStatus.PENDING:
            print(
                "  检查等级下降提示或写手额度，"
                "调整 --changes / --agent-script / --review 后再 run。"
            )
        elif task.status is TaskStatus.AWAITING_ACCEPTANCE:
            print(
                "  等待当前提交的 CI；核对提交编号后再 run 生成模拟 CI，真实 CI 请到 GitHub 核对。"
            )
        elif task.status is TaskStatus.AWAITING_AI_REVIEW:
            print(
                "  等待本轮指定审核者的结论；用 show 核对席位、提交和额度，再 run 模拟缺少的结论。"
            )
        elif task.status is TaskStatus.AWAITING_MERGE:
            print("  合并结果未确认：用 show 核对当前 SHA、CI、批准及最近一次 MERGE 动作状态。")
            print("  若涉及真实 PR，先去 GitHub 核对合并结果；本命令不会补造执行成功证据。")
        elif task.status in {TaskStatus.WORKING, TaskStatus.ERROR, TaskStatus.YOU_WORKING}:
            print("  此状态需要人工处理；本轮不自动恢复丢失的回执或异常任务。")
        print(f"  如需取消：uv run tandem cancel --task-id {task_id} {db}")

    def run(self, *, until_idle: bool = False, max_rounds: int = 10) -> int:
        """0 表示全部到达终点；1 表示未完成；2 表示达到轮数上限。"""
        if max_rounds < 1:
            raise ValueError("最大轮数必须大于 0")
        print("模拟运行 / dry-run：假 Agent、假改动、假 CI、假审核；不会调用真实 AI 或合并。")
        rounds = max_rounds if until_idle else 1
        for index in range(rounds):
            print(f"第 {index + 1} 轮")
            changed = False
            for task in self.runner.store.list_tasks():
                # 即使已有任务暂停，也继续驱动其他任务。
                changed = self._advance(task) or changed
            if not until_idle:
                return self._finish()
            if not changed or not any(
                task.status in AUTOMATIC_STATES for task in self.runner.store.list_tasks()
            ):
                return self._finish()
        print(f"达到最大轮数 {max_rounds}，尚未确认空闲；请用 show 查看后再运行。")
        return 2

    def _finish(self) -> int:
        remaining = [task for task in self.runner.store.list_tasks() if not task.status.is_terminal]
        if remaining:
            print(f"尚未完成：有 {len(remaining)} 个任务卡住或等待后续处理，请按上方提示操作。")
            return 1
        print("全部完成：所有任务均已到达终点状态。")
        return 0
