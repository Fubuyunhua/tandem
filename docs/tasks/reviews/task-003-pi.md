# task-003 审核 · pi（DeepSeek）

- 审核对象：`feat/risk-gate` 的 `15b1d69`（相对 `feat/m1-runnable` 的 8 个提交差异；含与 `feat/m1-runnable` 的合并 `2988de3`）
- 任务书：`docs/tasks/risk-gate.md`；同时读了 `docs/tasks/reviews/task-003-claude.md` 的两轮意见、`docs/risk-gate-pr.md`
- 依据：ADR-0001（"底线条目""基础级别怎么算""等级 → 流程表""合并权只在 GitHub 闸门手里"）、PRD F2/F3、`risk.yml`、`src/tandem/core/level.py`、`src/tandem/shell/diff_source.py`
- 方法：**只读代码**，没有进 worktree 修改任何文件（本报告除外）。我把 `15b1d69` 用 `git archive` 导出到临时目录，在临时目录里跑测试、并在**临时 Git 仓库**里做了 6 组攻击性实验（每次都在临时仓库，未触动任何分支）。DONE 之前没有在项目里执行任何写操作。
- 我复现的基线：`pytest` **322 passed, 1 skipped**；ruff / pyright 由 CI 与提交说明保证，我没有在本机重复跑（只读导出里没装 sdist 依赖，跑不起来也不影响结论）。
- 结论：**修改后可以**。安全边界（base 是裁判、head 只是数据、规则固定读 base、事件文本不进 shell、摘要不能注入）经我攻击性实验全部成立；剩下三条要处理：一条**很可能让"必需检查"失效**（需你在真实仓库实测，P1），一条**继承内核缺口**（P2，等 Codex 在内核修），其余是提示与硬化建议。

## 一、你点名的四个问题，逐条回答

| 问题 | 结论 | 证据 |
|---|---|---|
| `pull_request_target` 下是否真的从不执行 head 代码 | **是**（数据边界成立） | ① 工作流只在 base 提交上 `actions/checkout`（`ref: base.sha`、`persist-credentials: false`），head 只用 `git fetch --no-tags --no-recurse-submodules origin $PR_HEAD_SHA` 取成对象，之后全程 `git diff`/`git show` 读文本；② 我实测把 head 的 `scripts/gate/risk_level.py` 换成"永远输出 C 并 `exit 0`"，然后按工作流方式（工作树在 base）调用：判 **D、exit 3**，恶意脚本没有运行；作为对照，同一个恶意脚本被直接执行时输出 `C`、`exit 0`——这正好说明本 PR 修的是什么；③ 他们的回归 `test_trusted_base_checkout_never_executes_head` 还把恶意 `src/tandem/__init__.py`、无效 `pyproject.toml`、无效 `uv.lock` 放进 head，工作树保持 base、`uv sync --locked` 用 base 的锁文件，head 的入口没有被 import、`head-executed` 标记文件没有出现；④ 不肯定的两处见 P5（fork 取对象）与 P6（第三方 action 钉版本） |
| 等级判定与内核 `bottom_line_reasons` 是否一致 | **一致**（且不另写规则） | `risk_level.py:build_report` 用 `GitDiffSource(...).collect(base, head)` → `compute_level(changes, policy)`；`bottom_lines` 直接来自 `bottom_line_reasons(changes, policy)`；逐文件解释 `explain_file()` 只是把同一份采集数据按条目切出子集再交给同一个内核函数，没有第二套路径匹配或断言计数（我核对过源码）。测试里有"报告 `bottom_lines` 等于内核输出"的断言（`test_report_uses_core_reasons_for_renames_and_deletions`）。唯一的两处偏差见 **P3**（子集丢 `secret_scan_hit`）和 **P2 的解释文案** |
| 能否被候选分支自己降级 | **基本不能**，有 1 个继承自内核的缺口 | 我逐条实测：① 删空 base 的底线 + 改 `src/tandem/core/` → **D**（base 规则生效）；② 改 head 的 `scripts/gate/risk_level.py` → **D** 且改后的脚本不执行；③ 用 `.gitattributes` 把测试文件标成 `-diff` 再减断言 → **D**（仍读到 2→1，有 `assertion_drops`）；④ 把测试文件改成 UTF-16 让断言"看起来归零" → **D**（2→0，fail-closed）；⑤ 把测试文件**原样改名**移出 `tests/`（`tests/test_a.py → src/helper.py`）→ **C**；⑥ 大小写改名 `tests/ → Tests/` → **C**。⑤⑥ 是内核 `TEST_FILE_PATTERN` 的缺口（Codex 第四轮复核问题 1，正在 `feat/redteam-fixes` 修），闸门只是复用内核，合并后自动受益。见 **P2** |
| D 级退出码 | **符合任务书，但可能挡不住合并** | `MANUAL_EXIT_CODE = 3`、错误 `2`、A/B/C `0`；工作流那一步没有 `continue-on-error`、没有 `||`，摘要有 `if: always()`，失败时摘要写"…不能放行"。我实测 D 场景 exit 3、非法输入 exit 2、无改动 A 场景 exit 0。**但是**：`pull_request_target` 的检查很可能挂在 base 提交上，进不了 PR 的必需检查 → 见 **P1**；另外 J2（D 永远红 ⇒ 永远不能合并）仍待你决定 |

