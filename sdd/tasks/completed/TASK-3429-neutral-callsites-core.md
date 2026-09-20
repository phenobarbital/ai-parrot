# TASK-3429: Provider-neutral call sites — types/abstract.py helper, plan.py promo OCR, legacy.py

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3422, TASK-3423, TASK-3424, TASK-3425, TASK-3427
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 6** (Provider-neutral call sites), goal **G11**. Every auxiliary
vision call in the pipeline package goes through the unconditional Google
`roi_client` with a hard-coded `model="gemini-3.5-flash"`. This task introduces
the single helper every rewritten call site uses —
`AbstractPlanogramType._vision_kwargs()` — and converts the three *core* sites:
`_check_illumination` (types/abstract.py), the promotional-OCR call inside
`PlanogramCompliance.run()` (plan.py) and `_find_poster` of the old
`PlanogramCompliancePipeline` (legacy.py). TASK-3430 and TASK-3431 then convert
the five type files with the same idiom; TASK-3432 finally deletes
`AbstractPipeline.roi_client`.

The behaviour of these paths was pinned by the characterization tests of
TASK-3422 / TASK-3423 / TASK-3424. They must stay green.

---

## Scope

- Add `AbstractPlanogramType._vision_kwargs(self, **extra) -> Dict[str, Any]`.
- Rewrite the **closed worklist** below (3 sites, 9 lines) with the fixed idiom.
  No other line of the three source files changes.
- Update the `mock_pipeline` fixture of
  `packages/ai-parrot-pipelines/tests/test_planogram_types.py` so `pipeline.llm`
  is the same mock object as `pipeline.roi_client` and
  `pipeline.resolved_backend` is set.
- Write `test_vision_kwargs.py`.

**NOT in scope**:
- The five concrete type files (TASK-3430, TASK-3431).
- Deleting `AbstractPipeline.roi_client` or its `GoogleGenAIClient` import
  (TASK-3432). After this task `roi_client` still exists and is simply unused by
  these three sites.
- `planogram/grid/detector.py:130` — `self.llm.detect_objects(...)` stays as it is.
- Any algorithm, prompt, `max_tokens`, `structured_output` or retry change.
- The handler.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` | MODIFY | add `_vision_kwargs`; rewrite the `_check_illumination` call site |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` | MODIFY | rewrite the promotional-OCR call site in `run()` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/legacy.py` | MODIFY | rewrite the `_find_poster` call site |
| `packages/ai-parrot-pipelines/tests/test_planogram_types.py` | MODIFY | `mock_pipeline` fixture: alias `llm`, set `resolved_backend` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_kwargs.py` | CREATE | unit tests for the helper and the three sites |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from typing import Any, Dict, List, Optional, Tuple, Union, TYPE_CHECKING   # already in types/abstract.py:7
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType   # types/abstract.py:30
from parrot_pipelines.planogram.backend import ResolvedBackend                # created by TASK-3426 (dependency of TASK-3427)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py
class AbstractPlanogramType(ABC):                                    # :30
    def __init__(self, pipeline: "PlanogramCompliance", config: "PlanogramConfig") -> None   # :48-55
        # sets self.pipeline, self.config, self.logger
    async def _check_illumination(self, img, zone_bbox=None, roi=None, planogram_description=None) -> Optional[str]  # :151-249
    def get_render_colors(self) -> Dict[str, Tuple[int, int, int]]   # :448  (grep -c '    def get_render_colors' == 1)

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py
class PlanogramCompliance(AbstractPipeline):                         # :24
    # self._type_handler  → the AbstractPlanogramType instance       # :69
    async def run(self, image, output_dir=None, image_id=None, **kwargs) -> Dict[str, Any]   # :71-370

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/legacy.py
class PlanogramCompliancePipeline(AbstractPipeline):                 # :1255 ; super().__init__(llm=..., llm_provider=..., llm_model=...) at :1293
    # `async with self.llm as client:` already used at :1473 (the idiom to copy)
    async def _find_poster(...)                                      # def at :2257

