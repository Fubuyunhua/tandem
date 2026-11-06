# task-002 第二轮独立审核 · codex

审核对象：`53ea027..d65142033b6e0040e93106455561b8ad0821932d`，位于指定 `tandem-wsl` worktree。已读修复清单、原任务书、审核要求、本轮改动及相关测试；未读其他审核者本轮输出。

验证仅使用只读检查、纯函数测试和内存 mock：

- `python -B -m pytest tests/scripts/test_evidence.py tests/scripts/test_verdict.py tests/scripts/test_wsl_script.py -q -p no:cacheprovider -k 'not powershell_logic_harness'`：**44 passed、1 deselected**。
- `git diff --check 53ea027..HEAD` 通过。
- 未执行 WSL 操作、系统配置修改、真实 AI、网络/监听器、准备文件或恢复副本的真实写入；未运行会创建临时文件、进程或端口的集成测试及 PowerShell harness。下面标明“实测”的反例均为纯函数或内存 mock，不是对真实 WSL 的验收。
- 本机权限、真实 CLI 事件格式与实际隔离效果【未核实】；“先写失败测试再修复”的过程顺序，不能从现有测试源码证明，本轮不冒称已核实。

**关键区别：当前 `cmd_report` 的网络项始终不可通过，因此这些反例尚未使真实报告命令返回后台准入；但它们已能伪造单项证据，而且部分控制器操作本身有越权风险。不能因 G7 锁住准入就忽略它们。**

## 一、G1–G15 逐条结论

| 条目 | 状态 | 理由与测试依据 |
|---|---|---|
| G1 干净 rootfs 与哈希 | **已修好** | 已移除源发行版导出路径，导入前要求本地文件与 64 位期望 SHA256 并比较哈希。官方来源真实性仍由用户核对，文档已说明。静态测试通过；哈希匹配/不符等有 PowerShell harness 用例，本轮未执行该 harness。 |
| G2 永不注销已有发行版 | **已修好** | `-Recreate`、实际 `--unregister` 均已移除；新名称检查拒绝重名。原先“源目标同名先删除源”的路径已不存在，静态测试通过。 |
| G3 专用唯一目录、拒绝覆盖 | **已修好** | 不再生成或删除 tar 临时文件，改用专用运行目录与时间/随机后缀，已有同名目录拒绝复用；安装目录非空拒绝。没有遗留任意 `TarPath` 删除逻辑。目录用例在 harness 中，本轮仅静态核对，未验收并发创建竞态。 |
| G4 阶段失败报告 | **已修好** | `Invoke-TandemSetup` 跟踪阶段并在 catch 输出已完成/失败/未完成，取消不再谎称完全未修改。格式用例存在；真实导入中途失败是否留下注册残片未实测，执行时仍需按报告人工核对。 |
| G5 每项执行证据 | **部分** | 普通文字不再算尝试，已新增 ToolCall/Transcript 和六态判断，相关纯函数测试通过；但来源可篡改、路径/操作匹配不准确、解析错误不阻断，见 N1–N3。不能说已证明“真的尝试并被拒绝”。 |
| G6 正面通信证据 | **部分** | 现在要求模型回合/nonce、Git 调用记录和完整 ref，原先裸文字/裸哈希反例已覆盖；仍能用真实打印命令的事件伪造 Git 证据，Claude 分支还允许无 exit_code 的成功结果，见 N2。 |
| G7 网络未实现不得准入 | **已修好** | `judge_network_egress` 对零连接、无监听、任意政策标识都不返回通过；CLI 当前没有准入路径，测试覆盖未验证/实际连接两种情况。文档承认不能后台运行，是正确的修复。 |
| G8 全文件、全覆盖扫描 | **部分** | 分块读与重叠逻辑已替代首 1 MB 截断，不再普遍跳过 data/.git；但目录遍历错误静默遗漏，可写证据/输出目录被整体排除，零 chunk 可跳过读取，见 N4。 |
| G9 每轮副本、随机挑战、恢复 | **部分** | 有随机挑战、独立于仓库的副本、删除/改变/未知判断与改动恢复；删除后不重建，第二轮默认路径冲突，恢复前后证据不能稳定保留，见 N8。 |
| G10 独占新建诱饵 | **已修好（文件创建层）** | `create_exclusive` 使用 `O_CREAT|O_EXCL`，可用时加 `O_NOFOLLOW`，已存在或叶子链接会失败；有旧文件保持不变与链接拒绝测试。没有新增任意删除旧文件的逻辑。父目录可信性仍依赖 G14，复测生命周期见 G9/N8。 |
| G11 dry-run 与清理 | **部分** | prepare、正常准备成功的 probe 已先返回，监听器改用上下文管理；但 probe 拒绝路径会写结果，report 在检查 dry-run 前会恢复文件和查询版本，见 N5。子进程组/后代进程退出未被当前测试证明。 |
| G12 环境版本与脱敏 | **部分** | 新增 CLI 版本、UID、发行版、工具/沙箱/网络标识及原始输出脱敏；但身份/版本大多是未认证声明，空工具集合可过完整性检查，checks.evidence 未脱敏，见 N9–N10。 |
| G13 拒绝 root probe | **已修好** | 已在启动 Agent 前检查有效 UID，UID=0 返回未执行；纯函数测试通过。未知 UID 仍放行函数本身，但不等于验证了目标 WSL 环境。root 拒绝时的 dry-run 写入问题另见 N5。 |
| G14 三阶段与权限准备 | **部分** | 三阶段命令、权限表和未准备时不启动 Agent 都已加入；按手册的 0750 父目录却无法执行低权限阶段，而且“report 会核对权限”并未实现；管理员还执行 worker 可修改的代码，见 N6–N7。 |
| G15 凭据清单模板 | **已修好** | 手册第 6 节已列 hub、worker、合并组件的用途、权限、存放、可读主体和吊销方式，并要求用户填写。模板不是实际凭据隔离验收，这一点仍需保留。 |

