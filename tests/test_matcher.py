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
