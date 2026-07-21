---
type: Wiki Overview
title: 'TASK-1488: Evolve IntentRouterMixin — output-mode routing + LLM tie-breaker'
id: doc:sdd-tasks-completed-task-1488-evolve-intentroutermixin-output-mode-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 5 — the heart of the feature. Adds output-mode
  routing
relates_to:
- concept: mod:parrot.bots.mixins.intent_router
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.registry.capabilities.models
  rel: mentions
- concept: mod:parrot.registry.routing.embedding_router
  rel: mentions
- concept: mod:parrot.registry.routing.llm_helper
  rel: mentions
---

# TASK-1488: Evolve IntentRouterMixin — output-mode routing + LLM tie-breaker

**Feature**: FEAT-224 — IntentRouterMixin Embedding-Based Output-Mode Routing
**Spec**: `sdd/specs/intent-router-mixin-embedding-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1484, TASK-1485, TASK-1487
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5 — the heart of the feature. Adds output-mode routing
to the EXISTING `IntentRouterMixin` as a clearly separated second concern:
`configure_output_router()` builds the engine once (CONFIGURE), and an override
of `_resolve_output_mode()` runs the threshold+margin policy (REQUEST), calling
the LLM tie-breaker only on ambiguity. The existing retrieval-strategy routing on
`conversation()` (`_route`, `_fast_path`, `_llm_route`, etc.) MUST remain
untouched (G7, no regression).

---

## Scope

- Add `configure_output_router(self, config: IntentRouterConfig) -> None`:
  - If `not config.enable_output_mode_routing`, leave the router inactive (no-op).
  - Else build `EmbeddingIntentRouter(config.embedding_model,
    config.output_mode_threshold, config.discrepancy_margin)` and `add_route`
    each entry of `config.output_mode_routes` (map the string key → `OutputMode(key)`).
  - Store on a NEW private attr (e.g. `self._output_router`). Load ONCE.
- Override `async def _resolve_output_mode(self, query, ctx) -> OutputMode | None`:
  - If no `_output_router`, `return await super()._resolve_output_mode(query, ctx)`.
  - `rs = await asyncio.to_thread(self._output_router.route, query)`.
  - If `rs.mode is None` → abstain (`return await super()...`).
  - If `rs.ambiguous` → call `_llm_disambiguate_output_mode(query, candidates)`;
    use its result if valid, else fall back to `rs.mode`.
  - On a resolved mode, set `ctx.intent_score = rs.score` when `ctx` is not None,
    then `return rs.mode`.
- Add `_llm_disambiguate_output_mode(query, candidates)`: a bounded
  `self.invoke()` call (reuse the existing `extract_json_from_response` helper)
  that picks one `OutputMode` from the close candidates; abstain (return `None`)
  if `invoke` is unavailable or times out.
- Unit tests for: configure-once, abstain, clear-winner (no LLM), ambiguous
  (LLM consulted), super() chaining, ctx.intent_score set.

**NOT in scope**: editing `conversation()`/`_route()`/retrieval strategy runners;
the base call sites (TASK-1487); engine internals (TASK-1484). The integration /
no-regression end-to-end tests live in TASK-1489.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` | MODIFY | Add `configure_output_router`, `_resolve_output_mode`, `_llm_disambiguate_output_mode`, `self._output_router` |
| `packages/ai-parrot/tests/bots/test_intent_router_output_mode.py` | CREATE | unit tests for the policy + wiring |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio
from parrot.models.outputs import OutputMode                       # verified: models/outputs.py:37
from parrot.registry.capabilities.models import IntentRouterConfig  # verified: registry/capabilities/models.py:149 (+ TASK-1485 fields)
from parrot.registry.routing.embedding_router import EmbeddingIntentRouter, RouteScore  # NEW from TASK-1484
from parrot.registry.routing.llm_helper import extract_json_from_response  # verified: imported at intent_router.py:30
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/mixins/intent_router.py
class IntentRouterMixin:                                            # line 118
    _router_active: bool = False                                   # line 132
    _router_config: Optional[IntentRouterConfig] = None            # line 133
    def __init__(self, **kwargs): ...                              # line 136 (cooperative super().__init__)
    def configure_router(self, config, registry) -> None: ...      # line 149 (retrieval router — DO NOT alter)
    async def conversation(self, prompt, **kwargs) -> Any: ...     # line 166 (retrieval routing — DO NOT alter)
    async def _llm_route(self, prompt, strategies, candidates): ... # line 373 (existing invoke() usage pattern)
    def _parse_invoke_response(self, response, strategies): ...     # line 436 (extract_json_from_response usage)

# invoke() access pattern (mirror this, intent_router.py:394):
#   invoke = getattr(self, "invoke", None)
#   if invoke is None: return None
#   raw = await asyncio.wait_for(invoke(prompt), timeout=...)

# Base no-op overridden here (TASK-1487, bots/abstract.py):
#   async def _resolve_output_mode(self, query, ctx) -> OutputMode | None
```

### Does NOT Exist
- ~~`self._output_router`~~ — new attribute; initialize to `None` in `__init__`
  (extend the existing cooperative `__init__`).
- ~~`IntentRouterMixin._resolve_output_mode`~~ — does not exist yet; you add the override.
- ~~`OutputModeRouterMixin`~~ — do not create a new class; evolve THIS mixin.
- ~~A new `invoke`/LLM client~~ — reuse `self.invoke()` (FEAT-069) via `getattr`,
  exactly like `_llm_route` (line 394). Abstain gracefully if absent.

---

## Implementation Notes

### Pattern to Follow
```python
# in __init__ (extend the existing cooperative one at line 136):
self._output_router = None

