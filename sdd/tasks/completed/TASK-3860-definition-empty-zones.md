# TASK-3860: Slots definition: expected-empty facings, custom attributes, zone kinds, zone-only units

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 **"Stage 3: identity, expected emptiness, zones and scores"**, §3 **Module 4** (definition
part of the skeleton) and §7 notes on descriptors / `definition_coverage` / mandatory bindings. The
slots definition (`comparison/definition.py`) is the only source of expected shelf/position/zone
counts. Today it cannot express (a) a position that is *meant* to be empty, (b) custom descriptor
attributes beyond the ink-specific typed fields, (c) the zone kinds needed by promotional, graphic
panel and counter fixtures, or (d) a fixture made only of zones — `_validate` rejects
"zero described positions" (`definition.py:214-215`, spec §6 corrections) and unowned zones never
reach a score unit. This task extends the schema, the loader, `definition_coverage` and
`validate_bindings`; scoring the new cases is TASK-3862 and identity resolution is TASK-3861.

---

## Scope

- Add `Descriptors.attributes: Dict[str, str | int | float | bool | List[str]]` (default `{}`) and
  reject an attribute key that collides with a typed descriptor field name.
- Add `FacingDefinition.expected_occupancy: Literal["occupied", "empty"] = "occupied"`; make
  `FacingDefinition.product: Optional[str] = None`; an **occupied** facing still requires a nonblank product.
- Add zone kinds `graphic`, `advertisement`, `counter`, `information_label` to `ZoneKind`
  (keep the four existing kinds).
- Let `SlotsDefinition.shelves` default to `[]` so a zone-only definition needs no physical shelf.
- In `load_slots_definition`: normalize every zone with `shelf_id=None` into a deterministic virtual
  score shelf `zone:<zone_id>` (appended after the physical shelves, zone order), reject a collision
  with an existing physical shelf id, preserve explicit ownership, and stay idempotent when a
  normalized definition is dumped and loaded again.
- In `_validate`: reject a completely empty definition (no facings and no zones); require ≥ 1
  described position only when occupied facings exist (all-expected-empty and zone-only definitions
  are legal); skip expected-empty facings in the conflicting-descriptor check.
- In `definition_coverage`: expected-empty facings count as sufficiently defined.
- In `validate_bindings`: every `required` zone needs a **mandatory** `zone_present` binding
  targeting it; every facing-less shelf (physical or virtual) needs at least one **mandatory**
  binding targeting the shelf or one of its zones.
- Add `"attributes"` to `_DESCRIPTOR_KEYS` so a page1 position carrying custom attributes keeps them.
- Update `tests/planogram_cycle/test_slots_definition.py` for the changed rules and add tests for every new rule.

**NOT in scope**: `FacingStatus.EXPECTED_EMPTY/UNEXPECTED_OCCUPIED` (TASK-3854); scoring, occupancy
counts and projection of expected-empty positions and virtual zone units (TASK-3862); descriptor
identity resolution and verify gating (TASK-3861); the converter emitting these fields (TASK-3877);
`LayoutProfile` descriptor vocabulary (TASK-3855). Do not edit `registration.py`, `scoring.py`,
`projection.py`, `verify.py`, `migration.py` or any type module.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` | MODIFY | Schema additions, virtual zone shelves, relaxed/new validation, binding completeness |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_slots_definition.py` | MODIFY | Update changed expectations; tests for every new rule |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# definition.py already imports (keep; extend where the blueprint says):
from typing import Any, Dict, List, Literal, Optional, Tuple, Union      # definition.py:8
from pydantic import BaseModel, Field, ValidationError                   # definition.py:10 (+ model_validator)
# test file imports from the package facade (test_slots_definition.py:8-16):
from parrot_pipelines.planogram.comparison import (RuleBinding, SlotsDefinitionError, definition_coverage,
    load_slots_definition, validate_bindings)                            # comparison/__init__.py:3-14
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py
ZoneKind = Literal["header", "backlit", "poster", "box_stack"]                               # :15
_DESCRIPTOR_KEYS: Tuple[str, ...] = ("display_name", ..., "price")                          # :17-26
class SlotsDefinitionError(ValueError)                                                       # :29
class Descriptors(BaseModel): display_name, family, xl, colors, pack, identifiers, aliases, price (:43)
    @property described -> bool (display_name non-blank)                                     # :45-48
    @property sufficient -> bool (described or a non-blank identifier)                       # :50-53
