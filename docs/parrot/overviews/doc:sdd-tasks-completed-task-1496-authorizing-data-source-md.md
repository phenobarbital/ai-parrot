---
type: Wiki Overview
title: 'TASK-1496: AuthorizingDataSource Decorator'
id: doc:sdd-tasks-completed-task-1496-authorizing-data-source-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: a callable that returns the current `PermissionContext` (from `_pctx_var`).
relates_to:
- concept: mod:parrot.auth.dataplane_guard
  rel: mentions
- concept: mod:parrot.auth.exceptions
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.authorizing
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.base
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.query_slug
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.resolver
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.rls
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.sql
  rel: mentions
---

# TASK-1496: AuthorizingDataSource Decorator

**Feature**: FEAT-228 — Deterministic Data-Plane Authorization for DatasetManager
**Spec**: `sdd/specs/dataplane-authz.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1491, TASK-1492, TASK-1494, TASK-1495
**Assigned-to**: unassigned

---

## Context

> Spec Module 7. The keystone of the feature: a decorator that wraps any
> `DataSource` with the full enforcement chain. Its `fetch()` resolves physical
> resources, runs the guard (driver:connect → table:read/source:read),
> collects and injects RLS predicates, then delegates to the inner source's
> `fetch()`. This is Option D from the brainstorm — enforcement at the source
> boundary, not at the tool entry point.

---

## Scope

- Implement `AuthorizingDataSource(DataSource)` that wraps an inner `DataSource`:
  - `__init__(inner, guard, pctx_provider)` — store inner source, guard, and
    a callable that returns the current `PermissionContext` (from `_pctx_var`).
  - `fetch(**params)` — the full enforcement chain:
    1. Check driver enforcement mode (sensitive → reject non-slug sources).
    2. Get `PermissionContext` from provider (None → fail-open, return `inner.fetch()`).
    3. Resolve physical resources from inner source (via `resolve_physical_resources`).
    4. Call `guard.authorize_source(ctx, resources)` (raises on denial).
    5. Collect RLS predicates from guard.
    6. Inject RLS into query/source (via injection functions from TASK-1494).
    7. Delegate to `inner.fetch()`.
  - Delegate `describe()`, `cache_key`, `has_builtin_cache` to inner source.
- Write integration-style unit tests that mock the guard and verify the full chain.

**NOT in scope**: DatasetManager `_make_source()` factory (TASK-1497),
DatabaseQueryTool wiring (TASK-1498), remote execution (Module 10 deferred).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/sources/authorizing.py` | CREATE | `AuthorizingDataSource` class |
| `tests/auth/test_authorizing_data_source.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Base class
from parrot.tools.dataset_manager.sources.base import DataSource  # line 23

# Resolver (TASK-1491)
from parrot.tools.dataset_manager.sources.resolver import (
    resolve_physical_resources, PhysicalResources, ReadOnlyViolation,
)

# RLS injection (TASK-1494)
from parrot.tools.dataset_manager.sources.rls import inject_rls_sql

# Guard (TASK-1495)
from parrot.auth.dataplane_guard import DataPlanePolicyGuard

# Auth types
from parrot.auth.permission import PermissionContext
from parrot.auth.exceptions import AuthorizationRequired

# Source type checks
from parrot.tools.dataset_manager.sources.sql import SQLQuerySource
from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource
```

### Existing Signatures to Use
```python
# parrot/tools/dataset_manager/sources/base.py:23
class DataSource(ABC):
    def __init__(self, routing_meta: Dict | None = None) -> None:    # line 46
    async def fetch(self, **params) -> pd.DataFrame:                 # line 69 (abstract)
    def describe(self) -> str:                                        # line 90 (abstract)
    @property
    def has_builtin_cache(self) -> bool:                              # line 102
    @property
    def cache_key(self) -> str:                                       # line 117 (abstract)

# From TASK-1491
def resolve_physical_resources(source: DataSource) -> PhysicalResources: ...

# From TASK-1494
def inject_rls_sql(sql, dialect, predicates) -> tuple[str, dict]: ...

# From TASK-1495
class DataPlanePolicyGuard:
    def is_sensitive_driver(self, driver: str) -> bool: ...
    async def authorize_source(self, ctx, resources) -> None: ...  # raises AuthorizationRequired
    async def rls_predicates(self, ctx, resources) -> list[RlsPredicate]: ...
```

### Does NOT Exist
- ~~`parrot.tools.dataset_manager.sources.authorizing`~~ — does not exist yet (this task creates it)
- ~~`AuthorizingDataSource`~~ — does not exist yet
- ~~`DataSource.driver`~~ — not a base-class attribute
- ~~`DataSource.inner`~~ — not a base-class attribute (we define this)

---

## Implementation Notes

### Pattern to Follow

