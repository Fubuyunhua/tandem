"""查看任务与按任务选择模式的命令行测试。"""

from pathlib import Path

import pytest

from tandem.core.model import EventKind, Finding, RunMode, Verdict
from tandem.shell.cli import main
from tandem.shell.store import Store
from tests.core.helpers import ev, review_event, run, to_ai_review


def test_show_displays_full_sha_findings_and_history(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "tasks.sqlite3"
    task = to_ai_review()
    event = review_event(task, "codex", Verdict.FAIL, findings=(Finding("F1", "缺少异常测试"),))
    task = run(task, event).task
    with Store(db) as store:
        store.commit(task=task, events=[ev(EventKind.CREATED), event])
    assert main(["show", "t1", "--db", str(db)]) == 0
    output = capsys.readouterr().out
    assert task.latest_sha is not None
    assert task.latest_sha in output
    assert task.open_findings[0].key in output
    assert "缺少异常测试" in output
    assert '"review_history"' in output
    assert '"state_version"' in output
    assert output.index('"kind": "CREATED"') < output.index('"kind": "REVIEW"')


def test_show_missing_database_does_not_create_it(tmp_path: Path) -> None:
    db = tmp_path / "missing.sqlite3"
    assert main(["show", "unknown", "--db", str(db)]) == 1
    assert not db.exists()


def test_show_missing_task(tmp_path: Path) -> None:
    db = tmp_path / "tasks.sqlite3"
    with Store(db):
        pass
    assert main(["show", "unknown", "--db", str(db)]) == 1


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("single_agent", RunMode.SINGLE_AGENT), ("multi_agent", RunMode.MULTI_AGENT)],
)
def test_submit_mode_is_saved_per_task(tmp_path: Path, mode: str, expected: RunMode) -> None:
    db = tmp_path / "tasks.sqlite3"
    assert main(["submit", "--task-id", "t1", "--mode", mode, "--db", str(db)]) == 0
    with Store(db) as store:
        task = store.load_task("t1")
        assert task is not None
        assert task.run_mode is expected
