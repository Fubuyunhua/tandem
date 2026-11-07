# task-006 审核 · pi（DeepSeek）

- 审核对象：`feat/state-invariants`（`6bb874d`，含并入的 `c4e67f7`）。新增 `tests/core/test_invariants.py`（1213 行）、`tests/shell/test_shell_invariants.py`（573 行）、任务书 `docs/tasks/state-invariants.md`、`hypothesis` 开发依赖。
- 方法：**只读**。没有改 worktree 里任何文件、没有提交。我把 `6bb874d` 用 `git archive` 导出到临时目录，用该 worktree 自己的 venv（含 hypothesis）跑测试、做变异实验与覆盖度统计；临时目录里改的是**导出副本**的内核代码，用来模拟"故意改坏"，测完已还原。没有联网、没有调用真实 AI。
- 我复现的基线：导出目录下 `pytest` **428 passed, 1 skipped**（34.9 s）；`tests/core/test_invariants.py` 单跑 **71 passed**（3.2 s）。深度模式实测：`TANDEM_INVARIANTS_DEEP=1` → core `DEEP=True, max_examples=1000`、shell `250`；core 性质文件 6.4 s，shell 的性质用例 97.7 s（可本地长跑，符合"CI 里默认关"的设计）。
- 结论：**修改后可以**。这套测试的结构（8 条不变量各有独立 oracle、每条都有"先跑通过再放变异"的变异验证、终态契约逐字段白名单、shell 崩溃恢复的 8 个 seam 强制触发）是我在这个项目里见过的最扎实的测试设计；但它对**内核规则**的覆盖比任务书列的字面不变量**更窄**——我用 6 个"真实退化的内核改动"做实验，4 个在 5 个随机种子上都**没被抓到**。下面按严重程度给出证据和最小改法。

## 一、按严重程度

### P1【中】"多家审核"没有约束"必须来自本次指定的席位"（M1 存活 5/5 种子）

- **位置**：`tests/core/test_invariants.py:101`（`check_review_count`）、`:288`（生成器）
- **问题**：oracle 只数"`task.reviews` 里 sha 与标准版本匹配、提供方不在 `providers_involved` 的通过结论 ≥ `min_reviewers`"。内核第 12 条的规则更严：结论必须来自 `designated_reviewers`（`_on_review` 里那条 `review.provider not in task.designated_reviewers → 忽略`），且 `designated ⊆ passing`。所以"忽略席位"的退化不会被任何 oracle 发现。
- **我的实验**（导出副本里改内核，跑 `tests/core/test_invariants.py`，种子 1–5）：把 `_on_review` 的席位校验改成 `pass`、并把 `complete` 从"席位全过"改成"家数够"→ **5 个种子全部 71 passed**。
- **为什么没抓到**：生成器发审核只用 `missing[0]`（必然是席位内），`choice==3` 的冒名审核虽然会用 `PROVIDERS` 里任意一家，但 `_reviews_by_provider` 仍按提供方聚合，凑齐两家（例如 `r1` + 未受邀的 `r3`）就满足了 oracle 的家数要求。
- **建议**：
  ```python
  # check_review_count 里补一句（与内核第 12 条对齐）
  seats = set(task.designated_reviewers)
  assert seats <= {r.provider for r in task.reviews if r.verdict is Verdict.PASS}, (
      "review_count: pass from outside the designated seats"
  )
  ```
  再给生成器加一档 `choice==7`：从 `PROVIDERS - designated` 里挑一家发 PASS（不是参与过写的提供方），让"未受邀审核者"成为常规输入。

### P2【中】第 6 条后半句"不经过待你审核就不能到待合并"被近似成"有人工批准事件"（M2 存活 5/5）

