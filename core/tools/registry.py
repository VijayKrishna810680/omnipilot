"""
Tool registry. A tool is a normal Python function plus a JSON schema the AI model reads.
'risky' tools (like running code) need the user's approval before they run.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable
    risky: bool = False

    def schema(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, properties: dict, required: list[str] | None = None, risky: bool = False):
    def wrap(fn):
        REGISTRY[name] = Tool(name, description,
                              {"type": "object", "properties": properties, "required": required or []},
                              fn, risky)
        return fn
    return wrap


@dataclass
class ToolResult:
    ok: bool
    output: str                 # text the model sees
    files: list[str] | None = None   # workspace-relative files created
    image: str | None = None    # workspace-relative image to show inline

    def for_model(self) -> str:
        data = {"ok": self.ok, "result": self.output}
        if self.files:
            data["files_created"] = self.files
        return json.dumps(data, ensure_ascii=False)[:12000]


def run_tool(name: str, arguments: str | dict, ctx) -> ToolResult:
    """Execute a tool safely: bad JSON, unknown tools and exceptions become error results."""
    if name not in REGISTRY:
        return ToolResult(False, f"Unknown tool '{name}'. Available: {', '.join(REGISTRY)}")
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
    except json.JSONDecodeError as e:
        return ToolResult(False, f"Arguments were not valid JSON: {e}")
    try:
        return REGISTRY[name].fn(ctx, **args)
    except TypeError as e:
        return ToolResult(False, f"Wrong arguments for {name}: {e}")
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"{type(e).__name__}: {e}")
