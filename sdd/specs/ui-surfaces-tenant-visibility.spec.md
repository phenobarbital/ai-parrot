---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Tenant-aware, permission-based visibility for UI surfaces

**Feature ID**: FEAT-535
**Date**: 2026-09-06
**Author**: Juan Ruffato (jfrruffato@trocglobal.com) + Claude
**Status**: approved (Juan, 2026-09-06 — the four design forks were decided in one Q&A round; §8 carries them as resolved)
**Target version**: not chosen by this spec. Work is based on `dev` and lands by PR; whoever cuts the release decides the number (the FEAT-528 convention).
**Reserved via**: `python -m scripts.sdd.reserve_ids --kind feature --count 1 --base-branch dev --label ui-surfaces-tenant-visibility` → `FEAT-535` (ledger commit on `origin/dev`, 2026-09-07T03:19Z). The same session also reserved `TASK-2926..2931` in this ledger as a MIRROR of ids FieldSync had already claimed for its FEAT-562 (the two repos share one TASK-id space; this ledger did not know about them and would have handed them out again).
**No brainstorm in this repo**: the problem and the four design decisions were worked through in FieldSync's `sdd/proposals/fieldsync-reporting-recipe.brainstorm.md` (FEAT-562) and its Q&A with Juan on 2026-09-06. This spec records them; it does not reopen them.
**Downstream consumer**: FieldSync — `fieldsync/surfaces.py` (FEAT-559) today stamps a program into `recipe_params` and filters lists in Python because parrot's row has no tenant column and its listing is owner-only; FEAT-562's program report is visible only to its seeder for the same reason. When this lands, FieldSync retires that wrapper's list filter, supplies a `SurfaceScopeResolver` built on its tenancy seam, and backfills the column from the stamp (FieldSync follow-up feature, see §8).

---

## 1. Motivation & Business Requirements

### Problem Statement

`navigator.ui_surfaces` (FEAT-492) knows exactly one principal per surface:
its owner. `PgUISurfaceStore.list` is `WHERE user_id = $1`; direct access is
owner-or-share-token (`resolve_surface_access`); the only way a second person
sees a surface is a minted share token they must be handed out of band.

That model fits a personal pin ("save this chart for me"). It does not fit a
**program dashboard**: FieldSync seeds one A2UI report per tenant
(`fieldsync-program-report`, FEAT-562) that every admin and manager of that
program should see in their reporting page without anybody mailing them a
link. Today the surface is visible to `user_id=36522` and to nobody else.

FieldSync already worked around the missing tenant: it stamps the program
into `recipe_params` (`fieldsync_tenant`) and filters parrot's owner-scoped
list in Python (`ProgramScopedSurfaceStore`). That wrapper cannot widen the
list beyond the owner — the SQL underneath is fixed — and it puts a tenancy
concern in a JSON blob because the table has no column for it. Both are
symptoms of the same gap: **parrot has no notion of who, besides the owner,
may see a surface.**

Juan, 2026-09-06: *"hagamos un spec para parrot en el cual podamos incorporar
la funcionalidad para que podamos otorgar acceso a visibilidad a través de
permisos que usamos en fieldsync, usando tenant como usamos en el resto, con
una capa de permisos pero que sea tenant aware."*

### Goals

- A surface carries a **tenant** and a **visibility** (`private` | `tenant` |
  `groups`) plus an `allowed_groups` list, as real columns on
  `navigator.ui_surfaces`, added idempotently by `ensure_schema()`.
- Listing returns what the caller **owns**, what was **shared** with them by
  token, and what is **visible** to them by tenant or group — in one call,
  tagged by access kind.
- Direct access (`GET`, `?format=html`, `refresh`) honours the same rule:
  a tenant/group-visible surface is readable AND refreshable by its viewers;
  delete, share and visibility changes stay owner-only.
- A **superuser** sees every surface of the tenant declared for the request.
  Never cross-tenant in one listing.
- The caller's identity, tenant, groups and superuser flag come from a
  **host-pluggable `SurfaceScopeResolver`** stored on the app. The default
  reads the navigator-auth session (`user_id`, `programs`, `groups`,
  `superuser`) and resolves a tenant ONLY when the session carries exactly
  one program; a multi-program host (FieldSync) supplies its own resolver
  (its URL-declared program). The tenant is NEVER taken from a request body.
- The owner sets visibility on save (`POST /api/v1/ui/surfaces`) and later
  with a new `PATCH /api/v1/ui/surfaces/{surface_id}`.
- Fully backward compatible: existing rows read as `visibility='private'`,
  `tenant=NULL`; existing clients sending no new fields behave exactly as
  today; the `A2UIHandler` mirror route stays consistent with the REST lane.
- Bonus asked for by FieldSync's FEAT-559 review: the surface metadata block
  also exposes `recipe_name` and `recipe_params`.

### Non-Goals (explicitly out of scope)

- Per-user ACLs on surfaces (the `handlers/agents/sharing.py` scaffold's
  concern). Groups are the unit here, not users.
- Changing share tokens: mint/resolve/claim/revoke and `list_shared_with`
  are untouched; a token still opens a surface from any tenant (FieldSync's
  standing decision).
- Cross-tenant listings, "all tenants" views, or org hierarchies.
- Any FieldSync code. FieldSync's resolver, wrapper retirement and backfill
  are a FieldSync feature that depends on this one (§8).
- Migrating FieldSync's `recipe_params.fieldsync_tenant` stamp inside parrot.
  parrot ships the column; the host backfills its own stamp.
