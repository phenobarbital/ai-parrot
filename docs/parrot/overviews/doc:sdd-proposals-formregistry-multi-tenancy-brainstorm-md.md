---
type: Wiki Overview
title: 'Brainstorm: FormRegistry Multi-Tenancy'
id: doc:sdd-proposals-formregistry-multi-tenancy-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: is the in-memory cache for `FormSchema` objects. Its persistence layer
---

---
type: feature
base_branch: dev
---

# Brainstorm: FormRegistry Multi-Tenancy

**Date**: 2026-05-19
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`FormRegistry` (`packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py`)
is the in-memory cache for `FormSchema` objects. Its persistence layer
(`FormStorage` / `PostgresFormStorage`) is already tenant-aware — `save / load /
delete / list_forms` accept a `tenant=` kwarg that resolves to a Postgres schema
(`epson.form_schemas` vs `pokemon.form_schemas`), and `FormSchema.tenant: str |
None` exists in `core/schema.py:187`.

The gap is the registry's in-memory state. `self._forms: dict[str, FormSchema]`
(`registry.py:139`) is keyed only by `form_id`. Two tenants that share a
`form_id` (entirely plausible — e.g. `"customer-intake"` exists for both
`epson` and `pokemon`) collide: the second `register()` silently overwrites
the first. Read APIs (`get`, `contains`, `unregister`, `list_forms`,
`list_form_ids`, `clear`, `load_from_directory`) do not accept a tenant, so
even a correctly-persisted multi-tenant Postgres backend is fronted by a
tenant-blind cache that can leak forms across tenants in the same process.

This brainstorm explores how to make a single `FormRegistry` instance manage
forms scoped by tenant — i.e. the registry routes both writes AND reads by
`(tenant, form_id)`, never by `form_id` alone.

## Constraints & Requirements

- **Async-first**: must preserve the `asyncio.Lock` model in `registry.py`.
- **Storage layer untouched**: `FormStorage` ABC, `PostgresFormStorage`, and
  `FormSchema.tenant` already support multi-tenancy and stay as-is.
- **Hard cutover acceptable**: this feature mandates that every persisted /
  registered form carries a tenant. Forms in Postgres or YAML that still have
  `tenant=None` must be migrated to an explicit `"default"` tenant before the
  upgrade ships.
- **No implicit propagation**: tenant must be passed explicitly by every
  caller. No `ContextVar`, no thread-locals — the registry's API is the
  contract.
- **Strict `tenant=None` semantics**: `tenant=None` always means "the default
  tenant", never "any tenant". Cross-tenant aggregation is the caller's job
  via an explicit `list_tenants()` loop.
- **Async lock model preserved**: a single `asyncio.Lock` continues to guard
  all mutations. Per-tenant locks are out of scope (premature optimization).
- **~30 caller sites must be updated**: `api/handlers.py`, `ui/handlers.py`,
  `renderers/telegram/router.py`, `tools/database_form.py`,
  `tools/create_form.py`, `api/uploads.py`, `api/render.py`,
  `api/operations.py` — each `registry.get(form_id)` site needs to learn
  the tenant of the current request.
- **Breaking change documented**: `on_unregister` callback signature changes;
  callers must update their handlers.

---

## Options Explored

### Option A: Nested-Dict Registry, Explicit Tenant, Hard Cutover

The registry's internal state becomes `dict[str, dict[str, FormSchema]]`:
the outer key is `tenant`, the inner key is `form_id`. Every public method
that today takes `form_id` (or operates on all forms) gains a kwarg-only
`tenant: str | None = None` parameter — `None` resolves to the configured
default tenant name (e.g. `"default"`). A new constructor argument
`default_tenant: str = "default"` defines that name, and a separate boolean
`require_tenant: bool = True` controls whether `register()` accepts forms
with `form.tenant is None` (when `True`, they get sealed to `default_tenant`
in memory; when `False`, the registry refuses them). The `on_unregister`
callback signature changes from `Callable[[str], Awaitable[None]]` to
`Callable[[str, str], Awaitable[None]]` — every callback receives
`(form_id, tenant)`. A new helper `list_tenants() -> list[str]` lets admin
code iterate explicitly when it needs a cross-tenant view; no aggregating
helpers (`list_all_forms()`) are added — explicit looping is the only way.

`load_from_directory` gains `tenant: str | None = None`. If a YAML carries
its own `tenant:` field, that value wins; otherwise the kwarg supplies it;
if neither is present the load fails fast.

