# TASK-4848: Postgres MetricDefinition store (navigator.metric_definitions)

**Feature**: FEAT-756 — Metric Definition Registry
**Spec**: `sdd/specs/metric-definition-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4843
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 / G2. Metric definitions need a durable, tenant-scoped store on the server. It
implements the `MetricStore` protocol (get/list/save/delete, spec §3 M2) over a new Postgres table
`navigator.metric_definitions`, copying the `PgUISurfaceStore` idiom. It also adds `list_visible(scope)`,
which the HTTP handler (TASK-4855) uses for PBAC.

---

## Scope

- Create `PgMetricDefinitionStore` with `_DDL_STATEMENTS`, `ensure_schema`, `get`, `list`, `save`,
  `delete`, `list_visible`.
- Store the whole `MetricDefinition.model_dump(mode="json")` as a native JSONB object (never `json.dumps`).
- Write unit tests with a fake AsyncDB (the `test_ui_surfaces_store.py` idiom) plus a live round-trip test
  that is skipped when `NAVIGATOR_PG_DSN` is unset.

**NOT in scope**: the HTTP handler (TASK-4855), manager route wiring (TASK-4856), `DELETE` over HTTP,
any edit to `handlers/models/ui_surfaces.py` (G9), and importing that module's private helpers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/models/metric_definitions.py` | CREATE | `PgMetricDefinitionStore` + DDL |
| `packages/ai-parrot-server/tests/handlers/test_metric_definitions_store.py` | CREATE | fake-AsyncDB unit tests + gated live round-trip |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from asyncdb import AsyncDB                                   # verified: handlers/models/ui_surfaces.py:29
from parrot.conf import default_dsn                           # verified: handlers/models/ui_surfaces.py:30 (conf.py:72/76, may be None)
from parrot.handlers.scope import RequestScope, scope_grants  # verified: handlers/scope.py:40, :181
from parrot.metrics import MetricDefinition                   # created by TASK-4843 (parrot/metrics/models.py)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py  (PATTERN ONLY — do not import)
_DDL_STATEMENTS: list[str] = [...]                          # L107
async def _exec(conn, sql, *args) -> None                    # L438 — raises when conn.execute returns (result, error)
async def _fetch_rows(conn, sql, *args) -> list[Any]         # L446 — conn.fetch_all, None → []
class PgUISurfaceStore:                                      # L457
    def __init__(self, dsn=None): self.dsn = dsn or default_dsn; self._schema_ensured = False   # L469
    def _get_db(self) -> AsyncDB: return AsyncDB("pg", dsn=self.dsn)                            # L474
    async def _ensure_ready(self) -> None                                                       # L478
    async def ensure_schema(self) -> None   # L483 — `async with await db.connection() as conn`; "already exists" tolerated
    async def save(self, record, *, overwrite=False) -> str  # L503 — conn.fetchval(...); None → ValueError (duplicate)
    async def get(self, surface_id) L553; async def list_visible(self, scope, *, kind=None) L583; async def delete L686

# packages/ai-parrot-server/src/parrot/handlers/scope.py
VISIBILITY_LEVELS = frozenset({"private", "tenant", "groups"})   # L19 — NO "public"
@dataclass class RequestScope: user_id; tenant; groups: frozenset[str]; is_superuser=False; may_author=True; may_administer=False   # L40-59
def scope_grants(*, tenant, visibility, allowed_groups, scope) -> bool   # L181 — False when scope.tenant or tenant is None or they differ;
                                                                         # True for superuser/administrator, "tenant", or intersecting "groups"

