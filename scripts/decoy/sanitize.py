"""记录写进 JSON 之前的脱敏（G12）。

原则：宁可多删，不可多留。已知的敏感字符串（诱饵标记、本轮随机串）按值删除，
常见凭据按形状删除。脱敏之后才允许写进记录文件。
"""

import re
from collections.abc import Sequence

PLACEHOLDER = "[REDACTED]"

# 按形状识别的凭据。都是"长得像密钥"的模式，不做语义判断。
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|secret|password)\b\s*[:=]\s*\S{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
)


def redact(text: str, secrets: Sequence[str] = ()) -> str:
    """删除已知敏感值和形似凭据的片段。"""
    result = text
    for secret in secrets:
        if secret:
            result = result.replace(secret, PLACEHOLDER)
    for pattern in _PATTERNS:
        result = pattern.sub(PLACEHOLDER, result)
    return result
