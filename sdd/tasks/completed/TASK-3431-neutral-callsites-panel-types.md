# TASK-3431: Provider-neutral call sites — endcap_backlit_multitier, graphic_panel_display

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
`AbstractPlanogramType._vision_kwargs()`. This task applies the same mechanical
edit to the two panel-style type files — `EndcapBacklitMultitier` (6 sites) and
`GraphicPanelDisplay` (4 sites) — which together hold 30 of the 63 worklist
lines of the feature. Every site goes through the Google-only
`self.pipeline.roi_client` with a hard-coded `model="gemini-3.5-flash"` today.

These two types are **not** migrated to the new cycle in this feature; they only
receive this provider-neutral update. No algorithm changes.

---

## Scope

- Rewrite the **closed worklist** below (10 sites, 30 lines) with the fixed idiom.
- Write `test_neutral_panel_types.py`.

**NOT in scope**:
- The shelf-style type files (TASK-3430) — disjoint files, runs concurrently.
- Deleting `AbstractPipeline.roi_client` (TASK-3432).
- Any prompt, retry, `max_tokens`, `structured_output` or algorithm change.
- Editing existing test files (none of the existing suites for these two types
  references `roi_client`; verified with `grep -rl roi_client` on the test trees).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py` | MODIFY | 6 sites |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py` | MODIFY | 4 sites |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_panel_types.py` | CREATE | tests for the ten sites |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot_pipelines.planogram.types import EndcapBacklitMultitier, GraphicPanelDisplay   # planogram/types/__init__.py:2-16
```

### Existing Signatures to Use
```python
# Created by TASK-3429 (dependency) — planogram/types/abstract.py
class AbstractPlanogramType(ABC):
    def _vision_kwargs(self, **extra: Any) -> Dict[str, Any]:
        """{"no_memory": True, **extra} plus "model" only when self.pipeline.resolved_backend.model is a non-empty str."""

# self.pipeline.llm              → the pipeline's resolved client (async context manager)
# self.pipeline.resolved_backend → set by AbstractPipeline (TASK-3427, ancestor)
# self.pipeline.roi_client       → STILL EXISTS after this task; must simply no longer be used here

# planogram/types/endcap_backlit_multitier.py — enclosing methods of the six sites
    async def compute_roi(self, img)                                # def :162   site :205-213  (structured_output=_RawDetections, max_tokens=8192)
    async def detect_objects_roi(self, img, roi)                    # def :372   site :415-423  (structured_output=_RawDetections, max_tokens=8192)
    async def _detect_fact_tags_prescan(...)                        # def :1069  site :1109-1117 (image=crop_small, max_tokens=4096)
    async def _detect_section(...)                                  # def :1209  site :1260-1268 (image=crop_small, max_tokens=4096)
    async def _detect_combined_flat_shelves(...)                    # def :1395  site :1507-1515 (image=crop_small, max_tokens=4096)
    async def _detect_flat_shelf(...)                               # def :1653  site :1683-1691 (image=crop_small, max_tokens=4096)
# planogram/types/graphic_panel_display.py — enclosing methods of the four sites
    async def detect_objects_roi(self, img, roi)                    # def :92    site :138-146  (structured_output=Detections, max_tokens=8192)
    async def _find_display_roi(...)                                # def :554   site :595-603  (structured_output=Detections, max_tokens=8192)
    async def _check_illumination_from_roi(...)                     # def :651   site :699-705  (image=roi_small, max_tokens=16)
    async def _enrich_zone(...)                                     # def :715   site :793-799  (image=zone_small, max_tokens=512)
```

**CLOSED WORKLIST** — output of
`grep -nE 'model="gemini|roi_client|GoogleGenAIClient|llm\.detect_objects|no_memory'` (verified 2026-09-18):

