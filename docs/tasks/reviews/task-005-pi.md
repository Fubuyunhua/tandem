# task-005 独立审核 · pi（DeepSeek）

- 审核对象：`feat/cli-run`，范围 `39cd14f..8347525`（`git diff 39cd14f..8347525`）
- 依据：`docs/tasks/cli-run.md`、`docs/design/task-lifecycle.md` 第七版、ADR-0001、`docs/tasks/m1-runnable.md`
- 方法：只读。未修改任何实现或测试文件，只新增本文件。写本报告前没有读 `docs/tasks/reviews/task-005-claude.md`。
- 环境：`uv run pytest -q` = **289 passed, 1 skipped**；`uv run pyright` = **0 errors**；`uv run ruff check` 通过。所有手工复现都用 `C:/Users/weicai/AppData/Local/Temp/rv/*.sqlite3` 上的临时数据库，离线运行，未调用真实 AI、未联网、未推送。
- 结论：**修改后可以**。`run` 的主体设计是对的（每一轮只产生假证据，裁决全部交给内核，人工关口不自动跨越），但存在一处**等级下降后自动合并**的漏洞（中），另有 3 处信息展示与提示的缺陷（低）。这些不推翻结构，但建议在交给你人工审核前修掉第 1 条。

## 一、交付物核对

| 任务书 | 实现 | 判断 |
|---|---|---|
| 1. `run` 一轮派活 / 假回执 / 假改动 / 假 CI / 假审核，逐步打印"旧 → 新（原因）"，停在人工状态并提示命令 | `src/tandem/shell/local_run.py:94`（`_advance`）、`:149`（`_hint`）；`src/tandem/shell/cli.py:204`（`cmd_run`） | 基本符合；见问题 1、2、5 |
| 2. `run --until-idle` 反复执行，有最大轮数 | `local_run.py:179`；`--max-rounds` 默认 10，非正整数在 argparse 阶段拒绝（`cli.py:492`、`tests/shell/test_cli_run.py:166`） | 符合 |
| 3. `show <任务编号>` 显示状态、等级、提交编号、审核意见、待回应意见（复合键）、历史事件 | `cli.py:142` | 符合；见问题 3、4 |
| 4. README 手动示例（单 Agent / 多 Agent 各一） | `README.md` 新增「手动走一遍本地模拟」 | 符合，且把 `--changes` 的坑写在文档里了（但运行时没有拦截，见问题 1） |
| 5. 五个测试场景 | `tests/shell/test_cli_run.py`、`tests/shell/test_cli_show.py` | 五项都有对应测试；覆盖缺口见第四节 |

`src/tandem/core/`、`docs/adr/`、`docs/design/`、`docs/PRD.md`、`tests/test_purity.py` 未被修改（`git diff --name-only 39cd14f..8347525` 已核对）。

## 二、问题清单

### 1. 【中】`--changes` 让等级下降后，`run` 会**绕过人工关口自动合并**

- **位置**：`src/tandem/shell/cli.py:489`（`--changes` 默认 `src/x.py`，且允许空串）、`cli.py:204`（`cmd_run` 把它当本轮所有任务的改动）、`src/tandem/shell/local_run.py:94`（`_advance` 只管状态，不比对等级）、`:139`（模拟合并只要求 `approved_sha == latest_sha` 且 `ci_green`）
- **为什么重要**：等级是内核在每次交回代码时按真实改动重算的（ADR 要求，内核没错）。但 `run` 的"真实改动"来自一个全局参数，一旦这个参数比 `submit --paths` 弱，任务就会**降级**，而 `run` 不拦截、只在小字里打印"按真实改动算出来是 X 级"，随后按低等级自动走完审核和合并。你手工审核"第一个版本"时，这正是最不能自动通过的地方。
- **复现 A（D 级任务被你批过方案，忘记带 `--changes` 就自动合并）**：
  ```
  uv run tandem submit --db X --task-id t1 --mode multi_agent --paths src/tandem/core/model.py
  uv run tandem run    --db X --until-idle --changes src/tandem/core/model.py   # 停在“待你批准方案”
  uv run tandem approve --db X --task-id t1 --sha <方案 SHA>                     # → 待处理
  uv run tandem run    --db X --until-idle                                     # 忘了 --changes，用默认 src/x.py
  ```
  实测输出：`处理中 → 待验收（…按真实改动算出来是 C 级）` → `待验收 → 待AI审核` → `待AI审核 → 待合并` → `待合并 → 已合并`。任务记录 `level` 变成 `C`，`approved_sha` 由内核写入，**全程没有你批准代码**。
