---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [a2ui, linked-surfaces, authorization, dataplane-guard, ledger-fix]
---

# Feature Specification: Fail-closed slug authorization on the QuerySlugSource fetch path

**Feature ID**: FEAT-667
**Date**: 2026-10-14
**Author**: Claude (agent:sdd-fix)
**Status**: approved
**Target version**: 0.30.x

---

## 1. Motivation & Business Requirements

> Ledger-driven fix (`/sdd-fix`, fixgroup:04e6aabc0d26). Resolves the
> remaining half of `issue:176ec55ba7c3` (major, feature_gap) — "FEAT-598:
> specify a real fail-closed slug authorization adapter".

### Problem Statement

FEAT-598's spec (M5/AC14/AC18) requires the data-plane guard to assert the
owner's authorization on every `(tenant, slug)` a linked surface uses, with
`AuthorizingDataSource` as the mandatory defense when QuerySource's
in-process PBAC is absent. Since the issue was filed, the **persistence**
boundary landed correctly: `LinkedSurfaceService` builds
`PhysicalResources(source_type="query_slug", source_id=f"{tenant or 'public'}:{slug}")`
per source and the guard gates `source:read` on it
(`service.py:109-125`, spec rev 0.3: `query_slug:<tenant|public>:<slug>`
under the existing `source:read` gate — no new `slug:execute` action).

The **fetch/refresh** path is still unguarded: `AuthorizingDataSource.fetch`
resolves resources via `resolve_physical_resources(self._inner)`
(`authorizing.py:130`), and the resolver returns an **empty**
`PhysicalResources()` for `QuerySlugSource` (`resolver.py:167-170`).
`DataPlanePolicyGuard.authorize_source` with empty resources checks nothing
(no driver, no tables, no source identity), so wrapping a slug source in the
authorizing adapter — exactly what `execute_sources` does for every linked
refresh — performs **no slug check at all**. When QuerySource PBAC is
unavailable (its documented silent-no-op degradation), nothing authorizes
the slug on refresh.

### Goals
- `resolve_physical_resources(QuerySlugSource)` returns the same slug
  identity the persistence boundary already uses:
  `PhysicalResources(source_type="query_slug", source_id=f"{tenant or 'public'}:{slug}")`.
- `AuthorizingDataSource` over a `QuerySlugSource` therefore gates
  `source:read` on `query_slug:<tenant|public>:<slug>` on EVERY fetch
  (linked-surface refresh included), fail-closed on deny and on evaluator
  error (guard step 3b semantics, `dataplane_guard.py:286-315`).
- Regression tests cover real adapter behavior with no in-process
  QuerySource PBAC involved: denied slug → `AuthorizationRequired` before
  any fetch; allowed slug → inner fetch proceeds.

### Non-Goals (explicitly out of scope)
- No new `slug:execute` action (spec rev 0.3 resolved the naming:
  `source:read` on `query_slug:*` is the contract).
- No change to `DataPlanePolicyGuard`, `LinkedSurfaceService`, or
  `execute_sources` — the identity convention and wiring already exist.
- No RLS changes: slug RLS injection (`inject_rls_query_slug`) keeps its
  existing behavior.
- `ctx is None` keeps its documented fail-open semantics (adapter step 1).

---

## 2. Architectural Design

### Overview

One mapping change in the physical-resource resolver plus regression tests.
The guard, the adapter chain, and the persistence-side convention are
untouched; the resolver simply stops returning an empty (uncheckable)
resource set for slug sources.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `resolve_physical_resources` (`resolver.py:167`) | modified | `QuerySlugSource` branch returns slug identity instead of empty |
| `AuthorizingDataSource.fetch` (`authorizing.py:130,143`) | unchanged consumer | now receives a checkable resource set for slugs |
| `DataPlanePolicyGuard.authorize_source` step 3b (`dataplane_guard.py:286`) | unchanged | gates `source:read` on `query_slug:<tenant\|public>:<slug>` |
| `LinkedSurfaceService` (`service.py:118-121`) | convention source | identity string mirrored exactly |

### New Public Interfaces

None.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: resolver slug identity + tests | yes | exact return value and test shapes fixed below | — |

