"""等级计算的测试：底线条目、改名、纯文档降级、"先查底线再看 A 级"。"""

from __future__ import annotations

import pytest

from tandem.core.level import base_level, compute_level, hits_bottom_line
from tandem.core.model import ChangeSet, FileChange, Level, Policy, Thresholds
from tandem.shell.config import load_policy


@pytest.fixture(scope="module")
def policy() -> Policy:
    """用仓库里真实的 risk.yml，顺便守住配置文件本身。"""
    return load_policy()


def _documents(*paths: str) -> ChangeSet:
    return ChangeSet(
        paths=paths, file_changes=tuple(FileChange(path, "100644", "100644") for path in paths)
    )


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
    changes = _documents("docs/design/note.md", "README.md")
    assert compute_level(changes, policy, Level.B) is Level.B


def test_pure_docs_without_suggestion_stays_c(policy: Policy) -> None:
    assert compute_level(_documents("docs/note.md"), policy) is Level.C


def test_code_cannot_downgrade(policy: Policy) -> None:
    changes = ChangeSet(paths=("src/tandem/shell/cli.py",))
    assert compute_level(changes, policy, Level.B) is Level.C


def test_absolute_lowest_is_b(policy: Policy) -> None:
    """最多降一级，最低到 B：建议 A 也只降到 B。"""
    assert compute_level(_documents("docs/note.md"), policy, Level.A) is Level.B


def test_docs_mixed_with_code_cannot_downgrade(policy: Policy) -> None:
    changes = ChangeSet(paths=("docs/note.md", "src/tandem/shell/cli.py"))
    assert compute_level(changes, policy, Level.B) is Level.C


def test_model_can_raise_any_level(policy: Policy) -> None:
    assert compute_level(ChangeSet(), policy, Level.D) is Level.D
    assert compute_level(ChangeSet(paths=("src/tandem/shell/cli.py",)), policy, Level.D) is Level.D


def test_base_level_ignores_suggestion(policy: Policy) -> None:
    assert base_level(_documents("docs/note.md"), policy) is Level.C
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
    assert compute_level(_documents("docs/note.txt"), policy, Level.B) is Level.B
    assert compute_level(_documents("docs/note.rst"), policy, Level.B) is Level.B


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
    assert compute_level(_documents(r"docs\note.md"), policy, Level.B) is Level.B
    assert compute_level(ChangeSet(paths=(r"src\tandem\core\model.py",)), policy) is Level.D


def test_leading_dot_slash_is_normalized(policy: Policy) -> None:
    assert compute_level(_documents("./docs/note.md"), policy, Level.B) is Level.B


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


# ------------------------------------------------- 断言减少要按文件判断


def test_single_file_drop_is_d_even_when_totals_are_flat(policy: Policy) -> None:
    """一个文件少了断言、另一个文件多了断言：合计不变，但仍然是底线 D。"""
    from tandem.core.model import AssertionDrop

    changes = ChangeSet(
        paths=("tests/test_app.py", "tests/test_new.py"),
        assertions_before=2,
        assertions_after=2,  # 合计没变
        assertion_drops=(AssertionDrop(path="tests/test_app.py", before=2, after=1),),
    )
    assert changes.assertions_decreased
    assert compute_level(changes, policy) is Level.D


def test_bottom_line_reasons_name_the_file_that_lost_assertions(policy: Policy) -> None:
    """底线报告要能说出是哪个文件减少了，供 tandem show / risk-gate 用。"""
    from tandem.core.level import bottom_line_reasons
    from tandem.core.model import AssertionDrop

    changes = ChangeSet(
        paths=("tests/test_app.py", "tests/test_new.py"),
        assertions_before=2,
        assertions_after=2,
        assertion_drops=(AssertionDrop(path="tests/test_app.py", before=2, after=1),),
    )
    reasons = bottom_line_reasons(changes, policy)
    assert any("tests/test_app.py" in reason for reason in reasons)
    assert any("断言" in reason for reason in reasons)


def test_rename_drop_reason_mentions_both_paths(policy: Policy) -> None:
    from tandem.core.level import bottom_line_reasons
    from tandem.core.model import AssertionDrop

    changes = ChangeSet(
        renames=(("tests/test_a.py", "tests/test_b.py"),),
        assertion_drops=(
            AssertionDrop(
                path="tests/test_b.py",
                previous_path="tests/test_a.py",
                before=3,
                after=2,
            ),
        ),
    )
    reasons = bottom_line_reasons(changes, policy)
    joined = "；".join(reasons)
    assert "tests/test_a.py" in joined and "tests/test_b.py" in joined
    assert compute_level(changes, policy) is Level.D


def test_totals_still_count_as_a_drop_when_no_per_file_detail(policy: Policy) -> None:
    """兼容旧数据：只有合计数字时，合计减少照旧算命中底线。"""
    changes = ChangeSet(paths=("tests/test_app.py",), assertions_before=5, assertions_after=4)
    assert compute_level(changes, policy) is Level.D


# ------------------------------------------------- K7：任务等级只升不降


def test_level_never_goes_down() -> None:
    """等级只升不降：取（当前任务等级，本次算出的等级）里更严格的那个。"""
    from tandem.core.level import keep_stricter

    assert keep_stricter(Level.D, Level.C) is Level.D
    assert keep_stricter(Level.C, Level.D) is Level.D
    assert keep_stricter(Level.B, Level.A) is Level.B
    assert keep_stricter(Level.A, Level.B) is Level.B
    assert keep_stricter(Level.C, Level.C) is Level.C
    assert keep_stricter(Level.A, Level.A) is Level.A
    for left in Level:
        for right in Level:
            kept = keep_stricter(left, right)
            assert kept.rank == max(left.rank, right.rank)


def test_document_only_commit_cannot_downgrade_a_d_task() -> None:
    """D 级方案批准后提交纯文档改动：仍算 D（旧实现会重算成 B/C）。"""
    from tandem.core.level import keep_stricter
    from tandem.core.model import FileChange

    policy = load_policy()
    docs = ChangeSet(
        paths=("docs/note.md",),
        file_changes=(FileChange("docs/note.md", "000000", "100644"),),
    )
    computed = compute_level(docs, policy, Level.B)
    assert computed is Level.B  # 单看这次改动确实是 B
    assert keep_stricter(Level.D, computed) is Level.D