- **复现 B（空 `--changes` 直接变成 A 级，连 AI 审核都没有）**：
  ```
  uv run tandem submit --db Y --task-id t1 --mode multi_agent --paths src/x.py
  uv run tandem run    --db Y --changes ""
  ```
  实测：`处理中 → 待验收（…算出来是 A 级）` → `待验收 → 待合并（CI 绿，A 级不需要 AI 审核）` → `已合并`，一轮结束。
- **建议**（任选其一，越小越好）：
  1. `--changes` 去掉默认值改成必填，`--changes ""` 直接报错（避免"忘记参数"走进自动合并）；
  2. 在 `_advance` / `_receipt` 里比对新等级与 `task.level`：新等级**更低**时打印醒目警告并拒绝继续（要降级必须显式加 `--allow-level-drop`），理由写清"模拟证据不能证明这次真的只改了低风险文件"；
  3. A/B 级（跳过 AI 审核或跳过你的批准）在 `run` 里默认也停在"待合并"等人按一下，加 `--allow-auto-merge` 才自动合并。
- **说明**：README 已写明"`submit --paths` 只是初始分级输入，后续 run 不会记住它，请每次提供一致的 `--changes`"。文档是诚实的，但**运行时没有任何拦截或警告**，后果又是自动合并，所以我按"中"记；如果只保留文档、不加拦截，请至少在输出里明确写"本次等级比你提交时低，这是模拟证据决定的"。

### 2. 【中】第 5b 条（C 级升 D）进"待你批准方案"时**没有方案内容**，`run` 仍提示你去 `approve`

- **位置**：`src/tandem/core/transition.py:415-432`（5b 分支只把 `plan_version` 加一，不写方案正文；属于内核，task-005 不能改）、`src/tandem/shell/local_run.py:149`（`_hint` 无条件给出 `approve` 命令）
- **复现**：
  ```
  uv run tandem submit --db Z --task-id t1 --mode single_agent --paths src/x.py      # C 级
  uv run tandem run    --db Z --changes src/tandem/core/model.py                     # 实际改了 core
  ```
  实测：`处理中 → 待你批准方案（按真实改动重新算出来是 D 级，方案还没批准）`，此时 `show` 里 `"note": ""`、`"plan_version": 1`、`"approved_plan_version": null`，记录里**没有任何方案正文**；`run` 仍旧打印 `approve --task-id 't1' --sha <代码 SHA>`。照命令执行后 `approved_plan_version == plan_version == 1`，D 级的方案关口就此消失，而你在"批准"一个不存在的方案。
- **建议**：内核在 5b 时应把这次提交记为"本版方案"（或标记"本版方案只有代码、没有文字方案"）；`run` 在 `approved_plan_version != plan_version` 且没有 `PLAN_SUBMITTED` 文本时，提示"本关缺少方案内容，请先让写手交方案"，不要直接给 `approve` 命令。这一条需要内核配合，写手改不了，建议进 PR 的"需要内核配合"清单。

### 3. 【低】方案正文会被 `note` 覆盖，`show` 事后答不出"我批的是哪版方案"

