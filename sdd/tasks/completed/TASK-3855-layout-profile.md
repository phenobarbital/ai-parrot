# TASK-3855: LayoutProfile, ReferencePolicy, ZoneSelector and resolve_layout_profile

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3854
**Assigned-to**: unassigned

---

## Context

Spec §2 **"Layout and configuration contract"** and §3 **Module 1** (`layout.py` skeleton). Today
every planogram type hardcodes its perception/identification settings as class attributes
(`InkWall.min_usable_shapes = 8`, `ProductOnShelves.get_shape_profiles()`, a hardcoded descriptor
vocabulary). FEAT-612 moves those settings into one strict, validated `LayoutProfile`: each type
supplies a default (TASK-3864..3869) and a store config overrides it through the new key
`PlanogramConfig.planogram_config["layout_profile"]` (no new DB column). This task creates the
models and the merge/validate function; the shared stages (TASK-3856/3857/3859) read the resolved
profile from `CycleContext.layout`, and the orchestrator (TASK-3871) resolves it once at construction.

---

## Scope

- Create `planogram/layout.py` with `ReferencePolicy`, `ZoneSelector`, `LayoutProfile` (all
  `extra="forbid"`) and `resolve_layout_profile(defaults, config, *, config_name)` exactly as the M1 skeleton.
- Implement every validation rule of the spec §2 table: nonempty `shape_profiles` for `cv`, every
  profile kind a `ShapeKind` value, unique profile names, unique selector zone ids, nonnegative /
  positive caps, reversed/out-of-range selector regions, unique descriptor fields with required ⊆
  declared, unique `ocr_targets`, positive `references.max_per_call`.
- Implement the merge policy: fresh copy of the defaults, recursive merge of nested models
  (`references`), atomic replacement of lists, no mutation of caller dicts or class defaults,
  unknown keys rejected (including unknown keys inside a `shape_profiles` item, since
  `ShapeProfile` itself does not forbid extras).
- Implement the compatibility alias: old top-level `planogram_config["perception_mode"]` is used
  only when `layout_profile.perception_mode` is absent; contradictory values fail.
- Every error is a `ValueError` whose message contains `config_name` and the full field path
  (e.g. `layout_profile.references.max_per_call`).
- Add `validate_zone_selectors(profile, definition, *, config_name)` — the definition-dependent
  checks of the spec §2 table (dangling selector zone ids, selectors required for repeated same-kind zones).
- Create `tests/planogram_cycle/test_layout_profile.py`.

**NOT in scope**: `IdentifyStrategy.SLOTS` itself (TASK-3854); any per-type default profile
(TASK-3864..3869); calling `resolve_layout_profile` from `PlanogramCompliance.__init__` (TASK-3871);
matching selectors to observed zones at run time (TASK-3856); `PlanogramConfig` model descriptions
(TASK-3872); converter use (TASK-3877). Do not edit `perception/profiles.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py` | CREATE | Strict layout models, merge/validate, selector-vs-definition check |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_layout_profile.py` | CREATE | Validation / merge / alias / no-mutation tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from parrot_pipelines.planogram.contracts import IdentifyStrategy, ShapeKind      # contracts.py:43, :15
from parrot_pipelines.planogram.perception.profiles import ShapeProfile           # profiles.py:10
from parrot_pipelines.planogram.perception.slots import AnchorRule                # slots.py:27
from parrot_pipelines.planogram.comparison.definition import SlotsDefinition      # definition.py:98
```
Import-cycle check (spec §7 "layout imports existing enums/profiles"): `perception/slots.py:13`
imports `..contracts`; `comparison/definition.py` imports nothing from the planogram package;
`contracts.py` must never import `layout.py`. So `layout.py` → contracts/profiles/slots/definition is acyclic.

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/profiles.py:10
class ShapeProfile(BaseModel):                      # NOTE: no extra="forbid" — unknown keys are silently dropped
    name: str
    kind: str                                       # a ShapeKind VALUE as plain str (:18)
    min_width/max_width/min_height/max_height: float (gt=0, le=1); min_aspect/max_aspect: float (gt=0)
    polarity: Literal["bright", "dark", "edge"]
    min_rectangularity: float = 0.75; min_contrast_std: float = 25.0
    thresholds: Tuple[int, ...] = (130, 150, 170, 190, 210, 230); dedup_overlap: float = 0.5
    _check_bands validator: min_* < max_*, thresholds in 0..255                 # :31-50
