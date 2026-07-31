---
type: Wiki Overview
title: 'Feature Specification: FormRegistry Multi-Tenancy'
id: doc:sdd-specs-formregistry-multi-tenancy-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: (`packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py`)
---

---
type: feature
base_branch: dev
---

# Feature Specification: FormRegistry Multi-Tenancy

**Feature ID**: FEAT-183
**Date**: 2026-05-19
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD

---

## 1. Motivation & Business Requirements

### Problem Statement

`FormRegistry`
(`packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py`)
is the in-memory cache for `FormSchema` objects. Its persistence layer
(`FormStorage` / `PostgresFormStorage`) is already tenant-aware — `save / load
/ delete / list_forms` accept a `tenant=` kwarg that resolves to a Postgres
schema (`epson.form_schemas` vs `pokemon.form_schemas`), and
`FormSchema.tenant: str | None` exists in `core/schema.py:187`.

The gap is the registry's in-memory state. `self._forms: dict[str, FormSchema]`
(`registry.py:139`) is keyed only by `form_id`. Two tenants that share a
`form_id` (entirely plausible — e.g. `"customer-intake"` exists for both
`epson` and `pokemon`) collide: the second `register()` silently overwrites
the first. Read APIs (`get`, `contains`, `unregister`, `list_forms`,
`list_form_ids`, `clear`, `load_from_directory`) do not accept a tenant, so a
correctly-persisted multi-tenant Postgres backend is fronted by a tenant-blind
cache that can leak forms across tenants in the same process.

This feature closes the gap so a single `FormRegistry` instance manages forms
scoped by tenant — writes AND reads are keyed by `(tenant, form_id)`, never
by `form_id` alone.

### Goals

- A single `FormRegistry` instance scopes its in-memory state by tenant.
- Two tenants may register forms with the same `form_id` without collision.
- Every public read/write method accepts an explicit `tenant=` kwarg.
- `tenant=None` strictly resolves to the configured default tenant
  (`"navigator"`) — never aggregates across tenants.
- A cross-tenant introspection helper (`list_tenants()`) exists; explicit
  looping is the **only** way to perform admin-style cross-tenant operations.
- `FormSchema.tenant` is the source of truth for a form's tenant; the registry
  validates and indexes by it.
- The `asyncio.Lock` model is preserved.

### Non-Goals (explicitly out of scope)

- **No data migration script.** Per the brainstorm's resolved Open Question,
  no forms currently exist in production, so a Postgres backfill script is
  not part of this feature. New deployments start with tenant-tagged forms
  from day one.
- **No implicit tenant propagation** (`ContextVar`, thread-locals, aiohttp
  middleware). Tenant flows through explicit method parameters only — Option
  B from `sdd/proposals/formregistry-multi-tenancy.brainstorm.md` was
  rejected on this point.
- **No per-tenant registry instances / fleet pattern.** Option C in the
  brainstorm (`TenantRegistryManager` holding per-tenant `FormRegistry`s)
  was rejected; we stay with one instance per process.
- **No changes to `FormStorage` / `PostgresFormStorage`.** The storage layer
  is already multi-tenant; this feature only touches the registry and its
  callers.
- **No cross-tenant aggregation helpers** like `list_all_forms()`. Admin code
  loops `await registry.list_tenants()` explicitly.
- **No per-tenant locking.** A single `asyncio.Lock` continues to guard all
  mutations; per-tenant locks are deferred (premature optimization).
- **No legacy `on_unregister(form_id)` signature retained.** The callback API
  changes in place; no `on_unregister_v2`.

---

## 2. Architectural Design

### Overview

`FormRegistry`'s internal state moves from `dict[str, FormSchema]` to
`dict[str, dict[str, FormSchema]]` — outer key is `tenant`, inner key is
`form_id`. Two new constructor arguments configure the multi-tenant contract:

- `default_tenant: str = "navigator"` — the tenant name used when callers pass
  `tenant=None`. Chosen to match `PostgresFormStorage.DEFAULT_SCHEMA`
  (`storage.py:51`) so single-tenant deploys see one consistent label across
  the registry and the Postgres schema.
