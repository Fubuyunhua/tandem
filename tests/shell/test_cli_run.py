"""本地模拟命令的跨调用集成测试，不调用真实 AI 或 Git。"""

from pathlib import Path

import pytest

from tandem.core.model import (
    Action,
    ActionKind,
    ActionStatus,
    EventKind,
    PlanEntry,
    QuotaState,
    TaskRecord,
    TaskStatus,
    Verdict,
)
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
    return main(["run", "--db", str(db), "--changes", "src/x.py", *options])


def _approve(db: Path, task: TaskRecord) -> None:
    assert task.latest_sha is not None
    assert (
        main(["approve", "--db", str(db), "--task-id", task.task_id, "--sha", task.latest_sha]) == 0
    )


def test_single_agent_manual_loop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "tasks.sqlite3"
    _submit(db)
    assert _run(db) == 1
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
    assert _run(db, "--review", "fail") == 1
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
    assert _run(db, "--changes", core, "--until-idle") == 1
    plan = _task(db)
    assert plan.status is TaskStatus.AWAITING_PLAN_APPROVAL
    assert not plan.ci_green
    assert core in plan.note
    assert _run(db, "--until-idle") == 1
    assert _task(db) == plan  # 人工暂停期间不发任何推进事件。
    _approve(db, plan)
    assert _run(db, "--changes", core) == 1
    code = _task(db)
    assert code.status is TaskStatus.AWAITING_YOUR_REVIEW
    assert code.approved_plan_version == code.plan_version == 1
    _approve(db, code)
    assert _run(db, "--changes", core) == 0
    assert _task(db).status is TaskStatus.MERGED


def test_real_changes_can_upgrade_c_to_d(tmp_path: Path) -> None:
    db = tmp_path / "tasks.sqlite3"
    _submit(db)
    assert _run(db, "--changes", "src/tandem/core/model.py") == 1
    assert _task(db).status is TaskStatus.AWAITING_PLAN_APPROVAL
    assert _task(db).level.value == "D"


