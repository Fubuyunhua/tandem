# pi：人的侧——技能维持、理解债与高效审核

> 日期：2026-11-04  
> 范围：只讨论个人层面的技能、理解与审核容量；团队流程、CI 自动化和“哪些决定交给 AI”的分工由其他调研员负责。  
> 证据标注：**【A】** 对照实验/系统综述/多项研究一致；**【B】** 观察性数据/日志/小样本实验（含预印本）；**【C】** 间接证据或合理推理；**【D】** 个人经验/行业惯例。

---

## 一句话结论

AI 可以替你产出代码，但不能替你形成判断力；唯一可持续的做法是把 AI 的产出当成“必须被理解的变更”，用 **200–400 行/次**的粒度、**先预测后阅读**、**可失败测试**和**每天 60–90 分钟**的深度审核预算，把注意力集中在意图、边界、契约和可回滚性上——技能与审核容量都来自刻意保留的摩擦。

---

## 1. 关键发现

### 1.1 AI 对技能与理解的影响：主要证据

| 研究 | 样本与方法 | 主要结果 | 关键局限 |
|---|---|---|---|
| Anthropic，2026-01-29（预印本） | 52 名工程师（以初级为主）RCT；学习不熟悉的 Python 异步库 Trio；AI 侧栏可随时给正确代码 | AI 组测验 **50% vs 67%**，低 17 个百分点（相对约 25%）；Cohen's d=0.738，p=0.01；最大差距在 debugging；完成时间只快约 2 分钟，不显著 | 样本小、短期、非 agentic、以初级为主；交互模式是观察性的 |
| METR，2025-07-10 | 16 名资深开源维护者、246 个真实 issue、自己的大型仓库；Cursor + Claude 3.5/3.7；$150/h | 允许 AI 时任务反而 **长 19%**；开发者事前预计快 24%，事后仍认为快 20% | 2026-02 更新认为新数据因选择偏差不可靠；原结果已标注过时 |
| Microsoft Research / CMU，CHI 2025 | 319 名知识工作者、936 个真实 GenAI 使用案例的横断面调查 | 对 GenAI 信心越高，自报批判性思维越少；对自己信心越高，越多；批判性思维转向核实、整合、任务管理 | 自报、横断面，不能证明因果；不是能力测试 |
| MIT Media Lab，2025（arXiv 预印本） | 54 人、三组（LLM/搜索引擎/纯大脑）、议论文写作、EEG；第四阶段 18 人交叉 | LLM 组脑连接最弱、文章拥有感最低、更难引用自己写的内容 | 预印本、样本小、任务是写作不是编程；EEG 到“认知债”的推断有争议 |
| Bastani 等，PNAS 2025 | 近千名高中数学生；GPT Base（直接给答案）vs GPT Tutor（提示、不给答案） | GPT Base：练习 +48%，撤掉 AI 后考试 **−17%**；GPT Tutor：练习 +127%，撤掉后基本无负面影响 | 高中数学，不是编程；短期；单一场景 |

**Anthropic 的细节最值得读。** 它把“用不用 AI”拆成了“怎么用 AI”。低分组：完全委托、逐步依赖、用 AI 反复调试，测验均低于 40%。高分组：先生成再追问理解、代码+解释混合提问、只问概念自己写，均不低于 65%。其中“只问概念、自己写”是高分模式里最快的。这说明**认知参与**比“是否使用 AI”更能预测学习结果；但这是定性观察，不能当因果。

**METR 的正确读法不是“AI 一定让人变慢”。** 它证明的是：在成熟、复杂、维护者自己熟悉的代码库上，AI 的净收益不是自动的；而且**主观感受与实测可以背离**。2026-02-24 的更新说明，当越来越多开发者拒绝“无 AI”条件时，RCT 会出现选择偏差：老开发者子集现在估计快 18%，新开发者快 4%，置信区间都跨 0。METR 自己认为“现在很可能比 2025 年更快”，但证据很弱。所以这条证据应被用来校准“我觉得快”的自信，而不是断言 AI 无用。