- `require_tenant: bool = True` — when `True`, `register()` raises
  `ValueError` if the form's effective tenant (after resolution) would be
  `None`. When `False`, a `None`-tenant form is sealed to `default_tenant` in
  memory at registration time.

Every public method that today takes `form_id` or operates on all forms gains
a kwarg-only `tenant: str | None = None` parameter. The resolution rule is:

1. Explicit kwarg on the call (if not `None`).
2. For `register()`: `form.tenant` if the kwarg is `None`.
3. The registry's configured `default_tenant`.

`get / contains / unregister` look up `self._forms[resolved_tenant][form_id]`
with no fallback — a `form_id` registered under `"epson"` is invisible to
`get(form_id, tenant="pokemon")`. `list_forms / list_form_ids / clear` operate
on `self._forms[resolved_tenant]` only. There is no aggregation regardless of
input.

A new helper `list_tenants() -> list[str]` returns the outer-dict keys
**sorted** (stable for tests and admin UIs). No `list_all_forms()` exists.

The `on_register` callback signature is unchanged
(`Callable[[FormSchema], Awaitable[None]]` — the form already carries
`.tenant`). The `on_unregister` callback signature **changes** in place from
`Callable[[str], Awaitable[None]]` to `Callable[[str, str], Awaitable[None]]`
— callbacks receive `(form_id, tenant)`. This is a breaking change; all
in-tree consumers are updated in the same PR.

`load_from_directory(path, *, tenant=None, recursive=True, overwrite=False)`
parses YAML form definitions. Tenant resolution per file:

1. If the YAML declares a top-level `tenant:` field, that value wins (and is
   recorded on `FormSchema.tenant`).
2. Otherwise the `tenant=` kwarg supplies it.
3. If both are missing AND `require_tenant=True`, the file is **skipped with
   a warning** (per resolved Open Question), not a hard failure.

`load_from_storage(tenant=...)` is behaviorally unchanged but now lands
results in `self._forms[tenant]`, so calling it for multiple tenants in
sequence no longer overwrites — sequential `load_from_storage(tenant="epson")`
then `load_from_storage(tenant="pokemon")` produces a registry with both
tenants populated and isolated.

`__contains__` is replaced immediately (per resolved Open Question) with a
tuple-aware version: `__contains__(item)` where `item` is `(tenant, form_id)`.
The previous `__contains__(form_id)` form is removed — callers must use the
tuple. `__len__` returns the total count across all tenants.

`__aiter__` continues to yield `FormSchema` objects across all tenants in
deterministic order (sorted by tenant, then by `form_id` within each tenant)
so iteration in tests is reproducible.

A bulk script `scripts/sdd/tag_yaml_fixtures.py` walks tracked YAML form
fixtures (`tests/`, `examples/forms/`, any other discovered locations) and
inserts a `tenant: navigator` line into files that lack a top-level
`tenant:` field. The script is idempotent.

### Component Diagram

