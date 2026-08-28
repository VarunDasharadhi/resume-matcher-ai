# CV Generation Progress Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the blank/stuck-looking wait when generating an ATS CV with (1) a full-page progress overlay that opens immediately and shows an honest elapsed timer plus rotating status text, and (2) a real, visible stage boundary by splitting AI CV generation into two separate requests (draft, then an optional refine pass) instead of one opaque up-to-120-second call.

**Architecture:** `utils/analysis.py`'s `generate_ats_cv` is split into `generate_ats_cv_draft` (one AI-or-local pass) and `refine_ats_cv` (one AI refinement pass over an existing draft); `generate_ats_cv` itself becomes a thin wrapper composing the two so its existing external contract and all existing callers/tests are unaffected. `app.py` gains a new `POST /cv/refine` route and `POST /cv` is changed to call the draft-only function. `cv.html` conditionally shows a "Refine to close the gaps" action when a draft came from AI and scored under 90. A new full-page overlay (markup in `base.html`, styles in `style.css`) opens on submit of any form carrying a `data-progress` attribute and closes naturally when the resulting page loads — no new backend infrastructure, no streaming, no job storage, fully compatible with the app's existing fully-stateless, carry-state-via-POST-form architecture.

**Tech Stack:** Flask, Jinja templates, vanilla JS (no framework, matching the rest of the app), existing CSS custom-property design system in `static/style.css`.

**Spec:** No separate spec file — the design was produced directly by an architecture-review pass (Opus) earlier in this session, and approved by the user with the fuller scope ("overlay + real draft/refine split"). Key findings baked into this plan:
- The app is deliberately stateless (see `README.md`: "nothing is written to a database or disk, ever") and deployed on Vercel via the legacy `builds` config in `vercel.json`, which blocks setting `maxDuration` and has an unconfirmed history of buffering streamed responses. A polling-based or server-streamed progress design was rejected for both reasons.
- The two-request split (draft, then refine) is a genuine architectural fit: it reuses the exact same POST-form-carries-state pattern already used throughout the app (see `/cv/rescore`), requires no new infrastructure, and roughly halves the worst-case single-request duration (~120s combined -> ~60s worst case per request, since `_http_client()`/`_gemini_client()` both use a 30s timeout with up to 2 calls per pass: OpenRouter then Gemini fallback).

## Global Constraints

- No new dependencies (Flask, Jinja, vanilla JS, existing CSS tokens only).
- No em dashes and no AI-sounding phrasing in any new user-facing string (progress stage text, button labels) — this project's global copy rule.
- All new CSS must reuse existing custom properties from `static/style.css`'s `:root` block (`--ink`, `--surface`, `--surface-2`, `--line`, `--cream`, `--cream-dim`, `--muted`, `--amber`, `--sage`, `--coral`, `--shadow`, `--radius`, `--radius-sm`, `--serif`, `--sans`, `--mono`) — no new colors, no new fonts.
- The app is fully stateless: no database, no server-side session, no in-memory job/task store. All state travels via POST form fields, exactly like the existing `/analyze` -> `/result` -> `/cv` -> `/cv/rescore` flow.
- `generate_ats_cv`'s existing external contract (function name, parameters, return shape `{"cv_text", "ats", "source", "attempts"}`) must keep working unchanged — it already has 9+ passing tests in `tests/test_analysis.py` that must not need modification.
- Every existing route's validation behavior stays as-is: `/cv` requires both `resume_text` and `job_description`; `/cv/rescore` requires only `job_description` (a deliberate prior ruling: `resume_text` on that route is inert passthrough for the back-link, never scored). The new `/cv/refine` route follows the same pattern as `/cv/rescore`.

---

## File Structure

- **`utils/analysis.py`** (modified) — split `generate_ats_cv` into `generate_ats_cv_draft` (new) and `refine_ats_cv` (new); `generate_ats_cv` becomes a thin wrapper over both, unchanged externally.
- **`app.py`** (modified) — `cv_generator` (`/cv`) calls `generate_ats_cv_draft` instead of `generate_ats_cv`; new `cv_refine` route (`/cv/refine`).
- **`templates/base.html`** (modified) — new progress-overlay markup + driver script + a `pageshow`/bfcache guard that also fixes a pre-existing stuck-button bug on Back navigation.
- **`static/style.css`** (modified) — new `.pw-*` progress-overlay styles, reusing existing design tokens only.
- **`templates/result.html`** (modified) — `#cv-form-launch` gains `data-progress="cv"`.
- **`templates/cv.html`** (modified) — new conditional "Refine to close the gaps" action (own form, `data-progress="cv-refine"`).
- **`tests/test_analysis.py`** (modified) — tests for `generate_ats_cv_draft` and `refine_ats_cv`.
- **`tests/test_app.py`** (modified) — tests for the modified `/cv` route and the new `/cv/refine` route.

---

### Task 1: Split CV generation into draft + refine functions

**Files:**
- Modify: `utils/analysis.py:147-178` (the existing `generate_ats_cv` function)
- Test: `tests/test_analysis.py`

**Interfaces:**
- Consumes: existing `ai_available()`, `_cv_with_ai(resume_text, job_description, prior_ats=None)`, `_local_cv_rewrite(resume_text, job_description)`, `score_ats(cv_text, job_description)` — all already defined in `utils/analysis.py`, unchanged.
- Produces:
  - `generate_ats_cv_draft(resume_text: str, job_description: str) -> Dict` returning `{"cv_text": str, "ats": dict, "source": "ai" | "local", "attempts": 1}`.
  - `refine_ats_cv(cv_text: str, resume_text: str, job_description: str, prior_ats: Dict) -> Dict` returning `{"cv_text": str, "ats": dict, "source": "ai", "attempts": 2}`.
  - `generate_ats_cv(resume_text: str, job_description: str) -> Dict` keeps its exact existing signature and return shape (used by later tasks as a fallback path is NOT needed; the route in Task 2 calls the two new functions directly, but `generate_ats_cv` itself must keep working for its existing tests).

