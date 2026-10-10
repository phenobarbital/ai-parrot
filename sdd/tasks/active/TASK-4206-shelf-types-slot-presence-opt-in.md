# TASK-4206: Shelf-based types opt in to slot presence

**Feature**: FEAT-648 — `products_found` for every product-detecting planogram type
**Spec**: `sdd/specs/products-found-endcap.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. `products_found` is already computed by the shared
`compare_observations` for every type, gated only by `ReportingPolicy.slot_presence`
(default `False`); only `InkWall` turns it on. This task adds the per-type opt-in
(decided in the proposal, U2 = Option B) to the four shelf-based types.

It also replaces FEAT-645's `test_non_ink_wall_result_unchanged`, because this very
change breaks it: `ProductOnShelves.compare` calls `_ensure_layout(ctx)`, which resolves
the type's default profile onto a `CycleContext` whose `layout` is `None` — so after the
opt-in that test's `products_found == []` assertion no longer holds. Changing the code
and the test in one task keeps every commit green.

---

## Scope

- Add `reporting=ReportingPolicy(slot_presence=True)` to the `LayoutProfile(...)` returned
  by `default_layout_profile()` in `EndcapBacklitMultitier`, `ProductOnShelves`,
  `ProductCounter` and `GraphicPanelDisplay`. Do NOT pass `product_label` (stays
  `display_name`, U1).
- Add the `ReportingPolicy` import to each of the four modules.
- Rename `test_non_ink_wall_result_unchanged` → `test_non_ink_wall_labels_unchanged_with_presence`
  in `test_ink_wall.py` and replace its two `== []` assertions with positive presence
  assertions; keep the `expected_products` (display-name labels) assertion unchanged.

**NOT in scope**: `InkWall`, `EndcapNoShelvesPromotional`, `ReportingPolicy` defaults,
`presence.py`, `compare.py`, `plan.py`, the handler; the new test module (TASK-4207);
docs (TASK-4208).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py` | MODIFY | import + `reporting=` kwarg |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` | MODIFY | import + `reporting=` kwarg |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py` | MODIFY | import + `reporting=` kwarg |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py` | MODIFY | import + `reporting=` kwarg |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py` | MODIFY | rename + positive assertions in the non-ink-wall test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# inside planogram/types/*.py (relative imports, as the sibling modules do)
from ..comparison.definition import ReportingPolicy   # verified: types/ink_wall.py:14 ; class at comparison/definition.py:49
from ..comparison.definition import SlotsDefinition   # verified: types/product_on_shelves.py:15 (extend THIS line)
# tests/planogram_cycle/test_ink_wall.py already imports FacingStatus from contracts (test_ink_wall.py:22-36, used at :533)
```

### Existing Signatures to Use
```python
# planogram/comparison/definition.py:49
class ReportingPolicy(BaseModel):            # extra="forbid"
    product_label: Literal["display_name", "product"] = "display_name"   # :54
    slot_presence: bool = False                                          # :55
    misplaced_min_confidence: float = 0.9                                # :56

# planogram/layout.py:99
class LayoutProfile(BaseModel):
    reporting: ReportingPolicy = Field(default_factory=ReportingPolicy)

# pattern — planogram/types/ink_wall.py:79-80
            references=ReferencePolicy(enabled=False),
            reporting=ReportingPolicy(product_label="product", slot_presence=True),

