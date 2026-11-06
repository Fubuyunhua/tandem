"""等级计算：先查底线，再看是不是 A 级，最后才让模型意见在基础级别上调整一次。

对应 ADR-0001 的"基础级别怎么算"：
1. 命中任何一条底线条目 → D（不管改没改仓库）；
2. 不改仓库、也没命中底线 → A；
3. 其他所有改动 → C；
4. 模型意见：可以把任何级别往上调；只有当所有改动都是纯文档时，才允许从 C 降到 B。

两条防绕过的规则：
- 改名按"改名前、改名后两个路径都参与判断"处理，改名本身不直接判 D，
  但它把两个路径带进路径检查，堵住"挪进 docs/ 就降级"的漏洞。
- 路径先规范化：绝对路径、空路径、含 ``..`` 的路径一律拒绝，直接判 D；
  "纯文档"只认文档类型（扩展名在 risk.yml 里配置），``docs/run.py`` 这类可执行文件
  不能因为目录名叫 docs 就降到 B。
"""

from __future__ import annotations

from fnmatch import fnmatchcase

from tandem.core.model import ChangeSet, Level, Policy


def normalize_path(path: str) -> str | None:
    """把路径规范化成仓库相对路径。

    非法输入返回 ``None``：绝对路径（含 Windows 盘符、UNC）、空路径、
    含 ``..`` 的路径都不接受。合法输入去掉 ``.`` 段、统一成正斜杠。
    """
    text = path.strip().replace("\\", "/")
    if not text:
        return None
    # 绝对路径：以 / 开头（含 UNC 的 //server），或者带盘符 C:
    if text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        return None
    parts = [piece for piece in text.split("/") if piece not in ("", ".")]
    if any(piece == ".." for piece in parts):
        return None
    if not parts:
        return None
    return "/".join(parts)


def _pattern_hits(pattern: str, path: str) -> bool:
    """模式是否命中路径。

    除了整条路径匹配，还逐级去掉前缀再匹配，这样 ``core/**`` 也能命中
    ``src/tandem/core/model.py``，符合 ADR 里 ``core/**``、``**/migrations/**``
    这种写法。
    """
    # 跨平台采用保守的一致语义，Linux 上也不允许大小写变体逃过底线。
    pattern, path = pattern.casefold(), path.casefold()
    patterns = [pattern]
    if pattern.startswith("**/"):
        patterns.append(pattern[3:])
    candidates = [path]
    parts = path.split("/")
    candidates.extend("/".join(parts[index:]) for index in range(1, len(parts)))
    return any(
        fnmatchcase(candidate, glob) or (glob.endswith("/**") and candidate == glob[:-3])
        for candidate in candidates
        for glob in patterns
    )


def _matches_any(patterns: tuple[str, ...], path: str) -> bool:
    return any(_pattern_hits(pattern, path) for pattern in patterns)


def judged_paths(changes: ChangeSet) -> tuple[tuple[str, ...], bool]:
    """返回（规范化后的路径, 有没有非法路径）。"""
    normalized: list[str] = []
    illegal = False
    for path in changes.all_paths:
        clean = normalize_path(path)
        if clean is None:
            illegal = True
        else:
            normalized.append(clean)
    return tuple(normalized), illegal


def bottom_line_reasons(changes: ChangeSet, policy: Policy) -> tuple[str, ...]:
    """命中底线的全部原因，带上是哪个文件、哪一条。

    ``tandem show`` 和 risk-gate 的报告直接用它说明"为什么判 D"。
    """
    reasons: list[str] = []
    if changes.secret_scan_hit:
        reasons.append("密钥扫描命中")
    for drop in changes.assertion_drops:
        if drop.previous_path is not None and drop.previous_path != drop.path:
            where = f"{drop.previous_path} 改名为 {drop.path}"
        else:
            where = drop.path
        tail = "（文件被删除）" if drop.after == 0 and drop.path in changes.deleted_paths else ""
        reasons.append(f"测试文件 {where} 的断言从 {drop.before} 条减到 {drop.after} 条{tail}")
    if not changes.assertion_drops and changes.assertions_decreased:
        reasons.append(
            f"测试文件的断言合计从 {changes.assertions_before} 条减到 {changes.assertions_after} 条"
        )
    # 删除文件本身是一条底线条目
    reasons.extend(f"删除了文件 {path}" for path in changes.deleted_paths)
    paths, illegal = judged_paths(changes)
    if illegal:
        reasons.append("改动里有非法路径（绝对路径、空路径或含 .. 的路径）")
    for path in paths:
        if _matches_any(policy.bottom_line_paths, path):
            reasons.append(f"改动了底线条目相关的路径 {path}")
    for entry in changes.file_changes:
        for target in (entry.before_target, entry.after_target):
            if target is None:
                continue
            clean = normalize_path(target)
            if clean is None or _matches_any(policy.bottom_line_paths, clean):
                reasons.append(f"符号链接 {entry.path} 指向受保护或仓库外路径 {target}")
    return tuple(reasons)


def hits_bottom_line(changes: ChangeSet, policy: Policy) -> bool:
    """是否命中底线条目。底线条目一律 D。"""
    return bool(bottom_line_reasons(changes, policy))


def _is_document(path: str, policy: Policy) -> bool:
    """按扩展名判断是不是纯文档。类型清单来自 risk.yml。"""
    lowered = path.lower()
    return any(lowered.endswith(extension.lower()) for extension in policy.relaxable_extensions)


def all_paths_relaxable(changes: ChangeSet, policy: Policy) -> bool:
    """所有参与的路径是不是都在可放宽区（v1 只有纯文档）。

    既要落在可放宽的路径范围里，也要是文档类型。
    """
    paths, illegal = judged_paths(changes)
    if illegal or not paths:
        return False
    if hits_bottom_line(changes, policy):
        return False
    if any(
        entry.before_mode not in {"000000", "100644"} or entry.after_mode != "100644"
        for entry in changes.file_changes
    ):
        return False
    return all(
        _matches_any(policy.relaxable_paths, path) and _is_document(path, policy) for path in paths
    )


def base_level(changes: ChangeSet, policy: Policy) -> Level:
    """只看规则的基础级别。"""
    if hits_bottom_line(changes, policy):
        return Level.D
    if not changes.touches_repository:
        return Level.A
    return Level.C


def compute_level(changes: ChangeSet, policy: Policy, suggestion: Level | None = None) -> Level:
    """算出最终等级。

    ``suggestion`` 是分诊顾问的意见，只能在这个基础级别上调整一次，
    不能在上一次的结果上接着调（防止连续降级）。
    """
    base = base_level(changes, policy)
    if suggestion is None:
        return base
    if suggestion.rank > base.rank:
        return suggestion
    if suggestion.rank == base.rank:
        return base
    # 只有"纯文档 + 模型同意放宽"才能降，而且最多降到 B
    if base is Level.C and all_paths_relaxable(changes, policy):
        return Level.B
    return base