The ~30 caller sites are updated in the same PR — each must thread the
request tenant explicitly. A small `scripts/sdd/migrate_form_tenants.py`
backfills `tenant=NULL` rows in Postgres to `tenant='default'`.

✅ **Pros:**
- Matches all four Round 1 decisions exactly: explicit param, strict
  semantics, hard cutover, breaking callback.
- O(forms_of_tenant) for `list_forms(tenant=X)` and `clear(tenant=X)` —
  the nested layout is the natural shape for the recommended semantics.
- `list_tenants()` is `O(1)` (dict keys); no separate index to maintain.
- Tenant invariant is enforced at the registry boundary: a caller can't
  accidentally read another tenant's form (`get(form_id, tenant="epson")`
  only sees `_forms["epson"]`).
- No new dependencies. No magic. Reads exactly like the current code.

❌ **Cons:**
- Breaking change for every caller of `registry.get/contains/unregister/...`.
  ~30 sites to update in lockstep.
- `on_unregister` callback consumers must be updated in the same PR (small
  surface but still a breaking change in the public API).
- Forms in Postgres with `tenant=NULL` need a migration step before deploy.
- `__contains__` (sync, `registry.py:413`) can't grow a tenant kwarg without
  losing its sync nature — needs deprecation or replacement with the async
  `contains(form_id, tenant=...)`.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | All work uses stdlib `asyncio` + existing Pydantic models. |

🔗 **Existing Code to Reuse:**
- `services/registry.py:116-415` — `FormRegistry` class is rewritten in place;
  the locking, callbacks, and persistence-delegation patterns stay.
- `services/storage.py:97-110` — `_resolve_schema()` precedence is the
  conceptual template for `_resolve_tenant()` inside the registry.
- `core/schema.py:178-187` — `FormSchema.tenant` is the source of truth that
  the registry indexes by.
- `tests/unit/test_storage_schema_tenant.py` — pattern for verifying that
  same-id-different-tenant entries are isolated.

---

### Option B: ContextVar-Propagated Tenant, Soft Migration

Internal state still gets multi-tenant — same `dict[tenant][form_id]`
layout — but tenant propagation uses a `contextvars.ContextVar[str | None]`
set by an aiohttp middleware on the request boundary. Public methods grow
a kwarg-only `tenant: str | None = _UNSET` parameter that defaults to
"read the ContextVar". `require_tenant=False` is the default, so single-
tenant deploys keep working with `tenant=None`. The `on_unregister`
callback signature is extended via a parallel `on_unregister_v2(form_id,
tenant)` event; the old hook is marked deprecated but stays.

✅ **Pros:**
- The ~30 callers (`registry.get(form_id)`) compile and run unchanged —
  the middleware seeds the ContextVar and the registry resolves it.
- Backwards-compatible: existing single-tenant deploys see no behavior change.
- Soft migration path: roll out the registry, then opt-in `require_tenant=True`
  once all forms have been migrated.

❌ **Cons:**
- Implicit context. Background tasks (`asyncio.create_task`,
  `SubmissionForwarder`), scheduled jobs, and tests need to remember to
  set the ContextVar explicitly. Easy to forget, hard to debug.
- Violates the user's explicit Round 1 preference for explicit parameter
  passing and hard cutover.
- Two callback APIs (`on_unregister` + `on_unregister_v2`) is permanent debt.
- A bug where the ContextVar is unset means `get()` silently falls back to
  the default tenant — exactly the cross-tenant leak risk this feature is
  meant to close.
- Tests get harder: every test needs to set up the ContextVar or wrap calls
  with explicit kwargs.

📊 **Effort:** Low (registry side) / Medium (middleware + audit of background tasks)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `contextvars` (stdlib) | Async-safe tenant propagation | Built-in. |

🔗 **Existing Code to Reuse:**
- Same as Option A, plus an aiohttp middleware (not yet present — would be
  new code) in `parrot_formdesigner/api/middleware.py`.

---

### Option C: Tenant Registry Manager (Per-Tenant Sub-Registries)

Keep `FormRegistry` essentially single-tenant and introduce a new outer
class `TenantRegistryManager` that holds a `dict[str, FormRegistry]` — one
isolated registry per tenant. The manager exposes `for_tenant(tenant) ->
FormRegistry` and `list_tenants() -> list[str]`. All caller-facing code
goes through the manager: `manager.for_tenant("epson").get(form_id)`.

✅ **Pros:**
- The existing `FormRegistry` class barely changes — only `register()` needs
  a guard that `form.tenant` matches the registry it lives in.
