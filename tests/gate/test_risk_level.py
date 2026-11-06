"""从真实临时 Git 仓库启动命令行闸门，验证裁决、解释与退出码。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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


def test_ordinary_rename_uses_existing_core_semantics(repository: Path) -> None:
    """内核不会把普通改名直接判 D；受保护旧路径的场景另有测试。"""
    git(repository, "mv", "app.py", "docs/app.py")
    commit(repository)
    report = check_report(repository, "C", "改名规则：新旧路径同时参与判断")
    assert report["bottom_lines"] == []
    assert report["files"][0]["paths"] == ["app.py", "docs/app.py"]


def test_reports_existing_cross_file_assertion_limitation(repository: Path) -> None:
    """复现 task-001 的合计抵消遗漏，保留既有裁决并如实解释。"""
    write(repository, "tests/test_app.py", "def test_app():\n    assert 1\n")
    write(repository, "tests/test_new.py", "def test_new():\n    assert True\n")
    commit(repository)
    report = check_report(repository, "C", "测试断言减少：2 → 1")
    assert report["assertions_before"] == report["assertions_after"] == 2
    assert report["bottom_lines"] == []


@pytest.mark.parametrize("event", [{}, {"pull_request": []}, {"pull_request": {"base": {}}}])
def test_invalid_pr_event_does_not_pass(repository: Path, event: object) -> None:
    (repository.parent / "event.json").write_text(json.dumps(event), encoding="utf-8")
    result = invoke(repository, use_event=True)
    assert result.returncode == 2
    assert "事件缺少 PR base/head" in result.stderr
    assert not (repository / "risk-level.json").exists()


def test_diverged_base_uses_common_ancestor(repository: Path) -> None:
    ancestor = git(repository, "rev-parse", "HEAD")
    write(repository, "app.py", "base_only = True\n")
    base = commit(repository)
    git(repository, "checkout", "-qb", "review", ancestor)
    write(repository, "docs/说明.md", "仅待审分支的改动\n")
    head = commit(repository)
    result = invoke(repository, "--base", base, "--head", head)
    assert result.returncode == 0, result.stderr
    report = json.loads((repository / "risk-level.json").read_text(encoding="utf-8"))
    assert report["merge_base"] == ancestor
    assert report["files"][0]["paths"] == ["docs/说明.md"]
    assert len(report["files"]) == 1


def test_head_cannot_remove_base_bottom_lines(repository: Path) -> None:
    """PR 同时删空底线、改受保护文件，仍按 base 的每条底线判 D。"""
    policy = yaml.safe_load((repository / "risk.yml").read_text(encoding="utf-8"))
    policy["bottom_line_paths"] = []
    write(repository, "risk.yml", yaml.safe_dump(policy))
    write(repository, "src/tandem/core/example.py", "protected = False\n")
    commit(repository)
    report = check_report(repository, "D", "底线路径：src/tandem/core/**")
    assert report["policy_source"] == f"{report['base']}:risk.yml"
    assert any("底线路径：risk.yml" in rule for rule in report["bottom_lines"])


@pytest.mark.parametrize("base_policy", [None, "invalid: ["])
def test_bad_base_policy_cannot_be_replaced_by_head(
    repository: Path, base_policy: str | None
) -> None:
    """base 规则缺失或损坏就报错，不能改读 head 的可用规则。"""
    if base_policy is None:
        (repository / "risk.yml").unlink()
    else:
        write(repository, "risk.yml", base_policy)
    commit(repository)
    shutil.copyfile(ROOT / "risk.yml", repository / "risk.yml")
    commit(repository)
    result = invoke(repository, "--base", "HEAD~1", "--head", "HEAD")
    assert result.returncode == 2
    assert "等级闸门失败" in result.stderr
    assert not (repository / "risk-level.json").exists()


def test_trusted_base_checkout_never_executes_head(repository: Path) -> None:
    """模拟工作流的 base 工作树；恶意 head 的入口、导入和依赖都只能当数据。"""
    shutil.copytree(
        ROOT / "src" / "tandem",
        repository / "src" / "tandem",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    write(repository, "scripts/gate/risk_level.py", SCRIPT.read_text(encoding="utf-8"))
    shutil.copyfile(ROOT / "pyproject.toml", repository / "pyproject.toml")
    shutil.copyfile(ROOT / "uv.lock", repository / "uv.lock")
    base = commit(repository)
    malicious = "from pathlib import Path\nPath('head-executed').touch()\nraise SystemExit(0)\n"
    write(repository, "scripts/gate/risk_level.py", malicious)
    write(repository, "src/tandem/__init__.py", malicious)
    write(repository, "pyproject.toml", "invalid: head build must never run\n")
    write(repository, "uv.lock", "invalid: head lock must never be loaded\n")
    write(repository, "risk.yml", "bottom_line_paths: []\n")
    head = commit(repository)
    # head 对象留在对象库，工作树只检出 base；用 PYTHONPATH 显式导入 base 的包。
    git(repository, "checkout", "-q", "--detach", base)
    result = subprocess.run(
        [sys.executable, "scripts/gate/risk_level.py", "--base", base, "--head", head],
        cwd=repository,
        env=dict(os.environ, PYTHONPATH=str(repository / "src"), PYTHONIOENCODING="utf-8"),
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 3, result.stderr
    assert not (repository / "head-executed").exists()
    report = json.loads((repository / "risk-level.json").read_text(encoding="utf-8"))
    assert report["level"] == "D"
    assert report["policy_source"] == f"{base}:risk.yml"
    assert git(repository, "rev-parse", "HEAD") == base
    assert (repository / "uv.lock").read_text(encoding="utf-8") == (ROOT / "uv.lock").read_text(
        encoding="utf-8"
    )
    assert any("scripts/gate/**" in rule for rule in report["bottom_lines"])


def test_workflow_keeps_gate_read_only_and_blocking() -> None:
    """保护触发器、最小权限和失败语义，避免接线改变闸门的安全契约。"""
    # BaseLoader 不会按 YAML 1.1 把 GitHub 的 on 关键字当作布尔值。
    workflow = yaml.load(
        (ROOT / ".github/workflows/risk-gate.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]) == {"pull_request_target"}
    assert workflow["permissions"] == {"contents": "read"}
    assert len(workflow["jobs"]) == 1
    job = workflow["jobs"]["risk-level"]
    assert job["name"] == "risk-level"
    assert "permissions" not in job
    assert "continue-on-error" not in job
    checkouts = [step for step in job["steps"] if "checkout@" in step.get("uses", "")]
    assert len(checkouts) == 1
    checkout = checkouts[0]
    assert checkout["with"]["fetch-depth"] == "0"
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.base.sha }}"
    assert checkout["with"]["persist-credentials"] == "false"
    fetch = next(step for step in job["steps"] if "git -c" in step.get("run", ""))
    assert fetch["env"]["PR_HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    assert 'fetch --no-tags --no-recurse-submodules origin "$PR_HEAD_SHA"' in fetch["run"]
    assert all("${{" not in step.get("run", "") for step in job["steps"])
    sync = next(step for step in job["steps"] if "uv sync" in step.get("run", ""))
    assert sync["run"] == "uv sync --locked"
    assert job["steps"].index(checkout) < job["steps"].index(fetch) < job["steps"].index(sync)
    gate = next(step for step in job["steps"] if "risk_level.py" in step.get("run", ""))
    assert "continue-on-error" not in gate
    assert "||" not in gate["run"]
    summary = next(step for step in job["steps"] if "GITHUB_STEP_SUMMARY" in step.get("run", ""))
    assert summary["if"] == "always()"