## 二、问题清单（按严重程度）

### P1【中高 · 需你在真实仓库实测】`pull_request_target` 的检查很可能不是 PR 的"必需检查"

- **位置**：`.github/workflows/risk-gate.yml:6`（`on: pull_request_target`）
- **为什么重要**：按 GitHub 的语义，`pull_request_target` 触发的工作流里 `GITHUB_SHA` 是**基准分支的最新提交**，检查结果也就挂在**那个提交**上；而分支保护的"必需状态检查"看的是 PR 的 **head/合并提交**。如果确实如此，`risk-level` 即使名字固定、即使被勾成必需检查，**也不会拦住 PR 的合并**——恰好吃掉了 ADR「合并权只在 GitHub 闸门手里」这条前提。Claude 两轮都没提这一点，任务书也只要求"检查项名字固定"。
- **复现/验证方式**（我做不了，需要联网的仓库）：
  1. 把本分支合进 `feat/m1-runnable`（或任何长期分支）；
  2. 开一个只改普通文件（C 级）的测试 PR，等 `risk-level` 跑完；
  3. `gh pr checks <PR>` 或在 PR 页面看：`risk-level` 是否出现在**这个 PR 的检查列表**里，还是只出现在 base 分支那个提交的页面上；
  4. 若 PR 页面看不到它，就基本可以确认它挂错了地方——此时把 `risk-level` 设为必需检查也不会生效。
- **建议**（三选一，按你偏好）：
  a. 保持 `pull_request_target` 做可信计算，再用一个 `workflow_run` 触发器把结果作为**检查**发在 PR head 上（需要 `checks: write`，只在这个中继 workflow 里给，且它不执行 head 代码）；
  b. 回到 `pull_request`，但先检出 base、从 **base** 读脚本和 `risk.yml`（Claude 第一轮给的第二方案）——代价是工作流文件本身来自 PR，可被改，需要额外守护；
  c. 如果实测发现 `pull_request_target` 的检查确实挂到 PR head（与我记忆的文档语义不同），那就保持现状，只需在文档里写明"已实测"。

### P2【中 · 继承内核缺口】把测试文件原样改名移出 `tests/`（或改成 `Tests/`）仍判 C

- **位置**：闸门侧无代码问题，根因在 `src/tandem/shell/diff_source.py` 的 `TEST_FILE_PATTERN` 与改名分支（内核）；闸门 `scripts/gate/risk_level.py:explain_file` 只是复用它
- **复现**（我在临时仓库里实测，两条都是 exit 0、`level=C`、`bottom_lines=[]`）：
  - `git mv tests/test_a.py src/helper.py`（内容一字不改）→ `C`；报告里的逐文件解释是 `改名规则：新旧路径同时参与判断，取更严格级别`
  - `git mv tests/test_a.py Tests/test_a.py` → `C`（`TEST_FILE_PATTERN` 区分大小写）
- **为什么重要**：把测试文件挪出去，pytest 就不再收集那些断言，"测试断言减少"这条底线被绕开；而闸门给出的解释还写着"取更严格级别"，读起来像是已检查过、实际是 C。
- **建议**：内核修复（Codex 在 `feat/redteam-fixes`）按"旧路径按测试属性算 before、新路径按测试属性算 after，移出测试路径时 after 记 0"改，闸门合并后自动受益；同时把闸门那句补充解释改成与结论一致的说法（例如"改名：新旧路径都参与判断（本次未命中底线）"），只在真的命中底线时保留"取更严格级别"。本轮不用改闸门代码，但要等内核合并后再验证一次。