- Strong isolation: a `FormRegistry` instance can never see another tenant's
  forms. Excellent locality of reasoning.
- Easy to reason about lifetime, locking, and shutdown per tenant.

❌ **Cons:**
- Still requires touching the ~30 callers to insert the
  `manager.for_tenant(...)` step — same breaking-change footprint as A.
- Persistence becomes awkward: one `PostgresFormStorage` shared by N
  `FormRegistry` instances, or N storages? Both have pitfalls (shared
  storage needs per-call `tenant=` regardless; per-tenant storage
  duplicates the connection pool).
- Adds a new top-level class to the public API; everywhere `registry` is
  injected today, callers now need either the manager or a tenant-bound
  registry, doubling the DI surface.
- Cross-tenant iteration is the manager's job; the per-tenant `FormRegistry`
  stays blind to its siblings. Fine for isolation, slightly more code for
  admin views.
- Diverges from the precedent set by `PostgresFormStorage`, which made
  multi-tenancy a property of a single instance (not a fleet of instances).

📊 **Effort:** Medium (new class + DI changes), comparable to A but spread differently.

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | Stdlib + existing models. |

🔗 **Existing Code to Reuse:**
- `services/registry.py:116-415` — `FormRegistry` is reused near-verbatim.
- `services/storage.py:55-91` — `PostgresFormStorage(tenant=...)` instance
  configuration is the model for the per-tenant pattern.

---

## Recommendation

**Option A** is recommended because it matches every explicit constraint
the user set in discovery:

- Explicit tenant params in every public method (Round 1).
- Strict `tenant=None` semantics, never aggregating (Round 1).
- Hard cutover with a migration script for legacy `tenant=NULL` rows (Round 1).
- Breaking `on_unregister(form_id, tenant)` callback (Round 1).
- Nested `dict[tenant][form_id]` layout — O(forms_per_tenant) for tenant-scoped
  ops, `list_tenants()` is `O(1)` (Round 2).
- YAML `tenant:` field wins, kwarg supplies a default, both missing fails fast
  (Round 2).
- No `list_all_forms()` helper — admin code must loop `list_tenants()`
  explicitly (Round 2).

Option B was rejected because the user explicitly chose explicit-param over
ContextVar, and hard cutover over a flag-gated migration. Implicit context
also reintroduces the very leak risk this feature exists to close — a
silent "fall back to default tenant" when the ContextVar isn't set.

Option C trades a smaller per-class change for a larger DI surface change.
It does not deliver materially better isolation than A's `dict[tenant][...]`
layout (which already makes cross-tenant access at the lookup level
impossible), and it diverges from the storage layer's "one instance, many
tenants" precedent — making the abstraction inconsistent at the package level.

The tradeoffs A accepts: ~30 caller updates in one PR, plus a small
migration script for legacy data. Both are mechanical, both are auditable
in code review, and both buy us a registry where tenant isolation is a
hard invariant rather than a runtime convention.

---

## Feature Description

### User-Facing Behavior

Application code that holds a single `FormRegistry` instance can serve any
number of tenants from the same process without cross-contamination. A
request handler that knows it's serving `epson` calls `await registry.get(
form_id, tenant="epson")` and is guaranteed never to see forms registered
under any other tenant. Conversely, attempting `registry.get(form_id,
tenant="pokemon")` for a form that only exists under `epson` returns `None`
even if the `form_id` matches.

YAML form definitions declare their owning tenant inline:

```yaml
form_id: customer-intake
tenant: epson
version: "1.0"
...
```

Administrative or maintenance code that needs a cross-tenant view iterates
explicitly:

```python
for tenant in await registry.list_tenants():
    forms = await registry.list_forms(tenant=tenant)
    ...
