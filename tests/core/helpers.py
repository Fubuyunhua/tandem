"""测试公用的小工具：构造事件、任务、额度快照和审核结论。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from tandem.core.model import (
    Action,
    ActionKind,
    ChangeSet,
    Decision,
    Event,
    EventKind,
    Finding,
    Level,
    Policy,
    QuotaSnapshot,
    QuotaState,
    Review,
    RunMode,
    TaskRecord,
    TaskStatus,
    Verdict,
)
from tandem.core.transition import create_task, decide
from tandem.shell.config import load_policy

# 固定的"当前时间"：内核不读时钟，时间由外壳传进来
NOW = datetime(2026, 11, 7, 9, 30)
SHA_1 = "1" * 40
SHA_2 = "2" * 40

CODE_CHANGES = ChangeSet(paths=("src/tandem/shell/cli.py",))

# 不通过（FAIL）的结论至少要带一条有编号、有正文的意见，测试里统一用这一条
SOME_FINDINGS = (Finding(id="F1", text="这里有一个具体问题"),)
DOC_CHANGES = ChangeSet(paths=("docs/design/note.md",))
CORE_CHANGES = ChangeSet(paths=("src/tandem/core/model.py",))


def repository_policy() -> Policy:
    """仓库里真实的 risk.yml（M1 的默认配置是单 Agent 模式）。"""
    return load_policy()


def policy() -> Policy:
    """测试默认用多 Agent 策略：转换表里大部分条目只在多 Agent 模式下才会发生。"""
    return replace(load_policy(), run_mode=RunMode.MULTI_AGENT)


def quota(exhausted: tuple[str, ...] = ()) -> QuotaSnapshot:
    return QuotaSnapshot.from_mapping({name: QuotaState.EXHAUSTED for name in exhausted})


def ev(kind: EventKind, **fields: Any) -> Event:
    return Event(kind=kind, task_id="t1", **fields)


def run(
    record: TaskRecord,
    event: Event,
    policy_: Policy | None = None,
    quota_: QuotaSnapshot | None = None,
    now: datetime = NOW,
) -> Decision:
    return decide(
        record,
        event,
        policy_ if policy_ is not None else policy(),
        quota_ if quota_ is not None else QuotaSnapshot(),
        now,
    )


def single_agent_policy() -> Policy:
    """M1 的运行模式：只有 Claude，所有等级都由你审。"""
    return replace(policy(), run_mode=RunMode.SINGLE_AGENT)


def new_task(level: Level = Level.C, run_mode: RunMode | None = None) -> TaskRecord:
    record = create_task("t1", level, policy())
    if run_mode is not None:
        record = replace(record, run_mode=run_mode)
    return record


def actions_of(decision: Decision, kind: ActionKind) -> list[Action]:
    return [action for action in decision.actions if action.kind is kind]


# ------------------------------------------------------------------ 走到各个状态


def to_working(record: TaskRecord, provider: str = "claude") -> TaskRecord:
    return run(record, ev(EventKind.ASSIGN, provider=provider)).task


def to_acceptance(
    record: TaskRecord, sha: str = SHA_1, changes: ChangeSet = CODE_CHANGES
) -> TaskRecord:
    return run(
        record,
        ev(
            EventKind.CODE_SUBMITTED,
            attempt=record.attempt,
            sha=sha,
            changes=changes,
        ),
    ).task


def to_ai_review(level: Level = Level.C, quota_: QuotaSnapshot | None = None) -> TaskRecord:
    """C 级：派活 → 交代码 → CI 绿 → 待AI审核。"""
    record = to_working(new_task(level))
    record = to_acceptance(record)
    return run(record, ev(EventKind.CI_GREEN, sha=record.latest_sha), quota_=quota_).task


def to_d_ai_review() -> TaskRecord:
    """D 级：先走方案批准，再交代码到待AI审核。"""
    record = to_working(new_task(Level.D))
    record = run(record, ev(EventKind.PLAN_SUBMITTED, sha=SHA_1, plan="先改 core 里的 decide")).task
    record = run(record, ev(EventKind.PLAN_APPROVED, sha=SHA_1)).task
    record = to_working(record)
    record = to_acceptance(record, changes=CORE_CHANGES)
    return run(record, ev(EventKind.CI_GREEN, sha=record.latest_sha)).task


def review_event(
    record: TaskRecord,
    reviewer: str,
    verdict: Verdict = Verdict.PASS,
    sha: str | None = None,
    standard_version: int | None = None,
    provider: str | None = None,
    findings: tuple[Finding, ...] = (),
) -> Event:
    return ev(
        EventKind.REVIEW,
        review=Review(
            reviewer=reviewer,
            provider=provider if provider is not None else reviewer,
            verdict=verdict,
            sha=sha if sha is not None else (record.latest_sha or SHA_1),
            standard_version=(
                standard_version if standard_version is not None else record.standard_version
            ),
            findings=findings,
        ),
    )


def to_merged(level: Level = Level.C) -> TaskRecord:
    """C 级一路走到已合并。"""
    record = to_ai_review(level)
    for reviewer in record.designated_reviewers:
        record = run(record, review_event(record, reviewer)).task
    return run(record, ev(EventKind.MERGED, sha=record.latest_sha)).task


def to_merge_ready() -> TaskRecord:
    """C 级走到待合并（合并动作已发出，但还没收到合并成功）。"""
    record = to_ai_review()
    for reviewer in record.designated_reviewers:
        record = run(record, review_event(record, reviewer)).task
    return record


def to_needs_intervention_by_ci() -> TaskRecord:
    """三条 CI 红 → 待你介入（R01，CI 是红的）。"""
    record = to_working(new_task())
    record = to_acceptance(record)
    for _ in range(3):
        record = run(record, ev(EventKind.CI_RED, sha=record.latest_sha, reason="测试没过")).task
        if record.status is TaskStatus.PENDING:
            record = to_working(record)
            record = to_acceptance(record, sha=SHA_2)
    return record


def to_needs_intervention_by_reviewers(exhausted: str = "codex") -> TaskRecord:
    """凑不齐审核者 → 待你介入（R03，CI 是绿的）。"""
    record = to_working(new_task())
    record = to_acceptance(record)
    return run(
        record, ev(EventKind.CI_GREEN, sha=record.latest_sha), quota_=quota((exhausted,))
    ).task


def to_error() -> TaskRecord:
    """在待AI审核时出意外 → 异常。"""
    record = to_ai_review()
    return run(record, ev(EventKind.INCIDENT, reason="Agent 卡住 30 分钟", error_code="A01")).task


class Walker:
    """按顺序喂事件，顺便记下经过的状态，用来走查场景。"""

    def __init__(
        self,
        record: TaskRecord,
        policy_: Policy | None = None,
        quota_: QuotaSnapshot | None = None,
    ) -> None:
        self.record = record
        self.policy = policy_ if policy_ is not None else policy()
        self.quota = quota_ if quota_ is not None else QuotaSnapshot()
        self.statuses: list[TaskStatus] = [record.status]
        self.decisions: list[Decision] = []

    def step(self, event: Event) -> Decision:
        decision = decide(self.record, event, self.policy, self.quota, NOW)
        self.record = decision.task
        self.decisions.append(decision)
        self.statuses.append(self.record.status)
        return decision

    def assign(self, provider: str = "claude") -> Decision:
        return self.step(ev(EventKind.ASSIGN, provider=provider))

    def submit_code(self, sha: str = SHA_1, changes: ChangeSet = CODE_CHANGES) -> Decision:
        return self.step(
            ev(
                EventKind.CODE_SUBMITTED,
                attempt=self.record.attempt,
                sha=sha,
                changes=changes,
            )
        )

    def ci_green(self, sha: str | None = None) -> Decision:
        return self.step(
            ev(EventKind.CI_GREEN, sha=sha if sha is not None else self.record.latest_sha)
        )

    def ci_red(self, reason: str = "测试没过") -> Decision:
        return self.step(ev(EventKind.CI_RED, sha=self.record.latest_sha, reason=reason))

    def review(
        self,
        reviewer: str,
        verdict: Verdict = Verdict.PASS,
        findings: tuple[Finding, ...] = (),
    ) -> Decision:
        return self.step(review_event(self.record, reviewer, verdict, findings=findings))

    def pass_all(self) -> None:
        for reviewer in self.record.designated_reviewers:
            self.review(reviewer)

    def merge_success(self) -> Decision:
        return self.step(ev(EventKind.MERGED, sha=self.record.latest_sha))

    def actions(self, kind: ActionKind) -> list[Action]:
        found: list[Action] = []
        for decision in self.decisions:
            found.extend(actions_of(decision, kind))
        return found
