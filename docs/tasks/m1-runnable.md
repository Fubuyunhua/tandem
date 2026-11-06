# 任务书：M1 可运行骨架（task-001）

- 写手：pi（模型 opencode-go/deepseek-v4.1-flash）
- 审核：Codex、Claude（两家都不是写手所在的提供方，符合 ADR-0001"多家审核"）
- 闸门：CI 必须全部通过
- 用户的决定（原话）："本次所有的代码都由ai生成，先给我搞一个能够跑的项目，我在你们测试完成之后进行人工的审核和后续的手动代码修改"
  - 所以这一次 `core/` 也由 AI 写。用户审核以后，再自己手动修改。

## 先读这些
1. `docs/design/task-lifecycle.md`：**最前面的"第七版"**是要实现的状态流转（13 个状态、转换表 #1–#27、取消表、任务记录字段）。后面的旧版本只是讨论记录，不要实现。
2. `docs/adr/0001-overall-architecture.md`："裁决原则""底线条目""基础级别怎么算""等级 → 流程表""第三版架构""可重放"这几节。
3. `docs/PRD.md` 的 F4 回执协议。
4. 现有代码：`src/tandem/`、`tests/test_purity.py`、`pyproject.toml`、`.github/workflows/ci.yml`。

## 目标
做出一个**能在本地完整跑一遍**的最小循环：任务从提交开始，经过状态流转、等级计算、（假的）Agent 干活、（假的）审核，一直走到"已合并"或停在需要人处理的状态。所有判断都在纯函数内核里完成，外壳负责存储和执行。

**这一轮不做的事**：不调用任何真实的 AI；不真正合并 PR；不发飞书消息；不做额度调度器（ADR-0001 已暂缓）。

## 目录结构（可以微调，但内核和外壳的边界不能变）
```
risk.yml                       # 策略：底线路径、可放宽路径、等级流程、上限
src/tandem/core/
  model.py                     # 枚举和不可变数据结构
  level.py                     # 根据真实改动算等级
  transition.py                # decide()：实现第七版转换表
src/tandem/shell/
  config.py                    # 读取 risk.yml，转成 Policy
  store.py                     # SQLite：事件只追加；任务记录带状态版本号；动作记录
  receipt.py                   # 解析回执
  agents/base.py               # Agent 适配器接口（Protocol）
  agents/fake.py               # 按剧本行动的假 Agent，供测试和演示用
  agents/claude_cli.py         # 调用 `claude -p --output-format json`，带超时和强制结束；不在测试里运行
  executor.py                  # 执行动作；默认 dry-run（只记录，不产生真实副作用）
  runner.py                    # 读事件 → 调内核 → 先保存再执行
  cli.py                       # 命令行入口 `tandem`
tests/
  test_purity.py               # 已有，不要削弱
  core/...                     # 内核测试
  shell/...                    # 外壳测试（用临时目录里的 SQLite）
```

## 内核要求（`src/tandem/core/`）
- 必须通过 `tests/test_purity.py`：不读时钟、不取随机数、不读写文件、不联网、不导入 `tandem.shell`。
- 主函数签名：
  ```python
  def decide(task: TaskRecord, event: Event, policy: Policy, quota: QuotaSnapshot, now: datetime) -> Decision
  ```
  `Decision` 里包含新的 `TaskRecord` 和动作清单 `list[Action]`。
- 用 `Enum` 定义 13 个状态、A–D 四个等级、运行模式（单 Agent / 多 Agent）。每个 `match` 末尾都写 `assert_never`，让 pyright 能查出漏处理的情况。
- 数据结构用 `@dataclass(frozen=True)`，内核不修改传入的对象。
- **等级计算**（`level.py`）：按 ADR-0001 的"基础级别怎么算"实现：
  - 先查底线，再看是不是 A 级；
  - 改名时，改名前和改名后的路径都参与判断；
  - 断言数量减少算 D；命中密钥扫描算 D；
  - 模型意见可以随便往上调；只有改动全是纯文档时，才能从 C 降到 B。
  - 改动信息由外壳收集好，用 `ChangeSet` 传进来，包括改动的路径、删除的文件、改名的路径对、断言数量的变化、是否命中密钥扫描。
