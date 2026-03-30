# TASK-491: IntentRouterMixin

**Feature**: intent-router
**Spec**: `sdd/specs/intent-router.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (8-16h)
**Depends-on**: TASK-489, TASK-490
**Assigned-to**: unassigned

---

## Context

> Core routing mixin that intercepts `conversation()` calls and routes user queries to the most appropriate strategy (dataset query, vector search, tool call, graph traversal, free LLM, etc.). This is the central piece of the intent-router feature.
> Implements spec Section 3 — Module 3 (IntentRouterMixin).
> Cross-feature dependency: relies on FEAT-069's `invoke()` method for LLM-based routing decisions.

---

## Scope

- Create the `parrot/bots/mixins/` package with `__init__.py` and `intent_router.py`.
- Implement `IntentRouterMixin` class with the following methods:
  - `configure_router(config: IntentRouterConfig, registry: CapabilityRegistry) -> None` — sets up the router, sets `_router_active = True`.
  - `conversation(prompt, **kwargs)` — intercept method; if `_router_active`, calls `_route()` first, then delegates to super with injected context.
  - `_route(prompt: str) -> tuple[Optional[str], Optional[RoutingDecision], Optional[RoutingTrace]]` — main routing logic.
  - `_discover_strategies(prompt: str) -> list[RoutingType]` — auto-detect available strategies from agent config (vector_store, dataset_manager, tools, graph_store, pageindex_retriever).
  - `_execute_strategy(routing_type: RoutingType, prompt: str, candidates: list[RouterCandidate]) -> Optional[str]` — dispatch to the appropriate strategy runner.
  - `_execute_with_cascade(decision: RoutingDecision, prompt: str) -> tuple[Optional[str], RoutingTrace]` — execute primary, then cascades in order until context is produced or cascades exhausted.
  - `_execute_exhaustive(strategies: list[RoutingType], prompt: str, candidates: list[RouterCandidate]) -> tuple[str, RoutingTrace]` — run all strategies, concatenate results with labels.
  - `_build_fallback_prompt(prompt: str, trace: RoutingTrace) -> str` — build enriched prompt with trace summary for the LLM fallback.
  - `_build_hitl_question(prompt: str, candidates: list[RouterCandidate]) -> str` — build a clarifying question as a normal response.
  - Strategy runners (private methods):
    - `_run_graph_pageindex(prompt, candidates)` — query graph store / pageindex retriever.
    - `_run_dataset_query(prompt, candidates)` — query dataset manager.
    - `_run_vector_search(prompt, candidates)` — query vector store.
    - `_run_tool_call(prompt, candidates)` — invoke a tool.
    - `_run_free_llm(prompt, candidates)` — pass through to LLM with no context.
    - `_run_multi_hop(prompt, candidates)` — chain multiple strategies sequentially.
- Strategy discovery:
  - If `self.vector_store` exists → VECTOR_SEARCH available.
  - If `self.dataset_manager` exists → DATASET available.
  - If `self.tools` non-empty → TOOL_CALL available.
  - If `self.graph_store` exists → GRAPH_PAGEINDEX available.
  - If `self.pageindex_retriever` exists → GRAPH_PAGEINDEX available.
  - FREE_LLM always available. FALLBACK always available. HITL always available.
- Fast path: keyword scan on prompt to short-circuit obvious routes (e.g., "search for" → VECTOR_SEARCH).
- LLM path: use `invoke()` (from FEAT-069) to ask the LLM to pick a RoutingDecision.
- Cascade: execute primary strategy; if no context produced, try cascades in order up to `max_cascades`.
- Exhaustive mode: run all discovered strategies, concatenate results with section labels.
- HITL: if confidence < `hitl_threshold`, return a clarifying question as a normal response (no LLM call).
- Fallback: if no strategy produced context, call `ask()` with trace summary.
- Error handling: `InvokeError` → graceful degradation to FREE_LLM.
- Strategy timeout: `asyncio.wait_for()` per strategy with `strategy_timeout_s`.
- `_router_active` flag: `False` by default, set to `True` after `configure_router()`.
- `PageIndexRetriever` is lazy-imported to avoid circular imports.

**NOT in scope**: AbstractBot modifications (TASK-492), auto-registration hooks (TASK-493), OntologyIntentResolver changes (TASK-494).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/mixins/__init__.py` | CREATE | Package init; export IntentRouterMixin |
| `parrot/bots/mixins/intent_router.py` | CREATE | IntentRouterMixin class with all routing logic |
| `tests/bots/test_intent_router.py` | CREATE | Unit tests for the mixin |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/bots/mixins/intent_router.py
import asyncio
import logging
import time
from typing import Optional

from parrot.registry.capabilities.models import (
    IntentRouterConfig, RoutingDecision, RoutingTrace, RoutingType,
    RouterCandidate, TraceEntry,
)
from parrot.registry.capabilities.registry import CapabilityRegistry


