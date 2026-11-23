"""SQLite-file LangGraph checkpointer (separate from the business DB and from the cache) + workflow registry.
The registry holds only workflow metadata (id, thread, type, status) - not logs or story content."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from langgraph.checkpoint.sqlite import SqliteSaver

_LOCK = threading.Lock()
_SAVERS: dict[str, SqliteSaver] = {}


def get_checkpointer(path: str | Path) -> SqliteSaver:
    p = str(Path(path).resolve())
    with _LOCK:
        if p not in _SAVERS:
            Path(p).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(p, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            _SAVERS[p] = SqliteSaver(conn)
        return _SAVERS[p]


def close_checkpointer(path: str | Path) -> None:
    """Close the shared connection (used by tests to simulate an application restart)."""
    p = str(Path(path).resolve())
    with _LOCK:
        s = _SAVERS.pop(p, None)
    if s is not None:
        s.conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowRegistry:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._c() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS workflow_registry (
                workflow_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, workflow_type TEXT NOT NULL,
                story_id TEXT, request_json TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")

    @contextmanager
    def _c(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create(self, wid: str, tid: str, wtype: str, request: dict) -> None:
        with self._c() as c:
            c.execute("INSERT INTO workflow_registry VALUES (?,?,?,?,?,?,?,?)",
                      (wid, tid, wtype, request.get("story_id"), json.dumps(request), "running", _now(), _now()))

    def update(self, wid: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._c() as c:
            c.execute(f"UPDATE workflow_registry SET {cols}, updated_at=? WHERE workflow_id=?",
                      (*fields.values(), _now(), wid))

    def get(self, wid: str) -> Optional[dict]:
        with self._c() as c:
            r = c.execute("SELECT * FROM workflow_registry WHERE workflow_id=?", (wid,)).fetchone()
        return dict(r) if r else None

    def list(self, limit: int, offset: int) -> tuple[list[dict], int]:
        with self._c() as c:
            rows = c.execute("SELECT * FROM workflow_registry ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
                             (limit, offset)).fetchall()
            total = c.execute("SELECT COUNT(*) FROM workflow_registry").fetchone()[0]
        return [dict(r) for r in rows], total