```text
endcap_backlit_multitier.py:205 / 209 / 210        async with …roi_client… / model="gemini-3.5-flash", / no_memory=True,   (compute_roi)
endcap_backlit_multitier.py:415 / 419 / 420        (detect_objects_roi)
endcap_backlit_multitier.py:1109 / 1113 / 1114     (_detect_fact_tags_prescan)
endcap_backlit_multitier.py:1260 / 1264 / 1265     (_detect_section)
endcap_backlit_multitier.py:1507 / 1511 / 1512     (_detect_combined_flat_shelves)
endcap_backlit_multitier.py:1683 / 1687 / 1688     (_detect_flat_shelf)
graphic_panel_display.py:138 / 142 / 143           (detect_objects_roi)
graphic_panel_display.py:595 / 599 / 600           (_find_display_roi)
graphic_panel_display.py:699 / 703 / 704           (_check_illumination_from_roi)
graphic_panel_display.py:793 / 797 / 798           (_enrich_zone)
```

Occurrence counts (verified with `grep -c`):
`endcap_backlit_multitier.py` — `async with self.pipeline.roi_client as client:` == 6,
`model="gemini-3.5-flash",` == 6, `no_memory=True,` == 6;
`graphic_panel_display.py` — 4 / 4 / 4. Sites at :205/:415 are indented 16 spaces, the rest of
`endcap_backlit_multitier.py` 12 spaces; `graphic_panel_display.py` :138/:595 use 16, :699/:793 use 12.
Several sites are textually identical over the whole call; all occurrences receive the **same**
replacement, so no per-site disambiguation is required (replace-all semantics).

### Does NOT Exist
- ~~`llm.detect_objects` calls in these two files~~ — none; every hit is an `ask_to_image` site.
- ~~`self.pipeline.vision_model` / `self.pipeline.llm_model_id`~~ — use `**self._vision_kwargs()`.
- ~~existing tests referencing `roi_client` for these types~~ — none; do not edit existing test files.
- ~~`_RawDetections` in `parrot.models.detections`~~ — it is a module-local model of `endcap_backlit_multitier.py`; do not import it elsewhere.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_panel_types.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py#EndcapBacklitMultitier.compute_roi",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py#EndcapBacklitMultitier.detect_objects_roi",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py#EndcapBacklitMultitier._detect_fact_tags_prescan",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py#EndcapBacklitMultitier._detect_section",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py#EndcapBacklitMultitier._detect_combined_flat_shelves",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py#EndcapBacklitMultitier._detect_flat_shelf",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py#GraphicPanelDisplay.detect_objects_roi",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py#GraphicPanelDisplay._find_display_roi",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py#GraphicPanelDisplay._check_illumination_from_roi",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py#GraphicPanelDisplay._enrich_zone"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Two replacements applied to **all occurrences** in each file:

| Replace (verbatim, keep the leading indentation) | With |
|---|---|
| `async with self.pipeline.roi_client as client:` | `async with self.pipeline.llm as client:` |
| the two consecutive lines `model="gemini-3.5-flash",` + `no_memory=True,` | the single line `**self._vision_kwargs(),` (same indentation) |

### Key Constraints
- Two lines out, one line in, per site. `structured_output=…` and `max_tokens=…` stay after the
  unpacking (`f(a=1, **d, b=2)` is valid Python).
- Do not touch retry loops, prompts, crops or parsing.
- Known, accepted consequence: the pipeline client's own temperature/timeout now apply instead of
  `roi_client`'s `temperature=0.0, timeout=20`. Do not compensate.
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src` inside the
  worktree. Never `uv sync`.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` — `_vision_kwargs` and the converted `_check_illumination` site (TASK-3429) are the reference result.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Apply each block, then complete every `# FILL IN:` marker.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Re-run the worklist grep and confirm the 30 lines — *why*: the list is closed; extra hits mean the file changed and the contract must be refreshed first.
