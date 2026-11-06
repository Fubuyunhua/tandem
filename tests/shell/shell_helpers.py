"""外壳测试公用工具：造 Runner、造回执、造改动采集器。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from tandem.core.model import Policy, RunMode
from tandem.shell.agents.base import AgentAdapter
from tandem.shell.agents.fake import FakeAgent
from tandem.shell.config import load_policy
from tandem.shell.diff_source import DiffSource, FakeDiffSource
from tandem.shell.executor import Executor
from tandem.shell.receipt import render_receipt
from tandem.shell.runner import Runner
from tandem.shell.store import Store
from tests.core.helpers import CODE_CHANGES, SHA_1

NOW = datetime(2026, 11, 7, 9, 30, tzinfo=UTC)


def code_receipt(
    task_id: str = "t1", attempt: int = 1, sha: str = SHA_1, conclusion: str = "DONE：写完了"
) -> str:
    """一份只带必填字段的代码回执（改动由采集器提供，回执里不写 changes）。"""
    return render_receipt(conclusion, {"task_id": task_id, "attempt": attempt, "sha": sha})


def plan_receipt(
    task_id: str = "t1", attempt: int = 1, sha: str = "plan-sha", plan: str = "先写内核"
) -> str:
    return render_receipt(
        "PLAN：先交方案",
        {"task_id": task_id, "attempt": attempt, "sha": sha, "plan": plan},
    )


def multi_agent_policy() -> Policy:
    """多 Agent 模式：转换表里大部分条目都在这个模式下才会发生。"""
    return replace(load_policy(), run_mode=RunMode.MULTI_AGENT)


def single_agent_policy() -> Policy:
    """M1 的真实配置。"""
    return replace(load_policy(), run_mode=RunMode.SINGLE_AGENT)


def make_runner(
    db: Path,
    script: list[str] | None = None,
    *,
    run_mode: RunMode = RunMode.MULTI_AGENT,
    dry_run: bool = True,
    agents: dict[str, AgentAdapter] | None = None,
    diff_source: DiffSource | None = None,
) -> Runner:
    agent = FakeAgent(provider="claude", script=script if script is not None else [])
    # 传目录就自动放一个库文件，传文件就用它
    store = Store(db / "tandem.sqlite3" if db.is_dir() else db)
    executor = Executor(
        agents={"claude": agent} if agents is None else agents,
        dry_run=dry_run,
    )
    return Runner(
        store=store,
        policy=replace(load_policy(), run_mode=run_mode),
        executor=executor,
        diff_source=(
            diff_source if diff_source is not None else FakeDiffSource(changes=CODE_CHANGES)
        ),
        clock=lambda: NOW,
    )
