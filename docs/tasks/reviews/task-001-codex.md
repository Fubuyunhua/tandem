# task-001 独立代码审核 · codex

审核范围：`main...feat/m1-runnable` 的全部改动；基线 `f973b8fc312b1ca91f2eb9e446a1dee1099ca0bd`，分支头 `cadc2c4f07dd2a64829da2cb2661cb12c989ba55`。依据任务书、第七版状态流转、ADR-0001 和 PRD F4；未读取其他审核者输出。

验证全程离线，未调用真实 AI：`pytest -q -p no:cacheprovider` 为 **164 passed**，pyright 为 **0 errors**，ruff check、format 检查和默认配置下的 `tandem demo` 均通过；使用 `uv --offline --no-sync`，禁止生成 Python 字节码。下面的反例通过内存事件、内存 SQLite 和内存 mock 验证，未添加或修改测试文件。

内核当前未发现实际 IO、间接调用外壳或携带外部执行能力的对象；`test_purity.py` 未被修改。默认执行器也确实阻止真实 Agent 和合并等外部副作用。问题主要在于：**通过了纯度与正常路径测试，不代表放行条件和恢复流程正确**。

## 1. 改审核标准可以绕过红色 CI，直接生成合并动作

- **问题**：从 CI 失败进入人工介入后，改标准并获得审核通过，即使 `ci_green=False` 仍能进入待合并。
- **位置**：`src/tandem/core/transition.py:703`、`src/tandem/core/transition.py:583`；对应第七版 #12、#22。
- **为什么重要**：实测路径为“验收连续失败 3 次→待你介入→STANDARD_CHANGED(version=2)→两家 PASS”，结果是 `AWAITING_MERGE`，同时 `ci_green=False`，并产生 `MERGE` 动作。#22 没有处理尚未通过验收的任务，#12 也没有执行最终 CI 守卫。即使目前执行器是 dry-run，内核已经批准了明确禁止的动作。
- **建议**：把当前 SHA 的 CI 成功作为所有合并许可的统一不变量，而不是只在人工批准函数里检查；改标准不能替代验收，CI 未绿时不得走到可合并分支。补“R01 后改标准、两家通过仍不能合并”的回归测试。
- **严重程度**：高

## 2. 同一提供方换两个审核者名称，就能伪装成两家通过

- **问题**：审核资格按 `review.provider` 检查，完成集合却按 `review.reviewer` 汇总，二者没有绑定。
- **位置**：`src/tandem/core/transition.py:532`、`src/tandem/core/transition.py:583`；`tests/core/helpers.py:122`。
- **为什么重要**：指定审核者为 `('codex', 'opencode-go')` 时，依次提交 `(reviewer='codex', provider='codex')` 和 `(reviewer='opencode-go', provider='codex')` 两条 PASS，实测进入 `AWAITING_MERGE`，记录中两条 provider 都是 codex。反过来，合法提供方若使用不同的会话名作为 reviewer，也可能一直等不到完成。测试助手强制 `reviewer == provider`，恰好掩盖了字段错配。
- **建议**：明确审核者 ID 与真实模型提供方的映射，接收结论时验证绑定，按指定审核席位完成、按提供方去重，并在放行时再次核对至少两家不同且未参与编写的提供方。配置里的 `opencode-go` 是工具/服务入口，后续接真实模型时必须另记实际模型提供方，不能直接当独立性证明。增加名称不同、同方多会话、伪装另一席位的反例。
- **严重程度**：高

## 3. 新提交在审核阶段被忽略，批准与合并事件也没有严格核对目标 SHA

