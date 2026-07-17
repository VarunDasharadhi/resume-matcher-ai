"""Integration tests for the stateless request flow (Flask test client).

Each test forces local-engine mode (no API keys) so nothing hits the network.
"""
import json
from io import BytesIO

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

import app as app_module
from utils.matcher import analyze_match


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def _pdf_bytes(text):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(72, 720, text)
    c.save()
    return buf.getvalue()


def test_index_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"AI Resume Matcher" in resp.data or b"R\xc3\xa9sum\xc3\xa9Match" in resp.data


def test_index_shows_contact_email(client):
    resp = client.get("/")
    assert b"developerworld.net@gmail.com" in resp.data


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_analyze_pdf_renders_result_inline(client):
    pdf = _pdf_bytes("Python developer with Django, Flask, AWS, Git and PostgreSQL")
    data = {
        "job_description": "Need Python, Django, AWS, Docker and Kubernetes",
        "resume": (BytesIO(pdf), "resume.pdf"),
    }
    resp = client.post("/analyze", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200            # rendered inline, no redirect
    assert b"Match report" in resp.data
    assert b"Generate cover letter" in resp.data
    # carried data present for the next step
    assert b'name="analysis"' in resp.data
    assert b"Kubernetes" in resp.data         # a missing skill shown


def test_analyze_missing_file_redirects(client):
    resp = client.post(
        "/analyze", data={"job_description": "Python"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302


def test_analyze_unsupported_type_redirects(client):
    data = {
        "job_description": "Python",
        "resume": (BytesIO(b"hello"), "resume.txt"),
    }
    resp = client.post("/analyze", data=data, content_type="multipart/form-data")
    assert resp.status_code == 302


def test_cover_letter_post_renders(client):
    resp = client.post("/cover-letter", data={
        "resume_text": "Python developer with Django and AWS.",
        "job_description": "Need Python and Django.",
        "analysis": "{}",
    })
    assert resp.status_code == 200
    assert b"Hiring Manager" in resp.data
    assert b"Download as PDF" in resp.data


def test_result_repost_rerenders(client):
    analysis = {
        "score": 72, "summary": "Solid fit.",
        "matching_skills": ["Python"], "missing_skills": ["Docker"],
        "suggestions": ["Add Docker"], "source": "local",
    }
    resp = client.post("/result", data={
        "analysis": json.dumps(analysis),
        "resume_text": "Python dev", "job_description": "Python Docker",
    })
    assert resp.status_code == 200
    assert b"Match report" in resp.data
    assert b"Docker" in resp.data


def test_result_with_malformed_json_redirects(client):
    """Tampered/corrupted carried data must not produce a 500."""
    resp = client.post("/result", data={
        "analysis": "not-json{{{", "resume_text": "", "job_description": "",
    })
    assert resp.status_code == 302


def test_result_with_partial_analysis_renders_with_defaults(client):
    """Missing keys are defaulted so the template never crashes."""
    resp = client.post("/result", data={
        "analysis": "{}", "resume_text": "", "job_description": "",
    })
    assert resp.status_code == 200
    assert b"Match report" in resp.data


def test_download_report_with_malformed_json_redirects(client):
    resp = client.post("/download/report", data={"analysis": "]["})
    assert resp.status_code == 302


def test_download_report_returns_pdf(client):
    analysis = {
        "score": 80, "summary": "Good.", "matching_skills": ["Python"],
        "missing_skills": [], "suggestions": ["Keep going"], "source": "local",
    }
    resp = client.post("/download/report", data={"analysis": json.dumps(analysis)})
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data[:5] == b"%PDF-"


def test_download_cover_letter_returns_pdf(client):
    resp = client.post(
        "/download/cover-letter",
        data={"cover_letter": "Dear Hiring Manager,\n\nThanks.\n\nBest,\nAlex"},
    )
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data[:5] == b"%PDF-"


def test_api_match_happy_path(client):
    resume_text = "Python developer with Django, Flask, AWS, Git and PostgreSQL"
    job_description = "Need Python, Django, AWS, Docker and Kubernetes"
    resp = client.post(
        "/api/match",
        json={"resume_text": resume_text, "job_description": job_description},
    )
    assert resp.status_code == 200
    assert resp.get_json() == analyze_match(resume_text, job_description)


def test_api_match_missing_resume_text_400(client):
    resp = client.post("/api/match", json={"job_description": "Need Python"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_api_match_missing_job_description_400(client):
    resp = client.post("/api/match", json={"resume_text": "Python developer"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_api_match_empty_fields_400(client):
    resp = client.post(
        "/api/match", json={"resume_text": "  ", "job_description": " "}
    )
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_api_match_requires_api_key_when_set(client, monkeypatch):
    monkeypatch.setenv("MATCH_API_KEY", "secret-key")
    resp = client.post(
        "/api/match",
        json={"resume_text": "Python developer", "job_description": "Need Python"},
    )
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "unauthorized"}


def test_api_match_rejects_wrong_api_key(client, monkeypatch):
    monkeypatch.setenv("MATCH_API_KEY", "secret-key")
    resp = client.post(
        "/api/match",
        json={"resume_text": "Python developer", "job_description": "Need Python"},
        headers={"X-API-Key": "wrong-key"},
    )
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "unauthorized"}


def test_api_match_accepts_correct_api_key(client, monkeypatch):
    monkeypatch.setenv("MATCH_API_KEY", "secret-key")
    resp = client.post(
        "/api/match",
        json={"resume_text": "Python developer", "job_description": "Need Python"},
        headers={"X-API-Key": "secret-key"},
    )
    assert resp.status_code == 200


def test_api_match_open_when_no_api_key_configured(client, monkeypatch):
    monkeypatch.delenv("MATCH_API_KEY", raising=False)
    resp = client.post(
        "/api/match",
        json={"resume_text": "Python developer", "job_description": "Need Python"},
    )
    assert resp.status_code == 200
