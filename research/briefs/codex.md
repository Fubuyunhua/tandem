# 任务书：codex —— 工程侧：AI 编码自动化流水线与风险分级放行

先读 `research/briefs/00-context.md`。你的名字是 `codex`，输出写到 `research/out/codex.md`。

## 要回答的问题

1. **业界现状**：主流厂商和团队是如何搭建"AI 自主编码 + 自动验证 + 选择性人审"流程的？请至少覆盖其中一部分，并说明各自的放行/审核机制：
   - OpenAI Codex（cloud tasks、AGENTS.md、自动 code review）
   - GitHub Copilot coding agent / Copilot code review / Agent HQ
   - Claude Code（hooks、headless/`-p`、GitHub Actions、permission modes / auto mode、subagents）
   - Cursor background agents / Bugbot、Google Jules、Devin、Factory、OpenHands
   - Spec-driven development（GitHub spec-kit、Kiro 等）
   - AI review 机器人（CodeRabbit、Greptile、Graphite 等）
   - 公开过内部实践的公司（例如 Stripe、Shopify、Uber、Anthropic、OpenAI 关于 harness / agentic coding 的工程博客）
2. **风险分级**：哪些改动可以自动合并，哪些必须人审？业界用什么信号来判断？例如：改动路径（auth、支付、迁移、CI 配置、依赖）、diff 大小、可逆性、测试覆盖、是否改动公共 API、安全扫描结果、agent 的自评置信度等。有没有现成的"policy-as-code"做法（CODEOWNERS、branch protection、OPA 等）？
3. **验证关卡（gates）**：除了"测试通过"，还有哪些有效关卡？例如类型检查、lint、mutation testing、property-based testing、golden/snapshot、安全扫描（SAST、secret、依赖）、预览环境、canary/feature flag、agent 互审（一个 agent 写、另一个 agent 审）、可复现性检查。哪些关卡对个人开发者性价比最高？
4. **决策留痕**：AI 自主做出的决定如何记录，方便人事后抽查？例如 ADR、决策日志、PR 描述模板、"needs-human" 标签队列。

## 必须产出的落地方案

为委托人设计一个**单人可落地**的流水线，前提是：Windows、GitHub、手头有 Claude Code / Codex / pi / Antigravity 四个 agent，并用 herdr 编排。需要包含：
- 一份**风险分级规则**示例（YAML 或表格）：L0 自动合并 / L1 自动合并但每日抽查 / L2 必须人审 / L3 人来决策、AI 只给方案。
- 一份 CI 步骤示例（GitHub Actions 片段即可，标注哪些是必须的、哪些可选）。
- "写/审分离"的 agent 编排建议：哪个 agent 适合写、哪个适合审，以及为什么。
- 起步时**只做哪 3 件事**（最小可行版本）。
