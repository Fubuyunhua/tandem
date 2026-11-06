"""本地模拟命令的跨调用集成测试，不调用真实 AI 或 Git。"""

from pathlib import Path

import pytest

from tandem.core.model import QuotaState, TaskRecord, TaskStatus, Verdict
from tandem.shell.cli import main
from tandem.shell.store import Store


def _submit(
    db: Path, task_id: str = "t1", *, mode: str = "single_agent", path: str = "src/x.py"
) -> None:
    assert (
        main(["submit", "--db", str(db), "--task-id", task_id, "--mode", mode, "--paths", path])
        == 0
    )


def _task(db: Path, task_id: str = "t1") -> TaskRecord:
    with Store(db) as store:
        task = store.load_task(task_id)
        assert task is not None
        return task


def _run(db: Path, *options: str) -> int:
    return main(["run", "--db", str(db), *options])


def _approve(db: Path, task: TaskRecord) -> None:
    assert task.latest_sha is not None
    assert (
        main(["approve", "--db", str(db), "--task-id", task.task_id, "--sha", task.latest_sha]) == 0
    )


def test_single_agent_manual_loop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "tasks.sqlite3"
    _submit(db)
    assert _run(db) == 0
    waiting = _task(db)
    assert waiting.status is TaskStatus.AWAITING_YOUR_REVIEW
    assert waiting.ci_green
    assert waiting.reviews == ()
    output = capsys.readouterr().out
    assert "待处理 → 处理中" in output
    assert "处理中 → 待验收" in output
    assert "待验收 → 待你审核" in output
    assert "tandem show" in output
    assert "tandem approve" in output
    assert waiting.latest_sha is not None and waiting.latest_sha in output
    assert main(["show", "t1", "--db", str(db)]) == 0
    _approve(db, waiting)
    assert _task(db).status is TaskStatus.AWAITING_MERGE
    assert _run(db) == 0
    merged = _task(db)
    assert merged.status is TaskStatus.MERGED
    assert merged.latest_sha == waiting.latest_sha == merged.approved_sha
    # 终点重复运行不追加事件或启动写手。
    with Store(db) as store:
        count = len(store.list_events())
    assert _run(db, "--until-idle") == 0
    with Store(db) as store:
        assert len(store.list_events()) == count


def test_multi_agent_failure_then_next_run_passes(tmp_path: Path) -> None:
    db = tmp_path / "tasks.sqlite3"
    _submit(db, mode="multi_agent")
    assert _run(db, "--review", "fail") == 0
    failed = _task(db)
    assert failed.status is TaskStatus.PENDING
    assert failed.attempt == 1  # 普通 run 不在同一轮重派退回的任务。
    assert failed.open_findings
    assert failed.review_history[0].verdict is Verdict.FAIL
    assert _run(db, "--review", "pass") == 0
    merged = _task(db)
    assert merged.status is TaskStatus.MERGED
    assert merged.attempt == 2
    assert merged.latest_sha != failed.latest_sha
    assert merged.open_findings == ()
    assert len(merged.current_reviews()) == 2
    assert all(review.sha == merged.latest_sha for review in merged.current_reviews())
    assert len(merged.review_history) == 3


def test_d_level_waits_for_plan_and_then_for_code_approval(tmp_path: Path) -> None:
    db = tmp_path / "tasks.sqlite3"
    core = "src/tandem/core/model.py"
    _submit(db, path=core)
    assert _run(db, "--changes", core, "--until-idle") == 0
    plan = _task(db)
    assert plan.status is TaskStatus.AWAITING_PLAN_APPROVAL
    assert not plan.ci_green
    assert core in plan.note
    assert _run(db, "--until-idle") == 0
    assert _task(db) == plan  # 人工暂停期间不发任何推进事件。
    _approve(db, plan)
    assert _run(db, "--changes", core) == 0
    code = _task(db)
    assert code.status is TaskStatus.AWAITING_YOUR_REVIEW
    assert code.approved_plan_version == code.plan_version == 1
    _approve(db, code)
    assert _run(db, "--changes", core) == 0
    assert _task(db).status is TaskStatus.MERGED


