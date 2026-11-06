"""外壳主流程：读事件 → 调内核 → 先保存再执行。

顺序很重要：先把事件追加进日志、把新的任务快照存下来，再去执行动作。
万一执行到一半崩了，重启后能从日志和动作表里看出哪些动作没确认完成。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from tandem.core.model import (
    ActionKind,
    ActionStatus,
    Decision,
    Event,
    EventKind,
    Level,
    Policy,
    QuotaSnapshot,
    QuotaState,
    TaskRecord,
    TaskStatus,
)
from tandem.core.transition import create_task, decide
from tandem.shell.diff_source import DiffSource
from tandem.shell.executor import ExecutedAction, Executor
from tandem.shell.receipt import Receipt
from tandem.shell.store import Store


class RunnerError(RuntimeError):
    """外壳流程出问题了。"""


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class QuotaTracker:
    """额度估计（终审第 15 条）：不知道就当还有，收到"额度用完"才标记用完。

    接上 store 以后立刻持久化，重启不会忘掉"这一家已经用完"。
    """

    states: dict[str, QuotaState] = field(default_factory=dict[str, QuotaState])
    store: Store | None = None

    def attach(self, store: Store) -> None:
        """接上存储：先把之前存下来的额度读回来（存下来的事实优先）。"""
        self.store = store
        self.states.update(store.load_quota())

    def snapshot(self) -> QuotaSnapshot:
        return QuotaSnapshot.from_mapping(self.states)

    def mark_exhausted(self, provider: str) -> None:
        self.states[provider] = QuotaState.EXHAUSTED
        if self.store is not None:
            self.store.save_quota(provider, QuotaState.EXHAUSTED)

    def mark_available(self, provider: str) -> None:
        self.states[provider] = QuotaState.AVAILABLE
        if self.store is not None:
            self.store.save_quota(provider, QuotaState.AVAILABLE)


@dataclass(frozen=True)
class RunResult:
    """一次事件处理的结果。"""

    decision: Decision
    executed: tuple[ExecutedAction, ...]

    @property
    def receipts(self) -> tuple[str, ...]:
        return tuple(item.receipt for item in self.executed if item.receipt is not None)


@dataclass
class Runner:
    """把存储、内核、执行器串起来。"""

    store: Store
    policy: Policy
    executor: Executor
    diff_source: DiffSource
    quota: QuotaTracker = field(default_factory=QuotaTracker)
    clock: Callable[[], datetime] = _utc_now

    def __post_init__(self) -> None:
        # 启动时接上存储，把之前记下的额度估计恢复回来
        self.quota.attach(self.store)

    def submit(self, task_id: str, level: Level, *, base_sha: str = "main") -> TaskRecord:
        """建一个新任务。等级由提交时收集到的真实改动算好传进来。"""
        if self.store.load_task(task_id) is not None:
            raise RunnerError(f"任务 {task_id} 已经存在")
        now = self.clock()
        task = replace(create_task(task_id, level, self.policy), updated_at=now, base_sha=base_sha)
        # 创建事实也进事件日志，事后能追问任务是从哪来的
        self.store.commit(
            events=[Event(kind=EventKind.CREATED, task_id=task_id)],
            task=task,
            now=now,
        )
        return task

    def code_event(self, task: TaskRecord, receipt: Receipt, *, base: str | None = None) -> Event:
        """Agent 交回代码。

        改动一律来自 `DiffSource`：回执只提供任务编号、尝试次数和提交编号，
        Agent 自报的 changes 已经被回执解析丢掉了（回执只是自述，不是证据）。
        """
        collected = self.diff_source.collect(
            base if base is not None else (task.base_sha or "main"), receipt.sha
        )
        reason = collected.describe()
        if receipt.warnings:
            reason = f"{reason}；{'；'.join(receipt.warnings)}"
        return Event(
            kind=EventKind.CODE_SUBMITTED,
            task_id=task.task_id,
            state_version=task.state_version,
            attempt=receipt.attempt,
            sha=receipt.sha,
            changes=collected.changes,
            reason=reason,
        )

    def handle(self, event: Event) -> RunResult:
        """处理一个事件：先保存，再执行。"""
        task = self.store.load_task(event.task_id)
        if task is None:
            raise RunnerError(f"没有任务 {event.task_id}")
        now = self.clock()
        decision = decide(task, event, self.policy, self.quota.snapshot(), now)

        # 一个事务：事件 + 带预期旧版本的任务快照 + 待执行动作。
        # 事务提交以后才去动外部世界，崩在中途也能从日志和动作表看出来。
        self.store.commit(
            events=[event],
            task=decision.task if decision.changed else None,
            expected_version=task.state_version,
            actions=decision.actions,
            now=now,
        )

        executed: list[ExecutedAction] = []
        for action in decision.actions:
            outcome = self.executor.execute(action, decision.task)
            if action.provider is not None and action.kind is ActionKind.SET_QUOTA_EXHAUSTED:
                self.quota.mark_exhausted(action.provider)
            if outcome.status is not ActionStatus.SENT:
                self.store.update_action_status(action.action_id, outcome.status, now)
            executed.append(outcome)
        return RunResult(decision=decision, executed=tuple(executed))

    def assign_pending(self, provider: str | None = None) -> list[RunResult]:
        """给所有"待处理"的任务派活（第 1 条事件的来源）。"""
        results: list[RunResult] = []
        target = provider if provider is not None else self.policy.default_writer
        for task in self.store.list_tasks_by_status(TaskStatus.PENDING):
            event = Event(
                kind=EventKind.ASSIGN,
                task_id=task.task_id,
                state_version=task.state_version,
                provider=target,
            )
            results.append(self.handle(event))
        return results
