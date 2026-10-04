# TASK-3783: SlugCatalog tenant-aware over QuerySource's DefinitionRepository

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3782
**Assigned-to**: unassigned

---

## Context

FEAT-558's `SlugCatalog` reads `public.queries` through `QueryModel` only (`catalog.py:131-192`), so a slug that
lives in a QuerySource 5.1.1 **tenant store** (FEAT-147) is invisible to the toolkit. Linked-surface descriptors
carry `tenant: str | null` per source (spec G8, AC4), so the toolkit gate (`get_allowed(slug, tenant=)`) must
resolve `(tenant, slug)` exactly as QuerySource does: `store = registry.resolve(tenant)`,
`repo.get(QueryIdentity(store, slug))` (spec §3 M7, AC6). The `programs` allowlist (`TenantGuard`) applies
**unchanged** — for tenant stores the runtime `program_slug` equals the store schema
(`repositories/definitions.py:111-119`).

Implements spec §3 Module 7 (catalog half). The toolkit methods that pass `tenant=` are TASK-3784.

---

## Scope

- Add keyword-only `tenant: str | None = None` to `SlugCatalog.get`, `SlugCatalog.get_allowed`, `SlugCatalog.list`.
- `tenant is None` → the existing `QueryModel` path, byte-for-byte unchanged (AC4: a `null` tenant runs against
  `public`; existing FEAT-558 tests must stay green).
- `tenant` set → resolve through `DefinitionRepository` obtained via `_qs.get_definition_repository()` (TASK-3782):
  `get`: `repo.registry.resolve(tenant)` → `await repo.get(QueryIdentity(store=store, slug=slug))` →
  `SlugRecord.from_row(definition.runtime)`; `list`: `await repo.list(store, params)` over `DefinitionPage.rows`.
- Map `TenantError.error_code`: `query_not_found` / `tenant_not_available` → `SlugNotFoundError`;
  `invalid_tenant` → `InvalidConditionsError`; `tenant_store_unavailable` (and any other code) →
  `QuerysourceToolkitError` (propagate with `from exc`).
- Tests with a fake repository asserting `QueryIdentity(store, slug)` and `program_slug == schema`.

