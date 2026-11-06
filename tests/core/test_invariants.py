"""Generated event traces and independent invariant oracles.

TANDEM_INVARIANTS_DEEP=1: 1000 traces of up to 200 events (CI: 80 x 40).
No network, shell execution, or real agents are used. Known specification conflicts
are isolated in strict xfail regressions below; ordinary traces check the policy's
A/B review counts and the normal D review route as well.
"""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tandem.core import transition as core
from tandem.core.model import (
    ActionKind,
    ChangeSet,
    CheckResult,
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
    Thresholds,
    Verdict,
)
from tests.core.helpers import NOW

DEEP = os.getenv("TANDEM_INVARIANTS_DEEP") == "1"
TRACE_SETTINGS = settings(max_examples=1000 if DEEP else 80, deadline=None)
PROVIDERS = ("writer", "r1", "r2", "r3")


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
    return Review(provider, provider, Verdict.PASS, task.latest_sha or "s0", task.standard_version)


def check_ci(before: TaskRecord, decision: Decision, green_sha: str | None) -> None:
    if any(action.kind is ActionKind.MERGE for action in decision.actions):
        assert decision.task.latest_sha is not None, "ci: missing sha"
        assert decision.task.ci_green, "ci: red flag"
        assert decision.task.latest_sha == green_sha, "ci: no matching external green event"


def check_separation(task: TaskRecord) -> None:
    for review in task.reviews:
        if review.verdict is Verdict.PASS:
            assert review.provider not in task.providers_involved, "separation"


def check_review_count(task: TaskRecord, policy: Policy, human: bool, *, strict: bool) -> None:
    if task.status is not TaskStatus.AWAITING_MERGE or human:
        return
    if task.run_mode is RunMode.SINGLE_AGENT or task.level is Level.D:
        return
    providers = {
        review.provider
        for review in task.reviews
        if review.verdict is Verdict.PASS
        and review.sha == task.latest_sha
        and review.standard_version == task.standard_version
        and review.provider not in task.providers_involved
    }
    needed = (
        policy.thresholds.required_reviewers
        if strict
        else policy.rule_for(task.level).min_reviewers
    )
    assert len(providers) >= needed, "review_count"


def check_terminal(before: TaskRecord, decision: Decision) -> None:
    if before.status in (TaskStatus.MERGED, TaskStatus.CANCELLED, TaskStatus.FAILED):
        assert decision.task == before and not decision.changed and not decision.actions, "terminal"


def check_version(before: TaskRecord, decision: Decision) -> None:
    if decision.changed:
        assert decision.task.state_version == before.state_version + 1, "version"
    else:
        assert decision.task == before, "version: ignored record changed"
        assert not decision.actions, "version: ignored actions"


def check_d(before: TaskRecord, decision: Decision, seen_your_review: bool) -> None:
    after = decision.task
    if after.level is not Level.D:
        return
    if after.status is TaskStatus.AWAITING_ACCEPTANCE and decision.changed:
        assert after.approved_plan_version is not None, "d: no approved plan"
        assert after.approved_plan_version == after.plan_version, "d: stale plan"
    if after.status is TaskStatus.AWAITING_MERGE:
        assert seen_your_review, "d: skipped your review"


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
        changes = ChangeSet(paths=("docs/a.md",))
    return event(
        task,
        kind,
        sha=task.latest_sha or "s0",
        attempt=task.attempt,
        changes=changes,
        model_suggestion=task.level,
        review=passing(task, missing[0] if missing else "r1"),
        check_result=CheckResult.NOT_CONFIRMED,
    )


@TRACE_SETTINGS
@given(
    level=st.sampled_from(list(Level)),
    mode=st.sampled_from(list(RunMode)),
    required=st.integers(2, 3),
    prefix=st.integers(0, 9),
    instructions=st.lists(
        st.tuples(st.integers(0, 5), st.sampled_from(list(EventKind)), st.integers(0, 7)),
        min_size=1,
        max_size=200 if DEEP else 40,
    ),
)
def test_generated_event_sequences(level, mode, required, prefix, instructions) -> None:
    policy = make_policy(mode, required)
    task = core.create_task("trace", level, policy)
    green_sha: str | None = None
    seen_your_review = False
    human = False
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
                kind,
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
            )
        elif choice == 4:
            ev = replace(ev, task_id="another-task")
        elif choice == 5:
            quota = QuotaSnapshot(((PROVIDERS[value % 4], QuotaState.EXHAUSTED),))
        before = task
        decision = check_pure(before, ev, policy, quota)
        if decision.changed and ev.kind is EventKind.CI_GREEN:
            green_sha = ev.sha
        if decision.task.latest_sha != before.latest_sha:
            green_sha = None
            seen_your_review = False
            human = False
        if decision.changed and ev.kind is EventKind.CI_RED:
            green_sha = None
        seen_your_review |= decision.task.status is TaskStatus.AWAITING_YOUR_REVIEW
        human |= decision.changed and ev.kind in (
            EventKind.YOUR_APPROVAL,
            EventKind.INTERVENTION_APPROVED,
        )
        check_ci(before, decision, green_sha)
        check_separation(decision.task)
        check_review_count(decision.task, policy, human, strict=False)
        check_terminal(before, decision)
        check_version(before, decision)
        # Known D intervention bypass is asserted without exemption in its xfail below.
        if not (human and ev.kind is EventKind.INTERVENTION_APPROVED):
            check_d(before, decision, seen_your_review)
        check_fresh(before, decision)
        task = decision.task


