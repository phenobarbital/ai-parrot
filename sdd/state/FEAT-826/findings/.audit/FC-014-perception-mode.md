---
id: FC-014
query_id: Q022
type: grep
intent: "perception_mode / llm_detector handling for zone-only rows."
executed_at: 2026-11-06T16:10:00Z
duration_ms: 300
parent_id: null
depth: 0
---

# FC-014 — Every type defaults to perception_mode "cv"; llm_detector is a per-row override

## Summary

All six types set `perception_mode="cv"` in their default layout. `LayoutProfile.perception_mode` is `Literal["cv", "llm_detector"]`; a row overrides it via `planogram_config.layout_profile.perception_mode` or a top-level `perception_mode` (a contradiction between the two is a validation error). In `llm_detector` mode `stages/perceive.py` takes a dedicated branch and the generic detector fallback in `plan.py` is disabled. `convert_config` only carries a top-level `perception_mode` over; it never sets `llm_detector` on its own.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py`
  lines: 81-85
  symbol: `LayoutProfile`
  excerpt: |
    perception_mode: Literal["cv", "llm_detector"] = "cv"
    roi_detection: bool = True
    roi_zone_labels: List[str] = Field(default_factory=list)
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py`
  lines: 174-180
  symbol: `resolve_layout_profile`
  excerpt: |
    top_perception_mode = (config or {}).get("perception_mode")
    if top_perception_mode is not None:
        if "perception_mode" in overrides and overrides["perception_mode"] != top_perception_mode:
            ... invalid layout_profile.perception_mode: contradicts top-level perception_mode
        overrides["perception_mode"] = top_perception_mode
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
  lines: 82-82
  symbol: `EndcapNoShelvesPromotional.default_layout_profile`
  excerpt: |
    perception_mode="cv",
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/perceive.py`
  lines: 308-312
  symbol: `(perceive stage)`
  excerpt: |
    if profile.perception_mode == "llm_detector":
    ...
            return result.model_copy(update={"errors": [f"{image_id}: llm_detector produced
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`
  lines: 365-365
  symbol: `PlanogramCompliance._fallback_if_needed`
  excerpt: |
    if threshold <= 0 or layout.perception_mode == "llm_detector":
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py`
  lines: 618-620
  symbol: `convert_config`
  excerpt: |
    if "perception_mode" in config:
        layout["perception_mode"] = config["perception_mode"]
        report.warnings.append("perception_mode accepted and moved to layout_profile")

## Notes

- The mechanically converted candidates for the two rows (FC-021) therefore run in `cv` mode; only the hand-written apply scripts (FC-002/FC-003) set `llm_detector`, with a comment that a lit lightbox alone satisfies the CV poster profile and would skip the ROI.
- `stages/perceive.py` was not read beyond the two matched lines.
