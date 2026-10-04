# TASK-3696: Integration tests: DDL ingest → MCP lookup; live SQLite sync → plane-warmed partition; bots/database suite plane on/off

**Feature**: FEAT-600 — SQL Schema Plane
**Spec**: `sdd/specs/sql-schema-plane.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3686, TASK-3690, TASK-3693
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests and brainstorm spike 4 (plane-tier regression). Three end-to-end checks over real SQLite files, no external services: (1) fold the in-repo `001_task_memory.sql` into a temp plane and read it back through `create_wiki_mcp_server`'s tool list; (2) a `SQLToolkit(database_type="sqlite")` against a temp SQLite DB → `sync` → `lookup` → `neighbors`, then a `CachePartition(plane=…)` reads without touching the DB; (3) run the existing `tests/bots/database` suite with an in-memory plane injected via a conftest-level fixture toggle (documented, opt-in env `PARROT_TEST_SCHEMA_PLANE=1`).

---

## Scope

- Create `packages/ai-parrot/tests/integration/knowledge/__init__.py`, `wiki/__init__.py`, `wiki/test_schema_plane_e2e.py` with the three scenarios (scenario 3 as a subprocess `pytest` run guarded by a marker so it stays opt-in).
- Do NOT modify existing conftest files.

**NOT in scope**: BigQuery cost baseline (spec §8 Q2 — needs credentials); production Postgres plane.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/knowledge/__init__.py` | CREATE | package |
| `packages/ai-parrot/tests/integration/knowledge/wiki/__init__.py` | CREATE | package |
| `packages/ai-parrot/tests/integration/knowledge/wiki/test_schema_plane_e2e.py` | CREATE | three e2e scenarios |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (HEAD `0384596cf`, 2026-09-24). Use them VERBATIM. Anything not listed
> here must be verified with `grep`/`read` before use.

### Verified Imports
```python
from parrot.knowledge.wiki.schema.service import SchemaPlaneService          # TASK-3684/3686
from parrot.knowledge.wiki.schema.models import SchemaPlaneConfig, SchemaSourceConfig   # TASK-3680
from parrot.knowledge.wiki.schema.tools import create_schema_tools               # TASK-3689
from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server              # verified: packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py
from parrot.bots.database.toolkits.sql import SQLToolkit                         # verified: toolkits/sql.py:62 (database_type="sqlite" is in _SQLGLOT_DIALECT_MAP :50)
from parrot.bots.database.cache import CachePartition                             # verified: cache.py:54 (+ plane kwargs from TASK-3691)
from parrot.bots.database.agent import DatabaseAgent                             # verified: agent.py:126 (+ schema_plane from TASK-3693)
```

### Existing Signatures to Use
```python
# see TASK-3684/3686/3689/3690/3691/3693 contracts; corpus: packages/ai-parrot/src/parrot/tools/working_memory/task_memory/migrations/001_task_memory.sql (6T/70c/3fk)
# packages/ai-parrot/src/parrot/bots/database/toolkits/base.py:104 DatabaseToolkit(dsn, allowed_schemas=None, primary_schema=None, tables=None, read_only=True, cache_partition=None, retry_config=None, database_type="postgresql", ...)
# sqlite DSN for asyncdb: FILL IN after reading toolkits/base.py _DRIVER_MAP (grep -n _DRIVER_MAP)
```

### Does NOT Exist
- ~~a shared `schema_service` fixture in an existing conftest~~ — define fixtures locally in this test module
- ~~BigQuery in CI~~ — out of scope

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/integration/knowledge/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/integration/knowledge/wiki/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/integration/knowledge/wiki/test_schema_plane_e2e.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py#create_wiki_mcp_server",
    "sym:packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py#SQLToolkit",
    "sym:packages/ai-parrot/src/parrot/bots/database/cache.py#CachePartition"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`packages/ai-parrot/tests/integration/bots/database/test_feat_172_no_regression.py` for integration-test style.

### Key Constraints
- No network, no Redis (pass `redis_url=None`), no BigQuery.
- Scenario 3 is opt-in (`PARROT_TEST_SCHEMA_PLANE=1`) and runs `pytest packages/ai-parrot/tests/bots/database -q` in a subprocess with the plane fixture env set; it is a directory run INSIDE the test, not a Validation Command.

