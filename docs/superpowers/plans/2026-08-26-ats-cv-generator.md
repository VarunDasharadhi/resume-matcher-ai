# ATS-Optimized CV Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CV generator that rewrites the user's already-submitted resume tailored to the job description, scores it with a dedicated ATS scorer, auto-refines once via AI toward 90+/100, and lets the user edit the result and download it as a PDF.

**Architecture:** Three new/extended modules following existing patterns: `utils/ats_scorer.py` (new, pure scoring), `utils/analysis.py` (extended with an AI-with-local-fallback `generate_ats_cv`), `utils/pdf_exporter.py` (extended with `export_cv_to_pdf`). Wired into `app.py` via three new routes and a new `templates/cv.html`, following the app's existing stateless, carry-state-via-POST-form pattern (no DB, no session).

**Tech Stack:** Python 3, Flask, ReportLab (Platypus), httpx (existing AI client), pytest + monkeypatch (existing test stack). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-26-ats-cv-generator-design.md`

## Global Constraints

- No new dependencies; reuse `matcher.extract_skills`, `analysis._chat_completion`/`_extract_json`/model-chain machinery, and `pdf_exporter`'s ReportLab styles/patterns.
- Fully stateless: no database, no server-side session. All state travels via POST form fields, exactly like the existing `/analyze` → `/result` → `/cover-letter` flow.
- PDF is the only download format.
- AI guardrail (must appear in every AI prompt used for CV generation): never invent employers, job titles, dates, degrees, or skills not evidenced in the source resume. Reordering, rephrasing, plausible quantification, and JD-terminology substitution for an existing synonym are allowed; fabrication is not.
- House style for all AI-generated text: no em dashes (use `_strip_dashes`, already in `utils/analysis.py`), plain human language, no buzzwords.
- AI CV generation is capped at 2 attempts total (1 initial pass + at most 1 refinement pass) to stay within serverless timeout budgets.
- `utils/ats_scorer.py` must be pure and deterministic: no AI calls, no I/O, safe on empty-string input.

---

### Task 1: ATS scorer

**Files:**
- Create: `utils/ats_scorer.py`
- Test: `tests/test_ats_scorer.py`

**Interfaces:**
- Produces:
  - `score_ats(cv_text: str, job_description: str) -> dict` returning
    `{"score": int, "coverage": {"score": int, "matching_skills": list[str], "missing_skills": list[str]}, "sections": {"score": int, "found": list[str], "missing": list[str]}, "contact_info": {"score": int, "has_email": bool, "has_phone": bool}, "quantified_achievements": {"score": int, "count": int}, "keyword_placement": {"score": int, "top_skills_in_lead": list[str]}}`.
  - `is_section_header(line: str) -> bool` — true when a single line, stripped, is exactly one of the standard resume section headers.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ats_scorer.py`:

