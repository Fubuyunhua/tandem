# M1 第一版人工验收指南

本页供你审核**本地可运行骨架**。验收基线是 `feat/cli-run@5e8cfb8`，包含合入的 `feat/m1-runnable@2988de3` 和 task-005 的 CLI 修复。其他分支的实现、远端 CI 和真实部署，单独列明。

你现在可以亲手检查任务怎么流转、证据怎么绑定、哪里必须等你。WSL 后台、真实模型干活、真实 GitHub 闭环仍有未完成项；本地演示通过不能据此宣布 PRD 的整个 M1 已交付。

文档整理时全程离线，没有调用真实 AI、GitHub 或 WSL。下面的 PowerShell 准备块和 A–G 已逐段在临时新库复跑：**47 次 CLI 调用，全部符合预期退出码**；复跑时仅代填 Read-Host，从实际 show 输出复制完整编号/意见键，没有修改 CLI 行为。另运行了 T0–T5、demo、命令帮助及本地集成清单检查。T0 为 **337 passed，1 skipped**，ruff check/format 与 pyright 通过。跳过的是 Windows 不允许创建全部特殊文件名的 Git 测试。测试通过证明的是具体场景，不是所有安全性质的形式化证明。

## 1. 先统一“通过”的含义

- `run` 的 Agent、改动、CI、审核都是假的。40 位“提交编号”由模拟器生成，并不证明 Git 中存在对应提交；“CI 绿”是模拟事件，不表示刚执行过真实项目测试。
- `approve` 表示你对指定编号作出明确决定；`run` 不会代你生成三种人工批准事件。单 Agent 是 M1 默认模式。下面多 Agent 案例用于演练后续规则，不表示真实多模型已接入。
- 当前分支没有 `poll`、`reconcile` 或真实 GitHub 写入命令。task-004 在另一个分支；其默认 dry-run 仍可能读取 GitHub，`--live` 会启用真实写入。**M1 不用 --live，由用户在 GitHub 上手动合并。** 本页没有任何联网验收命令。
- 退出码：`run` 的 **1** 表示仍有任务等人、待重做或卡住，这是很多演练的预期结果；**2** 表示轮数达到上限，参数错误也可能返回 2，要看输出；**0** 表示全部任务到终点，终点包括已合并、已取消、失败。它不证明真实 PR 已合并。
- `show` 展示已有 AI 意见。若要练独立审查，先写自己的判断再展开它；已经看过 AI 意见的发现，不应记作独立发现。目前软件没有替你强制这项顺序。

## 2. PRD 的 M1 条目逐项核对

