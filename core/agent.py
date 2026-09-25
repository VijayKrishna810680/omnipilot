"""
The OmniPilot agent.

Loop:  think (model) -> call tools -> read results -> think again ... -> final answer.
Risky tools (running code) pause the loop and ask the user for approval; the agent resumes
exactly where it stopped. Every step is emitted as an event so the UI can show it live.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Iterator

# importing the tool modules registers them
from core.tools import code as _code, documents as _docs, excel as _xl, images as _img, memory_tools as _mem  # noqa: F401
from core.tools import file_search as _fs, web as _web  # noqa: F401
from core.activity import ActivityLog
from core.config import MAX_AGENT_STEPS
from core.memory import Memory
from core.router import NoProviderError, Router
from core.tools.registry import REGISTRY, run_tool
from core.workspace import Workspace

SYSTEM_PROMPT = """You are OmniPilot, a capable all-in-one AI assistant and agent. Today is {today}.

You can chat, explain and advise, AND you can take actions with tools:
- create_document: Word/PDF reports, letters, resumes, plans (write rich Markdown content).
- create_presentation: PowerPoint decks.
- create_excel / analyze_file: spreadsheets with formulas and charts; analyze uploaded CSV/Excel.
- generate_image: pictures from a detailed description.
- write_file, run_python, read_file, list_files, zip_project: build and test software projects,
  analyze data, draw charts (plt.savefig). Always test code with run_python before saying it works.
- web_search / read_webpage: research current information on the internet; cite sources as links.
- search_files: find answers inside the user's uploaded documents (PDF, Word, slides, Excel); cite file and page.
- remember / recall: long-term memory about the user.

Guidelines:
- For questions about recent events, prices, or anything that may have changed, use web_search first,
  read 1-3 good sources, then answer with a "Sources:" list of links. Never invent URLs.
- When the user asks about "my file/document/PDF", use search_files and base the answer on the passages.
- For simple questions, just answer. Use tools when the user wants a file, image, project, data analysis or calculation.
- Make files complete and high quality (real content, not placeholders).
- For projects: write every file, run tests, fix errors, then zip the folder.
- When the user shares a lasting preference or fact about themselves, call remember.
- After using tools, give a short summary of what you made and the file names. Never invent results:
  quote numbers (totals, test results) from tool outputs instead of calculating them yourself.
- If a tool fails, read the error, fix the cause and try again (max 2 retries), or explain the problem.
- Code runs in a sandbox with no network and no subprocess. To run tests use pytest in-process:
  run_python("import pytest; raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider', 'folder']))").
- Excel: data rows start at row 2 (row 1 = headers). Use total_row=true for totals and "{{row}}" in
  per-row formulas (e.g. "=B{{row}}-C{{row}}") so every reference is correct.
- Write answers in Markdown only. Never use HTML tags such as <br>.

