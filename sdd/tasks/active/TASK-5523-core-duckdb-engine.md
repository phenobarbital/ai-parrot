# TASK-5523: Core in-process DuckDB engine over Arrow

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. The repository has no in-process engine over DataFrames: DuckDB is used only as a queried
database, one short-lived connection per query (`DuckDBSource`). This task adds a reusable engine in **core**
(`parrot.interfaces.duckdb_engine`) with no accounting concept: one root connection, Arrow-registered frames,
per-thread cursors. The accounting DuckDB runtime (TASK-5533) and a future DuckDB-backed dataset store build on it.
It lives in core because `ai-parrot-semantic` depends on `ai-parrot`, never the reverse (spec §8 "Engine home").

This task also settles spec §8 **Q1**: whether a frame registered on one DuckDB cursor is invisible to other
cursors of the same root connection. Write `test_engine_per_call_frames_isolated` first.

---

## Scope

- Implement `FrameConversionError`, `to_arrow()` and `DuckDBEngine` in `parrot/interfaces/duckdb_engine.py`.
- Add the optional core extra `duckdb = ["duckdb>=1.0"]` to `packages/ai-parrot/pyproject.toml`.
- Write `packages/ai-parrot/tests/interfaces/test_duckdb_engine.py` with the seven M1 tests of spec §4.
- Record the Q1 outcome (isolated by cursor, or fallback used) in the Completion Note.

**NOT in scope**: anything accounting-specific (`DuckDBRuntime` is TASK-5533); `DuckDBSource` or
`DatabaseQueryToolkit` changes; a DuckDB-backed `DatasetManager` store; declaring polars anywhere; editing
`packages/ai-parrot-semantic/pyproject.toml` (its `duckdb` extra already exists and `test_packaging.py` pins it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/duckdb_engine.py` | CREATE | `FrameConversionError`, `to_arrow`, `DuckDBEngine` |
| `packages/ai-parrot/tests/interfaces/test_duckdb_engine.py` | CREATE | M1 unit tests |
| `packages/ai-parrot/pyproject.toml` | MODIFY | new optional extra `duckdb` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot._imports import require_extra   # packages/ai-parrot/src/parrot/_imports.py:248
import pyarrow as pa                         # core dependency "pyarrow>=25.0" (packages/ai-parrot/pyproject.toml:190); venv 26.0.0
# duckdb: venv 1.5.6, declared nowhere in core yet — import ONLY inside functions, after require_extra
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/_imports.py:248
def require_extra(extra: str, *modules: str) -> None
    # calls lazy_import(mod, extra=extra) per module; raises ImportError whose message says
    # "pip install ai-parrot[<extra>]" — so require_extra("duckdb", "duckdb") names ai-parrot[duckdb]

# packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:119-121 — pandas → Arrow pattern
try:
    table = pa.Table.from_pandas(df, preserve_index=True)   # this task uses preserve_index=False
except _ARROW_CONVERSION_ERRORS as exc: ...

# packages/ai-parrot/pyproject.toml
# :190 "pyarrow>=25.0",   :223 [project.optional-dependencies]
# :268 "# Financial analysis (ta-lib requires libta-lib-dev)"  (1 occurrence) — followed by :269 finance = [
```

### Does NOT Exist
- ~~`parrot.interfaces.duckdb_engine`~~, ~~`class DuckDBEngine`~~ — this task creates them; no `parrot/engines/`,
  `parrot/duckdb/`, `parrot/tools/duckdb/` package exists. `parrot/interfaces/dataframes.py` exists and is
  unrelated — do not edit it.
- ~~a `duckdb` extra in core~~ — `grep -n duckdb packages/ai-parrot/pyproject.toml` returns nothing today.
- ~~`fetch_arrow_table` / `.register(` anywhere in package sources~~ — no precedent; the only `import duckdb` is
  in `parrot/tools/databasequery/sources/duckdb.py`, which opens one connection per query and registers nothing.
- ~~`import polars`~~ — polars is declared nowhere; detect it by duck typing (`hasattr(frame, "to_arrow")`).
- ~~a free `finance` extra name~~ — `finance = [...]` at `pyproject.toml:269` is ta-lib, unrelated.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/duckdb_engine.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/interfaces/test_duckdb_engine.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY"}
  ],
  "contract_symbols": ["sym:packages/ai-parrot/src/parrot/_imports.py#require_extra"]
}
```

---

## Implementation Notes

### Key Constraints
- Never import `duckdb` at module import time — core must import without the extra (spec AC2).
- One root connection per engine; every `execute` uses a fresh `root.cursor()` inside `asyncio.to_thread`;
  cursors are closed in `finally`; never share a cursor across threads.
- A semaphore of `threads` bounds concurrent executions.
- Long-lived tables (`register`) are visible to every call; per-call `frames` are visible only to that call
  and are removed afterwards (spec §3 M1).
- `self.logger = logging.getLogger(__name__)`; no `print`.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:119-121` — Arrow conversion error handling.
- `packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py:136-143` — lazy `import duckdb` precedent.

---

## Implementation Blueprint

