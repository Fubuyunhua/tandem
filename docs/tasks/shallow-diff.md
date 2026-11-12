# task-008：隔离 diff 在浅克隆里报错

分支 `fix/shallow-diff`（基于 `feat/m1-runnable@0f2c69b`），工作目录 `C:\Users\weicai\Desktop\projects\tandem-redteam`。

## 问题（来源：PR #8 上 Codex 机器人的 P2 意见，还没修）

`src/tandem/shell/diff_source.py` 在临时 bare 仓库里只借用源仓库的对象库（`GIT_OBJECT_DIRECTORY`）。
浅克隆的边界信息存在源仓库的 `.git/shallow` 文件里，临时仓库没有这个文件。
结果：在浅克隆里，两个相邻提交本来能算出 merge-base，`collect` 却因为去读边界之外不存在的父提交而抛 `DiffError`。
CI 默认就是浅克隆，所以这会让等级算不出来。

## 要做的

1. 先写一个失败的测试复现它：建一个有 3 个以上提交的仓库，用 `git clone --depth 2 file://...` 做浅克隆，对最近两个提交调用 `GitDiffSource.collect`，现在应该抛 `DiffError`。
2. 修复，二选一，选你认为更稳的并在提交说明里写理由：
   - 把源仓库的 shallow 边界带进临时仓库（例如把 `.git/shallow` 复制到临时仓库的 `shallow` 文件；注意 worktree 场景下要用 `git rev-parse --git-common-dir` 找到真实位置）；
   - 或者 merge-base 在源仓库里算好，再把得到的完整 OID 交给隔离仓库只做树比较。
3. 不能削弱已有的隔离：不读用户 git 配置、`--no-ext-diff --no-textconv --ignore-submodules=none`、只认完整 OID，这些测试都要继续通过。
4. 边界之外确实缺对象时（例如 base 不在浅克隆范围内），要明确报 `DiffError` 并说清原因，不能静默算出空改动。为这个情况也加一条测试。
5. 顺手修一个测试小问题：`tests/gate/test_risk_level.py` 里在 Windows 上找 Bash 的逻辑用 `Path(shutil.which("git")).resolve().parents[1] / "bin/bash.exe"`。从 Git Bash 里跑测试时 `which git` 是 `mingw64/bin/git`，算出来的路径不存在。改成依次尝试几个候选位置（`<Git 根>/bin/bash.exe`、`<Git 根>/usr/bin/bash.exe`，Git 根要能从 `mingw64/bin` 和 `cmd` 两种位置推出来）。

## 完成标准

- 在 PowerShell 里：`uv run ruff check`、`uv run ruff format --check`、`uv run pyright`、`uv run pytest`、`uv run tandem demo` 全过。
- 提交作者用仓库里已配置的身份，不要改 git config。按仓库已有习惯写中文提交说明。本任务说明文件也一起提交。
- 不要 push，不要建 PR，做完告诉我提交编号和你选了哪种修法。
