"""Tests for the analysis orchestration layer (AI with local fallback).

Covers provider selection (OpenRouter / OpenAI / local), robust JSON parsing
of model output, and graceful fallback to the local engine.
"""
from types import SimpleNamespace

import utils.analysis as analysis


def _fake_response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


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
    # A fallback chain of free models.
    assert isinstance(cfg["models"], list) and cfg["models"]
    assert any(":free" in m for m in cfg["models"])


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


def test_analyze_with_ai_falls_through_to_next_model(monkeypatch):
    """A rate-limited / failing model is skipped; the next one is tried."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENAI_MODEL", "bad/one:free,good/two:free")
    calls = []

    good_json = (
        '{"score": 88, "summary": "Great fit.", '
        '"matching_skills": ["Python"], "missing_skills": [], '
        '"suggestions": ["Tighten the summary."]}'
    )

    class FakeCompletions:
        def create(self, model, **kwargs):
            calls.append(model)
            if model.startswith("bad"):
                raise RuntimeError("429 rate limited")
            return _fake_response(good_json)

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr(analysis, "_client", lambda: fake_client)

    local = analysis.analyze_match("Python", "Python")
    result = analysis._analyze_with_ai("Python", "Python developer", local)

    assert result["score"] == 88
    assert "bad/one:free" in calls
    assert calls[-1] == "good/two:free"


def test_analyze_with_ai_raises_when_all_models_fail(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENAI_MODEL", "a:free,b:free")

    class FakeCompletions:
        def create(self, model, **kwargs):
            raise RuntimeError("429")

    monkeypatch.setattr(
        analysis, "_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )
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
