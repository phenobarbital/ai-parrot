# TASK-3346: Pass 2 — closed-set verification with distractors

**Feature**: FEAT-565 — New Planogram Compliance Algorithm
**Spec**: `sdd/specs/new-planogram-compliance-algo.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3338, TASK-3342, TASK-3344
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 9** / §2 stage 7. After pass 1 (open-set, `examples/planogram/plancheck/identify.py`,
TASK-3344) and registration (`plancheck/registration.py`, TASK-3345), some slots are
*registered and occupied but unread*. The request's step 3 asks to infer those from the
planogram. Pass 2 does it **with visual confirmation instead of blind inference**: per row, the
model sees the strip again and, for each such slot, must choose between the expected product,
2–3 distractors, `other`, or `cannot_tell`, quoting visible evidence.

Its confirmation bias is contained by design: distractors make it a discrimination task,
evidence is mandatory, option order is deterministic and not expected-first, and everything it
confirms is tagged `verified_by_expectation` — which scoring (TASK-3347) excludes from the strict score.

---

## Scope

- Implement `VERIFY_PROMPT_VERSION`, `pick_distractors()`, `option_order()`, `verify_rows()` in
  `examples/planogram/plancheck/verify.py` exactly as in the spec skeleton.
- Build the pass-2 prompt (target slots + options shown by catalog `display_name`, answer by SKU).
- Apply outcomes to the observations **in place**; return error strings.
- Write `examples/planogram/tests/test_plancheck_verify.py` (spec §4 M9 tests + outcome tests).

**NOT in scope**: deciding whether pass 2 runs (`Settings.verify_pass` auto/on/off is resolved in
`examples/planogram/plancheck/pipeline.py`, TASK-3349); rendering strips (`render_strip` is imported from
`examples/planogram/plancheck/identify.py`, TASK-3344); the vision call/caching/retry
(`examples/planogram/plancheck/vision.py`, TASK-3342); statuses and credits (TASK-3347); any model change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/plancheck/verify.py` | CREATE | Distractor policy, option order, pass-2 orchestration |
| `examples/planogram/tests/test_plancheck_verify.py` | CREATE | Unit tests with `fake_backend` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
import asyncio, hashlib, json, logging       # stdlib
from typing import TYPE_CHECKING
import numpy as np                           # installed: numpy 2.4.6 (verified in spec §6)
import pytest                                # tests; coroutines need @pytest.mark.asyncio (no asyncio_mode=auto)
```

#### Created by dependency tasks (exist only after they land)
```python
# examples/planogram/plancheck/models.py — TASK-3337 (part 1) / TASK-3338 (part 2)
from plancheck.models import (Catalog, PlanogramFacing, PlanogramRef, RowVerification,
                              VerificationReading, Slot, SlotReading, SlotObservation)
# examples/planogram/plancheck/identify.py — TASK-3344
from plancheck.identify import render_strip
#   def render_strip(image: np.ndarray, slots: list[Slot], *, marks: bool = True) -> tuple[bytes, Box]
#   → (PNG bytes of one row strip with numbered outlines; mark number == slot.index, strip box)
# examples/planogram/plancheck/vision.py — TASK-3342  (import ONLY under TYPE_CHECKING)
from plancheck.vision import VisionBackend
#   async def ask(self, prompt: str, images: Sequence[bytes], schema: type[T], *, stage: str, prompt_version: str) -> T
```
`examples/planogram/tests/conftest.py` (TASK-3337) provides fixtures `shelf_image`, `mini_planogram`,
`mini_catalog`, `fake_backend` (a `FakeBackend`: `.queue: dict[str, list]` keyed by stage, `.calls: list[dict]`
with keys `stage`, `prompt`, `n_images`, `schema`; a queued `Exception` instance is raised, a callable is
called with `(prompt, images)`; empty queue → `AssertionError`).

### Existing Signatures to Use
Nothing in the repository today. Model fields used (fixed by spec §3 Module 1 — re-verify in
`examples/planogram/plancheck/models.py`):
```python
class VerificationReading: slot_id: str; choice: str; evidence: str = ""   # choice: offered SKU | "other" | "cannot_tell"
class RowVerification:     slots: list[VerificationReading]
class SlotObservation:     slot: Slot; reading: SlotReading | None; resolved_sku: str | None
                           candidate_skus: list[str]; resolution: Resolution; facing_id: str | None; issues: list[str]
