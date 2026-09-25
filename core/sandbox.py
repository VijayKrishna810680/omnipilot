"""
Run AI-written Python code in a restricted child process.

Protections:
  - separate process in the session workspace folder, with a time limit
  - memory / CPU / file-size limits (Linux)
  - no API keys or secrets in its environment
  - an audit hook that blocks network access, launching programs and writing outside the workspace
For multi-user production, run this inside a container (Docker/gVisor) as well.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

from core.config import CODE_MEMORY_MB, CODE_TIMEOUT_SEC, ROOT

MPL_CACHE = ROOT / "data" / ".mplcache"   # shared chart font cache, built once

BOOTSTRAP = textwrap.dedent(r'''
    import os, sys
    WORK = os.path.realpath(os.getcwd())
    BLOCKED = ("socket.connect", "socket.bind", "socket.sendto", "subprocess.Popen", "os.system",
               "os.exec", "os.spawn", "os.posix_spawn", "os.fork", "os.kill", "ctypes.dlopen",
               "shutil.rmtree", "os.chmod", "os.chown")
    def _hook(event, args):
        if event.startswith(BLOCKED):
            raise PermissionError(f"Blocked for safety: {event}")
        if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            path, mode = args[0], (args[1] or "r") if len(args) > 1 else "r"
            flags = args[2] if len(args) > 2 else 0
            writing = any(c in str(mode) for c in "wax+") or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
            if writing:
                real = os.path.realpath(os.fsdecode(path))
                if not (real == WORK or real.startswith(WORK + os.sep) or real == "/dev/null"):
                    raise PermissionError(f"Blocked for safety: writing outside the workspace ({path})")
        if event in ("os.remove", "os.unlink", "os.rename", "os.rmdir") and args:
            real = os.path.realpath(os.fsdecode(args[0]))
            if not real.startswith(WORK + os.sep):
                raise PermissionError(f"Blocked for safety: {event} outside the workspace")
    import matplotlib
    matplotlib.use("Agg")
    try:  # load heavy libraries (and build the font cache) BEFORE the safety hook is switched on
        import matplotlib.pyplot, matplotlib.font_manager  # noqa: F401
        import pandas, numpy  # noqa: F401
    except Exception:
        pass
    sys.addaudithook(_hook)
    del _hook
    code = open(sys.argv[1], encoding="utf-8").read()
    exec(compile(code, "agent_code.py", "exec"), {"__name__": "__main__"})
''')


@dataclass
class RunResult:
    ok: bool
    stdout: str
    stderr: str
    new_files: list[str]
    timed_out: bool = False


def _limits():
    try:
        import resource
        mem = CODE_MEMORY_MB * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        resource.setrlimit(resource.RLIMIT_CPU, (CODE_TIMEOUT_SEC, CODE_TIMEOUT_SEC + 5))
        resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 1024 * 1024, 50 * 1024 * 1024))
    except Exception:  # noqa: BLE001 -- not available on Windows
        pass


def run_python(code: str, workdir: Path, timeout: int = CODE_TIMEOUT_SEC) -> RunResult:
    workdir = Path(workdir)
    MPL_CACHE.mkdir(parents=True, exist_ok=True)
    before = {p: p.stat().st_mtime_ns for p in workdir.rglob("*") if p.is_file()}
    (workdir / ".agent_code.py").write_text(code, encoding="utf-8")
    (workdir / ".bootstrap.py").write_text(BOOTSTRAP, encoding="utf-8")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(workdir),
           "MPLCONFIGDIR": str(MPL_CACHE), "PYTHONIOENCODING": "utf-8", "LANG": "C.UTF-8",
           # one math thread: on many-core servers OpenBLAS threads would exceed the memory limit
           "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    try:
        proc = subprocess.run([sys.executable, "-I", ".bootstrap.py", ".agent_code.py"], cwd=workdir, env=env,
                              capture_output=True, text=True, timeout=timeout,
                              preexec_fn=_limits if os.name == "posix" else None)
        out, err, ok, timed_out = proc.stdout, proc.stderr, proc.returncode == 0, False
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        err, ok, timed_out = f"Stopped: code ran longer than {timeout}s", False, True
    after = {p: p.stat().st_mtime_ns for p in workdir.rglob("*") if p.is_file() and not p.name.startswith(".")
             and "__pycache__" not in p.parts}
    new = sorted(str(p.relative_to(workdir)) for p, t in after.items() if before.get(p) != t)
    return RunResult(ok, out[-8000:], err[-4000:], new, timed_out)
