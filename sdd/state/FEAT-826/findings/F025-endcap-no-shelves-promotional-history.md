---
id: F025
query_id: Q033
type: git_log
intent: "History of the graphics-only endcap type."
executed_at: 2026-11-06T16:04:38Z
duration_ms: 300
parent_id: null
depth: 0
lanes: [git]
merged_from: [FG-005]
---
# F025 — History of types/endcap_no_shelves_promotional.py

## Summary

Six commits since 2026-06-01. Only two are functional: `3e1178be23` (2026-09-19, FEAT-574 TASK-3430,
provider-neutral call sites) and `4aae7d9738` (2026-10-01, FEAT-612 TASK-3867, the migration of this type
to the staged cycle). The other four are repo-wide chores (CI test repair, black, provider-enum imports).
The type file itself has been untouched since 2026-10-01; later behaviour for zone-only endcaps
(`llm_detector`, appearance, optional zones) was added in shared cycle modules, not in the type.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
  commits:
  - `4aae7d9738` 2026-10-01 · Jesus Lara · feat(refactor-planogram-compliance): TASK-3867 — engine-committed coder deliverable
  - `3e1178be23` 2026-09-19 · Jesus Lara · feat(new-planogram-pipeline): TASK-3430 — provider-neutral call sites in shelf-style…
  - `8c758aa3c1` 2026-09-17 · Jesus Lara · fix(ci): install the whole workspace in test-core and repair ~200 drifted tests
  - `14b548483c` 2026-09-05 · Jesus · style: apply black formatting (post sdd-worker)
  - `a0471ded2d` 2026-09-04 · Jesus · feat(pep-420-llm-clients): TASK-2846 — hard-cut every provider-enum import outside parrot…
  - `77b599141f` 2026-09-04 · Jesus · feat(pep-420-llm-clients): TASK-2841 — core convention prerequisites

## Notes

- Earlier history (from F022): `e822289fe9` 2026-04-08 "feat(endcap-no-shelves-promotional): fix production
  crashes + improve illumination d…" — the type had production crashes shortly after the March 2026 rows shipped.
