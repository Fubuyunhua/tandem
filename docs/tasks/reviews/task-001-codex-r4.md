# task-001 第四轮复核 · codex

结论：**修改后可以**。

审核范围固定为 `39cd14f..2988de38c54dc899917b89bc9f68cc26d6f46b60`，逐项核对 pi 的四个实现提交，参照自己的第三轮报告。没有修改实现、测试或其他文档；没有联网、调用真实 AI 或读取其他审核者输出。只新增并提交本报告，不推送。

开始时工作区干净、HEAD 为 2988de3。该版本全量检查结果：ruff check / format 检查通过，pyright **0 errors**，pytest **287 passed，1 skipped**；跳过的是 Windows 特殊文件名测试。使用 `uv --offline --no-sync`，禁用字节码及 pytest/ruff 缓存。

审核期间 pi 修改了测试并另行提交 **77855c0**（异常核对后的合并重发）。本报告不评价该提交；后续回退验证通过 `git show` 固定加载 **2988de3 的实现、helpers 和测试到独立进程内存**，不采用并行编辑的测试，也不 checkout 或覆盖工作区。下面的位置均指 2988de3。

## 四个提交的判断

| 提交 | 判断 | 修复是否成立、边界及新增问题 |
|---|---|---|
| `31b51d2` 完整 SHA 复合键 | **已修好** | finding_key 使用完整 SHA，short_key 仅用于备注展示；同提供方、同标准、同 F1、同前 8 位而完整 SHA 不同的两条意见不再被合并，否决按完整键分别检查。撤回键修复后，新增碰撞回归确实失败。未发现本次修改引入新的身份混淆。第三轮旧 JSON 格式兼容问题没有被修复；提交说明明确声明无存量、暂不修，本轮不把它算作已修，也不重复列为新增问题。 |
| `e38600b` 断言逐文件判断 | **部分** | 普通文件的减少不再被新增文件抵消；改名配对、逐文件记录和 JSON 回环成立。恢复旧采集器后，抵消减少及改名明细回归均失败。但改名后不再属于测试路径时仍统计新文件正文里的断言，存在“退出测试发现范围但不算减少”的残留边界，见问题 1。这是原计数方式的遗漏继续保留，并非本提交新引入的回归。 |
| `4310a82` 换 SHA 清旧证据 | **已修好（现有可达路径）** | PLAN_SUBMITTED 换 SHA 的真实漏清路径已修，撤销统一清理后对应新增测试失败。逐项检查所有换 SHA 入口，未发现调用方显式带旧 CI 绿到新 SHA 的可达事件路径；“显式传值优先”仍是内部例外，不能把它表述成不可绕过的统一不变量，详见下节。未发现本提交引入新的放行路径。 |
| `2988de3` 5b 方案内容与 SHA | **部分** | WORKING→代码回执升 D 的直接 #5b 路径保存了带正文、底线原因和 SHA 的 PlanEntry；正常文字方案的历史保存也成立；有 SHA 的旧任务及人工接手批准能够继续。三个处理器分别恢复旧写法后，相应新增测试均以断言失败检出。修复没有覆盖审核中新提交、人工提交升级 D 的方案内容，也未禁止新建的无 SHA 方案获批，见问题 2、3；属于本次修复范围遗漏，未观察到有 SHA 的旧任务被新校验卡死。 |

## `_drop_stale_evidence` 的显式覆盖例外

`src/tandem/core/transition.py:78` 先填失效值，再 `merged.update(changes)`，因此直接调用内部辅助函数时，`{"latest_sha": 新SHA, "ci_green": True}` 的结果确实仍为 True。**它不是强制覆盖调用方的守卫。**

但在本次范围的实际事件路径中：

- `_on_plan_submitted` 改 latest_sha 时没有显式传 CI/批准/审核字段，因此由统一处理器清理。
- `_on_code_submitted`、`_on_new_submission`、`_on_you_submitted_code` 均显式传 `ci_green=False`、`approved_sha=None`、空审核及空席位，覆盖结果仍然安全。
- `_merge` 会先构造 candidate，但本版本所有调用者都没有通过它改变 latest_sha；CI_GREEN 的 `replace(task, ci_green=True)` 也没有改 SHA，且前面已经核对事件 SHA。

