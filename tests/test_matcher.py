"""Tests for the local resume/job-description analysis engine."""
from utils.matcher import extract_skills, analyze_match


def test_extract_skills_finds_known_skills():
    text = "Experienced in Python, Django and PostgreSQL with some AWS exposure."
    found = extract_skills(text)
    assert "Python" in found
    assert "Django" in found
    assert "PostgreSQL" in found
    assert "AWS" in found


def test_extract_skills_is_case_insensitive():
    found = extract_skills("built apis with FLASK and react")
    assert "Flask" in found
    assert "React" in found


def test_extract_skills_uses_word_boundaries():
    # "Java" should not be matched from "JavaScript"
    found = extract_skills("I write JavaScript every day.")
    assert "JavaScript" in found
    assert "Java" not in found


def test_extract_skills_handles_multiword_skills():
    found = extract_skills("Worked with Machine Learning and CI/CD pipelines.")
    assert "Machine Learning" in found


def test_analyze_match_perfect_overlap_scores_high():
    resume = "Python developer skilled in Django, PostgreSQL, Docker and AWS."
    job = "We need a Python developer with Django, PostgreSQL, Docker and AWS."
    result = analyze_match(resume, job)
    assert result["score"] >= 90
    assert set(result["matching_skills"]) >= {"Python", "Django", "PostgreSQL", "Docker", "AWS"}
    assert result["missing_skills"] == []


def test_analyze_match_identifies_missing_skills():
    resume = "Python developer with Django experience."
    job = "Looking for Python, Django, Kubernetes and Terraform skills."
    result = analyze_match(resume, job)
    assert "Kubernetes" in result["missing_skills"]
    assert "Terraform" in result["missing_skills"]
    assert "Python" in result["matching_skills"]
    assert result["score"] < 100


def test_analyze_match_no_overlap_scores_low():
    resume = "Graphic designer skilled in Photoshop and Illustrator."
    job = "Backend engineer needing Python, Go, Kubernetes and Kafka."
    result = analyze_match(resume, job)
    assert result["score"] < 40


def test_analyze_match_returns_required_keys():
    result = analyze_match("Python", "Python developer needed")
    for key in ("score", "matching_skills", "missing_skills", "suggestions"):
        assert key in result
    assert isinstance(result["score"], int)
    assert 0 <= result["score"] <= 100
    assert isinstance(result["suggestions"], list)


def test_analyze_match_suggestions_mention_missing_skills():
    resume = "Python developer."
    job = "Need Python and Kubernetes."
    result = analyze_match(resume, job)
    joined = " ".join(result["suggestions"]).lower()
    assert "kubernetes" in joined


def test_analyze_match_empty_job_description_does_not_crash():
    result = analyze_match("Python developer", "")
    assert 0 <= result["score"] <= 100


def test_extract_skills_ignores_common_words_that_shadow_skills():
    # Everyday English must not register as programming skills.
    text = (
        "We need someone ready to go the extra mile, express genuine interest, "
        "respond in a swift manner, excel at communication, and handle the rest "
        "of the workload."
    )
    found = extract_skills(text)
    assert "Go" not in found
    assert "Express" not in found
    assert "Swift" not in found
    assert "Excel" not in found
    assert "REST APIs" not in found


def test_extract_skills_still_finds_ambiguous_skills_when_capitalized():
    text = (
        "Built services in Go and Swift, REST APIs with Express, "
        "and dashboards in Excel and R."
    )
    found = extract_skills(text)
    assert "Go" in found
    assert "Swift" in found
    assert "Express" in found
    assert "Excel" in found
    assert "REST APIs" in found
    assert "R" in found


def test_extract_skills_r_not_matched_from_r_and_d():
    assert "R" not in extract_skills("Collaborate closely with the R&D department.")


def test_extract_skills_spring_framework_not_season():
    assert "Spring" not in extract_skills("Internship starting Spring 2026.")
    assert "Spring" in extract_skills("Microservices with Spring Boot.")
    assert "Spring" in extract_skills("Deep experience with Spring and Hibernate.")


def test_extract_skills_rails_framework_not_guard_rails():
    assert "Rails" not in extract_skills("Put guard rails around the release process.")
    assert "Rails" in extract_skills("Web apps in Ruby on Rails.")