**注意：** 17% 是 17 个百分点（50% vs 67%），相对降幅约 25%，媒体经常混用。

**补充：** Peng 等 2023 年在简单 HTTP server 任务上快 **55.8%**；结论取决于任务熟悉度和可验证性——委托人日常面对的恰是“不熟悉 + 难验证”的一端。

**理解债（comprehension debt）的定性证据。** Addy Osmani 2026-03-14 把它定义为“代码库中存在的东西，与人真正理解的东西之间的差距”；它不像技术债那样通过构建变慢来报警，而是制造虚假信心。Storey 2026 把债拆成技术债（代码）、认知债（人的共享理解）、意图债（外化的理由）。Ahmad 2026 分析了 207 名本科生、8 周、621 份反思日记，识别出四种积累模式：黑箱接受、上下文错配、依赖导致的能力萎缩、绕过验证；以及一种缓解模式：把 AI 当“理解脚手架”。这些是预印本/定性研究，不能当精确测量，但分类很好用。

### 1.2 保持手写能力：哪些方法有证据

先说结论：**不是“少用 AI”，而是“保留三个动作”：自己生成、主动检索、向自己解释。** 以下证据多来自教育/学习科学，迁移到职业编程需要自己校准。

| 方法 | 证据 | 怎么用 |
|---|---|---|
| 刻意练习 | **【A】** 但效应有限：Macnamara 2014 元分析中，职业领域解释不到 1% 的表现差异（游戏 26%、音乐 21%） | 练“具体弱点”，不是“多写代码”；要有即时反馈和重复 |
| 检索练习 | **【A】** 2026 年元分析平均 g=0.37；心理学课堂元分析 d=0.56 | 合上 AI，从记忆写出函数/测试/数据流；再对照 |
| 间隔练习 | **【A】** 同一元分析中间隔效应 g=0.20；数学学习元分析 g=0.28 | 把复习分散到多天，不要一次看完 |
| 生产性失败 | **【A】** Kapur 2008/2011：先尝试复杂问题、失败、再教学，短期表现更差，但概念/迁移测试更好 | 先自己写 15–20 分钟，再问 AI；把“卡住”当成学习的一部分 |
| 自我解释 | **【A】** Chi 1989；编程领域 RCT（Tamang 2021）显示两者都能提升代码理解（Socratic 更强：59% vs 30%） | 每段代码用 3 句话解释“做什么/为什么/何时失败” |
| 受约束的 AI 辅导 | **【A】**（数学/物理）Bastani 2025；Kestin 2025 的定制 AI tutor 比主动学习课堂学得更多、用时更少 | 只给提示、不给答案；要求先尝试；要求最后做测验 |
| 每周无 AI 时段 | **【C】** 由检索/间隔/生产性失败间接支持；没有职业开发者 RCT | 每周一次 90 分钟端到端，允许查文档，不允许问模型 |
| 重写 AI 代码的关键部分 | **【C】** 生成效应/自我解释的间接支持 | 遮住 AI 版本，从 spec/测试重写 100–200 行，再 diff |
| 用 AI 生成练习题 | **【C】** LLM 能生成新颖、可用的编程练习（Sarsa 2022），但学习效果取决于你是否闭卷做 | 让 AI 出题 + 出测试，你闭卷做，最后用测试判分 |

**关于“AI 只给提示”。** Bastani 的实验显示：直接给答案撤掉后比从没用过更差，加教学护栏则无伤害——**护栏让收益可持续。**

### 1.3 审核容量的科学

**结论：人的深度审核速度大约是 200–400 行/小时，单次 60 分钟左右；超过之后，漏检率会明显上升。** 这不是“建议”，而是有几十年审查研究支撑的数量级。