```python
"""Tests for the ATS-readiness scorer (deterministic, no AI)."""
from utils.ats_scorer import is_section_header, score_ats

SAMPLE_JD = "Need a Python developer with Django, AWS and Docker."

SAMPLE_CV = """John Doe
john.doe@example.com | (555) 123-4567

SUMMARY
Python developer with 5 years building Django services on AWS.

EXPERIENCE
Backend Engineer, Acme Corp
- Reduced API latency by 40% by migrating to Django and AWS Lambda.
- Led a team of 3 engineers, shipping 12 releases in 2025.

EDUCATION
B.S. Computer Science, State University

SKILLS
Python, Django, AWS, Docker, PostgreSQL
"""


def test_score_ats_strong_cv_clears_ninety():
    result = score_ats(SAMPLE_CV, SAMPLE_JD)
    assert result["score"] == 90
    assert result["coverage"] == {
        "score": 50,
        "matching_skills": ["Python", "Django", "AWS", "Docker"],
        "missing_skills": [],
    }
    assert result["sections"]["score"] == 20
    assert set(result["sections"]["found"]) == {"Summary", "Experience", "Education", "Skills"}
    assert result["contact_info"] == {"score": 10, "has_email": True, "has_phone": True}


def test_coverage_scores_partial_overlap():
    result = score_ats("SKILLS\nPython\n", SAMPLE_JD)
    assert result["coverage"] == {
        "score": 12,
        "matching_skills": ["Python"],
        "missing_skills": ["Django", "AWS", "Docker"],
    }


def test_coverage_defaults_to_25_when_jd_has_no_recognized_skills():
    result = score_ats("Some CV text", "We need a hard worker who is a great fit for our culture.")
    assert result["coverage"] == {"score": 25, "matching_skills": [], "missing_skills": []}


def test_sections_scores_five_points_each_found():
    result = score_ats("SUMMARY\nHello\n\nEXPERIENCE\nDid stuff\n", SAMPLE_JD)
    assert result["sections"]["score"] == 10
    assert set(result["sections"]["found"]) == {"Summary", "Experience"}
    assert set(result["sections"]["missing"]) == {"Education", "Skills"}


def test_contact_info_detects_email_and_phone_independently():
    email_only = score_ats("jane@example.com", "")
    assert email_only["contact_info"] == {"score": 5, "has_email": True, "has_phone": False}

    phone_only = score_ats("Call me at (555) 123-4567", "")
    assert phone_only["contact_info"] == {"score": 5, "has_email": False, "has_phone": True}


def test_quantified_achievements_counts_lines_with_metrics_capped_at_ten():
    cv = "\n".join(f"- Shipped {n} features" for n in range(1, 10))  # 9 lines
    result = score_ats(cv, "")
    assert result["quantified_achievements"] == {"score": 10, "count": 9}


def test_quantified_achievements_ignores_section_header_lines():
    result = score_ats("SKILLS\nPython\n", "")
    assert result["quantified_achievements"] == {"score": 0, "count": 0}


def test_keyword_placement_rewards_top_skills_appearing_early():
    cv = "Python Django AWS Docker expert.\n" + ("filler " * 200)
    result = score_ats(cv, SAMPLE_JD)
    assert result["keyword_placement"] == {
        "score": 10,
        "top_skills_in_lead": ["Python", "Django", "AWS", "Docker"],
    }


def test_keyword_placement_zero_when_top_skills_are_late():
    cv = ("filler " * 200) + "\nPython Django AWS Docker expert."
    result = score_ats(cv, SAMPLE_JD)
    assert result["keyword_placement"] == {"score": 0, "top_skills_in_lead": []}


def test_keyword_placement_zero_when_jd_has_no_recognized_skills():
    result = score_ats("Some CV", "We need a hard worker.")
    assert result["keyword_placement"] == {"score": 0, "top_skills_in_lead": []}


def test_score_ats_empty_inputs_do_not_error():
    result = score_ats("", "")
    assert result["score"] == 25
    assert result["sections"]["score"] == 0
    assert result["contact_info"] == {"score": 0, "has_email": False, "has_phone": False}


def test_is_section_header_matches_standard_headers():
    assert is_section_header("SUMMARY")
    assert is_section_header("  Skills  ")
    assert is_section_header("Work Experience")


def test_is_section_header_rejects_non_header_lines():
    assert not is_section_header("SUMMARY:")
    assert not is_section_header("Python, Django, AWS")
    assert not is_section_header("")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ats_scorer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'utils.ats_scorer'`

- [ ] **Step 3: Implement `utils/ats_scorer.py`**

