# Agent instructions

This file is the shared contract for every harness that reads `AGENTS.md` directly, rather than
`CLAUDE.md`. Claude Code reads it too, via `CLAUDE.md`'s `@AGENTS.md` import. Keep this file
authoritative and self-contained; don't assume the reader has also seen `CLAUDE.md`.

## What this is

Flask app: match-scores a resume against a job description (skill gaps, AI cover letter) and generates an ATS-optimized CV (AI generation, fallback, PDF export, ATS scorer). Live host is Vercel (manual deploy).

## Session start

Read `STATE.md` and `GOTCHAS.md` first, both short. Git and any live dashboards outrank any prose
claim about current state; check them before trusting a claim here. `DECISIONS.md` is the
append-only dated decision log: read it before reopening a settled call, add a line when you make
a new one, never rewrite an existing dated line.

Full protocol for what to read on entry, what to write on exit, and what to do when something
unexpected happens: `~\.agents\PROTOCOL.md`.

## Stack and run commands

Python 3.12, Flask, Gunicorn. Parsing: PyMuPDF, python-docx, olefile. AI: httpx to Gemini/OpenRouter/OpenAI. PDF: ReportLab. Frontend: plain HTML/CSS/JS, no bundler.

Install: `pip install -r requirements.txt` (`-r requirements-dev.txt` adds pytest). Dev: `python app.py` (localhost:5000).

## Verification gate

`pytest` (`pytest.ini` at root, `testpaths = tests`). Real, codified test gate. Lint: none configured, no flake8/ruff/pylint config file exists in this repo, don't invent a lint step that isn't there.

This gate is non-negotiable for any harness or agent making code changes here, not just Claude
Code. A change that has not run the gate clean is not done. Do not commit with `--no-verify`. If a
cap or a gate step is genuinely wrong for the content, say so and get it changed rather than
routing around it.

## Repo boundaries

Never push without Varun's go-ahead. Live host is Vercel per `README.md`/`vercel.json` (older EA notes said Render, that is stale). Deploy is manual (`npx vercel --prod`); no auto-deploy found.

`../job-pipeline`'s own `score.py` imports this repo's `utils.matcher.analyze_match` directly via `sys.path.insert`, no HTTP, no API key, so this repo's `utils/matcher.py` is shared infrastructure, not private to this app. `job-pipeline`'s Tier 2 sweep also calls this app's HTTP `/api/match` endpoint separately. Either path means this repo's own `pytest` suite is the real gate before any change to the scoring logic can be trusted by `job-pipeline`; run it here before relying on a change there.

Shared checkout: run `git status` before any checkout, commit, branch, or reset. If the tree carries changes you did not make, treat the repo as read-only and hand off rather than touch it.

## Writing style

No em dashes anywhere (user-facing copy, comments, docs). Natural, human phrasing; errors say what
happened and what to do next. Match the surrounding code's conventions.
