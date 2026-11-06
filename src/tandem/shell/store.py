"""SQLite 存储。

四张表：
- ``events``：事件只追加。用触发器把 UPDATE / DELETE 直接挡掉。
- ``tasks``：任务的最新快照 + 状态版本号，版本号只允许往前走。
- ``actions``：每个动作的编号和状态（已发出 / 结果未知 / 已完成），
  是动作状态的唯一事实来源，任务快照里那份由它投影出来。
- ``quota``：每家提供方的额度估计，重启后从这里恢复。

数据库默认放在 ``data/`` 下（已被 git 忽略）。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from tandem.core.model import (
    Action,
    ActionKind,
    ActionStatus,
    Event,
    QuotaState,
    TaskRecord,
    TaskStatus,
)
from tandem.shell import serde

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    state_version INTEGER,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- 事件只追加：改和删都直接报错
CREATE TRIGGER IF NOT EXISTS events_append_only_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, '事件表只追加，不能修改');
END;

CREATE TRIGGER IF NOT EXISTS events_append_only_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, '事件表只追加，不能删除');
END;

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    state_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    level TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quota (
    provider TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS actions (
    action_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    provider TEXT,
    detail TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class StoreError(RuntimeError):
    """存储层发现了不该发生的事，比如版本号倒退。"""


class ConflictError(StoreError):
    """同一版本号被另一个处理者抢先改了（并发冲突）。"""


@dataclass(frozen=True)
class CommitResult:
    """一次事务写进去的东西。"""

    events: int = 0
    task_written: bool = False
    actions: int = 0


def _now() -> datetime:
    return datetime.now(UTC)


class Store:
    """一个 SQLite 数据库。用完记得 ``close()``，或者用 ``with``。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(path))
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    # ------------------------------------------------------------ 事件

    def append_event(self, event: Event, now: datetime | None = None) -> None:
        """只追加，不修改。"""
        stamp = (now or _now()).isoformat()
        with self._connection:
            self._insert_event(event, stamp)

    def list_events(self, task_id: str | None = None) -> list[Event]:
        if task_id is None:
            rows = self._connection.execute("SELECT payload FROM events ORDER BY id").fetchall()
        else:
            rows = self._connection.execute(
                "SELECT payload FROM events WHERE task_id = ? ORDER BY id", (task_id,)
            ).fetchall()
        return [serde.event_from_dict(json.loads(str(row["payload"]))) for row in rows]

    # ------------------------------------------------------------ 任务

    def commit(
        self,
        *,
        events: Sequence[Event] = (),
        task: TaskRecord | None = None,
        expected_version: int | None = None,
        actions: Sequence[Action] = (),
        now: datetime | None = None,
    ) -> CommitResult:
        """一个事务保存“事件 + 任务快照 + 待执行动作”。

        ``expected_version`` 是写这次决定时读到的旧版本号：任务表用
        ``UPDATE ... WHERE state_version = ?`` 更新，受影响行数为 0 就说明
        有人抢先改过，抛 ``ConflictError``（同一版本号只接受内容完全相同的重放）。
        事务提交以后才轮到外壳去执行副作用。
        """
        stamp = (now or _now()).isoformat()
        with self._connection:  # 一个事务：要么全进去，要么全不进去
            for event in events:
                self._insert_event(event, stamp)
            written = False
            if task is not None:
                self._write_task(task, expected_version, stamp)
                written = True
            for action in actions:
                self._insert_action(action, stamp)
        return CommitResult(events=len(events), task_written=written, actions=len(actions))

    def _insert_event(self, event: Event, stamp: str) -> None:
        self._connection.execute(
            "INSERT INTO events (task_id, kind, state_version, payload, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                event.task_id,
                event.kind.name,
                event.state_version,
                serde.dumps(serde.event_to_dict(event)),
                stamp,
            ),
        )

    def _insert_action(self, action: Action, stamp: str) -> None:
        self._connection.execute(
            "INSERT INTO actions"
            " (action_id, task_id, kind, provider, detail, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(action_id) DO UPDATE SET status = excluded.status,"
            "   updated_at = excluded.updated_at",
            (
                action.action_id,
                action.task_id,
                action.kind.name,
                action.provider,
                action.detail,
                action.status.name,
                stamp,
                stamp,
            ),
        )

    def _write_task(self, task: TaskRecord, expected_version: int | None, stamp: str) -> None:
        payload = serde.dumps(serde.task_to_dict(task))
        row = self._connection.execute(
            "SELECT state_version, payload FROM tasks WHERE task_id = ?", (task.task_id,)
        ).fetchone()
        current_version = None if row is None else int(row["state_version"])
        current_payload = None if row is None else str(row["payload"])

        if expected_version is None:
            if current_version is not None:
                if current_payload == payload:  # 完全相同的重放
                    return
                raise ConflictError(f"任务 {task.task_id} 已经存在，不能重复创建")
            self._connection.execute(
                "INSERT INTO tasks (task_id, state_version, status, level, payload, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    task.task_id,
                    task.state_version,
                    task.status.name,
                    task.level.name,
                    payload,
                    stamp,
                ),
            )
            return

        if current_version is None:
            raise StoreError(f"任务 {task.task_id} 不存在，不能更新")
        if task.state_version < current_version:
            raise StoreError(
                f"任务 {task.task_id} 的版本号不能从 {current_version} 退回 {task.state_version}"
            )
        if task.state_version == current_version:
            # 同一版本号只接受内容完全相同的重放
            if current_payload == payload:
                return
            raise ConflictError(
                f"任务 {task.task_id} 在版本 {current_version} 上已经有另一份内容，拒绝覆盖"
            )
        if expected_version != current_version:
            raise ConflictError(
                f"任务 {task.task_id} 已经被另一个处理者改到版本 {current_version}，"
                f"本次基于版本 {expected_version} 的写入被拒绝"
            )
        cursor = self._connection.execute(
            "UPDATE tasks SET state_version = ?, status = ?, level = ?, payload = ?,"
            " updated_at = ? WHERE task_id = ? AND state_version = ?",
            (
                task.state_version,
                task.status.name,
                task.level.name,
                payload,
                stamp,
                task.task_id,
                expected_version,
            ),
        )
        if cursor.rowcount == 1:
            return
        raise ConflictError(f"任务 {task.task_id} 的更新没有生效（期望旧版本 {expected_version}）")

    def load_task(self, task_id: str) -> TaskRecord | None:
        row = self._connection.execute(
            "SELECT payload FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return self._project_actions(serde.task_from_dict(json.loads(str(row["payload"]))))

    def list_tasks(self) -> list[TaskRecord]:
        rows = self._connection.execute("SELECT payload FROM tasks ORDER BY task_id").fetchall()
        return [
            self._project_actions(serde.task_from_dict(json.loads(str(row["payload"]))))
            for row in rows
        ]

    def _project_actions(self, task: TaskRecord) -> TaskRecord:
        """动作状态的唯一事实来源是动作表，任务快照里的那份由它投影出来。"""
        statuses = {action.action_id: action.status for action in self.list_actions(task.task_id)}
        if not statuses:
            return task
        projected = tuple(
            replace(action, status=statuses[action.action_id])
            if action.action_id in statuses
            else action
            for action in task.actions
        )
        if projected == task.actions:
            return task
        return replace(task, actions=projected)

    def list_tasks_by_status(self, status: TaskStatus) -> list[TaskRecord]:
        return [task for task in self.list_tasks() if task.status is status]

    # ------------------------------------------------------------ 动作

    def record_action(self, action: Action, now: datetime | None = None) -> None:
        """单独补记一个动作（正常路径是跟决定一起 commit）。"""
        stamp = (now or _now()).isoformat()
        with self._connection:
            self._insert_action(action, stamp)

    def update_action_status(
        self, action_id: str, status: ActionStatus, now: datetime | None = None
    ) -> None:
        """执行完（或结果未知）以后更新动作状态。动作表是可以更新的，它就是为此存在。"""
        stamp = (now or _now()).isoformat()
        with self._connection:
            self._connection.execute(
                "UPDATE actions SET status = ?, updated_at = ? WHERE action_id = ?",
                (status.name, stamp, action_id),
            )

    def list_actions(self, task_id: str | None = None) -> list[Action]:
        if task_id is None:
            rows = self._connection.execute(
                "SELECT action_id, task_id, kind, provider, detail, status FROM actions"
                " ORDER BY created_at, action_id"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT action_id, task_id, kind, provider, detail, status FROM actions"
                " WHERE task_id = ? ORDER BY created_at, action_id",
                (task_id,),
            ).fetchall()
        return [
            Action(
                action_id=str(row["action_id"]),
                kind=ActionKind[str(row["kind"])],
                task_id=str(row["task_id"]),
                detail=str(row["detail"]),
                provider=None if row["provider"] is None else str(row["provider"]),
                status=ActionStatus[str(row["status"])],
            )
            for row in rows
        ]

    # ------------------------------------------------------------ 额度

    def load_quota(self) -> dict[str, QuotaState]:
        """重启后恢复额度估计：不知道就是不知道，用完过的继续算用完。"""
        rows = self._connection.execute("SELECT provider, state FROM quota").fetchall()
        return {str(row["provider"]): QuotaState[str(row["state"])] for row in rows}

    def save_quota(self, provider: str, state: QuotaState, now: datetime | None = None) -> None:
        stamp = (now or _now()).isoformat()
        with self._connection:
            self._connection.execute(
                "INSERT INTO quota (provider, state, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(provider) DO UPDATE SET state = excluded.state,"
                "   updated_at = excluded.updated_at",
                (provider, state.name, stamp),
            )

    def unconfirmed_actions(self, task_id: str) -> list[Action]:
        """第 26 条：重启后只核对没有确认完成的动作。"""
        return [action for action in self.list_actions(task_id) if action.status.is_unconfirmed]
