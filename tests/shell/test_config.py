"""risk.yml 的读取测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tandem.core.model import Level, RunMode
from tandem.shell.config import ConfigError, load_config, load_policy, parse_config


def test_load_repository_risk_yml() -> None:
    config = load_config()
    assert config.run_mode is RunMode.MULTI_AGENT
    assert [provider.name for provider in config.providers] == ["claude", "codex", "opencode-go"]
    assert config.policy.default_writer == "claude"
    assert "core/**" in config.policy.bottom_line_paths
    assert "docs/**" in config.policy.relaxable_paths
    assert config.policy.thresholds.required_reviewers == 2


def test_level_rules_come_from_config() -> None:
    policy = load_policy()
    rule_d = policy.rule_for(Level.D)
    assert rule_d.requires_plan_approval
    assert rule_d.requires_human_merge
    rule_c = next(rule for rule in policy.level_rules if rule.level is Level.C)
    assert rule_c.requires_ai_review
    assert not rule_c.requires_human_merge


def test_load_policy_from_custom_file(tmp_path: Path) -> None:
    target = tmp_path / "risk.yml"
    target.write_text(
        "run_mode: single_agent\nproviders:\n  - name: claude\nbottom_line_paths:\n  - 'core/**'\n",
        encoding="utf-8",
    )
    policy = load_policy(target)
    assert policy.run_mode is RunMode.SINGLE_AGENT
    assert policy.default_writer == "claude"


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yml")


def test_bad_run_mode_raises() -> None:
    with pytest.raises(ConfigError):
        parse_config({"run_mode": "swarm", "providers": [{"name": "claude"}]})


def test_missing_providers_raises() -> None:
    with pytest.raises(ConfigError):
        parse_config({"run_mode": "multi_agent", "providers": []})


def test_default_writer_must_be_able_to_write() -> None:
    with pytest.raises(ConfigError):
        parse_config(
            {
                "run_mode": "multi_agent",
                "default_writer": "ghost",
                "providers": [{"name": "claude"}],
            }
        )


def test_unknown_level_raises() -> None:
    with pytest.raises(ConfigError):
        parse_config(
            {
                "run_mode": "multi_agent",
                "providers": [{"name": "claude"}],
                "levels": {"E": {"ai_review": True}},
            }
        )
