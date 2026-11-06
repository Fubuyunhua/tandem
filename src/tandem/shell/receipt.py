"""解析回执。

回执格式（PRD F4）：第一行写结论，后面附 JSON。
JSON 必须包含 ``task_id``、``attempt``、``sha``，缺任何一个都算无效回执。
另外支持 PRD 里的 ``brief``（what / why / verify / rollback / learn / level）
和外壳收集好的 ``changes``（真实改动，用来重新算等级）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from tandem.core.model import ChangeSet
from tandem.shell.serde import SerializationError, changes_from_dict

REQUIRED_FIELDS = ("task_id", "attempt", "sha")


class ReceiptError(ValueError):
    """回执不合法。"""


@dataclass(frozen=True)
class Brief:
    """PRD F4 新增的 brief 六项。"""

    what: str = ""
    why: str = ""
    verify: str = ""
    rollback: str = ""
    learn: str = ""
    level: str = ""


@dataclass(frozen=True)
class Receipt:
    """一份解析好的回执。"""

    conclusion: str
    task_id: str
    attempt: int
    sha: str
    plan: str = ""
    brief: Brief | None = None
    changes: ChangeSet | None = None
    body: str = ""


def _text(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ReceiptError(f"{name} 必须是字符串")
    return value


def _parse_brief(value: object) -> Brief:
    if not isinstance(value, dict):
        raise ReceiptError("brief 必须是一个对象")
    source: dict[str, object] = {}
    for key, item in cast("dict[object, object]", value).items():
        if not isinstance(key, str):
            raise ReceiptError("brief 的键必须是字符串")
        source[key] = item
    return Brief(
        what=_text(source.get("what", ""), "brief.what"),
        why=_text(source.get("why", ""), "brief.why"),
        verify=_text(source.get("verify", ""), "brief.verify"),
        rollback=_text(source.get("rollback", ""), "brief.rollback"),
        learn=_text(source.get("learn", ""), "brief.learn"),
        level=_text(source.get("level", ""), "brief.level"),
    )


def parse_receipt(text: str) -> Receipt:
    """解析回执原文。不合法就抛 ReceiptError。"""
    lines = text.splitlines()
    if not lines:
        raise ReceiptError("回执是空的")
    conclusion = lines[0].strip()
    if not conclusion:
        raise ReceiptError("回执第一行必须是结论")
    body = "\n".join(lines[1:]).strip()
    if not body:
        raise ReceiptError("回执第一行之后必须附 JSON")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as error:
        raise ReceiptError(f"回执后面的 JSON 不合法：{error}") from error
    if not isinstance(data, dict):
        raise ReceiptError("回执后面的 JSON 必须是一个对象")

    payload: dict[str, object] = {}
    for key, value in cast("dict[object, object]", data).items():
        if not isinstance(key, str):
            raise ReceiptError("回执 JSON 的键必须是字符串")
        payload[key] = value

    missing = [name for name in REQUIRED_FIELDS if name not in payload]
    if missing:
        raise ReceiptError(f"回执缺少必填字段：{'、'.join(missing)}")

    task_id = _text(payload["task_id"], "task_id").strip()
    if not task_id:
        raise ReceiptError("task_id 不能是空的")
    sha = _text(payload["sha"], "sha").strip()
    if not sha:
        raise ReceiptError("sha 不能是空的")
    attempt_value = payload["attempt"]
    if isinstance(attempt_value, bool) or not isinstance(attempt_value, int):
        raise ReceiptError("attempt 必须是整数")
    if attempt_value < 1:
        raise ReceiptError("attempt 必须从 1 开始")

    plan = payload.get("plan", "")
    if not isinstance(plan, str):
        raise ReceiptError("plan 必须是字符串")

    changes: ChangeSet | None = None
    if payload.get("changes") is not None:
        try:
            changes = changes_from_dict(payload["changes"])
        except SerializationError as error:
            raise ReceiptError(f"回执里的 changes 不合法：{error}") from error

    brief = _parse_brief(payload["brief"]) if payload.get("brief") is not None else None

    return Receipt(
        conclusion=conclusion,
        task_id=task_id,
        attempt=attempt_value,
        sha=sha,
        plan=plan,
        brief=brief,
        changes=changes,
        body=body,
    )


def render_receipt(conclusion: str, payload: dict[str, object]) -> str:
    """按回执格式拼一份出来。假 Agent 和测试用。"""
    return conclusion + "\n" + json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