- **位置**：`tests/core/test_invariants.py:180`（`check_d`）、`:197`（`human_approval_sha`）
- **问题**：`check_d` 只要求"存在一个 `YOUR_APPROVAL`/`INTERVENTION_APPROVED` 输入，其 sha 等于当时的 `latest_sha`"。它无法区分"这个批准发生在待你审核"还是"发生在别的状态"。任务书第 6 条明确写的是"**永远不会不经过『待你审核』就进入『待合并』**"。
- **我的实验**：让 `_on_intervention_approved` 也接受 `AWAITING_ACCEPTANCE`（CI 已绿、sha 匹配），即"待验收 → 人工批准 → 待合并"，直接跳过待你审核 → **5 个种子全部 71 passed**（`check_ci` 也满足，因为 CI 确实是绿的）。
- **建议**：不变量要记"路径"，不能只看终态。生成器里已经有逐步的 `decision.task.status`，可以维护
  ```python
  seen_your_review_for_sha: str | None = None
  # 每一步后：if decision.task.status is TaskStatus.AWAITING_YOUR_REVIEW: seen_your_review_for_sha = decision.task.latest_sha
  ```
  然后在 `check_d` 的 `AWAITING_MERGE` 分支断言 `seen_your_review_for_sha == after.latest_sha`（D 级）。这条同时能抓住"从待验收直接批准"和"从异常/待介入直接批准"两种跳关。

### P3【中】"批准必须绑定当前提交编号"（r4 问题 3）没有任何不变量覆盖（M12 存活 5/5）

- **位置**：`tests/core/test_invariants.py:180`（`check_d` 只管 D 级）、`:101`（`check_review_count` 在单 Agent 或有人工批准时提前返回）
- **问题**：`_on_your_approval` 的 sha 校验（r4 修的就是这条）在性质测试里没有对应断言。去掉它以后，C 级任务在"待你审核"收到任何 sha 的批准都会进入待合并；oracle 侧 `human_approval_sha` 因为 `ev.sha != latest_sha` 返回 `None`，于是 `check_review_count` 退回"看审核结论"——单 Agent 模式直接 return，多 Agent 模式审核结论本来就够 → 全都放行。
- **我的实验**：删掉 `_on_your_approval` 的 sha 校验 → **5 个种子全部 71 passed**。
- **建议**：加一条与 `check_plan_approval` 同构的 oracle：
  ```python
  def check_approval_sha(before, ev, decision):
      if ev.kind not in (EventKind.YOUR_APPROVAL, EventKind.INTERVENTION_APPROVED):
          return
      if decision.changed and decision.task.status is TaskStatus.AWAITING_MERGE:
          assert ev.sha is not None and ev.sha == before.latest_sha, "approval_sha: not bound"
      elif ev.sha is None or ev.sha != before.latest_sha:
          assert not decision.changed, "approval_sha: unbound approval changed the record"
  ```

### P4【中】"过期/错位事件必须被忽略"没有显式断言，只能靠别的 oracle 撞上（M3 只在 1/5 种子上被抓到）

- **位置**：`tests/core/test_invariants.py:171`（`check_version` 只校验"changed ⇒ 版本 +1"）、`:288` 的 `choice==2`（生成 `state_version + 1`）
- **问题**：任务书特别要求生成器覆盖"过期、错位"事件，生成器确实生成了（`choice==2` 造未来版本号，`choice==4` 造别的任务编号，shell 侧还造 `state_version - 1` 和 `None`），但**没有任何 oracle 断言"这些事件必须被忽略"**。于是"删掉版本号校验"这种退化，只能靠它恰好把某个任务推到违规状态才会被别的 oracle 发现。
- **我的实验**：把 `_dispatch` 里的版本号校验改成 `if False:` → 种子 1–4 **全部通过**，只有种子 5 失败（`1 failed`）。也就是说 CI 单种子跑很可能漏掉。
- **建议**：加一条与"版本单调"互补的不变量（成本极低，生成器已经在造这类输入）：
  ```python
  def check_stale(before, ev, decision):
      if ev.task_id != before.task_id:
          assert not decision.changed and decision.task == before, "stale: wrong task accepted"
      if ev.state_version is not None and ev.state_version != before.state_version:
          assert not decision.changed and decision.task == before, "stale: wrong version accepted"
  ```
  并把 `test_oracles_reject_kernel_mutants` 的参数表加上 `"stale"`（变异：删掉 `_dispatch` 的版本校验）。

### P5【低】"错误 SHA 的 CI 绿"覆盖不足：oracle 能抓，但随机轨迹几乎撞不到（M11 存活 5/5）