The current code (for reference, this is what you are replacing):

```python
def generate_ats_cv(resume_text: str, job_description: str) -> Dict:
    """Generate a tailored, ATS-optimized CV for a job description.

    AI path (when configured): one pass, scored; if under 90, one
    refinement pass fed the specific gaps from the first score, keeping
    whichever attempt scored higher. Any AI failure before a usable first
    draft exists falls back to the local rewrite; a refinement failure
    keeps the first draft. Local path (no AI key): a single deterministic
    pass via ``_local_cv_rewrite``.
    """
    if ai_available():
        try:
            first_text = _cv_with_ai(resume_text, job_description)
        except Exception as exc:
            logger.warning("AI CV generation failed, falling back to local: %s", exc)
        else:
            first_ats = score_ats(first_text, job_description)
            if first_ats["score"] >= 90:
                return {"cv_text": first_text, "ats": first_ats, "source": "ai", "attempts": 1}
            try:
                second_text = _cv_with_ai(resume_text, job_description, prior_ats=first_ats)
                second_ats = score_ats(second_text, job_description)
            except Exception as exc:
                logger.warning("AI CV refinement failed, keeping first draft: %s", exc)
                return {"cv_text": first_text, "ats": first_ats, "source": "ai", "attempts": 2}
            if second_ats["score"] >= first_ats["score"]:
                return {"cv_text": second_text, "ats": second_ats, "source": "ai", "attempts": 2}
            return {"cv_text": first_text, "ats": first_ats, "source": "ai", "attempts": 2}

    local_text = _local_cv_rewrite(resume_text, job_description)
    local_ats = score_ats(local_text, job_description)
    return {"cv_text": local_text, "ats": local_ats, "source": "local", "attempts": 1}
```

- [ ] **Step 1: Write the failing tests**

Append these to `tests/test_analysis.py` (after the existing `test_generate_ats_cv_prompt_states_no_fabrication_guardrail` test, i.e. after whatever is currently the last test in the file — check with `grep -n "^def test_" tests/test_analysis.py` and append at the end):

```python
def test_generate_ats_cv_draft_returns_ai_result_with_attempts_one(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    good_cv = "SUMMARY\nPython developer.\n\nSKILLS\nPython, Django\n"

    def fake_chat(model, prompt, **kwargs):
        return json.dumps({"cv_text": good_cv})

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    result = analysis.generate_ats_cv_draft("Python developer.", "Need Python and Django.")
    assert result["source"] == "ai"
    assert result["attempts"] == 1
    assert result["cv_text"] == good_cv
    assert 0 <= result["ats"]["score"] <= 100


def test_generate_ats_cv_draft_does_not_auto_refine_when_under_ninety(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    weak_cv = "SKILLS\nPython\n"
    calls = []

    def fake_chat(model, prompt, **kwargs):
        calls.append(prompt)
        return json.dumps({"cv_text": weak_cv})

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    result = analysis.generate_ats_cv_draft(
        "Python developer.", "Need a Python developer with Django, AWS and Docker."
    )
    assert result["attempts"] == 1
    assert result["cv_text"] == weak_cv
    assert len(calls) == 1  # draft never triggers a second AI call on its own


def test_generate_ats_cv_draft_without_key_uses_local(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = analysis.generate_ats_cv_draft(
        "Python developer with Django and AWS experience.",
        "Need a Python developer with Django, AWS and Kubernetes.",
    )
    assert result["source"] == "local"
    assert result["attempts"] == 1
    assert "Python developer with Django and AWS experience." in result["cv_text"]


def test_generate_ats_cv_draft_falls_back_to_local_when_ai_fails_outright(monkeypatch, caplog):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(analysis, "_chat_completion", boom)
    with caplog.at_level(logging.WARNING, logger="utils.analysis"):
        result = analysis.generate_ats_cv_draft(
            "Python developer.", "Need a Python developer with Django."
        )
    assert result["source"] == "local"
    assert result["attempts"] == 1
    assert any("network down" in r.getMessage() for r in caplog.records)


def test_refine_ats_cv_returns_refined_when_it_scores_higher(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    weak_cv = "SKILLS\nPython\n"
    strong_cv = (
        "John Doe\njohn.doe@example.com | (555) 123-4567\n\n"
        "SUMMARY\nPython developer with 5 years building Django services on AWS.\n\n"
        "EXPERIENCE\nBackend Engineer, Acme Corp\n"
        "- Reduced API latency by 40% by migrating to Django and AWS Lambda.\n"
        "- Led a team of 3 engineers, shipping 12 releases in 2025.\n\n"
        "EDUCATION\nB.S. Computer Science, State University\n\n"
        "SKILLS\nPython, Django, AWS, Docker, PostgreSQL\n"
    )
    prior_ats = analysis.score_ats(weak_cv, "Need a Python developer with Django, AWS and Docker.")
    calls = []

    def fake_chat(model, prompt, **kwargs):
        calls.append(prompt)
        return json.dumps({"cv_text": strong_cv})

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    result = analysis.refine_ats_cv(
        weak_cv,
        "Python developer.",
        "Need a Python developer with Django, AWS and Docker.",
        prior_ats,
    )
    assert result["source"] == "ai"
    assert result["attempts"] == 2
    assert result["cv_text"] == strong_cv
    assert len(calls) == 1
    # the refine prompt must reference the prior attempt's specific gaps
    assert "Django" in calls[0] or "AWS" in calls[0] or "Docker" in calls[0]


def test_refine_ats_cv_keeps_prior_draft_when_refinement_scores_lower(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    decent_cv = "SUMMARY\nOK\n\nSKILLS\nPython, Django, AWS\n"
    worse_cv = "SKILLS\nPython\n"
    prior_ats = analysis.score_ats(decent_cv, "Need a Python developer with Django, AWS and Docker.")

    def fake_chat(model, prompt, **kwargs):
        return json.dumps({"cv_text": worse_cv})

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    result = analysis.refine_ats_cv(
        decent_cv,
        "Python developer.",
        "Need a Python developer with Django, AWS and Docker.",
        prior_ats,
    )
    assert result["attempts"] == 2
    assert result["cv_text"] == decent_cv
    assert result["ats"] == prior_ats


def test_refine_ats_cv_failure_keeps_prior_draft(monkeypatch, caplog):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    weak_cv = "SKILLS\nPython\n"
    prior_ats = analysis.score_ats(weak_cv, "Need a Python developer with Django.")

    def boom(*args, **kwargs):
        raise RuntimeError("429 rate limited")

    monkeypatch.setattr(analysis, "_chat_completion", boom)
    with caplog.at_level(logging.WARNING, logger="utils.analysis"):
        result = analysis.refine_ats_cv(
            weak_cv, "Python developer.", "Need a Python developer with Django.", prior_ats
        )
    assert result["source"] == "ai"
    assert result["attempts"] == 2
    assert result["cv_text"] == weak_cv
    assert result["ats"] == prior_ats
    assert any("429 rate limited" in r.getMessage() for r in caplog.records)


def test_generate_ats_cv_still_composes_draft_and_refine(monkeypatch):
    """generate_ats_cv's existing external contract must be unaffected by the split."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    weak_cv = "SKILLS\nPython\n"
    strong_cv = (
        "John Doe\njohn.doe@example.com | (555) 123-4567\n\n"
        "SUMMARY\nPython developer with 5 years building Django services on AWS.\n\n"
        "EXPERIENCE\nBackend Engineer, Acme Corp\n"
        "- Reduced API latency by 40% by migrating to Django and AWS Lambda.\n"
        "- Led a team of 3 engineers, shipping 12 releases in 2025.\n\n"
        "EDUCATION\nB.S. Computer Science, State University\n\n"
        "SKILLS\nPython, Django, AWS, Docker, PostgreSQL\n"
    )
    responses = [json.dumps({"cv_text": weak_cv}), json.dumps({"cv_text": strong_cv})]
    calls = []

    def fake_chat(model, prompt, **kwargs):
        calls.append(prompt)
        return responses[len(calls) - 1]

    monkeypatch.setattr(analysis, "_chat_completion", fake_chat)
    result = analysis.generate_ats_cv(
        "Python developer.", "Need a Python developer with Django, AWS and Docker."
    )
    assert result["source"] == "ai"
    assert result["attempts"] == 2
    assert result["cv_text"] == strong_cv
    assert len(calls) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_analysis.py -k "draft or refine_ats_cv or still_composes" -v`