class IntentRouterMixin:
    """Mixin that adds intent-based routing to any Bot/Agent.

    Must be mixed into a class that has conversation() and ask() methods.
    Uses MRO: IntentRouterMixin.conversation() → super().conversation().
    """

    _router_active: bool = False
    _router_config: Optional[IntentRouterConfig] = None
    _capability_registry: Optional[CapabilityRegistry] = None

    def configure_router(
        self, config: IntentRouterConfig, registry: CapabilityRegistry
    ) -> None:
        """Activate the intent router with the given config and registry."""
        self._router_config = config
        self._capability_registry = registry
        self._router_active = True
        self.logger.info("Intent router configured and active.")

    async def conversation(self, prompt: str, **kwargs):
        """Intercept conversation to route via intent router if active."""
        if not self._router_active:
            return await super().conversation(prompt, **kwargs)

        context, decision, trace = await self._route(prompt)
        if decision and decision.routing_type == RoutingType.HITL:
            # Return clarifying question directly
            return self._build_hitl_question(prompt, decision.candidates)

        if context:
            kwargs["injected_context"] = context
        if decision:
            kwargs["routing_decision"] = decision
        if trace:
            kwargs["routing_trace"] = trace
        return await super().conversation(prompt, **kwargs)

    async def _route(self, prompt: str):
        """Main routing logic: discover → decide → execute."""
        start = time.monotonic()
        trace = RoutingTrace()

        strategies = self._discover_strategies(prompt)
        if not strategies:
            trace.elapsed_ms = (time.monotonic() - start) * 1000
            return None, None, trace

        # Search registry for candidates
        candidates = []
        if self._capability_registry:
            candidates = await self._capability_registry.search(prompt, top_k=5)

        # Fast path: keyword scan
        decision = self._fast_path(prompt, strategies, candidates)
        if not decision:
            # LLM path via invoke()
            decision = await self._llm_route(prompt, strategies, candidates)

        if not decision:
            trace.elapsed_ms = (time.monotonic() - start) * 1000
            return None, None, trace

        # Check HITL threshold
        if decision.confidence < self._router_config.hitl_threshold:
            decision.routing_type = RoutingType.HITL
            trace.elapsed_ms = (time.monotonic() - start) * 1000
            return None, decision, trace

        # Execute strategy (cascade or exhaustive)
        if self._router_config.exhaustive_mode:
            context, trace = await self._execute_exhaustive(
                strategies, prompt, candidates
            )
        else:
            context, trace = await self._execute_with_cascade(
                decision, prompt
            )

        trace.elapsed_ms = (time.monotonic() - start) * 1000

        if not context:
            context = self._build_fallback_prompt(prompt, trace)
            decision.routing_type = RoutingType.FALLBACK

        return context, decision, trace
```

### Key Constraints
- **MRO**: IntentRouterMixin must call `super().conversation()` so it cooperates with Python's MRO when mixed into Agent/Chatbot.
- **`_router_active` flag**: conversation() must be a no-op pass-through when False.
- **Lazy import of PageIndexRetriever**: use `importlib` or inline import to avoid circular deps.
- **asyncio.wait_for**: wrap each strategy execution with the configured timeout.
- **InvokeError handling**: catch InvokeError from invoke() and fall back to FREE_LLM.
- **No direct LLM provider calls**: use `self.invoke()` for LLM routing decisions, `self.ask()` for fallback.
- **Thread-safety**: this mixin is not required to be thread-safe (one agent = one event loop).

### References in Codebase
- `parrot/bots/base.py` — `AbstractBot.conversation()`, `AbstractBot.ask()`
- `parrot/bots/agents/` — Agent class that will mix this in
- `parrot/tools/dataset_manager/tool.py` — DatasetManager (for _run_dataset_query)
- `parrot/vectorstores/` — vector store interface (for _run_vector_search)
- `parrot/knowledge/ontology/` — graph store (for _run_graph_pageindex)

---

## Acceptance Criteria

- [ ] `IntentRouterMixin` class exists in `parrot/bots/mixins/intent_router.py`
- [ ] `configure_router()` sets `_router_active = True`
- [ ] `conversation()` passes through when `_router_active` is False
- [ ] `conversation()` routes via `_route()` when `_router_active` is True
- [ ] `_discover_strategies()` detects available strategies from agent attributes
- [ ] `_execute_with_cascade()` tries primary then cascades, stops on first context
- [ ] `_execute_exhaustive()` runs all strategies and concatenates results
- [ ] HITL returns clarifying question when confidence < hitl_threshold
- [ ] Fallback engages when no strategy produces context
- [ ] InvokeError gracefully degrades to FREE_LLM
- [ ] Each strategy execution is wrapped in asyncio.wait_for with timeout
- [ ] `from parrot.bots.mixins import IntentRouterMixin` works
- [ ] No linting errors: `ruff check parrot/bots/mixins/`

---

## Test Specification

```python
# tests/bots/test_intent_router.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.registry.capabilities.models import (
    IntentRouterConfig, RoutingDecision, RoutingTrace, RoutingType,
    CapabilityEntry, ResourceType, RouterCandidate, TraceEntry,
)
from parrot.bots.mixins.intent_router import IntentRouterMixin


