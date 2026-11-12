# PR 描述草稿：接入 PR 风险等级闸门（task-003）

目标分支：`feat/m1-runnable`。本轮仅在本地开发和提交，未推送、未创建远程 PR。

## 改动与行为

新增 `scripts/gate/risk_level.py`，通过现有 `GitDiffSource` 和 `compute_level`
根据真实提交差异计算等级。普通代码和纯文档均为 C；命中底线为 D；无改动为 A。
不接收模型意见。输出含中文规则解释的报告和 UTF-8 JSON，列明提交编号、共同祖先、
各文件新旧路径、底线原因、删除和断言变化。汇总与逐文件底线解释都调用内核的
`bottom_line_reasons()`；脚本只选取对应文件的采集数据，不另写路径匹配或断言计数。
JSON 的 `assertion_drops` 保留逐文件减少记录，断言合计仅用于概览。
密钥扫描明确标为“未扫描”。逐文件解释透传整批改动的 `secret_scan_hit`；
将来扫描命中时，每条文件解释都会保留“密钥扫描命中”，与汇总一致。
这个标志尚无文件级定位，不能据此认定每个文件都含密钥。
改名解释按实际内核原因显示“本次未命中底线，判 C”或“本次命中底线，判 D”，
不再笼统承诺“取更严格级别”。

等级工作流使用 `pull_request_target`，检查名固定为 `risk-level`，权限仅
`contents: read`，检出时设 `persist-credentials: false`。
检出事件指定的 base 提交作为工作目录，仅 fetch PR head 提交对象，不检出 head。
使用事件里的 base/head，而非 GitHub 生成的测试合并提交。
D 级**只报告、不让检查失败**（K6，用户 2026-11-12 拍板）：退出码 0、JSON 里
`needs_manual: true`、摘要标题写“需要人工”；人工关口由内核的“待你审核”保证。
输入、配置、采集或输出错误仍然退出 2，检查仍然失败。A/B/C 返回 0。
失败时也会运行摘要步骤，且不会抹去闸门失败状态。

## 安全模式：base 是裁判，head 仅是数据

采用 `pull_request_target` 是为了让工作流定义来自可信基准分支，
防止 PR 修改工作流、脚本或规则后给自己判低等级。
工作目录固定检出事件里的 `base.sha`：裁判脚本、`src/tandem`、`pyproject.toml`、
`uv.lock` 和 `uv sync --locked` 都来自 base，不执行 head 的任何文件。
即使本地调用时工作树位于 head，策略也固定通过 `git show <base>:risk.yml` 读取，
不会改读工作树、head 或共同祖先的规则；base 规则缺失或损坏时直接报错。
报告用 `policy_source` 标明该来源，即 `<base SHA>:risk.yml`。
这里的 base 是本次 PR 事件记录的基准分支最新提交（本地调用则是 `--base` 指定的提交），
不是 `merge_base` 共同祖先。diff 使用 `base...head` 排除 base 独有的改动，
策略却取 base 最新已接纳的版本，让裁判代码、依赖和策略来自同一可信提交，
也避免长期开着的 PR 一直沿用共同祖先处的旧规则。
因此 base 收紧或放宽规则，都会在携带新 `base.sha` 的后续运行中生效；
这不保证规则只会更严。一次运行固定在事件 SHA 上，基准分支推进不会自动改写旧报告，
重跑旧事件也不等于读取执行时的最新分支 tip；需要使用包含新 base SHA 的事件重新评估。

head 只作为 Git 对象供改动采集读取；`git diff`/`git show` 取出的内容不作代码执行。
fetch 使用环境变量中已校验的正整数 PR 编号，读取 base 仓库的
`refs/pull/<编号>/head`，使 fork 的提交也可获取，不要求服务端接受任意 SHA 获取。
获取后把 `FETCH_HEAD^{commit}` 与事件的 `head.sha` 比较；如果 PR 已更新、引用不存在、
输入非法或 fetch 失败，立即使步骤失败，不回退到其他提交或给出可放行的结果。
PR 编号和 SHA 只通过 `env:` 传入，事件文字不拼接到 shell 脚本。
仓库公开，fetch 匿名读取对象，不提供 token 或认证 header；
不递归获取子模块，不检出 head、不安装 head 依赖、不导入 head 包，
也不运行 head 中的本地 Action 或构建钩子。
裁判 job 的 `astral-sh/setup-uv` 固定为用户提供的
`d0cc045d04ccac9d8b7881df0226f9e82c39688e`（v6），避免 major 标签移动改变裁判环境；
本轮未联网核验该标签，也未修改普通 CI 的 action 版本。

`pull_request_target` 不能用来直接执行不可信 PR；本工作流的安全前提正是上述数据边界。
普通 CI 仍用 `pull_request` 执行 PR 测试，两者职责不同。
此修复合并到目标基准分支后，才会成为后续 PR 实际使用的可信裁判；
不能假定只在 PR 中改了工作流，就已经替换了目标分支上正在生效的版本。

## 本地使用与结果

在可信 base 检出的仓库根目录安装、运行本项目，head 预先作为 Git 对象获取：

```powershell
uv run python scripts/gate/risk_level.py --base <base提交> --head <head提交> --output risk-level.json
```

