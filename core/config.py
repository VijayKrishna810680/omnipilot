"""Settings for OmniPilot. Values come from environment variables, a .env file or Streamlit secrets."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            if value.strip() and not os.getenv(key.strip()):
                os.environ[key.strip()] = value.strip().strip('"').strip("'")


_load_dotenv()

WORKSPACE_ROOT = Path(os.getenv("OP_WORKSPACE", ROOT / "workspace"))
MEMORY_DB = Path(os.getenv("OP_MEMORY_DB", ROOT / "data" / "memory.sqlite"))
LOG_DB = Path(os.getenv("OP_LOG_DB", ROOT / "data" / "activity.sqlite"))

MAX_AGENT_STEPS = int(os.getenv("OP_MAX_STEPS", "12"))
CODE_TIMEOUT_SEC = int(os.getenv("OP_CODE_TIMEOUT", "30"))
CODE_MEMORY_MB = int(os.getenv("OP_CODE_MEMORY_MB", "512"))