class FacingDefinition(BaseModel): facing_id, shelf_id, slot (ge=1), product: str (:62), brand, facings,
                                   facing_index, position, descriptors (:67)                 # :56-67
class ShelfDefinition(BaseModel): shelf_id: str; shelf_number: int; level: Optional[str]; facings   # :70-76
class ZoneDefinition(BaseModel): zone_id: str; kind: ZoneKind; shelf_id: Optional[str] = None; required: bool = True  # :79-85
class RuleBinding(BaseModel): rule_id, kind: RuleKind, target_id, params, mandatory: bool = True     # :88-95
class SlotsDefinition(BaseModel): version="1"; meta; shelves: List[ShelfDefinition] (:103); zones   # :98-108
    def all_facings(self) -> List[FacingDefinition]                                          # :106
def _normalise_page1(data) -> Dict[str, Any]          # :111-159 (requires slot/position/product per position)
def _duplicates(ids: List[str]) -> List[str]          # :162
def _validate(definition: SlotsDefinition) -> None    # :173-215
    # duplicate ids :182-189; slots 1..n :191-194; "neither facings nor zones" :196-199;
    # conflicting descriptors keyed by facing.product :201-212; "zero described positions" :214-215
def load_slots_definition(source: Union[Dict[str, Any], str, Path]) -> SlotsDefinition       # :218-264
    # model_validate :249-252; sort shelves/facings :254-256; _validate(definition) :257
def definition_coverage(definition: SlotsDefinition) -> Tuple[float, List[str]]             # :267-282 (1.0 when no facings)
def validate_bindings(definition: SlotsDefinition, planogram_config: Dict[str, Any]) -> List[RuleBinding]  # :285-337
    # namespaces facing/zone/shelf :316-328; zone-only shelf check :330-336 ("zone-only shelf has no bound rule")
