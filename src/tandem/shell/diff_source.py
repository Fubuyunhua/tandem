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

from tandem.core.model import ChangeSet

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


@dataclass(frozen=True)
class FakeDiffSource:
    """假实现：直接给一份写好的改动，不碰版本库。"""

    changes: ChangeSet
    secret_scan: SecretScanState = SecretScanState.NOT_SCANNED

    def collect(self, base: str, sha: str) -> CollectedDiff:
        return CollectedDiff(
            changes=self.changes,
            base=base,
            sha=sha,
            secret_scan=self.secret_scan,
        )


@dataclass(frozen=True)
class GitDiffSource:
    """真实实现：`git diff --name-status -M base...sha`，再数一遍断言的变化。"""

    cwd: Path | None = None
    scanner: SecretScanner = NoSecretScan()

    def collect(self, base: str, sha: str) -> CollectedDiff:
        listing = self._git("diff", "--name-status", "-M", f"{base}...{sha}")
        paths: list[str] = []
        deleted: list[str] = []
        renames: list[tuple[str, str]] = []
        for line in listing.splitlines():
            if not line.strip():
                continue
            fields = line.split("\t")
            status = fields[0]
            if status.startswith("R") and len(fields) >= 3:
                renames.append((fields[1], fields[2]))
            elif status.startswith("D") and len(fields) >= 2:
                deleted.append(fields[1])
            elif len(fields) >= 2:
                paths.append(fields[1])

        changed = tuple(paths)
        before, after = self._assertion_totals(base, sha, changed)
        scan = self.scanner.scan((*changed, *deleted, *(pair[1] for pair in renames)))
        return CollectedDiff(
            changes=ChangeSet(
                paths=changed,
                deleted_paths=tuple(deleted),
                renames=tuple(renames),
                assertions_before=before,
                assertions_after=after,
                secret_scan_hit=scan is SecretScanState.HIT,
            ),
            base=base,
            sha=sha,
            secret_scan=scan,
        )

    def _assertion_totals(
        self, base: str, sha: str, paths: tuple[str, ...]
    ) -> tuple[int | None, int | None]:
        """只在测试文件里数断言，统计增加前后的总数。"""
        tests = [path for path in paths if TEST_FILE_PATTERN.search(path)]
        if not tests:
            return None, None
        before = sum(self._count_assertions(base, path) for path in tests)
        after = sum(self._count_assertions(sha, path) for path in tests)
        return before, after

    def _count_assertions(self, revision: str, path: str) -> int:
        text = self._git_show(revision, path)
        return len(ASSERTION_PATTERN.findall(text))

    def _git_show(self, revision: str, path: str) -> str:
        completed = subprocess.run(
            ["git", "show", f"{revision}:{path}"],
            cwd=self.cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            # 新增的文件在旧提交里不存在，按 0 算
            return ""
        return completed.stdout

    def _git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise DiffError(f"git {' '.join(args)} 失败：{completed.stderr.strip()}")
        return completed.stdout
