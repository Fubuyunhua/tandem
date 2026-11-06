"""存储层测试：只追加、版本号、原子提交、动作状态。"""

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
    CheckResult,
    Event,
    EventKind,
    Level,
    Review,
    RevisionCount,
    TaskRecord,
    TaskStatus,
    Verdict,
)
from tandem.shell.store import ConflictError, Store, StoreError


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    with Store(tmp_path / "tandem.sqlite3") as opened:
        yield opened


def _task(version: int = 0, **changes: object) -> TaskRecord:
    return replace(TaskRecord(task_id="t1", state_version=version), **changes)


def test_events_are_append_only(store: Store) -> None:
    store.commit(
        events=[
            Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"),
            Event(kind=EventKind.CI_GREEN, task_id="t1"),
        ]
    )
    events = store.list_events("t1")
    assert [event.kind for event in events] == [EventKind.ASSIGN, EventKind.CI_GREEN]


def test_database_refuses_to_update_or_delete_events(tmp_path: Path) -> None:
    path = tmp_path / "tandem.sqlite3"
    with Store(path) as store:
        store.commit(events=[Event(kind=EventKind.ASSIGN, task_id="t1")])
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
        base_sha="main",
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
    store.commit(task=task)
    assert store.load_task("t1") == task


def test_task_version_cannot_go_backwards(store: Store) -> None:
    store.commit(task=_task(5))
    with pytest.raises(StoreError):
        store.commit(task=_task(4), expected_version=5)


def test_same_version_only_accepts_identical_content(store: Store) -> None:
    """同一版本号只接受内容完全相同的重复保存（重放）。"""
    store.commit(task=_task(5))
    # 内容不同 → 拒绝
    with pytest.raises(ConflictError):
        store.commit(task=_task(5, reason="另一份内容"), expected_version=5)
    # 内容完全相同 → 幂等
    store.commit(task=_task(5), expected_version=5)
    loaded = store.load_task("t1")
    assert loaded is not None
    assert loaded.state_version == 5


def test_concurrent_writers_second_one_is_rejected(tmp_path: Path) -> None:
    """两个处理者基于同一个旧版本各写一次：第二个必须失败，不能覆盖第一个。"""
    path = tmp_path / "tandem.sqlite3"
    with Store(path) as first, Store(path) as second:
        first.commit(task=_task(0))
        base = first.load_task("t1")
        assert base is not None

        first.commit(
            task=replace(base, state_version=1, status=TaskStatus.WORKING),
            expected_version=0,
        )
        with pytest.raises(ConflictError):
            second.commit(
                task=replace(base, state_version=1, status=TaskStatus.CANCELLED),
                expected_version=0,
            )

        loaded = second.load_task("t1")
        assert loaded is not None
        assert loaded.status is TaskStatus.WORKING


def test_commit_is_atomic(store: Store) -> None:
    """任务更新失败时，同一个事务里的事件和动作都不能留在库里。"""
    store.commit(task=_task(3))
    with pytest.raises(ConflictError):
        store.commit(
            events=[Event(kind=EventKind.CI_GREEN, task_id="t1")],
            task=replace(_task(4), status=TaskStatus.AWAITING_AI_REVIEW),
            expected_version=99,  # 旧的版本号对不上
            actions=[Action(action_id="t1:4:0", kind=ActionKind.NOTIFY, task_id="t1")],
        )
    assert store.list_events("t1") == []
    assert store.list_actions("t1") == []
    loaded = store.load_task("t1")
    assert loaded is not None
    assert loaded.state_version == 3


