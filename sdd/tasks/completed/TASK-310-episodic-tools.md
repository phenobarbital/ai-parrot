# TASK-310 — Agent-Usable Episodic Memory Tools

**Feature**: FEAT-045 (Episodic Memory Store v2)
**Spec**: `sdd/specs/episodicmemorystore.spec.md`
**Status**: pending
**Priority**: medium
**Effort**: M
**Depends on**: TASK-304, TASK-309
**Parallel**: false
**Parallelism notes**: Imports EpisodicMemoryStore from TASK-309 and models from TASK-304. Exposes store operations as agent-callable tools.

---

## Objective

Create agent-usable tools that allow LLM agents to explicitly search, record, and retrieve warnings from episodic memory during their reasoning loop.

## Files to Create/Modify

- `parrot/memory/episodic/tools.py` — new file

## Implementation Details

### EpisodicMemoryToolkit (AbstractToolkit)

Inherit from `AbstractToolkit` so all public async methods become agent-callable tools.

```python
class EpisodicMemoryToolkit(AbstractToolkit):
    def __init__(self, store: EpisodicMemoryStore, namespace: MemoryNamespace) -> None:
        self._store = store
        self._namespace = namespace
```

### Tool 1: search_episodic_memory

```python
async def search_episodic_memory(
    self,
    query: str,
    top_k: int = 5,
    failures_only: bool = False,
) -> str:
    """Search past agent experiences by semantic similarity.

    Args:
        query: What to search for in past experiences.
        top_k: Maximum number of results to return.
        failures_only: If True, only return past failures and mistakes.

    Returns:
        Formatted list of relevant past experiences with lessons learned.
    """
```

Implementation:
- Call `store.recall_similar(query, namespace, top_k, include_failures_only=failures_only)`.
- Format results as readable text with situation, action, outcome, and lesson.

### Tool 2: record_lesson

```python
async def record_lesson(
    self,
    situation: str,
    lesson: str,
    category: str = "decision",
    importance: int = 5,
) -> str:
    """Explicitly record a lesson learned for future reference.

    Args:
        situation: What was happening when the lesson was learned.
        lesson: The concise lesson or insight to remember.
        category: Type of lesson (decision, user_preference, workflow_pattern).
        importance: How important this lesson is (1-10, default 5).

    Returns:
        Confirmation that the lesson was recorded.
    """
```

Implementation:
- Call `store.record_episode()` with outcome=SUCCESS, generate_reflection=False (lesson is already the reflection).
- Set lesson_learned=lesson, category from param.

### Tool 3: get_warnings

```python
async def get_warnings(
    self,
    context: str = "",
) -> str:
    """Get warnings about past mistakes relevant to the current task.

    Args:
        context: Description of what you're about to do (for relevance matching).

    Returns:
        Formatted warnings about past failures and successful approaches.
    """
```

Implementation:
- Call `store.get_failure_warnings(namespace, context)`.
- Return formatted text.

## Acceptance Criteria

- [ ] `search_episodic_memory` returns formatted past experiences.
- [ ] `record_lesson` stores a new episode with the lesson as reflection.
- [ ] `get_warnings` returns formatted failure warnings relevant to context.
- [ ] All tools have clear docstrings (these become LLM tool descriptions).
- [ ] Tools follow AbstractToolkit pattern (auto-registered via ToolManager).
- [ ] Error handling: tools return error messages rather than raising exceptions.
