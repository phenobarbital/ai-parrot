---
id: F003
query_id: Q003
type: wiki_query
intent: Orient: form submit endpoint and lifecycle
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F003 — Form submission surface (wiki)

## Summary

Submission is `submit_data` in `api/handlers.py` (TASK-602), with partial saves (FEAT-186), lifecycle hooks onBeforeSubmit/onAfterSubmit/onError (FEAT-188, TASK-1270), unknown-fields policy (FEAT-458), validate dry-run endpoint (TASK-2437), and persistence sinks (FEAT-457). Documented in `packages/parrot-formdesigner/docs/lifecycle-events.md`.

## Citations

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
  symbol: `submit_data`
- path: `packages/parrot-formdesigner/docs/lifecycle-events.md`
  wiki_page_id: file:packages/parrot-formdesigner/docs/lifecycle-events.md
- path: `sdd/specs/formdesigner-lifecycle-events.spec.md`
  wiki_page_id: file:sdd/specs/formdesigner-lifecycle-events.spec.md
- path: `sdd/specs/formdesigner-partial-saves.spec.md`
  wiki_page_id: file:sdd/specs/formdesigner-partial-saves.spec.md