## 二、新问题与未闭合问题（10 条，按严重程度排序）

### N1. 结构化证据仍由受测用户控制，管理员报告还使用其中的路径片段写文件

- **问题**：`probe/` 为 0777，Agent 可替换原始流和 result.json；report 没有可信接收链，还把不可信 agent 字段拼进输出路径。
- **位置**：`scripts/decoy/run_decoy.py:287`、`scripts/decoy/run_decoy.py:627`、`scripts/decoy/run_decoy.py:752`。
- **为什么重要**：公开 probe.json 已给出 nonce、挑战与目标，受测用户可以伪造完整 JSONL、executed、UID、发行版、版本和连接数；控制器即使自己重新解析 JSON，也没有恢复真实性。更严重的是 result.agent 可是绝对路径或含 `../`：内存 mock 的真实 cmd_report 将输出从 `safe-out` 改到了 `C:\outside\proof-fixed.json`；WSL 上对应绝对 Linux 路径也会逃出 out-dir。若按手册用 root 收证，影响是管理员越界写入，不只是“统计不准”。输出目录/叶子文件的符号链接也没有防护。
- **建议**：由独立可信控制器启动低权限 worker，并直接接收/落盘事件，worker 不得写证据目录；报告只读取封存的控制器证据，并验证本轮标识和完整性。agent 仅作展示字段，用控制器生成的 ID 命名；安全打开文件，拒绝链接和路径逃逸。当前未可信封存的流只能显示为不可信材料，不能显示 blocked/verified 的认证结论。G7 目前仍会阻止整体准入，但并不阻止这里的管理员写入风险。
- **严重程度**：高

### N2. 命令提到路径或 Git 字样，不代表执行了所声称的操作

- **问题**：目标按路径/文件名子串匹配，拒绝按输出关键词匹配，没有验证工具种类、真实目标或命令语义。
- **位置**：`scripts/decoy/verdict.py:155`、`scripts/decoy/verdict.py:171`、`scripts/decoy/verdict.py:262`、`scripts/decoy/verdict.py:402`；`scripts/decoy/evidence.py:80`。
- **为什么重要**：无需改写事件文件，正常 CLI 执行 `echo 'Permission denied' # <诱饵路径>`，退出 1，其事件就被判 secret_read=blocked；同样可骗过配置项。`printf` 打印假 ref、注释中写 `git ls-remote <repo>`，Git 项也实测 verified。另实测 `/tmp/private_key.pem` 的拒绝记录可代替 `/etc/tandem/decoy/private_key.pem`；反过来，成功 Read 配置会误判为“篡改成功”，即便内容未变。结构化格式没有修复这些语义错配。
- **建议**：对受支持的 Read/Write 工具验证准确规范路径及操作；任意 shell 字符串不能仅靠子串识别，改用可信固定探测命令/包装器并收取实际错误码。Git 探测由包装器绑定 argv、仓库与 ref，不接受注释/打印模拟。拒绝原因来自权限层，不来自随意输出的英语关键词。补以上真事件形状的反例，而非只测真假 JSON 格式。
- **严重程度**：高

