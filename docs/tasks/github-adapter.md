# 任务书：GitHub 适配器（task-004）

- 写手：Codex
- 审核：Claude、pi（DeepSeek）
- 闸门：CI 必须全部通过
- 用户的决定：这一轮所有代码都由 AI 生成，测试完成后用户再人工审核
- 基线：分支 `feat/github-adapter`，从 `feat/m1-runnable`（task-001）分出来，所以 PR 的目标分支是 `feat/m1-runnable`

## 背景
PRD 的 M1 写的是："事件源先只接带 agent 标签的 Issue"。task-001 的外壳目前只有假 Agent 和 dry-run 执行器，还没有和 GitHub 连起来。这次要补上 GitHub 这一侧的外壳，但**真实的写操作默认关闭**。

先读：`docs/PRD.md`（F3、F4、M1）、`docs/adr/0001-overall-architecture.md`（"决定"一节里的凭据清单，以及第三版架构）、`docs/design/task-lifecycle.md` 第七版、`src/tandem/shell/`（尤其是 `executor.py`、`runner.py`、`cli.py`）。

## 交付物
1. `src/tandem/shell/github.py`：
   - 一个 `GitHubClient` 接口（Protocol）。实现上通过 `gh` 命令行和 `gh api` 调用，不要新增 HTTP 库依赖。
   - **读操作**：列出带 `agent` 标签的、处于打开状态的 Issue；读取某个 PR 的 head SHA、状态、是否已合并；读取某个提交的 CI 检查结果。
   - **写操作**：合并 PR（必须带上预期的 head SHA，SHA 对不上就拒绝合并）、关闭 PR、在 Issue 或 PR 上发评论。所有写操作默认 dry-run，只有显式传入 `--live` 才真正执行，而且要先读一遍当前状态做核对。
   - 一个假实现 `FakeGitHub`，供测试使用。
2. 事件来源：把带 `agent` 标签的 Issue 转成任务提交（任务编号用 `gh-<issue 编号>`），重复轮询时不能重复建任务。把 CI 结果转成 `CI_GREEN` / `CI_RED` 事件，带上提交编号。
3. 第 26 条的核对：异常恢复时，用 GitHub 的真实状态生成核对结果（合并其实已经成功 / PR 已关闭 / 没有动作完成）。
4. CLI：
   - 增加 `tandem poll`：拉取一次 Issue 和 CI 状态，生成事件，交给 Runner 处理。默认 dry-run。
   - 增加 `tandem reconcile <任务编号>`：对处于异常状态的任务做核对。
5. 测试：全部使用 `FakeGitHub`，不联网。覆盖：
   - 标签过滤；
   - 重复轮询不会重复建任务；
   - 合并时 SHA 对不上就拒绝；
   - dry-run 不产生写操作；
   - 第 26 条的三种核对结果；
   - `gh` 命令失败时的处理（转成异常事件，不能当作成功）。

## 安全要求
- 绝不在代码或日志里打印 token。凭据只靠 `gh` 自己的登录状态。
- 合并只能通过"预期 SHA 一致"的接口进行；拼出来的 `gh` 命令参数要做转义，或者用参数列表，不能拼成一整段 shell 字符串。
- Issue 的标题和正文都是**不可信的输入**（可能有提示注入），只能当作数据传递，不能拼进命令。

## 工作方式
- 只在 worktree `C:\Users\weicai\Desktop\projects\tandem-github` 里工作，分小步提交。每次提交前 ruff、pyright、pytest 全部通过。**不要推送。**
- 不要修改 `src/tandem/core/`、`docs/adr/`、`docs/design/`、`docs/PRD.md`、`docs/tasks/`、`tests/test_purity.py`。如果需要内核提供新的事件字段，写进回报里，不要自己改。
- **不要联网，不要真的调用 `gh` 去访问 GitHub**，不要调用真实的 AI。
- 标识符用英文，注释和文档用中文。

## 完成后
在终端回复：第一行写 `DONE`，然后列出提交清单、你做的、任务书里没写清楚的选择，以及需要内核配合的地方。