```
caller (request handler / tool / loader)
     │  registry.get(form_id, tenant="epson")
     ▼
FormRegistry
 ├── _resolve_tenant(tenant)             # explicit > form.tenant > default_tenant
 ├── _forms: dict[tenant, dict[form_id, FormSchema]]   # nested cache
 ├── _lock: asyncio.Lock                                # global mutex
 ├── _on_register: list[Callable[[FormSchema], Awaitable]]
 ├── _on_unregister: list[Callable[[str, str], Awaitable]]   # NEW: (form_id, tenant)
 ├── _storage: FormStorage | None
 └── list_tenants() -> list[str]         # NEW; sorted
     │
     ▼ (when persist=True)
FormStorage.save(form, tenant=resolved)
     │
     ▼
PostgresFormStorage → <tenant>.form_schemas
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormStorage` ABC (`services/registry.py:29-113`) | uses (unchanged) | Already accepts `tenant=` on save/load/delete/list_forms. |
| `PostgresFormStorage` (`services/storage.py`) | uses (unchanged) | `_resolve_schema()` precedence is the conceptual template for `_resolve_tenant()` in the registry. |
| `FormSchema` (`core/schema.py:154`) | uses (unchanged) | `FormSchema.tenant: str \| None` (line 187) is the source of truth indexed by the registry. |
| `api/handlers.py` (~10 call sites) | modifies | Each `registry.get / list_forms / register / unregister / contains` site threads the request tenant explicitly. |
| `ui/handlers.py` (~5 sites at lines 83, 122, 168, 206) | modifies | Tenant from session / auth context. |
| `renderers/telegram/router.py` (lines 99, 374, 422) | modifies | Tenant from chat / session metadata. |
| `tools/database_form.py` (line 213) | modifies | Tenant from tool execution context. |
| `tools/create_form.py` (lines 306, 366) | modifies | Tenant from tool execution context. |
| `api/uploads.py` (line 231) | modifies | Tenant from request. |
| `api/render.py` (line 127) | modifies | Tenant from request. |
| `api/operations.py` (lines 383, 459) | modifies | Tenant from request. |
| `on_unregister` callback consumers | **breaking** | Callback signature is `(form_id, tenant)`; audit and update every registered consumer in the same PR. |
| YAML form fixtures (tests, examples) | content migration | `scripts/sdd/tag_yaml_fixtures.py` inserts `tenant: navigator` into files lacking it. |
| `tests/unit/test_storage_schema_tenant.py` | reference pattern | Source for the registry-level tenant isolation tests. |

### Data Models

No new Pydantic models. `FormSchema.tenant: str | None` already exists
(`core/schema.py:187`) and is the field this feature indexes by.

### New Public Interfaces

The new public surface on `FormRegistry`:

```python
class FormRegistry:
    def __init__(
        self,
        storage: FormStorage | None = None,
        *,
        default_tenant: str = "navigator",
        require_tenant: bool = True,
    ) -> None: ...

    async def register(
        self,
        form: FormSchema,
        *,
        persist: bool = False,
        overwrite: bool = True,
        tenant: str | None = None,
    ) -> None:
        """Register a form. Resolution: kwarg > form.tenant > default_tenant.
        Logs a warning if explicit kwarg differs from form.tenant.
        Raises ValueError if require_tenant=True and resolution falls all the
        way through to default_tenant only because form.tenant was None and
        no kwarg was supplied."""

    async def unregister(
        self, form_id: str, *, tenant: str | None = None
    ) -> bool: ...

    async def get(
        self, form_id: str, *, tenant: str | None = None
    ) -> FormSchema | None: ...

    async def contains(
        self, form_id: str, *, tenant: str | None = None
    ) -> bool: ...

    async def list_forms(
        self, *, tenant: str | None = None
    ) -> list[FormSchema]: ...

    async def list_form_ids(
        self, *, tenant: str | None = None
    ) -> list[str]: ...

    async def clear(self, *, tenant: str | None = None) -> None:
        """Clears one tenant's forms only. Never aggregates."""

    async def clear_all(self) -> None:
        """Drops every tenant's forms. Test/maintenance only."""

    async def list_tenants(self) -> list[str]:
        """Sorted list of tenants that have at least one registered form."""

    async def load_from_directory(
        self,
        path: str | Path,
        *,
        recursive: bool = True,
        overwrite: bool = False,
        tenant: str | None = None,
    ) -> int: ...

    async def load_from_storage(self, *, tenant: str | None = None) -> int: ...

    def on_register(
        self, callback: Callable[[FormSchema], Awaitable[None]]
    ) -> None: ...

    def on_unregister(
        self, callback: Callable[[str, str], Awaitable[None]]
    ) -> None:
        """BREAKING: callback receives (form_id, tenant)."""

    def __contains__(self, item: tuple[str, str]) -> bool:
        """item = (tenant, form_id). Sync; raises TypeError on plain str."""
```

---

## 3. Module Breakdown

