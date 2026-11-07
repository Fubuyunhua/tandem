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


# ------------------------------------------------- H1：Git 的引号/转义路径要按 -z 解码


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo-h1"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    (root / "README.md").write_text("初始\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _create_files(root: Path, names: list[str]) -> list[str]:
    """按给定的名字建文件，返回确实落地（没有被文件系统改名）的那些。"""
    created: list[str] = []
    for name in names:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_text("内容\n", encoding="utf-8")
        except OSError:  # pragma: no cover - 平台不允许这种文件名
            continue
        if target.exists():
            created.append(name)
    return created


def test_git_diff_source_decodes_chinese_paths(tmp_path: Path) -> None:
    """含中文的路径 Git 默认会加引号转义；按 -z 解析以后必须是真实路径，等级按底线判 D。"""
    root = _make_repo(tmp_path)
    name = ".github/workflows/中.yml"
    assert _create_files(root, [name]) == [name]
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "add chinese workflow")

    collected = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD")
    assert name in collected.changes.paths
    assert all('"' not in path for path in collected.changes.paths)
    from tandem.core.level import compute_level
    from tests.core.helpers import policy

    assert compute_level(collected.changes, policy()) is Level.D


def test_git_diff_source_decodes_special_file_names(tmp_path: Path) -> None:
    """制表符、双引号这些字符也不能让路径变形（文件系统不允许时跳过）。"""
    root = _make_repo(tmp_path)
    wanted = ["tab\tname.txt", 'quote"name.txt', "空格 名字.txt"]
    created = _create_files(root, wanted)
    if len(created) < len(wanted):  # pragma: no cover - Windows 不允许 " 等字符
        pytest.skip(f"这个平台无法创建全部文件名，只测到 {created}")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "add special names")

    collected = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD")
    assert set(created) <= set(collected.changes.paths)


def test_git_diff_source_decodes_chinese_renames(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    before = "文档/说明.md"
    assert _create_files(root, [before]) == [before]
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "add doc")
    after = "文档/新说明.md"
    _git(root, "mv", before, after)
    _git(root, "commit", "-q", "-m", "rename doc")

    collected = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD")
    assert collected.changes.renames == ((before, after),)


def test_parse_name_status_z_handles_every_entry_type() -> None:
    """-z 的格式：状态 NUL 路径 NUL；改名多一个路径。"""
    from tandem.shell.diff_source import parse_name_status_z

    payload = (
        b"M\0docs/a.md\0"
        b"R100\0old.py\0new.py\0"
        b"D\0gone.py\0"
        b"A\0.github/workflows/\xe4\xb8\xad.yml\0"
        b"C75\0src/a.py\0src/b.py\0"
    )
    paths, deleted, renames = parse_name_status_z(payload)
    assert paths == ["docs/a.md", ".github/workflows/中.yml", "src/b.py"]
    assert deleted == ["gone.py"]
    assert renames == [("old.py", "new.py")]


def test_parse_name_status_z_rejects_truncated_output() -> None:
    from tandem.shell.diff_source import DiffError, parse_name_status_z

    with pytest.raises(DiffError):
        parse_name_status_z(b"M\0")


# ------------------------------------------------- H2：断言要按 diff 两端统计，改名的配对


