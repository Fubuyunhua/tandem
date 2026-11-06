"""SQLite 存储。

三张表：
- ``events``：事件只追加。用触发器把 UPDATE / DELETE 直接挡掉。
- ``tasks``：任务的最新快照 + 状态版本号，版本号只允许往前走。
- ``actions``：每个动作的编号和状态（已发出 / 结果未知 / 已完成）。

数据库默认放在 ``data/`` 下（已被 git 忽略）。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from tandem.core.model import Action, ActionKind, ActionStatus, Event, TaskRecord, TaskStatus
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

    def list_events(self, task_id: str | None = None) -> list[Event]:
        if task_id is None:
            rows = self._connection.execute("SELECT payload FROM events ORDER BY id").fetchall()
        else:
            rows = self._connection.execute(
                "SELECT payload FROM events WHERE task_id = ? ORDER BY id", (task_id,)
            ).fetchall()
        return [serde.event_from_dict(json.loads(str(row["payload"]))) for row in rows]

    # ------------------------------------------------------------ 任务

    def save_task(self, task: TaskRecord, now: datetime | None = None) -> None:
        """保存最新快照。状态版本号只允许往前走。"""
        existing = self.load_task(task.task_id)
        if existing is not None and task.state_version < existing.state_version:
            raise StoreError(
                f"任务 {task.task_id} 的版本号要从 {existing.state_version} 往前，"
                f"不能退回 {task.state_version}"
            )
        stamp = (now or _now()).isoformat()
        with self._connection:
            self._connection.execute(
                "INSERT INTO tasks (task_id, state_version, status, level, payload, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(task_id) DO UPDATE SET"
                "   state_version = excluded.state_version,"
                "   status = excluded.status,"
                "   level = excluded.level,"
                "   payload = excluded.payload,"
                "   updated_at = excluded.updated_at",
                (
                    task.task_id,
                    task.state_version,
                    task.status.name,
                    task.level.name,
                    serde.dumps(serde.task_to_dict(task)),
                    stamp,
                ),
            )

    def load_task(self, task_id: str) -> TaskRecord | None:
        row = self._connection.execute(
            "SELECT payload FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return serde.task_from_dict(json.loads(str(row["payload"])))

    def list_tasks(self) -> list[TaskRecord]:
        rows = self._connection.execute("SELECT payload FROM tasks ORDER BY task_id").fetchall()
        return [serde.task_from_dict(json.loads(str(row["payload"]))) for row in rows]

    def list_tasks_by_status(self, status: TaskStatus) -> list[TaskRecord]:
        return [task for task in self.list_tasks() if task.status is status]

    # ------------------------------------------------------------ 动作

    def record_action(self, action: Action, now: datetime | None = None) -> None:
        """内核要求做的动作先记下来（默认"已发出"），再去执行。"""
        stamp = (now or _now()).isoformat()
        with self._connection:
            self._connection.execute(
                "INSERT INTO actions"
                " (action_id, task_id, kind, provider, detail, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(action_id) DO UPDATE SET"
                "   status = excluded.status,"
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

    def unconfirmed_actions(self, task_id: str) -> list[Action]:
        """第 26 条：重启后只核对没有确认完成的动作。"""
        return [action for action in self.list_actions(task_id) if action.status.is_unconfirmed]
