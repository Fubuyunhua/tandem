"""K1/K2：只用必需检查裁决 CI，使用内存响应替换整个 gh 进程。"""

import subprocess
from dataclasses import replace

import pytest

from tandem.shell import cli
from tandem.shell.config import ConfigError, load_config, parse_config
from tandem.shell.github import CIState, FakeGitHub, GhGitHub, GitHubError
from tests.shell.test_github_transport import SHA, FakeGhProcess


def _response(
    monkeypatch: pytest.MonkeyPatch,
    checks: list[dict[str, object]],
    statuses: list[object] | None = None,
) -> None:
    process = FakeGhProcess(
        FakeGitHub(),
        replies={
            f"commits/{SHA}/check-runs?per_page=100&filter=latest": [{"check_runs": checks}],
            f"commits/{SHA}/statuses?per_page=100": statuses or [[]],
        },
    )
    monkeypatch.setattr(subprocess, "run", process.run)


def _check(name: str, conclusion: str = "success", status: str = "completed") -> dict[str, object]:
    return {"name": name, "status": status, "conclusion": conclusion}


def test_nonrequired_risk_level_failure_does_not_block_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _response(monkeypatch, [_check("check"), _check("risk-level", "failure")])
    assert GhGitHub("owner/repo").get_ci(SHA) is CIState.GREEN


def test_nonrequired_status_failure_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    _response(monkeypatch, [_check("check")], [[{"context": "risk-level", "state": "failure"}]])
    assert GhGitHub("owner/repo").get_ci(SHA) is CIState.GREEN


def test_missing_required_check_cannot_be_green(monkeypatch: pytest.MonkeyPatch) -> None:
    _response(monkeypatch, [_check("optional")])
    assert GhGitHub("owner/repo").get_ci(SHA) is CIState.PENDING


@pytest.mark.parametrize("conclusion", ["skipped", "neutral"])
def test_required_check_must_succeed(monkeypatch: pytest.MonkeyPatch, conclusion: str) -> None:
    _response(monkeypatch, [_check("check", conclusion)])
    assert GhGitHub("owner/repo").get_ci(SHA) is CIState.RED


def test_all_configured_names_must_appear(monkeypatch: pytest.MonkeyPatch) -> None:
    _response(monkeypatch, [_check("check")])
    client = GhGitHub("owner/repo", required_checks=("check", "lint"))
    assert client.get_ci(SHA) is CIState.PENDING
    _response(monkeypatch, [_check("check", "failure")])
    assert client.get_ci(SHA) is CIState.PENDING  # 缺一个仍为 PENDING，不能过早结束本轮验收。
    _response(monkeypatch, [_check("check"), _check("lint")])
    assert client.get_ci(SHA) is CIState.GREEN


def test_required_checks_can_mix_runs_and_latest_statuses(monkeypatch: pytest.MonkeyPatch) -> None:
    _response(
        monkeypatch,
        [_check("check")],
        [[{"context": "lint", "state": "success"}], [{"context": "lint", "state": "failure"}]],
    )
    assert GhGitHub("owner/repo", required_checks=("check", "lint")).get_ci(SHA) is CIState.GREEN


def test_duplicate_name_cannot_hide_a_failed_required_run(monkeypatch: pytest.MonkeyPatch) -> None:
    _response(monkeypatch, [_check("check"), _check("check", "failure")])
    assert GhGitHub("owner/repo").get_ci(SHA) is CIState.RED


def test_cli_github_factory_uses_configured_names(monkeypatch: pytest.MonkeyPatch) -> None:
    config = replace(load_config(), required_checks=("lint",))
    monkeypatch.setattr(cli, "load_config", lambda: config)
    _response(monkeypatch, [_check("check", "failure"), _check("lint")])
    assert cli._github_client("owner/repo").get_ci(SHA) is CIState.GREEN


def test_required_checks_configuration_default_and_override() -> None:
    base = {"run_mode": "single_agent", "providers": [{"name": "claude"}]}
    assert parse_config(base).required_checks == ("check",)
    assert load_config().required_checks == ("check",)
    assert parse_config({**base, "required_checks": ["check", "lint"]}).required_checks == (
        "check",
        "lint",
    )


@pytest.mark.parametrize(
    "names", [[], None, "check", [""], [" "], [" check"], [1], ["check", "check"]]
)
def test_invalid_required_checks_are_rejected(names: object) -> None:
    with pytest.raises(ConfigError, match="required_checks"):
        parse_config(
            {
                "run_mode": "single_agent",
                "providers": [{"name": "claude"}],
                "required_checks": names,
            }
        )


@pytest.mark.parametrize("names", [(), ("",), ("check", "check")])
def test_client_cannot_disable_required_checks(names: tuple[str, ...]) -> None:
    with pytest.raises(GitHubError):
        GhGitHub("owner/repo", required_checks=names)


@pytest.mark.parametrize("command", ["poll", "approve"])
def test_cli_passes_required_checks_for_polling_and_writes(
    tmp_path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    from tandem.core.model import TaskRecord, TaskStatus
    from tandem.shell.github import PullRequest
    from tandem.shell.store import GitHubSource, Store

    names: list[tuple[str, ...]] = []
    config = replace(load_config(), required_checks=("lint",))
    monkeypatch.setattr(cli, "load_config", lambda: config)
    github = FakeGitHub(prs={8: PullRequest(8, SHA)}, checks={SHA: CIState.GREEN})

    def client(repo: str, *, required_checks: tuple[str, ...] = ("check",)) -> FakeGitHub:
        assert repo == "owner/repo"
        names.append(required_checks)
        return github

    monkeypatch.setattr(cli, "GhGitHub", client)
    db = tmp_path / "cli.sqlite3"
    if command == "poll":
        assert cli.main(["poll", "--db", str(db), "--repo", "owner/repo"]) == 0
    else:
        with Store(db) as store:
            store.commit(
                task=TaskRecord(
                    "gh-7", status=TaskStatus.AWAITING_YOUR_REVIEW, latest_sha=SHA, ci_green=True
                )
            )
            store.save_github_source(GitHubSource("gh-7", "owner/repo", 7, "", "", 8))
        assert cli.main(["approve", "--db", str(db), "--task-id", "gh-7", "--sha", SHA]) == 0
    assert names == [("lint",)]
    assert github.writes == []
