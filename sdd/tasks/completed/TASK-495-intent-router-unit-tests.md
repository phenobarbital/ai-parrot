# TASK-495: Intent Router Unit Tests

**Feature**: intent-router
**Spec**: `sdd/specs/intent-router.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-489, TASK-490, TASK-491, TASK-492, TASK-493, TASK-494
**Assigned-to**: unassigned

---

## Context

> Cross-cutting unit test suite that validates the integration between all intent-router modules. While each previous task created its own focused tests, this task adds tests that exercise interactions between components: cascade chains, exhaustive mode with mixed results, HITL edge cases, RoutingTrace completeness, MRO correctness, and RoutingTrace in AIMessage metadata.
> Implements spec Section 3 — Module 7 (Intent Router Unit Tests).

---

## Scope

- Extend existing test files from TASK-489 through TASK-494 with cross-cutting tests:
  - **Cascade chain tests**: primary → cascade1 → cascade2 → FALLBACK flow through the full chain.
  - **Exhaustive mode with mixed results**: some strategies succeed, some fail, verify concatenated output.
  - **HITL threshold edge cases**: confidence exactly at threshold, just below, just above.
  - **RoutingTrace completeness**: verify all entries are populated with correct routing_type, produced_context, elapsed_ms.
  - **MRO correctness**: verify IntentRouterMixin cooperates with AbstractBot via Python MRO.
  - **RoutingTrace in AIMessage metadata**: verify trace appears in metadata after full conversation flow.
- No new source files — only modify/extend existing test files.

**NOT in scope**: E2E integration tests (TASK-496), new source code changes, performance testing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/bots/test_intent_router.py` | MODIFY | Add cascade chain, exhaustive, HITL edge case, MRO tests |
| `tests/bots/test_abstractbot_routing.py` | MODIFY | Add RoutingTrace metadata completeness tests |
| `tests/registry/test_capability_models.py` | MODIFY | Add edge case validation tests |
| `tests/registry/test_capability_registry.py` | MODIFY | Add cross-component interaction tests |

---

## Implementation Notes

### Pattern to Follow
```python
# tests/bots/test_intent_router.py — additional classes

class TestCascadeChain:
    """Test full cascade flow: primary → cascade1 → cascade2 → FALLBACK."""

    @pytest.mark.asyncio
    async def test_full_cascade_to_fallback(self, bot, config, mock_registry):
        """When all strategies fail, cascade exhausts and hits FALLBACK."""
        bot.configure_router(config, mock_registry)
        decision = RoutingDecision(
            routing_type=RoutingType.GRAPH_PAGEINDEX,
            cascades=[RoutingType.DATASET, RoutingType.VECTOR_SEARCH],
            confidence=0.8,
        )
        # All strategies return None
        bot._execute_strategy = AsyncMock(return_value=None)
        context, trace = await bot._execute_with_cascade(decision, "test")
        assert context is None
        assert len(trace.entries) >= 3  # primary + 2 cascades

    @pytest.mark.asyncio
    async def test_cascade_stops_on_first_success(self, bot, config, mock_registry):
        """Cascade stops as soon as one strategy produces context."""
        bot.configure_router(config, mock_registry)
        decision = RoutingDecision(
            routing_type=RoutingType.GRAPH_PAGEINDEX,
            cascades=[RoutingType.DATASET, RoutingType.VECTOR_SEARCH],
            confidence=0.8,
        )
        bot._execute_strategy = AsyncMock(
            side_effect=[None, "dataset context", "should not reach"]
        )
        context, trace = await bot._execute_with_cascade(decision, "test")
        assert context == "dataset context"
        assert bot._execute_strategy.call_count == 2  # primary + first cascade


class TestExhaustiveMode:
    """Test exhaustive mode: all strategies run and results concatenated."""

    @pytest.mark.asyncio
    async def test_mixed_results_concatenated(self, bot, config, mock_registry):
        """Successful strategies have their results concatenated with labels."""
        config.exhaustive_mode = True
        bot.configure_router(config, mock_registry)
        bot._execute_strategy = AsyncMock(
            side_effect=["graph result", None, "vector result"]
        )
        strategies = [
            RoutingType.GRAPH_PAGEINDEX,
            RoutingType.DATASET,
            RoutingType.VECTOR_SEARCH,
        ]
        context, trace = await bot._execute_exhaustive(
            strategies, "test", []
        )
        assert "graph result" in context
        assert "vector result" in context
        assert len(trace.entries) == 3

    @pytest.mark.asyncio
    async def test_all_fail_returns_empty(self, bot, config, mock_registry):
        config.exhaustive_mode = True
        bot.configure_router(config, mock_registry)
        bot._execute_strategy = AsyncMock(return_value=None)
        strategies = [RoutingType.DATASET, RoutingType.VECTOR_SEARCH]
        context, trace = await bot._execute_exhaustive(
            strategies, "test", []
        )
        assert not context or context.strip() == ""


class TestHITLEdgeCases:
    """Test HITL threshold boundary conditions."""

    @pytest.mark.asyncio
    async def test_confidence_exactly_at_threshold(self, bot, config, mock_registry):
        """Confidence == hitl_threshold should NOT trigger HITL."""
        config.hitl_threshold = 0.3
        bot.configure_router(config, mock_registry)
        # decision with confidence = 0.3 (exactly at threshold)
        # Should NOT be demoted to HITL
        pass

    @pytest.mark.asyncio
    async def test_confidence_just_below_threshold(self, bot, config, mock_registry):
        """Confidence < hitl_threshold triggers HITL."""
        config.hitl_threshold = 0.3
        bot.configure_router(config, mock_registry)
        # decision with confidence = 0.29
        # Should be demoted to HITL
        pass

    @pytest.mark.asyncio
    async def test_confidence_just_above_threshold(self, bot, config, mock_registry):
        """Confidence > hitl_threshold proceeds normally."""
        config.hitl_threshold = 0.3
        bot.configure_router(config, mock_registry)
        # decision with confidence = 0.31
        # Should NOT be demoted to HITL
        pass


class TestRoutingTraceCompleteness:
    """Verify all trace entries have required fields populated."""

    @pytest.mark.asyncio
    async def test_trace_entries_have_routing_type(self, bot, config, mock_registry):
        bot.configure_router(config, mock_registry)
        decision = RoutingDecision(
            routing_type=RoutingType.VECTOR_SEARCH,
            confidence=0.9,
        )
        bot._execute_strategy = AsyncMock(return_value="context")
        _, trace = await bot._execute_with_cascade(decision, "test")
        for entry in trace.entries:
            assert entry.routing_type is not None
            assert isinstance(entry.elapsed_ms, float)
            assert isinstance(entry.produced_context, bool)


class TestMROCorrectness:
    """Verify IntentRouterMixin cooperates with AbstractBot via MRO."""

    def test_mro_order(self):
        """IntentRouterMixin.conversation appears before MockBot.conversation in MRO."""
        mro = RouterBot.__mro__
        mixin_idx = next(
            i for i, cls in enumerate(mro) if cls is IntentRouterMixin
        )
        bot_idx = next(
            i for i, cls in enumerate(mro) if cls is MockBot
        )
        assert mixin_idx < bot_idx

    @pytest.mark.asyncio
    async def test_super_conversation_called(self, bot, config, mock_registry):
        """IntentRouterMixin calls super().conversation() which reaches MockBot."""
        bot.configure_router(config, mock_registry)
        bot._route = AsyncMock(return_value=(None, None, None))
        result = await bot.conversation("test prompt")
        assert "base response" in result
```

