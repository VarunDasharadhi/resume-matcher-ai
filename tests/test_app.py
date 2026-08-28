"""Integration tests for the stateless request flow (Flask test client).

Each test forces local-engine mode (no API keys) so nothing hits the network.
"""
import html
import json
import re
from io import BytesIO

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

import app as app_module
import utils.analysis as analysis
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
    assert b"Refine to close the gaps" not in resp.data


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
    assert b"Refine to close the gaps" not in resp.data


def test_cv_rescore_missing_job_description_redirects(client):
    resp = client.post("/cv/rescore", data={"cv_text": "hello", "job_description": ""})
    assert resp.status_code == 302


def test_cv_rescore_shows_actionable_hints_for_weak_components(client):
    resp = client.post("/cv/rescore", data={
        "cv_text": "SKILLS\nPython\n",
        "job_description": "Need a Python developer with Django, AWS and Docker.",
        "resume_text": "Python developer.",
    })
    assert resp.status_code == 200
    assert b"No email address detected" in resp.data
    assert b"No phone number detected" in resp.data
    assert b"strengthen quantified achievements" in resp.data
    assert b"Missing sections" in resp.data
    assert b"Still missing" in resp.data
    assert b"never adds them for you" in resp.data


def test_cv_rescore_hides_contact_hints_when_already_present(client):
    resp = client.post("/cv/rescore", data={
        "cv_text": (
            "John Doe\njohn.doe@example.com | (555) 123-4567\n\n"
            "SUMMARY\nPython developer.\n\n"
            "EXPERIENCE\nBackend Engineer, Acme Corp\n"
            "- Reduced latency by 40% for 10,000 users.\n\n"
            "EDUCATION\nB.S. Computer Science\n\n"
            "SKILLS\nPython\n"
        ),
        "job_description": "Need a Python developer.",
        "resume_text": "Python developer.",
    })
    assert resp.status_code == 200
    assert b"No email address detected" not in resp.data
    assert b"No phone number detected" not in resp.data


def test_download_cv_returns_pdf(client):
    resp = client.post("/download/cv", data={"cv_text": "SUMMARY\nA great candidate."})
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data[:5] == b"%PDF-"


def _extract_analysis_attr(html_bytes, marker):
    """Pull the ``analysis`` hidden-field value out of a form's HTML block.

    Jinja HTML-escapes the JSON when it writes the attribute (quotes become
    ``&#34;`` etc.), same as any real browser would render it; unescape here
    so the extracted value matches what a browser actually submits on the
    next form post, not the raw escaped markup.
    """
    m = re.search(
        marker + rb'.*?name="analysis" value="([^"]*)"',
        html_bytes, re.DOTALL,
    )
    assert m, f"analysis hidden field not found near {marker!r}"
    return html.unescape(m.group(1).decode("utf-8")).encode("utf-8")


def test_cv_generator_preserves_analysis_for_back_link(client):
    resume_text = "Python developer with Django, Flask, AWS, Git and PostgreSQL"
    job_description = "Need Python, Django, AWS, Docker and Kubernetes"
    pdf = _pdf_bytes(resume_text)
    analyze_resp = client.post("/analyze", data={
        "job_description": job_description,
        "resume": (BytesIO(pdf), "resume.pdf"),
    }, content_type="multipart/form-data")
    assert analyze_resp.status_code == 200

    analysis_json = _extract_analysis_attr(analyze_resp.data, rb'id="cv-form-launch"')
    assert analysis_json != b"{}"

    cv_resp = client.post("/cv", data={
        "resume_text": resume_text,
        "job_description": job_description,
        "analysis": analysis_json,
    })
    assert cv_resp.status_code == 200

    carried_analysis = _extract_analysis_attr(cv_resp.data, rb'class="back-form"')
    assert carried_analysis == analysis_json, "analysis JSON was not carried through /cv"

    back_resp = client.post("/result", data={
        "analysis": carried_analysis,
        "resume_text": resume_text,
        "job_description": job_description,
    })
    assert back_resp.status_code == 200
    assert b"Kubernetes" in back_resp.data
    assert b"No overlapping skills detected." not in back_resp.data


def test_cv_rescore_preserves_analysis_for_back_link(client):
    resp = client.post("/cv/rescore", data={
        "cv_text": "SKILLS\nPython, Django, AWS, Docker",
        "job_description": "Need a Python developer with Django, AWS and Docker.",
        "resume_text": "Python developer with Django, AWS and Docker experience.",
        "analysis": '{"score": 77, "summary": "Solid fit."}',
    })
    assert resp.status_code == 200
    carried_analysis = _extract_analysis_attr(resp.data, rb'class="back-form"')
    assert b"77" in carried_analysis


