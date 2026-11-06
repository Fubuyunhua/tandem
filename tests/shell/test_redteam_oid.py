"""回执引用在采集前解析一次，此后只保存完整 OID。"""

import subprocess
from pathlib import Path

from tandem.core.model import Event, EventKind, Level
from tandem.shell.diff_source import GitDiffSource
from tandem.shell.receipt import Receipt
from tests.shell.shell_helpers import make_runner, required


def test_receipt_ref_is_pinned_before_branch_moves(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()

    git("init", "-q")
    git("config", "user.name", "test")
    git("config", "user.email", "test@example.invalid")
    (repo / "a.py").write_text("x = 1\n")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (repo / "a.py").write_text("x = 2\n")
    git("commit", "-qam", "candidate")
    oid = git("rev-parse", "HEAD")
    git("branch", "candidate")
    runner = make_runner(tmp_path / "tasks.sqlite3", diff_source=GitDiffSource(cwd=repo))
    try:
        runner.submit("t1", Level.C, base_sha=base)
        runner.handle(Event(EventKind.ASSIGN, "t1", provider="claude"))
        event = runner.code_event(
            required(runner.store.load_task("t1")), Receipt("DONE", "t1", 1, "candidate")
        )
        assert event.sha == oid
        (repo / "a.py").write_text("x = 3\n")
        git("commit", "-qam", "move")
        git("branch", "-f", "candidate", "HEAD")
        assert event.sha != git("rev-parse", "candidate")
    finally:
        runner.store.close()