- **问题**：新 SHA 只在“处理中交回代码”分支更新，横切的旧结论失效规则没有真正实现。
- **位置**：`src/tandem/core/transition.py:303`、`src/tandem/core/transition.py:611`、`src/tandem/core/transition.py:649`；`tests/core/test_transition_rows.py:560`。
- **为什么重要**：实测待 AI 审核 h1 时，提交带正确 attempt 的 h2 代码事件被忽略，任务仍保存 h1；继续提交 h1 的两条通过结论，仍产生合并许可。另实测 `YOUR_APPROVAL(sha=h2)` 能批准当前 h1，`MERGED` 完全不带 SHA 也会标成已合并。现有“新提交作废”测试先退回到处理中才提交，没有验证审核中、待人工审核或待合并时发生新提交。
- **建议**：增加独立的新提交更新处理，覆盖所有允许接收变更的非终点状态：更新真实 SHA、清空旧审核/批准/否决、回到验收与必要的方案审批；已经发出的合并动作需核对结果。批准事件必须指明并匹配当前 SHA，合并成功必须带核对过的 SHA，不接受缺失时的宽松回退。CI_RED 也应像 CI_GREEN 一样核对 SHA；目前旧 SHA 的红结果会误增当前验收失败次数。
- **严重程度**：高

## 4. 人工接手提交代码不重新算级别，也无法补记新参与的 AI

- **问题**：#24 处理器忽略 `event.changes` 与新参与提供方，人工提交路径绕过了等级与写审分离逻辑。
- **位置**：`src/tandem/core/transition.py:749`；`tests/core/test_scenarios.py:215`。
- **为什么重要**：实测 C 级任务进入“你处理中”，提交带 `CORE_CHANGES` 的 h2 后仍为 C；即使事件注明另一个参与提供方，也不加入 `providers_involved`。多 Agent 模式下，这份核心改动可能按 C 自动放行，帮忙写过代码的 AI 还可能被选去审。名为“你自己改了 core”的场景 9 测试实际只传 SHA，没有传核心改动，也没有断言最终为 D，因此没有验证它声称的关键条件。
- **建议**：人工与 Agent 提交共用真实改动重新分级、旧证据失效的逻辑；人工事件增加明确的参与提供方集合并累积保存，不能仅把旧集合打印到备注。按 D 的方案条件处理升级。补真正修改 `core/**`、混合作者及新增参与提供方的完整场景测试。
- **严重程度**：高

## 5. “纯文档”只靠宽泛目录 glob，代码和跨目录路径也能降到 B

- **问题**：`all_paths_relaxable` 把 `docs/**` 下所有文件都当纯文档，路径归一化也只替换分隔符。
- **位置**：`src/tandem/core/level.py:20`、`src/tandem/core/level.py:55`；`risk.yml:49`。
- **为什么重要**：实测 `ChangeSet(paths=('docs/run.py',))` 配模型建议 B，结果就是 B，Python 代码因目录名获得低风险流程。`docs/../src/helper.py` 也可命中文档 glob，而代码没有拒绝 `..`；这类非规范输入一旦由外壳传入，会错误分类。已有混合代码测试只使用 `src/...`，未测文档目录内的可执行文件。改名的旧、新路径虽然都参与判断，但“可放宽”的定义本身仍过宽。
- **建议**：规则同时约束规范的仓库相对路径与允许文档类型，拒绝绝对路径、空路径、`..` 等非法输入；可执行文档、Agent 指令和受保护文件另设底线。新增 docs 内代码、异常路径、重命名后混合类型的测试。另外，ADR 的同 Issue 多 PR 合计规则在当前任务/改动模型中没有 Issue/PR 关联或聚合入口，应补一个可用假数据验证的合计层，不能把单个 `ChangeSet` 测试当成已防住拆 PR。
- **严重程度**：高

## 6. 事件、任务与动作不是原子保存，状态版本号也不能防止并发覆盖

- **问题**：Runner 分别提交事件、快照和动作，Store 又允许同版本的不同内容覆盖，无法兑现状态版本号的防冲突作用。
- **位置**：`src/tandem/shell/runner.py:94`、`src/tandem/shell/store.py:123`、`src/tandem/shell/store.py:137`；`tests/shell/test_store.py:101`。
- **为什么重要**：内存注入 `save_task` 故障后，实测事件表已有 ASSIGN，任务仍是 PENDING，动作表为空。同一旧快照被两个处理者读取时，各自产出版本 n+1，第二个能覆盖第一个；实测同为版本 1 的 WORKING 可直接被另一份 CANCELLED 覆盖。这不是幂等，因为内容不同；现有测试反而明确允许同版本改变 reason。
- **建议**：用一个事务提交事件处理结果、带预期旧版本的任务更新与待执行动作；使用 `UPDATE ... WHERE state_version = expected` 并检查受影响行数。执行副作用在事务提交后进行。相同版本重复保存仅接受完全相同内容；并发冲突重新读取并裁决。增加两个连接竞争与提交中途异常的测试。
- **严重程度**：高

