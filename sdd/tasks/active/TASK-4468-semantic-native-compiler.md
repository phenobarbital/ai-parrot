# TASK-4468: Native single-table compiler and async compile entry (M5a)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4467, TASK-4475
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M5; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Create sole NativeCompiler and engines.compile; no engine field, dispatch, plugin protocol or parity oracle. Compile via asyncio.to_thread; cache hits skip compilation only.
- Compile single-table aggregates, dimensions including dimensions-only DISTINCT, grains, typed WHERE/HAVING filter trees, ordering and pagination. Enforce the closed subset and no database access.
- Fix contains wildcard escaping for backslash/percent/underscore using dialect-valid AST generation; do not embed user SQL. Close issue:46e8f6219bf5 only after literal wildcard regression evidence.
- Advanced joins/filtered measures/derived metrics extend this compiler in a dependent task; this task must reject unsupported forms explicitly. Add three-dialect single-table snapshots and DuckDB row oracle.
- Use an unambiguous canonical JSON tuple for CompiledQuery.cache_key (model digest, policy digest, canonical query, dialect, compiler version, connection id), so CompileCache.put can index model_digest without another parameter.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_native_compiler.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from ..cache import CompileCache
from ..errors import SemanticValidationError
from ..loader import LoadedModel
from ..models import SemanticQuery, CompiledQuery
from ..models import SemanticQuery, CompiledQuery, Grain
from .native import NativeCompiler
from __future__ import annotations
from pathlib import Path
from sqlglot import exp
import asyncio
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

No existing project symbol is extended; consume only dependency-created satellite contracts and the installed libraries below.

### Dependency Contracts and Parallelism Evidence

- TASK-4467: consumes packages/ai-parrot-semantic/src/parrot/semantic/loader.py (Clean-room model loader, graph scoping and fixtures (M4b))
- TASK-4475: consumes packages/ai-parrot-semantic/src/parrot/semantic/execution.py, packages/ai-parrot-semantic/src/parrot/semantic/cache.py (Execution bridge and pre-governance compile cache (M9a))

### Does NOT Exist

- `parrot.semantic` on dev — the package and symbols are created by this graph, never imported from the salvage branch environment.
- A semantic engine selector, sidemantic adapter or sidemantic parity oracle — native SQL generation is the only path.
- `PermissionContext.session_id` or `.agent_id` — the satellite identity contract carries trusted scope; request_id is not a session id.
- Automatic semantic authorization in `DatasetManager.add_dataframe()` — retained snapshots require the guarded host-sink contract.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_native_compiler.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

- Keep the scope and signatures fixed by spec rev 0.4. Complete the bounded blueprint gaps, not a broad refactor. Preserve the clean-room rule: do not open sidemantic source/API glue.
- Use async I/O, Pydantic v2, strict types and Google-style docstrings. CPU SQL passes run off the event loop. Use logging, not print; black/ruff are the format/lint gates.
- Run in the feature worktree with the existing venv activated; never repair the shared environment. Write test logs to `artifacts/logs/`.
- The full-file snippets below are starting points. Recheck dependency-created MODIFY anchors after their tasks land; they cannot be falsely reported verified on dev today.

## Implementation Blueprint

### Steps (in order)

1. Verify existing anchors and dependency contracts — because stale signatures invalidate a mechanical implementation.
2. Implement the listed targets in their blueprint order — because each target has one explicit owner and the graph orders shared writers.
3. Complete all scope-specific validation branches and regression scenarios — because success-path-only tests cannot establish the required fail-closed behavior.
4. Run this task's validation commands and focused lint — because only evidence from its declared files closes this task.

### `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py` (CREATE)

```python
"""Single native compiler entry point; caches contain pre-governance output only."""
from __future__ import annotations
import asyncio
from ..cache import CompileCache
from ..loader import LoadedModel
from ..models import SemanticQuery, CompiledQuery
from .native import NativeCompiler

async def compile(query: SemanticQuery, model: LoadedModel, dialect: str, *,
                  cache: CompileCache | None = None) -> CompiledQuery:
    """Compile under to_thread, or return immutable pre-governance cache output."""
    # FILL IN: canonical versioned key, cache lookup/put and await asyncio.to_thread;
    # model digest invalidation must work and no subject data may enter the cache.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py` (CREATE)

```python
"""Sole native SQL AST compiler; no warehouse connection or engine dispatch."""
from __future__ import annotations
from sqlglot import exp
from ..loader import LoadedModel
from ..models import SemanticQuery, CompiledQuery, Grain
from ..errors import SemanticValidationError
NATIVE_AGGREGATIONS = ("sum", "count", "count_distinct", "avg", "min", "max")

class NativeCompiler:
    """Compile the closed semantic grammar to deterministic dialect SQL."""
    def __init__(self, model: LoadedModel) -> None:
        self.model = model
    def compile(self, query: SemanticQuery, dialect: str) -> CompiledQuery:
        """Build SELECT with typed filters, physical provenance and deterministic keys."""
        # FILL IN: single-table subset, dimensions-only DISTINCT, WHERE/HAVING,
        # order/limit/offset and LIKE escaping; reject advanced forms until extension.
        ...
    def _grain_expr(self, column: exp.Column, grain: Grain) -> exp.Expression:
        """Return a DATE_TRUNC expression for the requested grain."""
        return exp.DateTrunc(this=column, unit=exp.Var(this=grain.upper()))
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_native_compiler.py` (CREATE)

```python
"""Regression contract: Native single-table compiler and async compile entry (M5a)."""
from pathlib import Path
import pytest


def test_single_table_dialect_sql_and_rows(tmp_path: Path) -> None:
    """Verify single table dialect sql and rows."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_literal_like_wildcards(tmp_path: Path) -> None:
    """Verify literal like wildcards."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_cache_key_and_no_database_at_compile(tmp_path: Path) -> None:
    """Verify cache key and no database at compile."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_native_compiler.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Create sole NativeCompiler and engines.compile; no engine field, dispatch, plugin protocol or parity oracle. Compile via asyncio.to_thread; cache hits skip compilation only.
- [ ] Compile single-table aggregates, dimensions including dimensions-only DISTINCT, grains, typed WHERE/HAVING filter trees, ordering and pagination. Enforce the closed subset and no database access.
- [ ] Fix contains wildcard escaping for backslash/percent/underscore using dialect-valid AST generation; do not embed user SQL. Close issue:46e8f6219bf5 only after literal wildcard regression evidence.
- [ ] Advanced joins/filtered measures/derived metrics extend this compiler in a dependent task; this task must reject unsupported forms explicitly. Add three-dialect single-table snapshots and DuckDB row oracle.
- [ ] Use an unambiguous canonical JSON tuple for CompiledQuery.cache_key (model digest, policy digest, canonical query, dialect, compiler version, connection id), so CompileCache.put can index model_digest without another parameter.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_native_compiler.py -q`

## Test Specification

- `test_single_table_dialect_sql_and_rows`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_literal_like_wildcards`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_cache_key_and_no_database_at_compile`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4468` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Populated only by the authorized completion workflow with implementation/validation evidence. Task planning is not completion.
