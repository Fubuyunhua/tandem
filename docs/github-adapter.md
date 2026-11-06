# GitHub 外壳适配器

`GitHubClient` 定义读取和写入接口；`GhGitHub` 只通过 `gh api` 访问 GitHub，凭据使用 gh 已有登录状态。没有新增 HTTP 依赖，不读取、记录或输出 token。开发测试全部离线，FakeGitHub 代替 GitHub；进程边界测试也整体替换 subprocess，不会启动 gh。

## 命令

以下为使用示例，本次开发没有实际访问 GitHub。默认 dry-run 只关闭远端写入，仍会读取 GitHub、保存本地任务和处理事件。

```sh
tandem poll --repo owner/repo
tandem poll --repo owner/repo --bind gh-12=34
tandem approve --task-id gh-12 --sha <完整提交SHA>
tandem approve --task-id gh-12 --sha <完整提交SHA> --live
tandem cancel --task-id gh-12 --live
tandem reconcile gh-12 --repo owner/repo --pr 34
```

所有命令支持 `--db <路径>`。轮询只跑一次，不启动 Agent，也不调用分诊模型。`--bind` 可以重复，关联必须显式提供，不从 Issue 正文推断。`reconcile --pr` 可以在首次核对时补充关联；已有 PR 不允许静默替换。批准和取消会从本地来源读取仓库，也可以显式提供 `--repo`；来源和仓库不匹配时拒绝执行。

写操作只有 `--live` 才真正执行；Python 接口对应 `live=True`，缺省为 False。评论使用 `client.comment(number, body, live=True)`，Issue 和 PR 均适用。评论正文通过标准输入中的 JSON 传递，所有 gh 参数均为列表，关闭 shell。合并前核对当前 PR、预期 SHA 和 CI；请求中再次携带 SHA，并采用 squash 合并；写后读取 PR 确认结果。关闭 PR 也先读后写再确认。评论先读取目标状态。

## 事件与持久化

- 只接收打开且带精确 `agent` 标签的 Issue，排除 PR。分页读取，不使用固定条数截断。
- 任务编号固定为 `gh-<Issue 编号>`，默认等级 C；交回代码后继续通过现有真实 diff 流程重新计算等级。Issue 的标题、正文仅保存为不可信来源数据，不作为命令或权限指令。
- 外壳的 `github_sources` 表保存仓库、Issue、原始内容和显式 PR 关联；重复轮询、重启都不会重复创建任务。任务编号没有仓库前缀，因此一个数据库遇到跨仓库同编号会拒绝，多个仓库宜使用不同数据库。
- 来源先登记、任务后创建；中断发生在二者之间时，下次轮询可以补建。已有同名但无来源的任务不自动接管。
- CI 同时读取 check runs 和旧式 commit statuses。每个 status context 只看最新记录；任何失败产生 CI_RED，全部成功才产生 CI_GREEN，无结果或仍在运行则等待。事件携带完整提交 SHA 和状态版本，仅处理待验收任务，避免重复增加失败次数。
- gh 非零退出、超时、缺少程序、非法 JSON 均转为固定的脱敏错误。已有任务关联的读取失败和动作失败会记录 G01 异常事件；没有任务时 CLI 返回失败。未经确认的动作保留 UNKNOWN，不生成合并成功事件。
- 核对已合并 PR 时还要核对 head SHA；已关闭则提交 PR_CLOSED，仍打开则提交 NOT_CONFIRMED。只有 GitHub 证实完成的对应动作才改为 DONE，核对本身不重复合并或关闭。

dry-run 会持久化模拟后的状态和动作记录，与已有执行器语义一致。应使用单独的演练数据库；不能把一次模拟批准当成真实合并，也不能指望重复批准自动重放动作。

## 当前内核边界

无需新增事件字段；已有 `sha`、`check_result` 和 `error_code` 足够表达这次接入。仓库、Issue、PR 的关联保留在外壳，不修改内核。

内核只允许处理中、待验收、待 AI 审核、待合并接收异常。取消先成为终点，再执行关闭 PR，因此关闭失败时，外壳能记录 INCIDENT 和 UNKNOWN，但内核不会回到异常，当前 reconcile 也只接收异常任务。若要支持取消清理失败后的自动恢复，需要内核定义该恢复入口。

NOT_CONFIRMED 恢复到待合并时，现有内核不重新发出 MERGE 动作，本适配器也不越过内核自动重试。若要一键重试未完成的合并，需要内核明确动作重发语义。PR_CLOSED 当前返回待处理但不清除 `pr_opened`，同一任务更换 PR 的生命周期也需要后续统一定义。
