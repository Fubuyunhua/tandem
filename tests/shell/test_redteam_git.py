"""只用本地 Git 对象验证子模块、用户配置和符号链接边界。"""

import subprocess
from pathlib import Path

import pytest

from tandem.core.level import compute_level
from tandem.core.model import Level
from tandem.shell.config import load_policy
from tandem.shell.diff_source import DiffError, GitDiffSource
from tandem.shell.serde import changes_from_dict, changes_to_dict
from tests.shell.test_diff_source import _commit_file, _git, _make_repo


def test_diff_ignores_user_diff_settings_and_includes_gitlinks(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    old = _git(root, "rev-parse", "HEAD").strip()
    _commit_file(root, "a.py", "x=1\n", "object")
    new = _git(root, "rev-parse", "HEAD").strip()
    _git(root, "update-index", "--add", "--cacheinfo", f"160000,{old},src/tandem/core")
    _git(root, "commit", "-qm", "add gitlink")
    _git(root, "update-index", "--cacheinfo", f"160000,{new},src/tandem/core")
    _git(root, "commit", "-qm", "update gitlink")
    _git(root, "config", "diff.ignoreSubmodules", "all")
    _git(root, "config", "diff.renameLimit", "not-an-integer")
    changes = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD").changes
    assert "src/tandem/core" in changes.paths
    assert compute_level(changes, load_policy()) is Level.D
    entries = getattr(changes, "file_changes", ())
    assert entries and entries[0].after_mode == "160000"


@pytest.mark.parametrize(
    "target, expected",
    [
        ("../README.md", Level.C),
        ("../src/tandem/core/level.py", Level.D),
        ("../src/TANDEM/CORE", Level.D),
    ],
)
def test_symlink_modes_survive_collection_and_serialization(
    tmp_path: Path, target: str, expected: Level
) -> None:
    root = _make_repo(tmp_path)
    _commit_file(root, "docs/a.md", "documentation\n", "doc")
    oid = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=root,
        input=target,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    _git(root, "update-index", "--cacheinfo", f"120000,{oid},docs/a.md")
    _git(root, "commit", "-qm", "symlink")
    changes = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD").changes
    assert compute_level(changes, load_policy(), Level.B) is expected
    entries = getattr(changes, "file_changes", ())
    assert entries and entries[0].before_mode == "100644"
    assert entries[0].after_mode == "120000"
    assert changes_from_dict(changes_to_dict(changes)) == changes


def test_missing_existing_test_blob_is_not_counted_as_empty(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _commit_file(root, "tests/test_a.py", "def test_a():\n    assert False\n", "test")
    oid = _git(root, "rev-parse", "HEAD:tests/test_a.py").strip()
    _commit_file(root, "tests/test_a.py", "def test_a():\n    pass\n", "remove assertion")
    # 只破坏临时测试仓库里的一个松散对象，模拟读对象失败。
    blob = (root / ".git" / "objects" / oid[:2] / oid[2:]).resolve()
    assert blob.is_relative_to(root.resolve())
    blob.chmod(0o600)
    blob.unlink()
    with pytest.raises(DiffError):
        GitDiffSource(cwd=root).collect("HEAD~1", "HEAD")


def test_deleted_document_remains_bottom_line_d(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _commit_file(root, "docs/a.md", "documentation\n", "doc")
    _git(root, "rm", "docs/a.md")
    _git(root, "commit", "-qm", "delete doc")
    changes = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD").changes
    assert changes.file_changes[0].after_mode == "000000"
    assert compute_level(changes, load_policy(), Level.B) is Level.D
