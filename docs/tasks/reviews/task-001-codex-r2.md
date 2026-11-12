# task-001 第二轮审核 · codex

结论：**修改后可以**。

审核分支 `feat/m1-runnable`，范围 `5f009fe..c6f566b904c4daf83563a130f1432259843e6f80`。依据修复清单、原审核任务书、M1 任务书、状态流转第七版和 ADR-0001；回看了自己的第一轮报告，未读取其他审核者本轮输出。

全程离线，未调用真实 AI，未提交或推送。除本报告外未修改项目文件。运行现有测试时使用临时数据库和本地测试仓库；额外反例只使用内存 SQLite、假 Agent、内存 mock 和通过 stdin 执行的脚本，没有添加测试文件。

验证结果：`uv run --offline --no-sync pytest -q -p no:cacheprovider` **246 passed**；pyright **0 errors**；ruff check 与 format 检查通过。设置了 `UV_OFFLINE`、`UV_NO_SYNC`、`PYTHONDONTWRITEBYTECODE`，ruff 使用 `--no-cache`。pytest 包含 demo 验证。未发现本轮引入内核 IO 或真实 AI 调用，默认外部动作仍受 dry-run 保护。

## F1–F14 逐条核对

| 条目 | 判断 | 理由与证据 |
|---|---|---|
| F1 | **部分** | 回执 `changes` 已忽略并警告；新增 `DiffSource`、真实 Git 实现、假实现及“未扫描”标记；`Runner.code_event` 使用采集结果。但真实采集的 Git 引号路径、改名断言、分叉基线处理有遗漏，且事件构造丢弃原回执任务编号，见问题 1–3。 |
| F2 | **已修好** | 所有生成 `MERGE` 的分支收口到 `_merge`，统一检查 `ci_green` 与当前提交；R01→改标准→两家通过仍停在待 AI 审核，不产生 MERGE。对应新增回归在内存换回基线审核处理器后确实失败。另有一个辅助测试无效，见问题 8，不影响主反例已被有效覆盖的判断。 |
| F3 | **已修好** | 接收结论按 provider 检查指定席位、排除编写参与者并去重；完成条件按不同 provider 数量及全部指定席位判断。同方冒充另一席位的旧反例已被阻止，对应测试换回基线处理器后失败。审核身份目前仍来自调用方输入，不能把 M1 假事件当作真实提供方身份认证。 |
| F4 | **已修好** | 验收中、AI 审核中、待人工审核等状态有新提交更新及旧结论失效路径；已经发出 MERGE 时显式保留状态，等待核对。四种指定事件检查 SHA，CLI `--sha` 必填。审核中新 SHA 的新增回归换回基线处理器后失败。 |
| F5 | **部分** | 人工提交已重算等级、清掉当前审核/批准/CI，并累积参与提供方；升级 D 会先审批方案；场景 9 现在真正传入 CORE_CHANGES 并断言 D。但没有清理旧审核席位，与新放行守卫组合会阻断合法人工介入批准，见问题 7。 |
| F6 | **已修好** | 文档目录与配置扩展名共同约束降级；空路径、绝对路径、`..` 判 D；新增 docs 内 Python、非法路径、反斜杠、改名路径测试。这里的纯函数修复成立；Git 输出未解码属于 F1 采集边界问题。 |
| F7 | **部分** | 事件、快照、动作已在单事务保存，UPDATE 带预期旧版本并检查 rowcount；不同内容的同版本写入会冲突；有回滚和双连接竞争测试。但是“完全相同”的事务重放会重置动作结果，并可重复启动假 Agent，见问题 6。 |
| F8 | **已修好** | CLI 待你审核发送 YOUR_APPROVAL，待你介入发送 INTERVENTION_APPROVED；被忽略时返回非零并打印原因；已补单 Agent C、D 的实际 CLI 批准测试。 |
| F9 | **已修好** | 待 AI 审核收到额度事件会按额度、参与历史与指定席位复查，不足时 R03；新增测试先进入 AI 审核再耗尽审核者，确实覆盖 #16，换回基线处理器后失败。 |
| F10 | **已修好** | risk.yml 默认 single_agent；demo 显式构造 multi_agent，逐场景核对终态及 SHA，失败返回非零；测试以 single_agent 策略破坏 demo 并断言失败。 |
| F11 | **已修好** | 按本轮收窄后的要求：额度落库并在新 Runner 恢复，submit 追加 CREATED，任务动作状态由动作表投影；有关闭再打开数据库的额度测试及动作一致性测试。完整日志重放仍是明确获准暂缓的缺口；本地审核不能证明其已列入远端 PR 描述。 |
| F12 | **已修好** | WORKING 出错后 NOT_CONFIRMED 回到 PENDING；启动失败产生 INCIDENT；外壳测试实际走假 Agent 失败→ERROR→重试→第二次派活→假回执→验收。恢复状态测试换回基线处理器后失败。 |
| F13 | **部分** | findings、review_history、open_findings、逐 ID 理由及序列化均已增加；带两项 findings 的拒绝修改反例有有效测试。但是合法默认值仍允许空 findings 的 FAIL，原来的无理由放行反例仍成立；跨轮重复编号还会吞掉新意见，见问题 4、5。 |
| F14 | **已修好** | main 在执行命令前把 stdout/stderr 的 TextIOWrapper 都 reconfigure 为 UTF-8；测试从 cp936 输出流验证实际字节，以及入口调用顺序。 |

