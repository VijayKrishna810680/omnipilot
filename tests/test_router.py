"""The router must fall back to the next provider/model when one hits a rate limit."""
from core.router import NoProviderError, Reply, Router


def test_fallback_on_rate_limit(monkeypatch):
    r = Router(keys={"GROQ_API_KEY": "a", "GEMINI_API_KEY": "b"}, enable_ollama=False)
    calls = []

    def fake(provider, model, *a, **k):
        calls.append(f"{provider}/{model}")
        if provider == "groq":
            raise RuntimeError("Error code: 429 - rate limit reached")
        return Reply(content="hello", provider=provider, model=model)

    monkeypatch.setattr(r, "_call", fake)
    reply = r.chat([{"role": "user", "content": "hi"}])
    assert reply.provider == "gemini"
    assert calls[:2] == ["groq/openai/gpt-oss-120b", "groq/openai/gpt-oss-20b"]


def test_all_fail_raises(monkeypatch):
    r = Router(keys={"GROQ_API_KEY": "a"}, enable_ollama=False)
    monkeypatch.setattr(r, "_call", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("401 invalid key")))
    monkeypatch.setattr("time.sleep", lambda s: None)
    try:
        r.chat([{"role": "user", "content": "hi"}])
        assert False
    except NoProviderError as e:
        assert "401" in str(e)


def test_only_configured_providers_are_used(monkeypatch):
    for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert Router(keys={"GEMINI_API_KEY": "x"}, enable_ollama=False).available() == ["gemini"]