- **位置**：`tests/core/test_invariants.py:288`（`choice==3` 用 `st.sampled_from(list(EventKind))` 随机换 kind）
- **实验**：删掉 `_on_ci_green` 的 sha 校验 → 5 个种子全通过。但我手工搭一条"待验收 → CI_GREEN(sha=WRONG) → 两家通过 → 合并"，`check_ci` 立刻报 `ci: no matching external green event`。所以这是**生成器覆盖问题**，不是 oracle 漏洞：`choice==3` 要求"随机抽到的 kind 正好是 CI_GREEN"且"当前正好在待验收"，概率约 0.4%/步，80 个例子 × 40 步的默认规模下经常一次都撞不到。
- **建议**：把 `choice==3`（以及 P1 建议的新 choice）的 kind 改成"**与当前状态相关**的 kind 集合"（例如在待验收时优先抽 `CI_GREEN`/`CI_RED`/`CODE_SUBMITTED`），而不是全 23 种均匀抽；或者按 P4 的思路直接给"CI 事件的 sha 必须等于当前提交编号"加显式不变量。

### P6【低】变异测试的判据 `match=` 太松：`"d"` 是单个字母

- **位置**：`tests/core/test_invariants.py:607`（`pytest.raises(AssertionError, match=invariant)`），`invariant="d"` 来自 `:470` 附近的参数表
- **说明**：`re.search("d", ...)` 会匹配 `"pure: different outputs"`、`"terminal: changed protected field ..."` 等任何含字母 d 的消息。目前每个 witness 只调用一个 oracle，所以实际风险小；但一旦 witness 里再加一条断言，"D 级变异"就可能被无关断言"顶包"通过。
- **建议**：把 oracle 的选择性匹配改成消息前缀，例如 `match=f"{invariant}: "`（现有消息都形如 `"ci: ..."`、`"d: ..."`、`"version: ..."`），或让每个 oracle 抛自己的异常类。

### P7【低】随机轨迹从不进入 待你介入 / 异常 / 你处理中 / 已取消 / 失败

- **实测**（种子 1，80 个例子，1378 次 `decide` 的输出状态分布）：`MERGED 692、WORKING 192、AWAITING_MERGE 136、AWAITING_ACCEPTANCE 118、AWAITING_AI_REVIEW 74、PENDING 70、AWAITING_PLAN_APPROVAL 64、AWAITING_YOUR_REVIEW 32`；`NEEDS_INTERVENTION / ERROR / YOU_WORKING / CANCELLED / FAILED` **各 0 次**；产生 `MERGE` 动作 102 次。
- **说明**：终态契约由 `test_every_event_obeys_terminal_cleanup_contract`（三种终态 × 全事件字母表 × 两遍、逐字段白名单）和 `test_terminal_cleanup_*` 覆盖得很好；但 `NEEDS_INTERVENTION`（第 14b/15/16/20/21 条）和 `ERROR`（第 8/26 条）在**性质轨迹**里一次都没出现，第 1/3/5 条不变量在这两个状态上只靠手写例子。
- **建议**：生成器加一路"强制走岔路"的 prefix，例如在 `advance()` 里按比例注入 `INCIDENT`（→ ERROR）、`REFUSED_TO_FIX`/`QUOTA_EXHAUSTED`（→ NEEDS_INTERVENTION）；或在 `test_generated_event_sequences` 之后再写一个"从待你介入/异常出发"的轨迹生成器（同样的 oracle 复用）。

### P8【信息】oracle 与内核规则是两份独立实现，需要一起改

- **位置**：`tests/core/test_invariants.py:118`（`check_terminal` 内部重算了 r5 的"来源登记 + 只收尾一次"规则）、`:180`（`check_d` 重算 D 的关卡）
- **说明**：这是"独立 oracle"的固有代价，写得对；但内核规则一变（例如将来允许核对更多清理动作、或 D 级改成"AI 通过即可合并"），oracle 必须同步，否则会假红/假绿。建议在 oracle 的 docstring 里写明它对应 `docs/design/task-lifecycle.md` 的哪几条、以及 `src/tandem/core/transition.py` 的哪个函数，方便下次改规则时一起改。

## 二、我复核通过、认为写得很好的部分

