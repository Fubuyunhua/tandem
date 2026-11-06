"""改动采集器：根据 `base...sha` 自己算出真实改动。

等级必须按真实改动算，所以"改动是什么"这件事由外壳从版本库读，
既不听 Agent 回执的自述，也不听内核的猜测（ADR-0001"完成与否只看外部证据"）。

密钥扫描这一步先留接口：默认实现如实返回"未扫描"，并在记录里标明。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from tandem.core.identity import is_commit_oid
from tandem.core.model import AssertionDrop, ChangeSet

# 数断言用的近似写法：Python 的 assert、JS 的 expect(
ASSERTION_PATTERN = re.compile(r"(?<![\w.])(assert\b|expect\s*\()")

# 测试文件的判定（只用来数断言）
TEST_FILE_PATTERN = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.(py|js|ts)$)")


class DiffError(RuntimeError):
    """读不到真实改动。"""


class SecretScanState(Enum):
    """密钥扫描的三种结果。M1 只会有"未扫描"。"""

    NOT_SCANNED = "未扫描"
    CLEAN = "未命中"
    HIT = "命中"


class SecretScanner(Protocol):
    """密钥扫描接口。以后接 gitleaks 时实现它即可。"""

    def scan(self, paths: tuple[str, ...]) -> SecretScanState: ...


@dataclass(frozen=True)
class NoSecretScan:
    """默认实现：这一轮还没扫描，如实说"未扫描"。"""

    def scan(self, paths: tuple[str, ...]) -> SecretScanState:
        return SecretScanState.NOT_SCANNED


@dataclass(frozen=True)
class CollectedDiff:
    """采集结果：真实改动 + 扫描状态 + 一句给人看的说明。"""

    changes: ChangeSet
    base: str = ""
    sha: str = ""
    secret_scan: SecretScanState = SecretScanState.NOT_SCANNED

    def describe(self) -> str:
        return f"改动来自采集器（{self.base}...{self.sha}）；密钥扫描：{self.secret_scan.value}"


class DiffSource(Protocol):
    """一处改动从哪里来。测试和 demo 用假实现，生产用 git。"""

    def collect(self, base: str, sha: str) -> CollectedDiff: ...
    def resolve_oid(self, ref: str) -> str: ...


@dataclass(frozen=True)
class FakeDiffSource:
    """假实现：直接给一份写好的改动，不碰版本库。"""

    changes: ChangeSet
    secret_scan: SecretScanState = SecretScanState.NOT_SCANNED

    def resolve_oid(self, ref: str) -> str:
        if not is_commit_oid(ref):
            raise DiffError("假采集器只接受完整模拟 OID")
        return ref

    def collect(self, base: str, sha: str) -> CollectedDiff:
        return CollectedDiff(
            changes=self.changes,
            base=base,
            sha=sha,
            secret_scan=self.secret_scan,
        )


def parse_name_status_z(payload: bytes) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """解析 `git diff --name-status -z -M` 的输出。

    `-z` 的格式是“状态 NUL 路径 NUL”，改名/复制条目多一个路径：
    ``R100 NUL 旧路径 NUL 新路径 NUL``。路径按 UTF-8 原样解码，不做 Git 的引号转义。
    """
    fields = payload.decode("utf-8", "surrogateescape").split("\0")
    paths: list[str] = []
    deleted: list[str] = []
    renames: list[tuple[str, str]] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        if not status:
            index += 1
            continue
        if status[0] in {"R", "C"}:
            if index + 2 >= len(fields):
                raise DiffError(f"git diff 输出被截断：{status}")
            before, after = fields[index + 1], fields[index + 2]
            if not before or not after:
                raise DiffError(f"git diff 输出被截断：{status}")
            if status[0] == "R":
                renames.append((before, after))
            else:
                # 复制出来的文件对新路径来说是一处新增
                paths.append(after)
            index += 3
            continue
        if index + 1 >= len(fields):
            raise DiffError(f"git diff 输出被截断：{status}")
        path = fields[index + 1]
        if not path:
            raise DiffError(f"git diff 输出被截断：{status}")
        if status[0] == "D":
            deleted.append(path)
        else:
            paths.append(path)
        index += 2
    return paths, deleted, renames


@dataclass(frozen=True)
class GitDiffSource:
    """真实实现：`git diff --name-status -M base...sha`，再数一遍断言的变化。"""

    cwd: Path | None = None
    scanner: SecretScanner = NoSecretScan()

    def resolve_oid(self, ref: str) -> str:
        value = self._git_bytes("rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
        oid = value.decode("ascii").strip().lower()
        if not is_commit_oid(oid):
            raise DiffError("Git 未返回完整提交 OID")
        return oid

    def collect(self, base: str, sha: str) -> CollectedDiff:
        sha = self.resolve_oid(sha)
        base = self.resolve_oid(base)
        # 先求共同祖先，再看"受审分支相对共同祖先"改了什么
        merge_base = self._merge_base(base, sha)
        # -z：用 NUL 分隔并且**不做**引号转义，中文、制表符、双引号都能原样拿到
        payload = self._git_bytes("diff", "--name-status", "-z", "-M", merge_base, sha)
        paths, deleted, renames = parse_name_status_z(payload)
        changed = tuple(paths)
        before, after, drops = self._assertion_changes(merge_base, sha, paths, deleted, renames)
        scan = self.scanner.scan((*changed, *deleted, *(pair[1] for pair in renames)))
        return CollectedDiff(
            changes=ChangeSet(
                paths=changed,
                deleted_paths=tuple(deleted),
                renames=tuple(renames),
                assertions_before=before,
                assertions_after=after,
                assertion_drops=drops,
                secret_scan_hit=scan is SecretScanState.HIT,
            ),
            base=base,
            sha=sha,
            secret_scan=scan,
        )

    def _merge_base(self, base: str, sha: str) -> str:
        """两条历史的分叉点。没有共同祖先时不猜"之前"是什么。"""
        merged = subprocess.run(
            ["git", "merge-base", base, sha],
            cwd=self.cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            check=False,
        )
        if merged.returncode != 0:
            raise DiffError(
                f"{base} 和 {sha} 没有共同祖先，算不出'之前'的内容：{merged.stderr.strip()}"
            )
        return merged.stdout.strip()

    def _assertion_changes(
        self,
        merge_base: str,
        sha: str,
        paths: list[str],
        deleted: list[str],
        renames: list[tuple[str, str]],
    ) -> tuple[int | None, int | None, tuple[AssertionDrop, ...]]:
        """按文件统计断言变化，返回（合计之前、合计之后、逐个文件的减少记录）。

        底线条目是"测试文件里的断言数量减少"，必须**逐个文件**判断：
        一个文件少了一条、另一个文件多了一条，合计持平也不能算没减少。
        - 普通增改：同一路径比两端；
        - 改名：旧路径数之前、新路径数之后，配成一对；
        - 删除：删除前有断言就算减少（之后按 0）。
        新增文件只会让断言变多，不能抵消别的文件的减少。
        """
        before_total = 0
        after_total = 0
        drops: list[AssertionDrop] = []
        counted = False

        for path in paths:
            if not TEST_FILE_PATTERN.search(path):
                continue
            before = self._count_assertions(merge_base, path)
            after = self._count_assertions(sha, path)
            before_total += before
            after_total += after
            counted = True
            if after < before:
                drops.append(AssertionDrop(path=path, before=before, after=after))

        for path in deleted:
            if not TEST_FILE_PATTERN.search(path):
                continue
            before = self._count_assertions(merge_base, path)
            before_total += before
            counted = True
            if before > 0:
                drops.append(AssertionDrop(path=path, before=before, after=0))

        for old_path, new_path in renames:
            if not (TEST_FILE_PATTERN.search(old_path) or TEST_FILE_PATTERN.search(new_path)):
                continue
            before = self._count_assertions(merge_base, old_path)
            after = self._count_assertions(sha, new_path)
            before_total += before
            after_total += after
            counted = True
            if after < before:
                drops.append(
                    AssertionDrop(path=new_path, before=before, after=after, previous_path=old_path)
                )

        if not counted:
            return None, None, ()
        return before_total, after_total, tuple(drops)

    def _count_assertions(self, revision: str, path: str) -> int:
        text = self._git_show(revision, path)
        return len(ASSERTION_PATTERN.findall(text))

    def _git_show(self, revision: str, path: str) -> str:
        completed = subprocess.run(
            ["git", "show", f"{revision}:{path}"],
            cwd=self.cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            check=False,
        )
        if completed.returncode != 0:
            # 新增的文件在旧提交里不存在，按 0 算
            return ""
        return completed.stdout

    def _git_bytes(self, *args: str) -> bytes:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.cwd,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", "replace").strip()
            raise DiffError(f"git {' '.join(args)} 失败：{detail}")
        return completed.stdout