- Row-level security on the recipe's DATA (that is `DatasetManager`
  PBAC/RLS, FEAT-228) — this spec is about who sees the rendered surface.
- The agent chat/RPC lanes (`AgentTalk`, `A2UIHandler` beyond its
  surface-GET mirror).

---

## 2. Architectural Design

### Overview

Three additive layers, all inside `ai-parrot-server`:

1. **Schema + store** (`handlers/models/ui_surfaces.py`). Three columns
   appended through `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements in
   `_DDL_STATEMENTS` (the live-migration idiom already used by
   `models/bots.py:573-577`), one index on `(tenant, visibility)`.
   `UISurfaceRecord` gains `tenant`, `visibility`, `allowed_groups`;
   `save`/`_row_to_record`/`_UPSERT_SQL` carry them. Two new store methods:
   `list_visible(scope, *, kind=None)` (owner ∪ tenant-visible ∪
   group-visible ∪ superuser-in-tenant, one SQL) and
   `update_visibility(surface_id, user_id, visibility, allowed_groups)`
   (owner-only `WHERE user_id = $2`). `list` and `list_shared_with` stay as
   they are.

2. **Scope resolution** (new `handlers/ui_surfaces_scope.py`). A frozen
   `SurfaceScope(user_id, tenant, groups, is_superuser)`, a
   `SurfaceScopeResolver` protocol (`async resolve(request) -> SurfaceScope`),
   the default `SessionSurfaceScopeResolver`, and
   `get_scope_resolver(app)` reading `app["ui_surfaces_scope_resolver"]`
   (falling back to the default). The default resolver reuses the existing
   identity plumbing (`_get_user_id` / `parrot.auth.session_identity.resolve_user_id`)
   and reads `programs`, `groups`, `superuser` from
   `session[AUTH_SESSION_OBJECT]` — type-checked (`list`/`bool`), never
   truth-checked (the FieldSync Rule-6 lesson: a `Mock` answers `.get()`
   with a truthy `Mock`). `tenant` is `programs[0]` only when
   `len(programs) == 1`; otherwise `None`, which makes every tenant/group
   rule evaluate to "no match" and keeps owner-only behaviour for hosts that
   did not opt in.

3. **Access rule + handler** (`handlers/ui_surfaces.py`, `handlers/a2ui.py`).
   `resolve_surface_access(store, surface_id, user_id, token, *, scope=None)`
   adds one branch after owner and before token: `scope_grants(record, scope)`
   → `(record, None)`. Both callers pass the resolved scope. `_get_list`
   calls `list_visible` + `list_shared_with` and tags each row
   `access: "owner" | "tenant" | "shared"` (owner wins on duplicates; a
   token-shared surface that is ALSO tenant-visible is reported once as
   `tenant`). `PublishSurfaceRequest` gains `visibility` and
   `allowed_groups`; the handler sets `record.tenant = scope.tenant` and
   rejects `visibility != private` with `422` when the scope has no tenant.
   New `patch` verb on the existing `/{surface_id}` view → `_patch_visibility`
   (owner-only, `404` otherwise — no existence oracle). `_surface_metadata`
   adds `tenant`, `visibility`, `allowed_groups`, `recipe_name`,
   `recipe_params`. Refresh keeps its existing rule — the replay runs under
   the OWNER's `PermissionContext` (`build_principal_context(record.user_id)`)
   for viewers exactly as it does for share bearers today.

No route is added (`PATCH` dispatches on the existing
`/api/v1/ui/surfaces/{surface_id}` view; `manager.py:2060-2064` unchanged).
No new dependency.

### Component Diagram

```
request ──► UISurfacesHandler (BaseView, @is_authenticated @user_session)
              │  scope = await get_scope_resolver(app).resolve(request)      ← host may install its own
              │            SurfaceScope(user_id, tenant, groups, is_superuser)
              ├─ GET  /ui/surfaces            ─► store.list_visible(scope, kind) ∪ store.list_shared_with(user_id) ─► access tags
              ├─ GET  /ui/surfaces/{id}       ─► resolve_surface_access(store, id, user_id, token, scope=scope) ─► negotiation
              ├─ POST /ui/surfaces            ─► record.tenant = scope.tenant; visibility/allowed_groups from body ─► store.save
              ├─ POST /ui/surfaces/{id}/refresh ─► same access rule; RecipeRunner under owner pctx (unchanged)
              ├─ PATCH /ui/surfaces/{id}      ─► store.update_visibility(id, user_id, visibility, allowed_groups)  (owner-only)
              └─ DELETE / share mint / revoke ─► unchanged, owner-only
A2UIHandler._get_surface (mirror) ──► resolve_surface_access(..., scope=scope)   ← same rule, cannot drift

navigator.ui_surfaces  + tenant VARCHAR(63) NULL · visibility VARCHAR(16) NOT NULL DEFAULT 'private' · allowed_groups JSONB NOT NULL DEFAULT '[]'
                        + INDEX ix_ui_surfaces_tenant_visibility (tenant, visibility)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `PgUISurfaceStore` (`handlers/models/ui_surfaces.py`) | extends | columns, record fields, `list_visible`, `update_visibility`; `list`/`list_shared_with`/shares untouched |
