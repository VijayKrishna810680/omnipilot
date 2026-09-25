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
                     ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]),
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


class Router:
    def __init__(self, order: list[str] | None = None, keys: dict[str, str] | None = None,
                 enable_ollama: bool | None = None):
        self.keys = {k: v for k, v in (keys or {}).items() if v}
        self.order = order or DEFAULT_ORDER
        self.enable_ollama = bool(os.getenv("OLLAMA_URL")) if enable_ollama is None else enable_ollama
        self.last_errors: list[str] = []

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
             max_tokens: int = 4000) -> Reply:
        self.last_errors = []
        candidates = [(p, m) for p in self.available() for m in PROVIDERS[p].models]
        if not candidates:
            raise NoProviderError("No AI provider configured. Add a free GROQ_API_KEY or GEMINI_API_KEY.")
        for attempt_round in range(2):  # second round after a short pause (rate limits reset quickly)
            for provider, model in candidates:
                try:
                    return self._call(provider, model, messages, tools, max_tokens)
                except Exception as e:  # noqa: BLE001 -- we record and fall through
                    self.last_errors.append(f"{provider}/{model}: {str(e).splitlines()[0][:160]}")
                    if not _is_retryable(e):
                        continue
            time.sleep(3)
        raise NoProviderError("All providers failed: " + " | ".join(self.last_errors[-4:]))

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
        return Reply(content=msg.content or "", tool_calls=calls, provider=provider, model=model)
