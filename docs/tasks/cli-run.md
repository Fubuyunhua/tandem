# 任务书：`tandem run`，让任务在本地一步步往前走（task-005）

- 写手：Codex
- 审核：Claude、pi（DeepSeek）
- 基线：分支 `feat/cli-run`，从 `feat/m1-runnable` 分出来，PR 的目标分支是 `feat/m1-runnable`
- 用户的决定：这一轮所有代码都由 AI 生成，测试完成后用户再人工审核

## 背景
task-001 的 CLI 现在只有 `demo / status / submit / approve / reject / cancel`。用 `tandem submit` 提交的任务会一直停在"待处理"，因为没有任何命令负责派活、运行 Agent、产生 CI 结果。用户要人工审核"第一个版本"，就需要能自己动手，把一个任务从提交一直推进到合并。

先读：`docs/design/task-lifecycle.md` 第七版、`src/tandem/shell/cli.py`、`runner.py`、`executor.py`、`agents/fake.py`、`diff_source.py`、`risk.yml`。

## 交付物
1. `tandem run`：处理一轮所有能推进的任务，然后退出。具体做这几件事：
   - 给"待处理"的任务派活；
   - 用假 Agent 生成回执。假 Agent 的行为由参数控制，比如 `--agent-script ok|ci-red|refuse`；
   - 用假的改动采集器提供改动内容，比如 `--changes src/x.py,docs/a.md`，以及模拟的 CI 结果；
   - 多 Agent 模式下，用假审核者给出结论，比如 `--review pass|fail`。
   - 每推进一步都打印"任务：旧状态 → 新状态（原因）"。
   - 停在需要人处理的状态（待你审核、待你批准方案、待你介入）时不再继续，提示下一步该用哪个命令。
2. `tandem run --until-idle`：反复执行，直到没有任务能自动推进为止，并设置最大轮数，防止死循环。
3. `tandem show <任务编号>`：显示这个任务的完整记录，包括当前状态、等级、提交编号、审核意见、待你回应的意见（带复合键），以及历史事件列表。用户在 `approve` 之前，用它看清楚自己批准的是什么。
4. 把一个"手动走一遍"的示例写进 `README.md`：从 `submit` 开始，经过 `run`、`show`、`approve --sha`，最后到"已合并"，单 Agent 模式和多 Agent 模式各一个例子。
5. 测试：
   - 单 Agent 模式下，`submit → run → approve → run` 能走到已合并；
   - 多 Agent 模式下，审核不通过 → 退回 → 重新运行；
   - D 级任务停在"待你批准方案"；
   - `--until-idle` 不会死循环；
   - `show` 的输出里包含提交编号和待回应的意见。

## 要求
- 所有真实的外部动作仍然是 dry-run。`run` 只驱动假 Agent、假采集器、假审核者；运行真实 AI 的参数这一轮**不要加**。
- 只在 worktree `C:\Users\weicai\Desktop\projects\tandem-run` 里工作，分小步提交。每次提交前 ruff、pyright、pytest 全部通过。**不要推送。**
- 不要修改 `src/tandem/core/`、`docs/adr/`、`docs/design/`、`docs/PRD.md`、`docs/tasks/`、`tests/test_purity.py`。需要内核配合的地方写进回报里。
- 不要联网，不要调用真实 AI。标识符用英文，注释和文档用中文。

## 完成后
在终端回复：第一行写 `DONE`，然后列出提交清单和你做的选择。
