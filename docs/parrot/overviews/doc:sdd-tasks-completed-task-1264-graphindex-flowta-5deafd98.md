---
type: Wiki Overview
title: 'TASK-1264: Flowtask Integration + pyproject.toml Extra'
id: doc:sdd-tasks-completed-task-1264-graphindex-flowtask-pyproject-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This task provides two integration pieces: (1) a Flowtask component wrapper
  that allows `GraphIndexBuilder` to be invoked as a Flowtask pipeline step, and (2)
  a new `[graphindex]` extra in `pyproject.toml` that bundles all GraphIndex-specific
  dependencies for opt-in installation.'
relates_to:
- concept: mod:parrot.knowledge.graphindex
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
---

# TASK-1264: Flowtask Integration + pyproject.toml Extra

**Feature**: FEAT-187 — GraphIndex — Structured Knowledge Graph Indexing
**Spec**: `sdd/specs/graphindex.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1262
**Assigned-to**: unassigned

---

## Context

This task provides two integration pieces: (1) a Flowtask component wrapper that allows `GraphIndexBuilder` to be invoked as a Flowtask pipeline step, and (2) a new `[graphindex]` extra in `pyproject.toml` that bundles all GraphIndex-specific dependencies for opt-in installation. This follows the existing `FlowtaskToolkit` pattern for dynamic component loading.

Implements: Spec §6 Integration (Flowtask), §7 Dependencies.

---

## Scope

- Create Flowtask component wrapper that calls `GraphIndexBuilder.build()`
- Follow the existing `FlowtaskToolkit` pattern for dynamic component loading
- Add new `[graphindex]` extra to `packages/ai-parrot/pyproject.toml` with:
  - `rustworkx>=0.15`
  - `tree-sitter>=0.23`
  - `tree-sitter-languages>=1.10`
  - `pathspec>=0.12`
- Note: `faiss-cpu` is already in core dependencies — do NOT add it again
- Write unit tests for the Flowtask component

**NOT in scope**: toolkit methods, analytics, persistence, builder internals

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/graphindex/flowtask.py` | CREATE | Flowtask component wrapper calling GraphIndexBuilder.build() |
| `packages/ai-parrot/pyproject.toml` | MODIFY | Add `[graphindex]` optional dependency extra |
| `packages/ai-parrot-tools/tests/graphindex/test_flowtask.py` | CREATE | Unit tests for Flowtask component |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Existing FlowtaskToolkit pattern:
# packages/ai-parrot-tools/src/parrot_tools/flowtask/tool.py
# FlowtaskToolkit loads components dynamically

from parrot.knowledge.graphindex.builder import GraphIndexBuilder
from parrot.knowledge.graphindex.schema import SourceConfig, BuildResult
from parrot.knowledge.ontology.schema import TenantContext
```

### Existing Pattern to Follow
```python
# Flowtask Component pattern (EXTERNAL package):
# Components loaded via flowtask.components.<Name>
# Pattern: async with component as comp: result = await comp.run()
#
# The Component base class is in the external flowtask package, NOT in ai-parrot.
# ai-parrot provides toolkit wrappers that bridge to flowtask components.
```

### Current Dependencies (verify before modifying)
```toml
# faiss-cpu is ALREADY in core dependencies — do not duplicate
# Check packages/ai-parrot/pyproject.toml for existing optional extras pattern
```

### Does NOT Exist
- ~~`flowtask.Component` in ai-parrot~~ — the `Component` base class is in the external `flowtask` package
- ~~`[graphindex]` extra in pyproject.toml~~ — this task creates it
- ~~`rustworkx` in current dependencies~~ — this task adds it via the new extra
- ~~`tree-sitter` in current dependencies~~ — this task adds it via the new extra

---

## Implementation Notes

### Pattern to Follow
```python
import logging
from typing import Any, Optional

