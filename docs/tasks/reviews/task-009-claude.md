# task-009 审核（Claude，范围 4403cf5..1d9857c）

结论：**通过，没有需要改的问题。**

- K7（271fd43）：等级比较集中在 `core/level.py` 的 `keep_stricter`，三个重算入口都走它；`_on_new_submission` 把新等级写回任务；状态说明能看出“算出 C，保持 D”。外壳的 `--allow-level-drop` 及其分支一并删除，没有留下第二套判断。
- K6（b43d994）：D 级退出码改为 0，`needs_manual: true` 和“需要人工”摘要保留；输入、采集、规则读取错误仍然退出 2，有测试守住。工作流里没有残留依赖退出码 3 的判断。
- K4（09ebb4b）：新测试用三个不同提交累积到 R01，和已有的同一提交测试不重复；`_on_ci_red` 的注释写明了理由和代价。
- 本地 PowerShell：ruff、pyright、681 passed、demo 全过。

备注：4403cf5（Bash 定位）与 `fix/shallow-diff` 的 2cb30d1 改的是同一处，合并时保留后者。
