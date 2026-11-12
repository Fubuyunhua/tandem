"""只检查 AST 中的静态弱化信号，不执行候选代码。"""

import ast
import operator
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tandem.core.model import TestWeakening

SKIP_NAMES = frozenset({"skip", "skipif", "xfail", "importorskip"})
COMPARISONS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


@dataclass(frozen=True)
class _Signal:
    key: str
    reason: str
    line: int


def _truth(node: ast.expr) -> bool | None:
    try:
        return bool(ast.literal_eval(node))
    except (ValueError, TypeError, SyntaxError):
        pass
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = _truth(node.operand)
        return None if value is None else not value
    if isinstance(node, ast.BoolOp):
        values = [_truth(value) for value in node.values]
        if isinstance(node.op, ast.And):
            return False if False in values else True if all(v is True for v in values) else None
        return True if True in values else False if all(v is False for v in values) else None
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        compare = COMPARISONS.get(type(node.ops[0]))
        if compare is not None:
            try:
                return compare(ast.literal_eval(node.left), ast.literal_eval(node.comparators[0]))
            except (ValueError, TypeError, SyntaxError):
                pass
    return None


def _signals(text: str) -> tuple[_Signal, ...]:
    tree = ast.parse(text)
    aliases = {
        alias.asname or alias.name: alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name in SKIP_NAMES
    }
    call_targets = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    result: list[_Signal] = []
    seen: set[tuple[str, int]] = set()

    def add(node: ast.expr | ast.Assert, kind: str, reason: str) -> None:
        key = kind + ":" + ast.dump(node, include_attributes=False)
        if (key, node.lineno) not in seen:
            seen.add((key, node.lineno))
            result.append(_Signal(key, reason, node.lineno))

    for node in ast.walk(tree):
        target = node.func if isinstance(node, ast.Call) else node
        name = (
            target.attr
            if isinstance(target, ast.Attribute)
            else target.id
            if isinstance(target, ast.Name)
            else ""
        )
        name = aliases.get(name, name)
        if name in SKIP_NAMES:
            if isinstance(node, ast.Call):
                add(node, "skip", f"新增 {name} 跳过/预期失败标记或调用")
            elif isinstance(node, ast.Attribute) or (
                isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
            ):
                if id(node) not in call_targets:
                    add(node, "skip", f"新增 {name} 跳过/预期失败标记或引用")
        if isinstance(node, (ast.If, ast.While)):
            truth = _truth(node.test)
            dead = node.body if truth is False else node.orelse if truth is True else []
            for statement in dead:
                for child in ast.walk(statement):
                    if isinstance(child, ast.Assert):
                        add(child, "constant-false", "新增常量假分支中的断言")
    return tuple(result)


def new_test_weakenings(before: str, after: str, path: str) -> tuple[TestWeakening, ...]:
    previous = Counter(item.key for item in _signals(before))
    added: list[TestWeakening] = []
    for item in _signals(after):
        if previous[item.key]:
            previous[item.key] -= 1
        else:
            added.append(TestWeakening(path, item.reason, item.line))
    return tuple(added)
