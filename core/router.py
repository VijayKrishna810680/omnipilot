"""
Model router: one interface to many AI providers, with automatic fallback.

When a provider hits its free limit (or fails), the router moves on to the next one,
so chat keeps working. Providers are used only if their API key is set.

Free options:
  groq        GROQ_API_KEY        console.groq.com (no credit card)
  gemini      GEMINI_API_KEY      aistudio.google.com (no GCP billing)
  openrouter  OPENROUTER_API_KEY  openrouter.ai (has free models)
  ollama      (no key)            your own computer, no limits
Paid option:
  openai      OPENAI_API_KEY
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field


@dataclass
class Provider:
    name: str
    base_url: str | None
    key_env: str | None
    models: list[str]


PROVIDERS: dict[str, Provider] = {
    "groq": Provider("groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY",
                     ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]),
    "gemini": Provider("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY",
                       ["gemini-flash-latest"]),
    "openrouter": Provider("openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
                           ["openai/gpt-oss-120b:free"]),
    "ollama": Provider("ollama", os.getenv("OLLAMA_URL", "http://localhost:11434/v1"), None,
                       [os.getenv("OLLAMA_MODEL", "qwen2.5:7b")]),
    "openai": Provider("openai", None, "OPENAI_API_KEY", ["gpt-4o-mini"]),
}
DEFAULT_ORDER = ["groq", "gemini", "openrouter", "openai", "ollama"]


class NoProviderError(RuntimeError):
    pass


@dataclass
class Reply:
    """What the model answered: text and/or tool calls."""
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)  # [{"id", "name", "arguments"(json str)}]
    provider: str = ""
    model: str = ""


def _is_retryable(err: Exception) -> bool:
    text = str(err).lower()
    return any(k in text for k in ("429", "rate", "quota", "overloaded", "503", "502", "timeout",
                                   "temporarily", "capacity", "connection"))


def _retry_after(err: Exception) -> float | None:
    """Seconds the provider asks us to wait (e.g. 'Please try again in 7.2s' or '1m3.5s')."""
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", str(err))
    if m:
        return int(m.group(1) or 0) * 60 + float(m.group(2))
    return None


def _short(err: Exception) -> str:
    text = str(err)
    m = re.search(r"'message': '([^']{0,200})", text)
    return (m.group(1) if m else text.splitlines()[0])[:200]


THINK = re.compile(r"<think>.*?</think>\s*", re.S)
MAX_WAIT = 30  # seconds we are willing to wait for a free-tier limit to reset


class Router:
    def __init__(self, order: list[str] | None = None, keys: dict[str, str] | None = None,
                 enable_ollama: bool | None = None):
        self.keys = {k: v for k, v in (keys or {}).items() if v}
        self.order = order or DEFAULT_ORDER
        self.enable_ollama = bool(os.getenv("OLLAMA_URL")) if enable_ollama is None else enable_ollama
        self.last_errors: list[str] = []
        self.cooldown: dict[tuple[str, str], float] = {}  # (provider, model) -> time it can be used again
        self.sleep, self.now = time.sleep, time.time

    # ---- which providers can we use right now?
    def key_for(self, name: str) -> str | None:
        p = PROVIDERS[name]
        if p.key_env is None:
            return "ollama"
        return self.keys.get(p.key_env) or os.getenv(p.key_env)

    def available(self) -> list[str]:
        out = []
        for name in self.order:
            if name == "ollama" and not self.enable_ollama:
                continue
            if self.key_for(name):
                out.append(name)
        return out

    # ---- call with fallback
    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             max_tokens: int = 3000) -> Reply:
        """Try each provider/model in order. On a rate limit, remember when that model is free again,
        move on to the next one, and if all are busy wait (up to MAX_WAIT) for the soonest one."""
        self.last_errors = []
        candidates = [(p, m) for p in self.available() for m in PROVIDERS[p].models]
        if not candidates:
            raise NoProviderError("No AI provider configured. Add a free GROQ_API_KEY or GEMINI_API_KEY.")
        for _round in range(3):
            waits = []
            for provider, model in candidates:
                ready_at = self.cooldown.get((provider, model), 0)
                if ready_at > self.now():
                    waits.append(ready_at - self.now())
                    continue
                try:
                    return self._call(provider, model, messages, tools, max_tokens)
                except Exception as e:  # noqa: BLE001 -- we record and fall through
                    self.last_errors.append(f"{provider}/{model}: {_short(e)}")
                    if _is_retryable(e):
                        wait = _retry_after(e) or 5.0
                        self.cooldown[(provider, model)] = self.now() + wait
                        waits.append(wait)
            if not waits or min(waits) > MAX_WAIT:
                break
            self.sleep(min(waits) + 0.5)
        raise NoProviderError("All providers failed: " + " | ".join(self.last_errors[-3:]))

    def _call(self, provider: str, model: str, messages, tools, max_tokens) -> Reply:
        from openai import OpenAI
        p = PROVIDERS[provider]
        client = OpenAI(base_url=p.base_url, api_key=self.key_for(provider), max_retries=0, timeout=120)
        kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if "gpt-oss" in model or model.startswith("gemini"):
            kwargs["reasoning_effort"] = "low"
        resp = client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        calls = [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments or "{}"}
                 for c in (msg.tool_calls or [])]
        return Reply(content=THINK.sub("", msg.content or ""), tool_calls=calls, provider=provider, model=model)