# Created by TASK-3427 (dependency) — packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py
class AbstractPipeline(ABC):
    self.llm                 # the resolved client instance (existing attribute, abstract.py:26)
    self.resolved_backend    # ResolvedBackend(provider: str, model: Optional[str], origin: ...)  — model None ⇒ provider default
    self.roi_client          # STILL EXISTS after this task (deleted by TASK-3432)

# Created by TASK-3425 (dependency): AnthropicClient.ask_to_image accepts no_memory: bool = False
# Google ask_to_image already accepts model=, no_memory=, max_tokens=, structured_output=
#   (packages/ai-parrot-client-google/src/parrot/clients/google/client.py:4999-5010)

# AbstractClient async context manager (packages/ai-parrot/src/parrot/clients/base.py:1155-1170):
#   __aenter__ creates an aiohttp session when use_session and calls _ensure_client(); __aexit__ closes the session.
```

**CLOSED WORKLIST** — output of
`grep -nE 'model="gemini|roi_client|GoogleGenAIClient|llm\.detect_objects|no_memory'` on the three
source files (verified 2026-09-18). These 9 lines are the ONLY lines to change:

```text
planogram/types/abstract.py:234             async with self.pipeline.roi_client as client:      (_check_illumination, def :151)
planogram/types/abstract.py:238                     model="gemini-3.5-flash",
planogram/types/abstract.py:239                     no_memory=True,
planogram/plan.py:210                               async with self.roi_client as client:       (run, def :71 — promo OCR loop)
planogram/plan.py:214                                       model="gemini-3.5-flash",
planogram/plan.py:215                                       no_memory=True,
planogram/legacy.py:2282                    async with self.roi_client as client:               (_find_poster, def :2257)
planogram/legacy.py:2286                            model="gemini-3.5-flash",
planogram/legacy.py:2287                            no_memory=True,
```

Each file contains each of the three patterns **exactly once**
(`grep -c 'roi_client as client' <file>` == 1, `grep -c 'model="gemini-3.5-flash"' <file>` == 1,
`grep -c 'no_memory=True' <file>` == 1 for all three files).

### Does NOT Exist
- ~~`AbstractPlanogramType._vision_kwargs`~~ — created by THIS task.
- ~~`PlanogramCompliance._vision_kwargs` / `AbstractPipeline._vision_kwargs`~~ — the helper lives on the type only; `plan.py` reaches it through `self._type_handler`, `legacy.py` builds the dict inline.
- ~~`self.pipeline.vision_model`, `self.pipeline.llm_model_id`~~ — not attributes; the model is `self.pipeline.resolved_backend.model`.
- ~~`AbstractClient.ask_to_image`~~ — not on the base class; duck-typed per provider.
- ~~a `model` kwarg on `llm.detect_objects`~~ — not exposed by Google; do not add `**self._vision_kwargs()` to `detect_objects` calls.
- ~~`pipeline.resolved_backend` on `MagicMock(spec=PlanogramCompliance)`~~ — instance attributes are not in the spec; the fixture must set it explicitly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/legacy.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/test_planogram_types.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_kwargs.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType._check_illumination",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance.run",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/legacy.py#PlanogramCompliancePipeline._find_poster"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# BEFORE (every site)                                  # AFTER (type files and types/abstract.py)
async with self.pipeline.roi_client as client:         async with self.pipeline.llm as client:
    msg = await client.ask_to_image(                       msg = await client.ask_to_image(
        image=roi_small,                                       image=roi_small,
        prompt=prompt,                                         prompt=prompt,
        model="gemini-3.5-flash",                              **self._vision_kwargs(),
        no_memory=True,                                        max_tokens=128,
        max_tokens=128,                                    )
    )
```
`f(a=1, **d, b=2)` is valid Python — keep `**self._vision_kwargs()` exactly where the two
removed lines were, so the diff is two lines out, one line in.

