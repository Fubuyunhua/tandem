"""pi 审核回归：真实收集边界、源码类型和模式证据。"""

from pathlib import Path

import pytest

from tandem.core.level import compute_level
from tandem.core.model import ChangeSet, FileChange, Level
from tandem.shell.assertions import is_test_path, leaves_test_collection
from tandem.shell.config import DEFAULT_RISK_PATH, load_policy
from tandem.shell.diff_source import GitDiffSource
from tests.shell.test_diff_source import _commit_file, _git, _make_repo


@pytest.mark.parametrize("entries", [(), (FileChange("docs/a.md", "100644", "100644"),)])
def test_unknown_or_partial_modes_cannot_relax(entries: tuple[FileChange, ...]) -> None:
    changes = ChangeSet(paths=("docs/a.md", "docs/b.md"), file_changes=entries)
    assert compute_level(changes, load_policy(), Level.B) is Level.C


@pytest.mark.parametrize(
    "path",
    [
        "tests/__pycache__/test_a.pyc",
        "tests/test_a.json",
        "tests/test_a.txt",
        "src/__tests__/fixture.json",
        "tests/helpers.py",
    ],
)
def test_only_named_source_tests_are_counted(path: str) -> None:
    assert not is_test_path(path)


@pytest.mark.parametrize(
    "directory",
    [
        "build",
        "dist",
        "node_modules",
        "venv",
        ".hidden",
        "example.egg",
        "CVS",
        "_darcs",
        "{arch}",
    ],
)
def test_entering_pytest_ignored_directory_is_removal(directory: str) -> None:
    assert leaves_test_collection("tests/test_a.py", f"tests/{directory}/test_a.py")


@pytest.mark.parametrize("directory", ["build", ".hidden"])
def test_ignored_directory_move_is_d_in_git(tmp_path: Path, directory: str) -> None:
    root = _make_repo(tmp_path)
    _commit_file(root, "tests/test_a.py", "def test_a():\n    assert False\n", "test")
    (root / "tests" / directory).mkdir()
    _git(root, "mv", "tests/test_a.py", f"tests/{directory}/test_a.py")
    _git(root, "commit", "-qm", "hide test")
    changes = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD").changes
    assert changes.removed_test_paths == ("tests/test_a.py",)
    assert compute_level(changes, load_policy()) is Level.D


def test_unittest_counting_boundary_is_documented() -> None:
    text = DEFAULT_RISK_PATH.with_name("README.md").read_text(encoding="utf-8")
    assert "self.assert*" in text and "pytest.raises" in text


def test_fail_closed_boundaries_are_documented() -> None:
    text = DEFAULT_RISK_PATH.with_name("README.md").read_text(encoding="utf-8")
    assert "无共同祖先" in text and "部分克隆" in text and "DiffError" in text
