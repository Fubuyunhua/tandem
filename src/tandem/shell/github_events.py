"""Issue、CI 与第 26 条核对的事件来源，不调用模型。"""

from dataclasses import dataclass, replace

from tandem.core.model import (
    ActionKind,
    ActionStatus,
    CheckResult,
    Event,
    EventKind,
    Level,
    TaskRecord,
    TaskStatus,
)
from tandem.shell.github import CIState, GitHubClient, GitHubError
from tandem.shell.runner import Runner, RunnerError
from tandem.shell.store import GitHubSource


@dataclass
class GitHubEvents:
    runner: Runner
    github: GitHubClient
    repo: str

    def bind_pr(self, task_id: str, number: int) -> None:
        source = self.runner.store.github_source(task_id)
        if source is None or source.repo != self.repo:
            raise RunnerError("任务没有这个仓库的 Issue 来源")
        if number <= 0:
            raise RunnerError("PR 编号必须为正整数")
        self.runner.store.save_github_source(replace(source, pr_number=number))

    def _incident(self, task: TaskRecord) -> None:
        self.runner.handle(
            Event(
                kind=EventKind.INCIDENT,
                task_id=task.task_id,
                state_version=task.state_version,
                error_code="G01",
                reason="GitHub 读取或核对失败，外部状态尚未确认",
            )
        )

    def poll(self) -> tuple[str, ...]:
        store = self.runner.store
        created: list[str] = []
        try:
            issues = self.github.list_issues()
        except GitHubError:
            for task in store.list_tasks():
                source = store.github_source(task.task_id)
                if source is not None and source.repo == self.repo and not task.status.is_terminal:
                    self._incident(task)
            raise
        for issue in issues:
            if issue.state != "open" or "agent" not in issue.labels:
                continue
            task_id = f"gh-{issue.number}"
            source = store.github_source(task_id)
            if source is None and store.load_task(task_id) is not None:
                raise RunnerError("已有同名任务但没有 GitHub 来源，拒绝接管")
            # 先登记来源；在创建快照前崩溃，下次可以继续创建。
            store.save_github_source(
                source
                if source is not None and source.repo == self.repo
                else GitHubSource(
                    task_id,
                    self.repo,
                    issue.number,
                    issue.title,
                    issue.body,
                )
            )
            if store.load_task(task_id) is None:
                self.runner.submit(task_id, Level.C)
                created.append(task_id)
        failed = False
        for task in store.list_tasks_by_status(TaskStatus.AWAITING_ACCEPTANCE):
            source = store.github_source(task.task_id)
            if source is None or source.repo != self.repo or task.latest_sha is None:
                continue
            try:
                state = self.github.get_ci(task.latest_sha)
            except GitHubError:
                self._incident(task)
                failed = True
                continue
            if state is CIState.PENDING:
                continue
            self.runner.handle(
                Event(
                    kind=EventKind.CI_GREEN if state is CIState.GREEN else EventKind.CI_RED,
                    task_id=task.task_id,
                    state_version=task.state_version,
                    sha=task.latest_sha,
                    reason="GitHub 提交检查结果",
                )
            )
        if failed:
            raise GitHubError("部分任务的 CI 读取失败，已记录异常事件")
        return tuple(created)

    def reconcile(self, task_id: str) -> CheckResult:
        store = self.runner.store
        task = store.load_task(task_id)
        source = store.github_source(task_id)
        if task is None or task.status is not TaskStatus.ERROR:
            raise RunnerError("只有异常状态的任务可以核对")
        if source is None or source.repo != self.repo:
            raise RunnerError("任务没有这个仓库的 GitHub 来源")
        pending = store.unconfirmed_actions(task_id)
        if source.pr_number is None:
            if task.pr_opened or any(
                a.kind in {ActionKind.MERGE, ActionKind.CLOSE_PR} for a in pending
            ):
                raise RunnerError("缺少 PR 关联，不能确认外部动作")
            result = CheckResult.NOT_CONFIRMED
        else:
            try:
                pr = self.github.get_pr(source.pr_number)
                if pr.merged:
                    expected = task.approved_sha or task.latest_sha
                    if expected is None or pr.head_sha != expected:
                        raise GitHubError("已合并的 PR 与任务提交不一致")
                    result = CheckResult.MERGE_SUCCEEDED
                elif pr.state == "closed":
                    result = CheckResult.PR_CLOSED
                else:
                    result = CheckResult.NOT_CONFIRMED
            except GitHubError:
                self._incident(task)
                raise
        outcome = self.runner.handle(
            Event(
                kind=EventKind.RETRY,
                task_id=task_id,
                state_version=task.state_version,
                check_result=result,
                sha=task.approved_sha or task.latest_sha,
            )
        )
        if outcome.decision.changed:
            for action in pending:
                if (action.kind is ActionKind.MERGE and result is CheckResult.MERGE_SUCCEEDED) or (
                    action.kind is ActionKind.CLOSE_PR and result is CheckResult.PR_CLOSED
                ):
                    store.update_action_status(action.action_id, ActionStatus.DONE)
        return result
