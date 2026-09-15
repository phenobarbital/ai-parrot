---
id: F018
query_id: Q018
type: git_log
intent: Recent activity on renderers and msteams
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F018 — git log — renderers + msteams/cards (120 days)

## Summary
`adaptive_card.py` last changed 2026-08-25 (TASK-2449 upload FileEnvelope display), 2026-08-22 (TASK-2337 new field-type posture), 2026-07-31 (field_uid warnings). Teams/cards side: 2026-08-29 TASK-2545 (native inputs + a2ui_action routing), 2026-07-21 the shared `parrot.outputs.cards` builder landed (AC 1.5 models, wrapper migrated to it), 2026-07-23 "unify adaptive card version". Both areas are active but stable; no conflicting in-flight work on the Submit payload.

## Citations
- `48227a5fd` 2026-08-25 feat(raw-upload-field-types): TASK-2449 — Other Renderers Update (html5/pdf/adaptive_card)
- `ca5e3dbc3` 2026-08-22 feat(field-type-catalog): TASK-2337 — recorded renderer posture for the twelve new types
- `01c431ca3` 2026-07-31 feat(formdesigner-field-uid): TASK-2005 — renderers emit data-field-uid + RenderWarning.field_uid
- `0ad7d9c3a` 2026-08-29 feat(a2ui-v1-dialect): TASK-2545 — Adaptive Cards native inputs, Action.Submit{a2ui_action}, Action.OpenUrl; Teams wrapper routes a2ui_action
- `9428e08b1` 2026-07-23 fix(msteams): resolve APP_TENANTID from env, unify adaptive card version, fix response truncation
- `a5ac3cdbf` 2026-07-21 refactor: migrate A2UI, forms, and HITL card renderers to shared parrot.outputs.cards builder
- `cd5d9f5a5` 2026-07-21 feat(cards): AC 1.5 input + action models — Input.*, Action.Submit/OpenUrl/ToggleVisibility/ShowCard
