"""执行器：把内核给的动作清单变成副作用。

默认 dry-run：合并、关闭 PR、推送分支、启动真实 Agent 这些动作只记日志，
不产生真实副作用。只有假 Agent 会真的"运行"（它本来就没有副作用）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from tandem.core.model import Action, ActionKind, ActionStatus, TaskRecord
from tandem.shell.agents.base import AgentAdapter, AgentError, AgentRequest
from tandem.shell.github import GitHubClient, GitHubError
from tandem.shell.store import Store

# 这些动作在 M1 里没有真实实现，非 dry-run 时记为"结果未知"
NOT_IMPLEMENTED = (
    ActionKind.MERGE,
    ActionKind.CLOSE_PR,
    ActionKind.PUSH_BRANCH,
    ActionKind.STOP_AGENT,
    ActionKind.REQUEST_REVIEW,
    ActionKind.NOTIFY,
)


@dataclass(frozen=True)
class ExecutedAction:
    """一个动作的执行结果。"""

    action: Action
    status: ActionStatus
    simulated: bool
    message: str
    receipt: str | None = None


def build_prompt(task: TaskRecord, action: Action) -> str:
    """把任务记录翻译成给 Agent 的任务说明。"""
    lines = [
        f"任务编号：{task.task_id}",
        f"等级：{task.level.value}",
        f"第几次尝试：{task.attempt}",
        f"当前状态：{task.status.value}",
    ]
    if action.provider is not None:
        lines.append(f"写手：{action.provider}")
    if task.approved_plan_version is not None:
        lines.append(f"已批准第 {task.approved_plan_version} 版方案")
    if task.reason:
        lines.append(f"上一次的原因：{task.reason}")
    lines.append(f"这次要做的事：{action.detail}")
    lines.extend(
        [
            "",
            "回执格式：第一行写结论，后面附 JSON。",
            "JSON 必须包含 task_id、attempt、sha；可选 plan、brief、changes。",
        ]
    )
    return "\n".join(lines)


@dataclass
class Executor:
    """执行动作。``dry_run=True`` 时只记日志。"""

    agents: Mapping[str, AgentAdapter] = field(default_factory=dict[str, AgentAdapter])
    dry_run: bool = True
    log: list[str] = field(default_factory=list[str])
    github: GitHubClient | None = None
    github_store: Store | None = None
    github_repo: str | None = None

    def execute(self, action: Action, task: TaskRecord) -> ExecutedAction:
        if self.github is not None and action.kind in {ActionKind.MERGE, ActionKind.CLOSE_PR}:
            return self._github_action(action, task)
        self.log.append(
            f"{'[dry-run] ' if self.dry_run else ''}{action.kind.value}"
            f"{'（' + action.provider + '）' if action.provider is not None else ''}"
            f"：{action.detail}"
        )
        match action.kind:
            case ActionKind.START_AGENT:
                return self._start_agent(action, task)
            case ActionKind.SET_QUOTA_EXHAUSTED:
                # 额度是外壳的状态，由 Runner 记账；这里不算副作用
                return ExecutedAction(action, ActionStatus.DONE, True, "额度已记在外壳里")
            case (
                ActionKind.MERGE
                | ActionKind.CLOSE_PR
                | ActionKind.PUSH_BRANCH
                | ActionKind.STOP_AGENT
                | ActionKind.REQUEST_REVIEW
                | ActionKind.NOTIFY
            ):
                if self.dry_run:
                    return ExecutedAction(action, ActionStatus.DONE, True, "dry-run：只记日志")
                return ExecutedAction(
                    action,
                    ActionStatus.UNKNOWN,
                    False,
                    "M1 没有实现真实副作用，这一条只记录",
                )
            case _:  # pragma: no cover - 新增动作类型时 pyright 会报错
                raise AgentError(f"未知的动作：{action.kind}")

    def _github_action(self, action: Action, task: TaskRecord) -> ExecutedAction:
        assert self.github is not None
        source = (
            None if self.github_store is None else self.github_store.github_source(task.task_id)
        )
        try:
            if source is None or source.repo != self.github_repo or source.pr_number is None:
                raise GitHubError("缺少匹配仓库的 PR 关联")
            if action.kind is ActionKind.MERGE:
                if (
                    task.approved_sha is None
                    or task.approved_sha != task.latest_sha
                    or not task.ci_green
                ):
                    raise GitHubError("合并缺少当前提交的批准或 CI 证据")
                confirmed = self.github.merge_pr(
                    source.pr_number, task.approved_sha, live=not self.dry_run
                )
            else:
                confirmed = self.github.close_pr(source.pr_number, live=not self.dry_run)
        except GitHubError:
            return ExecutedAction(action, ActionStatus.UNKNOWN, False, "GitHub 动作失败或结果未知")
        if not self.dry_run and not confirmed:
            return ExecutedAction(action, ActionStatus.UNKNOWN, False, "GitHub 未确认动作完成")
        return ExecutedAction(
            action,
            ActionStatus.DONE,
            self.dry_run,
            "dry-run：未执行写入"
            if self.dry_run
            else "GitHub 已确认动作完成"
            if confirmed
            else "GitHub 未确认动作完成",
        )

    def _start_agent(self, action: Action, task: TaskRecord) -> ExecutedAction:
        provider = action.provider or ""
        agent = self.agents.get(provider)
        if agent is None:
            return ExecutedAction(
                action, ActionStatus.UNKNOWN, False, f"没有登记 {provider} 的适配器"
            )
        if not agent.simulated and self.dry_run:
            return ExecutedAction(
                action,
                ActionStatus.DONE,
                True,
                f"dry-run：不会真的启动 {provider}",
            )
        request = AgentRequest(
            task_id=task.task_id,
            provider=provider,
            attempt=task.attempt,
            prompt=build_prompt(task, action),
        )
        try:
            receipt = agent.run(request)
        except AgentError as error:
            return ExecutedAction(action, ActionStatus.UNKNOWN, False, f"Agent 出错：{error}")
        return ExecutedAction(action, ActionStatus.DONE, False, "收到回执", receipt=receipt)
