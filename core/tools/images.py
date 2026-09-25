"""Generate images from text with free image services (with fallbacks)."""
from __future__ import annotations

import os
import urllib.parse

from core.tools.registry import ToolResult, tool
from core.workspace import safe_filename


def _pollinations(prompt, width, height, seed):
    """Pollinations: free 'flux' model. Needs a free key from enter.pollinations.ai (sign in with GitHub)."""
    import requests
    token = os.getenv("POLLINATIONS_TOKEN") or os.getenv("POLLINATIONS_API_KEY")
    q = urllib.parse.quote(prompt[:900])
    params = {"model": os.getenv("POLLINATIONS_MODEL", "flux"), "width": width, "height": height,
              "nologo": "true", "seed": seed}
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    errors = []
    urls = [f"https://gen.pollinations.ai/image/{q}"] + ([] if token else [f"https://image.pollinations.ai/prompt/{q}"])
    for url in urls:
        try:
            r = requests.get(url, params=params, headers=headers, timeout=120)
            if r.ok and r.headers.get("content-type", "").startswith("image/"):
                return r.content
            errors.append(f"{url.split('/')[2]} HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{url.split('/')[2]}: {e}")
    hint = "" if token else " - add a free POLLINATIONS_TOKEN from enter.pollinations.ai"
    raise RuntimeError(", ".join(errors) + hint)


def _huggingface(prompt, width, height, seed):
    import requests
    token = os.getenv("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN not set")
    model = os.getenv("HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
    r = requests.post(f"https://router.huggingface.co/hf-inference/models/{model}",
                      headers={"Authorization": f"Bearer {token}"},
                      json={"inputs": prompt, "parameters": {"width": width, "height": height, "seed": seed}},
                      timeout=180)
    if not (r.ok and r.headers.get("content-type", "").startswith("image/")):
        raise RuntimeError(f"Hugging Face HTTP {r.status_code}: {r.text[:120]}")
    return r.content


IMAGE_BACKENDS = [("pollinations", _pollinations), ("huggingface", _huggingface)]


@tool("generate_image",
      "Generate an image from a detailed text description (style, subject, colors, lighting). "
      "Returns a PNG/JPG file shown to the user.",
      {"prompt": {"type": "string", "description": "Detailed English description of the image"},
       "filename": {"type": "string"},
       "width": {"type": "integer", "default": 1024},
       "height": {"type": "integer", "default": 1024},
       "seed": {"type": "integer", "description": "Same seed = same image"}},
      ["prompt"])
def generate_image(ctx, prompt, filename="image", width=1024, height=1024, seed=42):
    width, height = max(256, min(int(width), 1536)), max(256, min(int(height), 1536))
    errors = []
    for name, backend in IMAGE_BACKENDS:
        try:
            data = backend(prompt, width, height, int(seed))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
            continue
        ext = ".jpg" if data[:3] == b"\xff\xd8\xff" else ".png"
        path = ctx.workspace.path(safe_filename(filename, ext))
        path.write_bytes(data)
        rel = ctx.workspace.rel(path)
        return ToolResult(True, f"Image saved as {rel} ({len(data) // 1024} KB) via {name}", files=[rel], image=rel)
    return ToolResult(False, "Image generation failed: " + " | ".join(errors))
