"""按剧本行动的假 Agent：测试和 `tandem demo` 用它，不联网、不花钱。"""

from __future__ import annotations

from dataclasses import dataclass, field

from tandem.shell.agents.base import AgentError, AgentRequest


@dataclass
class FakeAgent:
    """剧本里写好一份份回执，每次派活按顺序取一份。"""

    provider: str
    script: list[str] = field(default_factory=list[str])
    prompts: list[str] = field(default_factory=list[str])

    @property
    def simulated(self) -> bool:
        return True

    @property
    def remaining(self) -> int:
        return len(self.script)

    def push(self, receipt: str) -> None:
        """再往剧本里加一份回执。"""
        self.script.append(receipt)

    def run(self, request: AgentRequest) -> str:
        self.prompts.append(request.prompt)
        if not self.script:
            raise AgentError(f"{self.provider} 的剧本已经用完了，没有回执可以交")
        return self.script.pop(0)
