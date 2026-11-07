"""P7/P8：评论确认边界与单条脏数据隔离，外部进程完全替换。"""

import logging
import subprocess
from pathlib import Path

import pytest

from tandem.core.model import EventKind, TaskRecord, TaskStatus
from tandem.shell.github import CIState, FakeGitHub, GhGitHub, Issue
from tandem.shell.github_events import GitHubEvents
from tandem.shell.store import GitHubSource
from tests.shell.shell_helpers import make_runner
from tests.shell.test_github_transport import FakeGhProcess

DOCUMENT = Path(__file__).resolve().parents[2] / "docs/github-adapter.md"


def test_document_states_comment_has_no_readback_confirmation() -> None:
    assert "评论不做写后确认" in DOCUMENT.read_text(encoding="utf-8")


@pytest.mark.parametrize("live", [False, True])
def test_comment_checks_target_once_but_never_reads_back(
    monkeypatch: pytest.MonkeyPatch, live: bool
) -> None:
    backend = FakeGitHub(issues=(Issue(7, state="closed"),))
    process = FakeGhProcess(backend)
    monkeypatch.setattr(subprocess, "run", process.run)
    assert GhGitHub("owner/repo").comment(7, "不可信原文", live=live) is live
    assert [args[args.index("--method") + 1] for args, _ in process.calls] == (
        ["GET", "POST"] if live else ["GET"]
    )


@pytest.mark.parametrize(
    "dirty",
    [
        None,
        {"title": None},
        {"body": 0},
        {"body": False},
        {"labels": None},
        {"labels": ["agent"]},
        {"state": "secret-token"},
        {"number": True},
        {"number": 0},
        {"number": -1},
        {"number": "secret-token"},
    ],
)
def test_bad_issue_is_skipped_logged_and_does_not_stop_ci(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    dirty: dict | None,
) -> None:
    valid = {
        "number": 7,
        "title": "安全标题",
        "body": "需求",
        "state": "open",
        "labels": [{"name": "agent"}],
    }
    malformed = None if dirty is None else {**valid, "number": 8, "title": "secret-token", **dirty}
    process = FakeGhProcess(
        FakeGitHub(checks={"a" * 40: CIState.GREEN}),
        replies={
            "issues?state=open&labels=agent&per_page=100": [
                [valid, malformed, {**valid, "number": 9}]
            ]
        },
    )
    monkeypatch.setattr(subprocess, "run", process.run)
    runner = make_runner(tmp_path)
    try:
        runner.store.commit(
            task=TaskRecord("gh-70", status=TaskStatus.AWAITING_ACCEPTANCE, latest_sha="a" * 40)
        )
        runner.store.save_github_source(GitHubSource("gh-70", "owner/repo", 70, "", ""))
        with caplog.at_level(logging.WARNING):
            assert GitHubEvents(runner, GhGitHub("owner/repo"), "owner/repo").poll() == (
                "gh-7",
                "gh-9",
            )
        assert runner.store.load_task("gh-8") is None
        assert any(
            e.kind is EventKind.CI_GREEN and e.task_id == "gh-70"
            for e in runner.store.list_events()
        )
        assert not any(e.kind is EventKind.INCIDENT for e in runner.store.list_events())
        warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
        assert len(warnings) == 1
        assert "跳过" in caplog.text and "Issue" in caplog.text
        assert "secret-token" not in caplog.text
    finally:
        runner.store.close()
