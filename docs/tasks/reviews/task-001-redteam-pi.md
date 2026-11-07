# PR #8（红队修复）审核 · pi（DeepSeek）

- 审核对象：`feat/redteam-fixes` 的 `4472229..48961d6`（4 个修复提交：`27eebd8` 路径与 CI 配置、`cd8338f` diff 隔离与模式、`7bb5800` 可执行断言与收集范围、`48961d6` 不可读证据与 JS 行终止符），并参照 `docs/tasks/reviews/task-001-codex-redteam.md` 的 10 条与 `docs/tasks/reviews/task-001-redteam-claude.md`。
- 依据：ADR-0001（底线条目 / 基础级别 / 等级 → 流程）、`risk.yml`、`src/tandem/core/level.py`、`src/tandem/shell/diff_source.py`、`src/tandem/shell/assertions.py`。
- 方法：**只读**。没有改动 worktree 里任何文件、没有提交；全部用 `git show` / `git diff` 读代码，并把 `48961d6` 用 `git archive` 导出到临时目录，在那里跑测试和做攻击实验（临时目录 + 临时 Git 仓库，未触动任何分支）。基线：导出后 `pytest` **356 passed, 1 skipped**。
- 审核期间该 worktree 又前进了一提交（Codex 正在并行修 R1）：`1579fa1 fix: treat case-only test moves as collection removals`。我的结论针对你给的 `489961d6...`（准确说是 `48961d6`）；`1579fa1` 恰好修掉了我下面 P2 里"**未能实测**"的那个子变体（`tests/ → Tests/` 这类纯大小写改名），但**没有**覆盖 P2 的主场景（移到 `tests/build/`、`tests/.hidden/`、`tests/node_modules/` 这类 pytest 默认忽略的子目录），所以 P2 仍然成立。
- 结论：**修改后可以**。这 4 个提交确实把 Codex 10 条里的 #3/#4/#5/#6/#7/#8/#10 和 Claude 的 R2 修掉了，diff 隔离的设计我做了敌意配置的实测，成立；但**"制造假绿灯"这一类还有两条活路**（P1、P2），都能让 `pytest` 从红变绿而闸门仍判 C，建议至少把 P2 补上、P1 写进已知边界。

## 一、四个重点的结论

| 重点 | 结论 | 证据 |
|---|---|---|
| 断言计数（AST / JS 近似）能否被绕过 | **能，有两种** | ① **Python** 侧换成 `ast.Assert` 计数后，注释/字符串冒充（#6）、`.test.ts` 命名（#7）、移出测试路径（#8）都修好了，无法用"注释冒充断言"骗过去；但**"让断言不再执行"完全躲得开**：`pytest.skip`、`@pytest.mark.skip`、`if False:` 都不改变 `ast.Assert` 的个数，实测 `pytest` 从 `1 failed` 变成 `1 skipped / 1 passed`（exit 0），闸门判 **C**（P1）；② **JS** 侧是词法近似，实测用**合法正则** `/expect()/` 或一个叫 `assert` 的变量就能保住计数（`1 → 1`、判 C），把真正的 `expect(...)` 删掉也不响（P3）。README 已经声明"模板插值、正则字面量、别名和动态调用存在近似边界"，但这是"能用来绕过门槛"，不只是精度问题 |
| diff 隔离（临时 bare 仓库借对象库）有没有漏洞 | **我试过的都没有** | 采集时先在真仓库把引用解析成完整 OID，然后 `git init --bare --template= --object-format=…`，`GIT_CONFIG_NOSYSTEM=1`、`GIT_CONFIG_GLOBAL=/dev/null`、剥掉所有 `GIT_*` 变量、`GIT_OBJECT_DIRECTORY` 指向原对象库；`git diff --raw -z -M --ignore-submodules=none --no-ext-diff --no-textconv`。我在源仓库注入 `diff.external=false`、`diff.renames=false`、`diff.renameLimit=not-an-integer`、`diff.ignoreSubmodules=all`、`core.attributesFile=<恶意属性文件>` 以及一个 `*.py diff=evil` 的 `.gitattributes`，采集仍然把改名识别成 `('src/a.py','src/b.py')`，等级不受影响。剩下的都是 fail-closed（部分克隆/对象缺失/无共同祖先 → `DiffError` → 闸门 exit 2），见 P8 |
| 符号链接与文件模式判定 | **成立** | 模式来自 `--raw` 的两端（`parse_raw_diff_z`），gitlink `160000` 会进 `paths` 且因为"保护目录自身"的新规则判 D；符号链接 `120000` 不再按纯文档放宽（`all_paths_relaxable` 要求 `after_mode == "100644"`），实测：`docs/a.md → ../README.md` 判 **C**（不是 B）、`→ ../src/tandem/core/level.py` 判 **D** 且原因写明、`→ ../../etc/passwd` 判 **D**（`/仓库外链接`）；链接链按 Git 树逐段解析、循环或超过 40 层直接拒绝采集；文档改成可执行（`100755`）也是 C 而不是 B |
| 底线路径匹配的大小写与根目录 | **都修好了** | `_pattern_hits` 现在对 pattern 和 path 同时 `casefold()`，并把 `**/xxx/**` 额外展开成 `xxx/**`，还加了 `glob.endswith("/**") and candidate == glob[:-3]` 保护目录自身。实测 `MIGRATIONS/001.sql`、`Core/level.py`、`.GITHUB/workflows/…`、`keys/a.PEM`、`sub/dir/pytest.ini`、`tests/CONFTEST.py` 全部判 **D**；根目录 `migrations/001.sql` 与目录自身 `src/tandem/core`、`.github` 也判 D。代价是 Linux 上也会多报 D（README 已说明） |

