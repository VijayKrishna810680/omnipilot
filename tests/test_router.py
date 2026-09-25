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


def test_waits_for_rate_limit_reset_then_succeeds(monkeypatch):
    r = Router(keys={"GROQ_API_KEY": "a"}, enable_ollama=False)
    slept, calls, clock = [], [], [1000.0]
    r.now = lambda: clock[0]
    r.sleep = lambda sec: (slept.append(sec), clock.__setitem__(0, clock[0] + sec))

    def fake(provider, model, *a, **k):
        calls.append(model)
        if len(calls) <= 3:  # every Groq model is busy at first
            raise RuntimeError("Error code: 429 - Rate limit reached ... Please try again in 2.5s.")
        return Reply(content="ok", provider=provider, model=model)

    monkeypatch.setattr(r, "_call", fake)
    assert r.chat([{"role": "user", "content": "hi"}]).content == "ok"
    assert len(slept) == 1 and 2.5 <= slept[0] <= 3.5


def test_gives_up_when_wait_is_too_long(monkeypatch):
    r = Router(keys={"GROQ_API_KEY": "a"}, enable_ollama=False)
    r.sleep = lambda s: (_ for _ in ()).throw(AssertionError("should not wait"))
    monkeypatch.setattr(r, "_call", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("429 Rate limit reached for tokens per day. Please try again in 12m30.5s")))
    try:
        r.chat([{"role": "user", "content": "hi"}])
        assert False
    except NoProviderError as e:
        assert "Rate limit" in str(e)


def test_hidden_reasoning_is_removed():
    from core.router import THINK
    assert THINK.sub("", "<think>step by step</think>\nHello") == "Hello"
