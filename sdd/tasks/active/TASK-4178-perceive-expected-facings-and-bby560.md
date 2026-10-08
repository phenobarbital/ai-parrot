# TASK-4178: Wire expected facings into perception + BBY560 integration tests

**Feature**: FEAT-646 — Ink-wall slot recovery and completeness policy
**Spec**: `sdd/specs/ink-wall-registration-and-completeness.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4174, TASK-4176, TASK-4177
**Assigned-to**: unassigned

---

## Context

Spec §2 Part A (perception side) and §4 Integration Tests. TASK-4176 gave `build_slots()` an
`expected_facings` keyword and TASK-4174 added `LayoutProfile.definition_gap_fill` (True for ink walls). This
task adds `_expected_facings(ctx)` — sibling of `_expected_rows(ctx)` — and passes it to `build_slots()` from
`rebuild_geometry()` (the shared geometry tail that `perceive_image()` and the LLM fallback both call) when
the profile opts in. It then adds the two CV-only integration tests on the BBY560 example image, which also
exercise TASK-4177's membership change.

---

## Scope

- Add `_expected_facings(ctx) -> Optional[List[int]]` in `stages/perceive.py`: facing count of every definition
  shelf that carries facings, top→bottom (definition order); `None` without a definition or without such shelves.
- In `rebuild_geometry()`, pass `expected_facings=_expected_facings(ctx) if profile.definition_gap_fill else None`.
- New test module `test_ink_wall_bby560.py`: `_expected_facings` unit tests, plus
  `test_ink_wall_bby560_full_height_slots` and `test_ink_wall_bby560_membership_edge_tag` (CV only, no LLM),
  skipped when the example image is absent (it is not tracked in git).

**NOT in scope**: `build_slots` internals (TASK-4176); membership internals (TASK-4177); completeness in scoring
(TASK-4175); AC7 (live-LLM manual check — not automated).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/perceive.py` | MODIFY | `_expected_facings` + pass it to `build_slots` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall_bby560.py` | CREATE | unit + BBY560 integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# stages/perceive.py:6 already has: from typing import Dict, List, Optional, Sequence, Tuple
from parrot_pipelines.planogram.stages.perceive import perceive_image  # perceive.py:296
from parrot_pipelines.planogram.stages import perceive as perceive_module  # for _expected_facings in tests
from parrot_pipelines.planogram.comparison.definition import load_slots_definition  # used by test_ink_wall.py:21
from parrot_pipelines.planogram.contracts import CreditPolicy, CycleContext, EvidenceWeights, FixtureMembership, ShapeKind
from parrot_pipelines.planogram.types import InkWall  # test_ink_wall.py:39
from parrot_pipelines.planogram.layout import LayoutProfile  # layout.py:66
```

### Existing Signatures to Use
```python
# stages/perceive.py
def _profile(ctx: CycleContext) -> LayoutProfile                         # :46 (raises if ctx.layout is None)
def _expected_rows(ctx: CycleContext) -> Optional[int]:                  # :53
    shelves = getattr(ctx.definition, "shelves", None) or []
    return sum(1 for shelf in shelves if shelf.facings) or None
async def rebuild_geometry(image, shapes, image_id, ctx, *, detection_source) -> PerceptionResult  # :231
#   slots = build_slots(rows, size, image_id=..., rule=profile.anchor_rule, fill_gaps=profile.fill_gaps,
#       untagged_bottom_row=profile.untagged_bottom_row, max_rows=_expected_rows(ctx),)   # :246-254, max_rows at :253
#   others = assign_membership(others, zones, size)                      # membership assigned after slots
async def perceive_image(image, image_id, ctx) -> PerceptionResult      # :296 (cv path: _propose → rebuild_geometry)

# perception/slots.py (after TASK-4176)
def build_slots(..., max_rows: Optional[int] = None, expected_facings: Optional[Sequence[int]] = None) -> List[Slot]
def candidate_shape_id(image_id, candidate) -> str  # :35 → "<image_id>:<profile>:<x1>-<y1>-<x2>-<y2>"

# layout.py (after TASK-4174)
class LayoutProfile: definition_gap_fill: bool = False

# comparison/definition.py
class ShelfDefinition: shelf_id; shelf_number; level; ordered; facings: List[FacingDefinition]  # :128
class SlotsDefinition: shelves: List[ShelfDefinition]                                          # :159

# types/ink_wall.py
class InkWall: default_layout_profile() -> LayoutProfile  # :64
#   _registrable_slots(self, perception, idents) -> List[Slot]  # :136 (drops OFF_FIXTURE-anchored slots)

# tests/planogram_cycle/test_ink_wall.py patterns to copy (do NOT import from another test module)
class _InlineExecutor: async def run(self, fn, *args): return fn(*args)   # :49
class _NoOcr: available = False                                          # :62
def _ctx(definition=None) -> CycleContext                                # :74 (vision=None, executor, ocr, definition, credit_policy, evidence_weights)
# pytest.ini: asyncio_mode = auto — plain `async def test_...` works
```

