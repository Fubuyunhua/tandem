"""F1：等级必须按真实改动算，回执里自报的 changes 一律忽略。

改动由外壳的 `DiffSource` 自己采集（真实实现走 `git diff --name-status -M`），
内核和 Agent 的回执都不参与"改动是什么"这件事。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tandem.core.model import ChangeSet, Event, EventKind, Level, TaskStatus
from tandem.shell.diff_source import (
    DiffError,
    FakeDiffSource,
    GitDiffSource,
    SecretScanState,
)
from tandem.shell.receipt import parse_receipt, render_receipt
from tests.shell.shell_helpers import code_receipt, make_runner


def test_receipt_changes_field_is_ignored_with_warning() -> None:
    """回执里塞 changes 也不会被采用，只记一条警告。"""
    text = render_receipt(
        "DONE",
        {
            "task_id": "t1",
            "attempt": 1,
            "sha": "abc",
            "changes": {"paths": ["docs/a.md"]},
        },
    )
    receipt = parse_receipt(text)
    assert not hasattr(receipt, "changes")
    assert any("changes" in warning for warning in receipt.warnings)


def test_receipt_without_changes_has_no_warning() -> None:
    receipt = parse_receipt('DONE\n{"task_id": "t1", "attempt": 1, "sha": "abc"}')
    assert receipt.warnings == ()


def test_fake_diff_source_reports_unscanned_secrets() -> None:
    source = FakeDiffSource(changes=ChangeSet(paths=("src/tandem/shell/cli.py",)))
    collected = source.collect("main", "abc")
    assert collected.changes.paths == ("src/tandem/shell/cli.py",)
    assert collected.secret_scan is SecretScanState.NOT_SCANNED
    # 密钥扫描还没接，必须在记录里如实标明
    assert "未扫描" in collected.describe()


def test_runner_ignores_the_agent_self_report(tmp_path: Path) -> None:
    """回执自称只改了 docs，采集器说改了 core：按 core 算，任务升成 D 级。"""
    lying = render_receipt(
        "DONE：只改了文档",
        {"task_id": "t1", "attempt": 1, "sha": "abc", "changes": {"paths": ["docs/a.md"]}},
    )
    runner = make_runner(
        tmp_path,
        [lying],
        diff_source=FakeDiffSource(changes=ChangeSet(paths=("src/tandem/core/model.py",))),
    )
    runner.submit("t1", Level.C)
    started = runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))
    receipt = parse_receipt(started.receipts[0])
    task = runner.store.load_task("t1")
    assert task is not None

    event = runner.code_event(task, receipt)
    assert event.changes is not None
    assert event.changes.paths == ("src/tandem/core/model.py",)
    assert "changes" in (event.reason or "")

    result = runner.handle(event)
    assert result.decision.task.level is Level.D
    assert result.decision.task.status is TaskStatus.AWAITING_PLAN_APPROVAL


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """一个本地小仓库：base 提交 → 改文件、改名、删文件、减少断言的提交。"""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("文档\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text(
        "def test_a():\n    assert 1 == 1\n    assert 2 == 2\n", encoding="utf-8"
    )
    (root / "old.py").write_text("x = 1\n", encoding="utf-8")
    (root / "gone.py").write_text("y = 2\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")

    (root / "docs" / "guide.md").write_text("改过的文档\n", encoding="utf-8")
    (root / "tests" / "test_a.py").write_text(
        "def test_a():\n    assert 1 == 1\n", encoding="utf-8"
    )
    (root / "old.py").rename(root / "new.py")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "change")
    _git(root, "rm", "-q", "gone.py")
    _git(root, "commit", "-q", "-m", "delete")
    return root


def test_git_diff_source_reads_real_changes(repository: Path) -> None:
    source = GitDiffSource(cwd=repository)
    collected = source.collect("HEAD~2", "HEAD")
    paths = set(collected.changes.paths)
    assert "docs/guide.md" in paths
    assert "tests/test_a.py" in paths
    # 改名：改名前和改名后都记下来
    assert collected.changes.renames == (("old.py", "new.py"),)
    # 删除
    assert collected.changes.deleted_paths == ("gone.py",)
    # 断言数量减少：这条底线条目要靠真实 diff 算出来
    assert collected.changes.assertions_decreased
    assert collected.secret_scan is SecretScanState.NOT_SCANNED


def test_git_diff_source_rejects_bad_revision(repository: Path) -> None:
    source = GitDiffSource(cwd=repository)
    with pytest.raises(DiffError):
        source.collect("HEAD", "not-a-revision")


def test_code_receipt_used_by_shell_helpers_has_no_changes() -> None:
    receipt = parse_receipt(code_receipt("t1"))
    assert receipt.sha
    assert not hasattr(receipt, "changes")