所以不能把“辅助函数能被内部显式参数覆盖”直接报告成一个已经可达的旧 CI 放行漏洞。需要收紧的是后续维护承诺：新增转换若显式传旧证据，统一处理器不会保护它；目前对应测试也没有覆盖这种内部例外。

## 残留问题（3 条）

### 1. 测试文件原样移出测试路径，活动测试减少却仍判 C

- **问题**：改名分支只要求旧、新路径至少一端属于测试路径，然后无条件统计新文件内容；没有按两端是否仍是测试文件分别计数。
- **位置**：`src/tandem/shell/diff_source.py:220`、`src/tandem/shell/diff_source.py:224`。
- **为什么重要**：在临时本地 Git 仓库中，`tests/test_a.py` 有 3 条断言，另保留一个测试；将它原样改名为 `src/helper.py`。实测 Git 识别为改名，pytest 收集数从 **2 降到 1**，剩余测试 **1 passed**；采集器却报告 **3→3、assertion_drops=()、等级 C**。这些断言已不在默认测试发现范围内，移走测试可以避开 D 级底线。另单独验证了用户点名的较窄情况：若同时把正文断言从 3 减到 2，即使新路径非测试路径，当前实现仍能抓到并判 D；遗漏的是“原样移出”的测试证据消失。
- **建议**：按旧路径的测试属性计算 before，按新路径的测试属性计算 after；旧端是测试而新端不是时，测试断言的 after 应为 0。补真实 Git 改名到非测试路径、pytest 收集减少且剩余测试仍绿的回归；反方向移入测试路径也按对应端判断。
- **严重程度**：**中**。

### 2. 人工提交和审核中新提交升级 D，仍会批准不存在的方案正文

- **问题**：本次 PlanEntry 只写入正常 PLAN_SUBMITTED 与 WORKING 的直接 #5b 分支；另外两个同样进入方案审批的升级分支只增加 plan_version。
- **位置**：`src/tandem/core/transition.py:506`、`src/tandem/core/transition.py:542`、`src/tandem/core/transition.py:1036`、`src/tandem/core/transition.py:1072`。
- **为什么重要**：分别实测：① C 级待 AI 审核时收到新 SHA 的 CORE_CHANGES；② 人工接手后提交新 SHA 的 CORE_CHANGES。两者都到 AWAITING_PLAN_APPROVAL、plan_version=1，但 **plan() 为 None，plan_text 为空**。带正确 SHA 批准后，前者到 PENDING，后者到 YOU_WORKING；人工再次提交后可到 AWAITING_ACCEPTANCE。状态路径没有卡死，却继续保留了该提交本来要修的“批准不存在的方案内容”。新增 #5b 测试只从 WORKING 出发，未覆盖这两个分支。
- **建议**：把“升级 D 时为这版提交生成方案正文和 PlanEntry”提为共用逻辑，三种代码提交入口都保存相同的 SHA、正文和底线原因；批准前验证本版方案可显示，而非仅依赖 latest_sha 回退。补人工和审核中新提交的持久化/批准回归。
- **严重程度**：**中**。

### 3. 新方案也能没有 SHA，缺 SHA 或任意 SHA 的批准仍会生效

- **问题**：PLAN_SUBMITTED 不要求 SHA，创建的 entry.sha 可以是空串；批准只在 expected_sha 非空时才执行 SHA 校验。这个兼容回退没有限定为旧任务。
- **位置**：`src/tandem/core/transition.py:349`、`src/tandem/core/transition.py:361`、`src/tandem/core/transition.py:386`。
- **为什么重要**：实测全新 D 任务 ASSIGN→`PLAN_SUBMITTED(plan="new plan with no SHA")`，得到新建 PlanEntry 但 sha=""、latest_sha=None。随后 `PLAN_APPROVED()` **完全不带 SHA**，或传一个任意 SHA，都能到 **PENDING** 并批准版本 1。它不满足本提交“批准必须带且匹配方案 SHA”的承诺。现有 helpers 中的 `to_d_ai_review` 本身仍在构造这种无 SHA 的方案和批准，全量测试因此也没有排除这条路径。
- **建议**：新方案回执必须带可绑定的 SHA；批准也必须具有明确、匹配的目标。旧任务若既没有方案 SHA 也没有 latest_sha，不应把无法核对当作匹配，可明确要求重新提交有编号的方案。保留旧任务有 latest_sha 时的兼容路径，增加全新无 SHA 方案/批准的负例。
- **严重程度**：**中**。

