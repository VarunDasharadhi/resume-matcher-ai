"""Analysis orchestration: use an LLM provider when available, else local.

The providers (OpenRouter or OpenAI) are called over their plain REST
chat-completions API with a pooled httpx client, no provider SDK needed.
Every public function returns the same normalized shape regardless of which
backend produced it, so the rest of the app never has to care whether an API
key is configured.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

import httpx

from utils.matcher import analyze_match, extract_skills

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
# Fallback chain of free OpenRouter models, tried in order. Free models get
# rate-limited (429) intermittently and the catalog changes over time, so we
# try several and finish with the `openrouter/free` auto-router as a catch-all.
# Override with OPENAI_MODEL / LLM_MODEL (comma-separated for a custom chain).
DEFAULT_OPENROUTER_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "openrouter/free",
]


def _parse_models(value: Optional[str]) -> List[str]:
    """Split a comma-separated model override into a clean list."""
    if not value:
        return []
    return [m.strip() for m in value.split(",") if m.strip()]


def _provider_config() -> Optional[Dict]:
    """Resolve which LLM provider to use from the environment.

    OpenRouter is preferred when ``OPENROUTER_API_KEY`` is set; otherwise plain
    OpenAI when ``OPENAI_API_KEY`` is set. Returns ``None`` (=> local engine)
    when neither key is present. ``models`` is a fallback chain tried in order.
    """
    override = _parse_models(os.getenv("OPENAI_MODEL") or os.getenv("LLM_MODEL"))

    or_key = os.getenv("OPENROUTER_API_KEY")
    if or_key:
        return {
            "provider": "openrouter",
            "api_key": or_key,
            "base_url": os.getenv("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL),
            "models": override or list(DEFAULT_OPENROUTER_MODELS),
        }

    oa_key = os.getenv("OPENAI_API_KEY")
    if oa_key:
        return {
            "provider": "openai",
            "api_key": oa_key,
            "base_url": os.getenv("OPENAI_BASE_URL") or None,
            "models": override or [DEFAULT_OPENAI_MODEL],
        }

    return None


_RANGE_DASH = re.compile(r"(?<=\d)\s*[–—]\s*(?=\d)")
_PROSE_DASH = re.compile(r"\s*[—–]\s*")


def _strip_dashes(text: str) -> str:
    """Replace em/en dashes with human punctuation.

    Models often ignore a 'no em dashes' instruction, so we enforce it after
    the fact: number ranges keep a hyphen (2020-2023), everything else becomes
    a comma. This keeps output looking human and consistent.
    """
    if not text:
        return ""
    text = _RANGE_DASH.sub("-", text)
    return _PROSE_DASH.sub(", ", text)


def _clean_result(result: Dict) -> Dict:
    """Strip em/en dashes from all human-readable fields of an analysis."""
    result["summary"] = _strip_dashes(result.get("summary", ""))
    result["suggestions"] = [_strip_dashes(s) for s in result.get("suggestions", [])]
    result["matching_skills"] = [_strip_dashes(s) for s in result.get("matching_skills", [])]
    result["missing_skills"] = [_strip_dashes(s) for s in result.get("missing_skills", [])]
    return result


def ai_available() -> bool:
    """True when any LLM provider (OpenRouter or OpenAI) is configured."""
    return _provider_config() is not None


def provider_label() -> str:
    """Human-readable name of the active engine for UI display."""
    cfg = _provider_config()
    if not cfg:
        return "Local engine"
    return "OpenRouter" if cfg["provider"] == "openrouter" else "OpenAI"


def analyze_resume(resume_text: str, job_description: str) -> Dict:
    """Analyze a resume against a job description.

    Returns a normalized dict: ``score``, ``summary``, ``matching_skills``,
    ``missing_skills``, ``suggestions`` and ``source`` ("ai" | "local").
    """
    local = analyze_match(resume_text, job_description)

    if ai_available():
        try:
            ai = _analyze_with_ai(resume_text, job_description, local)
            ai["source"] = "ai"
            return _clean_result(ai)
        except Exception as exc:
            # Any AI failure (auth, network, quota, bad JSON) -> graceful local.
            logger.warning("AI analysis failed, falling back to local: %s", exc)

    local["summary"] = _local_summary(local)
    local["source"] = "local"
    return _clean_result(local)


def generate_cover_letter(resume_text: str, job_description: str) -> str:
    """Produce a cover letter, via AI when possible, else a local template."""
    if ai_available():
        try:
            return _strip_dashes(_cover_letter_with_ai(resume_text, job_description))
        except Exception as exc:
            logger.warning("AI cover letter failed, falling back to local: %s", exc)
    return _strip_dashes(_cover_letter_local(resume_text, job_description))


# --------------------------------------------------------------------------- #
# AI backend
# --------------------------------------------------------------------------- #
# (config key, client) pair so warm serverless instances reuse the HTTP
# connection pool instead of paying a new TLS handshake on every request.
_client_cache: Optional[Tuple[tuple, httpx.Client]] = None


def _http_client() -> httpx.Client:
    """Build (or reuse) a pooled HTTP client for the configured provider."""
    global _client_cache

    cfg = _provider_config()
    base_url = cfg.get("base_url") or OPENAI_BASE_URL
    cache_key = (cfg["provider"], cfg["api_key"], base_url)
    if _client_cache and _client_cache[0] == cache_key:
        return _client_cache[1]

    headers = {"Authorization": f"Bearer {cfg['api_key']}"}
    if cfg["provider"] == "openrouter":
        # Optional but recommended attribution headers for OpenRouter.
        headers["HTTP-Referer"] = os.getenv(
            "APP_URL", "https://github.com/VarunDasharadhi/resume-matcher-ai"
        )
        headers["X-Title"] = "AI Resume Matcher"
    # No retries/backoff: fail fast so we move to the next model in the chain
    # quickly instead of hanging on a rate-limited one.
    client = httpx.Client(base_url=base_url, headers=headers, timeout=30.0)
    _client_cache = (cache_key, client)
    return client


def _chat_completion(model: str, prompt: str, temperature: float, max_tokens: int) -> str:
    """POST one chat completion and return the message text.

    Raises on HTTP errors or a malformed response body, so callers can move
    on to the next model in the chain.
    """
    response = _http_client().post(
        "chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
    )
    response.raise_for_status()
    data = response.json()
    return (data["choices"][0]["message"]["content"] or "").strip()


def _extract_json(text: str) -> Dict:
    """Parse a JSON object out of a model response.

    Free models often wrap JSON in ``` fences or surround it with prose, so we
    locate the outermost ``{...}`` and parse that.
    """
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def _analyze_with_ai(resume_text: str, job_description: str, local: Dict) -> Dict:
    """Ask the model for a structured JSON analysis and normalize it.

    Tries each model in the configured chain until one returns parseable JSON;
    raises the last error if all fail (caller falls back to the local engine).
    """
    models = _provider_config()["models"]
    prompt = f"""You are an expert technical recruiter and resume coach.
Compare the RESUME against the JOB DESCRIPTION and respond with STRICT JSON
matching this schema (no markdown, no commentary, JSON only):

{{
  "score": <integer 0-100, how well the resume matches the job>,
  "summary": "<2-3 sentence verdict on the candidate's fit>",
  "matching_skills": ["skills present in BOTH resume and job"],
  "missing_skills": ["important skills the job wants but the resume lacks"],
  "suggestions": ["4-6 specific, actionable resume improvements for THIS job"]
}}

Write the summary and suggestions in a natural, human voice: plain, direct
language, like a helpful colleague. Do not use em dashes; use commas, periods,
or parentheses instead. Avoid buzzwords and stiff corporate phrasing.

RESUME:
{resume_text[:8000]}

JOB DESCRIPTION:
{job_description[:4000]}
"""
    last_error: Optional[Exception] = None
    for model in models:
        try:
            content = _chat_completion(model, prompt, temperature=0.3, max_tokens=900)
            data = _extract_json(content)
            return _normalize_ai(data, local)
        except Exception as exc:  # rate-limit, 404, bad JSON, etc. -> next model
            logger.info("model %s failed, trying next: %s", model, exc)
            last_error = exc
    raise last_error if last_error else RuntimeError("no models configured")


def _normalize_ai(data: Dict, local: Dict) -> Dict:
    """Coerce the model's JSON into our canonical shape, with safe fallbacks."""
    def as_list(value) -> List[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    try:
        score = int(round(float(data.get("score", local["score"]))))
    except (TypeError, ValueError):
        score = local["score"]
    score = max(0, min(100, score))

    return {
        "score": score,
        "summary": str(data.get("summary") or _local_summary(local)).strip(),
        "matching_skills": as_list(data.get("matching_skills")) or local["matching_skills"],
        "missing_skills": as_list(data.get("missing_skills")) or local["missing_skills"],
        "suggestions": as_list(data.get("suggestions")) or local["suggestions"],
    }


def _cover_letter_with_ai(resume_text: str, job_description: str) -> str:
    models = _provider_config()["models"]
    prompt = f"""Write a professional, tailored cover letter.

RESUME:
{resume_text[:8000]}

JOB DESCRIPTION:
{job_description[:4000]}

Requirements:
- Address it to 'Hiring Manager'
- Open with a real hook, not a generic greeting line
- Weave in 3-4 concrete, relevant skills or achievements from the resume
- Sound like a real person: warm, confident, and natural, not stiff or corporate
- Use plain punctuation. Do not use em dashes; use commas or periods instead
- Avoid buzzwords and cliches (no 'synergy', 'leverage', 'I am writing to express')
- 200-280 words, ready to send (no placeholders like [Your Name] beyond a sign-off)
"""
    last_error: Optional[Exception] = None
    for model in models:
        try:
            text = _chat_completion(model, prompt, temperature=0.5, max_tokens=600)
            if text:
                return text
        except Exception as exc:
            logger.info("model %s failed, trying next: %s", model, exc)
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("empty response from all models")


# --------------------------------------------------------------------------- #
# Local backend
# --------------------------------------------------------------------------- #
def _local_summary(local: Dict) -> str:
    score = local["score"]
    n_match = len(local["matching_skills"])
    n_miss = len(local["missing_skills"])
    if score >= 80:
        verdict = "Strong match"
    elif score >= 50:
        verdict = "Moderate match"
    else:
        verdict = "Limited match"
    return (
        f"{verdict}. The resume covers {n_match} of the "
        f"{n_match + n_miss} key skills this role calls for, "
        f"for an overall match of {score}%."
    )


def _cover_letter_local(resume_text: str, job_description: str) -> str:
    """A genuinely usable template cover letter built from matched skills."""
    result = analyze_match(resume_text, job_description)
    matched = result["matching_skills"]
    job_skills = extract_skills(job_description)

    if matched:
        skills_phrase = _join_human(matched[:4])
        strength_line = (
            f"My background maps directly to what you're looking for, with "
            f"hands-on experience in {skills_phrase}."
        )
    elif job_skills:
        skills_phrase = _join_human(job_skills[:3])
        strength_line = (
            f"I'm eager to bring my experience to bear on the {skills_phrase} "
            f"work this role centers on."
        )
    else:
        strength_line = (
            "I'm confident my experience aligns well with the goals of this role."
        )

    return (
        "Dear Hiring Manager,\n\n"
        "This role caught my eye, and after reading through it I think I'd be a "
        "good fit. The work lines up closely with what I do and what I want to "
        "do next.\n\n"
        f"{strength_line} Across my career I've focused on shipping work that "
        "actually moves the needle, working well with the people around me, and "
        "getting better at my craft as I go. I like solving real problems and "
        "owning the results.\n\n"
        "I'd love to talk about how I can help your team. Thanks for taking the "
        "time to read this, and I hope we get the chance to speak soon.\n\n"
        "Best regards,\n"
        "[Your Name]"
    )


def _join_human(items: List[str]) -> str:
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"