- **转换**：实现第七版的 #1–#27 和取消表。另外：
  - 每个任务带状态版本号。事件里如果带了版本号，但和任务当前的版本号不一致，就忽略这个事件，不改任何东西。
  - 已取消的任务后来又收到回执，直接忽略。
  - 有新提交进来时，针对旧提交的审核结论、批准、否决全部作废。
  - 审核者从额度快照里挑选：要求来自不同的提供方，而且不能是写过这次代码的提供方（参与过的提供方集合要一直保留）。
  - 额度未知时，默认还有额度；收到"额度用完"事件后，再把这一家标记为用完。
  - 第 26 条（异常后重试）：外壳会先去核对外部事实，再发一个带核对结果的事件，比如"合并实际上已经成功"。内核根据这个结果决定进入哪个状态。

## 外壳要求（`src/tandem/shell/`）
- 运行时依赖只允许新增 `PyYAML`（开发依赖可以加 `types-PyYAML`）。
- `store.py`：事件表只追加；任务表保存最新快照和状态版本号；动作表记录每个动作的编号和状态（已发出 / 结果未知 / 已完成）。数据库默认放在 `data/` 目录下（已被 git 忽略）。
- `receipt.py`：回执格式是第一行写结论，后面附 JSON。JSON 必须包含 `task_id`、`attempt`、`sha`，缺任何一个都算无效回执。
- `executor.py`：所有会产生外部副作用的动作（合并、关闭 PR、推送、启动真实 Agent）默认都是 dry-run，只记日志。只有假 Agent 会真的"运行"。
- `cli.py`：在 `pyproject.toml` 里注册 `tandem` 命令，至少提供这几个子命令：
  - `tandem demo`：用临时数据库和假 Agent 跑两个场景，打印每个任务经过的状态路径。
    - 场景 1：C 级任务，多 Agent 模式，最后走到"已合并"（dry-run）；
    - 场景 2：D 级任务，停在"待你批准方案"。
  - `tandem status`：列出任务和它们当前的状态。
  - `tandem submit`、`tandem approve`、`tandem reject`、`tandem cancel`：对任务做相应操作。

## 测试要求
- 第七版转换表的**每一条**都至少有一个测试，测试名里带上条目编号，比如 `test_row_12_all_reviewers_pass_merges`。
- `task-lifecycle.md` 第 4 节的 9 个场景，每个都写成一个测试，按场景描述把整条路径走一遍。
- 等级计算：每一条底线条目、改名、纯文档降级、"先查底线再看 A 级"，都要有测试。
- 外壳：回执解析（有效和无效两种情况）；store 的只追加和版本号；`demo` 端到端跑通。
- 测试里不能联网，也不能调用真实的 AI。

## CI
在 `.github/workflows/ci.yml` 里，测试之后加一步 `uv run tandem demo`，作为冒烟测试。其他步骤不要改，也不要改触发方式和权限。

## 工作方式
- 在当前分支 `feat/m1-runnable` 上工作，**分几个小提交**，比如：模型和等级 → 转换 → 外壳 → CLI 和 demo → CI。
- 每次提交前都运行：`uv run ruff check`、`uv run ruff format --check`、`uv run pyright`、`uv run pytest`，全部通过才提交。
- 使用仓库里已经配置好的 git 身份，不要修改 git 配置，**不要推送**。
- 不要修改 `docs/adr/`、`docs/design/`、`docs/PRD.md`、`docs/tasks/`，也不要修改 `tests/test_purity.py` 的检查规则。
- 代码里的标识符用英文，注释和文档字符串用中文。
- 遇到任务书没写清楚的地方，按 ADR-0001 和第七版的原则自己做合理的选择，并在最后的回报里列出来。

## 完成后
在终端回复：
1. 第一行写 `DONE`；
2. 列出提交清单；
3. 列出你自己做的、任务书里没写清楚的选择。
