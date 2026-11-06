# task-001 第三轮复核 · codex

结论：**修改后可以**。

范围：`feat/m1-runnable` 的 `d5933b7..39cd14f9cb28cca1ce6f17a27b6fdd1ce2316725`。依据 H1–H8 清单、原审核任务书及上一轮已核对的 M1 / 状态流转第七版 / ADR-0001 要求。未读取其他审核者输出；全程离线、未调用真实 AI、未提交或推送；只写本报告，未修改实现及测试文件。

现有检查：**270 passed，1 skipped**；pyright **0 errors**；ruff check、format 检查通过；单独运行 `tandem demo` 返回 **0**，C 场景到已合并、D 场景停在方案审批。跳过项是 Windows 不允许创建全部制表符/双引号文件名的真实 Git 测试；中文路径、中文改名和 NUL 解析测试实际执行。命令使用 `uv --offline --no-sync`，禁用字节码、pytest 缓存与 ruff 缓存。

## H1–H8 核对结果

| 条目 | 判断 | 理由 |
|---|---|---|
| H1 | **已修好** | 使用 `git diff --name-status -z -M` 的原始字节，按状态/路径的 NUL 字段解析，普通路径、改名和复制条目分开处理。真实 Git 中文受保护路径断言为 D，中文改名前后路径保持原样；特殊文件名测试按平台限制跳过，另有解析器测试。旧解析实现被新增测试检出。 |
| H2 | **已修好** | 先求 merge-base，普通增改、删除和改名分别统计两端内容，改名使用旧/新路径配对。真实 Git 测试确认改名后 3→2 个断言和分叉历史的共同祖先 3→受审提交 2 个断言都判 D。换回旧采集实现，两项均失败。 |
| H3 | **已修好** | `code_event` 在调用采集器前核对回执任务编号，错误时抛 ReceiptError。两个任务相同 attempt 的交叉投递测试验证采集器零调用、事件数和任务不变；换回旧函数后测试因未抛 ReceiptError 而失败。 |
| H4 | **已修好** | 新 FAIL 必须至少有一项编号、正文均非空的意见；空意见或仅有空白意见被拒收，不再进入退回修改路径。旧历史中的无意见 FAIL 也不能无说明批准。撤销新校验和旧记录防护后，对应三项测试均检出错误。 |
| H5 | **部分** | 已增加带来源的 OpenFinding、按复合键去重和按键否决；不同提供方/不同轮次复用 F1 的回归有效，序列化回环也通过。但是键只取 SHA 前 8 位，仍存在不同提交意见被吞掉的情况；上一版已持久化的意见格式也无法读取，见下方两项问题。 |
| H6 | **已修好** | 动作编号冲突时核对 task/kind/provider/detail，保留执行状态；事务返回新领取的动作 ID，Runner 只执行这些动作。换回旧 Store 提交/动作写入与旧 Runner 执行循环后，新增“相同决定只运行一次假 Agent”测试失败。现有测试同时覆盖 DONE 不倒退及编号不同内容冲突。 |
| H7 | **已修好** | Agent、人工及审核中新提交都清除旧席位；R03 记录当前合格席位；明确人工批准使用 human=True，AI 证据入口仍禁止编写者投票。人工接手→声明 codex 帮写→新 SHA CI 绿→R03→逐项回应→人工批准的新增路径通过。分别换回旧人工提交、旧 CI 处理器，清席位和 R03 席位测试均失败。 |
| H8 | **已修好** | 守卫检查覆盖本次 changes 之前的 approved_sha，避免先写入新批准再把旧批准检查掉；AI 最后一个通过和人工批准均从有效状态进入放行分支。把守卫改回检查 candidate 后，两个负例都失败，不再是错误状态下忽略事件的空测试。 |

## 换回旧写法的验证

所有替换仅发生在独立 Python 进程的内存中；没有 checkout、覆盖源码或新增测试文件。读取 `git show d5933b7:<path>`，使用该版本的函数/类，或在数据结构已变化时通过 AST 恢复原先的判断方式，再调用当前新增测试。临时 Git 仓库由现有测试在临时目录建立，不操作工作仓库提交。

