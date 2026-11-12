"""Generated event traces and independent invariant oracles.

TANDEM_INVARIANTS_DEEP=1: 1000 traces of up to 200 events (CI: 80 x 40).
No network, shell execution, or real agents are used. Review counts follow each
level's policy. D assignments may request a plan; code needs plan approval and
merging needs human approval bound to the current SHA. Plan approval must name
the current plan's SHA, independently of the latest code SHA.
"""

from __future__ import annotations

import os
import re
from copy import deepcopy
from dataclasses import fields, replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tandem.core import transition as core
from tandem.core.model import (
    Action,
    ActionKind,
    ActionStatus,
    ActionUpdate,
    ChangeSet,
    CheckResult,
    Decision,
    Event,
    EventKind,
    FileChange,
    Finding,
    Level,
    OpenFinding,
    Policy,
    QuotaSnapshot,
    QuotaState,
    Review,
    RevisionCount,
    RunMode,
    TaskRecord,
    TaskStatus,
    Thresholds,
    Verdict,
)
from tests.core.helpers import NOW

DEEP = os.getenv("TANDEM_INVARIANTS_DEEP") == "1"
TRACE_SETTINGS = settings(max_examples=1000 if DEEP else 80, deadline=None)
PROVIDERS = ("writer", "r1", "r2", "r3")


def oid(n: int) -> str:
    """40 位十六进制的提交编号。

    内核只认完整 OID：缩写、分支名、任意字符串都会在入口被拒收
    （见 src/tandem/core/identity.py 和 _dispatch 的格式闸门）。
    """
    return f"{n:040x}"


TERMINAL_STATUSES = (TaskStatus.MERGED, TaskStatus.CANCELLED, TaskStatus.FAILED)
TERMINAL_CLEANUP_FIELDS = frozenset(
    {
        "actions",
        "cleanup_checked",
        "note",
        "reason",
        "state_version",
        "updated_at",
    }
)
CLEANUP_KINDS = frozenset({ActionKind.STOP_AGENT, ActionKind.CLOSE_PR, ActionKind.PUSH_BRANCH})


def make_policy(mode: RunMode = RunMode.MULTI_AGENT, required: int = 2) -> Policy:
    return Policy(
        providers=PROVIDERS,
        writer_providers=PROVIDERS,
        reviewer_providers=PROVIDERS,
        default_writer="writer",
        run_mode=mode,
        thresholds=Thresholds(required_reviewers=required),
        bottom_line_paths=("core/**",),
        relaxable_paths=("docs/**",),
        relaxable_extensions=(".md",),
    )


def event(task: TaskRecord, kind: EventKind, **fields: object) -> Event:
    # Typed replace keeps all omitted payload fields genuinely absent.
    return replace(Event(kind, task.task_id, state_version=task.state_version), **fields)


def passing(task: TaskRecord, provider: str) -> Review:
    return Review(
        provider, provider, Verdict.PASS, task.latest_sha or oid(0), task.standard_version
    )


def check_ci(before: TaskRecord, decision: Decision, green_sha: str | None) -> None:
    if any(action.kind is ActionKind.MERGE for action in decision.actions):
        assert decision.task.latest_sha is not None, "ci: missing sha"
        assert decision.task.ci_green, "ci: red flag"
        assert decision.task.latest_sha == green_sha, "ci: no matching external green event"


def check_separation(task: TaskRecord) -> None:
    for review in task.reviews:
        if review.verdict is Verdict.PASS:
            assert review.provider not in task.providers_involved, (
                "separation: a reviewer also wrote this code"
            )


def check_review_count(
    task: TaskRecord,
    policy: Policy,
    human: bool,
    seats: frozenset[str] | None = None,
) -> None:
    """多审核者不变量（P1）：结论必须来自本次**指定的审核席位**，且席位全过。

    ``seats`` 是轨迹在"发出审核请求"那一步记下的席位（输入证据）。不传时退回
    读记录里的 ``designated_reviewers``：那样能抓住"忽略席位校验"的退化，
    但抓不住"把未受邀的人塞进席位"的退化，所以轨迹里一律传记下来的席位。
    """
    if task.status is not TaskStatus.AWAITING_MERGE or human:
        return
    if not task.ci_green:
        # 新内核规则（红队修复）：同一提交先绿后红时，放行证据会被撤销，
        # 但状态可以留在待合并（合并已经发出，不能假装撤回）。这种记录没有
        # "现在就能放行"的证据，不该按待放行去要求审核结论。
        return
    if task.run_mode is RunMode.SINGLE_AGENT or task.level is Level.D:
        return
    designated = set(task.designated_reviewers) if seats is None else set(seats)
    providers = {
        review.provider
        for review in task.reviews
        if review.verdict is Verdict.PASS
        and review.sha == task.latest_sha
        and review.standard_version == task.standard_version
        and review.provider not in task.providers_involved
    }
    assert providers <= designated, "review_count: pass from outside the designated seats"
    needed = policy.rule_for(task.level).min_reviewers
    assert len(providers) >= needed, "review_count: not enough reviewers"
    if needed:
        # 席位都得出结论，不能"两家够了就合并"而漏掉指定的那一家
        assert designated <= providers, "review_count: designated seat has no pass"


def check_terminal(before: TaskRecord, ev: Event, decision: Decision) -> None:
    if before.status not in TERMINAL_STATUSES:
        return
    after = decision.task
    assert after.status is before.status, "terminal: state has an outgoing edge"
    assert not decision.actions, "terminal: dispatched new actions"
    known = {action.action_id: action for action in before.actions}
    valid = (
        ev.kind is EventKind.CLEANUP_CHECKED
        and ev.task_id == before.task_id
        and ev.state_version in (None, before.state_version)
        and ev.check_result in (CheckResult.PR_CLOSED, CheckResult.NOT_CONFIRMED)
        and bool(ev.action_ids)
        and all(
            key in known and known[key].kind in CLEANUP_KINDS and key in before.cleanup_action_ids
            for key in ev.action_ids
        )
    )
    outcome = (
        ActionStatus.DONE if ev.check_result is CheckResult.PR_CLOSED else ActionStatus.ABANDONED
    )
    expected = before.actions
    if valid:
        # A conflicting finished result rejects the ENTIRE batch, including
        # still-open targets. Matching finished targets may accompany open ones.
        if all(
            known[key].status in (ActionStatus.SENT, ActionStatus.UNKNOWN, outcome)
            for key in ev.action_ids
        ):
            expected = tuple(
                replace(action, status=outcome) if action.action_id in ev.action_ids else action
                for action in before.actions
            )
    if expected == before.actions:
        assert not decision.changed and after == before, "terminal: ignored event changed record"
        assert not decision.action_updates, "terminal: ignored event wrote action updates"
        return
    assert decision.changed, "terminal: cleanup receipt was not recorded"
    # A whitelist protects every other field, including future TaskRecord fields.
    for field in fields(TaskRecord):
        if field.name not in TERMINAL_CLEANUP_FIELDS:
            assert getattr(after, field.name) == getattr(before, field.name), (
                f"terminal: changed protected field {field.name}"
            )
    assert decision.action_updates == [
        ActionUpdate(key, outcome) for key in dict.fromkeys(ev.action_ids)
    ], "terminal: wrong action bookkeeping updates"
    assert after.actions == expected, "terminal: changed action identity or wrong target/status"
    assert after.cleanup_checked is True, "terminal: cleanup flag missing"
    assert after.state_version == before.state_version + 1, "terminal: cleanup version must add one"
    assert after.updated_at == NOW, "terminal: cleanup time must use supplied clock"


def check_version(before: TaskRecord, decision: Decision) -> None:
    if decision.changed:
        assert decision.task.state_version == before.state_version + 1, (
            "version: changed record must add exactly one version"
        )
    else:
        assert decision.task == before, "version: ignored record changed"
        assert not decision.actions, "version: ignored actions"
        assert not decision.action_updates, "version: ignored action updates"


