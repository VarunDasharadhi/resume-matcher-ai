# HANDOFF, RETIRED 2026-09-09

This file is retired. Never append new session entries here. Current facts are in `STATE.md`,
dated decisions in `DECISIONS.md`, gotchas in `GOTCHAS.md`, session narrative in
`docs/journal/`. This file's content below is kept as history only.

# AI Resume Matcher

## Latest session (2026-08-29) — ATS CV generator + progress feedback + reliability fixes

### What was done
1. **Committed the carried-over `/api/match` endpoint** from the prior session (`5c1507d`), closing that session's open next-step.
2. **Built the ATS-optimized CV generator feature** end to end: a dedicated ATS-readiness scorer (`utils/ats_scorer.py`), an AI-with-local-fallback generation function, PDF export, and the routes/UI wiring. Spec `2ec38fe`, plan `f0c19be`, four task commits (`9f7c214`, `de895e6`, `0a7535d`, `0fd49b2`), then a whole-branch review fix wave (`f9b743f`) that caught two real bugs per-task review had missed: the CV page's "Back to report" link silently rendered a fabricated empty report, and the no-AI local rewrite injected a match-report verdict ("Limited match... 40%") into the CV text itself.
3. **Added Gemini as a fallback provider and raised the token budget** (`92b34f4`) after live testing showed the free OpenRouter auto-router failing or truncating JSON often enough on this longer CV-generation prompt to matter.
4. **Built client-side progress feedback for CV generation**: split generation into separate draft and refine passes, added a `/cv/refine` route, and a full-page progress overlay (timer, easing progress bar, rotating stage text) so a 2-100 second AI wait no longer looks like a frozen page. Plan `0ca33dd`, four task commits (`e480e11`, `60fd355`, `83a154d`, `efc2012`), fix wave `fe609a7`.
5. **Three reliability fixes driven by the user's own live testing against a running dev server**, each specified completely and drafted by a free model (`gemini-flash-lite-latest` via the `freemodel` helper) with mandatory independent review before merge:
   - `8f6c64d` — the AI wasn't reliably following the "put top skills near the top" instruction (0/10 keyword-placement scores even after a refinement pass told to fix it). Now deterministically prepended in code from skills the scorer already confirmed are genuinely present, never invented. Also expanded the on-page hints to explain every weak scoring component, not just two of them.
   - `3f540ec` — the "Refine to close the gaps" button was hidden whenever the draft fell back to the local engine, which happened often, leaving users with no upgrade path at all. Now offered whenever the score is under 90 regardless of source; a refine that fails no longer falsely claims "AI, 2 passes".
   - `193c429` — reordered `_cv_with_ai` to try Gemini before the OpenRouter/OpenAI chain (previously the reverse), since direct Gemini calls proved far more reliable for this prompt in repeated live testing. Also fixed a test-isolation leak this reorder exposed: 16 pre-existing tests that mocked only the OpenRouter call path were leaking the real `.env` `GEMINI_API_KEY` and making live network calls once Gemini ran first.
6. **First live use of the free-model delegation workflow** in this repo: one dispatch (a route/template change) ignored large parts of a complete spec and was discarded in favor of hand-applying the spec directly; a second dispatch (the Gemini reorder) followed the spec correctly, but independent review still caught a vacuous regression test (an `AssertionError` sentry silently swallowed by the function's own broad `except Exception`) before it shipped.

### Current state
- 19 commits ahead of `origin/main`, nothing pushed this session.
- Full pytest suite: 135/135 passing.
- Dev server verified locally via direct HTTP/Python calls and the user's own browser testing, not deployed. None of this session's work has been checked against a real Vercel deploy.
- `.env` now also carries `GEMINI_API_KEY`, sourced from the `GEMINI_API_KEY_ALT` entry in the user's global secrets vault specifically to keep quota separate from the Loadlens project's usage of the primary key.
- `docs/superpowers/plans/2026-07-17-contact-report-modal.md` and this `HANDOFF.md` are still untracked, carried over from two sessions ago.

### Next steps
1. Push to `origin/main`.
2. Deploy to Vercel and confirm the CV generator and progress overlay work in production; confirm real serverless timeout headroom for a full AI CV-generation request, since `vercel.json` still uses the legacy `builds` config (blocks setting `maxDuration` explicitly).
3. Watch the `GEMINI_API_KEY` (ALT) quota now that Gemini is the primary CV-generation path, not a fallback: the primary `GEMINI_API_KEY` (different key, Loadlens project) hit a free-tier 429 on 2026-08-29 per the user's global key manifest. A confirmed paid-tier key (`GEMINI_API_KEY_PAID`) exists if ALT hits the same wall.
4. Decide on `uploads/Software Developer Resume.pdf` and `.docx` still being tracked in git (carried over, still unactioned).
5. Commit or discard the two untracked files above.

### Gotchas
- Werkzeug's debug reloader child process can run under a completely different Python executable than the one that launched the parent server (seen here: parent was this repo's own venv, child resolved to `AppData\Roaming\uv\python\...`). It looks exactly like an unrelated stray process squatting on the dev port, but is the live server correctly serving current code. Check the parent process's command line (`Get-CimInstance Win32_Process`) before killing what looks like a foreign process on the port.
- AVG Antivirus on this machine intercepts and can corrupt outbound HTTPS from Python, surfacing as anything from `SSL: CERTIFICATE_VERIFY_FAILED` to an outright `avgMonFltProxy` permission error mid-response. It is per-venv (a new venv needs the fix reapplied) unless a folder- or domain-level AVG exception replaces the per-venv certifi-bundle patch.

## Latest session (2026-07-17, early morning) — Vercel Analytics + Contact/Report modal

