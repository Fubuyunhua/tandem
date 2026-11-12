# task-008 审核（Claude，范围 2cb30d1）

结论：**浅克隆确实修好了，但把 merge-base 搬回源仓库，重新打开了一个能把改动整个藏掉的口子（S1），必须改。**

## S1（必须改）源仓库里的 grafts 可以伪造共同祖先，让 diff 变空

隔离仓库存在的意义，就是不让 Agent 能写到的 `.git/` 内容影响“改了什么”的计算。
现在 merge-base 在源仓库里算，`--no-replace-objects` 只关掉了 replace 引用，**没有关掉 grafts**。

我实测的反例（Git for Windows，本机）：

```text
M ── B          （base 分支）
 \
  S             （受审提交，新增 core.py）

真实 merge-base(B, S) = M
写入 .git/info/grafts：「<B> <S>」（宣称 B 的父提交是 S）
git --no-replace-objects merge-base B S  →  S
```

merge-base 变成 S 以后，`diff S..S` 是空的，新增的 `core.py` 不出现在改动里，等级会算成 A。
加上 `GIT_GRAFT_FILE=<不存在的路径>` 以后，结果恢复为 M。

要做：
1. 源仓库里跑 merge-base 时，同时满足：
   - 环境变量 `GIT_GRAFT_FILE` 指向一个不存在的路径；
   - `--no-replace-objects`；
   - `-c core.commitGraph=false`（commit-graph 文件里的父提交信息不经校验就会被采信，伪造的图同样能改变祖先关系）；
   - 继续用 `_clean_git_environment()`。
2. 隔离仓库里也加 `-c core.commitGraph=false`。它借用的对象目录里的 `objects/info/commit-graph` 同样可能被伪造。这是修复之前就存在的问题，一起修。
3. 测试：
   - 用上面的 grafts 反例：在源仓库写 `.git/info/grafts` 以后，`collect` 仍然报出 `core.py`，或者明确报 `DiffError`，**不能**得到空改动；
   - 断言两处 git 调用都带了 `core.commitGraph=false`（伪造 commit-graph 文件很难在测试里构造，检查参数即可）。
4. `.git/shallow` 也能被 Agent 改，但它只能删掉祖先边、不能加边，最坏结果是算不出共同祖先而报错，或者退到更老的祖先、显示更多改动。这一点在注释里写清楚，不需要额外处理。

## 已确认没问题
- 浅克隆的复现测试（`file://` + `--depth 2`），以及 base 落在边界之外时明确报错，两条测试都对。
- `resolve_oid` 失败时的报错信息更清楚了，仍然只接受完整 OID。
- gate 测试里的 Bash 定位改成多候选，从 Git Bash 里跑也能通过。

## 小问题
- Bash 定位的修复同时出现在 `fix/shallow-diff`（2cb30d1）和 `feat/decisions`（4403cf5）两个分支上，写法略有不同。不用处理，合并时我保留 `fix/shallow-diff` 这一版。

## 第二轮（d87f17e）

S1 已修好：`GIT_GRAFT_FILE` 指向空设备，所有 git 调用都带 `-c core.commitGraph=false`，merge-base 另外带 `--no-replace-objects`。兄弟分支的 grafts 反例在旧实现上采集出空改动，现在仍报出受保护文件并判 D；另有测试检查每次调用的参数和环境。本地 PowerShell：675 passed，ruff、pyright、demo 全过。**通过。**
