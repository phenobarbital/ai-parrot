# TASK-492: AbstractBot Touch-Point & RoutingTrace in AIMessage

**Feature**: intent-router
**Spec**: `sdd/specs/intent-router.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-491
**Assigned-to**: unassigned

---

## Context

> Modifies AbstractBot.conversation() to accept and use the routing context injected by IntentRouterMixin. Also implements the resolved open question: RoutingTrace is attached to AIMessage.metadata so that integration handlers (Telegram, Slack, etc.) can optionally display routing info.
> Implements spec Section 3 — Module 4 (AbstractBot Touch-Point) plus the resolved open question on RoutingTrace exposure.

---

## Scope

- Modify `AbstractBot.conversation()` in `parrot/bots/base.py`:
  - Pop `injected_context` from kwargs: `injected_context = kwargs.pop("injected_context", None)`. If present, use it as context instead of performing RAG/retrieval.
  - Pop `routing_decision` from kwargs: `routing_decision = kwargs.pop("routing_decision", None)`. Store for metadata purposes.
  - Pop `routing_trace` from kwargs: `routing_trace = kwargs.pop("routing_trace", None)`. Will be attached to AIMessage.
- After the LLM call produces the AIMessage response:
  - If `routing_trace` was provided, attach it: `response.metadata["routing_trace"] = routing_trace.model_dump()`.
  - If `routing_decision` was provided, optionally attach: `response.metadata["routing_decision"] = routing_decision.model_dump()`.
- Ensure existing behavior is unchanged when these kwargs are not present (no regression).

**NOT in scope**: IntentRouterMixin implementation (TASK-491), auto-registration hooks (TASK-493), test suite expansion (TASK-495).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/base.py` | MODIFY | Add kwargs popping and metadata attachment in conversation() |
| `tests/bots/test_abstractbot_routing.py` | CREATE | Tests for the new routing kwargs handling |

---

## Implementation Notes

### Pattern to Follow
```python
# In AbstractBot.conversation() — early in the method:
injected_context = kwargs.pop("injected_context", None)
routing_decision = kwargs.pop("routing_decision", None)
routing_trace = kwargs.pop("routing_trace", None)

# If injected_context is provided, use it instead of RAG retrieval:
if injected_context:
    # Skip self._retrieve_context() or equivalent
    context = injected_context
else:
    # Existing RAG/retrieval logic
    context = await self._retrieve_context(prompt)  # or however it's done

# After the LLM call produces the response (AIMessage):
if routing_trace is not None:
    if not hasattr(response, 'metadata') or response.metadata is None:
        response.metadata = {}
    response.metadata["routing_trace"] = routing_trace.model_dump()

if routing_decision is not None:
    if not hasattr(response, 'metadata') or response.metadata is None:
        response.metadata = {}
    response.metadata["routing_decision"] = routing_decision.model_dump()
```

### Key Constraints
- **Non-breaking**: When `injected_context`, `routing_decision`, and `routing_trace` are NOT in kwargs, behavior must be identical to before.
- **kwargs.pop()**: Must use `pop()` to remove these keys before passing kwargs to any downstream method that doesn't expect them.
- **AIMessage metadata**: Check `parrot/models/responses.py` for the AIMessage class. It should have a `metadata` field (dict). If it doesn't, add `metadata: dict = Field(default_factory=dict)`.
- **Import safety**: Only import RoutingTrace/RoutingDecision types if needed for isinstance checks. Use duck typing (`.model_dump()`) to avoid hard coupling.

### References in Codebase
- `parrot/bots/base.py` — `AbstractBot.conversation()` method
- `parrot/models/responses.py` — `AIMessage` class (check for metadata field)
- `parrot/bots/mixins/intent_router.py` — passes these kwargs via super().conversation()

---

## Acceptance Criteria

- [ ] `conversation()` pops `injected_context` from kwargs without error
- [ ] `conversation()` pops `routing_decision` from kwargs without error
- [ ] `conversation()` pops `routing_trace` from kwargs without error
- [ ] When `injected_context` is provided, it is used as context (RAG skipped)
- [ ] When `routing_trace` is provided, it appears in `response.metadata["routing_trace"]`
- [ ] When `routing_decision` is provided, it appears in `response.metadata["routing_decision"]`
- [ ] When none of these kwargs are provided, behavior is unchanged (no regression)
- [ ] No linting errors: `ruff check parrot/bots/base.py`

