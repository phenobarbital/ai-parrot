# TASK-506: AnswerMemory Bridge (save_interaction / recall_interaction)

**Feature**: extending-workingmemorytoolkit
**Spec**: `sdd/specs/extending-workingmemorytoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-503, TASK-504, TASK-505
**Assigned-to**: unassigned

---

## Context

This task adds the AnswerMemory bridge to `WorkingMemoryToolkit`, enabling
the LLM to save and recover Q&A interactions by `turn_id` or by fuzzy
question match. When combined with the generic entry system, recalled
interactions can be imported into the working memory catalog for further
processing.

Implements **Module 4** from the spec.

---

## Scope

- Add optional `answer_memory: Optional[AnswerMemory] = None` parameter to
  `WorkingMemoryToolkit.__init__()`. Store as `self._answer_memory`.

- Add `save_interaction()` async tool method:
  - Accepts `turn_id`, `question`, `answer`.
  - Delegates to `self._answer_memory.store_interaction(turn_id, question, answer)`.
  - Returns `{"status": "saved", "turn_id": turn_id}` on success.
  - Returns `{"status": "error", "error": "No AnswerMemory configured"}` when
    `self._answer_memory is None`.

- Add `recall_interaction()` async tool method:
  - Accepts `turn_id` (optional), `query` (optional), `import_as` (optional).
  - **By turn_id**: exact match via `self._answer_memory.get(turn_id)`.
  - **By query**: case-insensitive substring match across all stored questions
    in `self._answer_memory._interactions[agent_id]`. Returns the most recently
    stored match (iterate in reverse insertion order).
  - At least one of `turn_id` or `query` must be provided; error otherwise.
  - If `import_as` is provided, store the retrieved `{question, answer}` dict
    into `self._catalog.put_generic(import_as, interaction, entry_type=EntryType.JSON)`.
  - Returns `{"status": "recalled", "turn_id": ..., "interaction": {...}}` on success.
    Add `"imported_as": import_as` when imported.
  - Returns appropriate error when not found or no memory configured.

**NOT in scope**: BasicAgent auto-injection (TASK-507), package exports (TASK-508).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` | MODIFY | Add `answer_memory` param, `save_interaction()`, `recall_interaction()` |

---

## Implementation Notes

### Pattern to Follow

```python
from parrot.memory import AnswerMemory  # TYPE_CHECKING import recommended

@tool_schema(SaveInteractionInput)
async def save_interaction(
    self, turn_id: str, question: str, answer: str,
) -> dict:
    if self._answer_memory is None:
        return {"status": "error", "error": "No AnswerMemory configured"}
    await self._answer_memory.store_interaction(turn_id, question, answer)
    return {"status": "saved", "turn_id": turn_id}
```

### Fuzzy Search Implementation

```python
# For query-based recall, iterate AnswerMemory internals:
async with self._answer_memory._lock:
    agent_turns = self._answer_memory._interactions.get(
        self._answer_memory.agent_id, {}
    )
    query_lower = query.lower()
    # Reverse iteration for most-recent-first
    for tid in reversed(list(agent_turns.keys())):
        interaction = agent_turns[tid]
        if query_lower in interaction["question"].lower():
            return tid, interaction
```

### Key Constraints

- Import `AnswerMemory` under `TYPE_CHECKING` to avoid circular imports
  and keep it an optional dependency at runtime.
- The fuzzy search accesses `_interactions` (private attribute) — this is
  acceptable since both classes live in the same framework. Add a comment
  noting this coupling.
- `recall_interaction()` must validate that at least one of `turn_id` or
  `query` is provided.

### References in Codebase