```

Callers that must keep working (do not edit them): `plan.py:222-223` (`load_slots_definition` via
`asyncio.to_thread`, then `validate_bindings`), `migration.py:257-258, 294-300`.
Converter output already emits a `zone_present` binding per zone (`migration.py:171-174`), but with
`mandatory=bool(product.get("mandatory", True))` — a converted optional product can therefore yield a
required zone with a NON-mandatory binding; that config now fails validation until TASK-3877 aligns
the converter. Accept this; do not edit `migration.py`.

### Does NOT Exist
- ~~`FacingDefinition.expected_occupancy`~~, ~~`Descriptors.attributes`~~ — this task adds them.
- ~~ZoneKind `graphic` / `advertisement` / `counter` / `information_label`~~ — this task adds them.
- ~~A new `RuleKind`~~ — keep exactly the four rule kinds (spec §2: "no new speculative counting rule").
- ~~A per-kind `params` schema for `RuleBinding`~~ — the spec defines none; do not invent one.
- ~~Virtual shelves in the page1 layout~~ — `_normalise_page1` always returns `"zones": []`; normalization applies after `model_validate`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_slots_definition.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#Descriptors",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#FacingDefinition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#ShelfDefinition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#ZoneDefinition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#RuleBinding",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#SlotsDefinition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#SlotsDefinitionError",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#_validate",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#load_slots_definition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#definition_coverage",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#validate_bindings"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Keep the module's style: cross-object rules live in `_validate` and raise `SlotsDefinitionError`
  naming the offending id; field-level rules are Pydantic validators (wrapped into
  `SlotsDefinitionError` by `load_slots_definition:249-252`).
- Existing definitions keep their behavior (spec §2): every new field defaults to the old meaning
  (`expected_occupancy="occupied"`, `attributes={}`), existing kinds and error messages stay
  (tests match on `"duplicate facing_id"`, `"1..n"`, `"conflicting descriptors"`,
  `"neither facings nor zones"`, `"zone-only shelf"`, `"zero described"`).

### Key Constraints
- **Expected-empty facings** (spec §2 Stage 3, §7): `product` may be `None`; they stay in the
  definition (and later in denominators) but are never product identity anchors — exclude them from
  the conflicting-descriptor map (`described` is keyed by `facing.product`) and count them as
  sufficient in `definition_coverage`. An expected-empty facing MAY still carry a `product` value
  (e.g. converter provenance); it is ignored for descriptor conflicts and identity.
- **Virtual shelves**: id `f"zone:{zone.zone_id}"`, `shelf_number = max(physical numbers, default 0) + 1 + i`
  in zone order, `level=None`, `facings=[]`; set the zone's `shelf_id` to it. If a PHYSICAL shelf
  already has that id while the zone is unowned → `SlotsDefinitionError("virtual shelf id collision: zone:<id>")`.
  A zone already owned by `zone:<id>` (re-loaded dump) is simply preserved — this keeps load idempotent.
  This is a scoring projection, never an invented detected shelf (spec §2).
- **Empty definition**: `not definition.all_facings() and not definition.zones` → `SlotsDefinitionError("empty definition: ...")`.
- **Descriptor attributes collision** (spec §7): a key in `attributes` equal to any typed field name of
  `Descriptors` (`display_name`, `family`, `xl`, `colors`, `pack`, `identifiers`, `aliases`, `price`) is
  rejected; never silently drop a custom field.
- **Bindings** (spec §2, §7): required zone without a mandatory `zone_present` binding whose
  `target_id == zone_id` → `SlotsDefinitionError(f"required zone {zone_id}: no mandatory zone_present binding")`.
  Facing-less shelf with no mandatory binding on it or its zones → keep the message prefix
  `"{shelf_id}: zone-only shelf has no mandatory bound rule"` (tests match `"zone-only shelf"`).
  Runtime never inserts bindings or expected observations.
- `load_slots_definition` stays synchronous (callers wrap it in `asyncio.to_thread`).

### Transitional note
Until TASK-3861 lands, `verify.pick_candidates` sorts by `f.product` (`verify.py:87`) and
`ProductOnShelves._canonical_identity` calls `f.product.casefold()` (`product_on_shelves.py:777`):
both would fail on a definition that actually contains `product=None` facings. No existing test or
config contains one, so no current test breaks; TASK-3861 / TASK-3865 fix those readers.
The last assertion of `test_slots_definition.py::test_zone_only_shelf_without_binding_is_rejected`
must be updated here because the fixture's header zone is `required` (default) and now needs a
mandatory `zone_present` binding on the zone itself (a binding on `shelf_header` is no longer enough).

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py:321-347` — how score_shelves maps zone targets to shelves (why virtual shelves make zone-only units scoreable)
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/registration.py:197` — registration uses only shelves WITH facings, so virtual shelves never enter row alignment

---

## Implementation Blueprint

### Steps (in order)
1. Extend `ZoneKind`, `_DESCRIPTOR_KEYS`, imports — *why*: schema vocabulary first.
2. Add `Descriptors.attributes` + collision validator — *why*: custom descriptors without dropping typed ink fields (spec §2).
3. Add `expected_occupancy`, optional `product` + occupancy validator on `FacingDefinition` — *why*: express expected emptiness explicitly.
4. Default `SlotsDefinition.shelves` to `[]` — *why*: zone-only definitions have no physical shelves.
5. Add `_normalise_zone_shelves(definition)` and call it in `load_slots_definition` before `_validate` — *why*: deterministic virtual score units.
6. Update `_validate` (empty definition, described rule only for occupied facings, skip empties in conflicts) — *why*: spec §6 correction for `definition.py:215`.
7. Update `definition_coverage` and `validate_bindings` — *why*: spec §7 coverage note and mandatory presence rules.
8. Update / add tests; run validation commands.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -Fxc 'from pydantic import BaseModel, Field, ValidationError' definition.py)
# REPLACE line definition.py:10
from pydantic import BaseModel, Field, ValidationError, model_validator
```
```python
# occurrences: 1 (verified: grep -Fxc 'ZoneKind = Literal["header", "backlit", "poster", "box_stack"]' definition.py)
# REPLACE line definition.py:15
ZoneKind = Literal[
    "header", "backlit", "poster", "box_stack", "graphic", "advertisement", "counter", "information_label"
]
AttributeValue = Union[str, int, float, bool, List[str]]
VIRTUAL_SHELF_PREFIX = "zone:"
```
```python
# occurrences: 1 (verified: grep -Fxc '    "price",' definition.py)
# AFTER — insert below `    "price",` (verified: definition.py:25, inside _DESCRIPTOR_KEYS)
    "attributes",
```
```python
# occurrences: 1 (verified: grep -Fxc '    price: Optional[float] = None' definition.py)
# AFTER — insert below `    price: Optional[float] = None` (verified: definition.py:43, inside Descriptors)
    attributes: Dict[str, AttributeValue] = Field(default_factory=dict)  # custom, profile-declared descriptors

    @model_validator(mode="after")
    def _no_typed_collision(self) -> "Descriptors":
        """Reject custom attribute keys that shadow a typed descriptor field."""
        # FILL IN: typed = set(type(self).model_fields) - {"attributes"}; clash = sorted(typed & set(self.attributes));
        #          raise ValueError(f"descriptor attributes collide with typed fields: {', '.join(clash)}") — spec §7
        return self
```
```python
# occurrences: 1 (verified: grep -Fxc '    product: str' definition.py)
# REPLACE line definition.py:62 (inside FacingDefinition)
    product: Optional[str] = None  # required (nonblank) unless expected_occupancy == "empty"
```
```python
# occurrences: 1 (verified: grep -Fxc '    descriptors: Descriptors = Field(default_factory=Descriptors)' definition.py)
# AFTER — insert below that line (verified: definition.py:67, last field of FacingDefinition)
    expected_occupancy: Literal["occupied", "empty"] = "occupied"

    @model_validator(mode="after")
    def _occupied_needs_product(self) -> "FacingDefinition":
        """An occupied position must name its product; an expected-empty one may not."""
        # FILL IN: expected_occupancy == "occupied" and not (product and product.strip()) ->
        #          ValueError(f"{self.facing_id}: occupied facing requires a nonblank product")
        return self
```
```python
# occurrences: 1 (verified: grep -Fxc '    shelves: List[ShelfDefinition]' definition.py)
# REPLACE line definition.py:103 (inside SlotsDefinition)
    shelves: List[ShelfDefinition] = Field(default_factory=list)  # [] for zone-only fixtures
```
```python
# NEW private helper — insert ABOVE `def load_slots_definition(` (verified: definition.py:218, occurrences: 1)
def _normalise_zone_shelves(definition: SlotsDefinition) -> None:
    """Give every unowned zone a deterministic virtual score shelf ``zone:<zone_id>`` (in place, after sorting).

    Raises:
        SlotsDefinitionError: a physical shelf already uses the virtual id of an unowned zone.
    """
    # FILL IN: rules of Implementation Notes "Virtual shelves"; append ShelfDefinition(shelf_id=..., shelf_number=...,
    #          level=None, facings=[]) in zone order; set zone.shelf_id; never touch owned zones
```
```python
# occurrences: 1 (verified: grep -Fxc '    _validate(definition)' definition.py)
# BEFORE — insert above `    _validate(definition)` (verified: definition.py:257, after the facing sort loop)
    _normalise_zone_shelves(definition)
```
```python
# _validate (verified: definition.py:173-215).
# 1) FIRST statement of the body, before the duplicate-id loop at :182:
    if not definition.all_facings() and not definition.zones:
        raise SlotsDefinitionError("empty definition: no facings and no zones")
# 2) occurrences: 1 (verified: grep -Fxc '    for facing in definition.all_facings():' definition.py) — line :202.
#    First line of that loop body becomes:
        if facing.expected_occupancy == "empty" or not facing.descriptors.described:
            continue
#    (replaces the existing `if not facing.descriptors.described:` / `continue` at :203-204)
# 3) occurrences: 1 (verified: grep -Fxc '    if not described:' definition.py) — REPLACE lines :214-215 with:
    occupied = [f for f in definition.all_facings() if f.expected_occupancy == "occupied"]
    if occupied and not described:
        raise SlotsDefinitionError("zero described positions: at least one occupied facing needs a display_name")
```
```python
# definition_coverage (verified: definition.py:267-282).
# occurrences: 1 (verified: grep -Fxc '    sufficient_products = {f.product for f in facings if f.descriptors.sufficient}' definition.py)
# REPLACE lines :280-281 with:
    occupied = [f for f in facings if f.expected_occupancy == "occupied"]
    sufficient_products = {f.product for f in occupied if f.descriptors.sufficient}
    undescribed = [f.facing_id for f in occupied if f.product not in sufficient_products]
```
```python
# validate_bindings (verified: definition.py:285-337).
# occurrences: 1 (verified: grep -Fxc '    targets = {b.target_id for b in bindings}' definition.py)
# REPLACE lines :330-336 (the zone-only shelf block) with:
    # Order matters: the zone-only-unit check runs FIRST so existing "zone-only shelf" expectations keep matching.
    mandatory_targets = {b.target_id for b in bindings if b.mandatory}
    for shelf in definition.shelves:
        if shelf.facings:
            continue
        shelf_zone_ids = {z.zone_id for z in definition.zones if z.shelf_id == shelf.shelf_id}
        if shelf.shelf_id not in mandatory_targets and not (shelf_zone_ids & mandatory_targets):
            raise SlotsDefinitionError(f"{shelf.shelf_id}: zone-only shelf has no mandatory bound rule")
    presence = {b.target_id for b in bindings if b.kind == "zone_present" and b.mandatory}
    for zone in definition.zones:
        if zone.required and zone.zone_id not in presence:
            raise SlotsDefinitionError(f"required zone {zone.zone_id}: no mandatory zone_present binding")
```
**Why**: every block is a verified single-occurrence anchor; the replacements keep the existing
error prefixes that tests match. Also update the docstrings of `load_slots_definition`,
`definition_coverage` and `validate_bindings` (Raises / Returns) to describe the new rules — the
docstring is the contract other tasks read.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_slots_definition.py` (MODIFY)
```python
# test_zone_only_shelf_without_binding_is_rejected (verified: test_slots_definition.py:245-250)
# REPLACE its last line `    assert validate_bindings(definition, _config(_binding("r1", "shelf_header")))` with:
    assert validate_bindings(definition, _config(_binding("r1", "zone_header")))
# test_missing_rule_bindings_key_returns_empty (verified: :253-263) and the first assertion of
# test_zone_only_shelf_without_binding_is_rejected stay UNCHANGED: the zone-only check runs first and still matches.
```
Append the new tests of the Test Specification at the end of the file.

**Why**: the fixture's `zone_header` is `required` by default, so a `zone_present` bound to the
*shelf* satisfies the zone-only-unit rule but no longer the mandatory-presence rule for the zone.

### FILL IN checklist
- [ ] `Descriptors._no_typed_collision` — spec §7 collision rule.
- [ ] `FacingDefinition._occupied_needs_product` — spec §2 Stage 3; AC9.
- [ ] `_normalise_zone_shelves` — deterministic ids/numbers, collision, idempotent; AC9.
- [ ] `_validate` / `definition_coverage` / `validate_bindings` edits — AC9, AC10.
- [ ] tests — every rule has a passing and a failing case.

---

## Acceptance Criteria

- [ ] Existing native and page1 definitions load exactly as before (same shelves order, facings, coverage) (spec §2 "existing definitions retain their behavior").
- [ ] A definition with only expected-empty facings loads; an occupied facing without product raises `SlotsDefinitionError` naming the facing (AC9).
- [ ] A zone-only definition (no `shelves` key) loads with one virtual shelf `zone:<zone_id>` per unowned zone, in zone order, with deterministic `shelf_number`s; dumping and reloading gives an equal definition (AC9).
- [ ] A physical shelf named `zone:<id>` next to an unowned zone `<id>` is rejected; an explicitly owned zone keeps its shelf.
- [ ] `{"shelves": [], "zones": []}` is rejected as an empty definition (AC9).
- [ ] The four new zone kinds validate; an unknown kind still fails.
- [ ] `attributes={"finish": "matte", "sizes": ["s", "m"]}` loads; `attributes={"family": "x"}` is rejected.
- [ ] `definition_coverage` is 1.0 for a zone-only definition and counts expected-empty facings as covered.
- [ ] `validate_bindings` rejects a required zone lacking a mandatory `zone_present` binding and a facing-less shelf lacking any mandatory binding; accepts the complete set (AC10).
- [ ] Validation commands pass; `ruff check` and `black --check` clean.
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_slots_definition.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_slots_definition.py`

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_slots_definition.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_compare.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_slots_definition.py  (append)


def _zone_only(*zones) -> dict:
    return {"version": "1", "zones": list(zones)}


def test_expected_empty_facing_needs_no_product(native_definition):
    native_definition["shelves"][1]["facings"][2].update({"product": None, "expected_occupancy": "empty"})
    definition = load_slots_definition(native_definition)
    empty = next(f for f in definition.all_facings() if f.facing_id == "f13")
    assert empty.expected_occupancy == "empty" and empty.product is None


def test_occupied_facing_requires_product(native_definition):
    native_definition["shelves"][1]["facings"][2]["product"] = "  "
    with pytest.raises(SlotsDefinitionError, match="f13"):
        load_slots_definition(native_definition)


def test_all_expected_empty_definition_is_legal():
    # FILL IN: one shelf, two facings with expected_occupancy="empty" and no product/descriptors -> loads;
    #          definition_coverage(...) == (1.0, [])


def test_zone_only_definition_gets_virtual_shelves():
    definition = load_slots_definition(_zone_only({"zone_id": "g1", "kind": "graphic"},
                                                  {"zone_id": "i1", "kind": "information_label"}))
    assert [s.shelf_id for s in definition.shelves] == ["zone:g1", "zone:i1"]
    assert [z.shelf_id for z in definition.zones] == ["zone:g1", "zone:i1"]
    assert definition_coverage(definition) == (1.0, [])
    # FILL IN: shelf_numbers strictly increasing; load_slots_definition(definition.model_dump()) == definition


def test_virtual_shelf_collision_is_rejected():
    # FILL IN: physical shelf "zone:g1" with a facing + unowned zone "g1" -> SlotsDefinitionError match "collision"


def test_owned_zone_keeps_its_shelf(native_definition):
    definition = load_slots_definition(native_definition)
    assert next(z for z in definition.zones if z.zone_id == "zone_header").shelf_id == "shelf_header"
    assert not any(s.shelf_id.startswith("zone:") for s in definition.shelves)


def test_empty_definition_is_rejected():
    with pytest.raises(SlotsDefinitionError, match="empty definition"):
        load_slots_definition({"shelves": [], "zones": []})


@pytest.mark.parametrize("kind", ["graphic", "advertisement", "counter", "information_label", "header"])
def test_new_zone_kinds_validate(kind):
    assert load_slots_definition(_zone_only({"zone_id": "z", "kind": kind})).zones[0].kind == kind


def test_custom_attributes_and_collision(native_definition):
    native_definition["shelves"][1]["facings"][0]["descriptors"]["attributes"] = {"finish": "matte", "sizes": ["s"]}
    assert load_slots_definition(copy.deepcopy(native_definition)).all_facings()  # loads
    # FILL IN: attributes {"family": "x"} -> SlotsDefinitionError match "collide"


def test_required_zone_needs_mandatory_zone_present(native_definition):
    definition = load_slots_definition(native_definition)
    shelf_rule = _binding("r0", "shelf_header", "illumination")  # mandatory: satisfies the zone-only-unit rule
    with pytest.raises(SlotsDefinitionError, match="required zone zone_header"):
        validate_bindings(definition, _config(shelf_rule, {**_binding("r1", "zone_header"), "mandatory": False}))
    assert validate_bindings(definition, _config(_binding("r1", "zone_header")))


def test_optional_zone_only_unit_needs_a_mandatory_rule():
    definition = load_slots_definition(_zone_only({"zone_id": "g1", "kind": "graphic", "required": False}))
    # FILL IN: only a non-mandatory illumination binding on g1 -> match "zone-only shelf";
    #          a mandatory visual_features binding on g1 -> accepted
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3860 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Implemented by coder seat via sdd-worker orchestration (merge-tier tests green for planogram scope; unrelated ai-parrot-server collection errors due to missing fakeredis in shared env).

