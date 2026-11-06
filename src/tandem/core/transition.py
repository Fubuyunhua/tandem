"""决策中心：`decide()` 实现 `docs/design/task-lifecycle.md` 第七版的 #1–#27 和取消表。

内核只做判断：输入是任务记录、事件、策略、额度快照、当前时间，
输出是新的任务记录和动作清单。外壳负责保存和真正执行这些动作。

几条横切规则在这里统一处理：
- 事件带了状态版本号但对不上 → 忽略，不改任何东西；
- 已取消的任务后来又收到回执 → 忽略；
- 有新提交进来 → 针对旧提交的审核结论、批准、否决全部作废；
- 审核者只能来自不同提供方，且不能是写过这次代码的提供方。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import assert_never

from tandem.core.level import compute_level
from tandem.core.model import (
    Action,
    ActionKind,
    CheckResult,
    Decision,
    Event,
    EventKind,
    Level,
    Policy,
    QuotaSnapshot,
    Review,
    RunMode,
    TaskRecord,
    TaskStatus,
    Verdict,
)

# 写手是"你"时记在 writer 字段里的名字
HUMAN_WRITER = "you"


def create_task(task_id: str, level: Level, policy: Policy) -> TaskRecord:
    """新任务的初始记录。等级由外壳按提交时的改动算好传进来。"""
    return TaskRecord(task_id=task_id, level=level, run_mode=policy.run_mode)


class _Actions:
    """动作清单构造器。

    ``action_id`` 由"任务编号 + 目标状态版本号 + 序号"组成，是确定性的，
    重放同样的输入会得到同样的编号。
    """

    def __init__(self, task: TaskRecord, version: int) -> None:
        self._task = task
        self._version = version
        self.items: list[Action] = []

    def add(self, kind: ActionKind, detail: str = "", provider: str | None = None) -> None:
        self.items.append(
            Action(
                action_id=f"{self._task.task_id}:{self._version}:{len(self.items)}",
                kind=kind,
                task_id=self._task.task_id,
                detail=detail,
                provider=provider,
            )
        )


def _ignore(task: TaskRecord, why: str) -> Decision:
    """这个事件不改变任何东西。"""
    return Decision(task=task, actions=[], reason=why, changed=False)


def _transition(
    task: TaskRecord,
    status: TaskStatus,
    reason: str,
    actions: list[Action],
    **changes: object,
) -> Decision:
    """进入下一个状态：状态版本号 +1，动作记进任务记录。"""
    updated = replace(
        task,
        status=status,
        state_version=task.state_version + 1,
        reason=reason,
        **changes,
    )
    return Decision(
        task=updated.with_actions(tuple(actions)), actions=actions, reason=reason, changed=True
    )


def eligible_reviewers(
    task: TaskRecord,
    policy: Policy,
    quota: QuotaSnapshot,
    extra_excluded: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """合格的审核者：不同提供方、有额度、没写过这次代码。"""
    excluded = task.providers_involved | set(extra_excluded)
    result: list[str] = []
    for provider in policy.reviewer_providers:
        if provider in excluded:
            continue
        if not quota.has_quota(provider):
            continue
        result.append(provider)
    return tuple(result)


def _select_reviewers(
    task: TaskRecord,
    policy: Policy,
    quota: QuotaSnapshot,
    extra_excluded: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """按等级要求的家数挑审核者。凑不齐就返回空，由第 16 条处理。"""
    needed = policy.rule_for(task.level).min_reviewers
    candidates = eligible_reviewers(task, policy, quota, extra_excluded)
    if len(candidates) < needed:
        return ()
    return candidates[:needed]


def _current_reviews(task: TaskRecord) -> tuple[Review, ...]:
    return task.current_reviews()


def _reviews_by_provider(reviews: tuple[Review, ...]) -> dict[str, Review]:
    """按提供方去重：一家提供方只能算一票。

    审核者的名字（"codex"、"codex-session-2"）只是会话名，独立性按模型提供方算。
    """
    grouped: dict[str, Review] = {}
    for review in reviews:
        grouped.setdefault(review.provider, review)
    return grouped


def merge_blocker(task: TaskRecord, policy: Policy) -> tuple[str, ...]:
    """放行的统一不变量：任何产生 MERGE 动作的路径都要先过这里。

    返回非空表示不允许合并，元组里是原因（写进日志）。
    """
    reasons: list[str] = []
    if not task.ci_green:
        reasons.append("当前提交编号的 CI 不是绿的")
    if task.latest_sha is None:
        reasons.append("任务没有提交编号")
    if task.approved_sha is not None and task.approved_sha != task.latest_sha:
        reasons.append("批准的提交编号和当前的不一致")
    if task.latest_sha is not None:
        intruders = set(task.designated_reviewers) & task.providers_involved
        if intruders:
            reasons.append(f"审核者里有人写过这次代码：{'、'.join(sorted(intruders))}")
    return tuple(reasons)


def _merge(
    task: TaskRecord,
    policy: Policy,
    reason: str,
    actions: _Actions,
    blocked_record: TaskRecord | None = None,
    **changes: object,
) -> Decision:
    """唯一产生 MERGE 动作的出口。

    守卫不过时：默认把这个事件当作没生效（忽略），
    传了 ``blocked_record`` 就把"审核结论"记下来、状态留在原地（第 12 条用）。
    """
    candidate = replace(task, **changes)
    blockers = merge_blocker(candidate, policy)
    if blockers:
        message = "；".join(blockers)
        if blocked_record is None:
            return _ignore(task, f"{reason}；但不能合并：{message}")
        actions.add(ActionKind.NOTIFY, detail=f"不能合并：{message}")
        return _transition(
            blocked_record,
            blocked_record.status,
            f"{reason}；但不能合并：{message}",
            actions.items,
        )
    actions.add(ActionKind.MERGE, detail=reason)
    return _transition(candidate, TaskStatus.AWAITING_MERGE, reason, actions.items)


def decide(
    task: TaskRecord,
    event: Event,
    policy: Policy,
    quota: QuotaSnapshot,
    now: datetime,
) -> Decision:
    """内核主函数。纯函数：同样的输入总是得到同样的输出。"""
    result = _dispatch(task, event, policy, quota)
    if result.changed:
        # 时间只作为参数传进来，内核里不读时钟
        result = replace(result, task=replace(result.task, updated_at=now))
    return result


def _dispatch(
    task: TaskRecord,
    event: Event,
    policy: Policy,
    quota: QuotaSnapshot,
) -> Decision:
    if event.task_id != task.task_id:
        return _ignore(task, "事件的任务编号和任务记录不一致")
    if event.state_version is not None and event.state_version != task.state_version:
        return _ignore(
            task,
            f"事件带的版本号 {event.state_version} 和任务当前的 {task.state_version} 不一致",
        )
    if task.status.is_terminal:
        return _ignore(task, f"任务已经结束（{task.status.value}），事件直接丢弃")

    match event.kind:
        case EventKind.ASSIGN:
            return _on_assign(task, event, policy, quota)
        case EventKind.PLAN_SUBMITTED:
            return _on_plan_submitted(task, event, policy)
        case EventKind.PLAN_APPROVED:
            return _on_plan_approved(task, event)
        case EventKind.PLAN_REJECTED:
            return _on_plan_rejected(task, event)
        case EventKind.CODE_SUBMITTED:
            return _on_code_submitted(task, event, policy)
        case EventKind.REFUSED_TO_FIX:
            return _on_refused_to_fix(task, event)
        case EventKind.QUOTA_EXHAUSTED:
            return _on_quota_exhausted(task, event, policy, quota)
        case EventKind.INCIDENT:
            return _on_incident(task, event)
        case EventKind.CI_GREEN:
            return _on_ci_green(task, event, policy, quota)
        case EventKind.CI_RED:
            return _on_ci_red(task, event, policy)
        case EventKind.REVIEW:
            return _on_review(task, event, policy)
        case EventKind.YOUR_APPROVAL:
            return _on_your_approval(task, event, policy)
        case EventKind.YOUR_REJECTION:
            return _on_your_rejection(task, event)
        case EventKind.MERGED:
            return _on_merged(task, event)
        case EventKind.INTERVENTION_APPROVED:
            return _on_intervention_approved(task, event, policy)
        case EventKind.REWORK:
            return _on_rework(task, event)
        case EventKind.STANDARD_CHANGED:
            return _on_standard_changed(task, event, policy, quota)
        case EventKind.TAKE_OVER:
            return _on_take_over(task)
        case EventKind.YOU_SUBMITTED_CODE:
            return _on_you_submitted_code(task, event, policy)
        case EventKind.ABANDON:
            return _on_abandon(task, event)
        case EventKind.RETRY:
            return _on_retry(task, event)
        case EventKind.CANCEL:
            return _on_cancel(task)
        case _:  # pragma: no cover - 新增事件类型时 pyright 会在这里报错
            assert_never(event.kind)


# ---------------------------------------------------------------- 第 1–7 条


def _on_assign(task: TaskRecord, event: Event, policy: Policy, quota: QuotaSnapshot) -> Decision:
    """1. 待处理 → 处理中：写手有额度；多 Agent 模式下还要凑得齐审核者。"""
    if task.status is not TaskStatus.PENDING:
        return _ignore(task, "只有待处理的任务才会派活")
    writer = event.provider if event.provider is not None else policy.default_writer
    if writer not in policy.writer_providers:
        return _ignore(task, f"{writer} 不是能写代码的提供方")
    if not quota.has_quota(writer):
        return _ignore(task, f"{writer} 额度用完，下次换一家")

    rule = policy.rule_for(task.level)
    if task.run_mode is RunMode.MULTI_AGENT and rule.requires_ai_review:
        reviewers = eligible_reviewers(task, policy, quota, extra_excluded=(writer,))
        if len(reviewers) < rule.min_reviewers:
            return _ignore(
                task, f"多 Agent 模式下需要 {rule.min_reviewers} 家合格审核者，现在凑不齐"
            )

    actions = _Actions(task, task.state_version + 1)
    actions.add(ActionKind.START_AGENT, detail=f"把任务派给 {writer}", provider=writer)
    return _transition(
        task,
        TaskStatus.WORKING,
        f"派活给 {writer}",
        actions.items,
        writer=writer,
        writer_is_human=False,
        providers_involved=task.providers_involved | {writer},
        attempt=task.attempt + 1,
    )


def _on_plan_submitted(task: TaskRecord, event: Event, policy: Policy) -> Decision:
    """2. 处理中 → 待你批准方案：D 级，并且当前这版方案还没批准。"""
    if task.status is not TaskStatus.WORKING:
        return _ignore(task, "只有在处理中的任务才会交回方案")
    rule = policy.rule_for(task.level)
    if not rule.requires_plan_approval:
        return _ignore(task, f"{task.level.value} 级不需要你批准方案，方案留作记录")
    plan_version = task.plan_version + 1
    if task.approved_plan_version == plan_version:
        return _ignore(task, f"第 {plan_version} 版方案已经批准过了")

    actions = _Actions(task, task.state_version + 1)
    actions.add(
        ActionKind.NOTIFY, detail=f"{task.level.value} 级需要你先批准第 {plan_version} 版方案"
    )
    return _transition(
        task,
        TaskStatus.AWAITING_PLAN_APPROVAL,
        f"交回第 {plan_version} 版方案，等你批准",
        actions.items,
        plan_version=plan_version,
        latest_sha=event.sha if event.sha is not None else task.latest_sha,
        note=event.plan or task.note,
    )


def _on_plan_approved(task: TaskRecord, event: Event) -> Decision:
    """3. 待你批准方案 → 待处理：记下批准的是哪一版方案。"""
    if task.status is not TaskStatus.AWAITING_PLAN_APPROVAL:
        return _ignore(task, "只有待你批准方案的任务才会批准方案")
    if event.sha is not None and task.latest_sha is not None and event.sha != task.latest_sha:
        return _ignore(task, "你批准的是另一版方案：提交编号和当前的不一致")
    actions = _Actions(task, task.state_version + 1)
    # 写手是你时，批准完方案回到"你处理中"，你可以接着提交自己已经写好的代码；
    # 写手是 Agent 时回到"待处理"，等重新派活。
    target = TaskStatus.YOU_WORKING if task.writer_is_human else TaskStatus.PENDING
    actions.add(
        ActionKind.NOTIFY, detail=f"第 {task.plan_version} 版方案已批准，回到{target.value}"
    )
    return _transition(
        task,
        target,
        f"你批准了第 {task.plan_version} 版方案",
        actions.items,
        approved_plan_version=task.plan_version,
    )


def _on_plan_rejected(task: TaskRecord, event: Event) -> Decision:
    """4. 待你批准方案 → 待处理：带你的意见。"""
    if task.status is not TaskStatus.AWAITING_PLAN_APPROVAL:
        return _ignore(task, "只有待你批准方案的任务才会打回方案")
    reason = event.reason or "你没有写意见"
    actions = _Actions(task, task.state_version + 1)
    actions.add(ActionKind.NOTIFY, detail="方案被打回，等写手重做方案")
    return _transition(
        task,
        TaskStatus.PENDING,
        f"你打回了第 {task.plan_version} 版方案：{reason}",
        actions.items,
        approved_plan_version=None,
        note=reason,
    )


# 这些状态下都允许接收新代码：新提交让旧的审核、批准、否决全部作废
NEW_SUBMISSION_STATES = frozenset(
    {
        TaskStatus.AWAITING_ACCEPTANCE,
        TaskStatus.AWAITING_AI_REVIEW,
        TaskStatus.AWAITING_YOUR_REVIEW,
        TaskStatus.NEEDS_INTERVENTION,
        TaskStatus.ERROR,
        TaskStatus.AWAITING_MERGE,
    }
)


def _on_code_submitted(task: TaskRecord, event: Event, policy: Policy) -> Decision:
    """5 / 5b. 处理中 → 待验收，或者重新算级别后升成 D 级 → 待你批准方案。"""
    if task.status is not TaskStatus.WORKING:
        if task.status in NEW_SUBMISSION_STATES:
            return _on_new_submission(task, event, policy)
        return _ignore(task, f"{task.status.value}时不该收到代码回执")
    if event.sha is None or event.attempt is None or event.changes is None:
        return _ignore(task, "回执缺少任务编号、第几次尝试或提交编号，按无效回执处理")
    if event.attempt != task.attempt:
        return _ignore(
            task, f"回执带的是第 {event.attempt} 次尝试，和当前第 {task.attempt} 次对不上"
        )

    # 按真实改动重新算级别（每次都重算，不沿用上一次的结果）
    new_level = compute_level(event.changes, policy, event.model_suggestion)
    rule = policy.rule_for(new_level)
    plan_pending = rule.requires_plan_approval and task.approved_plan_version != task.plan_version
    actions = _Actions(task, task.state_version + 1)

    if plan_pending:
        plan_version = task.plan_version + 1
        actions.add(ActionKind.NOTIFY, detail="按真实改动算出 D 级，要先批准方案")
        return _transition(
            task,
            TaskStatus.AWAITING_PLAN_APPROVAL,
            f"按真实改动重新算出来是 {new_level.value} 级，方案还没批准",
            actions.items,
            level=new_level,
            latest_sha=event.sha,
            approved_sha=None,
            reviews=(),
            ci_green=False,
            plan_version=plan_version,
            returned_from_review=False,
        )

    actions.add(ActionKind.NOTIFY, detail=f"交回代码（第 {task.attempt} 次尝试），等 CI")
    return _transition(
        task,
        TaskStatus.AWAITING_ACCEPTANCE,
        f"交回代码 {event.sha}，按真实改动算出来是 {new_level.value} 级",
        actions.items,
        level=new_level,
        # 新提交让旧结论、批准、否决全部作废
        latest_sha=event.sha,
        approved_sha=None,
        reviews=(),
        ci_green=False,
        pr_opened=True,
        returned_from_review=False,
        note=event.reason or "",
    )


def _on_new_submission(task: TaskRecord, event: Event, policy: Policy) -> Decision:
    """审核、验收、待合并期间来了新提交。

    更新提交编号、作废旧审核结论和批准、重新算级别，然后回到验收
    （升成 D 级且方案没批准时，先回到方案批准）。
    """
    if event.sha is None or event.attempt is None or event.changes is None:
        return _ignore(task, "新提交缺少提交编号、尝试次数或真实改动，按无效回执处理")
    if event.attempt < task.attempt:
        return _ignore(task, f"收到的是第 {event.attempt} 次尝试的回执，比当前的还早，忽略")
    if task.status is TaskStatus.AWAITING_MERGE and any(
        action.kind is ActionKind.MERGE for action in task.actions
    ):
        return _ignore(task, "合并已经开始，新提交先记下，等核对合并结果后再决定")

    new_level = compute_level(event.changes, policy, event.model_suggestion)
    rule = policy.rule_for(new_level)
    plan_approved = (
        task.approved_plan_version is not None and task.approved_plan_version == task.plan_version
    )
    actions = _Actions(task, task.state_version + 1)
    invalidated: dict[str, object] = {
        "level": new_level,
        "latest_sha": event.sha,
        "approved_sha": None,
        "reviews": (),
        "ci_green": False,
        "pr_opened": True,
        "returned_from_review": False,
        "attempt": max(task.attempt, event.attempt),
        "note": event.reason or "",
    }
    if rule.requires_plan_approval and not plan_approved:
        actions.add(ActionKind.NOTIFY, detail="新提交升成 D 级，要先批准方案")
        return _transition(
            task,
            TaskStatus.AWAITING_PLAN_APPROVAL,
            f"新提交 {event.sha} 按真实改动算出来是 {new_level.value} 级，方案还没批准",
            actions.items,
            plan_version=task.plan_version + 1,
            **invalidated,
        )
    actions.add(ActionKind.NOTIFY, detail=f"收到新提交 {event.sha}，旧结论全部作废，重新验收")
    return _transition(
        task,
        TaskStatus.AWAITING_ACCEPTANCE,
        f"新提交 {event.sha}（{new_level.value} 级），旧审核结论和批准全部作废",
        actions.items,
        **invalidated,
    )


def _on_refused_to_fix(task: TaskRecord, event: Event) -> Decision:
    """6. 处理中 → 待你介入：写手拒绝修改，取消仲裁。"""
    if task.status is not TaskStatus.WORKING:
        return _ignore(task, "只有在处理中的任务才会拒绝修改")
    if not task.returned_from_review:
        return _ignore(task, "上一轮不是被审核退回的，拒绝修改不生效")
    reason = event.reason or "写手没有写理由"
    actions = _Actions(task, task.state_version + 1)
    actions.add(ActionKind.NOTIFY, detail="写手拒绝修改，等你决定")
    return _transition(
        task,
        TaskStatus.NEEDS_INTERVENTION,
        f"写手拒绝修改：{reason}",
        actions.items,
        note=reason,
        returned_from_review=False,
    )


def _on_quota_exhausted(
    task: TaskRecord, event: Event, policy: Policy, quota: QuotaSnapshot
) -> Decision:
    """7. 处理中 → 待处理：额度用完，把这一家标记为用完，下次换一家。"""
    if task.status is TaskStatus.AWAITING_AI_REVIEW:
        return _on_reviewer_unavailable(task, event, policy, quota)
    if task.status is not TaskStatus.WORKING:
        return _ignore(task, "只有在处理中或待 AI 审核时才会报额度用完")
    provider = event.provider or task.writer or policy.default_writer
    progress = event.reason or "没有写进度说明"
    actions = _Actions(task, task.state_version + 1)
    actions.add(
        ActionKind.SET_QUOTA_EXHAUSTED,
        detail=f"{provider} 额度用完（额度是估计值）",
        provider=provider,
    )
    actions.add(ActionKind.STOP_AGENT, detail=f"结束 {provider} 的进程", provider=provider)
    actions.add(ActionKind.NOTIFY, detail=f"{provider} 额度用完，已退回待处理")
    return _transition(
        task,
        TaskStatus.PENDING,
        f"{provider} 额度用完，换一家接着做；进度：{progress}",
        actions.items,
        note=f"额度是估计值。{progress}",
        returned_from_review=False,
    )


def _on_reviewer_unavailable(
    task: TaskRecord, event: Event, policy: Policy, quota: QuotaSnapshot
) -> Decision:
    """第 16 条：审核途中审核者失效，按当前额度和参与历史重新检查审核者家数。"""
    gone = event.provider or "某一方"
    rule = policy.rule_for(task.level)
    remaining = tuple(
        seat
        for seat in eligible_reviewers(task, policy, quota, extra_excluded=(gone,))
        if seat in task.designated_reviewers
    )
    actions = _Actions(task, task.state_version + 1)
    actions.add(
        ActionKind.SET_QUOTA_EXHAUSTED,
        detail=f"{gone} 额度用完（额度是估计值）",
        provider=gone,
    )
    if len(remaining) < rule.min_reviewers:
        actions.add(ActionKind.NOTIFY, detail=f"{gone} 用不了，凑不齐合格的审核者")
        return _transition(
            task,
            TaskStatus.NEEDS_INTERVENTION,
            f"R03 {gone} 用不了，凑不齐 {rule.min_reviewers} 家审核者",
            actions.items,
            error_code="R03",
            designated_reviewers=remaining,
            note=task.note or f"审核者 {gone} 失效",
        )
    actions.add(ActionKind.NOTIFY, detail=f"{gone} 用不了，剩下的 {len(remaining)} 家继续审")
    return _transition(
        task,
        TaskStatus.AWAITING_AI_REVIEW,
        f"{gone} 用不了，剩下的 {len(remaining)} 家审核者继续审",
        actions.items,
        designated_reviewers=remaining,
    )


# ---------------------------------------------------------------- 第 8–11 条


def _on_incident(task: TaskRecord, event: Event) -> Decision:
    """8. 各种进行中的状态 → 异常：记下出问题前的状态和没确认的动作。"""
    if task.status not in {
        TaskStatus.WORKING,
        TaskStatus.AWAITING_ACCEPTANCE,
        TaskStatus.AWAITING_AI_REVIEW,
        TaskStatus.AWAITING_MERGE,
    }:
        return _ignore(task, f"任务在 {task.status.value}，这里不该有意外事件")
    unconfirmed = [action.action_id for action in task.actions if action.status.is_unconfirmed]
    actions = _Actions(task, task.state_version + 1)
    actions.add(ActionKind.STOP_AGENT, detail="结束可能还在跑的进程")
    actions.add(ActionKind.NOTIFY, detail="任务出现异常，等你处理")
    return _transition(
        task,
        TaskStatus.ERROR,
        f"意外：{event.reason or event.error_code or '未说明'}",
        actions.items,
        status_before_error=task.status,
        error_code=event.error_code or "E01",
        note=f"还没确认完成的动作：{', '.join(unconfirmed) if unconfirmed else '无'}",
    )


def _on_ci_green(task: TaskRecord, event: Event, policy: Policy, quota: QuotaSnapshot) -> Decision:
    """9 / 9b. 待验收 → 待AI审核（多 Agent 模式），或者 → 待你审核（单 Agent 模式）。"""
    if task.status is not TaskStatus.AWAITING_ACCEPTANCE:
        return _ignore(task, "只有在待验收的任务才会收到 CI 结果")
    if task.latest_sha is None or event.sha != task.latest_sha:
        return _ignore(task, "CI 的提交编号和回执里的不一致")
    actions = _Actions(task, task.state_version + 1)

    if task.run_mode is RunMode.SINGLE_AGENT:
        actions.add(ActionKind.NOTIFY, detail="CI 绿，等你看")
        return _transition(
            task,
            TaskStatus.AWAITING_YOUR_REVIEW,
            "CI 绿；单 Agent 模式下所有等级都由你审",
            actions.items,
            ci_green=True,
            note="这次没有 AI 审核",
        )

    rule = policy.rule_for(task.level)
    if not rule.requires_ai_review:
        return _merge(
            task,
            policy,
            f"CI 绿，{task.level.value} 级不需要 AI 审核",
            actions,
            ci_green=True,
            approved_sha=task.latest_sha,
        )

    reviewers = _select_reviewers(task, policy, quota)
    if not reviewers:
        actions.add(ActionKind.NOTIFY, detail="凑不齐合格的审核者")
        return _transition(
            task,
            TaskStatus.NEEDS_INTERVENTION,
            "R03 凑不齐合格的审核者",
            actions.items,
            ci_green=True,
            error_code="R03",
        )
    for reviewer in reviewers:
        actions.add(
            ActionKind.REQUEST_REVIEW,
            detail=f"请 {reviewer} 审核提交 {task.latest_sha}",
            provider=reviewer,
        )
    return _transition(
        task,
        TaskStatus.AWAITING_AI_REVIEW,
        f"CI 绿，交给 {len(reviewers)} 家审核（{'、'.join(reviewers)}）",
        actions.items,
        ci_green=True,
        designated_reviewers=reviewers,
        reviews=(),
    )


def _on_ci_red(task: TaskRecord, event: Event, policy: Policy) -> Decision:
    """10 / 11. 待验收 → 待处理（带原因），失败达到上限 → 待你介入（R01）。"""
    if task.status is not TaskStatus.AWAITING_ACCEPTANCE:
        return _ignore(task, "只有在待验收的任务才会收到 CI 结果")
    if task.latest_sha is None or event.sha != task.latest_sha:
        return _ignore(task, "CI 结果没有带当前提交编号，或者编号对不上，忽略")
    failures = task.accept_failures + 1
    limit = policy.thresholds.max_accept_failures
    reason = event.reason or "CI 没有给出原因"
    actions = _Actions(task, task.state_version + 1)

    if failures >= limit:
        actions.add(ActionKind.NOTIFY, detail=f"验收失败 {failures} 次，达到上限")
        return _transition(
            task,
            TaskStatus.NEEDS_INTERVENTION,
            f"R01 验收失败达到 {failures} 次：{reason}",
            actions.items,
            accept_failures=failures,
            ci_green=False,
            reviews=(),
            error_code="R01",
            note=reason,
            returned_from_review=False,
        )

    actions.add(ActionKind.NOTIFY, detail=f"CI 红（第 {failures} 次），退回修改")
    return _transition(
        task,
        TaskStatus.PENDING,
        f"CI 红，第 {failures} 次：{reason}",
        actions.items,
        accept_failures=failures,
        ci_green=False,
        reviews=(),
        note=reason,
        returned_from_review=False,
    )


# ---------------------------------------------------------------- 第 12–16 条


def _on_review(task: TaskRecord, event: Event, policy: Policy) -> Decision:
    """12–16. 收审核结论：全过就合并（D 级则等你），有人不通过就退回或找你。"""
    if task.status is not TaskStatus.AWAITING_AI_REVIEW:
        return _ignore(task, "只有在待 AI 审核的任务才会收审核结论")
    review = event.review
    if review is None:
        return _ignore(task, "审核事件没有带结论")
    if review.provider in task.providers_involved:
        return _ignore(task, f"{review.provider} 写过这次代码，不能当审核者")
    if review.provider not in task.designated_reviewers:
        return _ignore(task, f"{review.provider} 不是这次指定的审核者")
    if review.sha != task.latest_sha:
        return _ignore(task, "审核结论针对的不是当前提交编号，作废")
    if review.standard_version != task.standard_version:
        return _ignore(task, "审核结论用的是旧的审核标准版本，作废")

    if any(existing.provider == review.provider for existing in _current_reviews(task)):
        return _ignore(task, f"{review.provider} 已经出过结论，同一提供方不能算两家")

    recorded = replace(task, reviews=task.reviews + (review,))
    by_provider = _reviews_by_provider(_current_reviews(recorded))
    rule = policy.rule_for(task.level)
    actions = _Actions(task, task.state_version + 1)

    failing = tuple(item for item in by_provider.values() if item.verdict is Verdict.FAIL)
    failing_names = "；".join(item.reviewer for item in failing)
    if failing:
        if task.writer_is_human:
            # 14b：写手是你，带 AI 的反对意见交给你选择
            actions.add(ActionKind.NOTIFY, detail="AI 不通过你自己写的代码，等你决定")
            return _transition(
                recorded,
                TaskStatus.NEEDS_INTERVENTION,
                f"{len(failing)} 家审核不通过（写手是你）：{failing_names}",
                actions.items,
                note="AI 的反对意见：" + failing_names,
            )
        revisions = task.revision_count(task.standard_version) + 1
        if revisions >= policy.thresholds.max_revisions:
            # 15：修改次数达到上限（R02）
            actions.add(ActionKind.NOTIFY, detail=f"审核不通过已经 {revisions} 次，等你决定")
            return _transition(
                recorded,
                TaskStatus.NEEDS_INTERVENTION,
                f"R02 审核不通过，修改次数达到 {revisions} 次：{failing_names}",
                actions.items,
                revision_counts=task.bumped_revision(),
                error_code="R02",
            )
        # 14：退回修改，之前的审核结论全部作废
        actions.add(ActionKind.NOTIFY, detail="审核不通过，退回修改")
        return _transition(
            recorded,
            TaskStatus.PENDING,
            f"审核不通过（第 {revisions} 次修改）：{failing_names}",
            actions.items,
            revision_counts=task.bumped_revision(),
            reviews=(),
            returned_from_review=True,
        )

    designated = set(task.designated_reviewers)
    passing = {
        provider: item
        for provider, item in by_provider.items()
        if item.verdict is Verdict.PASS and provider in designated
    }
    enough_seats = len(designated) >= rule.min_reviewers
    complete = enough_seats and designated <= set(passing) and len(passing) >= rule.min_reviewers
    if complete:
        if rule.requires_human_merge:
            # 13：D 级，审核都过了，等你审
            actions.add(ActionKind.NOTIFY, detail="AI 审核全过，D 级等你看完整 diff")
            return _transition(
                recorded,
                TaskStatus.AWAITING_YOUR_REVIEW,
                "所有指定的审核者都通过，D 级等你看",
                actions.items,
            )
        # 12：全过就合并（dry-run），守卫会再核对一次 CI 和提交编号
        return _merge(
            recorded,
            policy,
            f"所有指定的审核者都通过，准备合并 {task.latest_sha}",
            actions,
            recorded,
            approved_sha=task.latest_sha,
        )

    # 还有提供方没出结论，状态不变，只把这条结论记下来
    return _transition(recorded, TaskStatus.AWAITING_AI_REVIEW, "还要等其他提供方的结论", [])


# ---------------------------------------------------------------- 第 17–25 条


def _on_your_approval(task: TaskRecord, event: Event, policy: Policy) -> Decision:
    """17. 待你审核 → 待合并：CI 绿，绑定当前提交编号。"""
    if task.status is not TaskStatus.AWAITING_YOUR_REVIEW:
        return _ignore(task, "只有待你审核的任务才会由你批准")
    if event.sha is None or event.sha != task.latest_sha:
        return _ignore(task, "你批准时要带上你看到的那个提交编号，和当前不一致就不生效")
    actions = _Actions(task, task.state_version + 1)
    approved_sha = task.latest_sha
    if approved_sha is None:
        return _ignore(task, "任务没有提交编号，不能批准")
    return _merge(
        task,
        policy,
        f"你批准了提交 {approved_sha}",
        actions,
        approved_sha=approved_sha,
        note=event.reason or task.note,
    )


def _on_your_rejection(task: TaskRecord, event: Event) -> Decision:
    """18. 待你审核 → 待处理：带原因。"""
    if task.status is not TaskStatus.AWAITING_YOUR_REVIEW:
        return _ignore(task, "只有待你审核的任务才会由你打回")
    reason = event.reason or "你没有写原因"
    actions = _Actions(task, task.state_version + 1)
    actions.add(ActionKind.NOTIFY, detail="你打回了，退回修改")
    return _transition(
        task,
        TaskStatus.PENDING,
        f"你打回了提交 {task.latest_sha}：{reason}",
        actions.items,
        reviews=(),
        approved_sha=None,
        note=reason,
    )


def _on_merged(task: TaskRecord, event: Event) -> Decision:
    """19. 待合并 → 已合并：提交编号和审核时一致。"""
    if task.status is not TaskStatus.AWAITING_MERGE:
        return _ignore(task, "只有待合并的任务才会收到合并成功")
    approved = task.approved_sha or task.latest_sha
    if approved is None or event.sha is None:
        return _ignore(task, "合并成功必须带核对过的提交编号")
    if event.sha != approved:
        return _ignore(task, f"合并的提交编号 {event.sha} 和审核时的 {approved} 不一致")
    actions = _Actions(task, task.state_version + 1)
    actions.add(ActionKind.NOTIFY, detail="任务已合并")
    return _transition(task, TaskStatus.MERGED, f"提交 {approved} 已合并", actions.items)


def _on_intervention_approved(task: TaskRecord, event: Event, policy: Policy) -> Decision:
    """20. 待你介入 → 待合并：CI 必须是绿的，否决 AI 意见要写理由。"""
    if task.status is not TaskStatus.NEEDS_INTERVENTION:
        return _ignore(task, "只有待你介入的任务才会人工审核通过")
    if task.latest_sha is None:
        return _ignore(task, "任务没有提交编号，不能批准")
    if event.sha is None or event.sha != task.latest_sha:
        return _ignore(task, "人工审核通过要绑定当前提交编号，和当前不一致就不生效")
    failing = [item for item in _current_reviews(task) if item.verdict is Verdict.FAIL]
    if failing and not (event.reason or "").strip():
        return _ignore(task, "否决 AI 的审核意见要对每一条写理由")
    actions = _Actions(task, task.state_version + 1)
    return _merge(
        task,
        policy,
        f"你人工审核通过了提交 {task.latest_sha}",
        actions,
        approved_sha=task.latest_sha,
        note=event.reason or task.note,
    )


def _on_rework(task: TaskRecord, event: Event) -> Decision:
    """21. 待你介入 → 待处理：换一个 Agent 重做，带你的说明。"""
    if task.status is not TaskStatus.NEEDS_INTERVENTION:
        return _ignore(task, "只有待你介入的任务才会换一个 Agent 重做")
    reason = event.reason or "你没有写说明"
    actions = _Actions(task, task.state_version + 1)
    actions.add(ActionKind.NOTIFY, detail="换一个 Agent 重做")
    return _transition(
        task,
        TaskStatus.PENDING,
        f"你要求换一个 Agent 重做：{reason}",
        actions.items,
        reviews=(),
        approved_sha=None,
        note=reason,
        returned_from_review=False,
    )


def _on_standard_changed(
    task: TaskRecord, event: Event, policy: Policy, quota: QuotaSnapshot
) -> Decision:
    """22. 待你介入 → 待AI审核：换新的审核标准版本，计数清零但保留历史。"""
    if task.status is not TaskStatus.NEEDS_INTERVENTION:
        return _ignore(task, "只有待你介入的任务才会改审核标准")
    if event.standard_version is None or event.standard_version <= task.standard_version:
        return _ignore(task, "改审核标准要带一个比当前更大的标准版本号")

    changed = replace(task, standard_version=event.standard_version)
    reviewers = _select_reviewers(changed, policy, quota)
    actions = _Actions(task, task.state_version + 1)
    if not reviewers:
        actions.add(ActionKind.NOTIFY, detail="换了标准，但还是凑不齐合格的审核者")
        return _transition(
            changed,
            TaskStatus.NEEDS_INTERVENTION,
            "R03 改完标准还是凑不齐合格的审核者",
            actions.items,
            error_code="R03",
        )
    for reviewer in reviewers:
        actions.add(
            ActionKind.REQUEST_REVIEW,
            detail=f"请 {reviewer} 用第 {event.standard_version} 版标准重新审",
            provider=reviewer,
        )
    return _transition(
        changed,
        TaskStatus.AWAITING_AI_REVIEW,
        f"换成第 {event.standard_version} 版审核标准，重新审",
        actions.items,
        reviews=(),
        designated_reviewers=reviewers,
    )


def _on_take_over(task: TaskRecord) -> Decision:
    """23. 待你介入 → 你处理中：你自己接手，相当于上锁。"""
    if task.status is not TaskStatus.NEEDS_INTERVENTION:
        return _ignore(task, "只有待你介入的任务才会被你接手")
    actions = _Actions(task, task.state_version + 1)
    actions.add(ActionKind.NOTIFY, detail="你自己接手了，系统不再催你")
    return _transition(task, TaskStatus.YOU_WORKING, "你自己接手了", actions.items)


def _on_you_submitted_code(task: TaskRecord, event: Event, policy: Policy) -> Decision:
    """24. 你处理中 → 待验收：你提交代码，按真实改动重算等级，注明有哪些 AI 参与过。

    人工提交和 Agent 提交是同一套逻辑：同一份真实改动、同样的作废规则、
    同样的 D 级方案门槛。区别只有"写手是你"和"要补记参与过的提供方"。
    """
    if task.status is not TaskStatus.YOU_WORKING:
        return _ignore(task, "只有你处理中才会由你提交代码")
    if event.sha is None or event.changes is None:
        return _ignore(task, "你提交代码时要带提交编号和真实改动，否则按无效提交处理")

    new_level = compute_level(event.changes, policy, event.model_suggestion)
    rule = policy.rule_for(new_level)
    plan_approved = (
        task.approved_plan_version is not None and task.approved_plan_version == task.plan_version
    )
    involved_providers = task.providers_involved | set(event.providers)
    involved = "、".join(sorted(involved_providers)) or "无"
    actions = _Actions(task, task.state_version + 1)

    shared: dict[str, object] = {
        "level": new_level,
        "writer": HUMAN_WRITER,
        "writer_is_human": True,
        "providers_involved": frozenset(involved_providers),
        "latest_sha": event.sha,
        "approved_sha": None,
        "reviews": (),
        "ci_green": False,
        "pr_opened": True,
        "note": f"参与过的 AI：{involved}",
        "returned_from_review": False,
    }
    if rule.requires_plan_approval and not plan_approved:
        actions.add(ActionKind.NOTIFY, detail="你这次改动升成 D 级，要先批准方案")
        return _transition(
            task,
            TaskStatus.AWAITING_PLAN_APPROVAL,
            f"你提交的 {event.sha} 按真实改动算出来是 {new_level.value} 级，方案还没批准",
            actions.items,
            plan_version=task.plan_version + 1,
            **shared,
        )
    actions.add(ActionKind.NOTIFY, detail=f"你提交了 {event.sha}，等 CI")
    return _transition(
        task,
        TaskStatus.AWAITING_ACCEPTANCE,
        f"你提交了代码 {event.sha}（{new_level.value} 级），参与过的 AI：{involved}",
        actions.items,
        **shared,
    )


def _on_abandon(task: TaskRecord, event: Event) -> Decision:
    """25. 待你介入 → 失败：放弃。"""
    if task.status is not TaskStatus.NEEDS_INTERVENTION:
        return _ignore(task, "只有待你介入的任务才会被放弃")
    reason = event.reason or "你决定放弃"
    actions = _Actions(task, task.state_version + 1)
    actions.add(ActionKind.NOTIFY, detail="任务已放弃")
    return _transition(
        task, TaskStatus.FAILED, f"你放弃了任务：{reason}", actions.items, note=reason
    )


# ---------------------------------------------------------------- 第 26–27 条


def _on_retry(task: TaskRecord, event: Event) -> Decision:
    """26. 异常 → 核对后的状态：外壳先去外部核对，再决定回到哪里。"""
    if task.status is not TaskStatus.ERROR:
        return _ignore(task, "只有异常的任务才会重试")
    check = event.check_result
    if check is None:
        return _ignore(task, "重试前必须先去外部核对，并带上核对结果")
    actions = _Actions(task, task.state_version + 1)

    match check:
        case CheckResult.MERGE_SUCCEEDED:
            actions.add(ActionKind.NOTIFY, detail="核对后确认合并已经成功")
            return _transition(
                task,
                TaskStatus.MERGED,
                "核对后确认合并其实已经成功",
                actions.items,
                status_before_error=None,
                error_code=None,
            )
        case CheckResult.PR_CLOSED:
            actions.add(ActionKind.NOTIFY, detail="核对后确认 PR 已被关闭，回到待处理")
            return _transition(
                task,
                TaskStatus.PENDING,
                "核对后确认 PR 已被关闭，回到待处理",
                actions.items,
                status_before_error=None,
                error_code=None,
                ci_green=False,
                reviews=(),
            )
        case CheckResult.NOT_CONFIRMED:
            before = task.status_before_error
            target = before if before is not None and not before.is_terminal else TaskStatus.PENDING
            actions.add(ActionKind.NOTIFY, detail=f"核对后确认没有动作完成，回到{target.value}")
            return _transition(
                task,
                target,
                f"核对后确认没有动作完成，回到{target.value}",
                actions.items,
                status_before_error=None,
                error_code=None,
            )
        case _:  # pragma: no cover
            assert_never(check)


def _on_cancel(task: TaskRecord) -> Decision:
    """27. 除"待合并且合并已经开始"以外的任何非终点状态 → 已取消。"""
    merge_started = any(action.kind is ActionKind.MERGE for action in task.actions)
    if task.status is TaskStatus.AWAITING_MERGE and merge_started:
        return _ignore(task, "合并已经开始，不能取消；想撤回只能走回滚")

    actions = _Actions(task, task.state_version + 1)
    match task.status:
        case TaskStatus.PENDING | TaskStatus.AWAITING_PLAN_APPROVAL:
            # 只改状态，没有东西需要清理
            pass
        case TaskStatus.WORKING | TaskStatus.ERROR:
            actions.add(ActionKind.STOP_AGENT, detail="杀掉 Agent 进程")
            actions.add(ActionKind.PUSH_BRANCH, detail="保留分支作为副本")
        case (
            TaskStatus.AWAITING_ACCEPTANCE
            | TaskStatus.AWAITING_AI_REVIEW
            | TaskStatus.AWAITING_YOUR_REVIEW
            | TaskStatus.NEEDS_INTERVENTION
            | TaskStatus.YOU_WORKING
            | TaskStatus.AWAITING_MERGE
        ):
            actions.add(ActionKind.STOP_AGENT, detail="停掉正在运行的审核进程")
        case TaskStatus.MERGED | TaskStatus.CANCELLED | TaskStatus.FAILED:
            # 终点状态在上面已经拦过了，这里只是让 pyright 能查漏
            return _ignore(task, "任务已经结束，不能取消")
        case _:  # pragma: no cover
            assert_never(task.status)
    if task.pr_opened:
        actions.add(ActionKind.CLOSE_PR, detail="关闭 PR，保留分支")

    return _transition(
        task,
        TaskStatus.CANCELLED,
        f"你在{task.status.value}时取消了任务",
        actions.items,
        reviews=(),
        approved_sha=None,
        returned_from_review=False,
    )