### Key Constraints
- Two lines out, one line in, per site. Do not reorder other kwargs, do not touch prompts.
- `model` is passed **only** when the resolved backend pins one (a non-empty `str`). The
  `isinstance(model, str)` guard is deliberate: test pipelines are `MagicMock`s, whose
  auto-attributes are truthy non-strings — without the guard a `MagicMock` would be sent as `model`.
- Known, accepted consequence: `roi_client` was built with `temperature=0.0, max_retries=2,
  timeout=20` (`abstract.py:40`); the pipeline's own client now serves these calls with its own
  settings. Do **not** add `temperature` here — the spec fixes the helper's contract.
- If a characterization test from TASK-3422/3423/3424 asserts the literal `model="gemini-3.5-flash"`
  kwarg, do not edit that test (not your file): report it in the Completion Note.
- Run tests with
  `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src:packages/ai-parrot-client-anthropic/src`
  inside the worktree (the shared `.venv` is editable-installed against the main checkout). Never `uv sync`.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/legacy.py:1473` — `async with self.llm as client:` idiom.
- `packages/ai-parrot-pipelines/tests/test_planogram_types.py:94-107` — the fixture to update.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Add `_vision_kwargs` to `AbstractPlanogramType` — *why*: every other edit (here and in TASK-3430/3431) calls it, so it must exist first.
2. Rewrite the `_check_illumination` site in `types/abstract.py` — *why*: removes the base-class dependency on the Google-only `roi_client`.
3. Rewrite the promo-OCR site in `plan.py` using `self._type_handler._vision_kwargs()` — *why*: `PlanogramCompliance` is the pipeline, not a type; the helper is reachable through the handler it already owns (`plan.py:69`).
4. Rewrite the `_find_poster` site in `legacy.py` with an inline dict — *why*: `PlanogramCompliancePipeline` has no type handler; it must stop using `roi_client` before TASK-3432 deletes the attribute.
5. Update the `mock_pipeline` fixture — *why*: `MagicMock(spec=PlanogramCompliance)` does not expose instance attributes; without `resolved_backend` the helper would raise `AttributeError` in existing tests.
6. Write `test_vision_kwargs.py`, then run it plus the two existing suites named in Acceptance Criteria.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` (MODIFY) — helper
```python
# occurrences: 1 (verified: grep -c '    def get_render_colors' .../planogram/types/abstract.py)
# BEFORE — insert immediately ABOVE `    def get_render_colors(self) -> Dict[str, Tuple[int, int, int]]:` (verified: types/abstract.py:448)
    def _vision_kwargs(self, **extra: Any) -> Dict[str, Any]:
        """Build the provider-neutral kwargs for an auxiliary ``ask_to_image`` call.

        Args:
            **extra: Additional keyword arguments merged into the result.

        Returns:
            ``{"no_memory": True, **extra}`` plus ``"model"`` when the pipeline's
            resolved backend pins a model id. When the backend leaves the model
            unset, ``"model"`` is omitted so the client's own default applies.
        """
        kwargs: Dict[str, Any] = {"no_memory": True, **extra}
        backend = getattr(self.pipeline, "resolved_backend", None)
        model = getattr(backend, "model", None)
        if isinstance(model, str) and model:
            kwargs["model"] = model
        return kwargs

```
**Why this shape**: spec Module 6 fixes the helper's name, signature and return contract. `getattr`
chains (not attribute access) keep hand-built test pipelines and older subclasses working; the
`isinstance(..., str)` guard prevents a `MagicMock` attribute from being forwarded as a model id.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` (MODIFY) — `_check_illumination` site
```python
# occurrences: 1 (verified: grep -c 'async with self.pipeline.roi_client as client:' .../planogram/types/abstract.py)
# REPLACE the 3 worklist lines inside this call (verified: types/abstract.py:234-241). Result:
            async with self.pipeline.llm as client:
                msg = await client.ask_to_image(
                    image=roi_small,
                    prompt=prompt,
                    **self._vision_kwargs(),
                    max_tokens=128,
                )
