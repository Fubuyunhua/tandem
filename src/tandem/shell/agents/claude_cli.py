"""调用真实的 Claude CLI：提示词只走标准输入，不进入命令参数。

带超时和强制结束。测试里不会运行它（会失败时直接抛 AgentError），
M1 只在前台手动用，`tandem demo` 用的是假 Agent。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import cast

from tandem.shell.agents.base import AgentError, AgentRequest, AgentTimeout


@dataclass(frozen=True)
class ClaudeCliAgent:
    """真实副作用：启动一个外部进程。执行器默认 dry-run 不会启动它。"""

    provider: str = "claude"
    executable: str = "claude"
    timeout_seconds: float = 1800.0

    @property
    def simulated(self) -> bool:
        return False

    def build_command(self, request: AgentRequest) -> list[str]:
        return [self.executable, "-p", "--output-format", "json"]

    def run(self, request: AgentRequest) -> str:
        process = subprocess.Popen(
            self.build_command(request),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
        try:
            stdout, stderr = process.communicate(input=request.prompt, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            # 超时就强制结束，不然进程会一直挂着
            process.kill()
            raise AgentTimeout(
                f"{self.provider} 超过 {self.timeout_seconds} 秒没有回执，已经强制结束"
            ) from None
        if process.returncode != 0:
            raise AgentError(f"{self.provider} 退出码 {process.returncode}：{stderr.strip()}")
        return self._extract_receipt(stdout)

    def _extract_receipt(self, stdout: str) -> str:
        """``--output-format json`` 的返回里，真正的文字在 ``result`` 字段。"""
        try:
            data: object = json.loads(stdout)
        except json.JSONDecodeError:
            # 版本不同可能输出别的格式，原样返回，交给回执解析去判断
            return stdout
        if isinstance(data, dict):
            result = cast("dict[object, object]", data).get("result")
            if isinstance(result, str) and result.strip():
                return result
        return stdout