| `_DDL_STATEMENTS` | extends | three `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` + one `CREATE INDEX IF NOT EXISTS`, tolerated by the existing "already exists" race guard |
| `UISurfacesHandler` (`handlers/ui_surfaces.py`) | modifies | scope per request, list union, save fields, new `patch`, metadata |
| `resolve_surface_access` (module-level, shared) | modifies (additive kwarg) | `scope: SurfaceScope \| None = None` |
| `A2UIHandler._get_surface` (`handlers/a2ui.py:265-290`) | modifies | passes `scope`; otherwise unchanged |
| `parrot.auth.session_identity.resolve_user_id`, `navigator_auth.conf.AUTH_SESSION_OBJECT`, `navigator_session.get_session` | uses | default resolver identity + userinfo |
| `app["ui_surfaces_scope_resolver"]` | new app key | host injection point beside `ui_surfaces_store` / `ui_surfaces_negotiation` |
| `docs/frontend/agentdashboard-a2ui-reference.md` §3.4, §7 tables; `docs/postman/a2ui-agentdashboard.postman_collection.json` folder "3. UI surfaces" | modifies | new fields, `access` values, `PATCH` |
| `manager.py:2060-2064` | none | `PATCH` rides the existing `/{surface_id}` view |

### Data Models

```python
# handlers/models/ui_surfaces.py (additions)
class SurfaceVisibility(str, Enum):
    private = "private"   # owner + share tokens (today's behaviour, the default)
    tenant = "tenant"     # every caller whose scope.tenant == record.tenant
    groups = "groups"     # tenant match AND scope.groups ∩ allowed_groups ≠ ∅

class UISurfaceRecord(BaseModel):
    ...existing fields...
    tenant: str | None = None                                  # NEW — set by the server from SurfaceScope, never from a body
    visibility: SurfaceVisibility = SurfaceVisibility.private   # NEW
    allowed_groups: list[str] = Field(default_factory=list)    # NEW — group NAMES as the auth session spells them
```

DDL appended to `_DDL_STATEMENTS` (after the two `CREATE TABLE`s):

```sql
ALTER TABLE navigator.ui_surfaces ADD COLUMN IF NOT EXISTS tenant VARCHAR(63);
ALTER TABLE navigator.ui_surfaces ADD COLUMN IF NOT EXISTS visibility VARCHAR(16) NOT NULL DEFAULT 'private';
ALTER TABLE navigator.ui_surfaces ADD COLUMN IF NOT EXISTS allowed_groups JSONB NOT NULL DEFAULT '[]'::jsonb;
CREATE INDEX IF NOT EXISTS ix_ui_surfaces_tenant_visibility ON navigator.ui_surfaces (tenant, visibility);
```

The `CREATE TABLE IF NOT EXISTS` statement ALSO lists the three columns, so a
fresh database gets them in one statement and an existing one through the
`ALTER`s (both idempotent). `_INSERT_SQL`/`_UPSERT_SQL`/`_GET_SQL` gain the
three columns; `_LIST_SQL`, `_LIST_BY_KIND_SQL`, `_LIST_SHARED_WITH_SQL` are
derived from `_GET_SQL` and pick them up automatically.

Visibility SQL (one statement, parameters `$1 user_id`, `$2 tenant`,
`$3 groups::text[]`, `$4 is_superuser`, optional `$5 kind`):

```sql
SELECT <columns> FROM navigator.ui_surfaces
WHERE user_id = $1
   OR ($2::text IS NOT NULL AND tenant = $2 AND (
          visibility = 'tenant'
       OR (visibility = 'groups' AND allowed_groups ?| $3::text[])
       OR $4::boolean))
ORDER BY updated_at DESC
```

`tenant IS NULL` on the row or `$2 IS NULL` on the caller never matches the
second branch — a surface without a tenant is private no matter its
`visibility`, and a caller without a tenant sees only what they own or hold
a token for.

### New Public Interfaces

```python
# handlers/ui_surfaces_scope.py (NEW)
@dataclass(frozen=True)
class SurfaceScope:
    user_id: str | None
    tenant: str | None
    groups: frozenset[str]
    is_superuser: bool = False

class SurfaceScopeResolver(Protocol):
    async def resolve(self, request: web.Request) -> SurfaceScope: ...

class SessionSurfaceScopeResolver:
    """Default: navigator-auth session. tenant = programs[0] iff exactly one program."""
    async def resolve(self, request: web.Request) -> SurfaceScope: ...

def get_scope_resolver(app: web.Application) -> SurfaceScopeResolver     # app["ui_surfaces_scope_resolver"] or the default
def scope_grants(record: UISurfaceRecord, scope: SurfaceScope) -> bool   # pure: tenant/groups/superuser rule, owner excluded

# handlers/models/ui_surfaces.py (additions)
class PgUISurfaceStore:
    async def list_visible(self, scope: SurfaceScope, *, kind: UISurfaceKind | None = None) -> list[UISurfaceRecord]
    async def update_visibility(self, surface_id: str, user_id: str, visibility: SurfaceVisibility, allowed_groups: list[str]) -> bool

# handlers/ui_surfaces.py (changes)
class PublishSurfaceRequest(BaseModel):
    ...existing...
    visibility: SurfaceVisibility = SurfaceVisibility.private   # NEW
    allowed_groups: list[str] = Field(default_factory=list)    # NEW  (no `tenant` field — server-set)

class PatchVisibilityRequest(BaseModel):                        # NEW  body of PATCH /api/v1/ui/surfaces/{id}
    visibility: SurfaceVisibility
    allowed_groups: list[str] = Field(default_factory=list)

async def resolve_surface_access(store, surface_id, user_id, token, *, scope: SurfaceScope | None = None)  # additive kwarg

class UISurfacesHandler(BaseView):
    async def patch(self) -> web.Response          # NEW verb → _patch_visibility
```

HTTP contract (additive):

