"""Long-term memory: facts and preferences saved across chats, found again by keyword relevance (BM25)."""
from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from core.config import MEMORY_DB

_WORD = re.compile(r"[a-z0-9]+")
STOP = set("a an the is are was were be to of and or in on for with my me i you it this that at by as".split())


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in STOP]


class Memory:
    def __init__(self, path: Path | None = None, user: str = "default"):
        self.path = Path(path or MEMORY_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.user = user
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, user TEXT, text TEXT, created TEXT)")

    def _conn(self):
        return sqlite3.connect(self.path)

    def add(self, text: str) -> int:
        text = text.strip()
        with self._conn() as c:
            dup = c.execute("SELECT id FROM facts WHERE user=? AND lower(text)=lower(?)", (self.user, text)).fetchone()
            if dup:
                return dup[0]
            cur = c.execute("INSERT INTO facts (user, text, created) VALUES (?,?,?)",
                            (self.user, text, datetime.now(timezone.utc).isoformat(timespec="seconds")))
            return cur.lastrowid

    def all(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT id, text, created FROM facts WHERE user=? ORDER BY id DESC", (self.user,)).fetchall()
        return [{"id": r[0], "text": r[1], "created": r[2]} for r in rows]

    def delete(self, fact_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM facts WHERE id=? AND user=?", (fact_id, self.user))

    def search(self, query: str, k: int = 5) -> list[str]:
        """Rank facts with BM25 (the classic search-engine formula)."""
        facts = self.all()
        if not facts:
            return []
        docs = [_tokens(f["text"]) for f in facts]
        q = _tokens(query)
        n, avg = len(docs), sum(map(len, docs)) / max(len(docs), 1)
        df = Counter(w for d in docs for w in set(d))
        scores = []
        for f, d in zip(facts, docs):
            tf = Counter(d)
            s = sum(math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5)) * tf[w] * 2.2 /
                    (tf[w] + 1.2 * (0.25 + 0.75 * len(d) / max(avg, 1))) for w in q if w in tf)
            scores.append((s, f["text"]))
        return [t for s, t in sorted(scores, reverse=True)[:k] if s > 0]