- **Cisco/SmartBear 2006 案例**：10 个月、50 名开发者、2,500 次审查，覆盖 320 万行的代码库。平均 32 个缺陷/kLOC；61% 的审查没有发现缺陷。慢于 400 LOC/h 的审查者，缺陷密度高于平均；快于 450 LOC/h 时，87% 的审查低于平均。**【B】**
- **同一本书对三项审查实验的再分析**：缺陷发现率在前 60 分钟大致恒定，之后急剧下降；90 分钟后没有发现任何缺陷。作者建议单次约 1 小时，不超过 2 小时。**【B】**
- **TSP/PSP 的经验值**：200–400 LOC/h，对应 70–90% 缺陷发现率；这是操作建议，不是 Cisco 的回归系数。**【D/B】**
- **Google 2018 的 900 万次变更**：中位数只有 **24 行**；超过 35% 只改一个文件；不到 25% 有多个 reviewer；中位 reviewer 数 1；中位审查延迟不到 4 小时；70% 的变更在 24 小时内提交；reviewer 每周中位投入 **2.6 小时**；每条变更的平均评论数在约 1,250 行时达到峰值，之后不再增长。**【B】**
- **Beller 2014 的 1,400+ 变更**：现代代码审查修复的问题中，**75% 是 maintainability，25% 是 functional**；7–35% 的评论被丢弃；10–22% 的改动不是由明确评论触发的。**【B】**

**容量算式：** 1,000 行/天 ÷ 300 LOC/h ≈ 3.3 小时纯审查，按 60 分钟一段就是 3–4 段；加上测试和上下文，实际更久。若 AI 每天产 2,000–5,000 行，逐行深度审查在数学上不可能。**这不是自律问题，是算术问题。** 只能在“减少产出、提高自动化杠杆、风险抽样”中选。

**AI 代码让审核更贵，而不是更便宜。** 2026 年一项覆盖 300 个开源项目、278,790 条审查对话的预印本研究（arXiv:2603.15911）发现：人类审 AI 代码时讨论轮次多 **11.8%**；AI 建议采纳率显著更低；未采纳的 AI 建议中超过一半是错的或用别的修法；被采纳的 AI 建议让复杂度和代码量增加更多。2023 年 CCS 研究则发现：有 AI 辅助的参与者写出**更不安全**的代码，却**更相信自己写得安全**。合起来看，AI 代码“看起来干净”本身就是风险信号。**【B】**

### 1.4 高效审核策略：证据分级

| 做法 | 等级 | 说明 |
|---|---|---|
| 限速 200–400 LOC/h，单次 ≤60 分钟 | **B** | Cisco 2006 + 实验再分析；数据老、单一产品组，但方向一致 |
| 小批量：≤200–400 行、单文件/单概念 | **B** | Google 900 万变更；小批量与更好的审查结果相关 |
| 先写预测，再看 diff | **C** | 生成/检索效应 + 自动化偏差（Goddard 2011）；没有直接 RCT |
| 用 checklist | **B** | 小样本实验里清单法比最差方法缺陷发现率高约 30% |
| 审测试 + 变异测试，而不是逐行读实现 | **B/C** | 测试是意图的压缩；但 AI 测试可能同义反复，覆盖率≠质量 |
| 审 spec/意图，而不是语法 | **C** | Bacchelli 说“理解”是核心；Beller 说审查主要抓 maintainability；没有 RCT |
| 让 AI 生成 walkthrough/架构图 | **C/风险** | 解释会增加对正确和错误答案的依赖；CoT 可能不忠实；只当假设 |
| 按风险抽样，而不是随机抽样 | **C** | 统计抽样假设过程稳定；AI 代码缺陷可能相关，随机抽样危险 |
| 每周无 AI 时段 | **C** | 检索/间隔/生产性失败间接支持 |
| 重写关键 AI 代码 | **C** | 生成效应/自我解释间接支持 |

**三条最重要的“审意图不审语法”操作：**

1. **先读测试，再读实现。** 测试是意图的压缩，通常比实现短一个数量级；但要求测试是从 spec 写的，不是从实现反推的。反推的测试会复制同一个误解。
2. **先问“什么会让它错”，而不是“它做了什么”。** 让 AI 给 3 个失败模式和对应的可执行验证；你自己跑一遍。解释是假设，执行才是证据。
3. **把 review 当“理解仪式”，不是“找 bug 仪式”。** Bacchelli 的结论是理解变更才是核心；Beller 的数据说 review 主要抓 maintainability。把 review 当成“我能不能接管这段代码”的检查，比当成“最后一道 bug 过滤器”更现实。

