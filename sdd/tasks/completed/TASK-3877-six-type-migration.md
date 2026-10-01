# TASK-3877: Six-type config converter and layout-aware read-only preflight

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3855, TASK-3860, TASK-3864, TASK-3865, TASK-3866, TASK-3867, TASK-3868, TASK-3869
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 13**, §7 "Converter details and rollout" and AC13. `planogram/migration.py` (FEAT-574) converts
only `product_on_shelves` (`convert_config` raises `ValueError` otherwise, line 241-242) and its preflight treats
every type outside `MIGRATED_TYPES = {"product_on_shelves", "ink_wall"}` as ready (line 280-281). After this feature
all six registered types require a `slots_definition` and a valid `layout_profile`, so the migration utility must:

- convert all six types with per-type adapters, keep the original input untouched, derive stable ids, and list every
  human decision in `unresolved` (never invent descriptors, counts, text, selectors, empty expectations or weights);
- validate the candidate definition, bindings **and** layout, appending failures to `unresolved` (not `warnings`,
  which could produce exit 0);
- preflight every active row of the six types (definition + bindings + layout), and report unknown types as not ready;
- keep the CLI, exit codes (0 ready / 2 unresolved or failing / 1 usage or I/O), `--out` overwrite protection and the
  single SELECT-only query. No DB writes, no images, no LLM.

---

## Scope

- Set `MIGRATED_TYPES` to exactly the six registered keys.
- Add `layout_profile: Dict[str, Any]` to `ConversionReport`.
- Make `convert_config` dispatch by type: `product_on_shelves` (existing walk, unchanged output), `ink_wall`
  (page-1 layout), `endcap_backlit_multitier` (products + header/section zones), `endcap_no_shelves_promotional`
  and `graphic_panel_display` (zones only), `product_counter` (product elements → facings; background/information
  label → zones). Unsupported type ⇒ `ValueError`.
- Preserve source descriptors when the source provides them (`product["descriptors"]` dict); never create them.
- Move a legacy top-level `perception_mode` into `report.layout_profile` (spec §2 alias policy) and warn that
  legacy prompts / detector fields / `detection_grid` are accepted and ignored.
- Validate candidate + bindings + layout; failures go to `unresolved`.
- Extend `check_row`: unknown type ⇒ `ok=False`; six types ⇒ definition, bindings and layout validated.
- Rewrite/extend `test_config_migration.py` (see test table).

**NOT in scope**:
- DB writes / SQL generation / automatic application (spec §1 Non-Goals) — do not add any.
- `LayoutProfile`/`resolve_layout_profile` (TASK-3855), definition schema (TASK-3860), type defaults (TASK-3864..3869).
- Runbook text (`docs/pipelines/planogram-cycle-migration.md`) — TASK-3880.
- Live harness use of `check_row` — TASK-3878.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py` | MODIFY | Six per-type adapters, layout in report, layout-aware preflight |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py` | MODIFY | Six-type conversion, unresolved lists, preflight readiness, SELECT-only |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# already in migration.py (lines 9-24)
import argparse, asyncio, copy, json, logging, sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from pydantic import BaseModel, Field
from parrot_pipelines.planogram.comparison.definition import (
    SlotsDefinitionError, load_slots_definition, validate_bindings,
)                                                                  # definition.py:29, 218, 285
# lazy, inside functions only (keep `import migration` free of CV/type imports):
from parrot_pipelines.planogram.types import (                     # types/__init__.py:3-9
    EndcapBacklitMultitier, EndcapNoShelvesPromotional, GraphicPanelDisplay, InkWall, ProductCounter, ProductOnShelves,
)
# test-only
from parrot_pipelines.planogram.plan import PlanogramCompliance    # plan.py:48 (_PLANOGRAM_TYPES at :61-68)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py (376 lines)
MIGRATED_TYPES = frozenset({"product_on_shelves", "ink_wall"})                                   # line 28
_NON_FACING_TYPES = frozenset({"fact_tag", "price_tag", "slot"})                                 # line 29
_ZONE_TYPES = frozenset({"promotional_graphic", "graphic", "banner", ... "text_overlay"})         # lines 30-45
_PREFLIGHT_SQL = "SELECT * FROM troc.planograms_configurations WHERE is_active = TRUE ORDER BY config_name"  # line 46
class ConversionReport(BaseModel): candidate, bindings, unresolved, warnings                     # lines 49-55
class PreflightRow(BaseModel): config_name, planogram_type, ok, problems                         # lines 58-64
def _fixed_quantity(product) -> Optional[int]                                                    # line 67
def _zone_kind(product_type: str, name: str) -> str   # backlit | box_stack | poster | header     # lines 81-90
class _BindingSet: items; add(kind, target_id, params, mandatory=True)  # rule_id = f"{kind}:{target_id}"  # line 93
def _requirements(raw) -> List[Dict[str, Any]]                                                   # line 122
def _product_rules(product, target_id, bindings) -> None   # illumination/text/visual bindings    # line 133
def _walk_shelves(config, report, bindings) -> Tuple[list, list]  # shelf-{i}, "{shelf_id}:{slot}", zone-{level}-{n}  # line 152
def _endcap_rules(config, shelves, zones, bindings) -> None                                      # line 212
def convert_config(planogram_config: Dict[str, Any], *, planogram_type: str) -> ConversionReport  # line 229
    # 241-242: raise ValueError unless product_on_shelves; 249-254 candidate; 256-260 validation → warnings