### Steps (in order)
1. Write `test_engine_per_call_frames_isolated` first and run it against a minimal engine — *why*: spec §8 Q1;
   if cursors share registrations, switch to the fallback (unique internal name + per-cursor temporary view)
   before writing the rest.
2. Write `duckdb_engine.py` from the block below and complete each `FILL IN` — *why*: signatures are fixed by
   the spec Interface Skeleton and consumed by TASK-5533.
3. Add the extra to `packages/ai-parrot/pyproject.toml` — *why*: AC16; `require_extra`'s message names it.
4. Write the remaining tests; guard every duckdb-using test with `pytest.importorskip("duckdb")` — *why*: a
   core-only environment must skip, not fail.

### `packages/ai-parrot/src/parrot/interfaces/duckdb_engine.py` (CREATE)
```python
"""In-process DuckDB engine over Arrow (FEAT-713 M1).

A reusable engine with no domain concept: one root connection, Arrow-registered frames and a fresh cursor
per call, run off the event loop. ``duckdb`` is an optional extra (``ai-parrot[duckdb]``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from parrot._imports import require_extra

if TYPE_CHECKING:
    import pyarrow as pa


class FrameConversionError(ValueError):
    """A frame could not be converted to Arrow under the requested numeric rules."""


def to_arrow(frame: Any, *, decimal_columns: tuple[str, ...] = (), allow_float: bool = False) -> "pa.Table":
    """Convert a pandas, polars-like or Arrow frame to a ``pa.Table``.

    Args:
        frame: ``pa.Table`` (passed through), a pandas DataFrame, or any object exposing ``to_arrow()``.
        decimal_columns: Columns that must be exact decimals.
        allow_float: When True, float decimal columns are cast to ``decimal128(38, 6)``.

    Returns:
        The Arrow table.

    Raises:
        FrameConversionError: Unsupported frame type, an object-dtype decimal column, or a float decimal
            column while ``allow_float`` is False.
    """
    import pyarrow as pa

    # FILL IN: dispatch — pa.Table passthrough; pandas via pa.Table.from_pandas(frame, preserve_index=False)
    #   (detect pandas by `hasattr(frame, "dtypes") and hasattr(frame, "iloc")`, never import polars);
    #   polars-like via frame.to_arrow(); anything else ⇒ FrameConversionError — bounded by spec §3 M1.
    # FILL IN: for each name in decimal_columns — missing ⇒ FrameConversionError; pandas object dtype ⇒
    #   FrameConversionError (checked BEFORE conversion); float type ⇒ error unless allow_float, then cast to
    #   pa.decimal128(38, 6); decimal types pass unchanged — bounded by AC9 / test_to_arrow_rejects_object_and_float.
    raise NotImplementedError


class DuckDBEngine:
    """In-process DuckDB over Arrow: one root connection, per-thread cursors, never a shared cursor."""

    def __init__(self, *, threads: int = 4, database: str = ":memory:") -> None:
        """Open the root connection.

        Args:
            threads: Maximum concurrent executions.
            database: DuckDB database path, ``":memory:"`` by default.

        Raises:
            ImportError: ``duckdb`` is not installed (message names ``ai-parrot[duckdb]``).
        """
        require_extra("duckdb", "duckdb")
        import duckdb

        self.logger = logging.getLogger(__name__)
        self._root = duckdb.connect(database=database)
        self._semaphore = asyncio.Semaphore(threads)
        self._tables: dict[str, "pa.Table"] = {}
        self._closed = False

    async def register(self, name: str, table: "pa.Table", *, replace: bool = True) -> None:
        """Register a long-lived Arrow table visible to every later call.

        Raises:
            ValueError: The name exists and ``replace`` is False.
            RuntimeError: The engine is closed.
        """
        # FILL IN: closed check; duplicate check; store in self._tables (cursors re-register it per call,
        #   or register on the root — whichever the Q1 test proves visible to cursors).
        raise NotImplementedError

    async def unregister(self, name: str) -> None:
        """Remove a long-lived table; unknown names are ignored."""
        # FILL IN
        raise NotImplementedError

    def registered(self) -> tuple[str, ...]:
        """Names of the long-lived tables, sorted."""
        return tuple(sorted(self._tables))

    async def execute(
        self, sql: str, *, frames: Mapping[str, "pa.Table"] | None = None, parameters: Sequence[Any] | None = None
    ) -> "pa.Table":
        """Run *sql* on a fresh cursor in a worker thread.

        *frames* are registered for this call only and removed afterwards; they shadow long-lived tables of the
        same name and are invisible to other calls.

        Raises:
            RuntimeError: The engine is closed.
        """
        if self._closed:
            raise RuntimeError("DuckDBEngine is closed")
        async with self._semaphore:
            return await asyncio.to_thread(self._execute_sync, sql, dict(frames or {}), parameters)

    def _execute_sync(self, sql: str, frames: dict[str, "pa.Table"], parameters: Sequence[Any] | None) -> "pa.Table":
        cursor = self._root.cursor()
        try:
            # FILL IN: register long-lived tables not shadowed by frames, then frames, on THIS cursor;
            #   execute with parameters when given; return cursor.fetch_arrow_table(). If Q1 shows cursor
            #   registrations leak, use a unique internal name per call plus a per-cursor TEMP VIEW named <name>.
            raise NotImplementedError
        finally:
            cursor.close()

    async def close(self) -> None:
        """Close the root connection; later calls raise RuntimeError."""
        # FILL IN: idempotent; set _closed, close root (in to_thread), clear _tables.
        raise NotImplementedError
```
**Why**: the semaphore + `to_thread` + per-call cursor is the threading contract of spec §7 Patterns; the
`_execute_sync` split keeps all blocking DuckDB work in one place.

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# BEFORE — insert ABOVE `# Financial analysis (ta-lib requires libta-lib-dev)` (verified: packages/ai-parrot/pyproject.toml:268)
# occurrences: 1 (verified: grep -c '# Financial analysis (ta-lib requires libta-lib-dev)' packages/ai-parrot/pyproject.toml)
# In-process DuckDB engine (parrot.interfaces.duckdb_engine)
duckdb = ["duckdb>=1.0"]

