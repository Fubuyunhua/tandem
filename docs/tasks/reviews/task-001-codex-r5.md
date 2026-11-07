# task-001 第五轮复核 · Codex

结论：**修改后可以**。发现两项中等问题，均集中在新增的清理核对；另有一项低严重程度的内核输入校验缺口。没有观察到终点状态被重新打开或清理核对发出真实合并动作。

## 范围与验证方式

审核范围固定为 `77855c065f0f47cb294668afe6b4e2f59d2f7d5a..16815b376a0e290ffc92abafde5cf4129da96c2d`；`c45aca8` 是上一轮复核文档，不算 pi 的实现修改。`77855c0` 的 NOT_CONFIRMED 重发逻辑作为基线边界一起检查，不声称它是本区间新增的修改。

开始时 `code_auto` 的分支为 `feat/m1-runnable`，工作树干净、HEAD 为 `16815b3`。仅阅读本地对象、源码和测试；独立反例只运行纯函数与 SQLite `:memory:`，不修改实现或测试，不访问 GitHub、不运行真实 Agent、不联网。本次只新增并提交本报告。

对该 HEAD 执行：

- `uv run --no-sync ruff check --no-cache`：通过。
- `uv run --no-sync ruff format --check --no-cache`：通过。
- `uv run --no-sync pyright`：0 errors。
- `uv run --no-sync python -B -m pytest -p no:cacheprovider`：**307 passed，1 skipped**。

上述命令设置 `UV_OFFLINE=1`、`PYTHONDONTWRITEBYTECODE=1`，不同步依赖、不生成项目字节码或测试缓存；跳过的是既有 Windows 特殊文件名用例。下面的行号均指 `16815b3`。

## 发现：按严重程度排序

### 1. 中：清理核对只改任务快照，动作表仍是 UNKNOWN，读回时覆盖核对结果

- **位置**：`src/tandem/core/transition.py:1382`、`src/tandem/core/transition.py:1393`；接线涉及 `src/tandem/shell/runner.py:140`、`src/tandem/shell/store.py:150`、`src/tandem/shell/store.py:315`。
- **问题**：`_on_cleanup_checked` 修改 `decision.task.actions`，但返回的 `decision.actions` 是空列表。Runner 保存任务快照后，既没有新的待执行动作，也没有任何分支更新已有动作表状态。Store 读取任务又以动作表投影覆盖快照里的动作状态。因此核对说明和 `cleanup_checked=True` 存下来了，核对的 DONE/ABANDONED 却丢失。
- **独立复现**：使用 `cancelled_with_unconfirmed_cleanup()` 构造已取消、CLOSE_PR 为 UNKNOWN 的真实转换结果；向内存 Store 同时写入任务及它的历史动作，再通过正常 `Runner.handle(CLEANUP_CHECKED)` 处理。两种核对分别得到：

| check_result | handle 返回的决定 | Store.load_task 读回 | unconfirmed_actions |
|---|---|---|---|
| PR_CLOSED | CLOSE_PR = DONE | CLOSE_PR = UNKNOWN；cleanup_checked=True | 仍包含该动作 |
| NOT_CONFIRMED | CLOSE_PR = ABANDONED | CLOSE_PR = UNKNOWN；cleanup_checked=True | 仍包含该动作 |

- **为什么重要**：用户已经核对或明确放弃的清理动作，在重新读取时仍显示未确认，核对无法真正收尾；结果还与已保存的说明互相矛盾。这是新增 CLEANUP_CHECKED 接入现有持久化流程的缺口，不是字面序列化问题。
- **现有测试为什么没抓住**：`tests/shell/test_store.py:301` 的 roundtrip 用例仅把含 ABANDONED 的任务快照写入一个没有对应动作行的 Store；投影找不到动作表数据，就不会覆盖。它没有覆盖“原动作已存在 → Runner 核对 → 读回”的正常生命周期。
- **建议**：为“更新既有清理动作状态”提供专门的持久化路径，与事件和版本更新放在同一事务内；不能把它们当新动作重新执行，也不能破坏已有的动作编号去重语义。补两种结果的 Runner + 内存 Store 集成回归，断言动作表、投影快照及未确认查询一致。

最小复现骨架（在当前可信源码环境内运行，无外部副作用）：