def test_real_changes_can_upgrade_c_to_d(tmp_path: Path) -> None:
    db = tmp_path / "tasks.sqlite3"
    _submit(db)
    assert _run(db, "--changes", "src/tandem/core/model.py") == 0
    assert _task(db).status is TaskStatus.AWAITING_PLAN_APPROVAL
    assert _task(db).level.value == "D"


@pytest.mark.parametrize(
    ("options", "error_code"),
    [(["--agent-script", "ci-red"], "R01"), (["--review", "fail"], "R02")],
)
def test_until_idle_stops_at_intervention(
    tmp_path: Path, options: list[str], error_code: str
) -> None:
    db = tmp_path / "tasks.sqlite3"
    _submit(db, mode="multi_agent")
    assert _run(db, "--until-idle", *options) == 0
    task = _task(db)
    assert task.status is TaskStatus.NEEDS_INTERVENTION
    assert task.error_code == error_code
    assert task.attempt == 3


def test_max_rounds_reports_unfinished_loop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "tasks.sqlite3"
    _submit(db, mode="multi_agent")
    assert _run(db, "--until-idle", "--max-rounds", "1", "--review", "fail") == 2
    assert _task(db).status is TaskStatus.PENDING
    assert _task(db).attempt == 1
    assert "达到最大轮数 1" in capsys.readouterr().out


def test_no_progress_is_idle_even_when_pending(tmp_path: Path) -> None:
    db = tmp_path / "tasks.sqlite3"
    _submit(db)
    with Store(db) as store:
        store.save_quota("claude", QuotaState.EXHAUSTED)
    assert _run(db, "--until-idle", "--max-rounds", "2") == 0
    task = _task(db)
    assert task.status is TaskStatus.PENDING
    assert task.attempt == 0


def test_refusal_after_failed_review_keeps_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "tasks.sqlite3"
    _submit(db, mode="multi_agent")
    assert _run(db, "--review", "fail") == 0
    findings = _task(db).open_findings
    assert _run(db, "--agent-script", "refuse") == 0
    task = _task(db)
    assert task.status is TaskStatus.NEEDS_INTERVENTION
    assert task.open_findings == findings
    assert main(["show", "t1", "--db", str(db)]) == 0
    output = capsys.readouterr().out
    assert findings[0].key in output
    assert task.latest_sha is not None and task.latest_sha in output
    assert "模拟审核意见" in output
    assert "--veto" in output


def test_run_drives_other_tasks_past_a_human_stop(tmp_path: Path) -> None:
    db = tmp_path / "tasks.sqlite3"
    _submit(db, "human", mode="single_agent")
    _submit(db, "auto", mode="multi_agent")
    assert _run(db, "--until-idle") == 0
    assert _task(db, "human").status is TaskStatus.AWAITING_YOUR_REVIEW
    assert _task(db, "auto").status is TaskStatus.MERGED


def test_run_never_uses_real_agents_git_or_subprocesses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("模拟命令不应调用真实适配器、Git 或外部进程")

    monkeypatch.setattr("tandem.shell.agents.claude_cli.ClaudeCliAgent.run", forbidden)
    monkeypatch.setattr("tandem.shell.diff_source.GitDiffSource.collect", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    db = tmp_path / "tasks.sqlite3"
    _submit(db, mode="multi_agent")
    assert _run(db, "--until-idle") == 0
    assert _task(db).status is TaskStatus.MERGED


@pytest.mark.parametrize("rounds", ["0", "-1", "bad"])
def test_invalid_rounds_rejected_before_creating_database(tmp_path: Path, rounds: str) -> None:
    db = tmp_path / "tasks.sqlite3"
    with pytest.raises(SystemExit):
        _run(db, "--max-rounds", rounds)
    assert not db.exists()