### Module 1: FormRegistry rewrite (core)
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py`
- **Responsibility**: Convert `self._forms` to `dict[str, dict[str, FormSchema]]`,
  introduce `default_tenant` / `require_tenant` constructor args, implement
  `_resolve_tenant()` helper, update `register / unregister / get / contains
  / list_forms / list_form_ids / clear` with `tenant=` kwarg, add `clear_all()`
  and `list_tenants()`, replace `__contains__` with tuple-aware version, update
  `__aiter__` deterministic ordering, update `on_unregister` callback signature
  and firing site. Keep the single `asyncio.Lock`.
- **Depends on**: nothing (foundational change).

### Module 2: `load_from_directory` tenant resolution
- **Path**: same file (`services/registry.py`).
- **Responsibility**: Add `tenant: str | None = None` kwarg. Per-file
  resolution: YAML `tenant:` wins; else kwarg; else `require_tenant`
  controls whether the file is skipped-with-warning or sealed to
  `default_tenant`. The `YamlExtractor` integration at line 290 may need to
  surface the YAML's `tenant:` so the registry can decide before calling
  `register()`.
- **Depends on**: Module 1.

### Module 3: Bulk YAML fixture tagger
- **Path**: `scripts/sdd/tag_yaml_fixtures.py` (new) + invocation/CI hook
  documented in script docstring.
- **Responsibility**: Walk `tests/forms/`, `packages/parrot-formdesigner/tests/`,
  `examples/forms/`, and any other locations discovered via
  `grep -L "^tenant:" packages/parrot-formdesigner/tests/**/*.yaml`. For each
  file lacking a top-level `tenant:` line, insert `tenant: navigator`. Idempotent.
- **Depends on**: Module 1 (default_tenant value), Module 2 (loader semantics).

### Module 4: Caller updates — handlers & routers
- **Paths**:
  - `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
    (lines 204, 253, 261, 270, 279, 350, 401, 429, 442, 474, 488, 494, 526)
  - `packages/parrot-formdesigner/src/parrot_formdesigner/ui/handlers.py`
    (lines 83, 122, 168, 206)
  - `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/telegram/router.py`
    (lines 99, 374, 422)
- **Responsibility**: Each `registry.get / list_forms / register / unregister
  / contains` call site is updated to pass `tenant=` resolved from the
  request / session / chat context. The exact tenant resolver per surface
  is defined in this task's review checklist.
- **Depends on**: Module 1.

### Module 5: Caller updates — tools, uploads, render, operations
- **Paths**:
  - `packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py`
    (line 213)
  - `packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py`
    (lines 306, 366)
  - `packages/parrot-formdesigner/src/parrot_formdesigner/api/uploads.py`
    (line 231)
  - `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py`
    (line 127)
  - `packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py`
    (lines 383, 459)
- **Responsibility**: Same as Module 4, for the tools/services/render/operations
  surfaces.
- **Depends on**: Module 1.

### Module 6: `on_unregister` callback consumers
- **Paths**: discovered via
  `grep -rn "registry\.on_unregister" packages/parrot-formdesigner/src`.
- **Responsibility**: Update every callback registered via
  `FormRegistry.on_unregister` to accept `(form_id, tenant)`. Audit the
  callback firing site in `registry.py` (currently line 216) to pass the
  tenant captured at the moment of `unregister()`.
- **Depends on**: Module 1.

### Module 7: Test suite
- **Paths**:
  - `packages/parrot-formdesigner/tests/unit/test_registry_multi_tenancy.py` (new)
  - Update affected existing tests in `packages/parrot-formdesigner/tests/`
    that exercise `FormRegistry` (search:
    `grep -rln "FormRegistry\|registry\." packages/parrot-formdesigner/tests/`).
- **Responsibility**: Verify two tenants with identical `form_id` are
  isolated; `tenant=None` strictly resolves to `default_tenant`; `list_tenants`
  returns sorted keys; `on_unregister` callbacks receive
  `(form_id, tenant)`; `__contains__` accepts `(tenant, form_id)` tuple and
  rejects plain `str` with `TypeError`; `load_from_directory` with mixed-tenant
  YAMLs populates `_forms[tenant]` correctly; `register()` with explicit
  `tenant=` overrides `form.tenant` and emits a warning log on mismatch.