def _decode(value) -> Any                                                                        # line 264
def check_row(row: Dict[str, Any]) -> PreflightRow                                               # line 269 (280-281: non-migrated ⇒ ok; docstring :276 "legacy types are always ``ok``")
async def preflight(dsn: str) -> List[PreflightRow]   # lazy `from asyncdb import AsyncDB`; conn.fetch_all(_PREFLIGHT_SQL)  # line 308
def _load_config_file(path) -> Tuple[Dict[str, Any], Optional[str]]                              # line 325
def _main(argv=None) -> int   # convert: --out == input ⇒ 1; ValueError/OSError/JSON ⇒ 1; unresolved ⇒ 2; preflight: any not ok ⇒ 2  # line 333

# comparison/definition.py
def _normalise_page1(data) -> Dict[str, Any]   # page-1 layout → native; facing ids p{position:03d}_f{n}    # line 111 (private)
def load_slots_definition(source) -> SlotsDefinition   # accepts native OR page-1 layout (detects "planogram" key
                                                       #   or shelves[0]["products"] being a dict)            # line 218
def _validate(definition) -> None   # today: "zero described positions" (line 215) — TASK-3860 may relax/reword it
# Synthetic page-1 example in a committed test: tests/planogram_cycle/test_ink_wall_example.py:47-68 (`_page1()`)

# Legacy shapes the other types read (verified):
# product_counter.py:367-371  planogram_config["scoring_weights"] keys product / promotional_background / information_label
# endcap_no_shelves_promotional.py:322-344  planogram_config["shelves"] levels (default backlit_panel, lower_poster), products[].product_type
# graphic_panel_display.py:234-236  description.shelves[].level / .products[] (each product is one graphic zone)
# parrot/models/detections.py:282-316  ShelfSection(id, region, products); ShelfConfig.sections (backlit multitier)
```

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3855 — planogram/layout.py
class LayoutProfile(BaseModel): ...  # extra="forbid"; perception_mode, zone_selectors, ... (spec §3 M1)
def resolve_layout_profile(defaults: LayoutProfile, config: dict[str, Any], *, config_name: str) -> LayoutProfile:
    """Merge a copy and validate; raise ValueError naming config and invalid field."""
#   — read TASK-3855's Completion Note for whether `config` is the whole planogram_config (with "layout_profile" and
#     the top-level "perception_mode" alias) or the layout sub-dict; pass exactly what it documents.
# TASK-3864..3869 — each type: @classmethod default_layout_profile(cls) -> LayoutProfile
# TASK-3860 — ZoneKind adds "graphic", "advertisement", "counter", "information_label"; FacingDefinition.product optional
#   only when expected_occupancy == "empty"; zone-only definitions (no facings, virtual `zone:<zone_id>` units) valid;
#   empty definition rejected; required zones need a mandatory zone_present binding (validate_bindings).
```

