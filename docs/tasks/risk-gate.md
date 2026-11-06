# 任务书：PR 等级闸门（task-003）

- 写手：Codex
- 审核：Claude、pi（DeepSeek）。两家都不是写手所在的提供方
- 闸门：CI 必须全部通过
- 用户的决定：这一轮所有代码都由 AI 生成，测试完成后用户再人工审核
- 基线：分支 `feat/risk-gate`，从 `feat/m1-runnable`（task-001，还在审核中）分出来，所以 PR 的目标分支是 `feat/m1-runnable`

## 背景
ADR-0001 规定：**合并权只在 GitHub 闸门手里**，等级由规则根据真实改动算出来。task-001 已经在内核里实现了 `tandem.core.level.compute_level`，在外壳里实现了 `GitDiffSource`。这次要把它们接到 GitHub Actions 上，让每个 PR 都自动算出等级，并据此决定能不能合并。

先读：`docs/adr/0001-overall-architecture.md`（"底线条目""基础级别怎么算""等级 → 流程表"）、`risk.yml`、`src/tandem/core/level.py`、`src/tandem/shell/diff_source.py`、`.github/workflows/ci.yml`。

## 交付物
1. `scripts/gate/risk_level.py`：命令行入口。
   - 输入：基线提交和待审提交（默认取 PR 的 base 和 head）。
   - 用 `GitDiffSource` 和 `compute_level` 算出等级；不接受任何模型意见（闸门只看规则）。
   - 输出：等级、命中的底线条目，以及每个改动文件分别命中了哪条规则（人能看懂的解释）。另外输出一份 JSON 文件供后续步骤使用。
   - 退出码：A、B、C 级返回 0；**D 级返回一个专门的非零退出码**，让 CI 检查显示为"需要人工"。
2. `.github/workflows/risk-gate.yml`：一个新的工作流，只在 `pull_request` 上触发。
   - 权限只给 `contents: read`。**不要用 `pull_request_target`**，原因见 `ci.yml` 里的注释。
   - 检出时要拿到 base 和 head 两个提交（`fetch-depth: 0` 或其他等价做法）。
   - 运行 `risk_level.py`，把结果写进 job summary。
   - 检查项的名字固定为 `risk-level`，方便以后在分支保护里设成必需检查。
3. 测试 `tests/gate/test_risk_level.py`：在真实的临时 Git 仓库里覆盖下面这些情况，并断言输出和退出码：
   - 改普通代码，判 C；
   - 只改 `docs/*.md`，判 C（闸门不接受模型意见，所以不会降到 B）；
   - 改 `.github/`、`risk.yml`、`src/tandem/core/` 或依赖文件，判 D；
   - 删除文件、减少断言，判 D；
   - 把文件改名挪进 `docs/`，判 D；
   - 中文文件名的情况。

## 已知限制（写进脚本的帮助文字和 PR 描述）
- 改 `.github/workflows/risk-gate.yml` 本身也是 D 级。但工作流是按 PR 分支里的版本运行的，有人可以在同一个 PR 里修改闸门。这一点要靠分支保护和"D 级必须人工批准"来兜底，这一轮不解决，只如实写明。
- 密钥扫描还没有接入，结果里标明"未扫描"。

## 工作方式
- 只在 worktree `C:\Users\weicai\Desktop\projects\tandem-gate` 里工作，分小步提交。每次提交前 ruff、pyright、pytest 全部通过。**不要推送。**
- 不要修改 `src/tandem/core/`、`docs/adr/`、`docs/design/`、`docs/PRD.md`、`docs/tasks/`、`tests/test_purity.py`。如果发现 task-001 的代码有 bug，写进回报里，不要自己改。
- 不要联网，不要调用真实 AI，不要执行会改变系统状态的命令。
- 标识符用英文，注释和文档用中文。

## 完成后
在终端回复：第一行写 `DONE`，然后列出提交清单、你做的、任务书里没写清楚的选择，以及发现的 task-001 问题（如果有）。
