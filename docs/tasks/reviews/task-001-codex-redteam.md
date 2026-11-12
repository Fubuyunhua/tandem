# task-001 红队审查 · Codex

对象：feat/m1-runnable @ 2988de3。只读，实验均在内存和临时目录中进行。

1. 高：绿灯之后的红灯被忽略。
   位置：_on_ci_red (C:/Users/weicai/Desktop/projects/code_auto/src/tandem/core/transition.py:734)。
   复现：同一 SHA 依次收到 CI_GREEN → CI_RED → YOUR_APPROVAL。
   实际：红灯事件 changed=False，ci_green 仍为 True，批准后发出 MERGE。
   期望：同提交的有效红灯撤销绿灯证据，阻止后续合并。

2. 高：可变引用可以冒充不可变 SHA。
   位置：Runner.code_event (C:/Users/weicai/Desktop/projects/code_auto/src/tandem/shell/runner.py:113)。
   复现：回执 sha="candidate"，该分支起初只有普通代码；采集并收到同字符串的绿灯后，把分支移动到包含 core 修改的提交，再批准
   "candidate"。
   实际：任务仍为 C，发出 MERGE；重新采集当前引用则应判 D。
   期望：入口解析并保存完整、不可变提交 OID；CI 和批准均绑定该 OID。此攻击链需要 CI 入口也沿用未解析的字符串。

3. 高：新增 pytest 配置可以替换 CI 的测试范围，却只判 C。
   位置：risk.yml (C:/Users/weicai/Desktop/projects/code_auto/risk.yml:29)。
   复现：新增 pytest.ini，内容为 [pytest]、testpaths=smoke，再新增一个通过的 smoke 测试。
   实际：原本 1 failed, 1 passed 的临时项目变成 1 passed、退出码 0；改动判 C，原测试没有被删除。
   期望：影响测试收集的配置属于闸门配置，至少按 D 审核。

4. 高：仓库根目录的迁移漏判。
   位置：_pattern_hits (C:/Users/weicai/Desktop/projects/code_auto/src/tandem/core/level.py:44)。
   复现：修改 migrations/001.sql，例如改为 DROP TABLE users。
   实际：判 C；**/migrations/** 没匹配根目录形式。
   期望：根目录和嵌套目录的迁移都判 D。

5. 高，但以使用子模块为前提：子模块存在两层漏检。
   位置：GitDiffSource.collect (C:/Users/weicai/Desktop/projects/code_auto/src/tandem/shell/diff_source.py:137)。
   复现 A：更新路径为 src/tandem/core 的 gitlink。
   实际：只得到该目录路径，判 C；core/** 不匹配目录自身。
   复现 B：再配置 diff.ignoreSubmodules=all，只更新该 gitlink。
   实际：采集到空改动，默认判 A。
   期望：保护目录自身也命中 D；采集显式禁止忽略子模块。当前仓库没有 gitlink，此项属于接入子模块后的漏洞。

6. 中：注释可以冒充被删掉的断言。
   位置：ASSERTION_PATTERN (C:/Users/weicai/Desktop/projects/code_auto/src/tandem/shell/diff_source.py:21)。
   复现：把测试里的 assert False 改为 pass # assert False。
   实际：统计仍为 1 → 1，没有 assertion_drops，判 C。
   期望：可执行断言减少应判 D；注释和字符串不能抵消减少。

7. 中：常见 JS/TS 测试文件名不参与断言检查。
   位置：TEST_FILE_PATTERN (C:/Users/weicai/Desktop/projects/code_auto/src/tandem/shell/diff_source.py:24)。
   复现：删除 src/app.test.ts 中唯一的 expect(...)。
   实际：前后断言数均为 None，判 C。
   期望：支持的测试命名应覆盖 .test.ts 等形式，减少断言时判 D。

8. 高：把失败测试移出收集范围，可以获得假绿灯。
   位置：改名断言统计 (C:/Users/weicai/Desktop/projects/code_auto/src/tandem/shell/diff_source.py:220)。
   复现：将含失败断言的 tests/test_a.py 原样改名为 docs/test_a.md，保留另一个通过的测试。
   实际：Git 检测为改名，断言数 1 → 1，判 C；实际 pytest 从失败变为通过。
   期望：移出测试收集范围应视为测试移除，升级 D 或明确要求授权。

9. 高，但取决于运行部署：候选策略可能给自身降级。
   位置：load_config (C:/Users/weicai/Desktop/projects/code_auto/src/tandem/shell/config.py:210)。
   复现：候选 risk.yml 清空底线、开启多 Agent，并关闭 C 级 AI 审核；让新任务使用该候选配置。
   实际：同一份 risk.yml + core 改动，在原策略下为 D，在候选策略下为 C，绿灯后直接发出 MERGE。
   期望：审核候选改动时使用受信版本的生效策略。若服务从候选工作树重载配置，这条攻击链成立；现有 Runner 的已加载策略不会自行改变。

10. 中：符号链接仍可被当作纯文档降到 B。
   位置：_is_document (C:/Users/weicai/Desktop/projects/code_auto/src/tandem/core/level.py:109)。
   复现：把 docs/a.md 从普通文件换成指向 ../src/tandem/core/level.py 的符号链接。
   实际：采集丢失文件模式；给出 B 建议后判 B。
   期望：符号链接不能仅凭扩展名认作纯文档，至少保留 C。该实验没有证明能通过链接直接修改受保护目标。

另外验证了这些边界：

• 已知的跨文件断言抵消问题，在当前版本已判 D。

• Windows 反斜杠路径、删除受保护文件、改名进入或离开受保护目录，都判 D。

• 二进制内容及 .gitattributes 的 -diff 没能隐藏受保护路径，仍判 D。

• 大小写匹配确有缺口：src/TANDEM/CORE/level.py、RISK.YML 判 C；但普通 Git diff 保留索引中的原拼写，本轮未确认从当前工作树可达的大
  小写绕过链，不能仅凭该输入宣称已绕过保护。

两个工作区均干净；未联网、未推送。