```python
from pathlib import Path
from tandem.core.model import EventKind, CheckResult
from tandem.shell.store import Store
from tandem.shell.runner import Runner
from tandem.shell.executor import Executor
from tandem.shell.diff_source import FakeDiffSource
from tests.core.helpers import (
    cancelled_with_unconfirmed_cleanup, policy, ev, NOW, CODE_CHANGES,
)

record, action_id = cancelled_with_unconfirmed_cleanup()
with Store(Path(":memory:")) as store:
    store.commit(task=record, actions=record.actions)
    runner = Runner(
        store, policy(), Executor(), FakeDiffSource(CODE_CHANGES), clock=lambda: NOW
    )
    result = runner.handle(ev(
        EventKind.CLEANUP_CHECKED,
        check_result=CheckResult.NOT_CONFIRMED,
        action_ids=(action_id,),
    ))
    # result.decision.task 中该动作是 ABANDONED；下面两处仍是 UNKNOWN / 未确认。
    print(store.load_task("t1").actions)
    print(store.unconfirmed_actions("t1"))
```

### 2. 中：清理核对没有限制目标必须“尚未确认”，可以反复改写历史完成事实

- **位置**：`src/tandem/core/transition.py:1367`、`src/tandem/core/transition.py:1377`。
- **问题**：处理器只验证动作存在和 kind 属于白名单，没有检查目标原状态是否是 SENT/UNKNOWN。`cleanup_checked` 被写入但不参与目标校验；“重复”也只检查目标是否已经等于本次准备写入的状态。
- **独立复现**：从同一个已取消、未知 CLOSE_PR 开始，依次提交三个 CLEANUP_CHECKED；每次使用最新状态版本，排除过期事件因素：

```text
PR_CLOSED      -> changed=True, version=4, action=DONE
NOT_CONFIRMED  -> changed=True, version=5, action=ABANDONED
PR_CLOSED      -> changed=True, version=6, action=DONE
```

- **为什么重要**：已经确认完成的动作又被记为“无法确认、已放弃”；已经明确放弃的动作又被普通核对改成完成。即使任务仍是 CANCELLED，也违背“只对未完成的清理做一次核对”的收尾语义。问题 1 修好动作表后，这种覆盖会真正持久化，因此不能只修 Store 而忽略入口守卫。
- **类型白名单的另一个边界**：只靠 kind 也不能说明动作来自“进入终点时的清理”。独立走 `WORKING → QUOTA_EXHAUSTED → PENDING → CANCELLED`，最后一次取消不产生任何清理动作，但先前额度耗尽产生的 STOP_AGENT `t1:2:1` 仍可被 CLEANUP_CHECKED 改为 DONE。若设计有意允许核对这种历史未完成的停进程动作，应明确声明；当前注释却描述为“取消时外壳发出的那几条清理动作”。不能仅凭类型就声称已经验证了来源。
- **建议**：只允许目标从 SENT/UNKNOWN 收尾为 DONE/ABANDONED；对已经收尾的动作，同结果幂等忽略、相反结果拒绝，后续事实更正另设明确入口。按动作逐个限制，不宜简单用全任务 `cleanup_checked=True` 禁止核对其他尚未确认的清理动作。再明确清理动作的来源政策；若仅限终止清理，应保存可核验的动作集合/来源。
- **缺失测试**：DONE→ABANDONED、ABANDONED→DONE、混合已收尾/未确认目标的原子拒绝，以及历史 STOP_AGENT 与本次终止清理的区分。现有测试只覆盖未知动作成功收尾、START_AGENT 被拒和非终点被拒。

### 3. 低：方案 SHA 的新增内核检查只排除 None，空白字符串仍可完成批准