class GraphIndexComponent:
    """Flowtask component wrapper for GraphIndex pipeline.

    Bridges the Flowtask execution model to GraphIndexBuilder,
    allowing knowledge graph indexing to run as a pipeline step.
    """

    def __init__(self, config: dict[str, Any]):
        """Initialize with Flowtask component configuration.

        Args:
            config: Component configuration dict from Flowtask pipeline definition.
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._builder: Optional[GraphIndexBuilder] = None

    async def __aenter__(self):
        """Initialize the GraphIndexBuilder on component entry."""
        # Parse config into SourceConfig, TenantContext, etc.
        # Create GraphIndexBuilder instance
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup on component exit."""
        ...

    async def run(self) -> dict:
        """Execute the GraphIndex build pipeline.

        Returns:
            Dict with build results (node count, edge count, report path, etc.)
        """
        result = await self._builder.build(self._sources, self._ctx)
        return result.model_dump()
```

### pyproject.toml Extra Pattern
```toml
[project.optional-dependencies]
graphindex = [
    "rustworkx>=0.15",
    "tree-sitter>=0.23",
    "tree-sitter-languages>=1.10",
    "pathspec>=0.12",
]
```

### Key Constraints
- Async-first, type-hinted, Google-style docstrings
- Flowtask component must follow the `async with component as comp: result = await comp.run()` pattern
- The `[graphindex]` extra must NOT include `faiss-cpu` (already in core)
- Component config parsing must be robust to missing/optional fields
- Component must log progress at INFO level for pipeline observability

---

## Acceptance Criteria

- [ ] Flowtask component wrapper created following existing pattern
- [ ] Component works with `async with` context manager pattern
- [ ] `run()` delegates to `GraphIndexBuilder.build()` correctly
- [ ] `[graphindex]` extra added to `packages/ai-parrot/pyproject.toml`
- [ ] Extra includes: rustworkx>=0.15, tree-sitter>=0.23, tree-sitter-languages>=1.10, pathspec>=0.12
- [ ] Extra does NOT include faiss-cpu (already in core)
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/graphindex/test_flowtask.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

class TestGraphIndexComponent:
    async def test_context_manager_protocol(self):
        """Component works with async with pattern."""
        # Setup: create component with valid config
        # Assert: __aenter__ returns self, __aexit__ cleans up

    async def test_run_delegates_to_builder(self):
        """run() calls GraphIndexBuilder.build() with correct args."""
        # Setup: mock GraphIndexBuilder
        # Assert: build() called with parsed SourceConfig and TenantContext

    async def test_run_returns_serialized_result(self):
        """run() returns dict from BuildResult.model_dump()."""
        # Setup: mock builder returning BuildResult
        # Assert: result is a dict with expected keys

    async def test_invalid_config_raises(self):
        """Missing required config fields raise descriptive errors."""
        # Setup: incomplete config dict
        # Assert: appropriate exception during __aenter__

class TestPyprojectExtra:
    def test_graphindex_extra_exists(self):
        """pyproject.toml has [graphindex] optional dependency group."""
        # Read pyproject.toml, parse, check optional-dependencies.graphindex exists

    def test_graphindex_extra_has_required_deps(self):
        """[graphindex] extra includes rustworkx, tree-sitter, tree-sitter-languages, pathspec."""
        # Assert: all four packages listed

    def test_graphindex_extra_no_faiss(self):
        """[graphindex] extra must NOT include faiss-cpu (already in core)."""
        # Assert: faiss-cpu not in graphindex extra
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/graphindex.spec.md` for full context
2. **Check dependencies** — TASK-1262 (builder) must be done
3. **Verify the Codebase Contract** — examine existing FlowtaskToolkit in `packages/ai-parrot-tools/src/parrot_tools/flowtask/tool.py` and existing optional extras in `packages/ai-parrot/pyproject.toml`
4. **Update status** in `sdd/tasks/index/graphindex.json` -> `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1264-graphindex-flowtask-pyproject.md`
8. **Update index** -> `"done"`

---

## Completion Note

*(Agent fills this in when done)*
