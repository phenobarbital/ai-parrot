# TASK-4174: CompletenessPolicy model and the two new LayoutProfile knobs

**Feature**: FEAT-646 — Ink-wall slot recovery and completeness policy
**Spec**: `sdd/specs/ink-wall-registration-and-completeness.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Part B and §3 Modules 1–2. Every other model-level change of FEAT-646 hangs off the layout
profile: `CompletenessPolicy` (new, next to `ReportingPolicy`) is consumed by `summarize()` /
`project_compliance()` (TASK-4175), and `LayoutProfile.definition_gap_fill` is read by `perceive`
(TASK-4178). This task only adds the models, the two fields with today's-behaviour defaults, and the
ink-wall defaults (`definition_gap_fill=True`, `min_coverage=0.9`, `min_shelf_coverage=0.8`, spec G3 / Q4).
Both `M1` and `M2` touch `layout.py` and `types/ink_wall.py`, so the profile edits of both modules are
grouped here to keep those two files in a single task.

---

## Scope

- Add `CompletenessPolicy` (pydantic, `extra="forbid"`, `min_coverage` / `min_shelf_coverage` in [0, 1],
  default 1.0) to `comparison/definition.py`, directly after `ReportingPolicy`.
- Add `LayoutProfile.definition_gap_fill: bool = False` (after `untagged_bottom_row`) and
  `LayoutProfile.completeness: CompletenessPolicy = Field(default_factory=CompletenessPolicy)` (after
  `reporting`).
- Set the ink-wall defaults in `InkWall.default_layout_profile()`.
- Tests: `test_ink_wall_profile_defaults` (in `test_ink_wall.py`) and `test_layout_completeness_override`
  (in `test_layout_profile.py`).

**NOT in scope**: using the policy in `summarize` / `project_compliance` / `compare_observations`
(TASK-4175); reading `definition_gap_fill` in perception (TASK-4178); `build_slots` changes (TASK-4176).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` | MODIFY | add `CompletenessPolicy` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py` | MODIFY | `definition_gap_fill`, `completeness` fields + import |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py` | MODIFY | ink-wall defaults + import |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py` | MODIFY | `test_ink_wall_profile_defaults` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_layout_profile.py` | MODIFY | `test_layout_completeness_override` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field  # already imported in comparison/definition.py:10
from .comparison.definition import ReportingPolicy, SlotsDefinition  # layout.py:11 (extend this line)
from ..comparison.definition import ReportingPolicy, SlotsDefinition  # types/ink_wall.py:14 (extend this line)
from parrot_pipelines.planogram.layout import LayoutProfile, resolve_layout_profile, LAYOUT_KEY  # layout.py:66, :151, :18
from parrot_pipelines.planogram.types import InkWall  # used by test_ink_wall.py:39
```

### Existing Signatures to Use
```python
# comparison/definition.py:49
class ReportingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_label: Literal["display_name", "product"] = "display_name"
    slot_presence: bool = False
    misplaced_min_confidence: float = Field(default=0.9, ge=0.0, le=1.0)
class Descriptors(BaseModel):  # :59 — next class; insert CompletenessPolicy before it

# layout.py:66
class LayoutProfile(BaseModel):  # model_config extra="forbid" (:69)
    untagged_bottom_row: bool = False                                    # :74
    reporting: ReportingPolicy = Field(default_factory=ReportingPolicy)  # :97
def resolve_layout_profile(defaults, config, *, config_name) -> LayoutProfile  # :151
#   deep-merges config["layout_profile"]; a validation error is raised as ValueError naming config + path

# types/ink_wall.py:55
class InkWall(AbstractPlanogramType):
    @classmethod
    def default_layout_profile(cls) -> LayoutProfile:  # :64
        # last kwarg today: reporting=ReportingPolicy(product_label="product", slot_presence=True),  # :77

# tests/planogram_cycle/test_layout_profile.py
@pytest.fixture
def defaults() -> LayoutProfile  # :20
def test_invalid_fields_name_config_and_path(defaults, override, path)  # :84 — pattern for ValueError checks
# tests/planogram_cycle/test_ink_wall.py
def test_default_layout_profile_is_fresh_and_ink_shaped()  # :242 — pattern for profile assertions
```

### Does NOT Exist
- ~~`CompletenessPolicy`~~, ~~`LayoutProfile.completeness`~~, ~~`LayoutProfile.definition_gap_fill`~~ — created here
- ~~`ReportingPolicy.min_coverage`~~ — completeness does NOT live on `ReportingPolicy`
- ~~`ShelfConfig.completeness_threshold`~~ — not real (`ShelfConfig.compliance_threshold` is unrelated)
- ~~`comparison/completeness.py`~~ — no new module; the class lives in `comparison/definition.py`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_layout_profile.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#ReportingPolicy",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py#LayoutProfile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py#resolve_layout_profile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#InkWall.default_layout_profile"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Defaults must reproduce today's behaviour for every type (`definition_gap_fill=False`, 1.0 / 1.0) — spec AC3/AC4.
- Follow `ReportingPolicy` exactly: `extra="forbid"`, bounded `Field`s (spec §7).
- `layout.py` imports from `comparison/definition.py`; never the other way (no import cycle).

---

## Implementation Blueprint

### Steps (in order)
1. Add `CompletenessPolicy` after `ReportingPolicy` — *why*: spec §3 M2 places it next to the policy it mirrors.
2. Extend the `layout.py` import and add both fields — *why*: overrides then resolve through the existing `layout_profile` deep merge with no extra code.
3. Extend the `ink_wall.py` import and set the ink defaults — *why*: spec G3 / Q4 confirmed 0.9 / 0.8 and AC6.
4. Write the two tests and run the Validation Commands.

### `.../planogram/comparison/definition.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class Descriptors(BaseModel):' comparison/definition.py)
# BEFORE — insert above `class Descriptors(BaseModel):` (verified: comparison/definition.py:59)
class CompletenessPolicy(BaseModel):
    """Minimum resolved-facing fractions for a COMPLETE assessment (1.0 = every facing resolved).

    ``min_coverage`` gates the global ``assessment_status``; ``min_shelf_coverage`` gates each shelf's
    ``ComplianceResult.assessment``. Tolerance only changes completeness, never credits or scores.
    """

    model_config = ConfigDict(extra="forbid")

    min_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    min_shelf_coverage: float = Field(default=1.0, ge=0.0, le=1.0)


