# TASK-3436: Provider-neutral VisionAdapter with cache, repair retry and kwarg normalisation

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3420, TASK-3421, TASK-3426
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 10** (goal G11, provider-neutrality). `ask_to_image` is **not** declared on
`AbstractClient`; it is a duck-typed per-provider method whose keyword surface differs between the
Google and the Anthropic client. The new cycle must be drivable by either client, so exactly one
place is allowed to call `ask_to_image` for the new cycle: `VisionAdapter`. It owns the capability
guard, the per-provider kwarg normalisation, passing the **resolved model** explicitly (so a client
method's own default can never override the caller's selection), a schema-aware disk cache, exactly
one repair retry on an invalid structured answer, the shared per-run LLM semaphore, and the timeout.

The adapter is stored on `CycleContext.vision` (`parrot_pipelines.planogram.contracts`, TASK-3421)
and receives the `ResolvedBackend` produced by `parrot_pipelines.planogram.backend` (TASK-3426).
Its tests use the `fake_vision_client` fixture from
`packages/ai-parrot-pipelines/tests/conftest.py` (TASK-3420).

---

## Scope

- Create the package `parrot_pipelines/planogram/identification/` (`__init__.py`).
- Implement in `vision.py`: `VisionError(RuntimeError)`, `VisionAdapter` (`__init__`, `ask`),
  `cache_key`, `normalise_kwargs`, the `SUPPORTED_KWARGS` table, and the module-level picklable
  helper `encode_png(image: np.ndarray) -> bytes` that the identification tasks run through the CPU executor.
- Capability guard in `__init__`: a client without `ask_to_image` raises `VisionError` immediately.
- Per-provider kwarg table keyed by `client.client_name`; an unknown provider gets the common subset.
  A kwarg outside `KNOWN_KWARGS` **raises** — nothing is silently dropped.
- `ask`: cache lookup → call under semaphore + timeout → extract/validate → at most
  `repair_retries` repair retries → cache store. `images[0]` is the main image, the rest go as
  `reference_images`.
- Cache and file I/O through `asyncio.to_thread`; `cache_dir=None` disables the cache entirely.
- Offline unit tests listed under Test Specification.

**NOT in scope**: prompts, strips, identification or detection logic (later identification tasks);
building or resolving the client (pipeline constructor); `image_understanding` — the adapter
deliberately uses **only** `ask_to_image` so both providers take the same lane; changes to any
provider client (the Anthropic `no_memory` parity is TASK-3425's job — this adapter only relies on it
through the `SUPPORTED_KWARGS` table).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/__init__.py` | CREATE | Package marker + re-exports |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py` | CREATE | VisionAdapter, VisionError, cache_key, normalise_kwargs, encode_png |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_adapter.py` | CREATE | Offline unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
import asyncio, hashlib, json, logging                     # stdlib
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional, Sequence, Type, TypeVar
import cv2                                                  # opencv-python-headless>=4.8 — hard dependency of ai-parrot-pipelines
import numpy as np
from pydantic import BaseModel, ValidationError
from parrot_pipelines.planogram.backend import ResolvedBackend   # created by TASK-3426 (dependency)
```

