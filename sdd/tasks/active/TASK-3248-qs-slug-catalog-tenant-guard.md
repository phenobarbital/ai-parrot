# TASK-3248: SlugCatalog, SlugRecord and TenantGuard over public.queries

**Feature**: FEAT-558 — QuerysourceToolkit — tenant-scoped query-slug and MultiQuery tools
**Spec**: `sdd/specs/querysource-toolkit-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3245, TASK-3246
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (first half). QuerySource does **not** enforce tenancy — `QueryConnection.get_slug(slug, program=)`
ignores `program` (`interfaces/connections.py:494-506`). The toolkit therefore reads the `public.queries` row itself
through `QueryModel` with an explicit per-call connection (design research S1, same pattern as `get_query_slug`,
`connections.py:455-462`), checks `program_slug` against the allowlist **on every call** (S2: no positive
authorisation cache), and performs the gated upsert for `save_multiquery` (S5).

---

## Scope

- Implement `catalog.py`: `SlugRecord` (frozen dataclass), `TenantGuard`, `SlugCatalog` with `open/close/get/get_allowed/list/upsert`.
- Unit tests with fakes for `AsyncDB` and `QueryModel` (patched through `parrot_tools.querysource._qs.QueryModel`).

**NOT in scope**: `normalize_pipeline` / `NormalizedPipeline` (TASK-3249, appended to this file), tool methods (TASK-3251+).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py` | CREATE | record, guard, catalog |
| `packages/ai-parrot-tools/tests/querysource/conftest.py` | CREATE | shared fakes: `FakeAsyncDB`, `FakeQueryModel`, `fake_rows` |
| `packages/ai-parrot-tools/tests/querysource/test_catalog.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from asyncdb import AsyncDB                                   # verified: used at parrot_tools/querytoolkit.py:18 and querysource/interfaces/connections.py:125
from parrot_tools.querysource import _qs                      # TASK-3245 (get_query_model, get_exceptions, default_dsn)
from parrot_tools.querysource.errors import SlugNotFoundError, TenantDeniedError, QuerysourceToolkitError   # TASK-3245
from parrot_tools.querysource.models import SavedSlug         # TASK-3246
```

### Existing Signatures to Use
```python
# querysource/interfaces/connections.py:444-480 (installed 4.5.11) — the read pattern to copy
db = self.get_connection(driver='pg', evt=evt)                # :452 → AsyncDB('pg', dsn=asyncpg_url, ...)  (:113-130)
async with await db.connection() as conn:                     # :459
    return await QueryModel.get(query_slug=slug, _connection=conn)   # :463
except ValidationError as ex: raise SlugNotFound(...)          # :477-480
# asyncdb/models/model.py
async def insert(self, *, _connection=None, **kwargs)         # :124
async def update(self, *, _connection=None, **kwargs)         # :143
@classmethod async def filter(cls, *args, _connection=None, **kwargs)   # :344 → collection (list) of model instances
@classmethod async def get(cls, *, _connection=None, **kwargs)          # :372 → one instance; raises asyncdb NoDataFound when absent
@classmethod async def all(cls, *, _connection=None, **kwargs)          # :402
# querysource/models.py:48-104 — QueryModel columns read here
query_slug 49 · description 50 · conditions 61 · cond_definition 62 · fields 64 · filtering 65 · ordering 66 · grouping 67
query_raw 71 · is_cached 73 · provider 74 · cache_timeout 76 · program_slug 81
# querysource/exceptions.py: SlugNotFound:34 ; asyncdb.exceptions.NoDataFound is what QueryModel.get raises (connections.py:481-489 catches it)
# querysource/queries/multi/__init__.py:171-183 — multi-query detection: json.loads(query_raw) is a dict with 'queries'|'files'|'sources'
```

