"""GitHub 边界：只通过 gh 的登录状态访问，写入必须显式启用。"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Protocol, cast


class GitHubError(RuntimeError):
    """只向外暴露固定错误，不泄露命令输出中的凭据。"""


class CIState(Enum):
    GREEN = "green"
    RED = "red"
    PENDING = "pending"


@dataclass(frozen=True)
class Issue:
    number: int
    title: str = ""
    body: str = ""
    labels: tuple[str, ...] = ()
    state: str = "open"


@dataclass(frozen=True)
class PullRequest:
    number: int
    head_sha: str
    state: str = "open"
    merged: bool = False


class GitHubClient(Protocol):
    def list_issues(self) -> tuple[Issue, ...]: ...
    def get_pr(self, number: int) -> PullRequest: ...
    def get_ci(self, sha: str) -> CIState: ...
    def merge_pr(self, number: int, expected_sha: str, *, live: bool = False) -> bool: ...
    def close_pr(self, number: int, *, live: bool = False) -> bool: ...
    def comment(self, number: int, body: str, *, live: bool = False) -> bool: ...


def _number(number: int) -> str:
    if number <= 0:
        raise GitHubError("编号必须为正整数")
    return str(number)


def _sha(sha: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", sha):
        raise GitHubError("提交编号格式错误")
    return sha


class GitHubWrites:
    """真假实现共用核对规则；布尔值只表示写入已获确认。"""

    def get_pr(self, number: int) -> PullRequest:
        raise NotImplementedError

    def get_ci(self, sha: str) -> CIState:
        raise NotImplementedError

    def _issue_state(self, number: int) -> str:
        raise NotImplementedError

    def _write(self, resource: str, payload: dict[str, object], method: str) -> object:
        raise NotImplementedError

    def merge_pr(self, number: int, expected_sha: str, *, live: bool = False) -> bool:
        resource = f"pulls/{_number(number)}/merge"
        _sha(expected_sha)
        pr = self.get_pr(number)
        if pr.head_sha != expected_sha:
            raise GitHubError("PR 的 head SHA 与预期不一致，拒绝合并")
        if pr.merged:
            return True
        if pr.state != "open":
            raise GitHubError("PR 已关闭，拒绝合并")
        if self.get_ci(expected_sha) is not CIState.GREEN:
            raise GitHubError("CI 尚未全部通过，拒绝合并")
        if not live:
            return False
        result = _mapping(
            self._write(resource, {"sha": expected_sha, "merge_method": "squash"}, "PUT")
        )
        if result.get("merged") is not True:
            raise GitHubError("GitHub 未确认合并成功")
        confirmed = self.get_pr(number)
        if not confirmed.merged or confirmed.head_sha != expected_sha:
            raise GitHubError("合并后的状态尚未确认")
        return True

    def close_pr(self, number: int, *, live: bool = False) -> bool:
        resource = f"pulls/{_number(number)}"
        pr = self.get_pr(number)
        if pr.merged:
            raise GitHubError("PR 已合并，不能关闭")
        if pr.state == "closed":
            return True
        if not live:
            return False
        self._write(resource, {"state": "closed"}, "PATCH")
        confirmed = self.get_pr(number)
        if confirmed.state != "closed" or confirmed.merged:
            raise GitHubError("关闭后的状态尚未确认")
        return True

    def comment(self, number: int, body: str, *, live: bool = False) -> bool:
        resource = f"issues/{_number(number)}/comments"
        if self._issue_state(number) not in {"open", "closed"}:
            raise GitHubError("评论目标状态无效")
        if not live:
            return False
        self._write(resource, {"body": body}, "POST")
        return True


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise GitHubError("GitHub 返回的数据格式错误")
    return cast("dict[str, object]", value)


def _items(value: object) -> list[object]:
    if not isinstance(value, list):
        raise GitHubError("GitHub 返回的列表格式错误")
    return cast("list[object]", value)


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise GitHubError("GitHub 返回的文本格式错误")
    return value


@dataclass
class GhGitHub(GitHubWrites):
    """参数列表启动 gh；评论正文通过标准输入的 JSON 传递。"""

    repo: str
    timeout: float = 30

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repo):
            raise GitHubError("仓库必须为 owner/repo")

    def _api(
        self,
        resource: str,
        *,
        payload: dict[str, object] | None = None,
        method: str = "GET",
        pages: bool = False,
    ) -> object:
        args = ["gh", "api", f"repos/{self.repo}/{resource}", "--method", method]
        if pages:
            args.extend(["--paginate", "--slurp"])
        if payload is not None:
            args.extend(["--input", "-"])
        try:
            result = subprocess.run(
                args,
                input=None if payload is None else json.dumps(payload),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout,
                check=False,
                shell=False,
            )
            if result.returncode:
                raise GitHubError("gh 命令失败")
            return cast(object, json.loads(result.stdout))
        except (OSError, subprocess.TimeoutExpired, ValueError):
            raise GitHubError("gh 无法执行或返回了无效数据") from None

    def _write(self, resource: str, payload: dict[str, object], method: str) -> object:
        return self._api(resource, payload=payload, method=method)

    def list_issues(self) -> tuple[Issue, ...]:
        issues: list[Issue] = []
        for page in _items(self._api("issues?state=open&labels=agent&per_page=100", pages=True)):
            for raw in _items(page):
                item = _mapping(raw)
                if "pull_request" in item:
                    continue
                number = item.get("number")
                if not isinstance(number, int) or isinstance(number, bool):
                    raise GitHubError("Issue 编号格式错误")
                labels = tuple(
                    _text(_mapping(label).get("name")) for label in _items(item.get("labels"))
                )
                issue = Issue(
                    number,
                    _text(item.get("title")),
                    _text(item.get("body") or ""),
                    labels,
                    _text(item.get("state")),
                )
                if issue.state == "open" and "agent" in issue.labels:
                    issues.append(issue)
        return tuple(issues)

    def get_pr(self, number: int) -> PullRequest:
        data = _mapping(self._api(f"pulls/{_number(number)}"))
        merged = data.get("merged")
        state = _text(data.get("state"))
        if not isinstance(merged, bool) or state not in {"open", "closed"}:
            raise GitHubError("PR 状态格式错误")
        return PullRequest(
            number, _sha(_text(_mapping(data.get("head")).get("sha"))), state, merged
        )

    def _issue_state(self, number: int) -> str:
        return _text(_mapping(self._api(f"issues/{_number(number)}")).get("state"))

    def get_ci(self, sha: str) -> CIState:
        prefix = f"commits/{_sha(sha)}"
        conclusions: list[CIState] = []
        for page in _items(
            self._api(f"{prefix}/check-runs?per_page=100&filter=latest", pages=True)
        ):
            for raw in _items(_mapping(page).get("check_runs")):
                check = _mapping(raw)
                if check.get("status") != "completed":
                    conclusions.append(CIState.PENDING)
                elif check.get("conclusion") in {"success", "neutral", "skipped"}:
                    conclusions.append(CIState.GREEN)
                else:
                    conclusions.append(CIState.RED)
        # 旧式 status 按 context 只取最新一条，不能把历史失败算进去。
        seen: set[str] = set()
        for page in _items(self._api(f"{prefix}/statuses?per_page=100", pages=True)):
            for raw in _items(page):
                status = _mapping(raw)
                context = _text(status.get("context"))
                if context in seen:
                    continue
                seen.add(context)
                state = status.get("state")
                conclusions.append(
                    CIState.GREEN
                    if state == "success"
                    else CIState.RED
                    if state in {"error", "failure"}
                    else CIState.PENDING
                )
        if CIState.RED in conclusions:
            return CIState.RED
        if not conclusions or CIState.PENDING in conclusions:
            return CIState.PENDING
        return CIState.GREEN


@dataclass
class FakeGitHub(GitHubWrites):
    """内存替身；writes 只记录真正启用的写入，fail 用于模拟故障。"""

    issues: tuple[Issue, ...] = ()
    prs: dict[int, PullRequest] = field(default_factory=dict[int, PullRequest])
    checks: dict[str, CIState] = field(default_factory=dict[str, CIState])
    writes: list[tuple[str, dict[str, object]]] = field(
        default_factory=list[tuple[str, dict[str, object]]]
    )
    fail: bool = False

    def _check(self) -> None:
        if self.fail:
            raise GitHubError("gh 命令失败")

    def list_issues(self) -> tuple[Issue, ...]:
        self._check()
        return tuple(i for i in self.issues if i.state == "open" and "agent" in i.labels)

    def get_pr(self, number: int) -> PullRequest:
        self._check()
        if number not in self.prs:
            raise GitHubError("PR 不存在")
        return self.prs[number]

    def get_ci(self, sha: str) -> CIState:
        self._check()
        return self.checks.get(sha, CIState.PENDING)

    def _issue_state(self, number: int) -> str:
        self._check()
        if number in self.prs:
            return self.prs[number].state
        for issue in self.issues:
            if issue.number == number:
                return issue.state
        raise GitHubError("Issue 不存在")

    def _write(self, resource: str, payload: dict[str, object], method: str) -> object:
        self._check()
        number = int(resource.split("/")[1])
        if resource.endswith("/merge"):
            # 模拟服务端的原子 SHA 条件，覆盖读后、写前出现新提交的竞争。
            if self.prs[number].head_sha != payload.get("sha"):
                raise GitHubError("PR 的 head SHA 与预期不一致，拒绝合并")
            self.writes.append((resource, payload))
            self.prs[number] = replace(self.prs[number], state="closed", merged=True)
            return {"merged": True}
        self.writes.append((resource, payload))
        if method == "PATCH":
            self.prs[number] = replace(self.prs[number], state="closed")
        return {}
