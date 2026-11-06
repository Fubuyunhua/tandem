# tandem

个人 AI 开发循环系统：调度多家 AI 承担大部分实现工作，同时保证使用者在过程中持续锻炼**数学建模、架构设计、批判能力**。

名字来自双人自行车：AI 出大部分力气，但人也必须一直在蹬。

这个项目用它自己的流程开发它自己。

## 文档
- 需求：[`docs/PRD.md`](docs/PRD.md)
- 架构决策：[`docs/adr/`](docs/adr/)
- 任务状态流转：[`docs/design/task-lifecycle.md`](docs/design/task-lifecycle.md)

## 代码结构
- `src/tandem/core/`：内核，只做判断的纯函数（不读时钟、不联网、不读写文件）
- `src/tandem/shell/`：外壳，负责和外部世界打交道
- `tests/test_purity.py`：检查内核有没有接触外部世界

## 本地开发
需要 [uv](https://docs.astral.sh/uv/)。

```sh
uv sync
uv run ruff check
uv run ruff format --check
uv run pyright
uv run pytest
```


## 手动走一遍本地模拟

以下命令在仓库根目录的 PowerShell 中执行。环境已经安装依赖时，可把
`uv run` 写成 `uv run --offline --no-sync`，完全离线运行。

`run` 只使用假 Agent、假改动采集器、假 CI 和假审核者；打印的“已合并”也只是
本地任务记录，不会创建真实提交、调用真实 AI、推送或合并 PR。
建议为手动演示使用下面单独的数据库，避免与其他任务混在一起。

### 单 Agent：提交、查看、人工批准、模拟合并

```powershell
uv run tandem submit --db data/manual-single.sqlite3 --task-id single-demo --mode single_agent --paths src/x.py
uv run tandem run --db data/manual-single.sqlite3 --changes src/x.py
# 停在“待你审核”，先查看完整记录和模拟 CI 事件。
uv run tandem show single-demo --db data/manual-single.sqlite3
$sha = Read-Host '粘贴 show 输出中的完整提交编号'
uv run tandem approve --db data/manual-single.sqlite3 --task-id single-demo --sha $sha
uv run tandem run --db data/manual-single.sqlite3 --changes src/x.py
uv run tandem show single-demo --db data/manual-single.sqlite3
# 现在是“已合并”（模拟）。
```

`approve` 必须使用你刚查看的完整提交编号。错误编号不会放行。

### 多 Agent：D 级先批方案，再经两家模拟审核和人工批准

模式在 `submit --mode` 时保存到该任务，不需要修改 `risk.yml`。
这里使用 D 级改动，展示多 Agent 下仍然必须由你批准的两个关口。

```powershell
uv run tandem submit --db data/manual-multi.sqlite3 --task-id multi-demo --mode multi_agent --paths src/tandem/core/model.py
uv run tandem run --db data/manual-multi.sqlite3 --changes src/tandem/core/model.py
# 停在“待你批准方案”；记录中显示本次模拟改动路径和方案。
uv run tandem show multi-demo --db data/manual-multi.sqlite3
$planSha = Read-Host '粘贴方案的完整提交编号'
uv run tandem approve --db data/manual-multi.sqlite3 --task-id multi-demo --sha $planSha
uv run tandem run --db data/manual-multi.sqlite3 --changes src/tandem/core/model.py --review pass
# 两家模拟审核通过后，D 级停在“待你审核”。代码编号与方案编号不同。
uv run tandem show multi-demo --db data/manual-multi.sqlite3
$codeSha = Read-Host '粘贴这次代码的完整提交编号'
uv run tandem approve --db data/manual-multi.sqlite3 --task-id multi-demo --sha $codeSha
uv run tandem run --db data/manual-multi.sqlite3 --changes src/tandem/core/model.py
uv run tandem show multi-demo --db data/manual-multi.sqlite3
# 现在是“已合并”（模拟）。
```

C 级在多 Agent 下两家模拟审核通过就自动推进到模拟合并，不需要 `approve`。
可以用以下例子体验审核不通过、退回修改和再次运行：

```powershell
uv run tandem submit --db data/manual-review.sqlite3 --task-id review-demo --mode multi_agent --paths src/x.py
uv run tandem run --db data/manual-review.sqlite3 --changes src/x.py --review fail
uv run tandem show review-demo --db data/manual-review.sqlite3
# 待回应意见带完整复合键；本轮结束在“待处理”。
uv run tandem run --db data/manual-review.sqlite3 --changes src/x.py --review pass
# 新的尝试产生新的模拟提交编号，重新审核后到“已合并”。
```

### 运行参数与暂停规则

- `run` 一轮处理数据库里的所有任务；每个任务最多派活一次，再走代码、CI、审核、
  模拟合并等自动步骤。退回“待处理”后要等下一轮，人工暂停不会阻止其他任务推进。
- `run --until-idle` 自动开始后续轮次，直到需要人工处理或整轮无进展；
  `--max-rounds` 默认 10，必须为正整数。达到上限尚未确认空闲时返回 2。
- `--agent-script ok|ci-red|refuse` 默认 `ok`；`ci-red` 模拟 CI 失败。
  `refuse` 在任务上一轮被 AI 审核退回后模拟拒绝修改、进入“待你介入”；其他情况下
  按正常回执处理，D 级未批方案时仍先交方案。
- `--changes` 是本次模拟采集到的路径（逗号分隔，必填且不能全空），对本轮所有任务
  生效。`submit --paths` 只是初始分级输入，**后续 run 不会记住它**；请像例子一样，
  每次提供一致的 `--changes`，尤其是在 D 级方案批准后。每次代码回执都会重新分级。
  如果新等级低于任务原等级，run 会在派活前醒目提示并停止该任务，不写入推进事件。
  只有确认接受审核或人工关口可能减少后，显式加 `--allow-level-drop` 才会继续。
- 数据库不存在时，`run` 返回 1，不创建空库或父目录；先用 `submit` 建立任务。
- `--review pass|fail` 默认 `pass`，只控制 AI 审核阶段；单 Agent 仍由你审核。
- 停在“待你批准方案”“待你审核”“待你介入”时会给出 `show` 和适用的 `approve`
  命令。否决意见需要 `--veto '完整复合键=你的理由'`，每项分别填写。
  CI 红时不能批准；可用 `cancel --task-id ...` 取消任务。
- `show <任务编号>` 输出完整任务 JSON 和按顺序记录的历史事件，包含完整提交编号、
  审核正文、待回应意见键、版本、原因、动作状态；不对真实代码或真实 CI 作证明。
- 本轮没有增加异常恢复、人工接手提交和介入后重做的 CLI 入口。对于已有的
  “处理中”且丢失回执、“异常”或“你处理中”任务，run 会停止并提示人工处理，
  不会假装已核对外部结果或自动重新启动工作。
