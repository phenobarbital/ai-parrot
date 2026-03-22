# TASK-380: Unified Memory Models

**Feature**: long-term-memory
**Spec**: `sdd/specs/long-term-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task implements the foundational Pydantic data models for the unified memory layer (Module 1 from the spec). These models are used by all subsequent modules: `ContextAssembler`, `UnifiedMemoryManager`, and `LongTermMemoryMixin`.

---

## Scope

- Create `parrot/memory/unified/__init__.py` (empty placeholder, exports added in TASK-384)
- Create `parrot/memory/unified/models.py` with:
  - `MemoryContext` — assembled context from all memory subsystems (episodic_warnings, relevant_skills, conversation_summary, tokens_used, tokens_budget) with `to_prompt_string()` method
  - `MemoryConfig` — configuration for UnifiedMemoryManager (enable flags, token budget, weights, max warnings/skills)
- Reuse `MemoryNamespace` from `parrot/memory/episodic/models.py` — do NOT duplicate
- Write unit tests

**NOT in scope**: ContextAssembler logic (TASK-381), manager logic (TASK-382), mixin (TASK-383)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/memory/unified/__init__.py` | CREATE | Package init (empty placeholder) |
| `parrot/memory/unified/models.py` | CREATE | MemoryContext, MemoryConfig models |
| `tests/memory/unified/__init__.py` | CREATE | Test package init |
| `tests/memory/unified/test_models.py` | CREATE | Unit tests for models |

---

## Implementation Notes

### Pattern to Follow
```python
# Follow existing Pydantic pattern from parrot/memory/episodic/models.py
from pydantic import BaseModel, Field

class MemoryContext(BaseModel):
    """Assembled context from all memory subsystems."""
    episodic_warnings: str = Field(default="", description="Past failure lessons")
    relevant_skills: str = Field(default="", description="Applicable skills")
    conversation_summary: str = Field(default="", description="Recent turns")
    tokens_used: int = Field(default=0)
    tokens_budget: int = Field(default=2000)

    def to_prompt_string(self) -> str:
        """Format as injectable system prompt sections.

        Output format:
        <past_failures_to_avoid>
        ...
        </past_failures_to_avoid>
        <relevant_skills>
        ...
        </relevant_skills>
        <recent_conversation>
        ...
        </recent_conversation>
        """
        ...
```

### Key Constraints
- Use Pydantic v2 `BaseModel`
- `to_prompt_string()` should skip empty sections (no empty XML tags)
- `MemoryConfig` weights must sum to 1.0 — add a `model_validator` for this
- Import `MemoryNamespace` from episodic models, do not redefine

### References in Codebase
- `parrot/memory/episodic/models.py` — existing Pydantic models, `MemoryNamespace`
- `parrot/memory/episodic/store.py` — how models are used

---

## Acceptance Criteria

- [ ] `MemoryContext` and `MemoryConfig` are valid Pydantic models
- [ ] `to_prompt_string()` renders correct XML-tagged format
- [ ] `to_prompt_string()` omits empty sections
- [ ] `MemoryConfig` validates that weights sum to 1.0
- [ ] All tests pass: `pytest tests/memory/unified/test_models.py -v`
- [ ] Import works: `from parrot.memory.unified.models import MemoryContext, MemoryConfig`

---

## Test Specification

```python
# tests/memory/unified/test_models.py
import pytest
from parrot.memory.unified.models import MemoryContext, MemoryConfig


class TestMemoryContext:
    def test_default_values(self):
        ctx = MemoryContext()
        assert ctx.episodic_warnings == ""
        assert ctx.tokens_used == 0
        assert ctx.tokens_budget == 2000

    def test_to_prompt_string_all_sections(self):
        ctx = MemoryContext(
            episodic_warnings="Don't call API without auth",
            relevant_skills="Use get_schema for DB queries",
            conversation_summary="User asked about weather",
        )
        result = ctx.to_prompt_string()
        assert "<past_failures_to_avoid>" in result
        assert "<relevant_skills>" in result
        assert "<recent_conversation>" in result

    def test_to_prompt_string_empty_sections_omitted(self):
        ctx = MemoryContext(episodic_warnings="warning only")
        result = ctx.to_prompt_string()
        assert "<past_failures_to_avoid>" in result
        assert "<relevant_skills>" not in result
        assert "<recent_conversation>" not in result


class TestMemoryConfig:
    def test_default_config(self):
        config = MemoryConfig()
        assert config.max_context_tokens == 2000
        assert config.enable_episodic is True

    def test_weights_must_sum_to_one(self):
        with pytest.raises(Exception):
            MemoryConfig(episodic_weight=0.5, skill_weight=0.5, conversation_weight=0.5)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/long-term-memory.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-380-unified-memory-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
