# TASK-3420: Shared test conftest with FakeVisionClient and synthetic image fixtures

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 3** ("Legacy characterization tests + fake vision client") and
§4 require every FEAT-574 test to run **offline**: synthetic images, a fake LLM,
no network. Today `packages/ai-parrot-pipelines/tests/` has **no** `conftest.py`
and no fake-LLM fixture — fakes are inline `MagicMock`s
(`tests/test_planogram_types.py:96-109`). This task creates the one shared
conftest that later characterization and cycle tests load: a queue-driven
`FakeVisionClient` (modelled on `examples/planogram/tests/conftest.py:187`
`FakeBackend`, *re-implemented*, never imported) plus two fixtures.

This task is **exclusive** (`parallel: false`): it creates a `conftest.py` that
every other test module in that tree loads at collection time.

---

## Scope

- Create `packages/ai-parrot-pipelines/tests/conftest.py` with:
  - `FakeAIMessage` — tiny response object exposing `.output` and
    `.structured_output` (what legacy call sites read: `msg.output`).
  - `FakeVisionClient` — the spec Module 3 skeleton **verbatim** (class name,
    attribute names, method signatures).
  - Fixtures `fake_vision_client` and `synthetic_shelf_image`.
- Create `packages/ai-parrot-pipelines/tests/planogram_cycle/test_fake_vision_client.py`
  proving the fake's contract (queue order, exception raising, callable
  responses, async-context-manager use, call recording, default response).
- The existing tests in the same tree (`tests/test_planogram_types.py`,
  `tests/test_endcap_no_shelves_promotional.py`) must still collect and pass
  with the new conftest present.

**NOT in scope**: any characterization test (TASK-3422 / TASK-3423 / TASK-3424);
any production code; adding an `__init__.py` to `tests/planogram_cycle/` (that
folder deliberately has none — test basenames are unique); editing existing test
files; any fixture for the new cycle's contracts (later tasks add their own
fixtures inside their own test files).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/tests/conftest.py` | CREATE | `FakeAIMessage`, `FakeVisionClient`, fixtures `fake_vision_client`, `synthetic_shelf_image` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_fake_vision_client.py` | CREATE | Contract tests of the fake and the synthetic image |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
import pytest                      # test dependency, already used: tests/test_planogram_types.py:7
from PIL import Image, ImageDraw   # pillow; used by parrot_pipelines/abstract.py:5
```
No `parrot` / `parrot_pipelines` import is needed (or allowed) in the conftest —
it must stay importable even when a provider client is missing.

### Existing Signatures to Use
```python
# How legacy call sites consume a vision client TODAY — the fake must satisfy all three:

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py:234-241
async with self.pipeline.roi_client as client:          # async context manager → needs __aenter__/__aexit__
    msg = await client.ask_to_image(image=roi_small, prompt=prompt, model="gemini-3.5-flash",
                                    no_memory=True, max_tokens=128)     # ALL keyword arguments
raw_answer = (msg.output or "").strip().upper()         # reads .output

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:330-335
raw = await self.pipeline.llm.detect_objects(image=target_image, prompt=obj_prompt,
                                             reference_images=refs, output_dir=None)   # NO context manager

# packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py:33-34
self.llm_provider = llm.client_name.lower()             # a client passed as llm= must expose .client_name

# Reference only (NEVER import it): examples/planogram/tests/conftest.py:187  class FakeBackend
#   __init__(self, *, is_local=False) :190 — self.calls: list[dict], self.queue: dict[str, list]
#   async ask(...) :195 — appends to self.calls, pops the stage queue; Exception → raised, callable → called

