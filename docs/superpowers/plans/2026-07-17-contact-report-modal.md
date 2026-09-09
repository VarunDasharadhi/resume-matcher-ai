# Contact / Report an Issue Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a footer "Contact" link that opens a small modal showing Varun's email with click-to-copy, available on every page.

**Architecture:** One Flask constant (`CONTACT_EMAIL`) surfaced through the existing `inject_globals()` context processor, rendered once in `templates/base.html` (which every template extends), styled with existing CSS custom properties, and wired up with vanilla JS reusing the exact copy-to-clipboard pattern already shipped in `templates/cover_letter.html`.

**Tech Stack:** Flask + Jinja2 (existing), plain CSS (existing `static/style.css` custom properties), vanilla JS (no new dependency, no new library).

## Global Constraints

- Email address is exactly `developerworld.net@gmail.com` — copy verbatim, do not alter casing or add mailto: formatting.
- No new Python dependency, no new JS library, no new backend route. This is a static, client-side "copy the address" affordance — no contact form, no email-sending.
- No new CSS colors. Every rule must reference an existing custom property from `static/style.css:7-27` (`--ink`, `--surface`, `--surface-2`, `--line`, `--cream`, `--cream-dim`, `--muted`, `--amber`, `--radius`, `--radius-sm`, `--shadow`, `--serif`, `--sans`, `--mono`).
- Icon glyphs are plain Unicode symbols matching the app's existing icon language (already uses ◎ ✓ ✕ ✍ ⬇ ⧉ elsewhere) — no emoji, no icon library.
- The copy-to-clipboard JS must reuse the exact try/catch + `setTimeout` shape already implemented in `templates/cover_letter.html:36-49` (including the "Press Ctrl+C" fallback if `navigator.clipboard` is unavailable or denied), not a new implementation.
- Reference spec: `docs/superpowers/specs/2026-07-17-contact-report-modal-design.md`.

---

### Task 1: Backend wiring + modal markup

**Files:**
- Modify: `app.py:40-50`
- Modify: `templates/base.html:51-55`
- Test: `tests/test_app.py`

**Interfaces:**
- Produces: Jinja context variable `contact_email` (string, value `"developerworld.net@gmail.com"`), available in every template via the existing `inject_globals()` context processor. Produces DOM elements `#contact-btn` (footer trigger button), `#contact-overlay` (modal root, no `.is-open` class yet so it stays hidden), `#contact-close` (close button), `#contact-copy` (the clickable copy row), `#contact-email-text` (span holding the raw email text), `#contact-copy-hint` (paragraph showing the copy hint/confirmation text). Task 2 consumes all of these IDs to add styling and interactivity.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_app.py`, right after `test_index_loads`:

```python
def test_index_shows_contact_email(client):
    resp = client.get("/")
    assert b"developerworld.net@gmail.com" in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python -m pytest tests/test_app.py -k test_index_shows_contact_email -v`
Expected: FAIL — `assert b"developerworld.net@gmail.com" in resp.data` is False (the email appears nowhere yet).

- [ ] **Step 3: Add the `CONTACT_EMAIL` constant and expose it via the context processor**

In `app.py`, the current block (around line 40) reads:

```python
MAX_CONTENT_LENGTH = 4 * 1024 * 1024  # 4 MB (within serverless body limits)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-only-change-in-production")
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH


@app.context_processor
def inject_globals():
    """Make AI availability known to every template (header/footer status)."""
    return {"ai_available": ai_available(), "provider_label": provider_label()}
```

Replace it with:

```python
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
```

- [ ] **Step 4: Add the footer trigger and modal markup**

In `templates/base.html`, the current footer block (around line 51) reads:

```html
  <footer class="site-foot">
    <span>Built with Flask · {{ provider_label }} · ReportLab</span>
    <span class="foot-sep">·</span>
    <a href="https://github.com/VarunDasharadhi/resume-matcher-ai" target="_blank" rel="noopener">Source</a>
  </footer>
