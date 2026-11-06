# task-005 审核 · Claude

结论：**可以**（有一处要用户决定的内核语义，不阻塞本 PR）。范围：`feat/cli-run` 的 5abc091..fa7e003。

## 实际操作验证（在临时数据库里按 README 走）
- 单 Agent：submit → run（停在待你审核，并打印 show / approve / cancel 的完整命令）→ 用错误编号 approve（拒绝，返回 2）→ 用正确编号 approve → run → 已合并。✅
- 多 Agent + D 级：run 停在待你批准方案 → 批准方案 → run（两家模拟审核通过后停在待你审核）→ 批准代码 → run → 已合并。✅
- 输出是"任务：旧状态 → 新状态（原因）"，停在人工关口时给出下一步命令，符合任务书。

## 要用户决定（内核语义，不是本 PR 的问题）
### L1 方案按 D 级批准后，实际改动只有普通文件，等级会降回 C，然后不经用户审核自动合并
- 复现：`submit --mode multi_agent --paths src/tandem/core/model.py` → run → 批准方案 → `run --changes src/x.py --review pass` → 直接到"已合并"。
- 按 ADR"等级以真实改动为准"，这是对的；但用户批准的是一个 D 级方案，可能默认后面还会自己看代码。
- 选项：a. 维持现状（等级只看真实改动）；b. 一个任务的等级只升不降：`max(提交时等级, 真实改动等级)`。我倾向 b，更符合"宁可多报"。

## 低
- L2：`--changes` 不记忆，D 级方案批准后忘了带同样的 `--changes` 就会出现 L1 的情况。README 已提醒；如果用户选 b，这个提醒可以删掉。
