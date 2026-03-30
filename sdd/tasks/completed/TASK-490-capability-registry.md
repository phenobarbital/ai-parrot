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

> Implements the semantic resource index that powers intent routing. The CapabilityRegistry holds all registered capabilities (datasets, tools, graph nodes, etc.) and enables embedding-based similarity search to discover which strategies are relevant for a given query.
> Implements spec Section 3 — Module 2 (CapabilityRegistry).

---

## Scope

- Create `parrot/registry/capabilities/registry.py` with the `CapabilityRegistry` class.
- Methods to implement:
  - `register(entry: CapabilityEntry) -> None` — add a capability entry to the registry, invalidate cached index.
  - `register_from_datasource(source: DataSource) -> None` — create a CapabilityEntry from a DataSource and register it.
  - `register_from_tool(tool: AbstractTool) -> None` — create a CapabilityEntry from an AbstractTool and register it.
  - `register_from_yaml(path: str) -> None` — load capabilities from a YAML file and register them.
  - `build_index(embedding_fn: Callable) -> None` — compute embeddings for all entries missing them, build the numpy matrix for cosine search.
  - `search(query: str, top_k: int = 5, resource_types: Optional[list[ResourceType]] = None) -> list[RouterCandidate]` — embed the query, cosine-similarity search, apply `not_for` penalty, return top-k candidates.
- Cosine similarity computed with numpy (no external vector DB dependency).
- `not_for` penalty: if query matches any `not_for` pattern, reduce score by a configurable factor (default 0.5).
- Index invalidation: setting `_index_dirty = True` on any new registration; `search()` auto-rebuilds if dirty.
- Update `parrot/registry/capabilities/__init__.py` to export `CapabilityRegistry`.

**NOT in scope**: IntentRouterMixin (TASK-491), auto-registration hooks in DatasetManager/ToolManager (TASK-493), AbstractBot modifications (TASK-492).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/registry/capabilities/registry.py` | CREATE | CapabilityRegistry class with all methods |
| `parrot/registry/capabilities/__init__.py` | MODIFY | Add CapabilityRegistry to exports |
| `tests/registry/test_capability_registry.py` | CREATE | Unit tests for registry operations |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/registry/capabilities/registry.py
import logging
from typing import Callable, Optional
from pathlib import Path

import numpy as np
import yaml

from parrot.registry.capabilities.models import (
    CapabilityEntry, ResourceType, RouterCandidate,
)


class CapabilityRegistry:
    """Semantic resource index for intent routing.

    Stores capability entries and provides embedding-based search
    to discover relevant strategies for a given user query.
    """

    def __init__(self, not_for_penalty: float = 0.5):
        self.logger = logging.getLogger(__name__)
        self._entries: list[CapabilityEntry] = []
        self._embedding_matrix: Optional[np.ndarray] = None
        self._index_dirty: bool = True
        self._embedding_fn: Optional[Callable] = None
        self._not_for_penalty: float = not_for_penalty

    def register(self, entry: CapabilityEntry) -> None:
        """Register a capability entry. Invalidates the search index."""
        self._entries.append(entry)
        self._index_dirty = True
        self.logger.debug("Registered capability: %s", entry.name)

    def register_from_datasource(self, source) -> None:
        """Create and register a CapabilityEntry from a DataSource."""
        entry = CapabilityEntry(
            name=source.name,
            description=getattr(source, "description", source.name),
            resource_type=ResourceType.DATASET,
            metadata=getattr(source, "routing_meta", {}),
            not_for=getattr(source, "routing_meta", {}).get("not_for", []),
        )
        self.register(entry)

    def register_from_tool(self, tool) -> None:
        """Create and register a CapabilityEntry from an AbstractTool."""
        entry = CapabilityEntry(
            name=tool.name,
            description=tool.description or tool.name,
            resource_type=ResourceType.TOOL,
            metadata=getattr(tool, "routing_meta", {}),
            not_for=getattr(tool, "routing_meta", {}).get("not_for", []),
        )
        self.register(entry)

    def register_from_yaml(self, path: str) -> None:
        """Load capability entries from a YAML file."""
        data = yaml.safe_load(Path(path).read_text())
        for item in data.get("capabilities", []):
            entry = CapabilityEntry(**item)
            self.register(entry)

    async def build_index(self, embedding_fn: Callable) -> None:
        """Compute embeddings and build the search matrix."""
        self._embedding_fn = embedding_fn
        descriptions = [e.description for e in self._entries]
        if not descriptions:
            self._embedding_matrix = np.empty((0, 0))
            self._index_dirty = False
            return
        embeddings = await embedding_fn(descriptions)
        for i, emb in enumerate(embeddings):
            self._entries[i].embedding = emb
        self._embedding_matrix = np.array(embeddings, dtype=np.float32)
        # L2 normalize rows for cosine similarity
        norms = np.linalg.norm(self._embedding_matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        self._embedding_matrix = self._embedding_matrix / norms
        self._index_dirty = False

    async def search(
        self,
        query: str,
        top_k: int = 5,
        resource_types: Optional[list[ResourceType]] = None,
    ) -> list[RouterCandidate]:
        """Embed query and return top-k matching capabilities."""
        if self._index_dirty and self._embedding_fn:
            await self.build_index(self._embedding_fn)
        if self._embedding_matrix is None or len(self._entries) == 0:
            return []
        # Embed query
        query_emb = (await self._embedding_fn([query]))[0]
        query_vec = np.array(query_emb, dtype=np.float32)
        query_norm = np.linalg.norm(query_vec)
        if query_norm > 0:
            query_vec = query_vec / query_norm
        # Cosine similarity
        scores = self._embedding_matrix @ query_vec
        # Apply not_for penalty
        for i, entry in enumerate(self._entries):
            if entry.not_for:
                query_lower = query.lower()
                if any(pattern.lower() in query_lower for pattern in entry.not_for):
                    scores[i] *= self._not_for_penalty
        # Filter by resource_types if specified
        candidates = []
        for i, entry in enumerate(self._entries):
            if resource_types and entry.resource_type not in resource_types:
                continue
            candidates.append(RouterCandidate(
                entry=entry,
                score=float(np.clip(scores[i], 0.0, 1.0)),
                resource_type=entry.resource_type,
            ))
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:top_k]
```