## 7. CLI 在“待你审核”发送了错误事件，用户批准后状态原地不动

- **问题**：`tandem approve` 把“待你审核”和“待你介入”都转换成 `INTERVENTION_APPROVED`，但内核只允许后一个状态接收它。
- **位置**：`src/tandem/shell/cli.py:142`、`src/tandem/core/transition.py:661`；`tests/shell/test_cli_demo.py:109`。
- **为什么重要**：实测单 Agent 任务 CI 绿后位于 `AWAITING_YOUR_REVIEW`，调用真实 `cmd_approve` 处理逻辑，返回码为 0，但状态仍为 `AWAITING_YOUR_REVIEW`。这阻断 M1 每个任务的人工放行，也阻断多 Agent 的 D 级放行。新增 CLI 测试只测方案批准，恰好没有走代码批准。
- **建议**：待你审核发送 `YOUR_APPROVAL`，待你介入才发送 `INTERVENTION_APPROVED`；事件被拒绝时 CLI 返回非零，不能假报成功。补单 Agent C/D 的代码批准、D 多 Agent 批准及 CI 红拒绝的 CLI 测试。
- **严重程度**：高

## 8. 审核途中失去审核者的 #16 没有实现，条目测试实际测的是 #9 的准备阶段

- **问题**：待 AI 审核期间没有路径处理审核者额度耗尽或合格集合不足。
- **位置**：`src/tandem/core/transition.py:374`、`src/tandem/core/transition.py:425`；`tests/core/test_transition_rows.py:341`、`tests/core/helpers.py:169`。
- **为什么重要**：实测任务已经 `AWAITING_AI_REVIEW`，额度快照标记两家审核者都耗尽，再送 `QUOTA_EXHAUSTED(provider='codex')`，事件被忽略，仍待 AI 审核。代码只在进入审核前、或改标准时选人；额度用完处理器只接收 WORKING。名为 row_16 的测试 helper 从待验收发送 CI_GREEN 时才设置缺额度，根本没有经过“待AI审核→待你介入”这条 #16 转换。
- **建议**：增加审核可用性变化事件或复核路径，在待 AI 审核中按当前额度与参与历史重新检查；确实凑不齐就以 R03 进入待你介入，保留已完成证据。重写 row_16 测试，先进入审核，再使审核者失效并验证转换，而非只测审核前分配。
- **严重程度**：高

## 9. 已存记录不足以重放，重启还会忘记额度和动作的最新状态

- **问题**：持久化只保存零散事件与最新任务快照，没有恢复逻辑，运行态与动作表也没有统一事实来源。
- **位置**：`src/tandem/shell/runner.py:74`、`src/tandem/shell/runner.py:77`、`src/tandem/shell/runner.py:105`；`src/tandem/shell/store.py:108`。
- **为什么重要**：`submit` 只存快照，不追加创建事件；后续事件也未保存当次政策、额度和完整决定输入，无法从日志重建原始等级、模式及裁决。实测旧 Runner 已把 Claude 标为 EXHAUSTED，同一 Store 新建 Runner 后又变 UNKNOWN，可再次派给它。动作结果只更新动作表，任务快照内的 `task.actions` 仍是 SENT；内核异常处理读取的正是后者，会把已完成动作也列为未确认。
- **建议**：保存创建事实、决定所用版本/快照与动作结果事实，提供明确的离线恢复/重放入口；重放不调用 Agent、不重复副作用。启动时恢复额度估计，或者显式标记未知且保留之前耗尽事实以供判断；任务动作视图由同一记录来源投影，避免两份状态分叉。补关闭再打开数据库后恢复任务、额度和未确认动作，以及从日志重建一致状态的测试。
- **严重程度**：中

