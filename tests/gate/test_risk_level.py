"""从真实临时 Git 仓库启动命令行闸门，验证裁决、解释与退出码。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "gate" / "risk_level.py"


def git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repository, capture_output=True, check=True, encoding="utf-8"
    )
    return result.stdout.strip()


def write(repository: Path, path: str, content: str) -> None:
    target = repository / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def commit(repository: Path) -> str:
    git(repository, "add", "-A")
    git(repository, "-c", "core.hooksPath=", "commit", "-qm", "测试提交")
    return git(repository, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    repository.mkdir()
    git(repository, "init", "-q")
    git(repository, "config", "user.name", "test")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "config", "commit.gpgsign", "false")
    shutil.copyfile(ROOT / "risk.yml", repository / "risk.yml")
    write(repository, "app.py", "value = 1\n")
    write(repository, "docs/说明.md", "原有文档\n")
    write(repository, "src/tandem/core/example.py", "protected = True\n")
    write(repository, "tests/test_app.py", "def test_app():\n    assert 1\n    assert 2\n")
    commit(repository)
    return repository


def invoke(
    repository: Path, *args: str, use_event: bool = False
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("GITHUB_EVENT_PATH", None)
    if use_event:
        env["GITHUB_EVENT_PATH"] = str(repository.parent / "event.json")
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=repository,
        env=env,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )


def check_report(repository: Path, expected_level: str, rule: str) -> dict:
    result = invoke(repository, "--base", "HEAD~1", "--head", "HEAD", "--summary", "report.md")
    assert result.returncode == (3 if expected_level == "D" else 0), result.stderr
    report = json.loads((repository / "risk-level.json").read_text(encoding="utf-8"))
    assert report["level"] == expected_level
    assert report["needs_manual"] == (expected_level == "D")
    assert report["secret_scan"] == "未扫描"
    assert rule in result.stdout
    assert f"PR 风险等级：{expected_level}" in result.stdout
    assert (repository / "report.md").read_text(encoding="utf-8") == result.stdout
    assert report["base"] == git(repository, "rev-parse", "HEAD~1")
    assert report["head"] == git(repository, "rev-parse", "HEAD")
    return report


@pytest.mark.parametrize("path", ["app.py", "docs/说明.md", "docs/guide.md", "中文代码.py"])
def test_ordinary_and_document_changes_are_c(repository: Path, path: str) -> None:
    write(repository, path, "新内容\n")
    commit(repository)
    report = check_report(repository, "C", "普通仓库改动")
    assert report["files"][0]["paths"] == [path]
    assert report["bottom_lines"] == []


@pytest.mark.parametrize(
    ("path", "pattern"),
    [
        (".github/workflows/risk-gate.yml", ".github/**"),
        ("risk.yml", "risk.yml"),
        ("src/tandem/core/example.py", "src/tandem/core/**"),
        ("pyproject.toml", "pyproject.toml"),
        ("uv.lock", "uv.lock"),
        ("requirements-dev.txt", "requirements*.txt"),
        ("package.json", "package.json"),
        ("scripts/gate/example.py", "scripts/gate/**"),
    ],
)
def test_protected_paths_are_d(repository: Path, path: str, pattern: str) -> None:
    if path == "risk.yml":
        with (repository / path).open("a", encoding="utf-8") as stream:
            stream.write("\n# 配置变更\n")
    else:
        write(repository, path, "changed\n")
    commit(repository)
    report = check_report(repository, "D", f"底线路径：{pattern}")
    assert any(pattern in rule for rule in report["files"][0]["rules"])


def test_deleted_file_is_d(repository: Path) -> None:
    (repository / "app.py").unlink()
    commit(repository)
    report = check_report(repository, "D", "底线动作：删除文件")
    assert report["files"][0]["action"] == "删除"


def test_fewer_assertions_is_d(repository: Path) -> None:
    write(repository, "tests/test_app.py", "def test_app():\n    assert 1\n")
    commit(repository)
    report = check_report(repository, "D", "测试断言总数减少 2 → 1")
    assert "测试断言减少：2 → 1" in report["files"][0]["rules"][0]


def test_renaming_protected_file_into_docs_is_d(repository: Path) -> None:
    git(repository, "mv", "src/tandem/core/example.py", "docs/已移动.md")
    commit(repository)
    report = check_report(repository, "D", "改名规则：新旧路径同时参与判断")
    assert report["files"][0]["paths"] == ["src/tandem/core/example.py", "docs/已移动.md"]
    assert any("src/tandem/core/**" in rule for rule in report["bottom_lines"])


def test_default_revisions_use_pr_event(repository: Path) -> None:
    base = git(repository, "rev-parse", "HEAD")
    write(repository, "app.py", "value = 2\n")
    head = commit(repository)
    event = {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}
    (repository.parent / "event.json").write_text(json.dumps(event), encoding="utf-8")
    result = invoke(repository, use_event=True)
    assert result.returncode == 0, result.stderr
    report = json.loads((repository / "risk-level.json").read_text(encoding="utf-8"))
    assert (report["base"], report["head"], report["level"]) == (base, head, "C")


def test_no_changes_is_a(repository: Path) -> None:
    result = invoke(repository, "--base", "HEAD", "--head", "HEAD")
    assert result.returncode == 0, result.stderr
    report = json.loads((repository / "risk-level.json").read_text(encoding="utf-8"))
    assert report["level"] == "A"
    assert report["files"] == []


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("--base", "HEAD"),
        ("--base", "HEAD", "--head", "missing"),
        ("--base", "--help", "--head", "HEAD"),
    ],
)
def test_input_errors_do_not_pass(repository: Path, args: tuple[str, ...]) -> None:
    result = invoke(repository, *args)
    assert result.returncode == 2
    assert not (repository / "risk-level.json").exists()


def test_help_discloses_limitations(repository: Path) -> None:
    result = invoke(repository, "--help")
    assert result.returncode == 0
    assert "分支保护" in result.stdout
    assert "D 级必须人工批准" in result.stdout
    assert "未扫描" in result.stdout