### Does NOT Exist
- ~~`_expected_facings`~~ — created here
- ~~`perceive_image(..., expected_facings=...)`~~ — perception reads it from `ctx`; signatures unchanged
- ~~a tracked BBY560 image~~ — `examples/planogram/images/epson_inkwall_config/2026-09-04-Kip-Kerrick-Best-Buy-560.jpeg`
  exists only locally; the integration tests MUST `pytest.skip` when it is missing
- ~~shape id `price_tag:205-2416-313-2469`~~ alone — the real id is prefixed by the image id: `f"{image_id}:price_tag:205-2416-313-2469"`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/perceive.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall_bby560.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/perceive.py#_expected_rows",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/perceive.py#rebuild_geometry",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/perceive.py#perceive_image",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#InkWall.default_layout_profile"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Shelves without facings are skipped, exactly like `_expected_rows` — so `len(_expected_facings(ctx)) ==
  _expected_rows(ctx)` whenever both are not `None`.
- Non-ink types keep `definition_gap_fill=False` ⇒ `expected_facings=None` ⇒ identical slots (AC3).
- Integration tests are CV-only: `perception_mode="cv"` (ink default), `ctx.vision=None`, inline executor.
- The CV path is deterministic, so exact counts are stable across runs on the same image.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_expected_facings` directly below `_expected_rows` — *why*: same data source, same skip rule.
2. Pass `expected_facings` in the `build_slots` call of `rebuild_geometry` — *why*: covers the CV path and the LLM-detector fallback with one edit.
3. Create the test module; run the Validation Commands (with the image present locally, the BBY560 tests must run, not skip).

### `.../stages/perceive.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _shape_from_candidate(' stages/perceive.py)
# BEFORE — insert above `def _shape_from_candidate(` (verified: stages/perceive.py:59), i.e. right after _expected_rows
def _expected_facings(ctx: CycleContext) -> Optional[List[int]]:
    """Facing count of every definition shelf that carries facings, top→bottom; ``None`` without a definition."""
    shelves = getattr(ctx.definition, "shelves", None) or []
    counts = [len(shelf.facings) for shelf in shelves if shelf.facings]
    return counts or None


# occurrences: 1 (verified: grep -c '        max_rows=_expected_rows(ctx),' stages/perceive.py)
# AFTER — insert below `        max_rows=_expected_rows(ctx),` (verified: stages/perceive.py:253)
        expected_facings=_expected_facings(ctx) if profile.definition_gap_fill else None,
