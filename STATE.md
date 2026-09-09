# resume-matcher-ai STATE

Git and any live dashboards outrank this file; check them before trusting a claim here.

This file holds only what is true right now. History and session narrative live in
`docs/journal/`, settled calls live in `DECISIONS.md`, gotcha detail lives in `docs/gotchas/`. It
is size-capped by `.githooks/pre-commit` (see `PROTOCOL.md`); move content out rather than
deleting it. Never describe uncommitted work here, `git status` covers that live and accurately.

## What this is

Flask app (Python 3.12, Gunicorn) that match-scores a resume against a job description and
generates an ATS-optimized CV (AI generation with local fallback, PDF export via ReportLab, an
ATS-readiness scorer). Live on Vercel, manual deploy. Depended on by `../job-pipeline`: that
repo's `score.py` imports this repo's `utils.matcher.analyze_match` directly (`sys.path.insert`,
no HTTP), and `job-pipeline`'s Tier 2 sweep also calls this app's `/api/match` HTTP endpoint. Has
its own GitHub remote, `main` branch.

## Where the code stands

`main` was at `107472c` ("Strip tool branding from the downloaded cover letter PDF too") before
this task's `chore/agent-contract` branch was cut off it, and matched `origin/main` exactly
(0 commits ahead) at that point. Per the last real `HANDOFF.md` entry (2026-08-29, before this
task tombstoned that file): the ATS-optimized CV generator shipped end to end (scorer, AI
generation with local fallback, PDF export, progress overlay), Gemini was added as a fallback/then
primary AI provider for CV generation, and three reliability fixes landed from live user testing.
That entry claimed 19 commits ahead of `origin/main` with nothing pushed; git now shows `main` and
`origin/main` at the same commit, so those commits were pushed at some point after that entry was
written (git outranks the stale prose claim).

Verification gate: `pytest` (`pytest.ini` at root). No lint tooling configured, no flake8/ruff/
pylint config exists. Ran clean on this branch: 135 passed, 0 failed (`venv\Scripts\python.exe -m
pytest`).

Two files were untracked and carried over for at least two prior sessions before this task:
`docs/superpowers/plans/2026-07-17-contact-report-modal.md` and (before this task's own commit)
`HANDOFF.md` itself, both flagged in the old HANDOFF's own "commit or discard" next step. This
task commits both as part of landing the contract files, since they are real historical content,
not deciding to discard them.

Last verified: 2026-09-09
