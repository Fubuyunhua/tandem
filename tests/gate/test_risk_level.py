"""从真实临时 Git 仓库启动命令行闸门，验证裁决、解释与退出码。"""

from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tandem.core.level import bottom_line_reasons
from tandem.core.model import ChangeSet
from tandem.shell.config import parse_config
from tandem.shell.diff_source import GitDiffSource

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
    "path",
    [
        ".github/workflows/risk-gate.yml",
        "risk.yml",
        "src/tandem/core/example.py",
        "pyproject.toml",
        "uv.lock",
        "requirements-dev.txt",
        "package.json",
        "scripts/gate/example.py",
    ],
)
def test_protected_paths_are_d(repository: Path, path: str) -> None:
    if path == "risk.yml":
        with (repository / path).open("a", encoding="utf-8") as stream:
            stream.write("\n# 配置变更\n")
    else:
        write(repository, path, "changed\n")
    commit(repository)
    reason = f"改动了底线条目相关的路径 {path}"
    report = check_report(repository, "D", reason)
    assert report["files"][0]["rules"] == [reason]


def test_deleted_file_is_d(repository: Path) -> None:
    (repository / "app.py").unlink()
    commit(repository)
    report = check_report(repository, "D", "删除了文件 app.py")
    assert report["files"][0]["action"] == "删除"


def test_fewer_assertions_is_d(repository: Path) -> None:
    write(repository, "tests/test_app.py", "def test_app():\n    assert 1\n")
    commit(repository)
    reason = "测试文件 tests/test_app.py 的断言从 2 条减到 1 条"
    report = check_report(repository, "D", reason)
    assert report["files"][0]["rules"] == [reason]


def test_renaming_protected_file_into_docs_is_d(repository: Path) -> None:
    git(repository, "mv", "src/tandem/core/example.py", "docs/已移动.md")
    commit(repository)
    report = check_report(repository, "D", "改名规则：新旧路径同时参与判断")
    assert report["files"][0]["paths"] == ["src/tandem/core/example.py", "docs/已移动.md"]
    assert "改动了底线条目相关的路径 src/tandem/core/example.py" in report["bottom_lines"]
    assert report["files"][0]["rules"][-1] == ("改名规则：新旧路径同时参与判断，本次命中底线，判 D")


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
    assert report["files"][0]["rules"] == ["改名规则：新旧路径同时参与判断，本次未命中底线，判 C"]


def test_cross_file_assertion_increases_do_not_cancel_drops(repository: Path) -> None:
    """一个文件新增断言不能抵消另一个文件的减少，即使合计持平也判 D。"""
    write(repository, "tests/test_app.py", "def test_app():\n    assert 1\n")
    write(repository, "tests/test_new.py", "def test_new():\n    assert True\n")
    commit(repository)
    reason = "测试文件 tests/test_app.py 的断言从 2 条减到 1 条"
    report = check_report(repository, "D", reason)
    assert report["assertions_before"] == report["assertions_after"] == 2
    assert report["bottom_lines"] == [reason]
    assert report["files"][0]["rules"] == [reason]
    assert report["assertion_drops"] == [
        {"path": "tests/test_app.py", "before": 2, "after": 1, "previous_path": None}
    ]


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
    report = check_report(repository, "D", "改动了底线条目相关的路径 src/tandem/core/example.py")
    assert report["policy_source"] == f"{report['base']}:risk.yml"
    assert "改动了底线条目相关的路径 risk.yml" in report["bottom_lines"]


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
    assert "改动了底线条目相关的路径 scripts/gate/risk_level.py" in report["bottom_lines"]


def test_report_uses_core_reasons_for_renames_and_deletions(repository: Path) -> None:
    """改名的断言减少与删除都沿用内核的解释，并归到对应文件。"""
    git(repository, "mv", "tests/test_app.py", "tests/test_renamed.py")
    write(repository, "tests/test_renamed.py", "def test_app():\n    assert 1\n")
    (repository / "app.py").unlink()
    commit(repository)
    reason = "测试文件 tests/test_app.py 改名为 tests/test_renamed.py 的断言从 2 条减到 1 条"
    report = check_report(repository, "D", reason)
    changes = GitDiffSource(cwd=repository).collect("HEAD~1", "HEAD").changes
    policy = parse_config(yaml.safe_load(git(repository, "show", "HEAD~1:risk.yml"))).policy
    assert report["bottom_lines"] == list(bottom_line_reasons(changes, policy))
    by_action = {file["action"]: file for file in report["files"]}
    assert by_action["删除"]["rules"] == ["删除了文件 app.py"]
    assert reason in by_action["改名"]["rules"]
    assert "删除了文件 app.py" not in by_action["改名"]["rules"]


