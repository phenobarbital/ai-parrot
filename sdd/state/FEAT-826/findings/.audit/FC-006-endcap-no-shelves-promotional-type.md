---
id: FC-006
query_id: Q015
type: read
intent: "Planogram type used for graphics-only endcaps."
executed_at: 2026-11-06T16:05:20Z
duration_ms: 500
parent_id: null
depth: 0
---

# FC-006 — EndcapNoShelvesPromotional is a thin type over the shared stages; default perception is CV

## Summary

`EndcapNoShelvesPromotional` ("Shelf-less promotional endcap: configured zones, text, and illumination") only supplies two provisional zone shape profiles (`promo_backlit_zone`, `promo_poster_zone`) and delegates perceive/identify/compare to the shared stages. Its default layout is `perception_mode="cv"`, `anchor_rule=SHAPE_IS_SLOT`, `identify_strategy=FULL_IMAGE`, `min_usable_shapes=1`, so a row must override `perception_mode` to get the ROI/LLM path. When the configuration lacks legacy keys, `_description()` falls back to a minimal `PlanogramDescription` with `shelves=[]`.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
  lines: 42-63
  symbol: `_zone_profiles`
  excerpt: |
    backlit = ShapeProfile(
        name="promo_backlit_zone",
        kind=ShapeKind.ZONE.value,
        min_width=0.40,
        ...
        polarity="bright",
    )
    poster = backlit.model_copy(update={"name": "promo_poster_zone", "polarity": "edge", ...})
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
  lines: 66-84
  symbol: `EndcapNoShelvesPromotional.default_layout_profile`
  excerpt: |
    requires_slots_definition: ClassVar[bool] = True
    min_usable_shapes: ClassVar[int] = 1
    ...
    return LayoutProfile(
        shape_profiles=_zone_profiles(),
        anchor_rule=AnchorRule.SHAPE_IS_SLOT,
        identify_strategy=IdentifyStrategy.FULL_IMAGE,
        perception_mode="cv",
        min_usable_shapes=1,
    )
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
  lines: 105-117
  symbol: `EndcapNoShelvesPromotional._description`
  excerpt: |
    try:
        return self.config.get_planogram_description()
    except Exception as exc:  # noqa: BLE001 - promotional configs may omit legacy keys
        ...
        return PlanogramDescription(
            brand=str(config.get("brand", "")),
            category=str(config.get("category", "promotional")),
            aisle=AisleConfig(name=str(config.get("aisle", "promotional"))),
            shelves=[],
        )

## Notes

- In the fallback, `aisle=AisleConfig(name=str(config.get("aisle", "promotional")))` stringifies the whole `aisle` dict when the row stores `{"name": ...}` (as both rewritten rows do, FC-002/FC-003). Cosmetic only if `get_planogram_description()` succeeds first; not verified which branch the rewritten rows take.
- A second zone-oriented type, `graphic_panel_display`, exists in the registry (FC-005); it was not read in this lane.
