"""Agent 适配器的接口（PRD F6：``command()`` 和 ``read()`` 的替代写法）。

外壳通过这个接口派活和收回执。内核完全不知道 Agent 的存在。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class AgentError(RuntimeError):
    """Agent 出错了（进程退出、输出看不懂等）。"""


class AgentTimeout(AgentError):
    """Agent 超时，已经被强制结束。"""


@dataclass(frozen=True)
class AgentRequest:
    """派给 Agent 的一份任务说明。"""

    task_id: str
    provider: str
    attempt: int
    prompt: str


class AgentAdapter(Protocol):
    """一个 Agent 适配器。"""

    @property
    def provider(self) -> str:
        """这个适配器属于哪一家提供方。"""
        ...

    @property
    def simulated(self) -> bool:
        """True 表示假 Agent：不需要真实副作用，测试里可以真的"跑"。"""
        ...

    def run(self, request: AgentRequest) -> str:
        """干活，返回回执原文。出错或超时抛 AgentError。"""
        ...
