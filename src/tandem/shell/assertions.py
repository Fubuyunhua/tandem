"""静态断言近似计数，不执行候选代码。"""

import ast
import re

TEST_FILE_PATTERN = re.compile(
    r"(^|/)(tests?/|__tests__/|test_[^/]*\.py$|[^/]*_test\.(py|[cm]?[jt]sx?)$"
    r"|[^/]*\.(test|spec)\.(py|[cm]?[jt]sx?)$)",
    re.IGNORECASE,
)
JS_NON_CODE = re.compile(
    r"//[^\n]*|/\*.*?\*/|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`",
    re.DOTALL,
)
JS_ASSERTION = re.compile(r"(?<![\w.])(assert\b|expect\s*\()")


def is_test_path(path: str) -> bool:
    return TEST_FILE_PATTERN.search(path.replace("\\", "/")) is not None


def leaves_test_collection(old: str, new: str) -> bool:
    """保守地将离开原测试目录也视为移除，避免同名文件在新位置不再被收集。"""
    if not is_test_path(old):
        return False
    if not is_test_path(new):
        return True
    parts = old.replace("\\", "/").casefold().split("/")
    for index, part in enumerate(parts[:-1]):
        if part in {"test", "tests", "__tests__"}:
            prefix = "/".join(parts[: index + 1]) + "/"
            return not new.replace("\\", "/").casefold().startswith(prefix)
    return False


def count_assertions(text: str, path: str) -> int:
    if path.casefold().endswith((".py", ".pyi")):
        tree = ast.parse(text, filename=path)
        return sum(isinstance(node, ast.Assert) for node in ast.walk(tree))
    # JS/TS 仅做词法近似：屏蔽注释、引号和模板字面量，不声称等同真实测试语义。
    code = JS_NON_CODE.sub(lambda match: " " * len(match.group()), text)
    return len(JS_ASSERTION.findall(code))
