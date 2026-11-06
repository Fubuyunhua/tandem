# PR 描述草稿：接入 PR 风险等级闸门（task-003）

目标分支：`feat/m1-runnable`。本轮仅在本地开发和提交，未推送、未创建远程 PR。

## 改动与行为

新增 `scripts/gate/risk_level.py`，通过现有 `GitDiffSource` 和 `compute_level`
根据真实提交差异计算等级。普通代码和纯文档均为 C；命中底线为 D；无改动为 A。
不接收模型意见。输出含中文规则解释的报告和 UTF-8 JSON，列明提交编号、共同祖先、
各文件新旧路径、路径规则、删除和断言变化。密钥扫描明确标为“未扫描”。

新增只由 `pull_request` 触发的工作流，检查名固定为 `risk-level`，权限仅
`contents: read`。检出 PR head 的完整历史，使用事件里的 base/head，
而非 GitHub 生成的测试合并提交。D 级退出码为 3，使检查失败并显示“需要人工”；
输入、配置、采集或输出错误退出码为 2；A/B/C 返回 0。
失败时也会运行摘要步骤，且不会抹去闸门失败状态。

## 本地使用与结果

在已安装本项目的仓库根目录运行：

```powershell
uv run python scripts/gate/risk_level.py --base <base提交> --head <head提交> --output risk-level.json
```

默认仓库为当前目录，可用 `--repo` 指定，策略读取该仓库当前工作树的 `risk.yml`。
`--base` 和 `--head` 须成对指定；省略时从 `GITHUB_EVENT_PATH` 的 PR 事件读取。
比较范围遵循采集器的 `base...head`，报告同时记录实际共同祖先。
本地默认 JSON 文件写到当前目录；可用 `--summary` 额外保存 Markdown 报告。
工作流将两份报告写入 `$RUNNER_TEMP/risk-level.json` 和 `$RUNNER_TEMP/risk-level.md`，
JSON 可供同一 job 的后续步骤读取，Markdown 会写入 job summary。

## 已知限制与 task-001 问题

- 修改 `.github/workflows/risk-gate.yml` 本身也是 D 级。但工作流按 PR 分支里的版本运行，
  有人可以在同一个 PR 里修改闸门。须靠分支保护和“D 级必须人工批准”兜底；
  本轮不解决，也不会自动配置分支保护或实现人工批准后变绿的机制。
- 密钥扫描尚未接入，结果标明“未扫描”。
- 内核规定改名同时判断新旧路径，并不把改名本身直接判 D。
  “移入 docs/ 判 D”以受保护源路径的移动作为验收场景；
  普通代码文件移入 docs/ 且无其他底线命中时仍为 C。
  这是按既有 ADR 和内核语义作出的选择；若任务意图为所有此类移动都判 D，
  需要另行调整 task-001 的规则，本轮未修改内核。
- task-001 的采集器按所有改动测试文件合计断言数量，存在抵消遗漏：
  `tests/test_app.py` 从 2 条减到 1 条，同时另一测试文件新增 1 条，合计仍为 2，
  因而现有内核判 C。新增复现测试记录了当前行为；报告会指出具体文件的断言减少，
  但等级仍忠实使用现有内核结果。本轮未修改采集器或内核。

## 验证

每次提交前均离线执行 `uv run ruff check`、`uv run ruff format --check`、
`uv run pyright`、`uv run pytest`；额外显式检查脚本的类型，
因为项目当前 pyright 默认范围只有 `src` 和 `tests`。
新增测试使用真实临时 Git 仓库，通过子进程断言标准输出、JSON、摘要和退出码，
覆盖任务书要求及 PR 默认输入、错误输入、分叉历史和上述既有边界。
工作流权限及阻断契约也有本地检查。未联网，未运行 GitHub Actions；
远程检查结果须在后续 PR 中确认。
