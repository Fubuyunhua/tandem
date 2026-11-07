# M1 分支集成演练记录

本次只在本地集成，分支为 `integ/m1-all`，工作目录为
`C:\Users\weicai\Desktop\projects\tandem-integ`。未联网、未 fetch、未推送，
未运行真实 Agent、gh、GitHub 工作流或 WSL 配置。结论是：**这三个分支的本地集成和模拟路线可运行**，
不能据此认定真实 GitHub 闭环、后台隔离或整个 PRD M1 已验收。

## 1. 固定输入与分支选择

用 `git worktree add -b integ/m1-all ... origin/feat/m1-runnable` 创建全新 worktree，
然后逐个 `git merge --no-commit --no-ff`，完成该轮检查和路线后才提交 merge commit。
没有改动已有的各功能 worktree，没有 rebase。

| 角色 / 顺序 | 使用的引用 | 固定提交 | 选择依据 |
|---|---|---|---|
| 起点 | origin/feat/m1-runnable | c977500 | 本地、远端跟踪引用一致；含截至 16815b3 的实现和 R5 报告 |
| 第一次合并 | feat/risk-gate，本地引用 | c8966cd | origin/feat/risk-gate 为 cfb2fc5，本地是其后代且领先两提交，按用户允许的规则使用更新的同名本地分支 |
| 第二次合并 | origin/feat/github-adapter | 8115b27 | 与同名本地分支一致 |
| 第三次合并 | origin/feat/cli-run | dab9e1a | 与同名本地分支一致；验收指南来自此提交 |
| 收尾追加追平 | feat/risk-gate 的新提交 | 9f56a64 | 演练期间本地分支继续前进；仅文档和 4 个回归用例，追加一轮完整验证 |

risk-gate 领先的两项修复为 `6e2aed8`（改名解释、扫描结果透传）和
`c8966cd`（通过 PR 引用获取 fork 对象、固定依赖 Action）。这里只核对本地对象与测试，
没有执行远端工作流来认证这些部署行为。

初版报告 `e8367e5` 完成后，检查到 risk-gate 又新增 `9f56a64`，因此在原定三轮之后
追加追平合并，不把并行新增内容误算进先前结果。最终风险分支输入固定为 `9f56a64`。

明确没有合入 PR #7 的 `feat/state-invariants@338cf6d` 或 PR #8 的
`feat/redteam-fixes@1579fa1`；最后也用祖先关系检查确认这两个分支头不在集成结果中。
共享的 m1 基线不等于合入了它们尚在修改的分支。
收尾时 PR #8 的本地头已到 `db9ac9e`；仍未合入，不能据其新增审核文档声称修复已集成。

## 2. 每轮合并、冲突与检查结果

| 轮次 | merge commit | 文本冲突及处理 | ruff check / format | pyright | pytest | demo |
|---|---|---|---|---|---|---|
| risk-gate | 475a5ec | 无文本冲突；首次 format 检查暴露 R5 文档代码块排版问题，修正后重跑 | 均通过 | 0 errors | 354 passed，1 skipped | 退出 0 |
| GitHub adapter | 654479a | 无文本冲突，自动合并 | 均通过 | 0 errors | 464 passed，1 skipped | 退出 0 |
| CLI run | 55fbb6f | cli.py 两个冲突块，组合双方导入和子命令；见下节 | 均通过 | 0 errors | 514 passed，1 skipped | 退出 0 |
| risk-gate 追平 | c2b61c8 | 无文本冲突；合入新增属性/base 策略来源的文档与测试，不改运行时代码 | 均通过 | 0 errors | 518 passed，1 skipped | 退出 0 |

每轮完整执行的检查为：

```powershell
$env:UV_OFFLINE = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
uv run ruff check --no-cache
uv run ruff format --check --no-cache
uv run pyright
uv run python -B -m pytest -q -p no:cacheprovider
uv run --no-sync tandem demo
```

新 worktree 的虚拟环境仅从本地缓存安装依赖。ruff 版本为 0.17.4。
每轮的一个 skip 都是既有的 Windows 特殊文件名测试；不是本次新增跳过。

### 2.1 第一次检查失败：复核文档的 Python 代码块

`docs/tasks/reviews/task-001-codex-r5.md` 的 Python 代码块没有满足格式器要求，
导致第一次 `ruff format --check` 返回 1，检查链因此未继续到 pyright/pytest。
这是基线文档在首次完整集成检查中暴露的问题，不是风险规则测试失败。

只对该文件执行 `ruff format`：拆分导入、调整函数调用的换行。
没有修改复核结论、反例、被审实现或测试。随后整轮四项检查通过，修改随 `475a5ec` 保存。
原 `code_auto` worktree 和它的 R5 文档提交没有被改写。