**关于 AI walkthrough。** 2025 年 CHI 的预注册实验（N=308）发现：解释会同时增加对**正确**和**错误**答案的依赖；提供来源或让解释出现不一致，才会降低对错误答案的依赖。2023 年的工作还发现，思维链解释可以系统性地掩盖模型真正的决策依据。所以 walkthrough 只能用来**生成阅读路线和假设**，不能用来**证明正确性**——让它列出改动点、不变量、失败模式、最不确定的地方，然后逐条用测试/运行验证。

**审测试的陷阱：** AI 可以写出覆盖率高、却只断言当前行为的测试；判断标准是**可失败性**——故意改坏一行，测试会不会红？变异测试可以把这点变成数字，但成本较高，适合关键模块。

**抽样只应按风险：** 认证/支付/迁移/加密/并发/外部输入/依赖变更/CI 配置全审，纯 UI 文案和样板可抽检；随机抽样会漏掉整类风险。这是推理，不是实验结论。

### 1.5 理解跟不上时的降速策略

**核心原则：不要让 AI 的生成速度决定你的理解速度；用“检查点”把两者解耦。**

1. **任务粒度**：一个 PR 只做一个概念；目标 ≤200 行；超过 400 行必须拆。把“拆 PR”写进 agent 指令，而不是事后人工拆。
2. **计划检查点**：先让 AI 给 5 行计划、验收标准、非目标；你批准后再写代码。审 1 页计划的成本远低于审 500 行 diff。
3. **测试检查点**：先写 failing test，再实现；测试必须能失败。不要让 AI 从自己的实现反写测试。
4. **理解检查点**：每 100–200 行停一次，用 3 句话复述“做什么/为什么/何时失败”。不能复述就停——这就是“红档”。
5. **合并检查点**：绿/黄/红分级（见 2.3）；红档不合并。
6. **WIP 限制**：学习型任务同时只开一个 agent；routine 任务可并行，但审核队列要限额。herdr 里一个 pane 放学习型 agent，一个放 routine agent，不要开五个 agent 产出你审不过来的代码。

---

## 2. 对委托人的可落地建议

### 2.1 个人“理解与技能”维护方案

**标准版：每天 45 分钟（不含审核），每周 3–3.5 小时，每月 2.5 小时。** 原则是“先自己产生，再让 AI 介入；先检索，再看答案”。

| 时段 | 时长 | 动作 | 产出 |
|---|---|---|---|
| 每天·早上 | 15 min | **无 AI 热身**：从记忆写一个函数 + 3 个测试；或遮住 AI 版本，重写昨天的一小段 | 可运行代码 + 卡点 |
| 每天·审核前 | 10 min | **先预测**：写下预期行为、涉及文件、一个失败模式，再打开 diff | 3 行预测 |
| 每天·午后 | 15 min | **Tutor mode**：选一个新概念，只问提示、自己写；用 Claude Code Learning 或 Study Mode | 自己写的一段代码 + 一个问题 |
| 每天·结束前 | 5 min | **学习日志**：3 句话解释今天的变更 + 1 个不变量 + 1 个仍不懂的点 | 日志条目 |
| 每周 | 90 min | **无 AI build**：一个小功能端到端（读代码、写测试、实现、跑 CI、自审） | 一个真实交付 |
| 每周 | 45 min | **重写与对比**：挑 100–200 行 AI 代码，遮住重写，diff，列出语义差异 | 差异清单 |
| 每周 | 30 min | **审核校准**：先预测 3 个缺陷，再跑测试/变异/另一个模型，记录漏检 | 漏检率 |
| 每周 | 15 min | **间隔复习**：学习日志 + 3 个概念自测 | 复习记录 |
| 每月 | 2 h | **无 AI 重建**：一个小模块或一道 kata，从零到可运行 | 可运行代码 |
| 每月 | 30 min | **理解债审计**：列出不能解释的模块，选一个排期 | 债清单 |

