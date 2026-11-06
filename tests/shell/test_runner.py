"""外壳端到端：提交 → 派活（假 Agent）→ 回执 → CI → 审核 → 合并。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tandem.core.model import (
    ActionKind,
    ActionStatus,
    Event,
    EventKind,
    Level,
    QuotaState,
    Review,
    TaskStatus,
    Verdict,
)
from tandem.shell.agents.claude_cli import ClaudeCliAgent
from tandem.shell.receipt import parse_receipt, render_receipt
from tandem.shell.runner import QuotaTracker, RunnerError
from tests.core.helpers import SHA_1
from tests.shell.shell_helpers import NOW, code_receipt, make_runner


def test_submit_creates_pending_task(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    task = runner.submit("t1", Level.C)
    assert task.status is TaskStatus.PENDING
    assert task.state_version == 0
    assert task.updated_at == NOW
    assert runner.store.load_task("t1") == task


def test_submit_twice_raises(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    runner.submit("t1", Level.C)
    with pytest.raises(RunnerError):
        runner.submit("t1", Level.C)


def test_assign_runs_fake_agent_and_returns_receipt(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, [code_receipt()])
    runner.submit("t1", Level.C)
    result = runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))

    assert result.decision.task.status is TaskStatus.WORKING
    assert len(result.receipts) == 1
    receipt = parse_receipt(result.receipts[0])
    assert receipt.sha == SHA_1
    actions = runner.store.list_actions("t1")
    assert [action.kind for action in actions] == [ActionKind.START_AGENT]
    assert actions[0].status is ActionStatus.DONE


def test_full_c_loop_reaches_merged(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, [code_receipt()])
    runner.submit("t1", Level.C)

    started = runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))
    receipt = parse_receipt(started.receipts[0])
    task = runner.store.load_task("t1")
    assert task is not None
    received = runner.handle(runner.code_event(task, receipt))
    assert received.decision.task.status is TaskStatus.AWAITING_ACCEPTANCE

    reviewed = runner.handle(Event(kind=EventKind.CI_GREEN, task_id="t1", sha=SHA_1))
    assert reviewed.decision.task.status is TaskStatus.AWAITING_AI_REVIEW
    reviewers = reviewed.decision.task.designated_reviewers
    assert reviewers == ("codex", "opencode-go")
    request_actions = [
        action for action in reviewed.executed if action.action.kind is ActionKind.REQUEST_REVIEW
    ]
    assert all(action.status is ActionStatus.DONE for action in request_actions)

    for reviewer in reviewers:
        runner.handle(
            Event(
                kind=EventKind.REVIEW,
                task_id="t1",
                review=Review(
                    reviewer=reviewer,
                    provider=reviewer,
                    verdict=Verdict.PASS,
                    sha=SHA_1,
                    standard_version=1,
                ),
            )
        )
    merging = runner.store.load_task("t1")
    assert merging is not None
    assert merging.status is TaskStatus.AWAITING_MERGE

    finished = runner.handle(Event(kind=EventKind.MERGED, task_id="t1", sha=SHA_1))
    assert finished.decision.task.status is TaskStatus.MERGED

    # 事件只追加，动作都有记录（第一条是创建事件）
    events = runner.store.list_events("t1")
    assert [event.kind for event in events] == [
        EventKind.CREATED,
        EventKind.ASSIGN,
        EventKind.CODE_SUBMITTED,
        EventKind.CI_GREEN,
        EventKind.REVIEW,
        EventKind.REVIEW,
        EventKind.MERGED,
    ]
    kinds = [action.kind for action in runner.store.list_actions("t1")]
    assert ActionKind.MERGE in kinds
    merge_action = next(
        action for action in runner.store.list_actions("t1") if action.kind is ActionKind.MERGE
    )
    assert merge_action.status is ActionStatus.DONE
    # 合并是 dry-run：动作记录下来了，但没有真的合并
    assert any("dry-run" in line for line in runner.executor.log)


def test_real_agent_is_not_started_in_dry_run(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, agents={"claude": ClaudeCliAgent()})
    runner.submit("t1", Level.C)
    result = runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))
    assert result.receipts == ()
    assert result.executed[0].simulated
    assert "dry-run" in result.executed[0].message


def test_missing_agent_is_recorded_as_unknown(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, agents={})
    runner.submit("t1", Level.C)
    result = runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))
    assert result.executed[0].status is ActionStatus.UNKNOWN
    assert runner.store.unconfirmed_actions("t1")


def test_quota_exhausted_marks_provider(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, [code_receipt()])
    runner.submit("t1", Level.C)
    runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))
    runner.handle(
        Event(kind=EventKind.QUOTA_EXHAUSTED, task_id="t1", provider="claude", reason="写一半")
    )
    assert runner.quota.snapshot().state("claude") is QuotaState.EXHAUSTED
    task = runner.store.load_task("t1")
    assert task is not None
    assert task.status is TaskStatus.PENDING


def test_version_mismatch_does_not_change_task(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    runner.submit("t1", Level.C)
    before = runner.store.load_task("t1")
    result = runner.handle(
        Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude", state_version=99)
    )
    assert not result.decision.changed
    assert runner.store.load_task("t1") == before
    # 事件还是要记进日志，方便事后追问"为什么是这个结果"
    assert len(runner.store.list_events("t1")) == 2


def test_handle_unknown_task_raises(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    with pytest.raises(RunnerError):
        runner.handle(Event(kind=EventKind.ASSIGN, task_id="ghost"))


def test_assign_pending_assigns_all_pending_tasks(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, [code_receipt("a"), code_receipt("b")])
    runner.submit("a", Level.C)
    runner.submit("b", Level.C)
    results = runner.assign_pending()
    assert [result.decision.task.status for result in results] == [
        TaskStatus.WORKING,
        TaskStatus.WORKING,
    ]


def test_quota_tracker_defaults_to_available() -> None:
    tracker = QuotaTracker()
    assert tracker.snapshot().has_quota("codex")
    tracker.mark_exhausted("codex")
    assert not tracker.snapshot().has_quota("codex")
    tracker.mark_available("codex")
    assert tracker.snapshot().has_quota("codex")


def test_handle_commits_event_task_and_actions_once(tmp_path: Path) -> None:
    """F7：一个事件只用一次事务写：事件 + 带预期旧版本的任务 + 待执行动作。"""
    runner = make_runner(tmp_path, [code_receipt()])
    runner.submit("t1", Level.C)
    calls: list[dict[str, object]] = []
    original = runner.store.commit

    def spy(**kwargs: object) -> object:
        calls.append(kwargs)
        return original(**kwargs)  # type: ignore[arg-type]

    runner.store.commit = spy  # type: ignore[method-assign]
    runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))

    assert len(calls) == 1
    assert calls[0]["expected_version"] == 0
    events = calls[0]["events"]
    actions = calls[0]["actions"]
    assert isinstance(events, list) and len(events) == 1
    assert isinstance(actions, list) and actions
    assert calls[0]["task"] is not None


def test_handle_persists_even_when_execution_fails(tmp_path: Path) -> None:
    """F7：先保存再执行。执行阶段出事，事件和决定的记录不能丢。"""
    from tandem.shell.agents.fake import FakeAgent

    broken = FakeAgent(provider="claude", script=[])
    runner = make_runner(tmp_path, agents={"claude": broken})
    runner.submit("t1", Level.C)
    result = runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))
    assert result.executed[0].status is ActionStatus.UNKNOWN
    assert "Agent 出错" in result.executed[0].message
    # 记录都留下了：创建、派活、以及执行失败自动产生的异常事件
    kinds = [event.kind for event in runner.store.list_events("t1")]
    assert kinds == [EventKind.CREATED, EventKind.ASSIGN, EventKind.INCIDENT]
    task = runner.store.load_task("t1")
    assert task is not None
    assert task.status is TaskStatus.ERROR


def test_conflict_is_raised_when_snapshot_changed_underneath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F7：读到的旧版本被别人改过时，写入被拒绝（不能悄悄覆盖）。"""
    from tandem.shell.store import ConflictError

    runner = make_runner(tmp_path, [code_receipt()])
    runner.submit("t1", Level.C)
    stale = runner.store.load_task("t1")
    assert stale is not None
    runner.store.commit(
        task=replace(stale, state_version=1, status=TaskStatus.CANCELLED),
        expected_version=0,
    )
    monkeypatch.setattr(runner.store, "load_task", lambda task_id: stale)
    with pytest.raises(ConflictError):
        runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))