### Key Constraints
- Cosine similarity uses numpy only — no FAISS or other vector DB dependency.
- `build_index()` and `search()` are async because the embedding function is async.
- Index auto-rebuilds on `search()` if `_index_dirty` is True and an embedding function is available.
- `not_for` penalty is multiplicative: score *= penalty_factor (default 0.5).
- L2-normalize all vectors for correct cosine similarity via dot product.

### References in Codebase
- `parrot/tools/dataset_manager/sources/base.py` — `DataSource` class (register_from_datasource input)
- `parrot/tools/base.py` — `AbstractTool` class (register_from_tool input)
- `parrot/clients/abstract_client.py` — `embed()` method can serve as embedding_fn

---

## Acceptance Criteria

- [ ] `CapabilityRegistry` class exists in `parrot/registry/capabilities/registry.py`
- [ ] `register()` adds entries and sets `_index_dirty = True`
- [ ] `register_from_datasource()` creates valid CapabilityEntry from DataSource
- [ ] `register_from_tool()` creates valid CapabilityEntry from AbstractTool
- [ ] `register_from_yaml()` loads from YAML file
- [ ] `build_index()` computes embedding matrix with L2 normalization
- [ ] `search()` returns correctly ranked RouterCandidate list
- [ ] `not_for` penalty reduces scores for matching patterns
- [ ] Index auto-rebuilds when dirty
- [ ] `from parrot.registry.capabilities import CapabilityRegistry` works
- [ ] No linting errors: `ruff check parrot/registry/capabilities/`

---

## Test Specification