**忙碌周最低版：每天 20 分钟，每周 90 分钟。** 每天 10 分钟无 AI 写 + 5 分钟预测 + 5 分钟日志；每周 60 分钟无 AI build + 30 分钟审核校准；每月 2 小时重建不变。**最低版不能砍掉“无 AI build”**，它是防止能力萎缩的锚点。

**执行要点：** “无 AI”允许查文档和代码库，不允许补全/聊天/agent；卡住 15 分钟先写卡点，结束后再问提示。“先预测”是打开 diff 前写三行：改哪两个文件、输入输出、最可能坏的边界。“重写”是选 100–200 行未来要维护的代码，遮住 AI 版本从测试/spec 重写，diff 只看语义差异。

### 2.2 审核清单：审 AI 产出时最该看的 7 个问题

| # | 问题 | 为什么 | 不合格时 |
|---|---|---|---|
| 1 | **意图**：能否用一句话说清“什么变了、为什么、成功标准”？ | 没有意图就无法判断对错；AI 最容易在“看起来合理”上偏 | 退回补 spec/验收标准 |
| 2 | **复述**：不看代码，我能否说出输入、输出、失败模式？ | 理解是审查的核心；不能复述就是理解债 | 红档：拆小/补学习块 |
| 3 | **可失败测试**：测试是从 spec 写的吗？故意改坏一行会红吗？ | 测试是意图的压缩；AI 测试可能同义反复 | 补测试/变异测试 |
| 4 | **边界**：空/大/并发/超时/重试/部分失败/权限/离线，哪些覆盖？哪些明确不覆盖？ | AI 代码常在“正常路径”上很漂亮，在边界上静默出错 | 列出未覆盖项，决定接受/补 |
| 5 | **契约与爆炸半径**：API/schema/迁移/配置/依赖/权限/错误码，谁受影响？能否回滚？ | AI 容易跨层改动而不自知；不可逆变更最贵 | 分阶段/加开关/拆 PR |
| 6 | **复杂度**：是否新增重复、抽象、全局状态、隐式耦合？能否更简单？ | AI 倾向“再加一层”；被采纳的 AI 建议平均增加复杂度 | 要求简化或说明理由 |
| 7 | **安全与可观测**：最坏情况是什么？密钥/PII/注入/供应链？出问题怎么知道？5 分钟怎么回滚？ | 有 AI 辅助的开发者更自信但代码更不安全；review 不是安全控制 | 加 SAST/依赖扫描/日志/告警 |

**加一条“on-call 测试”：** 我愿意为这段代码 on-call 吗？不愿意的原因通常就是上面某一条。

**清单用法：** 绿档只过 1/3/5，黄档全过，红档先停。Cisco 小样本实验里清单法比最差方法缺陷发现率高约 30%，但清单要短、可执行、每周按漏检调整。

### 2.3 审核分级与预算

| 档 | 条件 | 动作 | 预算 |
|---|---|---|---|
| **绿** | 能复述 + 测试可失败 + 可回滚 + 单模块 | CI 通过 + 抽检 10–20% 的绿档变更 | 5–10 min |
| **黄** | 能复述，但跨模块/迁移/性能/安全 | 全清单 + 分阶段 + 观察 | 30–60 min |
| **红** | 不能复述，或没有可失败测试，或不可逆 | 不合并；拆小/补测试/排学习块 | 另排 60–90 min |

**每日预算：60–90 分钟深度审核，分 2 段，每段 ≤45 分钟。** 超过预算时，不要“加速审”，而是：
1. 拒绝/拆分过大的变更；
2. 只放行绿档；
3. 黄/红档排到明天；
4. 在 `review-queue.md` 里记录“审核债”，像技术债一样每周看一次。

**容量参考：** 90 分钟 × 300 LOC/h ≈ 450 行/天，5 天约 2,250 行/周；超过这个量就必须在“减少产出、提高自动化杠杆、风险抽样”中选，否则就是在借 comprehension debt。

### 2.4 具体配置与提示词

**1）给 agent 的项目指令（`CLAUDE.md` / `AGENTS.md`）：**

