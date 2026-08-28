"""AI Resume Matcher (Flask application).

Upload a resume (PDF or Word .doc/.docx) plus a job description, get a match
score, matching/missing skills, tailored suggestions, a downloadable PDF
report, and an AI-generated cover letter. Works with an OpenRouter or OpenAI
API key (richer output) or fully offline via a built-in local analysis engine.

The app is fully stateless: nothing is written to a database or disk, ever.
Uploaded files are parsed entirely in memory, and everything needed for later
steps (cover letter, PDF downloads) is carried through the page via POST form
fields. This makes it safe to run anywhere, including serverless platforms
like Vercel.
"""
import json
import os
from io import BytesIO

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from utils import analysis
from utils.analysis import (
    ai_available,
    analyze_resume,
    generate_ats_cv_draft,
    generate_cover_letter,
    provider_label,
    refine_ats_cv,
)
from utils.ats_scorer import score_ats
from utils.matcher import analyze_match
from utils.parser import extract_text_from_bytes, is_supported
from utils.pdf_exporter import (
    export_analysis_to_pdf,
    export_cover_letter_to_pdf,
    export_cv_to_pdf,
)

load_dotenv()

MAX_CONTENT_LENGTH = 4 * 1024 * 1024  # 4 MB (within serverless body limits)
CONTACT_EMAIL = "developerworld.net@gmail.com"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-only-change-in-production")
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH


@app.context_processor
def inject_globals():
    """Make AI availability and contact info known to every template."""
    return {
        "ai_available": ai_available(),
        "provider_label": provider_label(),
        "contact_email": CONTACT_EMAIL,
    }


