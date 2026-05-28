---
id: F006
query_id: Q006
type: git_log
intent: Recent activity on forms vs parrot-formdesigner
executed_at: 2026-05-28T13:11:03+02:00
depth: 0
---

# F006 — All recent activity is on parrot-formdesigner; parrot/forms is dormant

## Summary

`git log --oneline --all -- packages/ai-parrot/src/parrot/forms/
packages/parrot-formdesigner/` (top 20) shows every recent commit
touching the formdesigner package, none touching `parrot/forms/` since
the FEAT-152 migration. Notable: FEAT-188 ("formdesigner-lifecycle-events")
landed 9/9 tasks in `parrot-formdesigner` recently — the canonical
location is the package, and `parrot/forms/` is frozen.

## Citations

- path: (git history)
  excerpt: |
    6c75db3f WIP on dev: sdd: close FEAT-188 — formdesigner-lifecycle-events (9/9 tasks)
    837278cc fix(formdesigner): address code-review issues for FEAT-188
    460b0631 feat(formdesigner-lifecycle-events): TASK-1273 — E2E tests, lifecycle-events docs
    640bf936 feat(formdesigner-lifecycle-events): TASK-1272 — HTML5 renderer lifecycle CustomEvent
    9aff952f feat(formdesigner-lifecycle-events): TASK-1271 — Remote events endpoint CSRF
    5ab7a8e7 feat(formdesigner-lifecycle-events): TASK-1270 — submit lifecycle hooks
    4dd4d41f feat(formdesigner-lifecycle-events): TASK-1269 — onBeforeOpen / onSchemaLoaded
    5d7259e0 feat(formdesigner-lifecycle-events): TASK-1268 — Add FormSchema.events field
    c5c37167 feat(formdesigner-lifecycle-events): TASK-1267 — Event dispatcher
    85bfc52c feat(formdesigner-lifecycle-events): TASK-1266 — Tenant-scoped event registry
    f4269046 feat(formdesigner-lifecycle-events): TASK-1265 — Core event models
    6b9bf4e6 json serialization of forms

## Notes

Implication: code in `parrot/forms/` is behind upstream
`parrot-formdesigner` (e.g., does not have the new lifecycle-events
work from FEAT-188). Any caller relying on the local fallback is
silently running on stale code.