What you remember about the user:
{memories}
"""


def _trim(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"... [{len(text) - limit} chars trimmed]"


def _compact(m: dict) -> dict:
    """Shorter copy of an old message: tool outputs and long tool arguments (e.g. file contents) trimmed."""
    if m["role"] == "tool":
        return {**m, "content": _trim(m["content"], 400)}
    if m.get("tool_calls"):
        calls = []
        for c in m["tool_calls"]:
            try:
                args = json.loads(c["function"]["arguments"] or "{}")
                args = {k: _trim(v, 200) if isinstance(v, str) else v for k, v in args.items()}
                if len(json.dumps(args)) > 1500:
                    args = {k: v for k, v in args.items() if isinstance(v, (str, int, float, bool))}
                arguments = json.dumps(args)
            except (ValueError, TypeError):
                arguments = "{}"
            calls.append({**c, "function": {**c["function"], "arguments": arguments}})
        return {**m, "tool_calls": calls}
    return m


@dataclass
class Context:
    """Everything a tool may use."""
    workspace: Workspace
    memory: Memory


@dataclass
class Event:
    type: str            # model | tool_start | tool_result | approval | final | error
    data: dict = field(default_factory=dict)


class Agent:
    def __init__(self, router: Router, workspace: Workspace, memory: Memory,
                 auto_approve: bool = False, log: ActivityLog | None = None, max_steps: int = MAX_AGENT_STEPS):
        self.router = router
        self.ctx = Context(workspace, memory)
        self.auto_approve = auto_approve
        self.log = log or ActivityLog()
        self.max_steps = max_steps
        self.messages: list[dict] = []      # conversation without the system prompt
        self.pending: list[dict] | None = None  # tool calls waiting for approval

    # ------------------------------------------------------------ public API
    def send(self, user_text: str) -> Iterator[Event]:
        if self.pending:
            yield Event("error", {"message": "Please approve or deny the pending action first."})
            return
        self.messages.append({"role": "user", "content": user_text})
        yield from self._loop()

    def resume(self, approved: bool) -> Iterator[Event]:
        calls, self.pending = self.pending or [], None
        if not calls:
            return
        yield from self._run_calls(calls, first_decision=approved)
        if self.pending is None:
            yield from self._loop()

    @property
    def tools_schema(self) -> list[dict]:
        return [t.schema() for t in REGISTRY.values()]

    # ------------------------------------------------------------ internals
    def _system(self) -> dict:
        last_user = next((m["content"] for m in reversed(self.messages) if m["role"] == "user"), "")
        facts = self.ctx.memory.search(str(last_user), k=6)
        recent = [f["text"] for f in self.ctx.memory.all()[:6]]
        mem = list(dict.fromkeys(facts + recent))
        return {"role": "system", "content": SYSTEM_PROMPT.format(
            today=date.today().isoformat(), memories="\n".join(f"- {m}" for m in mem) or "(nothing yet)")}

    def _window(self, max_messages: int = 40, budget_chars: int = 14000, keep_full: int = 6) -> list[dict]:
        """Keep long chats working on free-tier limits: send recent messages only, shorten old tool
        outputs and old file contents, and stay under a size budget. Always starts at a user turn,
        and never drops the current user request."""
        def size(ms):
            return sum(len(json.dumps(m)) for m in ms)

        n = len(self.messages)
        msgs = [_compact(m) if i < n - keep_full else m for i, m in enumerate(self.messages)][-max_messages:]
        while msgs and msgs[0]["role"] != "user":
            msgs = msgs[1:]
        while size(msgs) > budget_chars:
            later_users = [i for i, m in enumerate(msgs) if m["role"] == "user" and i > 0]
            if not later_users:
                break
            msgs = msgs[later_users[0]:]       # drop the oldest whole turn
        if size(msgs) > budget_chars:          # the current task alone is big: trim it too
            msgs = [_compact(m) for m in msgs[:-2]] + msgs[-2:]
        return [self._system()] + msgs

    def _loop(self) -> Iterator[Event]:
        for _ in range(self.max_steps):
            t0 = time.time()
            try:
                reply = self.router.chat(self._window(), tools=self.tools_schema)
            except NoProviderError as e:
                self.log.add(self.ctx.workspace.session_id, "model", "router", False, time.time() - t0, str(e))
                yield Event("error", {"message": str(e)})
                return
            self.log.add(self.ctx.workspace.session_id, "model", f"{reply.provider}/{reply.model}", True, time.time() - t0)
            yield Event("model", {"provider": reply.provider, "model": reply.model, "text": reply.content,
                                  "has_tools": bool(reply.tool_calls)})
            if not reply.tool_calls:
                self.messages.append({"role": "assistant", "content": reply.content})
                yield Event("final", {"text": reply.content})
                return
            self.messages.append({"role": "assistant", "content": reply.content or "",
                                  "tool_calls": [{"id": c["id"], "type": "function",
                                                  "function": {"name": c["name"], "arguments": c["arguments"]}}
                                                 for c in reply.tool_calls]})
            yield from self._run_calls(reply.tool_calls)
            if self.pending is not None:
                return
        msg = f"I stopped after {self.max_steps} steps to stay within limits. Say 'continue' to keep going."
        self.messages.append({"role": "assistant", "content": msg})
        yield Event("final", {"text": msg})

    def _run_calls(self, calls: list[dict], first_decision: bool | None = None) -> Iterator[Event]:
        for i, call in enumerate(calls):
            tool = REGISTRY.get(call["name"])
            decision = first_decision if i == 0 else None
            if tool and tool.risky and not self.auto_approve and decision is None:
                self.pending = calls[i:]
                yield Event("approval", {"tool": call["name"], "arguments": call["arguments"], "id": call["id"]})
                return
            if decision is False:
                content = '{"ok": false, "result": "The user denied this action. Ask what they want instead."}'
                self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
                yield Event("tool_result", {"tool": call["name"], "ok": False, "output": "Denied by user", "files": []})
                continue
            yield Event("tool_start", {"tool": call["name"], "arguments": call["arguments"]})
            t0 = time.time()
            result = run_tool(call["name"], call["arguments"], self.ctx)
            self.log.add(self.ctx.workspace.session_id, "tool", call["name"], result.ok, time.time() - t0,
                         result.output[:300])
            self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": result.for_model()})
            yield Event("tool_result", {"tool": call["name"], "ok": result.ok, "output": result.output,
                                        "files": result.files or [], "image": result.image})
