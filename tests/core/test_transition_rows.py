"""第七版转换表 #1–#27 的逐条测试。

每个测试名里带条目编号，方便和 `docs/design/task-lifecycle.md` 对照。
"""

from __future__ import annotations

import pytest

from tandem.core.model import (
    ActionKind,
    CheckResult,
    EventKind,
    Level,
    QuotaState,
    RunMode,
    TaskStatus,
    Verdict,
)
from tests.core.helpers import (
    CODE_CHANGES,
    CORE_CHANGES,
    DOC_CHANGES,
    SHA_1,
    SHA_2,
    actions_of,
    ev,
    new_task,
    quota,
    review_event,
    run,
    single_agent_policy,
    to_acceptance,
    to_ai_review,
    to_d_ai_review,
    to_error,
    to_merge_ready,
    to_merged,
    to_needs_intervention_by_ci,
    to_needs_intervention_by_reviewers,
    to_working,
)

# ------------------------------------------------------------------ 第 1 条


def test_row_01_assign_starts_working() -> None:
    decision = run(new_task(), ev(EventKind.ASSIGN, provider="claude"))
    task = decision.task
    assert task.status is TaskStatus.WORKING
    assert task.attempt == 1
    assert task.writer == "claude"
    assert "claude" in task.providers_involved
    assert decision.changed
    assert [action.kind for action in decision.actions] == [ActionKind.START_AGENT]


def test_row_01_assign_needs_writer_quota() -> None:
    decision = run(new_task(), ev(EventKind.ASSIGN, provider="claude"), quota_=quota(("claude",)))
    assert decision.task.status is TaskStatus.PENDING
    assert not decision.changed
    assert "额度" in decision.reason


def test_row_01_assign_needs_two_eligible_reviewers() -> None:
    # 只有 opencode-go 还有额度，凑不齐两家审核者
    decision = run(new_task(), ev(EventKind.ASSIGN, provider="claude"), quota_=quota(("codex",)))
    assert decision.task.status is TaskStatus.PENDING
    assert "审核者" in decision.reason


def test_row_01_single_agent_mode_needs_no_reviewer() -> None:
    # 单 Agent 模式下没有人能审，所以不要求凑审核者
    record = new_task(run_mode=RunMode.SINGLE_AGENT)
    decision = run(
        record,
        ev(EventKind.ASSIGN, provider="claude"),
        policy_=single_agent_policy(),
        quota_=quota(("codex", "opencode-go")),
    )
    assert decision.task.status is TaskStatus.WORKING


# ------------------------------------------------------------------ 第 2–4 条


def test_row_02_d_level_plan_waits_for_you() -> None:
    record = to_working(new_task(Level.D))
    decision = run(record, ev(EventKind.PLAN_SUBMITTED, plan="先改 decide 的签名"))
    assert decision.task.status is TaskStatus.AWAITING_PLAN_APPROVAL
    assert decision.task.plan_version == 1
    assert ActionKind.NOTIFY in [action.kind for action in decision.actions]


def test_row_02_c_level_plan_is_only_a_note() -> None:
    record = to_working(new_task(Level.C))
    decision = run(record, ev(EventKind.PLAN_SUBMITTED, plan="随便写点"))
    assert decision.task.status is TaskStatus.WORKING
    assert not decision.changed


def test_row_03_you_approve_the_plan() -> None:
    record = to_working(new_task(Level.D))
    record = run(record, ev(EventKind.PLAN_SUBMITTED, plan="方案第一版")).task
    decision = run(record, ev(EventKind.PLAN_APPROVED))
    assert decision.task.status is TaskStatus.PENDING
    assert decision.task.approved_plan_version == 1
    assert decision.task.plan_version == 1


def test_row_04_you_reject_the_plan() -> None:
    record = to_working(new_task(Level.D))
    record = run(record, ev(EventKind.PLAN_SUBMITTED, plan="方案第一版")).task
    decision = run(record, ev(EventKind.PLAN_REJECTED, reason="先写测试"))
    assert decision.task.status is TaskStatus.PENDING
    assert decision.task.approved_plan_version is None
    assert "先写测试" in decision.task.note


