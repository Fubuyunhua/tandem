"""外壳端到端：提交 → 派活（假 Agent）→ 回执 → CI → 审核 → 合并。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
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
    RunMode,
    TaskStatus,
    Verdict,
)
from tandem.shell.agents.claude_cli import ClaudeCliAgent
from tandem.shell.agents.fake import FakeAgent
from tandem.shell.config import load_policy
from tandem.shell.executor import Executor
from tandem.shell.receipt import parse_receipt, render_receipt
from tandem.shell.runner import QuotaTracker, Runner, RunnerError
from tandem.shell.serde import changes_to_dict
from tandem.shell.store import Store
from tests.core.helpers import CODE_CHANGES, SHA_1

NOW = datetime(2026, 11, 7, 9, 30, tzinfo=UTC)


def code_receipt(task_id: str = "t1", attempt: int = 1, sha: str = SHA_1) -> str:
    return render_receipt(
        "DONE：写完了",
        {
            "task_id": task_id,
            "attempt": attempt,
            "sha": sha,
            "changes": changes_to_dict(CODE_CHANGES),
        },
    )


def make_runner(
    tmp_path: Path,
    script: list[str] | None = None,
    *,
    dry_run: bool = True,
    agents: dict[str, object] | None = None,
) -> Runner:
    agent = FakeAgent(provider="claude", script=script if script is not None else [])
    store = Store(tmp_path / "tandem.sqlite3")
    executor = Executor(
        agents={"claude": agent} if agents is None else agents,  # type: ignore[arg-type]
        dry_run=dry_run,
    )
    # 端到端测试走多 Agent 流程；risk.yml 的默认值是单 Agent 模式
    policy = replace(load_policy(), run_mode=RunMode.MULTI_AGENT)
    return Runner(store=store, policy=policy, executor=executor, clock=lambda: NOW)


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
    assert receipt.changes is not None
    actions = runner.store.list_actions("t1")
    assert [action.kind for action in actions] == [ActionKind.START_AGENT]
    assert actions[0].status is ActionStatus.DONE


def test_full_c_loop_reaches_merged(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, [code_receipt()])
    runner.submit("t1", Level.C)

    started = runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))
    receipt = parse_receipt(started.receipts[0])
    received = runner.handle(
        Event(
            kind=EventKind.CODE_SUBMITTED,
            task_id="t1",
            attempt=receipt.attempt,
            sha=receipt.sha,
            changes=receipt.changes,
        )
    )
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

    # 事件只追加，动作都有记录
    events = runner.store.list_events("t1")
    assert len(events) == 6
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
    runner = make_runner(tmp_path)
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
    assert len(runner.store.list_events("t1")) == 1


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