```python
"""ATS (Applicant Tracking System) readiness scoring for a generated CV.

Distinct from utils.matcher's coarse resume<->job match score, this module
scores a *generated CV's* likelihood of clearing an ATS keyword/format
screen: keyword coverage, standard section headers, contact info,
quantified achievements, and where the job's top keywords land in the
document. Pure and deterministic, no AI involved.
"""
from __future__ import annotations

import re
from typing import Dict

from utils.matcher import extract_skills

_SECTION_PATTERNS: Dict[str, re.Pattern] = {
    "Summary": re.compile(
        r"^\s*(summary|profile|professional summary)\s*$", re.IGNORECASE | re.MULTILINE
    ),
    "Experience": re.compile(
        r"^\s*(experience|work experience|professional experience|employment history)\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "Education": re.compile(r"^\s*education\s*$", re.IGNORECASE | re.MULTILINE),
    "Skills": re.compile(
        r"^\s*(skills|technical skills|core skills)\s*$", re.IGNORECASE | re.MULTILINE
    ),
}

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
_METRIC_RE = re.compile(r"\d|%|\$")


def is_section_header(line: str) -> bool:
    """True when ``line``, stripped, is exactly one standard resume header.

    Used by ``pdf_exporter`` to give section headers their own paragraph
    style when rendering a generated CV to PDF.
    """
    stripped = line.strip()
    if not stripped:
        return False
    return any(pattern.match(stripped) for pattern in _SECTION_PATTERNS.values())


def _score_coverage(cv_text: str, job_description: str) -> Dict:
    job_skills = extract_skills(job_description)
    cv_skills = set(extract_skills(cv_text))
    matching = [s for s in job_skills if s in cv_skills]
    missing = [s for s in job_skills if s not in cv_skills]
    required = len(job_skills)
    score = round(50 * len(matching) / required) if required else 25
    return {"score": score, "matching_skills": matching, "missing_skills": missing}


def _score_sections(cv_text: str) -> Dict:
    found = [name for name, pattern in _SECTION_PATTERNS.items() if pattern.search(cv_text)]
    missing = [name for name in _SECTION_PATTERNS if name not in found]
    return {"score": len(found) * 5, "found": found, "missing": missing}


def _score_contact_info(cv_text: str) -> Dict:
    has_email = bool(_EMAIL_RE.search(cv_text))
    has_phone = bool(_PHONE_RE.search(cv_text))
    score = (5 if has_email else 0) + (5 if has_phone else 0)
    return {"score": score, "has_email": has_email, "has_phone": has_phone}


def _score_quantified_achievements(cv_text: str) -> Dict:
    lines = [ln for ln in cv_text.splitlines() if ln.strip()]
    count = sum(1 for ln in lines if not is_section_header(ln) and _METRIC_RE.search(ln))
    return {"score": min(10, count * 2), "count": count}


def _score_keyword_placement(cv_text: str, job_description: str) -> Dict:
    job_skills = extract_skills(job_description)[:5]
    if not job_skills:
        return {"score": 0, "top_skills_in_lead": []}
    lead_len = max(1, round(len(cv_text) * 0.2))
    lead_skills = set(extract_skills(cv_text[:lead_len]))
    found = [s for s in job_skills if s in lead_skills]
    score = round(10 * len(found) / len(job_skills))
    return {"score": score, "top_skills_in_lead": found}


def score_ats(cv_text: str, job_description: str) -> Dict:
    """Score a generated CV's ATS-readiness against a job description.

    Returns an overall 0-100 ``score`` plus a breakdown: ``coverage``
    (0-50), ``sections`` (0-20), ``contact_info`` (0-10),
    ``quantified_achievements`` (0-10), ``keyword_placement`` (0-10).
    """
    cv_text = cv_text or ""
    job_description = job_description or ""

    coverage = _score_coverage(cv_text, job_description)
    sections = _score_sections(cv_text)
    contact_info = _score_contact_info(cv_text)
    quantified = _score_quantified_achievements(cv_text)
    placement = _score_keyword_placement(cv_text, job_description)

    total = (
        coverage["score"] + sections["score"] + contact_info["score"]
        + quantified["score"] + placement["score"]
    )

    return {
        "score": max(0, min(100, total)),
        "coverage": coverage,
        "sections": sections,
        "contact_info": contact_info,
        "quantified_achievements": quantified,
        "keyword_placement": placement,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ats_scorer.py -v`
Expected: PASS (all 13 tests)

- [ ] **Step 5: Commit**

```bash
git add utils/ats_scorer.py tests/test_ats_scorer.py
git commit -m "Add dedicated ATS-readiness scorer for generated CVs"
```

---

### Task 2: CV generation orchestration (AI with local fallback)

**Files:**
- Modify: `utils/analysis.py`
- Test: `tests/test_analysis.py` (append)

**Interfaces:**
- Consumes: `ats_scorer.score_ats(cv_text: str, job_description: str) -> dict` (Task 1); existing `analysis._chat_completion`, `analysis._extract_json`, `analysis._provider_config`, `analysis.ai_available`, `analysis._strip_dashes`, `matcher.analyze_match`.
- Produces: `analysis.generate_ats_cv(resume_text: str, job_description: str) -> dict` returning `{"cv_text": str, "ats": dict, "source": "ai" | "local", "attempts": int}`. `attempts` is the number of AI generation calls issued (1 or 2) on the AI path, always 1 on the local path.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analysis.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_analysis.py -k generate_ats_cv -v`
Expected: FAIL with `AttributeError: module 'utils.analysis' has no attribute 'generate_ats_cv'`

- [ ] **Step 3: Implement `generate_ats_cv` in `utils/analysis.py`**

Add this import near the top of `utils/analysis.py`, alongside the existing `from utils.matcher import analyze_match, extract_skills` line:

```python
from utils.ats_scorer import score_ats
```

Add these functions after `generate_cover_letter` (which ends around line 143):

```python
def generate_ats_cv(resume_text: str, job_description: str) -> Dict:
    """Generate a tailored, ATS-optimized CV for a job description.

    AI path (when configured): one pass, scored; if under 90, one
    refinement pass fed the specific gaps from the first score, keeping
    whichever attempt scored higher. Any AI failure before a usable first
    draft exists falls back to the local rewrite; a refinement failure
    keeps the first draft. Local path (no AI key): a single deterministic
    pass via ``_local_cv_rewrite``.
    """
    if ai_available():
        try:
            first_text = _cv_with_ai(resume_text, job_description)
        except Exception as exc:
            logger.warning("AI CV generation failed, falling back to local: %s", exc)
        else:
            first_ats = score_ats(first_text, job_description)
            if first_ats["score"] >= 90:
                return {"cv_text": first_text, "ats": first_ats, "source": "ai", "attempts": 1}
            try:
                second_text = _cv_with_ai(resume_text, job_description, prior_ats=first_ats)
                second_ats = score_ats(second_text, job_description)
            except Exception as exc:
                logger.warning("AI CV refinement failed, keeping first draft: %s", exc)
                return {"cv_text": first_text, "ats": first_ats, "source": "ai", "attempts": 2}
            if second_ats["score"] >= first_ats["score"]:
                return {"cv_text": second_text, "ats": second_ats, "source": "ai", "attempts": 2}
            return {"cv_text": first_text, "ats": first_ats, "source": "ai", "attempts": 2}

    local_text = _local_cv_rewrite(resume_text, job_description)
    local_ats = score_ats(local_text, job_description)
    return {"cv_text": local_text, "ats": local_ats, "source": "local", "attempts": 1}


