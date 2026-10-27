# TASK-4475: Execution bridge and pre-governance compile cache (M9a)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4464
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M9; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Implement ConnectionResolver.resolve using named environment overlay over get_default_credentials(driver); credentials never come from SemanticQuery/tool arguments.
- Executor.run unwraps QueryResult.rows/row_count/columns correctly; never treat source.query as a list. Preserve empty-result column information through a private metadata helper when building SemanticQueryResult.
- Implement bounded CompileCache with get/put/invalidate_model and a model-digest index; invalidation must actually remove entries. Cache only pre-governance objects and canonical versioned keys.
- Unit tests use source doubles here; stock DuckDB integration is validated after its dedicated repair. Cap rows and define truncated from actual overfetch evidence, not equality with LIMIT.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/execution.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/src/parrot/semantic/cache.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_execution.py` | CREATE | Focused regression evidence |
| `packages/ai-parrot-semantic/tests/test_cache.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from .errors import SemanticExecutionError
from .models import CompiledQuery
from .models import GovernedQuery
from __future__ import annotations
from collections import OrderedDict
from parrot.interfaces.database import get_default_credentials
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit
from pathlib import Path
from typing import Any, Mapping
import logging
import os
import pytest
import re
import threading
import time
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py:115
class DatabaseQueryToolkit(AbstractToolkit):
    # line 154
    def __init__(self, **kwargs: Any) -> None:
    # line 180
    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs: Any) -> Any:
    # line 202
    def get_source(self, driver: str) -> AbstractDatabaseSource:
```

```python
# packages/ai-parrot/src/parrot/tools/databasequery/base.py:148
class QueryResult(BaseModel):
```

```python
# packages/ai-parrot/src/parrot/interfaces/database.py:501
def get_default_credentials(driver: str) -> dict[str, Any]:
```

### Dependency Contracts and Parallelism Evidence

- TASK-4464: consumes packages/ai-parrot-semantic/src/parrot/semantic/errors.py, packages/ai-parrot-semantic/src/parrot/semantic/models.py (Query/result contracts and trusted identity model (M2))

- Consumer-specific evidence: GovernedQuery/CompiledQuery for source execution and immutable cache entries

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
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/execution.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/cache.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_execution.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_cache.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py#DatabaseQueryToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/databasequery/base.py#QueryResult",
    "sym:packages/ai-parrot/src/parrot/interfaces/database.py#get_default_credentials"
  ]
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

### `packages/ai-parrot-semantic/src/parrot/semantic/execution.py` (CREATE)

```python
"""Named-connection credential resolution and governed-SQL execution (spec §3 Module 9)."""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Mapping

from parrot.interfaces.database import get_default_credentials
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit

from .errors import SemanticExecutionError
from .models import GovernedQuery


class ConnectionResolver:
    PREFIX = "PARROT_SEMANTIC_CONN_"

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self.env = env if env is not None else os.environ

    def resolve(self, connection: str, driver: str) -> dict[str, Any]:
        """Defaults for `driver` overlaid with PARROT_SEMANTIC_CONN_<CONNECTION>_<KEY>; empty -> no_credentials."""
        # FILL IN: prefix = self.PREFIX + re.sub(r"[^A-Za-z0-9]", "_", connection).upper() + "_";
        #          creds = dict(get_default_credentials(driver)); overlay matching env keys (lower-cased suffix);
        #          if not creds: raise SemanticExecutionError("no_credentials")
        raise NotImplementedError


class Executor:
    def __init__(self, toolkit: DatabaseQueryToolkit, resolver: ConnectionResolver) -> None:
        self.toolkit = toolkit
        self.resolver = resolver
        self.logger = logging.getLogger(__name__)

    async def run(self, governed: GovernedQuery, *, connection: str) -> tuple[list[dict], int, bool, int]:
        """Returns (rows, row_count, truncated, duration_ms); DB errors -> SemanticExecutionError (no SQL in message)."""
        # FILL IN: source = self.toolkit.get_source(governed.driver) (unknown driver -> "no_source");
        #   creds = self.resolver.resolve(connection, governed.driver); t0 = time.perf_counter();
        #   result = await source.query(creds, governed.sql); except Exception as exc -> log exc type only,
        #   raise SemanticExecutionError("execution_failed") from exc; cap rows at governed.limit
        raise NotImplementedError
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/src/parrot/semantic/cache.py` (CREATE)

```python
"""LRU of pre-governance CompiledQuery objects only (AC8)."""
from __future__ import annotations

import threading
from collections import OrderedDict

from .models import CompiledQuery


class CompileCache:
    def __init__(self, max_entries: int = 512) -> None:
        self.max_entries = max_entries
        self._data: OrderedDict[str, CompiledQuery] = OrderedDict()
        self._lock = threading.Lock()   # compile runs under asyncio.to_thread

    def get(self, key: str) -> CompiledQuery | None:
        with self._lock:
            hit = self._data.get(key)
            if hit is not None:
                self._data.move_to_end(key)
            return hit

    def put(self, compiled: CompiledQuery) -> None:
        # FILL IN: insert by compiled.cache_key, evict oldest beyond max_entries
        raise NotImplementedError

    def invalidate_model(self, model_digest: str) -> int:
        """Drop entries compiled for `model_digest`; returns the count."""
        # FILL IN: cache_key is canonical JSON containing the full versioned key tuple;
        # extract its model_digest component at put() and maintain a side index.
        # Keep put(compiled) signature fixed; do not use an undecodable opaque hash.
        raise NotImplementedError
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_execution.py` (CREATE)

```python
"""Regression contract: Execution bridge and pre-governance compile cache (M9a)."""
from pathlib import Path
import pytest


def test_named_env_overlay_and_missing_credentials(tmp_path: Path) -> None:
    """Verify named env overlay and missing credentials."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_queryresult_unwrap_and_execution_failure(tmp_path: Path) -> None:
    """Verify queryresult unwrap and execution failure."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_lru_bounds_and_real_model_invalidation(tmp_path: Path) -> None:
    """Verify lru bounds and real model invalidation."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_cache.py` (CREATE)

```python
"""Regression contract: Execution bridge and pre-governance compile cache (M9a)."""
from pathlib import Path
import pytest


def test_named_env_overlay_and_missing_credentials(tmp_path: Path) -> None:
    """Verify named env overlay and missing credentials."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_queryresult_unwrap_and_execution_failure(tmp_path: Path) -> None:
    """Verify queryresult unwrap and execution failure."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_lru_bounds_and_real_model_invalidation(tmp_path: Path) -> None:
    """Verify lru bounds and real model invalidation."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/execution.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/cache.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_execution.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_cache.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Implement ConnectionResolver.resolve using named environment overlay over get_default_credentials(driver); credentials never come from SemanticQuery/tool arguments.
- [ ] Executor.run unwraps QueryResult.rows/row_count/columns correctly; never treat source.query as a list. Preserve empty-result column information through a private metadata helper when building SemanticQueryResult.
- [ ] Implement bounded CompileCache with get/put/invalidate_model and a model-digest index; invalidation must actually remove entries. Cache only pre-governance objects and canonical versioned keys.
- [ ] Unit tests use source doubles here; stock DuckDB integration is validated after its dedicated repair. Cap rows and define truncated from actual overfetch evidence, not equality with LIMIT.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_execution.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_cache.py -q`

## Test Specification

- `test_named_env_overlay_and_missing_credentials`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_queryresult_unwrap_and_execution_failure`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_lru_bounds_and_real_model_invalidation`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4475` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Populated only by the authorized completion workflow with implementation/validation evidence. Task planning is not completion.
