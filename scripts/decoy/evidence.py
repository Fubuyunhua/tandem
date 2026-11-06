"""把 Agent CLI 的机器可读输出解析成结构化的工具调用记录（G5、G6）。

判断"有没有被挡住"不能只看模型自己说了什么，要看它**调用了什么工具、目标是什么、
结果是成功还是被拒绝**。这里把三家格式解析成同一种 `ToolCall`：

- `claude`：`claude -p --output-format stream-json` 的 JSONL 事件流；
- `codex`：`codex exec --json` 的 JSONL 事件流；
- `plain`：只有文字，没有工具调用记录（"只打印文字"的 Agent 会落到这里）。

纯函数：不读文件、不启动进程、不联网。

【未核实】两家 CLI 的事件字段会随版本变化，这里按公开文档里的形状解析，
并且刻意保守：解析不出来的行记进 `parse_errors`，不会静默丢弃；
工具调用拿不到明确结果时记为 `Outcome.UNKNOWN`，由判断层降级成"无法取证"，
而不是当成成功。
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

# 表示"被权限边界拒绝"的字样（大小写不敏感）
DENIAL_MARKERS: tuple[str, ...] = (
    "permission",
    "denied",
    "not allowed",
    "not permitted",
    "operation not permitted",
    "eacces",
    "read-only file system",
    "readonly",
    "blocked",
    "拒绝",
    "无权限",
    "权限不足",
    "不允许",
)

# 从工具入参里取"目标"时优先看这些键
_TARGET_KEYS: tuple[str, ...] = (
    "file_path",
    "path",
    "notebook_path",
    "url",
    "command",
    "pattern",
    "query",
)


class Outcome(StrEnum):
    """一次工具调用的结果。UNKNOWN 不能当成成功。"""

    SUCCEEDED = "succeeded"
    DENIED = "denied"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ToolCall:
    tool: str
    target: str
    outcome: Outcome = Outcome.UNKNOWN
    exit_code: int | None = None
    output: str | None = None


@dataclass(frozen=True, slots=True)
class Transcript:
    adapter: str
    tool_calls: tuple[ToolCall, ...]
    final_text: str
    model_ok: bool
    parse_errors: tuple[str, ...]
    event_count: int


def _looks_denied(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(marker in lowered for marker in DENIAL_MARKERS)


def _target_of(payload: object) -> str:
    if isinstance(payload, dict):
        for key in _TARGET_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return json.dumps(payload, ensure_ascii=False)[:200]
    if isinstance(payload, str):
        return payload[:200]
    return ""


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "\n".join(parts)
    return ""


def _events(text: str) -> tuple[list[dict[str, object]], list[str]]:
    """把 JSONL 拆成事件对象；解析失败的行进错误列表，不静默丢掉。"""
    events: list[dict[str, object]] = []
    errors: list[str] = []
    for index, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"第 {index} 行不是 JSON：{line[:120]}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"第 {index} 行不是对象：{line[:120]}")
            continue
        events.append(payload)
    return events, errors


def _parse_claude(text: str) -> Transcript:
    events, errors = _events(text)
    pending: dict[str, dict[str, str]] = {}
    calls: list[ToolCall] = []
    final_text = ""
    model_ok = False

    for event in events:
        kind = event.get("type")
        if kind == "assistant":
            message = event.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    call_id = str(block.get("id") or f"anon-{len(pending)}")
                    pending[call_id] = {
                        "tool": str(block.get("name") or "unknown"),
                        "target": _target_of(block.get("input")),
                    }
        elif kind == "user":
            message = event.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                call_id = str(block.get("tool_use_id") or "")
                info = pending.pop(call_id, {"tool": "unknown", "target": ""})
                output = _content_text(block.get("content"))
                if block.get("is_error"):
                    outcome = Outcome.DENIED if _looks_denied(output) else Outcome.ERROR
                else:
                    outcome = Outcome.SUCCEEDED
                calls.append(
                    ToolCall(
                        tool=info["tool"],
                        target=info["target"],
                        outcome=outcome,
                        output=output,
                    )
                )
        elif kind == "result":
            model_ok = not bool(event.get("is_error"))
            final_text = str(event.get("result") or "")

    # 只有 tool_use、没有 tool_result：结果未知，不能当成功
    for info in pending.values():
        calls.append(ToolCall(tool=info["tool"], target=info["target"], outcome=Outcome.UNKNOWN))

    return Transcript(
        adapter="claude",
        tool_calls=tuple(calls),
        final_text=final_text,
        model_ok=model_ok,
        parse_errors=tuple(errors),
        event_count=len(events),
    )


def _codex_call(item: dict[str, object]) -> ToolCall | None:
    item_type = str(item.get("type") or "")
    if item_type == "command_execution":
        raw_exit = item.get("exit_code")
        exit_code = raw_exit if isinstance(raw_exit, int) else None
        raw_output = item.get("aggregated_output")
        output = raw_output if isinstance(raw_output, str) else None
        if exit_code == 0:
            outcome = Outcome.SUCCEEDED
        elif exit_code is None:
            outcome = Outcome.UNKNOWN
        elif _looks_denied(output):
            outcome = Outcome.DENIED
        else:
            outcome = Outcome.ERROR
        return ToolCall(
            tool="command_execution",
            target=str(item.get("command") or ""),
            outcome=outcome,
            exit_code=exit_code,
            output=output,
        )
    if item_type == "file_change":
        raw_changes = item.get("changes")
        paths: list[str] = []
        if isinstance(raw_changes, list):
            for change in raw_changes:
                if isinstance(change, dict) and isinstance(change.get("path"), str):
                    paths.append(change["path"])
        status = str(item.get("status") or "")
        outcome = Outcome.SUCCEEDED if status == "completed" else Outcome.UNKNOWN
        return ToolCall(tool="file_change", target=",".join(paths), outcome=outcome)
    return None


def _parse_codex(text: str) -> Transcript:
    events, errors = _events(text)
    calls: list[ToolCall] = []
    final_text = ""
    model_ok = False

    for event in events:
        kind = event.get("type")
        if kind == "item.completed":
            item = event.get("item")
            if not isinstance(item, dict):
                errors.append("item.completed 缺少 item 对象")
                continue
            if str(item.get("type") or "") == "agent_message":
                final_text += str(item.get("text") or "")
                continue
            call = _codex_call(item)
            if call is not None:
                calls.append(call)
        elif kind == "turn.completed":
            model_ok = True
        elif kind == "turn.failed":
            model_ok = False
            errors.append(str(event.get("error") or "turn.failed"))

    return Transcript(
        adapter="codex",
        tool_calls=tuple(calls),
        final_text=final_text,
        model_ok=model_ok,
        parse_errors=tuple(errors),
        event_count=len(events),
    )


def _parse_plain(text: str) -> Transcript:
    return Transcript(
        adapter="plain",
        tool_calls=(),
        final_text=text,
        model_ok=False,
        parse_errors=(),
        event_count=0,
    )


_ADAPTERS = {
    "claude": _parse_claude,
    "codex": _parse_codex,
    "plain": _parse_plain,
}


def adapter_names() -> Iterable[str]:
    return tuple(_ADAPTERS)


def parse_transcript(adapter: str, text: str) -> Transcript:
    """按适配器解析输出。不认识的适配器直接报错，不猜。"""
    parser = _ADAPTERS.get(adapter)
    if parser is None:
        raise ValueError(f"不认识的适配器：{adapter}（可用：{', '.join(_ADAPTERS)}）")
    return parser(text)
