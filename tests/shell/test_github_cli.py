"""CLI 只连接 FakeGitHub，禁止启动 gh。"""

from pathlib import Path

import pytest

from tandem.core.model import TaskRecord, TaskStatus
from tandem.shell import cli
from tandem.shell.github import CIState, FakeGitHub, Issue, PullRequest
from tandem.shell.store import GitHubSource, Store

SHA = "a" * 40


def test_poll_and_reconcile_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    github = FakeGitHub(issues=(Issue(7, labels=("agent",)),), prs={8: PullRequest(8, SHA)})
    monkeypatch.setattr(cli, "GhGitHub", lambda _repo, **_kwargs: github)
    db = tmp_path / "cli.sqlite3"
    common = ["--db", str(db), "--repo", "owner/repo"]
    assert cli.main(["poll", *common, "--bind", "gh-7=8"]) == 0
    assert cli.main(["poll", *common]) == 0
    with Store(db) as store:
        task = store.load_task("gh-7")
        assert task is not None
        store.commit(
            task=TaskRecord("gh-7", status=TaskStatus.ERROR, state_version=1), expected_version=0
        )
    assert cli.main(["reconcile", "gh-7", *common]) == 0
    assert github.writes == []


@pytest.mark.parametrize("live", [False, True])
def test_approve_cli_live_is_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live: bool
) -> None:
    github = FakeGitHub(prs={8: PullRequest(8, SHA)}, checks={SHA: CIState.GREEN})
    monkeypatch.setattr(cli, "GhGitHub", lambda _repo, **_kwargs: github)
    db = tmp_path / "cli.sqlite3"
    with Store(db) as store:
        store.commit(
            task=TaskRecord(
                "gh-7",
                status=TaskStatus.AWAITING_YOUR_REVIEW,
                latest_sha=SHA,
                ci_green=True,
            )
        )
        store.save_github_source(GitHubSource("gh-7", "owner/repo", 7, "", "", 8))
    args = ["approve", "--db", str(db), "--task-id", "gh-7", "--sha", SHA]
    assert cli.main([*args, *(["--live"] if live else [])]) == 0
    assert bool(github.writes) is live
    with Store(db) as store:
        task = store.load_task("gh-7")
        assert task is not None
        assert task.status is (TaskStatus.MERGED if live else TaskStatus.AWAITING_MERGE)


def test_cli_failure_exit_and_safe_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    github = FakeGitHub(fail=True)
    monkeypatch.setattr(cli, "GhGitHub", lambda _repo, **_kwargs: github)
    assert cli.main(["poll", "--db", str(tmp_path / "cli.sqlite3"), "--repo", "owner/repo"]) == 1
    assert "失败" in capsys.readouterr().out
    assert github.writes == []
