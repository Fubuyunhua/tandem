"""按真实 Git 改动运行等级闸门，只接受规则，不接受模型意见。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from tandem.core.level import bottom_line_reasons, compute_level
from tandem.core.model import ChangeSet, Level, Policy
from tandem.shell.config import ConfigError, parse_config
from tandem.shell.diff_source import DiffError, GitDiffSource

MANUAL_EXIT_CODE = 3
ERROR_EXIT_CODE = 2
LIMITATIONS = (
    "工作流使用 pull_request_target，从 base 运行裁判代码和依赖；"
    "head 仅作为 Git 数据读取，risk.yml 固定读取 base 提交。"
    "分支保护和 D 级必须人工批准仍需配置；D 级退出码保持 3，批准后变绿机制待用户决定。"
    "密钥扫描尚未接入，结果标明未扫描。"
)


@dataclass(frozen=True)
class FileResult:
    """一处改动的路径、动作及规则解释。"""

    paths: tuple[str, ...]
    action: str
    rules: tuple[str, ...]


def git(repository: Path, *args: str) -> str:
    """只读本地 Git；失败时拒绝给出可放行的等级。"""
    result = subprocess.run(["git", *args], cwd=repository, capture_output=True, check=False)
    if result.returncode:
        raise DiffError(result.stderr.decode("utf-8", "replace").strip())
    return result.stdout.decode("utf-8", "surrogateescape").strip()


def resolve_commit(repository: Path, revision: str) -> str:
    """固定为提交编号，避免把引用当作 Git 选项或让引用在采集中变化。"""
    return git(repository, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}")


def pr_revisions() -> tuple[str, str]:
    """默认取 GitHub PR 事件中的 base/head，不使用合并提交 GITHUB_SHA。"""
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise ValueError("请同时指定 --base 和 --head，或提供 PR 的 GITHUB_EVENT_PATH")
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    try:
        base = event["pull_request"]["base"]["sha"]
        head = event["pull_request"]["head"]["sha"]
    except (KeyError, TypeError) as error:
        raise ValueError("事件缺少 PR base/head 提交编号") from error
    if not isinstance(base, str) or not isinstance(head, str) or not base or not head:
        raise ValueError("PR base/head 必须是非空字符串")
    return base, head


def explain_file(
    changes: ChangeSet,
    policy: Policy,
    paths: tuple[str, ...],
    action: str,
) -> FileResult:
    """只选取本文件的采集数据，底线解释统一交给内核。"""
    file_changes = ChangeSet(
        paths=paths if action == "修改或新增" else (),
        deleted_paths=paths if action == "删除" else (),
        renames=((paths[0], paths[1]),) if action == "改名" else (),
        assertion_drops=tuple(drop for drop in changes.assertion_drops if drop.path == paths[-1]),
    )
    rules = list(bottom_line_reasons(file_changes, policy))
    if action == "改名":
        rules.append("改名规则：新旧路径同时参与判断，取更严格级别")
    if not rules:
        rules.append("普通仓库改动：C；纯文档也不接受模型降级")
    return FileResult(paths=paths, action=action, rules=tuple(rules))


def build_report(repository: Path, base: str, head: str) -> dict[str, object]:
    """采集实际改动，用内核裁决并生成可追溯报告。"""
    base = resolve_commit(repository, base)
    head = resolve_commit(repository, head)
    # 不读取工作树或 head 的规则，防止 PR 删除底线后给自己降级。
    try:
        policy = parse_config(yaml.safe_load(git(repository, "show", f"{base}:risk.yml"))).policy
    except yaml.YAMLError as error:
        raise ConfigError(f"{base}:risk.yml 不是合法的 YAML：{error}") from error
    collected = GitDiffSource(cwd=repository).collect(base, head)
    changes = collected.changes
    level = compute_level(changes, policy)
    merge_base = git(repository, "merge-base", base, head)
    entries: list[tuple[str, tuple[str, ...]]] = [("修改或新增", (p,)) for p in changes.paths]
    entries.extend(("删除", (p,)) for p in changes.deleted_paths)
    entries.extend(("改名", pair) for pair in changes.renames)
    files = [explain_file(changes, policy, paths, action) for action, paths in entries]
    return {
        "base": base,
        "policy_source": f"{base}:risk.yml",
        "head": head,
        "merge_base": merge_base,
        "level": level.value,
        "needs_manual": level is Level.D,
        "secret_scan": collected.secret_scan.value,
        "bottom_lines": list(bottom_line_reasons(changes, policy)),
        "assertions_before": changes.assertions_before,
        "assertions_after": changes.assertions_after,
        "assertion_drops": [asdict(drop) for drop in changes.assertion_drops],
        "files": [asdict(file) for file in files],
        "limitations": LIMITATIONS,
    }


def render_report(report: dict[str, object]) -> str:
    """把 JSON 内容放在 Markdown 代码块内，路径不能注入 summary 标记。"""
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    fence = "```"
    # 围栏取比全文最长反引号串更长的长度，兼容任意合法文件名。
    while fence in payload:
        fence += "`"
    status = "需要人工" if report["needs_manual"] else "规则检查通过"
    return f"## PR 风险等级：{report['level']}（{status}）\n\n{fence}json\n{payload}\n{fence}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"退出码：A/B/C=0；D={MANUAL_EXIT_CODE}（需要人工）；错误=2。{LIMITATIONS}",
    )
    parser.add_argument("--base", help="基线提交；默认取 PR base.sha")
    parser.add_argument("--head", help="待审提交；默认取 PR head.sha")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="仓库路径，默认当前目录")
    parser.add_argument(
        "--output", type=Path, default=Path("risk-level.json"), help="JSON 输出路径"
    )
    parser.add_argument("--summary", type=Path, help="额外写入 Markdown 报告的路径")
    args = parser.parse_args(argv)
    if bool(args.base) != bool(args.head):
        parser.error("--base 和 --head 必须同时指定")
    try:
        base, head = (args.base, args.head) if args.base else pr_revisions()
        report = build_report(args.repo, base, head)
        rendered = render_report(report)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if args.summary:
            args.summary.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
    except (ConfigError, DiffError, OSError, ValueError) as error:
        print(f"等级闸门失败：{error}", file=sys.stderr)
        return ERROR_EXIT_CODE
    return MANUAL_EXIT_CODE if report["needs_manual"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
