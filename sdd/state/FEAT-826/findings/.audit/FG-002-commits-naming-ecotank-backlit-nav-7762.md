---
id: FG-002
query_id: Q030
type: git_log
intent: "Commits mentioning the EcoTank / backlit planograms on any branch."
executed_at: 2026-11-06T16:04:38Z
duration_ms: 900
parent_id: null
depth: 0
---

# FG-002 — Commits naming EcoTank / backlit / NAV-7762 on any branch

## Summary

`git log --all -i -E --grep='ecotank|backlit|NAV-7762'` hits the 40-row cap, but **no commit on any branch
names NAV-7762** (a separate `--grep='NAV-7762'` returned nothing) and **none names the Office Depot rows**
`epson_depot_ecotank_backlit` / `_not_backlit` in its subject. The matches are (a) the April 2026
`endcap_backlit_multitier` type (FEAT-096, Juan2coder, PR #803) and its illumination fixes, (b) the
2026-10-01 migration of that type to the staged cycle, and (c) two 2026-10-02 cycle commits whose bodies
mention "EcoTank ET-2980" / `endcap_backlit_multitier` only in passing. The configuration work for
planograms 23/24 therefore left no trace in git: it lives in the database and in git-ignored local scripts.

## Citations

- path: `.` (all refs)
  commits:
  - `d80f01f92a` 2026-10-02 · Jesus Lara · feat(planogram): tiered shelves keep stacked products as slots of their own — body: "layout_profile.tiered_shelves (on by default for endcap_backlit_multitier)"
  - `56d1cbe508` 2026-10-02 · Jesus Lara · feat(planogram): resolve identity by contained name and matched reference — body: '("EcoTank ET-2980" -> "ET-2980")'
  - `e999bc826e` 2026-10-01 · Jesus Lara · feat(refactor-planogram-compliance): TASK-3866 — migrate EndcapBacklitMultitier to s…
  - `ba86ed29c3` 2026-09-19 · Jesus Lara · sdd: complete TASK-3431 — Provider-neutral call sites: endcap_backlit_multitier, gra…
  - `f58ffcb8cf` 2026-06-25 · Juan2coder · fix(planogram/endcap_backlit_multitier): rescue degenerate ROI and keep occluded pro…
  - `bc4c244e20` 2026-04-15 · phenobarbital · Merge pull request #803 from phenobarbital/feat-096-endcap-backlit-multitier
  - `e8d64cb73c` 2026-04-14 · Juan2coder · fix(endcap-backlit-multitier): extract illumination from shelf_identified, require e…
  - `47389cefe3` 2026-04-14 · Juan2coder · fix(endcap-backlit-multitier): use roi_illumination directly for header light check
  - `3f98aae7fb` 2026-04-14 · Juan2coder · fix(endcap-backlit-multitier): rewrite header scoring as 50/50 campaign+light
  - `0b4c347e56` 2026-04-13 · Juan2coder · feat(endcap-backlit-multitier): TASK-657 — add DB migration script for planogram_id=15
  - `043db4fe1b` 2026-04-08 · Juan2coder · fix(endcap): show actual illumination state in found_products on mismatch
  - `e822289fe9` 2026-04-08 · Juan2coder · feat(endcap-no-shelves-promotional): fix production crashes + improve illumination d…
  - `1072f93784` 2026-04-01 · Juan2coder · feat(planogram): add GraphicPanelDisplay illumination detection via ROI

## Notes

- The list is capped at 40 rows (oldest shown 2026-04-01); older matches may exist but predate the legacy
  rows' creation (2026-03) only by days and cannot concern the new cycle.
- `0b4c347e56` shows a precedent: a DB migration script for a planogram row (id 15) was once committed
  as part of a feature. No equivalent exists for ids 23/24.
- Illumination (backlit ON/OFF) was a first-class concern of the legacy types in April 2026
  (`roi_illumination`, "50/50 campaign+light" header scoring) — after the March 2026 rows of this ticket,
  which encoded the light check as a prompt trick.
- [cross-lane: type=grep, intent=confirm that no tracked file references epson_depot_ecotank_backlit / _not_backlit outside examples/ and git-ignored artifacts/]
