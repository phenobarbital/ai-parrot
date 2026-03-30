# TASK-491: IntentRouterMixin

**Feature**: intent-router
**Spec**: `sdd/specs/intent-router.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-489, TASK-490
**Assigned-to**: unassigned

---

## Context

> Implements Module 3 from the spec. The core routing mixin that intercepts conversation()
> and orchestrates: strategy discovery, fast path (keyword), LLM path (invoke() →
> RoutingDecision), strategy execution with cascade, RoutingTrace collection, LLM Fallback
> (ask() with trace summary), HITL (clarifying question), and exhaustive mode (all strategies,
> concatenate, synthesize).
>
> **Cross-feature dependency**: Requires FEAT-069 (`invoke()`) to be merged for the LLM path.

---

## Scope

- Create `parrot/bots/mixins/intent_router.py` with `IntentRouterMixin` class.
- Implement:
  - `configure_router(registry, client, config, embedding_fn)` — setup, strategy discovery
  - `conversation(question, **kwargs)` — intercept, route, dispatch, pass to super()
  - `_route(query, user_context)` — fast path → LLM path → RoutingDecision
  - `_discover_strategies()` — auto-detect from agent config (vector_store, dataset_manager, tools, etc.)
  - `_execute_strategy(strategy, query, decision)` — dispatch to correct handler
  - `_execute_with_cascade(query, decision, trace)` — primary + cascade fallbacks
  - `_execute_exhaustive(query, trace)` — all strategies, concatenate non-empty, label
  - `_build_fallback_prompt(query, trace)` — RoutingTrace summary for LLM Fallback
  - `_build_hitl_question(query, trace)` — formulate clarifying question
  - `_run_graph_pageindex(query, decision)` — delegate to OntologyRAGMixin.ontology_process()
  - `_run_dataset_query(query, decision)` — delegate to DatasetManager
  - `_run_vector_search(query)` — delegate to existing _build_vector_context()
  - `_run_tool_call(query, decision)` — inject routing hint for tool calling
  - `_run_free_llm()` — return empty context (LLM handles normally)
  - `_run_multi_hop(query, decision)` — asyncio.gather primary + secondary
- Strategy timeout: `asyncio.wait_for()` per strategy.
- InvokeError graceful degradation → FREE_LLM.
- Write unit tests with mocked registry and invoke().

**NOT in scope**: CapabilityRegistry (TASK-490), AbstractBot changes (TASK-492), auto-registration (TASK-493), OntologyIntentResolver demotion (TASK-494).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/mixins/__init__.py` | CREATE or MODIFY | Export IntentRouterMixin |
| `parrot/bots/mixins/intent_router.py` | CREATE | IntentRouterMixin class |
| `tests/bots/test_intent_router.py` | CREATE | Unit tests |

---

## Implementation Notes

### Strategy Discovery
```python
def _discover_strategies(self) -> set[RoutingType]:
    available = set()
    if getattr(self, '_ont_graph_store', None):     available.add(RoutingType.GRAPH_PAGEINDEX)
    if getattr(self, '_vector_store', None) or getattr(self, '_use_vector', False):
                                                      available.add(RoutingType.VECTOR_SEARCH)
    if hasattr(self, 'dataset_manager'):              available.add(RoutingType.DATASET)
    if hasattr(self, '_pageindex_retriever'):          available.add(RoutingType.GRAPH_PAGEINDEX)
    if self.tool_manager.tool_count() > 0:            available.add(RoutingType.TOOL_CALL)
    available.add(RoutingType.FREE_LLM)
    if self._router_config.fallback_enabled:          available.add(RoutingType.FALLBACK)
    if self._router_config.hitl_enabled:              available.add(RoutingType.HITL)
    return available
```

### Exhaustive Mode
- Try ALL available strategies in fixed order.
- Collect ALL non-empty results. Label each: `### Graph context\n{result}`, `### Dataset context\n{result}`.
- Concatenate into single context block.
- Pass to main LLM with synthesis instruction.

