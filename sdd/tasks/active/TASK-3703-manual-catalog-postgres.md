# TASK-3703: PostgresManualCatalog with configurable FTS regconfig (M4)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3702
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 4** (Postgres backend) and §7 Risks ("FTS regconfig — English-only in contracts; `search_regconfig` is
validated as an identifier and defaults to `english`; Spanish corpora set `spanish` per tenant"). This is the production
`ManualCatalogStore`: a per-tenant schema with a jsonb card column, denormalized search columns, a **generated tsvector
using the configured regconfig**, a `FOR UPDATE` revision check, sha/URI clash detection, immutable version history, answer
audit rows and the publication outbox — copying `contracts/catalog_postgres.py` minus parties/deltas/relations.

Parallelism: subclasses `ManualCatalogStore` and reuses `SearchHit`/`UpsertResult`/`AnswerRecord` from TASK-3702
(manuals/catalog.py).

---

## Scope

- Create `parrot/knowledge/manuals/catalog_postgres.py`: `MANUALS_DDL` (tuple of statement templates using `{schema}` and
  `{regconfig}` — both validated identifiers), `MAX_SEARCH_TOP_K`, `MAX_QUEUE_LIMIT`, `PostgresManualCatalog`.
- Tables: `manuals` (card_json jsonb, manual_id PK, title/equipment_text/procedure_text/caption_text/toc_digest denormalized,
  verification, revision, source_uri unique, source_sha256 unique-when-nonempty, active, added_at, updated_at,
  `search_vector` GENERATED from `{regconfig}`), `manual_versions`, `answers`, `publication_outbox`.
- `search()` ranks with `plainto_tsquery('{regconfig}', $1)` / `ts_rank` and reports `matched` by which denormalized column hit.
- `verification_queue()` loads active cards and applies the shared `queue_entries_for` (never re-implements the rules in SQL).
- Tests with a fake asyncpg pool (DDL text, identifier validation, bound parameters) + one live test skipped without
  `GRAPHINDEX_PG_DSN`.

**NOT in scope**: the ABC or its models (TASK-3702); schema migration when a tenant changes regconfig (documented limitation:
the generated column is fixed at creation — `setup()` logs a warning if the stored expression differs); the broader live suite
(TASK-3730).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/manuals/catalog_postgres.py` | CREATE | Postgres backend with configurable regconfig |
| `packages/ai-parrot/tests/knowledge/manuals/test_catalog_postgres.py` | CREATE | DDL/regconfig unit tests (fake pool) + skipped live test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.manuals.catalog import (ManualCatalogStore, SearchHit, UpsertResult, VerificationQueueEntry,
    AnswerRecord, PublicationRecord, CatalogConflictError, DuplicateSourceError, validate_identifier, queue_entries_for)   # TASK-3702
from parrot.knowledge.manuals.models import ManualCard, ManualVersion, manual_snapshot_payload                          # TASK-3699
import json, logging, uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Optional
if TYPE_CHECKING:
    import asyncpg        # imported lazily at runtime (catalog_postgres.py:58-59 precedent)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/contracts/catalog_postgres.py  (template — copy, never import)
MAX_SEARCH_TOP_K = 50 :77; MAX_QUEUE_LIMIT = 500 :78; LOW_CONFIDENCE_THRESHOLD = 0.6 :74
CONTRACTS_DDL: tuple[str, ...] = (...)       # :82-268 — "{schema}" templated; generated tsvector hard-codes 'english' at :107-113
def _utcnow() -> datetime                    # :271-273
class PostgresContractCatalog(ContractCatalogStore):   # :276 (spec cited :294, which is __init__)
    def __init__(self, dsn=None, *, pool=None, tenant_id, schema="contracts", principal=None, now=_utcnow)   # :294-316 — ValueError without dsn AND pool (no default DSN)
    async def _ensure_pool(self) -> asyncpg.Pool   # :320-336 lazy asyncpg import; RuntimeError install hint 'ai-parrot[graphindex-postgres]'
    async def setup(self) -> None                  # :338-345 executes each DDL statement .format(schema=…)
    async def close(self) -> None                  # :347-352 closes only an owned pool
    async def _connection(self)                    # :354-364 nullcontext(publication conn) or pool.acquire(); setup on first use
    async def upsert(...)                          # :531 — SELECT revision … FOR UPDATE (:546); DuplicateSourceError (:566, :651)
    async def search(self, query, top_k=8)         # :914-944 blank ⇒ []; bounded top_k; plainto_tsquery('english', $1); ORDER BY rank DESC, id
    async def verification_queue(self, *, limit=50)  # :998-1060
    async def record_answer(self, record)          # :1327
# packages/ai-parrot/tests/knowledge/contracts/conftest.py  (live-gate pattern)
PG_DSN = os.environ.get("GRAPHINDEX_PG_DSN") :30; requires_pg skipif marker :35; pg_pool fixture :229-240; temp_schema fixture :243-251
```

### Does NOT Exist
- ~~A default DSN fallback~~ — explicit `dsn` or injected `pool` only (contracts :305-309).
- ~~Binding the regconfig into the generated column~~ — a generated column needs a literal; it is interpolated **only** after
  `validate_identifier` (done in the ABC constructor, TASK-3702). User/model values are always bound parameters.
- ~~Party/alias/delta/relation/obligation tables~~ — not part of the manuals catalog.
- ~~`manuals` conftest pg fixtures~~ — TASK-3698 created none; define the pool fixture inside the test module.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/manuals/catalog_postgres.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_catalog_postgres.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/catalog_postgres.py#PostgresContractCatalog",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/catalog_postgres.py#PostgresContractCatalog.search",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/catalog_postgres.py#PostgresContractCatalog.upsert"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Only configuration is interpolated**: `{schema}` and `{regconfig}` (both validated). Queries, ids, card JSON — always `$n` params.
- `upsert` in **one transaction**: `SELECT revision … FOR UPDATE`; compare `expected_revision`; check sha/URI owned by a different
  `manual_id` ⇒ `DuplicateSourceError`; upsert row with denormalized text (title = equipment models + procedure titles;
  `caption_text` = figure captions); insert `manual_versions` row (never updated); insert outbox row idempotently on its key
  (`ON CONFLICT DO NOTHING`); return `UpsertResult` with the queued row.
- `record_answer` must raise on failure — the service (TASK-3723) relies on "audit before release; failed audit ⇒ no release".
- `claim_publication` uses `FOR UPDATE SKIP LOCKED` like contracts (:1712-1730).
- Denormalized text columns keep FTS language-agnostic: the regconfig only changes stemming/stopwords.
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src`; asyncpg is
  optional — unit tests use a fake pool/connection that records `execute`/`fetch` SQL + args.

---

## Implementation Blueprint

### Steps (in order)
1. Write `MANUALS_DDL` with `{schema}`/`{regconfig}` placeholders — *why*: one idempotent schema per tenant.
2. Copy pool/setup/close/_connection from contracts — *why*: identical lifecycle semantics (owned vs injected pool).
3. Implement card, version, search, queue, audit and outbox methods — *why*: complete the ABC.
4. Write fake-pool unit tests and the gated live test.

### `packages/ai-parrot/src/parrot/knowledge/manuals/catalog_postgres.py` (CREATE)
```python
"""Postgres manual catalog (FEAT-601 M4) — per-tenant schema, jsonb cards, configurable FTS regconfig.

``asyncpg`` is imported lazily so importing ``parrot.knowledge.manuals`` needs no driver.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Optional

from parrot.knowledge.manuals.catalog import (AnswerRecord, CatalogConflictError, DuplicateSourceError, ManualCatalogStore,
                                              PublicationRecord, SearchHit, UpsertResult, VerificationQueueEntry,
                                              queue_entries_for)
from parrot.knowledge.manuals.models import ManualCard, ManualVersion, manual_snapshot_payload

if TYPE_CHECKING:
    import asyncpg

__all__ = ("PostgresManualCatalog", "MANUALS_DDL", "MAX_SEARCH_TOP_K", "MAX_QUEUE_LIMIT")

logger = logging.getLogger(__name__)
MAX_SEARCH_TOP_K = 50
MAX_QUEUE_LIMIT = 500

#: ``{schema}`` and ``{regconfig}`` are validated identifiers; nothing else is ever interpolated.
MANUALS_DDL: tuple[str, ...] = (
    "CREATE SCHEMA IF NOT EXISTS {schema}",
    """
    CREATE TABLE IF NOT EXISTS {schema}.manuals (
        manual_id       text PRIMARY KEY,
        card_json       jsonb NOT NULL,
        title           text NOT NULL DEFAULT '',
        equipment_text  text NOT NULL DEFAULT '',
        procedure_text  text NOT NULL DEFAULT '',
        caption_text    text NOT NULL DEFAULT '',
        toc_digest      text NOT NULL DEFAULT '',
        verification    text NOT NULL DEFAULT 'extracted',
        source_uri      text,
        source_sha256   text NOT NULL DEFAULT '',
        active          boolean NOT NULL DEFAULT true,
        revision        integer NOT NULL DEFAULT 1,
        added_at        timestamptz,
        updated_at      timestamptz,
        search_vector   tsvector GENERATED ALWAYS AS (
            to_tsvector('{regconfig}', coalesce(title, '') || ' ' || coalesce(equipment_text, '') || ' '
                || coalesce(procedure_text, '') || ' ' || coalesce(caption_text, '') || ' ' || coalesce(toc_digest, ''))
        ) STORED
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS manuals_source_uri_key ON {schema}.manuals (source_uri) WHERE source_uri IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS manuals_source_sha_key ON {schema}.manuals (source_sha256) WHERE source_sha256 <> ''",
    "CREATE INDEX IF NOT EXISTS manuals_search_idx ON {schema}.manuals USING GIN (search_vector)",
    # FILL IN: manual_versions (manual_id, n, revision, valid_from, valid_to, source_sha256, card_snapshot jsonb, recorded_at,
    #   evidence_ref, PK (manual_id, n)); answers (answer_id PK, asked_at, user_id, record_json jsonb);
    #   publication_outbox (tenant_id, manual_id, version_n, revision, target, run_id, payload jsonb, state, receipt, attempts,
    #   last_error, created_at, updated_at, PK (tenant_id, manual_id, version_n, revision, target)) — mirror contracts DDL shapes
)


def _utcnow() -> datetime:
    """Return the current UTC time (injectable for frozen-clock tests)."""
    return datetime.now(tz=timezone.utc)


class PostgresManualCatalog(ManualCatalogStore):
    """The production ManualCatalogStore backend."""

    def __init__(self, dsn: Optional[str] = None, *, pool: Any = None, tenant_id: str, schema: str = "manuals",
                 principal: Optional[str] = None, search_regconfig: str = "english",
                 now: Callable[[], datetime] = _utcnow) -> None:
        super().__init__(tenant_id=tenant_id, schema=schema, principal=principal, search_regconfig=search_regconfig)
        if dsn is None and pool is None:
            raise ValueError("PostgresManualCatalog requires an explicit dsn or an injected asyncpg pool; "
                             "there is no default DSN fallback.")
        self._dsn = dsn
        self._external_pool = pool
        self._pool: Any = pool
        self._owns_pool = pool is None
        self._now = now
        self._ready = False

    def ddl(self) -> list[str]:
        """The rendered DDL for this tenant (schema + regconfig interpolated)."""
        return [statement.format(schema=self.schema, regconfig=self.search_regconfig) for statement in MANUALS_DDL]

    # FILL IN: _ensure_pool / setup (execute self.ddl()) / close / _connection — copy contracts :320-364
    #   (install hint: `pip install 'ai-parrot[graphindex-postgres]'`)
    # FILL IN: upsert (single transaction, FOR UPDATE, clash checks, versions + outbox) — AC contract per TASK-3702 suite
    # FILL IN: get / find_by_sha / find_by_source_uri / list_cards / versions
    # FILL IN: search — blank ⇒ []; bounded top_k (1..MAX_SEARCH_TOP_K); plainto_tsquery('{regconfig}', $1) with regconfig
    #   formatted from self.search_regconfig; ORDER BY rank DESC, manual_id; matched = first denormalized column containing a query token
    # FILL IN: verification_queue — active cards → queue_entries_for → sort (priority, manual_id) → limit ≤ MAX_QUEUE_LIMIT
    # FILL IN: record_answer (raise on failure) / get_answer / outbox methods (claim with FOR UPDATE SKIP LOCKED)
```
**Why**: the regconfig is the one deliberate divergence from contracts (spec §7); everything else is a straight port so the
TASK-3702 contract suite semantics hold on Postgres.

### FILL IN checklist
- [ ] remaining DDL statements
- [ ] pool lifecycle
- [ ] `upsert` transaction
- [ ] read methods, `search`, `verification_queue`
- [ ] audit + outbox
- [ ] tests below

---

## Acceptance Criteria

- [ ] `PostgresManualCatalog(tenant_id="t1")` without dsn/pool ⇒ `ValueError`
- [ ] `ddl()` contains `to_tsvector('spanish'` when `search_regconfig="spanish"`; an invalid regconfig is rejected at construction
- [ ] No user/model value is interpolated into SQL (fake pool asserts args are bound)
- [ ] Live test (with `GRAPHINDEX_PG_DSN`): upsert → search → queue round-trips; skipped cleanly otherwise (AC19)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/manuals/test_catalog_postgres.py -q`
- `pytest packages/ai-parrot/tests/knowledge/manuals/test_catalog_contract.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/manuals/test_catalog_postgres.py
import os

import pytest

from parrot.knowledge.manuals.catalog_postgres import PostgresManualCatalog

PG_DSN = os.environ.get("GRAPHINDEX_PG_DSN")
requires_pg = pytest.mark.skipif(not PG_DSN, reason="live Postgres suites require an explicit GRAPHINDEX_PG_DSN")


class FakeConnection:
    """Records every execute/fetch/fetchrow call (sql, args)."""


class FakePool:
    """acquire() async-context yielding FakeConnection."""


def test_requires_dsn_or_pool():
    with pytest.raises(ValueError):
        PostgresManualCatalog(tenant_id="t1")


def test_postgres_catalog_regconfig():
    catalog = PostgresManualCatalog(pool=FakePool(), tenant_id="t1", search_regconfig="spanish")
    assert any("to_tsvector('spanish'" in statement for statement in catalog.ddl())
    with pytest.raises(ValueError):
        PostgresManualCatalog(pool=FakePool(), tenant_id="t1", search_regconfig="spanish'); drop")


async def test_search_binds_query_parameter():
    ...


async def test_record_answer_failure_raises():
    ...


@requires_pg
async def test_live_upsert_search_queue():
    ...
```

---

## Agent Instructions

1. Read spec §3 Module 4 and §7 Risks (FTS regconfig).
2. Confirm TASK-3702 is done; re-verify the contracts Postgres anchors.
3. Update the per-spec index status → `in-progress`.
4. Implement from the blueprint; complete every `# FILL IN:`.
5. Run the Validation Commands with the worktree `PYTHONPATH`.
6. Move this file to `sdd/tasks/completed/`, update the index → `done`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
