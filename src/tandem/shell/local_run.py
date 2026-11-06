"""本地模拟驱动：只构造假证据，所有裁决仍交给内核。"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from tandem.core.model import Event, EventKind, Finding, Review, TaskRecord, TaskStatus, Verdict
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
    """提示中的参数按 PowerShell 单引号规则转义。"""
    return "'" + value.replace("'", "''") + "'"


@dataclass
class LocalRun:
    """一轮中每个任务最多派活一次；退回后等下一轮，不在原地无限重做。"""

    runner: Runner
    agents: dict[str, FakeAgent]
    agent_script: str = "ok"
    review: str = "pass"

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
            payload["plan"] = "模拟方案：按 --changes 指定的改动工作，执行模拟 CI 后等待审核。"
            return render_receipt("PLAN：模拟方案，等待你批准", payload)
        if self.agent_script == "refuse" and task.returned_from_review:
            return render_receipt("REFUSE：模拟写手拒绝修改，交给你决定", payload)
        return render_receipt("DONE：模拟写手交回代码", payload)

    def _assign(self, task: TaskRecord) -> TaskRecord:
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
            if (
                current.approved_sha is not None
                and current.approved_sha == current.latest_sha
                and current.ci_green
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
                print(f"{current.task_id}：缺少当前 SHA 的 CI 或批准证据，不能模拟合并。")
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
            if task.latest_sha and (
                task.status is TaskStatus.AWAITING_PLAN_APPROVAL or task.ci_green
            ):
                vetoes = "".join(
                    f" --veto {_quote(finding.key + '=填写这条意见的理由')}"
                    for finding in task.open_findings
                )
                print(
                    f"  核对后：uv run tandem approve --task-id {task_id} {db}"
                    f" --sha {_quote(task.latest_sha)}{vetoes}"
                )
            else:
                print("  CI 尚未通过，不能批准；本轮未提供介入后的重做命令。")
        elif task.status is TaskStatus.PENDING:
            print("  可以调整 --agent-script / --review 后再次运行 tandem run。")
        elif task.status in {TaskStatus.WORKING, TaskStatus.ERROR, TaskStatus.YOU_WORKING}:
            print("  此状态需要人工处理；本轮不自动恢复丢失的回执或异常任务。")
        print(f"  如需取消：uv run tandem cancel --task-id {task_id} {db}")

    def run(self, *, until_idle: bool = False, max_rounds: int = 10) -> int:
        """达到轮数上限仍未确认空闲时返回非零，供脚本识别未完成。"""
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
                return 0
            if not changed or not any(
                task.status in AUTOMATIC_STATES for task in self.runner.store.list_tasks()
            ):
                print("已空闲：没有任务能继续自动推进。")
                return 0
        print(f"达到最大轮数 {max_rounds}，尚未确认空闲；请用 show 查看后再运行。")
        return 2
