"""读取 `risk.yml`，转成内核用的 `Policy`。

这是外壳的一部分：读文件属于外部交互，内核只接收解析好的数据。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

from tandem.core.model import Level, LevelRule, Policy, RunMode, Thresholds

# 仓库根目录：src/tandem/shell/config.py -> 上三级
DEFAULT_RISK_PATH = Path(__file__).resolve().parents[3] / "risk.yml"


class ConfigError(ValueError):
    """risk.yml 有问题。"""


@dataclass(frozen=True)
class ProviderSpec:
    """一家模型提供方，以及它能干什么。"""

    name: str
    can_write: bool = True
    can_review: bool = True


@dataclass(frozen=True)
class Config:
    """外壳读出来的配置：内核用的 Policy + 提供方清单。"""

    policy: Policy
    providers: tuple[ProviderSpec, ...]
    run_mode: RunMode


def _mapping(data: object, name: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ConfigError(f"{name} 必须是一个映射")
    source = cast("dict[object, object]", data)
    result: dict[str, Any] = {}
    for key, value in source.items():
        if not isinstance(key, str):
            raise ConfigError(f"{name} 的键必须是字符串")
        result[key] = value
    return result


def _optional_mapping(data: object, name: str) -> dict[str, Any]:
    """允许整节缺席，缺席时当作空映射。"""
    if data is None:
        return {}
    return _mapping(data, name)


def _list(data: object, name: str) -> list[object]:
    if not isinstance(data, list):
        raise ConfigError(f"{name} 必须是列表")
    source = cast("list[object]", data)
    return source


def _str_list(data: object, name: str) -> tuple[str, ...]:
    if data is None:
        return ()
    items: list[str] = []
    for value in _list(data, name):
        if not isinstance(value, str):
            raise ConfigError(f"{name} 里有非字符串的条目")
        items.append(value)
    return tuple(items)


def _int_value(data: object, name: str, default: int) -> int:
    if data is None:
        return default
    if isinstance(data, bool) or not isinstance(data, int):
        raise ConfigError(f"{name} 必须是整数")
    return data


def _bool_value(data: object, name: str, default: bool) -> bool:
    if data is None:
        return default
    if not isinstance(data, bool):
        raise ConfigError(f"{name} 必须是 true 或 false")
    return data


def _run_mode(data: object) -> RunMode:
    text = data if isinstance(data, str) else ""
    match text:
        case "single_agent":
            return RunMode.SINGLE_AGENT
        case "multi_agent":
            return RunMode.MULTI_AGENT
        case _:
            raise ConfigError("run_mode 只能是 single_agent 或 multi_agent")


def _providers(data: object) -> tuple[ProviderSpec, ...]:
    if data is None:
        raise ConfigError("providers 不能为空：至少要有一家能写代码")
    items: list[ProviderSpec] = []
    for entry in _list(data, "providers"):
        item = _mapping(entry, "providers[]")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise ConfigError("providers[] 缺少 name")
        items.append(
            ProviderSpec(
                name=name,
                can_write=_bool_value(item.get("can_write"), f"providers[{name}].can_write", True),
                can_review=_bool_value(
                    item.get("can_review"), f"providers[{name}].can_review", True
                ),
            )
        )
    if not items:
        raise ConfigError("providers 里至少要有一家")
    names = [item.name for item in items]
    if len(set(names)) != len(names):
        raise ConfigError("providers 里有重名的提供方")
    return tuple(items)


def _level_rules(data: object, thresholds: Thresholds) -> tuple[LevelRule, ...]:
    mapping = _optional_mapping(data, "levels")
    rules: list[LevelRule] = []
    for key, value in mapping.items():
        try:
            level = Level(key)
        except ValueError as error:
            raise ConfigError(f"levels 里有未知的等级 {key}") from error
        item = _mapping(value, f"levels.{key}")
        rules.append(
            LevelRule(
                level=level,
                requires_plan_approval=_bool_value(
                    item.get("plan_approval"), f"levels.{key}.plan_approval", False
                ),
                requires_ai_review=_bool_value(
                    item.get("ai_review"), f"levels.{key}.ai_review", True
                ),
                requires_human_merge=_bool_value(
                    item.get("human_merge"), f"levels.{key}.human_merge", False
                ),
                min_reviewers=_int_value(
                    item.get("min_reviewers"),
                    f"levels.{key}.min_reviewers",
                    thresholds.required_reviewers,
                ),
            )
        )
    return tuple(rules)


def parse_config(data: object) -> Config:
    """把已经读进来的 YAML 数据转成 Config，方便单独测试。"""
    root = _mapping(data, "risk.yml")
    raw_thresholds = _optional_mapping(root.get("thresholds"), "thresholds")
    thresholds = Thresholds(
        required_reviewers=_int_value(
            raw_thresholds.get("required_reviewers"),
            "thresholds.required_reviewers",
            2,
        ),
        max_accept_failures=_int_value(
            raw_thresholds.get("max_accept_failures"),
            "thresholds.max_accept_failures",
            3,
        ),
        max_revisions=_int_value(
            raw_thresholds.get("max_revisions"),
            "thresholds.max_revisions",
            3,
        ),
    )
    providers = _providers(root.get("providers"))
    default_writer = root.get("default_writer")
    writer_names = [item.name for item in providers if item.can_write]
    if not isinstance(default_writer, str) or not default_writer:
        if not writer_names:
            raise ConfigError("没有能写代码的提供方")
        default_writer = writer_names[0]
    if default_writer not in writer_names:
        raise ConfigError(f"default_writer={default_writer} 不是能写代码的提供方")

    run_mode = _run_mode(root.get("run_mode"))
    policy = Policy(
        bottom_line_paths=_str_list(root.get("bottom_line_paths"), "bottom_line_paths"),
        relaxable_paths=_str_list(root.get("relaxable_paths"), "relaxable_paths"),
        providers=tuple(item.name for item in providers),
        writer_providers=tuple(item.name for item in providers if item.can_write),
        reviewer_providers=tuple(item.name for item in providers if item.can_review),
        default_writer=default_writer,
        run_mode=run_mode,
        thresholds=thresholds,
        level_rules=_level_rules(root.get("levels"), thresholds),
    )
    return Config(policy=policy, providers=providers, run_mode=run_mode)


def load_config(path: Path | None = None) -> Config:
    """读 risk.yml。文件不存在或格式不对都抛 ConfigError。"""
    target = path if path is not None else DEFAULT_RISK_PATH
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(f"读不到 {target}：{error}") from error
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigError(f"{target} 不是合法的 YAML：{error}") from error
    return parse_config(data)


def load_policy(path: Path | None = None) -> Policy:
    """只要内核用的 Policy。"""
    return load_config(path).policy