def check_d(before: TaskRecord, decision: Decision, human_sha: str | None) -> None:
    """D 级关卡：方案要批过，合并前要有绑定当前提交的人工批准。

    "必须经过待你审核"这一半由 check_approval_route 做路径检查：只看
    "有过一次 sha 对得上的人工批准"是近似（从待验收直接批准也能满足）。
    """
    after = decision.task
    if after.level is not Level.D:
        return
    if after.status in (
        TaskStatus.AWAITING_ACCEPTANCE,
        TaskStatus.AWAITING_AI_REVIEW,
        TaskStatus.AWAITING_MERGE,
    ):
        assert after.approved_plan_version is not None, "d: no approved plan"
        assert after.approved_plan_version == after.plan_version, "d: stale plan"
    if after.status is TaskStatus.AWAITING_MERGE:
        assert human_sha is not None and human_sha == after.latest_sha, (
            "d: no current human approval"
        )


def human_approval_sha(
    before: TaskRecord,
    ev: Event,
    decision: Decision,
    previous: str | None = None,
) -> str | None:
    """Track actual input approval events, independently of approved_sha output."""
    if decision.task.latest_sha != before.latest_sha:
        previous = None
    if (
        decision.changed
        and ev.kind in (EventKind.YOUR_APPROVAL, EventKind.INTERVENTION_APPROVED)
        and ev.sha is not None
        and ev.sha == before.latest_sha
    ):
        return ev.sha
    return previous


def current_plan_sha(task: TaskRecord) -> str | None:
    # Read the versioned input evidence rather than trusting an approval output.
    entries = [entry for entry in task.plan_history if entry.version == task.plan_version]
    return entries[0].sha if entries and entries[0].sha else task.latest_sha


def check_plan_approval(before: TaskRecord, ev: Event, decision: Decision) -> None:
    if ev.kind is not EventKind.PLAN_APPROVED:
        return
    if before.status is not TaskStatus.AWAITING_PLAN_APPROVAL:
        assert not decision.changed, "plan_sha: approval outside plan review"
        return
    expected = current_plan_sha(before)
    if ev.sha is None or ev.sha != expected:
        assert not decision.changed and decision.task == before, "plan_sha: wrong plan approved"
    elif decision.changed:
        assert decision.task.approved_plan_version == before.plan_version, "plan_sha: wrong version"


def check_approval_route(before: TaskRecord, ev: Event, decision: Decision) -> None:
    """P2：改变记录的批准，来源状态必须是对的。

    任务书第 6 条写的是"D 级永远不会不经过『待你审核』就进入『待合并』"。
    只记"有过一次 sha 对得上的人工批准"不够：从待验收直接批准也能满足它。
    真正的路径检查是看**批准发生在哪个状态**：

    - YOUR_APPROVAL 只能来自待你审核（第 17 条）；
    - INTERVENTION_APPROVED 只能来自待你介入（第 20 条）。

    于是 D 级的两条合法路径都被钉住：审核全过 → 待你审核 → 你批准，
    或者走到待你介入 → 你人工审核通过；"从待验收直接批准"会被这条抓住。
    """
    if not decision.changed:
        return
    if ev.kind is EventKind.YOUR_APPROVAL:
        assert before.status is TaskStatus.AWAITING_YOUR_REVIEW, (
            "approval_route: your approval outside 待你审核"
        )
    elif ev.kind is EventKind.INTERVENTION_APPROVED:
        assert before.status is TaskStatus.NEEDS_INTERVENTION, (
            "approval_route: intervention approval outside 待你介入"
        )


def check_ci_sha(before: TaskRecord, ev: Event, decision: Decision) -> None:
    """P5：CI 结论必须绑定当前提交编号。

    check_ci 只在"出现 MERGE 动作"时核对绿灯，覆盖面太窄：错误编号的 CI 绿
    要等到后面审核凑齐、真的去合并时才可能暴露。这条在事件发生时就核对。
    """
    if ev.kind not in (EventKind.CI_GREEN, EventKind.CI_RED) or not decision.changed:
        return
    assert ev.sha is not None and ev.sha == before.latest_sha, (
        "ci_sha: CI result applied to another commit"
    )


def check_stale(before: TaskRecord, ev: Event, decision: Decision) -> None:
    """P4：过期或错位的事件必须被忽略，状态和版本号都不变。

    任务书要求生成器覆盖"过期、错位"事件，生成器一直在造（未来版本号、
    别的任务编号），但之前没有任何 oracle 断言"这些事件必须被忽略"，
    所以删掉版本号校验只能靠别的 oracle 偶然撞上。
    """
    if ev.task_id != before.task_id:
        assert not decision.changed and decision.task == before, (
            "stale: accepted an event for another task"
        )
        return
    if ev.state_version is not None and ev.state_version != before.state_version:
        assert not decision.changed and decision.task == before, (
            "stale: accepted an event with a stale version"
        )


def check_approval_sha(before: TaskRecord, ev: Event, decision: Decision) -> None:
    """P3：批准必须绑定当前提交编号才能进入待合并（r4 问题 3）。

    内核里 _on_your_approval / _on_intervention_approved 都要求
    ``event.sha == task.latest_sha``，否则忽略。这条不变量之前没有 oracle：
    去掉 sha 校验后，C 级任务收到任何编号的批准都会进入待合并，而
    check_review_count 在"有人工批准"时提前返回，于是全部放行。
    """
    if ev.kind not in (EventKind.YOUR_APPROVAL, EventKind.INTERVENTION_APPROVED):
        return
    bound = ev.sha is not None and ev.sha == before.latest_sha
    if decision.changed and decision.task.status is TaskStatus.AWAITING_MERGE:
        assert bound, "approval_sha: merged on an approval for another commit"
    elif not bound:
        assert not decision.changed, "approval_sha: unbound approval changed the record"


def check_fresh(before: TaskRecord, decision: Decision) -> None:
    after = decision.task
    if after.latest_sha != before.latest_sha:
        assert not after.reviews, "fresh: retained reviews"
        assert after.approved_sha is None, "fresh: retained approval"
        assert not after.ci_green, "fresh: retained CI"
    for review in after.reviews:
        assert review.sha == after.latest_sha, "fresh: old review counted"


def check_pure(before: TaskRecord, ev: Event, policy: Policy, quota: QuotaSnapshot) -> Decision:
    snapshot = deepcopy((before, ev, policy, quota, NOW))
    first = core.decide(before, ev, policy, quota, NOW)
    second = core.decide(before, ev, policy, quota, NOW)
    assert first == second, "pure: different outputs"
    assert (before, ev, policy, quota, NOW) == snapshot, "pure: mutated input"
    return first


def misplaced_kind(task: TaskRecord, fallback: EventKind) -> EventKind:
    """P5：把"错位事件"换成与当前状态相关的种类。

    以前 choice==3 从 23 种事件里均匀抽，撞到"待验收 + CI_GREEN"的概率约
    0.4%/步，默认规模下经常一次都撞不到；按状态挑种类以后，同样 80 个例子
    能打到的组合明显变多。
    """
    return {
        TaskStatus.WORKING: EventKind.CODE_SUBMITTED,
        TaskStatus.AWAITING_PLAN_APPROVAL: EventKind.PLAN_APPROVED,
        TaskStatus.AWAITING_ACCEPTANCE: EventKind.CI_GREEN,
        TaskStatus.AWAITING_AI_REVIEW: EventKind.REVIEW,
        TaskStatus.AWAITING_YOUR_REVIEW: EventKind.YOUR_APPROVAL,
        TaskStatus.AWAITING_MERGE: EventKind.MERGED,
    }.get(task.status, fallback)