```python
import logging
from typing import Callable, Optional
from parrot.tools.dataset_manager.sources.base import DataSource

class AuthorizingDataSource(DataSource):
    """Decorator: wraps a DataSource with authorization + RLS enforcement."""

    def __init__(
        self,
        inner: DataSource,
        guard: "DataPlanePolicyGuard",
        pctx_provider: Callable[[], Optional["PermissionContext"]],
    ) -> None:
        super().__init__(routing_meta=getattr(inner, '_routing_meta', None))
        self._inner = inner
        self._guard = guard
        self._pctx_provider = pctx_provider
        self._logger = logging.getLogger(__name__)

    async def fetch(self, **params) -> "pd.DataFrame":
        from parrot.tools.dataset_manager.sources.resolver import (
            resolve_physical_resources, ReadOnlyViolation,
        )
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource

        # Step 0: sensitive driver pre-check
        driver = getattr(self._inner, '_driver', None)
        if driver and self._guard.is_sensitive_driver(driver):
            if not isinstance(self._inner, QuerySlugSource):
                raise AuthorizationRequired(
                    f"Driver '{driver}' is classed sensitive: only query slugs allowed"
                )

        # Step 1: get permission context
        ctx = self._pctx_provider()
        if ctx is None:
            return await self._inner.fetch(**params)  # fail-open

        # Step 2: resolve physical resources
        resources = resolve_physical_resources(self._inner)

        # Step 3-4: authorize (raises on denial)
        await self._guard.authorize_source(ctx, resources)

        # Step 5: collect RLS predicates
        predicates = await self._guard.rls_predicates(ctx, resources)

        # Step 6: inject RLS if needed
        if predicates:
            self._apply_rls(predicates)

        # Step 7: delegate
        return await self._inner.fetch(**params)

    def describe(self) -> str:
        return self._inner.describe()

    @property
    def has_builtin_cache(self) -> bool:
        return self._inner.has_builtin_cache

    @property
    def cache_key(self) -> str:
        return self._inner.cache_key
```

### Key Constraints
- `pctx_provider` is a callable (typically `lambda: _pctx_var.get(None)`) so the
  decorator can fetch the current context at fetch-time, not construction-time.
- When `ReadOnlyViolation` is raised by the resolver, let it propagate — the
  caller (DatasetManager) catches it as a denial.
- When `sqlglot.errors.ParseError` is raised on a guarded driver, catch and
  re-raise as `AuthorizationRequired` (fail-closed). On unguarded driver, let
  the original error propagate.
- The decorator must NOT modify the inner source's state for non-RLS scenarios.
  RLS injection for SQL sources returns a new query string; for table/slug
  sources it modifies `_permanent_filter` (which is acceptable since the source
  is consumed once).

### References in Codebase
- `parrot/tools/dataset_manager/sources/base.py` — DataSource ABC
- `parrot/auth/dataplane_guard.py` (TASK-1495) — guard API
- `parrot/tools/dataset_manager/sources/resolver.py` (TASK-1491) — resolver API
- `parrot/tools/dataset_manager/sources/rls.py` (TASK-1494) — RLS injection API

---

## Acceptance Criteria

- [ ] Wraps any DataSource subclass transparently (describe/cache_key delegate)
- [ ] Sensitive driver + non-slug source → `AuthorizationRequired` before parsing
- [ ] No `PermissionContext` → fail-open (delegates to inner.fetch directly)
- [ ] Guard denial → `AuthorizationRequired`, inner.fetch() never called
- [ ] Guard allowed + RLS predicates → predicates injected before fetch
- [ ] Guard allowed + no RLS → delegates to inner.fetch unchanged
- [ ] Parse failure on guarded driver → `AuthorizationRequired`
- [ ] `ReadOnlyViolation` propagates as-is
- [ ] All tests pass: `pytest tests/auth/test_authorizing_data_source.py -v`
- [ ] No linting errors: `ruff check parrot/tools/dataset_manager/sources/authorizing.py`

---

## Test Specification

```python
# tests/auth/test_authorizing_data_source.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.exceptions import AuthorizationRequired


@pytest.fixture
def pctx():
    return PermissionContext(
        session=UserSession(username="test", groups=["Finance"], programs=[])
    )


@pytest.fixture
def mock_guard():
    guard = MagicMock()
    guard.is_sensitive_driver.return_value = False
    guard.authorize_source = AsyncMock()
    guard.rls_predicates = AsyncMock(return_value=[])
    return guard


@pytest.fixture
def mock_inner():
    inner = AsyncMock()
    inner._driver = "pg"
    inner.fetch = AsyncMock(return_value="dataframe")
    inner.describe.return_value = "test source"
    inner.has_builtin_cache = False
    inner.cache_key = "test-key"
    return inner


class TestAuthorizingDataSource:
    @pytest.mark.asyncio
    async def test_allowed_delegates_to_inner(self, mock_inner, mock_guard, pctx):
        source = AuthorizingDataSource(mock_inner, mock_guard, lambda: pctx)
        result = await source.fetch()
        mock_inner.fetch.assert_called_once()
        assert result == "dataframe"

    @pytest.mark.asyncio
    async def test_denied_raises_no_fetch(self, mock_inner, mock_guard, pctx):
        mock_guard.authorize_source = AsyncMock(
            side_effect=AuthorizationRequired("denied")
        )
        source = AuthorizingDataSource(mock_inner, mock_guard, lambda: pctx)
        with pytest.raises(AuthorizationRequired):
            await source.fetch()
        mock_inner.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_context_failopen(self, mock_inner, mock_guard):
        source = AuthorizingDataSource(mock_inner, mock_guard, lambda: None)
        result = await source.fetch()
        mock_inner.fetch.assert_called_once()
        mock_guard.authorize_source.assert_not_called()

    def test_describe_delegates(self, mock_inner, mock_guard):
        source = AuthorizingDataSource(mock_inner, mock_guard, lambda: None)
        assert source.describe() == "test source"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/dataplane-authz.spec.md` §5.3–§5.4 for enforcement chain
2. **Check dependencies** — verify TASK-1491, TASK-1492, TASK-1494, TASK-1495 are complete
3. **Verify the Codebase Contract** — confirm DataSource ABC and guard APIs
4. **Update status** in `sdd/tasks/index/dataplane-authz.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1496-authorizing-data-source.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-08
**Notes**: Full enforcement chain implemented. AuthorizationRequired uses tool_name/message signature. `driver` attr is accessed via `getattr(inner, 'driver', None)` since it's not on the base class. All 9 tests pass.

**Deviations from spec**: none
