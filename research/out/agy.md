# 通用人机决策授权框架：从代码工程到生活自动化

## 1. 一句话结论

AI 自主权绝非非黑即白的“全放手”或“全手动”，而应以**动作可逆性、影响半径、第三方涉入度及外部环境写权限**为核心维度，构建**确定性分级授权与审批路由**；个人生活自动化的最佳起步策略是**“高频只读预处理与草稿暂存（Read & Draft），人工终审落槌（One-Click Commit）”**，在消除认知过载的同时守牢安全与责任底线。

---

## 2. 关键发现

### 2.1 自主度分级框架演进：从工业监控到认知代理

1. **Sheridan–Verplank 10 级自动化与 Parasuraman 四阶段模型**
   - **理论核心**：Sheridan 与 Verplank（1978）提出了人机交互的 10 级自动化阶梯（从 L1 全人工到 L10 计算机完全忽略人类）。Parasuraman、Sheridan 和 Wickens（2000）进一步提出：**自动化不是单一开关，而是覆盖信息处理的 4 个阶段**：
     1. 信息获取（Information Acquisition，数据抓取与过滤）
     2. 信息分析（Information Analysis，整合推演与归纳）
     3. 决策选择（Decision Selection，形成备选方案）
     4. 动作执行（Action Implementation，真实世界生效）
   - **对现代 Agent 的启示**：AI 代理常在阶段 1 和 2 处于极高自主（L8–L10），但在阶段 3 和 4 必须受到制约。Sheridan 划分的关键节点是：**L4**（建议单一方案）、**L5**（人类批准后执行，Positive Consent）、**L6**（限时否决期，超时自动执行，Veto Window）、**L7**（自动执行后必须通知人类）。
   - **来源**：[Parasuraman, Sheridan, & Wickens (2000), IEEE Trans. Systems, Man, and Cybernetics](https://ieeexplore.ieee.org/document/844354)

2. **SAE J3016 自动驾驶分级的类比与认知局限**
   - **理论核心**：SAE 分级的核心界限在于 **L2 vs L3** 的动态任务后援（DDT Fallback）由谁承担。L2 必须由人类时刻监控且对事故负全责；L3 仅在特定运行设计域（ODD）内由系统承担后援，系统失效时才请求人类接管。
   - **对 Agent 的映射**：当前个人与编码 Agent 绝大多数本质属于 **“认知 L2”**。将 Agent 盲目视为 L4/L5 会引发严重的**自动化自满（Automation Complacency）**，在遭遇未预期输入时导致灾难性失误。
   - **来源**：[SAE J3016 (2021 Update), Driving Automation Systems](https://www.sae.org/standards/content/j3016_202104/)

3. **Knight First Amendment Institute 的 5 级 AI 自主度模型**
   - **理论核心**：Feng, McDonald, Zhang（2024 年 4 月）提出应从**“人类扮演的角色”**划分 AI Agent 的 5 级自主度：
     - **Level 1 Operator（操作员）**：人类主导，Agent 仅为被动执行微指令的工具；
     - **Level 2 Collaborator（协作者）**：人机平级共同推演与反复迭代；
     - **Level 3 Consultant（顾问）**：Agent 主动推进，遇歧义主动向人类求助；
     - **Level 4 Approver（审批人）**：Agent 独立规划并打包方案，经人类审批（HITL Gate）后才执行；
     - **Level 5 Observer（观察者）**：Agent 长周期完全自主运转，人类仅做日志审计并保留熔断开关。
   - **来源**：[Feng, McDonald, & Zhang (2024), Knight First Amendment Institute / arXiv:2404.14482](https://knightcolumbia.org/content/levels-of-autonomy-for-ai-agents)

4. **前沿技术演进（Anthropic & OpenAI）**
   - OpenAI 于 2024 年 7 月公布 5 级路线图（Chatbots → Reasoners → Agents → Innovators → Organizations）。
   - Anthropic 在《Building Effective Agents》（2024 年 12 月）中强调优先使用确定性工作流模式（Routing、Orchestrator-Workers、Evaluator-Optimizer），避免无约束黑盒代理，并警告**“审批疲劳（Approval Fatigue）”**是阻碍 HITL 落实的关键障碍。
   - **来源**：[Anthropic: Building Effective Agents (2024-12)](https://www.anthropic.com/research/building-effective-agents)

---

### 2.2 决策分类维度与管理学授权映射

1. **核心决策判定维度**：
   - **可逆性（Reversibility）**：Bezos 的单向门（Type 1，不可逆、高代价）与双向门（Type 2，低成本可逆）理论。双向门大力下放自主权；单向门必须保留强审批。
   - **影响半径（Blast Radius）**：本地暂存文件 vs 全局系统配置；单行代码重构 vs 生产数据库迁移。
   - **财务与法律敞口（Financial / Legal Stake）**：涉及资金支付、正式签约、法律合规等不可免责事项。
   - **外部关系涉入度（External Stakeholders）**：个人私有可见 vs 外部客户、商业伙伴、公众可见。外部沟通一旦发错，声誉修复成本极高。
   - **隐私与安全性（Privacy & Security）**：公开数据 vs 密码凭据、API Token、银行对账单、个人健康数据。
   - **Cynefin 复杂性领域**：清晰（Clear，规则驱动，完全代劳）、繁复（Complicated，多方案权衡，AI 作顾问）、复杂（Complex，需人机小步探索）、混沌（Chaotic，突发危机，必须人类接管）。

2. **管理学框架映射到人机协作**：
   - **RACI 矩阵的人机铁律**：**Accountable（最终问责者，A）永远必须是人类**，法律与道德主体无法由算法代持；AI 仅可充当 Responsible（执行者，R）、Consulted（顾问，C）或 Informed（被通知者，I）。
   - **Management 3.0 Delegation Poker（七级授权法）映射**：
     - *L1 Tell*：人类决策，命令 AI 执行微操作；
     - *L2 Sell*：人类决策，向 AI 解释目标以生成实现；
     - *L3 Consult*：人类决策前，AI 提供多方案利弊对比；
     - *L4 Agree（强审批）*：AI 规划方案，人类批准后方可执行（对应 Knight Approver）；
     - *L5 Advise（撤回窗口）*：AI 默认调度执行，预留人类限定否决窗口；
     - *L6 Inquire（事后汇报）*：AI 自动执行，事后以摘要（Digest）汇报；
     - *L7 Delegate（完全放权）*：受限沙箱内静默闭环运行，仅异常时告警。
   - **Eisenhower 矩阵映射**：重要紧急（人机协同即时攻坚）、重要不紧急（人深思+AI顾问）、紧急不重要（AI 自动处理并事后通报）、不重要不紧急（AI 批量静默归档过滤）。

---

### 2.3 Human-in-the-loop (HITL) 生产级设计模式与产品实践

1. **五大核心工程模式**：
   - **审批闸门（Positive Confirmation Gates）**：执行写操作前挂起，直观渲染 Diff 或载荷，等待显式确认。
   - **配额与上限约束（Hard Rate/Spending Caps）**：限制调用步数、API 费用上限及单笔事务金额。
   - **草稿暂存区模式（Staging / Draft-then-Commit）**：写操作先落入暂存区（如邮件存为 Draft、日历建立 Tentative Event、代码写入临时分支），由人类触发最终 Commit。
   - **延时撤销窗口（Undo / Cooldown Window）**：触发后进入 30 秒至 15 分钟的冷却队列，允许一键 Abort。
   - **异步汇总简报（Batch Digest Approval）**：解决审批疲劳的核心手段，将数十次微小决策聚合为每日清单一次性勾选确认。

2. **主流前沿产品落地设计**：
   - **OpenAI Operator（2025 年 1 月，CUA 模型）**：遇到**账户登录（Logins）**、**支付结账（Payments）**、**人机验证（CAPTCHA）**时，强制挂起并弹出悬浮窗交由人类接管，绝不代持敏感凭据。
     - *来源*：[OpenAI: Introducing Operator (2025-01)](https://openai.com/index/introducing-operator/)
   - **Anthropic Claude Computer Use & Claude Code（2024–2025 年）**：运行于隔离沙箱；写操作与 Bash 命令实行权限白名单；针对审批疲劳，通过分级权限模式（Permission Modes）与路径规则取代单步漫天弹窗。
     - *来源*：[Anthropic: Computer use countermeasures (2024-10)](https://www.anthropic.com/news/3-5-models-and-computer-use-countermeasures)

---

### 2.4 个人生活自动化落地生态与“甜蜜点”

1. **主流开源与自建工具栈**：
   - **n8n**：支持本地 Docker 部署，内建原生 AI Agent 节点、LangChain 生态与 Tool Calling，可视化编排“触发 → 推理 → 工具查询 → 分支路由 → Telegram/Slack 交互式审批按钮”。
   - **Home Assistant + Assist + MCP**：2024 年底至今，社区全面转向 **Model Context Protocol (MCP)** 动态工具检索，摆脱了以往“实体全量 Dump”导致每次消耗上万 Token 的弊端，结合 Ollama（Qwen 2.5 / Llama 3）可实现完全离线隐私控制。
   - **个人知识库（Obsidian / Notion）**：通过 MCP Server 或本地插件实现跨上下文检索与笔记自动归档。

2. **收益与风险矩阵（寻找“甜蜜点”）**：
   - **甜蜜点（Sweet Spot：高收益、极低风险）**：纯只读聚合分析（RSS 摘要、论文阅读、全网热点）、非破坏性元数据提取（发票 OCR、快递跟踪）、代码测试用例生成。
   - **高危深水区（High Risk：坚决不可完全自动）**：自主对外发信与社交言论、金融支付与扣款、不可恢复的文件物理删除。

---

### 2.5 真实安全威胁向量与公开事故警示

1. **间接提示词注入（Indirect Prompt Injection, XPIA）**：
   - Simon Willison（2022 年命名）与 Johann Rehberger（Embrace The Red）反复证明：LLM 在底层无法绝对区分“控制指令”与“外部数据”。当 Agent 读取网页、邮件或第三方文档时，恶意指令会被视同系统指令执行。
   - **Slack AI 私有数据泄露事故（2024 年 8 月，PromptArmor 披露）**：攻击者在公共渠道嵌入隐藏指令，受害者使用 Slack AI 总结项目时，恶意指令诱导模型将私有频道的 API Key 拼接入 Markdown 外部图片链接中，渲染时直接回传攻击者服务器。
     - *来源*：[PromptArmor: Slack AI Data Exfiltration (2024-08)](https://promptarmor.com/blog/slack-ai-data-exfiltration)
   - **ChatGPT 长期记忆中毒漏洞（2024 年 9 月，Johann Rehberger 披露）**：利用间接注入，受污染文档可指令 ChatGPT 长期记忆库悄悄存入恶意指令（SpAIware），形成跨独立会话的持久化劫持与数据渗出。
     - *来源*：[Johann Rehberger: ChatGPT Persistent Memory Leak (2024-09)](https://embracethered.com/blog/posts/2024/chatgpt-cross-session-data-leak/)
2. **过度代理（Excessive Agency - OWASP Top 10 LLM08）**：
   - 开发者赋予 Agent 超出需求的写权限或 Shell 权限，导致注入发生时破坏性成倍放大。
   - **防御黄金准则**：采用**双模型架构（Dual-LLM）**，负责读取外部不可信数据的模型不挂载任何写工具；网络出口做严格域名白名单拦截（Egress Filtering）。

---

## 3. 对委托人的可落地建议

### 3.1 统一“决策路由”框架（The Universal Decision Router, UDR）

该框架输入为**“一个待执行动作（Action Request）”**，通过 5 维打分模型输出其**自主度授权等级（L0–L4）**，同时适用于代码与生活。

```
                    ┌──────────────────────────────┐
                    │    待执行动作 (Action)       │
                    └──────────────┬───────────────┘
                                   │
                     [ 触发一票否决检查 (Veto)? ]
                                   ├────────────────────── 是 ──> L4 (人类绝对决策)
                                   │ 否
                     [ 计算 5 维风险综合得分 (0-100) ]
                                   │
          ┌────────────────────────┼────────────────────────┬──────────────────────┐
          ▼                        ▼                        ▼                      ▼
      0 - 15 分                16 - 35 分               36 - 60 分             61 - 100 分
   L0: Full Auto            L1: Auto & Notify       L2: Undo Window         L3: Staging Draft
   (静默完全自主)            (自动执行+汇总通知)      (先执行+延时撤回窗口)    (暂存草稿+人工落槌)
```

#### 1. 评估五大维度与打分规则（总分 0–100 分）

| 维度代码 | 评估维度 | 权重 | 低风险 (0-5分) | 中风险 (10-15分) | 高风险 (20-25分) |
| :--- | :--- | :---: | :--- | :--- | :--- |
| **$D_1$** | **可逆性** (Reversibility) | 25% | 完全双向门：无写副作用，或一键 Git Revert / 回收站撤回 | 受限可恢复：需消耗一定时间或手工排查才能撤销 | 单向门：物理删除、外发公开信、生产 DB drop、资金流转 |
| **$D_2$** | **影响半径与财务** (Blast Radius & Stake) | 25% | 本地临时暂存区；金额 0 元 | 单个模块/当前工程；金额 <50元 | 生产环境、全局系统配置；金额 >100元或具法律效力 |
| **$D_3$** | **外部关系涉入度** (Social Exposure) | 20% | 纯委托人私有可见，无外部主体参与 | 内部协作团队或熟人事务（非敏感日常事务） | 外部客户、商业合作伙伴、公共社交网络公开互动 |
| **$D_4$** | **数据敏感度** (Privacy & Security) | 15% | 公开数据、脱敏技术文档、公网新闻 | 个人内部一般笔记、日常作息、非涉密源码 | 密码凭据、API Token、银行对账单、个人核心隐私 |
| **$D_5$** | **输入受信度与注入面** (Untrusted Surface) | 15% | 100% 委托人自己写的指令，无外部不可信输入 | 混入半受信文档（如常用官方文档、可信代码库） | 直接摄取公网任意网页、来历不明邮件、公开群聊 |

**一票否决规则（Hard Veto to L4）**：
若动作涉及以下任意一项，直接归入 **L4**，禁止自动打分降级：
1. 涉及信用卡扣款、银行转账、资金划付；
2. 明文读取或写入 Master 密码、SSH 私钥、生产 API Key；
3. 对外部客户或公众的首次正式商务沟通；
4. 不可恢复的物理删除（如 `rm -rf`、清空云盘）。

#### 2. 自主度分级输出（L0–L4）与执行协议

- **L0: Full Auto（静默自主）** `[0 - 15 分]`：AI 自主执行，无弹窗中断，执行记录静默写入后台日志。
- **L1: Auto & Notify（执行后汇报）** `[16 - 35 分]`：AI 自动调度执行，通过每日 Digest 或即时推送告知人类。
- **L2: Undo Window / Exception Veto（带撤回窗口执行）** `[36 - 60 分]`：AI 触发动作后预留 **30 秒至 15 分钟撤回窗口**并发送预警，超时无人否决方才生效。
- **L3: Propose-then-Commit / Staging（暂存草稿，人工终审）** `[61 - 100 分]`：AI 完成全部准备工作，生成 **Diff / Draft / 预定单**，绝不触碰 Commit。推送带“Approve / Reject”的卡片，人工点击放行。
- **L4: Human Must Decide（人类独裁，AI 仅当顾问）** `[一票否决]`：AI 仅充当 Level 3 顾问输出对比分析，所有执行动作必须由人类在原生平台手工完成。

---

### 3.2 生活场景示例表（15 个具体场景判定）

| 序号 | 生活场景描述 | 可逆 $D_1$ | 影响 $D_2$ | 涉外 $D_3$ | 隐私 $D_4$ | 注入 $D_5$ | 综合得分 | 建议等级 | 判定理由与防踩坑规则 |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| 1 | **技术播客与 RSS 每日提炼早报** | 0 | 0 | 0 | 0 | 10 | **10** | **L0** | 纯只读场景，无破坏性，直接推送阅读。 |
| 2 | **订阅类邮件自动归档与打标签** | 5 | 5 | 0 | 5 | 10 | **25** | **L1** | 仅更改标签未删除邮件，每日汇总通报一次。 |
| 3 | **下载目录根据文件类型自动整理** | 10 | 10 | 0 | 5 | 0 | **25** | **L1** | 本地按后缀分类归档，保留原文件，极易恢复。 |
| 4 | **电子发票识别并提取结构化记账数据** | 0 | 5 | 0 | 15 | 5 | **25** | **L1** | 仅做 OCR 结构化提取存入暂存数据库，不扣款。 |
| 5 | **根据日历行程离家时自动调低空调** | 10 | 10 | 0 | 5 | 5 | **30** | **L1** | 智能家居状态调节，可逆性强，手机可随时覆盖。 |
| 6 | **代码库依赖安全漏洞自动提 PR 升级** | 5 | 15 | 0 | 5 | 15 | **40** | **L2** | 独立分支提 PR 并跑 CI，无冲突则通知自动合并。 |
| 7 | **外卖平台日常午餐定时自动续订** | 15 | 15 | 10 | 5 | 0 | **45** | **L2** | 小额扣款（<30元），设置 10 分钟撤回窗口通知。 |
| 8 | **日历中日常健身/专注时段防冲突占位**| 5 | 10 | 10 | 5 | 0 | **30** | **L2** | 个人日程占位，遇到会议冲突自动释放并提供撤销。 |
| 9 | **日常工作邮件回复草拟（等待批准发送）** | 20 | 15 | 20 | 10 | 15 | **80** | **L3** | **严禁自动发信！** 生成 Gmail Draft，弹窗确认。 |
| 10 | **基于健康手环异常数据生成问诊分析** | 0 | 15 | 0 | 20 | 5 | **40** | **L3** | 涉及健康决策，AI 仅汇总病症图表供人工就医参考。 |
| 11 | **跨时区商业客户会议时间协调与邀约** | 20 | 15 | 25 | 10 | 10 | **80** | **L3** | 涉及外部商务信任，委托人亲自核准后方可发送。 |
| 12 | **家庭智能门锁自动下发访客临时密码** | 20 | 20 | 10 | 20 | 5 | **75** | **L3** | 实体安防高风险，生成密码后必须人工核准激活。 |
| 13 | **个人信用卡还款与水电气费代扣缴纳** | 25 | 20 | 0 | 20 | 0 | **一票否决** | **L4** | **触碰财务资金！** 严禁交给 Agent，人工在银行完成。 |
| 14 | **根据行情异动自动触发证券调仓买卖** | 25 | 25 | 10 | 20 | 15 | **一票否决** | **L4** | 投资领域不可逆且剧烈波动，AI 仅出分析研报。 |
| 15 | **个人社交平台（X/微信）公开发文** | 25 | 20 | 25 | 10 | 15 | **一票否决** | **L4** | 声誉风险极高，易被注入劫持发表不当言论。 |

---

### 3.3 委托人起步的前 3 个生活自动化建议

针对委托人（Windows 环境、多 Agent 协同、希望兼顾自主与安全）的现状，推荐从**“零写风险、高认知释放”**的 3 个场景起步：

#### 建议 1：个人信息降噪“每日晨报 Agent”（RSS & Newsletter Digest）
- **核心定位**：纯只读聚合，**L0（抓取分析）+ L1（推送通报）**。
- **推荐工具栈**：Windows WSL2 或 Docker 本地运行 **n8n** + **Telegram Bot** + **Claude 3.5 Haiku / Gemini Flash API**。
- **具体落地方案**：
  1. *数据摄取*：n8n 设置每天早晨 7:30 定时触发，通过 RSS Feed Read 节点抓取委托人关注的技术博客、GitHub Trending、Substack 订阅。
  2. *清洗与降噪*：Code 节点去重，截取文章前 1500 字，批量送入 LLM 节点。
  3. *Prompt 规则*：
     > “你是一个严谨的信息过滤助手。按【重要架构突破】、【工具更新】、【高价值深度阅读】归纳。每篇限定 3 句话说明：核心痛点、实现原理、对独立开发者有何启发。过滤掉情绪化营销与纯公关稿件。”
  4. *推送呈现*：格式化为 Markdown 消息，由 Telegram 节点推送到个人频道。
- **安全与收益**：零外部写权限，无凭据泄露风险，每天为委托人节省 45 分钟刷手机的认知消耗。

#### 建议 2：非侵入式“邮件与会议暂存助手”（Email Triage & Staging Assistant）
- **核心定位**：暂存草稿模式，严格执行 **L3（Propose-then-Commit）**。
- **推荐工具栈**：**n8n** + **Gmail API** + **Google Calendar API** + **Telegram 交互式按钮**。
- **具体落地方案**：
  1. *触发与过滤*：Gmail Trigger 节点每 15 分钟拉取一次未读邮件（过滤掉 Spam 和营销邮件）。
  2. *智能分流与排查*：
     - 通知/账单类：自动打上 `Bot/Notice` 标签并归档（L1）；
     - 真人沟通/会议邀请：LLM 提取诉求与建议动作；若涉及邀约，调用 Google Calendar API 查询未来 3 天空闲时段。
  3. *草稿生成（绝不代发）*：调用 Gmail 节点的 `Create Draft` 生成专业回复草稿；同时在 Google Calendar 创建带 `[Tentative]` 标记的暂定日程。
  4. *通知与一键落槌*：向委托人 Telegram 发送卡片：
     > 📩 **新邮件待批**：张三请求探讨项目合作  
     > 💡 **AI 建议**：周四下午 3 点有空，已在 Gmail 生成草稿。  
     > [👉 查看草稿] | [✅ 确认发送 (Webhook)]
- **安全与收益**：消除写信冷启动阻力，同时守住“邮件绝不会由 AI 擅自发出”的安全底线。

#### 建议 3：生活财务“发票识别与记账草稿箱”（Receipt-to-Ledger Staging Pipeline）
- **核心定位**：本地数据暂存，**L1（提取）+ L3（批量确认）**。
- **推荐工具栈**：本地文件夹监听 + **Multimodal LLM (Gemini 1.5 Flash / GPT-4o-mini)** + **Notion Database**（或本地 Beancount / CSV）。
- **具体落地方案**：
  1. *采集*：监控发票邮件，或在 Windows 本地建立 `C:\Inbox\Receipts` 文件夹，手机拍发票同步至该目录。
  2. *多模态提取*：脚本或 n8n 调用多模态 API，结构化提取：消费日期、商户名称、金额、消费类目、发票代码。
  3. *写入暂存视图*：数据写入 Notion 的 `Transactions_Pending` 表，状态全部标记为 `Needs Review`。
  4. *周日批量落槌*：委托人每周日晚上打开 Notion，花 2 分钟快速扫视，无误后一键批量标记为 `Approved`，由脚本合并入主账本。
- **安全与收益**：免除手工记账繁琐，彻底避免 AI 误读金额引发财务错乱。

---

## 4. 争议与不确定

1. **间接提示词注入（XPIA）是否具备数学上的可防性？**
   - *现状与争议*：Simon Willison 及前沿安全研究员指出，由于 LLM 将“指令”与“数据”融合在同一序列中，目前在理论上**不存在能够 100% 免疫间接提示词注入的纯 Prompt 防御手段**。只要 Agent 拥有阅读不可信外部数据并调用写工具的权力，系统就存在潜在漏洞。目前的工业防护仅是降低概率，缺乏形式化安全保证。

2. **SAE 自动驾驶类比在认知任务中的边界模糊性**
   - *争议点*：自动驾驶的运行设计域（ODD）具有明确的物理几何边界（道路、天气、车速）；而人类认知工作（写代码、理解邮件意图）的边界极其发散。如何客观量化一段代码或一封邮件“是否超出了当前 Agent 的 ODD”？业界目前缺乏统一的置信度标尺，导致 Agent 往往在自信的状态下产生致命幻觉。

3. **HITL 的“审批疲劳”与“责任空心化”困境**
   - *争议点*：理论上所有 L3 动作都要求人类核准；但在实际工程中，若系统每天向用户推送超过 20 次批准请求，人类会迅速退化为“闭眼连点同意（Rubber-stamping）”，审批机制沦为形式主义。此时一旦发生事故，组织层面却会将责任完全推卸给“点击了同意的人类”，造成伦理与管理上的责任空心化。

4. **本地轻量级模型（Ollama/端侧）在复杂决策上的能力代差**
   - *争议点*：开源社区极力主张使用本地 Ollama（如 Llama 3 8B、Qwen 2.5 7B）以保护隐私。但实测表明，7B–14B 本地模型在长链条 Tool Calling 与遵循否定性约束（如“绝对禁止写操作”）时，失误率显著高于云端前沿模型。在隐私与可靠性之间，个人开发者仍需妥协。

---

## 5. 参考来源列表

1. **Parasuraman, R., Sheridan, T. B., & Wickens, C. D. (2000)**. *A model for types and levels of human interaction with automation*. IEEE Transactions on Systems, Man, and Cybernetics - Part A: Systems and Humans, 30(3), 286–297. [Link](https://ieeexplore.ieee.org/document/844354)
2. **Feng, K. J. K., McDonald, D. W., & Zhang, A. X. (2024-04)**. *Levels of Autonomy for AI Agents*. Knight First Amendment Institute at Columbia University / arXiv:2404.14482. [Link](https://knightcolumbia.org/content/levels-of-autonomy-for-ai-agents)
3. **SAE International (2021-04)**. *Taxonomy and Definitions for Terms Related to Driving Automation Systems for On-Road Motor Vehicles (Standard J3016_202104)*. [Link](https://www.sae.org/standards/content/j3016_202104/)
4. **Anthropic (2024-12)**. *Building Effective Agents*. Anthropic Engineering Research. [Link](https://www.anthropic.com/research/building-effective-agents)
5. **OpenAI (2025-01)**. *Introducing Operator: A Computer-Using Agent*. OpenAI Product Announcement. [Link](https://openai.com/index/introducing-operator/)
6. **Anthropic (2024-10)**. *Developing computer use: model safeguards and countermeasures*. Anthropic Research. [Link](https://www.anthropic.com/news/3-5-models-and-computer-use-countermeasures)
7. **Appelo, Jurgen (2011)**. *Management 3.0: Leading Agile Developers, Developing Agile Leaders* (Delegation Poker & 7 Levels of Delegation). Addison-Wesley Professional. [Link](https://management30.com/practice/delegation-poker/)
8. **Bezos, Jeff (1997, 2015)**. *Amazon Annual Letter to Shareholders: Type 1 and Type 2 Decisions*. [Link](https://www.aboutamazon.com/news/company-news/2015-letter-to-shareholders)
9. **PromptArmor (2024-08-20)**. *Data Exfiltration from Slack AI via Indirect Prompt Injection*. PromptArmor Threat Intelligence. [Link](https://promptarmor.com/blog/slack-ai-data-exfiltration)
10. **Rehberger, Johann (2024-09-18)**. *ChatGPT Persistent Memory SpAIware / Cross-Session Data Leak*. Embrace The Red. [Link](https://embracethered.com/blog/posts/2024/chatgpt-cross-session-data-leak/)
11. **OWASP Top 10 for Large Language Model Applications (2025)**. *LLM01: Prompt Injection & LLM08: Excessive Agency*. OWASP GenAI Project. [Link](https://genai.owasp.org/llm-top-10/)
12. **Willison, Simon (2023–2024)**. *Research series on Prompt Injection and Indirect Prompt Injection attacks*. [Link](https://simonwillison.net/series/prompt-injection/)
13. **Home Assistant & Model Context Protocol (MCP) Integration (2024-2025)**. *Dynamic Tool Discovery for Local Smart Home LLMs*. Home Assistant Developer Docs. [Link](https://www.home-assistant.io/)
