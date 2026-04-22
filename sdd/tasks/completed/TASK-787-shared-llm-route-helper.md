# TASK-787: Shared LLM-Route Helper Extraction

**Feature**: FEAT-111 — Router-Based Adaptive RAG (Store-Level)
**Spec**: `sdd/specs/router-based-adaptive-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of FEAT-111. Both `IntentRouterMixin` (strategy-level routing) and the upcoming `StoreRouter` (store-level routing) invoke an LLM via `self.invoke()`, wait with a timeout, then parse a JSON response. Today that logic lives inline in `IntentRouterMixin._parse_invoke_response` (`parrot/bots/mixins/intent_router.py:424`). This task extracts it into a shared helper so the new router reuses it without copy-pasting.

**Regression contract**: the existing `IntentRouterMixin` test suite must pass **unchanged** after this refactor.

---

## Scope

- Create `parrot/registry/routing/llm_helper.py` with:
  - `extract_json_from_response(response: Any) -> Optional[dict]` — pull a JSON object out of an `AIMessage`-like response (supports `.output`, `.content`, plain `str`, plain `dict`).
  - `async def run_llm_ranking(invoke_fn: Callable, prompt: str, timeout_s: float) -> Optional[dict]` — call `invoke_fn(prompt)` wrapped in `asyncio.wait_for`, parse JSON, return parsed dict or `None` on timeout / parse failure. Logs WARNING on failure; never raises.
- Refactor `IntentRouterMixin._parse_invoke_response` (`intent_router.py:424`) to delegate JSON extraction to `extract_json_from_response`. Enum-validation logic for `RoutingType` stays in the mixin; only the JSON-extraction mechanics move.
- **Behavior preservation**: the public API of `IntentRouterMixin` does not change. Existing tests under `tests/unit/bots/` for the intent router must pass without edits.
- Unit tests under `tests/unit/registry/routing/test_llm_helper.py`.

**NOT in scope**: changing `_fast_path`, `_llm_route`, or any strategy-routing logic. Pure helper extraction only.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/routing/llm_helper.py` | CREATE | Shared JSON-extraction + timeout-wrapped invoke |
| `packages/ai-parrot/src/parrot/registry/routing/__init__.py` | MODIFY | Re-export helpers |
| `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` | MODIFY | `_parse_invoke_response` delegates JSON extraction to the helper |
| `packages/ai-parrot/tests/unit/registry/routing/test_llm_helper.py` | CREATE | Unit tests for helper |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio
import json as _json
import logging
from typing import Any, Callable, Optional

from parrot.registry.capabilities.models import RoutingDecision, RoutingType  # already in use
```

### Existing Signatures to Use
```python
# parrot/bots/mixins/intent_router.py:361
async def _llm_route(
    self, prompt: str,
    strategies: list[RoutingType],
    candidates: list[RouterCandidate],
) -> Optional[RoutingDecision]: ...
    # Calls invoke via asyncio.wait_for(invoke(routing_prompt), timeout=...)

# parrot/bots/mixins/intent_router.py:424
def _parse_invoke_response(
    self, response: Any, available_strategies: list[RoutingType],
) -> Optional[RoutingDecision]:
    """Current inline logic:
       1. Normalize response → raw (from .output / .content / str)
       2. If dict, use as-is. If str, find `{..}` and json.loads().
       3. Map routing_type / confidence / reasoning / cascades into RoutingDecision.
    """
```

### Does NOT Exist
- ~~`parrot.registry.routing.llm_helper`~~ — this task creates it.
- ~~`run_llm_ranking`, `extract_json_from_response`~~ — this task creates them.
- ~~A shared base class for routers~~ — do not introduce one.

---

## Implementation Notes

### Pattern to Follow
The extraction mirrors the existing inline logic in `_parse_invoke_response` (`intent_router.py:424-486`). After extraction, the mixin keeps its own `RoutingDecision` assembly using the generic dict result.

### Key Constraints
- **Regression-safe**: run the existing intent-router unit tests (search for `test_intent_router*` and `test_parse_invoke*`) and confirm 0 failures BEFORE committing the refactor.
- `run_llm_ranking` catches `asyncio.TimeoutError` and any other `Exception` from `invoke_fn`, logs WARNING, returns `None`.
- `extract_json_from_response` must handle: object with `.output`, object with `.content`, raw `str`, raw `dict`. Return `None` when no JSON object can be extracted.
- Use `str.find("{")` / `str.rfind("}") + 1` to slice the JSON region, as the current code does.
- Do NOT change `_llm_route`'s prompt string — that is a strategy-router concern.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py:361` — `_llm_route`
- `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py:424` — `_parse_invoke_response`

---

## Acceptance Criteria

- [ ] `from parrot.registry.routing import extract_json_from_response, run_llm_ranking` works.
- [ ] Helper accepts `AIMessage`-like, `dict`, or `str` responses and returns the parsed dict or `None`.
- [ ] `run_llm_ranking` returns `None` on timeout / exception / unparseable output; logs WARNING; never raises.
- [ ] `IntentRouterMixin._parse_invoke_response` delegates to `extract_json_from_response` for the JSON-extraction step.
- [ ] Existing `IntentRouterMixin` tests pass unmodified: `pytest packages/ai-parrot/tests/unit/bots/ -v -k "intent_router or parse_invoke"` — 0 failures.
- [ ] New helper tests pass: `pytest packages/ai-parrot/tests/unit/registry/routing/test_llm_helper.py -v`.

---

## Test Specification

```python
import asyncio
import pytest
from parrot.registry.routing import extract_json_from_response, run_llm_ranking


class FakeAIMessage:
    def __init__(self, output): self.output = output


def test_extract_from_ai_message_dict():
    m = FakeAIMessage({"routing_type": "vector_search", "confidence": 0.9})
    result = extract_json_from_response(m)
    assert result["routing_type"] == "vector_search"


def test_extract_from_json_string():
    raw = 'Some preamble {"routing_type": "dataset", "confidence": 0.7} trailing'
    result = extract_json_from_response(raw)
    assert result["routing_type"] == "dataset"


def test_extract_from_plain_dict():
    result = extract_json_from_response({"foo": 1})
    assert result == {"foo": 1}


def test_extract_unparseable_returns_none():
    assert extract_json_from_response("no json here") is None
    assert extract_json_from_response(None) is None


@pytest.mark.asyncio
async def test_run_llm_ranking_timeout():
    async def slow(prompt):
        await asyncio.sleep(10)
    result = await run_llm_ranking(slow, "x", timeout_s=0.05)
    assert result is None


@pytest.mark.asyncio
async def test_run_llm_ranking_happy_path():
    async def fake(prompt):
        return FakeAIMessage({"routing_type": "vector_search", "confidence": 0.8})
    result = await run_llm_ranking(fake, "x", timeout_s=1.0)
    assert result["confidence"] == 0.8


@pytest.mark.asyncio
async def test_run_llm_ranking_exception_returns_none():
    async def boom(prompt):
        raise RuntimeError("bad")
    assert await run_llm_ranking(boom, "x", timeout_s=1.0) is None
```

---

## Agent Instructions

1. Read the spec (§3 Module 3, §7 Implementation Notes — especially the "shared helper (Module 3): keep extraction surgical" note).
2. Verify `intent_router.py:424` still matches the contract above — update the contract first if the file has drifted.
3. Run the existing intent-router tests BEFORE changing anything; record baseline.
4. Extract the helpers; refactor `_parse_invoke_response`.
5. Re-run the intent-router tests — they MUST still pass without modification.
6. Add the new helper tests.
7. Move this file to `sdd/tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*