Expected: FAIL with `AttributeError: module 'utils.analysis' has no attribute 'generate_ats_cv_draft'` (and similarly for `refine_ats_cv`).

- [ ] **Step 3: Replace the implementation**

In `utils/analysis.py`, replace the entire existing `generate_ats_cv` function (lines 147-178, shown above under "The current code") with:

```python
def generate_ats_cv_draft(resume_text: str, job_description: str) -> Dict:
    """Generate the first-pass tailored CV: one AI attempt, or the local
    rewrite if AI is unavailable or fails outright. Never auto-refines;
    callers decide whether to call refine_ats_cv based on the score.
    """
    if ai_available():
        try:
            text = _cv_with_ai(resume_text, job_description)
        except Exception as exc:
            logger.warning("AI CV generation failed, falling back to local: %s", exc)
        else:
            ats = score_ats(text, job_description)
            return {"cv_text": text, "ats": ats, "source": "ai", "attempts": 1}

    local_text = _local_cv_rewrite(resume_text, job_description)
    local_ats = score_ats(local_text, job_description)
    return {"cv_text": local_text, "ats": local_ats, "source": "local", "attempts": 1}


def refine_ats_cv(
    cv_text: str, resume_text: str, job_description: str, prior_ats: Dict
) -> Dict:
    """One AI refinement pass over an existing AI-sourced draft, fed the
    specific gaps from prior_ats. Keeps the prior draft if the refinement
    fails or scores no higher. Always returns attempts=2, source="ai" (this
    is only meaningful to call on a draft that came from AI).
    """
    try:
        refined_text = _cv_with_ai(resume_text, job_description, prior_ats=prior_ats)
        refined_ats = score_ats(refined_text, job_description)
    except Exception as exc:
        logger.warning("AI CV refinement failed, keeping prior draft: %s", exc)
        return {"cv_text": cv_text, "ats": prior_ats, "source": "ai", "attempts": 2}
    if refined_ats["score"] >= prior_ats["score"]:
        return {"cv_text": refined_text, "ats": refined_ats, "source": "ai", "attempts": 2}
    return {"cv_text": cv_text, "ats": prior_ats, "source": "ai", "attempts": 2}


def generate_ats_cv(resume_text: str, job_description: str) -> Dict:
    """Generate a tailored, ATS-optimized CV for a job description.

    Full two-pass convenience wrapper over generate_ats_cv_draft and
    refine_ats_cv: one AI pass, scored; if under 90 and the draft came from
    AI, one refinement pass. Kept for callers that want the combined result
    in one call; the web UI drives the two passes as separate requests
    instead (see /cv and /cv/refine in app.py) so progress is visible.
    """
    draft = generate_ats_cv_draft(resume_text, job_description)
    if draft["source"] != "ai" or draft["ats"]["score"] >= 90:
        return draft
    return refine_ats_cv(draft["cv_text"], resume_text, job_description, draft["ats"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_analysis.py -v`
Expected: PASS, all tests including the pre-existing `generate_ats_cv` tests (they must still pass unchanged — the wrapper preserves the exact prior behavior).

