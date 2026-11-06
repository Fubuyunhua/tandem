"""`docs/design/task-lifecycle.md` 第 4 节的 9 个场景，每个都走一遍完整路径。

用的是第七版的转换表。旧场景描述里有些操作在第七版里已经不需要了
（比如 C 级不要你批准），测试里按第七版走，并在注释里说明。
"""

from __future__ import annotations

from dataclasses import replace

from tandem.core.model import (
    ActionKind,
    CheckResult,
    EventKind,
    Level,
    RunMode,
    TaskStatus,
    Verdict,
    VetoReason,
)
from tests.core.helpers import (
    CODE_CHANGES,
    CORE_CHANGES,
    SHA_1,
    SHA_2,
    Walker,
    ev,
    new_task,
    policy,
    quota,
    run,
)
from tests.core.helpers import (
    SOME_FINDINGS as FINDINGS,
)


def test_scenario_1_normal_flow_c_level_merges() -> None:
    """1. 正常流程：C 级任务，Claude 写完，Codex 审过，合并。

    第七版里 C 级不需要你批准（ADR-0001：C 级由 AI 审核全部通过后自动合并），
    所以"你在手机上批准"这一步换成了两家审核者都通过。
    """
    walker = Walker(new_task())
    walker.assign("claude")
    walker.submit_code()
    walker.ci_green()
    walker.review("codex")
    walker.review("opencode-go")
    walker.merge_success()

    assert walker.statuses == [
        TaskStatus.PENDING,
        TaskStatus.WORKING,
        TaskStatus.AWAITING_ACCEPTANCE,
        TaskStatus.AWAITING_AI_REVIEW,
        TaskStatus.AWAITING_AI_REVIEW,
        TaskStatus.AWAITING_MERGE,
        TaskStatus.MERGED,
    ]
    assert walker.record.level is Level.C
    assert walker.record.approved_sha == SHA_1
    # 合并是 dry-run，交出去的是动作，不是真的合并
    assert walker.actions(ActionKind.MERGE)


def test_scenario_2_d_level_needs_plan_approval_first() -> None:
    """2. D 级任务：开工前需要你先批准方案。"""
    walker = Walker(new_task(Level.D))
    walker.assign("claude")
    walker.step(ev(EventKind.PLAN_SUBMITTED, plan="先加纯函数 decide，再加外壳"))
    walker.step(ev(EventKind.PLAN_APPROVED))
    walker.assign("claude")
    walker.submit_code(changes=CORE_CHANGES)
    walker.ci_green()
    walker.pass_all()
    walker.step(ev(EventKind.YOUR_APPROVAL, sha=walker.record.latest_sha))
    walker.merge_success()

    assert walker.statuses == [
        TaskStatus.PENDING,
        TaskStatus.WORKING,
        TaskStatus.AWAITING_PLAN_APPROVAL,
        TaskStatus.PENDING,
        TaskStatus.WORKING,
        TaskStatus.AWAITING_ACCEPTANCE,
        TaskStatus.AWAITING_AI_REVIEW,
        TaskStatus.AWAITING_AI_REVIEW,
        TaskStatus.AWAITING_YOUR_REVIEW,
        TaskStatus.AWAITING_MERGE,
        TaskStatus.MERGED,
    ]


def test_scenario_3_writer_runs_out_of_quota_and_hands_over() -> None:
    """3. 写到一半 Claude 额度用完，换 Codex 接着写。

    多了一家提供方，换手以后才凑得齐两家审核者。
    """
    base = policy()
    extended = replace(
        base,
        providers=(*base.providers, "deepseek"),
        writer_providers=(*base.writer_providers, "deepseek"),
        reviewer_providers=(*base.reviewer_providers, "deepseek"),
    )
    walker = Walker(new_task(), policy_=extended)
    walker.assign("claude")
    walker.step(ev(EventKind.QUOTA_EXHAUSTED, provider="claude", reason="写到一半没额度了"))
    assert walker.record.status is TaskStatus.PENDING
    assert walker.actions(ActionKind.SET_QUOTA_EXHAUSTED)[0].provider == "claude"

    walker.quota = quota(("claude",))
    walker.assign("codex")
    walker.submit_code()
    walker.ci_green()
    assert walker.record.designated_reviewers == ("opencode-go", "deepseek")
    walker.pass_all()
    walker.merge_success()

    assert walker.record.status is TaskStatus.MERGED
    assert walker.record.providers_involved == frozenset({"claude", "codex"})


def test_scenario_4_agent_hangs_for_thirty_minutes() -> None:
    """4. Agent 卡住 30 分钟不退出：先进异常，核对后回到原来的状态。"""
    walker = Walker(new_task())
    walker.assign("claude")
    walker.step(ev(EventKind.INCIDENT, reason="30 分钟没有动静", error_code="A01"))
    assert walker.record.status is TaskStatus.ERROR
    assert walker.record.status_before_error is TaskStatus.WORKING

    walker.step(ev(EventKind.RETRY, check_result=CheckResult.NOT_CONFIRMED))
    # 进程已经没了：回到待处理，等重新派活（不能假装还在处理中）
    assert walker.record.status is TaskStatus.PENDING
    walker.assign("claude")
    assert walker.record.status is TaskStatus.WORKING
    walker.submit_code()
    assert walker.record.status is TaskStatus.AWAITING_ACCEPTANCE


