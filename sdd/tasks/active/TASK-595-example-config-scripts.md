# TASK-595: Create Example Planogram Configuration Scripts

**Feature**: planogram-new-types
**Spec**: `sdd/specs/planogram-new-types.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-592, TASK-593
**Assigned-to**: unassigned

---

## Context

This task creates example Python scripts that generate JSON `planogramConfig` payloads for the two new types, ready for insertion into `troc.planograms_configurations` in PostgreSQL.

Implements Spec Section 3 — Module 4.

---

## Scope

- Create two example Python scripts:
  - `product_counter_config.py` — generates a complete `PlanogramConfig` JSON for `product_counter` type.
  - `endcap_no_shelves_config.py` — generates a complete `PlanogramConfig` JSON for `endcap_no_shelves_promotional` type.
- Each script should print the JSON string and optionally include an SQL INSERT statement.
- Include realistic prompts (`roi_detection_prompt`, `object_identification_prompt`) and `planogram_config` dictionaries.

**NOT in scope**:
- Actually running the SQL against a database
- Type class implementation (TASK-592, TASK-593)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/examples/planogram_configs/product_counter_config.py` | CREATE | Example config generator for product_counter |
| `packages/ai-parrot-pipelines/examples/planogram_configs/endcap_no_shelves_config.py` | CREATE | Example config generator for endcap_no_shelves_promotional |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/models.py:29
class PlanogramConfig(BaseModel):
    planogram_id: Optional[int]          # line 34
    config_name: str                     # line 39, default="default_planogram_config"
    planogram_type: str                  # line 44, default="product_on_shelves"
    planogram_config: Dict[str, Any]     # line 50
    roi_detection_prompt: str            # line 55
    object_identification_prompt: str    # line 60
    reference_images: Dict[str, Union[str, Path, List[str], List[Path], Image.Image]]  # line 65
    confidence_threshold: float          # line 74, default=0.25
    detection_model: str                 # line 79, default="yolo11l.pt"
```

### Existing References
```sql
-- packages/ai-parrot-pipelines/src/parrot_pipelines/table.sql
-- Table: troc.planograms_configurations
-- Contains the JSON planogram configs
```

### Does NOT Exist
- ~~`PlanogramConfig.expected_elements`~~ — not a model field
- ~~`PlanogramConfig.illumination_expected`~~ — not a model field; this goes inside `planogram_config` dict

---

## Implementation Notes

### Example JSON Structure for product_counter
```json
{
  "planogram_type": "product_counter",
  "config_name": "epson_ecotank_counter",
  "planogram_config": {
    "brand": "Epson",
    "expected_elements": ["product", "promotional_background", "information_label"],
    "scoring_weights": {
      "product": 1.0,
      "promotional_background": 0.5,
      "information_label": 0.3
    }
  },
  "roi_detection_prompt": "Identify the product counter/podium display area...",
  "object_identification_prompt": "Within the counter display, identify: 1) the main product, 2) the promotional background material, 3) the information label..."
}
```

### Example JSON Structure for endcap_no_shelves_promotional
```json
{
  "planogram_type": "endcap_no_shelves_promotional",
  "config_name": "epson_endcap_promo",
  "planogram_config": {
    "brand": "Epson",
    "expected_elements": ["backlit_panel", "lower_poster"],
    "illumination_expected": "ON"
  },
  "roi_detection_prompt": "Identify the full promotional endcap display. Focus on the retro-illuminated upper panel...",
  "object_identification_prompt": "Within the endcap, identify: 1) the backlit panel at the top, 2) the promotional poster at the bottom..."
}
```

---

## Acceptance Criteria

- [ ] Both scripts run without errors: `python product_counter_config.py`
- [ ] JSON output is valid and parseable
- [ ] Config JSON matches `PlanogramConfig` model schema
- [ ] Realistic prompts for each type's detection needs

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for context on both planogram types
2. **Check** that `packages/ai-parrot-pipelines/examples/` directory exists (create if needed)
3. **Implement** both scripts
4. **Verify** JSON output is valid
5. **Move this file** to `tasks/completed/`
6. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