---

## Test Specification

```python
# tests/bots/test_abstractbot_routing.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.registry.capabilities.models import (
    RoutingDecision, RoutingTrace, RoutingType, TraceEntry,
)


class TestAbstractBotRoutingKwargs:
    """Test that AbstractBot.conversation() handles routing kwargs."""

    @pytest.mark.asyncio
    async def test_injected_context_used(self):
        """When injected_context is provided, RAG retrieval is skipped."""
        # Setup: create a minimal bot instance
        # Call conversation with injected_context="pre-fetched context"
        # Assert that the context was used (not RAG)
        pass  # Implementation depends on AbstractBot internals

    @pytest.mark.asyncio
    async def test_routing_trace_in_metadata(self):
        """RoutingTrace is attached to AIMessage.metadata."""
        trace = RoutingTrace(
            mode="normal",
            entries=[
                TraceEntry(
                    routing_type=RoutingType.VECTOR_SEARCH,
                    produced_context=True,
                    elapsed_ms=50.0,
                )
            ],
            elapsed_ms=100.0,
        )
        # Setup: create bot, call conversation with routing_trace=trace
        # Assert response.metadata["routing_trace"] == trace.model_dump()
        pass

    @pytest.mark.asyncio
    async def test_routing_decision_in_metadata(self):
        """RoutingDecision is attached to AIMessage.metadata."""
        decision = RoutingDecision(
            routing_type=RoutingType.DATASET,
            confidence=0.85,
            reasoning="User asked about sales data",
        )
        # Setup: create bot, call conversation with routing_decision=decision
        # Assert response.metadata["routing_decision"] == decision.model_dump()
        pass

    @pytest.mark.asyncio
    async def test_no_routing_kwargs_unchanged_behavior(self):
        """Without routing kwargs, conversation behaves as before."""
        # Setup: create bot, call conversation without routing kwargs
        # Assert: normal flow, no metadata keys added
        pass

    @pytest.mark.asyncio
    async def test_kwargs_popped_not_forwarded(self):
        """Routing kwargs are popped and not forwarded to downstream methods."""
        # Setup: create bot with a spy on internal methods
        # Call conversation with injected_context, routing_trace, routing_decision
        # Assert these keys are NOT in kwargs passed to internal methods
        pass


class TestRoutingTraceSerializable:
    def test_trace_model_dump(self):
        """RoutingTrace.model_dump() produces a serializable dict."""
        trace = RoutingTrace(
            mode="exhaustive",
            entries=[
                TraceEntry(
                    routing_type=RoutingType.DATASET,
                    produced_context=True,
                    context_snippet="Sales Q1: $1.2M",
                    elapsed_ms=45.0,
                ),
                TraceEntry(
                    routing_type=RoutingType.VECTOR_SEARCH,
                    produced_context=False,
                    error="No results found",
                    elapsed_ms=30.0,
                ),
            ],
            elapsed_ms=75.0,
        )
        data = trace.model_dump()
        assert data["mode"] == "exhaustive"
        assert len(data["entries"]) == 2
        assert data["entries"][0]["produced_context"] is True
        assert data["entries"][1]["error"] == "No results found"
```

---

## Agent Instructions

1. Read this task file completely before starting.
2. Read the spec at `sdd/specs/intent-router.spec.md` for full context on Module 4 and the resolved open question on RoutingTrace exposure.
3. Verify TASK-491 is complete: `from parrot.bots.mixins.intent_router import IntentRouterMixin` must work.
4. Read `parrot/bots/base.py` carefully to understand the current `conversation()` flow.
5. Read `parrot/models/responses.py` to check AIMessage's metadata field.
6. Implement the changes described in **Scope** with minimal modifications to existing logic.
7. Ensure non-breaking: run existing tests for `parrot/bots/` to verify no regressions.
8. Run `ruff check` on all modified/created files.
9. Run the tests in **Test Specification** with `pytest`.
10. Do NOT implement anything outside the **Scope** section.
11. When done, fill in the **Completion Note** below and commit.

---

## Completion Note

*(Agent fills this in when done)*
