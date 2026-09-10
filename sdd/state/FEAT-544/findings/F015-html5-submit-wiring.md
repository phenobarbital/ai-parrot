---
id: F015
query_id: Q015
type: grep
intent: HTML5 renderer submit wiring
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F015 — html5.py — client-side submit and lifecycle bridge

## Summary

HTML5Renderer (content_type text/html) embeds a script that POSTs `FormData` to `formEl.action || window.location.href`, calls the lifecycle bridge `/api/v1/{tenant}/forms/{form_uid}/events/{eventName}` (onBeforeSubmit) and emits `parrot:before-submit/after-submit/error` CustomEvents. Upload fields target `/api/v1/{tenant}/forms/{form_id}/fields/{field_id}/upload`. The submit URL is NOT baked into the fragment — it relies on the page's `action`/location.

## Citations

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py`
  lines: 504-505
  excerpt: |
    return fetch('/api/v1/' + TENANT + '/forms/' + FORM_UID + '/events/' + eventName,
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py`
  lines: 570-598
  excerpt: |
    return fetch(formEl.action || window.location.href, { method: 'POST', credentials: 'same-origin', body: fd });
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py`
  lines: 140
  excerpt: |
    content_type="text/html"
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py`
  lines: 1406
