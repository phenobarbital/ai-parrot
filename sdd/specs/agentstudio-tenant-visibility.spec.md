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

# Feature Specification: Agent Studio — Tenant Scope & Owner-Controlled Visibility

**Feature ID**: FEAT-605
**Date**: 2026-09-25
**Author**: Juan Ruffato (with Claude); brainstorm revised by Jesus Lara (`306c42aca`)
**Status**: draft
**Target version**: ai-parrot-server 1.0.7 (ai-parrot core 1.0.7 for the meta-agent tools, lockstep)
**Brainstorm**: `sdd/proposals/agentstudio-tenant-visibility.brainstorm.md` (Option A, revised)
**Reserved via**: `python -m scripts.sdd.reserve_ids --kind feature --count 1 --base-branch dev --label agentstudio-tenant-visibility` → `FEAT-605` (ledger commit `718265c8e` on `origin/dev`)

---

## 1. Motivation & Business Requirements

### Problem Statement

Agent Studio (FEAT-467, extended by FEAT-593) is a single global namespace:

- `GET /api/v1/astudio/agents` lists **every** DB and registry agent to any
  authenticated caller (`studio/agents.py:193-205`). Ownership is enforced
  only on some mutating verbs (`_require_owner`, `studio/_base.py:230`), with
  superuser bypass. `POST /agents/{name}/reload` (`agents.py:450-478`) and
  `GET /agents/{name}/files/...` (`files.py:170-214`) check no owner at all.
- None of the Studio stores carries a tenant or visibility notion.
  `POST /astudio/agents` writes ownership into **registry metadata**
  (`BotConfig.config["created_by"]`, `agents.py:281`) and optionally a
  lossless YAML definition (`registry.create_agent_definition`,
  `agents.py:330`) — **not** an `ai_bots` row. Draft activation imports a
  Python module and stamps only in-memory registry metadata
  (`drafts.py:389-391`). `navigator.ai_bots` has `created_by INTEGER`
  (`models/bots.py:92`), `navigator.studio_drafts` has `owner_user_id`
  (`models/studio_drafts.py:52`), `navigator.ai_skills_catalog` has `owner`
  (`models/skills_catalog.py:38`) and `name VARCHAR NOT NULL UNIQUE` (`:35`).
- `StudioUser` (`studio/_base.py:102-118`) has no tenant.
- PBAC (`_pbac_gate`, `astudio:<area>`) is fail-open when `app['abac']` is
  absent — the case in FieldSync.

A multi-tenant host (FieldSync: one tenant per programme) cannot offer
Agent Studio to its users without every programme seeing and testing every
other programme's agents, drafts and skills. The same problem was solved
for UI surfaces by FEAT-535 (`tenant` / `visibility` / `allowed_groups` +
a host-pluggable scope resolver), which FieldSync consumes today.

Decided product model (FieldSync owner, 2026-09-24; ratified in the
revised brainstorm):

1. Studio-managed agents, drafts and skills belong to a **tenant**.
2. Any entitled user may author; **who may author is decided per tenant by
   the host** (`RequestScope.may_author`).
3. The **owner decides visibility**: `private` | `tenant` | `groups`.
4. BYOK keeps its existing fallback (user key → agent's configured server
   client). Per-tenant keys are out of scope.

Two defects found while building the Codebase Contract (not in the
brainstorm, in scope because tenancy makes them cross-tenant):

- **D1 — draft overwrite**: `POST /astudio/drafts` upserts by name
  (`_upsert_draft_row`, `drafts.py:93-117`) without checking the existing
  row's owner, so any caller can overwrite another user's draft file and row.
- **D2 — activation stamp is volatile**: activation stamps `created_by`
  only on in-memory `BotMetadata` (`drafts.py:389-391`); after a restart the
  startup loader re-imports `AGENTS_DIR/<name>.py` without it. The activated
  `studio_drafts` row is the only durable record of who owns it.

### Goals

- G1: One neutral server scope seam (`parrot.handlers.scope.RequestScope`)
  shared by UI surfaces and Agent Studio; FEAT-535 names keep working.
- G2: Tenant / visibility / allowed_groups persisted in each resource's
  actual system of record (registry/YAML metadata, `ai_bots`,
  `studio_drafts`, `ai_skills_catalog`), always server-stamped.
- G3: Every Agent Studio agent-addressed route, draft route and skill route
  applies one access service; invisible ⇒ 404, visible-but-not-owner on an
  owner-only route ⇒ 403.
- G4: Owner-only `PATCH …/visibility` for agents, drafts and skills.
- G5: Host-computed authoring gate (`may_author`) on every create path,
  including the AgentStudio meta-agent's writing tools.
- G6: Optional tenant-in-URL mount (`setup_studio_routes(app, prefix=…)`)
  with declared/resolved tenant mismatch rejection.
- G7: Hosts without a resolver keep FEAT-467 behaviour exactly.

### Non-Goals (explicitly out of scope)

- Tenant authorization for non-Studio runtime routes (`/api/v1/agents/chat/*`,
  `BotManager.get_bot` callers). This is **Studio control-plane visibility**,
  not a global runtime-tenant boundary (brainstorm "Runtime boundary").
- Per-tenant agent/draft/skill names — global uniqueness stays.
- Per-tenant LLM key slot, quota, usage attribution (separate feature).
- Shared storage for `AGENTS_DIR` across pods (separate operational feature).
- Tenant-awareness of `AgentRegistry` itself (it stays process-global).
- `/tools/{slug}/execute`, `/catalog/{kind}`, `/keys` — no agent identifier;
  they keep their PBAC / per-user contracts.
- Options B (PBAC-rule encoding), C (pluggable store), D (schema-per-tenant)
  were rejected in the brainstorm.

---

## 2. Architectural Design

### Overview

**Scope seam.** FEAT-535's scope primitives move to
`parrot/handlers/scope.py` (server package — the resolver depends on
aiohttp and navigator-session, so not `parrot.auth`):
`RequestScope(user_id, tenant, groups, is_superuser, may_author=True)`, a
`ScopeResolver` Protocol, the default `SessionScopeResolver`,
`get_scope_resolver(app)` and a primitive-only
`scope_grants(*, tenant, visibility, allowed_groups, scope)`.
`ui_surfaces_scope.py` becomes a compatibility module:
`SurfaceScope = RequestScope`, `SurfaceScopeResolver = ScopeResolver`,
`SessionSurfaceScopeResolver = SessionScopeResolver`, and its
`scope_grants(record, scope)` adapts a `UISurfaceRecord` to the primitive
call. A FieldSync resolver that still builds `SurfaceScope(user_id=…,
tenant=…, groups=…, is_superuser=…)` keeps working and gets
`may_author=True` by default.

**Resolver lookup.** `get_scope_resolver(app)` reads `app["scope_resolver"]`
first, then `app["ui_surfaces_scope_resolver"]`, then the default.
**Opted-in host** := either key is installed. Studio's behaviour switches on
that, not on the default resolver:

| Host state | Reads | Create | PATCH visibility |
|---|---|---|---|
| no resolver installed | FEAT-467 unchanged (list-all, read-any) | stamps `created_by` only; `tenant=None`, `private` | non-private ⇒ 422 `tenant_required` |
| resolver installed, `scope.tenant is None` | owner-only | stamps owner, `tenant=None` | non-private ⇒ 422 `tenant_required` |
| resolver installed, tenant resolved | owner ∪ `scope_grants` | stamps owner + tenant + visibility | owner-only |