def _cv_with_ai(
    resume_text: str, job_description: str, prior_ats: Optional[Dict] = None
) -> str:
    models = _provider_config()["models"]
    prompt = _cv_prompt(resume_text, job_description, prior_ats)
    last_error: Optional[Exception] = None
    for model in models:
        try:
            content = _chat_completion(model, prompt, temperature=0.4, max_tokens=1200)
            data = _extract_json(content)
            cv_text = str(data.get("cv_text") or "").strip()
            if cv_text:
                return _strip_dashes(cv_text)
        except Exception as exc:
            logger.info("model %s failed, trying next: %s", model, exc)
            last_error = exc
    raise last_error if last_error else RuntimeError("empty response from all models")


def _cv_prompt(resume_text: str, job_description: str, prior_ats: Optional[Dict]) -> str:
    base = f"""You are an expert resume writer helping a candidate tailor their CV to
a specific job description for an Applicant Tracking System (ATS) screen.

Rewrite the RESUME below as a complete, ready-to-use CV tailored to the JOB
DESCRIPTION. Respond with STRICT JSON matching this schema (no markdown, no
commentary, JSON only):

{{
  "cv_text": "<the full rewritten CV as plain text>"
}}

Formatting requirements for cv_text:
- Use standard section headers, each on its own line: SUMMARY, EXPERIENCE,
  EDUCATION, SKILLS (plus others like PROJECTS if the resume supports them).
- Keep the candidate's real name, contact details (email/phone if present),
  employers, job titles, dates, and degrees exactly as given; never invent
  or alter them.
- Do not invent or fabricate skills, employers, achievements, or
  qualifications not evidenced in the source resume. You may reorder,
  rephrase, tighten wording, and quantify existing achievements only where
  plausible from the source. You may restate a skill using the job
  description's exact terminology only when it is a synonym for something
  already in the resume (for example the resume says "JS" and the job
  wants "JavaScript").
- Where the resume supports it, add numbers to achievements (%, counts,
  time saved) to make impact concrete.
- Weave in the job description's key terms naturally into the SUMMARY and
  SKILLS sections, and near the top of relevant EXPERIENCE bullets.

Write in a natural, human voice: plain, direct language. Do not use em
dashes; use commas or periods instead. Avoid buzzwords and stiff corporate
phrasing.

RESUME:
{resume_text[:8000]}

JOB DESCRIPTION:
{job_description[:4000]}
"""
    if not prior_ats:
        return base
    return base + f"""
Your previous attempt scored {prior_ats['score']}/100 on an ATS check. Fix
these specific gaps without losing what already worked:
{_describe_gaps(prior_ats)}
"""


def _describe_gaps(ats: Dict) -> str:
    lines: List[str] = []
    missing_skills = ats["coverage"]["missing_skills"]
    if missing_skills:
        lines.append(
            "- Missing keywords the job asks for: "
            f"{', '.join(missing_skills)}. Only include ones truthfully "
            "supported by the resume."
        )
    missing_sections = ats["sections"]["missing"]
    if missing_sections:
        lines.append(f"- Missing standard section headers: {', '.join(missing_sections)}.")
    if not ats["contact_info"]["has_email"]:
        lines.append(
            "- No email address found; keep the candidate's email from the "
            "source resume visible near the top."
        )
    if not ats["contact_info"]["has_phone"]:
        lines.append(
            "- No phone number found; keep the candidate's phone number "
            "from the source resume visible near the top."
        )
    if ats["quantified_achievements"]["count"] < 3:
        lines.append(
            "- Too few quantified achievements. Add numbers to more "
            "bullets where plausible from the source."
        )
    if ats["keyword_placement"]["score"] < 10:
        lines.append(
            "- The job's top skills should appear earlier, in the SUMMARY "
            "or near the top of SKILLS/EXPERIENCE."
        )
    return "\n".join(lines) if lines else "- Tighten wording and strengthen keyword usage throughout."