class MockBot:
    """Mock base bot for MRO testing."""
    def __init__(self):
        self.logger = MagicMock()

    async def conversation(self, prompt, **kwargs):
        return f"base response: {prompt}"

    async def ask(self, prompt, **kwargs):
        return f"ask response: {prompt}"


class RouterBot(IntentRouterMixin, MockBot):
    """Test class combining mixin with mock bot."""
    pass


@pytest.fixture
def bot():
    return RouterBot()


@pytest.fixture
def config():
    return IntentRouterConfig(
        confidence_threshold=0.7,
        hitl_threshold=0.3,
        strategy_timeout_s=5.0,
    )


@pytest.fixture
def mock_registry():
    registry = MagicMock()
    registry.search = AsyncMock(return_value=[])
    return registry


class TestRouterInactive:
    @pytest.mark.asyncio
    async def test_passthrough_when_inactive(self, bot):
        result = await bot.conversation("hello")
        assert result == "base response: hello"
        assert bot._router_active is False


class TestConfigureRouter:
    def test_activates_router(self, bot, config, mock_registry):
        bot.configure_router(config, mock_registry)
        assert bot._router_active is True
        assert bot._router_config is config
        assert bot._capability_registry is mock_registry


class TestDiscoverStrategies:
    def test_detects_vector_store(self, bot, config, mock_registry):
        bot.configure_router(config, mock_registry)
        bot.vector_store = MagicMock()
        strategies = bot._discover_strategies("test")
        assert RoutingType.VECTOR_SEARCH in strategies

    def test_detects_dataset_manager(self, bot, config, mock_registry):
        bot.configure_router(config, mock_registry)
        bot.dataset_manager = MagicMock()
        strategies = bot._discover_strategies("test")
        assert RoutingType.DATASET in strategies

    def test_free_llm_always_available(self, bot, config, mock_registry):
        bot.configure_router(config, mock_registry)
        strategies = bot._discover_strategies("test")
        assert RoutingType.FREE_LLM in strategies


class TestExecuteWithCascade:
    @pytest.mark.asyncio
    async def test_primary_succeeds(self, bot, config, mock_registry):
        bot.configure_router(config, mock_registry)
        decision = RoutingDecision(
            routing_type=RoutingType.VECTOR_SEARCH,
            confidence=0.9,
        )
        bot._execute_strategy = AsyncMock(return_value="found context")
        context, trace = await bot._execute_with_cascade(decision, "test query")
        assert context == "found context"
        assert len(trace.entries) >= 1

    @pytest.mark.asyncio
    async def test_cascade_on_primary_failure(self, bot, config, mock_registry):
        bot.configure_router(config, mock_registry)
        decision = RoutingDecision(
            routing_type=RoutingType.VECTOR_SEARCH,
            cascades=[RoutingType.DATASET, RoutingType.FREE_LLM],
            confidence=0.8,
        )
        bot._execute_strategy = AsyncMock(side_effect=[None, "cascade context"])
        context, trace = await bot._execute_with_cascade(decision, "test query")
        assert context == "cascade context"


class TestHITL:
    @pytest.mark.asyncio
    async def test_hitl_on_low_confidence(self, bot, config, mock_registry):
        bot.configure_router(config, mock_registry)
        # Mock _route to return HITL decision
        bot._fast_path = MagicMock(return_value=RoutingDecision(
            routing_type=RoutingType.DATASET,
            confidence=0.1,  # Below hitl_threshold of 0.3
        ))
        bot._llm_route = AsyncMock(return_value=None)
        result = await bot.conversation("ambiguous query")
        # Should return clarifying question, not base response
        assert isinstance(result, str)


class TestTimeout:
    @pytest.mark.asyncio
    async def test_strategy_timeout(self, bot, config, mock_registry):
        config.strategy_timeout_s = 0.01  # Very short timeout
        bot.configure_router(config, mock_registry)

        async def slow_strategy(*args, **kwargs):
            import asyncio
            await asyncio.sleep(10)
            return "too slow"

        bot._run_vector_search = slow_strategy
        result = await bot._execute_strategy(
            RoutingType.VECTOR_SEARCH, "test", []
        )
        assert result is None  # Timed out
```

---

## Agent Instructions

1. Read this task file completely before starting.
2. Read the spec at `sdd/specs/intent-router.spec.md` for full context on Module 3.
3. Verify TASK-489 and TASK-490 are complete: models and registry must be importable.
4. Read `parrot/bots/base.py` to understand `AbstractBot.conversation()` signature and MRO.
5. Read `parrot/bots/agents/` to understand the Agent class that will mix this in.
6. Implement the code changes described in **Scope** and **Files to Create / Modify**.
7. Follow the patterns in **Implementation Notes** exactly.
8. Pay special attention to MRO: `super().conversation()` must work correctly.
9. Run `ruff check` on all modified/created files.
10. Run the tests in **Test Specification** with `pytest`.
11. Do NOT implement anything outside the **Scope** section.
12. When done, fill in the **Completion Note** below and commit.

---

## Completion Note

*(Agent fills this in when done)*