### Does NOT Exist
- ~~A DB-writing path in migration~~ — `preflight` only SELECTs; do not add INSERT/UPDATE/ALTER.
- ~~`convert_config` for types other than `product_on_shelves`~~ — added by this task.
- ~~`"tv_wall"` planogram type~~ — not registered (`plan.py:61-68`); converting it must raise `ValueError`.
- ~~Descriptor inference~~ — never fill `descriptors`/`display_name` from product names.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#ConversionReport",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#PreflightRow",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#convert_config",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#check_row",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#preflight",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#_main",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#_walk_shelves",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#_endcap_rules",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#_zone_kind",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#_BindingSet",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#load_slots_definition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#validate_bindings"
  ]
}
```

---

## Implementation Notes

### Planner cross-task notes (added at /sdd-task time)
- `resolve_layout_profile(defaults, config, *, config_name)` takes `config` = the WHOLE `planogram_config` dict (it reads `config.get("layout_profile", {})` itself and the top-level `perception_mode` alias) — because the spec's alias rule needs both keys and callers (TASK-3871 plan.py, TASK-3877 migration.py) must not pre-slice.
- Emit a `zone_selectors` entry (zone_id + detected kind/profile + ordinal from source order) for EVERY configured zone — because TASK-3863's zone matching is selector-driven and a multi-zone definition without selectors is treated as ambiguous/unassessed.
- GraphicPanelDisplay's legacy default illumination penalty (1.0) is no longer a type default (TASK-3868); emit it explicitly as `RuleBinding.params` for that type's illumination bindings.
- ProductCounter's legacy `planogram_config["scoring_weights"]` is accepted-but-ignored at runtime (TASK-3869); convert it to per-shelf `ShelfConfig` product/text/visual weights in the candidate.


### Pattern to Follow
Keep the existing module shape: pure helpers that append to `report.unresolved` / `report.warnings` and a
`_BindingSet`. Each per-type adapter has signature `(config, report, bindings) -> Tuple[shelves, zones]` so the
dispatcher builds `report.candidate` identically for every type.

### Key Constraints
- `product_on_shelves` output must stay byte-for-byte what it is today for the existing fixture (ids, zone kinds,
  bindings) — existing assertions in `test_config_migration.py` pin it. New zone kinds apply only to other types.
- Stable ids from source order/keys: shelves `shelf-{i}`, facings `{shelf_id}:{slot}`, zones `zone-{level}-{n}`
  (existing scheme, lines 158-190); page-1 ink ids come from `load_slots_definition`'s normalisation (`p{pos:03d}_f{n}`).
  No `uuid`, no randomness — two conversions of the same input are equal.
- Every required zone gets a mandatory `zone_present` binding; an optional (`mandatory: false`) zone becomes
  `required: false` with a non-mandatory binding (spec M8: optional zones stay optional).
- Repeated same-kind zones on one type ⇒ `unresolved` "zone selector required for <zone ids>" (spec §2: selectors are
  required for repeated same-kind zones; the converter never invents geometry). Backlit `sections` ⇒ `unresolved`
  "section <id>: configure a spatial group/zone selector" unless the source provides explicit geometry.
- `quantity_range` not fixed, missing counts, descriptor values, required text, empty expectations and
  `scoring_weights` ⇒ `unresolved` (spec §7 "remain explicit human decisions").
- `check_row` must not open images, call an LLM, or write; import the type classes lazily.
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.

### Existing tests: retained vs rewritten (`test_config_migration.py`, 195 lines)
| Test (line) | Verdict |
|---|---|
| `test_convert_does_not_mutate_input` (:63) | RETAIN + parametrize over six type fixtures |
| `test_fixed_quantity_seeds_facings_and_range_is_unresolved` (:69) | REWRITE the count assertion: `any("RR-60" in u …)` (validation failures now also land in `unresolved`) |
| `test_promotional_product_becomes_zone_with_zone_present_binding` (:82) | RETAIN (POS output unchanged) |
| `test_nested_illumination_and_text_become_bindings` (:93) | RETAIN |
| `test_thresholds_and_weights_stay_in_planogram_config` (:106) | RETAIN |
| `test_fact_tags_are_not_facings` (:113) | RETAIN |
| `test_candidate_validates_once_described` (:119) | REWRITE: validation failure is in `unresolved`, not `warnings`; message-agnostic |
| `test_non_pos_type_rejected` (:130) | REWRITE → `test_unknown_type_rejected` (`"tv_wall"`) |
| `test_check_row_legacy_type_is_ok` (:135) | REWRITE → `product_counter` row without definition is NOT ok; unknown type NOT ok |
| `test_check_row_flags_missing_and_invalid_definition` (:139) | RETAIN |
| `test_preflight_sql_is_select_only` (:170) | RETAIN |
| `test_cli_convert_exit_code_two_when_unresolved` (:175), `test_cli_convert_refuses_to_overwrite_input` (:185) | RETAIN |
| `test_cli_convert_exit_zero_when_fully_resolved` (:191) | REWRITE: source products carry `descriptors` (preserved, not invented) so the candidate validates ⇒ exit 0 |

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Replace `MIGRATED_TYPES`, add `_COUNTER_ZONE_TYPES` and the extended zone-kind helper (block 1) — *why*: the six-type registry is the readiness scope; new kinds must not alter POS output.
2. Add `layout_profile` to `ConversionReport` (block 2) — *why*: Module 13 skeleton field.
3. Replace `convert_config` with dispatcher + adapters + `_validate_candidate` (blocks 3-4) — *why*: per-type adapters and unresolved-not-warnings (spec §7).
4. Extend `check_row` (block 5) and preserve source descriptors (block 6) — *why*: unknown types not ready; layout validated; descriptors never dropped or invented.
5. Rewrite/extend tests; run Validation Commands.

### `migration.py` (MODIFY) — block 1: registry and zone kinds
```python
# occurrences: 1 (verified: grep -Fxc 'MIGRATED_TYPES = frozenset({"product_on_shelves", "ink_wall"})' migration.py → line 28)
# REPLACE line 28 with:
MIGRATED_TYPES = frozenset(
    {
        "product_on_shelves",
        "graphic_panel_display",
        "product_counter",
        "endcap_no_shelves_promotional",
        "endcap_backlit_multitier",
        "ink_wall",
    }
)
# AFTER — insert below the closing `)` of `_ZONE_TYPES` (verified: migration.py:45, before `_PREFLIGHT_SQL` at :46):
_COUNTER_ZONE_TYPES = frozenset({"promotional_background", "background", "information_label", "label"})


