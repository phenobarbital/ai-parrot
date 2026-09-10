---
id: F016
query_id: Q015
type: read
intent: FEAT-544 overlap/boundary
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F016 — FEAT-544 A2UI form renderer — boundary with a Teams renderer

## Summary
FEAT-544 (spec approved, TASK-3071..3078 active) builds an A2UI renderer for FormDesigner and makes `POST .../data` and `/validate` dual-wire (legacy JSON + A2UI action envelope). Its proposal already cites `adaptive_card.py` as the table-driven precedent and the TASK-2545 `Action.Submit{a2ui_action}` path as "precedent for a channel submit path", and records an "action sink mismatch" risk: a form surface must tell the client WHERE to send the action (`context.submit_url`). `api/a2ui_wire.py` does NOT exist yet. A Teams renderer can either reuse the legacy JSON body (stable today) or the A2UI envelope (lands with TASK-3074/3075).

## Citations
- path: `sdd/proposals/a2ui-form-output-renderer.proposal.md`
  lines: 66, 79
  excerpt: |
    adaptive_card.py FieldType → element map 71-119 — precedent for a dict-output renderer ...
    a2ui_renderers/adaptive_cards.py Action.Submit{a2ui_action} — precedent for a channel submit path
- path: `sdd/proposals/a2ui-form-output-renderer.proposal.md`
  lines: 189
  excerpt: |
    Action sink mismatch: ... a form surface must tell the client where to send the action (context.submit_url) ...
- path: `sdd/tasks/active/TASK-3075-submit-data-dual-wire.md`
  lines: 20-30
  symbol: A2UI branch in `submit_data` (pending)
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py`
  symbol: DOES NOT EXIST yet (created by TASK-3074)