def _local_cv_rewrite(resume_text: str, job_description: str) -> str:
    """Deterministic, no-AI CV rewrite.

    Never invents content: only surfaces skills already present in the
    resume (via ``analyze_match``) into a SKILLS section when one isn't
    already there, and adds a factual SUMMARY when one is missing. The
    rest of the resume text is left unchanged.
    """
    resume_text = resume_text or ""
    found = set(score_ats(resume_text, job_description)["sections"]["found"])

    prefix_parts: List[str] = []
    if "Skills" not in found:
        matched = analyze_match(resume_text, job_description)["matching_skills"]
        if matched:
            prefix_parts.append("SKILLS\n" + ", ".join(matched))
    if "Summary" not in found:
        prefix_parts.append("SUMMARY\n" + _local_summary(analyze_match(resume_text, job_description)))

    if not prefix_parts:
        return resume_text
    return "\n\n".join(prefix_parts) + "\n\n" + resume_text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analysis.py -v`
Expected: PASS (all tests, including the new `generate_ats_cv` ones)

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest -v`
Expected: PASS (no regressions in existing tests)

- [ ] **Step 6: Commit**

```bash
git add utils/analysis.py tests/test_analysis.py
git commit -m "Add AI-with-local-fallback ATS CV generation to analysis.py"
```

---

### Task 3: CV PDF export

**Files:**
- Modify: `utils/pdf_exporter.py`
- Test: `tests/test_pdf_exporter.py` (new)

**Interfaces:**
- Consumes: `ats_scorer.is_section_header(line: str) -> bool` (Task 1).
- Produces: `pdf_exporter.export_cv_to_pdf(cv_text: str) -> bytes`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pdf_exporter.py`:

```python
"""Tests for CV PDF export."""
from utils.pdf_exporter import export_cv_to_pdf


def test_export_cv_to_pdf_returns_pdf_bytes():
    pdf = export_cv_to_pdf(
        "SUMMARY\nExperienced engineer.\n\nSKILLS\nPython, Django, AWS"
    )
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 500


def test_export_cv_to_pdf_handles_empty_text():
    pdf = export_cv_to_pdf("")
    assert pdf[:5] == b"%PDF-"


def test_export_cv_to_pdf_handles_headers_without_blank_line_separator():
    pdf = export_cv_to_pdf("SUMMARY\nA capable engineer.\nSKILLS\nPython")
    assert pdf[:5] == b"%PDF-"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pdf_exporter.py -v`
Expected: FAIL with `ImportError: cannot import name 'export_cv_to_pdf' from 'utils.pdf_exporter'`

- [ ] **Step 3: Implement `export_cv_to_pdf` in `utils/pdf_exporter.py`**

Add this import near the top of `utils/pdf_exporter.py`, alongside the existing imports:

```python
from utils.ats_scorer import is_section_header
```

Add this function at the end of `utils/pdf_exporter.py`, after `export_cover_letter_to_pdf`:

```python
def export_cv_to_pdf(cv_text: str) -> bytes:
    """Render a tailored CV to a styled PDF, returned as bytes.

    Section header lines (SUMMARY, EXPERIENCE, EDUCATION, SKILLS, ...) get
    the ``h2`` style so the PDF keeps basic visual structure; everything
    else is grouped into body paragraphs, split on blank lines.
    """
    buffer = BytesIO()
    styles = _styles()
    story = [
        Paragraph("Tailored CV", styles["title"]),
        Paragraph("Generated by AI Resume Matcher", styles["subtitle"]),
        HRFlowable(width="100%", color=LINE, thickness=1, spaceAfter=12),
    ]

    cv_style = ParagraphStyle(
        "cv_body", parent=styles["body"], fontSize=10.5, leading=15, spaceAfter=8,
    )

    def flush(buf: List[str]) -> None:
        text = "\n".join(buf).strip()
        if text:
            story.append(Paragraph(_esc(text), cv_style))
        buf.clear()

    para_buf: List[str] = []
    for line in str(cv_text).splitlines():
        if is_section_header(line):
            flush(para_buf)
            story.append(Paragraph(_esc(line.strip().upper()), styles["h2"]))
        elif not line.strip():
            flush(para_buf)
        else:
            para_buf.append(line)
    flush(para_buf)

    _doc(buffer).build(story)
    return buffer.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pdf_exporter.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add utils/pdf_exporter.py tests/test_pdf_exporter.py
