---
type: Wiki Overview
title: 'TASK-1272: HTML5 renderer — CustomEvent emission and remote bridge script'
id: doc:sdd-tasks-completed-task-1272-html5-renderer-events-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements §3 Module 7. The HTML5 renderer is the only renderer in MVP scope.
  It must:'
---

# TASK-1272: HTML5 renderer — CustomEvent emission and remote bridge script

**Feature**: FEAT-188 — Form Lifecycle Events for parrot-formdesigner
**Spec**: `sdd/specs/formdesigner-lifecycle-events.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1268, TASK-1271
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 7. The HTML5 renderer is the only renderer in MVP scope. It must:
1. Emit DOM `CustomEvent`s at the five lifecycle points so frontend hosts can hook into them with zero coupling to parrot internals.
2. For bindings with `remote: true`, additionally `fetch` the server-side endpoint (created by TASK-1271) with the CSRF token.

---

## Scope

- Modify `HTML5Renderer.render` (renderers/html5.py:77) to embed a small inline `<script>` block in the generated form HTML that:
  - On `DOMContentLoaded`, dispatches `CustomEvent('parrot:before-open', {detail: {form_id}})` on the form container.
  - On submit (form's submit handler), dispatches `CustomEvent('parrot:before-submit', {detail: {form_id, payload}})` BEFORE actual submission. Listeners can `event.preventDefault()` to cancel.
  - After submission, dispatches `parrot:after-submit` or `parrot:error` with the response detail.
  - When the form's `events` declares `remote: true` for an event, additionally performs `fetch('/api/v1/forms/{form_id}/events/{event_name}', {method:'POST', body: JSON.stringify(payload), credentials:'same-origin', headers:{'X-CSRF-Token': <token from data-* attr or meta>}})` with a 5000ms timeout. On timeout, log warning and continue.
- Encode the CSRF token into the rendered HTML as a `<meta name="parrot-csrf-token" content="...">` (the token comes from the `X-Form-CSRF-Token` response header — but since the renderer emits HTML directly, the renderer must accept the token as a render kwarg OR fetch it from `form.meta`/context).
  - **Decision (this task)**: render accepts an optional `csrf_token: str | None` kwarg; if present, embed as `<meta>`. The handler that invokes the renderer (TASK-1271's `get_form` extension) is responsible for passing it.
- Update `FormAPIHandler.get_form` if needed to pass `csrf_token` through (small follow-up to TASK-1271).
- Add tests:
  - Unit: snapshot test the generated HTML contains the expected `<script>` block and `CustomEvent` calls.
  - Integration (optional, deferred): Playwright fixture — see TASK-1273.

**NOT in scope**: Telegram/AdaptiveCard/PDF/XForms renderers (post-MVP per spec §1 Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py` | MODIFY | Embed lifecycle `<script>` + `<meta>` for CSRF token |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/_html5_lifecycle.js` | CREATE | (Optional) the JS as a separate file for clarity, then injected as a string |
| `packages/parrot-formdesigner/tests/unit/renderers/test_html5_lifecycle.py` | CREATE | Unit tests verifying the rendered HTML contains expected hooks |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Top of renderers/html5.py:
from parrot_formdesigner.core.events import FormEventName, FormEventsConfig
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py:77
class HTML5Renderer(AbstractFormRenderer):
    async def render(self, form: FormSchema, **kwargs) -> RenderedForm: ...
    # Verify exact signature; may need to add a csrf_token kwarg.

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py:57
class AbstractFormRenderer(ABC):
    @abstractmethod
    async def render(self, form, **kwargs) -> RenderedForm: ...   # line 68
```

### Does NOT Exist

- ~~A JS bundler or webpack pipeline in this package~~ — confirm via `ls packages/parrot-formdesigner/`. The script is inlined as a Python string in the HTML output.
- ~~Any existing `CustomEvent` emission~~ — none today (grep confirms).
- ~~`HTML5Renderer.attach_lifecycle_events`~~ — does NOT exist; add it inline.

---

## Implementation Notes

### Script template (inlined as a Python string)