### Existing Signatures to Use
```python
# Created by TASK-3426 (dependency) — packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/backend.py
class ResolvedBackend(BaseModel):
    provider: str
    model: Optional[str]            # None ⇒ provider default — then the adapter passes NO model kwarg
    origin: Literal["llm_instance", "llm_string", "constructor", "config", "package_default"]
    def as_string(self) -> str: ...

# Created by TASK-3420 (dependency) — packages/ai-parrot-pipelines/tests/conftest.py
class FakeVisionClient:
    client_name: str = "fake"                       # tests may reassign it ("google", "claude")
    model: Optional[str] = None
    calls: List[Dict[str, Any]]                     # re-read the conftest for the recorded dict shape
    def queue(self, method: str, *responses: Any) -> None: ...
    async def ask_to_image(self, prompt: str, image: Any, **kwargs: Any) -> Any:
        """Returns an object with .output / .structured_output, or raises a queued Exception."""
# fixture: fake_vision_client() -> FakeVisionClient

# packages/ai-parrot-client-google/src/parrot/clients/google/client.py:4999-5010   (client_name = "google", :117)
async def ask_to_image(self, prompt: str, image: Union[Path, bytes], reference_images=None,
    model: Union[str, GoogleModel] = None, max_tokens=None, temperature=None, structured_output=None,
    count_objects: bool = False, history=None, no_memory: bool = False) -> AIMessage
#   (accepts bytes despite the narrow annotation; NO system_prompt kwarg)

# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py:1307-1320   (client_name = "claude", :80 — NOT "anthropic")
async def ask_to_image(self, prompt: str, image: Union[Path, bytes, Image.Image], reference_images=None,
    model=..., max_tokens=None, temperature=None, structured_output=None, count_objects: bool = False,
    history=None, system_prompt: Optional[str] = None, context_1m: bool = False) -> AIMessage
#   `no_memory` is added by TASK-3425 (not a dependency of this task) — rely on it ONLY via SUPPORTED_KWARGS["claude"].

# packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py:1468   (client_name = "openai", :94)
#   ask_to_image(..., structured_output=None, history=None, no_memory=False, low_quality=False) — no system_prompt, no count_objects

# packages/ai-parrot/src/parrot/models/responses.py:75
class AIMessage(BaseModel):
    output: Any                                  # :80
    structured_output: Optional[Any] = None      # :148
```

Algorithmic reference (**read-only, NEVER imported**): `examples/planogram/plancheck/vision.py` —
`cache_key` :45-66, `VisionBackend.ask` :163-211 (cache → call → extract → one repair retry → store),
`_call` lane 2 :220-228 (passes no `history`, no `no_memory`), `_extract` :230-254, capability guard :148.

### Does NOT Exist
- ~~`AbstractClient.ask_to_image`~~ — not in `parrot/clients/base.py`; use `hasattr(client, "ask_to_image")`.
- ~~`client_name == "anthropic"`~~ — the Anthropic client's `client_name` is `"claude"`. The factory *provider key* (`"anthropic"`) is a different thing; the table is keyed by `client_name`.
- ~~`system_prompt` on the Google / OpenAI `ask_to_image`~~ — fold it into the prompt for those providers.
- ~~`ClaudeAgentClient.ask_to_image`~~ — raises `NotImplementedError` (`claude_agent.py:1036-1040`); surfaces as `VisionError` on first call.
- ~~`VisionAdapter.__aenter__` / client construction inside the adapter~~ — the adapter receives an already-usable client.
- ~~`image_understanding` lane~~ — intentionally unused here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_adapter.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; the semaphore is held **only** around the provider call (not around cache I/O or validation).
- `asyncio.wait_for(..., timeout=self.timeout)`; `asyncio.TimeoutError` ⇒ `VisionError`. `asyncio.CancelledError` must propagate untouched.
- The `model` kwarg is passed **only when `backend.model` is not `None`**.
- `temperature=0.0` always; `max_tokens=self.max_tokens`.
- `no_memory=True` is requested on every call; it is included only for providers whose table lists it
  (debug-log when omitted). `system_prompt` is passed natively where supported, otherwise prepended to
  the prompt (`f"{system_prompt}\n\n{prompt}"`) — never dropped.
- Cache key covers the backend string, `max_tokens`, stage, prompt version, the **final** prompt, the
  schema's JSON schema and every image's sha256 — a schema change must produce a cache miss.
- A corrupt or schema-incompatible cache file is a miss (logged at debug), never an error.
- Tests: `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src` inside a worktree.

