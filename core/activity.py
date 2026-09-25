"""Activity log: every tool call and model call, for monitoring and debugging."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core.config import LOG_DB


class ActivityLog:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or LOG_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute("""CREATE TABLE IF NOT EXISTS activity (ts TEXT, session TEXT, kind TEXT, name TEXT,
                         ok INTEGER, seconds REAL, detail TEXT)""")

    def add(self, session: str, kind: str, name: str, ok: bool, seconds: float, detail: str = ""):
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT INTO activity VALUES (?,?,?,?,?,?,?)",
                      (datetime.now(timezone.utc).isoformat(timespec="seconds"), session, kind, name,
                       int(ok), round(seconds, 2), detail[:500]))

    def recent(self, limit: int = 300) -> list[dict]:
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute("SELECT * FROM activity ORDER BY rowid DESC LIMIT ?", (limit,))]
