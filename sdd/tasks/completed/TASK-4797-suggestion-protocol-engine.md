# TASK-4797: `SuggestionProvider` protocol + `SuggestionEngine`

**Feature**: FEAT-752 — Follow-up Suggestion Chips
**Spec**: `sdd/specs/followup-suggestion-chips.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4794
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (engine half) and §7 "Engine metadata". The engine is the extension point FEAT-756 plugs into: it
runs registered providers lane by lane, never raises, applies timeout / renderer check / dedupe / caps, and returns
the chips plus the `metadata["suggestions"]` dict. Bot wiring (`AbstractBot`/`BaseBot`) is TASK-4800.

---

## Scope

- Create package `parrot/bots/suggestions/` with `__init__.py`, `protocol.py`, `engine.py`.
- `protocol.py`: frozen dataclass `SuggestionContext`, `SuggestionProvider` `Protocol` (`runtime_checkable`), `LANES`.
- `engine.py`: `SuggestionEngine` (register / providers / collect) and `renderer_available()`.
- `__init__.py` re-exports ONLY protocol + engine names (TASK-4800 adds the provider re-exports).
- Tests in `tests/bots/test_suggestion_engine.py`.

**NOT in scope**: concrete providers (TASK-4798, TASK-4799); bot kwargs/methods/call sites (TASK-4800).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/suggestions/__init__.py` | CREATE | Package + re-exports |
| `packages/ai-parrot/src/parrot/bots/suggestions/protocol.py` | CREATE | Context + Protocol |
| `packages/ai-parrot/src/parrot/bots/suggestions/engine.py` | CREATE | Engine + renderer check |
| `packages/ai-parrot/tests/bots/test_suggestion_engine.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.suggestions import Suggestion, SuggestionSource   # created by TASK-4794
from parrot.models.responses import AIMessage                        # verified: models/responses.py:93
from parrot.models.outputs import OutputMode                         # verified: models/outputs.py:23
from parrot.outputs.formats import get_renderer                      # verified: outputs/formats/__init__.py:94
from navconfig.logging import logging                                # verified: bots/abstract.py:20 (project logger import)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/formats/__init__.py
def get_renderer(mode: OutputMode) -> type[Renderer]:   # line 94-105 — lazy-imports the mode's module, then
    # raises ValueError(f"No renderer registered for mode: {mode}") when absent
# registered today (core + ai-parrot-visualizations): CARD, STRUCTURED_CHART, STRUCTURED_TABLE, TABLE, MARKDOWN, ...
```

### Does NOT Exist
- ~~`parrot.bots.suggestions`~~ / ~~`SuggestionEngine`~~ / ~~`SuggestionProvider`~~ — created here.
- ~~`OutputFormatter.supported_modes()` / `available_modes()` / `list_modes()`~~ — capability checks go through
  `get_renderer()` only.
- ~~`asyncio.timeout`-based helpers in this repo for providers~~ — use `asyncio.wait_for` (pattern:
  `bots/mixins/intent_router.py:289-296`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/suggestions/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/bots/suggestions/protocol.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/bots/suggestions/engine.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/bots/test_suggestion_engine.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/formats/__init__.py#get_renderer",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage"
  ]
}
```

---

## Implementation Notes

Binding rules (spec §2 lanes table, §3 M2 skeleton, §7 Engine metadata):
- Lane order is fixed: `skill` → `deterministic` → `llm`; registration order is stable within a lane.
- Every provider runs under `try/except Exception` + `asyncio.wait_for(timeout_s)`; statuses: `ok`, `timeout`,
  `error`, `skipped` (lane not enabled). Log with `self.logger.warning` on timeout/error.
- Post-process in this order: renderer check (drop chips whose `output_mode` fails `renderer_available`) → dedupe by
  `label.casefold()` (first wins) → llm-lane chips capped at `max_llm_suggestions` → total capped at `max_suggestions`.
- Metadata is plain JSON types: `{"enabled_lanes": [...], "count": n, "providers": {name: {"status", "count",
  "elapsed_ms"}}, "llm": <provider.last_cost or None>}`. `llm` comes from `getattr(p, "last_cost", None)` of the
  first `llm`-lane provider that ran with status `ok`.
- Providers run sequentially (deterministic ones are pure and cheap; the LLM lane is a single call).

---

## Implementation Blueprint

### Steps (in order)
1. Write `protocol.py` — *why*: the provider contract FEAT-756 implements.
2. Write `engine.py`, fill `collect()` per the Implementation Notes — *why*: one place owns all guards.
3. Write `__init__.py` re-exports — *why*: `from parrot.bots.suggestions import SuggestionEngine` is the public path.
4. Tests; run Validation Commands.

### `packages/ai-parrot/src/parrot/bots/suggestions/protocol.py` (CREATE)
```python
"""Suggestion provider protocol (FEAT-752)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional, Protocol, Sequence, runtime_checkable

from parrot.models.outputs import OutputMode
from parrot.models.responses import AIMessage
from parrot.models.suggestions import Suggestion

Lane = Literal["skill", "deterministic", "llm"]
LANES: tuple[str, ...] = ("skill", "deterministic", "llm")


@dataclass(frozen=True)
class SuggestionContext:
    """Everything a provider may look at. ``bot`` is the producing bot (read-only use)."""

    question: str
    response: AIMessage
    output_mode: OutputMode
    bot: Any
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    tenant: Optional[str] = None


@runtime_checkable
class SuggestionProvider(Protocol):
    """Cooperative chip producer. Async; should not raise (the engine guards anyway)."""

    name: str
    lane: Lane

    async def suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]:
        """Return zero or more chips for this answer."""
        ...
```

### `packages/ai-parrot/src/parrot/bots/suggestions/engine.py` (CREATE)
```python
"""Suggestion engine: lane gating, guards, dedupe and caps (FEAT-752)."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from navconfig.logging import logging

