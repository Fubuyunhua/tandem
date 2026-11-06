"""PowerShell 脚本的静态检查与纯逻辑测试（G1–G4）。

建发行版这件事不能靠"跑一遍看看"来验证：真跑就会创建发行版。
所以这里做两件事：
1. 静态检查：脚本的可执行代码里不能出现注销、导出、重建这类破坏性命令；
2. 纯逻辑测试：dot-source 脚本，直接调用其中的断言函数（`tests/scripts/wsl_logic.ps1`）。

没有 PowerShell 的环境（例如 ubuntu 上的 CI）会跳过第 2 项，第 1 项照常执行。
"""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "wsl" / "setup-tandem-distro.ps1"
HARNESS = Path(__file__).resolve().parent / "wsl_logic.ps1"


def _powershell() -> str | None:
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _code_only(text: str) -> str:
    """去掉块注释和行注释，只留下可执行代码。"""
    import re

    without_block = re.sub(r"(?s)<#.*?#>", "", text)
    return "\n".join(
        line for line in without_block.splitlines() if not line.lstrip().startswith("#")
    )


def test_script_never_unregisters_exports_or_recreates() -> None:
    code = _code_only(SCRIPT.read_text(encoding="utf-8-sig"))
    assert "--unregister" not in code, "脚本永远不能注销发行版（G2）"
    assert "--export" not in code, "脚本不能从现有发行版导出（G1）"
    assert "-Recreate" not in code, "脚本不能有 -Recreate（G2）"


def test_script_requires_rootfs_and_hash_arguments() -> None:
    code = _code_only(SCRIPT.read_text(encoding="utf-8-sig"))
    assert "-RootfsPath" in code
    assert "-ExpectedSha256" in code
    assert "Get-FileHash" in code, "必须校验 rootfs 的 SHA256（G1）"
    assert "--import" in code


def test_script_is_utf8_with_bom() -> None:
    """Windows PowerShell 5.1 对无 BOM 的 UTF-8 会按 ANSI 读，中文会乱码。"""
    assert SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")


def test_powershell_logic_harness() -> None:
    powershell = _powershell()
    if powershell is None:
        pytest.skip("当前环境没有 PowerShell")
    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(HARNESS),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert "ALL PASS" in completed.stdout
