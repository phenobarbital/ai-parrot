# TASK-3430: Provider-neutral call sites — product_on_shelves, product_counter, endcap_no_shelves_promotional

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3429
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 6** (Provider-neutral call sites), goal **G11**. TASK-3429 added
`AbstractPlanogramType._vision_kwargs()` and converted the core sites. This task
applies the **same mechanical edit** to the three shelf-style type files:
`ProductOnShelves`, `ProductCounter`, `EndcapNoShelvesPromotional` — six
`ask_to_image` sites that today go through the Google-only
`self.pipeline.roi_client` with a hard-coded `model="gemini-3.5-flash"`.

No algorithm changes. The characterization tests of TASK-3422 / TASK-3423 /
TASK-3424 (ancestors through TASK-3429) must stay green.

---

## Scope

- Rewrite the **closed worklist** below (6 sites, 18 lines) with the fixed idiom.
- Update `_make_pipeline()` in `tests/pipelines/test_endcap_no_shelves.py` and
  `tests/pipelines/test_product_counter.py` so `pipeline.llm` is the same mock
  as `pipeline.roi_client` and `pipeline.resolved_backend` is set.
- Write `test_neutral_shelf_types.py`.

**NOT in scope**:
- `product_on_shelves.py:330` — `await self.pipeline.llm.detect_objects(` stays
  exactly as it is (it already uses the pipeline client; `detect_objects` has no
  `model` kwarg).
