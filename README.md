# tandem

个人 AI 开发循环系统：调度多家 AI 承担大部分实现工作，同时保证使用者在过程中持续锻炼**数学建模、架构设计、批判能力**。

名字来自双人自行车：AI 出大部分力气，但人也必须一直在蹬。

这个项目用它自己的流程开发它自己。

审核候选改动必须使用受信版本的策略。Runner 不从候选工作树重载 risk.yml，
而是始终使用构造时注入的不可变 Policy。启动器必须从受信的安装或已批准版本加载策略，
不能在待审核的候选工作树中加载其 risk.yml 来给该候选改动定级。

路径规则跨平台统一按大小写不敏感匹配，并保护目录自身（包括 gitlink）。
这会在 Linux 等大小写敏感环境中多报一些 D，换取 Windows/macOS 下不会因大小写漏报。
pyproject.toml 整个文件都按 D 处理，即使只修改无害的文档元数据或工具设置也需走 D 流程；
这是避免同一配置文件中的依赖、测试与 CI 设置绕过审核的保守代价。

改动采集先把引用固定为完整 OID，再在临时 bare 仓库中读取原对象库；不继承原仓库
或用户的 diff 配置，也不运行 external diff/textconv。子模块指针始终参与采集。
事件保存两端文件模式及链接目标；符号链接不按纯文档放宽，指向保护区或仓库外则判 D。
删除文档和删除其他文件一样命中删除底线，判 D；删除后的 000000 模式不能作为纯文档放宽，
因此这里并不是从 A 放宽到 B 的行为变化。
链接链按 Git 树逐段解析，循环或超过层数限制时拒绝采集，不跟随工作区文件系统链接。

Python 断言用 AST 计数，注释和字符串不算断言；无法解析时拒绝确认。
JS/TS 去掉行注释、块注释、引号及模板字面量后近似计数 assert/expect，
仍不能证明测试语义或强度，模板插值、正则字面量、别名和动态调用等存在近似边界。
测试命名覆盖 test/spec 的 JS、TS、JSX、TSX 文件及 __tests__ 目录；
改名为非测试路径或离开原测试目录按删除测试判 D，即使文件本来没有断言。
测试收集边界保留大小写：tests/ 改成 Tests/ 或测试文件纯大小写改名同样判 D，
避免 Windows/macOS 本地看似等价的路径在 Linux CI 中不再被收集。
移进 pytest 默认忽略目录（build、dist、node_modules、venv、.*、*.egg、CVS、_darcs、
{arch} 等）也判为移出收集范围。只统计源码扩展名且符合测试命名的文件，排除 pyc 和 JSON 等 fixture。
文档放宽必须有覆盖全部路径的已知文件模式；模式未知或缺失时不放宽。

已知边界：Python 只计 assert 语句，self.assert*、pytest.raises 不计；换成这些风格可能被判 D。
计数不能证明断言会执行，也不能证明断言强度；提前 return、动态跳过或改成 assert True 等仍需审核。
无法确认证据时拒绝采集并抛出 DiffError：例如无共同祖先、部分克隆缺对象、已有 blob 不可读、
Python 解析失败（包括不支持的 BOM/UTF-16 输入或语法错误）、非 commit 引用、链接循环或超过 40 层。
这些错误不应被当作 C 或成功；闸门应以错误退出而不是放行，本轮不执行候选测试来补证据。

## 文档
- 需求：[`docs/PRD.md`](docs/PRD.md)
- 架构决策：[`docs/adr/`](docs/adr/)
- 任务状态流转：[`docs/design/task-lifecycle.md`](docs/design/task-lifecycle.md)

## 代码结构
- `src/tandem/core/`：内核，只做判断的纯函数（不读时钟、不联网、不读写文件）
- `src/tandem/shell/`：外壳，负责和外部世界打交道
- `tests/test_purity.py`：检查内核有没有接触外部世界

## 本地开发
需要 [uv](https://docs.astral.sh/uv/)。

```sh
uv sync
uv run ruff check
uv run ruff format --check
uv run pyright
uv run pytest
```
