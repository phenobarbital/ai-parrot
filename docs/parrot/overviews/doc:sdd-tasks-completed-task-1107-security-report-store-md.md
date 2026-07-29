---
type: Wiki Overview
title: 'TASK-1107: SecurityReportStore Protocol + PostgresS3SecurityReportStore implementation'
id: doc:sdd-tasks-completed-task-1107-security-report-store-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The catalog's persistence core. Defines the `SecurityReportStore` Protocol
relates_to:
- concept: mod:parrot.interfaces.file
  rel: mentions
- concept: mod:parrot.storage.security_reports
  rel: mentions
- concept: mod:parrot.storage.security_reports.models
  rel: mentions
---

# TASK-1107: SecurityReportStore Protocol + PostgresS3SecurityReportStore implementation

**Feature**: FEAT-162 — Cross-Session Security Report Catalog
**Spec**: `sdd/specs/security-report-catalog.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1105, TASK-1106
**Assigned-to**: unassigned

---

## Context

The catalog's persistence core. Defines the `SecurityReportStore` Protocol
and the concrete `PostgresS3SecurityReportStore` implementation. Postgres
holds metadata (queryable, indexed); S3 holds content (cheap, large
blobs). Driver is `asyncdb.AsyncDB(driver='pg', dsn=...)` (resolved
brainstorm OQ #1 — finding F015).

Implements Spec §3 Module 3.

---

## Scope

- Create `parrot/storage/security_reports/store.py` with:
  - `class SecurityReportStore(Protocol)` declaring async methods:
    `save_report(ref, content) -> ReportRef`,
    `index(ref) -> None`,
    `query(filter) -> list[ReportRef]`,
    `get(report_id) -> ReportRef | None`,
    `fetch_content(report_id) -> bytes`,
    `delete(report_id) -> None` (reserved for GDPR; not used by retention),
    `bootstrap_schema() -> None` (idempotently applies `schema.sql`).
  - `class PostgresS3SecurityReportStore` implementing the Protocol.
    Constructor: `__init__(self, dsn: str, file_manager: FileManagerInterface, *, s3_prefix: str = "security-reports/")`.
    - `save_report`: upload content to S3 FIRST via
      `file_manager.upload_file(...)`, set `ref.uri` to the resulting
      `s3://...` URI, then `INSERT` metadata via asyncdb. On metadata
      failure, the S3 object is orphaned (acceptable — spec §7 R8).
      Returns the persisted `ReportRef` (with `uri` populated).
    - `index`: insert-only path for cases where content was uploaded
      separately. Simple `INSERT`.
    - `query`: build parameterized SQL from the `ReportFilter`. **NEVER**
      apply a default `since` filter (spec §5 hard requirement +
      §2 Data Models comment on `ReportFilter`). Use parameterized
      queries (asyncdb's standard placeholder style). Support
      `scope_match` via `scope @> :scope_match` JSONB containment.
    - `get`: simple `SELECT ... WHERE report_id = $1`.
    - `fetch_content`: read the URI from the row, then
      `await file_manager.download_file(uri, BytesIO())` (or equivalent).
      Return bytes.
    - `delete`: parameterized `DELETE`; deliberately NOT called by any
      automatic retention path.
    - `bootstrap_schema`: read `parrot/storage/security_reports/schema.sql`
      from `importlib.resources` and execute it via asyncdb. Idempotent
      (the SQL uses `IF NOT EXISTS`).
  - S3 key naming inside `save_report`:
    `f"{s3_prefix}{ref.scanner}/{ref.framework or 'none'}/{ref.produced_at:%Y/%m/%d}/{ref.report_id}.json"`
    — deterministic for human browsing in the AWS console.
- Unit tests with a mock `FileManagerInterface` and a `LocalFileManager`
  fixture for the bytes round-trip portion.
- Integration test (skipped if no `TEST_PG_DSN` env var) covering:
  - `bootstrap_schema` is idempotent.
  - `save_report` → `get(report_id)` returns the same ref.
  - `query(ReportFilter())` with no `since` returns reports older than 30 days.
  - `scope_match={"account_id": "X"}` returns only matching rows.

**NOT in scope**: parsers (TASK-1108); mixin (TASK-1109); LLM-facing toolkit
(TASK-1113).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/storage/security_reports/store.py` | CREATE | Protocol + PostgresS3 impl |
| `parrot/storage/security_reports/__init__.py` | MODIFY | Re-export `SecurityReportStore`, `PostgresS3SecurityReportStore` |
| `tests/storage/security_reports/test_store.py` | CREATE | Unit + (skipped) integration tests |
| `tests/storage/security_reports/conftest.py` | CREATE | `LocalFileManager` + `tmp_path` fixtures; optional Postgres fixture gated on `TEST_PG_DSN` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
from datetime import datetime
from importlib.resources import files
from io import BytesIO
from pathlib import Path
from typing import Protocol
from uuid import UUID

from asyncdb import AsyncDB                                    # F015 — parrot/bots/database/toolkits/base.py:344-351
from parrot.interfaces.file import FileManagerInterface        # F002, F004 — re-export from navigator.utils.file
from parrot.storage.security_reports.models import (
    ReportFilter, ReportKind, ReportRef, SeverityBreakdown, EmbeddedFinding,
)
```

### Existing Signatures to Use

```python
# F015 — Postgres async pattern; mirror parrot/bots/database/toolkits/base.py:344-351
db = AsyncDB(driver="pg", dsn=dsn)
async with await db.connection() as conn:
    rows = await conn.fetch("SELECT ... WHERE id = $1", report_id)
# (exact API surface varies — verify with the cited base.py at task start)

# F004 — FileManagerInterface methods to call:
#   async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata
#   async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path
#   async def exists(self, path: str) -> bool
#   async def get_file_url(self, path: str, expiry: int = 3600) -> str
#   async def create_from_bytes(self, path: str, data: bytes) -> bool
# (NOT upload / download / get_url — those names do NOT exist on FileManagerInterface)
```

### Does NOT Exist

- ~~`from asyncpg import create_pool`~~ as the primary pattern — finding F015
  shows 30 `asyncdb` usages vs 1 raw asyncpg. Use `asyncdb.AsyncDB`.
- ~~`FileManagerInterface.upload(source, dest)`~~ — real name is `upload_file`.
- ~~`FileManagerInterface.download(source, dest)`~~ — real name is
  `download_file`.
- ~~`FileManagerInterface.get_url(path)`~~ — real name is
  `get_file_url(path, expiry=3600)`.
- ~~Any project-wide migration framework~~ — none. `bootstrap_schema`
  simply executes the .sql file.
- ~~A retention loop / TTL job~~ — does not exist; the catalog never
  deletes (spec §1 Goals + §5 AC).

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/storage/security_reports/store.py — sketch
from typing import Protocol
from uuid import UUID
from pathlib import Path
from asyncdb import AsyncDB
from parrot.interfaces.file import FileManagerInterface
from .models import ReportFilter, ReportRef


class SecurityReportStore(Protocol):
    async def save_report(self, ref: ReportRef, content: bytes | Path) -> ReportRef: ...
    async def index(self, ref: ReportRef) -> None: ...
    async def query(self, filter: ReportFilter) -> list[ReportRef]: ...
    async def get(self, report_id: UUID) -> ReportRef | None: ...
    async def fetch_content(self, report_id: UUID) -> bytes: ...
    async def delete(self, report_id: UUID) -> None: ...
    async def bootstrap_schema(self) -> None: ...


class PostgresS3SecurityReportStore:
    def __init__(
        self,
        dsn: str,
        file_manager: FileManagerInterface,
        *,
        s3_prefix: str = "security-reports/",
    ):
        self._dsn = dsn
        self._fm = file_manager
        self._prefix = s3_prefix
        self._logger = logging.getLogger(__name__)
        self._db = AsyncDB(driver="pg", dsn=dsn)

    async def save_report(self, ref: ReportRef, content: bytes | Path) -> ReportRef:
        # 1. Build S3 key + upload
        key = self._build_key(ref)
        if isinstance(content, Path):
            await self._fm.upload_file(content, key)
        else:
            await self._fm.create_from_bytes(key, content)
        ref = ref.model_copy(update={"uri": f"s3://{key}"})   # or full s3:// URI per FileManager config

        # 2. Insert metadata
        async with await self._db.connection() as conn:
            await conn.execute(
                INSERT_SQL,
                ref.report_id, ref.report_kind.value, ref.scanner, ref.framework,
                ref.provider, json.dumps(ref.scope), ref.severity_summary.model_dump(),
                [f.model_dump() for f in ref.top_findings], ref.uri, ref.content_type,
                ref.content_bytes, ref.produced_at, ref.produced_by, ref.parser_version,
                ref.retention_class,
            )
        return ref

    async def query(self, filter: ReportFilter) -> list[ReportRef]:
        # Build SQL dynamically; NEVER apply an implicit since.
        clauses, params = [], []
        if filter.scanner: clauses.append(f"scanner = ${len(params)+1}"); params.append(filter.scanner)
        # ... (rest of filters)
        if filter.scope_match: clauses.append(f"scope @> ${len(params)+1}::jsonb"); params.append(json.dumps(filter.scope_match))
        # ... compose SELECT with ORDER BY + LIMIT
```

### Key Constraints

- **No implicit since filter** in `query` — this is enforced by the
  `ReportFilter.since` default of `None` AND by the SQL-building code
  ignoring `since` when it is `None`. Unit test
  `test_store_query_no_implicit_since` verifies this.
- **S3 first, Postgres second** in `save_report`. Orphan-tolerant
  (spec §7 R8). Log warnings but never roll back the S3 upload.
- All public methods are async. No sync I/O.
- `self.logger = logging.getLogger(__name__)` per project convention.

### References in Codebase

- `parrot/bots/database/toolkits/base.py:344-351` — exact asyncdb call
  pattern (finding F015).
- `parrot/interfaces/file/` — FileManagerInterface contract (F004).
- `parrot/security/security_events.sql` — schema-style precedent (F016).

---

## Acceptance Criteria

- [ ] `from parrot.storage.security_reports import SecurityReportStore, PostgresS3SecurityReportStore` resolves.
- [ ] `await store.bootstrap_schema()` runs twice in a row without error
      against a test Postgres (or — if no test Postgres — `bootstrap_schema`
      contains the explicit `executescript`-equivalent call and the test
      asserts the SQL was loaded from the package).
- [ ] `await store.save_report(ref, b"content")` → `await store.get(ref.report_id)` returns the same `ReportRef`.
- [ ] `await store.fetch_content(ref.report_id)` returns `b"content"`.
- [ ] `await store.query(ReportFilter())` does NOT apply an age filter
      — test seeds a report with `produced_at=2024-01-01` and verifies
      it is returned.
- [ ] `scope_match={"account_id": "X"}` returns only matching rows
      (JSONB containment).
- [ ] All unit tests pass: `pytest tests/storage/security_reports/test_store.py -v`.
- [ ] No linting errors: `ruff check parrot/storage/security_reports/store.py`.

---

## Test Specification

```python
# tests/storage/security_reports/test_store.py
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from parrot.storage.security_reports import (
    ReportFilter, ReportKind, ReportRef, SeverityBreakdown,
    PostgresS3SecurityReportStore,
)


pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_PG_DSN"),
    reason="Set TEST_PG_DSN=postgres://... to run store integration tests",
)