以上“已修好”指本轮明确要求和相应反例，不表示整个子系统已经具备生产身份认证或恢复能力。验收失败次数保留、同 Issue 多 PR 聚合及完整日志重放按清单保留，不作为本轮新增问题。

## 残留及新增问题（8 条，按严重程度排列）

### 1. Git 引号路径未经解码，底线路径可能降为 C

- **问题**：采集器用换行和制表符拆 `git diff --name-status` 输出，却把 Git 的带引号、转义形式直接当真实路径。
- **位置**：`src/tandem/shell/diff_source.py:96`、`src/tandem/shell/diff_source.py:103`。
- **为什么重要**：Git 默认会引用含非 ASCII 字符或特殊字符的路径。以 Git 输出格式构造 `M\t".github/workflows/\344\270\255.yml"` 的内存反例，采集到的路径仍含外层双引号及八进制转义；`compute_level` 实测返回 **C**。真实路径 `.github/workflows/中.yml` 应命中 `.github/**` 为 D。根目录组件前的引号使受保护前缀失配。现有本地仓库测试只有 ASCII 文件名，未覆盖此情况。
- **建议**：使用 `--name-status -z -M` 并按 NUL 格式解析普通条目及改名条目，明确解码路径；增加中文、制表符、双引号等文件名的真实临时 Git 仓库测试，并断言最终等级。
- **严重程度**：**高**。

### 2. 断言统计没有对应上实际 diff，改名或分叉基线可漏判减少

- **问题**：断言统计只接收普通增改的 `paths`，排除了改名；且路径列表用 `base...sha`，统计旧内容却用 base 本身，而非共同祖先。
- **位置**：`src/tandem/shell/diff_source.py:105`、`src/tandem/shell/diff_source.py:113`、`src/tandem/shell/diff_source.py:129`。
- **为什么重要**：内存模拟 `R080 tests/test_a.py → tests/test_b.py`，同时断言由 10 减为 9，结果 `assertions_before/after` 都是 None，等级 **C**。另一个分叉场景：共同祖先有 3 个断言，base 分支已改为 1 个，受审分支改为 2 个；三点 diff 审的是 3→2，本实现却数成 1→2，也返回 C。两者都遗漏了明确要求的 D 级底线。这些反例采用受控 Git 输出/文件内容 mock，未在工作仓库创建提交。
- **建议**：解析并固定 merge-base；统计前后分别使用同一 diff 两端的文件内容，改名使用旧路径和新路径配对；新增“改名且减少断言”与“base、受审分支均有独立提交”的真实 Git 测试。
- **严重程度**：**高**。

### 3. 新回执转换函数把错误任务编号改写成当前任务编号

- **问题**：`Runner.code_event(task, receipt)` 未验证 `receipt.task_id == task.task_id`，直接把传入 task 的编号写到事件里，使内核原有的编号检查失效。
- **位置**：`src/tandem/shell/runner.py:113`、`src/tandem/shell/runner.py:127`。
- **为什么重要**：实测 t1 正在 WORKING，把 `task_id='other-task'`、attempt 恰好匹配的回执传给 `code_event(t1, receipt)`，得到 `event.task_id='t1'`，handle 后 **t1 进入 AWAITING_ACCEPTANCE**。因此另一任务的误投回执不再被拒绝；真实改动即使来自采集器，也不是这次任务交回代码的有效证明。
- **建议**：采集前验证回执任务编号，错误时抛明确的回执错误或产生可记录的无效事件，禁止改写为匹配编号；增加两个任务相同 attempt 的交叉投递测试，验证任务与采集器均不被推进。
- **严重程度**：**高**。

### 4. 空 findings 的 FAIL 仍能走完上一轮无理由否决反例

