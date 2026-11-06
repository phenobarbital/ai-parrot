---
id: FC-005
query_id: Q014
type: read
intent: "Pipeline entrypoint: stages, result keys, report rendering."
executed_at: 2026-11-06T16:04:30Z
duration_ms: 1800
parent_id: null
depth: 0
---

# FC-005 — PlanogramCompliance refuses rows without slots_definition and validates zone selectors at construction

## Summary

`PlanogramCompliance.__init__` resolves the type handler from `planogram_config.planogram_type` (default `product_on_shelves`), raises `ValueError` when `slots_definition` is `None`, and — for a dict definition — runs `load_slots_definition` + `validate_bindings` + `validate_zone_selectors` immediately. `run()` executes perceive → identify → compare per image and returns the 8 legacy keys plus additive ones. The LLM-detector fallback is skipped when `perception_mode == "llm_detector"`. The ROI prompt still reads the legacy `advertisement_endcap.text_requirements` (or `tags`) to fill its placeholders. The pipeline renders an overlay image only; it produces no markdown report.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`
  lines: 79-86
  symbol: `PlanogramCompliance._PLANOGRAM_TYPES`
  excerpt: |
    _PLANOGRAM_TYPES = {
        "product_on_shelves": ProductOnShelves,
        "graphic_panel_display": GraphicPanelDisplay,
        "product_counter": ProductCounter,
        "endcap_no_shelves_promotional": EndcapNoShelvesPromotional,
        "endcap_backlit_multitier": EndcapBacklitMultitier,
        "ink_wall": InkWall,
    }
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`
  lines: 121-130
  symbol: `PlanogramCompliance.__init__`
  excerpt: |
    ptype = getattr(planogram_config, "planogram_type", None) or "product_on_shelves"
    composable_cls = self._PLANOGRAM_TYPES.get(ptype)
    ...
    if planogram_config.slots_definition is None:
        raise ValueError(
            f"PlanogramConfig {config_name!r} ({ptype}) has no slots_definition; convert it as described in {MIGRATION_RUNBOOK}"
        )
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`
  lines: 201-210
  symbol: `PlanogramCompliance._load_definition`
  excerpt: |
    definition = load_slots_definition(source)
    bindings = validate_bindings(definition, self.planogram_config.planogram_config or {})
    validate_zone_selectors(self._layout, definition, config_name=config_name)
    except (SlotsDefinitionError, ValueError) as exc:
        raise SlotsDefinitionError(f"PlanogramConfig {config_name!r}: {exc}") from exc
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`
  lines: 227-283
  symbol: `PlanogramCompliance.run`
  excerpt: |
    """Run the perceive -> identify -> compare cycle on one image or several photos of one fixture.
    ...
    if self._layout.references.enabled and self.reference_images:
        ctx.reference_bank = await load_reference_bank(self.reference_images, ctx)
    for img_id, source in inputs:
        try:
            img, perception = await self._perceive_one(source, img_id, ctx)
            identification = await self._type_handler.identify(img, perception, ctx)
        except Exception as exc:  # noqa: BLE001 - isolate one failed photo
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`
  lines: 337-348
  symbol: `PlanogramCompliance._roi_prompt`
  excerpt: |
    if not self._layout.roi_detection:
        return None
    config = self.planogram_config.planogram_config or {}
    requirements = (config.get("advertisement_endcap") or {}).get("text_requirements") or []
    tags = config.get("tags") or [item.get("required_text") for item in requirements if isinstance(item, dict)]
    return render_roi_prompt(
        self.planogram_config.roi_detection_prompt,
        brand=str(config.get("brand") or ""),
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`
  lines: 359-367
  symbol: `PlanogramCompliance._fallback_if_needed`
  excerpt: |
    layout = self._layout
    threshold = layout.min_usable_shapes
    if threshold <= 0 or layout.perception_mode == "llm_detector":
        return perception
    if count_usable_targets(perception, layout) >= threshold:
        return perception
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`
  lines: 55-55
  symbol: `MIGRATION_RUNBOOK`
  excerpt: |
    MIGRATION_RUNBOOK = "wiki/flows/pipelines/planogram-cycle-migration.md"

## Notes

- A legacy-format row (as in the ticket's March logs: `shelves[].products`, no `slots_definition`) cannot run on this pipeline at all: construction fails before any image is processed.
- The class docstring still says "Pure-LLM Planogram Compliance Pipeline" (line 67).
- Result assembly is covered in FC-016.