PRICE_TAG_PROFILE = ShapeProfile(name="price_tag", kind="price_tag", ...)       # profiles.py:64

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py:27
class AnchorRule(str, Enum): TAG_BELOW_PRODUCT = "tag_below_product"; SHAPE_IS_SLOT = "shape_is_slot"

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py
class ShapeKind(str, Enum): PRICE_TAG, PRODUCT, BOX, FACT_TAG, ZONE, UNKNOWN   # :15-23 (values "price_tag", ...)
class IdentifyStrategy(str, Enum): FULL_IMAGE="full_image", STRIPS="strips"    # :43-47 (+ SLOTS from TASK-3854)

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py
class ZoneDefinition(BaseModel): zone_id: str; kind: ZoneKind; shelf_id: Optional[str]; required: bool = True   # :79-85
class SlotsDefinition(BaseModel): version, meta, shelves, zones: List[ZoneDefinition]                           # :98-104

# The only config keys read from planogram_config today (spec §6 Key Attributes):
#   "perception_mode" (product_on_shelves.py:272), "verify_pass" (ink_wall.py:256), "rule_bindings" (definition.py:300)
```

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3854 — contracts.py
class IdentifyStrategy(str, Enum): ...; SLOTS = "slots"
```

### Does NOT Exist
- ~~`parrot_pipelines.planogram.layout`~~ — this task creates it.
- ~~`PlanogramConfig.layout_profile`~~ — there is no model field / DB column; the profile lives inside the
  `planogram_config` JSON dict under the key `"layout_profile"`.