- `endcap_backlit_multitier.py`, `graphic_panel_display.py` (TASK-3431).
- Deleting `AbstractPipeline.roi_client` (TASK-3432).
- Any prompt, retry, `max_tokens`, `structured_output` or algorithm change.
- Migrating `ProductOnShelves` to the new cycle (later tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` | MODIFY | 2 sites: `_find_poster`, `_ocr_fact_tags` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py` | MODIFY | 2 sites: `compute_roi`, `detect_objects_roi` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py` | MODIFY | 2 sites: `compute_roi`, `detect_objects_roi` |
| `tests/pipelines/test_endcap_no_shelves.py` | MODIFY | `_make_pipeline()`: alias `llm`, set `resolved_backend` |
| `tests/pipelines/test_product_counter.py` | MODIFY | `_make_pipeline()`: alias `llm`, set `resolved_backend` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_shelf_types.py` | CREATE | tests for the six sites |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot_pipelines.planogram.types import (
    ProductOnShelves, ProductCounter, EndcapNoShelvesPromotional,
)                                                                   # planogram/types/__init__.py:2-16
from parrot.models.detections import Detections                     # packages/ai-parrot/src/parrot/models/detections.py:32
```

### Existing Signatures to Use
```python
# Created by TASK-3429 (dependency) — planogram/types/abstract.py
class AbstractPlanogramType(ABC):
    def _vision_kwargs(self, **extra: Any) -> Dict[str, Any]:
        """{"no_memory": True, **extra} plus "model" only when self.pipeline.resolved_backend.model is a non-empty str."""

# self.pipeline.llm            → the pipeline's resolved client (async context manager; abstract.py:26)
# self.pipeline.resolved_backend → set by AbstractPipeline (TASK-3427, ancestor)
# self.pipeline.roi_client     → STILL EXISTS after this task; must simply no longer be used here

# planogram/types/product_on_shelves.py
class ProductOnShelves(AbstractPlanogramType):                       # :35
    async def _detect_legacy(...)                                    # def :262   (site :330 — UNCHANGED)
    async def _find_poster(self, image, planogram, partial_prompt)   # def :801   (site :825-833)
    async def _ocr_fact_tags(self, identified_products, img, planogram_description, shelf_regions=None)  # def :1219 (site :1357-1364)
# planogram/types/product_counter.py
    async def compute_roi(self, img)                                 # def :67    (site :108-116)
    async def detect_objects_roi(self, img, roi)                     # def :177   (site :223-231)
# planogram/types/endcap_no_shelves_promotional.py
    async def compute_roi(self, img)                                 # def :61    (site :103-111)
    async def detect_objects_roi(self, img, roi)                     # def :207   (site :250-258)
```

**CLOSED WORKLIST** — output of
`grep -nE 'model="gemini|roi_client|GoogleGenAIClient|llm\.detect_objects|no_memory'` (verified 2026-09-18):

```text
planogram/types/product_on_shelves.py:330         detected_items = await self.pipeline.llm.detect_objects(     ← KEEP AS IS
planogram/types/product_on_shelves.py:825                 async with self.pipeline.roi_client as client:       (_find_poster)
planogram/types/product_on_shelves.py:829                         model="gemini-3.5-flash",
planogram/types/product_on_shelves.py:830                         no_memory=True,
planogram/types/product_on_shelves.py:1357                async with self.pipeline.roi_client as client:       (_ocr_fact_tags)
planogram/types/product_on_shelves.py:1361                        model="gemini-3.5-flash",
planogram/types/product_on_shelves.py:1362                        no_memory=True,
planogram/types/product_counter.py:108                    async with self.pipeline.roi_client as client:       (compute_roi)
planogram/types/product_counter.py:112                            model="gemini-3.5-flash",
planogram/types/product_counter.py:113                            no_memory=True,
planogram/types/product_counter.py:223                    async with self.pipeline.roi_client as client:       (detect_objects_roi)
planogram/types/product_counter.py:227                            model="gemini-3.5-flash",
planogram/types/product_counter.py:228                            no_memory=True,
planogram/types/endcap_no_shelves_promotional.py:103      async with self.pipeline.roi_client as client:       (compute_roi)
planogram/types/endcap_no_shelves_promotional.py:107              model="gemini-3.5-flash",
planogram/types/endcap_no_shelves_promotional.py:108              no_memory=True,
planogram/types/endcap_no_shelves_promotional.py:250      async with self.pipeline.roi_client as client:       (detect_objects_roi)
planogram/types/endcap_no_shelves_promotional.py:254              model="gemini-3.5-flash",
planogram/types/endcap_no_shelves_promotional.py:255              no_memory=True,
```

Occurrence counts (verified with `grep -c`): in **each** of the three files
`async with self.pipeline.roi_client as client:` == 2, `model="gemini-3.5-flash",` == 2,
`no_memory=True,` == 2. In `product_counter.py` and `endcap_no_shelves_promotional.py` the two
sites are **textually identical over the whole call** — they cannot be told apart by context, and
they do not need to be: both receive the same replacement (replace-all semantics).

Test helpers (verified):
```python
# tests/pipelines/test_endcap_no_shelves.py:30-36   and   tests/pipelines/test_product_counter.py:30-36  (same shape)
def _make_pipeline() -> MagicMock:
    pipeline = MagicMock()
    pipeline.logger = MagicMock()
    pipeline._downscale_image = MagicMock(return_value=_make_image(512, 640))   # 512, 384 in test_product_counter.py
    pipeline.roi_client = MagicMock()                                            # :35 in both files (grep -c == 1)
    return pipeline
```

### Does NOT Exist
- ~~`self.pipeline.vision_model` / `self.pipeline.llm_model_id`~~ — use `**self._vision_kwargs()`.
- ~~a `model=` kwarg on `llm.detect_objects`~~ — not exposed; leave `:330` untouched.
- ~~`roi_client` sites other than the six listed~~ — the worklist is closed; `grep` proves it.
- ~~a shared `conftest.py` under `tests/pipelines/`~~ — none; each file has its own `_make_pipeline()`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py", "action": "MODIFY"},
    {"path": "tests/pipelines/test_endcap_no_shelves.py", "action": "MODIFY"},
    {"path": "tests/pipelines/test_product_counter.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_shelf_types.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._find_poster",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._ocr_fact_tags",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py#ProductCounter.compute_roi",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py#ProductCounter.detect_objects_roi",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py#EndcapNoShelvesPromotional.compute_roi",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py#EndcapNoShelvesPromotional.detect_objects_roi"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
The edit is identical at every site — **two replacements applied to all occurrences in the file**:

| Replace (verbatim, keep the leading indentation) | With |
|---|---|
| `async with self.pipeline.roi_client as client:` | `async with self.pipeline.llm as client:` |
| the two consecutive lines `model="gemini-3.5-flash",` + `no_memory=True,` | the single line `**self._vision_kwargs(),` (same indentation) |

### Key Constraints
- Two lines out, one line in, per site; nothing else in the call changes (`structured_output=Detections`,
  `max_tokens=8192` / `128` stay where they are — `f(a=1, **d, b=2)` is valid Python).
- Do not touch the retry loops, `asyncio.sleep`, prompts or parsing around the calls.
- Known, accepted consequence: these calls now use the pipeline client's own temperature/timeout
  instead of `roi_client`'s `temperature=0.0, timeout=20`. Do not compensate.
- Run tests with
  `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src` inside the worktree. Never `uv sync`.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` — `_vision_kwargs` and the converted `_check_illumination` site (TASK-3429) are the reference result.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Apply each block, then complete every `# FILL IN:` marker.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Re-run the worklist grep and confirm the 19 lines — *why*: the list is closed; a 20th hit means the file changed and the contract must be refreshed first.
2. In each of the three type files apply the two replace-all edits — *why*: the sites are textually identical, so a replace-all is both the simplest and the only unambiguous instruction.
3. Confirm `product_on_shelves.py:330` is byte-identical — *why*: `detect_objects` already uses the pipeline client and takes no `model`.
4. Update both `_make_pipeline()` helpers — *why*: keeps any test that configures `roi_client` working (same object) and makes `_vision_kwargs()` deterministic (`model=None`).
5. Write `test_neutral_shelf_types.py`; run it and the two modified test files.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c 'async with self.pipeline.roi_client as client:' .../types/product_on_shelves.py)
# N > 1 — disambiguation: NOT needed, apply to BOTH occurrences (replace-all). Sites: _find_poster :825-833, _ocr_fact_tags :1357-1364.
# Result, site 1 (_find_poster — verified context: `for attempt in range(max_attempts):` / `try:` above, `break` below):
                async with self.pipeline.llm as client:
                    msg = await client.ask_to_image(
                        image=image_small,
                        prompt=prompt,
                        **self._vision_kwargs(),
                        structured_output=Detections,
                        max_tokens=8192,
                    )
# Result, site 2 (_ocr_fact_tags — verified context: `"If no fact tags are readable, return 'UNKNOWN'."` above):
                async with self.pipeline.llm as client:
                    msg = await client.ask_to_image(
                        image=row_img,
                        prompt=prompt,
                        **self._vision_kwargs(),
                        max_tokens=128,
                    )
```
**Why**: removes the last Google-only dependency of `ProductOnShelves`' auxiliary calls without
altering what is asked or how the answer is parsed.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c 'async with self.pipeline.roi_client as client:' .../types/product_counter.py)
# N > 1 — the two sites (compute_roi :108-116, detect_objects_roi :223-231) are textually IDENTICAL; apply to BOTH. Result (each):
                async with self.pipeline.llm as client:
                    msg = await client.ask_to_image(
                        image=image_small,
                        prompt=prompt,
                        **self._vision_kwargs(),
                        structured_output=Detections,
                        max_tokens=8192,
                    )
```
**Why**: identical call, identical replacement.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c 'async with self.pipeline.roi_client as client:' .../types/endcap_no_shelves_promotional.py)
# N > 1 — the two sites (compute_roi :103-111, detect_objects_roi :250-258) are textually IDENTICAL; apply to BOTH. Result (each):
                async with self.pipeline.llm as client:
                    msg = await client.ask_to_image(
                        image=image_small,
                        prompt=prompt,
                        **self._vision_kwargs(),
                        structured_output=Detections,
                        max_tokens=8192,
                    )
