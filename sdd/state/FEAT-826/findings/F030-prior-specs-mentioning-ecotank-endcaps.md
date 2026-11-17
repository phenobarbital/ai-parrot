---
id: F030
query_id: Q009
type: wiki_query
intent: "Prior SDD decisions on planogram config rows (appearance rule, refactor, new pipeline)."
executed_at: 2026-11-06T16:11:08Z
duration_ms: 0
parent_id: null
depth: 0
lanes: [wiki]
merged_from: [FW-008]
---
# F030 — Three earlier specs touch these exact planograms: flowtask FEAT-004 (ids 23/24 named), FEAT-090 (type switch never ticked), FEAT-683 (row update deferred)

## Summary

A wiki query for the literal `epson_depot_ecotank_backlit_planogram_config` returns one page only: the FlowTask
spec FEAT-004 "Graphic Panel Display Planogram Type" (2026-03-20, approved), which lists
`epson_depot_ecotank_backlit_planogram_config` (id 23) and `..._not_backlit_...` (id 24) among the configurations
it serves and defines the legacy convention `"illumination_status: ON|OFF"` inside `visual_features`. ai-parrot
FEAT-090 (2026-04-07, approved) calls `endcap_no_shelves_promotional` the semantically correct type for the Epson
EcoTank endcaps and carries an unticked acceptance item to switch the EcoTank config from `graphic_panel_display`
to it. FEAT-683 (2026-10-15) was measured on the not-backlit row and defers its row update. The specs
`refactor-planogram-compliance`, `new-planogram-pipeline`, `new-planogram-compliance-algo`,
`planogram-compliance-handler` and `planogram-new-types` contain no mention of EcoTank / Office Depot.

## Citations

- path: `/home/jesuslara/proyectos/flowtask/sdd/specs/graphic-panel-display.spec.md`
  lines: 3-6, 28-29, 112-113
  symbol: `FEAT-004`
  wiki: `flowtask::file:sdd/specs/graphic-panel-display.spec.md` (query "epson_depot_ecotank_backlit_planogram_config", score 1.00, the only result)
  excerpt: |
    **Feature ID**: FEAT-004 ... **Status**: approved
    - `epson_depot_ecotank_backlit_planogram_config` (id 23)
    - `epson_depot_ecotank_not_backlit_planogram_config` (id 24)
    - `"illumination_status: ON"` → backlit expected
    - `"illumination_status: OFF"` → not backlit expected
- path: `sdd/specs/endcap-no-shelves-promotional-fix.spec.md`
  lines: 3-6, 16-17, 24-30, 195-196
  symbol: `FEAT-090`
  wiki: `file:sdd/specs/endcap-no-shelves-promotional-fix.spec.md` (Q001 score 1.00)
  excerpt: |
    `endcap_no_shelves_promotional` is the semantically correct pipeline type for Epson
    EcoTank endcap displays and any retail endcap that has: no physical products on shelves, a backlit
    illuminated header graphic, one or more promotional graphic zones below
    1. **`_check_illumination` is never called** ... endcaps with the backlight OFF are silently scored as compliant.
    2. **Only 2 hardcoded zones** — `backlit_panel` and `lower_poster` are fixed constants.
    - [ ] Epson EcoTank config switches from `graphic_panel_display` to
          `endcap_no_shelves_promotional` with identical compliance results
- path: `sdd/migrations/FEAT-096-planogram15-config.sql`
  lines: (not read)
  symbol: `FEAT-096`
  wiki: `file:sdd/migrations/FEAT-096-planogram15-config.sql` (query "EcoTank end cap backlit Office Depot planogram", score 1.00; page not opened)
  excerpt: |
    (stub only — a committed planogram config SQL migration exists as precedent; content not inspected)

## Notes

- Constraint for a fix here: every one of these specs treats the config **row** as a hand-authored data change
  outside the code feature (FEAT-683 Non-Goals; FEAT-612 "automatic SQL application" is a non-goal; runbook step 5
  "Apply the approved SQL update by hand"). None of them ships the rewritten rows for ids 23/24.
- The FEAT-090 problem statement describes the pre-FEAT-612 implementation (`_check_illumination`,
  `detect_objects`); the current type module is a thin delegate to the shared cycle (F006), so those three bugs
  no longer describe the code, but the unticked config-switch item was never recorded as done in the spec.
- The legacy id list in FEAT-004 (id 5 `epson_ecotank_planogram_config`, id 12 `epson_depot_ecotank_planogram_config`,
  ids 13/14 projector) is the flowtask spec's own numbering; not verified against a database in this lane.
- A second EcoTank-related spec surfaced but was not opened: `file:sdd/specs/endcap-backlit-multitier.spec.md`
  (score 0.63).
- [cross-lane: type=read, intent=open sdd/migrations/FEAT-096-planogram15-config.sql as a precedent for committing a planogram row change as SQL]
- [citation moved, §4c dedup] `sdd/specs/planogram-appearance-rule.spec.md` :: `FEAT-683` lines 29, 54-55 — cited in F008.