### Does NOT Exist
- ~~`QueryModel.get(program_slug=..., query_slug=...)` as tenant filter~~ — legal SQL-wise, but the spec requires loading by slug and checking `program_slug` explicitly so the error is `TenantDeniedError`, not "not found".
- ~~`QueryModel.Meta.connection` mutation~~ — forbidden; always pass `_connection=conn` (connections.py:455-458 comment).
- ~~`QueryModel.provider == "multi"`~~ — no such flag; detection is by parsing `query_raw`.
- ~~a TTL cache of slug → program~~ — deliberately absent (S2).
- ~~`AsyncDB.acquire()`~~ — the pattern is `async with await db.connection() as conn`.

---

## Implementation Notes

### Key Constraints
- `SlugCatalog.open()` builds `AsyncDB("pg", dsn=self._dsn)` lazily; `close()` calls `await self._db.close()` if the driver exposes it (guard with `hasattr`), then drops the reference.
- Convert `QueryModel` instances to `SlugRecord` via `getattr(row, name, default)` — rows are datamodel objects, not dicts.
- `upsert`: `get` existing → if found and `not overwrite` → error; if found and `existing.program_slug != program_slug` → error even with overwrite (S5); else `setattr` + `update(_connection=conn)`; if not found → `QueryModel(query_slug=…, description=…, query_raw=json.dumps(pipeline), program_slug=…, is_cached=False).insert(_connection=conn)`.
- Log at `debug` on each read, `info` on upsert, with `%s` formatting.

### References in Codebase
- `querysource/interfaces/connections.py:444-506` — per-call connection read
- `querysource/handlers/manager.py:461-520` — upsert semantics (update-or-insert by `query_slug`)

---

## Implementation Blueprint