- **位置**：`src/tandem/core/model.py:303-304`（`TaskRecord` 只有 `plan_version`/`approved_plan_version`，没有方案正文）、`src/tandem/shell/cli.py:142`（`cmd_show`）
- **复现**：D 级流程走到"待你批准方案"时 `show` 里 `note` 是方案正文；`approve` 后再 `run` 交代码，`note` 变成 `"这次没有 AI 审核"`，方案正文在任务快照里消失。**历史事件里还在**（`PLAN_SUBMITTED` 事件的 `plan` 字段，`show` 会打印全部事件），所以数据没丢，只是没被摘出来。
- **建议**：`show` 增加一段"方案历史"（从 `PLAN_SUBMITTED` 事件里读 `plan` + 对应 `sha` + 是否被批准），或内核给任务记录加一个 `plan_text`。后者更彻底，但那是内核改动。

### 4. 【低】`show` 的头部摘要太薄，批准前必须自己在 JSON 里翻

- **位置**：`cli.py:150-152`（只打印状态、等级、提交编号，其余全是 JSON）
- **说明**：批准前最需要一眼确认的是"这条提交的 CI 是否绿、我批准的绑定在哪个 SHA、这次审核是谁出的结论、有没有还没回应的意见"。这些字段在 JSON 里都有（`ci_green`、`approved_sha`、`reviews`、`open_findings`），但 `show` 没有摘要行，且 `note`/`reason` 改成人类可读的一句话都没有。我实测 `show` 对一条 `AWAITING_PLAN_APPROVAL` 的任务只给出 `"plan_version": 1` 而不告诉你"方案还没批"，需要自己读 JSON。
- **建议**：头部加 4~5 行摘要：`CI：绿/红/未知`、`批准的提交：…（与当前一致/不一致/无）`、`本轮审核：codex 通过 / opencode-go 待回应`、`待回应意见：2 条（键已列在下方）`、`方案：第 1 版已批准/待批准`。
- **另外**：`show` 直接把 AI 审核结论全部摊开，没有提示"先写你自己的看法"，和 PRD F5/学习模块的"先保存你的答案再展示 AI 意见"相悖。M1 人工批准场景下这是必要的折中，但值得在 `show` 开头加一句提醒。

### 5. 【低】卡在非人工状态时，`run` 只说一句就"已空闲"，退出码 0

- **位置**：`local_run.py:149`（`_hint` 只覆盖 PENDING / 待你批准方案 / 待你审核 / 待你介入 / 处理中 / 异常 / 你处理中，没有覆盖待验收、待AI审核、待合并）、`local_run.py:190-196`（`changed` 为 False 就打印"已空闲"并返回 0）
- **复现**（构造一条 `approved_sha != latest_sha` 的待合并任务，模拟"合并结果还没核对"）：
  ```
  uv run tandem run --db <该库> --until-idle
  ```
  实测输出：`t1：缺少当前 SHA 的 CI 或批准证据，不能模拟合并。` → `下一步：show` → `如需取消：cancel` → `已空闲：没有任务能继续自动推进。`，退出码 **0**。任务其实卡在"待合并"，需要外部核对合并结果才算完，但脚本和人都看不出该做什么。
- **建议**：`_hint` 给待合并/待验收/待AI审核补一句下一步（"等 CI" / "等审核" / "去 GitHub 核对合并结果后手工补事件"），并在"已空闲"时区分"全部完成"与"卡住等人"，后者返回非 0（或至少打印"有 N 个任务停在需要人处理的状态"）。

### 6. 【低，接真实执行器前必须改】模拟合并只看任务记录，不看 `MERGE` 动作的实际结果

- **位置**：`local_run.py:130-145`（`AWAITING_MERGE` 分支）
- **说明**：只要 `approved_sha == latest_sha and ci_green` 就发 `MERGED`，没有核对 `task.actions` 里 `MERGE` 动作的状态（`DONE` / `UNKNOWN`），也没有用 `store.unconfirmed_actions()`。当前 `cmd_run` 固定 `dry_run=True`，执行器把动作记成"已完成（模拟）"，所以不可达；但等 M2 接真实合并，这段代码会变成"没核对就宣布合并成功"，正好违反 ADR「完成与否只看外部证据」。
- **建议**：现在就加一个前置条件——`MERGE` 动作必须存在且状态为 `DONE`，否则打印"合并结果未确认，请先去核对"并停在待合并。这样将来换真实执行器时这条路径自然是对的。