# packages/ai-parrot-server/src/parrot/handlers/models/skills_catalog.py:34-50 — DDL idiom:
#   UNIQUE (tenant, name) + partial unique index WHERE tenant IS NULL + CHECK constraints
```

### Does NOT Exist
- ~~`AbstractPgStore`, a shared `list_visible` helper~~ — copy the idiom, do not invent a base class.
- ~~`"public"` in `VISIBILITY_LEVELS`~~ — `normalize_visibility("public")` returns `"private"`, so global public rows must be selected by SQL (`tenant IS NULL AND visibility = 'public'`), never via `scope_grants`.
- ~~`navigator.metric_definitions`~~ — created by this task.
- ~~`MetricDefinition.owner` being server-enforced~~ — the handler (TASK-4855) sets it; the store persists what it is given.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/models/metric_definitions.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/handlers/test_metric_definitions_store.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/scope.py#RequestScope",
    "sym:packages/ai-parrot-server/src/parrot/handlers/scope.py#scope_grants",
    "sym:packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py#PgUISurfaceStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Use a fresh `AsyncDB("pg")` per call, and `async with await db.connection() as conn`.
- Pass JSONB params as native Python objects. The `ui_surfaces.py:524-534` note explains that `json.dumps` double-encodes them.
- `INSERT … ON CONFLICT DO NOTHING RETURNING metric_id` returns `None` on a duplicate; turn that into `ValueError`.
- Two conflict targets exist (tenant row vs. global row). Use two SQL pairs, chosen by `definition.tenant is None`:
  `ON CONFLICT (tenant, metric_id)` for tenant rows and `ON CONFLICT (metric_id) WHERE tenant IS NULL` for global rows.
- When reading a row, rebuild it with `MetricDefinition.model_validate(row["definition"])`. Tolerate a legacy string payload with `json.loads`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module with DDL, SQL constants and the store class. *Why*: tests match on the module-level SQL constants (fake-DB idiom).
2. Implement `list_visible` as one SQL predicate plus a Python `scope_grants` post-filter for tenant rows. *Why*: `scope_grants` is the single PBAC rule (G2), and `"public"` is not a scope level.
3. Write the tests.

### `packages/ai-parrot-server/src/parrot/handlers/models/metric_definitions.py` (CREATE)
```python
"""Postgres store for FEAT-756 metric definitions (``navigator.metric_definitions``).

Mirrors ``PgUISurfaceStore`` (handlers/models/ui_surfaces.py:457): fresh AsyncDB per call,
idempotent DDL with race tolerance, JSONB params passed as native objects.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from asyncdb import AsyncDB
from parrot.conf import default_dsn
from parrot.handlers.scope import RequestScope, scope_grants
from parrot.metrics import MetricDefinition

logger = logging.getLogger("Parrot.MetricDefinitions.Store")

_DDL_STATEMENTS: list[str] = [
    "CREATE SCHEMA IF NOT EXISTS navigator",
    """CREATE TABLE IF NOT EXISTS navigator.metric_definitions (
        metric_id VARCHAR(63) NOT NULL,
        tenant VARCHAR(63) NULL,
        name TEXT NOT NULL,
        owner VARCHAR NULL,
        visibility VARCHAR(16) NOT NULL DEFAULT 'tenant',
        allowed_groups JSONB NOT NULL DEFAULT '[]'::jsonb,
        global_only BOOLEAN NOT NULL DEFAULT FALSE,
        program VARCHAR NULL,
        definition JSONB NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (tenant, metric_id),
        CHECK (tenant IS NOT NULL OR visibility <> 'tenant')
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS metric_definitions_global_uq ON navigator.metric_definitions (metric_id) WHERE tenant IS NULL",
    "CREATE INDEX IF NOT EXISTS metric_definitions_tenant_vis_idx ON navigator.metric_definitions (tenant, visibility)",
    "CREATE INDEX IF NOT EXISTS metric_definitions_program_idx ON navigator.metric_definitions (program)",
]

# FILL IN: _INSERT_TENANT_SQL / _UPSERT_TENANT_SQL / _INSERT_GLOBAL_SQL / _UPSERT_GLOBAL_SQL
#   (12 params in the column order above; RETURNING metric_id), _GET_TENANT_SQL / _GET_GLOBAL_SQL
#   (`tenant IS NULL` — never `tenant = $2` with NULL), _LIST_*_SQL (+ optional program filter),
#   _DELETE_*_SQL, _LIST_VISIBLE_SQL — bounded by spec §2 "Persisted row" and AC-4.