- **问题**：FAIL 可以不带任何 findings；退回后 reviews 被清空，理由检查只看 open_findings 和当前 reviews，不看尚未回应的历史 FAIL。
- **位置**：`src/tandem/core/model.py:245`、`src/tandem/core/transition.py:734`、`src/tandem/core/transition.py:1105`。
- **为什么重要**：原样复现“codex FAIL（默认空 findings）→退回→重新派活→REFUSED_TO_FIX→INTERVENTION_APPROVED（当前 SHA、无 reason、无 veto_reasons）”，结果仍是 **AWAITING_MERGE**；历史有 1 条 FAIL，open_findings 却为 0。新增测试仅为这个反例补了非空 findings，覆盖了新的规范输入，没有覆盖原本仍合法的输入。
- **建议**：FAIL 必须有至少一项编号和非空正文，否则拒收或转换成明确的待处理错误；兼容旧记录时应生成可追踪的反对项，不能把“没有结构化意见”视为“没有反对意见”。保留上一轮完全不带 findings 的反例并断言无法无理由合并。
- **严重程度**：**中**。

### 5. findings 只按本地 ID 合并，跨轮复用 F1 会吞掉新意见

- **问题**：`_merge_findings` 只以裸 `finding.id` 去重，并明确保留先到的正文；编号没有审核来源、SHA 或标准版本命名空间。
- **位置**：`src/tandem/core/model.py:221`、`src/tandem/core/transition.py:1087`。
- **为什么重要**：实测第一轮 codex 提出 `F1=old objection`；提交新 SHA 后，第二轮 opencode-go 提出 `F1=different new objection`。历史里两条都存在，但 open_findings 只剩 **旧正文**。人工介入只需回答旧 F1，新的独立反对意见不会单独要求理由。审核者通常各自从 F1 编号，这是正常输入而非特殊构造。
- **建议**：使用稳定的复合意见键，例如审核记录 ID/提供方、SHA、标准版本和本地编号；待回应项应携带来源上下文，CLI 否决也引用这个键。增加不同审核者或不同轮次同编号、不同正文的测试。
- **严重程度**：**中**。

### 6. 相同事务重放会把 DONE 动作重置为 SENT，并重复执行

- **问题**：任务快照接受完全相同内容后，仍继续 upsert 动作；冲突分支无条件覆盖 status。Runner 也无论动作是否已存在，执行 decision.actions 全部条目。
- **位置**：`src/tandem/shell/store.py:170`、`src/tandem/shell/store.py:186`、`src/tandem/shell/store.py:240`、`src/tandem/shell/runner.py:158`。
- **为什么重要**：内存 Store 中第一次保存动作，再标 DONE，然后重放相同 task/actions，动作实测变回 **SENT**。进一步使用固定时钟模拟两个读取同一旧 PENDING 快照的处理者，第二份完全相同决定没有冲突；同一 START_AGENT 编号实际消费了假 Agent 的第二份回执，任务仍只有版本 1。也就是“相同内容幂等”只检查了快照，未覆盖动作和执行。当前没有真实副作用，但 M1 假执行已经可复现重复启动。
- **建议**：动作编号冲突时校验不可变字段相同并保留现有执行状态；事务结果区分新动作与已存在动作，执行器只领取本次确实获得执行权的动作。增加相同决定重放、完成状态不倒退及假 Agent 只调用一次的测试。
- **严重程度**：**中**。

### 7. 人工接手后旧审核席位残留，会阻断本应允许的 R03 人工批准

- **问题**：新提交清除 reviews，却保留 designated_reviewers；CI 发现审核者不足进入 R03 时也不清理旧席位。统一守卫把旧席位与新的参与者集合相交，即使本次走人工介入而不是 AI 通过放行，也会拒绝。
- **位置**：`src/tandem/core/transition.py:156`、`src/tandem/core/transition.py:646`、`src/tandem/core/transition.py:985`。
- **为什么重要**：实测 C 任务曾指定 codex/opencode-go，FAIL 后写手拒绝修改；用户接手并声明 codex 帮写新 SHA。新 SHA CI 绿，但只剩一家合格审核者，正确进入 R03。此时用户带当前 SHA 和完整否决理由人工批准，却因旧席位仍有 codex 被守卫拒绝（changed=False）。第七版 #20 允许用户在 R03 人工审核通过；不能因历史上被指定、如今已成为作者的一家仍挂在旧席位里而永久挡住。
- **建议**：新 SHA 失效处理中一并失效旧席位；准备审核失败时记录当前实际席位。守卫应区分“用 AI 审核证据放行”和“明确人工介入批准”，保留编写者不得贡献审核票的不变量，避免把过期席位当作本次证据。
- **严重程度**：**中**。