### Key Constraints
- **No new source files**: This task only extends existing test files.
- **Use existing fixtures**: Reuse fixtures from the test files created in previous tasks.
- **Mocks must be realistic**: Mock strategy runners and registry to simulate real flows.
- **Edge cases matter**: Test boundary conditions (exactly at threshold, empty inputs, all-fail scenarios).

### References in Codebase
- `tests/bots/test_intent_router.py` — from TASK-491
- `tests/bots/test_abstractbot_routing.py` — from TASK-492
- `tests/registry/test_capability_models.py` — from TASK-489
- `tests/registry/test_capability_registry.py` — from TASK-490

---

## Acceptance Criteria

- [ ] Cascade chain test: primary → cascade1 → cascade2 → FALLBACK verified
- [ ] Cascade stops on first successful strategy verified
- [ ] Exhaustive mode: mixed results concatenated with labels verified
- [ ] Exhaustive mode: all-fail returns empty context verified
- [ ] HITL: confidence exactly at threshold does NOT trigger HITL
- [ ] HITL: confidence below threshold triggers HITL
- [ ] HITL: confidence above threshold proceeds normally
- [ ] RoutingTrace entries all have routing_type, elapsed_ms, produced_context
- [ ] MRO: IntentRouterMixin appears before base bot in resolution order
- [ ] MRO: super().conversation() correctly chains to base bot
- [ ] RoutingTrace appears in AIMessage.metadata after full conversation flow
- [ ] All tests pass: `pytest tests/bots/test_intent_router.py tests/bots/test_abstractbot_routing.py tests/registry/test_capability_models.py tests/registry/test_capability_registry.py`

---

## Test Specification

See **Implementation Notes** above for the full test code to add to existing files.

---

## Agent Instructions

1. Read this task file completely before starting.
2. Read the spec at `sdd/specs/intent-router.spec.md` for full context on Module 7.
3. Verify all prior tasks (TASK-489 through TASK-494) are complete.
4. Read the existing test files to understand current fixtures and test structure.
5. Add the new test classes to the existing test files as described in **Implementation Notes**.
6. Run `ruff check` on all modified test files.
7. Run the full test suite: `pytest tests/bots/test_intent_router.py tests/bots/test_abstractbot_routing.py tests/registry/test_capability_models.py tests/registry/test_capability_registry.py -v`.
8. Do NOT modify source code — only test files.
9. When done, fill in the **Completion Note** below and commit.

---

## Completion Note

*(Agent fills this in when done)*