```
**Why**: AC16 — `duckdb` is an optional extra of core, never a hard dependency. Do not touch `uv.lock`.

### `packages/ai-parrot/tests/interfaces/test_duckdb_engine.py` (CREATE)
```python
"""FEAT-713 M1 — in-process DuckDB engine over Arrow."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pyarrow as pa
import pytest

from parrot.interfaces.duckdb_engine import DuckDBEngine, FrameConversionError, to_arrow


def test_engine_requires_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing duckdb module raises the require_extra error naming ai-parrot[duckdb]."""
    # FILL IN: make importing duckdb fail (monkeypatch sys.modules["duckdb"] = None) and assert
    #   pytest.raises(ImportError, match=r"ai-parrot\[duckdb\]").


async def test_engine_register_and_execute_arrow() -> None:
    pytest.importorskip("duckdb")
    # FILL IN: register a table, SELECT from it, assert isinstance(result, pa.Table) and values.


async def test_engine_per_call_frames_isolated() -> None:
    """8 concurrent calls using the same frame name with different data each see only their own frame."""
    pytest.importorskip("duckdb")
    # FILL IN: asyncio.gather of 8 execute("SELECT max(v) FROM t", frames={"t": table_i}); assert result i == i.


async def test_engine_per_call_frame_shadows_and_is_removed() -> None:
    pytest.importorskip("duckdb")
    # FILL IN: long-lived "t" + per-call "t" ⇒ per-call wins; next call without frames sees the long-lived one.


async def test_engine_closed_raises() -> None:
    pytest.importorskip("duckdb")
    # FILL IN: close(), then execute ⇒ RuntimeError.


def test_to_arrow_pandas_polars_arrow() -> None:
    # FILL IN: pandas DataFrame and pa.Table convert; polars via pytest.importorskip("polars").


def test_to_arrow_rejects_object_and_float() -> None:
    # FILL IN: object-dtype Decimal column ⇒ FrameConversionError; float column ⇒ error unless allow_float,
    #   then the column type is pa.decimal128(38, 6).
```

### FILL IN checklist
- [ ] `to_arrow` — dispatch and decimal rules; bounded by spec §3 M1 and AC9.
- [ ] `DuckDBEngine.register/unregister/close` — lifecycle; bounded by the Interface Skeleton.
- [ ] `DuckDBEngine._execute_sync` — per-cursor registration; bounded by spec §8 Q1 (fallback in §7 Risks).
- [ ] Seven tests of spec §4 M1.

---

## Acceptance Criteria

- [ ] `python -c "import parrot.interfaces.duckdb_engine"` works with `duckdb` absent; `DuckDBEngine()` then
  raises `ImportError` naming `ai-parrot[duckdb]` (spec AC2).
- [ ] 8 concurrent per-call frames are isolated; per-call frames shadow and are removed (spec AC10, Q1).
- [ ] `to_arrow` handles pandas, Arrow and polars-when-installed; rejects object/float decimals unless
  `allow_float` (spec AC9).
- [ ] `packages/ai-parrot/pyproject.toml` declares `duckdb = ["duckdb>=1.0"]` as an optional extra only (AC16).
- [ ] `ruff check packages/ai-parrot/src/parrot/interfaces/duckdb_engine.py packages/ai-parrot/tests/interfaces/test_duckdb_engine.py` passes.

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_duckdb_engine.py -q`

---

## Test Specification

See the test block in the Implementation Blueprint; one test per spec §4 M1 row:
`test_engine_requires_extra`, `test_engine_register_and_execute_arrow`, `test_engine_per_call_frames_isolated`,
`test_engine_per_call_frame_shadows_and_is_removed`, `test_engine_closed_raises`,
`test_to_arrow_pandas_polars_arrow`, `test_to_arrow_rejects_object_and_float`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug accounting-metrics-layer --feature-id FEAT-713`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/accounting-metrics-layer.json`
4. **Verify the Codebase Contract** before writing any code; update it first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5523 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented; the Q1 outcome (cursor registrations isolated, or fallback used).

**Deviations from spec**: none | describe if any
