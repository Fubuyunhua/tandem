"""GitHub 适配器离线测试。"""

import pytest

from tandem.shell.github import CIState, FakeGitHub, GitHubError, Issue, PullRequest

SHA = "a" * 40


def test_filter_issues() -> None:
    github = FakeGitHub(
        issues=(Issue(1, labels=("agent",)), Issue(2), Issue(3, labels=("agent",), state="closed"))
    )
    assert [issue.number for issue in github.list_issues()] == [1]


def test_writes_require_live_and_matching_sha() -> None:
    github = FakeGitHub(prs={1: PullRequest(1, SHA)}, checks={SHA: CIState.GREEN})
    with pytest.raises(GitHubError, match="SHA"):
        github.merge_pr(1, "b" * 40, live=True)
    assert not github.merge_pr(1, SHA)
    assert not github.close_pr(1)
    assert not github.comment(1, "$(untrusted) --body token")
    assert github.writes == []
    assert github.merge_pr(1, SHA, live=True)
    assert github.prs[1].merged
    assert github.writes[0][1]["sha"] == SHA


@pytest.mark.parametrize("state", [CIState.PENDING, CIState.RED])
def test_merge_requires_green(state: CIState) -> None:
    github = FakeGitHub(prs={1: PullRequest(1, SHA)}, checks={SHA: state})
    with pytest.raises(GitHubError, match="CI"):
        github.merge_pr(1, SHA, live=True)
    assert github.writes == []


def test_close_and_comment() -> None:
    github = FakeGitHub(prs={1: PullRequest(1, SHA)})
    assert github.close_pr(1, live=True)
    assert github.comment(1, "原样传递的不可信正文", live=True)
    assert github.prs[1].state == "closed"
    assert len(github.writes) == 2


def test_failure_is_not_success() -> None:
    github = FakeGitHub(fail=True)
    with pytest.raises(GitHubError):
        github.close_pr(1, live=True)
    assert github.writes == []
