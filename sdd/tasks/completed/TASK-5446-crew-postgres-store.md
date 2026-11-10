# TASK-5446: Implement Postgres crew rows, tombstones and migration lock

**Feature**: FEAT-860 — Postgres CrewDefinition Storage
**Spec**: `sdd/specs/postgres-crew-storage.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5443, TASK-5444
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.2 contracts for implement postgres crew rows, tombstones and migration lock.
Spec §§2–5 are authoritative; §6 records baseline source, not old error-policy requirements.
This task is part of the four review resolutions recorded in spec §9.

## Scope

- Implement schema, mutations and row decoding using PgUISurfaceStore adapter rules — execute() cannot be trusted to raise write failures.
- Add typed _load_row_by_id(crew_id, tenant=None) -> CrewStoredRow | None and _list_rows(tenant=None) -> list[CrewStoredRow] — downstream suppression needs both identity indexes.
- Implement load_crew(name, tenant=None), load_crew_by_id(crew_id, tenant=None) -> CrewDefinition | None; list_all_crews() -> list[dict[str,str]]; get_all_crews(tenant=None) -> list[CrewDefinition] — preserve manager-facing shapes.
- Keep driver integrity causes intact; use ValueError for explicit stale-identity conflicts — composition translates errors without a dependency cycle.
- Test typed rows, write failures and lock cleanup — fake tests are complemented by the later live task.

**NOT in scope**: files outside the table; changing CrewDefinition model fields, execution-result storage,
creation.sql, _load_database_bots, dependency manifests or introducing new services.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/crew/postgres_persistence.py` | CREATE | Keep the database adapter independent from the composition to avoid circular exception imports. |
| `packages/ai-parrot-server/tests/unit/test_crew_postgres_store.py` | CREATE | Use per-test fake AsyncDB connections; inspect parameters and error paths rather than implementing a fake SQL parser. |

## Codebase Contract (Anti-Hallucination)

Verified at `0cfa595cb2` on `dev`; re-check after dependencies land.

### Verified Imports

```python
from asyncdb import AsyncDB
from pydantic import BaseModel
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, FlowRelation, ToolNodeDefinition
import pytest
```

Standard-library imports resolve under the project Python runtime; pytest/Pydantic/asyncdb are already declared in workspace pyproject.toml files. Crew model re-exports are verified in handlers/crew/models.py:17–23. Relative imports of new modules in blueprints are dependency contracts below, not claims of pre-existing code.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/models/crew_definition.py#CrewDefinition` — `class CrewDefinition(BaseModel):` (packages/ai-parrot/src/parrot/models/crew_definition.py:178).
- `sym:packages/ai-parrot/src/parrot/models/crew_definition.py#AgentDefinition` — `class AgentDefinition(BaseModel):` (packages/ai-parrot/src/parrot/models/crew_definition.py:31).
- `sym:packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py#PgUISurfaceStore` — `class PgUISurfaceStore:` (packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py:457).

### Dependency Imports and New Symbols

Consumes definition_codec from TASK-5443 and CREW_DEFINITION_PG_DSN from TASK-5444; unit tests use fakes, no shared DDL.

Exact blueprint imports (stdlib/existing references above; new symbols require the named prerequisite):

```python
from .definition_codec import crew_definition_from_dict, crew_definition_to_document
from .models import CrewDefinition
from __future__ import annotations
from asyncdb import AsyncDB
from contextlib import asynccontextmanager
from datetime import datetime
from parrot.conf import CREW_DEFINITION_PG_DSN
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, FlowRelation, ToolNodeDefinition
from parrot.handlers.crew.postgres_persistence import CrewPostgres, CrewStoredRow
from pydantic import BaseModel
from typing import Any, AsyncIterator
import logging
import pytest
```
Blueprint imports from `definition_codec`, `postgres_persistence`, `definition_storage`, and new Redis types are permitted only after their producer task completes; inspect those exact declarations before implementation. New symbols defined by this task are declared in its blueprint.

### Does NOT Exist

