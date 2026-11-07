"""CLI 只连接 FakeGitHub，禁止启动 gh。"""

from pathlib import Path

import pytest

from tandem.core.model import Action, ActionKind, ActionStatus, EventKind, TaskRecord, TaskStatus
from tandem.shell import cli
from tandem.shell.github import CIState, FakeGitHub, GitHubError, Issue, PullRequest
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


@pytest.mark.parametrize("live", [False, True])
def test_reconcile_reports_status_after_core_merge_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], live: bool
) -> None:
    github = FakeGitHub(prs={8: PullRequest(8, SHA)}, checks={SHA: CIState.GREEN})
    monkeypatch.setattr(cli, "GhGitHub", lambda _repo, **_kwargs: github)
    db = tmp_path / "retry.sqlite3"
    old = Action("old-merge", ActionKind.MERGE, "gh-7", status=ActionStatus.UNKNOWN)
    with Store(db) as store:
        store.commit(
            task=TaskRecord(
                "gh-7",
                status=TaskStatus.ERROR,
                status_before_error=TaskStatus.AWAITING_MERGE,
                latest_sha=SHA,
                approved_sha=SHA,
                ci_green=True,
                pr_opened=True,
                actions=(old,),
            ),
            actions=(old,),
        )
        store.save_github_source(GitHubSource("gh-7", "owner/repo", 7, "", "", 8))
    assert (
        cli.main(
            [
                "reconcile",
                "gh-7",
                "--db",
                str(db),
                "--repo",
                "owner/repo",
                *(["--live"] if live else []),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    expected = TaskStatus.MERGED if live else TaskStatus.AWAITING_MERGE
    assert f"当前状态：{expected.value}" in output
    assert "等待 task-001" not in output
    assert len(github.writes) == int(live)
    if not live:
        assert "dry-run" in output
    with Store(db) as store:
        task = store.load_task("gh-7")
        assert task is not None and task.status is expected
        merges = [a for a in store.list_actions("gh-7") if a.kind is ActionKind.MERGE]
        assert len(merges) == 2 and merges[1].action_id != "old-merge"
        assert any(e.kind is EventKind.MERGED for e in store.list_events()) is live


def test_reconcile_live_retry_failure_returns_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class BrokenMerge(FakeGitHub):
        def merge_pr(self, number: int, expected_sha: str, *, live: bool = False) -> bool:
            raise GitHubError("gh 命令失败")

    github = BrokenMerge(prs={8: PullRequest(8, SHA)}, checks={SHA: CIState.GREEN})
    monkeypatch.setattr(cli, "GhGitHub", lambda _repo, **_kwargs: github)
    db = tmp_path / "retry-failed.sqlite3"
    with Store(db) as store:
        store.commit(
            task=TaskRecord(
                "gh-7",
                status=TaskStatus.ERROR,
                status_before_error=TaskStatus.AWAITING_MERGE,
                latest_sha=SHA,
                approved_sha=SHA,
                ci_green=True,
            )
        )
        store.save_github_source(GitHubSource("gh-7", "owner/repo", 7, "", "", 8))
    assert cli.main(["reconcile", "gh-7", "--db", str(db), "--repo", "owner/repo", "--live"]) == 2
    assert "gh 命令失败" in capsys.readouterr().out
    with Store(db) as store:
        task = store.load_task("gh-7")
        assert task is not None and task.status is TaskStatus.ERROR and task.error_code == "G01"
        assert not any(e.kind is EventKind.MERGED for e in store.list_events())
    assert github.writes == []