### References in Codebase
- packages/ai-parrot/tests/integration/bots/database/test_feat_172_no_regression.py
- sdd/specs/sql-schema-plane.spec.md §4 Integration Tests

---

## Implementation Blueprint

> Executor-ready starting point derived from spec §3 Interface Skeletons; anchors re-verified at HEAD
> `0384596cf`. Complete every `# FILL IN:` marker; never change a signature, class name or path fixed here.

### Steps (in order)
1. Scenario 1: `from_dir` → `ingest_ddl([DDL_CORPUS], origin='taskmem', dialect='postgres')` → `create_schema_tools` → lookup a known table → assert DDL, columns, `defined_in` edge.
2. Scenario 2: create a temp SQLite DB with two FK-linked tables; `SchemaPlaneConfig(sources={{'sqlite': …}})`; `sync` via `SQLToolkit(database_type='sqlite')`; `lookup`/`neighbors`; then `CachePartition(plane=svc, origin='sqlite')` `get()` with the DB file deleted.
3. Scenario 3: guarded subprocess run of the bots/database suite with the plane on.

### `packages/ai-parrot/tests/integration/knowledge/wiki/test_schema_plane_e2e.py` (CREATE)
```python
"""FEAT-600 end-to-end: DDL ingest → tool lookup; live SQLite sync → plane-warmed partition; suite parity plane on/off."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.schema.models import SchemaPlaneConfig, SchemaSourceConfig
from parrot.knowledge.wiki.schema.service import SchemaPlaneService
from parrot.knowledge.wiki.schema.tools import create_schema_tools

DDL_CORPUS = Path("packages/ai-parrot/src/parrot/tools/working_memory/task_memory/migrations/001_task_memory.sql")


@pytest.fixture
def svc(tmp_path: Path) -> SchemaPlaneService:
    return SchemaPlaneService.from_dir(tmp_path / "schema", config=SchemaPlaneConfig(), read_only=False)


async def test_ddl_ingest_then_tool_lookup(svc):
    report = await svc.ingest_ddl([DDL_CORPUS], origin="taskmem", dialect="postgres", root=Path("."))
    assert len(report.created) == 6 and not report.parse_errors
    tools = {t.name: t for t in create_schema_tools(svc.store, None, WikiProjectConfig(), service=svc)}
    res = await tools["wiki_schema_lookup"]._execute(ref=report.created[0].replace("table:taskmem/", "taskmem:"))
    assert res.success and res.result["ddl"].startswith("CREATE TABLE")
    assert any(r["rel"] == "defined_in" for r in res.result["relations"])


async def test_live_sqlite_sync_and_plane_warmed_partition(tmp_path: Path, svc):
    db = tmp_path / "live.db"
    with sqlite3.connect(db) as con:
        con.executescript("CREATE TABLE stores(id INTEGER PRIMARY KEY); CREATE TABLE sales(id INTEGER PRIMARY KEY, store_id INTEGER REFERENCES stores(id));")
    svc.config.sources["sqlite"] = SchemaSourceConfig(alias="sqlite", dialect="sqlite", dsn_env="LIVE_DSN", allowed_schemas=["main"], tables=["main.stores", "main.sales"])
    # FILL IN: build SQLToolkit(dsn=<sqlite DSN form per toolkits/base.py _DRIVER_MAP>, database_type="sqlite", ...) and pass it as toolkit=
    report = await svc.sync("sqlite", dsn_resolver=lambda _n: str(db))
    assert set(report.created) == {"table:sqlite/main.stores", "table:sqlite/main.sales"}
    hops = await svc.neighbors("sqlite:main.sales", depth=1)
    assert hops and hops[0]["target"] == "table:sqlite/main.stores"
    db.unlink()  # the plane must now answer alone
    from parrot.bots.database.cache import CachePartition

    part = CachePartition(namespace="sqlite_main", plane=svc, origin="sqlite")  # FILL IN: exact ctor args (cache.py:60-75)
    meta = await part.get("main", "sales")
    assert meta is not None and meta.tablename == "sales"


@pytest.mark.skipif(os.environ.get("PARROT_TEST_SCHEMA_PLANE") != "1", reason="opt-in: runs the bots/database suite with the plane on")
def test_bots_database_suite_with_plane_on():
    env = {**os.environ, "PARROT_TEST_SCHEMA_PLANE": "1"}
    proc = subprocess.run([sys.executable, "-m", "pytest", "packages/ai-parrot/tests/bots/database", "-q"], env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout[-2000:]
```
**Why**: Covers spec §4 Integration Tests 1–3 and brainstorm spike 4 with SQLite only, so it runs in CI without credentials.