- **Depends on**: Modules 1–6.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_register_isolates_same_form_id_across_tenants` | 1 | Two tenants register a form with identical `form_id`; both are retrievable independently. |
| `test_get_strict_tenant_resolution` | 1 | `get(form_id, tenant="epson")` returns `None` if the form is registered under `"pokemon"`. |
| `test_get_none_tenant_resolves_to_default` | 1 | `get(form_id)` with no kwarg resolves to `default_tenant="navigator"` and finds the form. |
| `test_register_explicit_kwarg_overrides_form_tenant` | 1 | `register(form_with_tenant_x, tenant="y")` stores under `"y"` and emits a warning. |
| `test_register_require_tenant_true_raises_on_missing` | 1 | `require_tenant=True`, `form.tenant=None`, no kwarg → `ValueError`. |
| `test_register_require_tenant_false_seals_to_default` | 1 | `require_tenant=False`, `form.tenant=None` → form lands under `default_tenant`. |
| `test_unregister_tenant_scoped` | 1 | `unregister(form_id, tenant="epson")` does not touch the same `form_id` under `"pokemon"`. |
| `test_list_forms_tenant_scoped` | 1 | `list_forms(tenant="epson")` returns only `"epson"` forms. |
| `test_clear_tenant_scoped` | 1 | `clear(tenant="epson")` empties only `"epson"`; `"pokemon"` survives. |
| `test_clear_all_drops_everything` | 1 | `clear_all()` empties every tenant. |
| `test_list_tenants_sorted` | 1 | `list_tenants()` returns sorted keys. |
| `test_list_tenants_empty_when_no_forms` | 1 | Empty registry → `list_tenants() == []`. |
| `test_contains_tuple_only` | 1 | `(tenant, form_id) in registry` works; `form_id in registry` raises `TypeError`. |
| `test_len_total_across_tenants` | 1 | `len(registry) == sum of inner-dict sizes`. |
| `test_aiter_deterministic_order` | 1 | Iteration yields forms in `(tenant, form_id)` sorted order. |
| `test_on_register_callback_receives_form` | 1 | `on_register` callbacks receive `FormSchema` with `.tenant` populated. |
| `test_on_unregister_callback_receives_tuple` | 6 | `on_unregister` callbacks receive `(form_id, tenant)`; updated signature. |
| `test_load_from_directory_yaml_tenant_wins` | 2 | YAML with `tenant: epson` overrides kwarg `tenant="navigator"`. |
| `test_load_from_directory_kwarg_default_used` | 2 | YAML without `tenant:` uses the kwarg. |
| `test_load_from_directory_skip_with_warning_on_missing` | 2 | YAML without `tenant:` AND no kwarg AND `require_tenant=True` → file skipped, warning logged. |
| `test_load_from_storage_per_tenant_no_overwrite` | 1 | Sequential `load_from_storage(tenant="epson")` then `load_from_storage(tenant="pokemon")` populates both. |
| `test_persist_routes_to_form_tenant` | 1 | `register(form_with_tenant_x, persist=True)` invokes `storage.save(..., tenant="x")`. |

### Integration Tests

| Test | Description |
|---|---|
| `test_handlers_pass_tenant_to_registry` | Exercise an aiohttp handler with a request that carries a tenant identifier; assert the registry lookup receives the same tenant. |
| `test_telegram_router_tenant_propagation` | A Telegram-routed form lookup uses the session's tenant. |
| `test_bulk_fixture_tagger_idempotent` | Run `scripts/sdd/tag_yaml_fixtures.py` twice; the second run produces no diff. |

### Test Data / Fixtures

```python
@pytest.fixture
def make_form():
    """Factory: build a minimal FormSchema with a configurable tenant."""
    def _build(form_id: str, tenant: str | None = None) -> FormSchema:
        ...
    return _build

@pytest.fixture
async def registry():
    """Default-config registry (default_tenant='navigator', require_tenant=True)."""
    return FormRegistry()