```
**Why**: spec §2 Part A — the layout opts in; `build_slots` owns the full-height guard.

### `tests/planogram_cycle/test_ink_wall_bby560.py` (CREATE)
```python
"""FEAT-646: definition-aware gap fill and multi-bay membership on the BBY560 ink wall (CV only, no LLM)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from parrot_pipelines.planogram.comparison.definition import load_slots_definition
from parrot_pipelines.planogram.contracts import CreditPolicy, CycleContext, EvidenceWeights, FixtureMembership
from parrot_pipelines.planogram.stages import perceive as perceive_module
from parrot_pipelines.planogram.stages.perceive import perceive_image
from parrot_pipelines.planogram.types import InkWall

_IMAGE = (
    Path(__file__).resolve().parents[4]
    / "examples" / "planogram" / "images" / "epson_inkwall_config" / "2026-09-04-Kip-Kerrick-Best-Buy-560.jpeg"
)
EXPECTED_FACINGS = [17, 18, 18, 18, 18, 15]
EDGE_TAG = "price_tag:205-2416-313-2469"


class _InlineExecutor:
    """Runs CPU helpers inline."""

    max_workers = 1

    async def run(self, fn, *args):
        return fn(*args)

    async def aclose(self) -> None:
        return None


class _NoOcr:
    available = False


def _definition():
    """Six shelves with the BBY560 facing counts (ids only; identities are irrelevant to perception)."""
    # FILL IN: build {"version": "1", "shelves": [...]} with shelf_k having EXPECTED_FACINGS[k] facings
    #   (facing_id/shelf_id/slot/product/brand like test_ink_wall._definition_dict) and load_slots_definition() it


def _ctx(definition, **profile_updates) -> CycleContext:
    layout = InkWall.default_layout_profile().model_copy(update=profile_updates)
    return CycleContext(
        vision=None,
        executor=_InlineExecutor(),
        ocr=_NoOcr(),
        definition=definition,
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
        layout=layout,
    )


def test_expected_facings_counts_shelves_with_facings():
    # FILL IN: SimpleNamespace(definition=SimpleNamespace(shelves=[...])) with an empty shelf in the middle ⇒ counts skip it;
    #   definition None ⇒ None; all shelves empty ⇒ None
    ...


@pytest.fixture
def bby560() -> Image.Image:
    if not _IMAGE.exists():
        pytest.skip("BBY560 example image is not available (examples/ images are not tracked)")
    return Image.open(_IMAGE).convert("RGB")


async def test_ink_wall_bby560_full_height_slots(bby560):
    # FILL IN: perceive_image(bby560, "img0", _ctx(_definition())) vs _ctx(_definition(), definition_gap_fill=False);
    #   row 5 has >= 15 slots with the fill; rows 0–4 slot lists identical between the two runs — bounded by AC1/AC3
    ...


async def test_ink_wall_bby560_membership_edge_tag(bby560):
    # FILL IN: f"img0:{EDGE_TAG}" is FixtureMembership.ON_FIXTURE with "row_block" evidence; row 5 slots whose anchor is
    #   not OFF_FIXTURE number 15 — bounded by AC8. Assert only these two facts: the pre-TASK-4177 membership map
    #   cannot be reproduced here, so "no other shape changes" is guarded by test_membership.py instead.
    ...
```
(Replace each `...` with the test body.)

### FILL IN checklist
- [ ] `_definition()` — six shelves with `EXPECTED_FACINGS`
- [ ] `test_expected_facings_counts_shelves_with_facings` — skip rule + None cases
- [ ] two BBY560 tests — bounded by AC1/AC3/AC8; must skip cleanly when the image is missing

---

## Acceptance Criteria

- [ ] `_expected_facings` returns facing counts top→bottom, skipping empty shelves; `None` without a definition
- [ ] Ink-wall perception passes `expected_facings`; any profile with `definition_gap_fill=False` produces identical slots (AC3)
- [ ] With the local image: row 5 ≥ 15 slots; rows 0–4 unchanged vs `definition_gap_fill=False`; the edge tag is `ON_FIXTURE` (`row_block`); row 5 keeps 15 registrable slots (AC1, AC8)
- [ ] Existing `test_ink_wall.py`, `test_shared_perception.py`, `test_rows_slots.py` pass; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall_bby560.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_perception.py -q`

---

## Test Specification

See the test module in the Implementation Blueprint (spec §4 Integration Tests).

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug ink-wall-registration-and-completeness --feature-id FEAT-646`); TASK-4174, TASK-4176 and TASK-4177 must be `done`.
2. Verify the Codebase Contract; set this task `in-progress` in the per-spec index.
3. Implement from the blueprint; run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`. The example image lives in the main
   checkout only — copy or symlink it into the worktree's `examples/` path to run the BBY560 tests (never commit it).
4. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4178 ink-wall-registration-and-completeness verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