### FILL IN checklist
- [ ] sqlite DSN form for `SQLToolkit` (read `_DRIVER_MAP` in toolkits/base.py)
- [ ] `CachePartition` constructor args
- [ ] exact `relations` row shape from TASK-3684 `lookup`

---

## Acceptance Criteria

- [ ] scenario 1: 6 tables created from the corpus; tool lookup returns DDL + `defined_in` relation
- [ ] scenario 2: sync creates both tables, `neighbors` returns the FK hop, partition `get()` succeeds after the DB file is deleted (G4/AC8)
- [ ] scenario 3 (opt-in) green
- [ ] ruff/black clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/integration/knowledge/wiki/test_schema_plane_e2e.py -q`

---

## Test Specification

```python
# see Implementation Blueprint — this task IS the test module
```

---

## Agent Instructions

1. Read the spec (`sdd/specs/sql-schema-plane.spec.md`) §2, §3 module for this task, §6 Codebase Contract, §7.
2. Check dependencies — `TASK-3686, TASK-3690, TASK-3693` must be in `sdd/tasks/completed/`.
3. Verify the Codebase Contract above (`grep`/`read`) before writing code; re-run `grep -c` on every MODIFY anchor.
4. Implement from the Blueprint; complete every `# FILL IN:`; run the Validation Commands
   (inside a worktree: `PYTHONPATH=packages/ai-parrot/src pytest …`), then `ruff check` + `black --check` on touched files.
5. Commit ONLY the files listed above. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (seat: gpt-5.6-luna, backend: codex, attempt_uid d2614ad0912f42fdb59990d72c773acc; attempt 1 gpt-5.6-terra failed with `empty_delivery`, engine auto-retried onto attempt 2)
**Date**: 2026-09-24
**Notes**: Implementation commit `90abc4dbf` + engine lint-autofix commit `226155763` (merge `5b1671841`). Three end-to-end scenarios: (1) DDL ingest of `001_task_memory.sql` → `create_wiki_mcp_server` tool lookup, (2) live SQLite `sync` → `neighbors` → DB removal → plane-warmed `CachePartition` read, (3) opt-in `tests/bots/database` suite with the plane on (`PARROT_TEST_SCHEMA_PLANE=1`). Engine-side merge fidelity check passed (`unexpected_files: []`).

**Review fix (orchestrator-applied)**: `test_live_sqlite_sync_and_plane_warmed_partition` asserted `hops[0]["target"]`, a key `SchemaPlaneService.neighbors()` never returns — `BaseWikiStore.neighbors()` keys the adjacent page as `concept_id`, and `service.py`'s `neighbors()` spreads that dict verbatim. This file lives under `tests/integration/`, so it's excluded from the merge-tier sweep by its `-m 'not integration'` marker filter and only surfaced when run directly. Fixed to `hops[0]["concept_id"]` (fix commit `8d31f3390b`). Recorded as model feedback `coder-feedback:00da490a0816550f0789078c`.
**Verification**: all 3 scenarios pass — 2 direct (`2 passed, 1 skipped`) + scenario 3 separately with `PARROT_TEST_SCHEMA_PLANE=1` (`1 passed`, 53.5s). Reviewed via `coder-review:eaa58f5b7ec2e9e1e8749e04`.
**Merge validation**: merge-tier (root scope) — same 4 pre-existing/environmental failures as prior chunks (see `issue:33fe54e65d2d`), unrelated to this task's files.

**Deviations from spec**: none