```
**Why**: identical call, identical replacement.

### `tests/pipelines/test_endcap_no_shelves.py` and `tests/pipelines/test_product_counter.py` (MODIFY — same edit in both)
```python
# occurrences: 1 per file (verified: grep -c 'pipeline.roi_client = MagicMock()' <file>)
# REPLACE `    pipeline.roi_client = MagicMock()` (verified: :35 in both files) with:
    pipeline.llm = MagicMock()
    pipeline.roi_client = pipeline.llm  # same object until TASK-3432 removes roi_client
    pipeline.resolved_backend = MagicMock(provider="google", model=None)
```
**Why**: a bare `MagicMock()` pipeline would auto-create `resolved_backend.model` as a `MagicMock`;
pinning `model=None` documents the intended "no model kwarg" path for these suites.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_shelf_types.py` (CREATE)
```python
"""Provider-neutral call sites of the shelf-style planogram types (TASK-3430)."""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from parrot_pipelines.planogram.types import (
    EndcapNoShelvesPromotional,
    ProductCounter,
    ProductOnShelves,
)

_TYPES_DIR = Path(__file__).resolve().parents[2] / "src" / "parrot_pipelines" / "planogram" / "types"
_FILES = ("product_on_shelves.py", "product_counter.py", "endcap_no_shelves_promotional.py")


def _pipeline(model):
    """Mock pipeline whose llm is an async context manager yielding a recording client."""
    client = MagicMock()
    client.ask_to_image = AsyncMock(return_value=MagicMock(output="", structured_output=None))
    llm = MagicMock()
    llm.__aenter__ = AsyncMock(return_value=client)
    llm.__aexit__ = AsyncMock(return_value=False)
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.neutral_shelf_types")
    pipeline.llm = llm
    pipeline.roi_client = MagicMock(name="roi_client_must_not_be_used")
    pipeline.resolved_backend = MagicMock(provider="anthropic", model=model)
    pipeline._downscale_image = MagicMock(return_value=Image.new("RGB", (64, 64)))
    return pipeline, client


@pytest.mark.parametrize("name", _FILES)
def test_no_literals_left(name):
    text = (_TYPES_DIR / name).read_text(encoding="utf-8")
    assert "roi_client" not in text
    assert 'model="gemini' not in text
    assert "no_memory=True" not in text  # now supplied by _vision_kwargs()
```
**Why this shape**: the text test proves the closed worklist is exhausted; `_pipeline()` gives the
behavioural tests one reusable, provider-agnostic double. Behavioural test bodies are FILL IN
because each method needs its own minimal config mock.