def advance(task: TaskRecord) -> Event:
    kind = {
        TaskStatus.PENDING: EventKind.ASSIGN,
        TaskStatus.WORKING: EventKind.CODE_SUBMITTED,
        TaskStatus.AWAITING_PLAN_APPROVAL: EventKind.PLAN_APPROVED,
        TaskStatus.AWAITING_ACCEPTANCE: EventKind.CI_GREEN,
        TaskStatus.AWAITING_AI_REVIEW: EventKind.REVIEW,
        TaskStatus.AWAITING_YOUR_REVIEW: EventKind.YOUR_APPROVAL,
        TaskStatus.AWAITING_MERGE: EventKind.MERGED,
        TaskStatus.NEEDS_INTERVENTION: EventKind.TAKE_OVER,
        TaskStatus.YOU_WORKING: EventKind.YOU_SUBMITTED_CODE,
        TaskStatus.ERROR: EventKind.RETRY,
    }.get(task.status, EventKind.CREATED)
    missing = [p for p in task.designated_reviewers if p not in {r.provider for r in task.reviews}]
    changes = ChangeSet(paths=("core/a.py",) if task.level is Level.D else ("app.py",))
    if task.level is Level.A:
        changes = ChangeSet()
    if task.level is Level.B:
        changes = ChangeSet(
            paths=("docs/a.md",),
            file_changes=(FileChange("docs/a.md", "100644", "100644"),),
        )
    # 只有提交类事件需要新编号；其余事件要么沿用当前编号，要么根本不需要编号。
    sha: str | None = task.latest_sha
    if kind in (EventKind.CODE_SUBMITTED, EventKind.YOU_SUBMITTED_CODE):
        sha = oid(task.state_version + 1)
    elif kind is EventKind.PLAN_APPROVED:
        sha = current_plan_sha(task)
    return event(
        task,
        kind,
        sha=sha,
        plan="Generated proposal",
        attempt=task.attempt,
        changes=changes,
        model_suggestion=task.level,
        review=passing(task, missing[0] if missing else "r1"),
        check_result=CheckResult.NOT_CONFIRMED,
        action_ids=tuple(a.action_id for a in task.actions if a.kind in CLEANUP_KINDS),
    )


def execute_trace(
    level: Level,
    mode: RunMode,
    required: int,
    prefix: int,
    instructions: list[tuple[int, EventKind, int]],
) -> list[TaskStatus]:
    """跑一条轨迹：每一步都过一遍全部 oracle，返回访问过的状态（含起点）。"""
    policy = make_policy(mode, required)
    task = core.create_task("trace", level, policy)
    visited: list[TaskStatus] = [task.status]
    green_sha: str | None = None
    human_sha: str | None = None
    # 记下"这一步发出去的审核席位"，作为下一步的输入证据：
    # 只看输出记录里的席位，抓不住"把未受邀的人塞进席位"的退化。
    issued_seats: dict[str, frozenset[str]] = {}
    # Guarantee useful progress in every example, then interleave arbitrary events.
    instructions = [(0, EventKind.CREATED, 0)] * prefix + instructions
    for choice, kind, value in instructions:
        ev = advance(task)
        quota = QuotaSnapshot()
        if choice == 1:
            ev = replace(ev, kind=kind)
        elif choice == 2:
            ev = replace(ev, state_version=task.state_version + 1)
        elif choice == 3:
            # Wrong SHA, old attempts/standards, writer impersonation, missing fields.
            provider = PROVIDERS[value % len(PROVIDERS)]
            ev = event(
                task,
                misplaced_kind(task, kind),
                sha=f"s{value}",
                attempt=value - 1,
                provider=provider,
                providers=(provider,),
                standard_version=value,
                review=replace(
                    passing(task, provider),
                    reviewer="r1-session",
                    sha=f"s{value % 2}",
                    standard_version=value,
                    verdict=Verdict.FAIL if value % 2 else Verdict.PASS,
                    findings=(Finding("F1", "problem"),) if value % 3 else (),
                ),
                changes=ChangeSet(paths=("core/a.py",) if value % 2 else ("app.py",)),
                check_result=list(CheckResult)[value % 3],
                action_ids=(
                    tuple(a.action_id for a in task.actions if a.kind in CLEANUP_KINDS)
                    if value % 2 == 0
                    else ("unknown-action",)
                ),
                plan="Generated proposal",
            )
        elif choice == 4:
            ev = replace(ev, task_id="another-task")
        elif choice == 5:
            quota = QuotaSnapshot(((PROVIDERS[value % 4], QuotaState.EXHAUSTED),))
        elif choice == 6:
            ev = replace(ev, kind=EventKind.PLAN_APPROVED, sha=None)
        elif choice == 7:
            # 未受邀的提供方发一条通过结论（既没写过代码，也不在席位里）
            outsider = next(
                (
                    provider
                    for provider in PROVIDERS
                    if provider not in task.designated_reviewers
                    and provider not in task.providers_involved
                ),
                "outsider",
            )
            ev = event(task, EventKind.REVIEW, review=passing(task, outsider))
        elif choice == 8:
            # 岔路：把任务推向"待你介入 / 你处理中"（第 11/14b/15/20/23 条）。
            # 随机均匀抽事件时这几条路几乎走不到：要连续三次验收失败才会到待你介入。
            if task.status is TaskStatus.AWAITING_ACCEPTANCE:
                ev = replace(ev, kind=EventKind.CI_RED, sha=task.latest_sha)
            elif task.status is TaskStatus.NEEDS_INTERVENTION:
                ev = replace(ev, kind=EventKind.TAKE_OVER)
            elif task.status is TaskStatus.YOU_WORKING:
                ev = replace(ev, kind=EventKind.YOU_SUBMITTED_CODE)
        elif choice == 9:
            # 终点：放弃（待你介入 → 失败）或打回/合并
            if task.status is TaskStatus.NEEDS_INTERVENTION:
                ev = replace(ev, kind=EventKind.ABANDON, reason="放弃")
            elif task.status is TaskStatus.AWAITING_YOUR_REVIEW:
                ev = replace(ev, kind=EventKind.YOUR_REJECTION, reason="打回")
            elif task.status is TaskStatus.AWAITING_MERGE:
                ev = replace(ev, kind=EventKind.MERGED, sha=task.approved_sha or task.latest_sha)
        before = task
        decision = check_pure(before, ev, policy, quota)
        if decision.changed and ev.kind is EventKind.CI_GREEN:
            green_sha = ev.sha
        if decision.task.latest_sha != before.latest_sha:
            green_sha = None
            human_sha = None
        if decision.changed and ev.kind is EventKind.CI_RED:
            green_sha = None
        human_sha = human_approval_sha(before, ev, decision, human_sha)
        if decision.changed and decision.task.designated_reviewers:
            issued_seats[decision.task.latest_sha or ""] = frozenset(
                decision.task.designated_reviewers
            )
        check_ci(before, decision, green_sha)
        check_separation(decision.task)
        check_review_count(
            decision.task,
            policy,
            human_sha is not None and human_sha == decision.task.latest_sha,
            seats=issued_seats.get(decision.task.latest_sha or ""),
        )
        check_terminal(before, ev, decision)
        check_version(before, decision)
        check_d(before, decision, human_sha)
        check_approval_route(before, ev, decision)
        check_approval_sha(before, ev, decision)
        check_stale(before, ev, decision)
        check_ci_sha(before, ev, decision)
        check_plan_approval(before, ev, decision)
        check_fresh(before, decision)
        task = decision.task
        visited.append(task.status)
    return visited


@TRACE_SETTINGS
@given(
    level=st.sampled_from(list(Level)),
    mode=st.sampled_from(list(RunMode)),
    required=st.integers(2, 3),
    prefix=st.integers(0, 9),
    instructions=st.lists(
        st.tuples(st.integers(0, 9), st.sampled_from(list(EventKind)), st.integers(0, 7)),
        min_size=1,
        max_size=200 if DEEP else 40,
    ),
)
def test_generated_event_sequences(level, mode, required, prefix, instructions) -> None:
    execute_trace(level, mode, required, prefix, instructions)


