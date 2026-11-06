"""把内核的数据结构和 JSON 互转。

存储层只认 JSON，内核只认 dataclass，所以需要这一层。
外壳可以依赖内核，反过来不行。
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any, cast

from tandem.core.model import (
    Action,
    ActionKind,
    ActionStatus,
    ChangeSet,
    CheckResult,
    Event,
    EventKind,
    Level,
    Review,
    RevisionCount,
    RunMode,
    TaskRecord,
    TaskStatus,
    Verdict,
)


class SerializationError(ValueError):
    """存下来的数据和当前的数据结构对不上。"""


def _mapping(data: object, name: str) -> dict[str, object]:
    if not isinstance(data, dict):
        raise SerializationError(f"{name} 应该是一个对象")
    source = cast("dict[object, object]", data)
    result: dict[str, object] = {}
    for key, value in source.items():
        if not isinstance(key, str):
            raise SerializationError(f"{name} 的键必须是字符串")
        result[key] = value
    return result


def _enum_value[E: Enum](enum_type: type[E], data: object, name: str) -> E:
    if not isinstance(data, str):
        raise SerializationError(f"{name} 应该是枚举名")
    members: dict[str, E] = {member.name: member for member in enum_type}
    if data not in members:
        raise SerializationError(f"{name} 里有未知的枚举名 {data}")
    return members[data]


def _str(data: object, name: str) -> str:
    if not isinstance(data, str):
        raise SerializationError(f"{name} 应该是字符串")
    return data


def _int(data: object, name: str) -> int:
    if isinstance(data, bool) or not isinstance(data, int):
        raise SerializationError(f"{name} 应该是整数")
    return data


def _bool(data: object, name: str) -> bool:
    if not isinstance(data, bool):
        raise SerializationError(f"{name} 应该是 true 或 false")
    return data


def _list(data: object, name: str) -> list[object]:
    if not isinstance(data, list):
        raise SerializationError(f"{name} 应该是列表")
    return list(cast("list[object]", data))


# ---------------------------------------------------------------- ChangeSet / Review


def changes_to_dict(changes: ChangeSet) -> dict[str, object]:
    return {
        "paths": list(changes.paths),
        "deleted_paths": list(changes.deleted_paths),
        "renames": [list(pair) for pair in changes.renames],
        "assertions_before": changes.assertions_before,
        "assertions_after": changes.assertions_after,
        "secret_scan_hit": changes.secret_scan_hit,
    }


def changes_from_dict(data: object) -> ChangeSet:
    mapping = _mapping(data, "changes")
    renames: list[tuple[str, str]] = []
    for pair in _list(mapping.get("renames", []), "changes.renames"):
        items = _list(pair, "changes.renames[]")
        if len(items) != 2:
            raise SerializationError("改名必须是一对路径")
        renames.append((_str(items[0], "改名前"), _str(items[1], "改名后")))
    before = mapping.get("assertions_before")
    after = mapping.get("assertions_after")
    return ChangeSet(
        paths=tuple(_str(item, "changes.paths[]") for item in _list(mapping.get("paths"), "paths")),
        deleted_paths=tuple(
            _str(item, "changes.deleted_paths[]")
            for item in _list(mapping.get("deleted_paths", []), "deleted_paths")
        ),
        renames=tuple(renames),
        assertions_before=None if before is None else _int(before, "assertions_before"),
        assertions_after=None if after is None else _int(after, "assertions_after"),
        secret_scan_hit=_bool(mapping.get("secret_scan_hit", False), "secret_scan_hit"),
    )


def review_to_dict(review: Review) -> dict[str, object]:
    return {
        "reviewer": review.reviewer,
        "provider": review.provider,
        "verdict": review.verdict.name,
        "sha": review.sha,
        "standard_version": review.standard_version,
    }


def review_from_dict(data: object) -> Review:
    mapping = _mapping(data, "review")
    return Review(
        reviewer=_str(mapping.get("reviewer"), "review.reviewer"),
        provider=_str(mapping.get("provider"), "review.provider"),
        verdict=_enum_value(Verdict, mapping.get("verdict"), "review.verdict"),
        sha=_str(mapping.get("sha"), "review.sha"),
        standard_version=_int(mapping.get("standard_version"), "review.standard_version"),
    )


# ---------------------------------------------------------------- Action


def action_to_dict(action: Action) -> dict[str, object]:
    return {
        "action_id": action.action_id,
        "kind": action.kind.name,
        "task_id": action.task_id,
        "detail": action.detail,
        "provider": action.provider,
        "status": action.status.name,
    }


def action_from_dict(data: object) -> Action:
    mapping = _mapping(data, "action")
    provider = mapping.get("provider")
    return Action(
        action_id=_str(mapping.get("action_id"), "action.action_id"),
        kind=_enum_value(ActionKind, mapping.get("kind"), "action.kind"),
        task_id=_str(mapping.get("task_id"), "action.task_id"),
        detail=_str(mapping.get("detail", ""), "action.detail"),
        provider=None if provider is None else _str(provider, "action.provider"),
        status=_enum_value(ActionStatus, mapping.get("status"), "action.status"),
    )


# ---------------------------------------------------------------- TaskRecord


def task_to_dict(task: TaskRecord) -> dict[str, object]:
    return {
        "task_id": task.task_id,
        "status": task.status.name,
        "level": task.level.name,
        "state_version": task.state_version,
        "run_mode": task.run_mode.name,
        "status_before_error": None
        if task.status_before_error is None
        else task.status_before_error.name,
        "error_code": task.error_code,
        "plan_version": task.plan_version,
        "approved_plan_version": task.approved_plan_version,
        "writer": task.writer,
        "writer_is_human": task.writer_is_human,
        "providers_involved": sorted(task.providers_involved),
        "designated_reviewers": list(task.designated_reviewers),
        "reviews": [review_to_dict(review) for review in task.reviews],
        "standard_version": task.standard_version,
        "accept_failures": task.accept_failures,
        "revision_counts": [
            {"standard_version": entry.standard_version, "count": entry.count}
            for entry in task.revision_counts
        ],
        "latest_sha": task.latest_sha,
        "approved_sha": task.approved_sha,
        "ci_green": task.ci_green,
        "pr_opened": task.pr_opened,
        "attempt": task.attempt,
        "base_sha": task.base_sha,
        "returned_from_review": task.returned_from_review,
        "actions": [action_to_dict(action) for action in task.actions],
        "reason": task.reason,
        "note": task.note,
        "updated_at": None if task.updated_at is None else task.updated_at.isoformat(),
    }


def _optional_str(mapping: dict[str, object], key: str) -> str | None:
    value = mapping.get(key)
    return None if value is None else _str(value, key)


def _optional_int(mapping: dict[str, object], key: str) -> int | None:
    value = mapping.get(key)
    return None if value is None else _int(value, key)


def task_from_dict(data: object) -> TaskRecord:
    mapping = _mapping(data, "task")
    before = mapping.get("status_before_error")
    updated_at = mapping.get("updated_at")
    revision_counts: list[RevisionCount] = []
    for entry in _list(mapping.get("revision_counts", []), "revision_counts"):
        item = _mapping(entry, "revision_counts[]")
        revision_counts.append(
            RevisionCount(
                standard_version=_int(item.get("standard_version"), "standard_version"),
                count=_int(item.get("count"), "count"),
            )
        )
    return TaskRecord(
        task_id=_str(mapping.get("task_id"), "task_id"),
        status=_enum_value(TaskStatus, mapping.get("status"), "status"),
        level=_enum_value(Level, mapping.get("level"), "level"),
        state_version=_int(mapping.get("state_version"), "state_version"),
        run_mode=_enum_value(RunMode, mapping.get("run_mode"), "run_mode"),
        status_before_error=(
            None if before is None else _enum_value(TaskStatus, before, "status_before_error")
        ),
        error_code=_optional_str(mapping, "error_code"),
        plan_version=_int(mapping.get("plan_version"), "plan_version"),
        approved_plan_version=_optional_int(mapping, "approved_plan_version"),
        writer=_optional_str(mapping, "writer"),
        writer_is_human=_bool(mapping.get("writer_is_human"), "writer_is_human"),
        providers_involved=frozenset(
            _str(item, "providers_involved[]")
            for item in _list(mapping.get("providers_involved", []), "providers_involved")
        ),
        designated_reviewers=tuple(
            _str(item, "designated_reviewers[]")
            for item in _list(mapping.get("designated_reviewers", []), "designated_reviewers")
        ),
        reviews=tuple(
            review_from_dict(entry) for entry in _list(mapping.get("reviews", []), "reviews")
        ),
        standard_version=_int(mapping.get("standard_version"), "standard_version"),
        accept_failures=_int(mapping.get("accept_failures"), "accept_failures"),
        revision_counts=tuple(revision_counts),
        latest_sha=_optional_str(mapping, "latest_sha"),
        approved_sha=_optional_str(mapping, "approved_sha"),
        ci_green=_bool(mapping.get("ci_green"), "ci_green"),
        pr_opened=_bool(mapping.get("pr_opened"), "pr_opened"),
        attempt=_int(mapping.get("attempt"), "attempt"),
        base_sha=_str(mapping.get("base_sha", ""), "base_sha"),
        returned_from_review=_bool(mapping.get("returned_from_review"), "returned_from_review"),
        actions=tuple(
            action_from_dict(entry) for entry in _list(mapping.get("actions", []), "actions")
        ),
        reason=_str(mapping.get("reason", ""), "reason"),
        note=_str(mapping.get("note", ""), "note"),
        updated_at=None
        if updated_at is None
        else datetime.fromisoformat(_str(updated_at, "updated_at")),
    )


# ---------------------------------------------------------------- Event


def event_to_dict(event: Event) -> dict[str, object]:
    return {
        "kind": event.kind.name,
        "task_id": event.task_id,
        "state_version": event.state_version,
        "attempt": event.attempt,
        "sha": event.sha,
        "changes": None if event.changes is None else changes_to_dict(event.changes),
        "plan": event.plan,
        "review": None if event.review is None else review_to_dict(event.review),
        "reason": event.reason,
        "provider": event.provider,
        "providers": list(event.providers),
        "model_suggestion": None if event.model_suggestion is None else event.model_suggestion.name,
        "check_result": None if event.check_result is None else event.check_result.name,
        "standard_version": event.standard_version,
        "error_code": event.error_code,
    }


def event_from_dict(data: object) -> Event:
    mapping = _mapping(data, "event")
    suggestion = mapping.get("model_suggestion")
    check = mapping.get("check_result")
    changes = mapping.get("changes")
    review = mapping.get("review")
    return Event(
        kind=_enum_value(EventKind, mapping.get("kind"), "event.kind"),
        task_id=_str(mapping.get("task_id"), "event.task_id"),
        state_version=_optional_int(mapping, "state_version"),
        attempt=_optional_int(mapping, "attempt"),
        sha=_optional_str(mapping, "sha"),
        changes=None if changes is None else changes_from_dict(changes),
        plan=_optional_str(mapping, "plan"),
        review=None if review is None else review_from_dict(review),
        reason=_optional_str(mapping, "reason"),
        provider=_optional_str(mapping, "provider"),
        providers=tuple(
            _str(item, "event.providers[]")
            for item in _list(mapping.get("providers", []), "event.providers")
        ),
        model_suggestion=(
            None if suggestion is None else _enum_value(Level, suggestion, "model_suggestion")
        ),
        check_result=None if check is None else _enum_value(CheckResult, check, "check_result"),
        standard_version=_optional_int(mapping, "standard_version"),
        error_code=_optional_str(mapping, "error_code"),
    )


def dumps(data: dict[str, object]) -> str:
    """统一的 JSON 写法：中文不转义，方便直接看日志。"""
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def loads(text: str, name: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise SerializationError(f"{name} 不是合法的 JSON：{error}") from error
