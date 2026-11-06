"""等级计算的测试：底线条目、改名、纯文档降级、"先查底线再看 A 级"。"""

from __future__ import annotations

import pytest

from tandem.core.level import base_level, compute_level, hits_bottom_line
from tandem.core.model import ChangeSet, Level, Policy, Thresholds
from tandem.shell.config import load_policy


@pytest.fixture(scope="module")
def policy() -> Policy:
    """用仓库里真实的 risk.yml，顺便守住配置文件本身。"""
    return load_policy()


def _path_for_pattern(pattern: str) -> str:
    """把 glob 模式变成一个能命中它的具体路径（只处理 * 号）。"""
    return pattern.replace("**", "x").replace("*", "x")


def test_bottom_line_paths_cover_adr_items(policy: Policy) -> None:
    # ADR-0001 底线条目：core、闸门、提示词、依赖清单、迁移、密钥
    assert len(policy.bottom_line_paths) >= 12
    assert "core/**" in policy.bottom_line_paths
    assert ".github/**" in policy.bottom_line_paths
    assert "pyproject.toml" in policy.bottom_line_paths


@pytest.mark.parametrize("pattern", sorted(set(load_policy().bottom_line_paths)))
def test_each_bottom_line_entry_is_d(pattern: str, policy: Policy) -> None:
    """每一条底线条目：改动命中它，基础级别就是 D。"""
    path = _path_for_pattern(pattern)
    changes = ChangeSet(paths=(path,))
    assert hits_bottom_line(changes, policy), (pattern, path)
    assert compute_level(changes, policy) is Level.D


def test_core_path_under_src_is_bottom_line(policy: Policy) -> None:
    # ADR 写的是 core/**，实际路径是 src/tandem/core/...，两种写法都要命中
    assert compute_level(ChangeSet(paths=("src/tandem/core/model.py",)), policy) is Level.D
    assert compute_level(ChangeSet(paths=("core/model.py",)), policy) is Level.D


def test_delete_file_is_d(policy: Policy) -> None:
    assert compute_level(ChangeSet(deleted_paths=("src/tandem/shell/cli.py",)), policy) is Level.D


def test_assertion_decrease_is_d(policy: Policy) -> None:
    changes = ChangeSet(
        paths=("src/tandem/shell/cli.py",), assertions_before=10, assertions_after=9
    )
    assert compute_level(changes, policy) is Level.D


def test_assertion_increase_is_not_d(policy: Policy) -> None:
    changes = ChangeSet(
        paths=("src/tandem/shell/cli.py",), assertions_before=10, assertions_after=12
    )
    assert compute_level(changes, policy) is Level.C


def test_assertion_unknown_is_not_d(policy: Policy) -> None:
    assert compute_level(ChangeSet(paths=("src/tandem/shell/cli.py",)), policy) is Level.C


def test_secret_scan_hit_is_d(policy: Policy) -> None:
    changes = ChangeSet(paths=("docs/note.md",), secret_scan_hit=True)
    assert compute_level(changes, policy) is Level.D


def test_no_repository_change_is_a(policy: Policy) -> None:
    assert compute_level(ChangeSet(), policy) is Level.A


def test_bottom_line_checked_before_a_level(policy: Policy) -> None:
    """先查底线，再看是不是 A：不改仓库但命中底线，仍然是 D。"""
    changes = ChangeSet(secret_scan_hit=True)
    assert not changes.touches_repository
    assert compute_level(changes, policy) is Level.D


def test_rename_both_paths_take_part(policy: Policy) -> None:
    """改名时，改名前和改名后的路径都参与判断。"""
    into_core = ChangeSet(renames=(("docs/guide.md", "src/tandem/core/level.py"),))
    assert compute_level(into_core, policy) is Level.D
    out_of_core = ChangeSet(renames=(("src/tandem/core/level.py", "docs/level.md"),))
    assert compute_level(out_of_core, policy) is Level.D


def test_rename_within_docs_is_not_d(policy: Policy) -> None:
    changes = ChangeSet(renames=(("docs/a.md", "docs/b.md"),))
    assert compute_level(changes, policy) is Level.C


def test_pure_docs_can_downgrade_to_b(policy: Policy) -> None:
    changes = ChangeSet(paths=("docs/design/note.md", "README.md"))
    assert compute_level(changes, policy, Level.B) is Level.B