- [ ] **Step 5: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass, pristine output (no warnings).

- [ ] **Step 6: Commit**

```bash
git add utils/analysis.py tests/test_analysis.py
git commit -m "Split CV generation into separate draft and refine passes"
```

---

### Task 2: `/cv/refine` route and updated `/cv` route

**Files:**
- Modify: `app.py:184-203` (the `cv_generator` route)
- Create: new route `cv_refine` in `app.py`, placed immediately after `cv_rescore` (currently ending around line 228) and before `download_cv` (currently starting around line 231)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `generate_ats_cv_draft(resume_text, job_description) -> Dict` and `refine_ats_cv(cv_text, resume_text, job_description, prior_ats) -> Dict` from Task 1, already importable from `utils.analysis`.
- Produces: `POST /cv` (existing, behavior changed: draft-only, no auto-refine) and `POST /cv/refine` (new) — both render `cv.html` with the same template variables the route already passes today (`cv_text`, `ats`, `source`, `attempts`, `resume_text`, `job_description`, `analysis_json`), so Task 4's template changes can rely on these existing variable names plus one new one: `can_refine` (bool), computed in the route as `source == "ai" and ats["score"] < 90`.

Current `app.py` imports (near the top, confirm this exact line exists before editing):

```python
from utils.analysis import (
    ai_available,
    analyze_resume,
    generate_ats_cv,
    generate_cover_letter,
    provider_label,
)
```

(If the exact import list differs slightly, that's fine — just add `generate_ats_cv_draft` and `refine_ats_cv` to whatever import block pulls from `utils.analysis`. `generate_ats_cv` itself is no longer called from `app.py` after this task, but leave the import in place only if something else in the file still needs it — check with `grep -n "generate_ats_cv(" app.py` after this task; if the only remaining reference is inside `utils/analysis.py` itself, remove `generate_ats_cv` from `app.py`'s import list since importing an unused name is dead weight.)

Current `cv_generator` and `cv_rescore` routes (for reference):

```python
@app.route("/cv", methods=["POST"])
def cv_generator():
    resume_text = (request.form.get("resume_text") or "").strip()
    job_description = (request.form.get("job_description") or "").strip()
    analysis_json = request.form.get("analysis", "{}")
    if not resume_text or not job_description:
        flash("That session data was lost. Please run the analysis again.")
        return redirect(url_for("index"))

    result = generate_ats_cv(resume_text, job_description)
    return render_template(
        "cv.html",
        cv_text=result["cv_text"],
        ats=result["ats"],
        source=result["source"],
        attempts=result["attempts"],
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
        resume_text=resume_text,
        job_description=job_description,
        analysis_json=analysis_json,
    )
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py` (check current content first with `grep -n "^def test_cv" tests/test_app.py` — append after the last CV-related test, e.g. after `test_download_cv_returns_pdf`):

```python
def test_cv_generator_no_longer_auto_refines(client, monkeypatch):
    """/cv now returns the single-pass draft; a weak AI draft must NOT be
    silently upgraded to a second pass within this one request."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    calls = []

    def fake_chat(model, prompt, **kwargs):
        calls.append(prompt)
        return json.dumps({"cv_text": "SKILLS\nPython\n"})

    monkeypatch.setattr(app_module.analysis, "_chat_completion", fake_chat)
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

    monkeypatch.setattr(app_module.analysis, "_chat_completion", fake_chat)
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

    monkeypatch.setattr(app_module.analysis, "_chat_completion", fake_chat)
    prior_ats_json = json.dumps(
        app_module.score_ats("SKILLS\nPython\n", "Need a Python developer with Django, AWS and Docker.")
    )
    resp = client.post("/cv/refine", data={
        "cv_text": "SKILLS\nPython\n",
        "prior_ats": prior_ats_json,
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
```