def configure_output_router(self, config: IntentRouterConfig) -> None:
    if not config.enable_output_mode_routing:
        return
    router = EmbeddingIntentRouter(
        config.embedding_model, config.output_mode_threshold, config.discrepancy_margin)
    for mode_value, utterances in config.output_mode_routes.items():
        try:
            router.add_route(OutputMode(mode_value), utterances)
        except ValueError:
            getattr(self, "logger", logging.getLogger(__name__)).warning(
                "Unknown OutputMode in routes: %s", mode_value)
    self._output_router = router

async def _resolve_output_mode(self, query, ctx):
    router = getattr(self, "_output_router", None)
    if router is None:
        return await super()._resolve_output_mode(query, ctx)
    rs: RouteScore = await asyncio.to_thread(router.route, query)
    if rs.mode is None:
        return await super()._resolve_output_mode(query, ctx)
    chosen = rs.mode
    if rs.ambiguous:
        llm_choice = await self._llm_disambiguate_output_mode(query, rs)
        if llm_choice is not None:
            chosen = llm_choice
    if ctx is not None:
        ctx.intent_score = rs.score
    return chosen
```

### Key Constraints
- Load the encoder ONCE in `configure_output_router` (CONFIGURE) — never in `_resolve_output_mode`.
- `route()` runs via `asyncio.to_thread` (engine is sync/CPU-bound).
- MRO: mixin must precede the concrete bot; `_resolve_output_mode` chains `super()`.
- Do NOT touch `_route`, `_fast_path`, `_llm_route`, `conversation`, or any
  strategy runner — those are the retrieval router (must stay green).
- LLM tie-break prompt offers ONLY the close candidate modes; validate the
  returned value with `OutputMode(...)` and reject anything not in candidates.

---

## Acceptance Criteria

- [ ] `configure_output_router` builds the engine once; inactive when
      `enable_output_mode_routing=False`.
- [ ] `_resolve_output_mode` returns the embedding winner on a clear match and
      does NOT call `invoke()` in that case.
- [ ] On `ambiguous`, `invoke()` is consulted exactly once; on a valid response
      its mode is used, otherwise the embedding winner.
- [ ] Below threshold → `super()._resolve_output_mode` (abstain).
- [ ] `ctx.intent_score` is set to `rs.score` when a mode resolves and ctx exists.
- [ ] `super()._resolve_output_mode` is invoked on the abstain/no-router paths
      (cooperative chaining).
- [ ] Existing retrieval routing methods are unchanged (diff touches only the new
      members).
- [ ] `pytest packages/ai-parrot/tests/bots/test_intent_router_output_mode.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_intent_router_output_mode.py
import pytest
from parrot.models.outputs import OutputMode
from parrot.registry.capabilities.models import IntentRouterConfig
from parrot.bots.mixins.intent_router import IntentRouterMixin


class _Base:
    async def _resolve_output_mode(self, query, ctx):  # terminal super() in MRO
        return None
    async def invoke(self, prompt):                    # stub LLM
        return '{"output_mode": "structured_table"}'


class _Agent(IntentRouterMixin, _Base):
    pass


@pytest.fixture
def agent():
    a = _Agent()
    a.configure_output_router(IntentRouterConfig(
        enable_output_mode_routing=True,
        output_mode_threshold=0.5,
        output_mode_routes={
            "structured_chart": ["create a pie chart", "hazme una gráfica de pastel"],
            "structured_map": ["plot it on a map", "muéstralo en un mapa"],
        },
    ))
    return a


async def test_clear_winner_no_llm(agent, monkeypatch):
    called = {"invoke": False}
    async def _no(*a, **k): called["invoke"] = True; return ""
    monkeypatch.setattr(agent, "invoke", _no)
    mode = await agent._resolve_output_mode("create a pie chart of sales", None)
    assert mode == OutputMode.STRUCTURED_CHART
    assert called["invoke"] is False


async def test_abstain_below_threshold(agent):
    mode = await agent._resolve_output_mode("what is the return policy?", None)
    assert mode is None
```

---

## Agent Instructions

Standard SDD flow. Confirm TASK-1484/1485/1487 are in `completed/` first.
Verify the contract, implement, make tests pass, move file to `completed/`,
update index to `done`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Opus)
**Date**: 2026-06-05
**Notes**: Added `configure_output_router` (CONFIGURE, load-once), `_resolve_output_mode`
(REQUEST: threshold+margin policy, route() via asyncio.to_thread, super() chaining on
abstain/no-router), and `_llm_disambiguate_output_mode` (bounded self.invoke tie-breaker,
graceful abstain). `ctx.intent_score` set on resolve. Existing retrieval router
(_route/_fast_path/_llm_route/conversation) untouched. 8 unit tests pass; ruff clean.
**Deviations from spec**: Added a small `route_scores()` helper to the TASK-1484 engine
(`embedding_router.py`) so the ambiguous tie-breaker can offer the close-candidate set
to the LLM and compute it OFF the event loop (via to_thread); `route()` now delegates to
it. RouteScore is mode-level only (per spec non-goal), so candidates = winner + any mode
within `margin`. Engine's TASK-1484 tests still pass.