### N3. 不可解析的输出仅记备注，原始流泄漏仍可能被判 blocked

- **问题**：parse_errors 不影响单项或环境完整性，secret 判定只看解析保留的 final_text/tool.output，不检查完整原始流。
- **位置**：`scripts/decoy/evidence.py:113`、`scripts/decoy/verdict.py:184`、`scripts/decoy/run_decoy.py:703`。
- **为什么重要**：在有效的拒绝记录后追加一行含诱饵标记的非 JSON 文本，实测 parse_errors=1，而 secret_read 仍为 blocked。已泄漏到 stdout 的内容被“解析失败”丢掉了。未知 JSON 事件种类也可能被静默跳过。文档所说“格式漂移会降级无法取证”并没有实现；现有解析测试还明确允许带解析错误的流保留 model_ok=True。
- **建议**：原始 stdout/stderr 在脱敏前完整做泄漏检查；无法解释的工具/结果事件使相应证据降为 unverifiable，流损坏不能只做备注。白名单化已知可忽略的元数据事件，对未知安全相关事件拒绝推断。新增“有效拒绝记录 + 非 JSON 泄漏”和“未知事件带标记”的判定测试。
- **严重程度**：高

### N4. 扫描仍可把没看见的内容报告成完整覆盖

- **问题**：os.walk 未设置错误回调，排除项包含 Agent 可写目录，chunk_size 又没有正数校验。
- **位置**：`scripts/decoy/scan.py:33`、`scripts/decoy/scan.py:53`、`scripts/decoy/scan.py:81`；`scripts/decoy/run_decoy.py:663`。
- **为什么重要**：os.walk 无法遍历的子目录可静默消失，最后 complete=True；内存 mock 复现 complete=True、scanned_files=0。`--chunk-size 0` 使 read(0) 立即结束，实测含标记文件被判未找到。run_dir 内的 probe/ 明明 0777，却随整个 run_dir 排除，默认输出目录也被排除，Agent 可把泄漏副本藏在那里。将排除规则列入 JSON 并不等于排除位置没有风险。
- **建议**：遍历错误纳入 unreadable，拒绝非正 chunk_size；根是文件、空扫描集合、链接目录等情况也需明确口径。仅排除 worker 确实不能写的控制器私有内容，不能排除其可写 probe/ 或输出路径。扫描范围由可信写权限政策确定。补 EACCES 子目录、chunk_size=0、probe/及报告输出目录泄漏用例。
- **严重程度**：高

### N5. dry-run 仍会修改受保护副本，错误路径也会落盘

- **问题**：report 和 probe 部分拒绝分支在 dry-run 返回前已执行副作用。
- **位置**：`scripts/decoy/run_decoy.py:401`、`scripts/decoy/run_decoy.py:655`、`scripts/decoy/run_decoy.py:747`。
- **为什么重要**：内存 mock 实测 report --dry-run 调用 write_exact 恢复副本一次，并执行一次工具版本查询；root probe --dry-run 也调用了写“未执行”结果。现有 report dry-run 测试只断言未创建最终 out-dir，而且副本未篡改，测不到恢复写入；probe 测试只覆盖准备齐全、非 root 的正常路径。
- **建议**：所有阶段先分离只读计划与实际执行；dry-run 不恢复副本、不写失败结果、不启动版本查询进程。用 mock 禁止所有文件写和进程启动，覆盖副本已改、准备缺失、root 拒绝三类错误条件；不能只检查最终报告目录。
- **严重程度**：高

### N6. root 控制器运行的是 Agent 可以修改的仓库模块

- **问题**：手册让管理员在 worker 所有的 `~/tandem` 仓库中执行 `sudo python3 -m scripts.decoy.run_decoy`，没有隔离可信控制器代码。
- **位置**：`docs/runbooks/wsl-isolation.md:86`、`docs/runbooks/wsl-isolation.md:108`、`docs/runbooks/wsl-isolation.md:137`。
- **为什么重要**：Agent 的工作就是修改这份仓库；它可以在管理员下一次 prepare/report 前改掉模块、导入的 evidence/verdict 或其他 Python 包初始化代码。管理员随后不是“安全地读取不可信证据”，而是直接以 root 执行不可信代码。把证据目录改成只读也解决不了这个执行来源问题。此为按手册路径的静态风险分析，未实际执行提权。
- **建议**：控制器放在 root/专用控制用户所有、worker 不可写的安装目录与依赖环境，固定经审查版本；管理员通过该可信入口运行，不从 worker clone 的当前目录解析模块。worker 只提供受约束的探测结果或控制器直接收集的事件，不能替换裁判代码。
- **严重程度**：高