from parrot.models.outputs import OutputMode
from parrot.models.suggestions import Suggestion, SuggestionSource
from parrot.outputs.formats import get_renderer

from .protocol import LANES, SuggestionContext, SuggestionProvider


def renderer_available(mode: "OutputMode | str | None") -> bool:
    """True when ``mode`` is None or ``get_renderer(OutputMode(mode))`` succeeds."""
    if mode is None:
        return True
    try:
        get_renderer(OutputMode(mode))
    except ValueError:
        return False
    return True


class SuggestionEngine:
    """Runs providers lane by lane; never raises; returns ``(suggestions, metadata)``."""

    def __init__(self, *, max_suggestions: int = 6, max_llm_suggestions: int = 4, timeout_s: float = 4.0,
                 logger: Optional[logging.Logger] = None) -> None:
        """Caps and per-provider timeout. ``timeout_s`` applies to every provider, not only the LLM lane."""
        self.max_suggestions = max_suggestions
        self.max_llm_suggestions = max_llm_suggestions
        self.timeout_s = timeout_s
        self.logger = logger or logging.getLogger(__name__)
        self._providers: list[SuggestionProvider] = []

    def register(self, provider: SuggestionProvider, *, prepend: bool = False) -> None:
        """Append (or prepend) a provider; a duplicate ``name`` replaces the previous registration."""
        # FILL IN: drop any existing provider with the same .name, then insert at 0 or append — bounded by
        #          test_register_replaces_duplicate_name / test_bot_register_provider_prepend (TASK-4800)
        raise NotImplementedError

    @property
    def providers(self) -> tuple[SuggestionProvider, ...]:
        """Registration order sorted by lane (skill, deterministic, llm); stable within a lane."""
        return tuple(sorted(self._providers, key=lambda p: LANES.index(p.lane)))

    async def collect(self, ctx: SuggestionContext, *, lanes: frozenset[str]) -> tuple[list[Suggestion], dict[str, Any]]:
        """Run providers whose lane is in ``lanes``; guard, post-process and account. Never raises."""
        meta: dict[str, Any] = {"enabled_lanes": [l for l in LANES if l in lanes], "count": 0, "providers": {},
                                "llm": None}
        collected: list[Suggestion] = []
        for provider in self.providers:
            if provider.lane not in lanes:
                meta["providers"][provider.name] = {"status": "skipped", "count": 0, "elapsed_ms": 0.0}
                continue
            started = time.perf_counter()
            # FILL IN: await asyncio.wait_for(provider.suggest(ctx), self.timeout_s) under try/except
            #          (asyncio.TimeoutError -> "timeout", Exception -> "error", both logged with self.logger.warning);
            #          record {"status", "count", "elapsed_ms"}; for an ok llm-lane provider copy
            #          getattr(provider, "last_cost", None) into meta["llm"] — bounded by Implementation Notes
        # FILL IN: post-process exactly in the order of the Implementation Notes (renderer -> dedupe -> llm cap ->
        #          total cap); llm chips are those with source == SuggestionSource.LLM.value
        meta["count"] = len(collected)
        return collected, meta
