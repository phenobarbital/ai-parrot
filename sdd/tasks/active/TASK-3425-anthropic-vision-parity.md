# TASK-3425: AnthropicClient vision parity — `ask_to_image(no_memory, model resolution)` + `detect_objects`

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 4** (goal G11 — provider-neutral). The planogram pipeline must be
drivable end-to-end by either a Google or an Anthropic client. Today the two vision
surfaces differ:

- `AnthropicClient.ask_to_image` has **no `no_memory` kwarg** (Google and OpenAI do), so a
  provider-neutral call site passing `no_memory=True` raises `TypeError` on Anthropic.
- Its `model` parameter defaults to `ClaudeModel.SONNET_4`. Because a non-`None` default
  always wins inside `_resolve_model`, that default **masks the model the client was
  configured with** (`AnthropicClient(model="claude-sonnet-5")` still calls SONNET_4).
- `detect_objects` exists only on the Google client; legacy planogram call sites
  (`llm.detect_objects(...)`) cannot run on Anthropic.

This task lives in a different distribution (`ai-parrot-client-anthropic`) and shares no
file with any pipeline task.

---

## Scope

- Add `no_memory: bool = False` as the **last** parameter of `AnthropicClient.ask_to_image`.
  `no_memory=True` ⇒ no history is replayed. Nothing else changes: the method already
  touches no conversation memory (FEAT-524).
- Change the `model` parameter of `ask_to_image` to `Union[ClaudeModel, str, None] = None`
  and resolve it as: explicit `model` → `self.model` → `ClaudeModel.SONNET_5`, then
  `self._resolve_model()`. Use the resolved value for **both** the payload and the
  `AIMessageFactory.from_claude(model=...)` call.
- Add `AnthropicClient.detect_objects(image, prompt, reference_images=None, output_dir=None, *, model=None)`
  mirroring the Google positional signature and return-dict shape. Built on
  `self.ask_to_image(..., structured_output=<box schema>, no_memory=True)`.
- Write `tests/unit/test_vision_parity.py` (offline, mocked SDK).

**NOT in scope**: the Google client (its `detect_objects` keeps its hard-coded model —
spec §8 open question); the OpenAI client; any file under `packages/ai-parrot-pipelines/`;
the provider-neutral adapter that will call these methods (a later task); tool-use based
structured output (keep the existing JSON-prompt + `_parse_structured_output` path).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py` | MODIFY | `ask_to_image`: `no_memory`, model resolution; new `detect_objects` + box schema models |
| `packages/ai-parrot-client-anthropic/tests/unit/test_vision_parity.py` | CREATE | Offline unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# Already imported at the top of client.py — do NOT re-import:
from typing import AsyncIterator, Dict, List, Literal, Optional, Sequence, Union, Any, TYPE_CHECKING  # client.py:3
from pathlib import Path                                  # client.py:11
from pydantic import BaseModel, Field                     # client.py:13
from ...memory.render import HistoryMessage               # client.py:19
from ...models import AIMessage, AIMessageFactory, StructuredOutputConfig  # client.py:50-58 (block)
from ...exceptions import InvokeError                     # client.py:60
from .models import ClaudeModel                           # client.py:61
# `Image` is imported ONLY under TYPE_CHECKING (client.py:49) — the module has
# `from __future__ import annotations` (client.py:1), so annotations are fine, but any
# RUNTIME use of PIL needs a lazy import inside the method, as client.py:1265 does:
#     from PIL import Image

# For the test file:
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.clients.anthropic import AnthropicClient      # verified: tests/unit/test_claude_multiround_usage.py:17
from parrot.clients.anthropic.models import ClaudeModel   # verified: .../anthropic/models.py:4
```