def walk(level: Level, kinds: list[EventKind], policy: Policy | None = None) -> TaskRecord:
    selected = policy or make_policy()
    task = core.create_task("regression", level, selected)
    for kind in kinds:
        task = core.decide(
            task, replace(advance(task), kind=kind), selected, QuotaSnapshot(), NOW
        ).task
    return task


@pytest.mark.parametrize("level", [Level.A, Level.B])
@pytest.mark.xfail(strict=True, reason="task-006 requires >=2; ADR/policy allows A=0, B=1")
def test_regression_all_non_d_levels_need_required_reviewers(level: Level) -> None:
    kinds = [EventKind.ASSIGN, EventKind.CODE_SUBMITTED, EventKind.CI_GREEN]
    if level is Level.B:
        kinds.append(EventKind.REVIEW)
    task = walk(level, kinds)
    assert task.status is TaskStatus.AWAITING_MERGE
    check_review_count(task, make_policy(), False, strict=True)


@pytest.mark.xfail(strict=True, reason="D assignment starts an agent before plan approval")
def test_regression_d_cannot_start_work_before_plan_approval() -> None:
    task = walk(Level.D, [EventKind.ASSIGN])
    assert task.status is TaskStatus.WORKING
    assert task.approved_plan_version == task.plan_version


@pytest.mark.xfail(strict=True, reason="D intervention approval bypasses AWAITING_YOUR_REVIEW")
def test_regression_d_intervention_cannot_skip_your_review() -> None:
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
        event(task, EventKind.INTERVENTION_APPROVED, sha=task.latest_sha),
        policy,
        QuotaSnapshot(),
        NOW,
    )
    assert decision.task.status is TaskStatus.AWAITING_MERGE
    check_d(task, decision, False)


@pytest.mark.xfail(strict=True, reason="PLAN_SUBMITTED changes SHA without invalidating CI")
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
        task, event(task, EventKind.PLAN_SUBMITTED, sha="new-plan"), policy, QuotaSnapshot(), NOW
    )
    assert decision.task.latest_sha == "new-plan"
    check_fresh(task, decision)


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
            sha="new",
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
            check_review_count(decision.task, policy, False, strict=True)
        elif invariant == "terminal":
            check_terminal(task, decision)
        elif invariant == "version":
            check_version(task, decision)
        elif invariant == "d":
            check_d(task, decision, False)
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

        def one_vote(self, level):
            return replace(original_rule(self, level), min_reviewers=1)

        # Also select only one seat, matching an erroneous one-provider quorum.
        monkeypatch.setattr(Policy, "rule_for", one_vote)
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
    with pytest.raises(AssertionError, match=invariant):
        witness()


@TRACE_SETTINGS
@given(
    status=st.sampled_from([TaskStatus.MERGED, TaskStatus.CANCELLED, TaskStatus.FAILED]),
    version=st.integers(0, 100),
    sha=st.text(min_size=1, max_size=20),
)
def test_every_event_leaves_each_terminal_unchanged(status, version, sha) -> None:
    task = TaskRecord("terminal", status=status, state_version=version, latest_sha=sha)
    for kind in EventKind:
        ev = event(
            task,
            kind,
            sha=sha,
            attempt=task.attempt,
            changes=ChangeSet(paths=("app.py",)),
            review=passing(task, "r1"),
            check_result=CheckResult.NOT_CONFIRMED,
            standard_version=2,
        )
        decision = check_pure(task, ev, make_policy(), QuotaSnapshot())
        check_terminal(task, decision)
        check_version(task, decision)


@TRACE_SETTINGS
@given(
    required=st.integers(2, 3),
    old=st.text(min_size=1, max_size=15),
    suffix=st.text(min_size=1, max_size=15),
)
def test_new_commit_requires_all_reviewers_again(required, old, suffix) -> None:
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
    new = old + suffix
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
        check_review_count(decision.task, policy, False, strict=True)
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
    check_d(task, baseline, True)
    assert baseline.task.status is TaskStatus.AWAITING_YOUR_REVIEW
    original = Policy.rule_for

    def no_human(self, level):
        return replace(original(self, level), requires_human_merge=False)

    monkeypatch.setattr(Policy, "rule_for", no_human)
    decision = core.decide(task, ev, policy, QuotaSnapshot(), NOW)
    with pytest.raises(AssertionError, match="d: skipped your review"):
        check_d(task, decision, False)
