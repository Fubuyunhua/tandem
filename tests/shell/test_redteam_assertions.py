"""断言弱化、测试命名和移出收集范围的真实 Git 回归。"""

from pathlib import Path

import pytest

from tandem.core.level import compute_level
from tandem.core.model import Level
from tandem.shell.config import load_policy
from tandem.shell.diff_source import GitDiffSource
from tests.shell.test_diff_source import _commit_file, _git, _make_repo


@pytest.mark.parametrize(
    "path, before, after",
    [
        (
            "tests/test_a.py",
            "def test_a():\n    assert False\n",
            "def test_a():\n    pass # assert False\n",
        ),
        (
            "tests/test_a.py",
            "def test_a():\n    assert False\n",
            "def test_a():\n    text = 'assert False'\n",
        ),
        ("tests/a.test.js", "expect(false).toBe(true);\n", "// expect(false).toBe(true);\n"),
        ("tests/a.test.js", "expect(false).toBe(true);\n", "/* expect(false).toBe(true); */\n"),
        (
            "tests/a.test.js",
            "expect(false).toBe(true);\n",
            "const text = 'expect(false).toBe(true)';\n",
        ),
        (
            "tests/a.test.js",
            "// comment\u2028expect(false).toBe(true);\n",
            "// comment\u2028void 0;\n",
        ),
    ],
)
def test_comments_and_strings_cannot_replace_assertions(
    tmp_path: Path, path: str, before: str, after: str
) -> None:
    root = _make_repo(tmp_path)
    _commit_file(root, path, before, "assertion")
    _commit_file(root, path, after, "remove assertion")
    changes = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD").changes
    assert changes.assertions_before == 1
    assert changes.assertions_after == 0
    assert compute_level(changes, load_policy()) is Level.D


@pytest.mark.parametrize(
    "path",
    [
        "src/a.test.ts",
        "src/a.test.js",
        "src/a.test.tsx",
        "src/a.test.jsx",
        "src/a.spec.ts",
        "src/a.spec.js",
        "src/a.spec.tsx",
        "src/a.spec.jsx",
        "src/__tests__/a.js",
    ],
)
def test_common_test_names_are_counted(tmp_path: Path, path: str) -> None:
    root = _make_repo(tmp_path)
    _commit_file(root, path, "expect(false).toBe(true);\n", "assertion")
    _commit_file(root, path, "void 0;\n", "remove assertion")
    changes = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD").changes
    assert compute_level(changes, load_policy()) is Level.D


@pytest.mark.parametrize("body", ["def test_a():\n    assert False\n", "def test_a():\n    pass\n"])
def test_renaming_out_of_test_collection_is_a_removal(tmp_path: Path, body: str) -> None:
    root = _make_repo(tmp_path)
    _commit_file(root, "tests/test_a.py", body, "test")
    (root / "docs").mkdir()
    _git(root, "mv", "tests/test_a.py", "docs/a.md")
    _git(root, "commit", "-qm", "move outside collection")
    changes = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD").changes
    assert compute_level(changes, load_policy()) is Level.D


@pytest.mark.parametrize("target", ["docs/test_a.py", "Tests/test_a.py", "tests/Test_a.py"])
def test_unchanged_test_moved_out_or_case_renamed_is_d(tmp_path: Path, target: str) -> None:
    root = _make_repo(tmp_path)
    _commit_file(root, "tests/test_a.py", "def test_a():\n    assert True\n", "test")
    # 经过临时路径，Windows 上也能构造 Git 树中的纯大小写改名。
    _git(root, "mv", "tests/test_a.py", "staged-test.py")
    if not (root / target).parent.exists():
        (root / target).parent.mkdir(parents=True)
    _git(root, "mv", "staged-test.py", target)
    _git(root, "commit", "-qm", "rename unchanged test")
    changes = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD").changes
    assert changes.renames == (("tests/test_a.py", target),)
    assert "tests/test_a.py" in changes.removed_test_paths
    assert compute_level(changes, load_policy()) is Level.D