- **位置**：`src/tandem/core/transition.py:411`、`src/tandem/core/transition.py:444`、`src/tandem/core/transition.py:452`。
- **独立复现**：全新 D 任务 ASSIGN 后，直接调用公开 `decide` 入口，发送 `PLAN_SUBMITTED(sha="   ", plan="a real plan")`，再发送 `PLAN_APPROVED(sha="   ")`：前者进入 AWAITING_PLAN_APPROVAL，后者进入 PENDING，批准版本 1。`sha=""` 的方案也会被接收，不过随后因 expected_sha 为空而无法批准。
- **边界说明**：`src/tandem/shell/receipt.py:105` 已对实际 Agent 回执的 SHA 做 strip 并拒绝空值，独立验证空串及全空白回执都被 ReceiptError 拒绝。因此这不是本轮发现的“通过正常 Agent 回执就可绕过”的漏洞，也没有把测试使用的 `plan-a` 等非 40 位示例 SHA 当作错误；问题是公开内核事件入口没有完整兑现“必须带可核对编号”的不变量。
- **建议**：方案提交与批准都拒绝空白字符串，并明确采用拒绝还是统一规范化；继续保留旧任务有有效 latest_sha 时的兼容回退。补直接 Event 的 None、空串、全空白和错误 SHA 负例，不能只测试 None。

## 逐项判断与通过的部分

| 重点 | 判断与证据 |
|---|---|
| PR_CLOSED | 新 `_forget_pr_evidence()` 已清除 pr_opened、CI、approved_sha、有效审核、席位和退回标记；latest_sha 与历史仍保留。现有回归通过；没有看到旧 PR 的 CI/批准直接跟入新一轮放行。外壳的旧 PR 绑定生命周期不在本次内核修改范围，不能把此辅助函数当成已解决适配器换 PR 的证明。 |
| NOT_CONFIRMED | 基线 77855c0 的重发逻辑仍保留：正常待合并异常恢复会发出新编号 MERGE，CI 红或批准 SHA 不符时不重发。它不是本区间新增提交，不能把本次测试通过记成新修复。外壳合并后需要同步接纳“现在确实会有重发动作”的行为。 |
| CLEANUP_CHECKED 的窄入口 | 非终点任务收到该事件时被忽略；终点中错误动作类型、空 ID、缺失动作和不支持结果均会拒绝；不产生新的执行动作。但完成状态持久化及既有动作是否可再改的问题未闭合，见问题 1、2。 |
| 三个升级 D 入口 | WORKING 交代码、审核中新提交、人工提交均调用同一个 escalation_plan。额外把原 plan_version 设为 3，逐条实测都保存版本 4、正确 SHA 和底线正文，正确 SHA 批准后普通写手回 PENDING、人工写手回 YOU_WORKING。上一轮“另外两个入口没有方案正文”的遗漏已修好。 |
| 方案提交与批准 | None SHA 被拒，带有效编号时无 SHA/错误 SHA 的批准被拒，匹配值才生效；旧任务没有任何可用编号时拒绝批准。正常路径的上一轮问题已修，空白 Event 的窄缺口见问题 3。 |
| 终点状态 | 对三个真实终点记录（已取消、已合并、失败）穷举除 CLEANUP_CHECKED 外的全部 23 种事件，共 69 次：均 changed=False，任务记录完全不变。有效清理核对只更新记账，不改变终点状态，不产生 MERGE；没有发现离开终点的反例。 |
| 外部确认合并的标记 | 无系统批准时会保存 merge_confirmed_externally 和说明；正常有匹配批准时不标成未经放行。新字段及事件动作编号的序列化回环测试通过。该标记依赖可信外壳提供 GitHub 事实，内核本身不访问 GitHub。 |

### 精确终点不变量的文案还应包含 updated_at

`decide()` 在 changed=True 时统一写入参数 now。对清理核对使用与原记录不同的 now，实测变化字段是：

```text
state_version, actions, cleanup_checked, reason, note, updated_at
```

`transition.py:285` 附近“除了动作状态、cleanup_checked、说明和版本号，其他字段一律不变”的注释漏掉 updated_at。这个时间更新符合记录更新的通常语义，不列为独立功能故障，但 task-006 若照注释写完整字段性质测试，会得到误报；应把 updated_at 明列为允许变化字段。现有测试只是逐项点名若干字段，没有穷举 dataclass 的全部字段。

## 建议补测与最终结论

优先补“已有动作行”的 Runner/Store 清理核对集成回归和动作单向收尾负例，再补空白方案 SHA、完整字段终点性质测试。清理状态更新应是记账事务，不能通过执行旧清理动作来模拟确认，更不能因此重新合并或改变终点。

本轮没有修改实现、没有新增测试文件、没有替用户修复内核。结论保持 **修改后可以**：主要状态恢复和三入口方案正文已改善，但 CLEANUP_CHECKED 尚不能在真实持久化链路上可靠收尾。