### 2.2 GitHub adapter 与 CLI run 的两个冲突块

唯一发生 Git 文本冲突的文件为 `src/tandem/shell/cli.py`：

1. **导入区**：GitHub 分支新增 GhGitHub、GitHubError、GitHubEvents；CLI 分支新增 LocalRun。
   保留全部导入，由 ruff 整理分组，没有整文件选择 ours/theirs。
2. **build_parser 子命令区**：GitHub 分支增加 poll/reconcile，CLI 分支增加 run/show。
   将两套注册合并，保留 run 的必填非空 `--changes`、轮数和模拟参数，以及 GitHub 的
   `--repo`、显式 `--live` 和绑定参数。

自动合并的部分也逐项复核：

- COMMANDS 同时包含 poll/reconcile/run/show；submit 的 `--mode` 仍在。
- GitHub 的 `_connect_github`、安全失败消息、重发后的真实状态展示，以及
  `_print_decision` 对 UNKNOWN GitHub 动作返回失败的逻辑仍保留。
- status 的 Issue 标题单行截断仍在；run/show 的模拟行为与完整记录展示仍在。
- README 自动合并，GitHub 适配器入口和本地模拟说明都保留。
- 没有另外修改内核来凑通过，也没有带入 #7/#8 的实现。

合并后整套 GitHub 离线测试与 CLI-run 测试一起执行，并完成下述 47 条验收调用。

## 3. 人工验收路线的执行方法

以 `docs/m1-acceptance.md` 的准备块和第 4 节 A–G 为路线。
在前两轮该文件尚未合入，读取的是已存在的本地对象
`origin/feat/cli-run@dab9e1a:docs/m1-acceptance.md`；没有提前把 CLI 实现放入工作树。
最后一轮使用合入后的文件。

A–G 合计 **46 条 CLI 命令**，加准备阶段的 `tandem --help` 为指南所说的 **47 条**。
额外的 `run --help`、`show --help` 是命令能力探测，不计入 47 条；demo 也单列。

本次由 Codex 代执行命令，不代替用户的独立判断或审核批准。执行方式如下：

- 为每轮创建唯一临时目录，为 A–G 分配独立 SQLite 路径，不使用项目默认库或既有库。
- 调用当前 worktree 的已安装 CLI，使用参数列表；不传 `--live`，不调用 poll/reconcile。
- `Read-Host` 的代填值只取自本轮实际 show 输出的 JSON：完整代码 SHA、当前版方案 SHA、
  open_findings 的完整 key。没有预填固定模拟 SHA 冒充用户刚看到的证据。
- 每条命令核对指南预期退出码；对关键步骤还核对临时库的状态、CI/失败次数、方案/代码
  编号区别、当前与历史审核绑定等。读取快照只用于验证，不用于绕过 show 取得批准输入。
- 若 submit 因缺少接口失败，该案例后续依赖步骤记录为 blocked，不制造任务或编号继续批准。
- 1/2 本来就是很多拒绝、等待和轮数上限步骤的预期返回，按预期比较，不一概算失败。

第 7 节的独立思考题和用户最终接受哪些能力，留给用户亲自完成；不把代跑 CLI 当作
“用户已完成独立审查”。完整 pytest 覆盖指南 T1–T5 的已集成测试文件；没有引用旧指南的
历史子集测试数冒充本次测量。

## 4. 每轮路线的失败、阻断和最终结果

### 4.1 前两轮：依赖尚未齐全，不能完成 A–G

| 轮次 | 准备 --help | A–G 实际失败 | 后续阻断 | 原因 |
|---|---|---|---|---|
| risk-gate 后 | 退出 0 | 七个案例的 submit 均退出 2，预期 0 | 39 步 | argparse 不识别 `--mode`；run/show 帮助均退出 2 |
| GitHub adapter 后 | 退出 0 | 同上 | 39 步 | 新增 poll/reconcile 不等于新增 run/show/--mode；CLI-run 还未合入 |

失败入口分布：A/B/C/D/E/F/G 各第 1 步。被阻断的步骤数量分别为
7/9/5/4/3/4/7。没有把这些步骤记成通过，也没有把它们归咎于核心转换错误。
这是按指定分支顺序集成时可以预期、但确实存在的功能依赖失败。

### 4.2 第三轮及追平轮：分别 47/47 符合预期，无阻断

下表的退出码序列是两轮各自复跑的实际输出，顺序与指南每个案例的命令一致；
追平轮使用新的临时库，不复用第三轮的终点任务来冒充再次通过：