- CrewPostgres and CrewStoredRow do not exist before this task.
- No navigator.crew_definitions DDL exists before this feature; never reuse crew_executions.
- Do not import CrewStorageConflict from definition_storage: that would create a circular dependency.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/crew/postgres_persistence.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/test_crew_postgres_store.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/crew_definition.py#CrewDefinition",
    "sym:packages/ai-parrot/src/parrot/models/crew_definition.py#AgentDefinition",
    "sym:packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py#PgUISurfaceStore"
  ]
}
```

## Implementation Notes

Use async I/O, Pydantic v2 models, strict type hints and Google-style docstrings. Format with black (120 columns); lint with ruff. No new dependencies. Logs belong under artifacts/logs/.

## Implementation Blueprint

### Steps (in order)

1. Implement schema, mutations and row decoding using PgUISurfaceStore adapter rules — execute() cannot be trusted to raise write failures.
2. Add typed _load_row_by_id(crew_id, tenant=None) -> CrewStoredRow | None and _list_rows(tenant=None) -> list[CrewStoredRow] — downstream suppression needs both identity indexes.
3. Implement load_crew(name, tenant=None), load_crew_by_id(crew_id, tenant=None) -> CrewDefinition | None; list_all_crews() -> list[dict[str,str]]; get_all_crews(tenant=None) -> list[CrewDefinition] — preserve manager-facing shapes.
4. Keep driver integrity causes intact; use ValueError for explicit stale-identity conflicts — composition translates errors without a dependency cycle.
5. Test typed rows, write failures and lock cleanup — fake tests are complemented by the later live task.

### `packages/ai-parrot-server/src/parrot/handlers/crew/postgres_persistence.py` (CREATE)

```python
"""Durable crew definition rows and deletion tombstones."""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator
from asyncdb import AsyncDB
from pydantic import BaseModel
from parrot.conf import CREW_DEFINITION_PG_DSN
from .models import CrewDefinition
from .definition_codec import crew_definition_from_dict, crew_definition_to_document

TABLE = "navigator.crew_definitions"
MIGRATION_LOCK_KEY = "parrot:crew_definitions:migration"
# FILL IN: _DDL_STATEMENTS from spec section 2, including deleted_at and both constraints.
class CrewStoredRow(BaseModel):
    """Authoritative identity survives malformed definition deserialization."""
    tenant: str
    name: str
    crew_id: str
    definition: dict[str, Any] | str
    deleted_at: datetime | None = None

class CrewPostgres:
    """AsyncDB-backed definitions; errors propagate, None means confirmed absence."""
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or CREW_DEFINITION_PG_DSN
        self.logger = logging.getLogger(__name__)
        self._schema_ensured = False
    @property
    def configured(self) -> bool:
        return bool(self.dsn)
    def _get_db(self) -> AsyncDB:
        return AsyncDB("pg", dsn=self.dsn)
    async def ensure_schema(self) -> None:
        """Apply fixed DDL idempotently; retry on later calls after failure."""
        # FILL IN: AC1; never mark initialized after failed DDL.
        raise NotImplementedError
    async def ping(self) -> bool:
        """Ensure schema then SELECT 1; False on unavailable or missing DSN."""
        # FILL IN: AC1.
        raise NotImplementedError
    async def save_crew(self, crew: CrewDefinition) -> bool:
        """Upsert by name; explicit saves clear tombstones and update UTC time."""
        # FILL IN: AC2.
        raise NotImplementedError
    async def insert_if_absent(self, crew: CrewDefinition) -> bool:
        """Target name conflict only; preserve timestamps and raise on ID collision."""
        # FILL IN: AC3.
        raise NotImplementedError
    async def delete_crew(self, crew: CrewDefinition) -> bool:
        """Atomically create/retain a tombstone, refusing conflicting identities."""
        # FILL IN: AC4; use ValueError for a stale cached identity mismatch.
        raise NotImplementedError
    async def _load_row(self, name: str, tenant: str | None = None) -> CrewStoredRow | None:
        """Include deleted rows and malformed payload identities."""
        # FILL IN: AC5; sibling _load_row_by_id and _list_rows specified below.
        raise NotImplementedError
    async def _load_row_by_id(self, crew_id: str, tenant: str | None = None) -> CrewStoredRow | None:
        """FILL IN AC5: lookup tenant/ID including deleted or malformed rows."""
    async def _list_rows(self, tenant: str | None = None) -> list[CrewStoredRow]:
        """FILL IN AC5: list identities and payloads, retaining tombstones."""
    async def load_crew(self, name: str, tenant: str | None = None) -> CrewDefinition | None:
        """FILL IN AC5: return active validated model, otherwise None."""
    async def load_crew_by_id(self, crew_id: str, tenant: str | None = None) -> CrewDefinition | None:
        """FILL IN AC5: tenant/ID lookup returning only active valid models."""
    async def list_all_crews(self) -> list[dict[str, str]]:
        """FILL IN AC5: list active tenant/name entries across tenants."""
    async def get_all_crews(self, tenant: str | None = None) -> list[CrewDefinition]:
        """FILL IN AC5: decode active models; log malformed rows and skip."""
    @asynccontextmanager
    async def migration_lock(self) -> AsyncIterator[bool]:
        """Try and release the session advisory lock on the same dedicated connection."""
        # FILL IN: AC6, including cancellation-safe release and no DDL for dry runs.
        raise NotImplementedError
        yield False
    async def close(self) -> None:
        """Per-call connections require no persistent close operation."""