@pytest.fixture
async def lax_registry():
    """For tests that need the require_tenant=False seal-to-default behavior."""
    return FormRegistry(require_tenant=False)
```

---

## 5. Acceptance Criteria

> Feature is complete when ALL of the following are true:

- [ ] `FormRegistry._forms` is `dict[str, dict[str, FormSchema]]` keyed by
      `(tenant, form_id)`; no flat-`form_id` path remains in the source.
- [ ] `FormRegistry.__init__` accepts kwarg-only `default_tenant: str =
      "navigator"` and `require_tenant: bool = True`.
- [ ] `register / unregister / get / contains / list_forms / list_form_ids /
      clear / load_from_directory` accept a kwarg-only `tenant: str | None =
      None` parameter.
- [ ] `tenant=None` strictly resolves to `default_tenant` in every read path;
      no method aggregates across tenants when `tenant=None`.
- [ ] `register()` raises `ValueError` when `require_tenant=True` and the
      resolved tenant is `default_tenant` only because `form.tenant=None` and
      no explicit kwarg was supplied.
- [ ] `register()` with explicit `tenant=` overrides `form.tenant` and emits
      a `WARNING`-level log when the two differ.
- [ ] `list_tenants() -> list[str]` exists and returns the outer-dict keys
      sorted alphabetically.
- [ ] `clear_all()` exists and drops every tenant; `clear(tenant=None)`
      drops only `default_tenant`.
- [ ] `__contains__` accepts only `(tenant, form_id)` tuples; passing a
      plain `str` raises `TypeError`. `__aiter__` yields in
      `(tenant, form_id)` sorted order.
- [ ] `on_unregister` callback signature is
      `Callable[[str, str], Awaitable[None]]`; every in-tree consumer is
      updated; the firing site in `registry.py` passes the tenant captured
      at unregister time.
- [ ] `on_register` callback signature is unchanged.
- [ ] `load_from_directory` resolves tenant per file: YAML `tenant:` wins,
      kwarg supplies default, missing both AND `require_tenant=True` skips
      with a `WARNING` log.
- [ ] `load_from_storage(tenant=X)` lands results in `_forms[X]` and
      consecutive calls for different tenants do not overwrite each other.
- [ ] All caller sites listed in Modules 4–6 are updated and pass tenants
      explicitly. `grep -n "registry\.\(get\|contains\|unregister\)(" packages/parrot-formdesigner/src`
      returns zero calls without a `tenant=` kwarg (other than tests that
      verify the kwarg-default behavior).
- [ ] `scripts/sdd/tag_yaml_fixtures.py` runs to completion idempotently and
      every shipped YAML fixture under `packages/parrot-formdesigner/tests`
      and `examples/forms/` carries a `tenant:` field.
- [ ] `FormStorage` ABC and `PostgresFormStorage` source files have **zero**
      modifications in the resulting diff.
- [ ] Single `asyncio.Lock` continues to guard mutations; no per-tenant
      locks introduced.
- [ ] All unit tests pass (`pytest packages/parrot-formdesigner/tests/unit/ -v`).
- [ ] All integration tests pass
      (`pytest packages/parrot-formdesigner/tests/integration/ -v`).
- [ ] `ruff check packages/parrot-formdesigner/src` and
      `mypy packages/parrot-formdesigner/src` succeed.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** All references below were
> re-verified against the working tree at spec creation time. Implementing
> tasks MUST NOT reference imports, attributes, or methods absent from this
> section without verifying via `grep` or `Read` first.

### Verified Imports

```python
# Confirmed via packages/parrot-formdesigner/src/parrot_formdesigner/services/__init__.py:6-11
from parrot_formdesigner.services import FormRegistry, FormStorage      # __init__.py:8
from parrot_formdesigner.services import PostgresFormStorage            # __init__.py:9
from parrot_formdesigner.services import FormCache                      # __init__.py:6
from parrot_formdesigner.services import FormValidator, ValidationResult  # __init__.py:11

# Confirmed via core schema module

…(truncated)…