- `packages/ai-parrot/src/parrot/memory/agent.py` — `AnswerMemory` class
- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` — toolkit

---

## Acceptance Criteria

- [ ] `WorkingMemoryToolkit(answer_memory=am)` stores the reference
- [ ] `save_interaction(turn_id, question, answer)` persists to AnswerMemory
- [ ] `save_interaction()` returns error when `_answer_memory is None`
- [ ] `recall_interaction(turn_id="t1")` returns stored Q&A
- [ ] `recall_interaction(query="market")` finds by question substring
- [ ] `recall_interaction(query="market")` returns most recent match
- [ ] `recall_interaction()` with neither `turn_id` nor `query` returns error
- [ ] `recall_interaction(turn_id="unknown")` returns not-found error
- [ ] `recall_interaction(turn_id="t1", import_as="prev")` imports into catalog
- [ ] Imported entry is a `GenericEntry` with `entry_type=EntryType.JSON`
- [ ] `recall_interaction()` returns error when `_answer_memory is None`
- [ ] All existing tests pass

---

## Test Specification

```python
import pytest
from parrot.memory import AnswerMemory
from parrot.tools.working_memory import WorkingMemoryToolkit
from parrot.tools.working_memory.internals import GenericEntry
from parrot.tools.working_memory.models import EntryType


@pytest.fixture
def answer_memory():
    return AnswerMemory(agent_id="test-agent")


@pytest.fixture
def toolkit_with_memory(answer_memory):
    return WorkingMemoryToolkit(answer_memory=answer_memory)


@pytest.fixture
def toolkit_no_memory():
    return WorkingMemoryToolkit()


class TestSaveInteraction:
    async def test_save(self, toolkit_with_memory, answer_memory):
        result = await toolkit_with_memory.save_interaction(
            turn_id="t1", question="What is X?", answer="X is Y."
        )
        assert result["status"] == "saved"
        stored = await answer_memory.get("t1")
        assert stored["question"] == "What is X?"

    async def test_save_no_memory(self, toolkit_no_memory):
        result = await toolkit_no_memory.save_interaction(
            turn_id="t1", question="Q", answer="A"
        )
        assert result["status"] == "error"


class TestRecallInteraction:
    async def test_recall_by_turn_id(self, toolkit_with_memory, answer_memory):
        await answer_memory.store_interaction("t1", "What is X?", "X is Y.")
        result = await toolkit_with_memory.recall_interaction(turn_id="t1")
        assert result["status"] == "recalled"
        assert result["interaction"]["question"] == "What is X?"

    async def test_recall_by_query(self, toolkit_with_memory, answer_memory):
        await answer_memory.store_interaction("t1", "Market analysis Q1", "...")
        await answer_memory.store_interaction("t2", "Weather report", "...")
        result = await toolkit_with_memory.recall_interaction(query="market")
        assert result["turn_id"] == "t1"

    async def test_recall_by_query_most_recent(self, toolkit_with_memory, answer_memory):
        await answer_memory.store_interaction("t1", "Market Q1", "old")
        await answer_memory.store_interaction("t2", "Market Q2", "new")
        result = await toolkit_with_memory.recall_interaction(query="market")
        assert result["turn_id"] == "t2"

    async def test_recall_not_found(self, toolkit_with_memory):
        result = await toolkit_with_memory.recall_interaction(turn_id="missing")
        assert result["status"] == "error"

    async def test_recall_requires_turn_or_query(self, toolkit_with_memory):
        result = await toolkit_with_memory.recall_interaction()
        assert result["status"] == "error"

    async def test_recall_and_import(self, toolkit_with_memory, answer_memory):
        await answer_memory.store_interaction("t1", "Q?", "A!")
        result = await toolkit_with_memory.recall_interaction(
            turn_id="t1", import_as="prev"
        )
        assert result.get("imported_as") == "prev"
        entry = toolkit_with_memory._catalog.get("prev")
        assert isinstance(entry, GenericEntry)
        assert entry.entry_type == EntryType.JSON

    async def test_recall_no_memory(self, toolkit_no_memory):
        result = await toolkit_no_memory.recall_interaction(turn_id="t1")
        assert result["status"] == "error"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/extending-workingmemorytoolkit.spec.md` for full context
2. **Check dependencies** — TASK-503, TASK-504, TASK-505 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-506-answer-memory-bridge.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-02
**Notes**: Implemented as specified. All 115 tests pass.

**Deviations from spec**: none