## 二、问题清单（按严重程度）

### P1【中高】测试被"挂起"就绕过了断言底线：`pytest.skip` / `mark.skip` / `if False:` 都判 C

- **位置**：`src/tandem/shell/assertions.py:41`（`count_assertions` 只数 `ast.Assert` 个数），`src/tandem/shell/diff_source.py:_assertion_changes`（只看数量前后）
- **复现**（我在临时仓库里实测，基线 `risk.yml`，两次提交之间只改测试文件）：

  | 改动 | pytest | 闸门 |
  |---|---|---|
  | 原：`def test_a():\n    assert 1 == 2` | `1 failed` | — |
  | head：函数里加 `pytest.skip('later')`，断言原样保留 | `1 skipped`（exit 0） | **C**（1→1，无原因） |
  | head：加 `@pytest.mark.skip(reason='later')` | `1 skipped`（exit 0） | **C** |
  | head：把断言包进 `if False:` | `1 passed`（exit 0） | **C** |
  | 对照：把断言删干净 | `1 passed` | **D**（1→0）✓ |

- **为什么重要**：这是红队 #8"假绿灯"的同一类问题，成本比改名还低（一行代码），而闸门完全看不出来。计数只能证明"assert 这个关键字还在"，不能证明"它还会执行"。
- **建议**（按代价从小到大）：
  1. 静态可查的近似：测试文件里**新增** `skip`/`skipif`/`xfail`/`pytest.importorskip`、或把断言包进 `if False:`/常量假分支，至少给一条"需要人工"的理由（可以把 `ast` 里 `If` 的条件是常量假的断言、以及 `Attribute` 为 `skip/xfail` 的调用列出来）；
  2. 或者在报告里固定输出"新增跳过标记：<文件> <行>"，由你判断（不升级等级，但不再静默）；
  3. 真正可靠的办法是动态证据（`pytest --collect-only` + 实际执行数对比），但那要执行候选代码，属于 M2 沙箱议题，这一轮**至少写进 README 的已知边界**（现在只写了"不能证明测试语义或强度"，没有说明它能让红灯变绿）。

### P2【中】失败测试移进 `tests/build/`、`tests/.hidden/`、`tests/node_modules/` 仍判 C（本 PR 自己的修复有缺口）

- **位置**：`src/tandem/shell/assertions.py:31`（`leaves_test_collection` 只判断"是否离开了原来的测试根目录前缀"）
- **复现**（真实临时 Git 仓库，`pyproject.toml` 里 `testpaths=["tests"]`，仓库里还有一个通过的测试）：

  | 改动 | pytest | 闸门 |
  |---|---|---|
  | `git mv tests/test_a.py tests/build/test_a.py` | `1 failed, 1 passed` → `1 passed`（exit 0） | **C**（`renames` 有记录，`removed_test_paths=()`、无原因） |
  | `tests/.hidden/test_a.py` | 同上 | **C** |
  | `tests/node_modules/test_a.py` | 同上 | **C** |
  | 对照：`tests/test_a.py → docs/a.md` | — | **D** ✓（#8 修的正是这一种） |