## 方案批准及旧任务路径的独立核对

- 将旧 JSON 中缺少 plan_history / plan_text 的任务读回，保留 latest_sha：错误 SHA 不生效，正确 SHA 能继续；普通写手回 PENDING，writer_is_human=True 回 YOU_WORKING。
- 人工提交 core 升 D 后，正确 SHA 批方案→YOU_WORKING→再次提交→AWAITING_ACCEPTANCE，CI 为 False，没有携带旧 CI 绿。此路径能运行，但方案正文缺失，已列问题 2。
- 旧任务本来没有方案记录时，`plan_text` 不会自动从旧 note 迁移；本轮没有把兼容读取误认作方案历史迁移已经完成。

## 独立进程内存回退结果

保留新数据结构以避免“属性不存在”冒充回归检出，恢复各提交父版本的处理函数/采集器；4310a82 则把 `_drop_stale_evidence` 换成直接返回 changes，等价撤销统一清理。测试固定来自 2988de3。共得到 **8 次 AssertionError 有效检出**；另有 1 次数据解包失败和 2 次通过，分别说明如下。

| 提交 / 回退 | 新测试 | 结果与评价 |
|---|---|---|
| 31b51d2：恢复父版本 finding_key | `test_row_20_same_sha_prefix_does_not_swallow_the_newer_finding` | **AssertionError**；有效检出完整键被截断。 |
| 同上 | `test_row_20_same_sha_prefix_findings_must_be_answered_separately` | **ValueError：expected 2, got 1**；旧实现先吞成一条，测试在解包阶段失败，尚未执行后续逐条理由断言。不能把这一次计为独立的否决检查断言检出。 |
| e38600b：恢复父版本 GitDiffSource | `test_git_diff_source_does_not_let_a_new_file_offset_a_drop` | **AssertionError**；有效，旧采集器无法给出逐文件减少。 |
| 同上 | `test_git_diff_source_reports_rename_drop_in_per_file_detail` | **AssertionError**；有效，缺少改名的逐文件减少记录。 |
| 同上 | `test_git_diff_source_counts_only_increases_as_not_bottom_line` | **通过**；这是正确行为正例，旧实现本来也满足，不能声称它在旧实现上失败。 |
| e38600b：模型恢复仅比较总数的 assertions_decreased 属性 | `test_single_file_drop_is_d_even_when_totals_are_flat` | **AssertionError**；有效检出逐文件属性退回总数比较。 |
| 4310a82：撤销统一清理 | `test_row_02_new_plan_with_a_new_sha_clears_stale_ci_and_seats` | **AssertionError**；有效复现旧方案提交携带旧 CI 绿。 |
| 同上 | `test_any_transition_that_changes_the_sha_drops_stale_evidence` | **通过**；人工提交处理器原本已经显式清掉这些字段。它仅覆盖一个具体入口，既不证明所有转换，也不检出本次统一处理器缺失。 |
| 2988de3：恢复父版本 `_on_code_submitted` | `test_row_05b_plan_records_what_you_are_approving` | **AssertionError**；有效，保留 PlanEntry API 后仍因没有方案条目失败，而非 AttributeError。 |
| 2988de3：恢复父版本 `_on_plan_approved` | `test_row_03_plan_approval_must_bind_the_plan_sha` | **AssertionError**；有效，父实现会接受该有 SHA 方案的无 SHA 批准。 |
| 2988de3：恢复父版本 `_on_plan_submitted` | `test_row_02_submitted_plan_text_survives_later_transitions` | **AssertionError**；有效，方案正文没有独立保存。 |

上述回退验证表明四个提交都有能拒绝对应主要旧错误的测试，但不能把所有新增测试都声称为“旧实现必失败”。目前仍缺问题 1–3 的边界用例；没有发现通过现有可达事件把旧 CI 绿直接带到新 SHA 并放行的反例。最终结论：**修改后可以**。
