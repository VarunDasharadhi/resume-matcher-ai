# 🎯 AI Résumé Matcher

**Live demo: https://resume-matcher-ai-iota.vercel.app**

Upload a résumé (**PDF or Word `.doc`/`.docx`**) and a job description, and in seconds
get a match score, a precise skill-gap breakdown, tailored improvement
suggestions, and a ready-to-send cover letter, all downloadable as polished
PDFs.

> **Works with _or_ without an API key.** Add an **OpenRouter** key (it has
> free models) or an **OpenAI** key and analysis + cover letters become
> AI-powered. Without one, a built-in **local analysis engine** does real
> skill extraction and scoring, so the app is always fully functional, fully
> offline-capable, and free to run.

---

## ✨ Features

- **Match score (0 to 100)** with an animated radial gauge
- **Skill-gap analysis**, matching vs. missing skills, as colour-coded chips
- **Actionable suggestions** tailored to the specific role
- **AI-generated cover letter** (or a solid template-based one offline)
- **PDF export** of both the match report and the cover letter
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

The analysis engine and AI-fallback logic are covered by unit tests:

```bash
pip install -r requirements-dev.txt
pytest
```

---

## 🔌 Configuration

All optional, see [`.env.example`](.env.example):

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | _(none)_ | Use OpenRouter (has **free** models). Preferred when set |
| `OPENAI_API_KEY` | _(none)_ | Use OpenAI directly (when no OpenRouter key) |
| `OPENAI_MODEL` | provider default | Model id, e.g. `meta-llama/llama-3.3-70b-instruct:free` (OpenRouter) or `gpt-4o-mini` (OpenAI) |
| `APP_URL` | repo URL | Attribution header sent to OpenRouter |
| `SECRET_KEY` | dev default | Signs Flask session cookies (set in prod!) |
| `PORT` | `5000` | Local server port |

**Provider selection:** OpenRouter is used when `OPENROUTER_API_KEY` is set,
otherwise OpenAI when `OPENAI_API_KEY` is set, otherwise the local engine. Any
API error falls back to the local engine automatically.

---

## ☁️ Deploy

**Vercel (current live host).** The app is fully stateless (no disk writes
between requests, PDFs built in memory), so it runs on serverless out of the box
via [`vercel.json`](vercel.json):

```bash
npx vercel --prod
```

To enable AI mode on the deployment, add your key as an environment variable and
redeploy:

```bash
npx vercel env add OPENROUTER_API_KEY production   # paste your sk-or-... key
npx vercel env add OPENAI_MODEL production          # e.g. meta-llama/llama-3.3-70b-instruct:free
npx vercel --prod
```

**Other hosts (Render / Railway / Heroku).** A `Procfile` is also included for
persistent-server platforms:

```
web: gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
```

Set `OPENROUTER_API_KEY` (or `OPENAI_API_KEY`) and `SECRET_KEY` as environment
variables in your host's dashboard.

---

## 📂 Project structure

```
app.py                 # Flask routes, upload handling, PRG flow, record store
utils/
  parser.py            # PDF/.doc/.docx -> text (PyMuPDF + python-docx + olefile)
  matcher.py           # Local skill-extraction + scoring engine (tested)
  analysis.py          # Orchestration: LLM REST calls with local fallback (tested)
  pdf_exporter.py      # Styled PDF reports & cover letters (ReportLab)
templates/             # base + index + result + cover_letter (Jinja)
static/style.css       # "Precision instrument" theme
tests/                 # pytest unit tests
```

---

## 🔐 Privacy

Résumés are parsed in memory and the uploaded file is deleted immediately after
text extraction. The extracted text and analysis are stored server-side only to
power the report/cover-letter pages and downloads.
