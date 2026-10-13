# TASK-4288: QuerySlugSource fetch-path slug authorization (resolver identity)

**Feature**: FEAT-667 — Fail-closed slug authorization on the QuerySlugSource fetch path
**Spec**: `sdd/specs/fixgroup-04e6aabc0d26.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: issue:176ec55ba7c3

---

## Context

Ledger fix lane (`/sdd-fix`, fixgroup:04e6aabc0d26). The FEAT-598 persistence
boundary authorizes linked-surface slugs via
`PhysicalResources(source_type="query_slug", source_id=f"{tenant or 'public'}:{slug}")`,
but the fetch/refresh path (`AuthorizingDataSource.fetch` →
`resolve_physical_resources`) gets an **empty** `PhysicalResources()` for
`QuerySlugSource`, so the guard checks nothing. Implements spec §3 M1.

---

## Scope

- Change the `QuerySlugSource` branch of `resolve_physical_resources`
  (resolver.py:167) to return the slug identity (spec §3 M1 skeleton).
- Replace `test_query_slug_source_returns_empty` with
  `test_query_slug_source_returns_slug_identity` (tenant-less and tenanted).
- Add two adapter regression tests: denied slug raises before fetch;
  allowed slug fetches and the guard saw the slug identity.

**NOT in scope**: `DataPlanePolicyGuard`, `LinkedSurfaceService`,
`execute_sources`, RLS injection, any `slug:execute` action.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py` | MODIFY | slug identity for QuerySlugSource |
| `packages/ai-parrot/tests/auth/test_physical_resource_resolver.py` | MODIFY | pin the new identity |
| `packages/ai-parrot/tests/auth/test_authorizing_data_source.py` | MODIFY | deny/allow slug regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources, resolve_physical_resources  # verified: resolver.py:47
from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource  # verified: query_slug.py:56
from parrot.auth.exceptions import AuthorizationRequired  # verified: authorizing.py:101
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py
class PhysicalResources(BaseModel):  # line 47
    driver: Optional[str] = None
    tables: set[str] = Field(default_factory=set)
    source_type: Optional[str] = None
    source_id: Optional[str] = None

# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py
class QuerySlugSource(DataSource):  # line 56; attrs: self.slug (line 96), self.tenant (line 99)
```

### Does NOT Exist
- ~~`slug:execute` action~~ — the gate is `source:read` on
  `query_slug:<tenant|public>:<slug>` (FEAT-598 rev 0.3).
- ~~`PhysicalResources.slug`~~ — identity goes in `source_type`/`source_id`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/auth/test_physical_resource_resolver.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/auth/test_authorizing_data_source.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py#PhysicalResources",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py#QuerySlugSource"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Identity string mirrors `service.py:118` exactly:
  `f"{source.tenant or 'public'}:{source.slug}"`.
- New adapter tests reuse the file's existing mock-guard fixture pattern
  (AsyncMock guard: `authorize_source`, `rls_predicates` → `[]`,
  `is_sensitive_driver` → False) — read the fixtures before writing.
- Keep the resolver branch comment explaining the mirror.

---

## Implementation Blueprint

### Steps (in order)
1. Edit the `QuerySlugSource` branch in resolver.py — *why*: the empty
   resource set is the entire bug.
2. Update the resolver test to pin the new identity — *why*: the old test
   pins the buggy behavior and would fail.
3. Add the deny/allow adapter tests — *why*: pins AC2/AC3 end-to-end on the
   adapter without QuerySource PBAC.
4. Run validation commands; `ruff check --fix` the three files.

### `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'if isinstance(source, QuerySlugSource):' resolver.py)
# REPLACE — the body of the `if isinstance(source, QuerySlugSource):` branch (verified: resolver.py:167-170)
    if isinstance(source, QuerySlugSource):
        # Mirror LinkedSurfaceService's persistence identity (service.py:118):
        # DataPlanePolicyGuard gates source:read on
        # "query_slug:<tenant|public>:<slug>" (FEAT-598 rev 0.3). An empty
        # PhysicalResources here made AuthorizingDataSource a no-op for slug
        # sources on the fetch/refresh path (issue:176ec55ba7c3).
        return PhysicalResources(
            source_type="query_slug",
            source_id=f"{source.tenant or 'public'}:{source.slug}",
        )
```
**Why this shape**: the guard's step 3b only fires when `source_type` and
`source_id` are both set; the string format must match the persistence
boundary so one PBAC policy covers both paths. Do not touch other branches.

### `packages/ai-parrot/tests/auth/test_physical_resource_resolver.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_query_slug_source_returns_empty' <path>)
# REPLACE — the whole test_query_slug_source_returns_empty method (verified: test_physical_resource_resolver.py:110-116)
    def test_query_slug_source_returns_slug_identity(self) -> None:
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource

        source = QuerySlugSource(slug="my_slug")
        result = resolve_physical_resources(source)
        assert result.driver is None
        assert result.tables == set()
        assert result.source_type == "query_slug"
        assert result.source_id == "public:my_slug"

    def test_query_slug_source_tenant_in_identity(self) -> None:
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource

        source = QuerySlugSource(slug="my_slug", tenant="acme")
        result = resolve_physical_resources(source)
        assert result.source_type == "query_slug"
        assert result.source_id == "acme:my_slug"
```
**Why**: pins AC1 for both tenant cases.

### `packages/ai-parrot/tests/auth/test_authorizing_data_source.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def test_sensitive_driver_slug_allowed' <path>)
# AFTER — insert below the whole test_sensitive_driver_slug_allowed test
# (verified: test_authorizing_data_source.py:110), matching the file's
# existing fixture/mock-guard idiom:
# FILL IN: adapt fixture names to the file's actual fixtures — bounded by AC2/AC3:
#   test_denied_slug_raises_no_fetch: guard.authorize_source raises
#     AuthorizationRequired; adapter over QuerySlugSource(slug="s", tenant="t")
#     raises; inner fetch mock never awaited.
#   test_allowed_slug_fetches: guard allows; inner fetch awaited once; the
#     PhysicalResources passed to guard.authorize_source has
#     source_type == "query_slug" and source_id == "t:s".
```
**Why**: proves the fetch path is fail-closed with ONLY the ai-parrot guard —
QuerySource PBAC absent — which is the issue's core demand.

### FILL IN checklist
- [ ] `test_authorizing_data_source.py` new tests — reuse the file's real fixtures/mocks; bounded by AC2/AC3.

---

## Acceptance Criteria

- [ ] AC1: resolver returns `("query_slug", "public:<slug>")` / `("query_slug", "<tenant>:<slug>")`; no driver/tables
- [ ] AC2: denied slug → `AuthorizationRequired` before inner fetch
- [ ] AC3: allowed slug → inner fetch runs; guard saw the slug identity
- [ ] AC4: both test files pass fully
- [ ] No linting errors on the three files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/auth/test_physical_resource_resolver.py -q`
- `pytest packages/ai-parrot/tests/auth/test_authorizing_data_source.py -q`

---

## Test Specification

See blueprint blocks above.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug fixgroup-04e6aabc0d26 --feature-id FEAT-667`)
2. **Read the spec** for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in `sdd/tasks/index/fixgroup-04e6aabc0d26.json` → `"in-progress"` and commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the three listed files
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4288 fixgroup-04e6aabc0d26 verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