```

**Why**: Keep the database adapter independent from the composition to avoid circular exception imports.

### `packages/ai-parrot-server/tests/unit/test_crew_postgres_store.py` (CREATE)

```python
"""FEAT-860 regression tests; use isolated fakes unless explicitly live."""
from __future__ import annotations
import pytest
from parrot.handlers.crew.postgres_persistence import CrewPostgres, CrewStoredRow
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, FlowRelation, ToolNodeDefinition

@pytest.mark.asyncio
async def test_upsert_and_tombstone_identity() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_name_conflict_does_not_swallow_id_conflict() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_malformed_row_reserves_identity() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_lock_release_and_retry_after_failure() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError
```

**Why**: Use per-test fake AsyncDB connections; inspect parameters and error paths rather than implementing a fake SQL parser.

### FILL IN checklist

- [ ] `packages/ai-parrot-server/src/parrot/handlers/crew/postgres_persistence.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] `packages/ai-parrot-server/tests/unit/test_crew_postgres_store.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] Replace all blueprint gaps with complete working code/tests; no placeholders in implementation files.

## Acceptance Criteria

- [ ] AC1: DDL matches spec exactly; schema retry, ping false/no connection without DSN, and per-call connection cleanup work.
- [ ] AC2: Writes use fetchval/RETURNING and dict JSONB; explicit save clears tombstone; UTC timestamps agree with document.
- [ ] AC3: insert_if_absent targets (tenant,name); a different-name ID collision raises and is never returned as False.
- [ ] AC4: Deletion inserts tombstones for Redis-only definitions and atomically checks same-name IDs; repeat deletion is idempotent.
- [ ] AC5: Row APIs retain tombstones/malformed document identity; normal public loads/lists return active valid models only.
- [ ] AC6: Advisory lock uses one session and releases on error/cancellation; acquisition never implicitly creates schema.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_crew_postgres_store.py -q`

## Test Specification

Each test block above is an executor starting point, not an implementation. Build fixtures locally in the declared test files; do not modify shared conftest.py. Assert observable state and error behavior from every acceptance criterion. Avoid network/LLM calls except the explicitly gated live tests in TASK-5451.

## Agent Instructions

Implement in the feature worktree provisioned by sdd-start, never on dev. Check the dependency states
in `sdd/tasks/index/postgres-crew-storage.json` first. Verify source anchors and dependency-created APIs before editing.
Complete only declared files, run narrow validation commands, and commit scoped code. Finalize with
`parrot sdd task finalize` and real TaskCompletionEvidence for the implementation HEAD; do not manually
move the task, stamp completion, or run legacy task-close helpers.

## Completion Note


- Task: TASK-5446
- Feature: postgres-crew-storage
- Implementation SHA: e726435ae87c174b5c1672fe7811461d21746892
- Closed at (UTC): 2026-11-09T21:24:06+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 313.984s · Tokens: n/a |
