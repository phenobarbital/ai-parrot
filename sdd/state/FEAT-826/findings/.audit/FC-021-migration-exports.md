---
id: FC-021
query_id: Q010
type: read
intent: "Follow-up: what the exported original and candidate rows for both configs contain (ids, type column, format)."
executed_at: 2026-11-06T16:05:30Z
duration_ms: 900
parent_id: FC-001
depth: 1
---

# FC-021 — Local exports: the rows are planogram_id 9 and 3 (not 23/24), type column already endcap_no_shelves_promotional, migrated on 2026-10-01

## Summary

`artifacts/planogram-migration/` (git-ignored) holds three export runs dated 2026-10-01. In the database they were exported from, the backlit row is `planogram_id=9` and the not-backlit row `planogram_id=3` — the ticket's production logs show 23 and 24, so ids differ between environments and `config_name` is the only stable key. In runs `2026-10-01` and `-b` the originals are legacy (`planogram_config` keys `advertisement_endcap, aisle, brand, category, shelves`; no `slots_definition`); in run `-c` the "original" already has `slots_definition` with zones `zone-header-1, zone-middle-1, zone-bottom-1` and `layout_profile` + `rule_bindings`, i.e. the mechanical conversion had been applied to that database by 13:38 UTC that day. `planogram_type` is `endcap_no_shelves_promotional` and `reference_images` is `{}` in every export.

## Citations

- path: `artifacts/planogram-migration/2026-10-01/original/epson_depot_ecotank_backlit_planogram_config.json`
  lines: null
  symbol: `(row export)`
  excerpt: |
    planogram_id: 9 · planogram_type: 'endcap_no_shelves_promotional' · is_active: True
    updated_at: 2026-04-08 15:49:40+00:00 · planogram_config keys: advertisement_endcap, aisle, brand, category, shelves
    slots_definition: None · reference_images: {}
- path: `artifacts/planogram-migration/2026-10-01/original/epson_depot_ecotank_not_backlit_planogram_config.json`
  lines: null
  symbol: `(row export)`
  excerpt: |
    planogram_id: 3 · planogram_type: 'endcap_no_shelves_promotional' · is_active: True
    updated_at: 2026-04-08 18:41:02+00:00 · slots_definition: None · reference_images: {}
- path: `artifacts/planogram-migration/2026-10-01/candidates/epson_depot_ecotank_backlit_planogram_config.json`
  lines: null
  symbol: `(converter candidate)`
  excerpt: |
    planogram_config keys: advertisement_endcap, aisle, brand, category, layout_profile, rule_bindings, shelves
    slots_definition.meta: {source: convert_config, planogram_type: endcap_no_shelves_promotional, brand: Epson, category: Printers}
    zones: zone-header-1, zone-middle-1, zone-bottom-1
- path: `artifacts/planogram-migration/2026-10-01-c/original/epson_depot_ecotank_backlit_planogram_config.json`
  lines: null
  symbol: `(row export)`
  excerpt: |
    planogram_id: 9 · updated_at: 2026-10-01 13:38:08+00:00
    planogram_config keys: advertisement_endcap, aisle, brand, category, layout_profile, rule_bindings, shelves
    zones: zone-header-1, zone-middle-1, zone-bottom-1
    columns include: account_name, brand, config_name, description, detection_model, llm_backend, object_identification_prompt,
      planogram_config, planogram_id, planogram_type, program_slug, reference_images, roi_detection_prompt, slots_definition, version
- path: `artifacts/planogram-migration/2026-10-01-c`
  lines: null
  symbol: `(directory)`
  excerpt: |
    apply.sql (44879 bytes)  llm_backend.sql (938 bytes)  candidates/  original/
    (no candidate file for either EcoTank end-cap row in run -c)

## Notes

- Values were extracted with a short script (JSON decoded, keys listed); the files were not read line by line, hence no line numbers.
- Which database these exports came from is not recorded in the files; the lane did not connect to any database. The current state of the rows in dev and in production (legacy / mechanically converted 3-zone / hand-rewritten 3- and 4-zone) is NOT established by this lane.
- Three generations of the same row exist: legacy (ticket logs, March), mechanical conversion (`zone-header-1/middle-1/bottom-1`, cv mode), hand rewrite (FC-002/FC-003, llm_detector).
- The table has `account_name` and `program_slug` columns; the ticket's rename ("EcoTank End Cap" → "EcoTank End Cap Backlit") is a display name that is not obviously one of the exported columns — the `description` column and the Epson360 UI source were not inspected.
- [cross-lane: type=wiki_query, intent=where the Epson360 "Planogram Type" display name (EcoTank End Cap Backlit / Not Backlit) is stored and how it maps to config_name / planogram_id]