def _carried_analysis():
    """Parse the analysis dict carried between pages; ``None`` if corrupted."""
    try:
        data = json.loads(request.form.get("analysis") or "{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    resume_file = request.files.get("resume")
    job_description = (request.form.get("job_description") or "").strip()

    if not resume_file or not resume_file.filename:
        flash("Please choose your résumé file (PDF, .doc, or .docx).")
        return redirect(url_for("index"))
    if not is_supported(resume_file.filename):
        flash(
            "That file type will not work. Please upload a PDF or a Word "
            "document (.doc or .docx)."
        )
        return redirect(url_for("index"))
    if not job_description:
        flash("Please paste the job description so we have something to match against.")
        return redirect(url_for("index"))

    # Parse the upload entirely in memory; nothing ever touches disk.
    try:
        resume_text = extract_text_from_bytes(resume_file.read(), resume_file.filename)
    except Exception:
        flash(
            "We had trouble reading that file. If it's an older .doc, try saving "
            "it as a PDF or .docx in Word (File, Save As) and upload that."
        )
        return redirect(url_for("index"))

    if not resume_text or not resume_text.strip():
        flash(
            "No text found in that document. If it's a scanned image, please "
            "upload a text-based PDF or .docx instead."
        )
        return redirect(url_for("index"))

    analysis = analyze_resume(resume_text, job_description)
    return _render_result(analysis, resume_text, job_description)


@app.route("/result", methods=["POST"])
def result():
    """Re-render the report from carried data (used by 'back to report')."""
    analysis = _carried_analysis()
    if analysis is None:
        flash("That report data was corrupted. Please run the analysis again.")
        return redirect(url_for("index"))
    return _render_result(
        analysis,
        request.form.get("resume_text", ""),
        request.form.get("job_description", ""),
    )


def _render_result(analysis: dict, resume_text: str, job_description: str):
    return render_template(
        "result.html",
        analysis=analysis,
        analysis_json=json.dumps(analysis),
        resume_text=resume_text,
        job_description=job_description,
    )


@app.route("/cover-letter", methods=["POST"])
def cover_letter():
    resume_text = request.form.get("resume_text", "")
    job_description = request.form.get("job_description", "")
    analysis_json = request.form.get("analysis", "{}")
    letter = generate_cover_letter(resume_text, job_description)
    return render_template(
        "cover_letter.html",
        cover_letter=letter,
        resume_text=resume_text,
        job_description=job_description,
        analysis_json=analysis_json,
    )


@app.route("/download/report", methods=["POST"])
def download_report():
    analysis = _carried_analysis()
    if analysis is None:
        flash("That report data was corrupted. Please run the analysis again.")
        return redirect(url_for("index"))
    pdf = export_analysis_to_pdf(analysis)
    return send_file(
        BytesIO(pdf), as_attachment=True,
        download_name="match_report.pdf", mimetype="application/pdf",
    )


@app.route("/download/cover-letter", methods=["POST"])
def download_cover_letter():
    letter = request.form.get("cover_letter", "")
    pdf = export_cover_letter_to_pdf(letter)
    return send_file(
        BytesIO(pdf), as_attachment=True,
        download_name="cover_letter.pdf", mimetype="application/pdf",
    )


@app.route("/cv", methods=["POST"])
def cv_generator():
    resume_text = (request.form.get("resume_text") or "").strip()
    job_description = (request.form.get("job_description") or "").strip()
    analysis_json = request.form.get("analysis", "{}")
    if not resume_text or not job_description:
        flash("That session data was lost. Please run the analysis again.")
        return redirect(url_for("index"))

    result = generate_ats_cv_draft(resume_text, job_description)
    can_refine = result["source"] == "ai" and result["ats"]["score"] < 90
    return render_template(
        "cv.html",
        cv_text=result["cv_text"],
        ats=result["ats"],
        source=result["source"],
        attempts=result["attempts"],
        can_refine=can_refine,
        resume_text=resume_text,
        job_description=job_description,
        analysis_json=analysis_json,
    )


@app.route("/cv/rescore", methods=["POST"])
def cv_rescore():
    job_description = (request.form.get("job_description") or "").strip()
    if not job_description:
        flash("That session data was lost. Please run the analysis again.")
        return redirect(url_for("index"))

    cv_text = request.form.get("cv_text") or ""
    # resume_text is carried for the back-link only, not scored: score_ats
    # only needs cv_text and job_description.
    resume_text = request.form.get("resume_text") or ""
    analysis_json = request.form.get("analysis", "{}")
    ats = score_ats(cv_text, job_description)
    return render_template(
        "cv.html",
        cv_text=cv_text,
        ats=ats,
        source=None,
        attempts=None,
        can_refine=False,
        resume_text=resume_text,
        job_description=job_description,
        analysis_json=analysis_json,
    )


@app.route("/cv/refine", methods=["POST"])
def cv_refine():
    job_description = (request.form.get("job_description") or "").strip()
    if not job_description:
        flash("That session data was lost. Please run the analysis again.")
        return redirect(url_for("index"))

    cv_text = request.form.get("cv_text") or ""
    resume_text = request.form.get("resume_text") or ""
    analysis_json = request.form.get("analysis", "{}")
    try:
        prior_ats = json.loads(request.form.get("prior_ats") or "{}")
    except ValueError:
        prior_ats = {}
    if not isinstance(prior_ats, dict) or "score" not in prior_ats:
        flash("That session data was lost. Please run the analysis again.")
        return redirect(url_for("index"))

    result = refine_ats_cv(cv_text, resume_text, job_description, prior_ats)
    return render_template(
        "cv.html",
        cv_text=result["cv_text"],
        ats=result["ats"],
        source=result["source"],
        attempts=result["attempts"],
        can_refine=False,
        resume_text=resume_text,
        job_description=job_description,
        analysis_json=analysis_json,
    )


@app.route("/download/cv", methods=["POST"])
def download_cv():
    cv_text = request.form.get("cv_text") or ""
    pdf = export_cv_to_pdf(cv_text)
    return send_file(
        BytesIO(pdf), as_attachment=True,
        download_name="tailored_cv.pdf", mimetype="application/pdf",
    )


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "ai": ai_available()}


@app.route("/api/match", methods=["POST"])
def api_match():
    """JSON scoring endpoint for programmatic callers (no file upload).

    Body: {"resume_text": str, "job_description": str}. Gated by the
    MATCH_API_KEY env var when set (via the X-API-Key header); open when unset.
    """
    required_key = os.getenv("MATCH_API_KEY", "")
    if required_key and request.headers.get("X-API-Key") != required_key:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    resume_text = (data.get("resume_text") or "").strip()
    job_description = (data.get("job_description") or "").strip()

    if not resume_text:
        return jsonify({"error": "resume_text is required"}), 400
    if not job_description:
        return jsonify({"error": "job_description is required"}), 400

    return jsonify(analyze_match(resume_text, job_description))


@app.errorhandler(413)
def too_large(_e):
    flash("That file is too large. Please upload one under 4 MB.")
    return redirect(url_for("index")), 413


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    # Local dev entrypoint (production uses gunicorn/Vercel). FLASK_DEBUG=0
    # turns the debugger off if this script is ever run on a shared host.
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "1") == "1")