```javascript
(function() {
  const formEl = document.getElementById('parrot-form-' + FORM_ID);
  if (!formEl) return;

  const events = EVENTS_CONFIG;  // injected by renderer
  const csrfToken = document
    .querySelector('meta[name="parrot-csrf-token"]')
    ?.getAttribute('content');

  function emit(name, detail) {
    formEl.dispatchEvent(new CustomEvent('parrot:' + name, {
      detail: detail, bubbles: true, cancelable: true,
    }));
  }

  async function bridge(eventName, payload, timeoutMs = 5000) {
    if (!events[eventName] || !events[eventName].remote) return;
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), timeoutMs);
    try {
      const resp = await fetch(
        '/api/v1/forms/' + FORM_ID + '/events/' + eventName,
        {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': csrfToken,
          },
          body: JSON.stringify({ payload: payload }),
          signal: ctl.signal,
        }
      );
      return await resp.json();
    } catch (e) {
      console.warn('[parrot] remote event ' + eventName + ' failed:', e);
    } finally {
      clearTimeout(timer);
    }
  }

  // onBeforeOpen
  document.addEventListener('DOMContentLoaded', async () => {
    emit('before-open', { form_id: FORM_ID });
    await bridge('onBeforeOpen', {});
  });

  // onBeforeSubmit + onAfterSubmit + onError
  formEl.addEventListener('submit', async function(ev) {
    const data = Object.fromEntries(new FormData(formEl).entries());
    const beforeEvt = new CustomEvent('parrot:before-submit', {
      detail: { form_id: FORM_ID, payload: data },
      bubbles: true, cancelable: true,
    });
    if (!formEl.dispatchEvent(beforeEvt)) {
      ev.preventDefault();
      return;
    }
    await bridge('onBeforeSubmit', data);
    // Let the form proceed; after-submit / error events should be wired
    // around the actual XHR/fetch the host uses. For an MVP form that
    // submits via standard HTTP POST, the host listens for the response.
  });
})();
```

### Key Constraints

- Vanilla JS only — no jQuery, no external runtime deps.
- No template engine assumed beyond the existing string-concat pattern in `html5.py`. Confirm before introducing Jinja or similar.
- Script must be safe to embed multiple times (multiple forms on a page) — the IIFE + `FORM_ID` scoping handles this.
- The events config injected as `EVENTS_CONFIG` is JSON-serialized from `form.events.model_dump(exclude_none=True)`.
- If `form.events is None`, skip script injection entirely (no overhead for forms without lifecycle hooks — preserves the no-breaking acid test).

### References in Codebase

- `renderers/html5.py:77` `HTML5Renderer` — entry point to modify.
- `renderers/base.py:57` `AbstractFormRenderer` — base class (no changes needed).

---

## Acceptance Criteria

- [ ] Rendered HTML for a form WITHOUT `events` contains NO lifecycle script (byte-identical to pre-change for that case).
- [ ] Rendered HTML for a form WITH `events` contains the lifecycle script with the injected `EVENTS_CONFIG`.
- [ ] The script embeds the form_id so multiple forms can coexist on a page.
- [ ] If `csrf_token` kwarg is passed to `render`, the output contains `<meta name="parrot-csrf-token" content="...">`.
- [ ] If `csrf_token` is None, NO `<meta>` is emitted.
- [ ] Snapshot tests in `tests/unit/renderers/test_html5_lifecycle.py` pass.
- [ ] All existing `HTML5Renderer` tests still pass.

---

## Test Specification

```python
# tests/unit/renderers/test_html5_lifecycle.py
import pytest
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.core.events import FormEventBinding, FormEventsConfig
from parrot_formdesigner.renderers.html5 import HTML5Renderer


@pytest.fixture
def renderer():
    return HTML5Renderer()


async def test_no_events_no_script(renderer):
    form = FormSchema(form_id="f1", title={"en": "t"}, sections=[])
    out = await renderer.render(form)
    assert "parrot:before-submit" not in out.content
    assert "parrot-csrf-token" not in out.content

async def test_events_emit_custom_events(renderer):
    form = FormSchema(
        form_id="f1", title={"en": "t"}, sections=[],
        events=FormEventsConfig(
            onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit"),
        ),
    )
    out = await renderer.render(form)
    assert "parrot:before-submit" in out.content
    assert "f1" in out.content  # form_id injected

async def test_csrf_meta_when_token_provided(renderer):
    form = FormSchema(
        form_id="f1", title={"en": "t"}, sections=[],
        events=FormEventsConfig(
            onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit", remote=True),
        ),
    )
    out = await renderer.render(form, csrf_token="abc123")
    assert '<meta name="parrot-csrf-token"' in out.content
    assert "abc123" in out.content
```

---

## Agent Instructions

1. **Read the spec** §3 Module 7.
2. **Check dependencies** — TASK-1268, TASK-1271.
3. **Verify the Codebase Contract** — read the current `HTML5Renderer.render` to confirm how HTML is assembled (string concatenation vs. template).
4. **Implement** — keep the script minimal and the no-events code path completely untouched.
5. **Verify** acceptance criteria with the snapshot tests.
6. **Move** this file to `sdd/tasks/completed/`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