| 条目 | 撤回的修复 | 当前新增测试 | 错误实现下结果 |
|---|---|---|---|
| H1 | 恢复旧 GitDiffSource 文本/制表符解析 | `test_git_diff_source_decodes_chinese_paths`、`test_git_diff_source_decodes_chinese_renames` | 两项均 AssertionError |
| H2 | 恢复旧 GitDiffSource 的断言采集 | `test_git_diff_source_counts_assertions_in_a_renamed_test_file`、`test_git_diff_source_uses_the_merge_base_for_the_before_side` | 两项均 AssertionError |
| H3 | 恢复旧 `Runner.code_event` | `test_code_event_rejects_a_receipt_from_another_task` | pytest 失败：DID NOT RAISE ReceiptError |
| H4 | 删除 FAIL 的有效意见校验；另恢复旧 `_missing_veto_reasons` | `test_row_14_fail_without_findings_is_rejected`、`test_row_14_fail_with_blank_finding_is_rejected`、`test_row_20_legacy_fail_without_findings_cannot_be_approved_silently` | 三项均 AssertionError |
| H5 | `_merge_findings` 改回仅按本地编号去重；为适配新结构使用 local_id 而非旧 Finding.id | `test_row_20_same_local_id_from_another_round_is_not_swallowed` | AssertionError |
| H6 | 恢复旧 Store.commit / `_insert_action` 和旧 Runner.handle | `test_replaying_an_identical_decision_does_not_run_the_agent_twice` | AssertionError |
| H7 | 分别恢复旧人工提交、旧 CI_GREEN 处理器 | `test_row_05_new_commit_clears_old_reviewer_seats`、`test_row_16_records_the_seats_that_actually_exist` | 两项均 AssertionError |
| H8 | `_merge` 改回 `merge_blocker(candidate, ...)` | `test_merge_guard_checks_the_approved_sha_on_the_ai_entry`、`test_merge_guard_checks_the_approved_sha_on_the_human_entry` | 两项均 AssertionError |

共 **14 次有效检出**，没有把接口错误、导入错误或临时文件清理错误计为检出。只能据此证明当前测试能拒绝这些旧行为，不能证明写手当时逐项执行过“先红再绿”的开发顺序。

## 影响本地运行或 ADR 安全不变量的问题（2 条）

### 1. 意见复合键截断 SHA，仍可吞掉新提交的反对意见

- **问题**：H5 要求的提交编号只以 8 位前缀参与身份计算，不是完整 SHA。
- **位置**：`src/tandem/core/transition.py:1115`、`src/tandem/core/transition.py:1140`。
- **为什么重要**：使用同一提供方 codex、标准 v1、编号 F1，先后针对 `abcdef12` 加 32 个 `1`、`abcdef12` 加 32 个 `2` 两个不同提交给出不同正文的 FAIL。内存完整事件路径实测：历史保存了两条不同 SHA 的反对意见，open_findings 却只剩第一条，因为两者键都是 `codex:F1@abcdef12:v1`。新 SHA 被打回后写手拒绝修改，用户只回答旧意见的键，就能进入 **AWAITING_MERGE**；新意见未被单独回应。8 位前缀不是唯一身份，不能承担 ADR 要求的按当前提交逐项确认。这里验证的是内核接受的完整 SHA 输入，没有声称在工作仓库制造了真实哈希碰撞提交。
- **建议**：存储和否决引用使用完整 SHA（或无损的结构化复合键），仅在展示时缩写；补“同一提供方、同标准、同本地编号、不同完整 SHA 但相同前 8 位”的回归，断言保留两项且必须分别回应。
- **严重程度**：**中**。

### 2. H5 改变持久化格式后，上一版本的待回应任务无法读取

- **问题**：新版反序列化要求每项有 key/provider/sha/standard_version/local_id；上一版 open_findings 只有 id/text，没有迁移或兼容读取。
- **位置**：`src/tandem/shell/serde.py:144`、`src/tandem/shell/serde.py:316`。
- **为什么重要**：使用 `d5933b7` 的实际审核处理器生成带 F1 的退回任务，再用该版本 serde 生成旧 JSON，其 open_findings 为 `[{"id":"F1","text":"legacy objection"}]`。把这份有效旧快照存入内存 SQLite，由新版 `Store.load_task`、`Store.list_tasks` 读取，两者都抛 **SerializationError: open_finding.key 应该是字符串**。因此已有这种待回应任务的本地数据库升级后，status 会因列任务失败而中断，approve 等入口也无法读取任务。新增回环测试仅验证新版写→新版读；H4 的“旧记录”测试在内存里构造新类型，也没有走旧 JSON 读取。
- **建议**：增加旧格式读取/迁移：结合 review_history 恢复完整来源键，无法唯一恢复时保留为明确未解决项，不能静默丢弃反对意见；加入旧版本真实 JSON→新 Store 读取→按键回应的测试。不要以删除用户数据库作为默认处理方式。
- **严重程度**：**中**。

后续：继续保留已获准暂缓的完整日志重放、同 Issue 多 PR 聚合和验收失败计数决策，并在接入真实执行器前补充身份认证与恢复验证。

现有全新数据库的 M1 demo 可运行，H1–H8 的回归保护明显有效；仍应修复上述意见身份和存量读取问题，再交用户人工审核。最终结论：**修改后可以**。