### FILL IN checklist
- [ ] `test_neutral_shelf_types.py::test_product_counter_compute_roi_uses_pipeline_llm` — build `ProductCounter(pipeline, config=MagicMock())`, await `compute_roi(img)`, assert `client.ask_to_image.await_args.kwargs` has `no_memory=True`, `model == "claude-sonnet-5"` and that `pipeline.roi_client.__aenter__` was never awaited; bounded by AC-2
- [ ] same for `EndcapNoShelvesPromotional.compute_roi` and `ProductOnShelves._find_poster` — bounded by AC-2
- [ ] one test with `model=None` asserting `"model" not in kwargs` — bounded by AC-3
- [ ] config mocks: set only the attributes each method reads (`roi_detection_prompt`, `get_planogram_description()`); read the method body first — bounded by "no source change to make a test pass"

---

## Acceptance Criteria

- [ ] AC-1: `grep -nE 'model="gemini|roi_client|no_memory'` returns zero matches in the three type files; `product_on_shelves.py` still contains exactly one `self.pipeline.llm.detect_objects(`.
- [ ] AC-2: each rewritten site awaits `ask_to_image` on the client yielded by `self.pipeline.llm`, with `no_memory=True` and the backend's model when pinned.
- [ ] AC-3: with `resolved_backend.model is None`, no `model` kwarg is sent.
- [ ] AC-4: `git diff` of the three type files contains only the 6 sites (18 lines removed, 12 added).
- [ ] AC-5: `pytest tests/pipelines/test_endcap_no_shelves.py tests/pipelines/test_product_counter.py -q` and the characterization files of TASK-3422/3423/3424 still pass.
- [ ] `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types` passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_shelf_types.py -q`

---

## Test Specification

```python
@pytest.mark.parametrize("name", _FILES)
def test_no_literals_left(name): ...

async def test_product_counter_compute_roi_uses_pipeline_llm():
    pipeline, client = _pipeline(model="claude-sonnet-5")
    handler = ProductCounter(pipeline=pipeline, config=<config mock>)
    await handler.compute_roi(Image.new("RGB", (256, 256)))
    kwargs = client.ask_to_image.await_args.kwargs
    assert kwargs["no_memory"] is True and kwargs["model"] == "claude-sonnet-5"
    pipeline.roi_client.__aenter__.assert_not_called()

async def test_endcap_no_shelves_compute_roi_uses_pipeline_llm(): ...
async def test_pos_find_poster_uses_pipeline_llm(): ...
async def test_model_omitted_when_backend_has_none(): ...
def test_pos_detect_objects_call_untouched():
    """product_on_shelves.py still contains 'await self.pipeline.llm.detect_objects(' exactly once."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — re-run the worklist grep; confirm `_vision_kwargs` exists on
   `AbstractPlanogramType`. If anything has changed, update the contract FIRST, then implement.
   **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/new-planogram-pipeline.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3430-neutral-callsites-shelf-types.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (FEAT-574 orchestrator)
**Date**: 2026-09-19

Implemented in fallback sequential mode (parrot-sdd-coder server unresponsive).
Closed worklist rewritten (6 sites: ProductOnShelves._find_poster/_ocr_fact_tags, ProductCounter.compute_roi/detect_objects_roi, EndcapNoShelvesPromotional.compute_roi/detect_objects_roi): async with self.pipeline.llm + **self._vision_kwargs() replacing the roi_client/model='gemini-3.5-flash'/no_memory lines; product_on_shelves.py's single self.pipeline.llm.detect_objects( call untouched. tests/pipelines/{test_endcap_no_shelves,test_product_counter}.py _make_pipeline: llm alias + resolved_backend(model=None).
Tests: test_neutral_shelf_types.py 10 passed; tests/pipelines endcap 19 / product_counter 18; characterization suites 13/17/10 and test_planogram_types 26 unchanged. No new ruff findings vs origin/dev.

Seat: orchestrator (fallback) · Backend: native · Model: claude-opus-5 · Attempts: 1
