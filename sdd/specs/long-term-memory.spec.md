# Feature Specification: Long-Term Memory (Unified Memory Architecture)

**Feature ID**: FEAT-055
**Date**: 2026-03-22
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.7.0
**Brainstorm**: `sdd/proposals/long-term-memory.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot agents have two independent memory subsystems — **EpisodicMemoryStore** (FEAT-045, implemented) and **SkillRegistry** (implemented) — plus the existing **ConversationMemory** backends. However, there is no unified layer that:

1. **Coordinates retrieval** across all three memory types in a single query.
2. **Manages token budgets** — each subsystem competes for context window space with no arbitration.
3. **Provides a single mixin** for agents to opt into long-term memory without manually wiring episodic + skills + conversation.
4. **Handles lifecycle** — configure, checkpoint, cleanup — across all subsystems together.
5. **Assembles context** with priority-based allocation (failure warnings > relevant skills > conversation history).

Without this layer, agents must manually orchestrate each memory subsystem, leading to boilerplate, inconsistent context injection, and no token budget enforcement.

### Goals

- Implement `UnifiedMemoryManager` that coordinates episodic, skills, and conversation memory.
- Implement `ContextAssembler` with priority-based token budgeting.
- Implement `LongTermMemoryMixin` as a single opt-in mixin for any bot/agent.
- Integrate with `AbstractBot.ask()` via hooks (context retrieval pre-LLM, interaction recording post-LLM).
- Support parallel retrieval from all memory subsystems for low latency.

### Non-Goals (explicitly out of scope)

- Modifying EpisodicMemoryStore internals (FEAT-045, already implemented).
- Modifying SkillRegistry internals (already implemented).
- Graph-based memory (ArangoDB) — future enhancement.
- ThoughtChain / hash-chained audit log — future enhancement.
- Changing ConversationMemory ABC or existing backends.
- Multi-agent SharedBrain across crews — future enhancement.

---

## 2. Architectural Design

### Overview

A coordination layer (`UnifiedMemoryManager`) sits above the three existing memory subsystems and provides a single interface for context retrieval and interaction recording. A `ContextAssembler` handles token budget allocation with configurable priorities. A `LongTermMemoryMixin` wires everything into the agent lifecycle.

### Component Diagram

```
                        ┌─────────────────────┐
                        │  LongTermMemoryMixin │
                        │  (agent opt-in)      │
                        └──────────┬───────────┘
                                   │
                        ┌──────────▼───────────┐
                        │ UnifiedMemoryManager │
                        │  - configure()       │
                        │  - get_context()     │
                        │  - record()          │
                        │  - cleanup()         │
                        └──────────┬───────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                     │
    ┌─────────▼─────────┐ ┌───────▼────────┐ ┌─────────▼──────────┐
    │ EpisodicMemoryStore│ │ SkillRegistry  │ │ ConversationMemory │
    │ (FEAT-045)         │ │ (existing)     │ │ (existing ABC)     │
    └────────────────────┘ └────────────────┘ └────────────────────┘
              │                    │                     │
    ┌─────────▼─────────┐         │           ┌─────────▼──────────┐
    │ FAISS / PgVector   │  FAISS + Files     │ Redis / File / Mem │
    └────────────────────┘                    └────────────────────┘

    ┌─────────────────────────────────────────────────────────────┐
    │                     ContextAssembler                        │
    │  Priority: failures(30%) > skills(30%) > conversation(40%) │
    │  Token budget enforcement per section                      │
    └─────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `EpisodicMemoryStore` | uses | Retrieves failure warnings, records episodes |
| `SkillRegistry` | uses | Retrieves relevant skills, optionally extracts new skills |
| `ConversationMemory` | uses | Retrieves recent turns for context |
| `AbstractBot` | extends (via mixin) | Hooks into `ask()` pre/post processing |
| `MemoryNamespace` | reuses | From `parrot/memory/episodic/models.py` |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import List, Optional


class MemoryContext(BaseModel):
    """Assembled context from all memory subsystems."""
    episodic_warnings: str = Field(default="", description="Past failure lessons")
    relevant_skills: str = Field(default="", description="Applicable skills")
    conversation_summary: str = Field(default="", description="Recent turns")
    tokens_used: int = Field(default=0, description="Total tokens consumed")
    tokens_budget: int = Field(default=2000, description="Max token budget")

    def to_prompt_string(self) -> str:
        """Format as injectable system prompt section."""
        ...