### What was done
1. **Vercel Web Analytics** — enabled on the linked project via the Vercel CLI, wired in with the plain-HTML script snippet in `base.html` (this app has no JS bundler, so the `@vercel/analytics` npm package's framework entry points don't apply). Removed the `@vercel/analytics` package, `node_modules`, and `package-lock.json` that had been installed but were unusable without a bundler. Commit `64c315d`.
2. **Contact / Report an Issue modal** — full brainstorm to implementation pipeline. Design spec adapted the copy-to-clipboard contact pattern already shipped in the `uk-immigration-compass` project (email: `developerworld.net@gmail.com`) onto this app's dark "Precision Instrument" theme. Written plan, then executed via subagent-driven development: a fresh implementer subagent per task plus a dedicated reviewer, then one final whole-branch reviewer. Result: a "Contact" link in the shared footer (visible on every page) opens a small modal with click-to-copy, reusing the cover-letter page's existing copy-to-clipboard JS pattern verbatim and only pre-existing CSS design tokens, no new colors, no form, no backend route. Commits `b3ae676` (spec), `5883e7a` (Task 1: Flask context + markup), `4e8e54d` (Task 2: CSS + JS interactivity).
3. **Review results** — both task reviews and the final whole-branch review came back clean: zero Critical or Important findings across all three passes. Only Minor, plan-scoped polish items were noted (two RGBA color literals that are colorimetrically identical to existing tokens, no ARIA dialog role, no scroll-lock).

### Current state
- Pushed to `origin/main` through `4e8e54d`.
- Full pytest suite as of that push: 64/64 passing.
- The working tree currently has uncommitted changes in `app.py` and `tests/test_app.py` that were not made by this session: a `/api/match` JSON scoring endpoint (gated by an optional `MATCH_API_KEY` env var via an `X-API-Key` header) plus 7 new pytest tests for it. These have not been reviewed or run as part of this session's work.
- `docs/superpowers/plans/2026-07-17-contact-report-modal.md` and this `HANDOFF.md` are untracked (never committed).
- The Vercel Analytics script and the CDN static-routing change from the prior session entry are both still unverified against a real deploy.

### Next steps
1. Review the uncommitted `/api/match` endpoint in `app.py` and its tests in `tests/test_app.py`; run the full suite with it included, then commit or discard.
2. Commit `docs/superpowers/plans/2026-07-17-contact-report-modal.md` and this `HANDOFF.md` update.
3. Deploy to Vercel and confirm three things live: `/static/style.css` serves from the CDN, the Vercel Analytics script loads and starts recording pageviews, and the Contact modal opens/copies correctly in production.
4. Decide on `uploads/Software Developer Resume.pdf` and `.docx` still being tracked in git (carried over, still unactioned).

## Latest session (2026-07-17, night) — Senior-level hardening pass + AI transport swap

### What was done
1. **Skill matcher precision fix** — ambiguous aliases (Go, Swift, Excel, REST, Express, Spring, Rails, R) were matching common English words ("go the extra mile", "excel at", "the rest of the team"); made uppercase-containing aliases case-sensitive, added targeted lookaheads for R&D and "Spring 2026". Commit `1b4a350`.
2. **In-memory upload parsing** — dropped the temp-file dance in `/analyze`; PyMuPDF, python-docx and olefile now all parse straight from bytes via `extract_text_from_bytes`, keeping the app genuinely stateless. Commit `22dd656`.
3. **Crash-proofed carried form data** — `/result` and `/download/report` now handle malformed or partial `analysis` JSON with a flash + redirect instead of a 500. Commit `22dd656`.
4. **AI failure visibility** — `analysis.py` now logs every AI fallback and every failed model in the OpenRouter chain (previously silent `except: pass`), and caches the outbound HTTP client per config so warm instances reuse the connection pool.
5. **Dropped the `openai` SDK entirely** — replaced with a ~20-line pooled `httpx` client hitting the chat-completions REST endpoint directly, tested via `httpx.MockTransport`. Removed the package from the venv (a botched `venv --clear` also corrupted `httpx`'s own install along the way; fixed with a full `pip install --force-reinstall`).
6. **Benchmarked free OpenRouter models** — ran the app's real analysis prompt against 6 free-tier candidates. Every pinned model either rate-limited immediately or was unreliable (one truncated its own JSON); `openrouter/free` (the auto-router) succeeded 5/5 with the lowest median latency. Set as the new default. Commit `85ba5d3`.
7. **Config hygiene** — dependency upper-bound pins in `requirements.txt`, a CDN route for `/static/*` in `vercel.json` so it stops round-tripping through the Python function, and `FLASK_DEBUG` env-gating for the dev entrypoint.

### Current state
- All 3 commits pushed to `origin/main` (`1b4a350`, `22dd656`, `85ba5d3`). Working tree clean.
- Full test suite passing: 63/63.
- venv rebuilt clean, `openai` package fully removed, verified via `pip show` and a site-packages scan.
- Live end-to-end verified against the real OpenRouter API: single request, single 200 OK, sane analysis returned.
- `vercel.json` CDN routing change is config-only and untested against a real deploy.

### Next steps
1. Deploy to Vercel and confirm `/static/style.css` serves from the CDN (not the Python function) and the homepage renders styled.
2. `uploads/Software Developer Resume.pdf` and `.docx` are still tracked in git despite the app no longer using that folder; decide whether to `git rm --cached` them (flagged, not yet actioned).
3. Consider whether `uploads/` and its `.gitkeep` are dead weight now that parsing is fully in-memory.

### Gotchas
- A `venv --clear` that hits a Windows file lock partway through can leave the venv in a silently corrupted state (empty dist-info dirs, modules that partially import but are missing attributes). If a rebuild fails on a lock, don't assume the venv is still in its pre-rebuild state; verify before continuing.
