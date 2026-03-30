# TASK-492: AbstractBot Touch-Point

**Feature**: intent-router
**Spec**: `sdd/specs/intent-router.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-491
**Assigned-to**: unassigned

---

## Context

> Implements Module 4 from the spec. Minimal change to AbstractBot.conversation() to
> accept `injected_context` kwarg from IntentRouterMixin. When injected_context is
> provided, use it instead of running the default RAG pipeline.

---

## Scope

- Modify `AbstractBot.conversation()` (or `BaseBot.ask()`) to:
  - `kwargs.pop("injected_context", None)` — extract router-provided context.
  - `kwargs.pop("routing_decision", None)` — extract routing metadata (for logging).
  - If `injected_context is not None`, use it as context instead of calling `_build_vector_context()`.
- Write unit tests verifying:
  - With injected_context → uses it, skips RAG.
  - Without injected_context → behaves exactly as today.

**NOT in scope**: IntentRouterMixin itself. Any changes to ask() beyond the kwargs handling.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/base.py` | MODIFY | Add injected_context handling to conversation()/ask() |
| `tests/bots/test_abstractbot_routing.py` | CREATE | Unit tests for the touch-point |

---

## Implementation Notes

### Pattern to Follow
```python
# In BaseBot.ask() or conversation() — minimal change:
injected_context = kwargs.pop("injected_context", None)
kwargs.pop("routing_decision", None)

# Later, where vector context is built:
if injected_context is not None:
    context = injected_context          # router resolved it
elif self._vector_store is not None:
    context = await self._retrieve(query)  # existing RAG behaviour
else:
    context = ""
```

### Key Constraints
- This is a MINIMAL change — one kwargs.pop() + one conditional block.
- Must not alter behavior for agents without IntentRouter.
- No new imports needed beyond what's already in base.py.

### References in Codebase
- `parrot/bots/base.py:495` — BaseBot.ask() where vector context is built
- `parrot/bots/base.py:592` — context retrieval section

---

## Acceptance Criteria

- [ ] `injected_context` kwarg accepted and used when present
- [ ] `routing_decision` kwarg accepted and popped (for logging/metadata)
- [ ] Without injected_context, behavior is identical to current
- [ ] All existing tests still pass
- [ ] New tests pass: `pytest tests/bots/test_abstractbot_routing.py -v`

---

## Test Specification

```python
class TestAbstractBotRoutingTouchpoint:
    async def test_injected_context_used(self, mock_bot):
        """When injected_context provided, skip RAG and use it."""
        result = await mock_bot.ask("test", injected_context="pre-routed context")
        # Verify _build_vector_context was NOT called
        # Verify the injected context was used

    async def test_no_injected_context_unchanged(self, mock_bot):
        """Without injected_context, normal RAG behavior."""
        result = await mock_bot.ask("test")
        # Verify _build_vector_context WAS called (if vector store present)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-492-abstractbot-touchpoint.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