class MemoryConfig(BaseModel):
    """Configuration for UnifiedMemoryManager."""
    enable_episodic: bool = True
    enable_skills: bool = True
    enable_conversation: bool = True
    max_context_tokens: int = 2000
    episodic_max_warnings: int = 3
    skill_max_context: int = 3
    episodic_weight: float = 0.3
    skill_weight: float = 0.3
    conversation_weight: float = 0.4
    skill_auto_extract: bool = False
```

### New Public Interfaces

```python
class UnifiedMemoryManager:
    """Coordinates all memory subsystems."""

    async def configure(self, **kwargs) -> None: ...
    async def get_context_for_query(
        self, query: str, user_id: str, session_id: str
    ) -> MemoryContext: ...
    async def record_interaction(
        self, query: str, response: Any, tool_calls: list, user_id: str, session_id: str
    ) -> None: ...
    async def cleanup(self) -> None: ...


class ContextAssembler:
    """Assembles context within token budget with priority allocation."""

    def assemble(
        self,
        episodic_warnings: str,
        relevant_skills: str,
        conversation: str,
    ) -> MemoryContext: ...


class LongTermMemoryMixin:
    """Single opt-in mixin for long-term memory in any bot/agent.

    Usage:
        class MyAgent(LongTermMemoryMixin, Agent):
            enable_long_term_memory = True
    """

    enable_long_term_memory: bool = False
    episodic_inject_warnings: bool = True
    skill_inject_context: bool = True
    skill_auto_extract: bool = False
    skill_expose_tools: bool = True
    memory_max_context_tokens: int = 2000

    async def _configure_long_term_memory(self) -> None: ...
    async def get_memory_context(self, query: str, user_id: str, session_id: str) -> str: ...
```

---

## 3. Module Breakdown

### Module 1: MemoryContext Models
- **Path**: `parrot/memory/unified/models.py`
- **Responsibility**: `MemoryContext`, `MemoryConfig` Pydantic models for the unified layer.
- **Depends on**: `parrot/memory/episodic/models.py` (reuses `MemoryNamespace`)

### Module 2: ContextAssembler
- **Path**: `parrot/memory/unified/context.py`
- **Responsibility**: Priority-based token budget allocation and context string assembly. Truncates sections that exceed their allocation. Uses approximate token counting (chars/4).
- **Depends on**: Module 1

### Module 3: UnifiedMemoryManager
- **Path**: `parrot/memory/unified/manager.py`
- **Responsibility**: Coordinates parallel retrieval from episodic, skills, and conversation memory. Passes results through ContextAssembler. Records interactions post-response.
- **Depends on**: Module 1, Module 2, `EpisodicMemoryStore`, `SkillRegistry`, `ConversationMemory`

### Module 4: LongTermMemoryMixin
- **Path**: `parrot/memory/unified/mixin.py`
- **Responsibility**: Agent-facing mixin that wires `UnifiedMemoryManager` into the agent lifecycle. Provides `_configure_long_term_memory()` for `configure()` and `get_memory_context()` for `ask()`.
- **Depends on**: Module 3

### Module 5: Package Init & Exports
- **Path**: `parrot/memory/unified/__init__.py` + update `parrot/memory/__init__.py`
- **Responsibility**: Public exports. Register unified components in memory package.
- **Depends on**: Modules 1–4

### Module 6: Integration Hooks in AbstractBot
- **Path**: `parrot/bots/` (minimal modifications)
- **Responsibility**: Add optional `memory_context` parameter to `create_system_prompt()`. Add post-response hook point in `ask()` for memory recording. Changes are additive and backward-compatible (default `None`).
- **Depends on**: Module 4

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_memory_context_to_prompt_string` | Module 1 | MemoryContext renders correct prompt format |
| `test_memory_config_defaults` | Module 1 | Default config values are sensible |
| `test_context_assembler_within_budget` | Module 2 | Assembled context stays within token limit |
| `test_context_assembler_priority_order` | Module 2 | Episodic warnings prioritized over skills |
| `test_context_assembler_truncation` | Module 2 | Oversized sections get truncated |
| `test_context_assembler_empty_sections` | Module 2 | Handles missing sections gracefully |
| `test_manager_parallel_retrieval` | Module 3 | All subsystems queried concurrently |
| `test_manager_partial_subsystems` | Module 3 | Works with only episodic, only skills, or only conversation |
| `test_manager_record_interaction` | Module 3 | Records to episodic and conversation |
| `test_mixin_configure` | Module 4 | Creates manager with correct subsystems |
| `test_mixin_disabled` | Module 4 | No-op when `enable_long_term_memory = False` |
| `test_mixin_get_memory_context` | Module 4 | Returns formatted context string |