- **为什么重要**：pytest 默认 `norecursedirs = *.egg .* _darcs build CVS dist node_modules venv {arch}`，所以"还留在 `tests/` 前缀下"并不等于"还会被收集"。改名的内容一字不改 → 断言数不变 → 没有 `assertion_drops`，`leaves_test_collection` 又认为"还在原测试目录里"，于是整条链路都判 C，而 CI 真的变绿了。
- **建议**：
  1. 把"移动后的路径落在 pytest 默认忽略目录名下（`build`、`dist`、`node_modules`、`venv`、`.*`、`*.egg`、`CVS`、`_darcs`、`{arch}`）"也当作移出收集范围（`removed_test_paths`），判 D；
  2. 更准一点：从 **base** 的 `pyproject.toml`/`pytest.ini` 读 `testpaths`（这些文件现在是底线条目，属于可信输入），把"新路径不再落在收集根之下"当作移出；顺带能覆盖我**没能实测**的一种变体：`testpaths=["tests"]` 时把 `tests/test_a.py` 改名成 `Tests/test_a.py`，Linux 上大小写敏感 → 不再收集，而 `leaves_test_collection` 因为 `casefold()` 认为"还是同一个前缀"；
  3. 补三条回归（`build`、`.hidden`、大小写根目录）。

### P3【中】JS/TS 的计数可以用合法正则字面量或同名变量补位

- **位置**：`src/tandem/shell/assertions.py:9-13`（`JS_NON_CODE` 只剥注释、三种引号；不认正则字面量），`JS_ASSERTION`（`assert\b` / `expect\s*\(`）
- **复现**（真实临时 Git 仓库）：

  | 改动 | 计数 | 闸门 |
  |---|---|---|
  | base `tests/a.js`：`expect(false).toBe(true);` | 1 | — |
  | head：`const pattern = /expect()/;`（**合法** JS，分组为空，实际什么都不测） | 1 | **C** |
  | head：`const assert = 0;`（来自 `assert(...)` 的 base） | 1 | **C** |

- **为什么重要**：README 已声明"正则字面量…存在近似边界"，但这里它是**可用的绕过**：删除真断言、留下一个正则/变量名，计数不变，红线消失。
- **建议**：在词法层补两条即可覆盖大多数情况：① 先剥 `/.../flags` 形态的正则字面量（注意不能把 `/` 除号误判，可按前一个非空白字符判断）；② 只把 `assert` 视为断言当它出现在"调用"位置（`assert(` / `.assert.` / `assert.` 等），纯变量声明不计。做不到的话，至少按 P1 的建议把"计数不变但语义改变"列为已知边界。

### P4【中低 · 合并 task-003 时必须同步】闸门的逐文件解释不会带上这些新原因

- **位置**：`feat/risk-gate` 的 `scripts/gate/risk_level.py:explain_file`（构造子集 `ChangeSet` 时只传 `paths/deleted_paths/renames/assertion_drops`）
- **说明**：本 PR 把两类新原因放进了 `bottom_line_reasons`：符号链接指向受保护/仓库外、以及 `removed_test_paths`。闸门为每个文件重建 `ChangeSet` 时没有传 `file_changes`、`removed_test_paths`、`secret_scan_hit`，所以合并之后会出现"汇总判 D、逐文件解释里没有任何一条对应原因"。我上一轮审 task-003 时已经提过 `secret_scan_hit` 的同类问题（P3），这次多两类。
- **建议**：`explain_file` 里按路径过滤 `file_changes`（`entry.path` 或 `entry.previous_path` 命中该条目）和 `removed_test_paths`（旧路径命中），一起传给 `bottom_line_reasons`；补一条"每个文件的 `rules` 必须能在汇总原因里找到出处"的一致性断言。

### P5【低】`file_changes` 为空时，模式检查被静默跳过（可放宽到 B）

- **位置**：`src/tandem/core/level.py:all_paths_relaxable`（`any(... for entry in changes.file_changes)`，空元组恒为假）
- **复现**：`compute_level(ChangeSet(paths=("docs/a.md",)), policy, Level.B)` → **B**；同样的路径加上 `file_changes=(FileChange("docs/a.md","100644","120000"),)` → **C**。
- **说明**：真实采集器一定会填 `file_changes`，所以目前不可达；但这意味着"模式未知 ⇒ 视为安全"。更稳的写法：`if not changes.file_changes: return False`（未知就不放宽），或要求 `file_changes` 覆盖 `all_paths` 的每一个路径。

### P6【低】`is_test_path` 把 `tests/` 下任何文件都当测试文件

- **位置**：`src/tandem/shell/assertions.py:4-8`（`(^|/)(tests?/|…)` 只要求路径里出现 `tests/`）
- **实测**：我在实验里跑 pytest 会生成 `tests/__pycache__/*.pyc`，这些产物被 `git add` 后按"测试文件"处理，非 `.py` 走 JS 正则，于是二进制里偶然出现的 `assert` 字节被计入合计（我第一轮实验的 `before/after` 因此从 `1/0` 变成 `1/1`）。本仓库 `.gitignore` 有 `__pycache__/`，正常不会提交；但 `tests/` 下的 `*.json`、`*.txt` fixture 同样会被当作测试文件计数。
- **建议**：计数只认源码扩展名（`.py/.pyi/.js/.jsx/.ts/.tsx/.cjs/.mjs/.mts/.cts`）且文件名符合测试命名（`test_*`/`*_test`/`*.test.*`/`*.spec.*` 或 `__tests__/` 下），而不是"任何落在 `tests/` 下的文件"。