Check the top of `tests/test_app.py` for its existing `client` fixture and the `import app as app_module` line (already present per the file's header comment "Each test forces local-engine mode... via the `client` fixture") — these new tests reuse that exact fixture, no new imports needed beyond what's already there (`json` is already imported per Task 1's sibling file pattern; verify with `grep -n "^import json" tests/test_app.py` and add it if missing).

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_app.py -k "cv_generator_no_longer_auto_refines or hides_refine or cv_refine" -v`
Expected: FAIL — `test_cv_generator_no_longer_auto_refines` fails because `/cv` still auto-refines (2 calls, not 1) and `b"Refine to close the gaps"` doesn't exist yet anywhere; `test_cv_refine_improves_score_and_renders` and `test_cv_refine_missing_job_description_redirects` fail with 404 (route doesn't exist yet).

- [ ] **Step 3: Update the routes**

In `app.py`, replace the import line so `generate_ats_cv_draft` and `refine_ats_cv` are available (keep `generate_ats_cv` in the import only if `grep -n "generate_ats_cv(" app.py` still shows a use of it elsewhere after this task; otherwise drop it):

```python
from utils.analysis import (
    ai_available,
    analyze_resume,
    generate_ats_cv_draft,
    generate_cover_letter,
    provider_label,
    refine_ats_cv,
)
```

Replace the `cv_generator` route body:

```python
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
```

Add the new route immediately after `cv_rescore` (before `download_cv`):

```python
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
```

Also update `cv_rescore` to pass `can_refine=False` (it doesn't offer refinement, since a manually-edited CV isn't a fresh AI draft):

```python
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
```

`json` must already be imported at the top of `app.py` (it is — used for `_carried_analysis`); confirm with `grep -n "^import json" app.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_app.py -v`
Expected: all pass, including pre-existing CV route tests (`test_cv_generator_local_engine_renders`, `test_cv_rescore_preserves_edited_text_and_rescoring`, etc.) — none of those assert on call counts or the refine button, so they're unaffected by this change. Note `test_cv_generator_no_longer_auto_refines` and `test_cv_refine_improves_score_and_renders` will still fail at this step because `cv.html` doesn't render "Refine to close the gaps" yet — that's Task 4. Confirm they fail ONLY on that specific assertion (`assert b"Refine to close the gaps"...`), not on route/500 errors, before moving on.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "Add /cv/refine route; /cv now returns a single-pass draft"
```

---

### Task 3: Progress overlay markup, styles, and driver script

**Files:**
- Modify: `templates/base.html` (add overlay markup after the existing `#contact-overlay` block, add a driver script after the existing `[data-action-group]` script)
- Modify: `static/style.css` (append new `.pw-*` rules after the existing `/* --- ATS CV generator --- */` section at the end of the file)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: nothing from other tasks — this is a self-contained frontend addition.
- Produces: any page can opt in by adding `data-progress="<stage-key>"` to a `<form>` element. The driver script (defined here) recognizes the stage keys `"cv"` and `"cv-refine"` (both used by Task 4). Global JS functions `openProgressOverlay(stageKey)` are NOT exposed globally on purpose (keep it an IIFE like the rest of `base.html`'s scripts) — Task 4 does not call any JS directly, it only adds the `data-progress` attribute to forms, which this task's script already listens for on page load via `document.querySelectorAll('form[data-progress]')`.

Current end of `templates/base.html` (for reference — the exact insertion points):

```html
  <div class="modal-overlay" id="contact-overlay">
    <div class="modal-card">
      <button type="button" class="modal-close" id="contact-close" aria-label="Close">✕</button>
      <div class="modal-icon">✉</div>
      <h3 class="modal-title">Get in touch</h3>
      <p class="modal-body">Found a bug, have feedback, or want to report an issue? Reach out anytime.</p>
      <button type="button" class="modal-copy" id="contact-copy">
        <span id="contact-email-text">{{ contact_email }}</span>
        <span class="modal-copy-icon" aria-hidden="true">⧉</span>
      </button>
      <p class="modal-copy-hint" id="contact-copy-hint">Tap to copy the email address</p>
    </div>
  </div>

  {% block scripts %}{% endblock %}
```

and near the end of the file:

```html
  <script>
    // Shared click feedback: within an [data-action-group], clicking one action
    // marks it active and dims the siblings so it's clear what was clicked and
    // users don't double-trigger. Transient actions (downloads, plain buttons)
    // auto-restore; navigations/submits stay until the page changes.
    document.querySelectorAll('[data-action-group]').forEach(group => {
      const items = Array.from(group.querySelectorAll('button, a.cta'));
      items.forEach(item => {
        item.addEventListener('click', () => {
          if (item.classList.contains('is-dimmed') || item.disabled) return;
          const form = item.closest('form');
          const action = form ? (form.getAttribute('action') || '') : '';
          const isDownload = item.hasAttribute('download') ||
            (item.getAttribute('href') || '').includes('/download/') ||
            action.includes('/download/');
          const navigates = !isDownload && (
            item.tagName === 'A' ||
            (item.tagName === 'BUTTON' && item.type === 'submit'));

          item.classList.add('is-active');
          items.forEach(other => { if (other !== item) other.classList.add('is-dimmed'); });

          if (!navigates) {
            setTimeout(() => {
              item.classList.remove('is-active');
              items.forEach(other => other.classList.remove('is-dimmed'));
            }, 1800);
          }
        });
      });
    });
  </script>
</body>
</html>
```

- [ ] **Step 1: Write the failing test**

Append to `tests/test_app.py`:

```python
def test_index_page_includes_progress_overlay_markup(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'id="progress-overlay"' in resp.data
    assert b'id="pw-stage"' in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_app.py -k test_index_page_includes_progress_overlay_markup -v`
Expected: FAIL, `id="progress-overlay"` not found in response.

- [ ] **Step 3: Add the overlay markup**

In `templates/base.html`, insert this new block immediately after the closing `</div>` of `#contact-overlay` and before `{% block scripts %}{% endblock %}`:

```html
  <div class="pw-overlay" id="progress-overlay" role="status" aria-live="polite">
    <div class="pw-card">
      <div class="pw-ring" aria-hidden="true"></div>
      <p class="pw-eyebrow" id="pw-eyebrow">Working</p>
      <h3 class="pw-stage" id="pw-stage">Getting started</h3>
      <div class="pw-bar" aria-hidden="true"><span class="pw-bar-fill" id="pw-bar-fill"></span></div>
      <p class="pw-meta"><span id="pw-elapsed">0:00</span> elapsed. Keep this tab open.</p>
    </div>
  </div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_app.py -k test_index_page_includes_progress_overlay_markup -v`
Expected: PASS.

- [ ] **Step 5: Add the CSS**

Append to the end of `static/style.css` (after the existing `.cv-editor-actions` rule, which is currently the last rule in the file):

```css
/* --- progress overlay --- */
.pw-overlay {
  display: none; position: fixed; inset: 0; z-index: 60;
  align-items: center; justify-content: center; padding: 20px;
  background: rgba(20,17,15,.82); backdrop-filter: blur(8px);
}
.pw-overlay.is-open { display: flex; }
.pw-card {
  width: 100%; max-width: 420px; text-align: center;
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius); box-shadow: var(--shadow);
  padding: 34px 30px 28px;
}
.pw-ring {
  width: 44px; height: 44px; margin: 0 auto 18px; border-radius: 50%;
  border: 2.5px solid var(--line); border-top-color: var(--amber);
  animation: spin .8s linear infinite;
}
.pw-eyebrow {
  font-family: var(--mono); font-size: .68rem; text-transform: uppercase;
  letter-spacing: .16em; color: var(--muted); margin: 0 0 8px;
}
.pw-stage {
  font-family: var(--serif); font-size: 1.2rem; font-weight: 500;
  color: var(--cream); margin: 0 0 20px; min-height: 2.6em;
  display: flex; align-items: center; justify-content: center;
}
.pw-bar {
  height: 4px; background: var(--surface-2); border-radius: 100px; overflow: hidden;
}
.pw-bar-fill {
  display: block; height: 100%; width: 0; background: var(--amber);
  transition: width .4s linear;
}
.pw-meta { font-family: var(--mono); font-size: .72rem; color: var(--muted); margin: 12px 0 0; }
```

- [ ] **Step 6: Add the driver script**

In `templates/base.html`, insert this new `<script>` block immediately after the existing `[data-action-group]` script (right before `</body>`):

```html
  <script>
    // Full-page progress overlay for actions that can take a while (AI CV
    // generation/refinement). Purely client-side: a timer-driven stage
    // label and an asymptotic progress bar, not tied to real backend
    // state, closes naturally when the real response replaces the page.
    (function () {
      const overlay = document.getElementById('progress-overlay');
      const stageEl = document.getElementById('pw-stage');
      const barFill = document.getElementById('pw-bar-fill');
      const elapsedEl = document.getElementById('pw-elapsed');
      if (!overlay) return;

      const STAGES = {
        cv: [
          [0, 'Reading your resume and the job description'],
          [3, 'Drafting a CV tailored to this role'],
          [20, 'Checking it against ATS rules'],
          [35, 'Free AI models are busy right now. Still working.'],
          [50, 'Almost there. This one is taking longer than usual.'],
        ],
        'cv-refine': [
          [0, 'Reading the current draft and its ATS score'],
          [3, 'Rewriting the sections that are losing points'],
          [20, 'Re-checking it against ATS rules'],
          [35, 'Free AI models are busy right now. Still working.'],
          [50, 'Almost there. This one is taking longer than usual.'],
        ],
      };

      let timer = null;
      let startedAt = 0;

      function tick(stages) {
        const elapsedMs = Date.now() - startedAt;
        const elapsedSec = elapsedMs / 1000;

        let label = stages[0][1];
        for (const [at, text] of stages) {
          if (elapsedSec >= at) label = text;
        }
        stageEl.textContent = label;

        const pct = 92 * (1 - Math.exp(-elapsedSec / 28));
        barFill.style.width = pct + '%';

        const totalSeconds = Math.floor(elapsedSec);
        const m = Math.floor(totalSeconds / 60);
        const s = String(totalSeconds % 60).padStart(2, '0');
        elapsedEl.textContent = m + ':' + s;
      }

      function openOverlay(stageKey) {
        const stages = STAGES[stageKey] || STAGES.cv;
        startedAt = Date.now();
        barFill.style.width = '0%';
        stageEl.textContent = stages[0][1];
        elapsedEl.textContent = '0:00';
        overlay.classList.add('is-open');
        timer = setInterval(() => tick(stages), 250);
      }

      function closeOverlay() {
        overlay.classList.remove('is-open');
        if (timer) { clearInterval(timer); timer = null; }
      }

      document.querySelectorAll('form[data-progress]').forEach(form => {
        form.addEventListener('submit', () => {
          openOverlay(form.getAttribute('data-progress'));
        });
      });

      // bfcache guard: if the user navigates Back/Forward onto a page that
      // still has the overlay marked open (or stuck is-active/is-dimmed
      // button state from the shared click-feedback script above), clear
      // it. Without this, Back onto a page mid-submit restores a page with
      // a permanently stuck overlay and disabled buttons.
      window.addEventListener('pageshow', e => {
        if (!e.persisted) return;
        closeOverlay();
        document.querySelectorAll('.is-dimmed').forEach(el => el.classList.remove('is-dimmed'));
        document.querySelectorAll('.is-active').forEach(el => el.classList.remove('is-active'));
        document.querySelectorAll('.cta.is-loading').forEach(el => {
          el.classList.remove('is-loading');
          el.disabled = false;
        });
      });
    })();
  </script>
```

- [ ] **Step 7: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add templates/base.html static/style.css tests/test_app.py
git commit -m "Add client-side progress overlay for long-running actions"
```

---

### Task 4: Wire the overlay and refine action into the CV pages

**Files:**
- Modify: `templates/result.html:43-51` (the `#cv-form-launch` form)
- Modify: `templates/cv.html` (add the conditional refine action, add `data-progress` attributes)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: the `data-progress` attribute mechanism from Task 3 (stage keys `"cv"` and `"cv-refine"`); the `can_refine` template variable from Task 2's routes.
- Produces: nothing further consumed by other tasks — this is the last task.

Current `templates/result.html` CV launch form (for reference):

```html
      <form method="post" action="{{ url_for('cv_generator') }}" id="cv-form-launch">
        <textarea name="resume_text" hidden>{{ resume_text }}</textarea>
        <textarea name="job_description" hidden>{{ job_description }}</textarea>
        <input type="hidden" name="analysis" value="{{ analysis_json }}">
        <button type="submit" class="cta cta-ghost" id="cv-btn">
          <span class="cta-label">📄 Generate ATS CV</span>
          <span class="cta-spinner" aria-hidden="true"></span>
        </button>
      </form>
```

Current `templates/cv.html` in full (for reference — you are modifying the `<section class="score-block">` block and the `<section class="cv-editor">` block):

```html
{% extends "base.html" %}
{% block title %}Tailored CV | AI Resume Matcher{% endblock %}

{% block content %}
<section class="result-head">
  <p class="eyebrow">
    <span class="eyebrow-num">06</span> / Tailored CV
    {% if source %}
    <span class="src-tag {% if source == 'ai' %}src-ai{% endif %}">
      {% if source == 'ai' %}AI, {{ attempts }} pass{{ 'es' if attempts != 1 else '' }}{% else %}Local engine{% endif %}
    </span>
    {% endif %}
  </p>
  <form method="post" action="{{ url_for('result') }}" class="back-form">
    <textarea name="resume_text" hidden>{{ resume_text }}</textarea>
    <textarea name="job_description" hidden>{{ job_description }}</textarea>
    <input type="hidden" name="analysis" value="{{ analysis_json }}">
    <button type="submit" class="back-link back-link--btn">← Back to report</button>
  </form>
</section>

<section class="score-block">
  <div class="gauge" data-score="{{ ats.score }}">
    <svg viewBox="0 0 200 200" class="gauge-svg" aria-hidden="true">
      <circle class="gauge-track" cx="100" cy="100" r="86"></circle>
      <circle class="gauge-fill" cx="100" cy="100" r="86"></circle>
    </svg>
    <div class="gauge-center">
      <span class="gauge-num" id="ats-gauge-num">0</span>
      <span class="gauge-unit">/100</span>
    </div>
  </div>
  <div class="score-copy">
    <h1 class="score-verdict" id="ats-verdict">ATS score</h1>
    <p class="score-summary">
      {% if ats.score >= 90 %}Ready to submit. This CV clears a 90+ ATS screen.
      {% elif ats.score >= 70 %}Close. Edit below to close the remaining gaps.
      {% else %}Needs work. Edit below, then re-check the score.
      {% endif %}
    </p>
    <ul class="ats-breakdown">
      <li class="ats-row"><span>Keyword coverage</span><strong>{{ ats.coverage.score }}/50</strong></li>
      <li class="ats-row"><span>Standard sections</span><strong>{{ ats.sections.score }}/20</strong></li>
      <li class="ats-row"><span>Contact info</span><strong>{{ ats.contact_info.score }}/10</strong></li>
      <li class="ats-row"><span>Quantified achievements</span><strong>{{ ats.quantified_achievements.score }}/10</strong></li>
      <li class="ats-row"><span>Keyword placement</span><strong>{{ ats.keyword_placement.score }}/10</strong></li>
    </ul>
    {% if ats.coverage.missing_skills %}
    <p class="ats-hint">Still missing: {{ ats.coverage.missing_skills | join(', ') }}</p>
    {% endif %}
    {% if ats.sections.missing %}
    <p class="ats-hint">Missing sections: {{ ats.sections.missing | join(', ') }}</p>
    {% endif %}
  </div>
</section>

<section class="cv-editor">
  <form method="post" action="{{ url_for('cv_rescore') }}" id="cv-form">
    <textarea name="cv_text" id="cv-textarea" class="cv-textarea" spellcheck="false">{{ cv_text }}</textarea>
    <textarea name="job_description" hidden>{{ job_description }}</textarea>
    <textarea name="resume_text" hidden>{{ resume_text }}</textarea>
    <input type="hidden" name="analysis" value="{{ analysis_json }}">
    <div class="cv-editor-actions" data-action-group>
      <button type="submit" class="cta cta-ghost" id="rescore-btn">
        <span class="cta-label">↻ Re-check ATS score</span>
        <span class="cta-spinner" aria-hidden="true"></span>
      </button>
      <button type="submit" form="download-cv-form" class="cta cta-amber" id="download-cv-btn">⬇ Download PDF</button>
    </div>
  </form>
  <form method="post" action="{{ url_for('download_cv') }}" id="download-cv-form" hidden>
    <textarea name="cv_text" id="download-cv-text"></textarea>
  </form>
</section>
{% endblock %}

{% block scripts %}
<script>
  (function () {
    const gauge = document.querySelector('.gauge');
    const fill = document.querySelector('.gauge-fill');
    const numEl = document.getElementById('ats-gauge-num');
    const verdict = document.getElementById('ats-verdict');
    const score = parseInt(gauge.dataset.score, 10) || 0;

    const r = 86, circ = 2 * Math.PI * r;
    fill.style.strokeDasharray = circ;
    fill.style.strokeDashoffset = circ;

    let hue = '#e0533a';
    if (score >= 90) hue = '#7fb069';
    else if (score >= 70) hue = '#e0a83d';
    fill.style.stroke = hue;
    numEl.style.color = hue;
    verdict.textContent = score >= 90 ? 'Strong ATS score'
      : score >= 70 ? 'Close to ready' : 'Needs work';

    requestAnimationFrame(() => {
      fill.style.strokeDashoffset = circ * (1 - score / 100);
    });

    const dur = 900, start = performance.now();
    function tick(now) {
      const p = Math.min((now - start) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      numEl.textContent = Math.round(eased * score);
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);

    document.getElementById('cv-form').addEventListener('submit', () => {
      const btn = document.getElementById('rescore-btn');
      btn.classList.add('is-loading');
      btn.disabled = true;
    });

    document.getElementById('download-cv-btn').addEventListener('click', () => {
      document.getElementById('download-cv-text').value =
        document.getElementById('cv-textarea').value;
    });
  })();
</script>
{% endblock %}
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py`:

```python
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

    monkeypatch.setattr(app_module.analysis, "_chat_completion", fake_chat)
    resp = client.post("/cv", data={
        "resume_text": "Python developer.",
        "job_description": "Need a Python developer with Django, AWS and Docker.",
    })
    assert b'data-progress="cv-refine"' in resp.data
```

(Check `_pdf_bytes` and the `BytesIO`/`json` imports already exist at the top of `tests/test_app.py` — they're used by other existing tests in the file, e.g. `test_result_page_shows_generate_cv_button`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_app.py -k "progress_attribute" -v`
Expected: FAIL, neither attribute exists yet.

- [ ] **Step 3: Update `templates/result.html`**

Change the `#cv-form-launch` form's opening tag to add `data-progress="cv"`:

```html
      <form method="post" action="{{ url_for('cv_generator') }}" id="cv-form-launch" data-progress="cv">
```

(Leave the rest of that form's contents unchanged.)

- [ ] **Step 4: Update `templates/cv.html`**

Replace the `<p class="score-summary">...</p>` block through the end of `.score-copy`'s ats-hint paragraphs (i.e. everything from `<p class="score-summary">` down to the closing `{% endif %}` of the "Missing sections" hint) with the same content plus a new conditional refine action appended after it:

```html
    <p class="score-summary">
      {% if ats.score >= 90 %}Ready to submit. This CV clears a 90+ ATS screen.
      {% elif ats.score >= 70 %}Close. Edit below to close the remaining gaps.
      {% else %}Needs work. Edit below, then re-check the score.
      {% endif %}
    </p>
    <ul class="ats-breakdown">
      <li class="ats-row"><span>Keyword coverage</span><strong>{{ ats.coverage.score }}/50</strong></li>
      <li class="ats-row"><span>Standard sections</span><strong>{{ ats.sections.score }}/20</strong></li>
      <li class="ats-row"><span>Contact info</span><strong>{{ ats.contact_info.score }}/10</strong></li>
      <li class="ats-row"><span>Quantified achievements</span><strong>{{ ats.quantified_achievements.score }}/10</strong></li>
      <li class="ats-row"><span>Keyword placement</span><strong>{{ ats.keyword_placement.score }}/10</strong></li>
    </ul>
    {% if ats.coverage.missing_skills %}
    <p class="ats-hint">Still missing: {{ ats.coverage.missing_skills | join(', ') }}</p>
    {% endif %}
    {% if ats.sections.missing %}
    <p class="ats-hint">Missing sections: {{ ats.sections.missing | join(', ') }}</p>
    {% endif %}
    {% if can_refine %}
    <form method="post" action="{{ url_for('cv_refine') }}" id="cv-refine-form" data-progress="cv-refine">
      <textarea name="cv_text" id="refine-cv-text" hidden></textarea>
      <input type="hidden" name="prior_ats" value='{{ ats | tojson }}'>
      <textarea name="job_description" hidden>{{ job_description }}</textarea>
      <textarea name="resume_text" hidden>{{ resume_text }}</textarea>
      <input type="hidden" name="analysis" value="{{ analysis_json }}">
      <button type="submit" class="cta cta-amber" id="refine-btn">
        <span class="cta-label">✦ Refine to close the gaps</span>
        <span class="cta-spinner" aria-hidden="true"></span>
      </button>
    </form>
    {% endif %}
```

Note the refine form's `cv_text` field starts empty and hidden (`id="refine-cv-text"`) — it must be filled with the LIVE textarea content at submit time, same pattern as the existing download form. Add this to the scripts block.

Replace the entire `{% block scripts %}...{% endblock %}` block with:

```html
{% block scripts %}
<script>
  (function () {
    const gauge = document.querySelector('.gauge');
    const fill = document.querySelector('.gauge-fill');
    const numEl = document.getElementById('ats-gauge-num');
    const verdict = document.getElementById('ats-verdict');
    const score = parseInt(gauge.dataset.score, 10) || 0;

    const r = 86, circ = 2 * Math.PI * r;
    fill.style.strokeDasharray = circ;
    fill.style.strokeDashoffset = circ;

    let hue = '#e0533a';
    if (score >= 90) hue = '#7fb069';
    else if (score >= 70) hue = '#e0a83d';
    fill.style.stroke = hue;
    numEl.style.color = hue;
    verdict.textContent = score >= 90 ? 'Strong ATS score'
      : score >= 70 ? 'Close to ready' : 'Needs work';

    requestAnimationFrame(() => {
      fill.style.strokeDashoffset = circ * (1 - score / 100);
    });

    const dur = 900, start = performance.now();
    function tick(now) {
      const p = Math.min((now - start) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      numEl.textContent = Math.round(eased * score);
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);

    document.getElementById('cv-form').addEventListener('submit', () => {
      const btn = document.getElementById('rescore-btn');
      btn.classList.add('is-loading');
      btn.disabled = true;
    });

    document.getElementById('download-cv-btn').addEventListener('click', () => {
      document.getElementById('download-cv-text').value =
        document.getElementById('cv-textarea').value;
    });

    const refineForm = document.getElementById('cv-refine-form');
    if (refineForm) {
      refineForm.addEventListener('submit', () => {
        document.getElementById('refine-cv-text').value =
          document.getElementById('cv-textarea').value;
        const btn = document.getElementById('refine-btn');
        btn.classList.add('is-loading');
        btn.disabled = true;
      });
    }
  })();
</script>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_app.py -v`
Expected: all pass, including the two tests left over from Task 2 (`test_cv_generator_no_longer_auto_refines`, `test_cv_refine_improves_score_and_renders`) that were waiting on this template change.

- [ ] **Step 6: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass, pristine output.

- [ ] **Step 7: Commit**

```bash
git add templates/result.html templates/cv.html tests/test_app.py
git commit -m "Wire progress overlay and refine action into the CV pages"
```

---

## Manual Verification (controller, after all tasks)

Automated tests cover the backend contract and template markup, but the actual overlay behavior (timer, bar easing, bfcache guard) is JS that pytest cannot exercise. Before considering this done:

1. Start the dev server and run the full "Generate ATS CV" flow in a real browser (or headless Playwright), watching for: the overlay opens immediately on click (no blank gap), the stage text and elapsed timer update, the overlay closes cleanly when the result page loads.
2. If the draft scores under 90 and came from AI, confirm the "Refine to close the gaps" button appears, and clicking it opens the overlay again (with the `cv-refine` stage copy) and lands on an updated page showing "AI, 2 passes" with the refine button gone.
3. Confirm the local-engine path (no AI key, or force a failure) still renders correctly with no refine button and no overlay getting stuck.
4. Click Back after generating a CV, then Forward, and confirm no stuck overlay or permanently-disabled button (the bfcache guard from Task 3).
