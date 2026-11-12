"""P2：隔离各层保护，避免被后续预检意外兜底而形成假阳性。"""

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from tandem.core.model import ActionKind, ActionStatus, Event, EventKind, TaskRecord, TaskStatus
from tandem.shell.github import CIState, FakeGitHub, GhGitHub, GitHubError, PullRequest
from tandem.shell.store import GitHubSource
from tests.shell.shell_helpers import make_runner, required
from tests.shell.test_github_transport import FakeGhProcess

SHA = "a" * 40


def test_nonzero_exit_with_valid_json_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        data = {"state": "open", "head": {"sha": SHA}, "merged": False}
        return subprocess.CompletedProcess(args, 1, json.dumps(data), "secret-token")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(GitHubError, match="gh 命令失败") as error:
        GhGitHub("owner/repo").get_pr(8)
    assert "secret-token" not in str(error.value)


class FalseMergeReply(FakeGitHub):
    def _write(self, resource: str, payload: dict[str, object], method: str) -> object:
        # 故意让后续 PR 读取显示已合并，只测试 merged=false 这一层守卫。
        super()._write(resource, payload, method)
        return {"merged": False}


def test_false_merge_reply_is_rejected() -> None:
    github = FalseMergeReply(prs={8: PullRequest(8, SHA)}, checks={SHA: CIState.GREEN})
    with pytest.raises(GitHubError, match="GitHub 未确认合并成功"):
        github.merge_pr(8, SHA, live=True)


def test_false_merge_reply_does_not_emit_merged(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, dry_run=False)
    github = FalseMergeReply(prs={8: PullRequest(8, SHA)}, checks={SHA: CIState.GREEN})
    try:
        runner.store.commit(
            task=TaskRecord(
                "gh-7", status=TaskStatus.AWAITING_YOUR_REVIEW, latest_sha=SHA, ci_green=True
            )
        )
        runner.store.save_github_source(GitHubSource("gh-7", "owner/repo", 7, "", "", 8))
        runner.executor.github = github
        runner.executor.github_repo = "owner/repo"
        runner.handle(Event(EventKind.YOUR_APPROVAL, "gh-7", sha=SHA))
        task = required(runner.store.load_task("gh-7"))
        assert task.status is TaskStatus.ERROR and task.error_code == "G01"
        assert runner.store.list_actions("gh-7")[0].status is ActionStatus.UNKNOWN
        assert not any(event.kind is EventKind.MERGED for event in runner.store.list_events())
    finally:
        runner.store.close()


def test_close_readback_open_is_rejected() -> None:
    class StillOpen(FakeGitHub):
        def _write(self, resource: str, payload: dict[str, object], method: str) -> object:
            self.writes.append((resource, payload))
            return {}

    github = StillOpen(prs={8: PullRequest(8, SHA)})
    with pytest.raises(GitHubError, match="关闭后的状态尚未确认"):
        github.close_pr(8, live=True)
    assert github.prs[8].state == "open"
    assert len(github.writes) == 1


@pytest.mark.parametrize("approved,green", [("b" * 40, True), (None, True), (SHA, False)])
def test_executor_merge_guard_is_independent_of_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, approved: str | None, green: bool
) -> None:
    class PermissiveGitHub(FakeGitHub):
        def merge_pr(self, number: int, expected_sha: str, *, live: bool = False) -> bool:
            self.writes.append(("unexpected-merge", {"sha": expected_sha}))
            return True

    github = PermissiveGitHub()
    runner = make_runner(tmp_path, dry_run=False)
    try:
        runner.store.commit(
            task=TaskRecord(
                "gh-7", status=TaskStatus.AWAITING_YOUR_REVIEW, latest_sha=SHA, ci_green=True
            )
        )
        runner.store.save_github_source(GitHubSource("gh-7", "owner/repo", 7, "", "", 8))
        runner.executor.github = github
        runner.executor.github_repo = "owner/repo"
        execute = runner.executor.execute

        def stale_execute(action, task):
            if action.kind is ActionKind.MERGE:
                task = replace(task, approved_sha=approved, ci_green=green)
            return execute(action, task)

        monkeypatch.setattr(runner.executor, "execute", stale_execute)
        outcome = runner.handle(Event(EventKind.YOUR_APPROVAL, "gh-7", sha=SHA))
        assert outcome.executed[0].status is ActionStatus.UNKNOWN
        task = required(runner.store.load_task("gh-7"))
        assert task.status is TaskStatus.ERROR and task.error_code == "G01"
        assert github.writes == []
        assert not any(event.kind is EventKind.MERGED for event in runner.store.list_events())
    finally:
        runner.store.close()


def test_issue_list_skips_pull_requests(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    issue = {
        "number": 7,
        "title": "需求",
        "body": None,
        "labels": [{"name": "agent"}],
        "state": "open",
    }
    # 完整 PR 防止被当作普通 Issue；不完整 PR 也应直接排除而非脏数据告警。
    process = FakeGhProcess(
        FakeGitHub(),
        replies={
            "issues?state=open&labels=agent&per_page=100": [
                [{**issue, "number": 8, "pull_request": {}}, {"pull_request": {}}, issue]
            ]
        },
    )
    monkeypatch.setattr(subprocess, "run", process.run)
    assert [item.number for item in GhGitHub("owner/repo").list_issues()] == [7]
    assert not caplog.records