1. **变异验证的结构**：每个 oracle 的变异测试都**先跑一遍无误的 witness**（`test_oracles_reject_kernel_mutants` 第 605 行前），避免"别处已有失败被当成抓到变异"——这个细节做得很对，我在自己的实验里也用了同样的办法。
2. **终态契约最扎实**：`test_every_event_obeys_terminal_cleanup_contract` 覆盖 3 种终态 × 全部 24 种事件 × 两遍；`check_terminal` 用 `fields(TaskRecord)` 白名单（连未来新增字段都保护），并精确比对 `decision.action_updates`、`cleanup_checked`、版本号、注入时钟；`test_terminal_cleanup_cannot_change_protected_fields` 对**每个受保护字段**逐一构造变异；`test_terminal_cleanup_bookkeeping_mutants_are_caught` 覆盖 append/drop/identity/untargeted/wrong-status/dispatch/version/flag，`test_terminal_cleanup_rejects_unverifiable_or_finished_targets` 覆盖未登记/同结果/相反结果/混合批次，`test_terminal_cleanup_action_update_mutants_are_caught` 覆盖 missing/target/status/duplicate。我把 r5 的规则逐条对了一遍，oracle 与内核一致。
3. **纯函数不变量**：用 `deepcopy` 前后比对**输入不被改写**，并用"隐藏计数器改变动作编号"的变异证明能抓到不确定性。
4. **D 级方案绑定**：`check_plan_approval` + `test_plan_sha_guard_mutant_is_caught` + `test_approval_generator_uses_plan_sha_instead_of_latest_code_sha` 都是**故意让方案 SHA 和代码 SHA 不同**来验证，而不是碰巧相等；`current_plan_sha` 从 `plan_history` 读输入证据而不是信任 `approved_sha` 输出，这个细节很好。
5. **shell 侧**：原子性用"完整前缀"比对（允许父事件或 followup 事件整体提交，不接受半笔）；`check_once` 同时校验"执行账本"与"动作表"，并且抓"有完成状态却没有执行记录"；每个 seam × `before/after` 强制断言 `fault.fired`（证明真的打到了断点）；崩溃用 `BaseException` 而不是普通异常（不会被 `except Exception` 吞掉）；重放明确写了**依赖 fixture 提供的元数据**、不是"从日志独立恢复"，也没有夸大 exactly-once——这几处诚实且准确。
6. **CI 成本**：core 性质文件 3.2 s、全套 34.9 s；深度模式 core 6.4 s、shell 97.7 s，开关确实是"CI 80×40 / 深度 1000×200"，并且 `deadline=None` 避免慢机器假红。`.hypothesis`/`.pytest_cache` 都自带 `.gitignore`，不会脏工作树。
7. **A/B 级**：`test_a_b_review_counts_follow_policy` 用"按等级的策略"驱动，A 级 0 家、B 级 1 家，与实际 `risk.yml`/`Policy.rule_for` 语义一致（不是写死 2）。

## 三、需要写手回答/决定的点

1. P1–P4 是否在本次补上？我建议至少补 P4（成本最低、正好用上生成器已经在造的过期事件）和 P1/P3（各 6 行 oracle），P2 需要生成器记"路径"，稍大但价值最高（它对应任务书第 6 条的原话）。
2. P7 是否接受"NEEDS_INTERVENTION/ERROR 只由手写例子覆盖"？如果接受，建议在任务书/README 里写明，避免以后有人以为性质测试覆盖了第 14b/15/16/20/21/26 条。
3. P5 的生成器抽样策略要不要按状态分层？分层之后同样 80 个例子能打到的路径会明显变多（我实测当前 80×40 的规模下，错误 sha 的 CI 绿 + 完整审核轮几乎撞不到）。

## 结论

**修改后可以。** 交付物齐全、设计正确、变异验证的方法学是对的，CI 成本也控制住了；缺的是不变量集合比内核规则窄了四类（席位、待你审核路径、批准绑定 SHA、过期事件忽略），以及"错误 SHA 的 CI 绿"这类组合在默认规模下太稀有。补上 P1–P4 的 oracle（都很小）之后，这套性质测试才真正能替代"每轮审核再找一条新反例"的现状。
