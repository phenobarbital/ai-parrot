---
id: FC-003
query_id: Q012
type: read
intent: "Local apply script holding the rewritten not-backlit row."
executed_at: 2026-11-06T16:03:45Z
duration_ms: 600
parent_id: null
depth: 0
---

# FC-003 — Rewritten not-backlit row: 4 zones, two with illumination OFF

## Summary

`artifacts/apply_epson_not_backlit.py` (git-ignored, 217 lines) has the same shape as the backlit script but defines **4** required zones: `zone-header-1` (kind `header`, band 0.0–0.20), `zone-backlit-1` (kind `backlit`, 0.20–0.42), `zone-comparison-1` (0.42–0.70), `zone-base-1` (0.70–1.0). Header and "backlit" zones both carry mandatory `illumination: off`; header and base carry mandatory `appearance`, while the comparison panel's `appearance` is non-mandatory. The ticket names three graphics (top, middle, bottom); this row splits the top into a header sign plus the Shaq panel.

## Citations

- path: `artifacts/apply_epson_not_backlit.py`
  lines: 40-45
  symbol: `ZONES`
  excerpt: |
    ZONES = [
        ("zone-header-1", "header", [0.0, 0.20], "header_sign"),
        ("zone-backlit-1", "backlit", [0.20, 0.42], "backlit_panel"),
        ("zone-comparison-1", "graphic", [0.42, 0.70], "comparison_panel"),
        ("zone-base-1", "graphic", [0.70, 1.0], "base_graphic"),
    ]
- path: `artifacts/apply_epson_not_backlit.py`
  lines: 48-59
  symbol: `RULES`
  excerpt: |
    "zone-header-1": {
        "illumination": "off",
        "texts": [text("EPSON"), text("EcoTank Printers")],
        ...
        "appearance": {"background_color": ["white"], "finish": ["matte"]},
        "appearance_mandatory": True,  # white/matte in every run
    },
    "zone-backlit-1": {
        "illumination": "off",
        "texts": [text("Goodbye Cartridges"), text("Hello Savings")],
- path: `artifacts/apply_epson_not_backlit.py`
  lines: 60-66
  symbol: `RULES`
  excerpt: |
    "zone-comparison-1": {
        "texts": [text("Choose The Right EcoTank For You")],
        "visual": ["comparison chart", "EcoTank printer models", "QR codes"],
        "appearance": {"background_color": ["blue"]},
        # Informative only: the crop often takes in the Shaq panel above it and reads "multicolor".
        "appearance_mandatory": False,
    },
- path: `artifacts/apply_epson_not_backlit.py`
  lines: 122-134
  symbol: `build_planogram_config`
  excerpt: |
    "aisle": {"name": "Epson EcoTank Endcap Not Backlit"},
    "layout_profile": {
        "perception_mode": "llm_detector",
        "roi_zone_labels": [label for *_, label in ZONES],
        "zone_selectors": [{"zone_id": zone_id, "kind": "zone", "band": band} for zone_id, _, band, _ in ZONES],
    },
    "rule_bindings": bindings,
- path: `artifacts/apply_epson_not_backlit.py`
  lines: 137-143
  symbol: `build_slots_definition`
  excerpt: |
    "meta": {"brand": "Epson", "category": "Printers", "planogram_type": "endcap_no_shelves_promotional"},
    "shelves": [],
    "zones": [{"zone_id": zone_id, "kind": kind, "shelf_id": None, "required": True} for zone_id, kind, _, _ in ZONES],

## Notes

- The ticket's four checks for this planogram are presence-oriented (top present, top correct image, middle present, bottom present). The row enforces more than that: mandatory text, visual, illumination-off and appearance rules on every zone, so a photo can fail on a rule the ticket never asked for.
- Same UPDATE/optimistic-lock/backup flow as FC-002 (lines 150-209).
