"""红队回归：证据必须绑定不可变提交，红灯不能被旧绿灯覆盖。"""

from dataclasses import replace

import pytest

from tandem.core.model import (
    Action,
    ActionKind,
    ActionStatus,
    CheckResult,
    EventKind,
    RunMode,
    TaskStatus,
)
from tests.core.helpers import CODE_CHANGES, SHA_1, SHA_2, ev, run, to_ai_review


@pytest.mark.parametrize(
    "state",
    [
        TaskStatus.AWAITING_AI_REVIEW,
        TaskStatus.AWAITING_YOUR_REVIEW,
        TaskStatus.AWAITING_MERGE,
        TaskStatus.NEEDS_INTERVENTION,
    ],
)
def test_red_revokes_green_for_same_oid(state: TaskStatus) -> None:
    task = replace(to_ai_review(), status=state, approved_sha=SHA_1)
    result = run(task, ev(EventKind.CI_RED, sha=SHA_1))
    assert result.changed
    assert not result.task.ci_green
    assert result.task.approved_sha is None
    assert result.task.reviews == ()
    assert not any(a.kind is ActionKind.MERGE for a in result.actions)
    approval = run(result.task, ev(EventKind.YOUR_APPROVAL, sha=SHA_1))
    assert not any(a.kind is ActionKind.MERGE for a in approval.actions)
    assert not run(task, ev(EventKind.CI_RED, sha=SHA_2)).changed


@pytest.mark.parametrize("sha", ["candidate", "abc", "g" * 40, "a" * 41, "a" * 63])
def test_invalid_oid_cannot_be_ci_or_approval_evidence(sha: str) -> None:
    task = replace(
        to_ai_review(),
        latest_sha=sha,
        status=TaskStatus.AWAITING_ACCEPTANCE,
        run_mode=RunMode.SINGLE_AGENT,
        ci_green=False,
    )
    assert not run(task, ev(EventKind.CI_GREEN, sha=sha)).changed
    task = replace(task, status=TaskStatus.AWAITING_YOUR_REVIEW, ci_green=True)
    assert not run(task, ev(EventKind.YOUR_APPROVAL, sha=sha)).changed


@pytest.mark.parametrize("kind", [EventKind.PLAN_SUBMITTED, EventKind.PLAN_APPROVED])
@pytest.mark.parametrize("sha", [None, "candidate", "g" * 40])
def test_plan_oid_rejection_has_one_entry_message(kind: EventKind, sha: str | None) -> None:
    result = run(to_ai_review(), ev(kind, sha=sha))
    assert not result.changed
    assert result.reason == "提交编号必须是完整的 40/64 位十六进制 OID"


@pytest.mark.parametrize(
    "state",
    [
        TaskStatus.AWAITING_AI_REVIEW,
        TaskStatus.AWAITING_YOUR_REVIEW,
        TaskStatus.AWAITING_MERGE,
    ],
)
@pytest.mark.parametrize("failures", [0, 2])
def test_red_before_merge_returns_to_reachable_workflow(state: TaskStatus, failures: int) -> None:
    task = replace(to_ai_review(), status=state, approved_sha=SHA_1, accept_failures=failures)
    result = run(task, ev(EventKind.CI_RED, sha=SHA_1))
    expected = TaskStatus.PENDING if failures == 0 else TaskStatus.NEEDS_INTERVENTION
    assert result.task.status is expected
    assert result.task.accept_failures == failures + 1
    assert result.task.approved_sha is None and not result.task.ci_green
    assert result.task.reviews == () and result.task.designated_reviewers == ()
    assert not any(a.kind is ActionKind.MERGE for a in result.actions)
    if expected is TaskStatus.PENDING:
        assigned = run(result.task, ev(EventKind.ASSIGN, provider="claude"))
        assert assigned.task.status is TaskStatus.WORKING
        submitted = run(
            assigned.task,
            ev(
                EventKind.CODE_SUBMITTED,
                attempt=assigned.task.attempt,
                sha=SHA_2,
                changes=CODE_CHANGES,
            ),
        )
        assert submitted.task.status is TaskStatus.AWAITING_ACCEPTANCE
        assert run(submitted.task, ev(EventKind.CI_GREEN, sha=SHA_2)).changed
    else:
        assert result.task.error_code == "R01"
        assert run(result.task, ev(EventKind.TAKE_OVER)).task.status is TaskStatus.YOU_WORKING


@pytest.mark.parametrize("status", [ActionStatus.SENT, ActionStatus.UNKNOWN, ActionStatus.DONE])
def test_red_after_merge_issue_only_revokes_evidence(status: ActionStatus) -> None:
    action = Action("issued", ActionKind.MERGE, "t1", status=status)
    task = replace(
        to_ai_review(), status=TaskStatus.AWAITING_MERGE, approved_sha=SHA_1, actions=(action,)
    )
    red = run(task, ev(EventKind.CI_RED, sha=SHA_1)).task
    assert red.status is TaskStatus.AWAITING_MERGE
    assert red.accept_failures == task.accept_failures
    assert red.approved_sha is None and not red.ci_green
    assert red.reviews == () and red.designated_reviewers == ()
    # 已发出的合并保留，之后通过异常核对确认真实结果。
    assert red.actions[0] == action
    incident = run(red, ev(EventKind.INCIDENT, error_code="G01")).task
    checked = run(incident, ev(EventKind.RETRY, check_result=CheckResult.MERGE_SUCCEEDED))
    assert checked.task.status is TaskStatus.MERGED
