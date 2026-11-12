"""Crash/restart properties for the SQLite shell; no real agents or side effects.

CI: 30 traces, <=20 generated events. TANDEM_INVARIANTS_DEEP=1: 250, <=80.
Every attempt closes its connection and recovery uses a fresh Store/Runner.
ProcessCrash is a BaseException, not an ordinary agent failure/retry signal.

Replay is conditional on fixture-supplied creation metadata/policy and witnessed
clock, quota and input action statuses: these are NOT all recorded in events.
Only durable events are replayed, through the real core decide, without executing
any actions. Final action statuses are projected from the durable action table.
This checks replay consistency with those inputs, not standalone log recovery or
exactly-once delivery: claimed but unexecuted actions may remain SENT indefinitely.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tandem.core.model import (
    Action,
    ActionStatus,
    ChangeSet,
    CheckResult,
    Decision,
    Event,
    EventKind,
    Finding,
    Level,
    Policy,
    QuotaSnapshot,
    Review,
    RunMode,
    TaskRecord,
    TaskStatus,
    Verdict,
    VetoReason,
)
from tandem.core.transition import decide
from tandem.shell import runner as runner_module
from tandem.shell import serde
from tandem.shell.agents.fake import FakeAgent
from tandem.shell.diff_source import FakeDiffSource
from tandem.shell.executor import ExecutedAction, Executor
from tandem.shell.runner import Runner
from tandem.shell.store import Store
from tests.core.helpers import NOW

DEEP = os.getenv("TANDEM_INVARIANTS_DEEP") == "1"
TRACE_SETTINGS = settings(max_examples=250 if DEEP else 30, deadline=None)
ALL_CHECKS = ("atomic", "once", "replay", "version")


def oid(n: int) -> str:
    """40 位十六进制的提交编号：内核在入口只认完整 OID（见 core/identity.py）。"""
    return f"{n:040x}"


SEAMS = (
    "_insert_event",
    "_write_task",
    "_insert_action",
    "commit",
    "execute",
    "update_action_status",
    "save_quota",
    "_incident_from",
)


class ProcessCrash(BaseException):
    """Unwind/close the connection, discard the Runner, then reopen the file."""


@dataclass
class Fault:
    seam: str = "none"
    after: bool = False
    occurrence: int = 1
    hits: int = 0
    fired: bool = False

    def install(self, patch: pytest.MonkeyPatch, runner: Runner) -> None:
        if self.seam == "none":
            return
        target = runner.executor if self.seam == "execute" else runner.store
        if self.seam == "_incident_from":
            target = runner
        original = getattr(target, self.seam)

        def interrupted(*args: Any, **kwargs: Any) -> Any:
            self.hits += 1
            trigger = self.hits == self.occurrence
            if trigger and not self.after:
                self.fired = True
                raise ProcessCrash(self.seam)
            result = original(*args, **kwargs)
            if trigger and self.after:
                self.fired = True
                raise ProcessCrash(self.seam)
            return result

        patch.setattr(target, self.seam, interrupted)


class RecordingExecutor(Executor):
    def __init__(self, ledger: list[Action], missing_agent: bool) -> None:
        agents = (
            {}
            if missing_agent
            else {
                name: FakeAgent(name, script=["simulated receipt"] * 256)
                for name in ("w", "r1", "r2")
            }
        )
        super().__init__(agents=agents, dry_run=True)
        self.ledger = ledger

    def execute(self, action: Action, task: TaskRecord) -> ExecutedAction:
        # The outer fault wrapper can crash before this entry (no invocation) or
        # after it returns (invocation happened even if status was never saved).
        self.ledger.append(action)
        return super().execute(action, task)


def policy(mode: RunMode = RunMode.MULTI_AGENT) -> Policy:
    return Policy(
        providers=("w", "r1", "r2"),
        writer_providers=("w", "r1", "r2"),
        reviewer_providers=("w", "r1", "r2"),
        default_writer="w",
        run_mode=mode,
        bottom_line_paths=("core/**",),
        relaxable_paths=("docs/**",),
        relaxable_extensions=(".md",),
    )


def sent(action: Action) -> Action:
    return replace(action, status=ActionStatus.SENT)


def structural(task: TaskRecord) -> TaskRecord:
    return replace(task, actions=tuple(sent(action) for action in task.actions))


@dataclass(frozen=True)
class Image:
    task: TaskRecord
    events: tuple[Event, ...]
    actions: tuple[Action, ...]


def image(store: Store) -> Image:
    # Read the stored payload independently of load_task/action projection.
    row = store._connection.execute("SELECT payload FROM tasks WHERE task_id = 't'").fetchone()
    assert row is not None
    task = serde.task_from_dict(json.loads(row["payload"]))
    return Image(
        structural(task),
        tuple(store.list_events("t")),
        tuple(
            sorted(
                (sent(action) for action in store.list_actions("t")),
                key=lambda a: a.action_id,
            )
        ),
    )


@dataclass(frozen=True)
class ReplayInput:
    event: Event
    quota: QuotaSnapshot
    now: datetime
    statuses: tuple[tuple[str, ActionStatus], ...]


@dataclass(frozen=True)
class Attempt:
    before: Image
    complete: Image
    replay_input: ReplayInput


def check_atomic(recovered: Image, before: Image, attempts: list[Attempt]) -> None:
    # handle can derive an INCIDENT: each event is its own transaction. A crash
    # may leave any COMPLETE prefix, never half of a parent or followup event.
    assert recovered in [before, *(attempt.complete for attempt in attempts)], (
        "atomic: partial event"
    )


def check_once(store: Store, ledger: list[Action]) -> None:
    counts = Counter(action.action_id for action in ledger)
    assert all(count <= 1 for count in counts.values()), "once: action invoked twice"
    table = {action.action_id: action for action in store.list_actions("t")}
    assert set(counts) <= set(table), "once: executed action was not durably claimed"
    task = store.load_task("t")
    assert task is not None
    assert {a.action_id: a for a in task.actions} == table, "once: action projection mismatch"
    for action in table.values():
        if action.status in (ActionStatus.DONE, ActionStatus.UNKNOWN):
            assert counts[action.action_id] == 1, "once: completion without invocation"


def check_replay(
    store: Store, initial: TaskRecord, selected: Policy, inputs: list[ReplayInput]
) -> None:
    events = store.list_events("t")
    assert events[0].kind is EventKind.CREATED
    assert len(events) == len(inputs) + 1, "replay: missing event/context"
    task = initial  # CREATED does not contain level, base SHA or creation time.
    for ev, context in zip(events[1:], inputs, strict=True):
        assert ev == context.event, "replay: log order/content changed"
        statuses = dict(context.statuses)
        task = replace(
            task,
            actions=tuple(
                replace(action, status=statuses.get(action.action_id, action.status))
                for action in task.actions
            ),
        )
        task = decide(task, ev, selected, context.quota, context.now).task
    table = {action.action_id: action for action in store.list_actions("t")}
    assert {a.action_id: sent(a) for a in task.actions} == {
        key: sent(action) for key, action in table.items()
    }, "replay: actions differ"
    task = replace(
        task,
        actions=tuple(
            replace(action, status=table[action.action_id].status) for action in task.actions
        ),
    )
    assert task == store.load_task("t"), "replay: snapshot differs from event decisions"


def check_version(store: Store, previous: int) -> int:
    row = store._connection.execute("SELECT state_version, payload FROM tasks WHERE task_id = 't'")
    stored = row.fetchone()
    assert stored is not None
    raw = serde.task_from_dict(json.loads(stored["payload"]))
    task = store.load_task("t")
    assert task is not None
    version = int(stored["state_version"])
    assert version >= previous, "version: durable version went backwards"
    assert version == raw.state_version == task.state_version, "version: column/payload mismatch"
    # Event.state_version is an expected OLD version; stale events may decrease
    # it legitimately. Check representation, not monotonicity of that column.
    rows = store._connection.execute("SELECT state_version, payload FROM events ORDER BY id")
    for event_row in rows:
        ev = serde.event_from_dict(json.loads(event_row["payload"]))
        assert event_row["state_version"] == ev.state_version, "version: event column mismatch"
    return version


class Scenario:
    def __init__(
        self, path: Path, selected: Policy, level: Level = Level.C, missing_agent: bool = False
    ) -> None:
        self.path = path
        self.policy = selected
        self.missing_agent = missing_agent
        self.ledger: list[Action] = []
        self.inputs: list[ReplayInput] = []
        self.previous_version = 0
        with Store(path) as store:
            self.initial = self.runner(store).submit("t", level)

    def runner(self, store: Store) -> Runner:
        return Runner(
            store,
            self.policy,
            RecordingExecutor(self.ledger, self.missing_agent),
            FakeDiffSource(ChangeSet(paths=("app.py",))),
            clock=lambda: NOW,
        )

    def load(self) -> TaskRecord:
        with Store(self.path) as store:
            task = store.load_task("t")
            assert task is not None
            return task

    def run(
        self,
        ev: Event,
        fault: Fault | None = None,
        *,
        stale: TaskRecord | None = None,
        checks: tuple[str, ...] = ALL_CHECKS,
    ) -> None:
        attempts: list[Attempt] = []
        with Store(self.path) as store:
            before = image(store)
            runner = self.runner(store)

            def observed(
                task: TaskRecord,
                event: Event,
                selected: Policy,
                quota: QuotaSnapshot,
                now: datetime,
            ) -> Decision:
                old = image(store)
                decision = decide(task, event, selected, quota, now)
                actions = {a.action_id: a for a in old.actions}
                actions.update({a.action_id: sent(a) for a in decision.actions})
                complete = Image(
                    structural(decision.task) if decision.changed else old.task,
                    old.events + (event,),
                    tuple(sorted(actions.values(), key=lambda a: a.action_id)),
                )
                context = ReplayInput(
                    event, quota, now, tuple((a.action_id, a.status) for a in task.actions)
                )
                attempts.append(Attempt(old, complete, context))
                return decision

            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(runner_module, "decide", observed)
                if stale is not None:
                    patch.setattr(store, "load_task", lambda _task_id: stale)
                if fault is not None:
                    fault.install(patch, runner)
                try:
                    runner.handle(ev)
                except ProcessCrash:
                    pass
        # No old connection, Runner, executor or quota tracker is reused here.
        with Store(self.path) as recovered:
            restarted = self.runner(recovered)
            assert restarted.quota.snapshot() == QuotaSnapshot.from_mapping(recovered.load_quota())
            final = image(recovered)
            if "atomic" in checks:
                check_atomic(final, before, attempts)
            # Retain only contexts of events that survived the crash/rollback.
            for attempt in attempts:
                if len(attempt.before.events) < len(final.events):
                    self.inputs.append(attempt.replay_input)
            if "once" in checks:
                check_once(recovered, self.ledger)
            if "replay" in checks:
                check_replay(recovered, self.initial, self.policy, self.inputs)
            if "version" in checks:
                self.previous_version = check_version(recovered, self.previous_version)


def next_event(task: TaskRecord, choice: int, kind: EventKind, serial: int) -> Event:
    normal = {
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
    selected = normal if choice in (0, 2, 3) else kind
    provider = next(
        (p for p in task.designated_reviewers if p not in {r.provider for r in task.reviews}), "r1"
    )
    # 提交类事件必须带一个新的完整 OID；其余事件沿用当前提交编号（可以是 None）。
    sha = task.latest_sha
    plan = task.plan()
    if selected is EventKind.PLAN_APPROVED and plan is not None and plan.sha:
        sha = plan.sha
    if selected in (
        EventKind.PLAN_SUBMITTED,
        EventKind.CODE_SUBMITTED,
        EventKind.YOU_SUBMITTED_CODE,
    ):
        sha = oid(serial + 1)
    # 事件里带了审核结论时，结论的提交编号也必须是完整 OID，否则整条事件被入口拒收。
    review_sha = sha or task.latest_sha or oid(0)
    ev = Event(
        selected,
        "t",
        state_version=task.state_version,
        attempt=task.attempt,
        sha=sha,
        provider=task.writer or "w",
        changes=ChangeSet(paths=("core/a.py" if task.level is Level.D else "app.py",)),
        plan="Generated proposal",
        reason=f"step-{serial}",
        standard_version=task.standard_version + 1,
        check_result=CheckResult.NOT_CONFIRMED,
        review=Review(provider, provider, Verdict.PASS, review_sha, task.standard_version),
        veto_reasons=tuple(VetoReason(f.key, "Reviewed explicitly") for f in task.open_findings),
    )
    if choice == 2:
        return replace(ev, state_version=task.state_version + 1)
    if choice == 3:
        # 合法但过期的提交编号：入口放行，由处理函数按"编号对不上"拒收。
        stale = oid(9000 + serial)
        return replace(
            ev,
            sha=stale,
            review=Review(
                "impersonated-reviewer",
                "w",
                Verdict.FAIL,
                stale,
                0,
                findings=(Finding("F1", "Please fix"),),
            ),
        )
    return ev


@TRACE_SETTINGS
@given(
    level=st.sampled_from([Level.C, Level.D]),
    mode=st.sampled_from(list(RunMode)),
    missing_agent=st.booleans(),
    prefix=st.integers(0, 5),
    steps=st.lists(
        st.tuples(
            st.integers(0, 4),
            st.sampled_from(list(EventKind)),
            st.sampled_from(("none", *SEAMS)),
            st.booleans(),
            st.integers(1, 3),
        ),
        min_size=1,
        max_size=80 if DEEP else 20,
    ),
)
def test_generated_crash_and_recovery(level, mode, missing_agent, prefix, steps) -> None:
    with TemporaryDirectory(prefix="tandem-shell-") as directory:
        scenario = Scenario(Path(directory) / "state.sqlite3", policy(mode), level, missing_agent)
        generated = [(0, EventKind.CREATED, "none", False, 1)] * prefix + steps
        for serial, (choice, kind, seam, after, occurrence) in enumerate(generated):
            ev = next_event(scenario.load(), choice, kind, serial)
            scenario.run(ev, Fault(seam, after, occurrence))
            # Redeliver the exact input after reopening, including its stale version.
            scenario.run(ev)


@pytest.mark.parametrize("seam", SEAMS)
@pytest.mark.parametrize("after", [False, True])
def test_every_crash_boundary_is_exercised(tmp_path: Path, seam: str, after: bool) -> None:
    scenario = Scenario(tmp_path / "state.sqlite3", policy())
    if seam == "save_quota":
        scenario.run(next_event(scenario.load(), 0, EventKind.CREATED, 0))
        ev = next_event(scenario.load(), 1, EventKind.QUOTA_EXHAUSTED, 1)
    else:
        ev = next_event(scenario.load(), 0, EventKind.CREATED, 0)
    fault = Fault(seam, after)
    scenario.run(ev, fault)
    assert fault.fired, f"the {seam} boundary must actually be reached"
    scenario.run(ev)


@pytest.mark.parametrize("seam", ["_insert_action", "execute", "update_action_status"])
@pytest.mark.parametrize("after", [False, True])
def test_crash_midway_through_multiple_actions(tmp_path: Path, seam: str, after: bool) -> None:
    scenario = Scenario(tmp_path / "state.sqlite3", policy())
    scenario.run(next_event(scenario.load(), 0, EventKind.CREATED, 0))
    ev = next_event(scenario.load(), 1, EventKind.QUOTA_EXHAUSTED, 1)
    fault = Fault(seam, after, occurrence=2)
    scenario.run(ev, fault)
    assert fault.fired
    scenario.run(ev)


@pytest.mark.parametrize("seam", ["_insert_event", "_write_task", "commit"])
@pytest.mark.parametrize("after", [False, True])
def test_crash_in_automatic_incident_followup(tmp_path: Path, seam: str, after: bool) -> None:
    scenario = Scenario(tmp_path / "state.sqlite3", policy(), missing_agent=True)
    ev = next_event(scenario.load(), 0, EventKind.CREATED, 0)
    fault = Fault(seam, after, occurrence=2)
    scenario.run(ev, fault)
    assert fault.fired
    scenario.run(ev)


@TRACE_SETTINGS
@given(seam=st.sampled_from(SEAMS), after=st.booleans())
def test_cached_decision_after_restart_does_not_execute_twice(seam, after) -> None:
    with TemporaryDirectory(prefix="tandem-cached-") as directory:
        scenario = Scenario(Path(directory) / "state.sqlite3", policy())
        old_snapshot = scenario.load()
        ev = next_event(old_snapshot, 0, EventKind.CREATED, 0)
        scenario.run(ev, Fault(seam, after))
        # A restarted worker can still hold the pre-crash snapshot. The core
        # returns the identical decision/action IDs: Store must not reclaim them.
        scenario.run(ev, stale=old_snapshot)
        scenario.run(ev, stale=old_snapshot)


@pytest.mark.parametrize("invariant", ALL_CHECKS)
def test_shell_oracles_kill_mutants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invariant: str,
) -> None:
    def witness(directory: Path) -> None:
        scenario = Scenario(directory / "state.sqlite3", policy())
        old_snapshot = scenario.load()
        ev = next_event(old_snapshot, 0, EventKind.CREATED, 0)
        fault = Fault("_write_task", after=True) if invariant == "atomic" else None
        scenario.run(ev, fault, checks=(invariant,))
        if invariant == "once":
            scenario.run(ev, stale=old_snapshot, checks=(invariant,))

    # Same witness/oracle, first without a mutant: existing failures cannot
    # accidentally count as evidence that the mutation has been caught.
    witness(tmp_path / "baseline")
    original_event = Store._insert_event
    original_action = Store._insert_action
    original_write = Store._write_task
    if invariant == "atomic":

        def split_transaction(self, event, stamp):
            original_event(self, event, stamp)
            self._connection.commit()  # event survives the later task-write crash

        monkeypatch.setattr(Store, "_insert_event", split_transaction)
    elif invariant == "once":

        def reclaim_existing(self, action, stamp):
            original_action(self, action, stamp)
            return True  # falsely claim execution even for an existing action ID

        monkeypatch.setattr(Store, "_insert_action", reclaim_existing)
    elif invariant == "replay":

        def corrupt_snapshot(self, task, expected_version, stamp):
            corrupted = (
                replace(task, note="not justified by events")
                if expected_version is not None
                else task
            )
            original_write(self, corrupted, expected_version, stamp)

        monkeypatch.setattr(Store, "_write_task", corrupt_snapshot)
    elif invariant == "version":

        def wrong_version_column(self, task, expected_version, stamp):
            original_write(self, task, expected_version, stamp)
            if expected_version is not None:
                self._connection.execute(
                    "UPDATE tasks SET state_version = state_version + 1 WHERE task_id = ?",
                    (task.task_id,),
                )

        monkeypatch.setattr(Store, "_write_task", wrong_version_column)
    with pytest.raises(AssertionError, match=invariant):
        witness(tmp_path / "mutant")


def test_version_oracle_rejects_consistent_but_regressed_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = Scenario(tmp_path / "state.sqlite3", policy())
    scenario.run(next_event(scenario.load(), 0, EventKind.CREATED, 0))
    assert scenario.previous_version == 1
    original = Store._write_task

    def regress_both(self, task, expected_version, stamp):
        original(self, task, expected_version, stamp)
        old = replace(task, state_version=0)
        self._connection.execute(
            "UPDATE tasks SET state_version = ?, payload = ? WHERE task_id = ?",
            (old.state_version, serde.dumps(serde.task_to_dict(old)), old.task_id),
        )

    monkeypatch.setattr(Store, "_write_task", regress_both)
    with pytest.raises(AssertionError, match="version: durable version went backwards"):
        scenario.run(next_event(scenario.load(), 0, EventKind.CREATED, 1), checks=("version",))