```
**Why**: same call, same `max_tokens`, same surrounding `try/except`; only the client and the two
hard-coded kwargs change.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async with self.roi_client as client:' .../planogram/plan.py)
# REPLACE the 3 worklist lines inside this call (verified: plan.py:210-217). Result:
                        async with self.llm as client:
                            msg = await client.ask_to_image(
                                image=p_img,
                                prompt=ocr_prompt,
                                **self._type_handler._vision_kwargs(),
                                max_tokens=1024,
                            )
```
**Why**: `self` here is the pipeline, so the client is `self.llm` and the helper is reached through
`self._type_handler`. Everything after `max_tokens=1024,` (the `found_content` parsing) is untouched.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/legacy.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async with self.roi_client as client:' .../planogram/legacy.py)
# REPLACE the 3 worklist lines inside this call (verified: legacy.py:2282-2290). Result:
                _model = getattr(getattr(self, "resolved_backend", None), "model", None)
                _vision_kwargs = {"no_memory": True}
                if isinstance(_model, str) and _model:
                    _vision_kwargs["model"] = _model
                async with self.llm as client:
                    msg = await client.ask_to_image(
                        image=image_small,
                        prompt=prompt,
                        **_vision_kwargs,
                        structured_output=Detections,
                        max_tokens=8192,
                    )
```
**Why**: the old YOLO pipeline has no type handler, so the same rule is written inline. The four new
lines go at the indentation of the `async with` (inside the `try:` of the retry loop).

### `packages/ai-parrot-pipelines/tests/test_planogram_types.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'pipeline.roi_client = MagicMock()' .../tests/test_planogram_types.py)
# REPLACE the two lines `pipeline.roi_client = MagicMock()` / `pipeline.llm = MagicMock()` (verified: :100-101) with:
    pipeline.llm = MagicMock()
    pipeline.roi_client = pipeline.llm  # same object until TASK-3432 removes roi_client
    pipeline.resolved_backend = MagicMock(provider="google", model=None)
```
**Why**: tests that configured answers on `roi_client` keep working because it is now the very
object the code reaches through `pipeline.llm`; `model=None` exercises the "no model kwarg" branch.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_kwargs.py` (CREATE)
```python
"""Tests for AbstractPlanogramType._vision_kwargs and the three core call sites (TASK-3429)."""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from parrot_pipelines.planogram.backend import ResolvedBackend
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType


class _LegacyType(AbstractPlanogramType):
    """Minimal concrete type for helper tests."""

    async def compute_roi(self, img):
        return None, None, None, None, []

    async def detect_objects_roi(self, img, roi):
        return []

    async def detect_objects(self, img, roi, macro_objects):
        return [], []

    def check_planogram_compliance(self, identified_products, planogram_description):
        return []


def _make_type(model):
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.vision_kwargs")
    pipeline.resolved_backend = ResolvedBackend(provider="anthropic", model=model, origin="config")
    # FILL IN: make pipeline.llm an async context manager whose __aenter__ returns a client with
    #          ask_to_image = AsyncMock(return_value=MagicMock(output="ON")) — bounded by AC-3
    return _LegacyType(pipeline=pipeline, config=MagicMock()), pipeline
```
**Why this shape**: a real `ResolvedBackend` proves the helper reads the contract of TASK-3426, not
a mock's shape. Test bodies are listed in the Test Specification.

### FILL IN checklist
- [ ] `test_vision_kwargs.py::_make_type` — async-context-manager mock for `pipeline.llm`; bounded by AC-3
- [ ] `test_vision_kwargs.py` test bodies — per Test Specification; bounded by AC-1..AC-4

