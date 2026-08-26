# ATS-Optimized CV Generator — Design

## Overview

Add a CV generator to the existing AI Resume Matcher app: given the resume and
job description a user already submitted, produce a tailored, ATS-optimized
rewrite of the resume, score it against a dedicated ATS-scoring model
(distinct from the existing coarse match score), automatically retry once via
AI if it lands under 90/100, then let the user edit the result in a textarea,
re-check the score against their edits, and download the final version as a
PDF.

## Goals

- Generate a CV rewrite tailored to a specific job description, from the
  resume text the app already extracted.
- Score the generated CV with a dedicated ATS scorer (keyword coverage,
  standard sections, contact info, quantified achievements, keyword
  placement), aiming for 90+/100.
- When an AI provider is configured, auto-refine once if the first pass
  scores under 90, feeding back the specific gaps.
- When no AI provider is configured, produce a deterministic local rewrite
  (best-effort, may land under 90, shown honestly).
- Let the user edit the generated CV in a textarea and re-check the ATS score
  against their edits (local scoring only, no AI cost).
- Download the current (possibly edited) CV as a styled PDF.
- Never fabricate employers, dates, degrees, or skills not evidenced in the
  source resume.

## Non-goals

- No structured/form-based resume input. Input is the free-text resume
  already extracted by the existing `/analyze` flow.
- No section-by-section structured editor. Editing is a single textarea.
- No DOCX or Markdown export, PDF only.
- No persistence. Follows the app's existing fully-stateless, carry-state-
  via-POST-form pattern; nothing is written to a database or disk.
- No automatic re-generation via AI after the initial 1-retry loop; further
  improvement past that point is manual editing by the user.

## Architecture

Three new pieces, following existing patterns in the codebase:

1. **`utils/ats_scorer.py`** (new) — pure scoring module, structured like
   `utils/matcher.py`. No AI, no I/O, fully unit-testable.
2. **`utils/analysis.py`** (extended) — one new orchestration function,
   `generate_ats_cv()`, alongside the existing `analyze_resume()` and
   `generate_cover_letter()`, using the same AI-with-local-fallback pattern
   and the same private HTTP/model-chain helpers already in the module.
3. **`app.py` + `templates/cv.html`** (new route(s) + new template) — wires
   the generator into the UI following the existing
   upload → analyze → result → cover-letter page flow.

No new dependencies. Reuses `matcher.extract_skills`, the existing
`_chat_completion`/`_extract_json`/model-chain machinery in `analysis.py`,
and the existing ReportLab-based `pdf_exporter.py` patterns.

## ATS scorer (`utils/ats_scorer.py`)

Public function:

```python
def score_ats(cv_text: str, job_description: str) -> dict:
    ...
```

Returns:

```python
{
    "score": int,               # 0-100, sum of the components below
    "coverage": {
        "score": int,           # 0-50
        "matching_skills": [str, ...],
        "missing_skills": [str, ...],
    },
    "sections": {
        "score": int,           # 0-20
        "found": [str, ...],    # e.g. ["Summary", "Experience"]
        "missing": [str, ...],  # e.g. ["Education", "Skills"]
    },
    "contact_info": {
        "score": int,           # 0-10
        "has_email": bool,
        "has_phone": bool,
    },
    "quantified_achievements": {
        "score": int,           # 0-10
        "count": int,           # number of lines with a digit/%/metric
    },
    "keyword_placement": {
        "score": int,           # 0-10
        "top_skills_in_lead": [str, ...],  # JD's top skills found in first 20% of text
    },
}
```

Component logic:

- **Coverage (50 pts)** — reuse `matcher.extract_skills()` to get the JD's
  skill list and the CV's skill list. `score = round(50 * matching / required)`
  where `required = len(job_skills)` (0 if the JD has no recognized skills,
  in which case coverage defaults to 25).
- **Sections (20 pts)** — regex-match standard header lines (case-insensitive,
  own line, e.g. `^\s*(summary|profile)\s*$`, `^\s*(experience|work
  experience)\s*$`, `^\s*education\s*$`, `^\s*skills\s*$`). 5 pts per section
  found, 4 sections checked.
