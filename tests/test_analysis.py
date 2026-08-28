"""Tests for the analysis orchestration layer (AI with local fallback).

Covers provider selection (OpenRouter / OpenAI / local), robust JSON parsing
of model output, and graceful fallback to the local engine.
"""
import json
import logging

import httpx
import pytest

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


# --------------------------------------------------------------------------- #
# ATS CV generation
# --------------------------------------------------------------------------- #
def test_generate_ats_cv_without_key_uses_local(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = analysis.generate_ats_cv(
        "Python developer with Django and AWS experience.",
        "Need a Python developer with Django, AWS and Kubernetes.",
    )
    assert result["source"] == "local"
    assert result["attempts"] == 1
    assert "Python developer with Django and AWS experience." in result["cv_text"]
    assert 0 <= result["ats"]["score"] <= 100


def test_generate_ats_cv_local_adds_skills_section_when_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = analysis.generate_ats_cv(
        "Built services with Python and Django.",
        "Need Python and Django.",
    )
    assert "SKILLS" in result["cv_text"]
    assert "Python" in result["cv_text"]


def test_local_cv_rewrite_never_injects_match_report_verdict(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = analysis.generate_ats_cv(
        "Built services with Python and Django.",
        "Need Python and Django.",
    )
    assert "match" not in result["cv_text"].lower()
    assert "SUMMARY" not in result["cv_text"]


def test_generate_ats_cv_ai_succeeds_first_pass(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    good_cv = (
        "John Doe\njohn.doe@example.com | (555) 123-4567\n\n"
        "SUMMARY\nPython developer with 5 years building Django services on AWS.\n\n"
        "EXPERIENCE\nBackend Engineer, Acme Corp\n"
        "- Reduced API latency by 40% by migrating to Django and AWS Lambda.\n"
        "- Led a team of 3 engineers, shipping 12 releases in 2025.\n\n"
        "EDUCATION\nB.S. Computer Science, State University\n\n"
        "SKILLS\nPython, Django, AWS, Docker, PostgreSQL\n"
    )
    calls = []

    def fake_chat(model, prompt, **kwargs):
        calls.append(prompt)
        return json.dumps({"cv_text": good_cv})

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    result = analysis.generate_ats_cv(
        "Python developer.", "Need a Python developer with Django, AWS and Docker."
    )
    assert result["source"] == "ai"
    assert result["attempts"] == 1
    assert result["ats"]["score"] == 90
    assert len(calls) == 1  # no refinement pass needed


def test_generate_ats_cv_refines_when_first_pass_under_ninety(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    weak_cv = "SKILLS\nPython\n"
    strong_cv = (
        "John Doe\njohn.doe@example.com | (555) 123-4567\n\n"
        "SUMMARY\nPython developer with 5 years building Django services on AWS.\n\n"
        "EXPERIENCE\nBackend Engineer, Acme Corp\n"
        "- Reduced API latency by 40% by migrating to Django and AWS Lambda.\n"
        "- Led a team of 3 engineers, shipping 12 releases in 2025.\n\n"
        "EDUCATION\nB.S. Computer Science, State University\n\n"
        "SKILLS\nPython, Django, AWS, Docker, PostgreSQL\n"
    )
    responses = [json.dumps({"cv_text": weak_cv}), json.dumps({"cv_text": strong_cv})]
    calls = []

    def fake_chat(model, prompt, **kwargs):
        calls.append(prompt)
        return responses[len(calls) - 1]

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    result = analysis.generate_ats_cv(
        "Python developer.", "Need a Python developer with Django, AWS and Docker."
    )
    assert result["source"] == "ai"
    assert result["attempts"] == 2
    assert result["cv_text"] == strong_cv
    assert result["ats"]["score"] == 90
    assert len(calls) == 2
    # the refinement prompt must reference the first attempt's specific gaps
    assert "Django" in calls[1] or "AWS" in calls[1] or "Docker" in calls[1]


def test_generate_ats_cv_keeps_first_draft_when_refinement_scores_lower(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    decent_cv = "SUMMARY\nOK\n\nSKILLS\nPython, Django, AWS\n"
    worse_cv = "SKILLS\nPython\n"
    responses = [json.dumps({"cv_text": decent_cv}), json.dumps({"cv_text": worse_cv})]
    calls = []

    def fake_chat(model, prompt, **kwargs):
        calls.append(prompt)
        return responses[len(calls) - 1]

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    result = analysis.generate_ats_cv(
        "Python developer.", "Need a Python developer with Django, AWS and Docker."
    )
    assert result["attempts"] == 2
    assert result["cv_text"] == decent_cv


def test_generate_ats_cv_refinement_failure_keeps_first_draft(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    weak_cv = "SKILLS\nPython\n"
    calls = []

    def fake_chat(model, prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            return json.dumps({"cv_text": weak_cv})
        raise RuntimeError("429 rate limited")

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    result = analysis.generate_ats_cv(
        "Python developer.", "Need a Python developer with Django, AWS and Docker."
    )
    assert result["source"] == "ai"
    assert result["attempts"] == 2
    assert result["cv_text"] == weak_cv


def test_generate_ats_cv_falls_back_to_local_when_ai_fails_outright(monkeypatch, caplog):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(analysis, "_chat_completion", boom)
    with caplog.at_level(logging.WARNING, logger="utils.analysis"):
        result = analysis.generate_ats_cv(
            "Python developer.", "Need a Python developer with Django."
        )
    assert result["source"] == "local"
    assert result["attempts"] == 1
    assert any("network down" in r.getMessage() for r in caplog.records)


def test_generate_ats_cv_prompt_states_no_fabrication_guardrail(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    captured = {}

    def fake_chat(model, prompt, **kwargs):
        captured["prompt"] = prompt
        return json.dumps({"cv_text": "SUMMARY\nOK\n"})

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    analysis.generate_ats_cv("Python developer.", "Need Python.")
    assert "invent" in captured["prompt"].lower() or "fabricat" in captured["prompt"].lower()


def test_gemini_chat_completion_posts_payload_and_parses_text(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "  hi from gemini  "}]}}]},
        )

    fake = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://generativelanguage.googleapis.com/v1beta",
    )
    monkeypatch.setattr(analysis, "_gemini_client", lambda: fake)

    out = analysis._gemini_chat_completion("PROMPT", max_tokens=500)
    assert out == "hi from gemini"
    assert captured["url"].endswith("/models/gemini-flash-lite-latest:generateContent")
    assert captured["headers"]["x-goog-api-key"] == "gem-key"
    assert captured["body"]["contents"] == [{"parts": [{"text": "PROMPT"}]}]
    assert captured["body"]["generationConfig"]["maxOutputTokens"] == 500


def test_cv_with_ai_falls_back_to_gemini_when_openrouter_fails(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")

    def boom(model, prompt, **kwargs):
        raise RuntimeError("openrouter down")

    def fake_gemini(prompt, max_tokens):
        return json.dumps({"cv_text": "SUMMARY\nFrom Gemini.\n"})

    monkeypatch.setattr(analysis, "_chat_completion", boom)
    monkeypatch.setattr(analysis, "_gemini_chat_completion", fake_gemini)

    cv_text = analysis._cv_with_ai("Python developer.", "Need Python.")
    assert cv_text == "SUMMARY\nFrom Gemini.\n"


def test_generate_ats_cv_falls_back_to_local_when_ai_and_gemini_both_fail(monkeypatch, caplog):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")

    def boom(*args, **kwargs):
        raise RuntimeError("all providers down")

    monkeypatch.setattr(analysis, "_chat_completion", boom)
    monkeypatch.setattr(analysis, "_gemini_chat_completion", boom)

    with caplog.at_level(logging.WARNING, logger="utils.analysis"):
        result = analysis.generate_ats_cv(
            "Python developer.", "Need a Python developer with Django."
        )
    assert result["source"] == "local"
    assert result["attempts"] == 1


def test_cv_with_ai_skips_gemini_when_key_not_configured(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def boom(model, prompt, **kwargs):
        raise RuntimeError("openrouter down")

    def gemini_should_not_be_called(*args, **kwargs):
        raise AssertionError("Gemini fallback must not run without GEMINI_API_KEY")

    monkeypatch.setattr(analysis, "_chat_completion", boom)
    monkeypatch.setattr(analysis, "_gemini_chat_completion", gemini_should_not_be_called)

    with pytest.raises(RuntimeError, match="openrouter down"):
        analysis._cv_with_ai("Python developer.", "Need Python.")


def test_generate_ats_cv_draft_returns_ai_result_with_attempts_one(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    good_cv = "SUMMARY\nPython developer.\n\nSKILLS\nPython, Django\n"

    def fake_chat(model, prompt, **kwargs):
        return json.dumps({"cv_text": good_cv})

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    result = analysis.generate_ats_cv_draft("Python developer.", "Need Python and Django.")
    assert result["source"] == "ai"
    assert result["attempts"] == 1
    assert result["cv_text"] == good_cv
    assert 0 <= result["ats"]["score"] <= 100


def test_generate_ats_cv_draft_does_not_auto_refine_when_under_ninety(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    weak_cv = "SKILLS\nPython\n"
    calls = []

    def fake_chat(model, prompt, **kwargs):
        calls.append(prompt)
        return json.dumps({"cv_text": weak_cv})

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    result = analysis.generate_ats_cv_draft(
        "Python developer.", "Need a Python developer with Django, AWS and Docker."
    )
    assert result["attempts"] == 1
    assert result["cv_text"] == weak_cv
    assert len(calls) == 1  # draft never triggers a second AI call on its own


def test_generate_ats_cv_draft_without_key_uses_local(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = analysis.generate_ats_cv_draft(
        "Python developer with Django and AWS experience.",
        "Need a Python developer with Django, AWS and Kubernetes.",
    )
    assert result["source"] == "local"
    assert result["attempts"] == 1
    assert "Python developer with Django and AWS experience." in result["cv_text"]


def test_generate_ats_cv_draft_falls_back_to_local_when_ai_fails_outright(monkeypatch, caplog):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(analysis, "_chat_completion", boom)
    with caplog.at_level(logging.WARNING, logger="utils.analysis"):
        result = analysis.generate_ats_cv_draft(
            "Python developer.", "Need a Python developer with Django."
        )
    assert result["source"] == "local"
    assert result["attempts"] == 1
    assert any("network down" in r.getMessage() for r in caplog.records)


def test_refine_ats_cv_returns_refined_when_it_scores_higher(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    weak_cv = "SKILLS\nPython\n"
    strong_cv = (
        "John Doe\njohn.doe@example.com | (555) 123-4567\n\n"
        "SUMMARY\nPython developer with 5 years building Django services on AWS.\n\n"
        "EXPERIENCE\nBackend Engineer, Acme Corp\n"
        "- Reduced API latency by 40% by migrating to Django and AWS Lambda.\n"
        "- Led a team of 3 engineers, shipping 12 releases in 2025.\n\n"
        "EDUCATION\nB.S. Computer Science, State University\n\n"
        "SKILLS\nPython, Django, AWS, Docker, PostgreSQL\n"
    )
    prior_ats = analysis.score_ats(weak_cv, "Need a Python developer with Django, AWS and Docker.")
    calls = []

    def fake_chat(model, prompt, **kwargs):
        calls.append(prompt)
        return json.dumps({"cv_text": strong_cv})

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    result = analysis.refine_ats_cv(
        weak_cv,
        "Python developer.",
        "Need a Python developer with Django, AWS and Docker.",
        prior_ats,
    )
    assert result["source"] == "ai"
    assert result["attempts"] == 2
    assert result["cv_text"] == strong_cv
    assert len(calls) == 1
    # the refine prompt must reference the prior attempt's specific gaps
    assert "Django" in calls[0] or "AWS" in calls[0] or "Docker" in calls[0]


def test_refine_ats_cv_keeps_prior_draft_when_refinement_scores_lower(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    decent_cv = "SUMMARY\nOK\n\nSKILLS\nPython, Django, AWS\n"
    worse_cv = "SKILLS\nPython\n"
    prior_ats = analysis.score_ats(decent_cv, "Need a Python developer with Django, AWS and Docker.")

    def fake_chat(model, prompt, **kwargs):
        return json.dumps({"cv_text": worse_cv})

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    result = analysis.refine_ats_cv(
        decent_cv,
        "Python developer.",
        "Need a Python developer with Django, AWS and Docker.",
        prior_ats,
    )
    assert result["attempts"] == 2
    assert result["cv_text"] == decent_cv
    assert result["ats"] == prior_ats


def test_refine_ats_cv_failure_keeps_prior_draft(monkeypatch, caplog):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    weak_cv = "SKILLS\nPython\n"
    prior_ats = analysis.score_ats(weak_cv, "Need a Python developer with Django.")

    def boom(*args, **kwargs):
        raise RuntimeError("429 rate limited")

    monkeypatch.setattr(analysis, "_chat_completion", boom)
    with caplog.at_level(logging.WARNING, logger="utils.analysis"):
        result = analysis.refine_ats_cv(
            weak_cv, "Python developer.", "Need a Python developer with Django.", prior_ats
        )
    assert result["source"] == "ai"
    assert result["attempts"] == 2
    assert result["cv_text"] == weak_cv
    assert result["ats"] == prior_ats
    assert any("429 rate limited" in r.getMessage() for r in caplog.records)


def test_generate_ats_cv_still_composes_draft_and_refine(monkeypatch):
    """generate_ats_cv's existing external contract must be unaffected by the split."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    weak_cv = "SKILLS\nPython\n"
    strong_cv = (
        "John Doe\njohn.doe@example.com | (555) 123-4567\n\n"
        "SUMMARY\nPython developer with 5 years building Django services on AWS.\n\n"
        "EXPERIENCE\nBackend Engineer, Acme Corp\n"
        "- Reduced API latency by 40% by migrating to Django and AWS Lambda.\n"
        "- Led a team of 3 engineers, shipping 12 releases in 2025.\n\n"
        "EDUCATION\nB.S. Computer Science, State University\n\n"
        "SKILLS\nPython, Django, AWS, Docker, PostgreSQL\n"
    )
    responses = [json.dumps({"cv_text": weak_cv}), json.dumps({"cv_text": strong_cv})]
    calls = []

    def fake_chat(model, prompt, **kwargs):
        calls.append(prompt)
        return responses[len(calls) - 1]

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    result = analysis.generate_ats_cv(
        "Python developer.", "Need a Python developer with Django, AWS and Docker."
    )
    assert result["source"] == "ai"
    assert result["attempts"] == 2
    assert result["cv_text"] == strong_cv
    assert len(calls) == 2