git commit -m "Add CV PDF export with section-aware styling"
```

---

### Task 4: Routes, templates, and CSS

**Files:**
- Modify: `app.py`
- Modify: `templates/result.html`
- Create: `templates/cv.html`
- Modify: `static/style.css`
- Test: `tests/test_app.py` (append)

**Interfaces:**
- Consumes: `analysis.generate_ats_cv` (Task 2), `ats_scorer.score_ats` (Task 1), `pdf_exporter.export_cv_to_pdf` (Task 3).
- Produces: routes `POST /cv` (endpoint `cv_generator`), `POST /cv/rescore` (endpoint `cv_rescore`), `POST /download/cv` (endpoint `download_cv`); template `cv.html`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py`:

```python
def test_result_page_shows_generate_cv_button(client):
    pdf = _pdf_bytes("Python developer with Django, Flask, AWS, Git and PostgreSQL")
    data = {
        "job_description": "Need Python, Django, AWS, Docker and Kubernetes",
        "resume": (BytesIO(pdf), "resume.pdf"),
    }
    resp = client.post("/analyze", data=data, content_type="multipart/form-data")
    assert b"Generate ATS CV" in resp.data


def test_cv_generator_local_engine_renders(client):
    resp = client.post("/cv", data={
        "resume_text": "Python developer with Django, AWS, Docker and Git experience.",
        "job_description": "Need a Python developer with Django, AWS and Docker.",
    })
    assert resp.status_code == 200
    assert b"Tailored CV" in resp.data
    assert b"Re-check ATS score" in resp.data
    assert b'name="cv_text"' in resp.data


def test_cv_generator_missing_fields_redirects(client):
    resp = client.post("/cv", data={"resume_text": "", "job_description": ""})
    assert resp.status_code == 302


def test_cv_rescore_preserves_edited_text_and_rescoring(client):
    resp = client.post("/cv/rescore", data={
        "cv_text": "MY CUSTOM EDIT\n\nSKILLS\nPython, Django, AWS, Docker",
        "job_description": "Need a Python developer with Django, AWS and Docker.",
        "resume_text": "Python developer with Django, AWS and Docker experience.",
    })
    assert resp.status_code == 200
    assert b"MY CUSTOM EDIT" in resp.data


def test_cv_rescore_missing_job_description_redirects(client):
    resp = client.post("/cv/rescore", data={"cv_text": "hello", "job_description": ""})
    assert resp.status_code == 302


def test_download_cv_returns_pdf(client):
    resp = client.post("/download/cv", data={"cv_text": "SUMMARY\nA great candidate."})
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data[:5] == b"%PDF-"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_app.py -k "cv or generate_cv" -v`
Expected: FAIL (routes and template don't exist yet)

- [ ] **Step 3: Add routes to `app.py`**

Update the import block at the top of `app.py`:

```python
from utils.analysis import (
    ai_available,
    analyze_resume,
    generate_ats_cv,
    generate_cover_letter,
    provider_label,
)
from utils.ats_scorer import score_ats
from utils.matcher import analyze_match
from utils.parser import extract_text_from_bytes, is_supported
from utils.pdf_exporter import (
    export_analysis_to_pdf,
    export_cover_letter_to_pdf,
    export_cv_to_pdf,
)
```

Add these routes after `download_cover_letter` and before the `/health` route:

```python
@app.route("/cv", methods=["POST"])
def cv_generator():
    resume_text = (request.form.get("resume_text") or "").strip()
    job_description = (request.form.get("job_description") or "").strip()
    if not resume_text or not job_description:
        flash("That session data was lost. Please run the analysis again.")
        return redirect(url_for("index"))

    result = generate_ats_cv(resume_text, job_description)
    return render_template(
        "cv.html",
        cv_text=result["cv_text"],
        ats=result["ats"],
        source=result["source"],
        attempts=result["attempts"],
        resume_text=resume_text,
        job_description=job_description,
    )


@app.route("/cv/rescore", methods=["POST"])
def cv_rescore():
    job_description = (request.form.get("job_description") or "").strip()
    if not job_description:
        flash("That session data was lost. Please run the analysis again.")
        return redirect(url_for("index"))

    cv_text = request.form.get("cv_text") or ""
    resume_text = request.form.get("resume_text") or ""
    ats = score_ats(cv_text, job_description)
    return render_template(
        "cv.html",
        cv_text=cv_text,
        ats=ats,
        source=None,
        attempts=None,
        resume_text=resume_text,
        job_description=job_description,
    )


@app.route("/download/cv", methods=["POST"])
def download_cv():
    cv_text = request.form.get("cv_text") or ""
    pdf = export_cv_to_pdf(cv_text)
    return send_file(
        BytesIO(pdf), as_attachment=True,
        download_name="tailored_cv.pdf", mimetype="application/pdf",
    )
```

- [ ] **Step 4: Create `templates/cv.html`**

```html
{% extends "base.html" %}
{% block title %}Tailored CV | AI Resume Matcher{% endblock %}

{% block content %}
<section class="result-head">
  <p class="eyebrow">
    <span class="eyebrow-num">06</span> / Tailored CV
    {% if source %}
    <span class="src-tag {% if source == 'ai' %}src-ai{% endif %}">
      {% if source == 'ai' %}AI, {{ attempts }} pass{{ 'es' if attempts != 1 else '' }}{% else %}Local engine{% endif %}
    </span>
    {% endif %}
  </p>
  <form method="post" action="{{ url_for('result') }}" class="back-form">
    <textarea name="resume_text" hidden>{{ resume_text }}</textarea>
    <textarea name="job_description" hidden>{{ job_description }}</textarea>
    <input type="hidden" name="analysis" value="{}">
    <button type="submit" class="back-link back-link--btn">← Back to report</button>
  </form>
</section>

<section class="score-block">
  <div class="gauge" data-score="{{ ats.score }}">
    <svg viewBox="0 0 200 200" class="gauge-svg" aria-hidden="true">
      <circle class="gauge-track" cx="100" cy="100" r="86"></circle>
      <circle class="gauge-fill" cx="100" cy="100" r="86"></circle>
    </svg>
    <div class="gauge-center">
      <span class="gauge-num" id="ats-gauge-num">0</span>
      <span class="gauge-unit">/100</span>
    </div>
  </div>
  <div class="score-copy">
    <h1 class="score-verdict" id="ats-verdict">ATS score</h1>
    <p class="score-summary">
      {% if ats.score >= 90 %}Ready to submit. This CV clears a 90+ ATS screen.
      {% elif ats.score >= 70 %}Close. Edit below to close the remaining gaps.
      {% else %}Needs work. Edit below, then re-check the score.
      {% endif %}
    </p>
    <ul class="ats-breakdown">
      <li class="ats-row"><span>Keyword coverage</span><strong>{{ ats.coverage.score }}/50</strong></li>
      <li class="ats-row"><span>Standard sections</span><strong>{{ ats.sections.score }}/20</strong></li>
      <li class="ats-row"><span>Contact info</span><strong>{{ ats.contact_info.score }}/10</strong></li>
      <li class="ats-row"><span>Quantified achievements</span><strong>{{ ats.quantified_achievements.score }}/10</strong></li>
      <li class="ats-row"><span>Keyword placement</span><strong>{{ ats.keyword_placement.score }}/10</strong></li>
    </ul>
    {% if ats.coverage.missing_skills %}
    <p class="ats-hint">Still missing: {{ ats.coverage.missing_skills | join(', ') }}</p>
    {% endif %}
    {% if ats.sections.missing %}
    <p class="ats-hint">Missing sections: {{ ats.sections.missing | join(', ') }}</p>
    {% endif %}
  </div>
</section>

<section class="cv-editor">
  <form method="post" action="{{ url_for('cv_rescore') }}" id="cv-form">
    <textarea name="cv_text" id="cv-textarea" class="cv-textarea" spellcheck="false">{{ cv_text }}</textarea>
    <textarea name="job_description" hidden>{{ job_description }}</textarea>
    <textarea name="resume_text" hidden>{{ resume_text }}</textarea>
    <div class="cv-editor-actions">
      <button type="submit" class="cta cta-ghost" id="rescore-btn">
        <span class="cta-label">↻ Re-check ATS score</span>
        <span class="cta-spinner" aria-hidden="true"></span>
      </button>
      <button type="submit" form="download-cv-form" class="cta cta-amber" id="download-cv-btn">⬇ Download PDF</button>
    </div>
  </form>
  <form method="post" action="{{ url_for('download_cv') }}" id="download-cv-form" hidden>
    <textarea name="cv_text" id="download-cv-text"></textarea>
  </form>
</section>
{% endblock %}

{% block scripts %}
<script>
  (function () {
    const gauge = document.querySelector('.gauge');
    const fill = document.querySelector('.gauge-fill');
    const numEl = document.getElementById('ats-gauge-num');
    const verdict = document.getElementById('ats-verdict');
    const score = parseInt(gauge.dataset.score, 10) || 0;

    const r = 86, circ = 2 * Math.PI * r;
    fill.style.strokeDasharray = circ;
    fill.style.strokeDashoffset = circ;

    let hue = '#e0533a';
    if (score >= 90) hue = '#7fb069';
    else if (score >= 70) hue = '#e0a83d';
    fill.style.stroke = hue;
    numEl.style.color = hue;
    verdict.textContent = score >= 90 ? 'Strong ATS score'
      : score >= 70 ? 'Close to ready' : 'Needs work';

    requestAnimationFrame(() => {
      fill.style.strokeDashoffset = circ * (1 - score / 100);
    });

    const dur = 900, start = performance.now();
    function tick(now) {
      const p = Math.min((now - start) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      numEl.textContent = Math.round(eased * score);
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);

    document.getElementById('cv-form').addEventListener('submit', () => {
      const btn = document.getElementById('rescore-btn');
      btn.classList.add('is-loading');
      btn.disabled = true;
    });

    document.getElementById('download-cv-btn').addEventListener('click', () => {
      document.getElementById('download-cv-text').value =
        document.getElementById('cv-textarea').value;
    });
  })();
</script>
{% endblock %}
```

- [ ] **Step 5: Add the "Generate ATS CV" button to `templates/result.html`**

In `templates/result.html`, inside the `<div class="score-actions" data-action-group>` block, add a third form after the existing `download_report` form (before the closing `</div>` on line 43):

```html
      <form method="post" action="{{ url_for('cv_generator') }}" id="cv-form-launch">
        <textarea name="resume_text" hidden>{{ resume_text }}</textarea>
        <textarea name="job_description" hidden>{{ job_description }}</textarea>
        <button type="submit" class="cta cta-ghost" id="cv-btn">
          <span class="cta-label">📄 Generate ATS CV</span>
          <span class="cta-spinner" aria-hidden="true"></span>
        </button>
      </form>
```

In the same file's `{% block scripts %}`, inside the existing IIFE, after the `if (clForm) { ... }` block, add:

```javascript
    const cvForm = document.getElementById('cv-form-launch');
    if (cvForm) {
      cvForm.addEventListener('submit', () => {
        const btn = document.getElementById('cv-btn');
        btn.classList.add('is-loading');
        btn.disabled = true;
      });
    }
```

- [ ] **Step 6: Append CSS to `static/style.css`**

Add at the end of `static/style.css`:

```css
/* --- ATS CV generator --- */
.ats-breakdown {
  list-style: none; margin: 18px 0 0; padding: 0;
  display: flex; flex-direction: column; gap: 8px;
}
.ats-row {
  display: flex; justify-content: space-between; align-items: center;
  font-family: var(--mono); font-size: .78rem; color: var(--cream-dim);
  padding: 8px 12px; background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}
.ats-row strong { color: var(--cream); font-weight: 600; }
.ats-hint { font-size: .85rem; color: var(--muted); margin: 10px 0 0; }

.cv-editor { margin-top: 34px; }
.cv-textarea {
  width: 100%; min-height: 480px; resize: vertical;
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
  color: var(--cream); font-family: var(--mono); font-size: .88rem; line-height: 1.6;
  padding: 22px; box-sizing: border-box;
}
.cv-textarea:focus { outline: none; border-color: var(--amber); box-shadow: 0 0 0 3px rgba(224,168,61,.15); }
.cv-editor-actions { display: flex; gap: 12px; justify-content: flex-end; margin-top: 16px; flex-wrap: wrap; }
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_app.py -v`
Expected: PASS (all tests, including the new CV route ones)

- [ ] **Step 8: Run the full test suite to check for regressions**

Run: `pytest -v`
Expected: PASS, all tests green

- [ ] **Step 9: Manually verify in the browser**

Run: `python app.py`, open `http://localhost:5000`, upload a resume, submit a job description, click "Generate ATS CV" on the report page, confirm the gauge/breakdown render, edit the textarea, click "Re-check ATS score" and confirm the score updates, then click "Download PDF" and confirm a PDF downloads and opens correctly.

- [ ] **Step 10: Commit**

```bash
git add app.py templates/result.html templates/cv.html static/style.css tests/test_app.py
git commit -m "Wire up ATS CV generator routes, template, and UI"
```

---

## Self-Review Notes

- **Spec coverage:** All spec sections have a task — scorer (Task 1), generation loop + local rewrite + guardrail (Task 2), PDF export (Task 3), routes/UI/error handling (Task 4). Testing sections are satisfied by each task's own test file/additions.
- **Placeholder scan:** No TBD/TODO; every step has real code.
- **Type consistency:** `score_ats` return shape defined in Task 1 is used identically in Task 2 (`generate_ats_cv`'s `ats` key), Task 3 (`is_section_header` reused from the same module), and Task 4 (template field names `ats.coverage.score`, `ats.sections.missing`, etc. match the dict keys exactly as returned by `score_ats`). `generate_ats_cv`'s return keys (`cv_text`, `ats`, `source`, `attempts`) match what Task 4's routes read.
