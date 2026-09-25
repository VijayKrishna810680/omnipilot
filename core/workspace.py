"""Each chat session gets its own folder for the files the agent creates."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from core.config import WORKSPACE_ROOT


class Workspace:
    def __init__(self, session_id: str | None = None, root: Path | None = None):
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.dir = (root or WORKSPACE_ROOT) / self.session_id
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, relative: str) -> Path:
        """Resolve a user/agent-supplied path and refuse anything outside the workspace."""
        rel = str(relative).strip().lstrip("/\\")
        p = (self.dir / rel).resolve()
        if self.dir.resolve() not in p.parents and p != self.dir.resolve():
            raise ValueError(f"Path '{relative}' is outside the workspace")
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def files(self) -> list[Path]:
        return sorted((p for p in self.dir.rglob("*") if p.is_file() and not p.name.startswith(".")),
                      key=lambda p: p.stat().st_mtime, reverse=True)

    def rel(self, p: Path) -> str:
        return str(p.resolve().relative_to(self.dir.resolve()))


def safe_filename(name: str, ext: str) -> str:
    name = re.sub(r"[^\w\-. ]+", "", str(name)).strip().replace(" ", "_") or "file"
    if not name.lower().endswith(ext):
        name = re.sub(r"\.[A-Za-z0-9]+$", "", name) + ext
    return name
