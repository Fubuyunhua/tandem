# 任务书：可信控制器的方案分析（task-007，只写文档，不写代码）

- 写手：Codex
- 审核：Claude
- 用途：帮用户做一个架构决定。**你只给出分析和取舍，不替用户做决定。**

## 背景
task-002（WSL 隔离和诱饵测试）经过两轮审核，Codex 的结论仍然是"需要大改"。所有剩下的问题都指向同一个根源：

> 当裁判的代码和被测的 Agent 运行在同一个地方、用同一个身份时，Agent 就能改裁判。

同样的问题也出现在 ADR-0001 的 hub 上：hub 持有 token，并且负责做裁决，如果它和 Agent 跑在同一个发行版里、用同一个身份，就不安全。

先读：
- `docs/adr/0001-overall-architecture.md`
- `docs/PRD.md`
- task-002 的两轮审核：`git show origin/feat/wsl-isolation:docs/tasks/reviews/task-002-codex.md` 和 `task-002-codex-r2.md`（用 `git show` 读取，不要切换分支）

## 用户面前的三个方案
- **A. 在发行版里分两个用户**：控制器用户拥有裁判代码和证据目录，Agent 用另一个低权限用户运行。
- **B. 裁判放在 Windows，Agent 放在 WSL**：Windows 这一侧的程序用 `wsl -d tandem -u worker -- <agent>` 启动 Agent，直接捕获它的输出，证据存在 Windows 这边。
- **C. 先暂停**。

你也可以提出别的方案。

## 交付物
`docs/design/trusted-controller-options.md`，用中文写，面向正在学习架构设计的用户，写得**具体、好懂**：
1. **威胁模型**：要防的是什么？举例：被提示注入的 Agent 想伪造"我被挡住了"的证据、想修改裁判代码、想读取合并用的 token。不防什么？
2. **每个方案**：
   - 信任边界画在哪里（画一张 ASCII 图）；
   - 谁持有哪些凭据；
   - Agent 能碰到什么、碰不到什么；
   - 实现复杂度；
   - 对 ADR-0001 的影响（hub 放在哪里）；
   - 还有哪些没核实的前提，标【未核实】。比如：关闭 interop 以后，从 Windows 调用 `wsl -d ... -u ...` 是否还能用？Claude 的沙箱在 WSL 里是否真的生效？
3. **对比表**：安全性、复杂度、对 M1 进度的影响、可测试性。
4. **你的倾向和理由**，单独放在最后一节，标明"Codex 的意见，仅供参考"。
5. **如果用户选了 B，最小可行的第一步是什么**：用 3–5 条写清楚，不写代码。

## 要求
- 只在 worktree `C:\Users\weicai\Desktop\projects\tandem-ctl`（分支 `docs/trusted-controller`）里工作，提交这一个文件。**不要推送。**
- 只读其他文件。不要联网，不要执行会改变系统状态的命令。

## 完成后
在终端回复：第一行写 `DONE`，然后用 3 句话概括结论。
