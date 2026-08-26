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