# ------------------------------------------------------------------ 第 5、5b 条


def test_row_05_code_submitted_goes_to_acceptance() -> None:
    record = to_working(new_task())
    decision = run(
        record,
        ev(EventKind.CODE_SUBMITTED, attempt=1, sha=SHA_1, changes=DOC_CHANGES),
    )
    assert decision.task.status is TaskStatus.AWAITING_ACCEPTANCE
    assert decision.task.latest_sha == SHA_1
    assert decision.task.pr_opened
    assert not decision.task.ci_green


def test_row_05_receipt_without_sha_is_invalid() -> None:
    record = to_working(new_task())
    decision = run(record, ev(EventKind.CODE_SUBMITTED, attempt=1, changes=DOC_CHANGES))
    assert decision.task.status is TaskStatus.WORKING
    assert "无效回执" in decision.reason


def test_row_05_receipt_with_wrong_attempt_is_ignored() -> None:
    record = to_working(new_task())
    decision = run(
        record,
        ev(EventKind.CODE_SUBMITTED, attempt=7, sha=SHA_1, changes=DOC_CHANGES),
    )
    assert decision.task.status is TaskStatus.WORKING
    assert "尝试" in decision.reason


def test_row_05b_recomputed_d_level_needs_plan_approval() -> None:
    # 说是"改样式"，实际改了 core：重新算级别后升成 D，方案还没批准
    record = to_working(new_task(Level.C))
    decision = run(
        record,
        ev(EventKind.CODE_SUBMITTED, attempt=1, sha=SHA_1, changes=CORE_CHANGES),
    )
    assert decision.task.status is TaskStatus.AWAITING_PLAN_APPROVAL
    assert decision.task.level is Level.D
    assert decision.task.plan_version == 1
    assert ActionKind.NOTIFY in [action.kind for action in decision.actions]


# ------------------------------------------------------------------ 第 6、7 条


def test_row_06_writer_refuses_to_fix_goes_to_you() -> None:
    record = to_ai_review()
    record = run(record, review_event(record, "codex", Verdict.FAIL)).task
    assert record.returned_from_review
    record = to_working(record)
    decision = run(record, ev(EventKind.REFUSED_TO_FIX, reason="标准不对，我不改"))
    assert decision.task.status is TaskStatus.NEEDS_INTERVENTION
    assert "标准不对" in decision.task.reason


def test_row_06_refusal_without_previous_review_is_ignored() -> None:
    record = to_working(new_task())
    decision = run(record, ev(EventKind.REFUSED_TO_FIX, reason="我不想改"))
    assert decision.task.status is TaskStatus.WORKING
    assert not decision.changed


def test_row_07_quota_exhausted_returns_to_pending() -> None:
    record = to_working(new_task())
    decision = run(record, ev(EventKind.QUOTA_EXHAUSTED, provider="claude", reason="写到一半"))
    assert decision.task.status is TaskStatus.PENDING
    assert [
        action.kind for action in decision.actions if action.kind is ActionKind.SET_QUOTA_EXHAUSTED
    ]
    assert "额度是估计值" in decision.task.note
    assert "写到一半" in decision.reason


# ------------------------------------------------------------------ 第 8 条


@pytest.mark.parametrize(
    "record_factory",
    [lambda: to_working(new_task()), lambda: to_acceptance(to_working(new_task()))],
)
def test_row_08_incident_goes_to_error(record_factory: object) -> None:
    record = record_factory()  # type: ignore[operator]
    decision = run(record, ev(EventKind.INCIDENT, reason="网络断了", error_code="E02"))
    assert decision.task.status is TaskStatus.ERROR
    assert decision.task.status_before_error is record.status
    assert decision.task.error_code == "E02"
    assert "还没确认完成的动作" in decision.task.note


# ------------------------------------------------------------------ 第 9、9b 条


