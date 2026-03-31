# TASK-496: Intent Router Integration Tests

**Feature**: intent-router
**Spec**: `sdd/specs/intent-router.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-489, TASK-490, TASK-491, TASK-492, TASK-493, TASK-494
**Assigned-to**: unassigned

---

## Context

> End-to-end integration tests that verify the full intent routing pipeline works correctly with realistic scenarios. These tests use mocked external services but exercise the complete flow from user query through routing decision to final response.
> Implements spec Section 3 — Module 8 (Intent Router Integration Tests).

---

## Scope

- Create `tests/bots/test_intent_router_e2e.py` with the following E2E test scenarios:
  1. **Dataset routing**: user asks about sales data → routed to DATASET strategy → DatasetManager queried → context injected → LLM response.
  2. **Graph routing**: user asks about product relationships → routed to GRAPH_PAGEINDEX → graph store queried → context injected → LLM response.
  3. **Vector fallback**: user asks a general question → primary strategy fails → cascade to VECTOR_SEARCH → vector store queried → LLM response.
  4. **LLM fallback with trace**: all strategies fail → FALLBACK with trace summary → LLM responds with trace context.
  5. **HITL cycle**: ambiguous query → HITL (clarifying question) → user clarifies → re-route → successful resolution.
  6. **Cascade flow**: GRAPH_PAGEINDEX → DATASET → VECTOR_SEARCH → successful at DATASET.
  7. **Exhaustive synthesis**: exhaustive mode → all strategies run → results concatenated → LLM synthesizes.
  8. **No strategies available**: agent has no tools/stores configured → graceful fallback to FREE_LLM.
  9. **Resolver demotion flow**: query that would have used OntologyIntentResolver → now goes through IntentRouterMixin → resolver used only for AQL planning.
- All external services (LLM, vector store, dataset manager, graph store) are mocked.
- Tests verify the full pipeline including RoutingTrace in AIMessage metadata.

**NOT in scope**: Performance/load testing, real LLM calls, real database connections.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/bots/test_intent_router_e2e.py` | CREATE | Full E2E integration test suite |

---

## Implementation Notes