# planogram/types/product_on_shelves.py:119-127 — compare() → _ensure_layout(ctx): sets ctx.layout from
#   resolve_layout_profile(self.default_layout_profile(), ...) when ctx.layout is None
# planogram/comparison/presence.py:42 build_slot_presence → one SlotPresence per occupied-expected
#   (shelf_id, position or slot); found True for MATCH/VARIANT_UNRESOLVED/INFERRED_PRESENT,
#   False for MISMATCH/EMPTY, None for NOT_VISIBLE/NOT_ASSESSED/CONFLICT
# tests/planogram_cycle/test_ink_wall.py:46  UNDESCRIBED ; :74 _ctx(definition) (layout=None) ;
#   :129 synthetic_slots_definition (3 shelves x 8 facings) ; :544-605 test_non_ink_wall_result_unchanged
```

### Does NOT Exist
- ~~`LayoutProfile(slot_presence=...)`~~ — not a top-level field; it lives under `reporting=`.
- ~~`parrot_pipelines.planogram.comparison.ReportingPolicy`~~ — not re-exported by `comparison/__init__.py`.
- ~~`ComplianceResult.products_found`~~ — presence lives on `ComparisonResult`.
- ~~`AbstractPlanogramType.reporting`~~ — no class attribute; the hook is `default_layout_profile()`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#ReportingPolicy",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py#LayoutProfile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py#EndcapBacklitMultitier.default_layout_profile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves.default_layout_profile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py#ProductCounter.default_layout_profile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py#GraphicPanelDisplay.default_layout_profile",
    "sym:packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py#test_non_ink_wall_result_unchanged"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Each `LayoutProfile(...)` call stays byte-identical except for the one added kwarg.
- `product_label` is NOT passed — the default `display_name` keeps `expected_products` /
  `found_products` labels unchanged (spec G4).
- Imports in alphabetical module order: `..comparison.definition` sorts before `..contracts`
  and `..layout`; place the new line accordingly (no isort step exists; match the file).

---

## Implementation Blueprint

### Steps (in order)
1. Add the import and the kwarg in the four type modules — *why*: the type profile is the
   only per-type hook (spec §2 Overview item 1).
2. Run `test_ink_wall.py::test_non_ink_wall_result_unchanged` once and observe it fail —
   *why*: confirms `_ensure_layout` now resolves `slot_presence=True` for `product_on_shelves`.
3. Rename and rewrite the test assertions — *why*: the old contract ("other types → `[]`")
   is reversed by FEAT-648.
4. Run the Validation Commands.

### `.../types/endcap_backlit_multitier.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from ..layout import LayoutProfile, resolve_layout_profile' — line 25)
# BEFORE — insert above `from ..layout import LayoutProfile, resolve_layout_profile` (verified: :25)
#   NOTE: `from ..contracts import (` starts at :16, so put the new line ABOVE :16 to keep
#   `..comparison` < `..contracts` ordering.
from ..comparison.definition import ReportingPolicy

# occurrences: 1 (verified: grep -c '            required_descriptor_fields=\[\],' — line 172)
# AFTER — insert below `            required_descriptor_fields=[],` (verified: :172)
            reporting=ReportingPolicy(slot_presence=True),
```
**Why**: G1/G3 — opt-in by profile; `tiered_shelves=True` definitions have shelves, so
`build_slot_presence` produces entries.

### `.../types/product_on_shelves.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from ..comparison.definition import SlotsDefinition' — line 15)
# REPLACE line 15 with:
from ..comparison.definition import ReportingPolicy, SlotsDefinition

# occurrences: 1 (verified: grep -c '            required_descriptor_fields=\[\],' — line 116)
# AFTER — insert below `            required_descriptor_fields=[],` (verified: :116)
            reporting=ReportingPolicy(slot_presence=True),
```
**Why**: same; the module already imports from `..comparison.definition`.

### `.../types/product_counter.py` (MODIFY)
```python
# BEFORE — insert above `from ..contracts import (` (verified: :15; `from ..layout import LayoutProfile` is :23, 1 occurrence)
from ..comparison.definition import ReportingPolicy

# occurrences: 1 (verified: grep -c '            required_descriptor_fields=\[\],' — line 102)
# AFTER — insert below `            required_descriptor_fields=[],` (verified: :102)
            reporting=ReportingPolicy(slot_presence=True),
