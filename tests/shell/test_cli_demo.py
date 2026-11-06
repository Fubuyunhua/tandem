"""命令行测试：demo 端到端跑通，submit / status / cancel 能配合工作。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tandem.shell.cli import main
from tandem.shell.diff_source import FakeDiffSource
from tandem.shell.receipt import parse_receipt
from tandem.shell.store import Store


def test_demo_prints_both_scenarios(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "场景 1" in out
    assert "场景 2" in out
    # 场景 1：C 级走到已合并
    assert "demo-c" in out
    assert "已合并" in out
    # 场景 2：D 级停在待你批准方案
    assert "demo-d" in out
    assert "待你批准方案" in out
    # 全部是 dry-run，没有调用真实 AI
    assert "dry-run" in out
    assert "没有调用任何真实 AI" in out


def test_demo_has_no_side_effects(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """demo 用临时数据库，不会碰工作目录里的 data/。"""
    before = set(Path.cwd().iterdir())
    assert main(["demo"]) == 0
    capsys.readouterr()
    assert set(Path.cwd().iterdir()) == before


def test_submit_then_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "tandem.sqlite3"
    assert main(["submit", "--db", str(db), "--task-id", "t1", "--paths", "docs/note.md"]) == 0
    submit_out = capsys.readouterr().out
    assert "等级 C" in submit_out

    assert main(["status", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "t1" in out
    assert "待处理" in out


def test_submit_core_path_is_d_level(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "tandem.sqlite3"
    assert (
        main(["submit", "--db", str(db), "--task-id", "t1", "--paths", "src/tandem/core/model.py"])
        == 0
    )
    out = capsys.readouterr().out
    assert "等级 D" in out


def test_submit_secret_scan_hit_is_d_level(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "tandem.sqlite3"
    assert main(["submit", "--db", str(db), "--task-id", "t1", "--secret-scan-hit"]) == 0
    out = capsys.readouterr().out
    assert "等级 D" in out


def test_submit_twice_reports_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "tandem.sqlite3"
    main(["submit", "--db", str(db), "--task-id", "t1", "--paths", "docs/a.md"])
    capsys.readouterr()
    assert main(["submit", "--db", str(db), "--task-id", "t1"]) == 1
    assert "提交失败" in capsys.readouterr().out


def test_cancel_pending_task(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "tandem.sqlite3"
    main(["submit", "--db", str(db), "--task-id", "t1", "--paths", "docs/a.md"])
    capsys.readouterr()
    assert main(["cancel", "--db", str(db), "--task-id", "t1"]) == 0
    assert "已取消" in capsys.readouterr().out
    assert main(["status", "--db", str(db)]) == 0
    assert "已取消" in capsys.readouterr().out


def test_approve_when_not_needed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "tandem.sqlite3"
    main(["submit", "--db", str(db), "--task-id", "t1", "--paths", "docs/a.md"])
    capsys.readouterr()
    assert main(["approve", "--db", str(db), "--task-id", "t1", "--sha", "abc"]) == 1
    assert "不需要你批准" in capsys.readouterr().out


def test_approve_unknown_task(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "tandem.sqlite3"
    assert main(["approve", "--db", str(db), "--task-id", "ghost", "--sha", "abc"]) == 1
    assert "没有任务" in capsys.readouterr().out


def test_status_without_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["status", "--db", str(tmp_path / "nope.sqlite3")]) == 1
    assert "还没有数据库" in capsys.readouterr().out


def test_missing_subcommand_exits() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_approve_plan_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """D 级任务交回方案后，用 tandem approve 批准，任务回到待处理。"""
    from tandem.core.model import Event, EventKind, Level
    from tests.shell.shell_helpers import make_runner, plan_receipt

    db = tmp_path / "tandem.sqlite3"
    runner = make_runner(db, [plan_receipt("t1", plan="先写内核，再接外壳")])
    runner.submit("t1", Level.D)
    runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))
    runner.handle(Event(kind=EventKind.PLAN_SUBMITTED, task_id="t1", plan="先写内核，再接外壳"))
    loaded = runner.store.load_task("t1")
    assert loaded is not None
    assert loaded.status.value == "待你批准方案"
    runner.store.close()

    assert main(["approve", "--db", str(db), "--task-id", "t1", "--sha", "abc"]) == 0
    out = capsys.readouterr().out
    assert "待处理" in out
    assert "你批准了第 1 版方案" in out


def test_utf8_output_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """F14：重定向输出时 Python 会用系统代码页，中文会乱码，入口要显式设成 UTF-8。"""
    import io

    from tandem.shell import cli

    raw_out = io.BytesIO()
    raw_err = io.BytesIO()
    out = io.TextIOWrapper(raw_out, encoding="cp936", errors="strict")
    err = io.TextIOWrapper(raw_err, encoding="cp936", errors="strict")
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)

    cli._configure_utf8_output()

    assert out.encoding.lower() == "utf-8"
    assert err.encoding.lower() == "utf-8"
    print("中文输出")
    out.flush()
    assert "中文输出" in raw_out.getvalue().decode("utf-8")


def test_main_configures_utf8_before_running(monkeypatch: pytest.MonkeyPatch) -> None:
    from tandem.shell import cli

    called: list[str] = []
    monkeypatch.setattr(cli, "_configure_utf8_output", lambda: called.append("utf8"))
    assert cli.main(["demo"]) == 0
    assert called == ["utf8"]


def test_default_risk_mode_is_single_agent() -> None:
    """F10：M1 只有 Claude，默认必须是单 Agent 模式；demo 自己显式开多 Agent。"""
    from tandem.core.model import RunMode
    from tandem.shell.config import load_config

    assert load_config().run_mode is RunMode.SINGLE_AGENT


def test_demo_fails_when_a_scenario_does_not_reach_expected_state(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """F10：场景没走到预期状态时，demo 必须返回非零，不能假报成功。"""
    from dataclasses import replace

    from tandem.core.model import RunMode
    from tandem.shell.cli import _demo_policy, run_demo
    from tandem.shell.config import load_policy

    # 故意用单 Agent 模式跑：场景 1 会停在"待你审核"，走不到"已合并"
    broken = replace(load_policy(), run_mode=RunMode.SINGLE_AGENT)
    assert _demo_policy().run_mode is RunMode.MULTI_AGENT
    assert run_demo(policy_=broken) != 0
    out = capsys.readouterr().out
    assert "场景 1" in out
    assert "失败" in out


def test_approve_sends_your_approval_when_waiting_for_you(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """F8：待你审核要发 YOUR_APPROVAL，不能发成交给"待你介入"的那个事件。"""
    from tandem.core.model import RunMode, TaskStatus
    from tests.shell.shell_helpers import advance_to_your_review, code_receipt, make_runner

    db = tmp_path / "tandem.sqlite3"
    runner = make_runner(db, [code_receipt("t1")], run_mode=RunMode.SINGLE_AGENT)
    task = advance_to_your_review(runner)
    assert task.status is TaskStatus.AWAITING_YOUR_REVIEW
    runner.store.close()

    assert (
        main(["approve", "--db", str(db), "--task-id", "t1", "--sha", task.latest_sha or ""]) == 0
    )
    out = capsys.readouterr().out
    assert "待合并" in out

    with Store(db) as store:
        loaded = store.load_task("t1")
        assert loaded is not None
        assert loaded.status is TaskStatus.AWAITING_MERGE


def test_approve_returns_nonzero_when_kernel_ignores_event(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """F8：内核忽略事件时，CLI 不能假报成功。"""
    from tests.shell.shell_helpers import advance_to_needs_intervention, code_receipt, make_runner

    db = tmp_path / "tandem.sqlite3"
    runner = make_runner(db, [code_receipt("t1", attempt=i, sha=f"{i}" * 40) for i in (1, 2, 3)])
    task = advance_to_needs_intervention(runner)
    assert task.error_code == "R01"
    runner.store.close()

    # CI 是红的，人工审核通过会被内核拒绝
    assert (
        main(
            [
                "approve",
                "--db",
                str(db),
                "--task-id",
                "t1",
                "--sha",
                task.latest_sha or "",
                "--reason",
                "我看过了",
            ]
        )
        != 0
    )
    out = capsys.readouterr().out
    assert "没有生效" in out
    assert "CI" in out


def test_reject_returns_nonzero_when_kernel_ignores_event(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from tandem.core.model import RunMode
    from tests.shell.shell_helpers import advance_to_your_review, code_receipt, make_runner

    db = tmp_path / "tandem.sqlite3"
    runner = make_runner(db, [code_receipt("t1")], run_mode=RunMode.SINGLE_AGENT)
    advance_to_your_review(runner)
    runner.store.close()

    # 待你审核只能打回一次；第二次已经没有可打回的状态了
    assert main(["reject", "--db", str(db), "--task-id", "t1", "--reason", "不行"]) == 0
    capsys.readouterr()
    assert main(["reject", "--db", str(db), "--task-id", "t1", "--reason", "再不行"]) != 0


def test_approve_with_wrong_sha_does_not_approve(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """F4：批准绑定你看到的提交编号；对不上就不生效。"""
    from tandem.core.model import RunMode, TaskStatus
    from tests.shell.shell_helpers import advance_to_your_review, code_receipt, make_runner

    db = tmp_path / "tandem.sqlite3"
    runner = make_runner(db, [code_receipt("t1")], run_mode=RunMode.SINGLE_AGENT)
    advance_to_your_review(runner)
    runner.store.close()

    assert main(["approve", "--db", str(db), "--task-id", "t1", "--sha", "另一个提交"]) != 0
    out = capsys.readouterr().out
    assert "没有生效" in out
    assert "提交编号" in out

    with Store(db) as store:
        loaded = store.load_task("t1")
        assert loaded is not None
        assert loaded.status is TaskStatus.AWAITING_YOUR_REVIEW


def test_approve_requires_sha_argument(tmp_path: Path) -> None:
    """F4：approve 必须带 --sha，漏了就由 argparse 直接报错。"""
    with pytest.raises(SystemExit):
        main(["approve", "--db", str(tmp_path / "x.sqlite3"), "--task-id", "t1"])


def test_approve_with_veto_requires_every_finding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """F13：人工否决 AI 意见时要按意见编号逐条给理由，缺一条就不生效。"""
    from tandem.core.model import Event, EventKind, Finding, TaskStatus, Verdict
    from tests.core.helpers import CODE_CHANGES, review_event
    from tests.shell.shell_helpers import (
        advance_to_needs_intervention,
        code_receipt,
        make_runner,
    )

    db = tmp_path / "tandem.sqlite3"
    runner = make_runner(db, [code_receipt("t1", attempt=i, sha=f"{i}" * 40) for i in (1, 2, 3)])
    record = advance_to_needs_intervention(runner)
    # 你接手，提交代码，CI 绿，AI 打回并给了两条意见
    record = runner.handle(Event(kind=EventKind.TAKE_OVER, task_id="t1")).decision.task
    record = runner.handle(
        Event(
            kind=EventKind.YOU_SUBMITTED_CODE,
            task_id="t1",
            sha="f" * 40,
            changes=CODE_CHANGES,
        )
    ).decision.task
    record = runner.handle(Event(kind=EventKind.CI_GREEN, task_id="t1", sha="f" * 40)).decision.task
    record = runner.handle(
        Event(
            kind=EventKind.REVIEW,
            task_id="t1",
            review=review_event(
                record,
                "codex",
                Verdict.FAIL,
                findings=(Finding(id="F1", text="缺测试"), Finding(id="F2", text="没用参数")),
            ).review,
        )
    ).decision.task
    assert record.status is TaskStatus.NEEDS_INTERVENTION
    sha = record.latest_sha or ""
    # 意见的键是复合键：提供方 + 提交编号 + 标准版本 + 本地编号
    keys = {finding.local_id: finding.key for finding in record.open_findings}
    assert set(keys) == {"F1", "F2"}
    runner.store.close()

    # 只答一条 → 不生效，并打印还缺哪一条
    assert (
        main(
            [
                "approve",
                "--db",
                str(db),
                "--task-id",
                "t1",
                "--sha",
                sha,
                "--veto",
                f"{keys['F1']}=这条补了测试",
            ]
        )
        != 0
    )
    out = capsys.readouterr().out
    assert keys["F2"] in out
    assert "没有生效" in out

    # 两条都答 → 生效
    assert (
        main(
            [
                "approve",
                "--db",
                str(db),
                "--task-id",
                "t1",
                "--sha",
                sha,
                "--veto",
                f"{keys['F1']}=这条补了测试",
                "--veto",
                f"{keys['F2']}=时间是从参数传的",
            ]
        )
        == 0
    )
    assert "待合并" in capsys.readouterr().out


def test_approve_d_level_task_from_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """F8：单 Agent 模式下 D 级任务也要能从 CLI 放行（CI 绿 + 审核都过）。"""
    from tandem.core.model import Event, EventKind, Level, RunMode, TaskStatus
    from tests.core.helpers import CORE_CHANGES, SHA_2
    from tests.shell.shell_helpers import code_receipt, make_runner, plan_receipt

    db = tmp_path / "tandem.sqlite3"
    runner = make_runner(
        db,
        [plan_receipt("t1"), code_receipt("t1", attempt=2, sha=SHA_2)],
        run_mode=RunMode.SINGLE_AGENT,
        # D 级任务改的是 core：采集器说真实改动就是 core
        diff_source=FakeDiffSource(changes=CORE_CHANGES),
    )
    runner.submit("t1", Level.D)
    started = runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))
    plan = parse_receipt(started.receipts[0])
    runner.handle(Event(kind=EventKind.PLAN_SUBMITTED, task_id="t1", sha=plan.sha, plan=plan.plan))
    runner.handle(Event(kind=EventKind.PLAN_APPROVED, task_id="t1", sha=plan.sha))
    started = runner.handle(Event(kind=EventKind.ASSIGN, task_id="t1", provider="claude"))
    receipt = parse_receipt(started.receipts[0])
    task = runner.store.load_task("t1")
    assert task is not None
    runner.handle(runner.code_event(task, receipt))
    runner.handle(Event(kind=EventKind.CI_GREEN, task_id="t1", sha=receipt.sha))
    task = runner.store.load_task("t1")
    assert task is not None
    assert task.status is TaskStatus.AWAITING_YOUR_REVIEW
    assert task.level is Level.D
    assert task.designated_reviewers == ()  # 单 Agent 模式没有 AI 审核
    runner.store.close()

    assert main(["approve", "--db", str(db), "--task-id", "t1", "--sha", receipt.sha]) == 0
    capsys.readouterr()
    with Store(db) as store:
        loaded = store.load_task("t1")
        assert loaded is not None
        assert loaded.status is TaskStatus.AWAITING_MERGE
