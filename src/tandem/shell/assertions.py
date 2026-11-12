"""静态断言近似计数，不执行候选代码。"""

import ast
import re
from fnmatch import fnmatchcase

from tandem.shell.js_lex import count_js_assertions

TEST_FILE_PATTERN = re.compile(
    r"(^|/)(test_[^/]+|[^/]+_test|[^/]+\.(test|spec))\.[^/]+$",
    re.IGNORECASE,
)
SOURCE_EXTENSIONS = frozenset({"py", "pyi", "js", "jsx", "ts", "tsx", "cjs", "mjs", "mts", "cts"})
# pytest 默认 norecursedirs；这里采用跨平台保守匹配，不读取候选配置。
NORECURSEDIRS = (
    "*.egg",
    ".*",
    "_darcs",
    "build",
    "CVS",
    "dist",
    "node_modules",
    "venv",
    "{arch}",
    "__pycache__",
)


def is_test_path(path: str) -> bool:
    path = path.replace("\\", "/")
    if path.rsplit(".", 1)[-1].casefold() not in SOURCE_EXTENSIONS:
        return False
    return (
        "__tests__" in path.casefold().split("/")[:-1] or TEST_FILE_PATTERN.search(path) is not None
    )


def leaves_test_collection(old: str, new: str) -> bool:
    """保守地将离开原测试目录也视为移除，避免同名文件在新位置不再被收集。"""
    if not is_test_path(old):
        return False
    if not is_test_path(new):
        return True
    old, new = old.replace("\\", "/"), new.replace("\\", "/")
    if any(
        fnmatchcase(part.casefold(), pattern.casefold())
        for part in new.split("/")[:-1]
        for pattern in NORECURSEDIRS
    ):
        return True
    # 保护路径可以不区分大小写，但 Linux CI 的测试收集不能据此把 Tests 当作 tests。
    if old != new and old.casefold() == new.casefold():
        return True
    parts = old.split("/")
    for index, part in enumerate(parts[:-1]):
        if part.casefold() in {"test", "tests", "__tests__"}:
            prefix = "/".join(parts[: index + 1]) + "/"
            return not new.startswith(prefix)
    return False


def count_assertions(text: str, path: str) -> int:
    if path.casefold().endswith((".py", ".pyi")):
        tree = ast.parse(text, filename=path)
        return sum(isinstance(node, ast.Assert) for node in ast.walk(tree))
    return count_js_assertions(text)
