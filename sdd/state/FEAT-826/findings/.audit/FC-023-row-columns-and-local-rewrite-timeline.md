---
id: FC-023
query_id: Q010
type: read
intent: "Follow-up: which row column holds the display name, and when the local rows were rewritten (backups), and whether any e2e result of the rewritten rows is kept."
executed_at: 2026-11-06T16:17:00Z
duration_ms: 900
parent_id: FC-021
depth: 1
---

# FC-023 — Row `description` holds the display name; local rows were hand-rewritten on 2026-10-15; no e2e result of the rewritten rows is kept

## Summary

The exported rows carry `description = 'EcoTank End Cap (Backlit)'` and `'EcoTank End Cap (Non-Backlit)'`, `account_name = 'Office Depot'`, `program_slug = 'epson'`, `planogram_type = 'endcap_no_shelves_promotional'`, `llm_backend = 'google:gemini-3.7-flash'`, and still hold the legacy `object_identification_prompt`, `detection_model = 'yolo11l.pt'` and geometry ratios. Seven local backups in `planogram_backups/` (git-ignored) show the rewrite sequence of 2026-10-15 in the exported database: the not-backlit row went from 3 mechanical zones to 4 zones at 16:05Z, the backlit row from `zone-header-1/middle-1/bottom-1` to `zone-header-1/comparison-1/base-1` at 17:17Z and gained `perception_mode: llm_detector` at 17:35Z. The newest backup of each row predates the final apply and lists no `appearance` binding, so the applied end state is not captured in any file. The only e2e result folders for the two configs date from 2026-10-01, before the rewrite.

## Citations

- path: `artifacts/planogram-migration/2026-10-01-c/original/epson_depot_ecotank_backlit_planogram_config.json`
  lines: null
  symbol: `description`
  excerpt: |
    planogram_id = '9'
    description = 'EcoTank End Cap (Backlit)'
    account_name = 'Office Depot'
    planogram_type = 'endcap_no_shelves_promotional'
    llm_backend = 'google:gemini-3.7-flash'
    created_at = '2026-01-23 15:02:36.565895+00:00'
- path: `artifacts/planogram-migration/2026-10-01-c/original/epson_depot_ecotank_not_backlit_planogram_config.json`
  lines: null
  symbol: `description`
  excerpt: |
    planogram_id = '3'
    description = 'EcoTank End Cap (Non-Backlit)'
    account_name = 'Office Depot'
    planogram_type = 'endcap_no_shelves_promotional'
- path: `planogram_backups/epson_depot_ecotank_backlit_planogram_config.20261015T182502Z.json`
  lines: null
  symbol: `(row backup)`
  excerpt: |
    id 9 | updated_at 2026-10-15 17:35:50
    zones ['zone-header-1', 'zone-comparison-1', 'zone-base-1'] | perception_mode llm_detector
    rule kinds ['illumination', 'text_requirements', 'visual_features', 'zone_present']
- path: `planogram_backups/epson_depot_ecotank_not_backlit_planogram_config.20261015T182500Z.json`
  lines: null
  symbol: `(row backup)`
  excerpt: |
    id 3 | updated_at 2026-10-15 16:22:08
    zones ['zone-header-1', 'zone-backlit-1', 'zone-comparison-1', 'zone-base-1'] | perception_mode None
    rule kinds ['illumination', 'text_requirements', 'visual_features', 'zone_present']
- path: `examples/planogram/results/epson_depot_ecotank_backlit_planogram_config`
  lines: null
  symbol: `(directory, last modified 2026-10-01T18:49)`
- path: `examples/planogram/results/epson_depot_ecotank_not_backlit_planogram_config`
  lines: null
  symbol: `(directory, last modified 2026-10-01T18:36)`

## Notes

- Values were extracted with a short script (JSON decoded, scalar columns printed); files were not read line by line, hence no line numbers.
- The ticket asks for the names "EcoTank End Cap Backlit" / "EcoTank End Cap Not Backlit" and the UI screenshot of 2026-03-17 lists exactly those in the "Planogram Type" filter; the row `description` values exported on 2026-10-01 read "EcoTank End Cap (Backlit)" / "(Non-Backlit)", i.e. the media-tag wording. Whether the Epson360 filter reads `description` or another source (and from which database) is not answerable from this repository.
- Row `created_at` is 2026-01-23 for both in the exported database, earlier than the ticket (2026-03-05): the exported database is not the one the ticket's March logs ran against (ids 9/3 vs 23/24).
- The local `docker_postgres_1` container was not running during this session, so the live state of the local rows was not queried. No production or dev database was contacted.
- Each backup is the state *before* an apply; the last apply of each script (which adds `appearance` rules per FC-002/FC-003) has no later backup, so "what is in the database now" rests on the scripts, not on a captured row.