# Existing tests that will load the new conftest (must keep passing, do not edit):
# packages/ai-parrot-pipelines/tests/test_planogram_types.py          (own fixtures: mock_pipeline :96, …)
# packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py
# packages/ai-parrot-pipelines/tests/__init__.py                       (exists — tests/ IS a package)
```

### Does NOT Exist
- ~~`packages/ai-parrot-pipelines/tests/conftest.py`~~ — this task creates it.
- ~~`packages/ai-parrot-pipelines/tests/planogram_cycle/`~~ — directory does not exist yet; create it **without** `__init__.py`.
- ~~any fake-LLM fixture anywhere in `packages/ai-parrot-pipelines/tests/` or `tests/pipelines/`~~ — only inline `MagicMock`s.
- ~~`AbstractClient.ask_to_image`~~ — not declared on the base client; it is a duck-typed per-provider method, which is why a plain class (not a subclass) is the right fake.
- ~~`plancheck` importability~~ — `examples/planogram/plancheck/` is a bare directory; do not import `FakeBackend`.
- ~~`AIMessage(output=...)` cheap constructor~~ — do not build real `AIMessage` objects; use `FakeAIMessage`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/tests/conftest.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_fake_vision_client.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType._check_illumination",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._detect_legacy",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py#AbstractPipeline.__init__",
    "sym:examples/planogram/tests/conftest.py#FakeBackend"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Queue-per-method fake, same idea as `examples/planogram/tests/conftest.py:187-203`
(queue per *stage* there, per *method name* here).

### Key Constraints
- **Provider-neutral durability**: a later task swaps `pipeline.roi_client` for
  `pipeline.llm`. Tests built on this fake assign the **same** `FakeVisionClient`
  object to both attributes, so the fake must work both as an async context
  manager (`async with fake as client`) and called directly
  (`await fake.detect_objects(...)`). `__aenter__` returns `self`.
- `ask_to_image` must accept **keyword-only style calls** (`image=…, prompt=…`)
  and arbitrary extra kwargs (`model`, `no_memory`, `max_tokens`,
  `structured_output`, `reference_images`, `system_prompt`, …) without raising.
- Every call is recorded in `self.calls` as a dict with at least
  `{"method", "prompt", "image", "kwargs"}`; record the **image size** too
  (`image_size`, `None` when the image is not a PIL image) — characterization
  tests assert on crop sizes.
- An **empty queue is not an error**: return `FakeAIMessage(output=self.default_output)`
  for `ask_to_image` and `[]` for `detect_objects`. Legacy `run()` makes an
  unpredictable number of auxiliary calls; tests queue only what they care about.
- No `print`; no network; no import of `parrot*` in the conftest.
- Google-style docstrings + type hints (repo rule), even in test helpers.
- Run with the worktree source on the path:
  `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src pytest <file> -q`
  (the shared `.venv` is editable-installed against the main checkout). Never `uv sync`.

### References in Codebase
- `examples/planogram/tests/conftest.py:187-203` — queue-driven fake (reference only)
- `packages/ai-parrot-pipelines/tests/test_planogram_types.py:96-109` — today's inline mock pipeline

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Create the folder `packages/ai-parrot-pipelines/tests/planogram_cycle/` with **no** `__init__.py` — *why*: test basenames are unique by plan; an `__init__.py` here would be a file other parallel tasks also need to create (overlap).
2. Write `conftest.py` from the block below — *why*: the class/fixture names are fixed by spec §3 Module 3 and consumed by TASK-3423, TASK-3424 and later cycle tests.
3. Complete the two `FILL IN` markers in `ask_to_image` / `synthetic_shelf_image` — *why*: response coercion and the drawing are the only judgement calls.
4. Write the test file and fill its bodies — *why*: it is this task's Validation Command.
5. Run the new test file **and** the two pre-existing test files of the same tree — *why*: a conftest is loaded by all of them; a collection error there is this task's regression.

### `packages/ai-parrot-pipelines/tests/conftest.py` (CREATE)
```python
"""Shared offline test helpers for ai-parrot-pipelines (FEAT-574).

Provides a queue-driven fake vision client and synthetic images so planogram
tests never touch the network or a real store photo.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from PIL import Image, ImageDraw


class FakeAIMessage:
    """Minimal stand-in for a provider ``AIMessage``.

    Attributes:
        output: Text (or object) the legacy call sites read via ``msg.output``.
        structured_output: Parsed structured answer, when one was queued.
    """

    def __init__(self, output: Any = "", structured_output: Any = None) -> None:
        self.output = output
        self.structured_output = structured_output
```

### `packages/ai-parrot-pipelines/tests/conftest.py` (CREATE) — continued, part 2/2 (same file: append directly below the previous block)
```python
class FakeVisionClient:
    """Offline stand-in for a provider client. Records calls; pops canned responses per method."""

    client_name: str = "fake"
    model: Optional[str] = None

    def __init__(self, default_output: str = "") -> None:
        self.calls: List[Dict[str, Any]] = []
        self.default_output: str = default_output
        self._queues: Dict[str, List[Any]] = {"ask_to_image": [], "detect_objects": []}

    def queue(self, method: str, *responses: Any) -> None:
        """Append canned responses for ``method`` (``"ask_to_image"`` | ``"detect_objects"``).

        Raises:
            KeyError: If ``method`` is not a fakeable method name.
        """
        self._queues[method].extend(responses)

    def calls_to(self, method: str) -> List[Dict[str, Any]]:
        """Return the recorded calls of one method, in call order."""
        return [c for c in self.calls if c["method"] == method]

    def _record(self, method: str, prompt: str, image: Any, kwargs: Dict[str, Any]) -> None:
        size = getattr(image, "size", None)
        self.calls.append(
            {"method": method, "prompt": prompt, "image": image, "image_size": size, "kwargs": dict(kwargs)}
        )

    async def ask_to_image(self, prompt: str, image: Any, **kwargs: Any) -> Any:
        """Returns an object with .output / .structured_output, or raises a queued Exception."""
        self._record("ask_to_image", prompt, image, kwargs)
        if not self._queues["ask_to_image"]:
            return FakeAIMessage(output=self.default_output)
        item = self._queues["ask_to_image"].pop(0)
        # FILL IN: coerce `item` — bounded by: Exception instance → raise it; callable → item = item(prompt, image, kwargs)
        #          (then coerce the result); FakeAIMessage → return as is; str → FakeAIMessage(output=item);
        #          anything else (e.g. a Pydantic model) → FakeAIMessage(output=item, structured_output=item).
        raise NotImplementedError

    async def detect_objects(
        self, image: Any, prompt: str, reference_images: Any = None, output_dir: Any = None, **kwargs: Any
    ) -> List[Dict[str, Any]]:
        """Return the next queued list of detection dicts (``[]`` when the queue is empty)."""
        self._record("detect_objects", prompt, image, {"reference_images": reference_images,
                                                       "output_dir": output_dir, **kwargs})
        if not self._queues["detect_objects"]:
            return []
        item = self._queues["detect_objects"].pop(0)
        if isinstance(item, Exception):
            raise item
        return item(prompt, image, kwargs) if callable(item) else item

    async def __aenter__(self) -> "FakeVisionClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


@pytest.fixture
def fake_vision_client() -> FakeVisionClient:
    """A fresh queue-driven fake client (assign it to BOTH ``pipeline.llm`` and ``pipeline.roi_client``)."""
    return FakeVisionClient()


@pytest.fixture
def synthetic_shelf_image() -> Image.Image:
    """An 800x1000 RGB synthetic endcap: bright header band, three shelf boards, a few product boxes."""
    img = Image.new("RGB", (800, 1000), (40, 40, 45))
    draw = ImageDraw.Draw(img)
    # FILL IN: draw the scene — bounded by: header band y∈[0,200) bright; shelf boards (thin light
    #          rectangles) at y≈500, 750, 980; 2-3 coloured product rectangles standing on each board;
    #          deterministic (no randomness); must stay 800x1000 RGB.
    return img
```
**Why this shape**: the class name, `client_name`, `model`, `calls`, `queue`,
`ask_to_image`, `detect_objects`, `__aenter__`/`__aexit__` and both fixture
names are fixed by the spec's Module 3 skeleton — later tasks reference them by
name. `FakeAIMessage`, `calls_to`, `default_output` and `image_size` are
additive helpers: legacy code reads `msg.output`, and characterization tests
assert crop sizes. The empty-queue default exists because legacy `run()` issues
auxiliary calls a test does not care about.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_fake_vision_client.py` (CREATE)
```python
"""Contract tests for the shared FakeVisionClient fixture (FEAT-574, TASK-3420)."""
from __future__ import annotations

from typing import Any

import pytest
from PIL import Image


@pytest.mark.asyncio
async def test_ask_to_image_pops_queue_in_order(fake_vision_client: Any) -> None:
    """Queued strings come back in order, wrapped with ``.output``."""
    fake_vision_client.queue("ask_to_image", "first", "second")
    img = Image.new("RGB", (10, 20))
    a = await fake_vision_client.ask_to_image(image=img, prompt="p1", model="whatever", no_memory=True)
    b = await fake_vision_client.ask_to_image(prompt="p2", image=img)
    assert (a.output, b.output) == ("first", "second")
    # FILL IN: assert the two recorded calls — bounded by: method == "ask_to_image", prompts "p1"/"p2",
    #          image_size == (10, 20), kwargs of the first call contain no_memory=True.


@pytest.mark.asyncio
async def test_empty_queue_returns_default_output(fake_vision_client: Any) -> None:
    """An empty queue is not an error."""
    # FILL IN: bounded by: ask_to_image → .output == "" ; detect_objects → [].


@pytest.mark.asyncio
async def test_queued_exception_is_raised(fake_vision_client: Any) -> None:
    """A queued Exception instance is raised by the call (and the call is still recorded)."""
    fake_vision_client.queue("ask_to_image", RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        await fake_vision_client.ask_to_image(prompt="p", image=None)
    assert len(fake_vision_client.calls) == 1


@pytest.mark.asyncio
async def test_callable_and_structured_responses(fake_vision_client: Any) -> None:
    """Callables receive (prompt, image, kwargs); non-str objects land in ``.structured_output``."""
    # FILL IN: bounded by: queue a lambda returning "X:" + prompt and assert .output;
    #          queue a dict (or Pydantic model) and assert .structured_output is that object.


@pytest.mark.asyncio
async def test_works_as_async_context_manager(fake_vision_client: Any) -> None:
    """``async with fake as client`` yields the same object (legacy roi_client idiom)."""
    async with fake_vision_client as client:
        assert client is fake_vision_client


@pytest.mark.asyncio
async def test_detect_objects_records_and_returns_queue(fake_vision_client: Any) -> None:
    """detect_objects returns the queued list and records keyword arguments."""
    boxes = [{"label": "printer", "box_2d": [1, 2, 30, 40], "confidence": 0.9}]
    fake_vision_client.queue("detect_objects", boxes)
    got = await fake_vision_client.detect_objects(image=None, prompt="find", reference_images=None, output_dir=None)
    assert got == boxes
    assert fake_vision_client.calls_to("detect_objects")[0]["prompt"] == "find"


def test_unknown_method_queue_raises(fake_vision_client: Any) -> None:
    """Queuing an unknown method is a programming error."""
    with pytest.raises(KeyError):
        fake_vision_client.queue("generate", "x")


def test_synthetic_shelf_image_is_deterministic(synthetic_shelf_image: Image.Image) -> None:
    """Size/mode are fixed and the header band is brighter than the wall."""
    assert synthetic_shelf_image.size == (800, 1000)
    assert synthetic_shelf_image.mode == "RGB"
    # FILL IN: bounded by: mean brightness of crop (0,0,800,200) > mean brightness of crop (0,250,800,450).
```
**Why this shape**: the test file uses the fixtures only (no import of the
conftest module — `tests/planogram_cycle/` has no `__init__.py`, so a
`from tests.conftest import …` would be fragile). If `pytest-asyncio` runs in
`auto` mode in this repo the `@pytest.mark.asyncio` marks are harmless; keep them.

### FILL IN checklist
- [ ] `conftest.py::FakeVisionClient.ask_to_image` — response coercion; bounded by the five cases listed in the marker
- [ ] `conftest.py::synthetic_shelf_image` — deterministic drawing; bounded by 800x1000 RGB, bright header, three boards
- [ ] `test_fake_vision_client.py::test_ask_to_image_pops_queue_in_order` — call-record assertions
- [ ] `test_fake_vision_client.py::test_empty_queue_returns_default_output` — body
- [ ] `test_fake_vision_client.py::test_callable_and_structured_responses` — body
- [ ] `test_fake_vision_client.py::test_synthetic_shelf_image_is_deterministic` — brightness assertion

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-pipelines/tests/conftest.py` defines `FakeAIMessage`, `FakeVisionClient`, `fake_vision_client`, `synthetic_shelf_image` with the exact names/signatures above
- [ ] `FakeVisionClient` works both as `async with fake as client:` and called directly; accepts keyword-only calls and arbitrary kwargs; records every call
- [ ] Empty queue ⇒ default response (no exception); queued `Exception` ⇒ raised
- [ ] The conftest imports nothing from `parrot*`
- [ ] No `__init__.py` was added under `tests/planogram_cycle/`
- [ ] Pre-existing tests of the tree still pass: `pytest packages/ai-parrot-pipelines/tests/test_planogram_types.py packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py -q`
- [ ] No linting errors: `ruff check packages/ai-parrot-pipelines/tests/conftest.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_fake_vision_client.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_fake_vision_client.py -q`

---

## Test Specification

The blueprint's test file **is** the test specification (8 tests):
`test_ask_to_image_pops_queue_in_order`, `test_empty_queue_returns_default_output`,
`test_queued_exception_is_raised`, `test_callable_and_structured_responses`,
`test_works_as_async_context_manager`, `test_detect_objects_records_and_returns_queue`,
`test_unknown_method_queue_raises`, `test_synthetic_shelf_image_is_deterministic`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 3, §4 Test Data / Fixtures)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm the three call-site idioms quoted above still exist
4. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
5. **Verify** all acceptance criteria, including the two pre-existing test files
6. **Commit code only** — never touch `sdd/`; the orchestrator moves this file and updates the index
7. **Fill in the Completion Note** below (the orchestrator persists it)

---

## Completion Note

**Completed by**: sdd-worker (FEAT-574 orchestrator)
**Date**: 2026-09-19

Implemented in fallback sequential mode (parrot-sdd-coder server hung; the first MCP dispatch to gpt-5.6-terra never ran — engine reported 'native tasks use prepare_native', 0 attempts).
conftest.py: FakeAIMessage, FakeVisionClient (queue per method, call recording incl. image_size, exception/callable/structured coercion, async context manager), fixtures fake_vision_client and synthetic_shelf_image. No parrot imports; no __init__.py in planogram_cycle/.
Tests: test_fake_vision_client.py 8 passed; test_planogram_types.py passes; test_endcap_no_shelves_promotional.py::test_status_not_missing_when_found fails identically on origin/dev (pre-existing).

Seat: orchestrator (fallback) · Backend: native · Model: claude-opus-5 · Attempts: 1