| Verb | Path | Change |
|---|---|---|
| `GET` | `/api/v1/ui/surfaces[?kind=]` | items now include tenant/group-visible surfaces; `access` ∈ `owner \| tenant \| shared`; metadata adds `tenant`, `visibility`, `allowed_groups`, `recipe_name`, `recipe_params` |
| `GET` | `/api/v1/ui/surfaces/{id}[?share=][&format=]` | visible-by-scope callers get `200` (JSON or HTML) instead of `404` |
| `POST` | `/api/v1/ui/surfaces` | body may carry `visibility`, `allowed_groups`; `tenant` set from scope; `422` when `visibility != private` and the scope has no tenant; `400` on an unknown visibility |
| `POST` | `/api/v1/ui/surfaces/{id}/refresh` | allowed for visible-by-scope callers (same as share bearers); replay under owner pctx (unchanged) |
| `PATCH` | `/api/v1/ui/surfaces/{id}` | NEW; owner-only; body `PatchVisibilityRequest`; `200` with metadata, `404` non-owner/unknown, `422` tenant rule as above |
| `DELETE`, share mint/resolve/claim/revoke | unchanged | |
| `GET` | `/api/v1/agents/{agent_id}/a2ui/surfaces/{id}` (mirror) | same access rule via `scope` |

---

## 3. Module Breakdown

### Module 1: Schema, record and store
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py`, `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_store.py`
- **Responsibility**: `SurfaceVisibility`; three record fields; DDL (`CREATE TABLE` column list + `ALTER ... ADD COLUMN IF NOT EXISTS` ×3 + index) appended to `_DDL_STATEMENTS`; `_INSERT_SQL`/`_UPSERT_SQL`/`_GET_SQL` extended (`allowed_groups` as `$N::jsonb` with `json.dumps`, decoded by the existing `_decode_jsonb`); `_row_to_record` reads the three columns with safe defaults (`visibility` falls back to `private`, `allowed_groups` to `[]`) so a row written before this feature still loads; `list_visible(scope, *, kind)` and `update_visibility(...)` with the SQL in §2; `save` writes the new columns. Real-Postgres tests (the file's existing `pg_store` fixture and skip idiom): `ensure_schema` idempotent on a table created by the OLD DDL (create it with the pre-feature statement first, then run `ensure_schema()` → columns present); old row loads as private; `list_visible` matrix (owner / tenant / groups hit / groups miss / superuser / caller without tenant / row without tenant); `update_visibility` owner-only.
- **Depends on**: nothing.

### Module 2: Scope resolution
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces_scope.py` (new), `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_scope.py` (new)
- **Responsibility**: `SurfaceScope`, `SurfaceScopeResolver`, `SessionSurfaceScopeResolver`, `get_scope_resolver`, `scope_grants`. The default resolver: `user_id` via the same path `_get_user_id` uses (promote that helper here, or import `resolve_user_id`); `userinfo = session.get(AUTH_SESSION_OBJECT)` must be a `dict`; `programs`/`groups` must be `list`/`tuple` of `str` (else empty); `superuser` must be `bool` (else `False`); `tenant = programs[0] if len(programs) == 1 else None`. Tests build the request with `aiohttp.test_utils.make_mocked_request` and install a REAL session dict the way navigator_session stores it (`request[SESSION_OBJECT]`), never a `Mock` with attributes — see the module docstring rationale ("what does this return for a request with nothing set?" → `SurfaceScope(None, None, frozenset(), False)`). `scope_grants` is a pure function with a truth table test.
- **Depends on**: Module 1 (types only).

