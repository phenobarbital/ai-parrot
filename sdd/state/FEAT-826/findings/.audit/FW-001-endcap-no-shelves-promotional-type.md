---
id: FW-001
query_id: Q001
type: wiki_query
intent: "Orient: how a zone-only promotional endcap (graphics, no products) is modelled as a planogram type."
executed_at: 2026-11-06T16:11:08Z
duration_ms: 0
parent_id: null
depth: 0
---

# FW-001 — `endcap_no_shelves_promotional` is the zone-only promotional endcap type; it defaults to CV perception

## Summary

The wiki's top hits are the FEAT-090 spec (`sdd/specs/endcap-no-shelves-promotional-fix.spec.md`) and the type
module itself. `EndcapNoShelvesPromotional` ("Shelf-less promotional endcap: configured zones, text, and
illumination") only supplies two provisional zone shape profiles (`promo_backlit_zone`, polarity `bright`;
`promo_poster_zone`, polarity `edge`) and delegates perceive/identify/compare to the shared cycle stages. Its
default layout profile is `perception_mode="cv"`, `anchor_rule=SHAPE_IS_SLOT`, `identify_strategy=FULL_IMAGE`,
`min_usable_shapes=1`, and it declares `requires_slots_definition = True`.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
  lines: 66-117
  symbol: `EndcapNoShelvesPromotional`
  wiki: `file:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py` (page read in full; reached from Q001 result `file:sdd/specs/endcap-no-shelves-promotional-fix.spec.md`, score 1.00)
  excerpt: |
    class EndcapNoShelvesPromotional(AbstractPlanogramType):
        """Shelf-less promotional endcap: configured zones, text, and illumination."""
        requires_slots_definition: ClassVar[bool] = True
        uses_enhanced_image: ClassVar[bool] = False
        min_usable_shapes: ClassVar[int] = 1

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
  lines: 74-84
  symbol: `EndcapNoShelvesPromotional.default_layout_profile`
  excerpt: |
    return LayoutProfile(
        shape_profiles=_zone_profiles(),
        anchor_rule=AnchorRule.SHAPE_IS_SLOT,
        fill_gaps=False,
        untagged_bottom_row=False,
        identify_strategy=IdentifyStrategy.FULL_IMAGE,
        perception_mode="cv",
        min_usable_shapes=1,
    )

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
  lines: 33-63
  symbol: `_zone_profiles`
  excerpt: |
    backlit = ShapeProfile(name="promo_backlit_zone", kind=ShapeKind.ZONE.value,
        min_width=0.40, max_width=1.0, min_height=0.06, max_height=0.35,
        min_aspect=1.5, max_aspect=12.0, polarity="bright", ...)
    poster = backlit.model_copy(update={"name": "promo_poster_zone", "polarity": "edge", ...})

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
  lines: 105-117
  symbol: `EndcapNoShelvesPromotional._description`
  excerpt: |
    try:
        return self.config.get_planogram_description()
    except Exception as exc:  # noqa: BLE001 - promotional configs may omit legacy keys
        ...
        return PlanogramDescription(brand=..., category=..., aisle=AisleConfig(...), shelves=[])

## Notes

- Other Q001 hits: `flowtask::file:sdd/proposals/endcap-no-shelves-promotional-fix.proposal.md` (1.00),
  `file:sdd/tasks/completed/TASK-625-fix-detect-objects-n-zones.md` (0.88),
  `file:packages/ai-parrot-pipelines/examples/planogram_configs/endcap_no_shelves_config.py` (0.58).
- Both provisional zone profiles cap `max_height` at 0.35 of the image and require `min_aspect` 1.5: a tall
  comparison panel or the floor base graphic need not match either CV profile. See FW-007 for the
  `perception_mode` / `roi_detection` switches.
- [cross-lane: type=read, intent=confirm in stages/perceive.py when the LLM-detector fallback runs for a zone-only type whose CV pass finds >= min_usable_shapes (1) shape]
