"""等级计算：先查底线，再看是不是 A 级，最后才让模型意见在基础级别上调整一次。

对应 ADR-0001 的"基础级别怎么算"：
1. 命中任何一条底线条目 → D（不管改没改仓库）；
2. 不改仓库、也没命中底线 → A；
3. 其他所有改动 → C；
4. 模型意见：可以把任何级别往上调；只有当所有改动都是纯文档时，才允许从 C 降到 B。

改名按"改名前、改名后两个路径都参与判断"处理：改名本身不直接判 D，
但它把两个路径带进路径检查，堵住"挪进 docs/ 就降级"的漏洞。
"""

from __future__ import annotations

from fnmatch import fnmatchcase

from tandem.core.model import ChangeSet, Level, Policy


def _normalize(path: str) -> str:
    """统一成正斜杠，便于跨平台比较（这里只做字符串替换，不碰文件系统）。"""
    return path.replace("\\", "/")


def _pattern_hits(pattern: str, path: str) -> bool:
    """模式是否命中路径。

    除了整条路径匹配，还逐级去掉前缀再匹配，这样 ``core/**`` 也能命中
    ``src/tandem/core/model.py``，符合 ADR 里 ``core/**``、``**/migrations/**``
    这种写法。
    """
    target = _normalize(path)
    candidates = [target]
    parts = target.split("/")
    candidates.extend("/".join(parts[index:]) for index in range(1, len(parts)))
    return any(fnmatchcase(candidate, pattern) for candidate in candidates)


def _matches_any(patterns: tuple[str, ...], path: str) -> bool:
    return any(_pattern_hits(pattern, path) for pattern in patterns)


def hits_bottom_line(changes: ChangeSet, policy: Policy) -> bool:
    """是否命中底线条目。底线条目一律 D。"""
    if changes.secret_scan_hit:
        return True
    if changes.assertions_decreased:
        return True
    # 删除文件本身是一条底线条目
    if changes.deleted_paths:
        return True
    return any(_matches_any(policy.bottom_line_paths, path) for path in changes.all_paths)


def all_paths_relaxable(changes: ChangeSet, policy: Policy) -> bool:
    """所有参与的路径是不是都在可放宽区（v1 只有纯文档）。"""
    paths = changes.all_paths
    if not paths:
        return False
    if hits_bottom_line(changes, policy):
        return False
    return all(_matches_any(policy.relaxable_paths, path) for path in paths)


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
