---
id: FC-012
query_id: Q021
type: read
intent: "Legacy-row migration rules (what is dead, what check_row validates)."
executed_at: 2026-11-06T16:09:20Z
duration_ms: 1400
parent_id: null
depth: 0
---

# FC-012 — check_row validates the definition, bindings and layout resolution; it does not run validate_zone_selectors

## Summary

`check_row` returns `ok=False` for an unknown `planogram_type` or a missing `slots_definition`; otherwise it runs `load_slots_definition`, `validate_bindings` and `_layout_problem` (which only calls `resolve_layout_profile`). It never calls `validate_zone_selectors`, which the pipeline constructor does (FC-013), so a row can pass preflight and still fail at `PlanogramCompliance(...)`. `preflight()` runs `check_row` over every active row (SELECT-only). `_convert_zones_only` is the converter for promotional endcaps: one zone per legacy `shelves[].products[]` entry named `zone-<level>-<n>`, each with a `zone_present` binding.

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
  lines: 676-695
  symbol: `_layout_problem`
  excerpt: |
    try:
        resolve_layout_profile(
            classes[planogram_type].default_layout_profile(), planogram_config, config_name=config_name
        )
    except ValueError as exc:
        return f"invalid layout_profile: {exc}"
    return None
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

## Notes

- Both apply scripts gate their UPDATE on `check_row` only (FC-002 lines 165-168), so they inherit this gap.
- The mechanical converter's zone ids (`zone-header-1`, `zone-middle-1`, `zone-bottom-1`, FC-021) differ from the hand-rewritten ones (`zone-comparison-1`, `zone-base-1`, `zone-backlit-1`).
