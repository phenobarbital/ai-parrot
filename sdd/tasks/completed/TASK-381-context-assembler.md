# TASK-381: Context Assembler

**Feature**: long-term-memory
**Spec**: `sdd/specs/long-term-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-380
**Assigned-to**: unassigned

---

## Context

This task implements the `ContextAssembler` (Module 2 from the spec) — the component responsible for priority-based token budget allocation when assembling context from multiple memory subsystems. It ensures the combined memory context never exceeds the configured token limit.

---

## Scope

- Create `parrot/memory/unified/context.py` with:
  - `ContextAssembler` class that:
    - Accepts a `max_tokens` budget and optional per-section weights
    - Allocates tokens by priority: episodic failures (highest) → relevant skills → conversation history
    - Truncates sections that exceed their allocation (truncate from oldest for conversation, from end for others)
    - Uses approximate token counting (chars / 4) with 10% headroom
    - Returns a `MemoryContext` with the assembled sections and token accounting
- Write unit tests

**NOT in scope**: Actual retrieval from memory stores (TASK-382), mixin wiring (TASK-383)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/memory/unified/context.py` | CREATE | ContextAssembler implementation |
| `tests/memory/unified/test_context.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
import logging
from .models import MemoryContext, MemoryConfig

logger = logging.getLogger(__name__)


class ContextAssembler:
    """Assembles context from multiple sources within a token budget.

    Priority order (highest first):
    1. Episodic failure warnings — critical for avoiding past mistakes
    2. Relevant skills — applicable knowledge
    3. Conversation history — recent turns (truncated from oldest)
    """

    def __init__(self, config: MemoryConfig | None = None):
        self.config = config or MemoryConfig()
        self._max_tokens = self.config.max_context_tokens

    def assemble(
        self,
        episodic_warnings: str = "",
        relevant_skills: str = "",
        conversation: str = "",
    ) -> MemoryContext:
        """Assemble context respecting token budget."""
        ...

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Approximate token count (chars / 4)."""
        return len(text) // 4

    def _truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """Truncate text to fit within token budget."""
        max_chars = max_tokens * 4
        if len(text) <= max_chars:
            return text
        return text[:max_chars - 3] + "..."
```

### Key Constraints
- Token estimation uses chars/4 — keep 10% headroom (effective budget = max_tokens * 0.9)
- Priority allocation: each section gets its weight * budget as maximum, but unused budget rolls to next priority
- Empty sections don't consume budget — their allocation rolls to remaining sections
- Conversation truncation: remove oldest turns first (split by newlines, drop from top)
- Must handle all-empty input gracefully (return empty MemoryContext)

### References in Codebase
- Brainstorm section 7.1 for the original ContextAssembler design
- `parrot/memory/episodic/store.py` — how episodic warnings are formatted

---

## Acceptance Criteria

- [ ] `ContextAssembler` assembles context within token budget
- [ ] Priority order is respected (episodic > skills > conversation)
- [ ] Unused budget from empty sections rolls to remaining sections
- [ ] Oversized sections are truncated properly
- [ ] Empty input returns empty `MemoryContext` with `tokens_used=0`
- [ ] All tests pass: `pytest tests/memory/unified/test_context.py -v`
- [ ] Import works: `from parrot.memory.unified.context import ContextAssembler`

---

## Test Specification

```python
# tests/memory/unified/test_context.py
import pytest
from parrot.memory.unified.context import ContextAssembler
from parrot.memory.unified.models import MemoryConfig


class TestContextAssembler:
    def test_assemble_within_budget(self):
        assembler = ContextAssembler(MemoryConfig(max_context_tokens=1000))
        ctx = assembler.assemble(
            episodic_warnings="Don't call unauthenticated",
            relevant_skills="Use get_schema tool",
            conversation="User: hello\nAssistant: hi",
        )
        assert ctx.tokens_used <= 1000

    def test_priority_order_episodic_first(self):
        """When budget is tight, episodic warnings take priority."""
        assembler = ContextAssembler(MemoryConfig(max_context_tokens=50))
        ctx = assembler.assemble(
            episodic_warnings="A" * 100,  # 25 tokens
            relevant_skills="B" * 200,   # 50 tokens
            conversation="C" * 200,      # 50 tokens
        )
        assert len(ctx.episodic_warnings) > 0
        assert ctx.tokens_used <= 50

    def test_empty_input(self):
        assembler = ContextAssembler()
        ctx = assembler.assemble()
        assert ctx.tokens_used == 0
        assert ctx.episodic_warnings == ""

    def test_unused_budget_rolls_over(self):
        """If episodic is empty, skills get more budget."""
        assembler = ContextAssembler(MemoryConfig(max_context_tokens=100))
        ctx = assembler.assemble(
            episodic_warnings="",
            relevant_skills="B" * 300,
            conversation="",
        )
        # Skills should get more than its default 30% since episodic is empty
        assert len(ctx.relevant_skills) > 0

    def test_conversation_truncated_from_oldest(self):
        assembler = ContextAssembler(MemoryConfig(max_context_tokens=50))
        conversation = "\n".join([f"Turn {i}" for i in range(100)])
        ctx = assembler.assemble(conversation=conversation)
        # Should contain later turns, not earlier ones
        assert "Turn 99" in ctx.conversation_summary or ctx.conversation_summary.endswith("...")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/long-term-memory.spec.md` for full context
2. **Check dependencies** — verify TASK-380 is completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-381-context-assembler.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-03-22
**Notes**: Implemented `ContextAssembler` with priority-based token allocation (episodic → skills → conversation). Unused budget rolls forward. Conversation truncates from oldest lines. All 9 tests pass.

**Deviations from spec**: none