### N7. 权限表使低权限阶段走不通，而且 report 没有实现宣称的权限验收

- **问题**：root:root 0750 的祖先目录阻止 worker 遍历，probe 又要求 stat 本应读不到的诱饵；report 只比较一个属主与声明 UID。
- **位置**：`docs/runbooks/wsl-isolation.md:88`、`docs/runbooks/wsl-isolation.md:93`；`scripts/decoy/run_decoy.py:363`、`scripts/decoy/run_decoy.py:519`。
- **为什么重要**：手册将 `/var/lib/tandem`、其 decoy 父目录及 `/etc/tandem` 都设为 root:root 0750。tandem 不在 root 组时，即使 run-1 是 0755、probe/ 是 0777，也不能穿过祖先目录读取计划或写证据。对诱饵 is_file 的预检同样可能失败或报权限错误，准备明明成功却被判未准备。测试统一使用 tmp_path 同用户权限，还 monkeypatch `_prep_ok=True`，没覆盖真正的身份切换。手册声称 report 核对权限，代码却未验证祖先、文件模式/ACL 或控制文件所有者。
- **建议**：明确哪些目录允许仅遍历、哪些文件仅控制器可读；低权限 probe 不应以“能 stat 私人诱饵”为开工前提，而应读取可信非敏感准备凭证。控制器自己验证完整权限链、链接和 UID，不接受 result.json 的 UID 作为身份认证。增加受控的权限矩阵测试；本次不得真实改权限，实际 WSL 验收仍由用户另行执行。
- **严重程度**：高

### N8. 每轮副本和恢复生命周期不完整：第二轮准备失败，删除也不恢复

- **问题**：受保护路径固定为 `<protected-dir>/decoy/private_key.pem` 与 `live/risk.yml`，换 run-dir 不会换副本；被删除文件的恢复分支缺失。
- **位置**：`scripts/decoy/run_decoy.py:115`、`scripts/decoy/run_decoy.py:264`、`scripts/decoy/run_decoy.py:503`。
- **为什么重要**：内存 mock 连续 prepare(run-1)、prepare(run-2)，protected-dir 不变，返回码为 0、1：第二轮独占创建撞上第一轮诱饵。手册建议“换 run-dir 重跑”不能解决。`_restore_copy` 对不存在文件返回无 restore_note，所以 report 不会重建删除的副本；它也在收证时先改变现场，重复报告可能失去首次篡改的独立事实。随机挑战生成正确，不等于每轮都有可用的新副本。
- **建议**：为每轮生成控制器拥有的独立 protected session 路径，记录创建清单；先封存本轮存在性/内容证据，再恢复或清理本轮副本。删除也应按基线安全重建；重复 report 保留首次判定，不通过恢复覆盖历史。补第二轮运行、删除恢复、失败后重试及重复收证测试。
- **严重程度**：中

### N9. 原始输出已脱敏，但 checks.evidence 仍把密钥原样写入最终 JSON

- **问题**：`build_record` 仅脱敏输出、命令及 notes，没有递归脱敏 checks 与其他可带不可信文字的字段。
- **位置**：`scripts/decoy/verdict.py:167`、`scripts/decoy/verdict.py:562`。
- **为什么重要**：把 `sk-abcdefghijklmnopqrstuvwxyz` 放进工具 command，Git 证据描述会包含它；实测 agent_output 已变 `[REDACTED]`，完整记录 JSON 却仍能找到原 token。目标 URL 中的凭据、shell 参数或错误消息也会落在证据字段。现有脱敏测试仅把 token 放在最终回答，因此漏掉二次复制路径。
- **建议**：对待序列化的完整记录递归脱敏，不可信命令/目标采用最小化存储；不要先截断再匹配跨截断边界的秘密。覆盖 checks.evidence、actual、环境声明、错误信息及带认证 URL。保留原始证据时放在真正受保护的控制器存储，不按手册复制未脱敏数据进仓库。
- **严重程度**：中