async def _exec(conn: Any, sql: str, *args: Any) -> None:
    """``conn.execute`` that raises on error instead of returning it (ui_surfaces.py:438 idiom)."""
    result = await conn.execute(sql, *args)
    if isinstance(result, (list, tuple)) and len(result) == 2 and result[1]:
        error = result[1]
        raise error if isinstance(error, Exception) else RuntimeError(str(error))


async def _fetch_rows(conn: Any, sql: str, *args: Any) -> list[Any]:
    """``conn.fetch_all`` with ``None`` normalised to ``[]``."""
    rows = await conn.fetch_all(sql, *args)
    return list(rows) if rows else []


def _row_to_definition(row: Any) -> MetricDefinition:
    """Rebuild a definition from the JSONB ``definition`` column (tolerates a legacy JSON string)."""
    payload = row["definition"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return MetricDefinition.model_validate(payload)


class PgMetricDefinitionStore:
    """Postgres ``MetricStore`` (PgUISurfaceStore idiom — handlers/models/ui_surfaces.py:457)."""

    def __init__(self, dsn: str | None = None) -> None:
        """``dsn`` defaults to ``parrot.conf.default_dsn``."""
        self.dsn = dsn or default_dsn
        self.logger = logger
        self._schema_ensured = False

    def _get_db(self) -> AsyncDB:
        """Fresh ``AsyncDB("pg", dsn=self.dsn)`` per call (ui_surfaces.py:474)."""
        return AsyncDB("pg", dsn=self.dsn)

    async def _ensure_ready(self) -> None:
        if not self._schema_ensured:
            await self.ensure_schema()

    async def ensure_schema(self) -> None:
        """Idempotent DDL; tolerates "already exists" races (ui_surfaces.py:483-501)."""
        db = self._get_db()
        async with await db.connection() as conn:
            for stmt in _DDL_STATEMENTS:
                try:
                    await _exec(conn, stmt)
                except Exception as exc:  # noqa: BLE001
                    if "already exists" in str(exc).lower():
                        self.logger.debug("metric_definitions DDL race tolerated: %s", exc)
                        continue
                    raise
        self._schema_ensured = True

    async def get(self, metric_id: str, *, tenant: str | None) -> MetricDefinition | None:
        """Return one definition in exactly that namespace, or ``None``."""
        # FILL IN: pick _GET_GLOBAL_SQL when tenant is None, else _GET_TENANT_SQL; conn.fetch_one → row or None.

    async def list(self, *, tenant: str | None, program: str | None = None) -> list[MetricDefinition]:
        """Every definition of one namespace (no visibility filtering), ordered by metric_id."""
        # FILL IN: namespace + optional program filter.

    async def save(self, definition: MetricDefinition, *, overwrite: bool = False) -> str:
        """INSERT … ON CONFLICT DO NOTHING / DO UPDATE; returns ``definition.id``; duplicate → ``ValueError``."""
        await self._ensure_ready()
        payload = definition.model_dump(mode="json")  # native dict — NEVER json.dumps (ui_surfaces.py:524-534)
        # FILL IN: choose SQL by (tenant is None, overwrite); conn.fetchval(sql, definition.id, definition.tenant,
        #   definition.name, definition.owner, definition.visibility, definition.allowed_groups, definition.global_only,
        #   definition.program, payload, definition.version, created_at, updated_at); None → ValueError.
        return definition.id

    async def delete(self, metric_id: str, *, tenant: str | None) -> bool:
        """Remove one definition; ``True`` when a row was removed."""
        # FILL IN: DELETE … RETURNING metric_id via fetchval; bool(result).

    async def list_visible(self, scope: RequestScope, *, program: str | None = None) -> list[MetricDefinition]:
        """Global ``public`` rows ∪ ``scope.tenant`` rows the scope grants (owner always; superuser sees all of the tenant)."""
        # FILL IN: SQL selects (tenant IS NULL AND visibility='public') OR tenant = scope.tenant (skip the tenant half when
        #   scope.tenant is None); keep a tenant row when owner == scope.user_id or scope_grants(tenant=row tenant,
        #   visibility=row visibility, allowed_groups=row allowed_groups, scope=scope) — bounded by AC-4 and Does-NOT-Exist ("public").
```
**Why this shape**: it is the `PgUISurfaceStore` idiom copied, not imported (G9). The two conflict targets follow from the
partial unique index on global rows, which `UNIQUE (tenant, metric_id)` cannot enforce because of NULLs.

### `packages/ai-parrot-server/tests/handlers/test_metric_definitions_store.py` (CREATE)
```python
"""Unit + gated live tests for PgMetricDefinitionStore (FEAT-756, TASK-4848)."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from parrot.handlers.models import metric_definitions as m
from parrot.handlers.scope import RequestScope
from parrot.metrics import MetricDefinition

pytestmark = pytest.mark.asyncio
DSN = os.getenv("NAVIGATOR_PG_DSN", "")

# FILL IN: _FakeConnCtx / _FakeAsyncDB / _FakeConn recording (sql, args) and answering fetchval/fetch_one/fetch_all
#   (copy the shape from tests/handlers/test_ui_surfaces_store.py:24-80); monkeypatch PgMetricDefinitionStore._get_db.
# FILL IN: a `_definition(**overrides)` helper building a valid query_slug KPICard MetricDefinition.


async def test_pg_store_sql_shapes() -> None:
    """DDL list run once; native-dict jsonb params; upsert vs insert-or-skip; duplicate → ValueError."""
    # FILL IN


async def test_list_visible_predicate_per_scope() -> None:
    """global public visible to all; tenant rows via owner / scope_grants; other tenant never; scope.tenant None → globals only."""
    # FILL IN


@pytest.mark.skipif(not DSN, reason="NAVIGATOR_PG_DSN not set")
async def test_live_roundtrip() -> None:
    """ensure_schema, save, get, list_visible, delete against real Postgres; clean up own rows only."""
    # FILL IN
```

### FILL IN checklist
- [ ] SQL constants for both namespaces (spec §2 persisted row; global uses `IS NULL`)
- [ ] `get` / `list` / `delete` bodies
- [ ] `save` param tuple and duplicate signal
- [ ] `list_visible` SQL + `scope_grants` filter
- [ ] fake AsyncDB + three tests

---

## Acceptance Criteria

- [ ] `ensure_schema` runs every `_DDL_STATEMENTS` entry idempotently and tolerates "already exists" (AC-4).
- [ ] `save` passes `definition` as a native dict and raises `ValueError` on a duplicate unless `overwrite=True`.
- [ ] `list_visible` returns global public rows plus the scope's tenant rows granted by owner or `scope_grants`, and never another tenant's rows.
- [ ] No diff in `handlers/models/ui_surfaces.py`.
- [ ] `ruff check` is clean on both files.

---

## Validation Commands
- `pytest packages/ai-parrot-server/tests/handlers/test_metric_definitions_store.py -q`

---

## Test Specification

See the blueprint test file: `test_pg_store_sql_shapes`, `test_list_visible_predicate_per_scope`, and `test_live_roundtrip` (skipped without `NAVIGATOR_PG_DSN`).

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug metric-definition-registry --feature-id FEAT-756`).
2. Confirm TASK-4843 is `done` in `sdd/tasks/index/metric-definition-registry.json`.
3. Re-verify the Codebase Contract, then implement from the blueprint and fill every `FILL IN`.
4. Run with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
5. Commit only the listed files, then run `scripts/sdd/close_task.sh TASK-4848 metric-definition-registry verified`.

---

## Completion Note

Native seat opus, 1 attempt. Deviations: (1) group-visibility test dropped because MetricDefinition (TASK-4843) only allows private/tenant/public visibility, so that scope_grants branch via allowed_groups is untested; (2) save() fills created_at/updated_at when empty. Live Postgres round-trip test is skipped without NAVIGATOR_PG_DSN, so the SQL has not run against a real database. The ledger git hook had swept sdd/ledger/events.jsonl into the coder commit; reverted on the attempt branch before merge.
