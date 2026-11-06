# AI 编码自动化流水线与风险分级放行

调研日期：2026-11-04。下列链接均已联网读取；无发布日期的滚动文档以本日检索版本为准，不将检索日当作发布日期。本文提供工程方案，不实施配置或改动其他文件。

## 1. 一句话结论

单人开发者应把自动化建立在“小任务、可执行风险规则、独立验证、按提交留痕”上：AI 负责实现与提出审查意见，受保护的 GitHub 检查负责放行，只有低风险且可回滚的改动自动合并。

## 2. 关键发现

### 2.1 厂商已有完整工作循环，但自动执行不等于自动批准

**OpenAI Codex。** Cloud 每个任务有独立 workspace，可在本机休眠后继续工作；用户检查变更和检查结果，再提交或开 PR。GitHub 集成支持 `@codex review` 和自动 review，并读取适用目录的 `AGENTS.md`。官方明确将 AI review 定位为额外审查层，硬约束仍由测试、分支保护和必需审批提供。因此 `AGENTS.md` 适合描述“不应改变的接口或数据边界”，不能代替权限策略。[Cloud 文档](https://learn.chatgpt.com/docs/cloud)、[GitHub review 文档](https://learn.chatgpt.com/docs/third-party/github)（滚动版本，2026-11-04）；[Custom Code Review rules](https://developers.openai.com/blog/custom-code-review-rules-for-codex)（2026-07-20）。

**GitHub Copilot。** cloud agent 默认结合 CodeQL、依赖检查、secret scanning 与第二次 AI review；能写指定分支，仍受仓库规则约束。安全文档描述其不能自行批准或合并 PR，Actions 默认需要人工允许后执行。较新的 Agent Merge 能自动修失败 workflow 和合并冲突，但云端文档明确：它不替代人审或仓库合并要求，可以和 auto-merge 配合。应区分“修到可合并”与“谁有权合并”，不能把这些产品名理解为统一的无人值守授权。[安全机制](https://docs.github.com/en/copilot/concepts/security-governance-and-network-settings/risks-and-mitigations)、[Agent Merge](https://docs.github.com/en/copilot/how-tos/copilot-on-github/use-copilot-agents/watch-and-fix-pull-requests)（均为本日滚动版本）。

**Claude Code。** `claude -p` 提供脚本入口和结构化输出；GitHub Action 可按事件执行或响应 `@claude`。`PreToolUse` hook 可在工具执行前阻止动作，`PostToolUse` 已经来不及阻止原动作；不要把所有 hook 错误都当作拒绝。权限 `auto` 模式由分类器评估动作与用户请求是否一致，`bypassPermissions` 则跳过常规权限提示；两者都不是业务风险批准。subagents 有独立上下文、工具权限，可用于只读审查。来源：[程序化运行](https://code.claude.com/docs/en/headless)、[Actions](https://code.claude.com/docs/en/github-actions)、[hooks](https://code.claude.com/docs/en/hooks)、[permissions](https://code.claude.com/docs/en/permissions)、[subagents](https://code.claude.com/docs/en/sub-agents)（本日滚动版本）。

### 2.2 有效 harness 依靠外部证据与交接材料

Anthropic 的长任务实践使用初始化环境、功能清单、进度文件、Git 历史和逐项端到端验证，解决 agent 跨会话丢失状态或过早宣布完成的问题。它是工程实验，不是自动合并安全性的证明。GitHub Spec Kit 则提供结构化流程、模板和结果记录：可把需求与验收条件前置，但规格本身仍可能错误，不能自行成为放行证据。[Anthropic harness](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents)（2025-11-26）；[Spec Kit](https://github.github.com/spec-kit/)（本日滚动版本）。

### 2.3 policy-as-code 已有基础设施，L0–L3 需自己定义

GitHub branch protection 支持必需状态检查、审批、过期审批失效、禁止绕过；CODEOWNERS 定义责任人，必须配合必需 owner review 才能强制执行，还需保护 CODEOWNERS 自身。OPA 可在 CI/CD 验证输入并执行自定义策略，但不会自动推导业务风险。上述来源没有给出可普适套用的 AI 改动风险等级标准。[分支保护](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)、[CODEOWNERS](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)、[OPA CI/CD](https://www.openpolicyagent.org/docs/cicd)（本日滚动版本）。

### 2.4 测试通过以外，要验证“测试是否抓得到错误”

Mutation testing 故意改变实现，检查现有测试能否杀死 mutant；property-based testing 适合用大量生成输入检验不变量。它们补充覆盖率，不能证明没有 bug。CodeQL 可通过 default setup 降低维护成本；安全扫描能力和私有仓库授权需按账户确认。[Stryker](https://stryker-mutator.io/docs/)（本日文档）；[Hypothesis](https://hypothesis.readthedocs.io/en/latest/)（检索页版本 6.170.14）；[CodeQL setup](https://docs.github.com/en/code-security/concepts/code-scanning/setup-types)（本日滚动版本）。

## 3. 对委托人的可落地建议

以下阈值、角色与抽查比例均为**建议的起始策略**，并非厂商标准或实证最优值。

### 3.1 风险规则：最高等级覆盖，默认 L2

| 等级 | 判定示例 | 放行方式 |
| --- | --- | --- |
| L0 | 仅 `docs/**`、普通 Markdown 的错字或说明；不含脚本、指令文件、法律文本；不超过 50 行 | 必需检查全绿后自动合并 |
| L1 | 明确白名单内的内部纯函数或非关键 UI；不超过 150 行、5 个文件；不改依赖/API；有行为测试且可回滚 | 独立 AI 审查完成、无未解决阻断项后自动合并；每日抽查 |
| L2 | auth、支付、权限、数据库迁移、依赖/lockfile、公共 API、部署/CI、agent 配置、风险策略或测试基础设施；超过大小阈值；其他未识别变化 | `needs-human`；人审当前提交后才能合并 |
| L3 | 产品权限模型、支付计价规则、不可逆删除、生产凭据授权、不可恢复迁移、数据外发边界 | AI 先给备选方案、影响和恢复路径；人决定后另开实施任务，通常仍为 L2 |

路径只是起点：文档中也可能藏可执行命令；改一行授权判断也可能是 L3。统计新增与删除行数，重命名同时检查旧、新路径；二进制、超大 diff、无法判定语义均升级。修改策略、验收条件、测试删除/跳过、扫描抑制和快照批量更新不能通过“测试全绿”降级。

统一规则为：`risk = max(所有命中规则)`；没有足够测试、失败/超时/跳过、审查缺失或重大分歧，一律停止自动合并。扫描发现 secret 立即阻断；High/Critical 或其他有实际利用路径的发现必须处置或由人记录限期豁免。agent 自报“95% 有信心”只留档，不参与自动降级。

### 3.2 从任务到合并的流程

1. 人写一小段任务卡：目标、非目标、允许路径、验收示例、预算和回滚方式。L3 在此暂停实现。herdr 中每项任务各用独立 Git worktree 和分支，避免四个 agent 写同一工作目录。
2. Claude Code 默认主写，便于用 `-p`、权限和 hooks 接脚本；Codex 用新会话审固定 SHA，先看任务卡和代码，自行找反例，再看作者解释。选择依据是接口便利与上下文分离，**没有证据证明某品牌天然更善于审查**，也可轮换。
3. pi 用作定向复现、定位失败的小任务执行者；Antigravity 可在已配置浏览器能力时验证 UI 与截图。它们不是每个 PR 必跑的额外裁判；本次未核实其具体 CLI、权限接口或 herdr 自动调度能力。herdr 先只管理终端，会话间由人工传任务卡/SHA；不虚构其 API。
4. 审查者不持合并权限、不修改待审分支。需要动态运行时使用无凭据的临时环境；“只读文件工具”不能阻止任意 shell 写文件。writer 最多自动修复两轮，仍失败或超预算转 `needs-human`。任何新提交均重新分类、跑检查和审查。
5. GitHub 作为唯一状态源：main 禁止直接推送/force push，要求 `verify`、`risk-policy` 与实际启用的安全检查；将状态检查绑定可信 App 来源。低风险才启用自动合并，且必须基于最新 base 验证；出现冲突或 base 更新后重跑。

**单人审批限制：** 不要全仓要求“另一个人批准一次”，否则自己开的 PR 会卡住。起步保留必需检查，L2 人工合并；自动化成熟后，由独立受信 GitHub App 提供必需 `risk-policy` 检查：L0/L1 验证齐全才成功，L2 只有收到仓库所有者对精确 head SHA 的显式确认才成功，L3 另需方案决定记录。验证评论作者的不可变用户 ID 和当前权限，标签仅用于展示；收到新提交即使确认失效。若引入其他维护者，再加 CODEOWNERS 必需审批。[GitHub 审批文档](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/approving-a-pull-request-with-required-reviews)（本日版本；上述自定义 App 为方案设计）。

风险判定器从受保护的 base/独立策略仓库加载规则，读取 GitHub 的真实 diff 元数据，不信任 PR 标签、正文或作者提供的 JSON。持合并凭据的进程只查 API 和执行策略，不能 checkout 后执行 PR 代码；若使用 `workflow_run` 等特权入口，也不能执行不可信 artifact。规则变更本身走 L2，防止 agent 修改裁判。

### 3.3 CI 示例与关卡优先级

以下是 **Node/TypeScript 项目的验证片段**；须先定义对应 npm scripts、提交 lockfile，再按实际技术栈替换。它不包含尚需实现的可信 `risk-policy` App，不能单独当成完整自动合并系统。示例主版本标签用于可读性，上线应审核并固定 Action commit SHA。

```yaml
name: pr-checks
on:
  pull_request:
    branches: [main]
permissions:
  contents: read
jobs:
  verify:                         # 必须：在分支规则中设为 required
    runs-on: ubuntu-latest       # 本地 Windows 不要求 CI 也用 Windows
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: actions/setup-node@v4
        with:
          node-version: '22'
      - run: npm ci
      - run: npm run lint
      - run: npm run typecheck
      - run: npm run test:ci      # 无 watch；失败退出非零
      - run: npm run build
      - run: npm audit --audit-level=high  # 基线依赖检查，不能替代 SAST
      # 可选：npm run test:e2e（关键路径成熟后变为必须）
      # 可选：npm run test:mutation（先只跑核心模块/夜间）
```

PR 中代码和安装脚本仍可执行，所以使用 GitHub 托管的临时 runner，不注入生产/API secret，不用日常 Windows 电脑当不可信 PR 的 self-hosted runner。工作流不要通过路径过滤而跳过整个 required check；即使仅文档变更，也要产生明确结果。Windows 专属功能增加 `windows-latest` 检查。

性价比建议按以下顺序增加，属于工程判断：

- **先必须：** lint、类型、构建、相关单元/回归测试、secret 扫描、依赖检查；支持且有授权时启用 CodeQL/SAST，扫描结果设为合并门槛，而非只产生可忽略报告。`npm audit` 不检查业务越权，也不等同供应链安全证明。
- **随后：** 登录/授权、支付沙盒等关键集成或端到端路径；UI/输出格式使用 golden/snapshot，但人确认基线，禁止 agent 一键更新基线消除失败。用干净 checkout、锁定运行时和依赖复跑；记录失败 seed、环境和命令。
- **按风险：** 对解析、序列化、金额等不变量加 property-based tests，对少量核心模块用 mutation testing；预览环境用合成数据。部署后用 feature flag 或 canary，按预设错误率/关键交易指标回滚。代码回退不能撤销已经执行的数据删除或迁移。
- **AI 互审：** 擅长发现遗漏需求和边界情况，但可能共享盲点；“没有评论”不是完成且通过，要求结构化结果和完成状态，不能用两个 agent 赞同替代客观证据。

### 3.4 决策留痕与抽查

每个 PR 固定记录：任务卡链接、base/head SHA、策略版本、命中规则及等级、agent/模型与版本、实际测试命令和结果链接、未解决发现、放行主体与理由、回滚方法。AI 原始输出只能作为附件，最终风险结果由可信控制器记录；不保存凭据或敏感原文。

审查输出最少包含 `head_sha / completed / findings / tests_missing / recommendation`，逐项 finding 给位置、触发条件与影响。L2 排入 `is:pr is:open label:needs-human`；架构、数据边界和不可逆取舍另写简短 ADR，记录备选、理由、后果与替代关系。

L1 每日抽 20%、至少一件；优先抽规则边缘和新模块，留下“理解/遗漏/回滚”记录。抽查发现严重漏检就暂停该类自动合并、补回归用例、修改策略。每周看逃逸缺陷和回滚率，并保留一段手写回归用例或实现的时间，限制每次同时在途的任务数量，让产出量符合自己的理解速度。

### 3.5 起步只做三件事

1. **任务卡与小 PR：** 写清验收、禁区、回滚；一个 worktree 一个任务，Claude 写、Codex 独立审；先限制最多两个在途任务。
2. **最小硬关卡：** 配好 main 必需 CI 与安全扫描，风险规则先记录并人工执行；CI/策略/agent 指令改动一律 L2，此时尚不自动合并。
3. **仅放开 L0：** 连续一周观察规则与 CI 后，接入可信风险检查，仅对普通文档白名单自动合并并记录 SHA；稳定后再开放 L1 和每日抽查。暂不引入 OPA、多重 AI 裁判或全量 mutation testing。

## 4. 争议与不确定

- 产品文档会变：Copilot 安全文档的人工合并限制与新 Agent Merge、不同客户端的能力不能混为一谈；应以实际入口和仓库规则为准。本文不承诺所有账户、私有仓库或套餐均可用。
- 未找到通用且经验证的行数阈值、风险算法或可用于放行的 agent 自评置信度标准；文中的 50/150 行及 20% 抽查应按漏检记录调整。
- 不同 agent 的上下文隔离有操作价值，但降低多少缺陷、是否优于单 agent 复审，所读实践没有给出可推广结论。Spec 和测试若都来自同一错误假设，也会共同通过。
- 本文选取 Codex、Copilot、Claude Code、Spec Kit 和 Anthropic 实践深入覆盖，未逐项核验 Cursor、Jules、Devin、Factory、OpenHands 或商业 review 机器人的当前能力，不作横向优劣排名。

## 5. 参考来源列表

以上各发现均附直接来源；便于汇总的索引如下：

1. OpenAI：[Codex Cloud](https://learn.chatgpt.com/docs/cloud)、[GitHub Review](https://learn.chatgpt.com/docs/third-party/github)；本日滚动文档。[自定义 review 规则](https://developers.openai.com/blog/custom-code-review-rules-for-codex)，2026-07-20。
2. GitHub：[Copilot 风险缓解](https://docs.github.com/en/copilot/concepts/security-governance-and-network-settings/risks-and-mitigations)、[Agent Merge](https://docs.github.com/en/copilot/how-tos/copilot-on-github/use-copilot-agents/watch-and-fix-pull-requests)；本日滚动文档。
3. Anthropic：[headless](https://code.claude.com/docs/en/headless)、[hooks](https://code.claude.com/docs/en/hooks)、[permissions](https://code.claude.com/docs/en/permissions)、[subagents](https://code.claude.com/docs/en/sub-agents)、[GitHub Actions](https://code.claude.com/docs/en/github-actions)；本日滚动文档。
4. Anthropic：[Effective harnesses for long-running agents](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents)，2025-11-26。
5. GitHub：[Spec Kit](https://github.github.com/spec-kit/)、[仓库](https://github.com/github/spec-kit)；本日检索的项目文档。
6. GitHub：[branch protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)、[CODEOWNERS](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)、[PR approvals](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/approving-a-pull-request-with-required-reviews)、[CodeQL setup](https://docs.github.com/en/code-security/concepts/code-scanning/setup-types)；本日滚动文档。
7. [OPA CI/CD](https://www.openpolicyagent.org/docs/cicd)、[Stryker mutation testing](https://stryker-mutator.io/docs/)、[Hypothesis](https://hypothesis.readthedocs.io/en/latest/)；本日文档，Hypothesis 页版本 6.170.14。
