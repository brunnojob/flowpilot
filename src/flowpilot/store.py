"""SQLite persistence for runs, step results, logs and per-workflow state.

Uses the standard-library ``sqlite3`` module in WAL mode behind a lock, which
is plenty for a single-node automation server and keeps dependencies minimal.
All public methods are synchronous and thread-safe; async callers should use
:func:`asyncio.to_thread` for heavy queries (the engine does).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    workflow TEXT NOT NULL,
    status TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    trigger_payload TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_workflow ON runs (workflow, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs (started_at DESC);

CREATE TABLE IF NOT EXISTS step_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    step_id TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms INTEGER,
    output TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_step_runs_run ON step_runs (run_id);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    step_id TEXT,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_run ON logs (run_id, id);

CREATE TABLE IF NOT EXISTS workflow_state (
    workflow TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workflow, key)
);

CREATE TABLE IF NOT EXISTS workflow_settings (
    workflow TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def utcnow() -> str:
    """Current UTC time as an ISO-8601 string with millisecond precision."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _dumps(value: Any, limit: int | None = None) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if limit and len(text) > limit:
        return json.dumps({"_truncated": True, "preview": text[:limit]}, ensure_ascii=False)
    return text


def _loads(text: str | None) -> Any:
    return None if text is None else json.loads(text)


