# 任务书：agy（Antigravity）—— 推广到生活：通用的人机决策授权框架

先读 `research/briefs/00-context.md`。你的名字是 `agy`，输出写到 `research/out/agy.md`。

## 要回答的问题

1. **自主度分级框架**：有哪些现成框架可以描述"AI 能自主到什么程度"？例如 Sheridan–Verplank 自动化等级、SAE 自动驾驶分级的类比、各机构提出的 AI agent 自主度分级（如 Knight First Amendment Institute 的 levels of autonomy、Anthropic/OpenAI/Google 关于 agent 的公开文章）。各自的维度是什么？
2. **决策分类方法**：用什么维度判断一个决定能否交给 AI？例如可逆性（Bezos 的 one-way / two-way door）、影响半径、金额、涉及他人与否、隐私敏感度、时效性/拖延成本、Cynefin 领域。管理学中的授权框架（Eisenhower 矩阵、RACI、Management 3.0 的 delegation poker 七级授权）如何映射到人与 AI 的分工？
3. **Human-in-the-loop 设计模式**：审批闸门、预算/额度上限、升级（escalation）规则、审计日志、撤销窗口、"先建议后执行"、批量汇总审批（digest）等。各类 agent 产品（如 OpenAI Operator/ChatGPT agent、Claude computer use、Google 的 agent 产品）在需要人确认时是怎么设计的？
4. **个人自动化落地**：普通人把 AI 自动化用于生活的成熟做法有哪些？例如邮件/日程分拣、记账与账单、信息订阅摘要、学习计划、健康记录、家庭事务、n8n / Zapier / Home Assistant / MCP 连接器、"life OS"/个人知识库。哪些场景收益最高、风险最低？
5. **风险**：prompt injection、凭据泄露、误操作不可撤销、隐私、过度依赖。有哪些真实事故或公开警示？应如何防护？

## 必须产出

- 一个**统一的"决策路由"框架**，能同时套用到代码和生活：输入是"一个待做的决定或动作"，输出是它属于哪个自主度等级（例如：AI 自动执行 / 执行后汇报 / 先建议后人批 / 人决策）。请给出判定维度和打分或判定规则。
- 一张**生活场景示例表**：10–15 个具体场景，每个场景标注等级和理由。
- 委托人**起步的前 3 个生活自动化**建议（低风险、高收益）。
