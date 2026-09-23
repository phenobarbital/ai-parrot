# TASK-3633: NeedleDelegate backend

**Feature**: FEAT-590 — Tool-Call Delegate
**Spec**: `sdd/specs/tool-call-delegate.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3624, TASK-3627
**Assigned-to**: unassigned

---

## Context

Spec Module 7. This is Needle 3 (121M parameters) via `cactus-needle`. The
engine documents neither async support nor thread safety, and the agent object
is stateful (`reset()`), so assume it is blocking and non-reentrant. It runs
through an executor with an instance pool keyed by tool subset
(`Needle(tools=...)` binds the toolset at construction).

**Read `sdd/state/FEAT-590/spike/decision.md` (TASK-3624) first.** It gives:
- the verified Needle API
- the executor choice (process vs. thread)
- the confidence behaviour
- the usable `max_input_chars`

If the decision is **DROP**, cancel this task. If Needle is not primary, still
implement it; it becomes the fallback.

---

## Scope

- `NeedleDelegate` satisfies `ToolCallDelegate`, with `backend_name="needle"` and `max_tools=5`.
- The executor defaults to `"process"`; `"thread"` is allowed only if the decision record says the engine releases the GIL.
  - Process mode runs a **top-level, picklable** worker function that owns a per-process `{frozenset(tool_names): [instances]}` cache. Bound methods and live Needle objects must never be pickled (design-research S10).
  - Thread mode uses an `asyncio.Queue` checkout pool per toolset: acquire → `reset()` → `complete()` → release.
- Facts map onto Needle's fixed `system` keys (`date`, `locale`, `device`, `battery`, `network`, `location`, `user`, `assistant`). Other facts are folded into the instruction text as `key: value` lines.
- Only `complete()` is used, never `agent.run()`.
- `needle` is imported lazily. A missing package raises `ImportError("NeedleDelegate requires the 'ai-parrot[needle]' extra (pip install ai-parrot[needle])")`.
- `aclose()` shuts down the executor and drops the pools; idempotent. The toolkit owns calling it (TASK-3635).
- Engine errors raise `DelegateBackendError`.
- Unit tests with the engine stubbed (no `needle` installed in CI). One optional integration test gated on `NEEDLE_WEIGHTS`.

**NOT in scope**: the pyproject extra (TASK-3637); fine-tuning.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/needle.py` | CREATE | Backend + picklable worker |
| `packages/ai-parrot/tests/bots/flows/plan/test_needle_delegate.py` | CREATE | Unit tests (engine stubbed) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from concurrent.futures import ProcessPoolExecutor
from parrot.bots.flows.plan.delegate.protocol import DelegateBackendError, ToolCallProposal, ToolSpec   # TASK-3627
# `needle` — lazy, inside functions only; API per decision.md (unverified until TASK-3624)
```

### Existing Signatures to Use
```python
# delegate/__init__.py maps "NeedleDelegate" -> ".needle" lazily (TASK-3627). Do NOT edit __init__.py.
```

### Does NOT Exist
- ~~`needle` in the venv~~: not installed. Tests must stub it (inject a fake `needle` module in `sys.modules`, or monkeypatch the worker).
- ~~`agent.run()`~~: forbidden.
- ~~A verified Needle API~~ beyond what `decision.md` records. The proposal §A.1 names (`Needle(tools=, system=, weights=)`, `.complete()`, `.reset()`, the response keys `function_calls`/`confidence`) are unverified until TASK-3624 checks them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/flows/plan/delegate/needle.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/bots/flows/plan/test_needle_delegate.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- The pool key is `frozenset(t.name for t in tools)`. Pool size is the delegate's own concurrency ceiling, independent of the node's `max_concurrency`.
- The executor is created lazily on the first call (AC14).
- A fine-tuned model reports `confidence=None`. Pass it through as `None`; the node's gate decides (§8 Q-S8).

---

## Implementation Blueprint

### Steps (in order)
1. Read the decision record; confirm the API and executor — *why*: the backend's facts come from the spike.
2. Write the module-level worker and cache — *why*: must be picklable for `ProcessPoolExecutor`.
3. Write the class — *why*: spec M7 skeleton.
4. Write the tests with a stubbed engine.

### `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/needle.py` (CREATE)
```python
"""``NeedleDelegate`` — Needle 3 tool proposals via an executor + instance pool (FEAT-590)."""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import Executor, ProcessPoolExecutor
from typing import Any, Dict, FrozenSet, List, Literal, Mapping, Optional, Sequence, Tuple, Type, Union

from pydantic import BaseModel

from .protocol import DelegateBackendError, ToolCallProposal, ToolSpec

__all__ = ("NeedleDelegate",)

_SYSTEM_KEYS = frozenset({"date", "locale", "device", "battery", "network", "location", "user", "assistant"})
_EXTRA_HINT = "NeedleDelegate requires the 'ai-parrot[needle]' extra (pip install ai-parrot[needle])"

# Per-process cache: {(weights, frozenset(tool names)): Needle instance}. Lives in the worker process.
_WORKER_CACHE: Dict[Tuple[Optional[str], FrozenSet[str]], Any] = {}