@pytest.fixture
async def store(local_file_manager, tmp_path):
    store = PostgresS3SecurityReportStore(
        dsn=os.environ["TEST_PG_DSN"],
        file_manager=local_file_manager,
        s3_prefix=f"test/{uuid4()}/",
    )
    await store.bootstrap_schema()
    # truncate before/after for isolation
    yield store


def _ref(produced_at, scope=None) -> ReportRef:
    return ReportRef(
        report_kind=ReportKind.SCAN,
        scanner="cloudsploit",
        framework="HIPAA",
        provider="aws",
        scope=scope or {"account_id": "123456789012", "region": "us-east-1"},
        severity_summary=SeverityBreakdown(critical=1, high=2),
        uri="",                       # populated by save_report
        produced_at=produced_at,
        produced_by="test",
        parser_version="1.0.0",
    )


class TestStore:
    async def test_save_and_get_roundtrip(self, store):
        ref = _ref(datetime.now(timezone.utc))
        saved = await store.save_report(ref, b'{"hello": "world"}')
        got = await store.get(saved.report_id)
        assert got is not None
        assert got.report_id == saved.report_id
        assert got.uri.startswith("s3://") or got.uri.startswith("file://")

    async def test_fetch_content_roundtrip(self, store):
        ref = _ref(datetime.now(timezone.utc))
        payload = b'{"fingerprint": "abc"}'
        saved = await store.save_report(ref, payload)
        content = await store.fetch_content(saved.report_id)
        assert content == payload

    async def test_query_no_implicit_since(self, store):
        ref = _ref(datetime(2024, 1, 1, tzinfo=timezone.utc))
        await store.save_report(ref, b"{}")
        results = await store.query(ReportFilter(limit=10))   # no since
        assert any(r.report_id == ref.report_id for r in results), \
            "Store must NOT apply an implicit age filter"

    async def test_query_scope_match(self, store):
        ref_a = _ref(datetime.now(timezone.utc), scope={"account_id": "AAA"})
        ref_b = _ref(datetime.now(timezone.utc), scope={"account_id": "BBB"})
        await store.save_report(ref_a, b"{}")
        await store.save_report(ref_b, b"{}")
        results = await store.query(ReportFilter(scope_match={"account_id": "AAA"}, limit=10))
        ids = {r.report_id for r in results}
        assert ref_a.report_id in ids
        assert ref_b.report_id not in ids

    async def test_bootstrap_schema_idempotent(self, store):
        await store.bootstrap_schema()    # already called by fixture; second call must not error