def test_scenario_5_you_cancel_while_agent_is_running() -> None:
    """5. Agent 在运行时，你在手机上点了"取消"。"""
    walker = Walker(new_task())
    walker.assign("claude")
    walker.step(ev(EventKind.CANCEL))
    assert walker.record.status is TaskStatus.CANCELLED
    kinds = [action.kind for action in walker.decisions[-1].actions]
    assert ActionKind.STOP_AGENT in kinds
    assert ActionKind.PUSH_BRANCH in kinds  # 保留分支作为副本

    # 之后才到达的回执直接丢弃
    late = run(
        walker.record,
        ev(EventKind.CODE_SUBMITTED, attempt=1, sha=SHA_1, changes=CODE_CHANGES),
    )
    assert late.task.status is TaskStatus.CANCELLED
    assert not late.changed


def test_scenario_6_ci_stays_red_after_two_fixes() -> None:
    """6. CI 变红，Agent 修了两次还是红的：验收失败达到 3 次，转给你（R01）。"""
    walker = Walker(new_task())
    walker.assign("claude")
    walker.submit_code()
    walker.ci_red("第 1 次红")
    for index in (2, 3):
        walker.assign("claude")
        walker.submit_code(sha=f"{index}" * 40)
        walker.ci_red(f"第 {index} 次红")

    assert walker.record.status is TaskStatus.NEEDS_INTERVENTION
    assert walker.record.error_code == "R01"
    assert walker.record.accept_failures == 3


def test_scenario_7_you_send_the_code_back() -> None:
    """7. 你审查时打回，要求修改：退回待处理，改完再走一遍。"""
    walker = Walker(new_task(Level.D))
    walker.assign("claude")
    walker.step(ev(EventKind.PLAN_SUBMITTED, plan="方案"))
    walker.step(ev(EventKind.PLAN_APPROVED))
    walker.assign("claude")
    walker.submit_code(changes=CORE_CHANGES)
    walker.ci_green()
    walker.pass_all()
    assert walker.record.status is TaskStatus.AWAITING_YOUR_REVIEW

    walker.step(ev(EventKind.YOUR_REJECTION, reason="这里的设计我看不懂，改一下"))
    assert walker.record.status is TaskStatus.PENDING
    assert walker.record.reviews == ()

    walker.assign("claude")
    walker.submit_code(sha=SHA_2, changes=CORE_CHANGES)
    walker.ci_green()
    walker.pass_all()
    walker.step(ev(EventKind.YOUR_APPROVAL, sha=walker.record.latest_sha))
    walker.merge_success()
    assert walker.record.status is TaskStatus.MERGED
    assert walker.record.latest_sha == SHA_2


def test_scenario_8_wake_up_after_three_hours_asleep() -> None:
    """8. 电脑睡眠 3 小时后醒来，有一个任务原本处于"运行中"。

    存活检查发现进程已经不在了，进异常（A02），核对后回到处理中。
    """
    walker = Walker(new_task())
    walker.assign("claude")
    walker.step(ev(EventKind.INCIDENT, reason="存活检查：进程已经不在了", error_code="A02"))
    assert walker.record.status is TaskStatus.ERROR
    assert walker.record.error_code == "A02"
    walker.step(ev(EventKind.RETRY, check_result=CheckResult.NOT_CONFIRMED))
    # 进程已经没了：回到待处理，等重新派活（不能假装还在处理中）
    assert walker.record.status is TaskStatus.PENDING
    walker.assign("claude")
    assert walker.record.status is TaskStatus.WORKING
    walker.submit_code()
    walker.ci_green()
    walker.pass_all()
    walker.merge_success()
    assert walker.record.status is TaskStatus.MERGED


def test_scenario_9_you_change_core_and_ai_disagrees() -> None:
    """9. 你自己改了 core/，提交给 AI 审查，AI 不同意。

    写手是你的时候 AI 不能否决你：带上反对意见进入待你介入，
    你写理由否决 AI 的意见后可以直接批准（第 20 条），但 CI 必须是绿的。
    """
    # 先让任务走到"待你介入"（凑不齐审核者），再由你接手
    walker = Walker(new_task())
    walker.assign("claude")
    walker.quota = quota(("codex",))
    walker.submit_code()
    walker.ci_green()
    assert walker.record.status is TaskStatus.NEEDS_INTERVENTION
    assert walker.record.error_code == "R03"

    walker.step(ev(EventKind.TAKE_OVER))
    assert walker.record.status is TaskStatus.YOU_WORKING
    walker.step(ev(EventKind.YOU_SUBMITTED_CODE, sha=SHA_2, changes=CORE_CHANGES))
    # 你改的是 core，按 D 级处理：先批准方案，回到"你处理中"，再提交同一份代码
    assert walker.record.status is TaskStatus.AWAITING_PLAN_APPROVAL
    assert walker.record.level is Level.D
    walker.step(ev(EventKind.PLAN_APPROVED, sha=walker.record.latest_sha))
    assert walker.record.status is TaskStatus.YOU_WORKING
    walker.step(ev(EventKind.YOU_SUBMITTED_CODE, sha=SHA_2, changes=CORE_CHANGES))
    assert walker.record.status is TaskStatus.AWAITING_ACCEPTANCE
    walker.quota = quota()  # 第二天 codex 的额度回来了
    walker.ci_green()
    assert walker.record.status is TaskStatus.AWAITING_AI_REVIEW
    assert walker.record.run_mode is RunMode.MULTI_AGENT
    assert walker.record.writer_is_human

    walker.review("codex", Verdict.PASS)
    walker.review("opencode-go", Verdict.FAIL, FINDINGS)
    assert walker.record.status is TaskStatus.NEEDS_INTERVENTION
    assert "写手是你" in walker.record.reason

    walker.step(
        ev(
            EventKind.INTERVENTION_APPROVED,
            sha=walker.record.latest_sha,
            veto_reasons=(VetoReason(finding_id="F1", reason="这条我补了重放测试"),),
        )
    )
    assert walker.record.status is TaskStatus.AWAITING_MERGE
    walker.merge_success()
    assert walker.record.status is TaskStatus.MERGED