- ~~`ShapeProfile.model_config = ConfigDict(extra="forbid")`~~ — not set; reject unknown shape-profile keys yourself.
- ~~A "detection_grid" / prompt field in LayoutProfile~~ — legacy fields are not part of the profile.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_layout_profile.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/profiles.py#ShapeProfile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#AnchorRule",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#ShapeKind",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#IdentifyStrategy",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#SlotsDefinition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#ZoneDefinition"
  ]
}
```

---

## Implementation Notes

### Planner cross-task notes (added at /sdd-task time)
- `resolve_layout_profile(defaults, config, *, config_name)` takes `config` = the WHOLE `planogram_config` dict (it reads `config.get("layout_profile", {})` itself and the top-level `perception_mode` alias) — because the spec's alias rule needs both keys and callers (TASK-3871 plan.py, TASK-3877 migration.py) must not pre-slice.
- `validate_zone_selectors(profile, definition, *, config_name)` is a public helper of layout.py; TASK-3871 calls it once the definition is loaded — keep the signature exactly.


### Pattern to Follow
- Pydantic v2 validators as in `perception/profiles.py:31-50` (`@model_validator(mode="after")`
  returning `self`, raising `ValueError` whose message names the field).
- Error wrapping: catch `ValidationError`, build `".".join(str(p) for p in err["loc"])` for each
  entry of `exc.errors()`, prefix with `layout_profile.`, and raise
  `ValueError(f"{config_name}: invalid layout_profile: {path}: {err['msg']}")` (join several errors with `; `).

### Key Constraints
- **No mutation** (spec §2): `defaults.model_dump()` gives a fresh dict; `copy.deepcopy` the override
  dict before merging; never assign into `config` or into `defaults`.
- **Merge rule**: dict-into-dict recurses (only `references` is a nested model today); every other
  value — lists included — replaces the default atomically. `shape_profiles: [...]` replaces the
  whole list; items are full profile dicts (no per-item merge).
- **Explicit null** is valid only where the field is Optional (`ZoneSelector.profile/kind/ordinal/region`);
  `None` for a non-optional field must fail validation (Pydantic does this — do not coerce it away).
- `ocr_targets` default must not be a shared mutable literal: use `Field(default_factory=...)`.
- Type defaults supply detection profiles, never retailer selector ids/counts (spec §2) — nothing in
  this module may hardcode a zone id, product or count.
- Region: `[x1, y1, x2, y2]` normalized to the full source image, each in `[0, 1]`, `x1 < x2`, `y1 < y2`.
- `min_usable_shapes >= 0` (0 disables fallback); `min_row_items >= 1`; `max_row_slope >= 0`;
  `work_width`, `substrip_max_slots`, `ocr_batch_size`, `references.max_per_call` `> 0`; `ordinal >= 0`.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:263-275` — the old `perception_mode` read (alias source)
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/profiles.py:10-50` — validator style

---

## Implementation Blueprint

### Steps (in order)
1. Write the three models with `ConfigDict(extra="forbid")` and field constraints — *why*: spec §2 "no implicit unknown-key acceptance in LayoutProfile".
2. Add the `LayoutProfile` cross-field validator — *why*: rules that span fields (cv needs profiles, required ⊆ declared, unique names).
3. Write `_deep_merge` and `_reject_unknown_shape_keys` — *why*: recursive merge with atomic lists; `ShapeProfile` would silently drop typos.
4. Write `resolve_layout_profile` (alias → merge → validate → wrap errors) — *why*: single construction-time entry point for TASK-3871.
5. Write `validate_zone_selectors` — *why*: zone-id checks need the loaded definition, which the merge does not see.
6. Write the tests and run the validation commands.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py` (CREATE)
```python
"""Validated layout profile: per-type perception/identification defaults plus config overrides (FEAT-612)."""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .comparison.definition import SlotsDefinition
from .contracts import IdentifyStrategy, ShapeKind
from .perception.profiles import ShapeProfile
from .perception.slots import AnchorRule

logger = logging.getLogger(__name__)

LAYOUT_KEY = "layout_profile"
_SHAPE_KINDS = frozenset(kind.value for kind in ShapeKind)


class ReferencePolicy(BaseModel):
    """Bound and select references without using expected shelf identity."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    selection: Literal["all", "by_brand"] = "all"
    max_per_call: int = Field(default=5, gt=0)
    brand_by_reference: Dict[str, str] = Field(default_factory=dict)


class ZoneSelector(BaseModel):
    """Match observed zones, never invent them from an expected id."""

    model_config = ConfigDict(extra="forbid")

    zone_id: str = Field(min_length=1)
    profile: Optional[str] = None
    kind: Optional[str] = None
    ordinal: Optional[int] = Field(default=None, ge=0)
    region: Optional[Tuple[float, float, float, float]] = None

    @model_validator(mode="after")
    def _check(self) -> "ZoneSelector":
        """Kind is a ShapeKind value; region is a normalized, non-reversed box."""
        # FILL IN: kind not in _SHAPE_KINDS -> ValueError("kind: ..."); region values outside [0, 1] or
        #          x1 >= x2 / y1 >= y2 -> ValueError("region: ...") — bounded by spec §2 selector paragraph
        return self


class LayoutProfile(BaseModel):
    """Strict, validated perception and identification settings; extra keys forbidden."""

    model_config = ConfigDict(extra="forbid")

    shape_profiles: List[ShapeProfile]
    anchor_rule: AnchorRule = AnchorRule.SHAPE_IS_SLOT
    fill_gaps: bool = False
    untagged_bottom_row: bool = False
    identify_strategy: IdentifyStrategy = IdentifyStrategy.FULL_IMAGE
    perception_mode: Literal["cv", "llm_detector"] = "cv"
    min_usable_shapes: int = Field(default=1, ge=0)
    min_row_items: int = Field(default=1, ge=1)
    max_row_slope: float = Field(default=0.12, ge=0.0)
    work_width: int = Field(default=2048, gt=0)
    substrip_max_slots: int = Field(default=8, gt=0)
    ocr_batch_size: int = Field(default=16, gt=0)
    descriptor_fields: List[str] = Field(default_factory=list)
    required_descriptor_fields: List[str] = Field(default_factory=list)
    ocr_targets: List[Literal["slot", "tag", "zone"]] = Field(default_factory=lambda: ["slot", "tag", "zone"])
    references: ReferencePolicy = Field(default_factory=ReferencePolicy)
    zone_selectors: List[ZoneSelector] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "LayoutProfile":
        """Cross-field rules of the spec §2 layout table. Messages start with the field name."""
        # FILL IN: perception_mode == "cv" and not shape_profiles -> "shape_profiles: required for cv"
        # FILL IN: each shape_profiles[i].kind not in _SHAPE_KINDS -> f"shape_profiles.{i}.kind: ..."
        # FILL IN: duplicate shape profile names, duplicate zone_selectors zone_id, duplicate descriptor_fields,
        #          duplicate ocr_targets -> ValueError naming the field and the duplicate values
        # FILL IN: required_descriptor_fields not a subset of descriptor_fields -> name the extra fields
        # FILL IN: zone_selectors[i].profile set, shape_profiles nonempty and not a declared profile name ->
        #          f"zone_selectors.{i}.profile: unknown profile ..."
        return self


def _reject_unknown_shape_keys(overrides: Dict[str, Any]) -> List[str]:
    """Field paths of unknown keys inside ``shape_profiles`` items (ShapeProfile does not forbid extras)."""
    # FILL IN: for i, item in enumerate(overrides.get("shape_profiles") or []), when item is a dict, collect
    #          f"layout_profile.shape_profiles.{i}.{key}" for key not in ShapeProfile.model_fields — bounded by spec §2
    return []


def _deep_merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """New dict: nested dicts merge recursively, every other value (lists included) replaces atomically."""
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def resolve_layout_profile(defaults: LayoutProfile, config: dict[str, Any], *, config_name: str) -> LayoutProfile:
    """Merge a copy and validate; raise ValueError naming config and invalid field.

    Args:
        defaults: The planogram type's default profile (never mutated).
        config: The raw ``planogram_config`` dict (never mutated); overrides live under ``"layout_profile"``.
        config_name: ``PlanogramConfig.config_name``, included in every error message.

    Returns:
        A new, validated profile.

    Raises:
        ValueError: ``layout_profile`` is not a dict, an unknown key, an invalid value, or a top-level
            ``perception_mode`` contradicting ``layout_profile.perception_mode``.
    """
    raw = (config or {}).get(LAYOUT_KEY)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(f"{config_name}: invalid layout_profile: expected an object, got {type(raw).__name__}")
    overrides = copy.deepcopy(raw)
    # FILL IN: alias — top = config.get("perception_mode"); when top is not None: if "perception_mode" in
    #          overrides and overrides["perception_mode"] != top -> ValueError naming config_name and both
    #          "perception_mode" and "layout_profile.perception_mode"; else overrides["perception_mode"] = top
    # FILL IN: unknown = _reject_unknown_shape_keys(overrides); if unknown -> ValueError(config_name + paths)
    merged = _deep_merge(defaults.model_dump(), overrides)
    try:
        profile = LayoutProfile.model_validate(merged)
    except ValidationError as exc:
        # FILL IN: build "layout_profile.<loc>: <msg>" for every exc.errors() entry; raise ValueError(...) from exc
        raise
    logger.debug("layout profile resolved for %s: mode=%s strategy=%s", config_name, profile.perception_mode,
                 profile.identify_strategy.value)
    return profile


def validate_zone_selectors(profile: LayoutProfile, definition: SlotsDefinition, *, config_name: str) -> None:
    """Definition-dependent selector checks (spec §2): no dangling zone ids; repeated same-kind zones need selectors.

    Raises:
        ValueError: naming ``config_name`` and ``layout_profile.zone_selectors.<i>.zone_id`` (dangling) or the
            zone ids of a repeated kind that lack a selector.
    """
    # FILL IN: zone_ids = {z.zone_id for z in definition.zones}; each selector.zone_id must be in zone_ids
    # FILL IN: group definition.zones by kind; for any kind with >= 2 zones, every zone_id of it must have a
    #          selector — list the missing ids in the error. Never create selectors or zones here.
```
**Why this shape**: names, types and defaults are the M1 skeleton verbatim; numeric bounds use
`Field` so Pydantic reports the exact `loc`. `validate_zone_selectors` is a separate function
because `resolve_layout_profile(defaults, config, *, config_name)` has no definition argument in
the spec skeleton and must keep that signature; the orchestrator (TASK-3871) calls both at
construction, after the definition is loaded. Do not add a `definition` parameter to `resolve_layout_profile`.