def _extended_zone_kind(product_type: str, name: str, default: str) -> str:
    """Zone kind for non-shelf types, using the FEAT-612 kinds; POS keeps ``_zone_kind`` unchanged."""
    text = f"{product_type} {name}".casefold()
    # FILL IN: "information" or "label" ⇒ "information_label"; "backlit" ⇒ "backlit"; "counter" ⇒ "counter";
    #   "advertis" ⇒ "advertisement"; "poster"/"banner"/"text_overlay" ⇒ "poster"; "box" ⇒ "box_stack";
    #   otherwise `default` — bounded by TASK-3860's ZoneKind literal (reject nothing here; validation does)
    raise NotImplementedError
```
**Why**: `MIGRATED_TYPES` must equal the registry (a test asserts it); a separate helper keeps the existing POS
candidate byte-identical while zone-only types get the four new kinds.

### `migration.py` (MODIFY) — block 2: report field
```python
# occurrences: 1 (verified: grep -Fxc '    """Result of a candidate conversion. ``candidate`` is a proposal for human review."""' → line 50)
# AFTER — insert below `    warnings: List[str] = Field(default_factory=list)` inside ConversionReport (verified: migration.py:55)
    layout_profile: Dict[str, Any] = Field(default_factory=dict)
```

### `migration.py` (MODIFY) — block 3: per-type adapters (insert above `def convert_config(`, line 229)
```python
# occurrences: 1 (verified: grep -Fxc 'def convert_config(planogram_config: Dict[str, Any], *, planogram_type: str) -> ConversionReport:' migration.py)
# BEFORE — insert above that line (verified: migration.py:229), below `_endcap_rules` (ends :226)
def _convert_ink(config: Dict[str, Any], report: ConversionReport, bindings: _BindingSet) -> Tuple[list, list]:
    """Page-1 / slots layout → native shelves (ids from the page-1 normalisation); descriptors are never invented."""
    # FILL IN: source = config.get("slots_definition") or config (page-1 doc: "planogram" key or shelves[0]["products"]
    #   is a dict); if not page-1 ⇒ unresolved "ink_wall: no page-1/slots layout found" and return [], [];
    #   definition = load_slots_definition(copy.deepcopy(source)) → SlotsDefinitionError ⇒ unresolved; else
    #   shelves = [s.model_dump(mode="json") for s in definition.shelves]; facings without descriptors ⇒ unresolved
    raise NotImplementedError


def _convert_zones_only(
    config: Dict[str, Any], report: ConversionReport, bindings: _BindingSet, *, default_kind: str
) -> Tuple[list, list]:
    """Promotional / graphic-panel: every configured element is a zone (no facings, no invented tiers)."""
    # FILL IN: for index, shelf in enumerate(config.get("shelves") or [], start=1): for each product ⇒ zone
    #   {"zone_id": f"zone-{level}-{n}", "kind": _extended_zone_kind(ptype, name, default_kind), "shelf_id": None,
    #    "required": bool(product.get("mandatory", True))}; bindings.add("zone_present", zone_id, {"name": name},
    #    mandatory=required); _product_rules(product, zone_id, bindings); repeated same kind ⇒ unresolved selector item.
    #   Return ([], zones) — unowned zones become virtual `zone:<zone_id>` units in load_slots_definition (TASK-3860)
    raise NotImplementedError


def _convert_counter(config: Dict[str, Any], report: ConversionReport, bindings: _BindingSet) -> Tuple[list, list]:
    """Product elements → facings on one counter shelf; background/information label → zones."""
    # FILL IN: facings for product elements (fixed quantity via _fixed_quantity, else unresolved), zones for
    #   _COUNTER_ZONE_TYPES via _extended_zone_kind(..., "graphic"); "scoring_weights" present ⇒ unresolved
    #   "scoring_weights: map to definition/profile weights"; never a fixed three-element list
    raise NotImplementedError


def _convert_backlit(config: Dict[str, Any], report: ConversionReport, bindings: _BindingSet) -> Tuple[list, list]:
    """Products via the shelves walk; header/backlit zones; sections need a human-configured spatial group."""
    # FILL IN: shelves, zones = _walk_shelves(config, report, bindings); _endcap_rules(config, shelves, zones, bindings);
    #   for each source shelf with "sections": unresolved f"{shelf_id} section {section['id']}: configure a zone
    #   selector / section group" (no geometry invented); fact tags never become facings (already skipped)
    raise NotImplementedError
```
**Why**: one adapter per legacy shape (spec §7 list); all adapters share `_BindingSet`/`_product_rules`, so rule
bindings are produced the same way for every type.

### `migration.py` (MODIFY) — block 4: dispatcher and validation (REPLACE `convert_config`, lines 229-261)
```python
# occurrences: 1 (same grep as block 3)
# REPLACE lines 229-261 (the whole current convert_config, ending `    return report`) with:
def convert_config(planogram_config: Dict[str, Any], *, planogram_type: str) -> ConversionReport:
    """Convert any of the six registered types; ValueError for unsupported types; never mutate input.

    Args:
        planogram_config: The raw ``planogram_config`` dict (never mutated).
        planogram_type: The configuration's planogram type.

    Returns:
        A ConversionReport; ``unresolved`` lists every human decision and every validation failure.

    Raises:
        ValueError: When ``planogram_type`` is not one of ``MIGRATED_TYPES``.
    """
    if planogram_type not in MIGRATED_TYPES:
        raise ValueError(f"Unsupported planogram_type '{planogram_type}'; convertible: {', '.join(sorted(MIGRATED_TYPES))}")
    config = copy.deepcopy(planogram_config)
    report = ConversionReport()
    bindings = _BindingSet()
    if planogram_type == "product_on_shelves":
        shelves, zones = _walk_shelves(config, report, bindings)
        _endcap_rules(config, shelves, zones, bindings)
    elif planogram_type == "ink_wall":
        shelves, zones = _convert_ink(config, report, bindings)
    elif planogram_type == "endcap_backlit_multitier":
        shelves, zones = _convert_backlit(config, report, bindings)
    elif planogram_type == "product_counter":
        shelves, zones = _convert_counter(config, report, bindings)
    else:  # endcap_no_shelves_promotional | graphic_panel_display
        shelves, zones = _convert_zones_only(config, report, bindings, default_kind="graphic")
    # FILL IN: layout — if "perception_mode" in config: report.layout_profile["perception_mode"] = config["perception_mode"]
    #   and warn; copy an existing config["layout_profile"] dict unchanged; warn once for each present legacy field
    #   (roi_detection_prompt, object_identification_prompt, detection_model, confidence_threshold, detection_grid)
    #   "accepted and ignored for one release"
    report.candidate = {
        "version": "1",
        "meta": {"source": "convert_config", "planogram_type": planogram_type,
                 "brand": config.get("brand"), "category": config.get("category")},
        "shelves": shelves,
        "zones": zones,
    }
    report.bindings = list(bindings.items.values())
    _validate_candidate(report, config, planogram_type)
    return report


def _validate_candidate(report: ConversionReport, config: Dict[str, Any], planogram_type: str) -> None:
    """Definition, bindings and layout validation; every failure is appended to ``unresolved``."""
    # FILL IN: load_slots_definition(copy.deepcopy(report.candidate)) + validate_bindings(defn, {**config,
    #   "rule_bindings": report.bindings}) — SlotsDefinitionError ⇒ report.unresolved.append(f"candidate does not
    #   validate: {exc}"); layout: _layout_problem(planogram_type, {**config, "layout_profile": report.layout_profile},
    #   "convert_config") → append when not None
    raise NotImplementedError
```
**Why**: dispatch keeps the existing POS path first and untouched; moving validation failures to `unresolved`
makes the CLI exit 2 for any candidate that is not ready (spec §7), and the meta `planogram_type` records provenance.
Note: the meta for POS changes by one key (`planogram_type`); if an existing assertion compares `meta`, update it.

### `migration.py` (MODIFY) — block 5: layout helper + `check_row`
```python
# occurrences: 1 (verified: grep -Fxc 'def _decode(value: Any) -> Any:' migration.py)
# AFTER — insert below the `_decode` function body (verified: migration.py:264-266), above `def check_row(`:
def _layout_problem(planogram_type: str, planogram_config: Dict[str, Any], config_name: str) -> Optional[str]:
    """Resolve the type's default layout with the row's overrides; return the error text or None."""
    from parrot_pipelines.planogram.layout import resolve_layout_profile  # lazy (TASK-3855)
    from parrot_pipelines.planogram import types as planogram_types     # lazy: CV imports only when checking

    classes = {
        "product_on_shelves": planogram_types.ProductOnShelves,
        "graphic_panel_display": planogram_types.GraphicPanelDisplay,
        "product_counter": planogram_types.ProductCounter,
        "endcap_no_shelves_promotional": planogram_types.EndcapNoShelvesPromotional,
        "endcap_backlit_multitier": planogram_types.EndcapBacklitMultitier,
        "ink_wall": planogram_types.InkWall,
    }
    # FILL IN: try resolve_layout_profile(classes[planogram_type].default_layout_profile(), <config per TASK-3855>,
    #   config_name=config_name); except ValueError as exc: return f"invalid layout_profile: {exc}"; return None

# In check_row (verified: migration.py:269) REPLACE lines 280-281 (grep -Fxc '    if ptype not in MIGRATED_TYPES:' → 1):
#     if ptype not in MIGRATED_TYPES:
#         return verdict
# with:
    if ptype not in MIGRATED_TYPES:
        return verdict.model_copy(update={"ok": False, "problems": [f"unknown planogram_type '{ptype}'"]})
# and, after the bindings try/except (ends line 304, inside the `else:` branch), append the layout check:
#   problem = _layout_problem(ptype, pg_config, verdict.config_name); if problem: problems.append(problem)
#   — FILL IN: only when pg_config decoded successfully (reuse the decoded dict; do not decode twice)
# Also update the check_row docstring (line 276) and preflight docstring (line 315): replace "legacy types are always
# ``ok``" with "unknown types are never ``ok``".
```
**Why**: spec M13 "unknown types are not silently ready" and "validate layout as well as definition and bindings";
the lazy imports keep `preflight`'s module import free of CV/type dependencies.

### `migration.py` (MODIFY) — block 6: preserve provided descriptors in `_walk_shelves`
```python
# occurrences: 1 (verified: grep -Fxc '                        "descriptors": {},' migration.py → line 199)
# REPLACE line 199 with:
                        "descriptors": copy.deepcopy(product.get("descriptors") or {}),
```
**Why**: spec §7 "Preserve provided descriptors; do not claim a generated candidate is ready" — a source without
descriptors still yields `{}` (existing POS assertions unchanged), a source with them keeps them verbatim.

### FILL IN checklist
- [ ] `_extended_zone_kind` — mapping order above; bounded by TASK-3860 ZoneKind
- [ ] `_convert_ink`, `_convert_zones_only`, `_convert_counter`, `_convert_backlit` — no invented values; bounded by AC13
- [ ] layout/legacy-field warnings in `convert_config`; `_validate_candidate`; `_layout_problem`; `check_row` layout step; block 6 descriptor preservation
- [ ] Tests per table below

---

## Acceptance Criteria

- [ ] `MIGRATED_TYPES == set(PlanogramCompliance._PLANOGRAM_TYPES)` — AC13.
- [ ] Each of the six types converts to a reviewable candidate with stable ids and an `unresolved` list; unknown type ⇒ `ValueError` — AC13.
- [ ] Zone-only candidates (promotional, panel) have zones and no facings; required zones carry mandatory `zone_present` — AC9/AC13.
- [ ] Unresolved covers non-fixed quantities, missing descriptors, backlit sections, repeated same-kind zones, `scoring_weights` — spec §7.
- [ ] Candidate/binding/layout validation failures are in `unresolved` (CLI exit 2), never only in `warnings`.
- [ ] Input dicts never mutated; `--out` equal to input ⇒ exit 1 — AC13.
- [ ] `check_row`: unknown type not ok; six types validate definition, bindings and layout; preflight stays one SELECT — AC13.
- [ ] Validation Commands pass; `ruff check` and `black --check` clean — AC16.
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py`

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_slots_definition.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py — additions (existing tests per table)
from parrot_pipelines.planogram.migration import MIGRATED_TYPES, preflight  # plus existing imports

# fixtures (generic labels only): pos_config (existing legacy_config), ink_page1 (shape of test_ink_wall_example.py:47),
# backlit_config (header backlit promo + one product shelf with "sections"), promo_config (backlit_panel + lower_poster,
# one optional zone), panel_config (two shelves of graphics, two with the same kind), counter_config (one product +
# promotional_background + information_label + scoring_weights)

def test_migrated_types_match_registry(): ...          # MIGRATED_TYPES == set(PlanogramCompliance._PLANOGRAM_TYPES)
@pytest.mark.parametrize("ptype,fixture", SIX)
def test_every_type_converts_without_mutation(ptype, fixture, request): ...  # candidate has shelves/zones; input == deepcopy
def test_conversion_is_deterministic(): ...            # convert twice ⇒ identical model_dump()
def test_unknown_type_rejected(): ...                  # ValueError for "tv_wall"
def test_zone_only_candidate_has_zones_and_mandatory_presence(): ...  # promo: facings == []; required ⇒ mandatory binding
def test_optional_zone_stays_optional(): ...           # required False, binding mandatory False
def test_repeated_same_kind_zones_need_selector(): ... # panel: unresolved mentions "selector"
def test_backlit_sections_are_unresolved(): ...        # unresolved mentions the section id
def test_counter_products_become_facings_and_labels_zones(): ...  # facing product == "P-100"; zone kind "information_label"
def test_counter_scoring_weights_are_unresolved(): ... # unresolved mentions "scoring_weights"
def test_ink_page1_never_invents_descriptors(): ...    # facings keep page-1 ids; missing descriptors ⇒ unresolved
def test_top_level_perception_mode_moves_to_layout_profile(): ...  # report.layout_profile == {"perception_mode": "cv"}
def test_validation_failures_are_unresolved_not_warnings(): ...    # undescribed candidate ⇒ item in unresolved
def test_check_row_unknown_type_not_ready(): ...       # ok False, problem names the type
def test_check_row_counter_without_definition_not_ready(): ...  # ok False, "missing"
def test_check_row_invalid_layout_not_ready(): ...     # {"layout_profile": {"no_such_key": 1}} ⇒ problem "invalid layout_profile"
async def test_preflight_issues_single_select(monkeypatch): ...  # fake `asyncdb` module in sys.modules records SQL;
                                                                 #   exactly one call, == _PREFLIGHT_SQL, no write verbs
def test_cli_convert_exit_zero_when_fully_resolved(tmp_path): ...  # source descriptors preserved ⇒ exit 0
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug refactor-planogram-compliance --feature-id FEAT-612`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/refactor-planogram-compliance.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/refactor-planogram-compliance.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3877 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Merged cleanly via sdd-worker orchestration; lint clean. TASK-3870 note: tests/planogram_cycle/test_ink_wall.py:171 reads InkWall._LEGACY_CONTRACT which TASK-3870 deleted (no task owns that file; needs follow-up). test_endcap_no_shelves_promotional.py 2 failures pre-exist.