默认仓库为当前目录，可用 `--repo` 指定；规则始终读取该仓库 base 提交中的 `risk.yml`。
本地操作也必须从可信 base 的脚本和依赖环境运行，不能先执行 head 的 `uv sync`。
`--base` 和 `--head` 须成对指定；省略时从 `GITHUB_EVENT_PATH` 的 PR 事件读取。
比较范围遵循采集器的 `base...head`，报告同时记录实际共同祖先。
本地默认 JSON 文件写到当前目录；可用 `--summary` 额外保存 Markdown 报告。
工作流将两份报告写入 `$RUNNER_TEMP/risk-level.json` 和 `$RUNNER_TEMP/risk-level.md`，
JSON 可供同一 job 的后续步骤读取，Markdown 会写入 job summary。

## 已知限制与已修复问题

- 修改 `.github/workflows/risk-gate.yml` 本身仍是 D 级，修改不能在同一 PR 的检查中
  替换正在运行的 base 裁判。仍需配置分支保护并审查裁判升级。
- P1 待用户决定和远程实测：`pull_request_target` 产生的检查能否成为 PR 的必需检查，
  本轮没有验证，不能仅凭检查名固定就认定分支保护已经生效。触发器和权限保持原样。
- J2 已由用户拍板（K6）：D 级不再让检查失败，只写 `needs_manual: true` 与“需要人工”
  摘要；这样把 `risk-level` 设为必需检查也不会把 D 级 PR 永久拦住，人工关口交给内核
  的“待你审核”。真正的错误（输入非法、取不到提交、读不了 base 规则）仍然退出 2。
- 密钥扫描尚未接入，结果标明“未扫描”。
- 内核规定改名同时判断新旧路径，并不把改名本身直接判 D。
  “移入 docs/ 判 D”以受保护源路径的移动作为验收场景；
  普通代码文件移入 docs/ 且无其他底线命中时仍为 C。
  这是按既有 ADR 和内核语义作出的选择；若任务意图为所有此类移动都判 D，
  需要另行调整 task-001 的规则，本轮未修改内核。
- P2 的测试文件移出发现路径、大小写改名等采集缺口由内核 PR #8 处理；
  本轮只修逐文件解释文案，不改内核、不合并 PR #8，也不宣称此分支已堵住这些路径。
  合入内核修复后仍需重新运行对应回归。
- P4：当前 `.gitattributes` 没有列入 `risk.yml` 的底线条目，单独新增它判 C。
  本地回归证明：同时设置 `tests/*.py -diff` 并把断言从 2 减为 1，仍判 D，
  因为断言采集读取原始 Git blob，不依赖展示用 diff；这只是该场景的结论，
  不代表属性变更没有风险。属性仍能隐藏评审 diff、影响换行和过滤器选择。
  **建议后续经用户批准，把根目录及子目录的 `.gitattributes` 都纳入底线保护**，
  由人工审查此类影响评审材料的配置变更；内核路径匹配会逐级匹配后缀，
  可考虑 `.gitattributes` 条目同时覆盖两者。本轮未修改 `risk.yml`。
- 已通过本地 merge 合入 `feat/m1-runnable` 的 `2988de3`，task-001 的断言抵消问题
  已修复：采集器生成逐文件 `assertion_drops`，一个文件从 2 条减到 1 条，
  另一个文件新增 1 条，即使合计仍为 2，也会判 D。原记录 C 级行为的测试已改为
  D 级回归，并验证内核解释、逐文件归属和 JSON 中的减少记录。
  内核及采集器的修复来自合并的目标分支，闸门直接复用该接口。

## 验证

每次提交前均离线执行 `uv run ruff check`、`uv run ruff format --check`、
`uv run pyright`、`uv run pytest`。
J4 已把 `scripts` 加入 pyright 默认检查范围，与 `src`、`tests` 一起由 CI 检查；
ruff 的默认文件发现原本就覆盖 `scripts/`，无需另加路径或改掉现有排除规则。
新增测试使用真实临时 Git 仓库，通过子进程断言标准输出、JSON、摘要和退出码，
覆盖任务书要求及 PR 默认输入、错误输入、分叉历史和上述既有边界。
新增改名后断言减少、删除测试文件的报告验证，确保汇总和逐文件解释使用内核原因。
J1 回归覆盖“head 删空底线并改受保护路径仍判 D”、base 规则缺失/损坏拒绝放行，
以及 base 工作树读取含恶意入口、包初始化代码和无效依赖文件的 head 时不执行它们。
工作流权限及阻断契约也有本地检查。未联网，未运行 GitHub Actions；
远程检查结果须在后续 PR 中确认。


## pi 审核跟进的本地证据

- P2：普通改名 C、受保护路径改名 D 的解释断言，均在旧文案上实际失败。
- P3：修改、删除、改名三种动作 × 扫描命中/未命中，命中三例在旧实现上失败；
  测试还检查文件底线原因属于汇总原因，排除额外的改名和普通改动说明。
- P5：读取 YAML 中原始 Bash 步骤，用本地临时 bare 远端和独立 fork 对象库执行，
  覆盖 PR 引用、工作树不变、恶意 head 不执行、非法编号/SHA、缺失引用和 SHA 不一致。
  旧工作流在取引用、校验编号/引用/SHA 一致性的对应测试上实际失败。
  本地文件协议不能模拟 GitHub 所有服务端行为，未声称已在线验证 fork PR。
- P6：测试断言 setup-uv 的完整固定 SHA，旧 v6 标签写法实际失败。
- P4/P8：另用真实临时仓库验证属性不能掩盖本例断言减少、属性单独变更仍 C，
  以及 base 相对共同祖先收紧或放宽规则时，报告均使用 base 策略。
