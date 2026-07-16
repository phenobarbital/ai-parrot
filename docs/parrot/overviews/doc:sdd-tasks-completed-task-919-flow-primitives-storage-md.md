---
type: Wiki Overview
title: 'TASK-919: Storage Migration — ExecutionMemory, PersistenceMixin, SynthesisMixin'
id: doc:sdd-tasks-completed-task-919-flow-primitives-storage-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Moves the storage subpackage (`ExecutionMemory`, `VectorStoreMixin`,
relates_to:
- concept: mod:parrot._imports
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

# TASK-919: Storage Migration — ExecutionMemory, PersistenceMixin, SynthesisMixin

**Feature**: FEAT-134 — Flow Primitives — Shared Core for AgentCrew & AgentsFlow
**Spec**: `sdd/specs/flow-primitives.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-913
**Assigned-to**: unassigned

---

## Context

Moves the storage subpackage (`ExecutionMemory`, `VectorStoreMixin`,
`PersistenceMixin`, `SynthesisMixin`) from `parrot.bots.flow.storage` into
`parrot.bots.flows.core.storage`. These mixins serve both engines.

`AgentResult` stays in `parrot.models.crew` (brainstorm D11). The moved
`ExecutionMemory` imports `AgentResult` from its original location.

Implements Spec §3 Module 7.

---

## Scope

- Create `packages/ai-parrot/src/parrot/bots/flows/core/storage/` with:
  - `__init__.py` — re-exports `ExecutionMemory`, `PersistenceMixin`,
    `SynthesisMixin`, `VectorStoreMixin`.
  - `memory.py` — `ExecutionMemory` (copy from existing, imports `AgentResult`
    from `parrot.models.crew`).
  - `mixin.py` — `VectorStoreMixin` (copy from existing).
  - `persistence.py` — `PersistenceMixin` (copy from existing).
  - `synthesis.py` — `SynthesisMixin` (copy from existing, references
    `CrewResult` for now — will be updated to `FlowResult` in Spec 2).
- Write basic import/smoke tests.

**NOT in scope**: Modifying the existing `parrot/bots/flow/storage/` —
re-exports pointing to the new location happen in TASK-920.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/__init__.py` | CREATE | Re-exports |
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/memory.py` | CREATE | ExecutionMemory |
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/mixin.py` | CREATE | VectorStoreMixin |
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/persistence.py` | CREATE | PersistenceMixin |
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/synthesis.py` | CREATE | SynthesisMixin |
| `packages/ai-parrot/tests/test_flow_primitives/test_storage.py` | CREATE | Import tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/bots/flow/storage/memory.py:4
from ....models.crew import AgentResult

# packages/ai-parrot/src/parrot/bots/flow/storage/mixin.py:4
from ....models.crew import AgentResult, VectorStoreProtocol

# packages/ai-parrot/src/parrot/bots/flow/storage/synthesis.py:7
from ....models.crew import CrewResult

# packages/ai-parrot/src/parrot/bots/flow/storage/persistence.py
# No parrot imports — only uses DocumentDb via lazy import
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flow/storage/memory.py:8-102
@dataclass
class ExecutionMemory(VectorStoreMixin):
    original_query: Optional[str] = None
    results: Dict[str, AgentResult] = field(default_factory=dict)
    execution_graph: Dict[str, List[str]] = field(default_factory=dict)
    execution_order: List[str] = field(default_factory=list)
    def __init__(self, original_query="", embedding_model=None, dimension=384, index_type="Flat"): ...
    def add_result(self, result: AgentResult, vectorize=True): ...
    def get_results_by_agent(self, agent_id: str) -> AgentResult: ...
    def get_reexecuted_results(self) -> List[AgentResult]: ...
    def get_context_for_agent(self, agent_id: str) -> Any: ...
    def clear(self, keep_query=False): ...
    def get_snapshot(self) -> Dict[str, Any]: ...

# packages/ai-parrot/src/parrot/bots/flow/storage/mixin.py:7-141
class VectorStoreMixin:
    def __init__(self, *, embedding_model=None, dimension=384, index_type="Flat", **kwargs): ...
    @property
    def embedding_model(self): ...
    def _chunk_result(self, result: AgentResult) -> List[str]: ...
    async def _vectorize_result_async(self, result: AgentResult): ...
    def search_similar(self, query: str, top_k=5) -> List[Tuple[str, AgentResult, float]]: ...
    def _clear_vectors(self): ...

# packages/ai-parrot/src/parrot/bots/flow/storage/persistence.py:8-47
class PersistenceMixin:
    async def _save_result(self, result, method, *, collection="crew_executions", **kwargs): ...

# packages/ai-parrot/src/parrot/bots/flow/storage/synthesis.py:21-108
class SynthesisMixin:
    async def _synthesize_results(self, crew_result: CrewResult, synthesis_prompt=None, *, llm=None, ...): ...
```

### Does NOT Exist
- ~~`parrot.bots.flows.core.storage`~~ — does not exist yet

---

## Implementation Notes

### Key Constraints
- `ExecutionMemory` and `VectorStoreMixin` import `AgentResult` from
  `parrot.models.crew` — this stays unchanged (D11 decision).
- `SynthesisMixin` references `CrewResult` — keep this import for now.
  In Spec 2, it will be updated to `FlowResult`.
- The relative import paths change because the modules move from
  `parrot/bots/flow/storage/` to `parrot/bots/flows/core/storage/`.
  Adjust `from ....models.crew` accordingly (count the dots carefully:
  `storage → core → flows → bots → parrot` = `from .....models.crew`).
- The `SYNTHESIS_PROMPT` constant must be included in the new `synthesis.py`.
- `lazy_import` in `mixin.py` imports from `parrot._imports` — verify path.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/flow/storage/` — source files to copy

---

## Acceptance Criteria

- [ ] All 4 storage modules exist in `packages/ai-parrot/src/parrot/bots/flows/core/storage/`
- [ ] `ExecutionMemory`, `PersistenceMixin`, `SynthesisMixin` importable from new location
- [ ] `ExecutionMemory` correctly imports `AgentResult` from `parrot.models.crew`
- [ ] `SynthesisMixin` correctly imports `CrewResult` from `parrot.models.crew`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_flow_primitives/test_storage.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_flow_primitives/test_storage.py
import pytest


class TestStorageImports:
    def test_import_execution_memory(self):
        from parrot.bots.flows.core.storage import ExecutionMemory
        assert ExecutionMemory is not None

    def test_import_persistence_mixin(self):
        from parrot.bots.flows.core.storage import PersistenceMixin
        assert PersistenceMixin is not None

    def test_import_synthesis_mixin(self):
        from parrot.bots.flows.core.storage import SynthesisMixin
        assert SynthesisMixin is not None

    def test_execution_memory_instantiation(self):
        from parrot.bots.flows.core.storage import ExecutionMemory
        mem = ExecutionMemory(original_query="test query")
        assert mem.original_query == "test query"
        assert mem.results == {}

    def test_execution_memory_clear(self):
        from parrot.bots.flows.core.storage import ExecutionMemory
        mem = ExecutionMemory(original_query="test")
        mem.clear()
        assert mem.original_query == ""
        mem2 = ExecutionMemory(original_query="test")
        mem2.clear(keep_query=True)
        assert mem2.original_query == "test"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 7
2. **Check dependencies** — TASK-913 must be completed
3. **Copy** each file from `packages/ai-parrot/src/parrot/bots/flow/storage/`
   into `packages/ai-parrot/src/parrot/bots/flows/core/storage/`
4. **Fix relative imports** — the nesting depth changes
5. **Verify** `from parrot._imports import lazy_import` works from the new location

---

## Completion Note

Completed 2026-04-29. Created `parrot/bots/flows/core/storage/` package with 5 files:
- `__init__.py`: re-exports ExecutionMemory, VectorStoreMixin, PersistenceMixin, SynthesisMixin.
- `memory.py`: ExecutionMemory dataclass (imports AgentResult from `parrot.models.crew` via `from .....models.crew`).
- `mixin.py`: VectorStoreMixin (FAISS-based; absolute import `from parrot._imports import lazy_import`).
- `persistence.py`: PersistenceMixin (DocumentDB persistence; 5-level relative import for DocumentDb).
- `synthesis.py`: SynthesisMixin (references CrewResult for now per D11; 5-level relative import).
All 19 unit tests pass.