def test_row_09_ci_green_starts_ai_review() -> None:
    record = to_ai_review()
    assert record.status is TaskStatus.AWAITING_AI_REVIEW
    assert record.designated_reviewers == ("codex", "opencode-go")
    assert record.ci_green
    assert len(actions_of(run(record, ev(EventKind.INCIDENT)), ActionKind.NOTIFY)) >= 1


def test_row_09_ci_green_dispatches_two_reviewers() -> None:
    record = to_working(new_task())
    record = to_acceptance(record)
    decision = run(record, ev(EventKind.CI_GREEN, sha=record.latest_sha))
    reviews = actions_of(decision, ActionKind.REQUEST_REVIEW)
    assert [action.provider for action in reviews] == ["codex", "opencode-go"]
    assert decision.task.designated_reviewers == ("codex", "opencode-go")


def test_row_09_ci_for_other_sha_is_ignored() -> None:
    record = to_acceptance(to_working(new_task()))
    decision = run(record, ev(EventKind.CI_GREEN, sha=SHA_2))
    assert decision.task.status is TaskStatus.AWAITING_ACCEPTANCE
    assert "提交编号" in decision.reason


def test_row_09b_single_agent_mode_goes_to_your_review() -> None:
    single = single_agent_policy()
    record = to_working(new_task(run_mode=RunMode.SINGLE_AGENT), provider="claude")
    record = to_acceptance(record)
    decision = run(record, ev(EventKind.CI_GREEN, sha=record.latest_sha), policy_=single)
    assert decision.task.status is TaskStatus.AWAITING_YOUR_REVIEW
    assert decision.task.note == "这次没有 AI 审核"


# ------------------------------------------------------------------ 第 10、11 条


def test_row_10_ci_red_returns_to_pending() -> None:
    record = to_acceptance(to_working(new_task()))
    decision = run(record, ev(EventKind.CI_RED, reason="测试没过"))
    assert decision.task.status is TaskStatus.PENDING
    assert decision.task.accept_failures == 1
    assert "测试没过" in decision.task.note


def test_row_11_third_ci_red_goes_to_you() -> None:
    record = to_needs_intervention_by_ci()
    assert record.status is TaskStatus.NEEDS_INTERVENTION
    assert record.error_code == "R01"
    assert record.accept_failures == 3


# ------------------------------------------------------------------ 第 12–16 条


def test_row_12_all_reviewers_pass_merges() -> None:
    record = to_ai_review()
    record = run(record, review_event(record, "codex")).task
    assert record.status is TaskStatus.AWAITING_AI_REVIEW  # 还差一家
    decision = run(record, review_event(record, "opencode-go"))
    assert decision.task.status is TaskStatus.AWAITING_MERGE
    assert decision.task.approved_sha == record.latest_sha
    assert actions_of(decision, ActionKind.MERGE)


def test_row_12_reviews_must_be_for_current_sha() -> None:
    record = to_ai_review()
    decision = run(record, review_event(record, "codex", sha=SHA_2))
    assert decision.task.status is TaskStatus.AWAITING_AI_REVIEW
    assert not decision.task.reviews
    assert "提交编号" in decision.reason


def test_row_12_writer_cannot_review_own_code() -> None:
    record = to_ai_review()
    decision = run(record, review_event(record, "claude"))
    assert decision.task.status is TaskStatus.AWAITING_AI_REVIEW
    assert not decision.task.reviews


def test_row_13_d_level_all_pass_waits_for_you() -> None:
    record = to_d_ai_review()
    assert record.level is Level.D
    record = run(record, review_event(record, record.designated_reviewers[0])).task
    record = run(record, review_event(record, record.designated_reviewers[1])).task
    assert record.status is TaskStatus.AWAITING_YOUR_REVIEW
    assert not any(action.kind is ActionKind.MERGE for action in record.actions)


def test_row_14_review_failure_returns_to_pending_and_voids_conclusions() -> None:
    record = to_ai_review()
    record = run(record, review_event(record, "codex")).task
    assert len(record.reviews) == 1
    decision = run(record, review_event(record, "opencode-go", Verdict.FAIL))
    assert decision.task.status is TaskStatus.PENDING
    assert decision.task.reviews == ()
    assert decision.task.returned_from_review
    assert decision.task.revision_count(decision.task.standard_version) == 1