```
**Why this shape**: signatures are fixed by the spec §3 M2 skeleton. `collect` must never raise — wrap the whole
post-processing in the same defensive style if you add anything that can fail.

### `packages/ai-parrot/src/parrot/bots/suggestions/__init__.py` (CREATE)
```python
"""Follow-up suggestion chips: provider protocol and engine (FEAT-752)."""
from .engine import SuggestionEngine, renderer_available
from .protocol import LANES, SuggestionContext, SuggestionProvider

__all__ = ("LANES", "SuggestionContext", "SuggestionEngine", "SuggestionProvider", "renderer_available")
```

### FILL IN checklist
- [ ] `SuggestionEngine.register` — replace-by-name + prepend.
- [ ] `SuggestionEngine.collect` — guarded loop + post-processing order.
- [ ] Test bodies below.

---

## Acceptance Criteria

- [ ] A provider raising / timing out yields `[]` for it, status `error` / `timeout`; other providers' chips kept.
- [ ] Lanes `{skill}` → deterministic and llm providers `skipped`; `{skill, deterministic}` → llm `skipped`.
- [ ] Duplicate labels (case-insensitive) collapse; total ≤ `max_suggestions`; llm-source chips ≤ `max_llm_suggestions`.
- [ ] A chip with an unregistered `output_mode` is dropped (monkeypatch `get_renderer` in `engine` to raise).
- [ ] A provider class defined in the test module registers and runs (FEAT-756 extension path).
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_suggestion_engine.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_suggestion_engine.py
import asyncio
import pytest
from parrot.bots.suggestions import SuggestionContext, SuggestionEngine
from parrot.bots.suggestions import engine as engine_mod
from parrot.models import AIMessage, Suggestion
from parrot.models.basic import CompletionUsage
from parrot.models.outputs import OutputMode


class StaticProvider:
    def __init__(self, name, lane, chips):
        self.name, self.lane, self._chips = name, lane, chips

    async def suggest(self, ctx):
        return self._chips


class Boom:
    name, lane = "boom", "deterministic"

    async def suggest(self, ctx):
        raise RuntimeError("boom")


@pytest.fixture
def ctx():
    msg = AIMessage(input="q", output="a", model="fake", provider="fake", usage=CompletionUsage())
    return SuggestionContext(question="q", response=msg, output_mode=OutputMode.DEFAULT, bot=None)


async def test_engine_never_raises_and_records_status(ctx):
    eng = SuggestionEngine(timeout_s=0.05)
    eng.register(Boom())
    eng.register(StaticProvider("ok", "deterministic", [Suggestion(label="A", prompt="a")]))
    chips, meta = await eng.collect(ctx, lanes=frozenset({"skill", "deterministic"}))
    assert [c.label for c in chips] == ["A"]
    assert meta["providers"]["boom"]["status"] == "error"


async def test_engine_timeout_status(ctx):
    # FILL IN: provider sleeping 1s with timeout_s=0.05 -> status "timeout"
    ...


async def test_engine_lane_gating(ctx):
    # FILL IN
    ...


async def test_engine_dedupe_cap_and_renderer_check(ctx, monkeypatch):
    # FILL IN: monkeypatch engine_mod.get_renderer to raise ValueError for OutputMode.CARD only
    ...


def test_register_replaces_duplicate_name():
    # FILL IN
    ...
```

---

## Agent Instructions

Follow `sdd/templates/task.md` § Agent Instructions (worktree via `ensure_worktree --slug followup-suggestion-chips
--feature-id FEAT-752`, `PYTHONPATH=packages/ai-parrot/src`, commit only listed files,
`scripts/sdd/close_task.sh TASK-4797 followup-suggestion-chips verified`).

---

## Completion Note

Implemented directly by the worker (sequential fallback). Files exactly as listed: `bots/suggestions/{__init__,protocol,engine}.py` and `tests/bots/test_suggestion_engine.py`.
`register`/`collect` filled per the Implementation Notes (renderer check -> casefold dedupe -> llm cap -> total cap). One deliberate structural choice: per-provider timing/status live in a `_run_provider` helper that returns `(chips, status, elapsed_ms)`, so no timing state is kept on the shared engine instance (a bot-level engine serves concurrent requests); a concurrent-collect test covers it. `collect` wraps the loop and post-processing in a defensive try/except.
Tests: 10 passed (spec's five plus lane order, llm cost copy, external provider, prepend, concurrency). ruff and black clean. Pyright import notices on the test file are stale resolution against the main checkout.