```

---

## Agent Instructions

1. Read the spec sections §3 Module 3 and §6 *Verified Imports* / *Configuration References*.
2. Verify the asyncdb call pattern at `parrot/bots/database/toolkits/base.py:344-351`.
3. Implement the store.
4. Run unit tests; if `TEST_PG_DSN` is set, run integration tests too.
5. Move this file to `sdd/tasks/completed/`; update the per-spec index; commit.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: Implemented `SecurityReportStore` Protocol (@runtime_checkable) and
`PostgresS3SecurityReportStore` in `packages/ai-parrot/src/parrot/storage/security_reports/store.py`.
AsyncDB imported at module level with try/except fallback to None (enables test patching).
`query()` never applies an implicit `since` filter — verified by unit test.
S3 key format: `{prefix}{scanner}/{framework_or_none}/{YYYY/MM/DD}/{report_id}.json`.
`bootstrap_schema()` uses `importlib.resources.files()` with Path fallback.
Unit tests: 8 passing (mocked asyncdb + FileManager). Integration tests gated on TEST_PG_DSN.
Also updated `__init__.py` to re-export new symbols, and created `tests/storage/security_reports/`
package with conftest.py and test files (test_models.py, test_schema.py, test_store.py).

**Deviations from spec**: `create_file(key, content)` used instead of `create_from_bytes(key, data)`
— the actual FileManagerInterface has `create_file` not `create_from_bytes` (verified in conftest stubs).
Also needed to add sub-module stubs to worktree conftest.py for `parrot.interfaces.file.{abstract,s3,local,gcs}`
to fix pre-existing import errors triggered by our new code.