# 确定性的轨迹配方：每条都写明它负责把生成器带到哪些状态。
# 用固定输入而不是随机种子，避免"覆盖率断言偶尔变红"。
COVERAGE_TRACES: list[tuple[Level, RunMode, int, int, list[tuple[int, EventKind, int]]]] = [
    # 正常路径：待处理 → 处理中 → 待验收 → 待AI审核 → 待合并 → 已合并
    (
        Level.C,
        RunMode.MULTI_AGENT,
        2,
        0,
        [
            (0, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (9, EventKind.CREATED, 0),
        ],
    ),
    # D 级：待你批准方案 → 待你审核
    (
        Level.D,
        RunMode.MULTI_AGENT,
        2,
        0,
        [
            (0, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
        ],
    ),
    # 岔路：验收失败三次 → 待你介入 → 你处理中
    (
        Level.C,
        RunMode.MULTI_AGENT,
        2,
        0,
        [
            (0, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (8, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (8, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (8, EventKind.CREATED, 0),
            (8, EventKind.CREATED, 0),
        ],
    ),
    # 终点：待你介入 → 失败；异常 → 已取消
    (
        Level.C,
        RunMode.MULTI_AGENT,
        2,
        0,
        [
            (0, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (8, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (8, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (0, EventKind.CREATED, 0),
            (8, EventKind.CREATED, 0),
            (9, EventKind.CREATED, 0),
        ],
    ),
    (
        Level.C,
        RunMode.MULTI_AGENT,
        2,
        0,
        [
            (0, EventKind.CREATED, 0),
            (1, EventKind.INCIDENT, 0),
            (1, EventKind.CANCEL, 0),
        ],
    ),
]


def test_generator_reaches_every_state() -> None:
    """P7：13 个状态每个都至少被生成器走到一次。

    以前 NEEDS_INTERVENTION / YOU_WORKING / FAILED（以及 ERROR / CANCELLED）
    在随机轨迹里一次都没出现，第 1/3/5 条不变量在这几个状态上只靠手写例子。
    这里用固定的轨迹配方证明"生成器确实能走到"，随机轨迹由 choice 8/9 提高概率。
    """
    visited: set[TaskStatus] = set()
    for level, mode, required, prefix, instructions in COVERAGE_TRACES:
        visited.update(execute_trace(level, mode, required, prefix, instructions))
    missing = sorted(status.name for status in set(TaskStatus) - visited)
    assert not missing, f"generator never reached these states: {missing}"


def walk(level: Level, kinds: list[EventKind], policy: Policy | None = None) -> TaskRecord:
    selected = policy or make_policy()
    task = core.create_task("regression", level, selected)
    for kind in kinds:
        task = core.decide(
            task, replace(advance(task), kind=kind), selected, QuotaSnapshot(), NOW
        ).task
    return task


def test_ci_sha_mutant_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """P5：删掉 _on_ci_green 的编号校验后，新 oracle 必须报错。"""
    policy = make_policy()
    task = walk(Level.C, [EventKind.ASSIGN, EventKind.CODE_SUBMITTED])
    assert task.status is TaskStatus.AWAITING_ACCEPTANCE
    ev = event(task, EventKind.CI_GREEN, sha=oid(555))
    baseline = core.decide(task, ev, policy, QuotaSnapshot(), NOW)
    assert not baseline.changed
    check_ci_sha(task, ev, baseline)
    original = core._on_ci_green

    def ignore_ci_sha(
        task: TaskRecord, ev: Event, policy: Policy, quota: QuotaSnapshot
    ) -> Decision:
        return original(task, replace(ev, sha=task.latest_sha), policy, quota)

    monkeypatch.setattr(core, "_on_ci_green", ignore_ci_sha)
    decision = core.decide(task, ev, policy, QuotaSnapshot(), NOW)
    assert decision.changed
    with pytest.raises(AssertionError, match="ci_sha"):
        check_ci_sha(task, ev, decision)


def test_stale_event_mutant_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """P4：删掉入口的版本号校验后，"过期事件被忽略"这条必须报错。"""
    policy = make_policy()
    task = walk(Level.C, [EventKind.ASSIGN, EventKind.CODE_SUBMITTED, EventKind.CI_GREEN])
    assert task.status is TaskStatus.AWAITING_AI_REVIEW
    seat = task.designated_reviewers[0]
    stale_ev = replace(
        event(task, EventKind.REVIEW, review=passing(task, seat)),
        state_version=task.state_version + 1,
    )
    baseline = core.decide(task, stale_ev, policy, QuotaSnapshot(), NOW)
    assert not baseline.changed
    check_stale(task, stale_ev, baseline)
    original = core._dispatch

    def ignore_version(
        task: TaskRecord, ev: Event, policy: Policy, quota: QuotaSnapshot
    ) -> Decision:
        return original(task, replace(ev, state_version=None), policy, quota)

    monkeypatch.setattr(core, "_dispatch", ignore_version)
    decision = core.decide(task, stale_ev, policy, QuotaSnapshot(), NOW)
    assert decision.changed
    with pytest.raises(AssertionError, match="stale"):
        check_stale(task, stale_ev, decision)


def test_approval_sha_mutant_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """P3：去掉"批准绑定当前提交编号"的校验后，oracle 必须报错。"""
    policy = make_policy(RunMode.SINGLE_AGENT)
    task = walk(Level.C, [EventKind.ASSIGN, EventKind.CODE_SUBMITTED, EventKind.CI_GREEN], policy)
    assert task.status is TaskStatus.AWAITING_YOUR_REVIEW
    ev = event(task, EventKind.YOUR_APPROVAL, sha=oid(777))
    baseline = core.decide(task, ev, policy, QuotaSnapshot(), NOW)
    assert not baseline.changed
    check_approval_sha(task, ev, baseline)
    original = core._on_your_approval

    def ignore_approval_sha(task: TaskRecord, ev: Event, policy: Policy) -> Decision:
        return original(task, replace(ev, sha=task.latest_sha), policy)

    monkeypatch.setattr(core, "_on_your_approval", ignore_approval_sha)
    decision = core.decide(task, ev, policy, QuotaSnapshot(), NOW)
    assert decision.task.status is TaskStatus.AWAITING_MERGE
    with pytest.raises(AssertionError, match="approval_sha"):
        check_approval_sha(task, ev, decision)


def test_approval_route_rejects_approval_from_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P2：从待验收直接人工批准（跳过待你审核）必须被抓到。"""
    policy = make_policy()
    task = walk(
        Level.D,
        [
            EventKind.ASSIGN,
            EventKind.CODE_SUBMITTED,
            EventKind.PLAN_APPROVED,
            EventKind.ASSIGN,
            EventKind.CODE_SUBMITTED,
            EventKind.CI_GREEN,
        ],
    )
    assert task.status is TaskStatus.AWAITING_AI_REVIEW
    ev = event(task, EventKind.INTERVENTION_APPROVED, sha=task.latest_sha)
    # 基线：待验收/AI 审核期间的人工批准被内核拒收
    baseline = core.decide(task, ev, policy, QuotaSnapshot(), NOW)
    assert not baseline.changed
    check_approval_route(task, ev, baseline)
    original = core._on_intervention_approved

    def accept_from_anywhere(task: TaskRecord, ev: Event, policy: Policy) -> Decision:
        # 退化：把"待AI审核"直接当成"待你介入"，等于跳过待你审核
        if task.status is TaskStatus.AWAITING_AI_REVIEW:
            task = replace(task, status=TaskStatus.NEEDS_INTERVENTION)
        return original(task, ev, policy)

    monkeypatch.setattr(core, "_on_intervention_approved", accept_from_anywhere)
    decision = core.decide(task, ev, policy, QuotaSnapshot(), NOW)
    assert decision.task.status is TaskStatus.AWAITING_MERGE
    check_d(task, decision, human_approval_sha(task, ev, decision))
    with pytest.raises(AssertionError, match="approval_route"):
        check_approval_route(task, ev, decision)


def test_review_count_rejects_pass_from_outside_the_seats() -> None:
    """P1：未受邀的通过结论不能算进家数（席位记录保持原样时也要被抓到）。"""
    policy = make_policy(required=2)
    task = walk(Level.C, [EventKind.ASSIGN, EventKind.CODE_SUBMITTED, EventKind.CI_GREEN])
    seats = frozenset(task.designated_reviewers)
    assert len(seats) == 2
    outsider = next(
        provider
        for provider in PROVIDERS
        if provider not in seats and provider not in task.providers_involved
    )
    for provider in task.designated_reviewers:
        task = core.decide(
            task,
            event(task, EventKind.REVIEW, review=passing(task, provider)),
            policy,
            QuotaSnapshot(),
            NOW,
        ).task
    assert task.status is TaskStatus.AWAITING_MERGE
    check_review_count(task, policy, False, seats=seats)
    corrupted = replace(
        task,
        reviews=(passing(task, outsider), *(r for r in task.reviews if r.provider != "r1")),
    )
    with pytest.raises(AssertionError, match="review_count"):
        check_review_count(corrupted, policy, False, seats=seats)


def test_review_seat_mutant_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """P1：把内核退化成"不查席位、按家数凑够就合并"，oracle 必须报错。"""
    policy = make_policy(required=2)
    task = walk(Level.C, [EventKind.ASSIGN, EventKind.CODE_SUBMITTED, EventKind.CI_GREEN])
    seats = frozenset(task.designated_reviewers)
    outsider = next(
        provider
        for provider in PROVIDERS
        if provider not in seats and provider not in task.providers_involved
    )
    original = core._on_review

    def seat_blind(task: TaskRecord, ev: Event, policy: Policy) -> Decision:
        review = ev.review
        if task.status is not TaskStatus.AWAITING_AI_REVIEW or review is None:
            return original(task, ev, policy)
        recorded = replace(
            task,
            reviews=task.reviews + (review,),
            review_history=task.review_history + (review,),
        )
        passing_now = {
            item.provider
            for item in recorded.current_reviews()
            if item.verdict is Verdict.PASS and item.provider not in recorded.providers_involved
        }
        if len(passing_now) >= policy.rule_for(task.level).min_reviewers:
            actions = core._Actions(recorded, recorded.state_version + 1)
            return core._merge(
                recorded,
                policy,
                "变异体：不看席位，家数够就合并",
                actions,
                recorded,
                approved_sha=recorded.latest_sha,
            )
        return original(task, ev, policy)

    # 基线：未受邀的结论被内核拒收
    baseline = core.decide(
        task,
        event(task, EventKind.REVIEW, review=passing(task, outsider)),
        policy,
        QuotaSnapshot(),
        NOW,
    )
    assert not baseline.changed
    monkeypatch.setattr(core, "_on_review", seat_blind)
    task = core.decide(
        task,
        event(task, EventKind.REVIEW, review=passing(task, sorted(seats)[0])),
        policy,
        QuotaSnapshot(),
        NOW,
    ).task
    decision = core.decide(
        task,
        event(task, EventKind.REVIEW, review=passing(task, outsider)),
        policy,
        QuotaSnapshot(),
        NOW,
    )
    assert decision.task.status is TaskStatus.AWAITING_MERGE
    with pytest.raises(AssertionError, match="review_count"):
        check_review_count(decision.task, policy, False, seats=seats)


@pytest.mark.parametrize("level", [Level.A, Level.B])
def test_a_b_review_counts_follow_policy(level: Level) -> None:
    kinds = [EventKind.ASSIGN, EventKind.CODE_SUBMITTED, EventKind.CI_GREEN]
    if level is Level.B:
        kinds.append(EventKind.REVIEW)
    task = walk(level, kinds)
    assert task.status is TaskStatus.AWAITING_MERGE
    check_review_count(task, make_policy(), False)
    assert len(task.reviews) == (0 if level is Level.A else 1)


def test_d_assignment_requests_plan_but_code_stays_gated() -> None:
    task = walk(Level.D, [EventKind.ASSIGN])
    assert task.status is TaskStatus.WORKING
    assert task.approved_plan_version is None
    decision = core.decide(task, advance(task), make_policy(), QuotaSnapshot(), NOW)
    assert decision.task.status is TaskStatus.AWAITING_PLAN_APPROVAL
    check_d(task, decision, None)


@pytest.mark.parametrize("sha", [oid(1), "stale", None])
def test_d_intervention_approval_requires_current_sha(sha: str | None) -> None:
    policy = make_policy()
    task = walk(
        Level.D,
        [
            EventKind.ASSIGN,
            EventKind.CODE_SUBMITTED,
            EventKind.PLAN_APPROVED,
            EventKind.ASSIGN,
            EventKind.CODE_SUBMITTED,
        ],
    )
    assert task.status is TaskStatus.AWAITING_ACCEPTANCE
    task = core.decide(
        task,
        event(task, EventKind.CI_GREEN, sha=task.latest_sha),
        policy,
        QuotaSnapshot((("r1", QuotaState.EXHAUSTED), ("r2", QuotaState.EXHAUSTED))),
        NOW,
    ).task
    assert task.status is TaskStatus.NEEDS_INTERVENTION
    decision = core.decide(
        task,
        event(task, EventKind.INTERVENTION_APPROVED, sha=sha),
        policy,
        QuotaSnapshot(),
        NOW,
    )
    ev = event(task, EventKind.INTERVENTION_APPROVED, sha=sha)
    if sha == task.latest_sha:
        assert decision.task.status is TaskStatus.AWAITING_MERGE
    else:
        assert not decision.changed and decision.task == task
    check_d(task, decision, human_approval_sha(task, ev, decision))


def test_regression_new_plan_sha_invalidates_old_ci() -> None:
    policy = make_policy()
    task = walk(
        Level.D,
        [
            EventKind.ASSIGN,
            EventKind.CODE_SUBMITTED,
            EventKind.PLAN_APPROVED,
            EventKind.ASSIGN,
            EventKind.CODE_SUBMITTED,
            EventKind.CI_GREEN,
        ],
    )
    review = replace(passing(task, "r1"), verdict=Verdict.FAIL, findings=(Finding("F1", "fix"),))
    task = core.decide(
        task, event(task, EventKind.REVIEW, review=review), policy, QuotaSnapshot(), NOW
    ).task
    task = core.decide(task, event(task, EventKind.ASSIGN), policy, QuotaSnapshot(), NOW).task
    assert task.status is TaskStatus.WORKING and task.ci_green
    decision = core.decide(
        task, event(task, EventKind.PLAN_SUBMITTED, sha=oid(77)), policy, QuotaSnapshot(), NOW
    )
    assert decision.task.latest_sha == oid(77)
    check_fresh(task, decision)


def test_oracle_messages_are_anchored_to_their_name() -> None:
    """P6：变异测试按 "<名字>: " 前缀匹配，不能被别的 oracle 的消息顶包。

    旧写法 ``match="d"`` 会匹配任何含字母 d 的消息，例如
    "pure: different outputs"、"terminal: changed protected field writer"；
    witness 里一旦再加一条断言，"D 级变异"就可能被无关断言"顶包"通过。
    """
    assert re.search(r"^d: ", "d: no current human approval")
    assert not re.search(r"^d: ", "pure: different outputs")
    assert not re.search(r"^d: ", "terminal: changed protected field writer")
    # 旧写法确实会匹配到这两条无关消息（这就是要修掉的风险）
    assert re.search("d", "pure: different outputs")
    assert re.search("d", "terminal: changed protected field writer")


@pytest.mark.parametrize(
    "invariant",
    [
        "ci",
        "separation",
        "review_count",
        "terminal",
        "version",
        "d",
        "pure",
        "fresh",
    ],
)
def test_oracles_reject_kernel_mutants(monkeypatch: pytest.MonkeyPatch, invariant: str) -> None:
    """Each production-logic mutation must fail the SAME oracle used by traces.

    Run its witness once unmodified first, so an unrelated/pre-existing failure
    cannot masquerade as a killed mutant. Patches never escape this test.
    """
    policy = make_policy()
    quota = QuotaSnapshot()
    task = walk(Level.C, [EventKind.ASSIGN, EventKind.CODE_SUBMITTED, EventKind.CI_GREEN])
    ev = event(task, EventKind.REVIEW, review=passing(task, "r1"))
    original_dispatch = core._dispatch
    original_transition = core._transition
    original_rule = Policy.rule_for
    original_review = core._on_review
    original_new = core._on_new_submission
    original_add = core._Actions.add

    if invariant == "ci":
        task = replace(task, status=TaskStatus.AWAITING_YOUR_REVIEW, ci_green=False)
        ev = event(task, EventKind.YOUR_APPROVAL, sha=task.latest_sha)
    elif invariant == "separation":
        # A designated provider has subsequently participated in writing.
        task = replace(task, providers_involved=task.providers_involved | {"r1"})
    elif invariant == "review_count":
        task = replace(task, designated_reviewers=("r1",))
    elif invariant == "pure":
        ev = event(task, EventKind.INCIDENT)
    elif invariant == "terminal":
        task = walk(Level.C, [EventKind.CANCEL])
        ev = event(task, EventKind.ASSIGN)
    elif invariant == "d":
        task = walk(Level.D, [EventKind.ASSIGN])
        ev = advance(task)
    elif invariant == "fresh":
        task = core.decide(task, ev, policy, quota, NOW).task
        ev = event(
            task,
            EventKind.CODE_SUBMITTED,
            sha=oid(4242),
            attempt=task.attempt,
            changes=ChangeSet(paths=("app.py",)),
        )

    def witness() -> None:
        decision = check_pure(task, ev, policy, quota)
        if invariant == "ci":
            check_ci(task, decision, None)
        elif invariant == "separation":
            check_separation(decision.task)
        elif invariant == "review_count":
            check_review_count(decision.task, policy, False)
        elif invariant == "terminal":
            check_terminal(task, ev, decision)
        elif invariant == "version":
            check_version(task, decision)
        elif invariant == "d":
            check_d(task, decision, None)
        elif invariant == "fresh":
            check_fresh(task, decision)

    witness()
    if invariant == "ci":
        monkeypatch.setattr(core, "merge_blocker", lambda *args, **kwargs: ())
    elif invariant == "separation":

        def accept_writer(task, ev, policy):
            decision = original_review(replace(task, providers_involved=frozenset()), ev, policy)
            return replace(
                decision,
                task=replace(
                    decision.task,
                    providers_involved=task.providers_involved,
                ),
            )

        monkeypatch.setattr(core, "_on_review", accept_writer)
    elif invariant == "review_count":

        def one_vote(task, ev, policy):
            weakened = replace(
                policy, level_rules=(replace(policy.rule_for(task.level), min_reviewers=1),)
            )
            return original_review(task, ev, weakened)

        # Weaken the kernel's quorum, leaving the oracle's input policy intact.
        monkeypatch.setattr(core, "_on_review", one_vote)
    elif invariant == "terminal":

        def reopen(task, ev, policy, quota):
            return original_dispatch(replace(task, status=TaskStatus.PENDING), ev, policy, quota)

        monkeypatch.setattr(core, "_dispatch", reopen)
    elif invariant == "version":

        def double_bump(*args, **kwargs):
            result = original_transition(*args, **kwargs)
            return replace(
                result,
                task=replace(
                    result.task,
                    state_version=result.task.state_version + 1,
                ),
            )

        monkeypatch.setattr(core, "_transition", double_bump)
    elif invariant == "d":

        def no_plan(self, level):
            return replace(original_rule(self, level), requires_plan_approval=False)

        monkeypatch.setattr(Policy, "rule_for", no_plan)
    elif invariant == "pure":
        # Emit an action whose identity depends on hidden call history.
        counter = 0

        def stateful_add(self, kind, detail="", provider=None):
            nonlocal counter
            counter += 1
            return original_add(self, kind, f"{detail}:{counter}", provider)

        monkeypatch.setattr(core._Actions, "add", stateful_add)
    elif invariant == "fresh":

        def keep_old_reviews(task, ev, policy):
            result = original_new(task, ev, policy)
            return replace(result, task=replace(result.task, reviews=task.reviews))

        monkeypatch.setattr(core, "_on_new_submission", keep_old_reviews)
    # P6：按消息前缀精确匹配。"d" 这种单字母会匹配到任何含 d 的消息
    # （"pure: different outputs"、"terminal: ..."），一旦 witness 里再加一条
    # 断言，变异就可能被无关断言"顶包"通过。
    with pytest.raises(AssertionError, match=f"^{re.escape(invariant)}: "):
        witness()


def terminal_record(status: TaskStatus, version: int = 10, sha: str = oid(10)) -> TaskRecord:
    # Populate evidence/history so a cleanup implementation that clears them is
    # detected even when it preserves the terminal status and increments version.
    base = walk(
        Level.D,
        [
            EventKind.ASSIGN,
            EventKind.CODE_SUBMITTED,
            EventKind.PLAN_APPROVED,
            EventKind.ASSIGN,
            EventKind.CODE_SUBMITTED,
            EventKind.CI_GREEN,
            EventKind.REVIEW,
        ],
    )
    return replace(
        base,
        status=status,
        state_version=version,
        latest_sha=sha,
        approved_sha=sha,
        status_before_error=TaskStatus.AWAITING_AI_REVIEW,
        error_code="retained-error",
        base_sha="base",
        accept_failures=2,
        revision_counts=(RevisionCount(1, 2),),
        open_findings=(OpenFinding("r2:F1@current:v1", "r2", sha, 1, "F1", "retained finding"),),
        reason="terminal reason",
        note="retained note",
        updated_at=NOW.replace(year=2025),
        cleanup_action_ids=("cleanup-stop", "cleanup-pr", "cleanup-push"),
        actions=(
            Action("cleanup-stop", ActionKind.STOP_AGENT, base.task_id, "stop", "writer"),
            Action(
                "cleanup-pr",
                ActionKind.CLOSE_PR,
                base.task_id,
                "close",
                status=ActionStatus.UNKNOWN,
            ),
            Action("cleanup-push", ActionKind.PUSH_BRANCH, base.task_id, "keep branch"),
            Action(
                "start",
                ActionKind.START_AGENT,
                base.task_id,
                "start",
                "writer",
                status=ActionStatus.DONE,
            ),
        ),
    )


@TRACE_SETTINGS
@given(
    status=st.sampled_from(TERMINAL_STATUSES),
    version=st.integers(0, 100),
    sha=st.builds(oid, st.integers(0, 10**9)),
    outcome=st.sampled_from([CheckResult.PR_CLOSED, CheckResult.NOT_CONFIRMED]),
)
def test_every_event_obeys_terminal_cleanup_contract(status, version, sha, outcome) -> None:
    task = terminal_record(status, version, sha)
    # Repeat the full alphabet after cleanup to verify the terminal still has no
    # outgoing edges and repeated identical cleanup receipts are no-ops.
    for kind in list(EventKind) * 2:
        ev = event(
            task,
            kind,
            sha=sha,
            attempt=task.attempt,
            changes=ChangeSet(paths=("app.py",)),
            review=passing(task, "r1"),
            check_result=outcome,
            standard_version=2,
            action_ids=("cleanup-stop", "cleanup-pr"),
        )
        decision = check_pure(task, ev, make_policy(), QuotaSnapshot())
        check_terminal(task, ev, decision)
        check_version(task, decision)
        task = decision.task


@TRACE_SETTINGS
@given(
    status=st.sampled_from(TERMINAL_STATUSES),
    action_ids=st.lists(
        st.sampled_from(
            [
                "cleanup-stop",
                "cleanup-pr",
                "cleanup-push",
                "start",
                "missing",
            ]
        ),
        max_size=5,
    ),
    outcome=st.sampled_from([None, *CheckResult]),
    guard=st.integers(0, 3),
    old_status=st.sampled_from(list(ActionStatus)),
    registered=st.lists(
        st.sampled_from(["cleanup-stop", "cleanup-pr", "cleanup-push"]), unique=True
    ),
)
def test_terminal_cleanup_checks_targets_and_guards(
    status,
    action_ids,
    outcome,
    guard,
    old_status,
    registered,
):
    task = terminal_record(status)
    task = replace(
        task,
        actions=tuple(replace(a, status=old_status) for a in task.actions),
        cleanup_action_ids=tuple(registered),
    )
    ev = event(task, EventKind.CLEANUP_CHECKED, action_ids=tuple(action_ids), check_result=outcome)
    if guard == 1:
        ev = replace(ev, task_id="other-task")
    elif guard == 2:
        ev = replace(ev, state_version=task.state_version - 1)
    elif guard == 3:
        ev = replace(ev, state_version=None)
    decision = check_pure(task, ev, make_policy(), QuotaSnapshot())
    check_terminal(task, ev, decision)
    check_version(task, decision)


@TRACE_SETTINGS
@given(
    required=st.integers(2, 3),
    old_number=st.integers(0, 10**9),
    suffix=st.integers(1, 10**6),
)
def test_new_commit_requires_all_reviewers_again(required, old_number, suffix) -> None:
    old = oid(old_number)
    policy = make_policy(required=required)
    task = walk(Level.C, [EventKind.ASSIGN, EventKind.CODE_SUBMITTED], policy)
    task = core.decide(
        task,
        event(
            task,
            EventKind.CODE_SUBMITTED,
            sha=old,
            attempt=task.attempt,
            changes=ChangeSet(paths=("app.py",)),
        ),
        policy,
        QuotaSnapshot(),
        NOW,
    ).task
    task = core.decide(
        task, event(task, EventKind.CI_GREEN, sha=old), policy, QuotaSnapshot(), NOW
    ).task
    first = passing(task, task.designated_reviewers[0])
    task = core.decide(
        task, event(task, EventKind.REVIEW, review=first), policy, QuotaSnapshot(), NOW
    ).task
    new = oid(old_number + suffix)
    decision = core.decide(
        task,
        event(
            task,
            EventKind.CODE_SUBMITTED,
            sha=new,
            attempt=task.attempt,
            changes=ChangeSet(paths=("app.py",)),
        ),
        policy,
        QuotaSnapshot(),
        NOW,
    )
    check_fresh(task, decision)
    task = decision.task
    task = core.decide(
        task, event(task, EventKind.CI_GREEN, sha=new), policy, QuotaSnapshot(), NOW
    ).task
    stale = core.decide(
        task, event(task, EventKind.REVIEW, review=first), policy, QuotaSnapshot(), NOW
    )
    assert not stale.changed and stale.task == task
    for provider in task.designated_reviewers:
        decision = core.decide(
            task,
            event(task, EventKind.REVIEW, review=passing(task, provider)),
            policy,
            QuotaSnapshot(),
            NOW,
        )
        check_ci(task, decision, new)
        check_review_count(decision.task, policy, False)
        check_separation(decision.task)
        check_version(task, decision)
        task = decision.task
    assert task.status is TaskStatus.AWAITING_MERGE


def test_d_review_route_mutant_cannot_skip_human(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill the other half of invariant 6: keep plan guard, remove human merge guard."""
    policy = make_policy()
    task = walk(
        Level.D,
        [
            EventKind.ASSIGN,
            EventKind.CODE_SUBMITTED,
            EventKind.PLAN_APPROVED,
            EventKind.ASSIGN,
            EventKind.CODE_SUBMITTED,
            EventKind.CI_GREEN,
        ],
    )
    task = core.decide(
        task,
        event(task, EventKind.REVIEW, review=passing(task, "r1")),
        policy,
        QuotaSnapshot(),
        NOW,
    ).task
    ev = event(task, EventKind.REVIEW, review=passing(task, "r2"))
    baseline = core.decide(task, ev, policy, QuotaSnapshot(), NOW)
    check_d(task, baseline, None)
    assert baseline.task.status is TaskStatus.AWAITING_YOUR_REVIEW
    original = Policy.rule_for

    def no_human(self, level):
        return replace(original(self, level), requires_human_merge=False)

    monkeypatch.setattr(Policy, "rule_for", no_human)
    decision = core.decide(task, ev, policy, QuotaSnapshot(), NOW)
    with pytest.raises(AssertionError, match="d: no current human approval"):
        check_d(task, decision, None)


@pytest.mark.parametrize("sha", [oid(1234), None])
def test_d_intervention_sha_guard_mutant_is_caught(
    monkeypatch: pytest.MonkeyPatch,
    sha: str | None,
) -> None:
    policy = make_policy()
    task = walk(
        Level.D,
        [
            EventKind.ASSIGN,
            EventKind.CODE_SUBMITTED,
            EventKind.PLAN_APPROVED,
            EventKind.ASSIGN,
            EventKind.CODE_SUBMITTED,
            EventKind.CI_GREEN,
        ],
    )
    task = core.decide(
        task, event(task, EventKind.QUOTA_EXHAUSTED, provider="r1"), policy, QuotaSnapshot(), NOW
    ).task
    assert task.status is TaskStatus.NEEDS_INTERVENTION
    ev = event(task, EventKind.INTERVENTION_APPROVED, sha=sha)
    baseline = core.decide(task, ev, policy, QuotaSnapshot(), NOW)
    assert not baseline.changed and baseline.task == task
    check_d(task, baseline, human_approval_sha(task, ev, baseline))
    original = core._on_intervention_approved

    def ignore_approval_sha(task, ev, policy):
        # Model removing the SHA check: accept the request as if it named current SHA.
        return original(task, replace(ev, sha=task.latest_sha), policy)

    monkeypatch.setattr(core, "_on_intervention_approved", ignore_approval_sha)
    decision = core.decide(task, ev, policy, QuotaSnapshot(), NOW)
    assert decision.task.status is TaskStatus.AWAITING_MERGE
    with pytest.raises(AssertionError, match="d: no current human approval"):
        check_d(task, decision, human_approval_sha(task, ev, decision))


@TRACE_SETTINGS
@given(
    mode=st.sampled_from(list(RunMode)),
    attempt=st.integers(0, 5),
    sha=st.text(min_size=1, max_size=20),
)
def test_unapproved_d_code_receipts_cannot_advance(mode, attempt, sha) -> None:
    policy = make_policy(mode)
    agent = walk(Level.D, [EventKind.ASSIGN], policy)
    # Reach human takeover through a real quota/CI intervention, then upgrade to D.
    human = walk(Level.C, [EventKind.ASSIGN, EventKind.CODE_SUBMITTED], policy)
    for _ in range(3):
        human = core.decide(
            human,
            event(human, EventKind.CI_RED, sha=human.latest_sha),
            policy,
            QuotaSnapshot(),
            NOW,
        ).task
        if human.status is TaskStatus.PENDING:
            human = core.decide(human, advance(human), policy, QuotaSnapshot(), NOW).task
            human = core.decide(human, advance(human), policy, QuotaSnapshot(), NOW).task
    human = core.decide(human, event(human, EventKind.TAKE_OVER), policy, QuotaSnapshot(), NOW).task
    assert human.status is TaskStatus.YOU_WORKING
    for task in (agent, human):
        for kind in (EventKind.CODE_SUBMITTED, EventKind.YOU_SUBMITTED_CODE):
            ev = event(
                task, kind, sha=sha, attempt=attempt, changes=ChangeSet(paths=("core/a.py",))
            )
            decision = core.decide(task, ev, policy, QuotaSnapshot(), NOW)
            assert decision.task.status not in (
                TaskStatus.AWAITING_ACCEPTANCE,
                TaskStatus.AWAITING_AI_REVIEW,
                TaskStatus.AWAITING_MERGE,
            )
            check_d(task, decision, None)


@TRACE_SETTINGS
@given(
    first_number=st.integers(0, 10**9),
    offset=st.integers(1, 10**6),
    submitted=st.sampled_from([EventKind.PLAN_SUBMITTED, EventKind.CODE_SUBMITTED]),
)
def test_plan_approval_is_bound_to_current_plan_sha(first_number, offset, submitted) -> None:
    first_sha = oid(first_number)
    policy = make_policy()
    task = walk(Level.D, [EventKind.ASSIGN])
    task = core.decide(
        task,
        event(task, EventKind.PLAN_SUBMITTED, sha=first_sha, plan="First proposal"),
        policy,
        QuotaSnapshot(),
        NOW,
    ).task
    task = core.decide(
        task, event(task, EventKind.PLAN_REJECTED), policy, QuotaSnapshot(), NOW
    ).task
    task = core.decide(task, event(task, EventKind.ASSIGN), policy, QuotaSnapshot(), NOW).task
    current_sha = oid(first_number + offset)
    task = core.decide(
        task,
        event(
            task,
            submitted,
            sha=current_sha,
            plan="Revised proposal",
            attempt=task.attempt,
            changes=ChangeSet(paths=("core/a.py",)),
        ),
        policy,
        QuotaSnapshot(),
        NOW,
    ).task
    assert task.status is TaskStatus.AWAITING_PLAN_APPROVAL
    assert task.plan_version == 2
    assert current_plan_sha(task) == current_sha
    assert task.plan_text.strip()
    for sha in (None, first_sha, current_sha):
        ev = event(task, EventKind.PLAN_APPROVED, sha=sha)
        decision = check_pure(task, ev, policy, QuotaSnapshot())
        check_plan_approval(task, ev, decision)
        check_version(task, decision)
        assert decision.changed == (sha == current_sha)


@pytest.mark.parametrize("sha", [None, oid(88)])
def test_plan_sha_guard_mutant_is_caught(monkeypatch: pytest.MonkeyPatch, sha: str | None) -> None:
    policy = make_policy()
    task = walk(Level.D, [EventKind.ASSIGN, EventKind.CODE_SUBMITTED])
    ev = event(task, EventKind.PLAN_APPROVED, sha=sha)
    baseline = core.decide(task, ev, policy, QuotaSnapshot(), NOW)
    check_plan_approval(task, ev, baseline)
    assert not baseline.changed
    if sha is None:
        # 新内核在入口就拒收"方案类事件没带提交编号"，根本到不了处理函数；
        # 这里显式把这条规则钉住，下面的变异体只对合法但错误的编号有意义。
        assert "OID" in baseline.reason
        return
    original = core._on_plan_approved

    def ignore_plan_sha(task, ev):
        return original(task, replace(ev, sha=current_plan_sha(task)))

    monkeypatch.setattr(core, "_on_plan_approved", ignore_plan_sha)
    decision = core.decide(task, ev, policy, QuotaSnapshot(), NOW)
    assert decision.changed
    with pytest.raises(AssertionError, match="plan_sha: wrong plan approved"):
        check_plan_approval(task, ev, decision)


def test_approval_generator_uses_plan_sha_instead_of_latest_code_sha() -> None:
    policy = make_policy()
    task = walk(Level.D, [EventKind.ASSIGN, EventKind.CODE_SUBMITTED])
    # A snapshot can retain a plan separately from the current code commit.
    task = replace(task, latest_sha=oid(99))
    ev = advance(task)
    assert ev.kind is EventKind.PLAN_APPROVED
    assert ev.sha == current_plan_sha(task) and ev.sha != task.latest_sha
    decision = core.decide(task, ev, policy, QuotaSnapshot(), NOW)
    assert decision.changed
    check_plan_approval(task, ev, decision)


def changed_field_value(value: object) -> object:
    from enum import Enum

    if isinstance(value, Enum):
        return next(item for item in type(value) if item is not value)
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, str):
        return value + "-mutant"
    if isinstance(value, tuple):
        assert value, "terminal fixture must populate tuple evidence"
        return value[:-1]
    if isinstance(value, frozenset):
        return value ^ {"mutant-provider"}
    raise AssertionError(f"terminal fixture lacks a mutation value for {value!r}")


@pytest.mark.parametrize(
    "field_name",
    [field.name for field in fields(TaskRecord) if field.name not in TERMINAL_CLEANUP_FIELDS],
)
def test_terminal_cleanup_cannot_change_protected_fields(
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
) -> None:
    task = terminal_record(TaskStatus.CANCELLED)
    ev = event(
        task,
        EventKind.CLEANUP_CHECKED,
        check_result=CheckResult.PR_CLOSED,
        action_ids=("cleanup-stop", "cleanup-pr"),
    )
    baseline = core.decide(task, ev, make_policy(), QuotaSnapshot(), NOW)
    assert baseline.changed
    check_terminal(task, ev, baseline)
    original = core._on_cleanup_checked

    def corrupt_cleanup(task, ev):
        result = original(task, ev)
        return replace(
            result,
            task=replace(
                result.task,
                **{
                    field_name: changed_field_value(getattr(task, field_name)),
                },
            ),
        )

    monkeypatch.setattr(core, "_on_cleanup_checked", corrupt_cleanup)
    decision = core.decide(task, ev, make_policy(), QuotaSnapshot(), NOW)
    with pytest.raises(AssertionError, match="^terminal: "):
        check_terminal(task, ev, decision)


@pytest.mark.parametrize(
    "mutation",
    [
        "append",
        "drop",
        "identity",
        "untargeted",
        "wrong-status",
        "dispatch",
        "version",
        "flag",
    ],
)
def test_terminal_cleanup_bookkeeping_mutants_are_caught(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    task = terminal_record(TaskStatus.FAILED)
    ev = event(
        task,
        EventKind.CLEANUP_CHECKED,
        check_result=CheckResult.NOT_CONFIRMED,
        action_ids=("cleanup-stop", "cleanup-pr"),
    )
    baseline = core.decide(task, ev, make_policy(), QuotaSnapshot(), NOW)
    assert baseline.changed
    check_terminal(task, ev, baseline)
    original = core._on_cleanup_checked

    def corrupt_cleanup(task, ev):
        result = original(task, ev)
        after = result.task
        if mutation == "append":
            after = replace(
                after, actions=after.actions + (Action("new", ActionKind.STOP_AGENT, task.task_id),)
            )
        elif mutation == "drop":
            after = replace(after, actions=after.actions[:-1])
        elif mutation == "identity":
            after = replace(
                after, actions=(replace(after.actions[0], detail="new payload"), *after.actions[1:])
            )
        elif mutation == "untargeted":
            after = replace(
                after,
                actions=tuple(
                    replace(a, status=ActionStatus.DONE) if a.action_id == "cleanup-push" else a
                    for a in after.actions
                ),
            )
        elif mutation == "wrong-status":
            after = replace(
                after,
                actions=(
                    replace(after.actions[0], status=ActionStatus.UNKNOWN),
                    *after.actions[1:],
                ),
            )
        elif mutation == "dispatch":
            return replace(result, actions=[Action("new", ActionKind.STOP_AGENT, task.task_id)])
        elif mutation == "version":
            after = replace(after, state_version=task.state_version + 2)
        elif mutation == "flag":
            after = replace(after, cleanup_checked=False)
        return replace(result, task=after)

    monkeypatch.setattr(core, "_on_cleanup_checked", corrupt_cleanup)
    decision = core.decide(task, ev, make_policy(), QuotaSnapshot(), NOW)
    with pytest.raises(AssertionError, match="^terminal: "):
        check_terminal(task, ev, decision)


@pytest.mark.parametrize("case", ["unregistered", "same-result", "opposite-result", "mixed-batch"])
def test_terminal_cleanup_rejects_unverifiable_or_finished_targets(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    task = terminal_record(TaskStatus.CANCELLED)
    if case == "unregistered":
        task = replace(task, cleanup_action_ids=())
    else:
        task = replace(
            task,
            actions=tuple(
                replace(a, status=ActionStatus.DONE) if a.action_id == "cleanup-stop" else a
                for a in task.actions
            ),
        )
    ev = event(
        task,
        EventKind.CLEANUP_CHECKED,
        action_ids=("cleanup-stop", "cleanup-pr") if case == "mixed-batch" else ("cleanup-stop",),
        check_result=CheckResult.PR_CLOSED
        if case in ("unregistered", "same-result")
        else CheckResult.NOT_CONFIRMED,
    )
    baseline = core.decide(task, ev, make_policy(), QuotaSnapshot(), NOW)
    assert not baseline.changed
    check_terminal(task, ev, baseline)
    original = core._on_cleanup_checked

    def bypass_provenance_or_finality(task, ev):
        if case == "unregistered":
            candidate = replace(task, cleanup_action_ids=ev.action_ids)
        else:
            candidate = replace(
                task,
                actions=tuple(
                    replace(a, status=ActionStatus.SENT) if a.action_id in ev.action_ids else a
                    for a in task.actions
                ),
            )
        result = original(candidate, ev)
        return replace(
            result, task=replace(result.task, cleanup_action_ids=task.cleanup_action_ids)
        )

    monkeypatch.setattr(core, "_on_cleanup_checked", bypass_provenance_or_finality)
    decision = core.decide(task, ev, make_policy(), QuotaSnapshot(), NOW)
    assert decision.changed
    with pytest.raises(AssertionError, match="^terminal: "):
        check_terminal(task, ev, decision)


@pytest.mark.parametrize("mutation", ["missing", "target", "status", "duplicate"])
def test_terminal_cleanup_action_update_mutants_are_caught(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    task = terminal_record(TaskStatus.MERGED)
    ev = event(
        task,
        EventKind.CLEANUP_CHECKED,
        action_ids=("cleanup-stop",),
        check_result=CheckResult.PR_CLOSED,
    )
    baseline = core.decide(task, ev, make_policy(), QuotaSnapshot(), NOW)
    assert baseline.changed
    check_terminal(task, ev, baseline)
    original = core._on_cleanup_checked

    def bad_updates(task, ev):
        result = original(task, ev)
        update = result.action_updates[0]
        updates = {
            "missing": [],
            "target": [replace(update, action_id="start")],
            "status": [replace(update, status=ActionStatus.UNKNOWN)],
            "duplicate": [update, update],
        }[mutation]
        return replace(result, action_updates=updates)

    monkeypatch.setattr(core, "_on_cleanup_checked", bad_updates)
    decision = core.decide(task, ev, make_policy(), QuotaSnapshot(), NOW)
    with pytest.raises(AssertionError, match="terminal: wrong action bookkeeping updates"):
        check_terminal(task, ev, decision)