### Module 3: Access rule and handler
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py`, `packages/ai-parrot-server/src/parrot/handlers/a2ui.py`, `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_handler.py`, `packages/ai-parrot-server/tests/handlers/test_a2ui_surfaces_route.py`, `packages/ai-parrot-server/tests/integration/test_ui_surfaces_e2e.py`
- **Responsibility**: `resolve_surface_access(..., scope=)`; handler resolves the scope once per request (`self._scope()`), `_get_list` = `list_visible` ∪ `list_shared_with` with dedupe and `access` tags; `_pin_save` sets `tenant` from scope and validates the tenant rule (`422`); new `patch` → `_patch_visibility` (owner-only via the store's `WHERE user_id`; `404` when zero rows); `_surface_metadata` adds the five fields; `_refresh` unchanged except that access now flows through the scope-aware rule; `A2UIHandler._get_surface` passes its scope (resolved with the same `get_scope_resolver(app)`). Tests extend the existing `fake_store` suite: list tags, `422` on tenant-less publish with `visibility=tenant`, `PATCH` owner/non-owner, viewer `GET`/`refresh` `200`, viewer `DELETE` `404`, and — mutation-checked — reverting `scope_grants` makes the viewer tests RED.
- **Depends on**: Modules 1, 2.

### Module 4: Documentation and collection
- **Path**: `docs/frontend/agentdashboard-a2ui-reference.md` (§3.4 surfaces API table at :236-237, §7), `docs/postman/a2ui-agentdashboard.postman_collection.json` (folder "3. UI surfaces": `PATCH` request, `visibility` fields on the pin request), `CHANGELOG` entry if the repo keeps one for `ai-parrot-server`.
- **Responsibility**: document the three columns, the `access` values, the `PATCH` verb, the host hook (`app["ui_surfaces_scope_resolver"]`, with the FieldSync example: URL-declared program + session groups), the default resolver's single-program rule, and the back-compat statement.
- **Depends on**: Modules 1–3.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_ensure_schema_adds_columns_to_pre_feature_table` | 1 | create the table with the OLD `CREATE TABLE`, run `ensure_schema()`, assert the three columns + index exist; second run is a no-op |
| `test_old_row_loads_as_private` | 1 | insert a row without the new columns' values → `visibility == private`, `tenant is None`, `allowed_groups == []` |
| `test_list_visible_matrix` | 1 | owner-only caller; tenant-visible row for same tenant / other tenant; groups hit / miss; superuser same tenant sees private rows of others; caller with `tenant=None` sees only owned; row with `tenant=None` never visible to others |
| `test_update_visibility_owner_only` | 1 | owner → `True` and row updated; other user → `False`, row unchanged |
| `test_default_resolver_empty_request` | 2 | `make_mocked_request` with nothing set → `SurfaceScope(None, None, frozenset(), False)` |
| `test_default_resolver_reads_session_dict` | 2 | real session dict with `programs=["epson"]`, `groups=[...]`, `superuser=True` → scope filled; `programs` of length 2 → `tenant None` |
| `test_default_resolver_type_checks` | 2 | `programs="epson"` (str) → ignored; `superuser="yes"` → `False` |
| `test_scope_grants_truth_table` | 2 | every combination of visibility × tenant match × groups × superuser; owner excluded (owner handled upstream) |
| `test_list_union_and_access_tags` | 3 | owned + tenant-visible + token-shared → tags `owner`/`tenant`/`shared`; duplicate reported once as `tenant` |
| `test_pin_visibility_requires_tenant_422` | 3 | scope without tenant + `visibility=tenant` → `422`; with tenant → `201` and `record.tenant == scope.tenant` |
| `test_pin_ignores_body_tenant` | 3 | body carrying a `tenant` key is not honoured (pydantic ignores; record tenant is the scope's) |
| `test_patch_owner_200_non_owner_404` | 3 | owner changes visibility; non-owner gets `404` and nothing changes |
| `test_viewer_get_and_refresh_200_delete_404` | 3 | tenant-visible viewer reads JSON and HTML, refreshes (owner pctx used — assert `build_principal_context(record.user_id)`), cannot delete |
| `test_mirror_route_uses_scope` | 3 | `A2UIHandler` GET for a tenant-visible viewer → `200` |
| `test_metadata_exposes_recipe_fields` | 3 | `recipe_name`, `recipe_params`, `tenant`, `visibility`, `allowed_groups` present in list and GET metadata |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_tenant_visibility_roundtrip` (extends `tests/integration/test_ui_surfaces_e2e.py`) | pin as user A with `visibility=tenant` under tenant T (resolver stub installed on the app); list as user B in T → present with `access=tenant`; GET + refresh as B → `200`; list as user C in tenant U → absent; PATCH to `groups` with `["g1"]`; B with `groups=["g1"]` sees it, B with `["g2"]` does not; superuser in T sees it regardless |

### Test Data / Fixtures
```python
# Scope stubs for handler tests: install on the app under the same key the handler reads
class _StubResolver:
    def __init__(self, scope: SurfaceScope): self._scope = scope
    async def resolve(self, request): return self._scope
app["ui_surfaces_scope_resolver"] = _StubResolver(SurfaceScope("u2", "epson", frozenset({"epson_fieldsync_manager"}), False))

# Default-resolver tests: real request + real session dict, never Mock attributes
req = make_mocked_request("GET", "/api/v1/ui/surfaces")
req[SESSION_OBJECT] = {AUTH_SESSION_OBJECT: {"user_id": 36522, "programs": ["epson"], "groups": ["epson_fieldsync_admin"], "superuser": False}}
```

---

## 5. Acceptance Criteria

- [ ] `ensure_schema()` on a database that already has the pre-feature `ui_surfaces` table adds `tenant`, `visibility`, `allowed_groups` and the index; running it again is a no-op; a fresh database gets the same shape
- [ ] Rows written before this feature load as `visibility=private`, `tenant=NULL`, `allowed_groups=[]`, and every pre-existing test in `test_ui_surfaces_store.py`, `test_ui_surfaces_handler.py`, `test_a2ui_surfaces_route.py`, `test_ui_surfaces_e2e.py` still passes unchanged in intent
- [ ] A client that sends no new fields observes exactly today's behaviour (owner-only list, owner-or-token access)
- [ ] `GET /api/v1/ui/surfaces` returns owned ∪ shared ∪ scope-visible with `access` ∈ `owner|tenant|shared`, deduplicated
- [ ] A tenant/group-visible viewer can `GET` (JSON and HTML) and `POST .../refresh`; cannot `DELETE`, mint shares or `PATCH` (`404`, no oracle)
- [ ] A superuser sees every surface whose `tenant` equals the scope's tenant, and nothing from other tenants
- [ ] `tenant` is never read from a request body; `visibility != private` without a scope tenant → `422`
- [ ] `PATCH /api/v1/ui/surfaces/{id}` changes visibility/groups for the owner only
- [ ] The default resolver returns an empty scope for a bare `make_mocked_request` and a filled one for a real session dict; it resolves a tenant only for a single-program session; it type-checks every value it reads
- [ ] `app["ui_surfaces_scope_resolver"]` overrides the default for both handlers (REST lane and A2UI mirror) — proven by the e2e test with a stub resolver
- [ ] `_surface_metadata` includes `tenant`, `visibility`, `allowed_groups`, `recipe_name`, `recipe_params`
- [ ] Reverting `scope_grants` (return `False`) turns the viewer tests RED; reverting the `WHERE user_id` in `update_visibility` turns the non-owner `PATCH` test RED — evidence in the completion notes
- [ ] Docs and Postman updated (Module 4); `ruff`/`flake8` clean on changed files; no new dependency

---

## 6. Codebase Contract

> Verified 2026-09-06 against `origin/dev` `3d03bb2cd` (post v1.0.0). Line numbers are from `git show origin/dev:<path>`.

### Verified Imports
```python
from navigator.views import BaseView                                        # ui_surfaces.py:24
from navigator_auth.conf import AUTH_SESSION_OBJECT                          # ui_surfaces.py:25
from navigator_auth.decorators import is_authenticated, user_session         # ui_surfaces.py:26
from navigator_session import get_session                                    # ui_surfaces.py:27  (SESSION_OBJECT also exported by navigator_session — the request-dict key)
from parrot.auth.permission import build_principal_context                   # ui_surfaces.py:28 ; permission.py:166
from parrot.auth.session_identity import resolve_user_id, resolve_session_user   # session_identity.py:90, :56
from parrot.handlers.models.ui_surfaces import PgUISurfaceStore, UISurfaceRecord, UISurfaceKind, UISurfaceShare  # models/ui_surfaces.py:351,49,41,72
from parrot.handlers.ui_surfaces import resolve_surface_access, UISurfacesHandler, SurfaceNegotiationService, _get_user_id, _surface_metadata  # :138,:272,:175,:97,:127
from aiohttp.test_utils import make_mocked_request                           # tests
```

### Existing Class Signatures
```python
# packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py
class UISurfaceKind(str, Enum)                                               # :41
class UISurfaceRecord(BaseModel):                                            # :49-69  surface_id, kind, title, envelope, catalog_id, agent_id, user_id, session_id, recipe_name, recipe_owner, recipe_params, created_at, updated_at; @property refreshable (:66)
class UISurfaceShare(BaseModel)                                              # :72
_DDL_STATEMENTS: list[str]                                                   # :89-127  CREATE SCHEMA; CREATE TABLE ui_surfaces (13 cols); 2 indexes; CREATE TABLE ui_surface_shares; 2 indexes
_INSERT_SQL / _INSERT_OR_SKIP_SQL / _UPSERT_SQL                              # :131-157  13 positional params ($4 and $11 are ::jsonb)
_GET_SQL                                                                     # :159-164  column list; _LIST_SQL/_LIST_BY_KIND_SQL derived via .replace (:166-170)
_LIST_SHARED_WITH_SQL                                                        # :172-182
_UPDATE_ENVELOPE_SQL / _DELETE_SQL (WHERE surface_id=$1 AND user_id=$2)      # :184-195
def _decode_jsonb(raw) -> dict                                               # :232
def _row_to_record(row) -> UISurfaceRecord                                   # :254-272  dict(row) → explicit field mapping (extend here)
def _as_uuid(value) -> uuid.UUID | None ; def _require_uuid(value)           # :309, :321
async def _exec(conn, sql, *args) ; async def _fetch_rows(conn, sql, *args) # :329, :337  (asyncdb quirks handled here — reuse, never call conn.execute for writes directly)
class PgUISurfaceStore:                                                      # :351
    DEFAULT_SHARE_TTL_DAYS = 90
    def __init__(self, dsn: str | None = None)                               # :357  default parrot.conf.default_dsn
    def _get_db(self) -> AsyncDB                                             # :361  AsyncDB("pg", dsn=self.dsn)
    async def ensure_schema(self) -> None                                    # :369  iterates _DDL_STATEMENTS via _exec; tolerates "already exists"
    async def save(self, record, *, overwrite=False) -> str                  # :397
    async def get(self, surface_id) -> UISurfaceRecord | None                # ~:430  conn.fetch_one(_GET_SQL, uuid)
    async def list(self, user_id, *, kind=None) -> list[UISurfaceRecord]     # :447  OWNER-SCOPED
    async def list_shared_with(self, user_id) -> list[UISurfaceRecord]       # :456
    async def update_envelope(self, surface_id, envelope, recipe_params)     # :466
    async def delete(self, surface_id, user_id) -> bool                      # :477  WHERE user_id = $2
    async def mint_share(self, surface_id, *, expires_at=None, use_default_ttl=False) -> UISurfaceShare   # :487
    # resolve_share / claim_share / revoke_share / list_shares follow

# packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py
class PublishSurfaceRequest(BaseModel)                                       # :58-77  kind, title, envelope, source_artifact_id, agent_id, session_id, recipe_name, recipe_owner, recipe_params
class RefreshSurfaceRequest(BaseModel): params: dict                         # :79-82
class MintShareRequest(BaseModel): expires_at, ttl                           # :85-89
async def _get_user_id(request) -> str | None                                # :97-124  request.user.user_id/id → session[AUTH_SESSION_OBJECT]["user_id"] → session["user_id"]
def _surface_metadata(record) -> dict                                        # :127-136  surface_id, kind, title, refreshable, created_at, updated_at, catalog_id, agent_id  (EXTEND)
async def resolve_surface_access(store, surface_id, user_id, token) -> tuple[record|None, (msg,status)|None]   # :138-167  owner → ok; token → resolve/claim or 410; else 404
class SurfaceNegotiationService                                              # :175  negotiate(request) / respond(record, accept) / _respond_html
@is_authenticated() @user_session() class UISurfacesHandler(BaseView)       # :270-272
    store (property, app["ui_surfaces_store"])                               # :287-292
    negotiation (property, app["ui_surfaces_negotiation"])                   # :295-300
    async def _user_id(self) -> str | None                                   # :310
    def _error(self, message, *, status=400) -> web.Response                 # :313-327  json_response directly (BaseView.error() whitelist landmine — keep using this)
    async def get(self) / post(self) / delete(self)                          # :329-354  dispatch by match_info / path suffix  (ADD patch)
    async def _resolve_surface_for_access(self, surface_id, user_id, token)  # :356-378  wraps resolve_surface_access
    async def _get_one(self, surface_id, user_id)                            # :379  ?share= token → negotiation
    async def _get_list(self, user_id)                                       # :388-410  401 without user; ?kind=; owned + shared; access tags
    async def _pin_save(self)                                                # :412-490  builds UISurfaceRecord(... user_id=user_id, recipe_params=req.recipe_params ...) at :471-483
    async def _refresh(self)                                                 # :491-560  access via _resolve_surface_for_access; 409 if not refreshable; merged_params = {**stored, **req.params} (:520); owner_pctx = build_principal_context(record.user_id, channel="ui_surfaces") (:533); runner.run(...) ; store.update_envelope (:554)
    async def _mint_share(self) / _delete_surface / _revoke_share            # :561-620  owner-only (404 otherwise)

# packages/ai-parrot-server/src/parrot/handlers/a2ui.py
    def _ui_surfaces_store(self) -> PgUISurfaceStore                         # :243-251  shares app["ui_surfaces_store"]
    async def _get_surface(self) -> web.Response                             # :265-290  _authenticate → user_id; resolve_surface_access(store, surface_id, user_id, token); negotiation.respond

# packages/ai-parrot-server/src/parrot/manager/manager.py
router.add_view("/api/v1/ui/surfaces", UISurfacesHandler)                    # :2060  … :2064 (/{surface_id}, /refresh, /share, /share/{token}) — PATCH needs NO new route

# packages/ai-parrot-server/src/parrot/handlers/models/bots.py
ALTER TABLE navigator.prompt_library ADD COLUMN IF NOT EXISTS agent_id VARCHAR;   # :573-575  the live-migration idiom inside a DDL string

# packages/ai-parrot/src/parrot/auth/session_identity.py
def resolve_session_user(request) -> Any | None                              # :56   AuthUser on request.user
def resolve_user_id(request, session=None) -> str | None                     # :90   normalizes Identity.id to str; falls back to session keys under AUTH_SESSION_OBJECT
# packages/ai-parrot/src/parrot/auth/permission.py
class UserSession: user_id: str; tenant_id: str; roles: frozenset[str]; metadata  # :21-40
class PermissionContext                                                      # :81
def build_principal_context(principal, channel, tenant_id=None, roles=None) -> PermissionContext   # :166
# packages/ai-parrot/src/parrot/auth/userinfo.py
class EmployeeProfile(BaseModel): ... groups: list[str] = []; programs: list[str] = []   # :43-75  (loaded from auth.vw_users by UserInfoService — a DB path; the default resolver reads the SESSION instead, no DB)

# navigator-auth session shape (fieldsync verification 2026-09-06): session[AUTH_SESSION_OBJECT] is a dict with "user_id", "programs": list[str], "groups": list[str], "superuser": bool  (navigator_auth/conf.py:269,342-343)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SessionSurfaceScopeResolver.resolve` | `get_session(request)`, `session[AUTH_SESSION_OBJECT]`, `resolve_user_id` | calls | ui_surfaces.py:97-124; session_identity.py:90 |
| `get_scope_resolver(app)` | `app["ui_surfaces_scope_resolver"]` | app key (new) beside `ui_surfaces_store` | ui_surfaces.py:287-300 |
| `resolve_surface_access(..., scope=)` | `scope_grants(record, scope)` | new branch between owner and token | ui_surfaces.py:158-167 |
| `UISurfacesHandler.patch` | `store.update_visibility` | new verb on the existing view | manager.py:2061 |
| `_get_list` | `store.list_visible(scope, kind)` + `store.list_shared_with(user_id)` | replaces `store.list(user_id, kind)` | ui_surfaces.py:400-401 |
| `_pin_save` | `UISurfaceRecord(tenant=scope.tenant, visibility=req.visibility, allowed_groups=req.allowed_groups)` | record construction | ui_surfaces.py:471-483 |
| `A2UIHandler._get_surface` | `resolve_surface_access(..., scope=await get_scope_resolver(app).resolve(request))` | kwarg | a2ui.py:284 |
| `_DDL_STATEMENTS` | `ensure_schema` loop with "already exists" tolerance | appended statements | models/ui_surfaces.py:369-395 |

### Does NOT Exist (Anti-Hallucination)
- ~~a `tenant`, `program`, `visibility` or `metadata` column on `navigator.ui_surfaces`~~ — 13 columns today (models/ui_surfaces.py:96-110); this feature adds three.
- ~~`PgUISurfaceStore.list_by_tenant` / `list_visible` / `update_visibility`~~ — new in Module 1.
- ~~a `SurfaceScope`/`SurfaceScopeResolver` anywhere in parrot~~ — new in Module 2. Do not confuse with `parrot.auth.permission.PermissionContext`/`UserSession` (PBAC for tools/data, not surface visibility) or with `EmployeeProfile` (DB-loaded profile).
- ~~`patch` on `UISurfacesHandler`~~ — only `get`/`post`/`delete` exist (ui_surfaces.py:329-354).
- ~~`request.session` attribute~~ — the session is a request-dict entry (`request[SESSION_OBJECT]`, read through `get_session(request)`); an attribute-only double must resolve to an EMPTY scope.
- ~~`UISurfaceShare.permissions` values other than `"read+refresh"`~~ — `Literal` (models/ui_surfaces.py:77); viewer rights mirror it, no new literal.
- ~~a per-user ACL on surfaces~~ — `handlers/agents/sharing.py` is a `NotImplementedError` scaffold for AGENTS, unrelated.
- ~~`fieldsync_tenant` / `_fieldsync_program` handling in parrot~~ — FieldSync's stamp; parrot never reads it.
- ~~a route registration for PATCH~~ — aiohttp `View` dispatches any verb to a same-named coroutine on the existing `/{surface_id}` view.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- DDL as strings in `_DDL_STATEMENTS`, executed through `_exec` with the existing race tolerance — never a separate migration file (parrot-owned DDL is lazy, FEAT-492 decision recorded in FieldSync's runbook §5).
- Writes go through `_exec`/`fetchval`, reads through `_fetch_rows`/`fetch_one`, exactly as the surrounding methods do — the asyncdb `execute` swallows errors and the uuid codec rejects `str` (the FEAT-528 review findings, commit `ebd85d55e`); pass `_require_uuid(surface_id)`.
- `allowed_groups` travels as `json.dumps(list)` into `::jsonb` and back through `_decode_jsonb` — same regime as `recipe_params`.
- Error responses through `self._error(...)` (direct `json_response`), never `BaseView.error()` (status whitelist landmine, ui_surfaces.py:313-327).
- Type-check what you read out of the session `Mapping`; never truth-check it.
- Owner-only mutations are enforced IN SQL (`WHERE user_id = $2`) as `delete` already does, not by comparing in Python after a read.
- Tests: `fake_store` fixture pattern for the handler (test_ui_surfaces_handler.py:131-160), real Postgres for the store (test_ui_surfaces_store.py:182-229 skip idiom), `make_mocked_request` + real session dict for the resolver.

### Known Risks / Gotchas
- **`allowed_groups ?| $3::text[]`** requires `$3` to be a Postgres text array; asyncpg accepts a Python `list[str]` for `text[]` — pass `list(scope.groups)`, never a JSON string. Covered by the matrix test on a real database.
- **Empty groups**: `?|` with an empty array is `false`, and a `groups`-visible surface with an empty `allowed_groups` is visible to nobody but the owner — intended; document it.
- **Two lists, one dedupe**: a surface both token-shared and tenant-visible appears in both queries; the handler dedupes by `surface_id` (visible wins over shared, owner wins over both).
- **Default resolver and multi-program sessions**: `tenant=None` for >1 program by design; a host with URL-declared tenants MUST install a resolver or its users see owner-only lists. Documented in Module 4 with the FieldSync example.
- **`CREATE TABLE` + `ALTER` both listing the columns**: harmless (`IF NOT EXISTS` on both); the `ALTER ... NOT NULL DEFAULT` on an existing populated table is a metadata-only change in PostgreSQL ≥ 11 — no rewrite.
- **Refresh by a viewer runs under the owner's pctx**: same as share bearers today (ui_surfaces.py:533); the owner is the one entitled to the data. Documented, not changed.
- **A2UI mirror route** authenticates through `_authenticate()` (agent-scoped); the scope resolver is called in addition, with the same request — do not derive tenant from `agent_id`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| none new | — | pydantic, aiohttp, asyncdb, navigator-auth/-session already dependencies of `ai-parrot-server` |

---

## 8. Open Questions

- [x] Storage of tenant + visibility — *Resolved (Juan, 2026-09-06)*: real columns (`tenant`, `visibility`, `allowed_groups`) via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`; not a metadata JSONB blob.
- [x] What a tenant/group viewer may do — *Resolved (Juan, 2026-09-06)*: read AND refresh (same as a share token); delete/share/visibility stay owner-only.
- [x] Superuser — *Resolved (Juan, 2026-09-06)*: sees every surface of the DECLARED tenant; never cross-tenant.
- [x] Who sets visibility — *Resolved (Juan, 2026-09-06)*: the owner, on save and later via `PATCH /ui/surfaces/{id}`; the server always sets `tenant` from the scope resolver, never from a body.
- [x] Default resolver tenant rule — *Resolved by design here*: `programs[0]` only when the session has exactly one program (the `programs[0]` convention was the FEAT-366 failure in FieldSync; hosts with URL tenants install their own resolver).
- [ ] **FieldSync follow-up feature** (in `fieldsync`, after this lands): `FieldsyncSurfaceScopeResolver` (tenant = `declared_programme(request)`, groups/superuser from `resolve_session_authorization`), installed under `app["ui_surfaces_scope_resolver"]` in `fieldsync/surfaces.py`; retire `ProgramScopedSurfaceStore`'s Python list filter (keep the stamp on save until the backfill is verified); one-off backfill `UPDATE navigator.ui_surfaces SET tenant = recipe_params->>'fieldsync_tenant' WHERE tenant IS NULL AND recipe_params ? 'fieldsync_tenant'`; seed scripts save with `visibility=tenant`; navigator-svelte shows the `tenant` access badge. — *Owner: Juan + Claude*
- [ ] **Group naming**: `allowed_groups` holds group NAMES as the auth session spells them (FieldSync: `<program>_fieldsync_admin`, `<program>_fieldsync_manager`). If a deployment's session carries group IDs instead, the host resolver must map them — confirm when the first non-FieldSync host adopts this. — *Owner: Jesús*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-06 | Juan + Claude | Initial spec; decisions from the FEAT-562 Q&A; approved same day |
