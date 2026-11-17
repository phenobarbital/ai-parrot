---
id: F012
query_id: Q021, Q002
type: read
intent: "Legacy-row migration rules (what is dead, what check_row validates)."
executed_at: 2026-11-06T16:09:20Z
duration_ms: 1400
parent_id: null
depth: 0
lanes: [codebase, wiki]
merged_from: [FC-012, FW-002]
---
# F012 — check_row validates the definition, bindings and layout resolution; it does not run validate_zone_selectors

## Summary

**[F012 · codebase]** `check_row` returns `ok=False` for an unknown `planogram_type` or a missing `slots_definition`; otherwise it runs `load_slots_definition`, `validate_bindings` and `_layout_problem` (which only calls `resolve_layout_profile`). It never calls `validate_zone_selectors`, which the pipeline constructor does (F006), so a row can pass preflight and still fail at `PlanogramCompliance(...)`. `preflight()` runs `check_row` over every active row (SELECT-only). `_convert_zones_only` is the converter for promotional endcaps: one zone per legacy `shelves[].products[]` entry named `zone-<level>-<n>`, each with a `zone_present` binding.

**[F012 · wiki]** `migration.py` converts a legacy row into a candidate `slots_definition` + `rule_bindings` and never writes a
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
  excerpt: |
    ptype = row.get("planogram_type") or "product_on_shelves"
    ...
    if ptype not in MIGRATED_TYPES:
        return verdict.model_copy(update={"ok": False, "problems": [f"unknown planogram_type '{ptype}'"]})
    raw = row.get("slots_definition")
    if raw in (None, "", {}):
        problems.append("slots_definition is missing")
    ...
        validate_bindings(definition, pg_config)
    ...
    problem = _layout_problem(ptype, pg_config, verdict.config_name)
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py`
  lines: 408-440
  symbol: `_convert_zones_only`
  excerpt: |
    zone_id = f"zone-{level}-{number}"
    ...
    zones.append({"zone_id": zone_id, "kind": _extended_zone_kind(ptype, name, default_kind),
                  "shelf_id": None, "required": required})
    bindings.add("zone_present", zone_id, {"name": name}, mandatory=required)
    _product_rules(product, zone_id, bindings)
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py`
  lines: 742-758
  symbol: `preflight`
  excerpt: |
    """List active rows and whether each migrated-type row is ready. SELECT-only.
    ...
    rows: Sequence[Any] = await conn.fetch_all(_PREFLIGHT_SQL) or []
    return [check_row(dict(row)) for row in rows]
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py`
  lines: 29-38
  symbol: `MIGRATED_TYPES`
  excerpt: |
    MIGRATED_TYPES = frozenset({"product_on_shelves", "graphic_panel_display", "product_counter",
        "endcap_no_shelves_promotional", "endcap_backlit_multitier", "ink_wall"})
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py`
  lines: 68-68
  symbol: `_PREFLIGHT_SQL`
  excerpt: |
    _PREFLIGHT_SQL = "SELECT * FROM troc.planograms_configurations WHERE is_active = TRUE ORDER BY config_name"
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

*From F012:*
- Both apply scripts gate their UPDATE on `check_row` only (F002 lines 165-168), so they inherit this gap.
- The mechanical converter's zone ids (`zone-header-1`, `zone-middle-1`, `zone-bottom-1`, F019) differ from the hand-rewritten ones (`zone-comparison-1`, `zone-base-1`, `zone-backlit-1`).

*From F012:*
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
- [citation moved, §4c dedup] `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py` :: `_layout_problem` lines 676-695 — cited in F007.
- [citation-check: condensed excerpt] `migration.py` lines 29-38 `MIGRATED_TYPES`: the excerpt reflows the frozenset onto two lines; the six members confirmed by direct read.
