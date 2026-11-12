# tandem

个人 AI 开发循环系统：调度多家 AI 承担大部分实现工作，同时保证使用者在过程中持续锻炼**数学建模、架构设计、批判能力**。

名字来自双人自行车：AI 出大部分力气，但人也必须一直在蹬。

这个项目用它自己的流程开发它自己。

审核候选改动必须使用受信版本的策略。Runner 不从候选工作树重载 risk.yml，
而是始终使用构造时注入的不可变 Policy。启动器必须从受信的安装或已批准版本加载策略，
不能在待审核的候选工作树中加载其 risk.yml 来给该候选改动定级。

路径规则跨平台统一按大小写不敏感匹配，并保护目录自身（包括 gitlink）。
这会在 Linux 等大小写敏感环境中多报一些 D，换取 Windows/macOS 下不会因大小写漏报。
pyproject.toml 整个文件都按 D 处理，即使只修改无害的文档元数据或工具设置也需走 D 流程；
这是避免同一配置文件中的依赖、测试与 CI 设置绕过审核的保守代价。

改动采集先把引用固定为完整 OID，再在临时 bare 仓库中读取原对象库；不继承原仓库
或用户的 diff 配置，也不运行 external diff/textconv。子模块指针始终参与采集。
事件保存两端文件模式及链接目标；符号链接不按纯文档放宽，指向保护区或仓库外则判 D。
删除文档和删除其他文件一样命中删除底线，判 D；删除后的 000000 模式不能作为纯文档放宽，
因此这里并不是从 A 放宽到 B 的行为变化。
链接链按 Git 树逐段解析，循环或超过层数限制时拒绝采集，不跟随工作区文件系统链接。

Python 断言用 AST 计数，注释和字符串不算断言；无法解析时拒绝确认。
JS/TS 词法扫描剥掉注释、字符串、模板和正则字面量，并按前文区分正则与除号；
assert 只在调用/成员位置计数，纯同名变量不计。它仍不是完整 JS/TS 解析器，
模板插值、复杂语法歧义、别名和动态调用等存在近似边界，不能证明测试语义或强度。
测试命名覆盖 test/spec 的 JS、TS、JSX、TSX 文件及 __tests__ 目录；
改名为非测试路径或离开原测试目录按删除测试判 D，即使文件本来没有断言。
测试收集边界保留大小写：tests/ 改成 Tests/ 或测试文件纯大小写改名同样判 D，
避免 Windows/macOS 本地看似等价的路径在 Linux CI 中不再被收集。
移进 pytest 默认忽略目录（build、dist、node_modules、venv、.*、*.egg、CVS、_darcs、
{arch} 等）也判为移出收集范围。只统计源码扩展名且符合测试命名的文件，排除 pyc 和 JSON 等 fixture。
文档放宽必须有覆盖全部路径的已知文件模式；模式未知或缺失时不放宽。

已知边界：Python 只计 assert 语句，self.assert*、pytest.raises 不计；换成这些风格可能被判 D。
计数不能证明断言会执行，也不能证明断言强度；提前 return、动态跳过或改成 assert True 等仍需审核。
新增 skip/skipif/xfail/importorskip 标记或调用、以及常量假分支内的断言，会生成带路径和行号的
静态弱化证据并判 D；仅比较两端新增信号，既有标记不会因行号移动再次报警。
这是按 AST 名称和常量条件保守检测，可能多报，仍不等于实际执行数量或沙箱中的动态证据。
无法确认证据时拒绝采集并抛出 DiffError：例如无共同祖先、部分克隆缺对象、已有 blob 不可读、
Python 解析失败（包括不支持的 BOM/UTF-16 输入或语法错误）、非 commit 引用、链接循环或超过 40 层。
这些错误不应被当作 C 或成功；闸门应以错误退出而不是放行，本轮不执行候选测试来补证据。

## 文档
- 需求：[`docs/PRD.md`](docs/PRD.md)
- 架构决策：[`docs/adr/`](docs/adr/)
- 任务状态流转：[`docs/design/task-lifecycle.md`](docs/design/task-lifecycle.md)
- GitHub 适配器：[`docs/github-adapter.md`](docs/github-adapter.md)

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
$planSha = Read-Host '粘贴 show 摘要中“方案提交编号”的完整编号'
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
  `--max-rounds` 默认 10，必须为正整数。全部任务到达终点返回 0；仍有任务待处理、
  等人或卡住时打印数量并返回 1（普通单轮 run 也一样）；达到轮数上限时返回 2。
  空数据库同样视为全部完成；终点包含已合并、已取消和失败，退出码不代表真实 PR 已合并。
- `--agent-script ok|ci-red|refuse` 默认 `ok`；`ci-red` 模拟 CI 失败。
  `refuse` 在任务上一轮被 AI 审核退回后模拟拒绝修改、进入“待你介入”；其他情况下
  按正常回执处理，D 级未批方案时仍先交方案。
- `--changes` 是本次模拟采集到的路径（逗号分隔，必填且不能全空），对本轮所有任务
  生效；每次代码回执都会按它重新分级。任务等级**只升不降**（K7）：等级取"任务当前
  等级"和"本次改动算出的等级"里更严格的那个，所以 D 级任务即使后续提交的改动看起来
  只碰普通文件，仍然保持 D、仍然要经过"待你审核"；`show` 的原因里会写明"本次改动
  算出 X 级，但任务已是 D 级，保持 D 级"。
- 数据库不存在时，`run` 返回 1，不创建空库或父目录；先用 `submit` 建立任务。
- `--review pass|fail` 默认 `pass`，只控制 AI 审核阶段；单 Agent 仍由你审核。
- 停在“待你批准方案”“待你审核”“待你介入”时会给出 `show` 和适用的 `approve`
  命令。否决意见需要 `--veto '完整复合键=你的理由'`，每项分别填写。
  CI 红时不能批准；可用 `cancel --task-id ...` 取消任务。
  “待验收”“待AI审核”“待合并”也会提示核对 CI、审核结论或合并动作。
  模拟合并必须同时满足当前 SHA 的 CI 和批准证据，且最近一次 MERGE 动作已确认 DONE；
  动作缺失、SENT 或 UNKNOWN 时会停住，不补造合并成功事件。
- `show <任务编号>` 输出完整任务 JSON 和按顺序记录的历史事件，包含完整提交编号、
  审核正文、待回应意见键、版本、原因、动作状态；不对真实代码或真实 CI 作证明。
  头部先摘要展示 CI、已批准 SHA 与当前是否一致、本轮审核、待回应意见数和方案批准状态。
  当前方案正文和方案提交编号独立展示，批准方案应使用该方案编号；代码编号可能不同。
  C 级按实际改动升成 D 时，方案正文会明确显示“没有文字方案，内容就是提交 …”。
  当前内核仅保存 CI 绿灯布尔值，False 展示为“未通过或未知”，不把缺失证据当作已知红灯。
- 运行时提示中的命令参数按平台转义：Windows 使用 PowerShell 单引号，其他平台使用
  POSIX shell（shlex）规则；上面的 PowerShell 示例在其他 shell 中需相应调整变量语法。
- 本轮没有增加异常恢复、人工接手提交和介入后重做的 CLI 入口。对于已有的
  “处理中”且丢失回执、“异常”或“你处理中”任务，run 会停止并提示人工处理，
  不会假装已核对外部结果或自动重新启动工作。