def _commit_file(root: Path, path: str, text: str, message: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


def test_git_diff_source_counts_assertions_in_a_renamed_test_file(tmp_path: Path) -> None:
    """改名后的测试文件也要数断言：3 条减成 2 条仍然算 D。"""
    from tandem.core.level import compute_level
    from tests.core.helpers import policy

    root = _make_repo(tmp_path)
    _commit_file(
        root,
        "tests/test_a.py",
        "def test_a():\n    assert 1\n    assert 2\n    assert 3\n",
        "add tests",
    )
    _git(root, "mv", "tests/test_a.py", "tests/test_b.py")
    _commit_file(
        root, "tests/test_b.py", "def test_a():\n    assert 1\n    assert 2\n", "rename and trim"
    )

    collected = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD")
    assert collected.changes.renames == (("tests/test_a.py", "tests/test_b.py"),)
    # 之前取旧路径、之后取新路径
    assert collected.changes.assertions_before == 3
    assert collected.changes.assertions_after == 2
    assert collected.changes.assertions_decreased
    assert compute_level(collected.changes, policy()) is Level.D


def test_git_diff_source_uses_the_merge_base_for_the_before_side(tmp_path: Path) -> None:
    """两条分支各自往前走：之前的内容要取共同祖先，不是 base 分支的最新内容。"""
    from tandem.core.level import compute_level
    from tests.core.helpers import policy

    root = _make_repo(tmp_path)
    _git(root, "checkout", "-q", "-b", "work")
    _commit_file(
        root,
        "tests/test_a.py",
        "def test_a():\n    assert 1\n    assert 2\n    assert 3\n",
        "ancestor",
    )
    _git(root, "checkout", "-q", "-b", "base-branch")
    _commit_file(root, "tests/test_a.py", "def test_a():\n    assert 1\n", "base side")
    _git(root, "checkout", "-q", "work")
    _commit_file(
        root, "tests/test_a.py", "def test_a():\n    assert 1\n    assert 2\n", "review side"
    )

    collected = GitDiffSource(cwd=root).collect("base-branch", "work")
    # 共同祖先是 3 条断言，受审分支是 2 条 → 减少，判 D
    assert collected.changes.assertions_before == 3
    assert collected.changes.assertions_after == 2
    assert compute_level(collected.changes, policy()) is Level.D


def test_git_diff_source_counts_deleted_test_files(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _commit_file(root, "tests/test_gone.py", "def test_a():\n    assert 1\n", "add test")
    _git(root, "rm", "-q", "tests/test_gone.py")
    _git(root, "commit", "-q", "-m", "drop test")

    collected = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD")
    assert collected.changes.deleted_paths == ("tests/test_gone.py",)
    assert collected.changes.assertions_before == 1
    assert collected.changes.assertions_after == 0


def test_git_diff_source_rejects_unrelated_histories(tmp_path: Path) -> None:
    """没有共同祖先时不能瞎猜"之前"的内容。"""
    from tandem.shell.diff_source import DiffError

    root = _make_repo(tmp_path)
    _git(root, "checkout", "-q", "--orphan", "other")
    _commit_file(root, "docs/x.md", "另一个历史\n", "orphan")

    with pytest.raises(DiffError):
        GitDiffSource(cwd=root).collect("main", "other")


# ------------------------------------------------- 断言减少按文件判断（task-003 Codex 发现）


def test_git_diff_source_does_not_let_a_new_file_offset_a_drop(tmp_path: Path) -> None:
    """一个测试文件少了断言、另一个新增测试文件补上：合计不变也要判 D。"""
    from tandem.core.level import compute_level
    from tests.core.helpers import policy

    root = _make_repo(tmp_path)
    _commit_file(
        root,
        "tests/test_app.py",
        "def test_a():\n    assert 1\n    assert 2\n",
        "add app tests",
    )
    _commit_file(
        root,
        "tests/test_app.py",
        "def test_a():\n    assert 1\n",
        "drop one assertion",
    )
    _commit_file(
        root, "tests/test_new.py", "def test_b():\n    assert 3\n", "add another test file"
    )
    # 目标提交相对共同祖先：test_app 少一条、test_new 多一条
    _git(root, "reset", "-q", "--hard", "HEAD")

    collected = GitDiffSource(cwd=root).collect("HEAD~2", "HEAD")
    assert collected.changes.assertions_before == 2
    assert collected.changes.assertions_after == 2  # 合计持平
    drops = collected.changes.assertion_drops
    assert [drop.path for drop in drops] == ["tests/test_app.py"]
    assert (drops[0].before, drops[0].after) == (2, 1)
    assert compute_level(collected.changes, policy()) is Level.D


def test_git_diff_source_counts_only_increases_as_not_bottom_line(tmp_path: Path) -> None:
    """只增加断言不算底线，仍然是 C 级。"""
    from tandem.core.level import compute_level
    from tests.core.helpers import policy

    root = _make_repo(tmp_path)
    _commit_file(root, "tests/test_app.py", "def test_a():\n    assert 1\n", "add test")
    _commit_file(
        root,
        "tests/test_app.py",
        "def test_a():\n    assert 1\n    assert 2\n    assert 3\n",
        "add assertions",
    )

    collected = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD")
    assert collected.changes.assertion_drops == ()
    assert compute_level(collected.changes, policy()) is Level.C


def test_git_diff_source_reports_rename_drop_in_per_file_detail(tmp_path: Path) -> None:
    """改名并减少断言：减少的记录要带上旧路径和新路径。"""
    root = _make_repo(tmp_path)
    _commit_file(
        root,
        "tests/test_a.py",
        "def test_a():\n    assert 1\n    assert 2\n",
        "add tests",
    )
    _git(root, "mv", "tests/test_a.py", "tests/test_b.py")
    _commit_file(root, "tests/test_b.py", "def test_a():\n    assert 1\n", "rename and trim")

    collected = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD")
    drops = collected.changes.assertion_drops
    assert len(drops) == 1
    assert drops[0].previous_path == "tests/test_a.py"
    assert drops[0].path == "tests/test_b.py"
    assert (drops[0].before, drops[0].after) == (2, 1)


def test_changes_with_assertion_drops_survive_json_roundtrip() -> None:
    """逐文件记录要能存进事件日志再读回来（tandem show 靠它说明原因）。"""
    from tandem.core.model import AssertionDrop
    from tandem.shell import serde

    changes = ChangeSet(
        paths=("tests/test_app.py", "tests/test_new.py"),
        assertions_before=2,
        assertions_after=2,
        assertion_drops=(
            AssertionDrop(
                path="tests/test_b.py",
                previous_path="tests/test_a.py",
                before=3,
                after=2,
            ),
        ),
    )
    restored = serde.changes_from_dict(serde.changes_to_dict(changes))
    assert restored == changes
