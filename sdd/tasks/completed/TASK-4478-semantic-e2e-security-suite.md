# TASK-4478: End-to-end governed-query security suite on DuckDB (M10 gate)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4477
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests + Worktree Strategy 'Ordering inside M10': the governance, cache-isolation and engine-switch e2e tests must be green before `run_sql` / `save_result_as_dataset` (TASK-4479) ship. This task writes those tests; it should change no source file — a failing test is reported, then fixed in the owning module's file only with a note.

---

## Scope

- Write `test_e2e_governed.py`: `test_e2e_duckdb_governed_query`, `test_e2e_rls_two_subjects_same_roles`, `test_e2e_pbac_denial_paths` (structured paths; the raw-SQL leg is added by TASK-4479), `test_e2e_native_engine_switch`.

**NOT in scope**: raw SQL and hand-off e2e (TASK-4479); fixing production code beyond a minimal, noted fix.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/tests/test_e2e_governed.py` | CREATE | e2e security suite |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
from parrot.semantic import SemanticLayerToolkit, SemanticQuery    # TASK-4477
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit   # verified: databasequery/toolkit.py:115
```

### Existing Signatures to Use
```python
# TASK-4477 — SemanticLayerToolkit(models_dir=, dialect=, dataplane_guard=, database_toolkit=, ...);
#             tools invoked through get_tools() so _pre_execute receives _permission_context (toolkit.py:174-178)
```

### DuckDB driver workaround (added 2026-10-19)
- The core `DatabaseQueryToolkit().get_source("duckdb").query(...)` is broken in this environment
  (`await conn.fetch_all()` on a list — issue:58d44d14dd8a; out of scope here). Patch the toolkit's duckdb
  source `query` exactly as `packages/ai-parrot-semantic/tests/test_execution.py` does (in-process `duckdb`
  executing the GOVERNED SQL against the fixture file and returning a real `QueryResult`). Assert on rows
  computed by DuckDB from the governed SQL — never stub rows. Record the workaround in your summary.

### Does NOT Exist
- ~~Calling tool methods directly to test PBAC~~ — direct calls bypass `_pre_execute`; invoke through the generated `ToolkitTool.execute(..., _permission_context=pctx)` path.
- ~~A real Postgres/BigQuery~~ — DuckDB only (SQL snapshots cover other dialects).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/tests/test_e2e_governed.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py#DatabaseQueryToolkit"
  ]
}
```

---

## Implementation Notes

- Point the model's connection at the DuckDB file with `PARROT_SEMANTIC_CONN_<NAME>_DATABASE` via monkeypatch.setenv.
- Two subjects with identical roles/tenant but different `programs` metadata must get different rows from one warm cache entry (AC8).

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
1. Build the toolkit against the DuckDB fixture — *why*: real execution.
2. Write the four e2e tests — *why*: release gate for TASK-4479.

### `packages/ai-parrot-semantic/tests/test_e2e_governed.py` (CREATE)
```python
"""FEAT-704 e2e security gate: governed queries on an in-process DuckDB (spec §4 Integration Tests)."""
from __future__ import annotations

import pytest

from ._models import duckdb_warehouse, models_dir  # noqa: F401
from parrot.semantic import SemanticLayerToolkit


@pytest.fixture
def toolkit(models_dir, duckdb_warehouse, allow_all_guard, monkeypatch):
    # FILL IN: monkeypatch.setenv("PARROT_SEMANTIC_CONN_<CONN>_DATABASE", duckdb_warehouse) for the fixture
    #          policy's connection name; return SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb",
    #          dataplane_guard=allow_all_guard)
    raise NotImplementedError


async def _call(tk, name: str, pctx, **params):
    tool = next(t for t in tk.get_tools() if t.name == name)
    # FILL IN: await tool.execute(**params, _permission_context=pctx) and unwrap the ToolResult payload
    raise NotImplementedError


async def test_e2e_duckdb_governed_query(toolkit, pctx_factory):
    # FILL IN: rows returned; ledger has one ok entry with governed_sql; compiled SQL recorded
    ...


async def test_e2e_rls_two_subjects_same_roles(toolkit, pctx_factory):
    # FILL IN: warm cache as A (programs=[north]); B same roles/tenant, programs=[south] -> only south rows;
    #          the cached CompiledQuery.sql is byte-identical before/after
    ...


async def test_e2e_pbac_denial_paths(models_dir, duckdb_warehouse, deny_table_guard, pctx_factory):
    # FILL IN: deny "sales.orders" -> compile_query, query_metrics, saved query, dimension values and a cache hit
    #          all return error pbac_denied, no SQL in the payload, DuckDB never queried
    ...


async def test_e2e_native_engine_switch(models_dir, duckdb_warehouse, allow_all_guard, pctx_factory):
    # FILL IN: copy the policy with engine: native -> same rows as the sidemantic model
    ...
```

### FILL IN checklist
- [ ] Fixture + `_call` helper.
- [ ] Four e2e test bodies — bounded by AC4, AC5, AC8, AC11.

---

## Acceptance Criteria

- [ ] All four tests pass on DuckDB.
- [ ] No source file changed, or each change is a minimal fix noted in the Completion Note.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_e2e_governed.py -q`

---

## Test Specification

```python
# see the packages/ai-parrot-semantic/tests/test_e2e_governed.py block above — it IS the test file
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
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4478 — End-to-end governed-query security suite on DuckDB (M10 gate)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4478 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

- Task: TASK-4478
- Feature: semantic-layer
- Closed at (UTC): 2026-10-19
- Fix commits: none
- Seat: opus (native) · Attempts: 1 · Tokens: 84k
- Validation: merge-tier ad0839b5:wave9:merge completed exit 0 (4 passed, 1 xfailed).
- Review: coder-review:17311e4001367e5ac819ef42 — no corrections.
- Workarounds in the test: duckdb source query() patched (issue:58d44d14dd8a) running GOVERNED SQL in-process; tmp policy RLS driver pg→duckdb; analyst usage widened to "*" (see below); _pbac.available=True with the guard double deciding.
- **OPEN (escalated)**: test_e2e_granted_metric_requires_no_usage_grant is xfail(strict). Lineage requires usage grants for every non-projection column incl. granted metric inputs (SUM(amount) → usage_denied for analyst), while spec AC6 scopes usage rights to masked/hidden columns; 'hidden' undefined. Filed issue:9a4e4c35b032 (major); awaiting design decision.
