# TASK-4475: Execution bridge, connection resolver and compile cache (M9a)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4464
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (execution + cache) + AC8: credentials resolved inside the satellite from a named connection (never from tool arguments); governed SQL executed through the existing `DatabaseQueryToolkit` sources; an LRU that stores ONLY pre-governance `CompiledQuery` objects.

---

## Scope

- Implement `packages/ai-parrot-semantic/src/parrot/semantic/execution.py`: `ConnectionResolver`, `Executor`.
- Implement `packages/ai-parrot-semantic/src/parrot/semantic/cache.py`: `CompileCache` (`get`, `put`, `invalidate_model`).
- Write `test_execution.py` and `test_cache.py`.

**NOT in scope**: result handles (TASK-4476); deciding the connection name (it comes from `ModelPolicy.connection`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/execution.py` | CREATE | ConnectionResolver + Executor |
| `packages/ai-parrot-semantic/src/parrot/semantic/cache.py` | CREATE | pre-governance LRU |
| `packages/ai-parrot-semantic/tests/test_execution.py` | CREATE | resolver/executor tests |
| `packages/ai-parrot-semantic/tests/test_cache.py` | CREATE | cache tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit    # verified: packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py:115
from parrot.tools.databasequery.base import AbstractDatabaseSource, QueryResult   # verified: base.py:323,148
from parrot.interfaces.database import get_default_credentials        # verified: packages/ai-parrot/src/parrot/interfaces/database.py:501
from parrot.semantic.models import GovernedQuery, CompiledQuery       # TASK-4464
from parrot.semantic.errors import SemanticExecutionError             # TASK-4464
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py
class DatabaseQueryToolkit(AbstractToolkit):     # line 115 — __init__(**kwargs) accepts only output_dir/static_dir (+ AbstractToolkit kwargs)
    def get_source(self, driver: str) -> AbstractDatabaseSource   # line 202 — cached per driver
# packages/ai-parrot/src/parrot/tools/databasequery/base.py
class QueryResult(BaseModel):   # line 148 — driver: str; rows: list[dict[str, Any]]; row_count; columns; execution_time_ms
class AbstractDatabaseSource(ABC):   # line 323
    async def query(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None = None) -> QueryResult   # line 446
# packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py — credentials.get("database", credentials.get("dsn", ":memory:")) (line 63)
# packages/ai-parrot/src/parrot/interfaces/database.py:501 — get_default_credentials(driver) -> dict ({} when unknown/unset; None values stripped)
```

### Does NOT Exist
- ~~Named-connection credentials in `DatabaseQueryToolkit`~~ — credentials are the first positional argument of `query()`.
- ~~`query()` returning a list of rows~~ — it returns `QueryResult` (spec skeleton says `rows = await source.query(...)`; use `.rows`/`.row_count`).
- ~~Caching governed SQL~~ — forbidden (AC8).

---

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
    "sym:packages/ai-parrot/src/parrot/interfaces/database.py#get_default_credentials"
  ]
}
```

---

## Implementation Notes

- Env grammar: `PARROT_SEMANTIC_CONN_<CONNECTION>_<KEY>` (connection upper-cased, non-alnum → `_`); KEY lower-cased into the dict and overlays the defaults.
- Executor truncation: if `row_count > governed.limit` (should not happen after the guard) set `truncated=True` and cut rows; timing via `time.perf_counter()`.
- `get_default_credentials` imports navconfig lazily; tests pass an explicit `env` mapping and monkeypatch the function.

### Key Constraints
- Async-first; sync CPU-only work (sqlglot, sidemantic compile) runs under `asyncio.to_thread` at the call site.
- Pydantic v2 models; `logging.getLogger(__name__)` / `self.logger`, never `print`.
- Google-style docstrings, strict type hints, 120-column lines; `ruff check` clean (TID251 bans apply).
- Fail closed wherever governance is involved (spec §7 "Patterns to Follow").
- Worktree testing: prefix pytest with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` (add `:packages/ai-parrot-server/src` for server tests); never `uv sync` inside a worktree.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim,
> then complete every `# FILL IN:` marker. Never change a signature, class name or path the
> blueprint fixes (they come from the spec §3 Interface Skeletons).

### Steps (in order)
1. Write `ConnectionResolver` — *why*: credentials never from tool args.
2. Write `Executor.run` — *why*: execution bridge, no SQL in error messages.
3. Write `CompileCache` (OrderedDict LRU keyed by `cache_key`) — *why*: AC8.
4. Write tests.

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
        # FILL IN: the cache_key is a hash, so keep a side map key -> model_digest filled by put()
        #          (put needs the digest: add keyword-only `model_digest: str | None = None` to put)
        raise NotImplementedError
```
**Why**: spec §3 M9 skeleton; `invalidate_model` needs a key→digest side map because the key is an opaque hash.

### FILL IN checklist
- [ ] `ConnectionResolver.resolve`.
- [ ] `Executor.run` — no SQL in messages (spec §7 schema drift).
- [ ] `CompileCache.put` / `invalidate_model`.

---

## Acceptance Criteria

- [ ] `test_connection_resolver_env_overlay` and `test_compile_cache_pre_governance_only` pass (AC8).
- [ ] Executor runs governed SQL against an in-process DuckDB source in a test.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_execution.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_cache.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_execution.py
import pytest
from parrot.semantic.execution import ConnectionResolver
from parrot.semantic.errors import SemanticExecutionError


def test_connection_resolver_env_overlay(monkeypatch):
    monkeypatch.setattr("parrot.semantic.execution.get_default_credentials", lambda d: {"user": "u", "password": "x"})
    r = ConnectionResolver(env={"PARROT_SEMANTIC_CONN_WAREHOUSE_PG_PASSWORD": "y"})
    assert r.resolve("warehouse_pg", "pg")["password"] == "y"
    monkeypatch.setattr("parrot.semantic.execution.get_default_credentials", lambda d: {})
    with pytest.raises(SemanticExecutionError):
        ConnectionResolver(env={}).resolve("x", "pg")

# FILL IN: Executor against DatabaseQueryToolkit().get_source("duckdb") with a tmp duckdb file;
#          test_cache.py: test_compile_cache_pre_governance_only (LRU eviction, invalidate_model)
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer --feature-id FEAT-704 --spec sdd/specs/semantic-layer.spec.md --index sdd/tasks/index/semantic-layer.json`).
2. **Read the spec** (`sdd/specs/semantic-layer.spec.md`), especially the sections named in Context.
3. **Check dependencies** — every `Depends-on` task is `done` in `sdd/tasks/index/semantic-layer.json`.
4. **Verify the Codebase Contract** before writing code; fix a stale entry in this file first.
5. **Implement** exactly the files above, following the blueprint; touch nothing else.
6. **Validate**: `ruff check --fix <files>`, then the Validation Commands.
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4475 — Execution bridge, connection resolver and compile cache (M9a)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4475 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

- Task: TASK-4475
- Feature: semantic-layer
- Closed at (UTC): 2026-10-19
- Fix commits: none
- Seat: sonnet (native) · Attempts: 1 · Tokens: 83k
- Validation: merge-tier ad0839b5:wave3:merge completed exit 0 (12 passed).
- Review: coder-review:cb0e13b33ecba0fc7f4e5e6f — no corrections.
- **Caveat**: the stock core DuckDB databasequery source is broken (awaits non-awaitable conn.fetch_all) — filed issue:58d44d14dd8a. test_execution.py patches the source's query() with in-process duckdb returning a real QueryResult; executor/resolver/source lookup still exercised.
