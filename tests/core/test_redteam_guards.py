"""红队回归：证据必须绑定不可变提交，红灯不能被旧绿灯覆盖。"""

from dataclasses import replace

import pytest

from tandem.core.model import ActionKind, EventKind, RunMode, TaskStatus
from tests.core.helpers import SHA_1, SHA_2, ev, run, to_ai_review


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