```

Single-tenant deployments continue to work by configuring the registry's
`default_tenant` (e.g. `"navigator"`) and either tagging every form with
that tenant in YAML/Postgres or relying on the registry to seal forms whose
`tenant` is `None` to the default at registration time (controlled by
`require_tenant`).

### Internal Behavior

The registry's state moves from `dict[str, FormSchema]` to
`dict[str, dict[str, FormSchema]]`. `register(form, persist=...)` resolves
the effective tenant via the precedence:

1. explicit `tenant=` kwarg on `register()` (if introduced for tests/admin)
2. `form.tenant`
3. registry's configured `default_tenant`

The resolved tenant is also passed to `self._storage.save(form, tenant=...)`,
preserving today's behavior of routing the write to the right Postgres
schema. `register()` raises `ValueError` if `require_tenant=True` and the
resolution yields the default tenant only because `form.tenant` was `None`
(i.e. the form did not declare an owner).

`get / contains / unregister` accept `tenant: str | None = None` (kwarg-only,
keyword-only via `*`). `None` resolves to `default_tenant`. The lookup is a
two-step dict access: `self._forms.get(tenant, {}).get(form_id)`. There is
no fallback to other tenants and no fuzzy matching.

`list_forms / list_form_ids` accept `tenant: str | None = None` and return
the values/keys of `self._forms[resolved_tenant]`. They do NOT aggregate
across tenants regardless of input.

`clear(tenant=None)` drops `self._forms[resolved_tenant]` only. A separate
`clear_all()` exists for tests; it is **not** triggered by `tenant=None`.

`load_from_directory(path, tenant=None, ...)` parses each YAML; if the YAML
contains a `tenant:` field, that wins; else the kwarg supplies the tenant;
if both are missing the file is skipped with a warning (or fails hard,
TBD — see Open Questions).

`load_from_storage(tenant=...)` is essentially unchanged behaviorally but
now lands its results in `self._forms[tenant]` instead of the flat dict,
so calling it for multiple tenants in sequence no longer overwrites.

`on_register(callback)` keeps its current signature (`Callable[[FormSchema],
Awaitable[None]]`) — the form already carries `.tenant`.
`on_unregister(callback)` changes to `Callable[[str, str], Awaitable[None]]`
where the second argument is the tenant of the unregistered form.

A new helper `list_tenants() -> list[str]` returns the outer-dict keys.

The single `asyncio.Lock` continues to guard all mutations. `__len__` returns
total count across all tenants. `__contains__` (sync) is deprecated — it
cannot grow a tenant parameter without breaking its sync contract; callers
should migrate to `await contains(form_id, tenant=...)`.

### Edge Cases & Error Handling

- **Same `form_id` across tenants**: explicitly supported. `register()`
  stores them in separate sub-dicts; no collision.
- **`form.tenant` mismatch with `tenant=` kwarg on `register()`**: the
  explicit kwarg wins, but the registry logs a warning when they differ
  (defends against accidental cross-tenant insert from edited YAML).
- **`tenant=None` with `require_tenant=True`**: `register()` raises
  `ValueError`. `get/contains/unregister/list_*` with `tenant=None` quietly
  resolve to `default_tenant`.
- **Unknown tenant on read**: `get / contains / list_forms / list_form_ids /
  clear` for a tenant that has zero registered forms returns `None` / `[]`
  / no-op. No error — the tenant simply has no forms yet.
- **`unregister()` of a form that exists under another tenant**: returns
  `False`. No fallback search.
- **`load_from_directory` with mixed-tenant YAMLs**: each file is processed
  independently; per-file failures don't abort the batch (current behavior
  preserved).
- **Migration of legacy `tenant=NULL` rows**: `scripts/sdd/migrate_form_tenants.py`
  rewrites NULL → `'default'` in the configured Postgres table(s) before
  upgrade. The script is idempotent.
- **Callback failures**: same as today — wrapped in try/except, logged at
  warning level, do not abort the registration/unregistration.

---

## Capabilities

### New Capabilities
- `formregistry-multi-tenancy`: a single `FormRegistry` instance that
  scopes in-memory state by `(tenant, form_id)`, with explicit tenant
  parameters on every public method, strict `tenant=None`-as-default
  semantics, and a cross-tenant introspection helper (`list_tenants()`).

### Modified Capabilities
- `form-abstraction-layer` (`sdd/specs/form-abstraction-layer.spec.md`):
  the registry contract within the abstraction layer changes shape.
  Downstream services and handlers must update.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `services/registry.py` | rewrites internals | New nested dict, new kwargs on public methods, new constructor args (`default_tenant`, `require_tenant`), new `list_tenants()`. |
| `services/__init__.py` | exports unchanged | `FormRegistry`, `FormStorage` already exported (lines 8, 16-17). |
| `api/handlers.py` (~10 call sites) | modifies | Each `registry.get/list_forms/register/unregister/...` site threads the request tenant. |
| `ui/handlers.py` (~5 sites) | modifies | Same as above. |
| `renderers/telegram/router.py` (3 sites at lines 99, 374, 422) | modifies | Tenant from session/chat metadata. |
| `tools/database_form.py` (line 213) | modifies | Tenant from tool execution context. |
| `tools/create_form.py` (lines 306, 366) | modifies | Tenant from tool execution context. |
| `api/uploads.py` (line 231) | modifies | Tenant from request. |
| `api/render.py` (line 127) | modifies | Tenant from request. |
| `api/operations.py` (lines 383, 459) | modifies | Tenant from request. |
| `on_unregister` callback consumers | **breaking** | Signature now `(form_id, tenant)`. Audit all callers in same PR. |
| Postgres legacy rows | data migration | One-shot script rewrites `tenant=NULL` → `tenant='default'`. |
| YAML form fixtures (tests + ops) | content migration | Each YAML must declare `tenant:` or be loaded via kwarg. |
| `tests/unit/test_storage_schema_tenant.py` | reference pattern | Source for registry-level tenant isolation tests. |

---

## Code Context

### User-Provided Code

None — the user described the design verbally during discovery; no code
snippets were pasted.

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:116
class FormRegistry:
    def __init__(self, storage: FormStorage | None = None) -> None:  # line 133
        self._forms: dict[str, FormSchema] = {}                       # line 139
        self._lock = asyncio.Lock()                                   # line 140
        self._storage = storage                                       # line 141
        self._on_register: list[Callable[[FormSchema], Awaitable[None]]] = []   # line 142
        self._on_unregister: list[Callable[[str], Awaitable[None]]] = []        # line 143
        self.logger = logging.getLogger(__name__)                     # line 144

    async def register(
        self, form: FormSchema, *, persist: bool = False, overwrite: bool = True
    ) -> None:                                                        # line 146-152
        ...
        # line 172:  await self._storage.save(form, tenant=form.tenant)

    async def unregister(self, form_id: str) -> bool:                 # line 199
    async def get(self, form_id: str) -> FormSchema | None:           # line 222
    async def list_forms(self) -> list[FormSchema]:                   # line 234
    async def list_form_ids(self) -> list[str]:                       # line 243
    async def contains(self, form_id: str) -> bool:                   # line 252
    async def clear(self) -> None:                                    # line 264
    async def load_from_directory(
        self, path: str | Path, *, recursive: bool = True, overwrite: bool = False
    ) -> int:                                                         # line 269-275
    async def load_from_storage(self, *, tenant: str | None = None) -> int:  # line 320
    def set_storage(self, storage: FormStorage) -> None:              # line 191
    @property
    def has_storage(self) -> bool:                                    # line 359-368
    @property
    def storage(self) -> "FormStorage | None":                        # line 370-380
    def on_register(self, callback: Callable[[FormSchema], Awaitable[None]]) -> None:    # line 382
    def on_unregister(self, callback: Callable[[str], Awaitable[None]]) -> None:         # line 392
    async def __aiter__(self):                                        # line 402
    def __len__(self) -> int:                                         # line 409
    def __contains__(self, form_id: str) -> bool:                     # line 413

# From packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:29
class FormStorage(ABC):
    @abstractmethod
    async def save(self, form: FormSchema, style: StyleSchema | None = None, *,
                   tenant: str | None = None) -> str: ...             # line 38-58
    @abstractmethod
    async def load(self, form_id: str, version: str | None = None, *,
                   tenant: str | None = None) -> FormSchema | None: ...# line 60-79
    @abstractmethod
    async def delete(self, form_id: str, *, tenant: str | None = None) -> bool: ...  # line 81-93
    @abstractmethod
    async def list_forms(self, *, tenant: str | None = None) -> list[dict[str, Any]]: ...  # line 95-113

# From packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:154
class FormSchema(BaseModel):
    form_id: str                                                      # line 178
    version: str = "1.0"                                              # line 179
    title: LocalizedString                                            # line 180
    description: LocalizedString | None = None                        # line 181
    sections: list[FormSection]                                       # line 182
    submit: SubmitAction | None = None                                # line 183
    cancel_allowed: bool = True                                       # line 184
    meta: dict[str, Any] | None = None                                # line 185
    created_at: datetime | None = None                                # line 186
    tenant: str | None = None                                         # line 187
```

#### Verified Imports

```python
# Confirmed via services/__init__.py:6-11
from parrot_formdesigner.services import FormRegistry, FormStorage    # __init__.py:8
from parrot_formdesigner.services import PostgresFormStorage          # __init__.py:9
from parrot_formdesigner.services import FormCache                    # __init__.py:6
from parrot_formdesigner.services import FormValidator                # __init__.py:11

# Confirmed via core schema module
from parrot_formdesigner.core.schema import FormSchema                # core/schema.py:154
```

#### Key Attributes & Constants

- `FormRegistry._forms` → `dict[str, FormSchema]` (`registry.py:139`)

…(truncated)…
