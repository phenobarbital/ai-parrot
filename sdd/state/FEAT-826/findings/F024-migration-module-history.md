---
id: F024
query_id: Q032
type: git_log
intent: "History of the migration module."
executed_at: 2026-11-06T16:04:38Z
duration_ms: 300
parent_id: null
depth: 0
lanes: [git]
merged_from: [FG-004]
---
# F024 — History of planogram/migration.py

## Summary

`migration.py` has 9 commits since 2026-08-01, all by Jesus Lara: created on 2026-09-19 by FEAT-574
(TASK-3448 "config migration tooling and runbook"), reworked on 2026-10-01 by FEAT-612 (TASK-3877) and four
same-day fixes (converter no longer drops text rules, zone selectors grounded, facing descriptors seeded from
the legacy row, fixture-band zone selectors, fact/price tags converted). **The file has not changed since
2026-10-01**, so the converter predates the appearance rule (2026-10-15), the opt-in `visual_features`
checklist and the per-requirement text features — it cannot emit any of them.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py`
  commits:
  - `d620279f1f` 2026-10-01 · Jesus Lara · feat(planogram): fixture-band zone selectors for fragmented zone detections
  - `053feed244` 2026-10-01 · Jesus Lara · feat(planogram-fact-tag-rule): TASK-4007 — convert fact/price tags into fact_tag_pre…
  - `53c0a1db3c` 2026-10-01 · Jesus Lara · feat(planogram): seed facing descriptors from the legacy row on conversion
  - `4ca1d813b7` 2026-10-01 · Jesus Lara · fix(planogram): converter no longer drops text rules; ground zone selectors
  - `f864d02aec` 2026-10-01 · Jesus Lara · style: apply black formatting (post sdd-worker)
  - `fa3b61a0a0` 2026-10-01 · Jesus Lara · fix(refactor-planogram-compliance): resolve ruff B905/B007 review findings
  - `dea49e7ed9` 2026-10-01 · Jesus Lara · style(refactor-planogram-compliance): TASK-3877 — engine lint autofix
  - `d6294b4e9b` 2026-10-01 · Jesus Lara · feat(refactor-planogram-compliance): TASK-3877 — engine-committed coder deliverable
  - `c101f23e7d` 2026-09-19 · Jesus Lara · feat(new-planogram-pipeline): TASK-3448 — config migration tooling and runbook

## Notes

- [cross-lane: type=grep, intent=check whether migration.py mentions appearance / illumination / perception_mode at all (expected: no, given its last change is 2026-10-01)]