### Existing Signatures to Use
```python
# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py
class AnthropicClient(AbstractClient):                                   # :75
    _default_model: str = "claude-sonnet-4-5"                            # :88
    # self.model comes from AbstractClient.__init__: kwargs.get("model", None)
    #   (packages/ai-parrot/src/parrot/clients/base.py:391) — it IS None when the caller gave none.

    def _resolve_model(self, model) -> str:                              # :256-273
        # raw = (model.value if isinstance(model, ClaudeModel) else model) or (self.model or self.default_model)
        # return self._backend.translate_model(raw)                      # :272-273

    async def _sdk_create(self, payload: dict):                          # :358-360
        # return await self.client.messages.create(**self._sanitize_payload_for_model(payload))

    def _encode_image_for_claude(self, image) -> Dict[str, Any]:         # :1262-1305 (Path | bytes | PIL.Image)

    async def ask_to_image(                                              # :1307-1483
        self, prompt: str, image: Union[Path, bytes, Image.Image],
        reference_images: Optional[List[Union[Path, bytes, Image.Image]]] = None,
        model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4,           # :1312
        max_tokens: Optional[int] = None, temperature: Optional[float] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        count_objects: bool = False,
        history: Optional[Sequence[HistoryMessage]] = None,
        system_prompt: Optional[str] = None,
        context_1m: bool = False,                                        # :1319
    ) -> AIMessage:                                                      # :1320
    #   :1352  messages = self._format_history(history or ())           (the ONLY history use)
    #   :1382  "model": self._resolve_model(model),                      (inside the ask_to_image payload)
    #   :1435  response = await self._sdk_create(payload); result = response.model_dump()
    #   :1447-1456 structured_output ⇒ final_output = await self._parse_structured_output(text, output_config, ...)
    #   :1465-1474 AIMessageFactory.from_claude(..., model=model.value if isinstance(model, ClaudeModel) else model,
    #              structured_output=final_output, ...)   → result is read back as `ai_message.structured_output`
    async def summarize_text(...)                                        # :1485 (next method — insert detect_objects BEFORE it)

# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/models.py
class ClaudeModel(Enum):                                                 # :4
    SONNET_5 = "claude-sonnet-5"                                         # :15
    SONNET_4 = "claude-sonnet-4-20250514"                                # :33

# Reference shape to MIRROR (do not import) —
# packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py:1234-1239
async def detect_objects(self, image: Union[str, Path, Image.Image], prompt: str,
    reference_images: Optional[List[Union[str, Path, Image.Image]]] = None,
    output_dir: Optional[Union[str, Path]] = None) -> List[Dict[str, Any]]
#   model answers with box_2d = [ymin, xmin, ymax, xmax] normalised 0-1000            (:1321-1322)
#   y0=int(box[0]/1000*H); x0=int(box[1]/1000*W); y1=int(box[2]/1000*H); x1=int(box[3]/1000*W)   (:1324-1327)
#   degenerate (y0 >= y1 or x0 >= x1) ⇒ skipped                                        (:1329-1330)
#   item = {"label": item.get("label","unknown"), "box_2d": [x0, y0, x1, y1], "confidence": item.get("confidence", 1.0),
#           "mask_image": None, "overlay_image": None} + passthrough of other keys except "mask"/"box_2d"   (:1332-1341)
#   unparseable answer ⇒ returns []   ;   output_dir ⇒ os.makedirs(output_dir, exist_ok=True)  (:1306)

# Test scaffold pattern — packages/ai-parrot-client-anthropic/tests/unit/test_claude_multiround_usage.py:48-59
#   client = AnthropicClient(api_key="fake_key"); client.logger = MagicMock()
#   mock_sdk_client = MagicMock(); mock_sdk_client.messages.create = AsyncMock(side_effect=[...])
#   client._backend = MagicMock(); client._backend.build_client = AsyncMock(return_value=mock_sdk_client)
#   client._backend.translate_model = lambda m: m
#   response mock: resp.model_dump.return_value = {"id","type","role","content":[{"type":"text","text":...}],
#                  "model","stop_reason","usage":{"input_tokens":..,"output_tokens":..}}      (:25-36)
# pytest.ini: asyncio_mode = auto  → plain `async def test_*` works, no decorator needed.
```

### Does NOT Exist
- ~~`no_memory` on `AnthropicClient.ask_to_image`~~ — this task adds it.
- ~~`AnthropicClient.detect_objects`~~ — zero hits in the package; this task adds it.
- ~~mixins / an `analysis.py` in the anthropic package~~ — `AnthropicClient` inherits only `AbstractClient`; put the method in `client.py`.
- ~~`AbstractClient.ask_to_image` / `AbstractClient.detect_objects`~~ — not declared in `parrot/clients/base.py`; duck-typed per provider.
- ~~module-level runtime `Image` in `client.py`~~ — TYPE_CHECKING only (`client.py:49`); lazy-import PIL inside methods.
- ~~`import os` in `client.py`~~ — not imported; use `Path(output_dir).mkdir(parents=True, exist_ok=True)`.
- ~~masks / segmentation on Anthropic~~ — `mask_image` and `overlay_image` are always `None`; nothing is written to `output_dir`.
- ~~tool-use structured output in `ask_to_image`~~ — it is JSON system-prompt + `_parse_structured_output` (`client.py:1390-1456`).
- ~~an existing test for `ask_to_image`~~ — none in `tests/unit/`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-client-anthropic/tests/unit/test_vision_parity.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py#AnthropicClient",
    "sym:packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py#AnthropicClient.ask_to_image",
    "sym:packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py#AnthropicClient._resolve_model",
    "sym:packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py#AnthropicClient._sdk_create",
    "sym:packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/models.py#ClaudeModel"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# Google's equivalent history gate — packages/ai-parrot-client-google/src/parrot/clients/google/client.py:5026
