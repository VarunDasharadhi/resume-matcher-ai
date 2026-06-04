"""AI Resume Matcher (Flask application).

Upload a resume (PDF or Word .doc/.docx) plus a job description, get a match
score, matching/missing skills, tailored suggestions, a downloadable PDF
report, and an AI-generated cover letter. Works with an OpenRouter or OpenAI
API key (richer output) or fully offline via a built-in local analysis engine.

The app is fully stateless: nothing is written to a database or persisted on
disk between requests. Uploaded files are read into a temp file only long
enough to extract text, and everything needed for later steps (cover letter,
PDF downloads) is carried through the page via POST form fields. This makes it
safe to run anywhere, including serverless platforms like Vercel.
"""
import json
import os
import tempfile
from io import BytesIO

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from utils.analysis import (
    ai_available,
    analyze_resume,
    generate_cover_letter,
    provider_label,
)
from utils.parser import extract_text, is_supported
from utils.pdf_exporter import export_analysis_to_pdf, export_cover_letter_to_pdf

load_dotenv()

MAX_CONTENT_LENGTH = 4 * 1024 * 1024  # 4 MB (within serverless body limits)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-only-change-in-production")
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH


@app.context_processor
def inject_globals():
    """Make AI availability known to every template (header/footer status)."""
    return {"ai_available": ai_available(), "provider_label": provider_label()}


def _ext(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


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

    # Read the upload into a temp file just long enough to extract its text.
    fd, tmp_path = tempfile.mkstemp(suffix=_ext(resume_file.filename))
    os.close(fd)
    try:
        resume_file.save(tmp_path)
        resume_text = extract_text(tmp_path)
    except Exception:
        flash(
            "We had trouble reading that file. If it's an older .doc, try saving "
            "it as a PDF or .docx in Word (File, Save As) and upload that."
        )
        return redirect(url_for("index"))
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

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
    analysis = json.loads(request.form.get("analysis") or "{}")
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
    analysis = json.loads(request.form.get("analysis") or "{}")
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


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "ai": ai_available()}


@app.errorhandler(413)
def too_large(_e):
    flash("That file is too large. Please upload one under 4 MB.")
    return redirect(url_for("index")), 413


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