### References in Codebase
- `examples/planogram/plancheck/vision.py` — reference algorithm (re-implemented, not imported).
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/legacy.py:1473` — `async with self.llm as client:` idiom used by callers; the adapter itself does not enter the client.

---

## Implementation Blueprint

### Steps (in order)
1. Create `identification/__init__.py` — *why*: the identification tasks import `VisionAdapter` from the package.
2. Write `vision.py` top to bottom as below — *why*: `normalise_kwargs` and `cache_key` are pure and tested on their own; the class composes them.
3. Implement `_extract` following the reference (`structured_output` first, then `output`; BaseModel / dict / JSON string, fenced or not) — *why*: Anthropic returns parsed JSON text, Google returns a model instance; both must validate into `schema`.
4. Implement `ask` exactly in the order cache → call → extract → repair → store — *why*: the repair prompt must reuse the same images and schema, and a repaired answer is cached under the ORIGINAL key.
5. Write the tests with `fake_vision_client`, run the validation command, `ruff check` the package.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/__init__.py` (CREATE)
```python
"""Identification stage of the planogram cycle: vision adapter, strategies, fallback detector, verification."""
from .vision import VisionAdapter, VisionError, cache_key, encode_png, normalise_kwargs

__all__ = ["VisionAdapter", "VisionError", "cache_key", "encode_png", "normalise_kwargs"]
```
**Why this shape**: only this task's names are exported; later identification modules are imported by
full module path so this file never needs another edit.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py` (CREATE)
```python
"""Provider-neutral vision adapter — the only caller of ``ask_to_image`` in the new planogram cycle."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional, Sequence, Type, TypeVar

import cv2
import numpy as np
from pydantic import BaseModel, ValidationError

from parrot_pipelines.planogram.backend import ResolvedBackend

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_COMMON: FrozenSet[str] = frozenset({"model", "max_tokens", "temperature", "structured_output", "reference_images"})
SUPPORTED_KWARGS: Dict[str, FrozenSet[str]] = {
    "google": _COMMON | {"no_memory"},                     # verified: google/client.py:4999-5010
    "claude": _COMMON | {"no_memory", "system_prompt"},    # verified: anthropic/client.py:1307-1320 (+ no_memory, TASK-3425)
    "openai": _COMMON | {"no_memory"},                     # verified: openai/client.py:1468
}
KNOWN_KWARGS: FrozenSet[str] = frozenset().union(*SUPPORTED_KWARGS.values())


class VisionError(RuntimeError):
    """Vision call failed, timed out, or stayed invalid after the repair retry."""


def normalise_kwargs(client_name: str, requested: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the kwargs ``client_name`` supports (unknown provider ⇒ common subset); drop ``None`` values.

    Raises:
        VisionError: a key outside ``KNOWN_KWARGS`` — unknown kwargs are never dropped silently.
    """
    # FILL IN: raise on unknown keys first; debug-log each known-but-unsupported key that is omitted
    raise NotImplementedError


def cache_key(backend: str, max_tokens: int, stage: str, prompt_version: str, prompt: str,
              schema: Type[BaseModel], images: Sequence[bytes]) -> str:
    """sha256 over a canonical JSON of all arguments incl. ``schema.model_json_schema()`` and image digests."""
    # FILL IN: json.dumps(payload, sort_keys=True, separators=(",", ":")) — bounded by reference vision.py:45-66
    raise NotImplementedError