**Persistence (system of record per resource).**

| Resource | Where tenant/visibility/allowed_groups live |
|---|---|
| Studio-created agent (`POST /agents`) | reserved keys in `BotConfig.config` (in-memory) — and in the YAML when `persist=true` (the lossless serializer writes `config`) |
| Activated draft agent | reserved keys in registry metadata **and** the `studio_drafts` row (status `activated`) — the row is the durable fallback after restart (fixes D2) |
| Database-origin agent | new columns on `navigator.ai_bots` |
| Draft | new columns on `navigator.studio_drafts` |
| Skill | new columns on `navigator.ai_skills_catalog` |

Reserved config keys are server-owned: `created_by`, `tenant`,
`visibility`, `allowed_groups`. A client `config` carrying any of them ⇒
400 `reserved_config_key`.

**Access service.** `parrot/handlers/studio/access.py` converts any of the
storage shapes above into one `StudioVisibilityRecord` and answers every
policy question (`can_see`, `access_tag`, `owns`). Handlers never infer
tenant from an absent row and never re-implement the rule.

**Route policy.**

| Route family | Invisible | Visible non-owner | Owner |
|---|---|---|---|
| `GET /agents`, `/drafts`, `/skills` (list) | omitted | included, `access` tag | included |
| `GET /agents/{name}`, `/drafts/{name}`, `/skills/{id}` | 404 | 200 | 200 |
| `POST /agents/{name}/test/ask`, `DELETE …/test` | 404 | allowed | allowed |
| `POST /agents/{name}/skills/import/{id}` | 404 (agent or skill) | 403 on the agent | skill must be visible |
| `GET/PUT/DELETE /agents/{name}/files/...` | 404 | 403 | allowed |
| `POST /agents/{name}/reload`, `DELETE /agents/{name}` | 404 | 403 | allowed |
| `POST /agents/{name}/tools`, `/toolkits`, `GET/PUT/DELETE /toolkit-config`, `/toolkits/{slug}`, `/options/{param}`, `/mcp-servers` | 404 | 403 | allowed |
| `GET/PUT/DELETE /agents/{name}/toolkits/{slug}/me` | 404 | allowed (own override) | allowed |
| `POST /drafts/{name}/activate`, `DELETE /drafts/{name}` | 404 | 403 | allowed |
| `PATCH …/visibility` (3 resources) | 404 | 403 | allowed |
| `POST /agents`, `/drafts`, `/skills`, meta-agent writing tools | — | — | requires `may_author` else 403 `authoring_denied` |

Tenant superuser: `scope_grants` is `True` inside the resolved tenant (read,
test); owner-only verbs keep FEAT-467's existing superuser bypass of
`_require_owner` **only within the resolved tenant** (never cross-tenant —
an invisible record is a 404 before `_require_owner` runs).

**Names.** Global uniqueness for agents, drafts and skills. Every create
collision answers `409 name_taken` with the message
`"Name '<slug>' is not available."` — no source, owner or tenant (replaces
the current `duplicate` code that discloses `registry`/`database`,
`agents.py:255-261`, `skills_catalog.py:361-362`). `POST /drafts` on a name
whose row belongs to someone else ⇒ `409 name_taken` (fixes D1).

