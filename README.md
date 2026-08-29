# 🎯 AI Résumé Matcher

**Live demo: https://resume-matcher-ai-iota.vercel.app**

Upload a résumé (**PDF or Word `.doc`/`.docx`**) and a job description, and in seconds
get a match score, a precise skill-gap breakdown, tailored improvement
suggestions, a ready-to-send cover letter, and an ATS-optimized tailored CV,
all downloadable as polished PDFs.

> **Works with _or_ without an API key.** Add a **Gemini**, **OpenRouter** (it
> has free models), or **OpenAI** key and analysis, cover letters, and CV
> generation become AI-powered. Without one, a built-in **local analysis
> engine** does real skill extraction and scoring, so the app is always fully
> functional, fully offline-capable, and free to run.

---

## ✨ Features

- **Match score (0 to 100)** with an animated radial gauge
- **Skill-gap analysis**, matching vs. missing skills, as colour-coded chips
- **Actionable suggestions** tailored to the specific role
- **AI-generated cover letter** (or a solid template-based one offline)
- **ATS-optimized CV generator**, tailored to the job description with a live
  ATS-readiness score breakdown (keyword coverage, standard sections, contact
  info, quantified achievements, keyword placement) and a one-click AI refine
  pass to close the remaining gaps. Never fabricates skills or achievements
  the source résumé doesn't already support.
- **Live progress feedback**, a full-page overlay with elapsed time and
  rotating stage text for AI calls that take a while, so a longer CV
  generation or refine pass never looks like a frozen page
- **PDF export** of the match report, the cover letter, and the tailored CV
- **Graceful fallback**, any AI-provider error (no key, quota, network) is
  logged and falls back to the local engine; the user always gets a result
- **Robust UX**, drag-and-drop upload, sample job description, loading states,
  input validation, flash errors, and a fully responsive layout

---

## 🧰 Tech stack

| Layer | Tooling |
|------|---------|
| Backend | Python · Flask |
| Analysis | OpenRouter / OpenAI over plain REST via httpx (optional) · custom local skill-matching engine |
| CV generation | Gemini direct API (tried first) → OpenRouter/OpenAI chain (fallback) · deterministic ATS-readiness scorer, never fabricates skills |
| Résumé in | PyMuPDF (PDF) · python-docx (.docx) · olefile (legacy .doc, best-effort) |
| PDF out | ReportLab (Platypus) |
| Frontend | Hand-written HTML/CSS/JS, Fraunces + Hanken Grotesk, no framework |
| Deploy | Gunicorn (Render / any PaaS) |

---

## 🚀 Run locally

```bash
# 1. Create & activate a virtual environment
python -m venv venv
# Windows:  venv\Scripts\activate
# macOS/Linux:  source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) configure an OpenAI key for AI mode
cp .env.example .env        # then edit .env and add OPENAI_API_KEY

# 4. Run
python app.py
```

Open <http://localhost:5000>. No `.env`? It just runs on the local engine.

---

## 🧪 Tests

The analysis engine, ATS scorer, and AI-fallback logic are covered by unit tests:

```bash
pip install -r requirements-dev.txt
pytest
```

---

## 🔌 Configuration

All optional, see [`.env.example`](.env.example):

| Variable | Default | Purpose |
|----------|---------|---------|
| `GEMINI_API_KEY` | _(none)_ | Use Gemini's direct API for CV generation (tried first there; more reliable in practice for that prompt). Falls back to the OpenRouter/OpenAI chain, then the local engine |
| `OPENROUTER_API_KEY` | _(none)_ | Use OpenRouter (has **free** models). Preferred when set for analysis and cover letters |
| `OPENAI_API_KEY` | _(none)_ | Use OpenAI directly (when no OpenRouter key) |
| `OPENAI_MODEL` | `openrouter/free` (OpenRouter) / `gpt-4o-mini` (OpenAI) | Override to pin a specific model id instead of the auto-router |
| `APP_URL` | repo URL | Attribution header sent to OpenRouter |
| `SECRET_KEY` | dev default | Signs Flask session cookies (set in prod!) |
| `PORT` | `5000` | Local server port |

**Provider selection:** for match analysis and cover letters, OpenRouter is
used when `OPENROUTER_API_KEY` is set, otherwise OpenAI when
`OPENAI_API_KEY` is set, otherwise the local engine. For CV generation,
Gemini is tried first when `GEMINI_API_KEY` is set, then the same
OpenRouter/OpenAI chain, then the local engine. Any API error falls back
automatically to the next option.

---

## ☁️ Deploy

**Vercel (current live host).** The app is fully stateless (no disk writes
between requests, PDFs built in memory), so it runs on serverless out of the box
via [`vercel.json`](vercel.json):

```bash
npx vercel --prod
```

To enable AI mode on the deployment, add your key(s) as environment variables and
redeploy:

```bash
npx vercel env add GEMINI_API_KEY production        # paste your Gemini key, for CV generation
npx vercel env add OPENROUTER_API_KEY production   # paste your sk-or-... key
npx vercel env add OPENAI_MODEL production          # optional; defaults to openrouter/free
npx vercel --prod
```

**Other hosts (Render / Railway / Heroku).** A `Procfile` is also included for
persistent-server platforms:

```
web: gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
```

Set `GEMINI_API_KEY` and/or `OPENROUTER_API_KEY` (or `OPENAI_API_KEY`) and
`SECRET_KEY` as environment variables in your host's dashboard.

---

## 📂 Project structure

```
app.py                 # Flask routes, upload handling, PRG flow, record store
utils/
  parser.py            # PDF/.doc/.docx -> text (PyMuPDF + python-docx + olefile)
  matcher.py           # Local skill-extraction + scoring engine (tested)
  analysis.py          # Orchestration: LLM REST calls (Gemini, OpenRouter, OpenAI) with local fallback (tested)
  ats_scorer.py        # Deterministic ATS-readiness scorer for generated CVs (tested)
  pdf_exporter.py      # Styled PDF reports, cover letters & CVs (ReportLab)
templates/             # base + index + result + cv + cover_letter (Jinja)
static/style.css       # "Precision instrument" theme
tests/                 # pytest unit tests
```

---

## 🔐 Privacy

Résumés are parsed in memory and the uploaded file is deleted immediately after
text extraction. The extracted text and analysis are stored server-side only to
power the report/cover-letter/CV pages and downloads.
