# task-003 审核 · Claude

结论：**需要修改**（一处高危，一处要用户决定）。范围：`feat/risk-gate` 的 5c56c06..e2fbbc4。CI `check` 通过；`risk-level` 在本 PR 上判 D 并失败，符合预期（改了 `.github/**` 和 `scripts/gate/**`）。

做得好的：不用合并提交而用 PR 的 base/head；`rev-parse --end-of-options` 防选项注入；PR 文本不进 shell；JSON + 中文摘要；真实 Git 测试；如实报告了断言抵消问题（已转给 task-001 的写手修）。

## 要改

### J1（高）PR 能改掉自己的裁判：脚本和 `risk.yml` 都来自 PR 分支
- 工作流在 `pull_request` 下检出 **PR head**，然后运行 head 里的 `scripts/gate/risk_level.py`、head 里的 `src/tandem/`，读 head 工作树里的 `risk.yml`。
- 反例：一个 PR 同时把 `risk.yml` 里的底线路径删掉（或把脚本改成永远输出 C），闸门就用改过的规则给自己判 C。PR 描述里写了"靠分支保护兜底"，但分支保护只要求检查**通过**，而检查本身已经被改掉了。
- 改：裁判的代码和规则必须来自**基准分支**，PR 的提交只当作**数据**读。可选做法：
  - 用 `pull_request_target`（运行基准分支上的工作流文件），检出 base 作为工作目录，再 `git fetch` PR head 的提交，只用 `git diff`/`git show` 读取，**绝不执行** head 里的任何文件；权限保持 `contents: read`、`persist-credentials: false`。
  - 或者保持 `pull_request`，但先检出 base、从 base 运行脚本和读 `risk.yml`，head 仅 fetch 为对象。（注意：此时工作流文件本身仍来自 PR，可以被改，所以首选上一种。）
- 测试：加一个"PR 修改 risk.yml 删掉底线 + 修改受保护路径"的场景，断言仍判 D（规则取自 base）。

### J2（要用户决定）D 级以"检查失败"表达，会让 D 级 PR 永远不能合并
- 用户定的规则是"CI 绿才能合并，人不能越过 CI"。如果 `risk-level` 被设为必需检查，D 级 PR 的检查永远是红的，没有任何合法路径能合并；如果不设为必需，它就只是提示。
- task-004 的适配器把提交上所有检查都当 CI，D 级任务会被当作 CI 失败打回，三次后 R01（见 task-004 审核 K1）。
- 这个需要用户在下面几种方案里选一种，**在用户决定前不要改退出码**：
  - a. `risk-level` 只报告等级（D 也返回 0，写进摘要和标签），D 级"必须人工"由内核的状态机和用户的 GitHub 审批保证；
  - b. 保持 D 级失败，另加一个"人工批准后重跑变绿"的机制（例如用户在 PR 上批准后，闸门检查到用户的 Approve 评审就返回 0）；
  - c. 其他方案。

## 低
- J3：`LIMITATIONS` 里写的"本轮不解决"在 J1 修好后要更新。
- J4：`ruff`/`pyright` 的默认范围不包括 `scripts/`，写手是手动额外检查的。建议把 `scripts` 加进 pyright 的 include，让 CI 也检查。

## 第二轮（85a9675、fbb4a30）· Claude

J1 **已修好**：改为 `pull_request_target`，检出 base 运行，head 只 fetch 为对象，`risk.yml`、脚本、依赖都来自 base；新增"PR 删空底线 + 改受保护路径仍判 D"的回归。J3、J4 已修。J2 仍等用户决定。

剩余两点（低）：
- 仓库是公开的，fetch PR head 不需要令牌。建议去掉 `FETCH_TOKEN` 和 `http.extraheader`，少一处凭据暴露面。
- `pull_request_target` 用的是**基准分支上的工作流文件**。PR #3 本身的目标分支 `feat/m1-runnable` 上还没有这个文件，所以本 PR 上 `risk-level` 不会再运行，要等它进入基准分支后，后续 PR 才会受检。这是预期行为，请用户知悉。

结论：**修改后可以**（J2 待用户决定）。