### Integration Tests

| Test | Description |
|---|---|
| `test_unified_memory_end_to_end` | Record interaction, then retrieve context for similar query |
| `test_mixin_with_agent` | Agent with mixin retrieves episodic warnings in context |

### Test Data / Fixtures

```python
@pytest.fixture
def memory_namespace():
    return MemoryNamespace(org_id="test", agent_id="test-agent", user_id="user1")

@pytest.fixture
def memory_config():
    return MemoryConfig(max_context_tokens=1000)

@pytest.fixture
def mock_episodic_store():
    """Mock EpisodicMemoryStore returning sample warnings."""
    ...

@pytest.fixture
def mock_skill_registry():
    """Mock SkillRegistry returning sample skills."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `UnifiedMemoryManager` retrieves context from episodic + skills + conversation in parallel
- [ ] `ContextAssembler` enforces token budget with priority allocation
- [ ] `LongTermMemoryMixin` is a single opt-in mixin for any `AbstractBot` subclass
- [ ] Agents with `enable_long_term_memory = True` automatically inject memory context into system prompt
- [ ] Post-response interaction recording is non-blocking (async fire-and-forget)
- [ ] All unit tests pass (`pytest tests/memory/unified/ -v`)
- [ ] No breaking changes to existing `ConversationMemory`, `EpisodicMemoryStore`, or `SkillRegistry`
- [ ] Works with partial subsystems (e.g., episodic only, no skills)
- [ ] Token budget stays within configured limit across all subsystems
- [ ] Memory retrieval latency < 200ms (p95) for in-memory/FAISS backends

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Use `AbstractBase` pattern from `parrot/base/` for any new base classes
- Async-first: all retrieval and recording methods are `async`
- Pydantic models for `MemoryContext`, `MemoryConfig`
- Comprehensive logging with `self.logger`
- Reuse existing `MemoryNamespace` from episodic module — do not duplicate
- Use `asyncio.gather()` for parallel retrieval from subsystems

### Known Risks / Gotchas

- **Token counting accuracy**: Using chars/4 approximation. If precise counting is needed later, swap in `tiktoken`. Mitigation: keep 10% headroom in budget.
- **Fire-and-forget tasks**: `asyncio.create_task()` for post-response recording could silently fail. Mitigation: wrap in try/except with logger.error.
- **Mixin MRO**: `LongTermMemoryMixin` must appear before `AbstractBot` in class definition. Document clearly.
- **Skill auto-extraction cost**: Requires an LLM call per successful complex interaction. Default off (`skill_auto_extract = False`).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2.0` | Already in project — MemoryContext/MemoryConfig models |
| `faiss-cpu` | `>=1.7` | Already in project — episodic backend |
| `redis` | `>=5.0` | Already in project — optional caching |

No new external dependencies required.

---

## 7. Open Questions

- [ ] **Reflection LLM**: Should the unified manager use same LLM as agent or a dedicated lightweight model? Recommendation: configurable, default to agent's LLM. — *Owner: Jesus Lara*: default to gemini-3.1-flash-lite
- [ ] **Cross-agent skill sharing**: Should `UnifiedMemoryManager` support a shared skill namespace across agents in the same org? Recommendation: yes, via `org_id/shared` scope. — *Owner: Jesus Lara*
- [ ] **Memory cleanup policy**: TTL-based pruning for episodic (90 days default), never auto-delete skills. Need confirmation. — *Owner: Jesus Lara*

---

## 8. Worktree Strategy

- **Isolation unit**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Modules have linear dependencies (models → context → manager → mixin → integration). No parallelizable tasks.
- **Cross-feature dependencies**: Requires FEAT-045 (EpisodicMemoryStore) to be merged first — already on `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-22 | Jesus Lara | Initial draft from brainstorm |
