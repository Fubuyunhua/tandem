"""Runner 使用已加载的受信策略，候选文件不能给当前任务降级。"""

from pathlib import Path

import yaml

from tandem.core.model import ChangeSet, Event, EventKind, Level, TaskStatus
from tandem.shell.config import DEFAULT_RISK_PATH, load_policy
from tandem.shell.diff_source import FakeDiffSource
from tandem.shell.receipt import parse_receipt
from tests.shell.shell_helpers import code_receipt, make_runner, required


def test_policy_boundary_is_documented() -> None:
    readme = DEFAULT_RISK_PATH.with_name("README.md").read_text(encoding="utf-8")
    assert "审核候选改动必须使用受信版本的策略" in readme
    assert "Runner 不从候选工作树重载 risk.yml" in readme


def test_candidate_policy_cannot_change_running_task(tmp_path: Path) -> None:
    candidate = tmp_path / "risk.yml"
    original = DEFAULT_RISK_PATH.read_text(encoding="utf-8")
    candidate.write_text(original, encoding="utf-8")
    runner = make_runner(
        tmp_path,
        [code_receipt()],
        diff_source=FakeDiffSource(
            changes=ChangeSet(paths=("src/tandem/core/model.py",)),
        ),
    )
    trusted = runner.policy
    try:
        runner.submit("t1", Level.C)
        started = runner.handle(Event(EventKind.ASSIGN, "t1", provider="claude"))
        data = yaml.safe_load(original)
        data["bottom_line_paths"] = []
        candidate.write_text(yaml.safe_dump(data), encoding="utf-8")
        assert load_policy(candidate).bottom_line_paths == ()
        receipt = parse_receipt(started.receipts[0])
        result = runner.handle(runner.code_event(required(runner.store.load_task("t1")), receipt))
        assert runner.policy is trusted
        assert result.decision.task.level is Level.D
        assert result.decision.task.status is TaskStatus.AWAITING_PLAN_APPROVAL
    finally:
        runner.store.close()
