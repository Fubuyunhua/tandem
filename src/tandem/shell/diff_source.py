"""改动采集器：根据 `base...sha` 自己算出真实改动。

等级必须按真实改动算，所以"改动是什么"这件事由外壳从版本库读，
既不听 Agent 回执的自述，也不听内核的猜测（ADR-0001"完成与否只看外部证据"）。

密钥扫描这一步先留接口：默认实现如实返回"未扫描"，并在记录里标明。
"""

from __future__ import annotations

import os
import posixpath
import subprocess
import tempfile
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Protocol

from tandem.core.identity import is_commit_oid
from tandem.core.model import AssertionDrop, ChangeSet, FileChange, TestWeakening
from tandem.shell.assertions import count_assertions, is_test_path, leaves_test_collection
from tandem.shell.weakening import new_test_weakenings


def _clean_git_environment() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_OPTIONAL_LOCKS="0")
    return env


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


def parse_raw_diff_z(
    payload: bytes,
) -> tuple[list[str], list[str], list[tuple[str, str]], tuple[FileChange, ...]]:
    """保留 raw diff 两端模式，名称仍按 NUL 解码。"""
    fields = payload.split(b"\0")
    index = 0
    names = bytearray()
    entries: list[FileChange] = []
    while index < len(fields) and fields[index]:
        header = fields[index].decode("ascii").split()
        if len(header) != 5 or not header[0].startswith(":"):
            raise DiffError("Git raw diff 格式错误")
        status = header[4]
        count = 2 if status.startswith(("R", "C")) else 1
        if index + count >= len(fields) or not all(fields[index + 1 : index + count + 1]):
            raise DiffError("Git raw diff 被截断")
        raw_paths = fields[index + 1 : index + count + 1]
        names.extend(status.encode() + b"\0" + b"\0".join(raw_paths) + b"\0")
        paths = [part.decode("utf-8", "surrogateescape") for part in raw_paths]
        entries.append(
            FileChange(paths[-1], header[0][1:], header[1], paths[0] if count == 2 else None)
        )
        index += count + 1
    paths, deleted, renames = parse_name_status_z(bytes(names))
    return paths, deleted, renames, tuple(entries)