```text
工作方式：
- 先给 5 行计划和验收标准，等我确认后再改代码。
- 单次 diff ≤200 行；超过就拆成多个 PR。
- 先写/改测试，再写实现；测试必须在实现错误时失败。
- 不要跨模块重构、不要升级依赖，除非单独 PR。
- 完成后给我：改了什么、为什么、如何验证、如何回滚、我仍需理解的点。
- 不要用大段解释替代测试；每个关键断言要有可执行的验证。
```

**2）Claude Code 输出风格：** 学新东西用 `/output-style Learning`（解释选择，留小段代码给你写）；读不熟悉的代码用 `Explanatory`；routine 用 `Default`/`Concise`。输出风格是指令不是保证，关键还是提示词和验收。

**3）只给提示的教练提示词：**

```text
你是我的编程教练，不是代码生成器。不要给完整实现。
先用一个问题检查我的理解；每次只给一个提示；我写完后你再指出错误，
并给一个更小的下一步练习。如果我直接要答案，提醒我先尝试。
```

**4）PR 大小守卫（本地 pre-push 示例）：**

```bash
lines=$(git diff --numstat origin/main...HEAD | awk '{a+=$1; d+=$2} END {print a+d}')
if [ "$lines" -gt 400 ] && [ "$ALLOW_LARGE" != "1" ]; then
  echo "Diff too large: $lines lines. Split it or set ALLOW_LARGE=1."
  exit 1
fi
```

**5）学习日志模板：**

```markdown
## YYYY-MM-DD
- 今天我不看 AI 也能写出的：...
- 今天我能解释的变更：...
- 仍不能解释的：...
- 明天要拆小的：...
```

**6）每周只看 5 个指标：** 无 AI 小时数、重写 LOC、审核漏检数、不能解释的模块数、红档 PR 数。不要用“AI 生成了多少行”当生产力指标；它只会奖励你最不需要的行为。

---

## 3. 争议与不确定

1. **METR 的结果已经过时。** 2025 年的 19% 变慢是“早期工具 + 资深维护者 + 大型仓库”的快照；2026 年后续实验因选择偏差不可靠。不要用它证明“AI 无用”，也不要否定别人的加速体验。
2. **Anthropic 的样本小、周期短、任务非 agentic。** 52 人、一次测验、以初级为主；作者自己说 agentic 工具影响可能更严重；交互模式是观察性的，不能当因果。
3. **MIT 的“认知债”是预印本。** 54 人、写作任务、EEG 连接性；样本小，指标解释有争议，不能直接外推到编程。它适合当“机制假设”，不适合当“定论”。
4. **Microsoft/CMU 是自报调查。** “批判性思维”是自评，不是能力测试；相关不等于因果。
5. **200–400 LOC/h 来自 2006 年的单一产品组。** 观察性数据，LOC 不是复杂度的好 proxy；AI 代码语义密度不同，数字可能偏移，但目前没有更好的大规模替代数据。
6. **“审测试”有陷阱。** AI 可以从实现反写测试，让测试变成同义反复；必须用“可失败性”/变异测试校验。
7. **学习模式缺乏独立效果证据。** Claude Code Learning、ChatGPT Study Mode 设计合理，但没有公开 RCT；Khanmigo 的两年 RCT 效果也不大（约 0.06–0.08 SD/年），且使用频率低。
8. **人工 review 不是安全控制。** 2026 年预印本中，100+ 名开发者在 5 小时任务里与 agent 协作，无监控时 94% 没发现恶意插入；即使有正确告警，56% 仍被攻破。这是对抗性长时实验，不能直接外推，但说明 **review 必须和自动化检查、权限隔离、可回滚一起用**。

---

## 4. 参考来源

### 技能形成与学习