def _import_needle() -> Any:
    """Import ``needle`` lazily with an actionable error."""
    try:
        import needle  # type: ignore  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(_EXTRA_HINT) from exc
    return needle


def _complete_in_worker(
    weights: Optional[str], tools: List[Dict[str, Any]], system: Dict[str, str], text: str
) -> Dict[str, Any]:
    """Top-level (picklable) worker: get/create the cached engine, reset, complete. Returns the raw response dict."""
    # FILL IN: needle = _import_needle(); key = (weights, frozenset(t["name"] for t in tools)); cache the
    #   Needle(tools=tools, system=system?, weights=weights) per decision.md; reset(); return complete(text)
    raise NotImplementedError


class NeedleDelegate:
    """Needle 3 behind an executor; one engine per tool subset."""

    backend_name = "needle"
    max_tools = 5

    def __init__(
        self,
        *,
        weights: Optional[str] = None,
        pool_size: int = 4,
        executor: Literal["process", "thread"] = "process",
        max_input_chars: int = 1000,
    ) -> None:
        self.weights = weights
        self.pool_size = pool_size
        self.executor_kind = executor
        self.max_input_chars = max_input_chars
        self._executor: Optional[Executor] = None
        self._closed = False
        self.logger = logging.getLogger(f"{__name__}.NeedleDelegate")

    def _split_facts(self, instruction: str, facts: Optional[Mapping[str, str]]) -> Tuple[str, Dict[str, str]]:
        """Map facts onto Needle's fixed system keys; fold the rest into the instruction."""
        # FILL IN
        raise NotImplementedError

    async def _run(self, tools: Sequence[ToolSpec], system: Dict[str, str], text: str) -> Dict[str, Any]:
        """Run the worker on the configured executor; engine errors → DelegateBackendError."""
        # FILL IN: lazy ProcessPoolExecutor(max_workers=pool_size) for "process";
        #   "thread" → asyncio.Queue checkout pool + asyncio.to_thread (per decision.md);
        #   loop.run_in_executor(self._executor, _complete_in_worker, self.weights, [t.model_dump() for t in tools], system, text)
        raise NotImplementedError

    async def propose_call(
        self, instruction: str, tools: Sequence[ToolSpec], facts: Optional[Mapping[str, str]] = None
    ) -> ToolCallProposal:
        """Propose one call from the engine's ``function_calls`` (first entry), or decline."""
        started = time.monotonic()
        # FILL IN: _split_facts → _run → map {function_calls, confidence, success/error} → ToolCallProposal(backend="needle")
        raise NotImplementedError

    async def extract(self, text: str, schema: Union[Type[BaseModel], Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """``needle.extract`` in the executor; ``None`` when nothing fits."""
        # FILL IN
        raise NotImplementedError

    async def aclose(self) -> None:
        """Shut the executor down and drop pools. Idempotent; owned by the toolkit."""
        if self._closed:
            return
        self._closed = True
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
```

### `packages/ai-parrot/tests/bots/flows/plan/test_needle_delegate.py` (CREATE)
```python
"""FEAT-590 M7: NeedleDelegate (engine stubbed — needle is not installed in CI)."""
from __future__ import annotations

import os
import sys

import pytest

from parrot.bots.flows.plan.delegate import ToolCallDelegate
from parrot.bots.flows.plan.delegate.needle import NeedleDelegate, _complete_in_worker


def test_satisfies_protocol_without_needle_installed() -> None:
    assert isinstance(NeedleDelegate(), ToolCallDelegate)


def test_needle_lazy_import_error_message(monkeypatch) -> None: ...   # FILL IN: sys.modules["needle"] = None → message names ai-parrot[needle]
def test_worker_is_picklable() -> None: ...                           # FILL IN: pickle.dumps(_complete_in_worker)
def test_needle_pool_keyed_by_toolset(monkeypatch) -> None: ...       # FILL IN: fake needle module; two toolsets → two cache entries
@pytest.mark.asyncio
async def test_facts_mapping(monkeypatch) -> None: ...               # FILL IN: date/locale → system; other → instruction text
@pytest.mark.asyncio
async def test_confidence_none_passthrough(monkeypatch) -> None: ... # FILL IN
@pytest.mark.asyncio
async def test_aclose_idempotent() -> None: ...                      # FILL IN
@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("NEEDLE_WEIGHTS"), reason="needs cactus-needle + weights")
@pytest.mark.asyncio
async def test_live_needle_delegate() -> None: ...                   # FILL IN
```

### FILL IN checklist
- [ ] `_complete_in_worker`, `_split_facts`, `_run`, `propose_call`, `extract`; bounded by the decision record and spec M7
- [ ] Tests. Use `executor="thread"` in the stubbed unit tests so the fake module is visible (a process worker would not see a monkeypatched `sys.modules`)

---

## Acceptance Criteria

- [ ] Satisfies `ToolCallDelegate`; importing and constructing never imports `needle` (AC14)
- [ ] The worker is picklable; `aclose` is idempotent
- [ ] `ruff check` is clean; tests pass without `needle` installed

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/flows/plan/test_needle_delegate.py -q`

---

## Test Specification

See the test file block above.

---

## Agent Instructions

Standard. Read `sdd/state/FEAT-590/spike/decision.md` first.

---

## Completion Note

*(Agent fills this in when done)*
