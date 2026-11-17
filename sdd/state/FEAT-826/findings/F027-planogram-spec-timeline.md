---
id: F027
query_id: Q035
type: git_log
intent: "Timeline of planogram specs."
executed_at: 2026-11-06T16:04:38Z
duration_ms: 300
parent_id: null
depth: 0
lanes: [git]
merged_from: [FG-007]
---
# F027 — Timeline of planogram specs since 2026-08-01

## Summary

Twenty spec commits trace the new cycle: FEAT-565 new-planogram-compliance-algo (2026-09-17), FEAT-574
new-planogram-pipeline (2026-09-18), FEAT-592 nova-image-planogram (2026-09-23), FEAT-612
refactor-planogram-compliance (2026-09-30), FEAT-624 planogram-fact-tag-rule (2026-10-01), FEAT-645
planogram-ink-wall-slot-presence (2026-10-08), and on 2026-10-15 FEAT-683 planogram-appearance-rule and
planogram-fact-tag-e2e-test. **No planogram spec has been added or changed since 2026-10-15**, and none is
about migrating production rows or about the Office Depot EcoTank endcaps.

## Citations

- path: `sdd/specs/planogram-*.spec.md`, `sdd/specs/*planogram*.spec.md`
  commits:
  - `4fc5aca268` 2026-10-15 · sdd: add 4 tasks for FEAT-683 — planogram-appearance-rule
  - `aa6cdfb57f` 2026-10-15 · sdd: add spec for FEAT-683 — planogram-appearance-rule
  - `5859125838` 2026-10-15 · sdd: spec and tasks for planogram-fact-tag-e2e-test
  - `b51552cbef` 2026-10-12 · feat(products-found-endcap): TASK-4208 — Document the reporting policy and products_found
  - `7582b4a3cc` 2026-10-08 · sdd: add spec for FEAT-645 — planogram-ink-wall-slot-presence
  - `600d6b28b7` 2026-10-01 · sdd: approve spec for FEAT-624 — planogram-fact-tag-rule
  - `cc0364bd2a` 2026-09-30 · sdd: approve spec for FEAT-612 - refactor-planogram-compliance
  - `8564cef57e` 2026-09-23 · sdd: approve spec for FEAT-592 — nova-image-planogram
  - `5141f5cd20` 2026-09-18 · sdd: approve spec for FEAT-574 — new-planogram-pipeline
  - `1811c150b6` 2026-09-17 · sdd: approve spec for FEAT-565 — new-planogram-compliance-algo

## Notes

- `b51552cbef` (2026-10-12, products-found-endcap) documents a *reporting policy* and `products_found` —
  possibly relevant to how a zone-only endcap result is reported downstream.
- [cross-lane: type=wiki_query, intent=find the products-found-endcap reporting policy (TASK-4208) and whether it defines what a graphics-only endcap reports as found products]