**NOT in scope**: toolkit method signatures (TASK-3784); `_qs.py` changes (done in TASK-3782); tenant discovery /
membership (spec Non-Goals — none exist in QuerySource 5.1.1); `upsert`/`list_programs` (stay public-only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py` | MODIFY | tenant-aware `get` / `get_allowed` / `list` |
| `packages/ai-parrot-tools/tests/querysource/test_catalog_tenant.py` | CREATE | tenant catalog tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.querysource import _qs                      # catalog.py:13 (already imported)
from parrot_tools.querysource.errors import (                 # catalog.py:14-19 (already imported)
    InvalidConditionsError, QuerysourceToolkitError, SlugNotFoundError, TenantDeniedError,
)
from parrot_tools.querysource.catalog import SlugCatalog, SlugRecord, TenantGuard   # catalog.py:131, :39, :97
# via TASK-3782 (lazy, never module-level):
#   _qs.get_tenants()               -> module querysource.tenants (QueryIdentity, TenantError)
#   await _qs.get_definition_repository() -> DefinitionRepository
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py
@dataclass(frozen=True)
class SlugRecord:                                     # L38-39; fields L42-55; from_row(cls, row) L67-94 uses getattr
    @classmethod
    def from_row(cls, row: Any) -> "SlugRecord": ...  # attribute access: query_slug, program_slug, description, provider, …
class TenantGuard:                                     # L97; assert_allowed(record) L107-110 (unchanged)
class SlugCatalog:                                     # L131
    def __init__(self, dsn: str, guard: TenantGuard) -> None:          # L134
    async def get(self, slug: str) -> SlugRecord:                        # L149-159 (QueryModel.get, NoDataFound → SlugNotFoundError)
    async def get_allowed(self, slug: str) -> SlugRecord:                # L161-165
    async def list(self, *, search: str | None, program: str | None, limit: int) -> list[SlugRecord]:  # L167-192
    async def list_programs(self) -> list[str]:                         # L194 (unchanged)

# querysource 5.1.1 (/home/jesuslara/proyectos/querysource)
# tenants.py:46  @dataclass(frozen=True) class QueryIdentity: store: QueryStore; slug: str
# tenants.py:54  @dataclass(frozen=True) class LoadedDefinition: identity; runtime: QueryModel; revision: str
# tenants.py:402 TenantRegistry.resolve(tenant=None) -> QueryStore  (None → default/public; "public" literal ok;
#                unknown → TenantError(error_code="tenant_not_available"))
# tenant_errors.py:15 TenantError(message, *, error_code) ; .error_code ∈ {invalid_tenant, tenant_not_available,
#                query_not_found, tenant_store_unavailable, tenant_write_forbidden, tenant_worker_unsupported}
# repositories/definitions.py:56  DefinitionRepository(registry, connection_factory); .registry attribute (L66)
#   async get(identity: QueryIdentity) -> LoadedDefinition          # L161; missing → TenantError(query_not_found)
#   async list(store, params: Mapping) -> DefinitionPage             # L175; params keys page, page_size (max 200,
#       _MAX_PAGE_SIZE L34), sort_field (default 'updated_at'), sort_direction, fields, filters;
#       'program_slug' in filters/fields/sort → TenantError(invalid_tenant)
#   _runtime_model: tenant store → program_slug = store.schema (L111-119)
# tenants.py DefinitionPage: rows: tuple[Mapping[str, Any], ...]; total: int   (rows are MAPPINGS, not objects)
```

### Does NOT Exist
- ~~`SlugCatalog.get(tenant=)`, `get_allowed(tenant=)`, `list(tenant=)`~~ — net-new here.
- ~~`SlugRecord.tenant`~~ — do not add a field; the caller already knows the tenant it asked for.
- ~~`program_slug` on tenant `DefinitionPage.rows`~~ — tenant contract never projects it; set it from `store.schema`.
- ~~`QueryModel.get(..., tenant=)`~~ — the legacy model has no tenant parameter.
- ~~A tenant-membership check~~ — tenant is routing, not security (spec §7 gotcha).
- ~~`repo.resolve(...)`~~ — resolution is `repo.registry.resolve(tenant)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/querysource/test_catalog_tenant.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py#SlugCatalog",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py#SlugCatalog.get",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py#SlugCatalog.get_allowed",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py#SlugCatalog.list",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py#SlugRecord",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py#SlugRecord.from_row",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py#TenantGuard"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every lane must pass `tenant` explicitly — `resolve(None)` silently falls back to `public.queries` (spec §7
  gotcha), which is exactly why `None` keeps the legacy path and a set tenant NEVER falls back.
- `TenantQueryHandler._prepare` (`querysource/handlers/tenant.py:198-212`) is the reference read-once pattern.
- The repository is obtained per call (it is stateless/cheap; connection factory binds to the calling loop) —
  do not cache it on the catalog across event loops.
- Keep the redaction contract of `SlugRecord` (never source/params/attributes/dwh_*/cache_options).

### References in Codebase
- `catalog.py:149-192` — existing get/list to extend.
- `packages/ai-parrot-tools/tests/querysource/conftest.py` — `patched_qs` / `fake_rows` fixtures to reuse for the
  `tenant=None` regression case.

---

## Implementation Blueprint

### Steps (in order)
1. Add a private helper `_tenant_error_to_toolkit(exc, slug, tenant)` mapping `TenantError.error_code` — *why*:
   one mapping table for get and list keeps AC8-style error semantics consistent.
2. Add a private `_store_record(row, store)` adapter that turns a `DefinitionPage` Mapping row (or a runtime
   `QueryModel`) into `SlugRecord` with `program_slug=store.schema` for tenant contracts — *why*: `from_row`
   uses attribute access and tenant rows carry no `program_slug`.
3. Extend `get` / `get_allowed` / `list` with keyword-only `tenant` — *why*: spec M7 skeleton signatures.
4. Write the tests with a fake repository.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def get(self, slug: str) -> SlugRecord:' packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py)
# REPLACE `get` (verified: catalog.py:149-159) with:
    async def get(self, slug: str, *, tenant: str | None = None) -> SlugRecord:
        """Load one definition; SlugNotFoundError when absent. Always hits the store (S2).

        ``tenant=None`` reads ``public.queries`` through QueryModel (FEAT-558 path, unchanged).
        A set ``tenant`` resolves through QuerySource's DefinitionRepository exactly like
        ``TenantQueryHandler._prepare`` (querysource handlers/tenant.py:198-212) and never falls back to public.
        """
        if tenant is not None:
            return await self._get_tenant(slug, tenant)
        await self.open()
        model = _qs.get_query_model()
        logger.debug("catalog.get %s", slug)
        async with await self._db.connection() as conn:  # connections.py:459
            try:
                row = await model.get(query_slug=slug, _connection=conn)  # connections.py:463
            except _not_found_exception_types() as exc:  # asyncdb NoDataFound / querysource SlugNotFound only
                raise SlugNotFoundError(f"slug '{slug}' not found") from exc
        return SlugRecord.from_row(row)

    async def _get_tenant(self, slug: str, tenant: str) -> SlugRecord:
        """repo.registry.resolve(tenant) → repo.get(QueryIdentity(store, slug)) → SlugRecord (program_slug == schema)."""
        tenants = _qs.get_tenants()
        repo = await _qs.get_definition_repository()
        logger.debug("catalog.get %s tenant=%s", slug, tenant)
        try:
            store = repo.registry.resolve(tenant)
            definition = await repo.get(tenants.QueryIdentity(store=store, slug=slug))
        except tenants.TenantError as exc:
            raise _tenant_error_to_toolkit(exc, slug=slug, tenant=tenant) from exc
        return _store_record(definition.runtime, store)

    async def get_allowed(self, slug: str, *, tenant: str | None = None) -> SlugRecord:
        """get() then guard.assert_allowed() — unchanged rule, now tenant-aware."""
        record = await self.get(slug, tenant=tenant)
        self.guard.assert_allowed(record)
        return record
```
**Why**: `None` keeps FEAT-558 semantics (AC4 "null runs against public"); the tenant branch mirrors the
QuerySource read-once reference; the guard call is literally unchanged (AC6).

```python
# occurrences: 1 (verified: grep -c '    async def list(self, *, search: str | None, program: str | None, limit: int) -> list[SlugRecord]:' catalog.py)
# CHANGE the signature (verified: catalog.py:167) to:
    async def list(
        self, *, search: str | None, program: str | None, limit: int, tenant: str | None = None
    ) -> list[SlugRecord]:
        """tenant=None: existing QueryModel path over public.queries; tenant set: repo.list(store, params)."""
        if tenant is not None:
            return await self._list_tenant(search=search, program=program, limit=limit, tenant=tenant)
        # … existing body (catalog.py:169-192) unchanged …

    async def _list_tenant(self, *, search: str | None, program: str | None, limit: int, tenant: str) -> list[SlugRecord]:
        """List one tenant store's definitions; program filter/allowlist evaluated against program_slug == schema."""
        tenants = _qs.get_tenants()
        repo = await _qs.get_definition_repository()
        try:
            store = repo.registry.resolve(tenant)
            page = await repo.list(store, {"page": 1, "page_size": 200})  # _MAX_PAGE_SIZE (definitions.py:34)
        except tenants.TenantError as exc:
            raise _tenant_error_to_toolkit(exc, slug="*", tenant=tenant) from exc
        records = [_store_record(row, store) for row in page.rows]
        # FILL IN: apply `program` (TenantDeniedError when restricted and program ∉ allowlist, same message as L174-176),
        # drop records the guard would deny (guard.restricted and program_slug ∉ programs), apply `search` exactly like
        # L189-191, sort by slug, slice [:limit] — bounded by AC6 (allowlist applies unchanged)
        raise NotImplementedError
```

```python
# Module-level helpers — AFTER `_not_found_exception_types` (verified: catalog.py:26-35), before `@dataclass(frozen=True)`
# occurrences: 1 (verified: grep -c 'def _not_found_exception_types' catalog.py)


def _tenant_error_to_toolkit(exc: Any, *, slug: str, tenant: str) -> QuerysourceToolkitError:
    """Map querysource TenantError.error_code to the toolkit hierarchy (messages written for the LLM)."""
    code = getattr(exc, "error_code", None)
    if code in ("query_not_found", "tenant_not_available"):
        return SlugNotFoundError(f"slug '{slug}' not found for tenant '{tenant}'")
    if code == "invalid_tenant":
        return InvalidConditionsError(f"invalid tenant request for '{tenant}': {exc}")
    return QuerysourceToolkitError(f"tenant '{tenant}' store error ({code}): {exc}")


def _store_record(row: Any, store: Any) -> "SlugRecord":
    """Build a SlugRecord from a runtime QueryModel or a DefinitionPage Mapping row of ``store``."""
    # FILL IN: Mapping rows → SimpleNamespace(**row) (from types import SimpleNamespace); set program_slug =
    # store.schema when store.contract == "tenant" (legacy rows keep their own program_slug) — bounded by
    # definitions.py:111-119 (runtime program_slug == schema for tenant stores)
    raise NotImplementedError
```
**Why**: two small pure helpers shared by get/list; the mapping table is the one spec §7 prescribes
(`TenantError.error_code` 404 codes vs store-unavailable).

### `packages/ai-parrot-tools/tests/querysource/test_catalog_tenant.py` (CREATE)
```python
"""FEAT-598 TASK-3783 — SlugCatalog resolves tenant slugs through DefinitionRepository."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from parrot_tools.querysource import _qs
from parrot_tools.querysource.catalog import SlugCatalog, TenantGuard
from parrot_tools.querysource.errors import SlugNotFoundError, TenantDeniedError


class _TenantError(Exception):
    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class _Identity:
    store: object
    slug: str


class FakeRepo:
    """Records identities; stores = {schema: {slug: runtime}}."""

    def __init__(self, stores: dict[str, dict[str, object]]) -> None:
        self.stores = stores
        self.identities: list[_Identity] = []
        self.registry = SimpleNamespace(resolve=self._resolve)

    def _resolve(self, tenant):
        # FILL IN: return SimpleNamespace(schema=tenant, table="queries", contract="tenant") for known tenants,
        # raise _TenantError(error_code="tenant_not_available") otherwise
        raise NotImplementedError

    async def get(self, identity):
        # FILL IN: record identity; return SimpleNamespace(runtime=…) or raise _TenantError(query_not_found)
        raise NotImplementedError

    async def list(self, store, params):
        # FILL IN: return SimpleNamespace(rows=tuple(<Mapping rows without program_slug>), total=N)
        raise NotImplementedError


@pytest.fixture
def fake_repo(monkeypatch):
    # FILL IN: build FakeRepo with an "acme" store holding epson_field_activity; monkeypatch
    # _qs.get_tenants → SimpleNamespace(QueryIdentity=_Identity, TenantError=_TenantError) and
    # _qs.get_definition_repository → async lambda returning the repo
    raise NotImplementedError


async def test_catalog_get_tenant_uses_definition_repository(fake_repo):
    catalog = SlugCatalog("postgres://fake", TenantGuard(None))
    rec = await catalog.get("epson_field_activity", tenant="acme")
    assert fake_repo.identities[-1].slug == "epson_field_activity"
    assert rec.program_slug == "acme"  # program_slug == schema for tenant stores


async def test_catalog_tenant_allowlist_applies(fake_repo):
    # FILL IN: TenantGuard(["epson"]) + tenant "acme" → TenantDeniedError (program_slug 'acme' ∉ allowlist)
    raise NotImplementedError


async def test_catalog_tenant_errors_map_to_slug_not_found(fake_repo):
    # FILL IN: unknown tenant and unknown slug both raise SlugNotFoundError
    raise NotImplementedError


async def test_catalog_list_tenant(fake_repo):
    # FILL IN: list(search=None, program=None, limit=10, tenant="acme") returns sorted SlugRecords, program_slug=="acme"
    raise NotImplementedError


async def test_catalog_tenant_none_keeps_query_model_path(patched_qs):
    rec = await SlugCatalog("postgres://fake", TenantGuard(None)).get("epson_field_activity")
    assert rec.program_slug == "epson" and patched_qs["get"]
```

### FILL IN checklist
- [ ] `catalog.py::SlugCatalog._list_tenant` — program/allowlist/search/sort/limit; bounded by AC6.
- [ ] `catalog.py::_store_record` — Mapping adapter + program_slug from schema; bounded by definitions.py:111-119.
- [ ] Test fakes + the four FILL IN test bodies.

---

## Acceptance Criteria

- [ ] `SlugCatalog.get(slug, tenant="acme")` calls `repo.get(QueryIdentity(store, slug))` and returns
      `program_slug == "acme"` (spec test `test_catalog_get_tenant_uses_definition_repository`).
- [ ] `TenantGuard` programs allowlist applies unchanged to tenant records (AC6).
- [ ] `tenant=None` path is unchanged; all existing `tests/querysource/test_catalog.py` tests pass.
- [ ] `TenantError(query_not_found|tenant_not_available)` → `SlugNotFoundError`.
- [ ] No module-level `querysource` import; `ruff check` / `black --check` clean.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/querysource/test_catalog_tenant.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_catalog.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note


- Task: TASK-3783
- Feature: a2ui-linked-surfaces
- Implementation SHA: 17721ac97646c6cd5242b2eb118655fa66466583
- Closed at (UTC): 2026-09-26T01:45:44+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| coder_record_review | NOT recorded - coder_record_review MCP tool rejects every payload including {} (systemic tool outage, confirmed also on coder_record_feedback and coder_record_native_observation) |
| merge_validation_outcome | failed: pre-existing failures unrelated to this task's diff -- 2 already-characterized test_agent_a2ui_stream.py brittle assertions, plus new-signature failures/errors in ai-parrot-server/tests/studio/* all traced to environmental DB/network unavailability (Postgres 'No route to host', DocumentDB 'Connection refused' -- no DB/network in this sandbox), verified reproducible on clean origin/dev. Task's own scoped tests: 89 passed (querysource catalog suite). See issue:181bd0c01bb4. |
| seat_summary | Seat: sonnet - Backend: native - Model: sonnet - Attempts: 1 - Duration: n/a - Tokens: n/a |