1. Shen, J. H., & Tamkin, A. (2026). *How AI Impacts Skill Formation.* arXiv:2601.20245. https://arxiv.org/abs/2601.20245
2. Anthropic (2026-01-29). *How AI assistance impacts the formation of coding skills.* https://www.anthropic.com/research/AI-assistance-coding-skills
3. Becker, J., Rush, N., Barnes, B., & Rein, D. (2025-07-10). *Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity.* METR. https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/
4. METR (2026-02-24). *We are Changing our Developer Productivity Experiment Design.* https://metr.org/blog/2026-02-24-uplift-update/
5. Lee, H.-P., Sarkar, A., Tankelevitch, L., Drosos, I., Rintel, S., Banks, R., & Wilson, N. (2025). *The Impact of Generative AI on Critical Thinking: Self-Reported Reductions in Cognitive Effort and Confidence Effects From a Survey of Knowledge Workers.* CHI 2025. https://doi.org/10.1145/3706598.3713778
6. Kosmyna, N., et al. (2025). *Your Brain on ChatGPT: Accumulation of Cognitive Debt when Using an AI Assistant for Essay Writing Task.* arXiv:2506.08872. https://arxiv.org/abs/2506.08872
7. Bastani, H., Bastani, O., Sungu, A., Ge, H., Kabakcı, Ö., & Mariman, R. (2025). *Generative AI without guardrails can harm learning: Evidence from high school mathematics.* PNAS. https://doi.org/10.1073/pnas.2422633122
8. Kestin, G., Miller, K., Klales, A., Milbourne, T., & Ponti, G. (2025). *AI tutoring outperforms in-class active learning: an RCT introducing a novel research-based design in an authentic educational setting.* Scientific Reports. https://doi.org/10.1038/s41598-025-97652-6
9. Oreopoulos, P., & Low, N. (2026). *One Click Away: AI Tutoring with Khanmigo in a Two-Year School Experiment.* NBER Working Paper 35620. https://doi.org/10.3386/w35620
10. Macnamara, B. N., Hambrick, D. Z., & Oswald, F. L. (2014). *Deliberate Practice and Performance in Music, Games, Sports, Education, and Professions: A Meta-Analysis.* Psychological Science. https://doi.org/10.1177/0956797614535810
11. Ruitenburg, S. K., et al. (2026). *A Meta-Analysis of the Effectiveness and Boundary Conditions of Retrieval Practice, Distributed Practice, and Interleaved Practice in Authentic School Classrooms.* Educational Psychology Review. https://doi.org/10.1007/s10648-026-10225-5
12. Murray, E., Horner, A. J., & Goebel, S. M. (2025). *A Meta-analytic Review of the Effectiveness of Spacing and Retrieval Practice for Mathematics Learning.* Educational Psychology Review. https://doi.org/10.1007/s10648-025-10035-1
13. Kapur, M., & Bielaczyc, K. (2011). *Designing for Productive Failure.* Journal of the Learning Sciences. https://doi.org/10.1080/10508406.2011.591717
14. Chi, M. T. H., Bassok, M., Lewis, M. W., Reimann, P., & Glaser, R. (1989). *Self-Explanations: How Students Study and Use Examples in Learning to Solve Problems.* Cognitive Science. https://doi.org/10.1207/s15516709cog1302_1
15. Tamang, L. J., Alshaikh, Z., Khayi, N. A., Oli, P., & Rus, V. (2021). *A Comparative Study of Free Self-Explanations and Socratic Tutoring Explanations for Source Code Comprehension.* SIGCSE 2021. https://doi.org/10.1145/3408877.3432423
16. Sparrow, B., Liu, J., & Wegner, D. M. (2011). *Google Effects on Memory: Cognitive Consequences of Having Information at Our Fingertips.* Science. https://doi.org/10.1126/science.1207745
17. Risko, E. F., & Gilbert, S. J. (2016). *Cognitive Offloading.* Trends in Cognitive Sciences. https://doi.org/10.1016/j.tics.2016.07.002

### 审核容量与代码审查

