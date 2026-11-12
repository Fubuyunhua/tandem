"""提交身份必须是完整十六进制 OID，不能是可变引用或缩写。"""

import re


def is_commit_oid(value: str | None) -> bool:
    return value is not None and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) is not None
