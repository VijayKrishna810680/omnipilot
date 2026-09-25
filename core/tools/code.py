"""Project builder tools: write files, run Python safely, read files, zip a project."""
from __future__ import annotations

import zipfile

from core.sandbox import run_python as sandbox_run
from core.tools.registry import ToolResult, tool
from core.workspace import safe_filename


@tool("write_file",
      "Create or overwrite a text file in the workspace (code, HTML, CSV, Markdown, config...). "
      "Use folders to build multi-file projects, e.g. 'todo_app/app.py'.",
      {"path": {"type": "string"}, "content": {"type": "string"}},
      ["path", "content"])
def write_file(ctx, path, content):
    p = ctx.workspace.path(path)
    p.write_text(content, encoding="utf-8")
    rel = ctx.workspace.rel(p)
    return ToolResult(True, f"Wrote {rel} ({len(content.splitlines())} lines)", files=[rel])


@tool("read_file", "Read a text file from the workspace (first 12,000 characters).",
      {"path": {"type": "string"}}, ["path"])
def read_file(ctx, path):
    p = ctx.workspace.path(path)
    if not p.exists():
        return ToolResult(False, f"{path} not found")
    return ToolResult(True, p.read_text(encoding="utf-8", errors="replace")[:12000])


@tool("list_files", "List all files in the workspace.", {}, [])
def list_files(ctx):
    files = [f"{ctx.workspace.rel(p)} ({p.stat().st_size} bytes)" for p in ctx.workspace.files()]
    return ToolResult(True, "\n".join(files) or "(workspace is empty)")


@tool("run_python",
      "Run Python code in a safe sandbox inside the workspace folder (no internet, 30s limit). "
      "pandas, numpy and matplotlib are available. Save charts with plt.savefig('name.png'). "
      "Print results you want to see. Use it to test code, analyze data or make charts.",
      {"code": {"type": "string"}}, ["code"], risky=True)
def run_python(ctx, code):
    r = sandbox_run(code, ctx.workspace.dir)
    text = (r.stdout or "") + (f"\n[stderr]\n{r.stderr}" if r.stderr else "")
    images = [f for f in r.new_files if f.lower().endswith((".png", ".jpg", ".jpeg"))]
    return ToolResult(r.ok, text.strip() or "(no output)", files=r.new_files or None,
                      image=images[0] if images else None)


@tool("zip_project", "Package a folder in the workspace into a .zip file the user can download.",
      {"folder": {"type": "string"}, "zip_name": {"type": "string"}}, ["folder"])
def zip_project(ctx, folder, zip_name=""):
    src = ctx.workspace.path(folder)
    if not src.is_dir():
        return ToolResult(False, f"Folder {folder} not found")
    out = ctx.workspace.path(safe_filename(zip_name or src.name, ".zip"))
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                z.write(p, p.relative_to(src.parent))
                count += 1
    rel = ctx.workspace.rel(out)
    return ToolResult(True, f"Created {rel} with {count} files", files=[rel])