18. Cohen, J. (2006). *Code Review at Cisco Systems.* In *Best Kept Secrets of Peer Code Review.* SmartBear. https://static1.smartbear.co/support/media/resources/cc/book/code-review-cisco-case-study.pdf
19. Cohen, J., Teleki, S., & Brown, E. (2006). *Best Kept Secrets of Peer Code Review.* SmartBear. https://static1.smartbear.co/support/media/resources/cc/book/best-kept-secrets-of-peer-code-review.pdf
20. Sadowski, C., Söderberg, E., Church, L., Sipko, M., & Bacchelli, A. (2018). *Modern Code Review: A Case Study at Google.* ICSE-SEIP 2018. https://doi.org/10.1145/3183519.3183525
21. Bacchelli, A., & Bird, C. (2013). *Expectations, Outcomes, and Challenges of Modern Code Review.* ICSE 2013. https://doi.org/10.1109/ICSE.2013.6606617
22. Beller, M., Bacchelli, A., Zaidman, A., & Juergens, E. (2014). *Modern Code Reviews in Open-Source Projects: Which Problems Do They Fix?* MSR 2014. https://doi.org/10.1145/2597073.2597082
23. McIntosh, S., Kamei, Y., Adams, B., & Hassan, A. E. (2014). *The Impact of Code Review Coverage and Code Review Participation on Software Quality: A Case Study of the Qt, VTK, and ITK Projects.* MSR 2014. https://doi.org/10.1145/2597073.2597076
24. Zhong, S., Noei, S., & Zou, Y. (2026). *Human-AI Synergy in Agentic Code Review.* arXiv:2603.15911. https://arxiv.org/abs/2603.15911
25. Perry, N., Srivastava, M., Kumar, D., & Boneh, D. (2023). *Do Users Write More Insecure Code with AI Assistants?* CCS 2023. https://doi.org/10.1145/3576915.3623157

### 理解债、过度依赖与解释风险

26. Osmani, A. (2026-03-14). *Comprehension Debt — the hidden cost of AI generated code.* https://addyosmani.com/blog/comprehension-debt/
27. Storey, M.-A. (2026). *From Technical Debt to Cognitive and Intent Debt: Rethinking Software Health in the Age of AI.* arXiv:2603.22106. https://arxiv.org/abs/2603.22106
28. Ahmad, M. O. (2026). *Comprehension Debt in GenAI-Assisted Software Engineering Projects.* arXiv:2604.13277. https://arxiv.org/abs/2604.13277
29. Goddard, K., Roudsari, A., & Wyatt, J. C. (2011). *Automation bias: a systematic review of frequency, effect mediators, and mitigators.* JAMIA. https://doi.org/10.1136/amiajnl-2011-000089
30. Kim, S. S. Y., Vaughan, J. W., & Liao, Q. V. (2025). *Fostering Appropriate Reliance on Large Language Models: The Role of Explanations, Sources, and Inconsistencies.* CHI 2025. https://doi.org/10.1145/3706598.3714020
31. Turpin, M., Michael, J., Perez, E., & Bowman, S. R. (2023). *Language Models Don't Always Say What They Think: Unfaithful Explanations in Chain-of-Thought Prompting.* NeurIPS 2023. https://arxiv.org/abs/2305.04388
32. Panickssery, A., Bowman, S. R., & Feng, S. (2024). *LLM Evaluators Recognize and Favor Their Own Generations.* NeurIPS 2024. https://arxiv.org/abs/2404.13076
33. Ye, J., Zou, H., & Yu, S. (2026). *Coding with "Enemy": Can Human Developers Detect AI Agent Sabotage?* arXiv:2606.05647. https://arxiv.org/abs/2606.05647

### 产品文档、行业报告与其他

34. Anthropic. *Claude Code Output Styles.* https://docs.claude.com/en/docs/claude-code/output-styles
35. OpenAI (2025). *Introducing study mode in ChatGPT.* https://openai.com/index/chatgpt-study-mode/
36. Veracode (2025-07-25). *2025 GenAI Code Security Report.* https://www.veracode.com/blog/genai-code-security-report/
37. Peng, S., Kalliamvakou, E., Cihon, P., & Demirer, M. (2023). *The Impact of AI on Developer Productivity: Evidence from GitHub Copilot.* arXiv:2302.06590. https://arxiv.org/abs/2302.06590
38. Sarsa, S., Denny, P., Hellas, A., & Leinonen, J. (2022). *Automatic Generation of Programming Exercises and Code Explanations Using Large Language Models.* ICER 2022. https://doi.org/10.1145/3501385.3543957
