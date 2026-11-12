# task-009：落实用户已拍板的三项决定（K4 / K6 / K7）

分支 `feat/decisions`（基于 `feat/m1-runnable@0f2c69b`），工作目录 `C:\Users\weicai\Desktop\projects\tandem-gate`。
用户在 2026-11-12 接受了这三项的推荐方案。`docs/m1-acceptance.md` 第 6 节有它们的背景。

## K7（原 L1）：任务等级只升不降

问题：D 级方案批准后，如果实际提交的改动只命中普通文件，内核按真实改动重算成 C 级，就会不经你审核自动合并（见 `docs/tasks/reviews/task-005-claude.md` 的 L1）。

要做：
1. 内核里每次重算等级的地方（`src/tandem/core/transition.py` 中调用 `compute_level` 的三处：交回代码、新提交、你提交代码）改成取 `max(当前任务等级, 本次算出的等级)`，顺序 A < B < C < D。等级比较写成一个小的纯函数放在 `core/level.py`，不要在三处各写一遍。
2. 状态说明里要能看出“本次改动算出 C，但任务已是 D，保持 D”，方便你在 `tandem show` 里看懂。
3. 外壳 `local_run.py` 里“模拟改动导致等级下降就停下、需要 `--allow-level-drop`”的逻辑现在多余了：删掉 `--allow-level-drop` 选项和对应分支，相关测试改成验证“等级不会下降”。README 里关于 `--changes` 不记忆会导致降级的提醒（task-005 的 L2）一并删除或改写。
4. 测试：至少覆盖 ① D 级方案批准后提交普通代码仍是 D、仍要经过“待你审核”；② C 级任务提交命中底线升到 D；③ 三处入口都遵守只升不降。
5. 这是内核改动，本身属于 D 级，改完我会审核。

## K6（原 J2）：等级闸门对 D 级只报告，不让检查失败

问题：`scripts/gate/risk_level.py` 对 D 级以退出码 3 结束，GitHub 检查显示红叉。如果把它设为必需检查，D 级 PR 就永远不能合并；人工关口其实已经由内核的“待你审核”保证。

要做：
1. D 级退出码改为 0；报告 JSON 里 `needs_manual: true` 保留，工作流摘要标题继续写明“需要人工”。
2. 真正的错误（输入非法、取不到提交、读不了规则）仍然退出 2，检查仍然失败。这一点要有测试守住。
3. 同步修改 `.github/workflows/risk-gate.yml` 里依赖退出码 3 的判断和摘要文案、`docs/risk-gate-pr.md`、`docs/tasks/risk-gate.md` 里的相关描述，以及 `tests/gate/` 下的期望值。
4. 注意 `.github/**` 和 `scripts/gate/**` 都是底线路径，这个改动本身是 D 级。

## K4：换了新提交，验收失败次数不清零

现状已经是“跨新提交累积”。要做的只是把它固定下来：
1. 加一条测试：失败两次后交回新提交，再失败一次就到上限，进入“待你介入”（R01）。如果已有等价测试，在测试名或注释里标明它守的是 K4 决定，不要重复写。
2. 在内核相关处理函数的注释里写一句这是有意为之，原因是防止 Agent 靠不停换提交无限重试。

## 文档

`docs/m1-acceptance.md` 第 6 节把 K4、K6、K7 从“待你决定”改成“已决定（2026-11-12）”，写明选了什么、代价是什么。第 7 节审核路线里提到这三项要你拍板的句子同步改掉。

## 完成标准

- 在 PowerShell 里：`uv run ruff check`、`uv run ruff format --check`、`uv run pyright`、`uv run pytest`、`uv run tandem demo` 全过。
- 三项各自独立提交，中文提交说明写清对应哪一项。提交作者用仓库里已配置的身份，不要改 git config。本任务说明文件也一起提交。
- 不要 push，不要建 PR。做完告诉我每项的提交编号。
