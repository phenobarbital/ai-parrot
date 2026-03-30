# TASK-490: CapabilityRegistry

**Feature**: intent-router
**Spec**: `sdd/specs/intent-router.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-489
**Assigned-to**: unassigned

---

## Context

> Implements Module 2 from the spec. The CapabilityRegistry is a semantic index of agent
> resources. It stores CapabilityEntry objects, builds an embedding-based index, and
> performs cosine similarity search with `not_for` exclusion support. Used by
> IntentRouterMixin for candidate retrieval before LLM classification.

---

## Scope

- Implement `CapabilityRegistry` class in `parrot/registry/capabilities/registry.py`.
- Methods:
  - `register(entry: CapabilityEntry)` — manual registration
  - `register_from_datasource(source: DataSource, name: str)` — auto-register from DataSource metadata
  - `register_from_tool(tool: AbstractTool)` — auto-register from tool name/description
  - `register_from_yaml(path: str)` — load manual entries from YAML (graph nodes, PageIndex trees)
  - `async build_index(embedding_fn: Callable)` — vectorize all entries' description + canonical_questions
  - `async search(query: str, top_k: int = 5, resource_types: list[ResourceType] | None = None) -> list[RouterCandidate]` — cosine similarity search with not_for penalty
- Index invalidation: `_index_built = False` on new registration, lazy rebuild on next search.
- Cosine similarity using numpy (no FAISS).
- Write unit tests.

**NOT in scope**: IntentRouterMixin, AbstractBot integration, strategy execution.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/registry/capabilities/registry.py` | CREATE | CapabilityRegistry class |
| `parrot/registry/capabilities/__init__.py` | MODIFY | Export CapabilityRegistry |
| `tests/registry/test_capability_registry.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
class CapabilityRegistry:
    def __init__(self):
        self._entries: dict[str, CapabilityEntry] = {}
        self._embeddings: dict[str, np.ndarray] = {}
        self._embedding_fn: Callable | None = None
        self._index_built: bool = False

    async def build_index(self, embedding_fn: Callable) -> None:
        self._embedding_fn = embedding_fn
        for entry_id, entry in self._entries.items():
            text = f"{entry.description} {' '.join(entry.canonical_questions)}"
            self._embeddings[entry_id] = await embedding_fn(text)
        self._index_built = True

    async def search(self, query: str, top_k: int = 5, ...) -> list[RouterCandidate]:
        if not self._index_built:
            await self.build_index(self._embedding_fn)
        query_vec = await self._embedding_fn(query)
        # Cosine similarity against all entries
        # Apply not_for penalty: if query matches not_for keywords, reduce score
        # Filter by resource_types if provided
        # Return top-K sorted by score
```

### Key Constraints
- `embedding_fn` is an async callable: `async (text: str) -> np.ndarray`.
- `not_for` matching: if any `not_for` keyword appears in the query (case-insensitive), reduce the entry's score by a penalty factor (e.g. 0.5).
- YAML format for manual entries should be a list of CapabilityEntry-shaped dicts.
- `register_from_datasource` extracts: id from name, description from DataSource.description or auto-generated, fields_preview from column names.
- `register_from_tool` extracts: id from tool.name, description from tool.description.

### References in Codebase
- `parrot/tools/dataset_manager/tool.py:88` — `DatasetEntry` for DataSource metadata
- `parrot/tools/base.py` — `AbstractTool` for tool name/description
- `parrot/registry/__init__.py` — existing registry package

---

## Acceptance Criteria

- [ ] Manual, DataSource, Tool, and YAML registration all work
- [ ] `build_index()` vectorizes entries using provided `embedding_fn`
- [ ] `search()` returns ranked `RouterCandidate` list by cosine similarity
- [ ] `not_for` exclusions reduce scores for matching entries
- [ ] Index auto-rebuilds when new entries registered after build
- [ ] `resource_types` filter works
- [ ] All tests pass: `pytest tests/registry/test_capability_registry.py -v`

---

## Test Specification

```python
# tests/registry/test_capability_registry.py
import pytest
import numpy as np
from parrot.registry.capabilities import CapabilityRegistry, CapabilityEntry, ResourceType

async def mock_embedding_fn(text: str) -> np.ndarray:
    """Deterministic mock embedding based on text hash."""
    np.random.seed(hash(text) % 2**32)
    return np.random.randn(64).astype(np.float32)

class TestCapabilityRegistry:
    async def test_register_and_search(self):
        reg = CapabilityRegistry()
        reg.register(CapabilityEntry(
            id="employees", resource_type=ResourceType.DATASET,
            description="Active employee records",
            canonical_questions=["who are active employees?"],
        ))
        await reg.build_index(mock_embedding_fn)
        results = await reg.search("active employees", top_k=5)
        assert len(results) >= 1
        assert results[0].entry.id == "employees"

    async def test_not_for_penalty(self):
        reg = CapabilityRegistry()
        reg.register(CapabilityEntry(
            id="warehouse", resource_type=ResourceType.DATASET,
            description="Warehouse ops with employee_id column",
            not_for=["employee data", "HR"],
        ))
        reg.register(CapabilityEntry(
            id="employees", resource_type=ResourceType.DATASET,
            description="Employee records",
        ))
        await reg.build_index(mock_embedding_fn)
        results = await reg.search("employee data", top_k=5)
        # "warehouse" should be penalized for "employee data" in not_for

    async def test_resource_type_filter(self):
        reg = CapabilityRegistry()
        reg.register(CapabilityEntry(id="ds1", resource_type=ResourceType.DATASET, description="dataset"))
        reg.register(CapabilityEntry(id="t1", resource_type=ResourceType.TOOL, description="tool"))
        await reg.build_index(mock_embedding_fn)
        results = await reg.search("test", resource_types=[ResourceType.DATASET])
        assert all(r.entry.resource_type == ResourceType.DATASET for r in results)

    async def test_index_invalidation(self):
        reg = CapabilityRegistry()
        reg.register(CapabilityEntry(id="a", resource_type=ResourceType.DATASET, description="first"))
        await reg.build_index(mock_embedding_fn)
        assert reg._index_built is True
        reg.register(CapabilityEntry(id="b", resource_type=ResourceType.DATASET, description="second"))
        assert reg._index_built is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-490-capability-registry.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
