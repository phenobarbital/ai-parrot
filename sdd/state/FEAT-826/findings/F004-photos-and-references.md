---
id: F004
query_id: Q013
type: tree
intent: "Store photos and reference images available for the two planograms."
executed_at: 2026-11-06T16:03:15Z
duration_ms: 300
parent_id: null
depth: 0
lanes: [codebase]
merged_from: [FC-004]
---
# F004 — 6 backlit and 6 not-backlit photos on disk; no references folder for either

## Summary

`examples/planogram/images/epson_depot_ecotank_backlit_planogram_config/` holds 6 photos and the not-backlit folder holds 6; neither has a `references/` subfolder. Two of the not-backlit photos are the ticket attachments for Office Depot stores 2270 and 2363. Result folders exist for both under `examples/planogram/results/`.

## Citations

- path: `examples/planogram/images/epson_depot_ecotank_backlit_planogram_config`
  lines: null
  symbol: `(directory)`
  excerpt: |
    881dbf0c-a6e7-4f64-999e-be005116a532-recap.jpg
    cdbda975-6b92-4692-a7d3-55f81968ed68.jpeg
    photo_2026-10-15_19-26-30 (2).jpg
    photo_2026-10-15_19-26-30 (3).jpg
    photo_2026-10-15_19-26-30.jpg
    photo_2026-10-15_19-34-05.jpg
- path: `examples/planogram/images/epson_depot_ecotank_not_backlit_planogram_config`
  lines: null
  symbol: `(directory)`
  excerpt: |
    151c4354-3bf2-4dfd-be07-23e2515d27f3-recap.jpg
    2026-02-03-Joe-Montoya-Office-Depot-2270.jpeg
    2026-02-03-Kip-Kerrick-Office-Depot-2363.jpeg
    photo_2026-10-15_19-26-45 (2).jpg
    photo_2026-10-15_19-26-45 (3).jpg
    photo_2026-10-15_19-26-45.jpg
- path: `examples/planogram/results`
  lines: null
  symbol: `(directory)`
  excerpt: |
    epson_depot_ecotank_backlit_planogram_config
    epson_depot_ecotank_not_backlit_planogram_config

## Notes

- `photo_2026-10-15_19-26-45 (3).jpg` and `photo_2026-10-15_19-26-45.jpg` have the same byte size (270111): probably duplicates, so the not-backlit set may be 5 distinct photos.
- The four other ticket attachments (stores 107, 201, 6600, 143) are not in either folder under their Jira names.
- Results folders were not opened (out of scope for the lane; they are generated output).