[PRD 第 7 节](PRD.md#7-里程碑用自己开发自己)没有单独的“M1 验收标准表”。下表把 M1 那一行逐句拆开，并用 F4、F7 补充回执和日志的含义；第 6 节三个月 KPI 不作为第一版本次必须达到的数值。

表中 `core/` 指 `src/tandem/core/`，`shell/` 指 `src/tandem/shell/`；T0–T5 是第 5 节的实际测试命令，A–G 是第 4 节可复制的流程。**“没有证明”不写成通过。**

| M1 原要求 | 实现位置与证明测试 | 你亲手怎么验证 | 当前结论 |
|---|---|---|---|
| M1-1 在 WSL 里跑 hub | 本分支没有 WSL 部署/保活入口；`shell/cli.py` 是一次性命令，不是守护服务。task-002、task-007 见 S4/S5 | T7 查看本分支集成清单；本页不执行 WSL 配置，暂无真实部署验收命令 | **未完成，后台暂停** |
| M1-2 事件源先只接打开且带 agent 标签的 Issue | 当前 `submit` 是人工建任务。task-004 分支的 `shell/github.py:GhGitHub.list_issues`、`github_events.py:GitHubEvents.poll` 另有标签过滤、分页和防重复测试；该分支尚未合入这里 | 本分支跑 T7 的 `--help`，没有 poll；不要把 A 的 submit 当作 Issue 轮询。离线来源 S6 | **独立分支已有实现，本分支未集成；未实连 GitHub** |
| M1-3 只接一个 Agent：Claude | `shell/agents/claude_cli.py:ClaudeCliAgent` 有真实进程适配器；`Executor._start_agent` 默认阻止它；`cmd_run` 只构造 FakeAgent。T4 的 `test_real_agent_is_not_started_in_dry_run`、T5 的 `test_run_never_uses_real_agents_git_or_subprocesses` | A 看输出首行的模拟声明；T4/T5 验证不会启动真实适配器 | **接口与默认阻断已做，真实 Claude 完成任务未验收** |
| M1-4 单 Agent 模式，所有等级由你批准 | `risk.yml:run_mode`、`transition._on_ci_green/_on_your_approval`、`LocalRun`；T3 的 `test_row_09b_single_agent_mode_goes_to_your_review`、T5 的 `test_single_agent_manual_loop` 与 `test_run_never_emits_human_approval_events` | A 必须停在待你审核；错 SHA 拒绝。B 用 D 级检查方案和代码两个关口；多 Agent 只是附加演练 | **本地模拟主路径可验收** |
| M1-5 Claude 没通过诱饵测试就只在前台用，后台顺延 | 本分支无准入开关/可信控制器。task-002 第二轮仍有证据可伪造和裁判可修改问题；task-007 只有方案分析 | 无本页命令能证明隔离有效；先读 S4/S5。T5 的“不启动真实 Agent”只证明演练限制 | **后台不准入；前台操作也不等于已有沙箱** |
| M1-6 实现任务状态流转 | `core/model.py:TaskStatus`、`transition.py:decide`、`shell/local_run.py`；T3 覆盖第七版 #1–#27 和 9 个场景，T5 覆盖跨 CLI 调用 | A–E；状态名、旧→新及原因应与 [第七版](design/task-lifecycle.md)相符 | **内核/演练主体已做；异常恢复、接手、重做 CLI 未齐** |
| M1-7 回执解析 | `shell/receipt.py:parse_receipt`、`Runner.code_event`；T2 的 `test_receipt_missing_required_field_is_invalid`、`test_attempt_must_be_a_positive_integer`，T4 的跨任务回执拒收测试 | T2；A/D 的 show 查看事件绑定的 task_id、attempt、sha | **必填身份字段及 brief 六项能解析；真实模型回执未验收，ask/notice/later 未实现完整交互** |
| M1-8 事件日志（F7：可追问为什么） | `Store.commit/list_events`、SQLite 只追加触发器、`serde`、`cmd_show`；T4 的 `test_database_refuses_to_update_or_delete_events`、`test_commit_is_atomic` | A/D 的 show 看事件顺序、原因和旧审核历史；T4 验证禁止改删和事务回滚 | **本地事件持久化已做；不是完整日志重放/全输入审计** |
| M1-9 每个任务实际消耗的额度 | `QuotaTracker` 只存“未知/还有/用完”，TaskRecord 没有实际 token/额度消费计量。T4 的 `test_quota_survives_restart` 只证明耗尽标记能恢复 | T4；show 中没有实耗数值。没有命令能据此证明真实订阅消费已记录 | **未完成实际计量；未知额度的决策规则已做** |

## 3. ADR-0001 安全不变量逐条对应

依据 [ADR 的裁决原则、底线条目、流程、横切规则和决定](adr/0001-overall-architecture.md)。同一安全约束的不同子项拆开列；学习统计等后续阶段规则也标出边界。代码和测试是证据入口，表里的“部分”不能被 T0 全绿自动改成“通过”。

### 3.1 决策与风险底线

| 不变量 | 实现 / 哪些测试证明 | 可运行验证与证明边界 |
|---|---|---|
| 内核不做 IO、不读时钟、不取随机数、不调用外壳；箭头只传数据 | `core/model.py` 的不可变记录、`decide(task,event,policy,quota,now)`；`tests/test_purity.py:test_core_is_pure`、检查器反例测试 | **T1**。再看 `Runner.handle`：外壳先读数据，再传入 now/快照。AST 检查不能替代控制器权限隔离 |
| 每次按真实改动重算；回执只是自述，不能自己决定改了什么 | `Runner.code_event`、`GitDiffSource.collect`、`compute_level`；T2 的 `test_runner_ignores_the_agent_self_report`、真实 Git diff 测试 | **T2、D、F**。run 使用 FakeDiffSource，`--changes` 是你指定的模拟证据；它不检验真实仓库差异 |
| 基础级别先查底线，再分 A/C；模型最多调整一次 | `core/level.py:base_level/compute_level`；T2 的 `test_bottom_line_checked_before_a_level`、`test_base_level_ignores_suggestion` | **T2**。当前 run 不调用模型分诊，也不会自动生成 B 级建议 |
| 底线不能被模型调松；v1 仅纯文档可降到 B，不能连续降级 | `all_paths_relaxable`、扩展名/路径规范化、`risk.yml`；T2 的 `test_python_file_inside_docs_cannot_downgrade`、`test_absolute_lowest_is_b`、非法路径测试 | **T2、F**。候选配置被谁信任是另一个问题，见下表与 S9；“任务等级只升不降”仍待你决定 |
| core、闸门、risk.yml、提示词、依赖/lock、迁移、密钥路径命中 D | `bottom_line_reasons`、`risk.yml:bottom_line_paths`；T2 的 `test_each_bottom_line_entry_is_d`、`test_core_path_under_src_is_bottom_line` | **T2、B**。**部分**：S9 报告了根目录 migrations、测试配置等边界；修复在其他分支，本页未重验合入 |
| 删除文件是底线；改名时旧、新路径都判断 | `ChangeSet.all_paths`、`GitDiffSource`、等级规则；T2 的 `test_delete_file_is_d`、`test_rename_both_paths_take_part` | **T2**。路径移动的基础行为有证明；移出测试发现范围的特殊情况仍见 S8/S9 |
| 测试断言按文件看减少，别处新增不能抵消 | `AssertionDrop`、`GitDiffSource._assertion_changes`；T2 的 `test_single_file_drop_is_d_even_when_totals_are_flat`、新增文件抵消回归 | **T2**。**部分**：注释/字符串、JS 命名、移出测试路径等红队边界在 S9，不能把近似计数当测试覆盖率证明 |
| 密钥扫描包括文档，命中也为 D | `SecretScanner/NoSecretScan` 接口、`ChangeSet.secret_scan_hit`；T2 的 `test_secret_scan_hit_is_d`、`test_fake_diff_source_reports_unscanned_secrets` | **T2**。**未接真实扫描器**；“未扫描”不等于干净 |
| 同一 Issue 拆多个 PR，要按合计改动分级 | 当前 ChangeSet 是单次改动，没有 Issue/多 PR 聚合层 | 无通过命令；见缺口 K3、S1。单 PR 的 T2 不证明防拆分 |
| 发布、tag、发包、对外发送必须在工具/权限/网络层硬拦截 | 当前 Executor 默认 dry-run；没有已验收的工具白名单、出口控制或不可修改控制器 | **T5**只证明 run 不启动真实适配器/进程；真实硬隔离没有通过命令，见 K5、S4/S5 |

### 3.2 批准、证据与恢复

| 不变量 | 实现 / 哪些测试证明 | 可运行验证与证明边界 |
|---|---|---|
| 当前提交 CI 绿才可合并；人也不能越过 CI，回滚同样如此 | `merge_blocker/_merge`；T3 的 `test_row_12_cannot_merge_after_ci_failure_even_with_new_standard`、`test_row_20_needs_green_ci` | **C、T3**。**部分**：S9 #1 的“绿后再红须撤销证据”是额外缺口；C 只验证先红，不能冒充该修复证明；真实回滚未实现 |
| 单 Agent 所有等级等你；D 级还必须先批方案、最后批代码 | `_on_plan_approved/_on_your_approval`、CLI 提示中的方案 SHA；T5 的 D 级完整流程、`test_plan_hint_uses_plan_sha_instead_of_latest_code` | **A、B、T5**。正常模拟路径可验收；人工/审核中新提交升 D 的空方案、无 SHA 新方案仍见 S8 #2/#3，未宣称全部方案入口已封死 |
| C/D 多家审核来自不同真实提供方，所有编写参与者不得投票；指定审核都要通过 | `eligible_reviewers/_on_review`、`providers_involved`；T3 的同方多会话、席位不足、编写者投票测试 | **D、T3**。本地只验证提供方字段和规则，FakeAgent 的名字不是实际模型身份认证；B 是两家假审核 |
| 任一家不通过就退回，旧结论失效；拒改直接交人，不仲裁 | `_on_review/_on_refused_to_fix`；T3 的 #14/#6，T5 的 `test_multi_agent_failure_then_next_run_passes` | **D、G**。D 重新运行后提交编号变化，当前结论只针对新编号，旧意见在历史中 |
| 用户可明确否决反对意见，但要逐项给理由，绑定完整 SHA 和标准版本；参与的 AI 要记录 | `OpenFinding/finding_key`、`_missing_veto_reasons`、人工提交 providers 累积；T3 的同 SHA 前缀不同意见、逐复合键理由、人工参与者测试 | **G、T3**。G 缺理由必须拒绝；它验证接口完整性，不证明你的理由正确。人工提交没有 CLI 入口，由内核场景测试覆盖 |
| 新 SHA 作废旧 CI、批准、审核/席位；旧版本事件不能覆盖新状态 | `_drop_stale_evidence`、提交入口、`_dispatch` 的版本检查；T3 的审核中新提交和新方案清旧 CI 回归，T4 的数据库并发冲突 | **D、T3、T4**。S8 已指出统一失效处理允许内部显式覆盖；当前已查入口安全不等于未来任意入口都安全。S9 #2 的可变引用/OID 入口约束还需合入修复 |
| 验收/修改次数有上限，换标准按版本计数保留历史；额度未知默认可用、耗尽不应被重启遗忘 | `Thresholds/RevisionCount`、`QuotaTracker`、#7/#11/#15/#16/#22；T3 相应 row 测试、T4 `test_quota_survives_restart` | **C、E、T3、T4**。额度状态不是实际计量；新提交是否清验收失败计数见 K4 |
| 合并已经开始不能取消；其他状态按取消表清理 | `_on_cancel`、动作记录；T3 的 `test_row_27_cannot_cancel_after_merge_started`、T5 的模拟合并需最近 MERGE 为 DONE 测试 | **C/E 的 cancel、T3、T5**。**真实进程终止/关闭 PR 没做**；模拟清理动作 DONE 不证明远端清理成功 |
| 异常恢复必须先核对外部事实，不盲目重做；进程超时要结束，并做启动/唤醒存活检查 | `_on_retry/_on_incident`、ClaudeCliAgent 的超时处理；T4 的假 Agent 失败→异常→重试→再运行；T3 的睡眠场景只喂模拟事件 | **T3/T4**。本分支没有 reconcile、后台存活轮询或唤醒钩子；实际核对/超时/后代进程清理没有通过命令。run 遇到 ERROR/WORKING/YOU_WORKING 会停下 |
| 先持久化决定和待执行动作，再执行外部动作；动作不应因重放重复执行 | `Runner.handle`、`Store.commit/_write_task/_insert_action`；T4 的原子事务、相同版本冲突、`test_replaying_an_identical_decision_does_not_run_the_agent_twice` | **T4**。验证本地事务和动作领取；不等于全日志重放或任意崩溃点恢复 |
| 记录只追加；历史可追问；重放只恢复事实，不重复动作/模型调用 | events 表拒改删触发器、review_history、plan_history；T4 的事件改删拒绝、方案存取回环 | **A/D 的 show、T4**。**部分**：任务/动作/额度表是可更新快照；完整输入、策略版本、模型原话和重放入口未齐，见 K2 |

### 3.3 生效规则、部署和人的权限

| 不变量 | 当前实现 / 证明 | 可运行验证与证明边界 |
|---|---|---|
| 裁判和生效策略归用户控制；候选 PR 不能改自己的裁判、凭据或检查结果 | 当前 `load_config` 从工作树读策略，并无可信控制器部署。task-003 分支改为从 base 运行裁判、head 只当 Git 对象；S3/S9 指出了原攻击路径 | **T7**确认本分支未集成该闸门；没有本页命令证明生产权限边界。仍需 S4/S5 的可信安装和身份分离 |
| Agent 无发布/合并凭据，后台最小权限；关闭 automount/interop；诱饵的读密钥、改生效配置、越白名单均被挡住，同时允许通信可用 | task-002 没有通过可信收证验收；task-007 比较 UID 分离、Windows 控制器、暂停三方案 | 无现场通过命令。T5 的 fake/no-subprocess 测试不证明这些权限。用户决定暂停 task-002，见 K5 |
| GitHub 分支保护、管理员不能绕过、检查必须来自可信上下文；CI 权限最小化 | 本分支 `.github/workflows/ci.yml` 为 `contents: read` 的 check 作业；远端规则未查。task-003/004 分支有额外闸门/检查名单设计 | 可读该 YAML、跑 **T0**；**不能离线证明远端分支保护生效**。risk-level D 级策略见 K6 |
| 不可逆动作定 D、执行前备份；代码一个 PR 一个 squash 提交，可 git revert；main 红时先停、出回滚方案、通知人，回滚也要绿 | 本分支没有真实不可逆执行、备份或自动回滚方案模块；task-004 的 squash 接口仅在其分支 | 无本页通过命令；不执行 revert/发布/写入演练。dry-run 规避了当前动作，不代表备份和回滚机制已经实现 |
| 规则/提示词/模型版本入日志，新规则影子运行；降级追加记录；抽查记录概率、类型，按任务类别/模型版本统计 | Git 有版本历史；当前日志没有保存全部决定输入和生效版本，也无影子策略/抽查统计 | **T4**只能验证现有事件记录，不能证明这些未来字段；见 K2/K10 |
| 学习防污染：先存你的答案再展示 AI；已看过记非独立；总结只能你写；同时最多 3 项；发现率去重、无问题记不适用；只有改规则/提示词才走 D | 学习模块和统计尚未做；show 会直接展示 AI 结论。当前指南的人工顺序只是练习约定 | 按第 7 节先写自己判断；无软件强制验收命令。S2 pi 审核第 4 条提到 show 的顺序折中；此组主要属 M4 |

## 4. 在新临时数据库里亲手跑

全部命令使用 **PowerShell**，在同一窗口依次执行。先确认 uv 与本地依赖已安装；`--offline --no-sync` 缺依赖时会报错，先停下来准备环境，不在这条验收路线中联网安装。

### 准备：只建本轮临时目录

```powershell
Set-Location 'C:\Users\weicai\Desktop\projects\tandem-run'
$lab = Join-Path ([IO.Path]::GetTempPath()) ('tandem-m1-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $lab | Out-Null
$single = Join-Path $lab 'single.sqlite3'
$d = Join-Path $lab 'd.sqlite3'
$red = Join-Path $lab 'red.sqlite3'
$review = Join-Path $lab 'review.sqlite3'
$limit = Join-Path $lab 'limit.sqlite3'
$drop = Join-Path $lab 'drop.sqlite3'
$veto = Join-Path $lab 'veto.sqlite3'
$lab
uv run --offline --no-sync tandem --help
```

临时目录每轮唯一，不会覆盖你的既有数据库。`Read-Host` 是让你手动粘贴刚看到的完整编号或意见键，不是照抄一个固定假编号。可随时用 `$LASTEXITCODE` 查看上条程序的退出码。下面预期返回 1/2 的步骤不应被当成脚本安装失败。

<a id="case-a"></a>
### A. 单 Agent：看清楚再批，错编号无效

```powershell
uv run --offline --no-sync tandem submit --db $single --task-id m1-single --mode single_agent --paths src/x.py
uv run --offline --no-sync tandem run --db $single --changes src/x.py
uv run --offline --no-sync tandem show m1-single --db $single
$sha = Read-Host '粘贴 show 的“提交编号”，完整 40 位'
uv run --offline --no-sync tandem approve --db $single --task-id m1-single --sha ('0' * 40)
uv run --offline --no-sync tandem approve --db $single --task-id m1-single --sha $sha
uv run --offline --no-sync tandem run --db $single --changes src/x.py
uv run --offline --no-sync tandem show m1-single --db $single
uv run --offline --no-sync tandem status --db $single
```

预期：submit=0；第一次 run=**1、待你审核**；错编号 approve=**2**且不改状态；正确批准=0、待合并；第二次 run=0、模拟已合并。show 中看 CI、已批准 SHA、本轮没有 AI 审核、历史事件。不要把 summary 的“CI 绿”当成真实 GitHub CI。

<a id="case-b"></a>
### B. D 级：方案、代码分别绑定编号

```powershell
uv run --offline --no-sync tandem submit --db $d --task-id m1-d --mode multi_agent --paths src/tandem/core/model.py
uv run --offline --no-sync tandem run --db $d --changes src/tandem/core/model.py
uv run --offline --no-sync tandem show m1-d --db $d
$planSha = Read-Host '粘贴 show 的“方案提交编号”'
uv run --offline --no-sync tandem approve --db $d --task-id m1-d --sha ('0' * 40)
uv run --offline --no-sync tandem approve --db $d --task-id m1-d --sha $planSha
uv run --offline --no-sync tandem run --db $d --changes src/tandem/core/model.py --review pass
uv run --offline --no-sync tandem show m1-d --db $d
$codeSha = Read-Host '粘贴这次代码的“提交编号”，不要用方案编号'
uv run --offline --no-sync tandem approve --db $d --task-id m1-d --sha $codeSha
uv run --offline --no-sync tandem run --db $d --changes src/tandem/core/model.py
uv run --offline --no-sync tandem show m1-d --db $d
```

预期：第一次 run=**1、待你批准方案**，有正文和具体 core 路径；错方案编号返回 2。批准方案后再 run=**1、待你审核**，两家假审核均通过，但仍不能越过你。方案编号和代码编号不同，正文仍保留。批准代码后 run=0、模拟已合并。这里没有真的修改 core 文件。

<a id="case-c"></a>
### C. CI 红：即使你愿意，也不能批准

```powershell
uv run --offline --no-sync tandem submit --db $red --task-id m1-red --mode single_agent --paths src/x.py
uv run --offline --no-sync tandem run --db $red --changes src/x.py --until-idle --agent-script ci-red
uv run --offline --no-sync tandem show m1-red --db $red
$redSha = Read-Host '粘贴当前提交编号'
uv run --offline --no-sync tandem approve --db $red --task-id m1-red --sha $redSha
uv run --offline --no-sync tandem cancel --db $red --task-id m1-red
uv run --offline --no-sync tandem show m1-red --db $red
```

预期：run=1，三次验收失败后 R01、待你介入，CI 为“未通过或未知”；approve=**2**并给出不能合并的原因。cancel=0，最后是已取消。此例只验证模拟先红，**不覆盖绿灯之后又变红**。

<a id="case-d"></a>
### D. 审核失败：重新提交，旧结论不能当新通行证

```powershell
uv run --offline --no-sync tandem submit --db $review --task-id m1-review --mode multi_agent --paths src/x.py
uv run --offline --no-sync tandem run --db $review --changes src/x.py --review fail
uv run --offline --no-sync tandem show m1-review --db $review
uv run --offline --no-sync tandem run --db $review --changes src/x.py --review pass
uv run --offline --no-sync tandem show m1-review --db $review
```

预期：第一次 run=1、退回待处理，有待回应意见及完整复合键；第二次=0、模拟已合并。新尝试的 SHA 改变，两条当前通过结论绑定新 SHA，历史仍包含原来的失败结论。这是多 Agent 的 C 级规则演练，所以不需要你批准代码。

<a id="case-e"></a>
### E. 最大轮数：上限到了不能谎称完成

```powershell
uv run --offline --no-sync tandem submit --db $limit --task-id m1-limit --mode multi_agent --paths src/x.py
uv run --offline --no-sync tandem run --db $limit --changes src/x.py --review fail --until-idle --max-rounds 1
uv run --offline --no-sync tandem show m1-limit --db $limit
uv run --offline --no-sync tandem cancel --db $limit --task-id m1-limit
```

预期：run=**2**，显示达到最大轮数；仍待处理，attempt=1，不能循环到“成功”。cancel=0。默认最大轮数为 10。

<a id="case-f"></a>
### F. 模拟证据降级：派活前阻止

```powershell
uv run --offline --no-sync tandem submit --db $drop --task-id m1-drop --mode multi_agent --paths src/tandem/core/model.py
uv run --offline --no-sync tandem run --db $drop --changes src/x.py
uv run --offline --no-sync tandem show m1-drop --db $drop
uv run --offline --no-sync tandem run --db $drop
uv run --offline --no-sync tandem cancel --db $drop --task-id m1-drop
```

预期：第一次 run=1，醒目提示 D→C 被阻止；仍为 D、待处理、attempt=0，没有派活事件。缺少 --changes 的 run=2、参数错误。CLI 有显式 `--allow-level-drop`，本路线不使用；它是模拟层防误操作措施，**不代表你已决定全局采用“等级只升不降”**。

<a id="case-g"></a>
### G. 加练：拒绝修改后，按完整意见键逐项回应

```powershell
uv run --offline --no-sync tandem submit --db $veto --task-id m1-veto --mode multi_agent --paths src/x.py
uv run --offline --no-sync tandem run --db $veto --changes src/x.py --review fail
uv run --offline --no-sync tandem run --db $veto --changes src/x.py --agent-script refuse
uv run --offline --no-sync tandem show m1-veto --db $veto
$vetoSha = Read-Host '粘贴当前提交编号'
$vetoKey = Read-Host '粘贴 open_findings 中完整 key，不是缩写'
uv run --offline --no-sync tandem approve --db $veto --task-id m1-veto --sha $vetoSha
uv run --offline --no-sync tandem approve --db $veto --task-id m1-veto --sha $vetoSha --veto "${vetoKey}=仅验证逐项回应入口"
uv run --offline --no-sync tandem run --db $veto --changes src/x.py
uv run --offline --no-sync tandem show m1-veto --db $veto
```

预期：两次 run 均返回 1，第二次停在待你介入；缺理由 approve=2，带完整键和理由后=0，最后 run=0。默认模拟只有一条反对意见；多条都要分别传 --veto。它只检验接口拒绝遗漏，不会判断理由是否有道理。

## 5. 可复跑的证据测试

<a id="tests"></a>
下面每条均在本次整理中实际执行过，全部离线。选择器只使用本分支存在的文件，不要求切换工作区或 checkout 其他分支。

```powershell
# T0：整套测试（337 passed, 1 skipped）
uv run --offline --no-sync pytest -q -p no:cacheprovider

# T1：内核纯度（3 passed）
uv run --offline --no-sync pytest -q -p no:cacheprovider tests/test_purity.py

# T2：等级、真实临时 Git 采集与回执（85 passed, 1 skipped）
uv run --offline --no-sync pytest -q -p no:cacheprovider tests/core/test_level.py tests/shell/test_diff_source.py tests/shell/test_receipt.py

# T3：转换与场景（121 passed）
uv run --offline --no-sync pytest -q -p no:cacheprovider tests/core/test_transition_rows.py tests/core/test_scenarios.py

# T4：持久化、动作、假 Agent 运行（36 passed）
uv run --offline --no-sync pytest -q -p no:cacheprovider tests/shell/test_store.py tests/shell/test_runner.py

# T5：CLI 的 run/show/approve 和 demo（66 passed）
uv run --offline --no-sync pytest -q -p no:cacheprovider tests/shell/test_cli_run.py tests/shell/test_cli_show.py tests/shell/test_cli_demo.py

# T6：不使用你刚建的库，demo 自己建临时库，预期退出 0
uv run --offline --no-sync tandem demo

# T7：集成清单。这个基线下两个 Test-Path 均为 False，不是“功能测试通过”
uv run --offline --no-sync tandem --help
Test-Path src/tandem/shell/github.py
Test-Path scripts/gate/risk_level.py
```

T2 中的真实 Git 指临时测试仓库的本地提交与 diff，不访问远端。T0–T5 不启动真实 AI。规则修复是否曾在旧实现上失败，要看 S1/S8 的回退验证记录；本页没有重新制作所有历史版本的红绿测试，也不把最终全绿当成开发过程的证明。

## 6. 已知没做、只做一半、待你决定

“在其他分支实现”与“已合入本验收基线”分开记。来源 S1–S9 的定位见第 8 节；PR 编号只有 S3 的审核明确提到了 #3，其他使用分支/任务号和具体审核定位，未联网猜编号。

| 编号 | 缺口 / 决定 | 现在允许据此相信什么 | PR / 审核来源 |
|---|---|---|---|
| K1 | 真实 Agent、真实 CI/审核/合并未在 run 接入；GitHub 写入默认 dry-run，--live 在适配器分支是真写入 | 只能验收模拟编排；不能验收真实无人值守闭环 | task-005 PR 分支 feat/cli-run，S2 pi §五；task-004 PR 分支 feat/github-adapter，S6 K1/K2 及“不用改，但记录” |
| K2 | 完整日志重放未做；决定输入/生效策略版本、额度快照、模型原话未完整存档；不是任意崩溃点都能自动恢复 | 有只追加事件和可更新快照，已有动作幂等测试；不能仅凭数据库重建所有历史裁决 | task-001 PR 分支 feat/m1-runnable，S1 原审第 9 条、修复清单 F11 允许暂缓 |
| K3 | 同 Issue 多 PR 合计风险未做 | 当前只判断一份 ChangeSet，不能据此证明防拆 PR | S1 原审第 5 条后半、修复清单“这一轮不改” |
| K4 | 新提交是否清验收失败计数待你决定 | 目前跨新提交累积；C 中三轮到 R01 是既定行为，不说明清零策略已经拍板 | S1 Claude 原审第 6 条、修复清单“这一轮不改” |
| K5 | task-002 隔离与后台准入暂停；可信控制器尚未实施验收 | 继续离线骨架/前台人工流程；不能批准后台 Agent。task-007 是方案分析，不是已经选择 A/B | 本次用户指示；S4 第二轮结论“需要大改”，N1/N6；S5 task-007 的方案 C/边界分析 |
| K6 | risk-level 的 D 级退出码待你决定；当前闸门分支仍为 3 | 适配器名单 `[check]` 不能改变远端分支保护；若远端仍必需 risk-level 成功，D 仍会被拦 | S3 PR #3 审核 J2；S6 K1 与适配器文档 |
| K7 | 任务等级是否只升不降待你决定 | CLI 已强制显式 changes，默认拒绝模拟降级；内核仍按每次真实改动重算，临时 override 不等于全局政策 | S2 Claude L1/L2、pi 问题 1；当前修复提交 98b3e49 与 README |
| K8 | 方案内容与 SHA 的所有入口尚未补齐 | B 的正常方案、直接 #5b 已能显示；人工/审核中新提交升级 D 的空正文、无 SHA 新方案仍不能算全覆盖 | S2 pi 问题 2/3，2988de3；S8 第四轮问题 2/3，用户已交 pi 后续处理 |
| K9 | 红队安全边界修复尚未合入本基线 | 绿后红撤销、不可变 OID、测试配置保护、迁移路径、断言识别、测试移出等，仍按待整合处理；不要因为当前全绿撤销这些限制 | S9 红队 #1–#10；其中 #8 与 S8 问题 1 相同，用户已交 feat/redteam-fixes 修复。本页未对正在变化的该分支重新验收 |
| K10 | 真实密钥扫描、备份/回滚自动化、影子策略、抽查概率/信任/理解债统计、学习防污染机制未做 | 默认不执行真实动作只能限制本轮演练，不证明这些机制存在 | S0 ADR 的底线、横切规则与学习闭环；S1/F1 明确扫描仅接口；各自属于 task-001/后续阶段的未交付范围 |
| K11 | 实际额度消费计量未做，只有耗尽状态；后台存活巡检/唤醒恢复未接入 | 能测试状态和模拟事故，不能宣称已在机器睡眠后恢复真实进程 | S0 PRD M1 / ADR 任务流转；task-001 PR 当前实现核对，尚无实耗验收记录；S1 原审第 10 条涉及假进程恢复 |
| K12 | 真实 GitHub 接入、风险工作流未合入本分支，远端规则未现场核实 | 当前只有 check 的通用 CI。其他分支的 FakeGitHub/临时 Git 测试是开发证据，不能当作远端上线记录 | S3/S6 的审核、分支文档；T7 本地清单 |
| K13 | 异常恢复、人工接手提交、介入后重做缺 CLI；真实取消失败/合并重发/换 PR 生命周期仍待整合 | run 对这些状态停止；不会假装查询过 GitHub。本基线尚未含后续 77855c0 的合并重发变更 | S2 pi §五，README；S6 文档“当前内核边界”的三项；S8 提到并行后续提交不在其审核范围 |
| K14 | 旧原型 JSON 数据库的全面迁移暂未做 | 本页只用新库；能读当前格式不说明所有历史格式可升级 | S7 第三轮问题 2；31b51d2 提交说明声明无存量、暂不修 |

你需要拍板的是 K4/K6/K7 等政策；K2/K3 等是范围缺口；K5/K9 等是接入真实后台前的安全条件。不要用“这次先接受本地骨架”顺带替这些事项作决定。

## 7. 30 分钟人工审核路线

建议按表计时，只做 A/B/C/D/F 中指定的部分；E/G 和完整 T0 留作加练。先把自己的判断记在纸上或个人笔记里，不要先抄本页审核结论。若已看过相关 AI 报告，标记这次为“对照学习”，不计独立发现率。

| 时间 | 先看文件 / 动作 | 你要具体问自己什么 |
|---|---|---|
| 0–4 分钟 | PRD §7 的 M1 行；ADR“裁决原则”和“决定”；本页第 1 节 | ① 我这次准备接受的是本地模拟，还是想让它真的后台运行？② `run` 打印已合并后，哪一个真实 GitHub 事实仍然没有得到证明？③ 先写出自己最担心的 3 个失控点 |
| 4–9 分钟 | `core/model.py` 的 Event/TaskRecord/Decision；`transition.py:decide/_dispatch/merge_blocker`；`runner.py:handle`。可跑 T1 | ① `now`、diff 和额度是谁读的？为什么不让 decide 自己读？② 决策产生 MERGE 动作，与外壳真的完成合并，是哪两个不同步骤？③ 如果我把 ci_green=True 填错，哪个边界能发现，哪个不能？ |
| 9–15 分钟 | 跑 A；看 `cli.py:cmd_show/cmd_approve`、`local_run.py:_advance`、`executor.py:_start_agent` | ① 错 SHA 是否真的不改任务？② 为什么第一次 run 返回 1 是正确的？③ 这个程序在哪一行保证本轮启动的是 FakeAgent，而不是只靠输出文字声称“模拟”？ |
| 15–21 分钟 | 跑 B 的方案与代码两个关口；再跑 F。看 `risk.yml`、`core/level.py:compute_level`、`local_run.py:_assign` | ① 我批准方案时看的正文、编号在哪里保存？② 两家假审核通过后，D 级为什么还得等我？③ 同一任务改成低风险路径时，提示来自内核政策还是 CLI 防误操作？我是否已经决定“只升不降”？ |
| 21–26 分钟 | 跑 C（或已有红库直接 show/approve），再跑 D。看 `store.py:commit/_write_task/_insert_action` 与事件触发器 | ① 我愿意承担责任也不能越过红 CI，代码具体在哪拒绝？② 两个进程都拿版本 n 写 n+1，谁拒绝后写者？③ 旧审核应删除，还是保留历史但失去当前资格？D 的 show 能否说明差别？ |
| 26–30 分钟 | 对照第 6 节、S2/S8/S9，回看你最初 3 个担心 | ① 哪个担心有实际失败/拒绝证据，哪个只是注释或提示词？② K4/K6/K7 各选什么、代价是什么？没有把握就写待定。③ 我接受哪些范围、明确不接受哪些真实能力？给下一轮留一个能复现的反例，而非“再安全一点” |

可用以下格式亲自留下审核决定，不需要一次接受所有内容：

- 本地骨架：接受 / 退回；我亲手执行的案例及观察：____。
- 真实 Agent、GitHub 写入、WSL 后台：本页无准入证据，保持暂停 / 另开验收；理由：____。
- 验收失败计数是否清零：____；risk-level 的 D 退出码如何表达人工关口：____；任务等级是否只升不降：____。
- 我独立发现的问题：____；已看过 AI 意见的部分：____。
- 下一项必须补的测试或边界实验：输入____、预期____、现在的证据____。

## 8. PR / 审核证据索引（离线定位）

本页没有查询 GitHub PR 状态。分支名称不是 PR 编号；当前没有本地证据的编号不补写。跨分支文件通过 **本地 Git 对象**读取，无需切换分支或联网；下面列出固定提交，避免以后分支移动后找不到本次依据。

| 来源 | 具体位置 / 当时对应 PR 分支 |
|---|---|
| S0 需求与决策 | [PRD](PRD.md) §5 F3/F4/F7、§7 M1；[ADR-0001](adr/0001-overall-architecture.md) 裁决原则、流程、横切规则、决定 |
| S1 task-001 原审与允许暂缓项 | [Codex 原审](tasks/reviews/task-001-codex.md) #5/#9/#10；[Claude 原审](tasks/reviews/task-001-claude.md) #6；[修复清单](tasks/task-001-fixes.md) F1/F11、“这一轮不改”。PR 分支 feat/m1-runnable |
| S2 task-005 两家审核及修复 | [Claude](tasks/reviews/task-005-claude.md) L1/L2；[pi](tasks/reviews/task-005-pi.md) 问题 1–5、§五。PR 分支 feat/cli-run；修复 98b3e49/4bad77f/641519e、合并 5e8cfb8；[README](../README.md) 是当前流程说明 |
| S3 task-003 风险闸门 | `git show 15b1d69:docs/tasks/reviews/task-003-claude.md` 的 J1/J2 及第二轮；`git show 15b1d69:docs/risk-gate-pr.md`。审核明确提到 PR #3；分支 feat/risk-gate。草稿里“未创建远程 PR”是较早的开发记录，不能据此覆盖后续审核提到的 PR |
| S4 task-002 隔离第二轮 | `git show 06f7c18:docs/tasks/reviews/task-002-codex-r2.md`，重点 N1/N6 和“不准入”的边界。PR 分支 feat/wsl-isolation；暂停来自本次用户指示 |
| S5 task-007 可信控制器 | `git show 6533498:docs/design/trusted-controller-options.md`，§2 信任边界、§5 暂停、§7 最小实验；同提交的 `docs/tasks/trusted-controller.md` 说明 task-002 后续。分支 docs/trusted-controller；它是文档分析，没有安全验收结论 |
| S6 task-004 GitHub 适配器 | `git show e7b3d4d:docs/tasks/reviews/task-004-claude.md` 的 K1–K5 和“不用改，但记录”；`git show e7b3d4d:docs/github-adapter.md` 的 M1/live、必需检查、内核边界。PR 分支 feat/github-adapter，K1/K2 修复为 dc93e86，文档修复 a3eb890；这些未合入本验收基线 |
| S7 task-001 第三轮 | [第三轮报告](tasks/reviews/task-001-codex-r3.md)；`git show 31b51d2` 的完整键修复及旧格式暂缓说明。PR 分支 feat/m1-runnable |
| S8 task-001 第四轮 | `git show c45aca8:docs/tasks/reviews/task-001-codex-r4.md`，问题 1–3及内存回退表；审核固定到 2988de3。PR 分支 feat/m1-runnable；本次用户已将 #2/#3 交 pi、#1 合并到红队 #8 跟进 |
| S9 task-001 红队 | `git show c92869e:docs/tasks/reviews/task-001-codex-redteam.md`，#1–#10；修复分支 feat/redteam-fixes 在继续工作，本页不把其工作中状态当作已合入或已验收 |

本页结论留给你填写：**可以接受本地骨架的哪些行为，哪些真实能力仍须补证据后再接受。**