def test_row_14b_ai_rejects_your_own_code() -> None:
    record = to_needs_intervention_by_ci()
    record = run(record, ev(EventKind.TAKE_OVER)).task
    record = run(record, ev(EventKind.YOU_SUBMITTED_CODE, sha=SHA_2)).task
    record = run(record, ev(EventKind.CI_GREEN, sha=SHA_2)).task
    assert record.status is TaskStatus.AWAITING_AI_REVIEW
    assert record.writer_is_human
    decision = run(record, review_event(record, "codex", Verdict.FAIL))
    assert decision.task.status is TaskStatus.NEEDS_INTERVENTION
    assert "写手是你" in decision.task.reason


def test_row_15_third_revision_goes_to_you() -> None:
    record = to_ai_review()
    for expected_revision in (1, 2):
        record = run(record, review_event(record, "codex", Verdict.FAIL)).task
        assert record.status is TaskStatus.PENDING
        assert record.revision_count(record.standard_version) == expected_revision
        record = to_working(record)
        record = to_acceptance(record, sha=SHA_2)
        record = run(record, ev(EventKind.CI_GREEN, sha=SHA_2)).task
    decision = run(record, review_event(record, "codex", Verdict.FAIL))
    assert decision.task.status is TaskStatus.NEEDS_INTERVENTION
    assert decision.task.error_code == "R02"
    assert decision.task.revision_count(decision.task.standard_version) == 3


def test_row_16_not_enough_reviewers_goes_to_you() -> None:
    record = to_needs_intervention_by_reviewers()
    assert record.status is TaskStatus.NEEDS_INTERVENTION
    assert record.error_code == "R03"
    assert record.ci_green


# ------------------------------------------------------------------ 第 17–22 条


def test_row_17_you_approve_and_merge() -> None:
    record = to_d_ai_review()
    for reviewer in record.designated_reviewers:
        record = run(record, review_event(record, reviewer)).task
    assert record.status is TaskStatus.AWAITING_YOUR_REVIEW
    decision = run(record, ev(EventKind.YOUR_APPROVAL))
    assert decision.task.status is TaskStatus.AWAITING_MERGE
    assert decision.task.approved_sha == record.latest_sha
    assert actions_of(decision, ActionKind.MERGE)


def test_row_18_you_reject_the_code() -> None:
    record = to_d_ai_review()
    for reviewer in record.designated_reviewers:
        record = run(record, review_event(record, reviewer)).task
    decision = run(record, ev(EventKind.YOUR_REJECTION, reason="这里不对"))
    assert decision.task.status is TaskStatus.PENDING
    assert decision.task.reviews == ()
    assert "这里不对" in decision.task.reason


def test_row_19_merge_success_finishes() -> None:
    record = to_merge_ready()
    assert record.status is TaskStatus.AWAITING_MERGE
    decision = run(record, ev(EventKind.MERGED, sha=record.latest_sha))
    assert decision.task.status is TaskStatus.MERGED
    assert decision.task.status.is_terminal


def test_row_19_merge_with_wrong_sha_is_ignored() -> None:
    record = to_merge_ready()
    decision = run(record, ev(EventKind.MERGED, sha=SHA_2))
    assert decision.task.status is TaskStatus.AWAITING_MERGE
    assert "不一致" in decision.reason


def test_row_20_you_approve_after_intervention() -> None:
    record = to_needs_intervention_by_reviewers()
    decision = run(record, ev(EventKind.INTERVENTION_APPROVED, reason="我看过了"))
    assert decision.task.status is TaskStatus.AWAITING_MERGE
    assert decision.task.approved_sha == record.latest_sha
    assert actions_of(decision, ActionKind.MERGE)


def test_row_20_needs_green_ci() -> None:
    record = to_needs_intervention_by_ci()
    assert not record.ci_green
    decision = run(record, ev(EventKind.INTERVENTION_APPROVED, reason="我看过了"))
    assert decision.task.status is TaskStatus.NEEDS_INTERVENTION
    assert "CI" in decision.reason