class Store:
    """Thread-safe SQLite store."""

    def __init__(self, path: str | Path, *, max_output_chars: int = 20_000) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.max_output_chars = max_output_chars
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _query(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    # ------------------------------------------------------------------ runs

    def create_run(
        self, run_id: str, workflow: str, trigger_type: str, payload: Any, started_at: str
    ) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO runs (id, workflow, status, trigger_type, trigger_payload, started_at)"
                " VALUES (?, ?, 'running', ?, ?, ?)",
                (
                    run_id,
                    workflow,
                    trigger_type,
                    _dumps(payload, self.max_output_chars),
                    started_at,
                ),
            )

    def finish_run(
        self, run_id: str, status: str, finished_at: str, duration_ms: int, error: str | None
    ) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE runs SET status=?, finished_at=?, duration_ms=?, error=? WHERE id=?",
                (status, finished_at, duration_ms, error, run_id),
            )

    def mark_interrupted(self) -> int:
        """Mark runs left 'running' by a crashed/stopped process as failed."""
        with self._tx() as c:
            cur = c.execute(
                "UPDATE runs SET status='failed', error='interrupted (server stopped)',"
                " finished_at=? WHERE status='running'",
                (utcnow(),),
            )
            return cur.rowcount

    @staticmethod
    def _run_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["trigger_payload"] = _loads(data.get("trigger_payload"))
        return data

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM runs WHERE id=?", (run_id,))
        if not rows:
            return None
        run = self._run_row(rows[0])
        run["steps"] = self.list_step_runs(run_id)
        return run

    def list_runs(
        self,
        workflow: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM runs"
        clauses: list[str] = []
        params: list[Any] = []
        if workflow:
            clauses.append("workflow=?")
            params.append(workflow)
        if status:
            clauses.append("status=?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        return [self._run_row(r) for r in self._query(sql, params)]

    def count_runs(self, workflow: str | None = None, status: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM runs WHERE 1=1"
        params: list[Any] = []
        if workflow:
            sql += " AND workflow=?"
            params.append(workflow)
        if status:
            sql += " AND status=?"
            params.append(status)
        return int(self._query(sql, params)[0][0])

    def stats(self, since_hours: int = 24) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
        row = self._query(
            "SELECT COUNT(*) AS total,"
            " SUM(status='success') AS success,"
            " SUM(status='failed') AS failed,"
            " SUM(status='running') AS running,"
            " AVG(duration_ms) AS avg_ms"
            " FROM runs WHERE started_at >= ?",
            (since,),
        )[0]
        total = row["total"] or 0
        success = row["success"] or 0
        finished = success + (row["failed"] or 0)
        return {
            "window_hours": since_hours,
            "total": total,
            "success": success,
            "failed": row["failed"] or 0,
            "running": row["running"] or 0,
            "success_rate": round(success / finished, 4) if finished else None,
            "avg_duration_ms": round(row["avg_ms"]) if row["avg_ms"] is not None else None,
        }

    def workflow_summaries(self, per_workflow: int = 20) -> dict[str, dict[str, Any]]:
        """Recent statuses and last run for every workflow that has runs."""
        rows = self._query(
            "SELECT workflow, id, status, started_at, duration_ms FROM ("
            " SELECT *, ROW_NUMBER() OVER (PARTITION BY workflow ORDER BY started_at DESC) AS rn"
            " FROM runs) WHERE rn <= ? ORDER BY workflow, started_at DESC",
            (per_workflow,),
        )
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            entry = out.setdefault(r["workflow"], {"last_run": None, "recent": []})
            item = {
                "id": r["id"],
                "status": r["status"],
                "started_at": r["started_at"],
                "duration_ms": r["duration_ms"],
            }
            if entry["last_run"] is None:
                entry["last_run"] = item
            entry["recent"].append(item)
        return out

    def prune(self, older_than_days: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
        with self._tx() as c:
            return c.execute(
                "DELETE FROM runs WHERE started_at < ? AND status != 'running'", (cutoff,)
            ).rowcount

    # ------------------------------------------------------------- step runs

    def start_step(self, run_id: str, step_id: str, type_: str, started_at: str) -> int:
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO step_runs (run_id, step_id, type, status, started_at)"
                " VALUES (?, ?, ?, 'running', ?)",
                (run_id, step_id, type_, started_at),
            )
            return int(cur.lastrowid or 0)

    def finish_step(
        self,
        row_id: int,
        status: str,
        attempts: int,
        finished_at: str,
        duration_ms: int,
        output: Any,
        error: str | None,
    ) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE step_runs SET status=?, attempts=?, finished_at=?, duration_ms=?,"
                " output=?, error=? WHERE id=?",
                (
                    status,
                    attempts,
                    finished_at,
                    duration_ms,
                    _dumps(output, self.max_output_chars),
                    error,
                    row_id,
                ),
            )

    def list_step_runs(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._query("SELECT * FROM step_runs WHERE run_id=? ORDER BY id", (run_id,))
        out = []
        for r in rows:
            d = dict(r)
            d["output"] = _loads(d["output"])
            d.pop("run_id", None)
            out.append(d)
        return out

    # ------------------------------------------------------------------ logs

    def add_log(self, run_id: str, level: str, message: str, step_id: str | None, ts: str) -> int:
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO logs (run_id, ts, level, step_id, message) VALUES (?, ?, ?, ?, ?)",
                (run_id, ts, level, step_id, message),
            )
            return int(cur.lastrowid or 0)

    def get_logs(self, run_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        rows = self._query(
            "SELECT id, ts, level, step_id, message FROM logs WHERE run_id=? AND id>? ORDER BY id",
            (run_id, after_id),
        )
        return [dict(r) for r in rows]

    # ----------------------------------------------------------------- state

    def get_state(self, workflow: str) -> dict[str, Any]:
        rows = self._query("SELECT key, value FROM workflow_state WHERE workflow=?", (workflow,))
        return {r["key"]: json.loads(r["value"]) for r in rows}

    def set_state(self, workflow: str, values: dict[str, Any]) -> None:
        now = utcnow()
        with self._tx() as c:
            c.executemany(
                "INSERT INTO workflow_state (workflow, key, value, updated_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT (workflow, key) DO UPDATE SET value=excluded.value,"
                " updated_at=excluded.updated_at",
                [(workflow, k, _dumps(v), now) for k, v in values.items()],
            )

    def delete_state(self, workflow: str, keys: list[str] | None = None) -> None:
        with self._tx() as c:
            if keys is None:
                c.execute("DELETE FROM workflow_state WHERE workflow=?", (workflow,))
            else:
                c.executemany(
                    "DELETE FROM workflow_state WHERE workflow=? AND key=?",
                    [(workflow, k) for k in keys],
                )

    # -------------------------------------------------------------- settings

    def get_enabled_overrides(self) -> dict[str, bool]:
        rows = self._query("SELECT workflow, enabled FROM workflow_settings")
        return {r["workflow"]: bool(r["enabled"]) for r in rows}

    def set_enabled(self, workflow: str, enabled: bool) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO workflow_settings (workflow, enabled, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT (workflow) DO UPDATE SET enabled=excluded.enabled,"
                " updated_at=excluded.updated_at",
                (workflow, int(enabled), utcnow()),
            )
