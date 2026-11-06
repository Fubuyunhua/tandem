# 审核任务：task-002（WSL 隔离与诱饵测试）

你是审核者。写手是 pi（DeepSeek），你和 Claude 是两家独立的审核者。

## 审核对象
分支 `feat/wsl-isolation` 相对 `main` 的全部改动：`git diff main...feat/wsl-isolation`。
这个分支在 git worktree `C:\Users\weicai\Desktop\projects\tandem-wsl` 里。

## 依据
- 任务书：`docs/tasks/wsl-isolation.md`
- `docs/adr/0001-overall-architecture.md`：问题 2（WSL2），以及"决定"一节里的验收项（诱饵测试、凭据清单）

## 要求
- **只读**：不要修改任何文件，只写你自己的输出文件；不要提交，也不要推送。
- 可以运行 `uv run pytest`、`uv run pyright`，以及 PowerShell 脚本的 `-DryRun` 模式来验证。**不要**执行任何会改变系统状态的命令：不要创建或删除 WSL 发行版，不要改 `.wslconfig`，不要调用真实的 AI，也不要联网。
- **独立完成**：不要读 `docs/tasks/reviews/` 下其他审核者的输出。
- 重点检查：
  1. **隔离是否真的成立**：按这套脚本建出来的发行版，后台 Agent 还能不能接触到你的私人数据或凭据？有没有漏掉的路径？
  2. **诱饵测试会不会误判**：有没有哪种情况，明明没挡住，测试却判为"通过"？或者反过来，明明挡住了，测试却判为"没通过"？
  3. **脚本是否安全**：破坏性操作前有没有确认？dry-run 是不是真的什么都不改？出错时会不会留下做了一半的状态？
  4. **测试质量**：测试检查的是真实的判断逻辑，还是只是为了让覆盖率好看？
  5. 任务书里的要求有没有遗漏。
- 最多 12 条，按严重程度从高到低排列。每条写：**问题**、**位置**（文件:行号）、**为什么重要**（给出具体的出错场景）、**建议**、**严重程度**（高 / 中 / 低）。
- 最后给出结论：**可以交给用户审核** / **修改后可以** / **需要大改**。

## 输出
- 写到 `C:\Users\weicai\Desktop\projects\tandem-wsl\docs\tasks\reviews\task-002-codex.md`。
- 写完后在终端只回复一行：`DONE`