### P3【低 · 将来会不一致】逐文件解释用的 `ChangeSet` 是子集，丢了 `secret_scan_hit`

- **位置**：`scripts/gate/risk_level.py:76`（`explain_file` 构造 `ChangeSet` 时没有透传 `secret_scan_hit`，也没有传 `assertions_before/after`）
- **为什么重要**：现在密钥扫描固定"未扫描"，所以看不出来；一旦接入 gitleaks，汇总的 `bottom_lines`（来自完整 `changes`）会包含"密钥扫描命中"，而逐文件的 `files[].rules` 永远不会出现这一条 —— 同一份报告里两处说法不一致。`assertions_before/after` 只在"没有逐文件记录时才比合计"的旧数据分支才会用到，目前采集器总会给出逐文件记录，所以这一条暂时不可达，但同样是隐患。
- **建议**：把 `secret_scan_hit` 透传给 `file_changes`（命中时每一条都标出来），或明确只在汇总里报并在文档里说明；顺手补一条"文件级解释 ⊆ 汇总原因 ∪ {普通改动}"的一致性断言。
  ```python
  file_changes = ChangeSet(..., secret_scan_hit=changes.secret_scan_hit)
  ```

### P4【低】`.gitattributes` 不在底线里（实测不能绕过断言底线，但值得列上）

- **位置**：`risk.yml` 的 `bottom_line_paths`
- **实测**：PR 加 `.gitattributes`（`tests/*.py -diff`）同时把断言从 2 减到 1 → 仍 **D**（`git show` 读的是原始 blob，不受属性影响），所以不是绕过。
- **但仍建议**：`.gitattributes` 能改变 diff 的展示方式和换行转换，属于"闸门和评审看到的东西"，按 ADR"宁可多报"的精神可以加进底线（或至少在 PR 描述里写明"本轮不把它列为底线，因为它不能影响等级计算"）。

### P5【低】fork PR 的 head 对象可能取不到

- **位置**：`.github/workflows/risk-gate.yml:23-32`（`git fetch origin "$PR_HEAD_SHA"`）
- **说明**：按 SHA 取对象要求服务端允许（`uploadpack.allow*SHA1InWant`）。公开仓库的**同仓分支**没问题；外部 fork 的 PR，head 提交在 base 仓库里要靠 `refs/pull/N/head` 才可见，按 SHA 取有可能报 `not our ref`，那一步失败 → 闸门失败（**fail-closed，安全上没问题**），但外部贡献者的 PR 会永远是红的。仓库现在是单人使用、外部 PR 概率低，所以只算低。
- **建议**：改成取 PR 引用再解析 SHA（同样只当数据），例如
  `git fetch --no-tags --no-recurse-submodules origin "refs/pull/${{ github.event.pull_request.number }}/head"` 之后 `rev-parse FETCH_HEAD`（注意 `${{ }}` 仍只放在 `env:` 里、由 shell 变量拼接），或者两条路径都试。

### P6【低】第三方 action 只钉到 major tag

- **位置**：`.github/workflows/risk-gate.yml:24`（`astral-sh/setup-uv@v6`）
- **说明**：这个 job 是"可信裁判"，`v6` 是可移动标签，理论上供应商或标签被改都会影响裁判本身。仓库其它工作流同样写法（`ci.yml`），所以不是本 PR 引入的新问题；但闸门比其他 job 更值得钉 commit SHA。

### P7【信息】D 的"需要人工"在 GitHub 上只能从日志/摘要看出来

- **位置**：`scripts/gate/risk_level.py:14`（`MANUAL_EXIT_CODE = 3`）、工作流摘要步骤
- **说明**：GitHub 只分"通过/失败"，退出码 3 和 2 在检查结论上一样是红。当前实现已经在摘要标题里区分了 `（需要人工）` 与"等级闸门未生成结果…不能放行"，够用；但如果将来做手机通知，别用"检查失败"当作"需要人工"的同义词。另外 J2（D 永远红 ⇒ 没有合法合并路径）仍等你的决定，代码这次按"不改退出码"处理，符合 Claude 第二轮的结论。

