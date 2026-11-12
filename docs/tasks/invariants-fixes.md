# task-006 第二轮：性质测试跟上新内核，并修复 pi 审核的 P1–P7

分支 `feat/state-invariants`，工作目录 `C:\Users\weicai\Desktop\projects\tandem-inv`。
我已经把最新的 `feat/m1-runnable@0f2c69b` 合进来了（提交 4709b4f，还没 push）。这次合并带进了 PR #3/#4/#5/#8，其中 #8 的红队修复改了不少内核规则（例如方案和代码事件只认完整 40/64 位 OID、`.gitattributes` 进底线、CI 先绿后红会退回待处理）。

## 第一步：让测试重新变绿（现在 58 个失败）

在 PowerShell 里跑 `uv run pytest`：`tests/core/test_invariants.py` 31 个失败，`tests/shell/test_shell_invariants.py` 27 个失败。典型报错：

- `Fault(seam='_write_task', ...).fired` 为 False：外壳的存储写入路径变了，故障注入点没被触发；
- `DID NOT RAISE AssertionError`：变异体没被抓到，可能是生成器产生的事件被新规则拒收了（例如非 OID 的 sha）。

要求：先弄清每类失败的原因，再改测试去贴合**新的内核规则**。不允许为了变绿去改 `src/` 下的内核或外壳代码；如果你认为内核真有 bug，停下来写清楚反例告诉我。

## 第二步：修复 `docs/tasks/reviews/task-006-pi.md` 里的 P1–P7

- P1：多审核者不变量要求审核来自指定的审核席位（`designated_reviewers`）；
- P2：D 级必须经过“待你审核”，用真正的路径检查替代现在的近似；
- P3：新增不变量：你的批准必须绑定当前提交（`approved_sha == latest_sha`）才能进入待合并/合并；
- P4：断言过期或错位的事件被忽略（状态和版本号不变）；
- P5：提高“错误 SHA 的 CI 绿”的采样比例；
- P6：把变异测试里过松的 `match="d"` 改成精确匹配；
- P7：让那 5 个从没到达过的状态能被生成器走到，并加一个覆盖率断言（每个状态至少到达一次）。
- P8 只需要在测试文件头的注释里说明：这些 oracle 与内核规则有重复，改内核规则时要同步。

每修一条，按“先让测试在旧代码上失败（或证明变异能被抓到），再改”的顺序做，并在提交说明里写明对应哪一条。

## 完成标准

- 在 PowerShell 里：`uv run ruff check`、`uv run ruff format --check`、`uv run pyright`、`uv run pytest`、`uv run tandem demo` 全过。
- 性质测试总耗时不要比现在长太多；如果 Hypothesis 例子数要调，写明理由。
- 提交作者用仓库里已配置的身份，不要改 git config。中文提交说明，本任务说明文件也一起提交。
- 不要 push，不要建 PR。做完告诉我：每条 P 的提交编号，以及第一步每类失败的原因。