### Pattern to Follow
```python
# tests/bots/test_intent_router_e2e.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.registry.capabilities.models import (
    CapabilityEntry, IntentRouterConfig, ResourceType,
    RoutingDecision, RoutingTrace, RoutingType,
    RouterCandidate, TraceEntry,
)
from parrot.registry.capabilities.registry import CapabilityRegistry
from parrot.bots.mixins.intent_router import IntentRouterMixin


# --- Test Infrastructure ---

class MockBot:
    """Simulates AbstractBot with minimal interface."""
    def __init__(self):
        self.logger = MagicMock()
        self._last_kwargs = {}

    async def conversation(self, prompt, **kwargs):
        self._last_kwargs = kwargs
        context = kwargs.get("injected_context", "")
        trace = kwargs.get("routing_trace")
        response = MagicMock()
        response.content = f"LLM response with context: {context[:50]}" if context else f"LLM response: {prompt}"
        response.metadata = {}
        if trace:
            response.metadata["routing_trace"] = trace.model_dump()
        return response

    async def ask(self, prompt, **kwargs):
        return f"Fallback answer: {prompt}"

    async def invoke(self, prompt, **kwargs):
        return MagicMock()


class E2ERouterBot(IntentRouterMixin, MockBot):
    """Full router bot for E2E testing."""
    pass


@pytest.fixture
def e2e_bot():
    bot = E2ERouterBot()
    return bot


@pytest.fixture
def e2e_config():
    return IntentRouterConfig(
        confidence_threshold=0.7,
        hitl_threshold=0.3,
        strategy_timeout_s=5.0,
        exhaustive_mode=False,
        max_cascades=3,
    )


@pytest.fixture
def populated_registry():
    """Registry with sample capabilities pre-registered."""
    registry = CapabilityRegistry()
    registry.register(CapabilityEntry(
        name="sales_dataset",
        description="Monthly and quarterly sales revenue data",
        resource_type=ResourceType.DATASET,
    ))
    registry.register(CapabilityEntry(
        name="product_graph",
        description="Product category and relationship graph",
        resource_type=ResourceType.GRAPH_NODE,
    ))
    registry.register(CapabilityEntry(
        name="knowledge_base",
        description="Company knowledge base and documentation",
        resource_type=ResourceType.VECTOR_COLLECTION,
    ))
    registry.register(CapabilityEntry(
        name="weather_tool",
        description="Get current weather for a city",
        resource_type=ResourceType.TOOL,
    ))
    return registry


# --- E2E Test Scenarios ---

class TestDatasetRouting:
    """Scenario 1: User asks about data → routed to dataset strategy."""

    @pytest.mark.asyncio
    async def test_sales_query_routes_to_dataset(
        self, e2e_bot, e2e_config, populated_registry
    ):
        e2e_bot.configure_router(e2e_config, populated_registry)
        e2e_bot.dataset_manager = MagicMock()
        e2e_bot.dataset_manager.query = AsyncMock(
            return_value="Q1 Sales: $1.2M, Q2 Sales: $1.5M"
        )
        # Mock the routing decision
        e2e_bot._llm_route = AsyncMock(return_value=RoutingDecision(
            routing_type=RoutingType.DATASET,
            confidence=0.92,
            reasoning="User is asking about sales data",
        ))
        result = await e2e_bot.conversation("What were our Q1 sales?")
        assert result is not None


class TestGraphRouting:
    """Scenario 2: User asks about relationships → graph strategy."""

    @pytest.mark.asyncio
    async def test_relationship_query_routes_to_graph(
        self, e2e_bot, e2e_config, populated_registry
    ):
        e2e_bot.configure_router(e2e_config, populated_registry)
        e2e_bot.graph_store = MagicMock()
        e2e_bot.graph_store.query = AsyncMock(
            return_value="Product A → Category: Electronics → Related: Product B, C"
        )
        e2e_bot._llm_route = AsyncMock(return_value=RoutingDecision(
            routing_type=RoutingType.GRAPH_PAGEINDEX,
            confidence=0.88,
        ))
        result = await e2e_bot.conversation(
            "What products are related to Product A?"
        )
        assert result is not None


class TestVectorFallback:
    """Scenario 3: Primary fails → cascade to vector search."""

    @pytest.mark.asyncio
    async def test_cascade_to_vector_search(
        self, e2e_bot, e2e_config, populated_registry
    ):
        e2e_bot.configure_router(e2e_config, populated_registry)
        e2e_bot.vector_store = MagicMock()
        e2e_bot.vector_store.search = AsyncMock(
            return_value=[{"content": "Relevant document found"}]
        )
        e2e_bot._llm_route = AsyncMock(return_value=RoutingDecision(
            routing_type=RoutingType.GRAPH_PAGEINDEX,
            cascades=[RoutingType.VECTOR_SEARCH],
            confidence=0.75,
        ))
        # Graph fails, vector succeeds
        e2e_bot._run_graph_pageindex = AsyncMock(return_value=None)
        e2e_bot._run_vector_search = AsyncMock(
            return_value="Relevant document found"
        )
        result = await e2e_bot.conversation("Tell me about our company policy")
        assert result is not None


class TestLLMFallbackWithTrace:
    """Scenario 4: All strategies fail → fallback with trace."""

    @pytest.mark.asyncio
    async def test_all_fail_triggers_fallback(
        self, e2e_bot, e2e_config, populated_registry
    ):
        e2e_bot.configure_router(e2e_config, populated_registry)
        e2e_bot._llm_route = AsyncMock(return_value=RoutingDecision(
            routing_type=RoutingType.DATASET,
            confidence=0.6,
        ))
        e2e_bot._execute_strategy = AsyncMock(return_value=None)
        result = await e2e_bot.conversation("Something completely unexpected")
        assert result is not None


class TestHITLCycle:
    """Scenario 5: Ambiguous query → clarify → re-route."""

    @pytest.mark.asyncio
    async def test_hitl_clarification_cycle(
        self, e2e_bot, e2e_config, populated_registry
    ):
        e2e_config.hitl_threshold = 0.4
        e2e_bot.configure_router(e2e_config, populated_registry)
        # First call: low confidence → HITL question
        e2e_bot._fast_path = MagicMock(return_value=None)
        e2e_bot._llm_route = AsyncMock(return_value=RoutingDecision(
            routing_type=RoutingType.DATASET,
            confidence=0.2,  # Below hitl_threshold
        ))
        result1 = await e2e_bot.conversation("data")
        assert isinstance(result1, str)  # Clarifying question

        # Second call: user clarifies, high confidence
        e2e_bot._llm_route = AsyncMock(return_value=RoutingDecision(
            routing_type=RoutingType.DATASET,
            confidence=0.9,
        ))
        e2e_bot._execute_strategy = AsyncMock(return_value="Sales data: $1M")
        result2 = await e2e_bot.conversation(
            "I meant the quarterly sales dataset"
        )
        assert result2 is not None


class TestCascadeFlow:
    """Scenario 6: Multi-step cascade GRAPH → DATASET → VECTOR."""

    @pytest.mark.asyncio
    async def test_three_step_cascade(
        self, e2e_bot, e2e_config, populated_registry
    ):
        e2e_bot.configure_router(e2e_config, populated_registry)
        decision = RoutingDecision(
            routing_type=RoutingType.GRAPH_PAGEINDEX,
            cascades=[RoutingType.DATASET, RoutingType.VECTOR_SEARCH],
            confidence=0.8,
        )
        e2e_bot._fast_path = MagicMock(return_value=None)
        e2e_bot._llm_route = AsyncMock(return_value=decision)
        # Graph fails, dataset succeeds
        e2e_bot._run_graph_pageindex = AsyncMock(return_value=None)
        e2e_bot._run_dataset_query = AsyncMock(
            return_value="Dataset result found"
        )
        e2e_bot._run_vector_search = AsyncMock(
            return_value="Should not reach"
        )
        result = await e2e_bot.conversation("Find product info")
        assert result is not None


class TestExhaustiveSynthesis:
    """Scenario 7: Exhaustive mode runs all, concatenates."""

    @pytest.mark.asyncio
    async def test_exhaustive_concatenation(
        self, e2e_bot, e2e_config, populated_registry
    ):
        e2e_config.exhaustive_mode = True
        e2e_bot.configure_router(e2e_config, populated_registry)
        e2e_bot.dataset_manager = MagicMock()
        e2e_bot.vector_store = MagicMock()
        e2e_bot._run_dataset_query = AsyncMock(return_value="Dataset: Q1=$1M")
        e2e_bot._run_vector_search = AsyncMock(
            return_value="Vector: Policy doc found"
        )
        e2e_bot._run_free_llm = AsyncMock(return_value=None)
        result = await e2e_bot.conversation("Give me everything about Q1")
        assert result is not None


class TestNoStrategiesAvailable:
    """Scenario 8: No tools/stores configured → graceful FREE_LLM."""

    @pytest.mark.asyncio
    async def test_bare_agent_falls_back_to_free_llm(
        self, e2e_bot, e2e_config, populated_registry
    ):
        e2e_bot.configure_router(e2e_config, populated_registry)
        # No vector_store, no dataset_manager, no tools, no graph_store
        result = await e2e_bot.conversation("Hello, how are you?")
        assert result is not None


class TestResolverDemotionFlow:
    """Scenario 9: Query goes through IntentRouterMixin, resolver for AQL only."""

    @pytest.mark.asyncio
    async def test_resolver_used_for_aql_only(
        self, e2e_bot, e2e_config, populated_registry
    ):
        e2e_bot.configure_router(e2e_config, populated_registry)
        e2e_bot.graph_store = MagicMock()

        # Mock the ontology resolver as an AQL planner
        mock_resolver = MagicMock()
        mock_resolver.resolve = AsyncMock(return_value=MagicMock(
            aql_query="FOR doc IN products FILTER doc.category == 'electronics' RETURN doc",
            action="graph_query",
        ))
        e2e_bot._ontology_resolver = mock_resolver

        e2e_bot._llm_route = AsyncMock(return_value=RoutingDecision(
            routing_type=RoutingType.GRAPH_PAGEINDEX,
            confidence=0.9,
        ))
        e2e_bot._run_graph_pageindex = AsyncMock(
            return_value="Graph: 5 electronic products found"
        )
        result = await e2e_bot.conversation(
            "List all electronic products"
        )
        assert result is not None


class TestRoutingTraceInMetadata:
    """Verify RoutingTrace appears in AIMessage metadata in E2E flow."""

    @pytest.mark.asyncio
    async def test_trace_in_response_metadata(
        self, e2e_bot, e2e_config, populated_registry
    ):
        e2e_bot.configure_router(e2e_config, populated_registry)
        e2e_bot.dataset_manager = MagicMock()
        e2e_bot._llm_route = AsyncMock(return_value=RoutingDecision(
            routing_type=RoutingType.DATASET,
            confidence=0.9,
        ))
        e2e_bot._execute_strategy = AsyncMock(return_value="context data")
        result = await e2e_bot.conversation("Show me sales data")
        # Verify trace is in metadata
        if hasattr(result, 'metadata'):
            assert "routing_trace" in result.metadata
            trace_data = result.metadata["routing_trace"]
            assert "mode" in trace_data
            assert "entries" in trace_data
```