---

## Acceptance Criteria

- [ ] AC-1: `_vision_kwargs()` returns `{"no_memory": True}` when the resolved model is `None`, a `MagicMock`, or `""`; returns `{"no_memory": True, "model": "<id>"}` when it is a non-empty `str`; `**extra` is merged.
- [ ] AC-2: `grep -nE 'model="gemini|roi_client' ` returns **zero** matches in `planogram/types/abstract.py`, `planogram/plan.py`, `planogram/legacy.py`.
- [ ] AC-3: `_check_illumination` awaits `ask_to_image` on the client yielded by `pipeline.llm`, with `no_memory=True`, `max_tokens=128`, and `model` only when pinned.
- [ ] AC-4: `git diff --stat` for the three source files shows only the worklist edits plus the helper (no prompt / algorithm change).
- [ ] AC-5: existing suites still pass: `pytest packages/ai-parrot-pipelines/tests/test_planogram_types.py -q` and the characterization files of TASK-3422/3423/3424.
- [ ] `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram` passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_kwargs.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_kwargs.py
def test_vision_kwargs_without_model():
    handler, _ = _make_type(model=None)
    assert handler._vision_kwargs() == {"no_memory": True}

def test_vision_kwargs_with_model_and_extra():
    handler, _ = _make_type(model="claude-sonnet-5")
    assert handler._vision_kwargs(max_tokens=16) == {"no_memory": True, "max_tokens": 16, "model": "claude-sonnet-5"}

def test_vision_kwargs_ignores_non_string_model():
    handler, pipeline = _make_type(model=None)
    pipeline.resolved_backend = MagicMock()          # .model is a MagicMock
    assert "model" not in handler._vision_kwargs()

def test_vision_kwargs_without_resolved_backend_attribute():
    handler, pipeline = _make_type(model=None)
    del pipeline.resolved_backend
    assert handler._vision_kwargs() == {"no_memory": True}

async def test_check_illumination_uses_pipeline_llm():
    """ask_to_image is awaited on pipeline.llm's client with model from the backend, never on roi_client."""
    # build a 64x64 image, call handler._check_illumination(img, roi=<bbox mock>), inspect call kwargs

def test_core_files_have_no_literals():
    """Read the three source files as text; assert 'roi_client' and 'model=\"gemini' are absent."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Re-run the worklist grep and confirm the same 9 lines (line numbers may have shifted; the line *text* must match)
   - Confirm `self.resolved_backend` exists on `AbstractPipeline` (TASK-3427)
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/new-planogram-pipeline.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3429-neutral-callsites-core.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (FEAT-574 orchestrator)
**Date**: 2026-09-19

Implemented in fallback sequential mode (parrot-sdd-coder server unresponsive).
AbstractPlanogramType._vision_kwargs(**extra) added (no_memory=True + model only when the resolved backend pins a non-empty str). Closed worklist rewritten (two lines out, one in per site): types/abstract.py _check_illumination -> async with self.pipeline.llm, **self._vision_kwargs(); plan.py promo OCR -> async with self.llm, **self._type_handler._vision_kwargs(); legacy.py _find_poster -> inline _vision_kwargs dict + async with self.llm. No prompt/max_tokens/structured_output change. test_planogram_types.py mock_pipeline: roi_client aliases llm, resolved_backend = MagicMock(provider='google', model=None).
Tests: test_vision_kwargs.py 6 passed; test_planogram_types.py 26; characterization suites of TASK-3422/3423/3424 13/17/10 passed unchanged (none asserted the literal gemini model). ruff: no new findings vs origin/dev in planogram/ (all 38 pre-existing).
Accepted consequence (per task): these calls now use the pipeline client's own temperature/retry/timeout settings instead of roi_client's (temperature 0.0, max_retries 2, timeout 20).

Seat: orchestrator (fallback) · Backend: native · Model: claude-opus-5 · Attempts: 1