```
**Why**: spec §2 Data Models fixes this exact model; defaults reduce to today's "every position resolved".

### `.../planogram/layout.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .comparison.definition import ReportingPolicy, SlotsDefinition' layout.py)
# REPLACE line 11
from .comparison.definition import CompletenessPolicy, ReportingPolicy, SlotsDefinition

# occurrences: 1 (verified: grep -c '    untagged_bottom_row: bool = False' layout.py)
# AFTER — insert below `    untagged_bottom_row: bool = False` (verified: layout.py:74)
    #: Fill each full-height row up to the facings its definition shelf expects (TAG_BELOW_PRODUCT only).
    definition_gap_fill: bool = False

# occurrences: 1 (verified: grep -c '    reporting: ReportingPolicy = Field(default_factory=ReportingPolicy)' layout.py)
# AFTER — insert below `    reporting: ReportingPolicy = Field(default_factory=ReportingPolicy)` (verified: layout.py:97)
    completeness: CompletenessPolicy = Field(default_factory=CompletenessPolicy)
```
**Why**: `extra="forbid"` on `LayoutProfile` means the override `{"layout_profile": {"completeness": {...}}}`
is rejected today; adding the field is all the override path needs.

### `.../planogram/types/ink_wall.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from ..comparison.definition import ReportingPolicy, SlotsDefinition' types/ink_wall.py)
# REPLACE line 14
from ..comparison.definition import CompletenessPolicy, ReportingPolicy, SlotsDefinition

# occurrences: 1 (verified: grep -c 'reporting=ReportingPolicy(product_label="product", slot_presence=True),' types/ink_wall.py)
# AFTER — insert below `            reporting=ReportingPolicy(product_label="product", slot_presence=True),` (verified: types/ink_wall.py:77)
            definition_gap_fill=True,
            completeness=CompletenessPolicy(min_coverage=0.9, min_shelf_coverage=0.8),
```
**Why**: the type owns its defaults (spec §7 "Patterns to Follow"); configs override through `layout_profile`.

### `tests/planogram_cycle/test_ink_wall.py` (MODIFY — append)
```python
def test_ink_wall_profile_defaults():
    """FEAT-646: ink walls opt into the definition-aware fill and a tolerant completeness policy."""
    profile = InkWall.default_layout_profile()
    assert profile.definition_gap_fill is True
    assert (profile.completeness.min_coverage, profile.completeness.min_shelf_coverage) == (0.9, 0.8)
    # FILL IN: assert a fresh instance per call (mutating one profile's completeness does not leak) — bounded by AC6
```

### `tests/planogram_cycle/test_layout_profile.py` (MODIFY — append)
```python
def test_layout_completeness_override(defaults: LayoutProfile) -> None:
    """FEAT-646 AC6: completeness overrides resolve and are validated."""
    # FILL IN: resolve_layout_profile(defaults, {"layout_profile": {"completeness": {"min_coverage": 0.95,
    #   "min_shelf_coverage": 0.85}}}, config_name="cfg") ⇒ both values set; defaults (no override) ⇒ 1.0 / 1.0
    #   and definition_gap_fill False; an unknown key ({"completeness": {"bogus": 1}}) and an out-of-range value
    #   ({"completeness": {"min_coverage": 1.5}}) ⇒ pytest.raises(ValueError) — bounded by AC6
```

### FILL IN checklist
- [ ] `test_ink_wall.py::test_ink_wall_profile_defaults` — freshness assertion; bounded by AC6
- [ ] `test_layout_profile.py::test_layout_completeness_override` — override + two rejections; bounded by AC6

---

## Acceptance Criteria

- [ ] `CompletenessPolicy` importable from `parrot_pipelines.planogram.comparison.definition`; defaults 1.0 / 1.0; `extra="forbid"`; range [0, 1] (spec AC6)
- [ ] `LayoutProfile()` defaults: `definition_gap_fill is False`, `completeness == CompletenessPolicy()` (spec AC3/AC4)
- [ ] `InkWall.default_layout_profile()`: `definition_gap_fill=True`, 0.9 / 0.8 (spec AC6)
- [ ] Existing `test_layout_profile.py`, `test_ink_wall.py`, `test_reporting_layout.py` still pass
- [ ] `ruff check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_layout_profile.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_reporting_layout.py -q`

---

## Test Specification

See the two test stubs in the Implementation Blueprint (spec §4: `test_ink_wall_profile_defaults`,
`test_layout_completeness_override`).

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug ink-wall-registration-and-completeness --feature-id FEAT-646`).
2. Read the spec; verify the Codebase Contract; set this task `in-progress` in `sdd/tasks/index/ink-wall-registration-and-completeness.json`.
3. Implement from the blueprint, complete every `FILL IN`, run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.
4. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4174 ink-wall-registration-and-completeness verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none


**Completion Note (sdd-worker)**: merged via coder_merge; tests for touched modules pass (87 passed, PYTHONPATH-scoped). Merge-tier sweep showed pre-existing env failures (parrot.utils.types Cython .so, ocr_reader pyproject pillow) in files this feature does not touch.
