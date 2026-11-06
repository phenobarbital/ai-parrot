---
id: FW-002
query_id: Q002
type: wiki_query
intent: "Orient: legacy-row migration to the perceive/identify/compare cycle (check_row, dead keys)."
executed_at: 2026-11-06T16:11:08Z
duration_ms: 0
parent_id: null
depth: 0
---

# FW-002 — Migration is convert → human review → hand-applied SQL → preflight; the converter only emits illumination from `illumination_required`

## Summary

`migration.py` converts a legacy row into a candidate `slots_definition` + `rule_bindings` and never writes a
database; `check_row` is the pure preflight verdict (type known, `slots_definition` present and loadable,
`validate_bindings`, layout problem). For zone-only types `_convert_zones_only` turns each
`shelves[].products[]` element into an unowned zone with a `zone_present` binding and calls `_product_rules`,
which emits an `illumination` binding **only** when the product carries `illumination_required`; text
requirements and `visual_features` become their own bindings. The runbook states every active row must be
migrated before the new runtime is deployed and that zone-only units enforce their threshold from assessed
mandatory rules.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py`
  lines: 698-739
  symbol: `check_row`
  wiki: `sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#check_row` (found via `wikitoolkit symbols lookup check_row`; Q002 top hit was `sym:packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py#test_check_row_flags_missing_and_invalid_definition`, score 1.00)
  excerpt: |
    raw = row.get("slots_definition")
    if raw in (None, "", {}):
        problems.append("slots_definition is missing")
    ...
        validate_bindings(definition, pg_config)
    ...
        problem = _layout_problem(ptype, pg_config, verdict.config_name)

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py`
  lines: 202-218
  symbol: `_product_rules`
  excerpt: |
    if product.get("illumination_required"):
        bindings.add("illumination", target_id, {"required": ..., "penalty": float(product.get("illumination_penalty", 0.5)), "name": ...})
    requirements = _requirements(product.get("text_requirements"))
    if requirements:
        bindings.add("text_requirements", target_id, {"requirements": requirements})
    if product.get("visual_features"):
        bindings.add("visual_features", target_id, {"expected": list(product["visual_features"])})

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py`
  lines: 408-440
  symbol: `_convert_zones_only`
  excerpt: |
    zone_id = f"zone-{level}-{number}"
    ...
    zones.append({"zone_id": zone_id, "kind": _extended_zone_kind(ptype, name, default_kind), "shelf_id": None, "required": required})
    bindings.add("zone_present", zone_id, {"name": name}, mandatory=required)
    _product_rules(product, zone_id, bindings)

- path: `wiki/flows/pipelines/planogram-cycle-migration.md`
  lines: 9-10, 22-23, 60-68
  symbol: `Deployment sequence`
  wiki: `file:docs/pipelines/planogram-cycle-migration.md` (stale page id — see Notes)
  excerpt: |
    Every active row using one of the six registered types must migrate before the new runtime is
    deployed. A missing `slots_definition` fails construction with a `ValueError` that names this runbook.
    - Zone-only units measure coverage from assessed mandatory rules, and their threshold is enforced
      even with zero facings.
    5. Apply the approved SQL update by hand; the converter never writes a database.
    6. Run `python -m parrot_pipelines.planogram.migration preflight --dsn "$PLANOGRAM_DSN"` until every
       active row is ready, then deploy.

## Notes

- The legacy rows captured in `source.md` (ticket logs) express backlit ON/OFF as free text inside
  `visual_features` (`'Illuminated'`, `'illumination_status: OFF'`) and inside the prompts, not as
  `illumination_required`. Per `_product_rules`, an automatic conversion of those rows would therefore yield a
  keyword `visual_features` binding and **no** `illumination` binding; the backlit distinction has to be authored
  by hand.
- The wiki still indexes the runbook as `file:docs/pipelines/planogram-cycle-migration.md`, but `docs/pipelines/`
  does not exist in the main checkout (`ls docs/pipelines` fails); the file lives at
  `wiki/flows/pipelines/planogram-cycle-migration.md` (118 lines). The runtime error text
  (`types/abstract.py` `validate_contract`, flowtask `_MIGRATION_RUNBOOK`) still names the old `docs/` path.
- Runbook line 95: "Owner/date: to be assigned before deployment."
- Other migration.py symbols (outline): `convert_config` L586-652, `_zone_selectors` L535-583, `_zone_bands`
  L522-532, `_validate_candidate` L655-668, `ConversionReport` L71-78, `PreflightRow` L81-87.
- [cross-lane: type=grep, intent=confirm whether check_row / _layout_problem calls validate_zone_selectors (layout.py L209-242) or only PlanogramCompliance construction does]