def test_quota_survives_restart(tmp_path: Path) -> None:
    """F11：额度估计要持久化，重启后不能忘掉"这一家已经用完"。"""
    runner = make_runner(tmp_path, [code_receipt()])
    runner.submit("t1", Level.C)
    runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))
    runner.handle(
        Event(kind=EventKind.QUOTA_EXHAUSTED, task_id="t1", provider="claude", reason="写一半")
    )
    runner.store.close()

    restarted = make_runner(tmp_path, [code_receipt()])
    assert restarted.quota.snapshot().state("claude") is QuotaState.EXHAUSTED
    restarted.store.close()


def test_submit_appends_a_created_event(tmp_path: Path) -> None:
    """F11：创建任务也要记事件，日志里能看到任务是怎么出现的。"""
    runner = make_runner(tmp_path)
    runner.submit("t1", Level.C)
    events = runner.store.list_events("t1")
    assert [event.kind for event in events] == [EventKind.CREATED]
    assert events[0].task_id == "t1"


def test_action_status_has_a_single_source_of_truth(tmp_path: Path) -> None:
    """F11：执行结果写回以后，任务快照里的动作状态和动作表一致。"""
    runner = make_runner(tmp_path, [code_receipt()])
    runner.submit("t1", Level.C)
    runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))

    table = runner.store.list_actions("t1")
    task = runner.store.load_task("t1")
    assert task is not None
    assert [action.status for action in task.actions] == [ActionStatus.DONE]
    assert [action.status for action in task.actions] == [action.status for action in table]