- **Contact info (10 pts)** — regex for an email address (5 pts) and a phone
  number pattern (5 pts) anywhere in the text.
- **Quantified achievements (10 pts)** — count non-header lines containing a
  digit, `%`, or currency symbol. `score = min(10, count * 2)` (5+ such lines
  gives full credit).
- **Keyword placement (10 pts)** — take the JD's top 5 skills (by order of
  appearance, via `extract_skills`), check how many appear in the first 20%
  of the CV text by character offset. `score = round(10 * found / min(5,
  len(job_skills)))`, 0 if the JD has no recognized skills.

All regex/heuristics are deterministic and testable in isolation, no AI
involved.

## Generation loop (`analysis.generate_ats_cv`)

```python
def generate_ats_cv(resume_text: str, job_description: str) -> dict:
    ...
```

Returns:

```python
{
    "cv_text": str,
    "ats": {...},        # score_ats() output for the returned cv_text
    "source": "ai" | "local",
    "attempts": int,      # 1 or 2, AI path only; always 1 for local
}
```

Logic:

1. If AI is unavailable (`ai_available()` is False): run the local rewrite
   (below), score it once, return with `source="local"`, `attempts=1`.
2. If AI is available:
   a. First pass: prompt the model to rewrite the resume for the JD as plain
      text with standard section headers (`SUMMARY`, `EXPERIENCE`,
      `EDUCATION`, `SKILLS`). Score the result.
   b. If `score >= 90`, return immediately (`attempts=1`).
   c. Otherwise, one refinement pass: re-prompt with the specific gaps from
      the first score breakdown (missing skills, missing sections, no
      quantified achievements, weak keyword placement), score the result,
      and return whichever of the two attempts scored higher (`attempts=2`).
   d. Any AI failure (auth, network, quota, bad JSON) at any point falls back
      to the local rewrite for that attempt, matching the existing
      `analyze_resume`/`generate_cover_letter` fallback behavior. If the
      first AI attempt fails outright, skip straight to the local path
      (`source="local"`, `attempts=1`); no refinement pass without a
      successful first draft to refine.

AI prompt requirements (both passes):

- Rewrite the resume text for the given job description, plain text output,
  ready to paste, with standard section headers on their own line.
- **Guardrail, must be explicit in the prompt:** do not invent employers, job
  titles, dates, degrees, or skills not evidenced in the source resume. You
  may reorder, rephrase, tighten wording, and quantify achievements only
  where plausible from the source. You may use the job description's exact
  terminology in place of a synonym already present in the resume (e.g.
  resume says "JS", JD says "JavaScript", output may say "JavaScript"), but
  never introduce a skill or claim absent from the source resume.
- Same house style as the rest of the app's AI prompts: no em dashes, plain
  human language, no buzzwords.
- Refinement pass additionally includes the prior attempt's score breakdown
  and asks the model to address the specific gaps without regressing what
  already scored well.

Response parsing reuses `_extract_json`-style handling if the model is asked
for `{"cv_text": "..."}` JSON (consistent with `_analyze_with_ai`), or plain
text extraction if simpler; implementation detail left to the implementer,
but must be robust to models wrapping output in code fences the same way
`_extract_json` already handles.

## Local rewrite (no AI key)

Deterministic, single pass:

1. Ensure standard section headers exist. If the extracted resume text has no
   recognizable `EXPERIENCE`/`EDUCATION`/`SKILLS` headers, prepend a `SKILLS`
   section listing the resume's own matching skills (from
   `matcher.analyze_match`, skills already in the resume, never invented).
2. Leave body content otherwise unchanged (no rewriting prose without AI).
3. Score once via `score_ats`. Result may land under 90; the UI states this
   honestly rather than implying success.

## Routes (`app.py`)

- **`POST /cv`** — entry point from `result.html`. Body carries
  `resume_text`, `job_description` (same hidden fields already carried
  between `/result` and `/cover-letter`). Calls `generate_ats_cv`, renders
  `cv.html` with the generated `cv_text`, `ats` breakdown, `source`,
  `attempts`, plus hidden `resume_text`/`job_description` for the next step.

