---
id: F001
query_id: Q010
type: grep
intent: "Where the two config names are referenced in the repo (scripts, tests, examples, docs)."
executed_at: 2026-11-06T16:03:10Z
duration_ms: 2100
parent_id: null
depth: 0
lanes: [codebase]
merged_from: [FC-001]
---
# F001 — The two config names appear in no package code, test or tracked example

## Summary

`epson_depot_ecotank_(not_)?backlit` has 70 hits, none in `packages/` source, `packages/*/tests` or the tracked e2e harness. Tracked hits: only `sdd/specs/planogram-appearance-rule.spec.md` (2). Everything else is git-ignored local material: the two `artifacts/apply_epson_*backlit.py` scripts, the `artifacts/planogram-migration/2026-10-01*/` exports (original + candidates + `apply.sql`, `zone_bands.sql`) and generated `.parrot/wiki/` pages. The rows therefore exist only as database data plus local, uncommitted scripts.

## Citations

- path: `sdd/specs/planogram-appearance-rule.spec.md`
  lines: 29-29
  symbol: `(spec text)`
  excerpt: |
    Measured on `epson_depot_ecotank_not_backlit_planogram_config` (4 valid photos, 20 zone
- path: `sdd/specs/planogram-appearance-rule.spec.md`
  lines: 55-55
  symbol: `(spec text)`
  excerpt: |
    `epson_depot_ecotank_not_backlit_planogram_config` is a follow-up data change once this ships.
- path: `artifacts/apply_epson_backlit.py`
  lines: 33-33
  symbol: `CONFIG_NAME`
  excerpt: |
    CONFIG_NAME = "epson_depot_ecotank_backlit_planogram_config"
- path: `artifacts/apply_epson_not_backlit.py`
  lines: 29-29
  symbol: `CONFIG_NAME`
  excerpt: |
    CONFIG_NAME = "epson_depot_ecotank_not_backlit_planogram_config"
- path: `artifacts/planogram-migration/2026-10-01-b/apply.sql`
  lines: null
  symbol: `(6 matches)`
  excerpt: |
    (generated UPDATE statements for both rows; not read in full)

## Notes

The default `grep` here is wrapped by a filter that honours `.gitignore`; the first pass returned only the spec. The counts above come from an unfiltered pass that excluded `.git`, worktrees, `results/`, `planogram_backups/`.
Hit distribution: `.parrot/wiki/configs` 28, `.parrot/wiki/overviews` 14, `artifacts/planogram-migration/**` 16, apply scripts 4, spec 2 (+2 in a `.worktrees/pr-1944-fix` copy).
