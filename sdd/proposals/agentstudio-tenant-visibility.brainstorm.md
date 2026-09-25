---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot-server, ai-parrot]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [agentstudio, multi-tenant, visibility, byok, pbac]
---

<!-- LANGUAGE: This document MUST be written entirely in English (proper nouns keep native spelling). -->

# Brainstorm: Agent Studio — Tenant Scope & Owner-Controlled Visibility

**Date**: 2026-09-24
**Author**: Juan Ruffato (with Claude)
**Status**: exploration
**Recommended Option**: A (revised — registry/YAML metadata is the Agent
Studio agent system of record)

> **Follow-up to** FEAT-467 `agentstudio-management` (the `/api/v1/astudio/*`
> control plane, PR #1255) and FEAT-535 `ui-surfaces-tenant-visibility`
> (PR #1332), whose scope mechanism this brainstorm proposes to generalise.
> **Downstream consumer**: FieldSync (companion brainstorm in the FieldSync
> repository: `sdd/proposals/fieldsync-agentstudio.brainstorm.md`). That file
> is not present in this checkout. This document therefore defines the
> required FieldSync resolver and mount contract; the companion must adopt it
> before integration is approved.
>
> **Relation to FEAT-598** (`a2ui-linked-surfaces`, draft): checked — it makes
> `tenant` a field of a surface's data-source descriptor and explicitly lists
> tenant-membership authorization and `ui_surfaces` DDL as non-goals. It does
> not cover agents/astudio. No spec on any pushed ref (961 `origin` refs swept
> 2026-09-24) proposes tenant columns for `ai_bots` / `studio_drafts` /
> `ai_skills_catalog` or a tenant-aware Agent Studio. **To confirm with Jesus**
> whether he has an unpublished local draft on this (recorded as an external
> integration prerequisite below).

---

## Problem Statement

Agent Studio (FEAT-467, extended by FEAT-593) is a single global namespace:

- `GET /api/v1/astudio/agents` lists **every** DB and registry agent to any
  authenticated user — there is no owner or tenant filter on reads
  (`studio/agents.py:196-207`). Ownership is enforced only on mutating verbs
  (`_require_owner`, `studio/_base.py:230`), with superuser bypass.
- None of the three Studio tables carries a tenant or a visibility notion:
  `navigator.ai_bots` has `created_by INTEGER` (`models/bots.py:92`),
  `navigator.studio_drafts` has `owner_user_id` (`models/studio_drafts.py:52`),
  `navigator.ai_skills_catalog` has `owner` (`models/skills_catalog.py:38`).
  The skills catalog's "org-wide" scope exists only as a Redis namespace
  `"<org_id>/_shared"` with `DEFAULT_ORG_ID = "default"`
  (`studio/skills_catalog.py:41-48`) — there is no org column.
- `StudioUser` (`studio/_base.py:102-118`) has `user_id`, `groups`,
  `is_superuser` — no tenant.
- PBAC (`_pbac_gate`, `astudio:<area>`) is fail-open when `app['abac']` is
  absent — which is the case in FieldSync.

A multi-tenant host (FieldSync: one tenant per programme — flexroc, epson,
pokemon, …) cannot offer Agent Studio to its users without every programme
seeing and being able to test every other programme's agents, drafts and
skills. The desired model, decided by the FieldSync owner (2026-09-24):

1. Studio-managed agents belong to a **tenant** (programme), including the
   normal FEAT-467 registry/YAML creation and draft-activation paths.
2. **Any entitled user** of the tenant may create agents — who may author is
   **configurable per tenant** by the host.
3. The **owner decides visibility**: `private` (only me), `tenant` (whole
   programme) or `groups` (named groups within the programme).
4. **BYOK with fallback** to the organisation's key.

The same problem was already solved for UI surfaces by FEAT-535 (`tenant`,
`visibility`, `allowed_groups` columns + a host-pluggable scope resolver),
which FieldSync consumes today (`fieldsync/surfaces.py`). Agent Studio should
not invent a second, divergent mechanism.

## Constraints & Requirements

- **Resolved default-host compatibility rule.** When no scope resolver is
  installed, Studio preserves FEAT-467's current list-all/read behavior and
  does not expose sharing controls. When a resolver is installed but resolves
  no tenant (zero/several programmes), it is an opted-in tenant host and gets
  owner-only reads; non-private creates/patches return 422. This deliberately
  differs from a silent behavior change for existing single-tenant installs.
- **Tenant is always server-set** — never read from a request body (same
  invariant as `ui_surfaces.py:566`). A non-`private` visibility without a
  tenant answers 422 (same as `ui_surfaces.py:512`, `:686`).
- **Never cross-tenant**: superuser widens visibility only *within* the
  resolved tenant (`scope_grants`, `ui_surfaces_scope.py:171-198`).
- **Owner-only visibility changes** (mirrors `_UPDATE_VISIBILITY_SQL`,
  `models/ui_surfaces.py:243-248`: `WHERE … AND user_id = $2`).
- **One scope seam for the whole server**: Studio reads the neutral resolver
  key first and falls back to FieldSync's existing surface-resolver key.
  FieldSync updates its existing resolver once to the extended contract; it
  does not install a separate Studio resolver.
- **Idempotent DDL** in the same idiom as `models/ui_surfaces.py:149-151`
  (`ALTER TABLE … ADD COLUMN IF NOT EXISTS`) — no data migration for
  existing rows (they stay `tenant NULL`, `visibility 'private'`).
- **Control-plane containment**: an agent a caller cannot see in Studio must
  not be reachable through *any* Agent Studio agent-addressed route, including
  test sessions and FEAT-593 overrides. Existing non-Studio chat routes remain
  unchanged by this feature; this feature must describe itself as Studio
  control-plane visibility, never as a global runtime-tenant authorization
  boundary.
- Async-first, Pydantic models for every payload, `navigator.views` CBVs
  (existing Studio conventions).

---

## Options Explored

### Option A: Generalise FEAT-535's server scope + persist visibility in each actual Studio system of record

Lift the FEAT-535 scope primitives into the server-neutral
`parrot.handlers.scope` module, not `parrot.auth` (the resolver depends on
aiohttp/navigator-session). It defines `RequestScope(user_id, tenant, groups,
is_superuser, may_author=True)`, the resolver Protocol, the default session
resolver, `get_scope_resolver(app)`, and the primitive-only
`scope_grants(*, tenant, visibility, allowed_groups, scope)`. Visibility is a
validated string (`private|tenant|groups`) at this seam; it must not import
`UISurfaceRecord` or `SurfaceVisibility`. `ui_surfaces_scope.py` re-exports
the compatible names and adapts its surface enum/record call.

Persist `tenant VARCHAR(63)`, `visibility VARCHAR(16) NOT NULL DEFAULT
'private'`, and `allowed_groups JSONB NOT NULL DEFAULT '[]'::jsonb` on the
three PostgreSQL resources: `navigator.ai_bots`, `navigator.studio_drafts`,
and `navigator.ai_skills_catalog`, with a `(tenant, visibility)` index each.
Add corresponding asyncdb fields and idempotent `ALTER TABLE ... ADD COLUMN
IF NOT EXISTS` statements. Existing rows are legacy (`tenant NULL`, private).

For FEAT-467's **primary agent path**, persist the same server-stamped values
in `BotMetadata.bot_config.config` under reserved keys `tenant`, `visibility`,
and `allowed_groups`, alongside the existing `created_by`. `POST /agents`
creates registry/YAML metadata, not an `ai_bots` row; draft activation imports
a Python module and stamps registry metadata, also not an `ai_bots` row. The
lossless FEAT-467 YAML serializer must retain these keys. A database-origin
agent instead reads the three table columns. A shared access service converts
either storage shape into one `StudioVisibilityRecord`; handlers must never
infer tenant state from an absent `ai_bots` row.

`StudioBaseView` resolves the scope once per request through the same app
key FieldSync already installs (`app["ui_surfaces_scope_resolver"]`, or a new
neutral `app["scope_resolver"]` that falls back to it). Then:

- **Create** stamps the applicable system of record with
  `tenant = scope.tenant` (server-set) and visibility from the body (`private`
  by default; non-private requires a tenant → 422). Client-supplied reserved
  metadata keys are rejected/overwritten before registry/YAML persistence.
- **List/read** filter with the `_LIST_VISIBLE_SQL` shape
  (`models/ui_surfaces.py:223-237`): mine OR (same tenant AND
  (tenant-visible OR groups-intersect OR superuser)). Registry/YAML agents
  use the same rule against their reserved metadata; only pre-existing
  metadata-less agents are legacy (see Edge Cases).
- **New verb** `PATCH /astudio/agents/{name}/visibility` (and the same for
  `/drafts/{name}` and `/skills/{id}`), owner-only.
- **Authoring gate**: `RequestScope.may_author` is computed by the host;
  `POST /agents`, `POST /drafts`, `POST /skills`, and the write-capable
  assistant flow answer 403 `authoring_denied` when it is false. The default
  is `True`. A legacy FieldSync resolver without the field remains readable
  through the default, but FieldSync must add its programme-specific rule
  before relying on authoring denial.
- **Optional tenant-in-URL mount**: `setup_studio_routes(app,
  prefix=STUDIO_PREFIX)` registers one mount only. A FieldSync mount uses
  `/api/v1/{tenant}/astudio`; the FieldSync resolver validates membership and
  resolves that tenant, while the Studio base view rejects a declared/resolved
  mismatch with 403 `tenant_mismatch` before accessing any record.

✅ **Pros:**
- One mechanism for surfaces and agents; FieldSync changes its existing
  resolver once to return the extended `RequestScope` rather than acquiring a
  second resolver.
- All three sharing levels (`private`/`tenant`/`groups`) come for free —
  the SQL, enum and rule already exist and are tested.
- Filtering happens in SQL, not by hosts re-filtering JSON responses.
- Single-tenant hosts see no change (`tenant NULL` everywhere).

❌ **Cons:**
- Touches three tables and ~6 handler modules (agents, drafts, files,
  skills_catalog, testing, toolkits/toolkit_config).
- Registry/YAML metadata needs a versioned, reserved-key persistence contract.
- Names remain globally unique for agents, drafts, and skills in v1. A
  collision in any tenant returns the same non-enumerating `409 name_taken`;
  no endpoint reveals the owning tenant. This is required by the existing
  registry, global draft filesystem paths, and `UNIQUE(name)` catalog schema.
- Moving the scope module is a small refactor of already-merged FEAT-535
  code (re-exports keep it non-breaking).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` / `datamodel` | `BotModel`, `StudioDraft`, `SkillCatalogEntry` models | already used; only new fields |
| `navigator-auth` | session userinfo (`programs`, `groups`, `superuser`) | already used by `_base.py` |
| `pydantic` | `VisibilityUpdateRequest` payload | already used by Studio models |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces_scope.py` — `SurfaceScope`, `SurfaceScopeResolver`, `SessionSurfaceScopeResolver`, `get_scope_resolver`, `scope_grants`.
- `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py` — `SurfaceVisibility` enum, idempotent ALTERs, `_LIST_VISIBLE_SQL`, `_UPDATE_VISIBILITY_SQL`.
- `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` — `_patch_visibility` (:648) and the 422 rules (:512, :686) as the verb template.
- `packages/ai-parrot-server/src/parrot/handlers/studio/_base.py` — `StudioUser`, `_get_user`, `_require_owner`.

---

### Option B: Encode tenant & visibility into the existing `ai_bots.permissions` PBAC rules (FEAT-153)

No new columns. Studio translates `visibility` into `permissions` rules on
the bot (`agent:resolve` allow for `programs:<tenant>` or `groups:[…]`), and
`GET /agents` filters by evaluating each bot's rules against the caller.

✅ **Pros:**
- No DDL on `ai_bots`; runtime chat resolution (`agent_guard`) enforces
  the same rules automatically — Studio and chat stay in parity.

❌ **Cons:**
- `studio_drafts` and `ai_skills_catalog` have no `permissions` column — the
  problem is only solved for one of three tables.
- Listing must load and evaluate every bot in Python (no SQL filter).
- Tenant becomes an interpretation of opaque rules; "which programme owns
  this agent?" has no direct answer (no index, no simple query).
- Collides with rules authors write by hand in `permissions` today.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth` PBAC | rule evaluation | fail-open without a PDP |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/handlers/models/bots.py:225-240` — `permissions` field and its rule format.

---

### Option C: Pluggable Studio store — hosts implement scoping

Parrot defines a `StudioStore` Protocol (list/get/create/update for agents,
drafts, skills) with the current behaviour as default implementation, and
lets a host inject its own (like `PgUISurfaceStore` is injected for
surfaces). FieldSync would implement a tenant-scoped store.

✅ **Pros:**
- Maximum host freedom (a host could map tenants to its own tables).
- Parrot stays tenant-agnostic.

❌ **Cons:**
- Every multi-tenant host reimplements the same filtering — exactly the
  duplication FEAT-535 removed for surfaces.
- Studio handlers currently query `BotModel`/`StudioDraft`/registry
  directly; extracting a store interface is a larger refactor than A.
- Visibility semantics would diverge per host.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | — | no new packages |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py` — `PgUISurfaceStore` as the injection precedent.

---

### Option D (unconventional): Schema-per-tenant Studio tables

Point `PARROT_SCHEMA` per request at the tenant's schema
(`<tenant>.ai_bots`, `<tenant>.studio_drafts`, …), matching FieldSync's own
schema-per-tenant layout.

✅ **Pros:**
- Hard isolation; per-tenant name uniqueness for free.

❌ **Cons:**
- `AgentRegistry` and `BotManager` are process-global and keyed by name;
  schema switching does nothing for them.
- `PARROT_SCHEMA` is a module constant (`conf.py`), not request-scoped;
  every model binds its schema at class definition.
- Superuser cross-tenant views, migrations × N schemas, and the shared
  skills catalog all get harder.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | per-schema connections | would need request-scoped schema binding |

🔗 **Existing Code to Reuse:**
- none directly.

---

## Recommendation

**Option A** is recommended because:

- It reuses a mechanism that is already merged, tested and consumed by the
  same host (FEAT-535 → FieldSync `FieldSyncSurfaceScopeResolver`). The
  host plugs in once and both surfaces and agents obey the same rule.
- It covers all three Studio tables with SQL-side filtering, where B covers
  one table with Python-side filtering and C pushes the work to every host.
- All three sharing levels requested (`private`/`tenant`/`groups`) exist in
  the FEAT-535 enum and SQL already.

What we trade off: names remain globally unique across agents, drafts and
skills in v1, so tenants cannot independently reuse a slug. In exchange,
visibility is correct for both database-origin and the normal registry/YAML
Agent Studio paths. This is a Studio control-plane boundary; a tenant-aware
`BotManager.get_bot` contract for non-Studio chat routes remains a separate
feature rather than an unstated security guarantee here.

---

## Feature Description

### User-Facing Behavior

(API consumers — the UI lives in host frontends.)

- Creating an agent/draft/skill in a tenant-scoped session stamps the
  caller's tenant automatically in its actual system of record. Agent
  registry/YAML metadata carries the fields; database agents, drafts, and
  skills use their table columns. The response carries `tenant` and
  `visibility`.
- `GET /astudio/agents`, `/drafts`, `/skills` return only what the caller
  owns, plus what their tenant shares with them (`tenant`, or `groups` they
  belong to). Superusers see everything **in their tenant**.
- Each listed item carries `owner`, `tenant`, `visibility`,
  `allowed_groups`, and an `access` tag (`owner` | `tenant` | `groups` |
  `superuser`) so a UI can render "shared with me" vs "mine".
- `PATCH …/visibility {visibility, allowed_groups?}` — owner-only; `groups`
  requires a non-empty `allowed_groups`; non-private requires a tenant.
- Non-owners with visibility can read and test a shared agent, read a shared
  draft, and import a shared skill, but cannot modify, delete, activate or
  reload. Agent asset-file contents and agent/toolkit configuration remain
  owner-only because they may disclose implementation or secret-adjacent
  data. A user may manage their own `/toolkits/{slug}/me` override only after
  the target agent passes the visibility gate.
- When the host denies authoring for the caller's tenant, `POST` answers
  403 `authoring_denied`.
- A host may mount the same API under `/api/v1/{tenant}/astudio/*`.

### Internal Behavior

1. `StudioBaseView` resolves and caches one `RequestScope` per request,
   exposes its tenant/authoring state on `StudioUser`, and verifies a URL
   tenant when present.
2. PostgreSQL models gain three fields each. Registry-created and
   draft-activated agents receive the matching reserved configuration keys;
   no path assumes an `ai_bots` row exists.
3. Database lists use visible-row SQL; registry lists apply the same pure
   rule to metadata. Single reads and every agent-addressed derivative route
   apply the shared access service and answer **404** when invisible.
4. Write paths retain owner checks; creation and write-capable assistant
   operations also check `may_author`.
5. Draft activation propagates the draft's tenant/visibility/groups into the
   newly registered `BotMetadata.bot_config.config`, then persists the
   activated draft row with the same values.
6. Skill import requires a visible skill and an owner-controlled target
   agent. Skill registry dual-write/reconciliation retains the catalog row's
   tenant metadata as the authorization source; it never treats the shared
   Redis namespace as an authorization grant.
7. The visibility gate covers Agent Studio agent reads, test ask/test stop,
   files (owner-only after existence resolution), tool assignment, toolkit
   assignment/configuration, MCP configuration, and FEAT-593 per-user
   overrides. `/tools/{slug}/execute` has no agent identifier and remains a
   PBAC-only global tool endpoint; it must not be claimed as an agent
   visibility enforcement point.
8. BYOK: unchanged per-user lookup (`resolve_user_api_key`,
   `studio/byok.py:55`). When no user key is stored, the agent's configured
   client is used (`testing.py:305-308`) — i.e. **the fallback to the
   organisation's key already exists**. Per-tenant key slots, quota, and
   usage attribution are explicitly excluded and tracked as a follow-up.

### Edge Cases & Error Handling

- **Session with several programmes and no tenant in URL** → default
  resolver yields `tenant=None` → owner-only; non-private visibility → 422.
- **Tenant declared in URL ≠ resolved tenant** → 400/403 (host seam decides;
  parrot rejects the mismatch).
- **Legacy rows/metadata** (`tenant NULL`) → in an opted-in tenant host,
  visible only to their owner; ownerless legacy registry/code agents are
  hidden. In a host with no resolver, the unchanged FEAT-467 global listing
  remains available and no visibility PATCH is offered.
- **Registry (YAML/code) agents** → Studio-created/persisted and activated
  agents have reserved metadata and are scopeable. Pre-existing ownerless
  registry/code agents follow the legacy rule above; there is no host flag
  that can accidentally make them tenant-visible.
- **Owner leaves the tenant / is removed from a group** → the row keeps its
  tenant; the ex-owner loses access through the resolver, not by mutation.
- **Name collision across tenants** (agents, drafts, or skills) → 409
  `name_taken` without revealing which tenant owns it.
- **Visibility downgraded while another user has a live test session** →
  the next `test/ask` re-checks visibility and answers 404.
- **Skill imported, then un-shared** → the copy in the agent's `skills/`
  dir stays (it is a copy, by FEAT-467 design); documented, not revoked.

---

## Capabilities

### New Capabilities
- `request-scope-server`: record-agnostic server scope dataclass, resolver
  Protocol, default session resolver and primitive-only `scope_grants`, lifted
  from FEAT-535 with compatibility re-exports.
- `astudio-tenant-columns`: `tenant` / `visibility` / `allowed_groups` on `ai_bots`, `studio_drafts`, `ai_skills_catalog` (+ idempotent DDL, indexes).
- `astudio-registry-visibility-metadata`: reserved, server-owned
  `tenant`/`visibility`/`allowed_groups` keys on registry/YAML Agent Studio
  metadata, including draft activation propagation and a common access record.
- `astudio-visible-listing`: scope-aware list/read for agents, drafts, skills (SQL filter, 404 on invisible).
- `astudio-visibility-patch`: owner-only `PATCH …/visibility` for the three resources.
- `astudio-authoring-gate`: host-computed `may_author` on the scope; 403 `authoring_denied` on create verbs.
- `astudio-tenant-prefix-mount`: `setup_studio_routes(app, prefix=…)` for `/api/v1/{tenant}/astudio`.

### Modified Capabilities
- `agentstudio-management` (FEAT-467): reads become scope-aware; registry/YAML
  and database-origin creation paths stamp tenant metadata.
- `tool-configuration-agentstudio` (FEAT-593): all agent-addressed toolkit/
  MCP endpoints check visibility first; agent changes remain owner-only and
  `user_toolkit_configs` stays per-user.
- `ui-surfaces-tenant-visibility` (FEAT-535): scope module moves within the
  server package and retains source-compatible re-exports.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `handlers/scope.py`, `handlers/ui_surfaces_scope.py` | creates/modifies | neutral `RequestScope`; compatibility re-export/adaptor for FEAT-535 |
| `handlers/studio/_base.py` | modifies | cached scope, URL-tenant match, `StudioUser.tenant`/`may_author` |
| `handlers/studio/access.py` | creates | one access service for registry metadata and DB rows; no handler-local policy |
| `handlers/studio/agents.py` | modifies | visible merged listing; reserved registry/YAML tenant metadata; 404 on invisible |
| `handlers/studio/drafts.py` | modifies | visible reads; stamped fields; activation carries metadata into registry |
| `handlers/studio/skills_catalog.py` | modifies | visible reads, tenant-aware catalog rows, import visibility check |
| `handlers/studio/testing.py`, `toolkits.py`, `toolkit_config.py`, `toolkit_overrides.py`, `files.py` | modifies | complete per-route visibility/owner policy |
| `handlers/models/bots.py`, `studio_drafts.py`, `skills_catalog.py` | modifies | three new columns + DDL |
| `handlers/studio/__init__.py` | modifies | `prefix` parameter; new PATCH routes |
| `docs/agent_studio_api.md` | modifies | visibility, tenant, errors |
| FieldSync | depends on | update the existing resolver once to return `RequestScope(..., may_author=...)`; mount once under its tenant URL |
| navigator-frontend-next / navigator-svelte | depends on | UI must render `access` / visibility controls |

No silent breaking change for hosts without a resolver. DB change is additive;
registry/YAML metadata is backward-compatible but its three reserved keys are
server-owned and cannot be supplied by API clients.

### Required Coverage

The FEAT-467 suite covers its individual surfaces but has no Agent Studio
tenant-visibility coverage. The spec must add unit and integration tests for
both database-origin and registry/YAML-origin agents (including draft
activation), for every actor below:

| Actor / state | Required assertions |
|---|---|
| owner | private/tenant/groups list, read, PATCH and allowed owner writes succeed |
| same-tenant peer | tenant read/test succeeds; groups succeeds only on intersection; owner-only files/config/writes remain denied |
| different tenant | list omits and every addressed Studio route returns 404 without leaking existence |
| tenant superuser | sees all records in the resolved tenant only; cannot cross tenant |
| no tenant / multi-programme | opted-in resolver yields owner-only and rejects non-private visibility with 422 |
| no resolver | regression test retains FEAT-467 list-all/read behavior and hides sharing controls |
| legacy and collisions | NULL tenant/ownerless registry behavior, non-enumerating `name_taken` for agent/draft/skill, reserved-key overwrite rejection |

Route coverage must include agent list/read/PATCH, drafts list/read/PATCH/
activate, skills list/read/PATCH/import, test ask and stop, files GET/PUT/
DELETE, tool assignment, toolkit assignment/config/options/MCP, and
`/agents/{name}/toolkits/{slug}/me`. Add an end-to-end tenant-URL mount test
against FieldSync once its companion brainstorm and resolver implementation
are available. `/tools/{slug}/execute`, catalogs, and BYOK keys are asserted
to remain outside agent visibility and retain their existing PBAC/per-user
contracts.

---

## Code Context

### User-Provided Code
None — requirements were given as decisions, not code.

### Verified Codebase References
Verified on `origin/dev` @ `ab9f97a82` (2026-09-24). Paths relative to
`packages/ai-parrot-server/src/parrot/`.

#### Classes & Signatures
```python
# handlers/ui_surfaces_scope.py:41-61
@dataclass(frozen=True)
class SurfaceScope:
    user_id: str | None
    tenant: str | None
    groups: frozenset[str]
    is_superuser: bool = False
# :67   EMPTY_SCOPE = SurfaceScope(user_id=None, tenant=None, groups=frozenset(), is_superuser=False)
# :73   class SurfaceScopeResolver(Protocol)            # async resolve(request)
# :86   class SessionSurfaceScopeResolver               # tenant only when exactly one programme
# :149  def get_scope_resolver(app: Any) -> SurfaceScopeResolver   # reads app["ui_surfaces_scope_resolver"] (:162)
# :171  def scope_grants(record: UISurfaceRecord, scope: SurfaceScope) -> bool

# handlers/models/ui_surfaces.py
# :49   class SurfaceVisibility(str, Enum)               # private | tenant | groups
# :121-123  tenant VARCHAR(63), visibility VARCHAR(16) NOT NULL DEFAULT 'private',
#           allowed_groups JSONB NOT NULL DEFAULT '[]'::jsonb
# :149-151  ALTER TABLE navigator.ui_surfaces ADD COLUMN IF NOT EXISTS ...
# :223  _LIST_VISIBLE_SQL          # user_id = $1 OR ($2 tenant AND (tenant | groups ?| $3 | $4 superuser))
# :243  _UPDATE_VISIBILITY_SQL     # WHERE surface_id = $1 AND user_id = $2
# :575  async def list_visible(self, scope: Any, *, kind: UISurfaceKind | None = None) -> list[UISurfaceRecord]
# :616  async def update_visibility(...)

# handlers/ui_surfaces.py
# :162  async def resolve_surface_access(...)
# :351  async def _scope(self) -> SurfaceScope
# :394  async def patch(self) -> web.Response
# :512  422 "visibility requires a tenant scope"
# :566  tenant=scope.tenant  # server-set, NEVER from the body
# :648  async def _patch_visibility(self) -> web.Response
# :686  422 "visibility requires a tenant on the surface"

# handlers/studio/_base.py
# :102  class StudioUser:  user_id: str (:114), groups: list[str] (:117), is_superuser: bool = False (:118)
# :121  class StudioBaseView(BaseView)
# :230  def _require_owner(self, resource_owner: Any, user: StudioUser) -> None

# handlers/studio/agents.py
# :175  async def get(self)   -> _get_one / _get_all
# :196-207  _get_all: every DB agent + every registry agent, no owner/tenant filter
# :209  async def post(self)  ; :281 config_dict["created_by"] = user.user_id
# :373  async def delete(self)
# :106-119  registry ownership is BotMetadata.bot_config.config["created_by"]

# handlers/studio/drafts.py
# :354-391  activation moves/imports Python then stamps only registry metadata;
#           it does not create a BotModel/ai_bots row

# handlers/studio/__init__.py
# :23   STUDIO_PREFIX = "/api/v1/astudio"
# :26   def setup_studio_routes(app: web.Application) -> None

# handlers/studio/testing.py
# :69   TestAskRequest.use_byok: bool = True
# :216  bot = await manager.get_bot(agent_name, new=True, session_id=session_id, request=self.request)
# :305-308  api_key = await resolve_user_api_key(...); if not api_key: return  (agent's configured client kept)

# handlers/studio/byok.py
# :31   COLLECTION = "user_llm_keys"
# :55   async def resolve_user_api_key(app: Any, user_id: str, provider: str) -> str | None

# handlers/studio/skills_catalog.py
# :41   DEFAULT_ORG_ID = "default"      ; :42 SHARED_NAMESPACE_SUFFIX = "_shared"
# :46   def _shared_namespace(org_id: str)   # f"{org_id}/_shared" (Redis index only)

# handlers/models/bots.py
# :22   class BotModel(Model)  ; table navigator.ai_bots (:30), permissions JSONB (:78), created_by INTEGER (:92)
# handlers/models/studio_drafts.py
# :41   class StudioDraft(Model) ; owner_user_id VARCHAR NOT NULL (:52)
# handlers/models/skills_catalog.py
# :29   class SkillCatalogEntry(Model) ; owner VARCHAR NOT NULL (:38)
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/tenant.py
# :39   def _get_programs(request) -> list[str]     # userinfo["programs"]
# :100  def requires_tenant(*, public: bool = False)  # match_info["tenant"] + membership/superuser
# :166  def declared_tenant(request) -> str
# packages/ai-parrot/src/parrot/auth/eval_context.py
# :23   async def build_eval_context(request)  # EvalContext(..., org_id=None) — no tenant yet
```

#### Verified Imports
```python
from parrot.handlers.ui_surfaces_scope import SurfaceScope   # ai-parrot-server, used by FieldSync fieldsync/surfaces.py
from parrot.handlers.studio import setup_studio_routes        # handlers/studio/__init__.py:26
```

#### Key Attributes & Constants
- `app["ui_surfaces_scope_resolver"]` → host resolver slot (`ui_surfaces_scope.py:162`)
- `STUDIO_PREFIX` → `"/api/v1/astudio"` (`studio/__init__.py:23`)
- `byok.COLLECTION` → `"user_llm_keys"` (`studio/byok.py:31`)

### Does NOT Exist (Anti-Hallucination)
- ~~`tenant` / `visibility` / `allowed_groups` on `ai_bots`, `studio_drafts`, `ai_skills_catalog`~~
- ~~`StudioUser.tenant`~~, ~~any tenant handling in `handlers/studio/*`~~
- ~~an owner/tenant filter on `GET /astudio/agents`~~ — lists everything
- ~~a PATCH/PUT to update an agent's config or visibility under `/astudio/agents`~~
- ~~`/api/v1/{tenant}/astudio`~~ — prefix is fixed
- ~~a tenant-aware `AgentRegistry`~~ — process-global, keyed by name
- ~~a per-tenant LLM key slot~~ — only per-user BYOK + server default
- ~~`requires_tenant` in core parrot~~ — lives in `parrot-formdesigner`
- ~~a tenant field in `build_eval_context`~~ — `org_id=None`
- ~~`handlers/crew/_tenancy.resolve_session_tenant` as a reusable resolver~~ — private to crew and falls back to `programs[0]` (the FEAT-366 bug FEAT-535 avoids); do not reuse

---

## Parallelism Assessment

- **Internal parallelism**: `request-scope-server` + shared Studio access
  service + model/registry metadata contract land sequentially. Then agents,
  drafts, skills, and derivative-route enforcement can proceed in parallel;
  the optional tenant-key slot is deliberately excluded from this feature.
- **Cross-feature independence**: FEAT-598 (`a2ui-linked-surfaces`, draft)
  touches `ui_surfaces` records, not the scope module — coordinate only on
  the re-export of `ui_surfaces_scope.py`. FEAT-593 files
  (`toolkit_config.py`, `tooling_store.py`) are touched for the visibility
  pre-check only.
- **Recommended isolation**: `mixed`
- **Rationale**: persistence and access semantics must be identical before
  handler lanes fan out; the remaining work has manageable overlap only in
  route registration and shared tests.

---

## Resolved Decisions and External Prerequisite

- **Default behavior:** no resolver means unchanged FEAT-467 global reads;
  an installed resolver with no resolved tenant means owner-only reads.
- **Scope seam:** `parrot.handlers.scope`, with `app["scope_resolver"]`
  preferred and `app["ui_surfaces_scope_resolver"]` as compatibility
  fallback. `RequestScope.may_author` is the authoritative host gate because
  PBAC can be fail-open.
- **Persistence:** registry/YAML config metadata is authoritative for
  Studio-created and activated agents; table fields are authoritative for
  database-origin agents. Pre-existing ownerless registry agents are hidden
  in opted-in tenant hosts.
- **Names:** global uniqueness remains for agents, drafts, and skills; all
  collisions return non-enumerating `409 name_taken`.
- **Runtime boundary:** this work enforces Studio control-plane visibility,
  not general non-Studio chat authorization.
- **BYOK:** the proposed tenant key slot, quota, and attribution are a
  separate feature; FEAT-467's user key then configured-server-client
  fallback is unchanged.
- **Deployment:** `AGENTS_DIR` remains pod-local exactly as FEAT-467 today;
  a multi-pod shared-storage migration is a separate operational feature.
- **FieldSync prerequisite:** its absent companion brainstorm and resolver
  implementation must adopt the `RequestScope` and URL-mount contracts before
  the cross-repository integration test can close. This is an integration
  dependency, not an unspecified design choice in this brainstorm.

---

## Design Compliance (ARCHITECTURE.md-equivalent gate, carried from the FieldSync consumer)

- [x] R1 Library-first: reuses FEAT-535 scope/visibility; `requires_tenant` (formdesigner) and `crew/_tenancy` evaluated and rejected/noted. Findings: above.
- [x] R1 Repo reuse: wiki query (`parrot` namespace) + git sweep of 961 refs. Findings: FEAT-535 reusable; nothing else covers astudio tenancy.
- [x] R2 Endpoints are `navigator.views` CBVs (existing `StudioBaseView` subclasses).
- [x] R2 Plain-handler module touched: N/A (Studio is CBV already).
- [x] R3 app.py delta: N/A in parrot (hosts call `setup_studio_routes`).
- [ ] R4 Complexity budgets: to verify per task (flake8) at spec time.
- [x] R5 Layering: SQL stays in models/stores; handlers call them.
- [x] R6 Test doubles: the Required Coverage matrix requires
  `make_mocked_request` with the real session key, SQL mutation checks, and
  registry/YAML metadata-path assertions.