### 8. SHA 守卫测试未进入守卫，完全删除守卫仍通过

- **问题**：`test_merge_guard_checks_the_approved_sha` 在任务已经 AWAITING_MERGE 时发送 REVIEW；这个状态直接忽略 REVIEW，根本不会执行 `_merge`。
- **位置**：`tests/core/test_transition_rows.py:654`、`src/tandem/core/transition.py:701`。
- **为什么重要**：实测在内存把 `merge_blocker` 整体替换成恒返回空元组，该测试仍然通过。它断言这次没有新 MERGE，实际上只是证明事件在错误状态被忽略，无法证明 approved_sha 守卫存在。不能用它支撑“所有放行不变量都有反例测试”。
- **建议**：先处于确实会调用 `_merge` 的状态，再制造批准与当前 SHA 不一致的输入；同时验证事件确实到达相关分支。对人工批准、AI 最后一个通过结论等入口分别补负例。
- **严重程度**：**低**。

## 上一轮反例与回归测试有效性

为区分“测试通过”和“能检出错误”，额外读取 `5f009fe` 的 transition.py 到内存模块，逐项替换当前同名处理器，再直接执行当前新增测试。只替换处理器，不写源码、不切分支；以下六项均以 **AssertionError** 检出基线行为，而非导入或接口错误：

| 上一轮反例 | 当前测试与判断 |
|---|---|
| 红 CI→R01→改标准→两家通过仍合并 | `test_row_12_cannot_merge_after_ci_failure_even_with_new_standard`：当前通过，基线 `_on_review` 下失败，有效。 |
| 同一提供方冒充另一指定审核者 | `test_row_12_review_extension_provider_counts_as_provider`：当前通过，基线 `_on_review` 下失败，有效。 |
| AI 审核中新提交被忽略 | `test_row_05_new_commit_during_ai_review_updates_sha`：当前通过，基线 `_on_code_submitted` 下失败，有效。 |
| 人工提交 core 不升 D | `test_row_24_your_commit_is_re_leveled_by_real_changes`：当前通过，基线人工提交处理器下失败，有效；场景 9 也已传真实 core 改动。 |
| 审核途中耗尽审核者被忽略 | `test_row_16_reviewer_lost_during_review_goes_to_you`：当前通过，基线额度处理器下失败，有效，确实从 AI 审核状态触发。 |
| 异常后假装回到 WORKING | `test_row_26_retry_after_working_returns_to_pending`：当前通过，基线重试处理器下失败，有效；另有外壳假 Agent 再运行测试。 |

其余反例按测试源码、实际执行及本轮反例交叉核对，没有宣称对它们做过上述基线替换：

- **docs 内代码、非法路径降级**：新增 `test_python_file_inside_docs_cannot_downgrade`、`test_illegal_paths_are_d_level` 直接断言旧错误输入的等级，具有有效负例，不再只测试普通 src 路径。
- **事务中途失败、同版本覆盖**：新增 `test_commit_is_atomic`、`test_same_version_only_accepts_identical_content`、双连接竞争测试检查回滚和拒绝覆盖；仍缺“内容相同但动作已经完成”的重放反例，见问题 6。
- **CLI 待你审核批准不动**：C、D 两个测试真实调用 `main(approve...)` 后重新打开数据库断言 AWAITING_MERGE，能检出错误事件；不是仅检查输出或返回码。
- **重启忘额度、动作状态分叉**：额度测试关闭数据库再重新构造 Runner；动作测试比较投影结果与动作表。有行为验证，不只是序列化字段存在。完整日志重放按修复清单暂缓。
- **demo 失败仍返回成功**：测试显式传入会使场景停下的单 Agent 策略并要求非零，能够检查终态失败；默认模式及 UTF-8 也有实际断言。
- **拒绝修改后无理由人工批准**：新测试只覆盖带两条 findings 的版本；上一轮不带 findings 的原反例仍可成功生成 MERGE，尚未形成完整回归保护，见问题 4。
- **新 SHA 及事件绑定**：新增审核中、验收中、人工审核中新提交和批准/合并/CI_RED SHA 负例；但 shell 的跨任务编号反例未覆盖，见问题 3。辅助 approved_sha 测试仍可在无守卫时通过，见问题 8。

无法仅凭最终通过的测试及修复提交证明每条修改都实际经历了“先红再绿”；本报告只确认可复核的行为与上述内存基线对照。

本轮已修复上一轮主要的 CI 绕过、同方双票和 CLI 放行阻断，结构无需推倒重做。修好采集边界、回执归属、否决意见和动作幂等后，再提交用户审核。最终结论：**修改后可以**。
