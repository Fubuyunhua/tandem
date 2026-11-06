"""第七版转换表 #1–#27 的逐条测试。

每个测试名里带条目编号，方便和 `docs/design/task-lifecycle.md` 对照。
"""

from __future__ import annotations

import pytest

from tandem.core.model import (
    ActionKind,
    CheckResult,
    EventKind,
    Finding,
    Level,
    QuotaState,
    Review,
    RunMode,
    TaskRecord,
    TaskStatus,
    Verdict,
    VetoReason,
)
from tests.core.helpers import (
    CODE_CHANGES,
    CORE_CHANGES,
    DOC_CHANGES,
    SHA_1,
    SHA_2,
    SOME_FINDINGS,
    Walker,
    actions_of,
    ev,
    new_task,
    policy,
    quota,
    review_event,
    run,
    single_agent_policy,
    to_acceptance,
    to_ai_review,
    to_d_ai_review,
    to_error,
    to_error_before_merge,
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
    record = run(record, review_event(record, "codex", Verdict.FAIL, findings=SOME_FINDINGS)).task
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
    decision = run(record, ev(EventKind.CI_RED, sha=record.latest_sha, reason="测试没过"))
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
    decision = run(
        record, review_event(record, "opencode-go", Verdict.FAIL, findings=SOME_FINDINGS)
    )
    assert decision.task.status is TaskStatus.PENDING
    assert decision.task.reviews == ()
    assert decision.task.returned_from_review
    assert decision.task.revision_count(decision.task.standard_version) == 1


def test_row_14b_ai_rejects_your_own_code() -> None:
    record = to_needs_intervention_by_ci()
    record = run(record, ev(EventKind.TAKE_OVER)).task
    record = run(
        record,
        ev(EventKind.YOU_SUBMITTED_CODE, sha=SHA_2, changes=CODE_CHANGES),
    ).task
    record = run(record, ev(EventKind.CI_GREEN, sha=SHA_2)).task
    assert record.status is TaskStatus.AWAITING_AI_REVIEW
    assert record.writer_is_human
    decision = run(record, review_event(record, "codex", Verdict.FAIL, findings=SOME_FINDINGS))
    assert decision.task.status is TaskStatus.NEEDS_INTERVENTION
    assert "写手是你" in decision.task.reason


def test_row_15_third_revision_goes_to_you() -> None:
    record = to_ai_review()
    for expected_revision in (1, 2):
        record = run(
            record, review_event(record, "codex", Verdict.FAIL, findings=SOME_FINDINGS)
        ).task
        assert record.status is TaskStatus.PENDING
        assert record.revision_count(record.standard_version) == expected_revision
        record = to_working(record)
        record = to_acceptance(record, sha=SHA_2)
        record = run(record, ev(EventKind.CI_GREEN, sha=SHA_2)).task
    decision = run(record, review_event(record, "codex", Verdict.FAIL, findings=SOME_FINDINGS))
    assert decision.task.status is TaskStatus.NEEDS_INTERVENTION
    assert decision.task.error_code == "R02"
    assert decision.task.revision_count(decision.task.standard_version) == 3


def test_row_16_not_enough_reviewers_at_entry_goes_to_you() -> None:
    """第 16 条的入口分支：进审核之前就凑不齐合格的审核者。"""
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
    decision = run(record, ev(EventKind.YOUR_APPROVAL, sha=record.latest_sha))
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
    decision = run(
        record,
        ev(EventKind.INTERVENTION_APPROVED, sha=record.latest_sha, reason="我看过了"),
    )
    assert decision.task.status is TaskStatus.AWAITING_MERGE
    assert decision.task.approved_sha == record.latest_sha
    assert actions_of(decision, ActionKind.MERGE)


def test_row_20_needs_green_ci() -> None:
    record = to_needs_intervention_by_ci()
    assert not record.ci_green
    decision = run(
        record,
        ev(EventKind.INTERVENTION_APPROVED, sha=record.latest_sha, reason="我看过了"),
    )
    assert decision.task.status is TaskStatus.NEEDS_INTERVENTION
    assert "CI" in decision.reason


def test_row_20_vetoing_ai_needs_reasons() -> None:
    record = to_needs_intervention_by_ci()
    record = run(record, ev(EventKind.TAKE_OVER)).task
    record = run(
        record,
        ev(EventKind.YOU_SUBMITTED_CODE, sha=SHA_2, changes=CODE_CHANGES),
    ).task
    record = run(record, ev(EventKind.CI_GREEN, sha=SHA_2)).task
    record = run(record, review_event(record, "codex", Verdict.FAIL, findings=SOME_FINDINGS)).task
    assert record.status is TaskStatus.NEEDS_INTERVENTION
    without_reason = run(record, ev(EventKind.INTERVENTION_APPROVED, sha=record.latest_sha))
    assert without_reason.task.status is TaskStatus.NEEDS_INTERVENTION
    # 一句笼统的话不够：要按意见编号逐条写（F13）
    generic = run(
        record,
        ev(
            EventKind.INTERVENTION_APPROVED,
            sha=record.latest_sha,
            reason="这条意见我不同意，理由如下",
        ),
    )
    assert generic.task.status is TaskStatus.NEEDS_INTERVENTION
    assert "F1" in generic.reason
    with_reason = run(
        record,
        ev(
            EventKind.INTERVENTION_APPROVED,
            sha=record.latest_sha,
            veto_reasons=_veto(record, "F1", "这条我补了测试"),
        ),
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
    decision = run(record, ev(EventKind.YOU_SUBMITTED_CODE, sha=SHA_2, changes=CODE_CHANGES))
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
        record = run(record, ev(EventKind.YOUR_APPROVAL, sha=record.latest_sha)).task
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
    record = run(
        record, review_event(record, "opencode-go", Verdict.FAIL, findings=SOME_FINDINGS)
    ).task
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


# ------------------------------------------------------------------ F2：合并前必须过 CI 这一关


def test_row_12_cannot_merge_after_ci_failure_even_with_new_standard() -> None:
    """R01 之后改审核标准、两家都通过，仍然不能合并：CI 是红的。"""
    record = to_needs_intervention_by_ci()
    assert not record.ci_green
    record = run(record, ev(EventKind.STANDARD_CHANGED, standard_version=2)).task
    assert record.status is TaskStatus.AWAITING_AI_REVIEW
    for reviewer in record.designated_reviewers:
        record = run(record, review_event(record, reviewer)).task

    assert record.status is TaskStatus.AWAITING_AI_REVIEW
    assert not any(action.kind is ActionKind.MERGE for action in record.actions)
    assert "CI" in record.reason


def test_merge_action_is_only_produced_with_green_ci() -> None:
    """所有能产生 MERGE 的路径都走同一个守卫：CI 不绿就不产生合并动作。"""
    # 路径一：AI 审核全过（C 级）
    merging = to_merge_ready()
    assert merging.ci_green
    assert any(action.kind is ActionKind.MERGE for action in merging.actions)

    # 路径二：人工介入后批准（R03，CI 绿）
    record = to_needs_intervention_by_reviewers()
    approved = run(
        record, ev(EventKind.INTERVENTION_APPROVED, sha=record.latest_sha, reason="我看过了")
    ).task
    assert approved.status is TaskStatus.AWAITING_MERGE
    assert any(action.kind is ActionKind.MERGE for action in approved.actions)

    # 路径三：你自己批准（第 17 条）
    record = to_d_ai_review()
    for reviewer in record.designated_reviewers:
        record = run(record, review_event(record, reviewer)).task
    approved = run(record, ev(EventKind.YOUR_APPROVAL, sha=record.latest_sha)).task
    assert approved.status is TaskStatus.AWAITING_MERGE
    assert any(action.kind is ActionKind.MERGE for action in approved.actions)


def test_merge_guard_checks_the_approved_sha_on_the_ai_entry() -> None:
    """最后一个 AI 通过（第 12 条）这条入口也要核对批准的提交编号。"""
    from dataclasses import replace

    record = to_ai_review()
    record = run(record, review_event(record, "codex")).task
    # 记录里还挂着一个针对旧提交的批准
    stale = replace(record, approved_sha=SHA_2)
    decision = run(stale, review_event(stale, "opencode-go"))
    # 事件确实到了"全过→放行"这条分支：结论被记下了，不是被状态拦掉
    assert decision.task.reviews
    assert decision.task.status is TaskStatus.AWAITING_AI_REVIEW
    assert not any(action.kind is ActionKind.MERGE for action in decision.actions)
    assert "批准的提交编号" in decision.reason


def test_merge_guard_checks_the_approved_sha_on_the_human_entry() -> None:
    """人工批准（第 20 条）这条入口也要核对批准的提交编号。"""
    from dataclasses import replace

    record = to_needs_intervention_by_reviewers()
    stale = replace(record, approved_sha=SHA_2)
    decision = run(
        stale, ev(EventKind.INTERVENTION_APPROVED, sha=record.latest_sha, reason="我看过了")
    )
    assert decision.task.status is TaskStatus.NEEDS_INTERVENTION
    assert not decision.changed
    assert "批准的提交编号" in decision.reason


def test_merge_guard_reaches_the_merge_branch_when_everything_is_fine() -> None:
    """正例：同样的入口，批准编号和当前一致时确实产生 MERGE。"""
    record = to_ai_review()
    record = run(record, review_event(record, "codex")).task
    decision = run(record, review_event(record, "opencode-go"))
    assert decision.task.status is TaskStatus.AWAITING_MERGE
    assert actions_of(decision, ActionKind.MERGE)


# ------------------------------------------------- F3：审核者按提供方去重、绑定席位


def test_row_12_same_provider_with_two_names_cannot_fake_two_reviewers() -> None:
    record = to_ai_review()
    record = run(record, review_event(record, "codex")).task
    impostor = review_event(record, "codex-session-2", provider="codex")
    decision = run(record, impostor)
    assert decision.task.status is TaskStatus.AWAITING_AI_REVIEW
    assert not any(action.kind is ActionKind.MERGE for action in decision.actions)
    assert "已经出过结论" in decision.reason


def test_row_12_reviewer_must_hold_a_designated_seat() -> None:
    record = to_ai_review()
    # 没有任何席位邀请过 deepseek
    decision = run(record, review_event(record, "deepseek", provider="deepseek"))
    assert decision.task.status is TaskStatus.AWAITING_AI_REVIEW
    assert decision.task.reviews == ()
    assert "指定的审核者" in decision.reason


def test_row_12_cannot_merge_below_the_minimum_number_of_providers() -> None:
    """就算把席位配错成两家同名，也不能凑够两家就合并。"""
    from dataclasses import replace

    record = to_ai_review()
    tampered = replace(record, designated_reviewers=("codex", "codex"), reviews=())
    decision = run(tampered, review_event(tampered, "codex"))
    assert decision.task.status is TaskStatus.AWAITING_AI_REVIEW
    assert not any(action.kind is ActionKind.MERGE for action in decision.actions)


def test_row_13_d_level_needs_two_distinct_providers_too() -> None:
    record = to_d_ai_review()
    record = run(record, review_event(record, record.designated_reviewers[0])).task
    assert record.status is TaskStatus.AWAITING_AI_REVIEW
    record = run(record, review_event(record, record.designated_reviewers[1])).task
    assert record.status is TaskStatus.AWAITING_YOUR_REVIEW


def test_row_12_review_extension_provider_counts_as_provider() -> None:
    """opencode-go 只是入口，审核结论里记录的真实提供方要参与判断。"""
    record = to_ai_review()
    record = run(record, review_event(record, "codex")).task
    # 席位是 opencode-go，但结论里报的真实提供方是 codex（同一家）
    decision = run(record, review_event(record, "opencode-go", provider="codex"))
    assert decision.task.status is TaskStatus.AWAITING_AI_REVIEW
    assert "已经出过结论" in decision.reason or "指定的审核者" in decision.reason


# ------------------------------------------------- F4：新提交让旧证据作废、放行要核对提交编号


def test_row_05_new_commit_during_ai_review_updates_sha() -> None:
    """审核期间来了新提交：更新提交编号，作废旧结论，回到验收。"""
    record = to_ai_review()
    record = run(record, review_event(record, "codex")).task
    assert record.reviews

    decision = run(
        record,
        ev(EventKind.CODE_SUBMITTED, attempt=record.attempt, sha=SHA_2, changes=CODE_CHANGES),
    )
    assert decision.task.status is TaskStatus.AWAITING_ACCEPTANCE
    assert decision.task.latest_sha == SHA_2
    assert decision.task.reviews == ()
    assert decision.task.approved_sha is None
    assert not decision.task.ci_green


def test_row_05_new_commit_during_acceptance_restarts_ci() -> None:
    record = to_acceptance(to_working(new_task()))
    decision = run(
        record,
        ev(EventKind.CODE_SUBMITTED, attempt=record.attempt, sha=SHA_2, changes=CODE_CHANGES),
    )
    assert decision.task.status is TaskStatus.AWAITING_ACCEPTANCE
    assert decision.task.latest_sha == SHA_2


def test_row_05_new_commit_during_your_review_voids_approval() -> None:
    record = to_d_ai_review()
    for reviewer in record.designated_reviewers:
        record = run(record, review_event(record, reviewer)).task
    assert record.status is TaskStatus.AWAITING_YOUR_REVIEW

    decision = run(
        record,
        ev(EventKind.CODE_SUBMITTED, attempt=record.attempt, sha=SHA_2, changes=CORE_CHANGES),
    )
    assert decision.task.status is TaskStatus.AWAITING_ACCEPTANCE
    assert decision.task.reviews == ()
    assert decision.task.level is Level.D


def test_row_05_new_d_level_commit_goes_back_to_plan_approval() -> None:
    record = to_ai_review()  # C 级，方案没批准过
    decision = run(
        record,
        ev(EventKind.CODE_SUBMITTED, attempt=record.attempt, sha=SHA_2, changes=CORE_CHANGES),
    )
    assert decision.task.status is TaskStatus.AWAITING_PLAN_APPROVAL
    assert decision.task.level is Level.D
    assert decision.task.plan_version == 1


def test_row_05_new_commit_after_merge_started_is_ignored() -> None:
    record = to_merge_ready()
    assert any(action.kind is ActionKind.MERGE for action in record.actions)
    decision = run(
        record,
        ev(EventKind.CODE_SUBMITTED, attempt=record.attempt, sha=SHA_2, changes=CODE_CHANGES),
    )
    assert decision.task.status is TaskStatus.AWAITING_MERGE
    assert not decision.changed
    assert "合并已经开始" in decision.reason


def test_row_05_stale_attempt_during_review_is_ignored() -> None:
    record = to_ai_review()
    decision = run(
        record,
        ev(EventKind.CODE_SUBMITTED, attempt=0, sha=SHA_2, changes=CODE_CHANGES),
    )
    assert decision.task.status is TaskStatus.AWAITING_AI_REVIEW
    assert not decision.changed


def test_row_05_new_commit_without_changes_is_ignored() -> None:
    record = to_ai_review()
    decision = run(record, ev(EventKind.CODE_SUBMITTED, attempt=record.attempt, sha=SHA_2))
    assert decision.task.status is TaskStatus.AWAITING_AI_REVIEW
    assert "无效" in decision.reason


def test_row_17_your_approval_requires_the_sha_you_saw() -> None:
    record = to_d_ai_review()
    for reviewer in record.designated_reviewers:
        record = run(record, review_event(record, reviewer)).task
    missing = run(record, ev(EventKind.YOUR_APPROVAL))
    assert missing.task.status is TaskStatus.AWAITING_YOUR_REVIEW
    assert "提交编号" in missing.reason
    wrong = run(record, ev(EventKind.YOUR_APPROVAL, sha=SHA_2))
    assert wrong.task.status is TaskStatus.AWAITING_YOUR_REVIEW
    matched = run(record, ev(EventKind.YOUR_APPROVAL, sha=record.latest_sha))
    assert matched.task.status is TaskStatus.AWAITING_MERGE


def test_row_19_merge_success_requires_the_sha() -> None:
    record = to_merge_ready()
    missing = run(record, ev(EventKind.MERGED))
    assert missing.task.status is TaskStatus.AWAITING_MERGE
    assert "提交编号" in missing.reason
    matched = run(record, ev(EventKind.MERGED, sha=record.latest_sha))
    assert matched.task.status is TaskStatus.MERGED


def test_row_10_ci_red_requires_the_current_sha() -> None:
    record = to_acceptance(to_working(new_task()))
    decision = run(record, ev(EventKind.CI_RED, sha=SHA_2, reason="旧提交红了"))
    assert decision.task.status is TaskStatus.AWAITING_ACCEPTANCE
    assert decision.task.accept_failures == 0


def test_row_20_intervention_approval_requires_the_current_sha() -> None:
    record = to_needs_intervention_by_reviewers()
    decision = run(record, ev(EventKind.INTERVENTION_APPROVED, sha=SHA_2, reason="我看过了"))
    assert decision.task.status is TaskStatus.NEEDS_INTERVENTION
    assert not decision.changed


# ------------------------------------------------- F5：人工提交也要重算等级、记录参与的 AI


def _to_you_working() -> TaskRecord:
    return run(to_needs_intervention_by_ci(), ev(EventKind.TAKE_OVER)).task


def test_row_24_your_commit_is_re_leveled_by_real_changes() -> None:
    record = _to_you_working()
    assert record.status is TaskStatus.YOU_WORKING
    # 你自己改了 core：等级必须重算成 D，方案还没批准 → 先回到方案批准
    decision = run(record, ev(EventKind.YOU_SUBMITTED_CODE, sha=SHA_2, changes=CORE_CHANGES))
    assert decision.task.level is Level.D
    assert decision.task.status is TaskStatus.AWAITING_PLAN_APPROVAL
    assert decision.task.latest_sha == SHA_2
    assert decision.task.plan_version == 1


def test_row_24_your_commit_with_code_changes_goes_to_acceptance() -> None:
    record = _to_you_working()
    decision = run(record, ev(EventKind.YOU_SUBMITTED_CODE, sha=SHA_2, changes=CODE_CHANGES))
    assert decision.task.status is TaskStatus.AWAITING_ACCEPTANCE
    assert decision.task.level is Level.C
    assert decision.task.writer_is_human
    assert decision.task.reviews == ()
    assert not decision.task.ci_green


def test_row_24_records_participating_providers() -> None:
    record = _to_you_working()
    decision = run(
        record,
        ev(
            EventKind.YOU_SUBMITTED_CODE,
            sha=SHA_2,
            changes=CODE_CHANGES,
            providers=("codex", "opencode-go"),
        ),
    )
    assert {"claude", "codex", "opencode-go"} <= decision.task.providers_involved
    assert "codex" in decision.task.note


def test_row_24_helpers_cannot_review_later() -> None:
    """帮忙写过的提供方不能当审核者：帮过忙的 codex 会被排除。"""
    record = _to_you_working()
    record = run(
        record,
        ev(
            EventKind.YOU_SUBMITTED_CODE,
            sha=SHA_2,
            changes=CODE_CHANGES,
            providers=("codex",),
        ),
    ).task
    record = run(record, ev(EventKind.CI_GREEN, sha=SHA_2)).task
    assert record.status is TaskStatus.NEEDS_INTERVENTION  # 只剩 opencode-go，凑不齐两家
    assert record.error_code == "R03"


def test_row_24_requires_real_changes() -> None:
    record = _to_you_working()
    decision = run(record, ev(EventKind.YOU_SUBMITTED_CODE, sha=SHA_2))
    assert decision.task.status is TaskStatus.YOU_WORKING
    assert "无效" in decision.reason


def test_row_24_requires_sha() -> None:
    record = _to_you_working()
    decision = run(record, ev(EventKind.YOU_SUBMITTED_CODE, changes=CODE_CHANGES))
    assert decision.task.status is TaskStatus.YOU_WORKING


def test_row_03_plan_approval_returns_a_human_writer_to_you_working() -> None:
    """写手是你时，批准方案回到"你处理中"，好让你提交已经写好的代码。"""
    record = _to_you_working()
    record = run(record, ev(EventKind.YOU_SUBMITTED_CODE, sha=SHA_2, changes=CORE_CHANGES)).task
    assert record.status is TaskStatus.AWAITING_PLAN_APPROVAL
    decision = run(record, ev(EventKind.PLAN_APPROVED, sha=record.latest_sha))
    assert decision.task.status is TaskStatus.YOU_WORKING
    assert decision.task.approved_plan_version == record.plan_version


def test_row_16_reviewer_lost_during_review_goes_to_you() -> None:
    """审核途中审核者失效：按当前额度和参与历史重新检查，凑不齐就以 R03 找你。"""
    record = to_ai_review()
    assert record.status is TaskStatus.AWAITING_AI_REVIEW
    record = run(record, review_event(record, "codex")).task
    decision = run(
        record,
        ev(EventKind.QUOTA_EXHAUSTED, provider="codex"),
        quota_=quota(("codex",)),
    )
    assert decision.task.status is TaskStatus.NEEDS_INTERVENTION
    assert decision.task.error_code == "R03"
    # 已经完成的证据要保留
    assert decision.task.reviews


def test_row_16_remaining_reviewers_continue_when_still_enough() -> None:
    """只要还剩够家数，就继续审，把失效的席位剔除。"""
    from dataclasses import replace

    policy_b = policy()
    level_b = Level.B
    record = to_ai_review()
    record = replace(
        record,
        level=level_b,
        designated_reviewers=("codex", "opencode-go"),
    )
    decision = run(
        record,
        ev(EventKind.QUOTA_EXHAUSTED, provider="codex"),
        policy_=policy_b,
        quota_=quota(("codex",)),
    )
    assert decision.task.status is TaskStatus.AWAITING_AI_REVIEW
    assert decision.task.designated_reviewers == ("opencode-go",)


def test_row_16_reviewer_lost_marks_quota_exhausted_action() -> None:
    from dataclasses import replace

    record = replace(to_ai_review(), level=Level.B)  # B 级只要 1 家，少一家还能继续
    decision = run(record, ev(EventKind.QUOTA_EXHAUSTED, provider="opencode-go"))
    exhausted = actions_of(decision, ActionKind.SET_QUOTA_EXHAUSTED)
    assert exhausted and exhausted[0].provider == "opencode-go"
    assert decision.task.status is TaskStatus.AWAITING_AI_REVIEW
    assert decision.task.designated_reviewers == ("codex",)


def test_row_00_creation_event_does_not_change_anything() -> None:
    """任务创建事件只给日志用，内核不改状态。"""
    record = new_task()
    decision = run(record, ev(EventKind.CREATED))
    assert not decision.changed
    assert "创建" in decision.reason


# ------------------------------------------------- F12：异常之后要真的重新开始工作


def test_row_26_retry_after_working_returns_to_pending() -> None:
    """核对结果是"没有动作完成"，而出问题前在处理中 → 回到待处理，等重新派活。"""
    record = to_working(new_task())
    record = run(record, ev(EventKind.INCIDENT, reason="Agent 进程消失", error_code="A02")).task
    assert record.status is TaskStatus.ERROR
    decision = run(record, ev(EventKind.RETRY, check_result=CheckResult.NOT_CONFIRMED))
    assert decision.task.status is TaskStatus.PENDING
    # 派活是由外壳产生 ASSIGN 事件做的，这里只负责回到待处理
    assert actions_of(decision, ActionKind.NOTIFY)


def test_row_26_retry_in_review_reissues_review_requests() -> None:
    """出问题前在待 AI 审核：重试要重新发审核请求，不能原地干等。"""
    record = to_ai_review()
    record = run(record, review_event(record, "codex")).task  # 已经有一家审过
    record = run(record, ev(EventKind.INCIDENT, reason="审核进程崩了", error_code="E03")).task
    decision = run(record, ev(EventKind.RETRY, check_result=CheckResult.NOT_CONFIRMED))
    assert decision.task.status is TaskStatus.AWAITING_AI_REVIEW
    requested = [action.provider for action in actions_of(decision, ActionKind.REQUEST_REVIEW)]
    # codex 已经有结论，只补发还没审的那一家
    assert requested == ["opencode-go"]


def test_row_26_retry_after_acceptance_goes_back_to_acceptance() -> None:
    record = to_acceptance(to_working(new_task()))
    record = run(record, ev(EventKind.INCIDENT, reason="CI 服务断了")).task
    decision = run(record, ev(EventKind.RETRY, check_result=CheckResult.NOT_CONFIRMED))
    assert decision.task.status is TaskStatus.AWAITING_ACCEPTANCE


# ------------------------------------------------- F13：反对意见要留内容，会审要逐条答


def _veto(record: TaskRecord, local_id: str, reason: str) -> tuple[VetoReason, ...]:
    """按本地编号找到复合键，写一条否决理由。"""
    key = next(finding.key for finding in record.open_findings if finding.local_id == local_id)
    return (VetoReason(finding_id=key, reason=reason),)


def _findings() -> tuple[Finding, ...]:
    return (
        Finding(id="F1", text="异常分支没有测试"),
        Finding(id="F2", text="这里的时间没从参数传进来"),
    )


def _to_you_deciding_with_findings() -> TaskRecord:
    """你自己写的代码被 AI 打回（14b），停在"待你介入"，带着两条反对意见。"""
    record = run(to_needs_intervention_by_ci(), ev(EventKind.TAKE_OVER)).task
    record = run(record, ev(EventKind.YOU_SUBMITTED_CODE, sha=SHA_2, changes=CODE_CHANGES)).task
    record = run(record, ev(EventKind.CI_GREEN, sha=SHA_2)).task
    return run(record, review_event(record, "codex", Verdict.FAIL, findings=_findings())).task


def test_row_14_returning_for_fix_keeps_the_findings() -> None:
    """退回修改只清"通过资格"，不能把要回应的问题一起删掉。"""
    record = to_ai_review()
    decision = run(record, review_event(record, "codex", Verdict.FAIL, findings=_findings()))
    assert decision.task.status is TaskStatus.PENDING
    assert decision.task.reviews == ()  # 这一轮的通过资格作废
    assert len(decision.task.review_history) == 1  # 历史意见留着
    assert [finding.local_id for finding in decision.task.open_findings] == ["F1", "F2"]
    assert decision.task.review_history[0].findings[0].text == "异常分支没有测试"


def test_row_20_veto_needs_a_reason_for_every_finding() -> None:
    record = _to_you_deciding_with_findings()
    assert record.status is TaskStatus.NEEDS_INTERVENTION
    assert [finding.local_id for finding in record.open_findings] == ["F1", "F2"]

    # 一条理由都不给 → 拒绝
    without = run(record, ev(EventKind.INTERVENTION_APPROVED, sha=SHA_2, reason="我觉得可以"))
    assert without.task.status is TaskStatus.NEEDS_INTERVENTION
    # 只答一条 → 也拒绝，并指出还缺哪一条
    partial = run(
        record,
        ev(
            EventKind.INTERVENTION_APPROVED,
            sha=SHA_2,
            veto_reasons=_veto(record, "F1", "这条我补测试了"),
        ),
    )
    assert partial.task.status is TaskStatus.NEEDS_INTERVENTION
    assert "F2" in partial.reason

    complete = run(
        record,
        ev(
            EventKind.INTERVENTION_APPROVED,
            sha=SHA_2,
            veto_reasons=(
                *_veto(record, "F1", "这条我补测试了"),
                *_veto(record, "F2", "时间是从参数传的"),
            ),
        ),
    )
    assert complete.task.status is TaskStatus.AWAITING_MERGE


def test_row_20_veto_after_refusing_to_fix_still_needs_reasons() -> None:
    """退回修改 → 写手拒绝修改 → 待你介入：批准时同样要逐条答。"""
    record = to_ai_review()
    record = run(record, review_event(record, "codex", Verdict.FAIL, findings=_findings())).task
    record = to_working(record)
    record = run(record, ev(EventKind.REFUSED_TO_FIX, reason="标准不对")).task
    assert record.status is TaskStatus.NEEDS_INTERVENTION
    decision = run(record, ev(EventKind.INTERVENTION_APPROVED, sha=record.latest_sha))
    assert decision.task.status is TaskStatus.NEEDS_INTERVENTION
    assert "F1" in decision.reason and "F2" in decision.reason


def test_row_13_passing_reviews_clear_open_findings() -> None:
    record = to_ai_review()
    record = run(record, review_event(record, "codex", Verdict.FAIL, findings=_findings())).task
    record = to_working(record)
    record = to_acceptance(record, sha=SHA_2)
    record = run(record, ev(EventKind.CI_GREEN, sha=SHA_2)).task
    for reviewer in record.designated_reviewers:
        record = run(record, review_event(record, reviewer)).task
    assert record.status is TaskStatus.AWAITING_MERGE
    assert record.open_findings == ()
    # 历史意见不会被删掉
    assert record.review_history


# ------------------------------------------------- H7：新提交要作废旧审核席位


def test_row_05_new_commit_clears_old_reviewer_seats() -> None:
    """新提交让旧的审核席位一起作废，不能拿过期席位挡住后面的人工批准。"""
    record = to_ai_review()
    assert record.designated_reviewers == ("codex", "opencode-go")
    record = run(record, review_event(record, "codex", Verdict.FAIL, findings=_findings())).task
    record = to_working(record)
    record = run(record, ev(EventKind.REFUSED_TO_FIX, reason="标准不对")).task
    record = run(record, ev(EventKind.TAKE_OVER)).task
    decision = run(
        record,
        ev(
            EventKind.YOU_SUBMITTED_CODE,
            sha=SHA_2,
            changes=CODE_CHANGES,
            providers=("codex",),
        ),
    )
    assert decision.task.designated_reviewers == ()


def test_row_16_records_the_seats_that_actually_exist() -> None:
    """凑不齐审核者进入 R03 时，记录里留下的是当前真实存在的席位。"""
    walker = Walker(new_task())
    walker.assign("claude")
    walker.submit_code()
    walker.quota = quota(("codex",))  # codex 用完，只剩 opencode-go
    decision = walker.ci_green()
    assert decision.task.status is TaskStatus.NEEDS_INTERVENTION
    assert decision.task.error_code == "R03"
    assert decision.task.designated_reviewers == ("opencode-go",)


def test_row_20_human_approval_survives_stale_seats() -> None:
    """人工接手后声明帮过忙的提供方：旧席位不能永久挡住 R03 下的人工批准。"""
    record = to_ai_review()
    record = run(record, review_event(record, "codex", Verdict.FAIL, findings=_findings())).task
    record = to_working(record)
    record = run(record, ev(EventKind.REFUSED_TO_FIX, reason="标准不对")).task
    assert record.status is TaskStatus.NEEDS_INTERVENTION
    record = run(record, ev(EventKind.TAKE_OVER)).task
    record = run(
        record,
        ev(
            EventKind.YOU_SUBMITTED_CODE,
            sha=SHA_2,
            changes=CODE_CHANGES,
            providers=("codex",),
        ),
    ).task
    record = run(record, ev(EventKind.CI_GREEN, sha=SHA_2)).task
    assert record.status is TaskStatus.NEEDS_INTERVENTION
    assert record.error_code == "R03"
    assert "codex" not in record.designated_reviewers

    decision = run(
        record,
        ev(
            EventKind.INTERVENTION_APPROVED,
            sha=SHA_2,
            veto_reasons=(
                *_veto(record, "F1", "这条我补了测试"),
                *_veto(record, "F2", "时间从参数传"),
            ),
        ),
    )
    assert decision.task.status is TaskStatus.AWAITING_MERGE
    assert actions_of(decision, ActionKind.MERGE)


def test_merge_guard_still_rejects_writer_votes_on_the_ai_entry() -> None:
    """凭 AI 证据放行时，席位里不能有写过这次代码的人（这条不因为人工入口而放松）。"""
    from dataclasses import replace

    record = to_ai_review()
    tampered = replace(record, designated_reviewers=("codex", "claude"))
    tampered = replace(tampered, reviews=())
    for reviewer, provider in (("codex", "codex"), ("claude", "claude")):
        decision = run(
            tampered,
            ev(
                EventKind.REVIEW,
                review=Review(
                    reviewer=reviewer,
                    provider=provider,
                    verdict=Verdict.PASS,
                    sha=tampered.latest_sha or SHA_1,
                    standard_version=tampered.standard_version,
                ),
            ),
        )
        tampered = decision.task
    assert tampered.status is TaskStatus.AWAITING_AI_REVIEW
    assert not any(action.kind is ActionKind.MERGE for action in tampered.actions)


# ------------------------------------------------- H4：不通过必须有具体意见


def test_row_14_fail_without_findings_is_rejected() -> None:
    """不通过的结论必须带至少一条有编号、有正文的意见，否则拒收。"""
    record = to_ai_review()
    decision = run(record, review_event(record, "codex", Verdict.FAIL))
    assert decision.task.status is TaskStatus.AWAITING_AI_REVIEW
    assert not decision.changed
    assert decision.task.reviews == ()
    assert "意见" in decision.reason


def test_row_14_fail_with_blank_finding_is_rejected() -> None:
    record = to_ai_review()
    decision = run(
        record,
        review_event(
            record,
            "codex",
            Verdict.FAIL,
            findings=(Finding(id="F1", text="   "),),
        ),
    )
    assert not decision.changed
    assert decision.task.reviews == ()
    unnamed = run(
        record,
        review_event(record, "codex", Verdict.FAIL, findings=(Finding(id=" ", text="没问题"),)),
    )
    assert not unnamed.changed


def test_row_20_legacy_fail_without_findings_cannot_be_approved_silently() -> None:
    """旧记录里那种"没有具体意见的 FAIL"不能被当成没有反对意见。"""
    from dataclasses import replace

    record = to_needs_intervention_by_reviewers()
    legacy = replace(
        record,
        review_history=(
            Review(
                reviewer="codex",
                provider="codex",
                verdict=Verdict.FAIL,
                sha=record.latest_sha or SHA_1,
                standard_version=record.standard_version,
            ),
        ),
    )
    silent = run(legacy, ev(EventKind.INTERVENTION_APPROVED, sha=legacy.latest_sha))
    assert silent.task.status is TaskStatus.NEEDS_INTERVENTION
    assert not silent.changed
    explained = run(
        legacy,
        ev(
            EventKind.INTERVENTION_APPROVED,
            sha=legacy.latest_sha,
            reason="这条意见我不同意，理由是……",
        ),
    )
    assert explained.task.status is TaskStatus.AWAITING_MERGE


# ------------------------------------------------- H5：意见要带来源，不能靠裸编号互相覆盖


def _two_rounds_same_local_id() -> TaskRecord:
    """第一轮 codex 提 F1，新提交后第二轮 opencode-go 也提 F1（正文不同）。"""
    record = to_ai_review()
    record = run(
        record,
        review_event(record, "codex", Verdict.FAIL, findings=(Finding(id="F1", text="旧意见"),)),
    ).task
    record = to_working(record)
    record = to_acceptance(record, sha=SHA_2)
    record = run(record, ev(EventKind.CI_GREEN, sha=SHA_2)).task
    record = run(
        record,
        review_event(
            record, "opencode-go", Verdict.FAIL, findings=(Finding(id="F1", text="新意见"),)
        ),
    ).task
    record = to_working(record)
    return run(record, ev(EventKind.REFUSED_TO_FIX, reason="标准不对")).task


def test_row_20_same_local_id_from_another_round_is_not_swallowed() -> None:
    record = _two_rounds_same_local_id()
    assert record.status is TaskStatus.NEEDS_INTERVENTION
    texts = {finding.text for finding in record.open_findings}
    assert texts == {"旧意见", "新意见"}
    keys = [finding.key for finding in record.open_findings]
    assert len(set(keys)) == 2  # 复合键：提供方 + 提交编号 + 标准版本 + 本地编号


def test_row_20_veto_answers_are_per_composite_key() -> None:
    record = _two_rounds_same_local_id()
    old_key, new_key = (finding.key for finding in record.open_findings)
    partial = run(
        record,
        ev(
            EventKind.INTERVENTION_APPROVED,
            sha=record.latest_sha,
            veto_reasons=(VetoReason(finding_id=old_key, reason="旧的那条已改"),),
        ),
    )
    assert partial.task.status is TaskStatus.NEEDS_INTERVENTION
    assert new_key in partial.reason

    complete = run(
        record,
        ev(
            EventKind.INTERVENTION_APPROVED,
            sha=record.latest_sha,
            veto_reasons=(
                VetoReason(finding_id=old_key, reason="旧的那条已改"),
                VetoReason(finding_id=new_key, reason="新的那条我不同意"),
            ),
        ),
    )
    assert complete.task.status is TaskStatus.AWAITING_MERGE


# ------------------------------------------------- H5 复核：键里必须用完整提交编号

# 两个不同的提交，前 8 位相同：拿前缀当身份就会把它们混成一条
SHA_PREFIX_SAME_A = "abcdef12" + "1" * 32
SHA_PREFIX_SAME_B = "abcdef12" + "2" * 32


def _two_rounds_same_prefix_different_sha() -> TaskRecord:
    """同一提供方、同标准、同本地编号 F1，针对两个前 8 位相同的提交各给一条意见。"""
    walker = Walker(new_task())
    walker.assign("claude")
    walker.submit_code(sha=SHA_PREFIX_SAME_A)
    walker.ci_green()
    walker.review("codex", Verdict.FAIL, (Finding(id="F1", text="旧提交的问题"),))
    walker.assign("claude")
    walker.submit_code(sha=SHA_PREFIX_SAME_B)
    walker.ci_green()
    walker.review("codex", Verdict.FAIL, (Finding(id="F1", text="新提交的问题"),))
    walker.assign("claude")
    return walker.step(ev(EventKind.REFUSED_TO_FIX, reason="标准不对")).task


def test_row_20_same_sha_prefix_does_not_swallow_the_newer_finding() -> None:
    """前 8 位相同但完整提交编号不同：两条意见都要保留，不能只留一条。"""
    record = _two_rounds_same_prefix_different_sha()
    assert record.status is TaskStatus.NEEDS_INTERVENTION
    texts = {finding.text for finding in record.open_findings}
    assert texts == {"旧提交的问题", "新提交的问题"}
    keys = [finding.key for finding in record.open_findings]
    assert len(set(keys)) == 2
    # 展示用的短键会撞车，所以完整键里不能只有前缀
    assert {finding.sha for finding in record.open_findings} == {
        SHA_PREFIX_SAME_A,
        SHA_PREFIX_SAME_B,
    }
    assert len({finding.short_key for finding in record.open_findings}) == 1  # 缩写确实相同
    # 展示时用短键列出来，存储和否决用的是完整键
    assert "codex:F1@abcdef12:v1" in record.note
    assert "旧提交的问题" in record.note and "新提交的问题" in record.note


def test_row_20_same_sha_prefix_findings_must_be_answered_separately() -> None:
    record = _two_rounds_same_prefix_different_sha()
    first, second = record.open_findings

    only_first = run(
        record,
        ev(
            EventKind.INTERVENTION_APPROVED,
            sha=record.latest_sha,
            veto_reasons=(VetoReason(finding_id=first.key, reason="这条我改了"),),
        ),
    )
    assert only_first.task.status is TaskStatus.NEEDS_INTERVENTION
    assert second.key in only_first.reason  # 还缺的那一条要按完整键指出来

    both = run(
        record,
        ev(
            EventKind.INTERVENTION_APPROVED,
            sha=record.latest_sha,
            veto_reasons=(
                VetoReason(finding_id=first.key, reason="这条我改了"),
                VetoReason(finding_id=second.key, reason="这条我不同意"),
            ),
        ),
    )
    assert both.task.status is TaskStatus.AWAITING_MERGE


# ------------------------------------------------- 提交编号一变，旧证据必须全部作废

SHA_OLD = "a1" + "0" * 38
SHA_NEW = "b2" + "0" * 38


def test_row_02_new_plan_with_a_new_sha_clears_stale_ci_and_seats() -> None:
    """D 级退回修改后重新交方案（新提交编号）：CI 绿、审核席位、批准都要作废。

    复现：ASSIGN → PLAN_SUBMITTED → PLAN_APPROVED → ASSIGN → CODE_SUBMITTED →
    CI_GREEN → 审核 FAIL → ASSIGN → PLAN_SUBMITTED(新 sha)。
    此时 latest_sha 换了，ci_green 仍然留着旧提交的 True。
    """
    walker = Walker(new_task(Level.D))
    walker.assign("claude")
    walker.step(ev(EventKind.PLAN_SUBMITTED, sha="plan-a", plan="第一版方案"))
    walker.step(ev(EventKind.PLAN_APPROVED, sha="plan-a"))
    walker.assign("claude")
    walker.submit_code(sha=SHA_OLD, changes=CORE_CHANGES)
    walker.ci_green()
    walker.review("codex", Verdict.FAIL, (Finding(id="F1", text="这里有问题"),))
    walker.assign("claude")

    assert walker.record.ci_green is True  # 上一轮的 CI 结论
    assert walker.record.designated_reviewers == ("codex", "opencode-go")

    walker.step(ev(EventKind.PLAN_SUBMITTED, sha=SHA_NEW, plan="第二版方案"))

    assert walker.record.status is TaskStatus.AWAITING_PLAN_APPROVAL
    assert walker.record.latest_sha == SHA_NEW
    assert walker.record.ci_green is False
    assert walker.record.reviews == ()
    assert walker.record.approved_sha is None
    assert walker.record.designated_reviewers == ()


def test_any_transition_that_changes_the_sha_drops_stale_evidence() -> None:
    """凡是换提交编号的转移，都不能把旧提交的 CI/批准/席位带进新提交。

    第 24 条（你提交代码）也走同一条规则：R03 之后你接手，CI 还是绿的，
    你换了一个新提交编号提交，旧的 CI 绿色不能跟过来。
    """
    record = to_needs_intervention_by_reviewers()  # R03，ci_green=True
    record = run(record, ev(EventKind.TAKE_OVER)).task
    assert record.status is TaskStatus.YOU_WORKING
    assert record.ci_green is True

    decision = run(
        record,
        ev(EventKind.YOU_SUBMITTED_CODE, sha=SHA_NEW, changes=CODE_CHANGES),
    )
    assert decision.task.latest_sha == SHA_NEW
    assert decision.task.ci_green is False
    assert decision.task.approved_sha is None
    assert decision.task.reviews == ()
    assert decision.task.designated_reviewers == ()


# ------------------------------------------------- 5b 的方案要有内容，并绑定这次提交

SHA_5B = "c3" + "0" * 38


def _escalated_to_d_by_real_changes() -> TaskRecord:
    """C 级任务实际改了 core：第 5b 条重新分级成 D，进"待你批准方案"。"""
    record = to_working(new_task(Level.C))
    return run(
        record,
        ev(EventKind.CODE_SUBMITTED, attempt=record.attempt, sha=SHA_5B, changes=CORE_CHANGES),
    ).task


def test_row_05b_plan_records_what_you_are_approving() -> None:
    """5b 没有文字方案：任务记录里要写清"内容就是这次提交的改动"，并带上底线原因。"""
    record = _escalated_to_d_by_real_changes()
    assert record.status is TaskStatus.AWAITING_PLAN_APPROVAL
    assert record.plan_version == 1

    entry = record.plan()
    assert entry is not None
    assert entry.version == 1
    assert entry.sha == SHA_5B  # 方案绑定这次交回的提交编号
    assert record.plan_text == entry.text
    assert "第 1 版方案" in entry.text
    assert "没有文字方案" in entry.text
    assert SHA_5B in entry.text
    # 底线原因要说清是哪个文件、哪一条
    assert "src/tandem/core/model.py" in entry.text
    assert "底线" in entry.text


def test_row_03_plan_approval_must_bind_the_plan_sha() -> None:
    """5b 场景下批准方案也要带提交编号，且必须和这版方案绑定的一致。"""
    record = _escalated_to_d_by_real_changes()

    missing = run(record, ev(EventKind.PLAN_APPROVED))
    assert missing.task.status is TaskStatus.AWAITING_PLAN_APPROVAL
    assert "提交编号" in missing.reason

    wrong = run(record, ev(EventKind.PLAN_APPROVED, sha=SHA_2))
    assert wrong.task.status is TaskStatus.AWAITING_PLAN_APPROVAL
    assert not wrong.changed

    matched = run(record, ev(EventKind.PLAN_APPROVED, sha=SHA_5B))
    assert matched.task.status is TaskStatus.PENDING
    assert matched.task.approved_plan_version == 1


def test_row_02_submitted_plan_text_survives_later_transitions() -> None:
    """PLAN_SUBMITTED 的正文要存进任务记录，之后不再被 note 覆盖。"""
    record = to_working(new_task(Level.D))
    record = run(
        record,
        ev(EventKind.PLAN_SUBMITTED, sha="plan-a", plan="先加纯函数，再接外壳"),
    ).task
    assert record.plan_text == "先加纯函数，再接外壳"

    record = run(record, ev(EventKind.PLAN_APPROVED, sha="plan-a")).task
    record = to_working(record)
    record = to_acceptance(record, sha=SHA_1, changes=CORE_CHANGES)
    # note 会被后面的转换改掉，方案正文不能跟着没
    assert record.plan_text == "先加纯函数，再接外壳"
    assert record.plan_version == 1
    assert record.approved_plan_version == 1


def test_row_26_retry_reissues_a_new_merge_action() -> None:
    """核对结果是"没有动作完成"，出问题前在待合并：重新发一个合并动作（新编号）。"""
    record = to_error_before_merge()
    assert record.status is TaskStatus.ERROR
    assert record.status_before_error is TaskStatus.AWAITING_MERGE
    old_merge_ids = {
        action.action_id for action in record.actions if action.kind is ActionKind.MERGE
    }

    decision = run(
        record,
        ev(EventKind.RETRY, check_result=CheckResult.NOT_CONFIRMED, sha=record.latest_sha),
    )
    assert decision.task.status is TaskStatus.AWAITING_MERGE
    issued = actions_of(decision, ActionKind.MERGE)
    assert len(issued) == 1
    assert issued[0].action_id not in old_merge_ids  # 新动作编号，不会和上一次撞
    assert decision.task.approved_sha == decision.task.latest_sha
    assert decision.task.status_before_error is None


def test_row_26_retry_does_not_reissue_merge_without_a_current_approval() -> None:
    """重新合并仍要过合并守卫：批准的不是当前提交，就不发合并动作，只说明原因。"""
    from dataclasses import replace

    record = to_error_before_merge()
    stale = replace(record, approved_sha=SHA_2)
    decision = run(stale, ev(EventKind.RETRY, check_result=CheckResult.NOT_CONFIRMED))
    assert decision.task.status is TaskStatus.AWAITING_MERGE
    assert not actions_of(decision, ActionKind.MERGE)
    assert "批准的提交编号" in decision.reason


def test_row_26_retry_does_not_reissue_merge_when_ci_is_red() -> None:
    from dataclasses import replace

    record = to_error_before_merge()
    red = replace(record, ci_green=False)
    decision = run(red, ev(EventKind.RETRY, check_result=CheckResult.NOT_CONFIRMED))
    assert not actions_of(decision, ActionKind.MERGE)
    assert "CI" in decision.reason
