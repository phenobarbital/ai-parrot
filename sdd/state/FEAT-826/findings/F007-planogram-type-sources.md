---
id: F007
query_id: Q016
type: grep
intent: "Planogram type registry and how a row selects its type."
executed_at: 2026-11-06T16:05:40Z
duration_ms: 400
parent_id: null
depth: 0
lanes: [codebase]
merged_from: [FC-007]
---
# F007 — The type comes from the row's planogram_type column, never from slots_definition.meta

## Summary

Every reader takes the type from the `planogram_type` **column** of the row (default `product_on_shelves`): the pipeline constructor, the in-repo HTTP handler, `migration_runner` and `check_row`. `slots_definition.meta.planogram_type` (written by the apply scripts and by `convert_config`) is informational. The six registered types are duplicated in two places: `PlanogramCompliance._PLANOGRAM_TYPES` and the `classes` dict inside `migration._layout_problem`.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py`
  lines: 342-342
  symbol: `(handler row hydration)`
  excerpt: |
    planogram_type=row.get("planogram_type", "product_on_shelves"),
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/models.py`
  lines: 44-44
  symbol: `PlanogramConfig.planogram_type`
  excerpt: |
    planogram_type: str = Field(
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration_runner.py`
  lines: 249-253
  symbol: `(convert loop)`
  excerpt: |
    planogram_type = row.get("planogram_type") or _DEFAULT_TYPE
    entry: Dict[str, Any] = {"config_name": name, "planogram_type": planogram_type}
    if planogram_type not in MIGRATED_TYPES:
        entry.update(status="unsupported", problems=[f"unknown planogram_type '{planogram_type}'"])
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py`
  lines: 681-688
  symbol: `_layout_problem`
  excerpt: |
    classes = {
        "product_on_shelves": planogram_types.ProductOnShelves,
        "graphic_panel_display": planogram_types.GraphicPanelDisplay,
        "product_counter": planogram_types.ProductCounter,
        "endcap_no_shelves_promotional": planogram_types.EndcapNoShelvesPromotional,
        "endcap_backlit_multitier": planogram_types.EndcapBacklitMultitier,
        "ink_wall": planogram_types.InkWall,

## Notes

- For both EcoTank rows the exported column value is `endcap_no_shelves_promotional` (F019), so column and meta agree locally. Nothing checks that agreement.
- The FlowTask consumer uses the same precedence: DB column first, task YAML value as fallback (F018).
- [citation moved, §4c dedup] `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` :: `PlanogramCompliance.__init__` lines 122-126 — cited in F005.
