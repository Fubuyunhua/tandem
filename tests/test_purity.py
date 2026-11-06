"""内核纯度检查：src/tandem/core 下的代码不能接触外部世界。

做法沿用 learn/layering/test_core.py：用 ast 扫描 import 和调用，不执行被检查的代码。
"""

import ast
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent.parent / "src" / "tandem" / "core"

# 会接触外部世界的模块（按顶层包名匹配）
FORBIDDEN_MODULES = {
    "asyncio",
    "http",
    "httpx",
    "io",
    "os",
    "pathlib",
    "random",
    "requests",
    "secrets",
    "shutil",
    "socket",
    "sqlite3",
    "subprocess",
    "sys",
    "threading",
    "time",
    "urllib",
}
FORBIDDEN_PACKAGES = {"tandem.shell"}

# 允许导入 datetime（用作参数类型），但不允许在内核里读当前时间
FORBIDDEN_ATTRIBUTES = {"now", "today", "utcnow"}
FORBIDDEN_CALLS = {"open", "input", "print", "exec", "eval", "__import__"}


def _core_files() -> list[Path]:
    return sorted(CORE_DIR.rglob("*.py"))


def _imported_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for name in _imported_names(tree):
        top = name.split(".")[0]
        if top in FORBIDDEN_MODULES:
            found.append(f"导入了 {name}")
        if any(name == p or name.startswith(p + ".") for p in FORBIDDEN_PACKAGES):
            found.append(f"导入了外壳 {name}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRIBUTES:
            found.append(f"读取当前时间 .{node.attr}（第 {node.lineno} 行）")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in FORBIDDEN_CALLS
        ):
            found.append(f"调用了 {node.func.id}()（第 {node.lineno} 行）")
    return found


def test_core_directory_exists() -> None:
    assert _core_files(), f"没有找到内核代码：{CORE_DIR}"


def test_core_is_pure() -> None:
    problems = {
        str(path.relative_to(CORE_DIR)): v for path in _core_files() if (v := _violations(path))
    }
    assert not problems, f"内核接触了外部世界：{problems}"


def test_checker_catches_violations(tmp_path: Path) -> None:
    """确认检查器本身有效：故意写一个不纯的文件，应该被抓到。"""
    bad = tmp_path / "bad.py"
    bad.write_text(
        "import subprocess\n"
        "from tandem.shell import runner\n"
        "from datetime import datetime\n"
        "x = datetime.now()\n"
        "open('f')\n",
        encoding="utf-8",
    )
    found = _violations(bad)
    assert len(found) == 4, found