```python
# tests/registry/test_capability_registry.py
import pytest
import numpy as np
from unittest.mock import AsyncMock

from parrot.registry.capabilities.models import (
    CapabilityEntry, ResourceType, RouterCandidate,
)
from parrot.registry.capabilities.registry import CapabilityRegistry


@pytest.fixture
def registry():
    return CapabilityRegistry()


@pytest.fixture
def sample_entries():
    return [
        CapabilityEntry(
            name="sales_data",
            description="Monthly sales revenue dataset",
            resource_type=ResourceType.DATASET,
        ),
        CapabilityEntry(
            name="weather_tool",
            description="Get current weather for a city",
            resource_type=ResourceType.TOOL,
        ),
        CapabilityEntry(
            name="product_graph",
            description="Product relationship graph with categories",
            resource_type=ResourceType.GRAPH_NODE,
        ),
    ]


@pytest.fixture
def mock_embedding_fn():
    """Returns deterministic embeddings based on description length."""
    async def _embed(texts: list[str]) -> list[list[float]]:
        return [
            [float(len(t) % 10) / 10, float(len(t) % 7) / 7, float(len(t) % 3) / 3]
            for t in texts
        ]
    return _embed


class TestRegister:
    def test_register_adds_entry(self, registry, sample_entries):
        registry.register(sample_entries[0])
        assert len(registry._entries) == 1

    def test_register_invalidates_index(self, registry, sample_entries):
        registry._index_dirty = False
        registry.register(sample_entries[0])
        assert registry._index_dirty is True


class TestBuildIndex:
    @pytest.mark.asyncio
    async def test_builds_embedding_matrix(self, registry, sample_entries, mock_embedding_fn):
        for entry in sample_entries:
            registry.register(entry)
        await registry.build_index(mock_embedding_fn)
        assert registry._embedding_matrix is not None
        assert registry._embedding_matrix.shape[0] == 3
        assert registry._index_dirty is False

    @pytest.mark.asyncio
    async def test_empty_registry(self, registry, mock_embedding_fn):
        await registry.build_index(mock_embedding_fn)
        assert registry._index_dirty is False


class TestSearch:
    @pytest.mark.asyncio
    async def test_returns_candidates(self, registry, sample_entries, mock_embedding_fn):
        for entry in sample_entries:
            registry.register(entry)
        await registry.build_index(mock_embedding_fn)
        results = await registry.search("sales revenue", top_k=2)
        assert len(results) <= 2
        assert all(isinstance(r, RouterCandidate) for r in results)

    @pytest.mark.asyncio
    async def test_filter_by_resource_type(self, registry, sample_entries, mock_embedding_fn):
        for entry in sample_entries:
            registry.register(entry)
        await registry.build_index(mock_embedding_fn)
        results = await registry.search("data", resource_types=[ResourceType.DATASET])
        assert all(r.resource_type == ResourceType.DATASET for r in results)

    @pytest.mark.asyncio
    async def test_not_for_penalty(self, registry, mock_embedding_fn):
        entry = CapabilityEntry(
            name="internal_tool",
            description="Internal admin operations",
            resource_type=ResourceType.TOOL,
            not_for=["admin"],
        )
        registry.register(entry)
        await registry.build_index(mock_embedding_fn)
        results = await registry.search("admin operations")
        if results:
            assert results[0].score < 1.0  # Penalty applied

    @pytest.mark.asyncio
    async def test_auto_rebuilds_on_dirty(self, registry, sample_entries, mock_embedding_fn):
        for entry in sample_entries:
            registry.register(entry)
        await registry.build_index(mock_embedding_fn)
        # Add new entry, making index dirty
        registry.register(CapabilityEntry(
            name="new_entry",
            description="A brand new capability",
            resource_type=ResourceType.TOOL,
        ))
        assert registry._index_dirty is True
        results = await registry.search("new capability")
        assert registry._index_dirty is False  # Auto-rebuilt
```

---

## Agent Instructions

1. Read this task file completely before starting.
2. Read the spec at `sdd/specs/intent-router.spec.md` for full context on Module 2.
3. Verify TASK-489 is complete: `from parrot.registry.capabilities.models import CapabilityEntry, ResourceType, RouterCandidate` must work.
4. Implement the code changes described in **Scope** and **Files to Create / Modify**.
5. Follow the patterns in **Implementation Notes** exactly.
6. Run `ruff check` on all modified/created files.
7. Run the tests in **Test Specification** with `pytest`.
8. Do NOT implement anything outside the **Scope** section.
9. When done, fill in the **Completion Note** below and commit.

---

## Completion Note

*(Agent fills this in when done)*
