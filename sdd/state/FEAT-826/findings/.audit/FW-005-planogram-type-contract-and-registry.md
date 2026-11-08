---
id: FW-005
query_id: Q005
type: wiki_page
intent: "API outline of the planogram type contract."
executed_at: 2026-11-06T16:11:08Z
duration_ms: 0
parent_id: null
depth: 0
---

# FW-005 — Type contract = default_layout_profile + perceive/identify/compare; six registered types, three of them candidates for an endcap

## Summary

`AbstractPlanogramType` requires four cycle members (`default_layout_profile`, `perceive`, `identify`,
`compare`) and its `validate_contract` raises `ValueError` before any inference when the config has no
`slots_definition`. The types package exports six composables: `ProductOnShelves`, `GraphicPanelDisplay`,
`ProductCounter`, `EndcapNoShelvesPromotional`, `EndcapBacklitMultitier`, `InkWall`. For a graphics-only endcap
with three zones the two zone-only types fit — `EndcapNoShelvesPromotional` (FW-001) and `GraphicPanelDisplay`
("Zone-only graphic panel: presence, text and illumination of configured zones ... no product counting and no
fact-tag path") — while `EndcapBacklitMultitier` is "Backlit header + product shelves" and expects product
facings.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py`
  lines: 57-75
  symbol: `AbstractPlanogramType.validate_contract`
  wiki: `file:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` (Q005 page; Q-orientation score 1.00)
  excerpt: |
    config_name = getattr(self.config, "config_name", None)
    if getattr(self.config, "slots_definition", None) is None:
        raise ValueError(
            f"{type(self).__name__} requires a slots_definition but config {config_name!r} has none; "
            "see docs/pipelines/planogram-cycle-migration.md"
        )

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py`
  lines: 23-115
  symbol: `AbstractPlanogramType`
  excerpt: |
    _CYCLE_HOOKS: ClassVar[Tuple[str, ...]] = ("default_layout_profile", "perceive", "identify", "compare")

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/__init__.py`
  lines: (whole file, ~19 lines; wiki page content, line numbers not given)
  symbol: `__all__`
  wiki: `file:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/__init__.py`
  excerpt: |
    from .product_on_shelves import ProductOnShelves
    from .graphic_panel_display import GraphicPanelDisplay
    from .product_counter import ProductCounter
    from .endcap_no_shelves_promotional import EndcapNoShelvesPromotional
    from .endcap_backlit_multitier import EndcapBacklitMultitier
    from .ink_wall import InkWall

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py`
  lines: 57-130
  symbol: `GraphicPanelDisplay`
  wiki: `file:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py`
  excerpt: |
    class GraphicPanelDisplay(AbstractPlanogramType):
        """Zone-only graphic panel: presence, text and illumination of configured zones.

        The legacy per-type illumination penalty (1.0) is no longer a code default: migrated rows carry it as
        ``RuleBinding.params["penalty"]`` (emitted by the config converter).
        """

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py`
  lines: 152-262
  symbol: `EndcapBacklitMultitier`
  wiki: `file:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py`
  excerpt: |
    class EndcapBacklitMultitier: Backlit header + product shelves: shared perceive/identify/compare; fact tags never count as products.

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`
  lines: 172-199
  symbol: `PlanogramCompliance.uses_reference_images`
  wiki: `sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance.uses_reference_images` (Q003 score 1.00)
  excerpt: |
    ptype = planogram_type or "product_on_shelves"
    composable_cls = cls._PLANOGRAM_TYPES.get(ptype)
    if composable_cls is None:
        raise ValueError(f"Unknown planogram_type '{ptype}'. Available types: {available}")
    layout = resolve_layout_profile(composable_cls.default_layout_profile(), planogram_config or {}, config_name=ptype)
    return layout.references.enabled

## Notes

- Q006 (`wikitoolkit related file:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py`) returned only `defines` edges to the class's own
  members plus three `references` edges: `file:packages/ai-parrot/src/parrot/pipelines/planogram/types/abstract.py`
  (core proxy), `file:packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py`,
  `file:packages/ai-parrot-pipelines/tests/planogram_cycle/test_type_hooks.py`. No edge to the concrete types; they
  were reached through the `types/__init__.py` page instead.
- The type registry is `PlanogramCompliance._PLANOGRAM_TYPES` (plan.py, seen in `uses_reference_images`); which
  string keys it holds was not read in this lane.
- [cross-lane: type=grep, intent=read plan.py _PLANOGRAM_TYPES to list the registry keys and confirm 'endcap_no_shelves_promotional' / 'graphic_panel_display' spelling]
- [cross-lane: type=read, intent=which planogram_type do rows 23/24 carry today (local DB / artifacts/apply_epson_*backlit.py)]
