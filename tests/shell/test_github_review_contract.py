"""审核要求的中文错误信息和 M1 使用说明，防止再次丢失关键约束。"""

from pathlib import Path

import pytest

from tandem.shell.store import ConflictError, GitHubSource, Store

DOCUMENT = Path(__file__).resolve().parents[2] / "docs" / "github-adapter.md"


@pytest.mark.parametrize("issue,pr", [(1, None), (2, 8)])
def test_github_duplicate_source_has_a_readable_chinese_error(
    tmp_path: Path, issue: int, pr: int | None
) -> None:
    original = GitHubSource("gh-1", "owner/repo", 1, "", "", 8)
    with Store(tmp_path / "sources.sqlite3") as store:
        store.save_github_source(original)
        with pytest.raises(ConflictError, match="GitHub Issue 或 PR 已关联其他任务"):
            store.save_github_source(GitHubSource("gh-2", "owner/repo", issue, "", "", pr))
        assert store.github_source("gh-1") == original
        assert store.github_source("gh-2") is None


def test_document_explains_provisional_issue_level_and_late_plan_approval() -> None:
    text = DOCUMENT.read_text(encoding="utf-8")
    assert "C 级只是初始占位" in text
    assert "risk.yml" in text
    assert "方案审批发生在交回代码后" in text


def test_document_warns_against_live_in_m1() -> None:
    text = DOCUMENT.read_text(encoding="utf-8")
    assert "M1 不要用 --live" in text
    assert "用户在 GitHub 上手动合并" in text
    assert "approve --live 会真的发起合并" in text


def test_document_keeps_three_deferred_core_boundaries() -> None:
    text = DOCUMENT.read_text(encoding="utf-8")
    assert "后续交给 task-001 写手处理" in text
    for boundary in ("取消清理失败恢复", "NOT_CONFIRMED 合并重发", "PR_CLOSED 后的 PR 生命周期"):
        assert boundary in text


def test_document_explains_required_checks_without_changing_risk_level() -> None:
    text = DOCUMENT.read_text(encoding="utf-8")
    assert "required_checks: [check]" in text
    assert "缺少任何一个" in text
    assert "不改变 risk-level 的退出码" in text