2. Apply the two replace-all edits in `endcap_backlit_multitier.py`, then in `graphic_panel_display.py` — *why*: all sites share one textual pattern, so replace-all is the only unambiguous instruction.
3. Re-run the grep: it must print nothing for both files — *why*: that is AC-1 and what TASK-3432's guard later enforces repo-wide.
4. Write `test_neutral_panel_types.py` and run it together with the existing suites for these types.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py` (MODIFY)
```python
# occurrences: 6 (verified: grep -c 'async with self.pipeline.roi_client as client:' .../types/endcap_backlit_multitier.py)
# N > 1 — disambiguation NOT needed: apply to ALL 6 occurrences (replace-all). Resulting shapes:
# (a) compute_roi :205 and detect_objects_roi :415  (16-space indent)
                async with self.pipeline.llm as client:
                    msg = await client.ask_to_image(
                        image=image_small,
                        prompt=prompt,
                        **self._vision_kwargs(),
                        structured_output=_RawDetections,
                        max_tokens=8192,
                    )
# (b) _detect_fact_tags_prescan :1109, _detect_section :1260, _detect_combined_flat_shelves :1507, _detect_flat_shelf :1683  (12-space indent)
            async with self.pipeline.llm as client:
                msg = await client.ask_to_image(
                    image=crop_small,
                    prompt=prompt,
                    **self._vision_kwargs(),
                    structured_output=_RawDetections,
                    max_tokens=4096,
                )
