---
id: FC-002
query_id: Q011
type: read
intent: "Local apply script holding the rewritten backlit row (new-cycle candidate config)."
executed_at: 2026-11-06T16:03:40Z
duration_ms: 600
parent_id: null
depth: 0
---

# FC-002 — Rewritten backlit row: 3 zones, llm_detector, illumination ON, no reference images

## Summary

`artifacts/apply_epson_backlit.py` (git-ignored, 212 lines) rewrites three columns of the active row — `planogram_config`, `slots_definition`, `roi_detection_prompt` — after a `check_row` preflight, dry-run by default, with a JSON backup and an `updated_at` optimistic lock on `--apply`. The row becomes 3 required zones (`zone-header-1` kind `backlit` band 0.0–0.35, `zone-comparison-1` 0.35–0.65, `zone-base-1` 0.65–1.0), each with mandatory `zone_present`, `text_requirements`, `visual_features`; the header adds mandatory `illumination: on` (penalty 0.5); comparison and base add mandatory `appearance`. `layout_profile.perception_mode` is `llm_detector`. It writes no `reference_images`, no `shelves`, no `advertisement_endcap`, and does not touch the `planogram_type` column (only `slots_definition.meta.planogram_type`).

## Citations

- path: `artifacts/apply_epson_backlit.py`
  lines: 45-49
  symbol: `ZONES`
  excerpt: |
    ZONES = [
        ("zone-header-1", "backlit", [0.0, 0.35], "backlit_header"),
        ("zone-comparison-1", "graphic", [0.35, 0.65], "comparison_panel"),
        ("zone-base-1", "graphic", [0.65, 1.0], "base_graphic"),
    ]
- path: `artifacts/apply_epson_backlit.py`
  lines: 51-56
  symbol: `RULES`
  excerpt: |
    "zone-header-1": {
        "illumination": "on",
        "texts": [text("EPSON"), text("Goodbye Cartridges"), text("Hello Savings")],
        "visual": ["EPSON logo", "image of Shaquille O'Neal", "EcoTank printer", "Goodbye Cartridges Hello Savings"],
    },
- path: `artifacts/apply_epson_backlit.py`
  lines: 99-103
  symbol: `build_planogram_config`
  excerpt: |
    if "illumination" in spec:
        bindings.append(
            {"rule_id": f"illumination:{zone_id}", "kind": "illumination", "target_id": zone_id,
             "params": {"required": spec["illumination"], "penalty": 0.5}, "mandatory": True}
        )
- path: `artifacts/apply_epson_backlit.py`
  lines: 117-129
  symbol: `build_planogram_config`
  excerpt: |
    return {
        "brand": "Epson",
        "category": "Printers",
        "aisle": {"name": AISLE_NAME},
        "layout_profile": {
            "perception_mode": "llm_detector",
            "roi_zone_labels": [label for *_, label in ZONES],
            "zone_selectors": [{"zone_id": zone_id, "kind": "zone", "band": band} for zone_id, _, band, _ in ZONES],
        },
        "rule_bindings": bindings,
    }
- path: `artifacts/apply_epson_backlit.py`
  lines: 132-138
  symbol: `build_slots_definition`
  excerpt: |
    "meta": {"brand": "Epson", "category": "Printers", "planogram_type": "endcap_no_shelves_promotional"},
    "shelves": [],
    "zones": [{"zone_id": zone_id, "kind": kind, "shelf_id": None, "required": True} for zone_id, kind, _, _ in ZONES],
- path: `artifacts/apply_epson_backlit.py`
  lines: 187-200
  symbol: `main`
  excerpt: |
    "UPDATE troc.planograms_configurations "
    "SET planogram_config = $2::jsonb, slots_definition = $3::jsonb, roi_detection_prompt = $4, "
    "updated_at = now() "
    "WHERE config_name = $1 AND is_active = TRUE AND updated_at = $5",  # optimistic lock
- path: `artifacts/apply_epson_backlit.py`
  lines: 14-18
  symbol: `(module docstring)`
  excerpt: |
    python apply_epson_backlit.py                 # dry run against the ENV database
    python apply_epson_backlit.py --apply         # write
    ENV=prod python apply_epson_backlit.py --apply
    Needs ai-parrot-pipelines >= 1.2.2 on the server that runs the compliance (zone bands + ROI zones).

## Notes

- Ticket mapping: "Top Graphic is present" → `zone_present:zone-header-1`; "correct image" → `text_requirements` + `visual_features` (+ `illumination: on`); there is no image-similarity check and no reference image.
- The ROI prompt (lines 78-88) asks for `endcap`, `backlit_header`, `comparison_panel`, `base_graphic` and a `Light: ON/OFF` note in `content`.
- The script is the only place the candidate lives; it is not tracked by git.