def test_pure_docs_without_suggestion_stays_c(policy: Policy) -> None:
    assert compute_level(ChangeSet(paths=("docs/note.md",)), policy) is Level.C


def test_code_cannot_downgrade(policy: Policy) -> None:
    changes = ChangeSet(paths=("src/tandem/shell/cli.py",))
    assert compute_level(changes, policy, Level.B) is Level.C


def test_absolute_lowest_is_b(policy: Policy) -> None:
    """最多降一级，最低到 B：建议 A 也只降到 B。"""
    assert compute_level(ChangeSet(paths=("docs/note.md",)), policy, Level.A) is Level.B


def test_docs_mixed_with_code_cannot_downgrade(policy: Policy) -> None:
    changes = ChangeSet(paths=("docs/note.md", "src/tandem/shell/cli.py"))
    assert compute_level(changes, policy, Level.B) is Level.C


def test_model_can_raise_any_level(policy: Policy) -> None:
    assert compute_level(ChangeSet(), policy, Level.D) is Level.D
    assert compute_level(ChangeSet(paths=("src/tandem/shell/cli.py",)), policy, Level.D) is Level.D


def test_base_level_ignores_suggestion(policy: Policy) -> None:
    assert base_level(ChangeSet(paths=("docs/note.md",)), policy) is Level.C
    assert base_level(ChangeSet(), policy) is Level.A


def test_empty_policy_has_no_bottom_line() -> None:
    policy = Policy(thresholds=Thresholds())
    assert compute_level(ChangeSet(paths=("core/model.py",)), policy) is Level.C


# ---------------------------------------------------------------- F6：路径规范化与文档类型


def test_document_extensions_come_from_config(policy: Policy) -> None:
    assert ".md" in policy.relaxable_extensions
    assert ".txt" in policy.relaxable_extensions


def test_python_file_inside_docs_cannot_downgrade(policy: Policy) -> None:
    """只认文档类型：docs/run.py 是可执行代码，不能因为目录叫 docs 就降到 B。"""
    changes = ChangeSet(paths=("docs/run.py",))
    assert compute_level(changes, policy) is Level.C
    assert compute_level(changes, policy, Level.B) is Level.C


def test_pure_docs_by_extension_can_downgrade(policy: Policy) -> None:
    assert compute_level(ChangeSet(paths=("docs/note.txt",)), policy, Level.B) is Level.B
    assert compute_level(ChangeSet(paths=("docs/note.rst",)), policy, Level.B) is Level.B


def test_markdown_outside_the_relaxable_directories_is_not_relaxable(policy: Policy) -> None:
    assert compute_level(ChangeSet(paths=("src/tandem/shell/note.md",)), policy, Level.B) is Level.C


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "C:/Users/me/secret.py",
        r"\\server\share\x.py",
        "",
        "   ",
        "docs/../src/tandem/core/model.py",
        "../outside.py",
    ],
)
def test_illegal_paths_are_d_level(path: str, policy: Policy) -> None:
    """绝对路径、空路径、带 .. 的路径一律拒绝，直接按 D 处理。"""
    changes = ChangeSet(paths=(path,))
    assert hits_bottom_line(changes, policy)
    assert compute_level(changes, policy) is Level.D


def test_backslashes_are_normalized(policy: Policy) -> None:
    assert compute_level(ChangeSet(paths=(r"docs\note.md",)), policy, Level.B) is Level.B
    assert compute_level(ChangeSet(paths=(r"src\tandem\core\model.py",)), policy) is Level.D


def test_leading_dot_slash_is_normalized(policy: Policy) -> None:
    assert compute_level(ChangeSet(paths=("./docs/note.md",)), policy, Level.B) is Level.B


def test_rename_with_illegal_path_is_d(policy: Policy) -> None:
    changes = ChangeSet(renames=(("docs/a.md", "../outside.md"),))
    assert compute_level(changes, policy) is Level.D


def test_normalize_path_helper() -> None:
    from tandem.core.level import normalize_path

    assert normalize_path("docs/a.md") == "docs/a.md"
    assert normalize_path("./docs//a.md") == "docs/a.md"
    assert normalize_path(r"docs\a.md") == "docs/a.md"
    assert normalize_path("/abs/path") is None
    assert normalize_path("docs/../x") is None
    assert normalize_path("") is None