### 7. 【低，可移植性】提示语写死 PowerShell 单引号转义

- **位置**：`local_run.py:23`（`_quote`）
- **说明**：`--db`/`--sha`/`--veto` 的提示按 PowerShell 规则用单引号转义。README 说明示例在 PowerShell 里跑，所以自洽；但如果哪天在 bash/WSL 里跑，提示里的单引号会被原样带进参数。建议按 `sys.platform`/shell 选择引号，或提示里只给参数值、不给整条命令。

## 三、没问题的地方（我专门验证过）

- **人工关口不会自动跨越**：`run` 从不发送 `PLAN_APPROVED`、`YOUR_APPROVAL`、`INTERVENTION_APPROVED`。实测单 Agent + 多 Agent 混在一个库里跑 `--until-idle`，事件日志是：
  - `human`（单 Agent）：`CREATED, ASSIGN, CODE_SUBMITTED, CI_GREEN` → 停在待你审核；
  - `auto`（多 Agent C 级）：`CREATED, ASSIGN, CODE_SUBMITTED, CI_GREEN, REVIEW, REVIEW, MERGED`。
  C 级多 Agent 自动合并是第七版第 12 条的本意（C 级不需要你批准），不是越权。
- **停在人工状态后不再推进**：`test_d_level_waits_for_plan_and_then_for_code_approval` 断言再次 `--until-idle` 后记录完全不变，我手工复核也一致。
- **`--until-idle` 的终止条件**：`changed` 用状态版本号判断，`--review fail` 有 R02 上限、`--agent-script ci-red` 有 R01 上限，两条都会收敛到"待你介入"；无进展（额度耗尽导致派活被拒）也算空闲；`--max-rounds` 是硬上限，超限返回 2。我按 R01、R02、无进展、终点重复运行四种情况都跑过，都不会死循环。
- **只用假证据**：`test_run_never_uses_real_agents_git_or_subprocesses` 把 `ClaudeCliAgent.run`、`GitDiffSource.collect`、`subprocess.run` 全部替换成"调用即失败"，整条流程仍能跑通，这条测试是有效的（不是只断言没报错）。
- **`show` 不泄露**：只读本任务，不打印别的任务；`show` 打不开数据库时返回 1 且**不会创建**空库（`test_show_missing_database_does_not_create_it`）。
- **`submit --mode` 保存在任务记录里**，不改 `risk.yml`；多 Agent 与单 Agent 任务能在同一个库里共存并各自按自己的模式推进（实测如上）。

## 四、测试是否覆盖任务书第 5 条

| 第 5 条要求 | 对应测试 | 我的判断 |
|---|---|---|
| 单 Agent：`submit → run → approve → run` 到已合并 | `test_single_agent_manual_loop`（另外断言终点重复 `run` 不追加事件） | 覆盖充分 |
| 多 Agent：审核不通过 → 退回 → 重新运行 | `test_multi_agent_failure_then_next_run_passes`（断言 attempt、open_findings、新 SHA、新结论绑定新 SHA、`review_history` 三条） | 覆盖充分 |
| D 级停在"待你批准方案" | `test_d_level_waits_for_plan_and_then_for_code_approval`、`test_real_changes_can_upgrade_c_to_d` | 覆盖，但只断言状态/等级，没有断言"此时方案内容是空的"（问题 2） |
| `--until-idle` 不会死循环 | `test_until_idle_stops_at_intervention[ci-red/R01, fail/R02]`、`test_max_rounds_reports_unfinished_loop`、`test_no_progress_is_idle_even_when_pending` | 覆盖充分（有硬上限 + 收敛 + 无进展三种） |
| `show` 输出包含提交编号和待回应意见 | `test_show_displays_full_sha_findings_and_history`、`test_refusal_after_failed_review_keeps_findings` | 覆盖，断言了完整 SHA、复合键、findings 正文、事件顺序 |