### P8【信息】规则取 base 的最新提交，不是共同祖先

- **位置**：`scripts/gate/risk_level.py:129`（`git show f"{base}:risk.yml"`），而 diff 用的是 `base...head`
- **说明**：PR 开着的时候如果 base 分支收紧了规则，闸门会**立刻**按新规则判（更严），反之放宽也会立刻生效。我判断这是可接受、偏保守的选择（和"裁判来自 base"一致），但建议在 PR 描述/README 里写一句 `policy_source` 的确切含义，免得以后有人以为读的是共同祖先的规则。

## 三、我做过的攻击性实验（都在临时仓库，可复现）

| # | 场景 | 结果 |
|---|---|---|
| 1 | head 把 `scripts/gate/risk_level.py` 改成"永远输出 C、exit 0"，并改 `src/tandem/core/x.py`；**直接跑 head 的脚本**（天真实现） | 输出 `C`、**exit 0**（这就是要防的） |
| 2 | 同一场景，按工作流方式：工作树检 base，跑 base 的脚本 `--base <base> --head <head>` | **D、exit 3**，`bottom_lines` = 改动了 `scripts/gate/risk_level.py`、`src/tandem/core/x.py` |
| 3 | 加 `.gitattributes`（`tests/*.py -diff`）并把断言 2 → 1 | **D**，`assertion_drops=[{path: tests/test_a.py, before: 2, after: 1}]` |
| 4 | 测试文件改成 UTF-16（断言"看起来归零"） | **D**，`drops: 2 → 0`（fail-closed） |
| 5 | `git mv tests/test_a.py src/helper.py`（原样移出测试路径） | **C**、`bottom_lines=[]`，逐文件解释仍是"改名规则…取更严格级别"（P2） |
| 6 | `git mv tests/test_a.py Tests/test_a.py`（大小写） | **C**（P2） |
| 7 | 文件名含三个反引号 + `##`（摘要注入） | 摘要围栏自动加长到 4 个反引号，路径仍在代码块内，`::warning::` 没有被当成工作流命令（只是文本） |
| 8 | 非法输入（缺 base/head、非法事件 JSON、base 规则缺失/损坏） | 全部 **exit 2** 且不写 JSON（fail-closed） |

## 四、做得好的地方（我核对过，不是照抄提交说明）

- **裁判来自 base，head 只是数据**：这一点是真的成立，而且我做了"天真实现会输出 C"的对照实验。
- **规则固定 `git show <base>:risk.yml`**，base 规则缺失/损坏直接报错，不回退到 head 或共同祖先（有测试）。
- **不执行 head**：不检出、不安装 head 依赖、不导入 head 包、不跑本地 Action；回归测试用恶意 `__init__.py`/无效 lock/无效 pyproject 证明。
- **事件文本不进 shell**：`${{ }}` 只出现在 `env:`，head 编号先过 `^[0-9a-f]{40}$` 再拼进 fetch；脚本侧一律参数列表 + `rev-parse --end-of-options`。
- **权限与阻断契约**：`contents: read`、`persist-credentials: false`、fetch 不带 token/`http.extraheader`、无 `continue-on-error`、无 `||`、摘要有 `if: always()`；还有一条解析 YAML 的回归守住这些（`test_workflow_keeps_gate_read_only_and_blocking`）。
- **等级解释复用内核**：汇总与逐文件都调 `bottom_line_reasons`，并为改名/删除/删除测试文件做了归属断言；还顺手把 task-001 的"断言抵消"缺口做了回归。
- **摘要注入**：围栏长度按正文里最长反引号串自动加长，我实测有效。

## 五、结论

**修改后可以。** 闸门最关键的那条不变量——"PR 不能改自己的裁判"——这次是真的立起来了，我按攻击者的思路试了四条路（改脚本、改规则、改 `.gitattributes`、改编码）都没能降级；D 级退出码、错误处理、摘要注入也都符合任务书。

要你处理的是两件事：**P1 需要你在真实仓库实测一次**（`pull_request_target` 的检查是否挂到 PR head；这决定闸门能不能真的当必需检查），以及 **J2（D 级永远红）怎么定**。剩下 P2 等内核在 `feat/redteam-fixes` 修好后合并验证；P3–P6 是可以顺手做的硬化，P7、P8 只需在文档里写清。