### HITL
- When confidence below hitl_confidence_threshold and hitl_enabled:
  - Use invoke() to formulate a clarifying question based on the query and what was tried.
  - Return the question as the response (injected as AIMessage content).
  - No suspension — next user message continues conversation history naturally.

### LLM Fallback
- Build prompt: "The following sources were checked: {trace_summary}. Answer from general knowledge with appropriate caveats."
- Call `super().conversation(question, system_prompt=fallback_prompt)` or equivalent.

### Key Constraints
- MRO: IntentRouterMixin must be first in class declaration for conversation() to intercept.
- `_router_active` flag: False by default, set True after configure_router().
- When not active, conversation() passes through to super() unchanged.
- PageIndexRetriever is lazy-imported.
- Each strategy execution wrapped in `asyncio.wait_for(timeout=config.strategy_timeout_ms/1000)`.

### References in Codebase
- `parrot/knowledge/ontology/mixin.py` — OntologyRAGMixin (cooperative inheritance pattern)
- `parrot/bots/base.py:495` — BaseBot.ask() flow
- `parrot/clients/base.py` — invoke() from FEAT-069

---

## Acceptance Criteria

- [ ] `configure_router()` sets up registry, client, config, discovers strategies
- [ ] `conversation()` intercepts when router active, passes through when not
- [ ] Fast path routes directly on keyword match
- [ ] LLM path uses invoke() → RoutingDecision with primary + cascades
- [ ] Cascade fallbacks execute in order when primary returns no results
- [ ] Exhaustive mode tries all, concatenates with labels
- [ ] RoutingTrace records all attempts with timing and produced_context
- [ ] LLM Fallback calls ask() with trace summary
- [ ] HITL returns clarifying question as normal response
- [ ] InvokeError → graceful degradation to FREE_LLM
- [ ] Strategy timeout handling
- [ ] All tests pass: `pytest tests/bots/test_intent_router.py -v`

---

## Test Specification

```python
# tests/bots/test_intent_router.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.bots.mixins.intent_router import IntentRouterMixin
from parrot.registry.capabilities import (
    RoutingDecision, RoutingType, RoutingTrace, IntentRouterConfig,
)

class TestStrategyDiscovery:
    def test_detects_vector_store(self, mock_agent):
        mock_agent._vector_store = MagicMock()
        strategies = mock_agent._discover_strategies()
        assert RoutingType.VECTOR_SEARCH in strategies

    def test_detects_no_strategies(self, bare_agent):
        strategies = bare_agent._discover_strategies()
        assert RoutingType.FREE_LLM in strategies
        assert RoutingType.DATASET not in strategies

class TestRouting:
    async def test_fast_path_keyword(self, configured_agent):
        # Trigger keyword match
        result = await configured_agent._route("show inventory levels", {})
        assert result.routing_type == RoutingType.DATASET

    async def test_llm_path_invoke(self, configured_agent):
        # Mock invoke() to return RoutingDecision
        result = await configured_agent._route("who are active employees?", {})
        assert isinstance(result, RoutingDecision)

    async def test_invoke_error_degradation(self, configured_agent):
        configured_agent._router_client.invoke = AsyncMock(side_effect=Exception("fail"))
        result = await configured_agent._route("test", {})
        assert result.routing_type == RoutingType.FREE_LLM

class TestCascade:
    async def test_primary_fails_cascade(self, configured_agent):
        # Primary DATASET returns 0 results → cascade to VECTOR_SEARCH
        ...

class TestExhaustive:
    async def test_all_strategies_tried(self, configured_agent):
        configured_agent._router_config.exhaustive = True
        # Verify all available strategies are tried
        ...

class TestHITL:
    async def test_low_confidence_clarification(self, configured_agent):
        configured_agent._router_config.hitl_enabled = True
        # Mock all strategies returning low confidence
        # Expect clarifying question returned
        ...

class TestFallback:
    async def test_fallback_with_trace(self, configured_agent):
        # All strategies fail → FALLBACK with trace summary
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-491-intent-router-mixin.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