| 案例 | 条数 | 实际退出码 | 关键验证 |
|---|---|---|---|
| A 单 Agent | 8 | 0,1,0,2,0,0,0,0 | 停待你审核；错 SHA 拒绝；正确批准后模拟已合并 |
| B D 级 | 10 | 0,1,0,2,0,1,0,0,0,0 | 先方案批准再代码批准；两家模拟审核；方案与代码 SHA 不同且正文保留 |
| C CI 红 | 6 | 0,1,0,2,0,0 | 失败次数 3、R01、CI 非绿；人工批准拒绝；取消后终点 |
| D 审核失败后新提交 | 5 | 0,1,0,0,0 | 新 SHA 改变；历史保留 FAIL；两条当前 PASS 绑定新 SHA |
| E 最大轮数 | 4 | 0,2,0,0 | 上限返回 2，任务仍待处理；没有循环冒充完成 |
| F 模拟降级 | 5 | 0,1,0,2,0 | D→C 默认阻止，attempt=0；缺 changes 拒绝；取消成功 |
| G 拒改与逐项理由 | 8 | 0,1,1,0,2,0,0,0 | 拒改后待介入；缺理由拒绝；完整意见键和理由后放行模拟合并 |
| 准备 --help | 1 | 0 | 命令可加载 |

额外的 run/show 帮助均退出 0，demo 退出 0。
T7 所关注的两个入口在最后一轮均已存在：`src/tandem/shell/github.py` 和
`scripts/gate/risk_level.py`。它们不再符合指南旧基线“两个 Test-Path 为 False”的历史状态，
这是集成后的能力变化，不是入口存在性测试失败。

### 4.3 本机临时证据位置

每个目录内的 `results.json` 保留命令参数、退出码、stdout/stderr、验证项和阻断原因；
最终轮还保留七个本轮 SQLite 库。它们不提交到 Git，也不保证跨机器或长期存在。

- `%TEMP%\tandem-integ-risk-gate-sacxe37s\results.json`
- `%TEMP%\tandem-integ-github-adapter-arnthm5h\results.json`
- `%TEMP%\tandem-integ-cli-run-l_q_z1lq\results.json`
- `%TEMP%\tandem-integ-risk-gate-refresh-n8qem_0c\results.json`

这些材料只含本地模拟任务；没有生产数据库、真实 Issue 正文或凭据。

## 5. 仍不能据此宣布通过的事项

- 本地假 CI、假审核和“已合并”不是 GitHub 上的事实；没有实连 GitHub，也没有跑风险工作流。
- `docs/m1-acceptance.md` 明确冻结在较早的 CLI 基线，K8/K12/K13 等跨分支结论具有时效性。
  本记录以实际合入的引用和上述结果说明变化，没有改写其历史审核结论。
- task-001 R5 的清理状态持久化、清理动作再次改写及空白 Event SHA 等问题没有在本轮修复。
  A–G 通过不覆盖这些反例；后续 pi 修复后应先更新共同基线再重跑。
- PR #7/#8 仍未合入；状态性质、红队安全边界等未因此补齐，不能把本次全绿当作它们通过。
- 风险 D 级退出码仍为 3；分支保护、人工批准如何转绿等政策未替用户决定。
- WSL 隔离、可信控制器、真实模型回合、真实网络白名单和实耗计量不在本次验收范围。

## 6. 建议的正式合并顺序

建议先让相关修复在 m1 核心基线上稳定，再采用本次已演练的顺序：

1. **更新后的 feat/m1-runnable**：作为共同基线；R5 修复后重新核对相关反例。
2. **feat/risk-gate**：使用已验证的 `9f56a64`（包含 c8966cd），保留可信 base 裁判模式。
3. **feat/github-adapter**：接入来源、持久化与安全执行边界；本轮与风险分支无文本冲突。
4. **feat/cli-run**：最后组合 CLI；在提交正式合并前解决同样的导入/注册区冲突，保留双方功能。

risk-gate 与 GitHub adapter 之间本次没有强制的文本依赖；按用户指定的先闸门顺序已经验证。
GitHub 与 CLI-run 都修改同一个 CLI 入口，建议两边先 merge 最新共同基线，
由最后合入的一侧负责组合注册表、保留 UNKNOWN 失败退出语义，并复跑整个 A–G。
不是用 ours/theirs 整文件覆盖来省掉冲突。

#7/#8 等稳定后再逐个追加独立演练，不夹入当前结果；每次都重新检查全套测试和临时库路线。
上述本地 merge commit 是集成证据，不是对真实后台或合并政策的自动批准。
最终追平后的全量结果为 **518 passed、1 skipped**，A–G 加准备帮助仍为 **47/47** 符合预期。