```
**Why**: 18 of the feature's 63 hard-coded lines live here; the type keeps its algorithm and only
stops depending on a Google-only client and model literal.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py` (MODIFY)
```python
# occurrences: 4 (verified: grep -c 'async with self.pipeline.roi_client as client:' .../types/graphic_panel_display.py)
# N > 1 — disambiguation NOT needed: apply to ALL 4 occurrences (replace-all). Resulting shapes:
# (a) detect_objects_roi :138 and _find_display_roi :595
                async with self.pipeline.llm as client:
                    msg = await client.ask_to_image(
                        image=image_small,
                        prompt=prompt,
                        **self._vision_kwargs(),
                        structured_output=Detections,
                        max_tokens=8192,
                    )
# (b) _check_illumination_from_roi :699
            async with self.pipeline.llm as client:
                msg = await client.ask_to_image(
                    image=roi_small,
                    prompt=prompt,
                    **self._vision_kwargs(),
                    max_tokens=16,
                )
# (c) _enrich_zone :793
            async with self.pipeline.llm as client:
                msg = await client.ask_to_image(
                    image=zone_small,
                    prompt=prompt,
                    **self._vision_kwargs(),
                    max_tokens=512,
                )
```
**Why**: same rule; the four `max_tokens` values differ and must be preserved exactly.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_panel_types.py` (CREATE)
```python
"""Provider-neutral call sites of the panel-style planogram types (TASK-3431)."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from parrot_pipelines.planogram.types import EndcapBacklitMultitier, GraphicPanelDisplay

_TYPES_DIR = Path(__file__).resolve().parents[2] / "src" / "parrot_pipelines" / "planogram" / "types"
_EXPECTED_SITES = {"endcap_backlit_multitier.py": 6, "graphic_panel_display.py": 4}


def _pipeline(model):
    """Mock pipeline whose llm is an async context manager yielding a recording client."""
    client = MagicMock()
    client.ask_to_image = AsyncMock(return_value=MagicMock(output="", structured_output=None))
    llm = MagicMock()
    llm.__aenter__ = AsyncMock(return_value=client)
    llm.__aexit__ = AsyncMock(return_value=False)
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.neutral_panel_types")
    pipeline.llm = llm
    pipeline.roi_client = MagicMock(name="roi_client_must_not_be_used")
    pipeline.resolved_backend = MagicMock(provider="anthropic", model=model)
    pipeline._downscale_image = MagicMock(return_value=Image.new("RGB", (64, 64)))
    return pipeline, client


@pytest.mark.parametrize("name,sites", sorted(_EXPECTED_SITES.items()))
def test_no_literals_and_site_count(name, sites):
    text = (_TYPES_DIR / name).read_text(encoding="utf-8")
    assert "roi_client" not in text
    assert 'model="gemini' not in text
    assert "no_memory=True" not in text
    assert len(re.findall(r"async with self\.pipeline\.llm as client:", text)) == sites
    assert text.count("**self._vision_kwargs(),") == sites
```
**Why this shape**: the count assertions prove every one of the ten sites was converted (not
deleted); `_pipeline()` is the double for the behavioural tests, whose bodies are FILL IN because
each method needs its own minimal config mock.

### FILL IN checklist
- [ ] `test_graphic_panel_illumination_uses_pipeline_llm` — await `GraphicPanelDisplay._check_illumination_from_roi(...)` (read its signature at `graphic_panel_display.py:651` first), assert `max_tokens == 16`, `no_memory is True`, `model == "claude-sonnet-5"`, and `pipeline.roi_client.__aenter__` never called; bounded by AC-2
- [ ] `test_backlit_compute_roi_uses_pipeline_llm` — same assertions for `EndcapBacklitMultitier.compute_roi`, `max_tokens == 8192`; bounded by AC-2
- [ ] `test_model_omitted_when_backend_has_none` — bounded by AC-3
- [ ] config mocks: set only what each method reads; read the method body first — bounded by "no source change to make a test pass"

---

## Acceptance Criteria

- [ ] AC-1: `grep -nE 'model="gemini|roi_client|no_memory'` prints nothing for both files.
- [ ] AC-2: each rewritten site awaits `ask_to_image` on the client yielded by `self.pipeline.llm`, preserving its original `max_tokens` / `structured_output`.
- [ ] AC-3: with `resolved_backend.model is None`, no `model` kwarg is sent.
- [ ] AC-4: `git diff --stat` — `endcap_backlit_multitier.py` 12 insertions / 18 deletions, `graphic_panel_display.py` 8 insertions / 12 deletions, nothing else.
- [ ] AC-5: existing suites for these types still pass (`pytest packages/ai-parrot-pipelines/tests/test_planogram_types.py -q`).
- [ ] `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types` passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_panel_types.py -q`

---

## Test Specification

```python
@pytest.mark.parametrize("name,sites", sorted(_EXPECTED_SITES.items()))
def test_no_literals_and_site_count(name, sites): ...

async def test_graphic_panel_illumination_uses_pipeline_llm():
    pipeline, client = _pipeline(model="claude-sonnet-5")
    handler = GraphicPanelDisplay(pipeline=pipeline, config=<config mock>)
    await handler._check_illumination_from_roi(<args per :651>)
    kwargs = client.ask_to_image.await_args.kwargs
    assert kwargs["no_memory"] is True and kwargs["model"] == "claude-sonnet-5" and kwargs["max_tokens"] == 16
    pipeline.roi_client.__aenter__.assert_not_called()

async def test_backlit_compute_roi_uses_pipeline_llm(): ...
async def test_model_omitted_when_backend_has_none(): ...
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
7. **Move this file** to `tasks/completed/TASK-3431-neutral-callsites-panel-types.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (FEAT-574 orchestrator)
**Date**: 2026-09-19

Implemented in fallback sequential mode (parrot-sdd-coder server unresponsive).
Closed worklist rewritten (10 sites: EndcapBacklitMultitier x6, GraphicPanelDisplay x4): async with self.pipeline.llm + **self._vision_kwargs(); max_tokens/structured_output preserved; diff exactly 12+/18- and 8+/12-.
Tests: test_neutral_panel_types.py 5 passed; test_planogram_types.py 26, tests/pipelines/test_abstract_type_grid.py 4, packages/ai-parrot/tests/test_graphic_panel_display.py 13 — all green. No new ruff findings vs origin/dev.

Seat: orchestrator (fallback) · Backend: native · Model: claude-opus-5 · Attempts: 1
