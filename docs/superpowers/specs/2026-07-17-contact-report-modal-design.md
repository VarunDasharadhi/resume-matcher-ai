# Contact / Report an Issue modal

## Context

Varun wants a small way for users to reach him from the app, mirroring the pattern already shipped in `uk-immigration-compass`: a footer link that opens a compact modal showing his email, click-to-copy, no form and no backend. This app should get the same pattern, restyled onto its own "Precision Instrument" theme (dark ink/cream/amber, Fraunces + Hanken Grotesk), reusing existing code where it already fits.

## Reference implementation (uk-immigration-compass)

- `App.tsx`: a `CONTACT_EMAIL` constant, a `Footer` component with a "Contact / Report an Issue" button that toggles `contactOpen` state, and a `ContactModal` component rendered via `createPortal` when open.
- Modal: full-screen overlay (click to close), centered white/dark card, close (X) button, mail icon badge, heading "Get in touch", one line of body copy, a click-to-copy row showing the email with a copy icon that flips to a checkmark + "Copied to clipboard" for 2s.
- No mailto link, no contact form, no backend route. Copy-to-clipboard is the entire mechanism.

## Design for this app

**Trigger — footer link.** `templates/base.html`'s existing `<footer class="site-foot">` gets one more segment after the "Source" link:
```html
<span class="foot-sep">·</span>
<button type="button" class="footer-link" id="contact-btn">Contact</button>
```
Visible on every page, since every template extends `base.html`. No layout change to any page body.

**Email source of truth.** `app.py` gains `CONTACT_EMAIL = "developerworld.net@gmail.com"` next to the existing `MAX_CONTENT_LENGTH` constant, added to the existing `inject_globals()` context processor (which already injects `ai_available` / `provider_label`) as `contact_email`. Every template can reference `{{ contact_email }}`; the address is defined exactly once.

**Modal markup.** A new block in `base.html`, right after the footer, hidden by default:
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
```
Icon glyphs (✕, ✉, ⧉) match the app's existing monochrome-symbol icon language (◎, ✓, ✕, ✍, ⬇, ⧉ already appear elsewhere) — no icon library, no emoji.

**Styling (`static/style.css`).** New rules only, reusing existing custom properties, no new colors:
- `.modal-overlay`: `position: fixed; inset: 0;` dark scrim (`rgba(20,17,15,.7)` in the vein of the existing `.grain`/`.glow` overlay treatment), `display: none` by default, `display: flex` + centering when `.is-open`.
- `.modal-card`: `background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow);` padding and max-width matching the existing `.preview-card` treatment.
- `.modal-icon`: small amber-tinted circular badge (`background: rgba(224,168,61,.12); color: var(--amber);`), consistent with the amber accent used throughout.
- `.modal-title`: `font-family: var(--serif);` matching other headings.
- `.modal-copy`: bordered row (`border: 1px solid var(--line)`), hover state brightens the border to `var(--amber)`, matching the existing button/chip hover language.
- `.footer-link`: unstyled `<button>` matching the existing `.site-foot a` link styling (same color, hover state) so it reads identically to the "Source" link next to it.

**Interaction (vanilla JS, no new pattern invented).**
- Click `#contact-btn` → add `.is-open` to `#contact-overlay`.
- Click the overlay backdrop, `#contact-close`, or press `Escape` → remove `.is-open`.
- Click `#contact-copy` → read `#contact-email-text`'s `textContent` and copy it to the clipboard via `navigator.clipboard.writeText`, then swap `#contact-copy-hint`'s text to "Copied to clipboard" for 1.8s, matching the exact try/catch + `setTimeout` pattern already used by `cover_letter.html`'s `#copy-btn` (including its "Press Ctrl+C" fallback if the Clipboard API is unavailable or denied).
- This script lives in `base.html`'s existing inline `<script>` block at the bottom (the one that already owns the `[data-action-group]` click-feedback logic), so it's available on every page without a new `{% block scripts %}` override anywhere.

## Explicitly out of scope

- No contact form, no `/contact` route, no email-sending, no new dependency. This is a static, client-side "copy the address" affordance, identical in scope to the reference implementation.
- No focus trap or advanced a11y beyond `aria-label` on the close button and Escape-to-close — matches the minimal-JS style already used elsewhere in this app (e.g. the upload dropzone's own keyboard handling is similarly lightweight).

## Testing

One new test in `tests/test_app.py`, matching the existing `test_index_loads` style: assert `contact_email` (`developerworld.net@gmail.com`) appears in the rendered `/` response body. No backend logic is added, so no other test surface exists.

## Verification

1. `pytest` — full suite green, plus the new test.
2. Manual: start the dev server, load `/`, click "Contact" in the footer, confirm the modal opens, click the email row, confirm it copies and the hint text flips to "Copied to clipboard", confirm Escape and backdrop-click both close it. Repeat on `/analyze` result page and the cover-letter page to confirm the footer trigger works identically everywhere (base.html is shared).