def test_cv_generator_no_longer_auto_refines(client, monkeypatch):
    """/cv now returns the single-pass draft; a weak AI draft must NOT be
    silently upgraded to a second pass within this one request."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    calls = []

    def fake_chat(model, prompt, **kwargs):
        calls.append(prompt)
        return json.dumps({"cv_text": "SKILLS\nPython\n"})

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    resp = client.post("/cv", data={
        "resume_text": "Python developer.",
        "job_description": "Need a Python developer with Django, AWS and Docker.",
    })
    assert resp.status_code == 200
    assert len(calls) == 1
    assert b"Refine to close the gaps" in resp.data


def test_cv_generator_hides_refine_when_score_already_high(client, monkeypatch):
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

    def fake_chat(model, prompt, **kwargs):
        return json.dumps({"cv_text": good_cv})

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    resp = client.post("/cv", data={
        "resume_text": "Python developer.",
        "job_description": "Need a Python developer with Django, AWS and Docker.",
    })
    assert resp.status_code == 200
    assert b"Refine to close the gaps" not in resp.data


def test_cv_refine_improves_score_and_renders(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    strong_cv = (
        "John Doe\njohn.doe@example.com | (555) 123-4567\n\n"
        "SUMMARY\nPython developer with 5 years building Django services on AWS.\n\n"
        "EXPERIENCE\nBackend Engineer, Acme Corp\n"
        "- Reduced API latency by 40% by migrating to Django and AWS Lambda.\n"
        "- Led a team of 3 engineers, shipping 12 releases in 2025.\n\n"
        "EDUCATION\nB.S. Computer Science, State University\n\n"
        "SKILLS\nPython, Django, AWS, Docker, PostgreSQL\n"
    )

    def fake_chat(model, prompt, **kwargs):
        return json.dumps({"cv_text": strong_cv})

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    resp = client.post("/cv/refine", data={
        "cv_text": "SKILLS\nPython\n",
        "resume_text": "Python developer.",
        "job_description": "Need a Python developer with Django, AWS and Docker.",
    })
    assert resp.status_code == 200
    assert b"AI, 2 passes" in resp.data
    assert b"Refine to close the gaps" not in resp.data  # already attempted


def test_cv_refine_missing_job_description_redirects(client):
    resp = client.post("/cv/refine", data={
        "cv_text": "SKILLS\nPython\n",
        "prior_ats": "{}",
        "job_description": "",
    })
    assert resp.status_code == 302


def test_cv_refine_works_without_prior_ats_field(client, monkeypatch):
    """prior_ats is no longer read from the request at all; the route
    computes it server-side from cv_text, so it must work correctly even
    when the field is absent (or present but ignored)."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    def fake_chat(model, prompt, **kwargs):
        return json.dumps({"cv_text": "SKILLS\nPython\n"})

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    resp = client.post("/cv/refine", data={
        "cv_text": "SKILLS\nPython\n",
        "resume_text": "Python developer.",
        "job_description": "Need a Python developer with Django, AWS and Docker.",
    })
    assert resp.status_code == 200
    assert b"Tailored CV" in resp.data


def test_index_page_includes_progress_overlay_markup(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'id="progress-overlay"' in resp.data
    assert b'id="pw-stage"' in resp.data


def test_result_page_cv_form_has_progress_attribute(client):
    pdf = _pdf_bytes("Python developer with Django, Flask, AWS, Git and PostgreSQL")
    data = {
        "job_description": "Need Python, Django, AWS, Docker and Kubernetes",
        "resume": (BytesIO(pdf), "resume.pdf"),
    }
    resp = client.post("/analyze", data=data, content_type="multipart/form-data")
    assert b'id="cv-form-launch"' in resp.data
    assert b'data-progress="cv"' in resp.data


def test_cv_refine_form_has_progress_attribute_when_refine_offered(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    def fake_chat(model, prompt, **kwargs):
        return json.dumps({"cv_text": "SKILLS\nPython\n"})

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    resp = client.post("/cv", data={
        "resume_text": "Python developer.",
        "job_description": "Need a Python developer with Django, AWS and Docker.",
    })
    assert b'data-progress="cv-refine"' in resp.data