**覆盖缺口（建议补，都属"补强"而非"漏测交付物"）**：

1. **没有等级下降的回归测试**：`--changes` 比 `submit --paths` 低（尤其空串）时，`run` 会把 D/C 级任务自动合并。这一轮最该补的一条测试。
2. **没有"绝不发批准事件"的负例**：现在的测试靠断言终态间接覆盖。如果有人给 `run` 加一个"自动批准"开关，`test_until_idle_stops_at_intervention` 之类未必失败。建议加一条：任意流程跑完后，事件日志里不出现 `PLAN_APPROVED` / `YOUR_APPROVAL` / `INTERVENTION_APPROVED`。
3. **没有 5b（C→D 重新分级）进入方案审批后的行为测试**：`test_real_changes_can_upgrade_c_to_d` 只到状态为止，没有断言"此时没有方案内容、提示是否合理"（问题 2）。
4. **`run` 在数据库不存在时会静默创建空库并返回 0**（`show` 则返回 1 且不建库），没有测试也没有文档说明。要让 `run` 的行为和 `show` 一致（或者明确写进 README），建议补一条。
5. **`--until-idle` 的"卡住"与"完成"没有区分**：两者都打印"已空闲"、都返回 0（问题 5），没有测试。

## 五、需要内核配合 / 本轮未做（不算缺陷，但要在 PR 里写明）

1. **方案正文没有落在任务记录里**（问题 2、3）：`TaskRecord` 只有 `plan_version`，5b 分支不写方案；`run` 和 `show` 都受影响。
2. 异常恢复、人工接手提交代码（第 23、24 条）、介入后换 Agent 重做（第 21 条）这一轮没有 CLI 入口，`run` 遇到这些状态只提示人工处理（README 已声明）。
3. 真实合并、真实 CI、真实审核仍是 dry-run；`run` 的"已合并"只是本地记录，这一点在输出首行、每条事件原因和 README 里都有标明。

## 六、我实际执行过的复核命令（可复现）

```powershell
# 单 Agent 正常流程
uv run tandem submit --db D --task-id t1 --mode single_agent --paths src/x.py
uv run tandem run --db D            # 停在待你审核，提示 show / approve --sha
uv run tandem approve --db D --task-id t1 --sha <SHA>
uv run tandem run --db D            # 到已合并

# D 级方案关口
uv run tandem submit --db D2 --task-id t1 --mode multi_agent --paths src/tandem/core/model.py
uv run tandem run --db D2 --until-idle --changes src/tandem/core/model.py   # 停在待你批准方案

# 问题 1 复现：方案批准后忘记 --changes → C 级自动合并
uv run tandem approve --db D2 --task-id t1 --sha <方案 SHA>
uv run tandem run --db D2 --until-idle      # 待验收(C) → 待AI审核 → 待合并 → 已合并

# 问题 1 复现 B：空 --changes → A 级一轮合并
uv run tandem submit --db D3 --task-id t1 --mode multi_agent --paths src/x.py
uv run tandem run --db D3 --changes ""

# 问题 2 复现：C 级实际改 core → 待你批准方案，方案为空
uv run tandem submit --db D4 --task-id t1 --mode single_agent --paths src/x.py
uv run tandem run --db D4 --changes src/tandem/core/model.py
uv run tandem show t1 --db D4 | Select-String '"(note|plan_version|approved_plan_version)"'
```

## 结论

**修改后可以。** 结构、dry-run 边界、人工关口的处理都成立，测试对第 5 条的五个场景是真覆盖（尤其 `--until-idle` 的三条收敛路径和"绝不碰真实进程"那条）。需要先修的是**问题 1**（等级下降后自动合并，缺运行时拦截）；问题 2 是内核缺口，`run` 至少不该在方案为空时直接提示 `approve`；问题 3、4、5 属于展示与提示的完善。补上问题 1 的回归测试后，我认为可以交给你人工审核。