```

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py` (CREATE) — continued, part 2/2 (same file: append directly below the previous block)
```python
def encode_png(image: np.ndarray) -> bytes:
    """PNG-encode a BGR array. Module-level and picklable — run it through the CPU executor, never inline."""
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("cv2.imencode failed")
    return buffer.tobytes()


class VisionAdapter:
    """Prompt + images + Pydantic schema → validated instance, on any client exposing ``ask_to_image``."""

    def __init__(self, client: Any, backend: ResolvedBackend, *, semaphore: asyncio.Semaphore,
                 cache_dir: Optional[Path] = None, max_tokens: int = 8192,
                 timeout: float = 120.0, repair_retries: int = 1) -> None:
        """Raises VisionError when the client has no ask_to_image."""
        if not hasattr(client, "ask_to_image"):
            raise VisionError(f"client {type(client).__name__} has no ask_to_image; it cannot drive the planogram cycle")
        self.client = client
        self.backend = backend
        self.client_name = str(getattr(client, "client_name", "") or "").lower()
        self.semaphore = semaphore
        self.cache_dir = Path(cache_dir).resolve() if cache_dir else None
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.repair_retries = repair_retries
        self.logger = logging.getLogger(__name__)

    async def ask(self, prompt: str, images: Sequence[bytes], schema: Type[T], *, stage: str,
                  prompt_version: str, system_prompt: Optional[str] = None) -> T:
        """images[0] is the main image, the rest go as reference_images. Returns a validated ``schema``
        instance. Raises ValueError on empty ``images``; VisionError after the repair retry fails or on timeout."""
        # FILL IN: cache → _call → _extract → up to self.repair_retries repair prompts
        #   (f"{prompt}\n\nYour previous answer was rejected: {exc}. Return ONLY valid JSON for the schema.")
        #   → cache store under the ORIGINAL key — bounded by reference vision.py:163-211
        raise NotImplementedError

    async def _call(self, prompt: str, images: Sequence[bytes], schema: Type[T], system_prompt: Optional[str]) -> Any:
        """One provider call under the semaphore and the timeout; provider exceptions → VisionError."""
        # FILL IN: requested = {model (only if backend.model), max_tokens, temperature=0.0, structured_output=schema,
        #   reference_images=list(images[1:]) or None, no_memory=True, system_prompt}; if "system_prompt" is not
        #   supported for self.client_name fold it into the prompt BEFORE normalise_kwargs; never catch CancelledError
        raise NotImplementedError

    @staticmethod
    def _extract(message: Any, schema: Type[T]) -> T:
        """AIMessage-like → schema instance. Raises ValidationError / ValueError."""
        # FILL IN: bounded by reference vision.py:230-254
        raise NotImplementedError

    async def _cache_load(self, key: str, schema: Type[T]) -> Optional[T]: ...   # FILL IN: to_thread read; any failure ⇒ None
    async def _cache_store(self, key: str, stage: str, prompt_version: str, result: BaseModel) -> None: ...  # FILL IN: to_thread write
```
**Why this shape**: constructor and `ask` signatures are fixed by the spec's Module 10 skeleton.
`SUPPORTED_KWARGS` is keyed by `client_name` because that is the only provider identity a client
instance carries (`"claude"` for Anthropic). `encode_png` lives here so both identification tasks can
share one picklable encoder without depending on each other. The two `...` cache helpers are
signatures to complete, not placeholders to keep.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_adapter.py` (CREATE)
See **Test Specification**. No `__init__.py` in this folder (unique basenames by design).

### FILL IN checklist
- [ ] `vision.py::normalise_kwargs` — unknown ⇒ raise; unsupported ⇒ logged omission; `None` values removed
- [ ] `vision.py::cache_key` — canonical JSON incl. schema JSON; bounded by the reference
- [ ] `vision.py::VisionAdapter.ask` — order cache → call → extract → repair → store; `repair_retries` honoured (0 ⇒ no retry)
- [ ] `vision.py::VisionAdapter._call` — semaphore + `wait_for`; system_prompt folding; model only when pinned
- [ ] `vision.py::VisionAdapter._extract` — BaseModel / dict / JSON string (fenced or plain)
- [ ] `vision.py::_cache_load` / `_cache_store` — `asyncio.to_thread`; disabled when `cache_dir is None`
- [ ] `test_vision_adapter.py` — every test body

---

## Acceptance Criteria

- [ ] `from parrot_pipelines.planogram.identification import VisionAdapter, VisionError, cache_key, encode_png` works.
- [ ] A client without `ask_to_image` raises `VisionError` at construction.
- [ ] Invalid structure ⇒ exactly one repair retry, then `VisionError`; a valid repaired answer is returned and cached.
- [ ] A schema change (different model class / field) yields a different cache key and a cache miss.
- [ ] The resolved model is passed when pinned and omitted when `backend.model is None`.
- [ ] `client_name="google"` never receives `system_prompt` (it is folded into the prompt); `client_name="claude"` receives it natively; both receive `no_memory=True`.
- [ ] `normalise_kwargs` raises `VisionError` for an unknown kwarg.
- [ ] Timeout ⇒ `VisionError`; cancellation propagates.
- [ ] No `requests`/`httpx`/`print`; `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/` passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_adapter.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_adapter.py
import asyncio
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from parrot_pipelines.planogram.backend import ResolvedBackend
from parrot_pipelines.planogram.identification.vision import (
    VisionAdapter, VisionError, cache_key, normalise_kwargs,
)


class Answer(BaseModel):
    value: int


def _backend(model="m-1") -> ResolvedBackend:
    return ResolvedBackend(provider="google", model=model, origin="constructor")


def _adapter(client, **kw) -> VisionAdapter:
    return VisionAdapter(client, _backend(kw.pop("model", "m-1")), semaphore=asyncio.Semaphore(2), **kw)


def test_client_without_ask_to_image_fails_fast(): ...            # VisionAdapter(object(), ...) → VisionError
async def test_vision_adapter_repair_retry_then_error(fake_vision_client): ...   # 2 invalid answers queued → VisionError, 2 calls
async def test_repaired_answer_is_returned(fake_vision_client): ...
async def test_vision_adapter_cache_is_schema_aware(fake_vision_client, tmp_path): ...   # 2nd ask = 0 new calls; other schema = miss
def test_cache_key_changes_with_schema_and_images(): ...
async def test_vision_adapter_passes_resolved_model_and_rejects_unknown_kwargs(fake_vision_client): ...
async def test_model_omitted_when_backend_has_none(fake_vision_client): ...
async def test_system_prompt_folded_for_google_native_for_claude(fake_vision_client): ...
async def test_timeout_becomes_vision_error(): ...                # inline client whose ask_to_image sleeps
def test_normalise_kwargs_unknown_raises(): ...
def test_encode_png_roundtrip(): ...
```
(`asyncio_mode` — check how the existing pipelines tests mark async tests before choosing between
`@pytest.mark.asyncio` and auto mode; FILL IN accordingly.)

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 10, §2 "Backend selection") for full context
2. **Check dependencies** — TASK-3420, TASK-3421, TASK-3426 must be completed; re-read `backend.py` and the tests `conftest.py` and update the contract first if a name differs
3. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
4. **Verify** acceptance criteria; run the Validation Command with the `PYTHONPATH` prefix
5. Commit only the three files listed; never touch `sdd/`
6. **Fill in the Completion Note**

---

## Completion Note

**Completed by**: sdd-worker (FEAT-574 orchestrator)
**Date**: 2026-09-19

Implemented in fallback sequential mode (parrot-sdd-coder server unresponsive).
identification/ package: VisionError; SUPPORTED_KWARGS keyed by client_name (google / claude / openai; unknown -> common subset) + KNOWN_KWARGS; normalise_kwargs (unknown raises, unsupported omitted with a debug log, None dropped); cache_key (canonical JSON incl. backend string, max_tokens, stage, prompt version, FINAL prompt, schema qualname + JSON schema, image sha256s); picklable encode_png; VisionAdapter (capability guard; ask = cache -> call -> extract -> up to repair_retries repair prompts -> store under the original key; semaphore held only around the provider call; asyncio.wait_for timeout -> VisionError; CancelledError propagates; model kwarg only when pinned; temperature 0.0; no_memory requested always; system_prompt native for claude, folded into the prompt otherwise; cache via asyncio.to_thread, corrupt/incompatible entries are misses, cache_dir=None disables).
Tests: test_vision_adapter.py 16 passed; ruff clean.

Seat: orchestrator (fallback) · Backend: native · Model: claude-opus-5 · Attempts: 1