## 10. 异常重试只改回状态，不恢复被停止的工作，场景测试手工制造了不存在的回执

- **问题**：`NOT_CONFIRMED` 重试回到 WORKING/待审核后只产生通知，没有重启或重发未完成工作。
- **位置**：`src/tandem/core/transition.py:824`、`src/tandem/shell/executor.py:115`；`tests/core/test_scenarios.py:121`、`tests/core/test_scenarios.py:196`。
- **为什么重要**：#8 会要求 STOP_AGENT；确认进程已经消失后，#26 的实测输出为 `WORKING`，动作却只有 `NOTIFY`。没有 Agent 能产生后续回执，任务会一直假装处理中。场景 4、8 直接在恢复后调用 `walker.submit_code()`，没有验证任何新 Agent 被启动。另执行器把 AgentError/超时变成 UNKNOWN 返回，但 Runner 不把它转成 INCIDENT，错误也不会自动进入异常状态。
- **建议**：按核对结果区分“仍在执行”和“需要重新执行”，后者返回待派活或生成新的有编号的启动/审核动作；执行失败应产生带尝试编号的异常事件。用假 Agent 真正走一次“启动失败/进程消失→异常→重试→再次运行→真实假回执”，而不是测试代码代替失踪 Agent 交回执。
- **严重程度**：中

## 11. 反对意见没有问题内容，退回后又被清掉，人工否决可以不写理由

- **问题**：审核记录只能保存结论和人名，无法表达并逐条回应反对意见，拒绝修改路径还会丢掉用于检查理由的结论。
- **位置**：`src/tandem/core/model.py:220`、`src/tandem/core/transition.py:547`、`src/tandem/core/transition.py:579`、`src/tandem/core/transition.py:669`。
- **为什么重要**：实测“codex FAIL→退回修改→重新派活→写手拒绝修改→待你介入→人工批准不传 reason”仍进入待合并；因为退回时 reviews 已清空，人工批准函数看不到任何 failing。即便未清空时，判断也只是“有任意非空 reason”，不是逐问题理由。Review 结构没有问题编号、具体意见或依据，用户连要否决什么都只能看到审核者名字。
- **建议**：把历史 findings 与当轮有效通过结论分开保存；清除通过资格不能删除待回应问题。每项意见保留 ID、内容、SHA/标准版本，人工覆盖按 ID 提交理由并检查完整性。新增上述拒绝修改路径及多条反对意见缺理由的反例；保持用户有最终决定权，但不能省略已要求的留痕。
- **严重程度**：中

## 12. Demo 与默认模式耦合，且没有验证终态，冒烟测试可能在场景失败时仍报成功

- **问题**：demo 使用全局 `risk.yml` 模式并无条件返回 0，而项目默认又配置为多 Agent，与 M1 单 Agent 设置相反。
- **位置**：`risk.yml:8`、`src/tandem/shell/cli.py:61`、`src/tandem/shell/cli.py:226`、`src/tandem/shell/cli.py:307`；`tests/shell/test_config.py:13`。
- **为什么重要**：仅在内存把 demo 读入的策略改为合法 `SINGLE_AGENT`，实测场景 1 只到“待你审核”，并未已合并，但 `run_demo()` 仍返回 0。CI 执行命令不会因此失败。当前配置注释写 M1 单 Agent，值却是 multi_agent，CLI 新建任务默认也会采用它；配置测试把这个不一致固定成预期。
- **建议**：项目默认采用 M1 模式；demo 场景 1 显式构造其所需的多 Agent 策略，不依赖生产默认。对两个场景分别校验最终状态、当前 SHA 和预期动作，不满足就返回非零；为合法默认配置变化及场景中断增加测试。用假审核事件模拟审核本身可以接受，但不能把“成功打印了路径”当成完成验收。
- **严重程度**：中

结论：**修改后可以**。内核/外壳结构与默认 dry-run 已搭起，现有检查也全绿；但 CI 约束、提供方独立性、新提交失效和 M1 人工批准都有已复现的错误，当前不能作为通过审核的可运行骨架交给用户。