def test_agent_failure_becomes_an_incident_and_retry_really_reruns(tmp_path: Path) -> None:
    """F12：Agent 启动失败 → 异常 → 核对后回到待处理 → 重新派活能真的再跑一次。"""
    from tandem.core.model import CheckResult
    from tandem.shell.agents.fake import FakeAgent

    agent = FakeAgent(provider="claude", script=[])  # 第一次派活时剧本是空的 → 报错
    runner = make_runner(tmp_path, agents={"claude": agent})
    runner.submit("t1", Level.C)

    failed = runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))
    assert failed.decision.task.status is TaskStatus.ERROR
    assert failed.decision.task.error_code == "A01"
    assert failed.decision.task.status_before_error is TaskStatus.WORKING

    retried = runner.handle(
        Event(kind=EventKind.RETRY, task_id="t1", check_result=CheckResult.NOT_CONFIRMED)
    )
    assert retried.decision.task.status is TaskStatus.PENDING

    agent.push(code_receipt(attempt=2))
    started = runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))
    assert started.decision.task.status is TaskStatus.WORKING
    assert started.receipts
    receipt = parse_receipt(started.receipts[0])
    task = runner.store.load_task("t1")
    assert task is not None
    received = runner.handle(runner.code_event(task, receipt))
    assert received.decision.task.status is TaskStatus.AWAITING_ACCEPTANCE


class _CountingDiffSource:
    """包一层采集器，用来断言"回执被拒时采集器也没被调用"。"""

    def __init__(self, inner: object) -> None:
        self.inner = inner
        self.calls: list[tuple[str, str]] = []

    def collect(self, base: str, sha: str) -> object:
        self.calls.append((base, sha))
        return self.inner.collect(base, sha)  # type: ignore[attr-defined]


def test_code_event_rejects_a_receipt_from_another_task(tmp_path: Path) -> None:
    """H3：回执里的任务编号和当前任务不一致时，采集器和任务都不能推进。"""
    from tandem.shell.diff_source import FakeDiffSource
    from tandem.shell.receipt import ReceiptError
    from tests.core.helpers import CODE_CHANGES

    counting = _CountingDiffSource(FakeDiffSource(changes=CODE_CHANGES))
    runner = make_runner(
        tmp_path,
        [code_receipt("t1"), code_receipt("t2")],
        diff_source=counting,  # type: ignore[arg-type]
    )
    runner.submit("t1", Level.C)
    runner.submit("t2", Level.C)
    runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))
    runner.handle(Event(kind=EventKind.ASSIGN, task_id="t2", provider="claude"))

    task1 = runner.store.load_task("t1")
    assert task1 is not None
    # 两个任务尝试次数相同，把 t2 的回执投给 t1
    crossed = render_receipt(
        "DONE：t2 的回执", {"task_id": "t2", "attempt": task1.attempt, "sha": "c" * 40}
    )
    events_before = len(runner.store.list_events("t1"))

    with pytest.raises(ReceiptError):
        runner.code_event(task1, parse_receipt(crossed))

    assert counting.calls == []  # 采集器没有被调用
    assert len(runner.store.list_events("t1")) == events_before
    assert runner.store.load_task("t1") == task1
