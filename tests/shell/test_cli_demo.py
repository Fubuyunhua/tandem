"""命令行测试：demo 端到端跑通，submit / status / cancel 能配合工作。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tandem.shell.cli import main


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
    assert main(["approve", "--db", str(db), "--task-id", "t1"]) == 1
    assert "不需要你批准" in capsys.readouterr().out


def test_approve_unknown_task(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "tandem.sqlite3"
    assert main(["approve", "--db", str(db), "--task-id", "ghost"]) == 1
    assert "没有任务" in capsys.readouterr().out


def test_status_without_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["status", "--db", str(tmp_path / "nope.sqlite3")]) == 1
    assert "还没有数据库" in capsys.readouterr().out


def test_missing_subcommand_exits() -> None:
    with pytest.raises(SystemExit):
        main([])