class PlanogramFacing:     facing_id: str; shelf: int; slot: int; sku: str; brand: str | None; identity_required: bool
class PlanogramRef:        facings: list[PlanogramFacing]; def shelf(self, number: int) -> list[PlanogramFacing]
class CatalogItem:         sku: str; brand: str; display_name: str; family: str | None; xl: bool; colors: list[str]; pack: int
class Catalog:             items: list[CatalogItem]; def by_sku(self, sku: str) -> CatalogItem | None
```

### Does NOT Exist
- ~~`plancheck.vision.VisionError` in tests/conftest~~ — fakes raise `RuntimeError`; treat **any** `Exception` from `backend.ask` as a row failure.
- ~~a `marks` parameter on `verify_rows`~~ — the signature is fixed by the spec; call `render_strip(image, row_slots)` with its default.
- ~~direct provider SDK use (`google.genai`, `openai`, `anthropic`, `client.client`, `chat.completions`)~~ — forbidden everywhere (§8 Q7); only `backend.ask`.
- ~~`import parrot` in this module~~ — not needed; `VisionBackend` is a type-only import.
- ~~`random.shuffle` / unseeded randomness~~ — option order must be reproducible across runs and processes (`hash()` is salted — do not use it).
- ~~`SlotObservation.row` / `.image_id`~~ — use `obs.slot.row` / `obs.slot.image_id`.
- ~~real part numbers from `planogram_page1.json` in tests or prompts examples~~ — public repo: synthetic data only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/plancheck/verify.py",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/tests/test_plancheck_verify.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Decided behaviour (spec §2 stage 7 + §3 Module 9 — do not re-decide)

**Targets** — an observation is verified only when ALL hold:
`obs.facing_id is not None` · `obs.reading is not None and obs.reading.occupancy == "occupied"` ·
`obs.resolution in {"unresolved", "ambiguous"}` · the facing has `identity_required == True` ·
`catalog.by_sku(facing.sku) is not None` (expected SKU present in the catalog).

**Distractors** (`pick_distractors`) — same brand as the expected catalog item only; order of preference:
1. same `family`, other variant (different `xl` / `colors` / `pack`);
2. SKUs of shelf neighbours within ±2 `slot` of the facing on the same shelf (same brand, in the catalog);
never the expected SKU, no duplicates, at most `n`, may be fewer (even empty). Deterministic order:
within each tier sort by SKU.

**Option order** (`option_order`) — deterministic permutation seeded by `sha256(slot_id)`:
sort the SKUs by `sha256(f"{slot_id}|{sku}")` hex digest. Same input set (any order) → same output;
the expected SKU is therefore not systematically first.

**One call per (image, row)** that has ≥ 1 target: strip = `render_strip(image, all slots of that row)`
(the whole row gives the model neighbour context; mark number = `slot.index`), prompt lists ONLY the
target slots, each with its options as `{"sku", "name"}` (`name` = catalog `display_name`) in
`option_order`, plus the literal choices `"other"` and `"cannot_tell"`. The prompt must demand
`evidence` (visible text/feature) for every SKU choice and must say the answer is the **sku** string.
Call: `await backend.ask(prompt, [png], RowVerification, stage="verify", prompt_version=VERIFY_PROMPT_VERSION)`
inside `async with semaphore:`; rows run concurrently via `asyncio.gather`.

**Outcomes** (evidence present = `reading.evidence.strip() != ""`):
| Model answer | Effect on the observation |
|---|---|
| expected SKU + evidence | `resolved_sku = expected`, `resolution = "verified_by_expectation"` |
| expected SKU, no evidence | `resolution = "inferred"`, `resolved_sku` stays `None`, issue `"verify_no_evidence"` |
| a distractor SKU + evidence | `resolved_sku = that SKU`, `resolution = "verified_by_expectation"` |
| a distractor SKU, no evidence | unchanged, issue `"verify_no_evidence"` (evidence is mandatory — spec §2 stage 7) |
| `"other"` / `"cannot_tell"` | unchanged |
| a choice not among the offered options | unchanged, issue `"verify_invalid_choice"` |
| slot id not requested | dropped; one error string `verify:<image_id>:row<row>: unknown slot id <id>` |
| requested slot missing from the answer | unchanged |
| `backend.ask` raises anything | every observation of that row unchanged; one error string `verify:<image_id>:row<row>: <exc>` |

`candidate_skus` is never modified. Non-target observations are never touched.

### Key Constraints
- Async; no blocking work in the coroutine besides `render_strip` — run it with `await asyncio.to_thread(render_strip, image, row_slots)` (cv2 encode is CPU-bound; spec §7).
- `VERIFY_PROMPT_VERSION = "verify-v1"`; bump it whenever the prompt text changes (it is part of the cache key in TASK-3342).
- `logging.getLogger(__name__)`, no `print`; strict type hints; Google-style docstrings; black 120.
- The prompt is the implementer's wording; the **schema, options, stage name and outcome table are not**.

### References in Codebase
- `sdd/specs/new-planogram-compliance-algo.spec.md` §2 stage 7, §3 Module 9, §7 "Confirmation bias of pass 2".
- `examples/planogram/plancheck/identify.py` (TASK-3344) — follow its prompt/JSON style for consistency.

---

## Implementation Blueprint

### Steps (in order)
1. Confirm `render_strip` exists in `examples/planogram/plancheck/identify.py` and `RowVerification` in `examples/planogram/plancheck/models.py` — *why*: both come from dependency tasks; never re-implement them here.
2. Create `verify.py` from the block below — *why*: signatures and `option_order` are fixed; selection, prompt and outcome application are yours.
3. Implement `pick_distractors` tier by tier with sorted output — *why*: determinism is an acceptance criterion and the cache key depends on the prompt text.
4. Implement `_targets`, `_build_verify_prompt`, then `verify_rows` with one task per (image, row) — *why*: a failing row must not affect the others.
5. Apply outcomes strictly per the outcome table — *why*: scoring (TASK-3347) keys strict/lenient credit on `resolution`.
6. Write tests, run the validation command, `ruff check` both files.

### `examples/planogram/plancheck/verify.py` (CREATE)
```python
"""Pass 2 — closed-set verification with distractors (FEAT-565, Module 9)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import TYPE_CHECKING

import numpy as np

from plancheck.identify import render_strip
from plancheck.models import Catalog, PlanogramFacing, PlanogramRef, RowVerification, SlotObservation

if TYPE_CHECKING:
    from plancheck.vision import VisionBackend

logger = logging.getLogger(__name__)

VERIFY_PROMPT_VERSION = "verify-v1"
STAGE = "verify"
CHOICE_OTHER = "other"
CHOICE_CANNOT_TELL = "cannot_tell"


def pick_distractors(facing: PlanogramFacing, planogram: PlanogramRef, catalog: Catalog, n: int = 3) -> list[str]:
    """Pick up to ``n`` same-brand distractor SKUs for ``facing`` (never the expected SKU).

    Tier 1: same family, other variant. Tier 2: shelf neighbours within ±2 slots. Sorted by SKU
    inside each tier; may return fewer than ``n`` (or none).
    """
    # FILL IN: tier 1 then tier 2, de-duplicated, same brand as catalog.by_sku(facing.sku) —
    # bounded by "Distractors" notes; return [] when the expected SKU is not in the catalog.
    raise NotImplementedError


def option_order(slot_id: str, skus: list[str]) -> list[str]:
    """Deterministic shuffle seeded by sha256(slot_id) — the expected SKU is not always first."""
    return sorted(set(skus), key=lambda sku: hashlib.sha256(f"{slot_id}|{sku}".encode("utf-8")).hexdigest())


def _targets(observations: list[SlotObservation], planogram: PlanogramRef, catalog: Catalog
             ) -> dict[tuple[str, int], list[tuple[SlotObservation, PlanogramFacing]]]:
    """Group verifiable observations by ``(image_id, row)`` with their expected facing."""
    # FILL IN: apply the five target conditions — bounded by "Targets" notes; keys sorted for determinism.
    raise NotImplementedError


def _build_verify_prompt(targets: list[tuple[SlotObservation, PlanogramFacing]], planogram: PlanogramRef,
                         catalog: Catalog) -> tuple[str, dict[str, list[str]]]:
    """Return (prompt, slot_id → offered SKUs). Options carry ``sku`` + catalog ``display_name``."""
    # FILL IN: instructions (answer per listed slot only; choice = one offered sku | "other" | "cannot_tell";
    # evidence mandatory) + json.dumps of [{"slot_id", "mark": slot.index, "options": [{"sku","name"}]}]
    # with options in option_order(slot_id, [expected, *distractors]) — bounded by "One call per row".
    raise NotImplementedError


async def verify_rows(image: np.ndarray, observations: list[SlotObservation], planogram: PlanogramRef,
                      catalog: Catalog, backend: VisionBackend, semaphore: asyncio.Semaphore) -> list[str]:
    """Verify registered, occupied, unresolved slots of ONE image against their expectation.

    Mutates ``observations`` in place per the outcome table of the task; returns error strings.
    Any exception from ``backend.ask`` fails only its row.
    """
    # FILL IN: for each (image_id, row) group: row_slots = every obs.slot of that image+row sorted by index;
    #   png, _ = await asyncio.to_thread(render_strip, image, row_slots); async with semaphore: backend.ask(...,
    #   RowVerification, stage=STAGE, prompt_version=VERIFY_PROMPT_VERSION); gather rows; apply outcomes —
    #   bounded by the outcome table.
    raise NotImplementedError
```
**Why this shape**: `option_order` is complete because its rule is decided (sha256-keyed sort — no
`random`, no salted `hash()`), and `set(skus)` makes it independent of input order. `VisionBackend`
is type-only so this module (and its tests) never import `parrot`. Helper names `_targets` /
`_build_verify_prompt` may be adjusted; the four public names and their signatures may not.

### `examples/planogram/tests/test_plancheck_verify.py` (CREATE)
```python
"""Unit tests for plancheck.verify (FEAT-565, spec §4 — M9)."""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from plancheck.models import (Catalog, PlanogramRef, RowVerification, Slot, SlotObservation, SlotReading,
                              VerificationReading)
from plancheck.verify import option_order, pick_distractors, verify_rows


def _occupied_unresolved(image_id: str, row: int, index: int, facing_id: str) -> SlotObservation:
    """Registered, occupied, unresolved observation placed over the conftest shelf_image grid."""
    # FILL IN: Slot box from conftest constants (TAG_X0, TAG_DX, TAG_ROWS_Y) so render_strip gets a valid box.
    raise NotImplementedError


def test_distractors_exclude_expected(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: for AC-11 (std black, family 10): result excludes "AC-11", all same brand, the same-family
    #   variants (AC-12 XL, AC-13 tri-color) come first, len <= 3; CLOSEOUT/unknown SKU → [].
    raise NotImplementedError


def test_option_order_deterministic() -> None:
    # FILL IN: same slot_id + permuted input → identical output; over several slot_ids the expected SKU
    #   is not always at index 0.
    raise NotImplementedError


@pytest.mark.asyncio
async def test_verify_expected_with_evidence(shelf_image: np.ndarray, mini_planogram, mini_catalog, fake_backend) -> None:
    # FILL IN: queue["verify"] = [RowVerification(...expected sku, evidence="reads 10 Black")] →
    #   resolution == "verified_by_expectation", resolved_sku == expected; one call, stage "verify", 1 image.
    raise NotImplementedError


@pytest.mark.asyncio
async def test_verify_without_evidence_is_inferred(shelf_image, mini_planogram, mini_catalog, fake_backend) -> None:
    # FILL IN: expected sku + evidence "" → resolution == "inferred", resolved_sku is None, issue recorded.
    raise NotImplementedError


@pytest.mark.asyncio
async def test_verify_distractor_other_and_invalid(shelf_image, mini_planogram, mini_catalog, fake_backend) -> None:
    # FILL IN: distractor+evidence → resolved to distractor/verified_by_expectation; "cannot_tell" → unchanged;
    #   unknown sku → unchanged + "verify_invalid_choice"; foreign slot_id → error string.
    raise NotImplementedError


@pytest.mark.asyncio
async def test_verify_row_failure_leaves_observations(shelf_image, mini_planogram, mini_catalog, fake_backend) -> None:
    # FILL IN: queue["verify"] = [RuntimeError("boom")] → returns 1 error string, observations unchanged.
    raise NotImplementedError


@pytest.mark.asyncio
async def test_verify_skips_non_targets(shelf_image, mini_planogram, mini_catalog, fake_backend) -> None:
    # FILL IN: direct / empty / unregistered / CLOSEOUT observations only → zero backend calls (empty queue ok).
    raise NotImplementedError
```
**Why this shape**: covers the three spec §4 M9 tests plus every row of the outcome table. All
tests use `fake_backend` from `examples/planogram/tests/conftest.py` (TASK-3337); semaphores are
`asyncio.Semaphore(2)` created inside each test.

### FILL IN checklist
- [ ] `verify.py::pick_distractors` — two tiers, same brand, sorted, never expected; bounded by "Distractors"
- [ ] `verify.py::_targets` — five target conditions; bounded by "Targets"
- [ ] `verify.py::_build_verify_prompt` — wording yours, structure fixed; bounded by "One call per row"
- [ ] `verify.py::verify_rows` — per-row tasks, `to_thread` strip, semaphore, outcome table, error strings
- [ ] `_occupied_unresolved` helper + seven test bodies — bounded by the comment in each stub

---

## Acceptance Criteria

- [ ] Public API is exactly `VERIFY_PROMPT_VERSION`, `pick_distractors`, `option_order`, `verify_rows` with the spec signatures.
- [ ] Only registered + occupied + `unresolved`/`ambiguous` + identity-required + in-catalog slots are sent; no target → no backend call.
- [ ] One `backend.ask` per (image, row) with targets: `stage="verify"`, schema `RowVerification`, exactly one image (the row strip).
- [ ] Every row of the outcome table holds; `candidate_skus` and non-target observations are never modified.
- [ ] A row failure returns one error string and leaves that row's observations unchanged; other rows still complete.
- [ ] `option_order` is reproducible across processes (no `random`, no `hash()`).
- [ ] No `parrot`/provider-SDK import, no `print`.
- [ ] `pytest examples/planogram/tests/test_plancheck_verify.py -q` passes; `ruff check` on both files is clean.

---

## Validation Commands

- `pytest examples/planogram/tests/test_plancheck_verify.py -q`

---

## Test Specification

See the test blueprint block above; the seven functions are the required minimum. Synthetic SKUs
from the conftest fixtures only (`AC-<shelf><slot>`, `BO-<shelf><slot>`).

---

## Agent Instructions

1. **Read the spec** §2 stage 7, §3 Module 9, §7.
2. **Check dependencies** — TASK-3338, TASK-3342, TASK-3344 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm `render_strip`'s signature in `examples/planogram/plancheck/identify.py` and the model fields in `examples/planogram/plancheck/models.py`; update this contract first if they differ.
4. **Update status** in `sdd/tasks/index/new-planogram-compliance-algo.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `# FILL IN:`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3346-verify.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
