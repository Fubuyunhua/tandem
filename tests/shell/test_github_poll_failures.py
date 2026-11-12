"""K3：全局 Issue 列表读取错误不得污染任务，单任务 CI 错误只影响它自己。"""

import logging
from pathlib import Path

import pytest

from tandem.core.model import Event, EventKind, TaskRecord, TaskStatus
from tandem.shell.github import CIState, FakeGitHub, GitHubError
from tandem.shell.github_events import GitHubEvents
from tandem.shell.store import GitHubSource
from tests.shell.shell_helpers import make_runner, required


def test_issue_list_failure_preserves_all_task_records_and_events(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    runner = make_runner(tmp_path)
    try:
        for number, status in enumerate(TaskStatus, start=1):
            task_id = f"gh-{number}"
            runner.store.commit(
                task=TaskRecord(task_id, status=status, latest_sha="a" * 40),
                events=[Event(EventKind.CREATED, task_id)],
            )
            runner.store.save_github_source(GitHubSource(task_id, "owner/repo", number, "", ""))
        before_tasks = runner.store.list_tasks()
        before_events = runner.store.list_events()
        before_actions = runner.store.list_actions()
        with caplog.at_level(logging.WARNING), pytest.raises(GitHubError):
            GitHubEvents(runner, FakeGitHub(fail=True), "owner/repo").poll()
        assert runner.store.list_tasks() == before_tasks
        assert runner.store.list_events() == before_events
        assert runner.store.list_actions() == before_actions
        assert "Issue 列表读取失败" in caplog.text
    finally:
        runner.store.close()


def test_issue_list_warning_does_not_include_external_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class BrokenList(FakeGitHub):
        def list_issues(self):
            raise GitHubError("secret-token")

    runner = make_runner(tmp_path)
    try:
        with caplog.at_level(logging.WARNING), pytest.raises(GitHubError) as error:
            GitHubEvents(runner, BrokenList(), "owner/repo").poll()
        assert "Issue 列表读取失败" in caplog.text
        assert "secret-token" not in caplog.text + str(error.value)
    finally:
        runner.store.close()


def test_ci_read_failure_only_changes_the_affected_task(tmp_path: Path) -> None:
    class OneBrokenCI(FakeGitHub):
        def get_ci(self, sha: str) -> CIState:
            if sha == "a" * 40:
                raise GitHubError("gh 命令失败")
            return CIState.GREEN

    runner = make_runner(tmp_path)
    try:
        for number, status in (
            (1, TaskStatus.AWAITING_ACCEPTANCE),
            (2, TaskStatus.AWAITING_YOUR_REVIEW),
        ):
            runner.store.commit(task=TaskRecord(f"gh-{number}", status=status, latest_sha="a" * 40))
            runner.store.save_github_source(
                GitHubSource(f"gh-{number}", "owner/repo", number, "", "")
            )
        unaffected = runner.store.load_task("gh-2")
        with pytest.raises(GitHubError):
            GitHubEvents(runner, OneBrokenCI(), "owner/repo").poll()
        assert required(runner.store.load_task("gh-1")).status is TaskStatus.ERROR
        assert runner.store.load_task("gh-2") == unaffected
        incidents = [
            event for event in runner.store.list_events() if event.kind is EventKind.INCIDENT
        ]
        assert [event.task_id for event in incidents] == ["gh-1"]
    finally:
        runner.store.close()
