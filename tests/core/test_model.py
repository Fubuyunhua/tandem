"""内核数据结构的小测试：状态、等级、额度、次数。"""

from __future__ import annotations

from tandem.core.model import (
    Level,
    Policy,
    QuotaSnapshot,
    QuotaState,
    RevisionCount,
    TaskRecord,
    TaskStatus,
)


def test_thirteen_statuses() -> None:
    assert len(list(TaskStatus)) == 13


def test_three_terminal_statuses() -> None:
    terminal = {status for status in TaskStatus if status.is_terminal}
    assert terminal == {TaskStatus.MERGED, TaskStatus.CANCELLED, TaskStatus.FAILED}


def test_level_rank_order() -> None:
    assert Level.A.rank < Level.B.rank < Level.C.rank < Level.D.rank
    assert Level.A.stricter(Level.D) is Level.D
    assert Level.C.stricter(Level.B) is Level.C


def test_quota_unknown_means_available() -> None:
    snapshot = QuotaSnapshot()
    assert snapshot.state("claude") is QuotaState.UNKNOWN
    assert snapshot.has_quota("claude")


def test_quota_exhausted_is_not_available() -> None:
    snapshot = QuotaSnapshot.from_mapping({"claude": QuotaState.EXHAUSTED})
    assert not snapshot.has_quota("claude")
    assert snapshot.has_quota("codex")


def test_revision_count_per_standard_version() -> None:
    record = TaskRecord(task_id="t1")
    bumped = TaskRecord(task_id="t1", revision_counts=record.bumped_revision())
    assert bumped.revision_count(1) == 1
    # 换了审核标准版本，计数从 0 开始，历史保留
    changed = TaskRecord(task_id="t1", standard_version=2, revision_counts=bumped.revision_counts)
    assert changed.revision_count(2) == 0
    assert changed.revision_count(1) == 1
    bumped_again = TaskRecord(
        task_id="t1", standard_version=2, revision_counts=changed.bumped_revision()
    )
    assert bumped_again.revision_count(2) == 1
    assert bumped_again.revision_count(1) == 1


def test_current_reviews_ignore_old_sha_and_version() -> None:
    from tandem.core.model import Review, Verdict

    record = TaskRecord(
        task_id="t1",
        latest_sha="new",
        standard_version=2,
        reviews=(
            Review("a", "codex", Verdict.PASS, "new", 2),
            Review("b", "codex", Verdict.PASS, "new", 1),
            Review("c", "codex", Verdict.PASS, "old", 2),
        ),
    )
    assert [review.reviewer for review in record.current_reviews()] == ["a"]


def test_default_policy_rules() -> None:
    policy = Policy()
    assert policy.rule_for(Level.C).min_reviewers == 2
    assert policy.rule_for(Level.D).requires_plan_approval
    assert policy.rule_for(Level.D).requires_human_merge
    assert not policy.rule_for(Level.A).requires_ai_review


def test_revision_history_is_append_only_shape() -> None:
    record = TaskRecord(task_id="t1", revision_counts=(RevisionCount(standard_version=1, count=2),))
    assert record.bumped_revision() == (RevisionCount(standard_version=1, count=3),)