### Key Constraints
- **All external services mocked**: No real LLM calls, no real DB connections, no real vector stores.
- **Full pipeline**: Each test exercises the complete flow from `conversation()` through routing to response.
- **Realistic scenarios**: Test names and queries should reflect real-world usage patterns.
- **RoutingTrace verification**: At least one test must verify trace appears in AIMessage.metadata.
- **Independence**: Each test class is independent and can run in isolation.

### References in Codebase
- `parrot/bots/mixins/intent_router.py` — IntentRouterMixin (TASK-491)
- `parrot/bots/base.py` — AbstractBot.conversation() (TASK-492)
- `parrot/registry/capabilities/registry.py` — CapabilityRegistry (TASK-490)
- `parrot/knowledge/ontology/intent.py` — OntologyIntentResolver (TASK-494)

---

## Acceptance Criteria

- [ ] Test file `tests/bots/test_intent_router_e2e.py` created
- [ ] Scenario 1: Dataset routing E2E test passes
- [ ] Scenario 2: Graph routing E2E test passes
- [ ] Scenario 3: Vector fallback cascade E2E test passes
- [ ] Scenario 4: LLM fallback with trace E2E test passes
- [ ] Scenario 5: HITL clarification cycle E2E test passes
- [ ] Scenario 6: Multi-step cascade E2E test passes
- [ ] Scenario 7: Exhaustive synthesis E2E test passes
- [ ] Scenario 8: No strategies available E2E test passes
- [ ] Scenario 9: Resolver demotion flow E2E test passes
- [ ] RoutingTrace in AIMessage metadata verified in at least one E2E test
- [ ] All tests pass: `pytest tests/bots/test_intent_router_e2e.py -v`
- [ ] No linting errors: `ruff check tests/bots/test_intent_router_e2e.py`

---

## Test Specification

See **Implementation Notes** above for the full test code.

---

## Agent Instructions

1. Read this task file completely before starting.
2. Read the spec at `sdd/specs/intent-router.spec.md` for full context on Module 8.
3. Verify all prior tasks (TASK-489 through TASK-494) are complete.
4. Read the source files from prior tasks to understand actual method signatures and behavior.
5. Create the E2E test file as described in **Implementation Notes**.
6. Adapt mock setups to match actual class interfaces (method signatures may differ from examples).
7. Run `ruff check` on the test file.
8. Run the tests: `pytest tests/bots/test_intent_router_e2e.py -v`.
9. Do NOT modify source code — only create/modify test files.
10. When done, fill in the **Completion Note** below and commit.

---

## Completion Note

*(Agent fills this in when done)*