@dataclass(frozen=True)
class GitDiffSource:
    """真实实现：`git diff --name-status -M base...sha`，再数一遍断言的变化。"""

    cwd: Path | None = None
    scanner: SecretScanner = NoSecretScan()
    _environment: dict[str, str] | None = field(default=None, repr=False, compare=False)

    def resolve_oid(self, ref: str) -> str:
        value = self._git_bytes("rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
        oid = value.decode("ascii").strip().lower()
        if not is_commit_oid(oid):
            raise DiffError("Git 未返回完整提交 OID")
        return oid

    def collect(self, base: str, sha: str) -> CollectedDiff:
        sha = self.resolve_oid(sha)
        base = self.resolve_oid(base)
        # 只借用对象库；临时 bare 仓库没有用户 diff.*、属性驱动或原仓库配置。
        objects = Path(self._git_bytes("rev-parse", "--git-path", "objects").decode().strip())
        if not objects.is_absolute():
            objects = (self.cwd or Path.cwd()) / objects
        object_format = self._git_bytes("rev-parse", "--show-object-format").decode().strip()
        env = _clean_git_environment()
        with tempfile.TemporaryDirectory(prefix="tandem-diff-") as directory:
            bare = Path(directory)
            initialized = subprocess.run(
                [
                    "git",
                    "init",
                    "--bare",
                    "--template=",
                    f"--object-format={object_format}",
                    str(bare),
                ],
                capture_output=True,
                env=env,
                check=False,
            )
            if initialized.returncode:
                raise DiffError("无法创建隔离的 Git 读取环境")
            env["GIT_OBJECT_DIRECTORY"] = str(objects.resolve())
            return replace(self, cwd=bare, _environment=env)._collect_oids(base, sha)

    def _collect_oids(self, base: str, sha: str) -> CollectedDiff:
        # 先求共同祖先，再看"受审分支相对共同祖先"改了什么
        merge_base = self._merge_base(base, sha)
        # -z：用 NUL 分隔并且**不做**引号转义，中文、制表符、双引号都能原样拿到
        payload = self._git_bytes(
            "diff",
            "--raw",
            "--no-abbrev",
            "-z",
            "-M",
            "--ignore-submodules=none",
            "--no-ext-diff",
            "--no-textconv",
            merge_base,
            sha,
        )
        paths, deleted, renames, entries = parse_raw_diff_z(payload)
        entries = tuple(
            replace(
                entry,
                before_target=self._resolve_link(merge_base, entry.previous_path or entry.path)
                if entry.before_mode == "120000"
                else None,
                after_target=self._resolve_link(sha, entry.path)
                if entry.after_mode == "120000"
                else None,
            )
            for entry in entries
        )
        changed = tuple(paths)
        before, after, drops = self._assertion_changes(merge_base, sha, paths, deleted, renames)
        weakenings: list[TestWeakening] = []
        for old, new in [*((path, path) for path in paths), *renames]:
            if is_test_path(new) and new.casefold().endswith((".py", ".pyi")):
                try:
                    weakenings.extend(
                        new_test_weakenings(
                            self._git_show(merge_base, old),
                            self._git_show(sha, new),
                            new,
                        )
                    )
                except (SyntaxError, ValueError, UnicodeError):
                    raise DiffError(f"无法解析测试文件 {new} 的静态弱化证据") from None
        scan = self.scanner.scan((*changed, *deleted, *(pair[1] for pair in renames)))
        return CollectedDiff(
            changes=ChangeSet(
                paths=changed,
                file_changes=entries,
                test_weakenings=tuple(weakenings),
                removed_test_paths=tuple(
                    old for old, new in renames if leaves_test_collection(old, new)
                ),
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

    def _tree_mode(self, revision: str, path: str) -> str:
        data = self._git_bytes("--literal-pathspecs", "ls-tree", "-z", revision, "--", path)
        return data.split(b" ", 1)[0].decode("ascii") if data else "000000"

    def _resolve_link(self, revision: str, path: str) -> str:
        seen: set[str] = set()
        target = path
        for _ in range(40):
            parts = target.split("/")
            for index in range(1, len(parts) + 1):
                prefix = "/".join(parts[:index])
                if self._tree_mode(revision, prefix) != "120000":
                    continue
                if prefix in seen:
                    raise DiffError("符号链接出现循环，不能确认目标")
                seen.add(prefix)
                raw = self._git_show(revision, prefix).replace("\\", "/")
                if len(raw) > 1 and raw[1] == ":":
                    return "/仓库外链接"
                target = posixpath.normpath(
                    posixpath.join(posixpath.dirname(prefix), raw, *parts[index:])
                )
                if target.startswith("/") or target == ".." or target.startswith("../"):
                    return "/仓库外链接"
                break
            else:
                return target
        raise DiffError("符号链接层数过多，不能确认目标")

    def _merge_base(self, base: str, sha: str) -> str:
        """两条历史的分叉点。没有共同祖先时不猜"之前"是什么。"""
        merged = subprocess.run(
            ["git", "merge-base", base, sha],
            cwd=self.cwd,
            env=self._environment or _clean_git_environment(),
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
            if not is_test_path(path):
                continue
            before = self._count_assertions(merge_base, path)
            after = self._count_assertions(sha, path)
            before_total += before
            after_total += after
            counted = True
            if after < before:
                drops.append(AssertionDrop(path=path, before=before, after=after))

        for path in deleted:
            if not is_test_path(path):
                continue
            before = self._count_assertions(merge_base, path)
            before_total += before
            counted = True
            if before > 0:
                drops.append(AssertionDrop(path=path, before=before, after=0))

        for old_path, new_path in renames:
            if not (is_test_path(old_path) or is_test_path(new_path)):
                continue
            before = self._count_assertions(merge_base, old_path)
            after = (
                0
                if leaves_test_collection(old_path, new_path)
                else self._count_assertions(sha, new_path)
            )
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
        try:
            return count_assertions(text, path)
        except (SyntaxError, ValueError, UnicodeError):
            raise DiffError(f"无法解析测试文件 {path}，不能确认断言证据") from None

    def _git_show(self, revision: str, path: str) -> str:
        completed = subprocess.run(
            ["git", "show", f"{revision}:{path}"],
            cwd=self.cwd,
            env=self._environment or _clean_git_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            check=False,
        )
        if completed.returncode != 0:
            # 只有路径确实不存在才能按新增文件的旧内容为空；已有对象读失败必须拒绝。
            if self._tree_mode(revision, path) == "000000":
                return ""
            raise DiffError(f"无法读取已存在的 Git 对象 {revision}:{path}")
        return completed.stdout

    def _git_bytes(self, *args: str) -> bytes:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.cwd,
            env=self._environment or _clean_git_environment(),
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", "replace").strip()
            raise DiffError(f"git {' '.join(args)} 失败：{detail}")
        return completed.stdout
