"""内核的数据结构：枚举与不可变数据结构。

设计约束（见 ADR-0001"裁决原则"和 `docs/design/task-lifecycle.md` 第七版）：
- 所有数据结构都是 ``@dataclass(frozen=True)``，内核只返回新对象，不修改传入的对象；
- 这里不读时钟、不取随机数、不读写文件，``datetime`` 只作为参数类型出现；
- 每个 ``match`` 都以 ``assert_never`` 收尾，让 pyright 能查出漏处理的分支。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import assert_never


class TaskStatus(Enum):
    """第七版的 13 个状态。值就是给人和通知看的中文名。"""

    PENDING = "待处理"
    WORKING = "处理中"
    AWAITING_PLAN_APPROVAL = "待你批准方案"
    AWAITING_ACCEPTANCE = "待验收"
    AWAITING_AI_REVIEW = "待AI审核"
    AWAITING_YOUR_REVIEW = "待你审核"
    AWAITING_MERGE = "待合并"
    NEEDS_INTERVENTION = "待你介入"
    YOU_WORKING = "你处理中"
    ERROR = "异常"
    MERGED = "已合并"
    CANCELLED = "已取消"
    FAILED = "失败"

    @property
    def is_terminal(self) -> bool:
        """终点状态：不再有出边。"""
        match self:
            case TaskStatus.MERGED | TaskStatus.CANCELLED | TaskStatus.FAILED:
                return True
            case (
                TaskStatus.PENDING
                | TaskStatus.WORKING
                | TaskStatus.AWAITING_PLAN_APPROVAL
                | TaskStatus.AWAITING_ACCEPTANCE
                | TaskStatus.AWAITING_AI_REVIEW
                | TaskStatus.AWAITING_YOUR_REVIEW
                | TaskStatus.AWAITING_MERGE
                | TaskStatus.NEEDS_INTERVENTION
                | TaskStatus.YOU_WORKING
                | TaskStatus.ERROR
            ):
                return False
            case _:  # pragma: no cover - 防御：新增状态时 pyright 会在这里报错
                assert_never(self)


class Level(Enum):
    """A–D 四个等级。D 最严格。"""

    A = "A"
    B = "B"
    C = "C"
    D = "D"

    @property
    def rank(self) -> int:
        """数值越大越严格，方便"取更高的级别"。"""
        match self:
            case Level.A:
                return 1
            case Level.B:
                return 2
            case Level.C:
                return 3
            case Level.D:
                return 4
            case _:  # pragma: no cover
                assert_never(self)

    def stricter(self, other: Level) -> Level:
        """返回两者中更严格的那个。"""
        return self if self.rank >= other.rank else other


class RunMode(Enum):
    """运行模式：M1 只有 Claude，所以单 Agent 模式下所有等级都由你审。"""

    SINGLE_AGENT = "单 Agent 模式"
    MULTI_AGENT = "多 Agent 模式"


class Verdict(Enum):
    """一条审核结论。"""

    PASS = "通过"
    FAIL = "不通过"


class QuotaState(Enum):
    """某一家的额度状态。未知按"还有额度"处理（终审第 15 条）。"""

    UNKNOWN = "未知"
    AVAILABLE = "还有额度"
    EXHAUSTED = "额度用完"


class CheckResult(Enum):
    """第 26 条：外壳去外部核对以后，把核对结果作为事件带回来。"""

    MERGE_SUCCEEDED = "合并其实已经成功"
    NOT_CONFIRMED = "外部没有确认任何动作完成"
    PR_CLOSED = "PR 已被关闭"


class ActionKind(Enum):
    """内核能要求的动作。外壳负责把它们变成真实副作用（默认 dry-run）。"""

    START_AGENT = "启动 Agent"
    REQUEST_REVIEW = "请求审核"
    MERGE = "合并 PR"
    CLOSE_PR = "关闭 PR"
    PUSH_BRANCH = "推送分支"
    STOP_AGENT = "结束 Agent 进程"
    NOTIFY = "通知你"
    SET_QUOTA_EXHAUSTED = "标记额度用完"

    @property
    def has_side_effect(self) -> bool:
        """会产生外部副作用的动作，默认 dry-run 只记日志。"""
        match self:
            case (
                ActionKind.MERGE
                | ActionKind.CLOSE_PR
                | ActionKind.PUSH_BRANCH
                | ActionKind.STOP_AGENT
                | ActionKind.START_AGENT
                | ActionKind.REQUEST_REVIEW
                | ActionKind.NOTIFY
            ):
                return True
            case ActionKind.SET_QUOTA_EXHAUSTED:
                return False
            case _:  # pragma: no cover
                assert_never(self)


class ActionStatus(Enum):
    """动作的三种状态（任务记录里要记住）。"""

    SENT = "已发出"
    UNKNOWN = "结果未知"
    DONE = "已完成"

    @property
    def is_unconfirmed(self) -> bool:
        """第 8、26 条：出问题时要知道还有哪些动作没确认完成。"""
        return self is not ActionStatus.DONE


@dataclass(frozen=True)
class QuotaSnapshot:
    """额度快照：外壳读好后传进来，内核不猜、不写。

    没有出现的提供方按 ``QuotaState.UNKNOWN`` 处理，也就是"默认还有额度"。
    """

    entries: tuple[tuple[str, QuotaState], ...] = ()

    @staticmethod
    def from_mapping(values: dict[str, QuotaState]) -> QuotaSnapshot:
        return QuotaSnapshot(entries=tuple(sorted(values.items())))

    def state(self, provider: str) -> QuotaState:
        for name, state in self.entries:
            if name == provider:
                return state
        return QuotaState.UNKNOWN

    def has_quota(self, provider: str) -> bool:
        """未知也算有额度；只有明确标记"额度用完"才算没有。"""
        return self.state(provider) is not QuotaState.EXHAUSTED


@dataclass(frozen=True)
class ChangeSet:
    """真实改动。由外壳从 diff 收集，内核据此算等级。

    断言数量由外壳在测试文件里数 ``assert`` / ``expect(`` 的个数得到。
    """

    paths: tuple[str, ...] = ()
    deleted_paths: tuple[str, ...] = ()
    renames: tuple[tuple[str, str], ...] = ()
    assertions_before: int | None = None
    assertions_after: int | None = None
    secret_scan_hit: bool = False

    @property
    def touches_repository(self) -> bool:
        """有没有改动仓库。用来判断基础级别是不是 A。"""
        return bool(self.paths or self.deleted_paths or self.renames)

    @property
    def all_paths(self) -> tuple[str, ...]:
        """所有参与判断的路径：改动的、删除的，以及改名前后两个路径。"""
        collected: list[str] = list(self.paths)
        collected.extend(self.deleted_paths)
        for before, after in self.renames:
            collected.append(before)
            collected.append(after)
        return tuple(collected)

    @property
    def assertions_decreased(self) -> bool:
        if self.assertions_before is None or self.assertions_after is None:
            return False
        return self.assertions_after < self.assertions_before


@dataclass(frozen=True)
class Review:
    """一条审核结论。审核结论绑定提交编号和审核标准版本。"""

    reviewer: str
    provider: str
    verdict: Verdict
    sha: str
    standard_version: int


@dataclass(frozen=True)
class Action:
    """内核要求外壳做的一件事。

    ``action_id`` 由内核按"任务编号 + 状态版本号 + 序号"生成，是确定性的，
    重放时能得到同样的编号。
    """

    action_id: str
    kind: ActionKind
    task_id: str
    detail: str = ""
    provider: str | None = None
    status: ActionStatus = ActionStatus.SENT


@dataclass(frozen=True)
class RevisionCount:
    """修改次数按审核标准版本分开计算，保留历史（第 22、23 条）。"""

    standard_version: int
    count: int


@dataclass(frozen=True)
class TaskRecord:
    """任务记录。第七版"每个任务要记住的信息"一节逐项对应。"""

    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    level: Level = Level.C
    state_version: int = 0
    run_mode: RunMode = RunMode.MULTI_AGENT

    # 出问题前的状态（第 8、26 条）
    status_before_error: TaskStatus | None = None
    error_code: str | None = None

    # 方案版本、批准的是哪一版（第 2、3、4、5b 条）
    plan_version: int = 0
    approved_plan_version: int | None = None

    # 写手（提供方名），以及写手是不是你（第 6、14、14b 条）
    writer: str | None = None
    writer_is_human: bool = False

    # 参与过的提供方集合：写过代码的都不能当审核者，换手时也不清掉
    providers_involved: frozenset[str] = frozenset()

    # 审核结论表与本次指定的审核者（第 12–16、22 条）
    designated_reviewers: tuple[str, ...] = ()
    reviews: tuple[Review, ...] = ()
    standard_version: int = 1

    # 次数
    accept_failures: int = 0
    revision_counts: tuple[RevisionCount, ...] = ()

    # 提交编号、CI 状态、PR 状态
    latest_sha: str | None = None
    approved_sha: str | None = None
    ci_green: bool = False
    pr_opened: bool = False

    # 第几次尝试（回执要带回来核对）
    attempt: int = 0

    # 改动采集的基线（外壳用 base...latest_sha 算真实改动，内核不读它）
    base_sha: str = ""

    # 上一轮是不是被审核退回的（第 6 条"取消了仲裁"）
    returned_from_review: bool = False

    # 动作记录：编号 + 状态
    actions: tuple[Action, ...] = ()

    # 原因 / 错误码、进度说明、备注
    reason: str = ""
    note: str = ""

    # 最后一次做决定的时间，由外壳作为参数传进来
    updated_at: datetime | None = None

    def revision_count(self, standard_version: int) -> int:
        """当前审核标准版本下已经改过几次。"""
        for entry in self.revision_counts:
            if entry.standard_version == standard_version:
                return entry.count
        return 0

    def bumped_revision(self) -> tuple[RevisionCount, ...]:
        """改一次，只动当前标准版本的计数，其他版本的历史保留。"""
        version = self.standard_version
        updated: list[RevisionCount] = []
        found = False
        for entry in self.revision_counts:
            if entry.standard_version == version:
                updated.append(RevisionCount(standard_version=version, count=entry.count + 1))
                found = True
            else:
                updated.append(entry)
        if not found:
            updated.append(RevisionCount(standard_version=version, count=1))
        return tuple(updated)

    def current_reviews(self) -> tuple[Review, ...]:
        """只保留针对当前提交编号、当前审核标准版本的结论。"""
        return tuple(
            review
            for review in self.reviews
            if review.sha == self.latest_sha and review.standard_version == self.standard_version
        )

    def with_actions(self, actions: tuple[Action, ...]) -> TaskRecord:
        return replace(self, actions=self.actions + actions)


@dataclass(frozen=True)
class LevelRule:
    """一个等级的流程。写在 risk.yml 里，不写死在代码里（ADR-0001）。"""

    level: Level
    requires_plan_approval: bool = False
    requires_ai_review: bool = True
    requires_human_merge: bool = False
    min_reviewers: int = 2


@dataclass(frozen=True)
class Thresholds:
    """几个数字阈值。都是 ADR-0001 里的占位值，由 risk.yml 提供。"""

    required_reviewers: int = 2
    max_accept_failures: int = 3
    max_revisions: int = 3


@dataclass(frozen=True)
class Policy:
    """策略：由外壳从 risk.yml 读出来后传进内核。"""

    bottom_line_paths: tuple[str, ...] = ()
    relaxable_paths: tuple[str, ...] = ()
    relaxable_extensions: tuple[str, ...] = ()
    providers: tuple[str, ...] = ()
    writer_providers: tuple[str, ...] = ()
    reviewer_providers: tuple[str, ...] = ()
    default_writer: str = ""
    run_mode: RunMode = RunMode.MULTI_AGENT
    thresholds: Thresholds = Thresholds()
    level_rules: tuple[LevelRule, ...] = ()

    def rule_for(self, level: Level) -> LevelRule:
        """取某个等级的流程；risk.yml 没写时按 ADR-0001 的表格给默认值。"""
        for rule in self.level_rules:
            if rule.level is level:
                return rule
        match level:
            case Level.A:
                return LevelRule(
                    level=Level.A,
                    requires_plan_approval=False,
                    requires_ai_review=False,
                    requires_human_merge=False,
                    min_reviewers=0,
                )
            case Level.B:
                return LevelRule(
                    level=Level.B,
                    requires_plan_approval=False,
                    requires_ai_review=True,
                    requires_human_merge=False,
                    min_reviewers=1,
                )
            case Level.C:
                return LevelRule(
                    level=Level.C,
                    requires_plan_approval=False,
                    requires_ai_review=True,
                    requires_human_merge=False,
                    min_reviewers=self.thresholds.required_reviewers,
                )
            case Level.D:
                return LevelRule(
                    level=Level.D,
                    requires_plan_approval=True,
                    requires_ai_review=True,
                    requires_human_merge=True,
                    min_reviewers=self.thresholds.required_reviewers,
                )
            case _:  # pragma: no cover
                assert_never(level)


class EventKind(Enum):
    """进入内核的所有事件。回执、CI、你的回答都在这里。"""

    ASSIGN = "派活"
    PLAN_SUBMITTED = "交回方案"
    PLAN_APPROVED = "你批准方案"
    PLAN_REJECTED = "你打回方案"
    CODE_SUBMITTED = "交回代码"
    REFUSED_TO_FIX = "写手拒绝修改"
    QUOTA_EXHAUSTED = "额度用完"
    INCIDENT = "意外（超时、崩溃、网络）"
    CI_GREEN = "CI 绿"
    CI_RED = "CI 红"
    REVIEW = "审核结论"
    YOUR_APPROVAL = "你批准"
    YOUR_REJECTION = "你打回"
    MERGED = "合并成功"
    INTERVENTION_APPROVED = "人工审核通过"
    REWORK = "换一个 Agent 重做"
    STANDARD_CHANGED = "改审核标准"
    TAKE_OVER = "你自己接手"
    YOU_SUBMITTED_CODE = "你提交代码"
    ABANDON = "放弃"
    RETRY = "重试（已核对）"
    CANCEL = "取消"


@dataclass(frozen=True)
class Event:
    """事件。只带数据，不带行为。

    ``state_version`` 是外壳看到的状态版本号：和任务当前版本号不一致时，
    内核忽略这个事件，不改任何东西（防两个事件同时修改同一个任务）。
    """

    kind: EventKind
    task_id: str
    state_version: int | None = None
    attempt: int | None = None
    sha: str | None = None
    changes: ChangeSet | None = None
    plan: str | None = None
    review: Review | None = None
    reason: str | None = None
    provider: str | None = None
    # 这次有哪些 AI 参与过（人工提交时要补记进"参与过的提供方"集合）
    providers: tuple[str, ...] = ()
    model_suggestion: Level | None = None
    check_result: CheckResult | None = None
    standard_version: int | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class Decision:
    """内核的输出：新的任务记录 + 动作清单 + 一句理由（写进日志用）。"""

    task: TaskRecord
    actions: list[Action]
    reason: str
    # 状态版本号有没有变。没变说明这个事件被忽略了（比如版本号对不上、终点状态）。
    changed: bool = False
