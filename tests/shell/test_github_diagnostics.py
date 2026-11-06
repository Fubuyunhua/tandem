"""P3/P4/P9：失败原因可诊断、恢复有提示，所有 GitHub 动作留执行日志。"""

from pathlib import Path

import pytest

from tandem.core.model import Action, ActionKind, ActionStatus, TaskRecord, TaskStatus
from tandem.shell import cli
from tandem.shell.github import CIState, FakeGitHub, GitHubError, PullRequest
from tandem.shell.store import GitHubSource, Store
from tests.shell.shell_helpers import make_runner

SHA = "a" * 40


@pytest.mark.parametrize(
    "failure,expected",
    [
        ("binding", "缺少匹配仓库的 PR 关联"),
        ("missing", "PR 不存在"),
        ("sha", "PR 的 head SHA 与预期不一致，拒绝合并"),
    ],
)
def test_approve_preserves_safe_failure_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
    expected: str,
) -> None:
    db = tmp_path / "failure.sqlite3"
    github = FakeGitHub(
        prs={}
        if failure == "missing"
        else {8: PullRequest(8, "b" * 40 if failure == "sha" else SHA)},
        checks={SHA: CIState.GREEN},
    )
    monkeypatch.setattr(cli, "GhGitHub", lambda _repo, **_kwargs: github)
    with Store(db) as store:
        store.commit(
            task=TaskRecord(
                "gh-7", status=TaskStatus.AWAITING_YOUR_REVIEW, latest_sha=SHA, ci_green=True
            )
        )
        store.save_github_source(
            GitHubSource("gh-7", "owner/repo", 7, "", "", None if failure == "binding" else 8)
        )
    assert cli.main(["approve", "--db", str(db), "--task-id", "gh-7", "--sha", SHA, "--live"]) == 2
    assert expected in capsys.readouterr().out
    with Store(db) as store:
        assert expected in repr(store.list_events("gh-7"))
        task = store.load_task("gh-7")
        assert task is not None and task.error_code == "G01"
    assert github.writes == []


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("kind", [ActionKind.MERGE, ActionKind.CLOSE_PR])
@pytest.mark.parametrize("fail", [False, True])
def test_github_actions_always_append_executor_log(
    tmp_path: Path, dry_run: bool, kind: ActionKind, fail: bool
) -> None:
    runner = make_runner(tmp_path, dry_run=dry_run)
    try:
        runner.store.save_github_source(GitHubSource("gh-7", "owner/repo", 7, "", "", 8))
        runner.executor.github = FakeGitHub(
            prs={8: PullRequest(8, SHA)}, checks={SHA: CIState.GREEN}, fail=fail
        )
        runner.executor.github_repo = "owner/repo"
        action = Action("audit-action-7", kind, "gh-7")
        task = TaskRecord("gh-7", approved_sha=SHA, latest_sha=SHA, ci_green=True)
        outcome = runner.executor.execute(action, task)
        assert len(runner.executor.log) == 1
        entry = runner.executor.log[0]
        assert ("[dry-run]" if dry_run else "[live]") in entry
        assert "audit-action-7" in entry and "gh-7" in entry
        assert kind.value in entry and outcome.message in entry
    finally:
        runner.store.close()


def test_unknown_github_error_does_not_leak_into_message_or_log(tmp_path: Path) -> None:
    class UnsafeBackend(FakeGitHub):
        def get_pr(self, number: int) -> PullRequest:
            raise GitHubError("secret-token\nBearer ghp_private_value")

    runner = make_runner(tmp_path, dry_run=False)
    try:
        runner.store.save_github_source(GitHubSource("gh-7", "owner/repo", 7, "", "", 8))
        runner.executor.github = UnsafeBackend()
        runner.executor.github_repo = "owner/repo"
        result = runner.executor.execute(
            Action("close-7", ActionKind.CLOSE_PR, "gh-7"), TaskRecord("gh-7")
        )
        assert result.status is ActionStatus.UNKNOWN
        assert "详情已隐藏" in result.message
        assert "secret-token" not in result.message + repr(runner.executor.log)
        assert "ghp_private_value" not in result.message + repr(runner.executor.log)
    finally:
        runner.store.close()


def test_not_confirmed_prints_next_step_without_retrying_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "reconcile.sqlite3"
    github = FakeGitHub(prs={8: PullRequest(8, SHA)})
    monkeypatch.setattr(cli, "GhGitHub", lambda _repo, **_kwargs: github)
    action = Action("merge-7", ActionKind.MERGE, "gh-7", status=ActionStatus.UNKNOWN)
    with Store(db) as store:
        store.commit(
            task=TaskRecord(
                "gh-7",
                status=TaskStatus.ERROR,
                status_before_error=TaskStatus.AWAITING_MERGE,
                latest_sha=SHA,
                approved_sha=SHA,
                pr_opened=True,
                actions=(action,),
            ),
            actions=(action,),
        )
        store.save_github_source(GitHubSource("gh-7", "owner/repo", 7, "", "", 8))
    assert cli.main(["reconcile", "gh-7", "--db", str(db), "--repo", "owner/repo"]) == 0
    output = capsys.readouterr().out
    assert "下一步" in output and "手工核对" in output
    assert "MERGE" in output and "tandem cancel" in output
    assert github.writes == []
    with Store(db) as store:
        assert store.list_actions("gh-7")[0].status is ActionStatus.UNKNOWN
        assert [a.action_id for a in store.list_actions("gh-7") if a.kind is ActionKind.MERGE] == [
            "merge-7"
        ]