### Module 1: Slug identity in the physical-resource resolver
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py`
- **Responsibility**: return a checkable identity for `QuerySlugSource`.
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  # modifies resolver.py:167 (QuerySlugSource branch of resolve_physical_resources)
  if isinstance(source, QuerySlugSource):
      # Mirror LinkedSurfaceService's persistence identity (service.py:118):
      # the guard gates source:read on "query_slug:<tenant|public>:<slug>".
      return PhysicalResources(
          source_type="query_slug",
          source_id=f"{source.tenant or 'public'}:{source.slug}",
      )
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_query_slug_source_returns_slug_identity` | M1 | replaces `test_query_slug_source_returns_empty` (resolver test:110): tenant-less slug → `("query_slug", "public:my_slug")`; tenanted slug → `("query_slug", "acme:my_slug")`; no driver/tables |
| `test_denied_slug_raises_no_fetch` | M1 | `AuthorizingDataSource(QuerySlugSource, deny-guard)` → `AuthorizationRequired`, inner fetch never called |
| `test_allowed_slug_fetches` | M1 | allow-guard → inner fetch called; guard received the slug identity resources |

### Integration Tests
Existing suites must pass: `tests/auth/test_physical_resource_resolver.py`,
`tests/auth/test_authorizing_data_source.py`.

---

## 5. Acceptance Criteria

- [ ] AC1: `resolve_physical_resources(QuerySlugSource(slug="s"))` returns
      `source_type="query_slug"`, `source_id="public:s"`; with
      `tenant="t"` → `source_id="t:s"`; `driver is None`, `tables == set()`.
- [ ] AC2: `AuthorizingDataSource` over a `QuerySlugSource` with a guard
      whose `authorize_source` raises `AuthorizationRequired` never calls
      the inner fetch (fail-closed on the fetch path, no QuerySource PBAC
      involved).
- [ ] AC3: with an allowing guard, the inner fetch runs and the guard was
      called with the slug-identity `PhysicalResources`.
- [ ] AC4: both existing test files pass with the updated expectations.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources, resolve_physical_resources  # verified: resolver.py:47,~140
from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource  # verified: query_slug.py:56
from parrot.auth.exceptions import AuthorizationRequired  # verified: authorizing.py:101
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py
class PhysicalResources(BaseModel):  # line 47
    driver: Optional[str] = None
    tables: set[str] = Field(default_factory=set)
    source_type: Optional[str] = None
    source_id: Optional[str] = None

# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py
class QuerySlugSource(DataSource):  # line 56
    self.slug = slug      # line 96
    self.tenant = tenant  # line 99
```

### Does NOT Exist (Anti-Hallucination)
- ~~`slug:execute` action~~ — rejected in FEAT-598 rev 0.3; the gate is
  `source:read` on resource `query_slug:<tenant|public>:<slug>`.
- ~~`PhysicalResources.slug`~~ — no such field; identity goes in
  `source_type`/`source_id`.

### Edit Sites (Blueprint Anchors)

Verified against: 675e873af

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py` | MODIFY | `    if isinstance(source, QuerySlugSource):` | `resolver.py:167` | 1 |
| `packages/ai-parrot/tests/auth/test_physical_resource_resolver.py` | MODIFY | `    def test_query_slug_source_returns_empty(self) -> None:` | `test_physical_resource_resolver.py:110` | 1 |
| `packages/ai-parrot/tests/auth/test_authorizing_data_source.py` | MODIFY | `    async def test_sensitive_driver_slug_allowed(` | `test_authorizing_data_source.py:110` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `service.py:118`'s identity string exactly:
  `f"{tenant or 'public'}:{slug}"`.
- Tests follow the existing mock-guard fixtures in
  `test_authorizing_data_source.py` (AsyncMock guard with
  `authorize_source` / `rls_predicates` / `is_sensitive_driver`).

### Known Risks / Gotchas
- **Deployment impact (intended)**: environments wrapping `QuerySlugSource`
  in `AuthorizingDataSource` without `query_slug:*` policies now enforce
  `source:read` on the fetch path — that is the fail-closed mandate of
  FEAT-598 AC14/AC18 ("the guard remains mandatory regardless"). Internal
  consumers only; hard cuts are the project norm.
- `databasequery/tool.py` builds resources from `SQLQuerySource` only —
  unaffected.

### External Dependencies
None.

---

## 8. Open Questions

None — the identity convention was resolved in FEAT-598 spec rev 0.3.

---

## 9. Design Research Cross-Check

Status: skipped (ledger-driven gap closure; the design decision — slug
identity under `source:read` — was already made and owner-confirmed in
FEAT-598 rev 0.3; this spec only extends it to the fetch path).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-14 | Claude (agent:sdd-fix) | Initial spec from fixgroup:04e6aabc0d26 / issue:176ec55ba7c3 |