### P7【低】把 `assert` 换成 `self.assertEqual` 会被算成"断言减少"

- **实测**：`assert x == 3` → `self.assertEqual(x, 3)` → `1 → 0` → **D**。方向是 fail-closed（安全），但一次正常的 unittest 风格重构会被判 D。
- **建议**：README 里补一句"只把 `assert` 语句计为断言；`self.assert*`/`pytest.raises` 不计，换成它们会被判 D"；以后若要支持，可把 `self.assertXxx(` 也计入。

### P8【信息】以下情况都是 fail-closed（闸门 exit 2，不会放行）

`resolve_oid` 拒绝非完整 OID；`_git_show` 读不到已存在的对象（只把"路径确实不存在"当新增）；`ast.parse` 失败（含 BOM、UTF-16、语法错误）→ `DiffError`；符号链接循环或超过 40 层；没有共同祖先；部分克隆缺对象。这些都会让闸门报错而不是判 C，符合"宁可多报"。

### P9【信息】Claude 的 R1 不在本范围

"待验收以外收到同一 SHA 的红灯会卡死"（`_on_ci_red` 撤证据后没有出路）在这 4 个提交里还没修，Codex 正在同一 worktree 上处理，我不重复审。

## 三、我复核后认为没问题的部分

- **路径与配置底线**：`pytest.ini`/`conftest.py`（含嵌套）/`tox.ini`/`setup.cfg`/`ruff.toml`/`pyrightconfig.json`/`.coveragerc`/`.pre-commit-config.yaml`/`.gitattributes`/`.gitmodules` 都进了底线；实测 `sub/dir/pytest.ini`、`tests/CONFTEST.py` 判 D。
- **大小写与根目录**：见第一节；`**/migrations/**` 现在也匹配根目录 `migrations/`。
- **子模块**：`--ignore-submodules=none` + "保护目录自身"让 gitlink 变更和目录自身都判 D；`diff.ignoreSubmodules=all` 被隔离掉。
- **符号链接**：模式保留、目标按 Git 树解析、指向保护区或仓库外判 D、不按纯文档放宽、循环/过深拒绝采集（不跟随工作区链接）。
- **隔离实现**：临时 bare 仓库 + 借对象库 + 清空 `GIT_*` + `--no-ext-diff/--no-textconv` + 显式 `--ignore-submodules=none`，我注入的敌意配置全部无效。
- **OID 固定**：`Runner.code_event` 先用 `resolve_oid(receipt.sha)` 再采集（红队 #2 的入口在这里）；`--verify --end-of-options <ref>^{commit}` 挡住 `-` 开头的参数注入与非 commit 对象。
- **序列化**：`file_changes`/`removed_test_paths` 进了 `changes_to_dict/from_dict`，符号链接测试里有回环断言。

## 四、威胁模型仍未覆盖（这一轮不必修，但要记录）

1. **"断言还在但不再执行"**（P1）：`skip`/`xfail`/常量假分支/提前 `return`。
2. **"断言还在但变弱"**：`assert x == 3` → `assert True`（计数不变，实测 C）；同一文件里用 `assert True` 补位同理。
3. **移到 pytest 不收集的位置**（P2）：`build/.hidden/node_modules` 之类。
4. **JS 词法近似**（P3）：正则字面量、同名变量、动态调用（`eval`、字符串拼出来的 expect）。

这四条都源于"用静态计数当断言证据"这个近似本身，ADR 已接受"宁可多报"的近似，但**方向是"宁可多报"，而这些都属于"少报了"**，所以值得至少写进 README 的已知边界，或者按 P1/P2 的建议补静态近似。

## 五、结论

**修改后可以。** 这批修复的方向和实现都扎实：隔离 diff 的做法我按攻击者思路试过，敌意配置、属性驱动、external diff/textconv、子模块忽略都没能影响采集；大小写、根目录、目录自身、符号链接、文件模式这些边界都实测通过；测试写成真实临时 Git 仓库 + 子进程调用，能抓回归。
需要处理的是 P1（`pytest.skip` 一类"让断言不执行"仍判 C，建议至少输出"新增跳过标记"并写进已知边界）和 P2（移动到 pytest 默认忽略的子目录仍判 C，属于本次修复的缺口，建议按目录名或 base 的 `testpaths` 判掉）；P3 是 JS 词法近似的可用绕过，建议补两条词法规则；P4 是合并 task-003 时必须同步的闸门侧改动；P5–P7 是硬化与文档。