```

### `.../types/graphic_panel_display.py` (MODIFY)
```python
# BEFORE — insert above `from ..contracts import (` (verified: :15; `from ..layout import LayoutProfile` is :23, 1 occurrence)
from ..comparison.definition import ReportingPolicy

# occurrences: 1 (verified: grep -c '            min_usable_shapes=1,' — line 81, last kwarg of the call)
# AFTER — insert below `            min_usable_shapes=1,` (verified: :81)
            reporting=ReportingPolicy(slot_presence=True),
```
**Why**: zone-heavy type; if a row's definition is zone-only the result is `[]` — inert, never wrong (spec §8 open question).

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def test_non_ink_wall_result_unchanged(' — line 544)
# RENAME the function at :544:
async def test_non_ink_wall_labels_unchanged_with_presence(
# REPLACE its docstring with:
    """A non-ink-wall comparison keeps display-name labels and now reports slot presence (FEAT-648)."""
# REPLACE the two assertions (currently at :600-601):
#     assert comparison.products_found == []
#     assert assembled["products_found"] == []
# with:
    assert assembled["products_found"] == comparison.products_found
    assert len(comparison.products_found) == 24  # 3 shelves x 8 occupied-expected positions
    read = [p for p in comparison.products_found if p.found is True]
    # FILL IN: assert the two identified slots (shelf 1, slots 1 and 2) are the found ones, with
    #   model == f"ACME-1-{slot}" and status FacingStatus.MATCH — bounded by spec AC-3; derive the exact
    #   shelf_id from the synthetic definition (_definition_dict, :99), do not hard-code a guess.
    # FILL IN: assert every other entry has found is None (no deciding view) — bounded by spec §7
    #   "Tri-state found"; if registration maps differently, assert what build_slot_presence yields and
    #   explain it in the Completion Note — never weaken to `found is not True`.
# KEEP unchanged: the expected_products assertion that follows (display-name labels, G4).
```
**Why**: the rename makes the FEAT-645 reversal visible in the diff (spec §7 risk 1).

### FILL IN checklist
- [ ] `test_ink_wall.py::test_non_ink_wall_labels_unchanged_with_presence` — exact found/None split; bounded by AC-3 and §7 tri-state.

---

## Acceptance Criteria

- [ ] The four `default_layout_profile().reporting` equal `ReportingPolicy(slot_presence=True)`; every other field unchanged.
- [ ] `InkWall` and `EndcapNoShelvesPromotional` untouched; `ReportingPolicy().slot_presence is False`.
- [ ] `test_non_ink_wall_result_unchanged` no longer exists; its replacement passes with non-empty presence and unchanged labels.
- [ ] `ruff check` clean on the five files.

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_slot_presence.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_shelf_types.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_panel_types.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_compliance_characterization.py -q`
- `pytest packages/ai-parrot-pipelines/tests/test_planogram_types.py -q`

(Inside the worktree prefix with `PYTHONPATH=packages/ai-parrot-pipelines/src`.)

---

## Test Specification

```python
# test_ink_wall.py — renamed test (see blueprint). Assertions shape:
assert len(comparison.products_found) == 24
assert {(p.model, p.status) for p in comparison.products_found if p.found} == {
    ("ACME-1-1", FacingStatus.MATCH), ("ACME-1-2", FacingStatus.MATCH)}
assert all(p.found is None for p in comparison.products_found if p.model not in {"ACME-1-1", "ACME-1-2"})
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug products-found-endcap --feature-id FEAT-648`).
2. Read the spec; verify the Codebase Contract (re-run the `grep -c` anchors).
3. Mark `in-progress` in `sdd/tasks/index/products-found-endcap.json`, implement from the blueprint, complete every `FILL IN`.
4. Run the Validation Commands; commit only the five files; close with `scripts/sdd/close_task.sh TASK-4206 products-found-endcap verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: Spec §3 places the `test_ink_wall.py` rewrite in Module 2; it lives here because the opt-in alone breaks the old test (see Context).
