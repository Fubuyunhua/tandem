# tandem

个人 AI 开发循环系统：调度多家 AI 承担大部分实现工作，同时保证使用者在过程中持续锻炼**数学建模、架构设计、批判能力**。

名字来自双人自行车：AI 出大部分力气，但人也必须一直在蹬。

这个项目用它自己的流程开发它自己。

## 文档
- 需求：[`docs/PRD.md`](docs/PRD.md)
- 架构决策：[`docs/adr/`](docs/adr/)
- 任务状态流转：[`docs/design/task-lifecycle.md`](docs/design/task-lifecycle.md)
- GitHub 适配器：[`docs/github-adapter.md`](docs/github-adapter.md)

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