```

Replace it with (adds the footer trigger, then the modal block right after the closing `</footer>`):

```html
  <footer class="site-foot">
    <span>Built with Flask · {{ provider_label }} · ReportLab</span>
    <span class="foot-sep">·</span>
    <a href="https://github.com/VarunDasharadhi/resume-matcher-ai" target="_blank" rel="noopener">Source</a>
    <span class="foot-sep">·</span>
    <button type="button" class="footer-link" id="contact-btn">Contact</button>
  </footer>

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
```

No CSS or JS yet — the overlay has no `.is-open` toggle logic in this task, so it's inert. That's expected; Task 2 makes it interactive.

- [ ] **Step 5: Run test to verify it passes**

Run: `./venv/Scripts/python -m pytest tests/test_app.py -k test_index_shows_contact_email -v`
Expected: PASS

- [ ] **Step 6: Run the full suite to confirm nothing else broke**

Run: `./venv/Scripts/python -m pytest`
Expected: all tests pass (64 total: 63 existing + 1 new).

- [ ] **Step 7: Commit**

```bash
git add app.py templates/base.html tests/test_app.py
git commit -m "$(cat <<'EOF'
Add contact email to Flask context and footer/modal markup

Backend half of the contact/report modal: CONTACT_EMAIL constant
surfaced through the existing inject_globals() context processor,
plus the footer trigger and modal skeleton in base.html. No styling
or interactivity yet, that's the next commit.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Styling + interactivity

**Files:**
- Modify: `static/style.css:101` (insert new rules after `.foot-sep`)
- Modify: `templates/base.html:59-90` (extend the existing inline `<script>` block)

**Interfaces:**
- Consumes: the DOM IDs and classes produced by Task 1 — `#contact-btn`, `#contact-overlay`, `#contact-close`, `#contact-copy`, `#contact-email-text`, `#contact-copy-hint`, and the `.footer-link` / `.modal-*` classes already present in the Task-1 markup.
- Produces: a fully working, styled, interactive modal. Nothing downstream consumes this — it's the final task.

- [ ] **Step 1: Add the CSS**

In `static/style.css`, right after the existing footer rule block:

```css
.foot-sep { opacity: .5; }
```

(line 101) insert this new block before the `/* ---- flash ---- */` comment:

```css

/* ---- footer link + contact modal ---- */
.footer-link {
  background: none; border: none; padding: 0; margin: 0; cursor: pointer;
  font-family: var(--mono); font-size: .72rem;
  color: var(--cream-dim); border-bottom: 1px solid var(--line);
}
.footer-link:hover { color: var(--amber); }

.modal-overlay {
  display: none; position: fixed; inset: 0; z-index: 50;
  align-items: center; justify-content: center; padding: 20px;
  background: rgba(20,17,15,.7); backdrop-filter: blur(6px);
}
.modal-overlay.is-open { display: flex; }
.modal-card {
  position: relative; width: 100%; max-width: 340px; text-align: center;
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius); box-shadow: var(--shadow);
  padding: 30px 26px 26px;
}
.modal-close {
  position: absolute; top: 14px; right: 14px;
  background: var(--surface-2); border: 1px solid var(--line);
  width: 30px; height: 30px; border-radius: 50%;
  color: var(--cream-dim); cursor: pointer; font-size: .8rem;
  display: flex; align-items: center; justify-content: center;
}
.modal-close:hover { color: var(--amber); border-color: var(--amber); }
.modal-icon {
  width: 46px; height: 46px; margin: 0 auto 16px;
  border-radius: 50%; background: rgba(224,168,61,.12); color: var(--amber);
  display: flex; align-items: center; justify-content: center; font-size: 1.2rem;
}
.modal-title { font-family: var(--serif); font-size: 1.2rem; margin: 0 0 8px; color: var(--cream); }
.modal-body { font-size: .88rem; color: var(--cream-dim); line-height: 1.5; margin: 0 0 20px; }
.modal-copy {
  width: 100%; display: flex; align-items: center; justify-content: space-between;
  gap: 10px; background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--radius-sm); padding: 12px 14px; cursor: pointer;
  font-family: var(--mono); font-size: .82rem; color: var(--cream);
}
.modal-copy:hover { border-color: var(--amber); }
.modal-copy-icon { color: var(--muted); }
.modal-copy-hint { font-size: .76rem; color: var(--muted); margin: 10px 0 0; }
```

- [ ] **Step 2: Add the JS interaction**

In `templates/base.html`, the existing inline `<script>` block (around line 59) starts with:

```html
  <script>
    // Shared click feedback: within an [data-action-group], clicking one action
```

Add the following new block immediately **before** that existing `<script>` tag (keep the existing script untouched):

```html
  <script>
    const contactBtn = document.getElementById('contact-btn');
    const contactOverlay = document.getElementById('contact-overlay');
    const contactClose = document.getElementById('contact-close');
    const contactCopy = document.getElementById('contact-copy');
    const contactEmailText = document.getElementById('contact-email-text');
    const contactHint = document.getElementById('contact-copy-hint');
    const contactHintDefault = contactHint.textContent;

    function openContact() { contactOverlay.classList.add('is-open'); }
    function closeContact() { contactOverlay.classList.remove('is-open'); }

    contactBtn.addEventListener('click', openContact);
    contactClose.addEventListener('click', closeContact);
    contactOverlay.addEventListener('click', e => {
      if (e.target === contactOverlay) closeContact();
    });
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && contactOverlay.classList.contains('is-open')) closeContact();
    });

    contactCopy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(contactEmailText.textContent);
        contactHint.textContent = 'Copied to clipboard';
        setTimeout(() => { contactHint.textContent = contactHintDefault; }, 1800);
      } catch (e) {
        contactHint.textContent = 'Press Ctrl+C';
      }
    });
  </script>
```

- [ ] **Step 3: Run the full pytest suite (regression check)**

Run: `./venv/Scripts/python -m pytest`
Expected: all 64 tests still pass (this task touches no Python, so this just confirms the CSS/HTML edits didn't break Jinja syntax).

- [ ] **Step 4: Manually verify the interactive behavior with Playwright**

Start the dev server:

```bash
FLASK_DEBUG=0 PORT=5097 ./venv/Scripts/python.exe app.py &
```

Then, using the Playwright MCP tools (`browser_navigate`, `browser_snapshot`, `browser_click`, `browser_evaluate`):

1. `browser_navigate` to `http://127.0.0.1:5097/`.
2. `browser_snapshot` — confirm a "Contact" button is present in the footer and the modal is not visible (no `is-open` class).
3. `browser_click` the "Contact" button.
4. `browser_snapshot` — confirm the modal card is now visible with heading "Get in touch", the email text, and the "Tap to copy the email address" hint.
5. `browser_click` the email/copy row.
6. `browser_snapshot` (or `browser_evaluate` reading `document.getElementById('contact-copy-hint').textContent`) — confirm the hint text changed to "Copied to clipboard".
7. `browser_click` the backdrop area (or press Escape via `browser_press_key`) — confirm the modal closes (re-snapshot, `is-open` class gone).
8. Repeat step 1-3 on `/health`-adjacent pages is not needed since `base.html` is shared by every template; spot-check one more page (submit the sample job description on `/` through `/analyze`, land on the result page) and confirm the same "Contact" button and working modal appear there too.

Stop the dev server afterward:

```bash
kill %1
```

- [ ] **Step 5: Commit**

```bash
git add static/style.css templates/base.html
git commit -m "$(cat <<'EOF'
Style and wire up the contact/report modal

CSS reuses only existing design tokens (no new colors). JS mirrors
the copy-to-clipboard pattern already used in cover_letter.html
exactly, including its Clipboard-API-denied fallback text.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Plan Self-Review

- **Spec coverage:** Trigger (Task 1 markup) ✓, email source of truth via context processor (Task 1) ✓, modal markup (Task 1) ✓, styling reusing existing tokens (Task 2) ✓, interaction incl. Escape/backdrop-close (Task 2) ✓, copy-to-clipboard reusing the exact cover_letter.html pattern (Task 2) ✓, no form/backend route (never added, by omission) ✓, one lightweight test (Task 1) ✓.
- **Placeholder scan:** none — every step has complete, literal code.
- **Type/name consistency:** `contact_email` (Jinja var, Task 1) is the only name Task 2 depends on indirectly (it reads the rendered `#contact-email-text` DOM node, not the Jinja variable directly, so there's no naming mismatch risk between tasks). All DOM IDs (`contact-btn`, `contact-overlay`, `contact-close`, `contact-copy`, `contact-email-text`, `contact-copy-hint`) are introduced once in Task 1 and referenced identically in Task 2 — verified matching.
