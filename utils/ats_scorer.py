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