def test_upgraded_plan_is_visible_and_wrong_sha_cannot_approve(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "tasks.sqlite3"
    _submit(db)
    assert _run(db, "--changes", "src/tandem/core/model.py") == 1
    plan = _task(db)
    entry = plan.plan()
    assert entry is not None
    assert main(["show", "t1", "--db", str(db)]) == 0
    summary = capsys.readouterr().out.split("完整任务记录")[0]
    assert f"没有文字方案，内容就是提交 {entry.sha}" in summary
    assert f"方案提交编号：{entry.sha}" in summary
    assert main(["approve", "--task-id", "t1", "--db", str(db), "--sha", "wrong"]) == 2
    assert _task(db) == plan
    _approve(db, plan)
    assert _task(db).approved_plan_version == plan.plan_version


def test_plan_hint_uses_plan_sha_instead_of_latest_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "tasks.sqlite3"
    with Store(db) as store:
        store.commit(
            task=TaskRecord(
                "t1",
                status=TaskStatus.AWAITING_PLAN_APPROVAL,
                latest_sha="b" * 40,
                plan_version=1,
                plan_history=(PlanEntry(1, "a" * 40, "方案正文"),),
            )
        )
    assert _run(db) == 1
    hint = next(line for line in capsys.readouterr().out.splitlines() if "tandem approve" in line)
    assert "a" * 40 in hint and "b" * 40 not in hint


@pytest.mark.parametrize(
    ("options", "error_code"),
    [(["--agent-script", "ci-red"], "R01"), (["--review", "fail"], "R02")],
)
def test_until_idle_stops_at_intervention(
    tmp_path: Path, options: list[str], error_code: str
) -> None:
    db = tmp_path / "tasks.sqlite3"
    _submit(db, mode="multi_agent")
    assert _run(db, "--until-idle", *options) == 1
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
    assert _run(db, "--until-idle", "--max-rounds", "2") == 1
    task = _task(db)
    assert task.status is TaskStatus.PENDING
    assert task.attempt == 0


def test_refusal_after_failed_review_keeps_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "tasks.sqlite3"
    _submit(db, mode="multi_agent")
    assert _run(db, "--review", "fail") == 1
    findings = _task(db).open_findings
    assert _run(db, "--agent-script", "refuse") == 1
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
    assert _run(db, "--until-idle") == 1
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


@pytest.mark.parametrize("changes", [None, "", "   ", ", ,"])
def test_changes_must_be_explicit_and_nonempty(tmp_path: Path, changes: str | None) -> None:
    db = tmp_path / "missing.sqlite3"
    args = ["run", "--db", str(db)]
    if changes is not None:
        args.extend(["--changes", changes])
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
    assert not db.exists()


def test_run_missing_database_does_not_create_it(tmp_path: Path) -> None:
    db = tmp_path / "missing" / "tasks.sqlite3"
    assert _run(db) == 1
    assert not db.parent.exists()


def test_level_never_drops_after_a_lighter_simulated_change(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """K7：方案批准后只交普通/文档改动，等级仍保持 D，仍要经过"待你审核"。"""
    db = tmp_path / "tasks.sqlite3"
    core = "src/tandem/core/model.py"
    _submit(db, mode="multi_agent", path=core)
    assert _run(db, "--changes", core) == 1  # 停在"待你批准方案"
    _approve(db, _task(db))
    assert _task(db).status is TaskStatus.PENDING

    # 后续只改文档：内核会"算出 C、保持 D"，不能降级后自动合并
    assert _run(db, "--changes", "docs/x.md", "--until-idle") == 1
    task = _task(db)
    assert task.level.value == "D"
    assert task.status is TaskStatus.AWAITING_YOUR_REVIEW
    output = capsys.readouterr().out
    assert "保持 D 级" in output
    assert "等级下降" not in output

    # 显式的降级开关已经删掉，参数不再被接受
    with pytest.raises(SystemExit):
        _run(db, "--allow-level-drop")


@pytest.mark.parametrize(
    "status", [None, ActionStatus.SENT, ActionStatus.UNKNOWN, ActionStatus.DONE]
)
def test_simulated_merge_requires_latest_action_done(
    tmp_path: Path, status: ActionStatus | None, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "tasks.sqlite3"
    # 旧动作 DONE 不能抵消最近一次合并的 UNKNOWN/SENT 或本次动作缺席。
    actions = (
        ()
        if status is None
        else (
            Action("old", ActionKind.MERGE, "t1", status=ActionStatus.DONE),
            Action("current", ActionKind.MERGE, "t1", status=status),
        )
    )
    with Store(db) as store:
        store.commit(
            task=TaskRecord(
                "t1",
                status=TaskStatus.AWAITING_MERGE,
                latest_sha="a" * 40,
                approved_sha="a" * 40,
                ci_green=True,
                actions=actions,
            ),
            actions=actions,
        )
    confirmed = status is ActionStatus.DONE
    assert _run(db, "--until-idle") == (0 if confirmed else 1)
    assert _task(db).status is (TaskStatus.MERGED if confirmed else TaskStatus.AWAITING_MERGE)
    with Store(db) as store:
        assert any(event.kind is EventKind.MERGED for event in store.list_events()) is confirmed
    output = capsys.readouterr().out
    assert ("全部完成" if confirmed else "有 1 个任务卡住") in output
    if not confirmed:
        assert "合并结果未确认" in output


@pytest.mark.parametrize(
    "state, hint",
    [
        (TaskStatus.AWAITING_ACCEPTANCE, "等待当前提交的 CI"),
        (TaskStatus.AWAITING_AI_REVIEW, "等待本轮指定审核者的结论"),
    ],
)
def test_blocked_states_print_next_step_and_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], state: TaskStatus, hint: str
) -> None:
    db = tmp_path / "tasks.sqlite3"
    with Store(db) as store:
        store.commit(task=TaskRecord("t1", status=state))
    assert _run(db, "--until-idle") == 1
    assert hint in capsys.readouterr().out


@pytest.mark.parametrize(
    "mode, path, options",
    [
        ("single_agent", "src/x.py", []),
        ("multi_agent", "src/tandem/core/model.py", []),
        ("multi_agent", "src/x.py", []),
        ("multi_agent", "src/x.py", ["--agent-script", "ci-red"]),
        ("multi_agent", "src/x.py", ["--review", "fail"]),
    ],
)
def test_run_never_emits_human_approval_events(
    tmp_path: Path, mode: str, path: str, options: list[str]
) -> None:
    db = tmp_path / "tasks.sqlite3"
    _submit(db, mode=mode, path=path)
    _run(db, "--changes", path, "--until-idle", *options)
    forbidden = {EventKind.PLAN_APPROVED, EventKind.YOUR_APPROVAL, EventKind.INTERVENTION_APPROVED}
    with Store(db) as store:
        assert not forbidden.intersection(event.kind for event in store.list_events())