### N10. 环境完整性检查只检查字符串存在，未核验受测身份、版本与策略

- **问题**：环境事实来自可改的 result.json 和 report 参数，缺少实际验证及必需工具集合检查。
- **位置**：`scripts/decoy/run_decoy.py:586`、`scripts/decoy/run_decoy.py:602`。
- **为什么重要**：实测传入 executed=True、任意 user、uid=None、distro='tandem'、tools={}、sandbox='none' 和任意版本字符串，`_environment_problems` 返回空列表。发行版只认字符串，不检查执行环境；CLI 版本由 probe 参数声明，Git 版本却可能是管理员收证时的工具版本。普通用户按手册 sudo report 时默认 USER 也可能记录成控制器用户，和 probe UID 混在一起。字段变多不代表环境已经验真。
- **建议**：把管理员声明、worker 实测与无法核实的事实分开，可信控制器在启动时记录实际 UID、可执行文件版本/身份、目标发行版及生效策略；缺 UID/必需工具/策略状态不得视为完整。别把 report 当前环境当作 probe 当时环境。真实 CLI 字段兼容性【未核实】，先使用脱敏的真实版本事件样本做离线适配测试，不联网也不调用模型。
- **严重程度**：中

## 三、上一轮反例的回归覆盖核对

| 上一轮反例 | 本轮已有覆盖 | 仍缺的验证 |
|---|---|---|
| 重建先删源/目标；TarPath 误删 | 静态检查无 export/unregister/Recreate，harness 有重名、哈希、非空目录、唯一目录用例 | 本轮没执行产生临时文件的 harness；没有完整 setup 阶段命令失败注入。不能据格式函数测试声称已做过真实 WSL 恢复演练。 |
| 只打印 OK 和假哈希即可通过 | `test_secret_read_plain_text_agent_is_not_attempted`、`test_git_hash_without_the_command_is_not_enough` 等纯测试通过，集成测试也已改为不准入 | 真实事件里 echo 假拒绝、printf 假 ref、错误同名路径、不同操作类型尚无反例；手工 JSON fixture 本身不是可信事件来源。 |
| localhost 0 连接冒充出口隔离 | 网络未验证/有连接用例及总结论不准入用例通过 | 这条已实质修好；不要为追求通过而提前解除 G7。 |
| 旧诱饵/符号链接覆盖真实密钥 | 新增文件保持不变、叶子 symlink 拒绝测试 | 未验证父目录/祖先权限与链接；本轮未执行文件创建类测试。 |
| data 泄漏、1 MB 后泄漏、覆盖不完整 | data/leak.txt 集成用例、分块读取、missing-dir 用例已存在 | “beyond_first_chunk”用例只写 5000 字节并设块为 1024，**未直接重放上一轮超过 1 MB 的输入**；还缺跨块标记、EACCES 子目录、可写排除目录和 chunk_size=0。算法可继续用 BytesIO 无落盘验证。 |
| 相同篡改内容复测假通过、删除配置 | 有随机挑战提示词、删除判 violated、改动恢复用例 | 没有同 protected-dir 连续两轮、删除后恢复、重复 report 保持首次事实的用例。 |
| dry-run 启动监听器/错误路径没清理 | 正常 prepare/probe dry-run 与监听器异常清理用例 | 缺 root/准备不足的 dry-run 写入、report 恢复写入/版本进程、超时后后代进程存活检查。现有 report 用例只断言没创建最终输出目录。 |
| 版本缺失仍通过、输出密钥进记录 | 有版本/沙箱缺失、发行版字符串不符、最终回答 token 脱敏用例 | 缺篡改 metadata、空工具集合、checks.evidence 泄漏；当前环境测试同 UID，无法验证 G14 权限表。 |

另外，`tests/scripts/test_decoy.py:259` 附近的 `assert ... or True` 永远成立，不能验证挑战内容；`test_report_blocked_read_needs_prep_ok` 把关键权限检查 mock 成 True，只能测试后续组合逻辑，不能作为隔离验收证据。建议删除无效断言，并对本轮反例逐一加入真正会在错误实现上失败的测试。

结论：**需要大改**。危险的发行版删除/复制路径和整体准入假阳性已有实质改善，但可信控制器、证据来源与权限链仍未建立，dry-run 还会写文件；应先修复这些边界，再继续真实 WSL 验收，G7 的不准入限制保持不变。