_rendered = () if no_memory else (history or ())
history = self._format_history(_rendered)
```

### Key Constraints
- **Non-breaking signature**: `no_memory` goes LAST in `ask_to_image`; every existing positional/keyword call keeps working.
- A method default must never override a caller's selection: `model=None` is the new default; the
  SONNET_5 fallback applies only when neither the call nor the client names a model.
- `detect_objects` never raises for a bad model answer or a failed call: catch `Exception`
  (including `InvokeError`), log with `self.logger.error`, return `[]` — Google parity (parse
  failure ⇒ `[]`). Never swallow `asyncio.CancelledError`.
- `context_1m: bool = False,` occurs 7 times in `client.py` (verified: grep -c) — locate the one
  inside `async def ask_to_image(` (unique), never by that line alone.
- Coordinates returned are **original-image pixels**, `[x1, y1, x2, y2]`.
- Google-style docstrings, strict type hints, `self.logger` — never `print`.
- Run tests inside the worktree with
  `PYTHONPATH=packages/ai-parrot-client-anthropic/src:packages/ai-parrot/src` (the shared venv is
  editable-installed against the main checkout). Never `uv sync` in the worktree.
- Before editing, grep for other callers relying on the SONNET_4 default:
  `grep -rn "ask_to_image(" packages --include=*.py | grep -v "/tests/"` — note any Anthropic caller in the Completion Note; do not edit them.

### References in Codebase
- `packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py:1234-1378` — return shape to mirror
- `packages/ai-parrot-client-anthropic/tests/unit/test_claude_multiround_usage.py:25-59` — SDK mocking pattern

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Edit the `ask_to_image` signature (block A) — *why*: `model=None` stops the method default from masking the client's model; `no_memory` last keeps the change non-breaking.
2. Insert the model-resolution lines and gate the history line (block B) — *why*: one resolved value must feed both the payload and the `AIMessage`, otherwise the message reports `None`.
3. Replace the two later uses of `model` inside `ask_to_image` (block C) — *why*: `_resolve_model(None)` would otherwise fall to `_default_model` (`claude-sonnet-4-5`) instead of SONNET_5.
4. Add the two schema models at module level and `detect_objects` before `summarize_text` (block D) — *why*: the pipeline's legacy call sites call `llm.detect_objects(...)` positionally exactly like Google's.
5. Write the tests (block E) and run the Validation Command — *why*: there is no existing coverage for this method.

### `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py` (MODIFY) — block A: signature
```python
# occurrences: 6 (verified: grep -c 'model: Union\[ClaudeModel, str\] = ClaudeModel.SONNET_4,' client.py)
# → NOT unique. Disambiguated anchor — edit ONLY inside the def that starts at client.py:1307:
#       async def ask_to_image(
#           self,
#           prompt: str,
#           image: Union[Path, bytes, Image.Image],
# occurrences of 'async def ask_to_image(': 1 (verified: grep -c)
# REPLACE these two lines of that signature:
        model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4,      # client.py:1312
        context_1m: bool = False,                                    # client.py:1319 (last param today)
# WITH:
        model: Union[ClaudeModel, str, None] = None,
        context_1m: bool = False,
        no_memory: bool = False,
```
**Why**: spec Module 4 skeleton fixes `model: Union[ClaudeModel, str, None] = None` and `no_memory` in last
position. Also extend the docstring `Args:` with both parameters (no_memory: "skip replaying `history`";
model: "explicit → client's configured model → `ClaudeModel.SONNET_5`").

### `.../anthropic/client.py` (MODIFY) — block B: history gate + model resolution
```python
# occurrences: 1 (verified: grep -c 'messages = self._format_history(history or ())' client.py)
# REPLACE `        messages = self._format_history(history or ())` (verified: client.py:1352) WITH:
        # FEAT-574: explicit model → client's configured model → SONNET_5. A method
        # default must never mask the caller's or the client's selection.
        model = model or self.model or ClaudeModel.SONNET_5
        messages = self._format_history(() if no_memory else (history or ()))
```
**Why**: `self.model` is `None` when the client was built without a model (`base.py:391`), so the chain is
well-defined. `no_memory` only gates history replay — the method performs no memory read/write (FEAT-524, `client.py:1461`).

### `.../anthropic/client.py` (MODIFY) — block C: no further edits needed if block B is applied
```python
# `"model": self._resolve_model(model),` occurs 6 times in the file (verified: grep -c) — DO NOT touch the others.
# Inside ask_to_image (client.py:1382 and :1468) `model` is now already resolved by block B, so both existing
# expressions keep working unchanged:
#     "model": self._resolve_model(model),                                   # :1382
#     model=model.value if isinstance(model, ClaudeModel) else model,        # :1468
# FILL IN: verify both lines still read the local `model` AFTER block B's assignment (block B must sit above
#          the payload construction) — bounded by AC "model resolution".
```
**Why**: keeps the diff minimal; `_resolve_model` still applies backend (Bedrock) translation.

### `.../anthropic/client.py` (MODIFY) — block D: schema models + `detect_objects`
```python
# Module level — insert AFTER the import block, before `class AnthropicClient` (verified: client.py:75).
class _NormalizedObjectBox(BaseModel):
    """One detected object; box is [ymin, xmin, ymax, xmax] normalised to 0-1000."""

    label: str = Field(default="unknown")
    box_2d: List[int] = Field(..., min_length=4, max_length=4)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class _NormalizedObjectBoxes(BaseModel):
    """Structured-output envelope for ``AnthropicClient.detect_objects``."""

    objects: List[_NormalizedObjectBox] = Field(default_factory=list)


# Method — occurrences: 1 (verified: grep -c '    async def summarize_text(' client.py)
# BEFORE — insert above `    async def summarize_text(` (verified: client.py:1485)
    async def detect_objects(
        self,
        image: Union[str, Path, Image.Image],
        prompt: str,
        reference_images: Optional[List[Union[str, Path, Image.Image]]] = None,
        output_dir: Optional[Union[str, Path]] = None,
        *,
        model: Union[ClaudeModel, str, None] = None,
    ) -> List[Dict[str, Any]]:
        """Detect objects in an image, mirroring the Google client's contract.

        Args:
            image: Path (str or Path) or PIL image.
            prompt: Caller-supplied detection prompt (no built-in prompt text).
            reference_images: Optional reference images.
            output_dir: Created when given; nothing is written (no masks on Anthropic).
            model: Optional model; same resolution order as ``ask_to_image``.

        Returns:
            Dicts ``{"label", "box_2d": [x1, y1, x2, y2] in ORIGINAL-image pixels, "confidence",
            "mask_image": None, "overlay_image": None, **passthrough}``. ``[]`` when the
            answer cannot be parsed — never raises for a bad model answer.
        """
        from PIL import Image as _PILImage  # lazy: PIL is TYPE_CHECKING-only at module level

        if output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
        pil = _PILImage.open(str(image)) if isinstance(image, (str, Path)) else image
        width, height = pil.size
        refs = [Path(r) if isinstance(r, str) else r for r in (reference_images or [])] or None
        # FILL IN: build `full_prompt` = prompt + an instruction to answer with `objects[]`, each with
        #          label, confidence and box_2d=[ymin, xmin, ymax, xmax] normalised 0-1000 — bounded by
        #          the _NormalizedObjectBoxes schema above.
        try:
            message = await self.ask_to_image(
                prompt=full_prompt, image=pil, reference_images=refs, model=model,
                structured_output=_NormalizedObjectBoxes, no_memory=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - Google parity: bad answer ⇒ []
            self.logger.error("detect_objects failed: %s", exc)
            return []
        # FILL IN: read `message.structured_output`; if it is not a _NormalizedObjectBoxes instance → return [].
        #          For each object: convert with the Google formulas (contract above), skip degenerate boxes
        #          (y0 >= y1 or x0 >= x1), clamp to [0,width]/[0,height], build the dict in the documented
        #          key order — bounded by AC "detect_objects shape".
        return results
```
**Why this shape**: positional parameters are byte-identical to Google's so `llm.detect_objects(image=, prompt=,
reference_images=, output_dir=None)` works on either client; `model` is keyword-only so it cannot shift a
positional call. `asyncio` is already imported (`client.py:2`). PIL is imported lazily because the module-level
`Image` exists only for type checkers.

### `packages/ai-parrot-client-anthropic/tests/unit/test_vision_parity.py` (CREATE) — block E
```python
"""Unit tests for AnthropicClient vision parity (FEAT-574, spec Module 4). Offline: SDK mocked."""
from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock, MagicMock
from PIL import Image

from parrot.clients.anthropic import AnthropicClient
from parrot.clients.anthropic.models import ClaudeModel
from parrot.memory.render import HistoryMessage


def _response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.model_dump.return_value = {
        "id": "msg_1", "type": "message", "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": "claude-sonnet-5", "stop_reason": "end_turn",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    return resp


def _make_client(texts: list[str], **kwargs) -> tuple[AnthropicClient, MagicMock]:
    client = AnthropicClient(api_key="fake_key", **kwargs)
    client.logger = MagicMock()
    sdk = MagicMock()
    sdk.messages.create = AsyncMock(side_effect=[_response(t) for t in texts])
    client._backend = MagicMock()
    client._backend.build_client = AsyncMock(return_value=sdk)
    client._backend.translate_model = lambda m: m
    return client, sdk


@pytest.fixture
def image() -> Image.Image:
    return Image.new("RGB", (200, 100), "white")

# FILL IN: test bodies per the Test Specification below. Read the SDK call with
#          `sdk.messages.create.call_args.kwargs` (keys: "model", "messages", ...).
#          If HistoryMessage's constructor differs, check packages/ai-parrot/src/parrot/memory/render.py first.
```
**Why**: same mocking seam as the existing FEAT-397 test, so no network and no real SDK are needed.

### FILL IN checklist
- [ ] `client.py::ask_to_image` docstring — document `no_memory` and the model resolution order
- [ ] `client.py::ask_to_image` block C — confirm block B sits above the payload; no other of the 6 look-alike lines touched
- [ ] `client.py::detect_objects` — `full_prompt` wording; bounded by the `_NormalizedObjectBoxes` schema
- [ ] `client.py::detect_objects` — conversion loop; bounded by the Google formulas and the degenerate-box rule
- [ ] `test_vision_parity.py` — the five test bodies; bounded by the Test Specification

---

## Acceptance Criteria

- [ ] `ask_to_image(..., no_memory=True, history=[...])` sends **no** replayed history: the SDK payload's `messages` has exactly one (user, multimodal) entry.
- [ ] `ask_to_image(..., history=[...])` (default `no_memory=False`) still replays history.
- [ ] Model resolution: explicit `model=` wins; else the client's configured `model`; else `"claude-sonnet-5"`. The same value is on the returned `AIMessage.model`.
- [ ] Existing callers passing `model=ClaudeModel.X` positionally/by keyword behave as before.
- [ ] `detect_objects` returns `[x1, y1, x2, y2]` in original-image pixels, drops degenerate boxes, sets `mask_image`/`overlay_image` to `None`, and returns `[]` on an unparseable answer or a failed call.
- [ ] `detect_objects(output_dir=tmp_path/"x")` creates the directory and writes nothing into it.
- [ ] All tests pass: `pytest packages/ai-parrot-client-anthropic/tests/unit/test_vision_parity.py -q`
- [ ] Existing suite still green: `pytest packages/ai-parrot-client-anthropic/tests/unit/test_claude_multiround_usage.py -q`
- [ ] `ruff check packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py` clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-client-anthropic/tests/unit/test_vision_parity.py -q`

---

## Test Specification

```python
async def test_ask_to_image_no_memory_skips_history(image):
    """no_memory=True ⇒ payload messages == [user multimodal turn] even when history is given."""

async def test_ask_to_image_replays_history_by_default(image):
    """no_memory=False ⇒ rendered history precedes the image turn (len(messages) > 1)."""

@pytest.mark.parametrize("ctor_model, call_model, expected", [
    (None, None, "claude-sonnet-5"),
    ("claude-opus-4-8", None, "claude-opus-4-8"),
    ("claude-opus-4-8", ClaudeModel.SONNET_4, "claude-sonnet-4-20250514"),
])
async def test_ask_to_image_model_resolution(image, ctor_model, call_model, expected):
    """explicit > client model > SONNET_5; payload["model"] and AIMessage.model agree."""

async def test_detect_objects_shape(image):
    """200x100 image, answer objects=[{label:"a", box_2d:[100,250,500,750], confidence:0.9},
    {label:"bad", box_2d:[500,500,500,900]}] ⇒ one dict:
    {"label":"a","box_2d":[50,10,150,50],"confidence":0.9,"mask_image":None,"overlay_image":None}."""

async def test_detect_objects_bad_answer_returns_empty(image, tmp_path):
    """Non-JSON answer ⇒ []; output_dir is created and stays empty."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 4, §6 provider-client block)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — re-grep the anchors and occurrence counts before editing; if they moved, update the contract FIRST
4. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, never change a signature the blueprint fixes
5. **Verify** all acceptance criteria
6. Commit only the two files listed above; never touch `sdd/`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
