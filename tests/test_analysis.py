"""Tests for the analysis orchestration layer (AI with local fallback).

Covers provider selection (OpenRouter / OpenAI / local), robust JSON parsing
of model output, and graceful fallback to the local engine.
"""
import json
import logging

import httpx

import utils.analysis as analysis


# --------------------------------------------------------------------------- #
# Provider selection
# --------------------------------------------------------------------------- #
def test_provider_config_prefers_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    cfg = analysis._provider_config()
    assert cfg["provider"] == "openrouter"
    assert cfg["api_key"] == "or-key"
    assert "openrouter.ai" in cfg["base_url"]
    # The auto-router: benchmarked 2026-07-17 against pinned free models and
    # won on both success rate and latency (see analysis.py comment).
    assert cfg["models"] == ["openrouter/free"]


def test_provider_config_uses_openai_when_only_openai_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    cfg = analysis._provider_config()
    assert cfg["provider"] == "openai"
    assert cfg["api_key"] == "oa-key"
    assert cfg["base_url"] is None
    assert cfg["models"] == ["gpt-4o-mini"]


def test_provider_config_none_without_any_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert analysis._provider_config() is None


def test_model_override_parses_comma_separated_chain(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENAI_MODEL", "custom/a:free, custom/b:free ,custom/c:free")
    assert analysis._provider_config()["models"] == [
        "custom/a:free", "custom/b:free", "custom/c:free",
    ]


def test_provider_label(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert analysis.provider_label() == "Local engine"
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert analysis.provider_label() == "OpenRouter"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert analysis.provider_label() == "OpenAI"


def test_ai_available_reflects_any_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert analysis.ai_available() is False
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    assert analysis.ai_available() is True


# --------------------------------------------------------------------------- #
# Robust JSON extraction (free models often wrap JSON in prose / code fences)
# --------------------------------------------------------------------------- #
def test_strip_dashes_removes_em_and_en_dashes():
    s = analysis._strip_dashes
    assert "—" not in s("Strong fit — tailor your resume")
    assert s("Strong fit — tailor") == "Strong fit, tailor"
    assert s("skills—Python and Django") == "skills, Python and Django"
    # number ranges keep a hyphen, not a comma
    assert s("2020–2023") == "2020-2023"
    assert "–" not in s("range 5 – 7 items")


def test_strip_dashes_none_safe():
    assert analysis._strip_dashes("") == ""
    assert analysis._strip_dashes(None) == ""


def test_extract_json_plain():
    assert analysis._extract_json('{"score": 80}')["score"] == 80


def test_extract_json_with_code_fence():
    assert analysis._extract_json('```json\n{"score": 73}\n```')["score"] == 73


def test_extract_json_with_surrounding_prose():
    text = 'Sure! Here is the analysis:\n{"score": 50, "summary": "ok"} Hope this helps.'
    data = analysis._extract_json(text)
    assert data["score"] == 50
    assert data["summary"] == "ok"


# --------------------------------------------------------------------------- #
# Fallback behavior
# --------------------------------------------------------------------------- #
def test_analyze_resume_without_key_uses_local(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = analysis.analyze_resume(
        "Python developer with Django and AWS.",
        "Need a Python developer with Django, AWS and Kubernetes.",
    )
    assert result["source"] == "local"
    assert 0 <= result["score"] <= 100
    assert "Kubernetes" in result["missing_skills"]
    assert "Python" in result["matching_skills"]
    assert result["summary"]
    assert isinstance(result["suggestions"], list) and result["suggestions"]


def test_analyze_with_ai_falls_through_to_next_model(monkeypatch, caplog):
    """A rate-limited / failing model is skipped (and logged); the next one is tried."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENAI_MODEL", "bad/one:free,good/two:free")
    calls = []

    good_json = (
        '{"score": 88, "summary": "Great fit.", '
        '"matching_skills": ["Python"], "missing_skills": [], '
        '"suggestions": ["Tighten the summary."]}'
    )

    def fake_chat(model, prompt, **kwargs):
        calls.append(model)
        if model.startswith("bad"):
            raise RuntimeError("429 rate limited")
        return good_json

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)

    local = analysis.analyze_match("Python", "Python")
    with caplog.at_level(logging.INFO, logger="utils.analysis"):
        result = analysis._analyze_with_ai("Python", "Python developer", local)

    assert result["score"] == 88
    assert "bad/one:free" in calls
    assert calls[-1] == "good/two:free"
    # The skipped model is recorded so chronic failures are diagnosable.
    assert any("bad/one:free" in r.getMessage() for r in caplog.records)


def test_analyze_with_ai_raises_when_all_models_fail(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENAI_MODEL", "a:free,b:free")

    def fake_chat(model, prompt, **kwargs):
        raise RuntimeError("429")

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    local = analysis.analyze_match("Python", "Python")
    try:
        analysis._analyze_with_ai("Python", "Python", local)
        assert False, "expected an exception when all models fail"
    except Exception:
        pass


def test_analyze_resume_falls_back_when_ai_errors(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(analysis, "_analyze_with_ai", boom)
    result = analysis.analyze_resume("Python", "Python developer needed")
    assert result["source"] == "local"
    assert 0 <= result["score"] <= 100


def test_analyze_resume_logs_ai_failure(monkeypatch, caplog):
    """AI failures must leave a trace in the logs, not vanish silently."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(analysis, "_analyze_with_ai", boom)
    with caplog.at_level(logging.WARNING, logger="utils.analysis"):
        result = analysis.analyze_resume("Python", "Python developer needed")
    assert result["source"] == "local"
    assert any("network down" in r.getMessage() for r in caplog.records)


def test_http_client_is_reused_for_same_config(monkeypatch):
    """Warm serverless instances should reuse the HTTP client, not rebuild it."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    first = analysis._http_client()
    assert analysis._http_client() is first
    # A config change must produce a fresh client, never a stale one.
    monkeypatch.setenv("OPENROUTER_API_KEY", "another-key")
    assert analysis._http_client() is not first


def test_http_client_carries_auth_and_base_url(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    client = analysis._http_client()
    assert "openrouter.ai" in str(client.base_url)
    assert client.headers["Authorization"] == "Bearer or-key"
    assert client.headers["X-Title"]  # OpenRouter attribution

    # Plain OpenAI: default API base, no attribution headers.
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")
    client = analysis._http_client()
    assert "api.openai.com" in str(client.base_url)
    assert client.headers["Authorization"] == "Bearer oa-key"


def test_chat_completion_posts_payload_and_parses_content(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "  hi there  "}}]}
        )

    fake = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://openrouter.ai/api/v1",
    )
    monkeypatch.setattr(analysis, "_http_client", lambda: fake)

    out = analysis._chat_completion("some/model:free", "PROMPT", 0.3, 99)
    assert out == "hi there"
    assert captured["url"].endswith("/api/v1/chat/completions")
    assert captured["body"]["model"] == "some/model:free"
    assert captured["body"]["messages"] == [{"role": "user", "content": "PROMPT"}]
    assert captured["body"]["temperature"] == 0.3
    assert captured["body"]["max_tokens"] == 99


def test_chat_completion_raises_on_http_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    fake = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429, json={"error": "rate limited"})
        ),
        base_url="https://openrouter.ai/api/v1",
    )
    monkeypatch.setattr(analysis, "_http_client", lambda: fake)

    try:
        analysis._chat_completion("some/model:free", "PROMPT", 0.3, 99)
        assert False, "expected an exception on HTTP 429"
    except httpx.HTTPStatusError:
        pass


def test_cover_letter_without_key_is_real_text(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    letter = analysis.generate_cover_letter(
        "Python developer with Django and AWS experience.",
        "Hiring a Python developer with Django and AWS.",
    )
    assert isinstance(letter, str)
    assert len(letter) > 100
    assert "Hiring Manager" in letter
    assert "Python" in letter or "Django" in letter