def test_row_20_vetoing_ai_needs_reasons() -> None:
    record = to_needs_intervention_by_ci()
    record = run(record, ev(EventKind.TAKE_OVER)).task
    record = run(record, ev(EventKind.YOU_SUBMITTED_CODE, sha=SHA_2)).task
    record = run(record, ev(EventKind.CI_GREEN, sha=SHA_2)).task
    record = run(record, review_event(record, "codex", Verdict.FAIL)).task
    assert record.status is TaskStatus.NEEDS_INTERVENTION
    without_reason = run(record, ev(EventKind.INTERVENTION_APPROVED))
    assert without_reason.task.status is TaskStatus.NEEDS_INTERVENTION
    with_reason = run(
        record, ev(EventKind.INTERVENTION_APPROVED, reason="这条意见我不同意，理由如下")
    )
    assert with_reason.task.status is TaskStatus.AWAITING_MERGE


def test_row_21_rework_with_another_agent() -> None:
    record = to_needs_intervention_by_ci()
    decision = run(record, ev(EventKind.REWORK, reason="换 opus 再试"))
    assert decision.task.status is TaskStatus.PENDING
    assert decision.task.reviews == ()
    assert "换 opus 再试" in decision.task.note


def test_row_22_change_review_standard_and_review_again() -> None:
    record = to_needs_intervention_by_reviewers()
    decision = run(record, ev(EventKind.STANDARD_CHANGED, standard_version=2, reason="标准太严"))
    assert decision.task.status is TaskStatus.AWAITING_AI_REVIEW
    assert decision.task.standard_version == 2
    assert decision.task.designated_reviewers == ("codex", "opencode-go")
    assert actions_of(decision, ActionKind.REQUEST_REVIEW)


def test_row_22_standard_version_must_go_up() -> None:
    record = to_needs_intervention_by_reviewers()
    decision = run(record, ev(EventKind.STANDARD_CHANGED, standard_version=1))
    assert decision.task.status is TaskStatus.NEEDS_INTERVENTION
    assert "标准版本号" in decision.reason


# ------------------------------------------------------------------ 第 23–27 条


def test_row_23_you_take_over() -> None:
    record = to_needs_intervention_by_ci()
    decision = run(record, ev(EventKind.TAKE_OVER))
    assert decision.task.status is TaskStatus.YOU_WORKING


def test_row_24_you_submit_code() -> None:
    record = run(to_needs_intervention_by_ci(), ev(EventKind.TAKE_OVER)).task
    decision = run(record, ev(EventKind.YOU_SUBMITTED_CODE, sha=SHA_2))
    assert decision.task.status is TaskStatus.AWAITING_ACCEPTANCE
    assert decision.task.writer_is_human
    assert decision.task.latest_sha == SHA_2
    # 注明有哪些 AI 参与过
    assert "claude" in decision.task.note


def test_row_25_abandon_fails_the_task() -> None:
    record = to_needs_intervention_by_ci()
    decision = run(record, ev(EventKind.ABANDON, reason="不做了"))
    assert decision.task.status is TaskStatus.FAILED


def test_row_26_retry_after_checking_external_facts() -> None:
    record = to_error()
    assert record.status is TaskStatus.ERROR
    assert record.status_before_error is TaskStatus.AWAITING_AI_REVIEW
    merged = run(record, ev(EventKind.RETRY, check_result=CheckResult.MERGE_SUCCEEDED))
    assert merged.task.status is TaskStatus.MERGED
    back = run(record, ev(EventKind.RETRY, check_result=CheckResult.NOT_CONFIRMED))
    assert back.task.status is TaskStatus.AWAITING_AI_REVIEW


def test_row_26_retry_needs_a_check_result() -> None:
    record = to_error()
    decision = run(record, ev(EventKind.RETRY))
    assert decision.task.status is TaskStatus.ERROR
    assert "核对" in decision.reason