def test_commit_writes_events_task_and_actions_together(store: Store) -> None:
    result = store.commit(
        events=[Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude")],
        task=_task(0, status=TaskStatus.WORKING),
        actions=[Action(action_id="t1:1:0", kind=ActionKind.START_AGENT, task_id="t1")],
    )
    assert result.events == 1
    assert result.task_written
    assert result.actions == 1
    assert store.list_events("t1")
    assert store.list_actions("t1")


def test_list_tasks_by_status(store: Store) -> None:
    store.commit(task=TaskRecord(task_id="a", status=TaskStatus.PENDING))
    store.commit(task=TaskRecord(task_id="b", status=TaskStatus.WORKING))
    pending = store.list_tasks_by_status(TaskStatus.PENDING)
    assert [task.task_id for task in pending] == ["a"]


def test_actions_record_and_update(store: Store) -> None:
    action = Action(
        action_id="t1:1:0", kind=ActionKind.MERGE, task_id="t1", detail="合并 PR", provider="github"
    )
    store.commit(actions=[action])
    assert store.unconfirmed_actions("t1") == [action]

    store.update_action_status("t1:1:0", ActionStatus.DONE)
    assert store.unconfirmed_actions("t1") == []
    stored = store.list_actions("t1")
    assert stored[0].status is ActionStatus.DONE


def test_events_can_be_filtered_by_task(store: Store) -> None:
    store.commit(
        events=[
            Event(kind=EventKind.ASSIGN, task_id="a"),
            Event(kind=EventKind.ASSIGN, task_id="b"),
        ]
    )
    assert len(store.list_events("a")) == 1
    assert len(store.list_events()) == 2


def test_task_snapshot_keeps_state_version(store: Store) -> None:
    store.commit(task=_task(3))
    loaded = store.load_task("t1")
    assert loaded is not None
    assert loaded.state_version == 3
    updated = replace(loaded, state_version=4, status=TaskStatus.WORKING)
    store.commit(task=updated, expected_version=3)
    assert store.load_task("t1") == updated


def test_replaying_the_same_actions_keeps_their_status(store: Store) -> None:
    """H6：动作编号相同、内容相同 → 保留原来的执行状态，不重置成"已发出"。"""
    action = Action(
        action_id="t1:1:0", kind=ActionKind.START_AGENT, task_id="t1", provider="claude"
    )
    task = _task(0, status=TaskStatus.WORKING)
    first = store.commit(
        events=[Event(kind=EventKind.ASSIGN, task_id="t1")], task=task, actions=[action]
    )
    assert first.claimed_action_ids == ("t1:1:0",)
    store.update_action_status("t1:1:0", ActionStatus.DONE)

    replay = store.commit(
        events=[Event(kind=EventKind.ASSIGN, task_id="t1")], task=task, actions=[action]
    )
    assert replay.claimed_action_ids == ()  # 这次没有抢到执行权
    stored = store.list_actions("t1")
    assert [item.status for item in stored] == [ActionStatus.DONE]


def test_action_id_reuse_with_different_content_is_rejected(store: Store) -> None:
    action = Action(
        action_id="t1:1:0", kind=ActionKind.START_AGENT, task_id="t1", provider="claude"
    )
    store.commit(actions=[action])
    other = Action(action_id="t1:1:0", kind=ActionKind.MERGE, task_id="t1", provider="github")
    with pytest.raises(ConflictError):
        store.commit(actions=[other])
    assert [item.kind for item in store.list_actions("t1")] == [ActionKind.START_AGENT]


def test_open_findings_survive_a_store_roundtrip(store: Store) -> None:
    """H5 的复合键要能存下来：重开数据库以后还能按同一个键写否决理由。"""
    from tandem.core.model import OpenFinding

    finding = OpenFinding(
        key="codex:F1@abcdef12:v1",
        provider="codex",
        sha="abcdef12" + "0" * 32,
        standard_version=1,
        local_id="F1",
        text="异常分支没有测试",
    )
    task = _task(2, open_findings=(finding,))
    store.commit(task=task)
    loaded = store.load_task("t1")
    assert loaded is not None
    assert loaded.open_findings == (finding,)


def test_plan_history_survives_a_store_roundtrip(store: Store) -> None:
    """方案正文要能存下来：note 会被后续转换改掉，方案不能跟着没。"""
    from tandem.core.model import PlanEntry

    task = _task(
        2,
        plan_version=1,
        approved_plan_version=None,
        plan_history=(
            PlanEntry(
                version=1, sha="c" * 40, text="第 1 版方案：没有文字方案，内容就是提交的改动"
            ),
        ),
        note="后来的原因把 note 覆盖了",
    )
    store.commit(task=task)
    loaded = store.load_task("t1")
    assert loaded is not None
    assert loaded.plan_history == task.plan_history
    assert loaded.plan_text.startswith("第 1 版方案")
    assert loaded.plan(1) is not None
    assert loaded.plan(2) is None


def test_cleanup_record_and_abandoned_action_roundtrip(store: Store) -> None:
    """清理核对的结果要能存下来：cleanup_checked、已放弃的动作、事件里的动作编号。"""
    abandoned = Action(
        action_id="t1:5:1",
        kind=ActionKind.CLOSE_PR,
        task_id="t1",
        detail="关闭 PR",
        status=ActionStatus.ABANDONED,
    )
    task = _task(5, status=TaskStatus.CANCELLED, cleanup_checked=True, actions=(abandoned,))
    event = Event(
        kind=EventKind.CLEANUP_CHECKED,
        task_id="t1",
        check_result=CheckResult.NOT_CONFIRMED,
        action_ids=("t1:5:1",),
    )
    store.commit(task=task, events=[event])

    loaded = store.load_task("t1")
    assert loaded is not None
    assert loaded.cleanup_checked is True
    assert loaded.actions[0].status is ActionStatus.ABANDONED
    assert store.unconfirmed_actions("t1") == []  # 放弃以后不再算未确认
    stored_event = store.list_events("t1")[0]
    assert stored_event.action_ids == ("t1:5:1",)
    assert stored_event.check_result is CheckResult.NOT_CONFIRMED