### FILL IN checklist
- [ ] `ZoneSelector._check` — kind ∈ ShapeKind values; region normalized & non-reversed; bounded by spec §2.
- [ ] `LayoutProfile._check` — cv needs profiles; kinds; duplicates; required ⊆ declared; selector profile refs.
- [ ] `_reject_unknown_shape_keys` — typo keys fail with full path; bounded by spec §2 "Reject unknown keys".
- [ ] `resolve_layout_profile` — alias rule, error wrapping with `config_name` + path; AC10.
- [ ] `validate_zone_selectors` — dangling ids, repeated same-kind zones; AC10.

---

## Acceptance Criteria

- [ ] `resolve_layout_profile(defaults, {}, config_name="c")` returns a profile equal to `defaults` but not the same object (AC3).
- [ ] Overrides reach every field: a nested `{"references": {"max_per_call": 2}}` keeps `enabled`/`selection` from the defaults; `shape_profiles`, `ocr_targets`, `zone_selectors` lists replace the default list (spec §2).
- [ ] Neither the caller's `config` dict nor `defaults` changes after a resolve (deep-compare before/after).
- [ ] Unknown top-level keys, unknown keys inside a shape profile, invalid enums, duplicate profile/selector names, reversed/out-of-range regions, nonpositive caps and required-not-declared descriptor fields raise `ValueError` whose message contains `config_name` and the dotted field path (AC10).
- [ ] Top-level `perception_mode` is used when `layout_profile.perception_mode` is absent; equal values pass; contradictory values raise (spec §2 compatibility policy).
- [ ] `validate_zone_selectors` rejects a selector naming an unknown zone and two same-kind zones without selectors; accepts them when both have selectors (AC10).
- [ ] No retailer product, zone id or count appears in `layout.py` (AC3).
- [ ] Validation commands pass; `ruff check` and `black --check` clean.
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_layout_profile.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_layout_profile.py`

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_layout_profile.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_contracts.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_layout_profile.py
"""LayoutProfile validation, merge and compatibility alias (FEAT-612, Module 1)."""

import copy

import pytest

from parrot_pipelines.planogram.comparison.definition import load_slots_definition
from parrot_pipelines.planogram.contracts import IdentifyStrategy
from parrot_pipelines.planogram.layout import (
    LayoutProfile, ReferencePolicy, ZoneSelector, resolve_layout_profile, validate_zone_selectors,
)
from parrot_pipelines.planogram.perception.profiles import PRICE_TAG_PROFILE
from parrot_pipelines.planogram.perception.slots import AnchorRule


@pytest.fixture
def defaults() -> LayoutProfile:
    """Generic synthetic defaults — no retailer data."""
    return LayoutProfile(shape_profiles=[PRICE_TAG_PROFILE], anchor_rule=AnchorRule.TAG_BELOW_PRODUCT)


def test_empty_config_returns_equal_copy(defaults):
    resolved = resolve_layout_profile(defaults, {}, config_name="cfg")
    assert resolved == defaults and resolved is not defaults


def test_overrides_reach_fields_and_lists_replace(defaults):
    # FILL IN: override identify_strategy="slots", min_row_items=4, ocr_targets=["tag"], fill_gaps=True;
    #          assert each value and that ocr_targets == ["tag"] (replaced, not appended)


def test_nested_references_merge_recursively(defaults):
    resolved = resolve_layout_profile(defaults, {"layout_profile": {"references": {"max_per_call": 2}}},
                                      config_name="cfg")
    assert resolved.references.max_per_call == 2
    assert resolved.references.enabled is True and resolved.references.selection == "all"


def test_no_mutation_of_config_or_defaults(defaults):
    config = {"layout_profile": {"references": {"max_per_call": 2}, "ocr_targets": ["slot"]}}
    before_config, before_defaults = copy.deepcopy(config), defaults.model_copy(deep=True)
    resolve_layout_profile(defaults, config, config_name="cfg")
    assert config == before_config and defaults == before_defaults


@pytest.mark.parametrize(
    "override, path",
    [
        ({"bogus": 1}, "layout_profile.bogus"),
        ({"shape_profiles": [{**PRICE_TAG_PROFILE.model_dump(), "min_widht": 0.1}]}, "shape_profiles.0.min_widht"),
        ({"shape_profiles": [{**PRICE_TAG_PROFILE.model_dump(), "kind": "robot"}]}, "shape_profiles.0.kind"),
        ({"identify_strategy": "tiles"}, "identify_strategy"),
        ({"ocr_batch_size": 0}, "ocr_batch_size"),
        ({"references": {"max_per_call": 0}}, "references.max_per_call"),
        ({"zone_selectors": [{"zone_id": "z", "region": [0.8, 0.1, 0.2, 0.9]}]}, "region"),
        ({"descriptor_fields": ["family"], "required_descriptor_fields": ["xl"]}, "required_descriptor_fields"),
        ({"perception_mode": "cv", "shape_profiles": []}, "shape_profiles"),
    ],
)
def test_invalid_fields_name_config_and_path(defaults, override, path):
    with pytest.raises(ValueError) as info:
        resolve_layout_profile(defaults, {"layout_profile": override}, config_name="store-cfg")
    assert "store-cfg" in str(info.value) and path in str(info.value)


def test_duplicate_selector_and_profile_names_rejected(defaults):
    # FILL IN: two ZoneSelector with zone_id "z1" -> ValueError mentioning zone_selectors;
    #          two shape profiles named "price_tag" -> ValueError mentioning shape_profiles


def test_top_level_perception_mode_alias(defaults):
    assert resolve_layout_profile(defaults, {"perception_mode": "llm_detector"},
                                  config_name="c").perception_mode == "llm_detector"
    # FILL IN: equal values in both places pass; "cv" vs "llm_detector" raises ValueError containing "perception_mode"


def test_explicit_null_only_for_optional(defaults):
    ok = resolve_layout_profile(defaults, {"layout_profile": {"zone_selectors": [{"zone_id": "z", "kind": None}]}},
                                config_name="c")
    assert ok.zone_selectors[0].kind is None
    # FILL IN: {"work_width": None} raises ValueError containing "work_width"


def test_validate_zone_selectors_against_definition(defaults):
    definition = load_slots_definition({"shelves": [
        {"shelf_id": "s1", "shelf_number": 1, "facings": [
            {"facing_id": "f1", "shelf_id": "s1", "slot": 1, "product": "P-1", "descriptors": {"display_name": "P 1"}}]}],
        "zones": [{"zone_id": "za", "kind": "poster", "shelf_id": "s1"},
                  {"zone_id": "zb", "kind": "poster", "shelf_id": "s1"}]})
    # FILL IN: profile without selectors -> ValueError listing "za" and "zb" (repeated same-kind zones)
    # FILL IN: a selector for "nowhere" -> ValueError mentioning "zone_selectors.0.zone_id"
    # FILL IN: selectors for both za and zb (distinct ordinals) -> returns None
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3855 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Merged cleanly via sdd-worker orchestration; lint clean; coder-reported task tests pass.