def test_row_27_cancel_from_pending_has_nothing_to_clean() -> None:
    decision = run(new_task(), ev(EventKind.CANCEL))
    assert decision.task.status is TaskStatus.CANCELLED
    assert decision.actions == []


def test_row_27_cancel_while_working_keeps_the_branch() -> None:
    record = to_working(new_task())
    decision = run(record, ev(EventKind.CANCEL))
    kinds = [action.kind for action in decision.actions]
    assert decision.task.status is TaskStatus.CANCELLED
    assert ActionKind.STOP_AGENT in kinds
    assert ActionKind.PUSH_BRANCH in kinds


def test_row_27_cancel_during_review_closes_pr() -> None:
    record = to_ai_review()
    decision = run(record, ev(EventKind.CANCEL))
    kinds = [action.kind for action in decision.actions]
    assert decision.task.status is TaskStatus.CANCELLED
    assert ActionKind.STOP_AGENT in kinds
    assert ActionKind.CLOSE_PR in kinds


def test_row_27_cannot_cancel_after_merge_started() -> None:
    record = to_merge_ready()
    decision = run(record, ev(EventKind.CANCEL))
    assert decision.task.status is TaskStatus.AWAITING_MERGE
    assert "合并已经开始" in decision.reason


# ------------------------------------------------------------------ 横切规则


def test_state_version_mismatch_ignores_event() -> None:
    record = to_working(new_task())
    decision = run(record, ev(EventKind.CODE_SUBMITTED, state_version=0, sha=SHA_1))
    assert decision.task == record
    assert not decision.changed
    assert "版本号" in decision.reason


def test_state_version_match_is_accepted() -> None:
    record = to_working(new_task())
    decision = run(
        record,
        ev(
            EventKind.CODE_SUBMITTED,
            state_version=record.state_version,
            attempt=record.attempt,
            sha=SHA_1,
            changes=DOC_CHANGES,
        ),
    )
    assert decision.task.status is TaskStatus.AWAITING_ACCEPTANCE


@pytest.mark.parametrize("level", [Level.C, Level.D])
def test_terminal_task_ignores_late_events(level: Level) -> None:
    if level is Level.C:
        record = to_merged()
    else:
        record = to_d_ai_review()
        for reviewer in record.designated_reviewers:
            record = run(record, review_event(record, reviewer)).task
        record = run(record, ev(EventKind.YOUR_APPROVAL)).task
        record = run(record, ev(EventKind.MERGED, sha=record.latest_sha)).task
    assert record.status is TaskStatus.MERGED
    decision = run(
        record,
        ev(EventKind.CODE_SUBMITTED, attempt=9, sha=SHA_2, changes=DOC_CHANGES),
    )
    assert decision.task == record
    assert "已经结束" in decision.reason


def test_new_commit_voids_reviews_and_approval() -> None:
    record = to_ai_review()
    record = run(record, review_event(record, "codex")).task
    assert len(record.reviews) == 1
    # 退回修改后重新交代码，旧的审核结论、批准必须作废
    record = run(record, review_event(record, "opencode-go", Verdict.FAIL)).task
    record = to_working(record)
    decision = run(
        record,
        ev(EventKind.CODE_SUBMITTED, attempt=record.attempt, sha=SHA_2, changes=CODE_CHANGES),
    )
    assert decision.task.reviews == ()
    assert decision.task.approved_sha is None
    assert decision.task.latest_sha == SHA_2


def test_cancelled_task_ignores_late_receipt() -> None:
    record = run(to_working(new_task()), ev(EventKind.CANCEL)).task
    assert record.status is TaskStatus.CANCELLED
    decision = run(record, ev(EventKind.CODE_SUBMITTED, attempt=1, sha=SHA_1, changes=CODE_CHANGES))
    assert decision.task.status is TaskStatus.CANCELLED
    assert not decision.changed


def test_quota_snapshot_unknown_means_available() -> None:
    snapshot = quota()
    assert snapshot.state("nobody") is QuotaState.UNKNOWN
    assert snapshot.has_quota("nobody")
