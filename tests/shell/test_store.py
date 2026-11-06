"""存储层测试：只追加、版本号、动作状态。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from tandem.core.model import (
    Action,
    ActionKind,
    ActionStatus,
    Event,
    EventKind,
    Level,
    Review,
    RevisionCount,
    TaskRecord,
    TaskStatus,
    Verdict,
)
from tandem.shell.store import Store, StoreError


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    with Store(tmp_path / "tandem.sqlite3") as opened:
        yield opened


def test_events_are_append_only(store: Store) -> None:
    store.append_event(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))
    store.append_event(Event(kind=EventKind.CI_GREEN, task_id="t1"))
    events = store.list_events("t1")
    assert [event.kind for event in events] == [EventKind.ASSIGN, EventKind.CI_GREEN]


def test_database_refuses_to_update_or_delete_events(tmp_path: Path) -> None:
    path = tmp_path / "tandem.sqlite3"
    with Store(path) as store:
        store.append_event(Event(kind=EventKind.ASSIGN, task_id="t1"))
    connection = sqlite3.connect(str(path))
    try:
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("UPDATE events SET kind = 'CI_GREEN'")
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("DELETE FROM events")
    finally:
        connection.close()


def test_task_snapshot_roundtrip(store: Store) -> None:
    task = TaskRecord(
        task_id="t1",
        status=TaskStatus.AWAITING_AI_REVIEW,
        level=Level.D,
        state_version=7,
        status_before_error=TaskStatus.WORKING,
        error_code="A01",
        plan_version=2,
        approved_plan_version=2,
        writer="claude",
        writer_is_human=False,
        providers_involved=frozenset({"claude", "codex"}),
        designated_reviewers=("codex", "opencode-go"),
        reviews=(
            Review(
                reviewer="codex",
                provider="codex",
                verdict=Verdict.PASS,
                sha="a" * 40,
                standard_version=1,
            ),
        ),
        standard_version=1,
        accept_failures=1,
        revision_counts=(RevisionCount(standard_version=1, count=2),),
        latest_sha="a" * 40,
        approved_sha=None,
        ci_green=True,
        pr_opened=True,
        attempt=3,
        returned_from_review=False,
        actions=(
            Action(
                action_id="t1:1:0",
                kind=ActionKind.MERGE,
                task_id="t1",
                detail="合并",
                provider=None,
                status=ActionStatus.UNKNOWN,
            ),
        ),
        reason="等审核",
        note="备注",
    )
    store.save_task(task)
    loaded = store.load_task("t1")
    assert loaded == task


def test_task_version_cannot_go_backwards(store: Store) -> None:
    store.save_task(TaskRecord(task_id="t1", state_version=5))
    with pytest.raises(StoreError):
        store.save_task(TaskRecord(task_id="t1", state_version=4))
    # 同一个版本号重复保存是允许的（幂等）
    store.save_task(TaskRecord(task_id="t1", state_version=5, reason="重放"))
    loaded = store.load_task("t1")
    assert loaded is not None
    assert loaded.reason == "重放"


def test_list_tasks_by_status(store: Store) -> None:
    store.save_task(TaskRecord(task_id="a", status=TaskStatus.PENDING))
    store.save_task(TaskRecord(task_id="b", status=TaskStatus.WORKING))
    pending = store.list_tasks_by_status(TaskStatus.PENDING)
    assert [task.task_id for task in pending] == ["a"]


def test_actions_record_and_update(store: Store) -> None:
    action = Action(
        action_id="t1:1:0", kind=ActionKind.MERGE, task_id="t1", detail="合并 PR", provider="github"
    )
    store.record_action(action)
    assert store.unconfirmed_actions("t1") == [action]

    store.update_action_status("t1:1:0", ActionStatus.DONE)
    assert store.unconfirmed_actions("t1") == []
    stored = store.list_actions("t1")
    assert stored[0].status is ActionStatus.DONE


def test_events_can_be_filtered_by_task(store: Store) -> None:
    store.append_event(Event(kind=EventKind.ASSIGN, task_id="a"))
    store.append_event(Event(kind=EventKind.ASSIGN, task_id="b"))
    assert len(store.list_events("a")) == 1
    assert len(store.list_events()) == 2


def test_task_snapshot_keeps_state_version(store: Store) -> None:
    store.save_task(TaskRecord(task_id="t1", state_version=3))
    loaded = store.load_task("t1")
    assert loaded is not None
    assert loaded.state_version == 3
    updated = replace(loaded, state_version=4, status=TaskStatus.WORKING)
    store.save_task(updated)
    assert store.load_task("t1") == updated