def test_deleted_test_reports_both_drop_and_deletion(repository: Path) -> None:
    (repository / "tests/test_app.py").unlink()
    commit(repository)
    reason = "测试文件 tests/test_app.py 的断言从 2 条减到 0 条（文件被删除）"
    report = check_report(repository, "D", reason)
    assert report["files"][0]["rules"] == [reason, "删除了文件 tests/test_app.py"]
    assert report["bottom_lines"] == report["files"][0]["rules"]


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
    fetch = next(step for step in job["steps"] if "git fetch" in step.get("run", ""))
    assert fetch["env"]["PR_HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    assert fetch["env"]["PR_NUMBER"] == "${{ github.event.pull_request.number }}"
    assert (
        'fetch --no-tags --no-recurse-submodules origin "refs/pull/${PR_NUMBER}/head"'
        in fetch["run"]
    )
    assert "FETCH_TOKEN" not in fetch["env"]
    assert "http.extraheader" not in fetch["run"]
    assert "github.token" not in str(fetch)
    assert all("${{" not in step.get("run", "") for step in job["steps"])
    sync = next(step for step in job["steps"] if "uv sync" in step.get("run", ""))
    assert sync["run"] == "uv sync --locked"
    assert job["steps"].index(checkout) < job["steps"].index(fetch) < job["steps"].index(sync)
    gate = next(step for step in job["steps"] if "risk_level.py" in step.get("run", ""))
    assert "continue-on-error" not in gate
    assert "||" not in gate["run"]
    summary = next(step for step in job["steps"] if "GITHUB_STEP_SUMMARY" in step.get("run", ""))
    assert summary["if"] == "always()"


@pytest.mark.parametrize(
    ("action", "paths"),
    [("修改或新增", ("app.py",)), ("删除", ("app.py",)), ("改名", ("app.py", "docs/app.py"))],
)
@pytest.mark.parametrize("secret_scan_hit", [False, True])
def test_file_explanations_preserve_global_secret_scan(
    action: str, paths: tuple[str, ...], secret_scan_hit: bool
) -> None:
    """扫描只有整批命中标志；每条文件解释都保留它，不冒充文件级定位。"""
    entry = runpy.run_path(str(SCRIPT))
    policy = parse_config(yaml.safe_load((ROOT / "risk.yml").read_text(encoding="utf-8"))).policy
    changes = ChangeSet(
        paths=("app.py", "other.py"),
        deleted_paths=("app.py",),
        renames=(("app.py", "docs/app.py"),),
        secret_scan_hit=secret_scan_hit,
    )
    file = entry["explain_file"](changes, policy, paths, action)
    assert ("密钥扫描命中" in file.rules) is secret_scan_hit
    summary_reasons = set(bottom_line_reasons(changes, policy))
    reasons = {rule for rule in file.rules if not rule.startswith(("改名规则：", "普通仓库改动："))}
    assert reasons <= summary_reasons


def test_judge_setup_uv_is_pinned() -> None:
    workflow = yaml.load(
        (ROOT / ".github/workflows/risk-gate.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    setup = [
        step["uses"]
        for step in workflow["jobs"]["risk-level"]["steps"]
        if "setup-uv@" in step.get("uses", "")
    ]
    assert setup == ["astral-sh/setup-uv@d0cc045d04ccac9d8b7881df0226f9e82c39688e"]


def windows_bash() -> Path | None:
    """Git for Windows 自带的 Bash。

    `which git` 可能是 `<Git>/cmd/git.exe`，也可能是从 Git Bash 里跑出来的
    `<Git>/mingw64/bin/git.exe`；两种都要能反推出 Git 根，再依次试
    `<Git>/bin/bash.exe` 与 `<Git>/usr/bin/bash.exe`。
    """
    git_executable = shutil.which("git")
    if git_executable is None:
        return None
    git_path = Path(git_executable).resolve()
    # git 可能在 <Git>/cmd/git.exe，也可能在 <Git>/mingw64/bin/git.exe，
    # 所以往上找三层，每层都试 bin/bash.exe 与 usr/bin/bash.exe。
    for root in git_path.parents[:3]:
        for candidate in (root / "bin/bash.exe", root / "usr/bin/bash.exe"):
            if candidate.is_file():
                return candidate
    return None


def run_workflow_fetch(
    repository: Path, number: str, head: str
) -> subprocess.CompletedProcess[str]:
    """离线执行 YAML 的原始 Bash 步骤，沿用 Actions 的遇错即停设置。"""
    workflow = yaml.load(
        (ROOT / ".github/workflows/risk-gate.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    step = next(
        step
        for step in workflow["jobs"]["risk-level"]["steps"]
        if "git fetch" in step.get("run", "")
    )
    if os.name == "nt":
        found = windows_bash()
        assert found is not None, "测试需要 Git for Windows 自带的 Bash"
        bash = found
    else:
        executable = shutil.which("bash")
        assert executable is not None
        bash = Path(executable)
    return subprocess.run(
        [str(bash), "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=repository,
        env=dict(os.environ, PR_NUMBER=number, PR_HEAD_SHA=head, GIT_TERMINAL_PROMPT="0"),
        capture_output=True,
        encoding="utf-8",
        check=False,
    )


@pytest.fixture
def fork_pr(repository: Path) -> tuple[Path, str, str]:
    """模拟 base 远端仅在 refs/pull/17/head 发布 fork 提交；全程本地路径。"""
    base = git(repository, "rev-parse", "HEAD")
    remote = repository.parent / "origin.git"
    remote.mkdir()
    git(remote, "init", "--bare", "-q")
    git(repository, "remote", "add", "origin", str(remote))
    git(repository, "push", "-q", "origin", f"{base}:refs/heads/main")
    fork = repository.parent / "fork"
    git(repository, "clone", "-q", "--no-local", str(repository), str(fork))
    git(fork, "config", "user.name", "test")
    git(fork, "config", "user.email", "test@example.com")
    git(fork, "config", "commit.gpgsign", "false")
    write(
        fork,
        "scripts/gate/risk_level.py",
        "from pathlib import Path\nPath('head-executed').touch()\n",
    )
    head = commit(fork)
    git(fork, "push", "-q", str(remote), f"{head}:refs/pull/17/head")
    missing = subprocess.run(
        ["git", "cat-file", "-e", head], cwd=repository, capture_output=True, check=False
    )
    assert missing.returncode != 0
    return repository, base, head


def test_workflow_fetches_fork_pull_ref_without_checkout(fork_pr: tuple[Path, str, str]) -> None:
    repository, base, head = fork_pr
    result = run_workflow_fetch(repository, "17", head)
    assert result.returncode == 0, result.stderr
    assert "refs/pull/17/head" in result.stderr
    assert git(repository, "rev-parse", "FETCH_HEAD") == head
    assert git(repository, "rev-parse", "HEAD") == base
    assert not (repository / "head-executed").exists()
    assert not (repository / "scripts/gate/risk_level.py").exists()
    # 取到的对象可交给可信脚本判断，head 中的恶意脚本仍不执行。
    gate = invoke(repository, "--base", base, "--head", head)
    assert gate.returncode == 3, gate.stderr
    assert not (repository / "head-executed").exists()


@pytest.mark.parametrize("case", ["bad_number", "bad_sha", "missing_ref", "changed_head"])
def test_workflow_fetch_fails_closed(fork_pr: tuple[Path, str, str], case: str) -> None:
    repository, base, head = fork_pr
    number = "17"
    if case == "bad_number":
        number = "17; touch injected"
    elif case == "bad_sha":
        head = "$(touch injected)"
    elif case == "missing_ref":
        number = "18"
    else:
        head = base
    result = run_workflow_fetch(repository, number, head)
    assert result.returncode != 0
    assert git(repository, "rev-parse", "HEAD") == base
    assert not (repository / "injected").exists()
    assert not (repository / "head-executed").exists()


@pytest.mark.parametrize("decrease_assertions", [False, True])
def test_attributes_do_not_hide_assertion_drops(
    repository: Path, decrease_assertions: bool
) -> None:
    write(repository, ".gitattributes", "tests/*.py -diff\n")
    if decrease_assertions:
        write(repository, "tests/test_app.py", "def test_app():\n    assert 1\n")
    commit(repository)
    # .gitattributes 本身在底线里（PR #8），所以不管断言少没少都是 D；
    # 这里要守住的是：-diff 属性不能把断言减少藏起来。
    report = check_report(
        repository,
        "D",
        "测试文件 tests/test_app.py 的断言从 2 条减到 1 条"
        if decrease_assertions
        else ".gitattributes",
    )
    assert any(".gitattributes" in reason for reason in report["bottom_lines"])
    if decrease_assertions:
        assert report["assertion_drops"] == [
            {"path": "tests/test_app.py", "before": 2, "after": 1, "previous_path": None}
        ]
    else:
        assert report["assertion_drops"] == []


@pytest.mark.parametrize("base_protects_app", [False, True])
def test_policy_source_is_latest_base_not_common_ancestor(
    repository: Path, base_protects_app: bool
) -> None:
    policy = yaml.safe_load((repository / "risk.yml").read_text(encoding="utf-8"))
    original_paths = list(policy["bottom_line_paths"])
    policy["bottom_line_paths"] = original_paths + ([] if base_protects_app else ["app.py"])
    write(repository, "risk.yml", yaml.safe_dump(policy))
    ancestor = commit(repository)
    policy["bottom_line_paths"] = original_paths + (["app.py"] if base_protects_app else [])
    write(repository, "risk.yml", yaml.safe_dump(policy))
    base = commit(repository)
    git(repository, "checkout", "-qb", "review-policy", ancestor)
    write(repository, "app.py", "value = 2\n")
    head = commit(repository)
    result = invoke(repository, "--base", base, "--head", head)
    assert result.returncode == (3 if base_protects_app else 0), result.stderr
    report = json.loads((repository / "risk-level.json").read_text(encoding="utf-8"))
    assert report["merge_base"] == ancestor
    assert report["policy_source"] == f"{base}:risk.yml"
    assert report["level"] == ("D" if base_protects_app else "C")
    assert [file["paths"] for file in report["files"]] == [["app.py"]]