- **`POST /cv/rescore`** — body carries the user-edited `cv_text` (from the
  textarea) and `job_description`. Calls `score_ats` only (no AI, no
  `generate_ats_cv`), re-renders `cv.html` with the updated score and the
  user's edited text preserved verbatim.

- **`POST /download/cv`** — body carries the current `cv_text`. Calls new
  `pdf_exporter.export_cv_to_pdf(cv_text)`, returns as an attachment
  (`tailored_cv.pdf`), following the exact pattern of `download_cover_letter`.

All three follow the existing carried-state, no-session, no-DB pattern.
`_carried_analysis()`-style guards are not needed here since there's no JSON
blob to corrupt, just plain text fields; missing `resume_text` or
`job_description` on `/cv` should flash and redirect to `index`, matching
existing validation style in `/analyze`.

## PDF export (`utils/pdf_exporter.py`)

New function `export_cv_to_pdf(cv_text: str) -> bytes`, structured like
`export_cover_letter_to_pdf`: title "Tailored CV", subtitle "Generated by AI
Resume Matcher", then paragraphs split on blank lines. Section header lines
(all-caps, matching the same header regex used in `ats_scorer.py`) are
rendered with the existing `h2` style instead of `body`, so the PDF gets
basic visual structure without a new styling system.

## UI flow

- `templates/result.html` — add a "Generate ATS-Optimized CV" button next to
  the existing cover-letter button/link, posting to `/cv` with the same
  carried `resume_text`/`job_description` fields already on that page.

- `templates/cv.html` (new) — new template:
  - ATS score shown with the existing radial-gauge visual pattern from
    `result.html` (reused, not reinvented), plus the four-component
    breakdown as labeled chips/rows (coverage, sections, contact info,
    quantified achievements, keyword placement) with their individual
    sub-scores.
  - A note on `source`/`attempts` when relevant, e.g. "Generated by AI
    Resume Matcher (AI, 2 passes)" or "Generated by the local engine, no AI
    key configured. Edit below to improve the score further."
  - A large editable `<textarea>` pre-filled with `cv_text`.
  - "Re-check ATS score" button, `POST /cv/rescore`, submits the textarea
    content plus the carried `job_description`.
  - "Download PDF" button, `POST /download/cv`, submits the current textarea
    content.
  - "Back to report" link, consistent with the existing cover-letter page's
    navigation.

## Error handling

- Missing `resume_text`/`job_description` on any of the three routes: flash
  a message and redirect to `index`, matching the existing pattern in
  `/analyze` and `_carried_analysis()`-guarded routes.
- AI failures inside `generate_ats_cv` never surface as errors to the user;
  they fall back to the local path exactly as `analyze_resume` and
  `generate_cover_letter` already do, logged via the existing `logger.warning`
  pattern.
- `score_ats` is pure and has no failure modes beyond empty-string inputs,
  which it must handle the same way `analyze_match` handles empty
  `resume_text`/`job_description` (treated as `""`, not an error).

## Testing

- **`tests/test_ats_scorer.py`** (new) — unit tests per component (coverage,
  sections, contact info, quantified achievements, keyword placement) plus
  the combined score, plus empty-input edge cases.
- **`tests/test_analysis.py`** (extended) — `generate_ats_cv`: AI
  first-pass-succeeds path (mocked `httpx` responses, as the existing AI
  tests already do), AI first-pass-under-90-triggers-refinement path,
  AI-failure-falls-back-to-local path, no-AI-key local-only path.
- **`tests/test_app.py`** (extended) — route tests for `/cv` (happy path,
  missing fields), `/cv/rescore` (score updates against edited text),
  `/download/cv` (returns a PDF attachment).

## Open implementation details (left to the implementer, not architecturally
significant)

- Exact phone-number and email regexes for `contact_info` scoring, standard
  patterns are sufficient (no need for exhaustive international phone format
  coverage).
- Exact AI prompt wording, must satisfy the guardrail and house-style
  requirements above but wording itself is an implementation detail.
- Whether the AI response is requested as JSON (`{"cv_text": "..."}`,
  consistent with `_analyze_with_ai`) or as raw text is left to the
  implementer, but must reuse the existing `_extract_json`-style robustness
  to code-fenced/prose-wrapped responses if JSON is used.
