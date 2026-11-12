"""只用本地 Git 对象验证子模块、用户配置和符号链接边界。"""

import os
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


def _shallow_clone(tmp_path: Path, depth: int = 2) -> Path:
    """用 file:// 做一个浅克隆，模拟 CI 里的默认检出方式。"""
    origin = _make_repo(tmp_path)
    for index in range(3):
        _commit_file(origin, f"app{index}.py", f"x={index}\n", f"commit {index}")
    target = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", str(depth), f"file://{origin}", str(target)],
        check=True,
        capture_output=True,
    )
    _git(target, "config", "user.email", "test@example.com")
    _git(target, "config", "user.name", "test")
    return target


def test_shallow_clone_still_collects_the_last_two_commits(tmp_path: Path) -> None:
    """浅克隆里相邻两个提交本来就够算 merge-base，采集不能因为找不到更早的父提交就失败。"""
    root = _shallow_clone(tmp_path)
    assert (root / ".git" / "shallow").exists()

    collected = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD")

    assert collected.changes.paths, "浅克隆里也应该读到真实改动"
    assert "app2.py" in collected.changes.paths


def test_shallow_clone_reports_a_clear_error_when_base_is_outside_the_boundary(
    tmp_path: Path,
) -> None:
    """base 落在浅克隆边界之外时，要明确报 DiffError，而不是静默算出空改动。"""
    root = _shallow_clone(tmp_path)

    with pytest.raises(DiffError) as raised:
        GitDiffSource(cwd=root).collect("HEAD~5", "HEAD")

    message = str(raised.value)
    assert "HEAD~5" in message or "浅克隆" in message or "对象" in message


def test_source_repo_grafts_cannot_forge_a_merge_base(tmp_path: Path) -> None:
    """S1：源仓库里的 .git/info/grafts 不能伪造共同祖先把改动整个藏掉。

    `--no-replace-objects` 只关掉 replace 引用，管不到 grafts。审查复核里的反例是
    两条兄弟分支：`M ── B`（base 分支）和 `M ── S`（受审提交），把 grafts 写成
    「B 的父提交是 S」，`merge-base(B, S)` 就变成 S，`diff S..S` 为空，新增的
    底线文件整个消失、等级算成 A。
    """
    root = _make_repo(tmp_path)
    fork_point = _git(root, "rev-parse", "HEAD").strip()

    _git(root, "checkout", "-qb", "base-branch")
    _commit_file(root, "docs/base.md", "base side", "base side commit")
    base = _git(root, "rev-parse", "HEAD").strip()

    _git(root, "checkout", "-qb", "review", fork_point)
    _commit_file(root, "src/tandem/core/model.py", "x = 1", "hits the bottom line")
    head = _git(root, "rev-parse", "HEAD").strip()
    assert base != head

    info = root / ".git" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "grafts").write_text(f"{base} {head}" + os.linesep, encoding="utf-8")

    try:
        collected = GitDiffSource(cwd=root).collect(base, head)
    except DiffError as error:
        # 明确报错也算合格：绝不能静默给出"没有改动"
        assert "共同祖先" in str(error) or "grafts" in str(error)
        return
    assert "src/tandem/core/model.py" in collected.changes.paths, (
        "grafts 伪造共同祖先以后，改动被藏掉了"
    )
    assert compute_level(collected.changes, load_policy()) is Level.D


def test_git_calls_disable_commit_graph_and_grafts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S1：源仓库的 merge-base 与隔离仓库的每次读取都要关掉 commit-graph 与 grafts。"""
    recorded: list[tuple[list[str], dict[str, str]]] = []
    original = subprocess.run

    def spy(command: list[str], **kwargs: object) -> object:
        raw_env = kwargs.get("env")
        env: dict[str, str] = dict(raw_env) if isinstance(raw_env, dict) else {}
        recorded.append((list(command), env))
        return original(command, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(subprocess, "run", spy)
    root = _make_repo(tmp_path)
    _commit_file(root, "app.py", "y = 2\n", "change")
    GitDiffSource(cwd=root).collect("HEAD~1", "HEAD")

    source_calls = [(argv, env) for argv, env in recorded if not env.get("GIT_OBJECT_DIRECTORY")]
    isolated_calls = [(argv, env) for argv, env in recorded if env.get("GIT_OBJECT_DIRECTORY")]
    assert source_calls and isolated_calls

    merge_base_calls = [(argv, env) for argv, env in source_calls if "merge-base" in argv]
    assert merge_base_calls, "没有跑到 merge-base"
    for argv, env in merge_base_calls:
        assert "core.commitGraph=false" in argv, argv
        graft_file = env.get("GIT_GRAFT_FILE")
        assert graft_file, "merge-base 必须让 git 读不到 grafts"

    assert any("diff" in argv for argv in (argv for argv, _ in isolated_calls))
    for argv, _ in isolated_calls:
        assert "core.commitGraph=false" in argv, argv