### Steps (in order)
1. Write `catalog.py` block below — *why*: mirrors querysource's own read path so connection ownership is explicit (S1).
2. Complete the `FILL IN` markers (row → record mapping, list filtering, upsert branches).
3. Write `conftest.py` fakes and tests; assert `QueryModel.get` is called on every `get_allowed()`.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py` (CREATE)
```python
"""Slug catalog over public.queries with explicit tenant checks (spec §3 M4)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from asyncdb import AsyncDB  # verified: parrot_tools/querytoolkit.py:18

from parrot_tools.querysource import _qs
from parrot_tools.querysource.errors import QuerysourceToolkitError, SlugNotFoundError, TenantDeniedError
from parrot_tools.querysource.models import SavedSlug

logger = logging.getLogger(__name__)
_PIPELINE_KEYS = ("queries", "files", "sources")  # multi/__init__.py:182-183


@dataclass(frozen=True)
class SlugRecord:
    """Redacted view of one public.queries row (never source/params/attributes/dwh_*/cache_options)."""
    slug: str
    program_slug: str
    description: str | None
    provider: str
    is_cached: bool
    cache_timeout: int
    conditions: dict[str, Any] = field(default_factory=dict)
    cond_definition: dict[str, Any] = field(default_factory=dict)
    filtering: dict[str, Any] = field(default_factory=dict)
    fields: list[str] = field(default_factory=list)
    ordering: list[str] = field(default_factory=list)
    grouping: list[str] = field(default_factory=list)
    query_raw: str | None = None
    pipeline: dict[str, Any] | None = None

    @property
    def is_multiquery(self) -> bool:
        """True when query_raw parsed to a dict holding queries|files|sources."""
        return self.pipeline is not None

    @property
    def placeholder_names(self) -> list[str]:
        """keys(cond_definition) ∪ keys(conditions), sorted."""
        return sorted(set(self.cond_definition) | set(self.conditions))

    @classmethod
    def from_row(cls, row: Any) -> "SlugRecord":
        """Build from a QueryModel instance (attribute access; columns verified models.py:49-81)."""
        raw = getattr(row, "query_raw", None)
        pipeline = None
        if isinstance(raw, str) and raw.lstrip().startswith("{"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and any(k in parsed for k in _PIPELINE_KEYS):
                    pipeline = parsed
            except ValueError:
                pipeline = None
        # FILL IN: map remaining columns with getattr(row, <col>, <default>) — bounded by models.py:49-81 names above
        return cls(slug=row.query_slug, program_slug=getattr(row, "program_slug", "default"), description=None,
                   provider=getattr(row, "provider", "db"), is_cached=bool(getattr(row, "is_cached", True)),
                   cache_timeout=int(getattr(row, "cache_timeout", 3600) or 0), query_raw=raw, pipeline=pipeline)


class TenantGuard:
    """Allowlist of program_slug values; None means unrestricted (proposal U4)."""

    def __init__(self, programs: list[str] | None) -> None:
        self.programs: tuple[str, ...] | None = tuple(programs) if programs is not None else None

    @property
    def restricted(self) -> bool:
        return self.programs is not None

    def assert_allowed(self, record: SlugRecord) -> None:
        """Raise TenantDeniedError when restricted and record.program_slug ∉ programs."""
        if self.restricted and record.program_slug not in self.programs:
            raise TenantDeniedError(f"slug '{record.slug}' is not available for programs {list(self.programs)}")

    def resolve_write_program(self, requested: str | None) -> str:
        """Program a save must use (S5): explicit ∈ allowlist; single-program default; else error."""
        # FILL IN: restricted+requested→must be in programs; restricted+None+len==1→that one; unrestricted+None→error;
        #          unrestricted+requested→requested — bounded by spec §3 M4 TenantGuard docstring
        raise QuerysourceToolkitError("program is required")
```
(continued — same file)
```python
class SlugCatalog:
    """Reads/writes public.queries through QueryModel with a per-call connection (S1); no auth cache (S2)."""

    def __init__(self, dsn: str, guard: TenantGuard) -> None:
        self._dsn = dsn
        self.guard = guard
        self._db: AsyncDB | None = None

    async def open(self) -> None:
        """Create the AsyncDB('pg') factory lazily (pattern: connections.py:113-130)."""
        if self._db is None:
            self._db = AsyncDB("pg", dsn=self._dsn)

    async def close(self) -> None:
        if self._db is not None and hasattr(self._db, "close"):
            await self._db.close()
        self._db = None

    async def get(self, slug: str) -> SlugRecord:
        """Load one row; SlugNotFoundError when absent. Always hits the DB (S2)."""
        await self.open()
        model = _qs.get_query_model()
        logger.debug("catalog.get %s", slug)
        async with await self._db.connection() as conn:  # connections.py:459
            try:
                row = await model.get(query_slug=slug, _connection=conn)  # connections.py:463
            except Exception as exc:  # asyncdb NoDataFound / querysource SlugNotFound — FILL IN: narrow to those two types
                raise SlugNotFoundError(f"slug '{slug}' not found") from exc
        return SlugRecord.from_row(row)

    async def get_allowed(self, slug: str) -> SlugRecord:
        """get() then guard.assert_allowed()."""
        record = await self.get(slug)
        self.guard.assert_allowed(record)
        return record

    async def list(self, *, search: str | None, program: str | None, limit: int) -> list[SlugRecord]:
        """QueryModel.filter(program_slug=p) per allowed program (or all() when unrestricted and program is None)."""
        await self.open()
        model = _qs.get_query_model()
        async with await self._db.connection() as conn:
            # FILL IN: choose programs = [program] if given (must be allowed when restricted, else TenantDeniedError),
            #          else guard.programs, else None → model.all(_connection=conn); collect rows via model.filter(...)
            rows: list[Any] = []
        records = [SlugRecord.from_row(r) for r in rows]
        if search:
            needle = search.lower()
            records = [r for r in records if needle in r.slug.lower() or needle in (r.description or "").lower()]
        return sorted(records, key=lambda r: r.slug)[:limit]

    async def upsert(self, *, slug: str, description: str, pipeline: dict[str, Any], program_slug: str,
                     overwrite: bool) -> SavedSlug:
        """Insert or (guarded) update a multi-query row: query_raw=json, is_cached=False (S5 ownership check)."""
        await self.open()
        model = _qs.get_query_model()
        async with await self._db.connection() as conn:
            # FILL IN: existing = model.get(...) or None; found & not overwrite → error; found & program mismatch → error;
            #          found → setattr(query_raw/description) + update(_connection=conn) → 'updated';
            #          absent → model(query_slug=slug, description=description, query_raw=json.dumps(pipeline),
            #                       program_slug=program_slug, is_cached=False).insert(_connection=conn) → 'inserted'
            action = "inserted"
        logger.info("catalog.upsert %s (%s) program=%s", slug, action, program_slug)
        return SavedSlug(slug=slug, program_slug=program_slug, action=action)
```
**Why this shape**: `get()` is the single authorisation read and is never cached (S2); `list()` filters server-side
by program so a restricted instance never sees foreign rows; `upsert()` refuses cross-program overwrites (S5).

### FILL IN checklist
- [ ] `catalog.py::SlugRecord.from_row` — remaining column mapping; bounded by models.py:49-81
- [ ] `catalog.py::TenantGuard.resolve_write_program` — four branches; bounded by spec §3 M4 docstring
- [ ] `catalog.py::SlugCatalog.get` — narrow the except to asyncdb `NoDataFound` and querysource `SlugNotFound` (via `_qs.get_exceptions()`)
- [ ] `catalog.py::SlugCatalog.list` — program selection + `filter`/`all`; bounded by AC "list_slugs returns only allowed rows"
- [ ] `catalog.py::SlugCatalog.upsert` — branches; bounded by S5

---

## Acceptance Criteria

- [ ] `TenantGuard(["pokemon"]).assert_allowed(record(program="epson"))` raises `TenantDeniedError`; `TenantGuard(None)` never raises.
- [ ] `SlugCatalog.get` passes the context-managed connection as `_connection=`; two `get_allowed()` calls perform two `QueryModel.get` calls.
- [ ] `SlugRecord.from_row` marks a row whose `query_raw` is the proposal's pipeline JSON as `is_multiquery=True` with `pipeline` populated; plain SQL → `False`.
- [ ] `upsert(overwrite=True)` on a slug owned by another program raises; on the same program updates; absent slug inserts with `is_cached=False`, `query_raw=json.dumps(pipeline)`.
- [ ] `pytest packages/ai-parrot-tools/tests/querysource/test_catalog.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/querysource/conftest.py
import json, pytest
from types import SimpleNamespace
from parrot_tools.querysource import _qs

PIPELINE = {"queries": {"a": {"slug": "pokemon_all_fso_odoo_new"}, "b": {"slug": "pokemon_warehouses_kiosk_all_fso"}},
            "Join": [{"type": "left", "left": "a", "right": "b", "using": ["warehouse_alias"]}],
            "Output": [{"tableOutput": {"flavor": "postgresql", "tablename": "t", "schema": "pokemon"}}]}

@pytest.fixture
def fake_rows():
    return {
        "epson_field_activity": SimpleNamespace(query_slug="epson_field_activity", program_slug="epson", description="Field activity",
            provider="db", is_cached=True, cache_timeout=3600, conditions={"firstdate": "2026-01-01", "lastdate": "2026-01-31"},
            cond_definition={"firstdate": "date", "lastdate": "date"}, filtering={}, fields=[], ordering=[], grouping=[],
            query_raw="SELECT * FROM epson.activity WHERE d BETWEEN {firstdate} AND {lastdate} {where_cond}"),
        "pokemon_all_fso_odoo_new": SimpleNamespace(query_slug="pokemon_all_fso_odoo_new", program_slug="pokemon", description=None,
            provider="db", is_cached=False, cache_timeout=0, conditions={}, cond_definition={}, filtering={}, fields=[], ordering=[],
            grouping=[], query_raw=json.dumps(PIPELINE)),
    }

class FakeConn:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

class FakeAsyncDB:
    def __init__(self, *a, **k): self.closed = False
    async def connection(self): return FakeConn()
    async def close(self): self.closed = True

@pytest.fixture
def patched_qs(monkeypatch, fake_rows):
    calls = {"get": [], "filter": [], "insert": [], "update": []}
    class NoData(Exception): pass
    class FakeQueryModel:
        def __init__(self, **kw): self.__dict__.update(kw)
        @classmethod
        async def get(cls, *, _connection=None, **kw):
            calls["get"].append((kw, _connection)); row = fake_rows.get(kw["query_slug"])
            if row is None: raise NoData(kw["query_slug"])
            return row
        @classmethod
        async def filter(cls, *a, _connection=None, **kw):
            calls["filter"].append(kw); return [r for r in fake_rows.values() if r.program_slug == kw.get("program_slug")]
        @classmethod
        async def all(cls, *, _connection=None, **kw): return list(fake_rows.values())
        async def insert(self, *, _connection=None, **kw): calls["insert"].append(self.__dict__); return self
        async def update(self, *, _connection=None, **kw): calls["update"].append(self.__dict__); return self
    monkeypatch.setattr(_qs, "QueryModel", FakeQueryModel)
    monkeypatch.setattr("parrot_tools.querysource.catalog.AsyncDB", FakeAsyncDB)
    return calls
```
```python
# packages/ai-parrot-tools/tests/querysource/test_catalog.py
import pytest
from parrot_tools.querysource.catalog import SlugCatalog, TenantGuard, SlugRecord
from parrot_tools.querysource.errors import TenantDeniedError, SlugNotFoundError, QuerysourceToolkitError

async def test_get_uses_per_call_connection_and_no_cache(patched_qs):
    cat = SlugCatalog("postgres://fake", TenantGuard(["epson"]))
    await cat.get_allowed("epson_field_activity"); await cat.get_allowed("epson_field_activity")
    assert len(patched_qs["get"]) == 2 and all(conn is not None for _, conn in patched_qs["get"])

async def test_tenant_denied_and_not_found(patched_qs):
    cat = SlugCatalog("postgres://fake", TenantGuard(["pokemon"]))
    with pytest.raises(TenantDeniedError): await cat.get_allowed("epson_field_activity")
    with pytest.raises(SlugNotFoundError): await cat.get("nope")

async def test_multiquery_detection(patched_qs, fake_rows):
    assert SlugRecord.from_row(fake_rows["pokemon_all_fso_odoo_new"]).is_multiquery
    rec = SlugRecord.from_row(fake_rows["epson_field_activity"])
    assert not rec.is_multiquery and rec.placeholder_names == ["firstdate", "lastdate"]

async def test_list_restricted(patched_qs):
    cat = SlugCatalog("postgres://fake", TenantGuard(["pokemon"]))
    assert [r.slug for r in await cat.list(search=None, program=None, limit=10)] == ["pokemon_all_fso_odoo_new"]

async def test_upsert_cross_program_refused(patched_qs):
    cat = SlugCatalog("postgres://fake", TenantGuard(None))
    with pytest.raises(QuerysourceToolkitError):
        await cat.upsert(slug="epson_field_activity", description="x", pipeline={"queries": {}}, program_slug="pokemon", overwrite=True)
    saved = await cat.upsert(slug="new_mq", description="x", pipeline={"queries": {}}, program_slug="pokemon", overwrite=False)
    assert saved.action == "inserted" and patched_qs["insert"][0]["is_cached"] is False
```

---

## Agent Instructions

1. Read spec §3 Module 4, §6 (QueryModel, asyncdb, connections anchors), §7 Patterns.
2. Verify TASK-3245/3246 completed; re-check `grep -n "async def get_query_slug" .venv/lib/python3.12/site-packages/querysource/interfaces/connections.py`.
3. Update index → `in-progress`; implement; tests; `ruff`.
4. Move this file to `sdd/tasks/completed/`, update index → `done`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
