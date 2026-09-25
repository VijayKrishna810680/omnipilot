import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from core.router import Reply, Router  # noqa: E402


class ScriptedRouter(Router):
    """A fake model that replays a fixed list of replies (for deterministic tests)."""

    def __init__(self, script):
        super().__init__(keys={"GROQ_API_KEY": "test"})
        self.script = list(script)
        self.seen = []

    def chat(self, messages, tools=None, max_tokens=4000):
        self.seen.append(messages)
        step = self.script.pop(0)
        if isinstance(step, str):
            return Reply(content=step, provider="scripted", model="test")
        calls = [{"id": f"call_{i}_{len(self.seen)}", "name": n, "arguments": json.dumps(a)} for i, (n, a) in enumerate(step)]
        return Reply(content="", tool_calls=calls, provider="scripted", model="test")


@pytest.fixture
def env(tmp_path):
    from core.activity import ActivityLog
    from core.memory import Memory
    from core.workspace import Workspace
    ws = Workspace("t", root=tmp_path / "ws")
    return ws, Memory(tmp_path / "mem.sqlite"), ActivityLog(tmp_path / "log.sqlite")
