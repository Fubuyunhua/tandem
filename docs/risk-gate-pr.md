# PR 描述草稿：接入 PR 风险等级闸门（task-003）

目标分支：`feat/m1-runnable`。本轮仅在本地开发和提交，未推送、未创建远程 PR。

## 改动与行为

新增 `scripts/gate/risk_level.py`，通过现有 `GitDiffSource` 和 `compute_level`
根据真实提交差异计算等级。普通代码和纯文档均为 C；命中底线为 D；无改动为 A。
不接收模型意见。输出含中文规则解释的报告和 UTF-8 JSON，列明提交编号、共同祖先、
各文件新旧路径、底线原因、删除和断言变化。汇总与逐文件底线解释都调用内核的
`bottom_line_reasons()`；脚本只选取对应文件的采集数据，不另写路径匹配或断言计数。
JSON 的 `assertion_drops` 保留逐文件减少记录，断言合计仅用于概览。
密钥扫描明确标为“未扫描”。

等级工作流使用 `pull_request_target`，检查名固定为 `risk-level`，权限仅
`contents: read`，检出时设 `persist-credentials: false`。
检出事件指定的 base 提交作为工作目录，仅 fetch PR head 提交对象，不检出 head。
使用事件里的 base/head，而非 GitHub 生成的测试合并提交。
D 级退出码为 3，使检查失败并显示“需要人工”；
输入、配置、采集或输出错误退出码为 2；A/B/C 返回 0。
失败时也会运行摘要步骤，且不会抹去闸门失败状态。

## 安全模式：base 是裁判，head 仅是数据

采用 `pull_request_target` 是为了让工作流定义来自可信基准分支，
防止 PR 修改工作流、脚本或规则后给自己判低等级。
工作目录固定检出事件里的 `base.sha`：裁判脚本、`src/tandem`、`pyproject.toml`、
`uv.lock` 和 `uv sync --locked` 都来自 base，不执行 head 的任何文件。
即使本地调用时工作树位于 head，策略也固定通过 `git show <base>:risk.yml` 读取，
不会改读工作树、head 或共同祖先的规则；base 规则缺失或损坏时直接报错。
报告用 `policy_source` 标明该来源。

head 只作为 Git 对象供改动采集读取；`git diff`/`git show` 取出的内容不作代码执行。
fetch 使用环境变量中的已校验提交编号，事件文字不拼接到 shell 脚本。
仓库公开，fetch 匿名读取对象，不提供 token 或认证 header；
不递归获取子模块，不检出 head、不安装 head 依赖、不导入 head 包，
也不运行 head 中的本地 Action 或构建钩子。

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
- J2 待用户决定：D 级继续以退出码 3 使检查失败。若设为必需检查，人工批准本身
  不会使其变绿，当前没有合法合并路径；本次不新增批准后变绿机制，也不改退出码。
- 密钥扫描尚未接入，结果标明“未扫描”。
- 内核规定改名同时判断新旧路径，并不把改名本身直接判 D。
  “移入 docs/ 判 D”以受保护源路径的移动作为验收场景；
  普通代码文件移入 docs/ 且无其他底线命中时仍为 C。
  这是按既有 ADR 和内核语义作出的选择；若任务意图为所有此类移动都判 D，
  需要另行调整 task-001 的规则，本轮未修改内核。
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