**Tenant-in-URL.** `setup_studio_routes(app, *, prefix=STUDIO_PREFIX)`.
When the prefix contains `{tenant}`, `StudioBaseView` compares
`match_info["tenant"]` with `scope.tenant` before touching any record and
answers 403 `tenant_mismatch` on difference (including `scope.tenant is None`).
Membership validation stays in the host resolver (FieldSync's seam).

### Component Diagram
```
request ─→ host seam (optional, e.g. FieldSync ProgrammeScopedView)
        ─→ StudioBaseView._scope()  ── get_scope_resolver(app) ──→ RequestScope
                 │   (tenant-mismatch check, cached per request)
                 ▼
          StudioAccess (studio/access.py)
            ├─ agent: ai_bots row │ registry BotConfig.config │ activated studio_drafts row
            ├─ draft: studio_drafts row
            └─ skill: ai_skills_catalog row
                 │  scope_grants(tenant, visibility, allowed_groups, scope)  (handlers/scope.py)
                 ▼
          handler verb  (list filter / 404 / 403 / owner write / stamp on create)
                 │
                 └─ meta-agent: RequestContext.kwargs["studio_scope"] → bots/studio/tools.py
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `handlers/ui_surfaces_scope.py` | modifies | becomes compatibility aliases + record adapter over `handlers/scope.py` |
| `handlers/ui_surfaces.py`, `handlers/a2ui.py` | unchanged imports | still import from `ui_surfaces_scope`; behaviour identical |
| `StudioBaseView` (`studio/_base.py`) | extends | scope, tenant check, authoring gate, visibility helpers |
| `AgentRegistry` (`registry/registry.py`) | uses | `get_metadata`, `list_agents`, `create_agent_definition` (writes `config`) |
| `BotModel`, `StudioDraft`, `SkillCatalogEntry` | extends | three fields each |
| `AgentStudioAgent` tools (`ai-parrot` `bots/studio/tools.py`) | modifies | read scope from `current_context().kwargs` |
| FieldSync `FieldSyncSurfaceScopeResolver` | depends on (external) | installs under `ui_surfaces_scope_resolver`; adds `may_author`; mounts `/api/v1/{tenant}/astudio` |

### Data Models
```python
# handlers/scope.py
VisibilityLevel = Literal["private", "tenant", "groups"]

@dataclass(frozen=True)
class RequestScope:
    user_id: str | None
    tenant: str | None
    groups: frozenset[str]
    is_superuser: bool = False
    may_author: bool = True

# handlers/studio/access.py
@dataclass(frozen=True)
class StudioVisibilityRecord:
    kind: Literal["agent", "draft", "skill"]
    name: str
    owner: str | None
    tenant: str | None
    visibility: VisibilityLevel
    allowed_groups: tuple[str, ...]
    source: Literal["database", "registry", "draft_row", "catalog"]

# handlers/studio/models.py
class VisibilityUpdateRequest(BaseModel):
    visibility: VisibilityLevel
    allowed_groups: list[str] = Field(default_factory=list)
```

### New Public Interfaces
```python
from parrot.handlers.scope import RequestScope, ScopeResolver, get_scope_resolver, scope_grants
from parrot.handlers.studio import setup_studio_routes  # gains keyword-only `prefix`
# New routes (relative to the mount prefix):
#   PATCH /agents/{name}/visibility
#   PATCH /drafts/{name}/visibility
#   PATCH /skills/{id}/visibility
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: request-scope-server | yes | names, key order, aliases fixed below | — |
| M2: studio-visibility-schema | yes | columns, DDL strings, startup hook fixed | — |
| M3: studio-access-service | no | — | the agent-record resolution order (row → registry → activated draft row) and legacy rules need judgement on edge cases |
| M4: studio-base-scope | yes | helper names + error codes fixed | — |
| M5: agents-visibility | no | — | merges three sources and YAML re-write on PATCH |
| M6: drafts-visibility | yes | contracts fixed (D1/D2 behaviour specified) | — |
| M7: skills-visibility | yes | contracts fixed | — |
| M8: derivative-route-gates | yes | route policy table in §2 is exhaustive | — |
| M9: meta-agent-scope | yes | ctx key + tool behaviour fixed | — |
| M10: routes-prefix-and-patch | yes | signature + route list fixed | — |
| M11: docs-and-coverage | yes | coverage matrix in §4 | — |

### Module 1: request-scope-server
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/scope.py` (new); `handlers/ui_surfaces_scope.py` (modify)
- **Responsibility**: neutral scope types, resolver lookup, pure grant rule; FEAT-535 compatibility.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # parrot/handlers/scope.py  (new)
  SCOPE_RESOLVER_APP_KEY = "scope_resolver"
  LEGACY_SCOPE_RESOLVER_APP_KEY = "ui_surfaces_scope_resolver"  # verified: handlers/ui_surfaces_scope.py:162
  VISIBILITY_LEVELS: frozenset[str] = frozenset({"private", "tenant", "groups"})

  @dataclass(frozen=True)
  class RequestScope:  # field order/defaults mirror SurfaceScope, verified: ui_surfaces_scope.py:41-61
      """Caller identity, single tenant, groups, superuser flag and host authoring gate."""
      user_id: str | None
      tenant: str | None
      groups: frozenset[str]
      is_superuser: bool = False
      may_author: bool = True

  EMPTY_SCOPE: RequestScope

  class ScopeResolver(Protocol):
      async def resolve(self, request: web.Request) -> RequestScope: ...

  class SessionScopeResolver:
      """Moved verbatim from SessionSurfaceScopeResolver (ui_surfaces_scope.py:86-146):
      tenant only when session `programs` has exactly one entry; never programs[0]."""
      async def resolve(self, request: web.Request) -> RequestScope: ...

  def has_installed_resolver(app: Any) -> bool:
      """True when app[SCOPE_RESOLVER_APP_KEY] or app[LEGACY_SCOPE_RESOLVER_APP_KEY] is set."""

  def get_scope_resolver(app: Any) -> ScopeResolver:
      """app['scope_resolver'] → app['ui_surfaces_scope_resolver'] → module default."""

  def normalize_visibility(value: Any) -> str:
      """Return a member of VISIBILITY_LEVELS (accepts str or str-Enum); raise ValueError otherwise."""

  def scope_grants(*, tenant: str | None, visibility: str, allowed_groups: Iterable[str], scope: RequestScope) -> bool:
      """Pure; ignores ownership. False when either tenant is None or they differ; else True when
      scope.is_superuser, visibility == 'tenant', or visibility == 'groups' and groups intersect."""

  # parrot/handlers/ui_surfaces_scope.py  (modifies :41-198)
  SurfaceScope = RequestScope                          # was class at :42
  SurfaceScopeResolver = ScopeResolver                 # was Protocol at :73
  SessionSurfaceScopeResolver = SessionScopeResolver   # was class at :86
  # get_scope_resolver, EMPTY_SCOPE re-exported from parrot.handlers.scope
  def scope_grants(record: UISurfaceRecord, scope: SurfaceScope) -> bool:  # keeps signature, verified :171
      """Adapter: delegates to parrot.handlers.scope.scope_grants(tenant=record.tenant,
      visibility=record.visibility.value, allowed_groups=record.allowed_groups, scope=scope)."""
  ```

### Module 2: studio-visibility-schema
- **Path**: `handlers/models/bots.py`, `handlers/models/studio_drafts.py`, `handlers/models/skills_catalog.py` (modify); `handlers/models/studio_visibility.py` (new)
- **Responsibility**: three fields on each model + idempotent DDL applied at startup.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # each of BotModel (after bots.py:251), StudioDraft (after studio_drafts.py:73),
  # SkillCatalogEntry (after skills_catalog.py:64):
  tenant: Optional[str] = Field(required=False, default=None)
  visibility: str = Field(required=False, default="private")
  allowed_groups: list = Field(required=False, default_factory=list)
  # + the three columns added to each class docstring's CREATE TABLE block

  # parrot/handlers/models/studio_visibility.py  (new)
  STUDIO_VISIBILITY_DDL: tuple[str, ...] = (
      # for T in navigator.ai_bots, navigator.studio_drafts, navigator.ai_skills_catalog:
      "ALTER TABLE <T> ADD COLUMN IF NOT EXISTS tenant VARCHAR(63)",
      "ALTER TABLE <T> ADD COLUMN IF NOT EXISTS visibility VARCHAR(16) NOT NULL DEFAULT 'private'",
      "ALTER TABLE <T> ADD COLUMN IF NOT EXISTS allowed_groups JSONB NOT NULL DEFAULT '[]'::jsonb",
      "CREATE INDEX IF NOT EXISTS idx_<t>_tenant_visibility ON <T>(tenant, visibility)",
  )  # idiom verified: handlers/models/ui_surfaces.py:149-151

  async def ensure_studio_visibility_schema(app: Any) -> None:
      """on_startup hook: run STUDIO_VISIBILITY_DDL on app['database']; no database ⇒ log and return;
      a failing statement is logged at ERROR and does not abort startup (mirrors reconcile_skills_catalog)."""
  ```
  `ai_bots` uses `PARROT_SCHEMA` (`bots.py:361`) — the DDL for `ai_bots` must be built from `PARROT_SCHEMA`/`PARROT_BOTS_TABLE`, not the literal `navigator`.

### Module 3: studio-access-service
- **Path**: `handlers/studio/access.py` (new)
- **Responsibility**: resolve a visibility record for agent/draft/skill; decide visibility, ownership, access tag; stamp and validate reserved keys.
- **Depends on**: M1, M2
- **Interface Skeleton**:
  ```python
  RESERVED_CONFIG_KEYS: frozenset[str] = frozenset({"created_by", "tenant", "visibility", "allowed_groups"})

  class StudioAccess:
      def __init__(self, view: "StudioBaseView") -> None: ...

      async def agent_record(self, name: str) -> StudioVisibilityRecord | None:
          """Resolution order: ai_bots row (columns) → registry metadata with reserved keys
          (BotConfig.config, verified agents.py:106-119) → activated studio_drafts row of the same
          name (D2 durable fallback) → registry metadata without keys (legacy: owner=created_by or None,
          tenant=None, private). None when the agent does not exist anywhere."""

      async def draft_record(self, row: StudioDraft) -> StudioVisibilityRecord: ...
      def skill_record(self, entry: SkillCatalogEntry) -> StudioVisibilityRecord: ...

      def can_see(self, record: StudioVisibilityRecord, scope: RequestScope, *, opted_in: bool) -> bool:
          """Not opted in ⇒ True (FEAT-467). Opted in ⇒ owns(record) or scope_grants(...).
          Ownerless legacy registry agents are invisible in an opted-in host."""

      def owns(self, record: StudioVisibilityRecord, scope: RequestScope) -> bool:
          """record.owner == scope.user_id, or scope.is_superuser AND record.tenant == scope.tenant (not None)
          — or, not opted in, the FEAT-467 superuser bypass."""

      def access_tag(self, record: StudioVisibilityRecord, scope: RequestScope) -> str:
          """'owner' | 'superuser' | 'tenant' | 'groups' | 'global' (not opted in)."""

      @staticmethod
      def reject_reserved_keys(config: dict) -> str | None:
          """Return the first reserved key present in a client-supplied config, else None."""

      @staticmethod
      def stamp(target: dict, *, scope: RequestScope, visibility: str, allowed_groups: list[str]) -> dict:
          """Write created_by/tenant/visibility/allowed_groups into a config dict (server-owned)."""
  ```

### Module 4: studio-base-scope
- **Path**: `handlers/studio/_base.py` (modify)
- **Responsibility**: per-request scope, tenant check, authoring gate, access helpers on every Studio view.
- **Depends on**: M1, M3
- **Interface Skeleton**:
  ```python
  @dataclass(slots=True)
  class StudioUser:  # verified _base.py:102-118
      ...                      # existing fields unchanged
      tenant: str | None = None
      may_author: bool = True

  class StudioBaseView(BaseView):  # verified _base.py:121
      async def _scope(self) -> RequestScope:
          """Resolve once per request via get_scope_resolver(app); cache on self; then, when
          match_info has 'tenant', raise 403 tenant_mismatch unless it equals scope.tenant."""
      def _opted_in(self) -> bool:
          """has_installed_resolver(self.request.app)."""
      async def _get_user(self) -> StudioUser:  # verified _base.py:164 — now also fills tenant/may_author
          ...
      async def _require_author(self) -> web.Response | None:
          """403 {'code': 'authoring_denied'} when scope.may_author is False, else None."""
      def _not_found(self, kind: str, name: str) -> web.Response:
          """404 {'code': 'not_found'} — identical body for 'absent' and 'invisible'."""
      def _access(self) -> StudioAccess: ...
  ```

### Module 5: agents-visibility
- **Path**: `handlers/studio/agents.py` (modify); new `StudioAgentVisibilityHandler` in the same module
- **Responsibility**: filtered list/read; create stamping + authoring gate + `name_taken`; reserved-key rejection; owner check on reload and delete; visibility PATCH.
- **Depends on**: M3, M4
- **Interface Skeleton**:
  ```python
  class StudioAgentsHandler(...):
      async def _get_all(self): ...   # verified agents.py:193 — filter via StudioAccess.can_see, add access fields
      async def _get_one(self, name: str): ...  # verified :182 — 404 when invisible
      async def post(self): ...       # verified :209 — _require_author; reject_reserved_keys(create_request.config)
                                      #   → 400 reserved_config_key; collision (:255) → 409 name_taken;
                                      #   stamp(config_dict, ...) replaces the bare created_by at :281;
                                      #   CreateAgentRequest gains visibility/allowed_groups (default private)
  class StudioAgentReloadHandler(...):
      async def post(self): ...       # verified :450 — agent_record + can_see (404) + owns (403) before :464

  class StudioAgentVisibilityHandler(_StudioAgentsMixin, StudioBaseView):
      """PATCH {prefix}/agents/{name}/visibility — owner-only."""
      async def patch(self) -> web.Response:
          """VisibilityUpdateRequest; non-private with tenant None ⇒ 422 tenant_required; groups with empty
          allowed_groups ⇒ 422 groups_required. Writes: DB agent → columns; registry agent → BotConfig.config
          keys, and when metadata.file_path is under AGENTS_DIR/agents/ re-writes the YAML via
          registry.create_agent_definition; activated-draft agent → also the studio_drafts row."""
  ```

### Module 6: drafts-visibility
- **Path**: `handlers/studio/drafts.py` (modify); new `StudioDraftVisibilityHandler`
- **Responsibility**: filtered list/read; owner-guarded save (D1); stamping; activation propagation (D2); visibility PATCH.
- **Depends on**: M3, M4
- **Interface Skeleton**:
  ```python
  class StudioDraftsHandler(...):
      async def _get_all(self): ...   # verified drafts.py:177-179 — filter
      async def _get_one(self, name: str): ...  # verified :168 — 404 when invisible
      async def post(self): ...       # verified :181 — _require_author; an existing row owned by another
                                      #   user ⇒ 409 name_taken BEFORE writing the file (:216);
                                      #   new rows stamped tenant/visibility/allowed_groups
  class StudioDraftActivateHandler(...):
      async def post(self): ...       # verified :279 — 404 when invisible; at :389-391 stamp all reserved keys
                                      #   from the draft row into metadata.bot_config.config; the final upsert
                                      #   (:408) keeps tenant/visibility/allowed_groups
  class StudioDraftVisibilityHandler(_StudioDraftsMixin, StudioBaseView):
      async def patch(self) -> web.Response:
          """Owner-only; updates the row; when status == 'activated' and the agent is registered, also
          updates its BotConfig.config reserved keys."""
  ```

### Module 7: skills-visibility
- **Path**: `handlers/studio/skills_catalog.py` (modify); new `StudioSkillVisibilityHandler`
- **Responsibility**: filtered list/read; publish stamping + authoring gate + `name_taken`; import requires a visible skill; visibility PATCH. The Redis `<org_id>/_shared` namespace is never an authorization source.
- **Depends on**: M3, M4
- **Interface Skeleton**:
  ```python
  class StudioSkillsCatalogHandler(...):
      async def _get_all(self): ...   # verified skills_catalog.py:282 — filter entries after :303
      async def _get_one(self, skill_id: str): ...  # verified :316 — 404 when invisible
      async def post(self): ...       # publish (first post at :333) — _require_author; 409 duplicate (:361)
                                      #   → name_taken; stamp owner/tenant/visibility (next to owner= at :374)
  class StudioSkillsImportHandler(...):
      async def post(self): ...       # verified :527 — agent: 404/403 via StudioAccess; skill (:548):
                                      #   invisible ⇒ 404
  class StudioSkillVisibilityHandler(_StudioSkillsMixin, StudioBaseView):
      async def patch(self) -> web.Response: ...
  ```

### Module 8: derivative-route-gates
- **Path**: `studio/testing.py`, `studio/toolkits.py`, `studio/toolkit_config.py`, `studio/toolkit_overrides.py`, `studio/files.py` (modify)
- **Responsibility**: apply the §2 route-policy table verbatim.
- **Depends on**: M3, M4
- **Interface Skeleton**:
  ```python
  # testing.py — StudioTestingHandler.post (:235) and .delete (:312): agent_record + can_see ⇒ 404
  #   before _get_or_create_test_bot (:216) / before session.pop (:319).
  # testing.py — StudioToolAssignHandler.post (:408): 404 invisible, then the existing _require_owner (:438).
  # toolkits.py — StudioToolkitsHandler.post (:281): 404 invisible before _require_owner (:311).
  # toolkit_config.py — _ToolingViewMixin._authorize (:36): 404 invisible before _require_owner (:45).
  # toolkit_overrides.py — _spec (:83) callers: 404 invisible; no owner requirement (own override).
  # files.py — get (:170): invisible ⇒ 404; visible non-owner ⇒ 403 (new — GET was ungated, :184);
  #   put (:216) / delete (:280): 404 invisible before the existing owner check (:236, 2 occurrences).
  ```

### Module 9: meta-agent-scope
- **Path**: `handlers/studio/meta_agent.py` (modify); `packages/ai-parrot/src/parrot/bots/studio/tools.py` (modify)
- **Responsibility**: the assistant's writing tools obey the same authoring gate and stamping.
- **Depends on**: M1, M3
- **Interface Skeleton**:
  ```python
  # meta_agent.py:110 — pass the resolved scope into the RequestContext:
  #   agent.session(request=..., app=..., user_id=user.user_id, studio_scope=scope)
  #   (RequestContext stores extra kwargs in .kwargs — verified parrot/utils/helpers.py:28,36 (`**kwargs` → `self.kwargs`))
  # POST /assistant itself is NOT gated by may_author (read-only questions stay allowed).

  # bots/studio/tools.py (ai-parrot core; no import of ai-parrot-server at module level — existing rule :25-32)
  def _require_scope() -> Any:
      """Return current_context().kwargs['studio_scope'] or None (host without scope)."""
  # save_agent_draft (:162) and create_yaml_agent (:274): when scope present and scope.may_author is False
  #   ⇒ raise PermissionError('authoring_denied'); stamp tenant/visibility('private')/allowed_groups([])
  #   next to created_by (:320) and in the StudioDraft row (:238).
  # _require_agent_owner (:84): also refuses an agent whose tenant differs from scope.tenant.
  ```

### Module 10: routes-prefix-and-patch
- **Path**: `handlers/studio/__init__.py`, `handlers/studio/models.py` (modify)
- **Responsibility**: mountable prefix, PATCH routes, DDL startup hook, request models.
- **Depends on**: M2, M5, M6, M7
- **Interface Skeleton**:
  ```python
  def setup_studio_routes(app: web.Application, *, prefix: str = STUDIO_PREFIX) -> None:  # verified :26
      """Register every Studio route under `prefix` (one mount per call). Appends
      ensure_studio_visibility_schema to app.on_startup BEFORE reconcile_skills_catalog (:88)."""
  # new routes:
  #   f"{prefix}/agents/{{name}}/visibility" → StudioAgentVisibilityHandler
  #   f"{prefix}/drafts/{{name}}/visibility" → StudioDraftVisibilityHandler
  #   f"{prefix}/skills/{{id}}/visibility"   → StudioSkillVisibilityHandler (registered before /skills/{id})

  # models.py
  class CreateAgentRequest(BaseModel):  # verified :38 — adds:
      visibility: VisibilityLevel = "private"
      allowed_groups: list[str] = Field(default_factory=list)
  class SkillPublishRequest(BaseModel):  # verified :78 — same two fields
  class VisibilityUpdateRequest(BaseModel): ...  # §2 Data Models
  # SaveDraftRequest (drafts.py:32) — same two fields
  ```

### Module 11: docs-and-coverage
- **Path**: `docs/agent_studio_api.md` (modify); tests under `packages/ai-parrot-server/tests/studio/` and `tests/handlers/`
- **Responsibility**: document tenancy, visibility, new errors (`name_taken`, `authoring_denied`, `tenant_mismatch`, `tenant_required`, `groups_required`, `reserved_config_key`), prefix mount; the §4 matrix.
- **Depends on**: M1–M10

---

## 4. Test Specification

All request doubles are built with `aiohttp.test_utils.make_mocked_request`
(precedent: `tests/studio/test_integration.py:34,83`) with the session under
the real session key; resolvers are real `ScopeResolver` implementations
installed on the app, never attributes set on a Mock. Every new assertion is
mutation-checked (revert the guard → the test goes RED).

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_scope_grants_matrix` | M1 | tenant None/mismatch/match × private/tenant/groups × superuser |
| `test_legacy_aliases_identity` | M1 | `SurfaceScope is RequestScope`; old positional/keyword construction works; `may_author` defaults True |
| `test_resolver_key_precedence` | M1 | `scope_resolver` > `ui_surfaces_scope_resolver` > default; `has_installed_resolver` |
| `test_ui_surfaces_scope_grants_adapter` | M1 | existing `tests/handlers/test_ui_surfaces_scope.py` passes unchanged |
| `test_visibility_ddl_idempotent` | M2 | statements are `IF NOT EXISTS`; `ai_bots` built from `PARROT_SCHEMA` |
| `test_agent_record_resolution_order` | M3 | DB row > registry keys > activated draft row > legacy |
| `test_reserved_keys_rejected` | M3/M5 | client config with `tenant` ⇒ 400 `reserved_config_key` |
| `test_tenant_mismatch_403` | M4 | `/api/v1/{tenant}/astudio` with different/None scope tenant |
| `test_authoring_denied` | M4–M9 | POST agents/drafts/skills and both meta-agent writing tools |
| `test_draft_overwrite_refused` | M6 | D1: other user's draft name ⇒ 409, file unchanged |
| `test_activation_stamp_survives_reload` | M6 | D2: registry metadata without keys → access resolves from activated row |
| `test_name_taken_non_enumerating` | M5–M7 | same body for registry/database/other-tenant collisions |

### Integration Tests (coverage matrix — both DB-origin and registry/YAML-origin agents, incl. activated drafts)
| Actor / state | Required assertions |
|---|---|
| owner | private/tenant/groups list, read, PATCH, owner writes succeed |
| same-tenant peer | tenant read/test ok; groups ok only on intersection; files/config/reload/delete/activate ⇒ 403 |
| different tenant | list omits; every addressed route in §2 table ⇒ 404 with identical body |
| tenant superuser | sees all records of the resolved tenant; cannot cross tenant |
| no tenant / multi-programme (resolver installed) | owner-only reads; non-private ⇒ 422 `tenant_required` |
| no resolver | FEAT-467 list-all/read-any regression; PATCH non-private ⇒ 422 |
| legacy & collisions | NULL-tenant rows; ownerless registry agents hidden when opted in; `name_taken` ×3 resources |

Route coverage: agents list/read/PATCH/reload/delete; drafts
list/read/PATCH/activate/delete/save; skills list/read/PATCH/import/publish;
test ask + stop; files GET/PUT/DELETE; tool assignment; toolkit
assignment/config/options/MCP; `/toolkits/{slug}/me`. Assert
`/tools/{slug}/execute`, `/catalog/{kind}`, `/keys` are unchanged.

### Test Data / Fixtures
```python
@pytest.fixture
def scoped_app():
    """web.Application with app['scope_resolver'] = a real resolver returning a
    configurable RequestScope, app['bot_manager'] with a real AgentRegistry, and a
    fake database acquired through the same `async with await db.acquire()` protocol."""
```

---

## 5. Acceptance Criteria

- [ ] AC1 `parrot.handlers.scope` exists; `ui_surfaces_scope` names are aliases; all existing UI-surfaces tests pass unchanged.
- [ ] AC2 Resolver lookup prefers `scope_resolver`, falls back to `ui_surfaces_scope_resolver`, then the default.
- [ ] AC3 With no resolver installed, every FEAT-467 test passes unchanged (list-all/read-any preserved).
- [ ] AC4 With a resolver and a tenant, lists return only owned ∪ granted records for agents (DB and registry), drafts and skills.
- [ ] AC5 Every route in the §2 policy table returns 404 for an invisible record with a body identical to a truly absent one.
- [ ] AC6 Owner-only routes return 403 to a visible non-owner; reload and files GET are now gated.
- [ ] AC7 Tenant is always server-stamped; a client `config` with a reserved key ⇒ 400 `reserved_config_key`.
- [ ] AC8 `PATCH …/visibility` exists for the three resources, is owner-only, and enforces `tenant_required` / `groups_required`.
- [ ] AC9 Registry agents created with `persist=true` keep tenant/visibility in their YAML across a registry reload.
- [ ] AC10 Activated draft agents keep their visibility after a process restart (D2) via the activated draft row.
- [ ] AC11 `POST /drafts` cannot overwrite another user's draft (D1).
- [ ] AC12 `may_author=False` blocks POST agents/drafts/skills and the meta-agent's `save_agent_draft` / `create_yaml_agent` with `authoring_denied`.
- [ ] AC13 Mounted under `/api/v1/{tenant}/astudio`, a declared ≠ resolved tenant ⇒ 403 `tenant_mismatch` before any record access.
- [ ] AC14 All create collisions answer `409 name_taken` without source/owner/tenant.
- [ ] AC15 DDL is idempotent and applied on startup; startup does not abort on a DDL failure.
- [ ] AC16 `docs/agent_studio_api.md` documents tenancy, visibility, prefix mount and the new error codes.
- [ ] AC17 `pytest packages/ai-parrot-server/tests/studio packages/ai-parrot-server/tests/handlers -q` green; new functions within complexity ≤ 10, ≤ 60 lines.

---

## 6. Codebase Contract

Verified against `718265c8e` (origin/dev, 2026-09-25). Paths relative to
`packages/ai-parrot-server/src/parrot/` unless stated.

### Verified Imports
```python
from parrot.handlers.ui_surfaces_scope import SurfaceScope, get_scope_resolver, scope_grants  # verified: handlers/ui_surfaces.py:37-41
from parrot.handlers.ui_surfaces_scope import get_scope_resolver  # verified: handlers/a2ui.py:57
from parrot.handlers.models.ui_surfaces import SurfaceVisibility, UISurfaceRecord  # verified: ui_surfaces_scope.py:27
from parrot.auth.session_identity import resolve_user_id  # verified: ui_surfaces_scope.py:26
from parrot.registry.registry import BotConfig  # verified: studio/agents.py:28
from parrot.conf import AGENTS_DIR  # verified: studio/agents.py:26
from parrot.utils.helpers import current_context  # verified: ai-parrot bots/studio/tools.py:41
```

### Existing Class Signatures
```python
# handlers/ui_surfaces_scope.py
@dataclass(frozen=True)
class SurfaceScope:                       # :41-61  user_id, tenant, groups, is_superuser=False
EMPTY_SCOPE = SurfaceScope(...)           # :67
class SurfaceScopeResolver(Protocol):     # :73 ; async def resolve(self, request) -> SurfaceScope  # :81
class SessionSurfaceScopeResolver:        # :86 ; resolve :103 ; tenant only if len(programs) == 1 (:144)
def get_scope_resolver(app: Any) -> SurfaceScopeResolver:  # :149 ; reads app.get("ui_surfaces_scope_resolver") :162
_DEFAULT_RESOLVER = SessionSurfaceScopeResolver()          # :168
def scope_grants(record: UISurfaceRecord, scope: SurfaceScope) -> bool:  # :171
__all__ = [...]                           # :31-38

# handlers/models/ui_surfaces.py
class SurfaceVisibility(str, Enum)        # :49
# ALTER ... ADD COLUMN IF NOT EXISTS tenant/visibility/allowed_groups  :149-151
# _LIST_VISIBLE_SQL :223 ; _UPDATE_VISIBILITY_SQL :243 ; async def ensure_schema(self) :475

# handlers/studio/_base.py
@dataclass(slots=True)
class StudioUser:                         # :102 ; user_id :114, groups :117, is_superuser :118
class StudioBaseView(BaseView):           # :121
    async def _resolve_session(self)      # :141
    async def _get_user(self) -> StudioUser  # :164
    def _is_superuser(userinfo, user=None) -> bool  # :199
    def _require_owner(self, resource_owner, user) -> None  # :230 (raises HTTPForbidden)
    async def _pbac_gate(self, resource, action)  # :308

# handlers/studio/agents.py
class _StudioAgentsMixin:                 # :39 ; _manager :42, _registry :46, _get_db_agent :51,
                                          # _get_all_db_agents :75, _check_duplicate :89,
                                          # _registry_agent_owner :106, _registry_agent_to_dict :121,
                                          # _db_agent_to_dict :139, _error :150
class StudioAgentsHandler                 # :167 ; get :175, _get_one :182, _get_all :193, post :209, delete :373
class StudioAgentReloadHandler            # :443 ; post :450 (no owner check today)

# handlers/studio/drafts.py
class SaveDraftRequest(BaseModel)         # :32
class _StudioDraftsMixin                  # :45 ; _get_draft_row :65, _get_all_draft_rows :80,
                                          # _upsert_draft_row :93 (no owner check — D1), _draft_to_dict :132
class StudioDraftsHandler                 # :155 ; _get_one :168, _get_all :177, post :181, delete :243
class StudioDraftActivateHandler          # :270 ; post :279 ; stamp :389-391 (in-memory only — D2)

# handlers/studio/skills_catalog.py
class _StudioSkillsMixin                  # :161 ; _get_org_id :164 ('default' fallback), _list_entries :210
class StudioSkillsCatalogHandler          # :268 ; get :276, _get_all :282, _get_one :316, post :333, put :397, delete :442
class StudioSkillsImportHandler(_StudioSkillsMixin, _StudioFilesMixin, StudioBaseView)  # :515 ; post :527

# handlers/studio/testing.py
class StudioTestingHandler                # :226 ; post :235, _maybe_apply_byok :288, delete :312
class StudioToolAssignHandler             # :399 ; post :408
# handlers/studio/toolkits.py   class StudioToolkitsHandler :221 ; post :281
# handlers/studio/toolkit_config.py  class _ToolingViewMixin :29 ; _authorize :36
# handlers/studio/toolkit_overrides.py  class StudioUserToolkitOverrideHandler :76 ; _spec :83
# handlers/studio/files.py  class _StudioFilesMixin :76 ; _resolve_agent :98 ; StudioFilesHandler :162 (get :170, put :216, delete :280)
# handlers/studio/tooling_store.py  class ToolingState :47 (owner :53) ; AgentToolingStore :78 ; load :84
# handlers/studio/meta_agent.py  class StudioAssistantHandler :45 ; post :77 ; session(...) :110
# handlers/studio/models.py  CreateAgentRequest :38 ; SkillPublishRequest :78 ; StudioError :23

# handlers/models/bots.py
class BotModel(Model)                     # :22 ; created_by: Optional[int] :251 ; Meta schema = PARROT_SCHEMA :361, strict :362
# handlers/models/studio_drafts.py
class StudioDraft(Model)                  # :41 ; owner_user_id :73
# handlers/models/skills_catalog.py
class SkillCatalogEntry(Model)            # :29 ; name UNIQUE (DDL :35) ; owner :64

# ai-parrot core: packages/ai-parrot/src/parrot/
class BotConfig(BaseModel)                # registry/registry.py:227 ; config: Dict[str, Any] :237
AgentRegistry.register                    # registry/registry.py:526
AgentRegistry.get_metadata                # :648
AgentRegistry.load_agent_definition_file  # :964
AgentRegistry.create_agent_definition(config: BotConfig, category="general") -> Path  # :1054 (serializes config)
AgentRegistry._import_module_from_path    # :1251
AgentRegistry.list_agents                 # :1421
class RequestContext                      # utils/helpers.py:7 ; **kwargs stored as self.kwargs (:28, :36)
AbstractBot.session(..., user_id=..., **ctx_kwargs)  # bots/abstract.py:4143
# bots/studio/tools.py: _require_user_id :61, _require_agent_owner :84, save_agent_draft :162,
#   StudioDraft row :238, create_yaml_agent :274, created_by stamp :320
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `get_scope_resolver` (new) | host resolver | `app["scope_resolver"]` / `app["ui_surfaces_scope_resolver"]` | `ui_surfaces_scope.py:162` |
| `StudioAccess.agent_record` | `BotModel.get(name=)` | method call | `studio/agents.py:68` |
| `StudioAccess.agent_record` | `registry.get_metadata(name)` | method call | `registry/registry.py:648` |
| `StudioAccess.agent_record` | `StudioDraft.get(name=)` | method call | `studio/drafts.py:73` |
| PATCH (registry, persisted) | `registry.create_agent_definition` | re-write YAML | `registry/registry.py:1054` |
| `ensure_studio_visibility_schema` | `app.on_startup` | hook | `studio/__init__.py:88` |
| meta-agent tools | `current_context().kwargs["studio_scope"]` | ctx kwargs | `utils/helpers.py:36`, `meta_agent.py:110` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.handlers.scope`~~, ~~`RequestScope`~~, ~~`StudioAccess`~~, ~~`StudioVisibilityRecord`~~ — created by this spec
- ~~`tenant` / `visibility` / `allowed_groups` on `ai_bots`, `studio_drafts`, `ai_skills_catalog`~~
- ~~a DDL runner for `studio_drafts` / `ai_skills_catalog`~~ — their DDL exists only in model docstrings; M2 adds the startup hook
- ~~`StudioUser.tenant`~~, ~~`StudioUser.may_author`~~
- ~~an owner check on `POST /agents/{name}/reload` or `GET /agents/{name}/files`~~
- ~~an owner check in `_upsert_draft_row`~~ (D1)
- ~~persistence of the activation stamp~~ (D2)
- ~~a `prefix` parameter on `setup_studio_routes`~~, ~~`/api/v1/{tenant}/astudio`~~
- ~~an agent PATCH/PUT for config or visibility under `/astudio/agents`~~
- ~~a tenant-aware `AgentRegistry`~~ — process-global, keyed by name
- ~~a per-tenant LLM key slot~~
- ~~`requires_tenant` in core parrot~~ — lives in `parrot-formdesigner/api/tenant.py:100`; not used here
- ~~`handlers/crew/_tenancy.resolve_session_tenant` as a reusable resolver~~ — falls back to `programs[0]`; do not reuse
- ~~a tenant in `build_eval_context`~~ — `org_id=None` (`ai-parrot/src/parrot/auth/eval_context.py:23-30`)

### Edit Sites (Blueprint Anchors)

Verified against: `718265c8e`. `S = packages/ai-parrot-server/src/parrot/handlers`.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `S/scope.py` | CREATE | — | — | — |
| `S/ui_surfaces_scope.py` | MODIFY | `class SurfaceScope:` | `:42` | 1 |
| `S/ui_surfaces_scope.py` | MODIFY | `def get_scope_resolver(app: Any) -> SurfaceScopeResolver:` | `:149` | 1 |
| `S/ui_surfaces_scope.py` | MODIFY | `def scope_grants(record: UISurfaceRecord, scope: SurfaceScope) -> bool:` | `:171` | 1 |
| `S/models/studio_visibility.py` | CREATE | — | — | — |
| `S/models/bots.py` | MODIFY | `    created_by: Optional[int] = Field(required=False, ui_help="The bot’s creator.")` | `:251` | 1 |
| `S/models/bots.py` | MODIFY | `        permissions JSONB DEFAULT '{}'::JSONB,` (docstring DDL; `created_by INTEGER,` occurs 2×) | `:78` | 1 |
| `S/models/studio_drafts.py` | MODIFY | `    owner_user_id: str = Field(required=True)` | `:73` | 1 |
| `S/models/skills_catalog.py` | MODIFY | `    owner: str = Field(required=True)` | `:64` | 1 |
| `S/studio/access.py` | CREATE | — | — | — |
| `S/studio/_base.py` | MODIFY | `    is_superuser: bool = False` | `:118` | 1 |
| `S/studio/_base.py` | MODIFY | `    async def _get_user(self) -> StudioUser:` | `:164` | 1 |
| `S/studio/agents.py` | MODIFY | `    async def _get_all(self):` | `:193` | 1 |
| `S/studio/agents.py` | MODIFY | `    async def _get_one(self, name: str):` | `:182` | 1 |
| `S/studio/agents.py` | MODIFY | `        existing = await self._check_duplicate(slug)` | `:255` | 1 |
| `S/studio/agents.py` | MODIFY | `        config_dict["created_by"] = user.user_id` | `:281` | 1 |
| `S/studio/agents.py` | MODIFY | `            result = await manager.reload_agent(name)` | `:464` | 1 |
| `S/studio/drafts.py` | MODIFY | `    async def _get_one(self, name: str):` | `:168` | 1 |
| `S/studio/drafts.py` | MODIFY | `        rows = await self._get_all_draft_rows()` | `:178` | 1 |
| `S/studio/drafts.py` | MODIFY | `        report = validate_draft(save_request.source)` (D1 guard goes before the file write at :216) | `:219` | 1 |
| `S/studio/drafts.py` | MODIFY | `            metadata.bot_config.config["created_by"] = user.user_id` | `:391` | 1 |
| `S/studio/skills_catalog.py` | MODIFY | `            entries = await self._list_entries(**filters)` | `:303` | 1 |
| `S/studio/skills_catalog.py` | MODIFY | `    async def _get_one(self, skill_id: str):` | `:316` | 1 |
| `S/studio/skills_catalog.py` | MODIFY | `            owner=user.user_id,` (inside `StudioSkillsCatalogHandler.post`; `async def post(self):` occurs 3×) | `:374` | 1 |
| `S/studio/skills_catalog.py` | MODIFY | `        exists, owner = await self._resolve_agent(agent_name)` | `:541` | 1 |
| `S/studio/testing.py` | MODIFY | `        bot = await manager.get_bot(agent_name, new=True, session_id=session_id, request=self.request)` | `:216` | 1 |
| `S/studio/testing.py` | MODIFY | `        bot_name = session.pop(key, None) if session is not None else None` | `:319` | 1 |
| `S/studio/testing.py` | MODIFY | `        self._require_owner(owner, user)  # raises web.HTTPForbidden on denial` | `:438` | 1 |
| `S/studio/toolkits.py` | MODIFY | `        self._require_owner(owner, user)  # raises web.HTTPForbidden on denial` | `:311` | 1 |
| `S/studio/toolkit_config.py` | MODIFY | `        self._require_owner(state.owner, await self._get_user())` | `:45` | 1 |
| `S/studio/toolkit_overrides.py` | MODIFY | `    async def _spec(self, name: str, slug: str):` | `:83` | 1 |
| `S/studio/files.py` | MODIFY | `        exists, _owner = await self._resolve_agent(agent_name)` | `:184` | 1 |
| `S/studio/files.py` | MODIFY | `        exists, owner = await self._resolve_agent(agent_name)` — 2×: in `put` (:236) and `delete`; quote the following `user = await self._get_user()` line per site | `:236` | 2 |
| `S/studio/meta_agent.py` | MODIFY | `            async with agent.session(request=self.request, app=self.request.app, user_id=user.user_id) as bot:` | `:110` | 1 |
| `S/studio/__init__.py` | MODIFY | `def setup_studio_routes(app: web.Application) -> None:` | `:26` | 1 |
| `S/studio/__init__.py` | MODIFY | `    app.on_startup.append(reconcile_skills_catalog)` | `:88` | 1 |
| `S/studio/models.py` | MODIFY | `class CreateAgentRequest(BaseModel):` | `:38` | 1 |
| `S/studio/models.py` | MODIFY | `class SkillPublishRequest(BaseModel):` | `:78` | 1 |
| `packages/ai-parrot/src/parrot/bots/studio/tools.py` | MODIFY | `    config_dict["created_by"] = user_id` | `:320` | 1 |
| `packages/ai-parrot/src/parrot/bots/studio/tools.py` | MODIFY | `row = StudioDraft(**fields, owner_user_id=user_id)` | `:238` | 1 |
| `packages/ai-parrot/src/parrot/bots/studio/tools.py` | MODIFY | `async def _require_agent_owner(app: Any, agent_name: str, user_id: str) -> None:` | `:84` | 1 |
| `docs/agent_studio_api.md` | MODIFY | (section-level; anchor chosen at task time) | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- FEAT-535 is the template for semantics, SQL shape and 422 rules
  (`ui_surfaces.py:512`, `:566`, `:648-686`).
- `_error(...)` helpers return plain `json_response` with `StudioError` so
  409/422/503 survive (`agents.py:150-162`).
- Startup hooks are fail-soft (`reconcile_skills_catalog` precedent).
- Core `ai-parrot` never imports `ai-parrot-server` at module level
  (`bots/studio/tools.py:25-32`): the tools read the scope object duck-typed
  from `current_context().kwargs`.
- Type-check what is read from a Mapping (FEAT-535 resolver discipline).

### Known Risks / Gotchas
- **`ai_bots` DDL on a shared production table**: `ADD COLUMN IF NOT EXISTS`
  with a constant default is metadata-only in PostgreSQL ≥ 11 but still takes
  a brief `ACCESS EXCLUSIVE` lock; the index build is not `CONCURRENTLY`
  (cannot run inside the implicit transaction). Acceptable for the table size;
  document it.
- **`BotModel` is `strict = True`** (`bots.py:362`): the new fields must exist
  before any insert — hence the startup hook runs before
  `reconcile_skills_catalog` and before the first request.
- **Registry is process-global and names are global**: `name_taken` is the
  price; do not try per-tenant names here.
- **D2 fallback relies on the `studio_drafts` row**: a host without
  `app['database']` loses activation visibility on restart (as it already
  loses `created_by` today) — logged, documented.
- **Skill import copies** the skill file; un-sharing does not revoke copies
  (FEAT-467 design).
- **Superuser bypass change**: in an opted-in host the superuser bypass of
  `_require_owner` becomes tenant-bounded (invisible ⇒ 404 first).
- **Error-code change**: `duplicate` → `name_taken` on create collisions. No
  frontend consumes Agent Studio yet (verified 2026-09-24 in
  navigator-frontend-next and navigator-svelte); documented in the API doc.
- Visibility downgrade during a live test session: the next `test/ask`
  re-checks and answers 404.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | no new dependencies (`asyncdb`, `datamodel`, `navigator-auth`, `pydantic` already used) |

---

## Worktree Strategy

- **Isolation**: one feature worktree; the `sdd-coder` engine gives each task its own sub-worktree.
- **Module dependency graph** (evidence = imports the module adds):
  - M3 → M1 (`scope_grants`, `RequestScope`), M3 → M2 (new model fields)
  - M4 → M1, M3 (`get_scope_resolver`, `StudioAccess`)
  - M5, M6, M7, M8 → M4 (base helpers)
  - M9 → M1 (duck-typed `RequestScope`), M3 (`RESERVED_CONFIG_KEYS` semantics — may inline)
  - M10 → M2 (startup hook), M5, M6, M7 (new visibility handlers)
  - M11 → all
  - M5, M6, M7, M8 are mutually independent → concurrent wave after M4.
- **Shared files**: `studio/models.py` (M5, M6, M7, M10 — request models: land in M10 or serialize), `studio/__init__.py` (M10 only), `studio/drafts.py` (M6 only).
- **Exclusive resources**: none (no lockfile/migration runner; the DDL is a startup hook).
- **Cross-feature dependencies**: none blocking. FEAT-598 (`a2ui-linked-surfaces`, draft) touches `ui_surfaces` records — coordinate on `ui_surfaces_scope.py` re-exports. External consumer: FieldSync companion `sdd/proposals/fieldsync-agentstudio.brainstorm.md` (FieldSync repo, `origin/dev` `e442a330`) must adopt `RequestScope`/`may_author` and the prefix mount before the cross-repo E2E closes.

---

## 8. Open Questions

- [x] Default behaviour without a resolver — *Resolved in brainstorm*: no resolver means unchanged FEAT-467 global reads; an installed resolver with no resolved tenant means owner-only reads.
- [x] Scope seam location and keys — *Resolved in brainstorm*: `parrot.handlers.scope`, with `app["scope_resolver"]` preferred and `app["ui_surfaces_scope_resolver"]` as compatibility fallback; `RequestScope.may_author` is the authoritative host gate because PBAC can be fail-open.
- [x] Persistence — *Resolved in brainstorm*: registry/YAML config metadata is authoritative for Studio-created and activated agents; table fields for database-origin agents; pre-existing ownerless registry agents hidden in opted-in hosts.
- [x] Names — *Resolved in brainstorm*: global uniqueness for agents, drafts, skills; all collisions return non-enumerating `409 name_taken`.
- [x] Runtime boundary — *Resolved in brainstorm*: Studio control-plane visibility only, not non-Studio chat authorization.
- [x] BYOK — *Resolved in brainstorm*: tenant key slot, quota, attribution are a separate feature; user key → configured server client fallback unchanged.
- [x] Deployment — *Resolved in brainstorm*: `AGENTS_DIR` remains pod-local; shared storage is a separate operational feature.
- [x] FieldSync prerequisite — *Resolved in brainstorm*: the companion brainstorm and resolver must adopt `RequestScope` and the URL-mount contract before the cross-repo integration test closes.
- [ ] D2 durable fallback via the activated `studio_drafts` row (added by this spec, not in the brainstorm) — acceptable, or should activation also persist the stamp elsewhere (e.g. a sidecar YAML)? — *Owner: Jesus*
- [ ] `duplicate` → `name_taken` code rename on existing FEAT-467 create routes — acceptable breaking change? — *Owner: Jesus*
- [ ] Target version 1.0.7 for both `ai-parrot-server` and `ai-parrot` (meta-agent tools live in core) — confirm release train. — *Owner: Jesus*

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` · Status: skipped (brainstorm status is `exploration`, precondition requires `accepted`) · Transcript: none.
> An independent adversarial review of the brainstorm was already performed by Jesus Lara on 2026-09-25 and folded into the brainstorm revision `306c42aca` (registry/YAML system of record, global-name scope, resolver compatibility, route inventory incl. FEAT-593 `/me`, control-plane naming, coverage matrix).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-25 | Juan Ruffato (with Claude) | Initial draft from revised brainstorm `306c42aca`; adds D1/D2 defects found during contract verification |
