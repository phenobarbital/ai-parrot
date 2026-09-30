---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
feature_id: FEAT-TBD  # PROVISIONAL — reserved on approval
# projects: parts of the codebase this doc concerns.
projects: [ai-parrot-server, ai-parrot]
# tags: free-form kebab-case keywords for organizing specs.
tags: [agentstudio, multi-tenant, storage, postgres, migrations, registry, byok]
---

<!-- LANGUAGE: This document MUST be written entirely in English (proper nouns keep native spelling). -->

# Feature Specification: Agent Studio — Database-Backed Storage

**Feature ID**: FEAT-TBD (provisional; reserved on approval)
**Date**: 2026-09-30
**Author**: Juan Ruffato (host owner, FieldSync), with Claude; for review by Jesus Lara (ai-parrot owner)
**Status**: draft
**Target version**: ai-parrot-server 1.0.7 (ai-parrot core 1.0.7 in lockstep, for the KB-directory hook and the assistant tools)
**Package**: one of three coordinated specs for "Agent Studio multi-tenant host integration":
this spec (**foundation: storage**), `agentstudio-tenant-visibility.spec.md` (FEAT-605 v0.2: access
rules on top of this storage), `agentstudio-host-toolkits.spec.md` (host toolkit discovery,
parallel lane).
**Host context**: FieldSync `artifacts/agentstudio/feat605-review.md`,
`artifacts/agentstudio/command-board-2026-09-30.md` (decisions D1–D7),
`sdd/proposals/fieldsync-agentstudio-mount.brainstorm.md` (blockers B1–B6).

---

## 1. Motivation & Business Requirements

### Problem Statement

Agent Studio (FEAT-467, extended by FEAT-593) keeps almost all of its state on the
local disk of the process that served the request:

| State | Where it lives today | Evidence |
|---|---|---|
| Agent definitions | In-memory `AgentRegistry` registration; YAML under `AGENTS_DIR/agents/<category>/` only when `persist: true` | `studio/agents.py:285-335` (`registry.register`, `create_agent_definition`, `load_agent_definition_file`) |
| identity / kb / skills assets | `AGENTS_DIR/<agent>/{identity,kb,skills}/` plain files | `studio/files.py:1-9`, `VALID_KINDS` `:26` |
| Toolkit / MCP config | agent YAML (registry agents) or `navigator.ai_bots` columns (DB agents); secrets in the DocumentDB vault | `studio/tooling_store.py:84-121`, `:292-311` |
| Drafts | Python source in `AGENTS_DIR/_drafts/<name>.py` + a `navigator.studio_drafts` row; activation imports the file and moves it to `AGENTS_DIR/<name>.py` | `studio/drafts.py:48-59`, `:357-364`; `models/studio_drafts.py` |
| Skills catalogue | `navigator.ai_skills_catalog` (system of record) + a `SkillRegistry` whose persistence path is `AGENTS_DIR/_shared/<org>/skills` | `models/skills_catalog.py`, `studio/skills_catalog.py:51-78` |
| BYOK keys | DocumentDB `user_llm_keys`, AES-GCM with the vault keyring | `studio/byok.py:31` |

Consequences for any host that runs more than one pod, or whose pods are ephemeral
(FieldSync blockers B1/B2):

- An agent created on pod A does not exist on pod B until a restart, and is lost on
  redeploy unless `AGENTS_DIR` is a shared volume.
- The runtime registry is process-global and keyed by bare name
  (`BotManager._bots: Dict[str, AbstractBot]`, `manager.py:216`; `add_bot` `:738-742`),
  so two tenants cannot both own an agent called `sales-helper`.
- Draft activation imports user-authored Python into the server process
  (`drafts.py:364`, B6). That is not acceptable on a tenant-facing path.
- Two Studio tables (`studio_drafts`, `ai_skills_catalog`) have no create code: their DDL
  lives only in model docstrings. FEAT-605 v0.1 proposed `ALTER TABLE navigator.ai_bots`
  at startup from any host (review J6).

### Decisions already taken (host owner, 2026-09-30 — not relitigated here)

1. All Studio state goes to Postgres: definitions, assets, toolkit/MCP config, drafts, catalogue.
2. New tables in schema `navigator`. `navigator.ai_bots` is **not touched**. Legacy DB bots and
   file/Python agents keep working unchanged. Studio in tenant mode reads only the new tables.
   Migrating legacy agents is a follow-up.
3. Tenant-scoped Studio agents are declarative only. The assistant emits the same definition
   `POST /agents` accepts, plus tooling. "Activate a draft" becomes "create the agent from the
   draft definition". Nothing is imported on the tenant path.
4. Names are unique per tenant: `UNIQUE(tenant, name)` plus an internal uuid. The in-memory
   registry keys Studio agents by a tenant-qualified id.
5. Pods stay in sync through a `version` / `updated_at` column (mechanism chosen in §2.6).
6. No startup DDL. Versioned SQL migrations, applied by the host.
7. KB assets are text in the DB with a size cap. Binaries (S3) are a later phase.
8. BYOK moves to Postgres in **phase 2** of this spec. v1 uses the org key.

### Goals

- G1: A Postgres schema (`navigator.ai_agents` + child tables) that stores every piece of
  Studio state with `tenant`, `owner`, `visibility`, `allowed_groups` from day one.
- G2: An async repository + service layer over the host's asyncdb pool (`app["database"]`)
  that takes a **partition** derived from the request scope and never encodes access policy.
- G3: Studio handlers switch from files to services with no response-shape break for
  existing FEAT-467/FEAT-593 clients (every additive change is listed in §2.9).
- G4: A tenant-qualified runtime cache in `BotManager` for Studio agents, with cross-pod
  consistency through the row `version`, without changing any existing name-keyed caller.
- G5: Versioned, idempotent SQL migrations shipped as package data, applied by the host
  (FieldSync runner, `psql`, or a small CLI shipped in ai-parrot-server). No DDL at startup.
- G6: Declarative-only drafts on the tenant path; the Python draft path survives only for
  non-tenant hosts, behind an explicit gate.
- G7 (phase 2): BYOK keys in a Postgres table encrypted with the vault keyring; no
  DocumentDB dependency for Studio keys.

### Non-Goals (explicitly out of scope)

- Access rules (who sees or edits what). They belong to FEAT-605 v0.2. This spec stores and
  returns the visibility fields and exposes a partition-only API.
- Migrating `navigator.ai_bots` rows, YAML agents or Python agents into `ai_agents`. Follow-up.
- Binary KB documents (PDF, images) and object storage (S3). A column is reserved (§2.3).
- Runtime use of Studio agents outside Studio (public chat endpoints, surfaces, scheduler).
  `get_bot(name)` does not resolve tenant agents (§2.7). Separate follow-up (host P13).
- Sticky sessions for in-memory test/assistant sessions (`testing.py`, `meta_agent.py`
  `_instances`). They stay per pod; noted in §7.
- Toolkit-secret vault migration off DocumentDB (`user_credentials`). Raised as Open Question Q5.
- Tenant-awareness of the global `AgentRegistry` (`agent_registry` singleton). Studio agents
  never enter it.

---

## 2. Architectural Design

### 2.1 Overview

```
Studio view (handlers/studio/*.py)
   │  partition = await self._studio_partition()  ← GLOBAL until FEAT-605 v0.2 derives it from RequestScope
   │  (FEAT-605 v0.2 applies can_see/owns on the records returned below)
   ▼
Studio services (handlers/studio/storage/services.py)      validation, size caps, bot-class allowlist,
   │                                                        secret split (reuses AgentToolingStore logic)
   ▼
Studio repositories (handlers/studio/storage/repositories.py)   raw parametrised SQL, asyncdb pool,
   │                                                             one partition argument on every method
   ▼
Postgres  navigator.ai_agents ─┬─ ai_agent_assets
                               ├─ ai_agent_tooling
          navigator.ai_agent_drafts   navigator.ai_skills_catalog (migrated in place)
          navigator.ai_studio_migrations (applied-migration ledger)

BotManager ── StudioAgentRuntime (manager/studio_runtime.py)
                 cache key "studio:<tenant|->:<name>" in BotManager._bots
                 revalidate: SELECT version … on every lookup (§2.6)
                 build: row → BotConfig → registry.create_agent_factory() → instance
                 assets: identity → constructor kwargs; kb/skills → per-pod derived cache dir
```

### 2.2 Storage backend selection

A single setting, read once at `setup_studio_routes()`:

| `PARROT_STUDIO_STORAGE` | Behaviour |
|---|---|
| `auto` (default) | `database` when `app["database"]` exists **and** the read-only probe `SELECT max(version) FROM navigator.ai_studio_migrations` returns at least the version this release requires; otherwise `filesystem`, logged at WARNING once. |
| `database` | Probe failure is logged at ERROR and every Studio endpoint answers 503 `studio_storage_unavailable` (fail closed). |
| `filesystem` | Current FEAT-467 behaviour, unchanged. Non-tenant hosts only. **Deprecated** — kept so a plain host that has not applied the migrations keeps working. |

The resolved backend is stored at `app["studio_storage"]` (a `StudioStorage` object, §3 M4).
A request whose partition has a tenant is refused with 503 `studio_storage_unavailable`
when the backend is `filesystem`. A tenant is never stored on disk.

The probe is a `SELECT`, never DDL. When the ledger table is missing, the probe fails and
the backend resolves as above.

### 2.3 Schema (owned by this spec; final contract)

All tables live in schema `navigator` (literal, not `PARROT_SCHEMA`; see Q6). Types are
`text` + `CHECK` rather than enums so a future value is one migration, not an enum rewrite.

```sql
-- 0001_studio_migrations_ledger.sql
CREATE TABLE IF NOT EXISTS navigator.ai_studio_migrations (
    version     integer PRIMARY KEY,
    name        text        NOT NULL,
    checksum    text        NOT NULL,          -- sha256 of the file body, recorded by the file itself
    applied_at  timestamptz NOT NULL DEFAULT now()
);

-- 0002_ai_agents.sql
CREATE TABLE IF NOT EXISTS navigator.ai_agents (
    agent_id        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant          text        NULL,         -- NULL = non-tenant host
    name            text        NOT NULL,
    owner           text        NOT NULL,     -- session user_id, stringified
    visibility      text        NOT NULL DEFAULT 'private',
    allowed_groups  text[]      NOT NULL DEFAULT '{}',
    definition      jsonb       NOT NULL,     -- StudioAgentDefinition (schema_version 1)
    status          text        NOT NULL DEFAULT 'active',
    version         integer     NOT NULL DEFAULT 1,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ai_agents_visibility_chk CHECK (visibility IN ('private','tenant','groups')),
    CONSTRAINT ai_agents_status_chk     CHECK (status IN ('active','disabled')),
    CONSTRAINT ai_agents_name_chk       CHECK (name ~ '^[a-z0-9_-]{1,64}$'),
    CONSTRAINT ai_agents_tenant_chk     CHECK (tenant IS NULL OR tenant ~ '^[a-z0-9][a-z0-9_-]{0,62}$'),
    CONSTRAINT ai_agents_shared_needs_tenant_chk CHECK (tenant IS NOT NULL OR visibility = 'private'),
    CONSTRAINT ai_agents_tenant_name_key UNIQUE (tenant, name)
);
-- NULLs are distinct in a UNIQUE constraint; this closes the gap for non-tenant rows
-- without requiring PG15 "NULLS NOT DISTINCT".
CREATE UNIQUE INDEX IF NOT EXISTS ai_agents_global_name_uq ON navigator.ai_agents (name) WHERE tenant IS NULL;
CREATE INDEX IF NOT EXISTS ai_agents_tenant_owner_idx      ON navigator.ai_agents (tenant, owner);
CREATE INDEX IF NOT EXISTS ai_agents_tenant_visibility_idx ON navigator.ai_agents (tenant, visibility);
CREATE INDEX IF NOT EXISTS ai_agents_allowed_groups_gin    ON navigator.ai_agents USING gin (allowed_groups);

CREATE TABLE IF NOT EXISTS navigator.ai_agent_assets (
    agent_id      uuid        NOT NULL REFERENCES navigator.ai_agents(agent_id) ON DELETE CASCADE,
    kind          text        NOT NULL CHECK (kind IN ('identity','kb','skills')),
    name          text        NOT NULL,       -- relative path, e.g. 'role.md', 'faq.md', 'triage/SKILL.md'
    content       text        NULL,           -- v1: always set (text only)
    content_type  text        NOT NULL DEFAULT 'text/markdown',
    size          integer     NOT NULL,       -- octet_length(content) for text rows
    storage_uri   text        NULL,           -- reserved: phase-S3 binary documents (v1 never writes it)
    sha256        text        NOT NULL,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, kind, name),
    CONSTRAINT ai_agent_assets_body_chk CHECK (content IS NOT NULL OR storage_uri IS NOT NULL),
    CONSTRAINT ai_agent_assets_hard_cap_chk CHECK (content IS NULL OR octet_length(content) <= 1048576),
    CONSTRAINT ai_agent_assets_name_chk CHECK (name !~ '(^/|\.\.)')
);

CREATE TABLE IF NOT EXISTS navigator.ai_agent_tooling (
    agent_id     uuid        NOT NULL REFERENCES navigator.ai_agents(agent_id) ON DELETE CASCADE,
    kind         text        NOT NULL CHECK (kind IN ('toolkit','mcp')),
    slug         text        NOT NULL,        -- toolkit slug, or MCP server name
    position     integer     NOT NULL DEFAULT 0,
    config       jsonb       NOT NULL DEFAULT '{}'::jsonb,   -- secret-free params (ToolkitSpec / AgentMCPServerSpec dump)
    secret_refs  jsonb       NOT NULL DEFAULT '{}'::jsonb,   -- {dotted.path: vault_name}; values never stored here
    vault_owner  text        NULL,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, kind, slug)
);

-- Version bump is enforced in the database so that no writer (Studio, a host backfill,
-- psql) can change an agent without the other pods noticing (§2.6).
CREATE OR REPLACE FUNCTION navigator.ai_agents_bump_version() RETURNS trigger AS $$
BEGIN
    NEW.version    := OLD.version + 1;
    NEW.updated_at := now();
    RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE OR REPLACE TRIGGER ai_agents_bump_version_trg
    BEFORE UPDATE ON navigator.ai_agents FOR EACH ROW EXECUTE FUNCTION navigator.ai_agents_bump_version();

CREATE OR REPLACE FUNCTION navigator.ai_agents_touch_parent() RETURNS trigger AS $$
BEGIN
    UPDATE navigator.ai_agents SET updated_at = now()
     WHERE agent_id = COALESCE(NEW.agent_id, OLD.agent_id);
    RETURN NULL;
END $$ LANGUAGE plpgsql;
CREATE OR REPLACE TRIGGER ai_agent_assets_touch_trg
    AFTER INSERT OR UPDATE OR DELETE ON navigator.ai_agent_assets
    FOR EACH ROW EXECUTE FUNCTION navigator.ai_agents_touch_parent();
CREATE OR REPLACE TRIGGER ai_agent_tooling_touch_trg
    AFTER INSERT OR UPDATE OR DELETE ON navigator.ai_agent_tooling
    FOR EACH ROW EXECUTE FUNCTION navigator.ai_agents_touch_parent();

-- 0003_ai_agent_drafts.sql
CREATE TABLE IF NOT EXISTS navigator.ai_agent_drafts (
    draft_id        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant          text        NULL,
    owner           text        NOT NULL,
    name            text        NOT NULL,
    visibility      text        NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','tenant','groups')),
    allowed_groups  text[]      NOT NULL DEFAULT '{}',
    definition      jsonb       NOT NULL,     -- StudioAgentBundle (definition + tooling + assets)
    validation      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status          text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','validated','failed','activated')),
    activated_agent_id uuid     NULL REFERENCES navigator.ai_agents(agent_id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ai_agent_drafts_name_chk CHECK (name ~ '^[a-z0-9_-]{1,64}$'),
    CONSTRAINT ai_agent_drafts_shared_needs_tenant_chk CHECK (tenant IS NOT NULL OR visibility = 'private'),
    CONSTRAINT ai_agent_drafts_tenant_name_key UNIQUE (tenant, name)
);
CREATE UNIQUE INDEX IF NOT EXISTS ai_agent_drafts_global_name_uq ON navigator.ai_agent_drafts (name) WHERE tenant IS NULL;
CREATE INDEX IF NOT EXISTS ai_agent_drafts_tenant_owner_idx ON navigator.ai_agent_drafts (tenant, owner);

-- 0004_ai_skills_catalog_tenancy.sql
-- The table already exists on hosts that ran FEAT-467 (DDL only in the model docstring,
-- models/skills_catalog.py). Baseline first, then extend in place.
CREATE TABLE IF NOT EXISTS navigator.ai_skills_catalog ( /* FEAT-467 shape, verbatim from
    models/skills_catalog.py docstring: skill_id, name UNIQUE, description, category, owner,
    triggers, body, version, status, search_index_stale, created_at, updated_at */ );
ALTER TABLE navigator.ai_skills_catalog ADD COLUMN IF NOT EXISTS tenant         text   NULL;
ALTER TABLE navigator.ai_skills_catalog ADD COLUMN IF NOT EXISTS visibility     text   NOT NULL DEFAULT 'private';
ALTER TABLE navigator.ai_skills_catalog ADD COLUMN IF NOT EXISTS allowed_groups text[] NOT NULL DEFAULT '{}';
ALTER TABLE navigator.ai_skills_catalog DROP CONSTRAINT IF EXISTS ai_skills_catalog_name_key;   -- global UNIQUE(name)
ALTER TABLE navigator.ai_skills_catalog ADD CONSTRAINT ai_skills_catalog_tenant_name_key UNIQUE (tenant, name);  -- guarded by a DO block
CREATE UNIQUE INDEX IF NOT EXISTS ai_skills_catalog_global_name_uq ON navigator.ai_skills_catalog (name) WHERE tenant IS NULL;
CREATE INDEX IF NOT EXISTS ai_skills_catalog_tenant_visibility_idx ON navigator.ai_skills_catalog (tenant, visibility);
-- Existing rows: tenant NULL, visibility 'private' (their current global behaviour is kept
-- for non-tenant hosts; FEAT-605 v0.2 decides adoption).

-- 0005_studio_drafts_baseline.sql
-- Legacy Python drafts (non-tenant only). Create-if-missing from the model docstring
-- (models/studio_drafts.py); no column changes.
CREATE TABLE IF NOT EXISTS navigator.studio_drafts ( /* FEAT-467 shape, verbatim */ );

-- Phase 2 — 0006_ai_user_llm_keys.sql  (see §2.10)
```

Every file ends by recording itself:
`INSERT INTO navigator.ai_studio_migrations(version, name, checksum) VALUES (…) ON CONFLICT (version) DO NOTHING;`
The checksum is computed by the release tooling and committed in the file; `migrate.py
--verify` recomputes it and reports drift.

`gen_random_uuid()` is core in PG13+. Q7 covers older servers.

### 2.4 Data Models

```python
# handlers/studio/storage/models.py  (new)

@dataclass(frozen=True, slots=True)
class StudioPartition:
    """The ONLY way to address rows. tenant=None is the non-tenant partition."""
    tenant: str | None
    GLOBAL: ClassVar["StudioPartition"]           # StudioPartition(None)

    @classmethod
    def from_scope(cls, scope: Any) -> "StudioPartition":
        """Duck-typed on `.tenant` so this module does not import FEAT-605's RequestScope."""

@dataclass(frozen=True, slots=True)
class StudioAgentKey:
    tenant: str | None
    name: str
    @property
    def qualified(self) -> str:
        """'studio:<tenant>:<name>', or 'studio:-:<name>' for tenant None.
        '-' can never be a tenant (tenant CHECK requires a leading [a-z0-9]),
        ':' can never appear in a name (name CHECK)."""
    @classmethod
    def parse(cls, qualified: str) -> "StudioAgentKey": ...

class StudioAgentDefinition(BaseModel):
    """What POST /agents accepts, minus transport flags. Stored in ai_agents.definition."""
    schema_version: Literal[1] = 1
    bot_class: str = "BasicBot"
    llm: str | None = None
    description: str | None = None
    category: str = "general"          # kept for UI grouping; no longer a path segment
    config: dict[str, Any] = Field(default_factory=dict)   # FEAT-605 reserved keys rejected

    @classmethod
    def from_create_request(cls, req: CreateAgentRequest) -> "StudioAgentDefinition": ...

class StudioAgentPatch(BaseModel):
    """PATCH /agents/{name} body (§2.9a). Merge-patch of the General fields; omitted = unchanged."""
    model_config = ConfigDict(extra="forbid")      # unknown key (incl. `name`, `bot_class`) → 422
    description: str | None = None
    llm: str | None = None                         # "provider:model", as CreateAgentRequest.llm
    model_params: dict[str, Any] | None = None     # merged into definition.config (temperature, max_tokens…);
                                                   #   FEAT-605 reserved keys rejected
    system_prompt: str | None = None               # stored as definition.config["system_prompt"]
                                                   #   (AbstractBot kwarg, abstract.py:277)
    category: str | None = None
    expected_version: int | None = None

class StudioAssetInput(BaseModel):
    kind: Literal["identity", "kb", "skills"]
    name: str
    content: str
    content_type: str = "text/markdown"

class StudioAgentBundle(BaseModel):
    """What the assistant emits and a draft stores: definition + tooling + assets.
    Secret-bearing fields are refused (secrets are entered in the Tools tab)."""
    name: str
    definition: StudioAgentDefinition
    toolkits: list[ToolkitSpec] = Field(default_factory=list)
    mcp_servers: list[AgentMCPServerSpec] = Field(default_factory=list)
    assets: list[StudioAssetInput] = Field(default_factory=list)

@dataclass(frozen=True, slots=True)
class StudioAgentRecord:
    agent_id: UUID; tenant: str | None; name: str; owner: str
    visibility: str; allowed_groups: tuple[str, ...]
    definition: StudioAgentDefinition; status: str; version: int
    created_at: datetime; updated_at: datetime
    @property
    def key(self) -> StudioAgentKey: ...

@dataclass(frozen=True, slots=True)
class StudioAssetRecord:   agent_id: UUID; kind: str; name: str; content: str | None
                           content_type: str; size: int; sha256: str; storage_uri: str | None; updated_at: datetime
@dataclass(frozen=True, slots=True)
class StudioToolingRecord: agent_id: UUID; kind: str; slug: str; position: int
                           config: dict; secret_refs: dict; vault_owner: str | None; updated_at: datetime
@dataclass(frozen=True, slots=True)
class StudioDraftRecord:   draft_id: UUID; tenant: str | None; owner: str; name: str
                           visibility: str; allowed_groups: tuple[str, ...]; bundle: StudioAgentBundle
                           validation: dict; status: str; activated_agent_id: UUID | None
                           created_at: datetime; updated_at: datetime
@dataclass(frozen=True, slots=True)
class StudioSkillRecord:   skill_id: UUID; tenant: str | None; owner: str; visibility: str
                           allowed_groups: tuple[str, ...]; name: str; description: str; category: str
                           triggers: list; body: str; version: int; status: str
                           search_index_stale: bool; created_at: datetime; updated_at: datetime
```

Every record exposes `owner`, `tenant`, `visibility`, `allowed_groups`, so FEAT-605 v0.2
can map it to its `StudioVisibilityRecord` without another query.

Repositories use raw parametrised SQL, not asyncdb `Model` classes: `text[]` columns and
`Optional`-typed fields are exactly where the asyncdb model processor has already failed
(`models/studio_drafts.py` docstring, TASK-2522), and raw SQL keeps every query auditable
for the partition predicate.

### 2.5 Repository and service API

```python
# handlers/studio/storage/repositories.py  (new)
class StudioAgentRepository:
    def __init__(self, pool: Any) -> None: ...    # app["database"] (asyncdb pg pool)
    async def get(self, part: StudioPartition, name: str) -> StudioAgentRecord | None
    async def get_version(self, part: StudioPartition, name: str) -> tuple[UUID, int] | None
    async def list(self, part: StudioPartition, *, owner: str | None = None) -> list[StudioAgentRecord]
    async def create(self, part: StudioPartition, *, name: str, owner: str,
                     definition: StudioAgentDefinition, visibility: str = "private",
                     allowed_groups: Sequence[str] = (), conn: Any = None) -> StudioAgentRecord
        # raises StudioNameConflict on either unique index
    async def update_definition(self, part, name, definition, *, expected_version: int | None = None) -> StudioAgentRecord
        # raises StudioVersionConflict when expected_version is given and differs
    async def update_visibility(self, part, name, *, visibility: str, allowed_groups: Sequence[str]) -> StudioAgentRecord
    async def set_status(self, part, name, status: str) -> StudioAgentRecord
    async def delete(self, part, name) -> bool                    # cascades to assets + tooling

class StudioAssetRepository:
    async def list(self, part, agent_name, kind: str | None = None) -> list[StudioAssetRecord]   # content omitted
    async def get(self, part, agent_name, kind, name) -> StudioAssetRecord | None
    async def put(self, part, agent_name, asset: StudioAssetInput, *, conn=None) -> StudioAssetRecord
    async def delete(self, part, agent_name, kind, name) -> bool
    async def load_all(self, agent_id: UUID) -> list[StudioAssetRecord]     # runtime builder only; id from a partitioned read

class StudioToolingRepository:
    async def list(self, part, agent_name) -> list[StudioToolingRecord]
    async def replace(self, part, agent_name, *, toolkits: Sequence[StudioToolingRecord],
                      mcp_servers: Sequence[StudioToolingRecord], conn=None) -> None   # one transaction
    async def upsert(self, part, agent_name, record: StudioToolingRecord) -> None
    async def delete(self, part, agent_name, kind: str, slug: str) -> bool

class StudioDraftRepository:     get / list(owner=) / upsert / set_status / update_visibility / delete     (partitioned, same shape)
class StudioSkillCatalogRepository: get(part, skill_id) / get_by_name / list(category=, owner=) / insert / update / update_visibility / delete / mark_stale / list_stale

class InMemoryStudioRepositories:  # storage/testing.py — same method set as the five repositories;
    # enforces UNIQUE(tenant, name) including the tenant-NULL partial index, the
    # tenant-NULL ⇒ private CHECK and the version bump, and raises the same
    # StudioNameConflict / StudioVersionConflict / None-for-absent signals. For FEAT-605 tests.

# Every child-table method joins through ai_agents with the partition predicate
#   WHERE a.name = $n AND a.tenant IS NOT DISTINCT FROM $t
# so an agent_id from another tenant is unreachable by construction.
```

```python
# handlers/studio/storage/services.py  (new)
class StudioAgentService:
    def __init__(self, repos: StudioRepositories, *, limits: StudioLimits,
                 class_allowlist: StudioClassAllowlist, tooling: "StudioToolingService") -> None
    async def create(self, part, *, owner: str, definition: StudioAgentDefinition,
                     bundle_extras: StudioAgentBundle | None = None) -> StudioAgentRecord
        # validates bot_class (allowlist when part.tenant is not None), reserved config keys,
        # name slug; inserts agent + tooling + assets in ONE transaction
    async def update(self, part, name, definition, *, expected_version=None) -> StudioAgentRecord
    async def patch(self, part, name, patch: StudioAgentPatch) -> StudioAgentRecord
        # merges into the stored definition, validates as `create` does, then update_definition
        # (version bumped by the trigger); StudioVersionConflict on expected_version mismatch
    async def update_visibility(self, part, name, *, visibility: str,
                                allowed_groups: Sequence[str]) -> StudioAgentRecord   # FEAT-605 PATCH …/visibility
    async def delete(self, part, name) -> bool
    async def get(self, part, name) -> StudioAgentRecord | None
    async def list(self, part, *, owner=None) -> list[StudioAgentRecord]

class StudioAssetService:      put / get / list / delete  — enforces StudioLimits, text-only (415), identity
                               filenames (IDENTITY_FILES), kb .md/.txt, skills paths + parse_skill_file
class StudioToolingService:    load / put_toolkit / delete_toolkit / put_mcp_servers — the FEAT-593 validation,
                               masking and secret split of AgentToolingStore, persisted to ai_agent_tooling
class StudioDraftService:      save_bundle / get / list / delete / update_visibility / activate(part, name, *, owner, replace=False)
                               activate = StudioAgentService.create/update from bundle; stamps activated_agent_id
class StudioSkillCatalogService: publish / update / update_visibility / delete / list / import_to_agent(part, skill_id, agent_name)
```

**Policy boundary.** Services validate *data* (shape, size, allowlists, uniqueness). They do
not decide *access*. Handlers keep their existing ownership calls (`_require_owner`) until
FEAT-605 v0.2 replaces them with `StudioAccess.can_see/owns` applied to the records returned
here. Listing is partition-scoped in SQL and visibility-filtered in Python by FEAT-605. That is
cheap because a tenant partition holds tens to hundreds of rows, and it keeps every policy
branch in one module. SQL push-down is a later optimisation behind the same service signature.

**Limits** (`StudioLimits`, from config, defaults):

| Setting | Default | Error |
|---|---|---|
| `STUDIO_ASSET_MAX_BYTES_IDENTITY` | 64 KiB per file | 413 `asset_too_large` |
| `STUDIO_ASSET_MAX_BYTES_KB` | 256 KiB per file | 413 |
| `STUDIO_ASSET_MAX_BYTES_SKILLS` | 128 KiB per file | 413 |
| `STUDIO_AGENT_MAX_ASSET_BYTES` | 4 MiB total per agent | 413 `agent_assets_quota` |
| DB hard ceiling | 1 MiB per row (`CHECK`) | 500 if bypassed; the service caps are always lower |

**Bot-class allowlist.** On a tenant partition, `bot_class` must be one of the classes
exported by `parrot.bots.__all__` (the source the catalog already uses,
`studio/catalog.py:96-104`) plus any the host adds via
`app["studio_class_allowlist"]`. `BotManager.get_bot_class` alone is not enough: it imports
`parrot.agents.<bot_class.lower()>` from a client-supplied string (`manager.py:291-296`).
Non-tenant partitions keep today's `get_bot_class` resolution.

### 2.6 Cross-pod synchronisation — chosen mechanism

**Chosen: read-through revalidation on every lookup, keyed on `ai_agents.version`
(bumped by trigger). No `LISTEN/NOTIFY` in v1.**

On every `StudioAgentRuntime.get(key)`:

1. `SELECT agent_id, version, status FROM navigator.ai_agents WHERE tenant IS NOT DISTINCT FROM $1 AND name = $2`
   (served by the `(tenant, name)` unique index).
2. Row missing or `status='disabled'` → evict the cached instance, return `None`.
3. Cached instance with the same `(agent_id, version)` → return it.
4. Otherwise rebuild under a per-key `asyncio.Lock` (single flight), swap, clean up the old
   instance with the existing `_safe_cleanup`.

Why this and not `LISTEN/NOTIFY`:

- **Correct by construction.** A pod cannot serve a stale definition. A missed notification
  (reconnect, pod start during a write, notify dropped when the transaction rolls back)
  cannot cause drift, because nothing depends on notifications.
- **No new infrastructure.** `LISTEN` needs a dedicated, long-lived, non-pooled connection
  per pod, reconnect logic, and it does not work through PgBouncer in transaction mode.
  The host's pool (`app["database"]`) cannot hold it.
- **Cost is bounded.** One indexed single-row `SELECT` per Studio lookup, on a path that is
  about to run an LLM call. The trigger makes the version unbypassable, including host backfills.
- **Optional knob.** `STUDIO_REVALIDATE_TTL_SECONDS` (default `0` = always revalidate). A host
  that wants fewer queries accepts up to TTL seconds of staleness. `LISTEN/NOTIFY` can be added
  later as an *accelerator* in front of the same check, never as the source of truth.

Listings (`GET /agents`, drafts, skills) always read Postgres, so they are consistent across
pods without any cache.

### 2.7 Registry integration (`BotManager`)

- Studio instances live in `BotManager._bots` under `StudioAgentKey.qualified`
  (`studio:<tenant|->:<name>`), so cleanup (`_cleanup_all_bots`), expiry and `get_bots()`
  keep working. `_botdef` is filled the same way `add_bot` does.
- New: `BotManager.studio` → `StudioAgentRuntime`, installed by one `on_startup` step that runs
  after `resolve_studio_storage` and only when `app["studio_storage"].backend == "database"`.
  The step is appended by `setup()` **and** by FEAT-605's `BotManager.setup_registry_only(app)`
  (its storage extension point), so a host that never calls `setup()` still gets the runtime.
  There is no eager materialisation: Studio agents are built lazily on first lookup.
- New: `await manager.get_studio_bot(key, *, new=False, session_id="", request=None)`:
  - `new=False`: `studio.get(key)` (revalidating, §2.6), then `enforce_agent_access(evaluator, key.qualified, request)`.
  - `new=True` (test chat): builds a **fresh instance from the current row** (not a clone of the
    cached one), registered as `f"{key.qualified}_{session_id}"` with the existing 1 h expiry.
    The instance carries `_studio_version`. `testing.py` rebuilds the session instance when
    the row version moved.
- `get_bot(name)` is unchanged for every existing caller, with **one additive fallback**: when
  the name is not found in `_bots` or the registry, the backend is `database`, and the host is
  not tenant-scoped, it tries `studio.get(StudioAgentKey(None, name))`. **Tenant rows are
  never reachable through `get_bot`**, and a qualified id passed to `get_bot` is not parsed.
  Exposing tenant agents to name-keyed runtime callers (chat, A2A, scheduler) needs a scope
  check and is the P13 follow-up.
- `reload_agent(name)` is unchanged. The Studio reload handler in DB mode calls
  `studio.reload(key)` (forced rebuild, same `ReloadResult` shape, `name` = bare name).
- `_load_database_bots` is not modified (it reads `ai_bots` only). Studio agents are loaded
  lazily on first lookup. No eager load at startup, so boot time does not grow with tenants.

**Instance build** (`StudioAgentBuilder`, §3 M7):

1. `BotConfig(name=<bare name>, class_name, module, origin="factory",
   config={**definition.config, "created_by": owner, "description": …},
   model=ModelConfig(...) if definition.llm, toolkits=[ToolkitSpec…], mcp_servers=[…])`.
   `created_by` is stamped for compatibility with `_registry_agent_owner` readers. The row
   columns are authoritative.
2. `factory = agent_registry.create_agent_factory(bot_config)`. This reuses the declarative
   translation (`registry.py:846-940`) **without registering** anything in the global registry.
3. Identity assets → constructor kwargs `role/goal/capabilities/backstory/rationale`
   (`AbstractBot.__init__` reads them from kwargs, `abstract.py:427-431`). No identity directory.
4. KB and skills assets → written to a **derived, per-pod cache**
   `STUDIO_RUNTIME_DIR/<agent_id>/v<version>/<name>/{kb,skills}/`
   (default `<tempdir>/parrot-studio-<pid>`, **never under `AGENTS_DIR`**). The instance gets
   `_agents_dir = STUDIO_RUNTIME_DIR/<agent_id>/v<version>` before `configure()`. The skills
   mixin already honours `_agents_dir` (`skills/mixin.py:81-96`). `LocalKBMixin` does not
   (`stores/local.py:56` hardcodes `AGENTS_DIR`), so core gets a small hook (§3 M10). The
   cache is disposable: deleted when a version is evicted, rebuilt from Postgres on demand,
   and never read as a source of truth.
5. `await bot.configure(app)`, then `bot._studio_key`, `bot._studio_version` are set.

### 2.8 Handler switch (files → services)

Each handler verb resolves `storage = self.request.app["studio_storage"]`. When
`storage.backend == "filesystem"`, the **existing body runs unchanged** (moved into a
`_legacy_<verb>` method, verbatim). Otherwise the service path runs. No handler grows past
Rule-4 budgets: the service path is a few lines per verb.

| Handler | Database-mode behaviour |
|---|---|
| `agents.py` `StudioAgentsHandler` | POST → `StudioAgentService.create` (always persisted; `persist`/`category` accepted, `category` stored in definition). Duplicate check: `ai_agents` partition, plus, for the GLOBAL partition only, the legacy registry and `ai_bots` names (keeps FEAT-467's 409 across stores). GET → service list/get; the GLOBAL partition still merges legacy DB and registry agents (as today), a tenant partition returns Studio rows only (decision 2). DELETE → service delete; the legacy `delegated`/`no_definition` branches apply only to legacy agents. **New** `patch` verb (`PATCH /agents/{name}`, §2.9a) → `StudioAgentService.patch`; database mode only. |
| `agents.py` `StudioAgentReloadHandler` | Studio agent → `manager.studio.reload(key)`; legacy → `manager.reload_agent(name)` as today. |
| `files.py` | `StudioAssetService`; same validation rules; `write_text` and `resolve_safe_path` disappear from the DB path. |
| `tooling_store.py` / `toolkit_config.py` / `toolkits.py` (assign) | `AgentToolingStore.load()` gains a first branch: Studio row → `ToolingState(source="studio")` and `_persist` → `StudioToolingRepository.replace`. Validation, masking, `_split_secrets` and vault writes are reused unchanged. |
| `toolkit_overrides.py` | Unchanged (per-user overrides). Agent lookup goes through the service when the agent is a Studio row. |
| `drafts.py` | POST accepts either `{name, source}` (Python, legacy) or `{name, bundle}` (declarative). Declarative → `StudioDraftService.save_bundle` (validation = Pydantic + allowlist + tooling schema). Activate on a declarative draft → `StudioDraftService.activate` (create, or update when `replace: true`). |
| `skills_catalog.py` | `StudioSkillCatalogService`; the shared `SkillRegistry` becomes a derived search index: namespace `<tenant or org_id>/_shared`, persistence path under `STUDIO_RUNTIME_DIR/_shared/<partition>/skills` (not `AGENTS_DIR`), rebuilt by `resync`/startup reconcile from Postgres. Import-to-agent writes an `ai_agent_assets` row. |
| `testing.py` | Resolves Studio agents through `get_studio_bot(key, new=True, …)`; the session key uses `key.qualified`; stale-version rebuild (§2.7). |
| `meta_agent.py` + core `bots/studio/tools.py` | Tools call the services (`create_yaml_agent` → `StudioAgentService.create`, `write_*_file` → `StudioAssetService.put`, new `save_agent_bundle` → `StudioDraftService.save_bundle`). Partition = `StudioPartition.from_scope(current_context().kwargs["studio_scope"].caller)` when FEAT-605 v0.2 binds `studio_scope` (built by its `build_tool_scope`; the tenant lives on `.caller`, not on the scope object), else GLOBAL. |
| `byok.py` | v1 unchanged (DocumentDB, or org key when the host does not mount `/keys`). Phase 2: §2.10. |
| `catalog.py` | Unchanged. |

**Python drafts gate.** The Python path (`source`, `save_agent_draft`, activate-by-import)
runs only when **all** hold: partition is GLOBAL, `STUDIO_PYTHON_DRAFTS` is true (default
`true` for backward compatibility), and the caller passes the existing superuser/owner
checks. On a tenant partition: 422 `declarative_only` (the FEAT-605 v0.2 code; one code for both
specs), and the assistant's tool list is
built **without** `save_agent_draft` (so the LLM is never offered it). This is checked by
`StudioDraftService.python_drafts_allowed(part)`, the single decision point.

**Partition source.** `async StudioBaseView._studio_partition()` (new, M4) returns
`StudioPartition.GLOBAL` in this spec. FEAT-605 v0.2 overrides it to
`StudioPartition.from_scope(await self._scope())` (tenant only; access policy stays in
FEAT-605's `StudioAccess`). It is `async` because the override awaits the scope. In an
opted-in host whose scope has no tenant, the FEAT-605 override never returns GLOBAL: the
handler answers empty / 404 / 422 `tenant_required` before any storage call, so tenant-NULL
rows are reachable only from hosts with no resolver. So this spec ships standalone for
non-tenant hosts, and tenancy lights up when FEAT-605 v0.2 lands (order D7).

### 2.9 Backward compatibility — every response-shape change

No field is removed or renamed. Filesystem mode is byte-for-byte unchanged. Database mode:

| Endpoint | Change (database mode) |
|---|---|
| `POST /agents` → 201 | `source: "studio"` (was `"registry"`); `persisted: true` always; `file_path: null`; **added** `agent_id`, `version`, `tenant`; **added** `warnings: [..]` when `persist: false` was sent ("ignored: database storage always persists"). |
| `GET /agents` items | new item kind with `source: "studio"`, `origin: "studio"`; **added** keys `agent_id`, `tenant`, `version`, `updated_at`, `visibility`, `allowed_groups` on Studio items only. Tenant partition: legacy `"registry"`/`"database"` items are not listed. |
| `GET /agents/{name}` | same keys as a list item. |
| `DELETE /agents/{name}` | same `{name, deleted}`; `409 no_definition` / `409 delegated` never returned for Studio rows. |
| `POST /agents/{name}/reload` | same `ReloadResult`. |
| `GET/PUT/DELETE /agents/{name}/files/...` | `reload_required` is `false` (writes apply on the next lookup on every pod, §2.6); **added** `version` (agent version after the write) and `sha256`. New errors: 413 `asset_too_large`, 413 `agent_assets_quota`, 415 `binary_assets_unsupported`. List stays `{kind, files: [str]}`. |
| `POST /drafts` | request **added** alternative body `{name, bundle}`; response `file_path: null` and **added** `kind: "declarative"` for bundle drafts (`kind: "python"` added on legacy drafts). Tenant partition + `source` → 422 `declarative_only`. |
| `GET /drafts[/{name}]` | **added** `kind`, `bundle` (declarative only), `tenant`, `visibility`, `allowed_groups`. |
| `POST /drafts/{name}/activate` | declarative: `{name, activated: true, file_path: null}` + **added** `agent_id`, `version`. |
| `toolkit-config`, `toolkits/{slug}`, `mcp-servers` | none. `editable` is true for Studio rows with an owner. |
| `/skills*` | **added** `tenant`, `visibility`, `allowed_groups` on items. Name uniqueness becomes per partition. The 409 is raised from `StudioNameConflict`; its body code is today's `duplicate` until FEAT-605 v0.2 lands and renames it to `name_taken` in every host (FEAT-605 C4, AC3). The same applies to the `POST /agents` 409. |
| Any mutating body | optional **added** `expected_version`; mismatch → 409 `version_conflict`. |
| All | 503 `studio_storage_unavailable` (new code) when the backend is unusable for the request. |
| `PATCH /agents/{name}` | **new route** (§2.9a). Nothing existing changes. |

### 2.9a `PATCH /agents/{name}` — edit an agent's General fields

- **Route**: `PATCH {prefix}/agents/{name}`, a new `patch` verb on the existing
  `StudioAgentsHandler` view (same `add_view` path as GET/DELETE `/agents/{name}`, so no new
  route line and no ordering issue with FEAT-605's `/agents/{name}/visibility`).
- **Body**: `StudioAgentPatch` (§2.4). Updatable: `description`, `llm`, `model_params`
  (merged into `definition.config`), `system_prompt` (`definition.config["system_prompt"]`),
  `category`. Optional `expected_version` → 409 `version_conflict` on mismatch. Reserved keys
  (FEAT-605 `RESERVED_KEYS`) inside `model_params` → 400 `reserved_config_key`.
- **Not updatable**: `name` → 422 `name_immutable`. `bot_class` → 422 (unknown key; a class
  change is a re-create, because the allowlist and the config shape depend on it). Identity
  files (`role.md`, …), KB, skills and tooling keep their own routes; this PATCH never writes
  assets or tooling.
- **Why the name is immutable**: the name is part of the registry key
  (`studio:<tenant|->:<name>`), of the partition predicate every child-table method joins on,
  of test-session keys and of the per-tenant `UNIQUE(tenant, name)` / `name_taken` rule. A
  rename would have to evict caches on every pod and re-check uniqueness under a lock, so it is
  a separate operation, out of scope for v1 (follow-up `POST /agents/{name}/rename`).
- **Versioning**: one `UPDATE navigator.ai_agents SET definition = …`; the existing
  `ai_agents_bump_version_trg` bumps `version` and `updated_at`, so every pod rebuilds on its
  next lookup (§2.6). No reload needed.
- **Response**: 200 with the same keys as `GET /agents/{name}` (Studio item, incl. `version`).
- **Backward compatibility**: additive. Filesystem backend → 503 `studio_storage_unavailable`.
  A legacy agent (registry / YAML / `ai_bots`) on the GLOBAL partition → 409
  `not_studio_agent`; it keeps its legacy edit paths. No existing response changes.
- **Access**: this spec validates data only. FEAT-605 v0.2 owns the policy row
  (`can_manage` inside the tenant, `may_author` required, 404 first).

### 2.10 Phase 2 — BYOK in Postgres (separate wave, separately releasable)

```sql
-- 0006_ai_user_llm_keys.sql
CREATE TABLE IF NOT EXISTS navigator.ai_user_llm_keys (
    user_id      text        NOT NULL,
    provider     text        NOT NULL,
    api_key_enc  text        NOT NULL,   -- encrypt_credential({"api_key": …}, llm_key_context(user_id, provider), keyring)
    key_id       integer     NOT NULL,   -- keyring version that sealed it (rotation audit)
    masked       text        NOT NULL,   -- byok._mask() output, for GET without decrypt
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, provider)
);
```

- Same AAD context as today (`llm_key_context`, `credentials_utils.py:68-80`), so a
  DocumentDB ciphertext copies to Postgres byte-for-byte without re-encryption.
- `PgUserLLMKeyStore` (get/put/delete/list_masked) plus a `BYOK_STORE = documentdb | postgres`
  switch (default `documentdb` until a host opts in; FieldSync sets `postgres`).
  `resolve_user_api_key` and `_UserLLMKeyResolver` (`auth/broker.py:327`) read from the
  configured store. The session hot copy is unchanged.
- Keys are per user, not per tenant (a user's own provider key). Q4 covers the alternative.
- One-shot copy script `python -m parrot.handlers.studio.storage.byok_copy --dry-run`.
- Keyring provisioning (`VAULT_MASTER_KEY_v{N}`, `VAULT_ACTIVE_KEY_ID` in pod env) stays a host
  responsibility. Without a keyring, `/keys` answers 503 `vault_unavailable` as today.
- v1 (before phase 2): hosts may leave `/keys` unmounted. Testing and the assistant fall back
  to the org/server key (`testing.py:288-305`).

### 2.11 Non-tenant host behaviour (plain ai-parrot-server)

| Situation | Behaviour |
|---|---|
| Migrations not applied, `auto` | `filesystem` backend, exactly FEAT-467/593 today, one WARNING at startup. |
| Migrations applied, `auto` | `database` backend on the GLOBAL partition (`tenant IS NULL`). New Studio agents go to `ai_agents`. Legacy registry/YAML/`ai_bots` agents stay listed and editable through their legacy paths. Python drafts still available (gate §2.8). New agents are reachable by bare name through `get_bot` (fallback §2.7), so `/api/v1/chat/<name>` keeps working. |
| Multi-pod | Consistent (§2.6). |
| No scope resolver | Partition is always GLOBAL; `visibility` is always `private` (CHECK). |

### 2.12 Migrations — where and how they are applied

- **Location**: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/NNNN_<slug>.sql`,
  shipped as package data (`pyproject.toml` `[tool.setuptools.package-data]` gains
  `"parrot.handlers.studio.storage.migrations" = ["*.sql"]`, next to the existing
  `"parrot.handlers" = ["*.sql"]`).
- **Properties**: forward-only, idempotent (`IF NOT EXISTS`, guarded `DO` blocks), one
  transaction per file, self-recording in `ai_studio_migrations`. No Python migrations.
- **Plain host**: `parrot-studio-migrate --dsn "$DSN" [--dry-run | --verify | --print]`
  (new console script in ai-parrot-server; `--print` concatenates pending files for review or
  `psql -f`). Also callable as `await apply_studio_migrations(pool)` from the host's own
  deploy hook. **Never called by `setup()` or `on_startup`.**
- **FieldSync**: its own runner applies the files (read via `importlib.resources` from the
  pinned wheel, or vendored into FieldSync's migration tree under its own numbers). Because
  each file records itself, parrot's startup probe sees the same ledger whichever runner
  applied it.
- **Required version**: `STUDIO_SCHEMA_REQUIRED = 5` in v1 (6 after phase 2) is a constant in
  `storage/migrate.py`, checked by the §2.2 probe.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: migrations + runner | yes | file list, DDL, ledger, CLI flags fixed in §2.3/§2.12 | — |
| M2: storage models | yes | dataclasses and Pydantic models fixed in §2.4 | — |
| M3: repositories | yes | method list and partition predicate fixed in §2.5 | — |
| M4: backend selection + partition hook | yes | settings, probe SQL, app keys, error code fixed in §2.2/§2.8 | — |
| M5: agent/asset/tooling services | yes | limits, allowlist, transaction boundaries fixed in §2.5 | — |
| M6: draft + catalogue services | yes | Python gate, activation mapping, index location fixed | — |
| M7: runtime + builder + BotManager hooks | no | — | single-flight locking and cleanup ordering need the thinking model |
| M8: handler switch | yes | per-handler table §2.8 and shape table §2.9 | — |
| M9: assistant tools | yes | tool mapping fixed §2.8 | — |
| M10: core KB directory hook | yes | one attribute, one branch | — |
| M11 (phase 2): BYOK Postgres store | yes | table, AAD, switch fixed §2.10 | — |

### Module 1: migrations + runner
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0001…0005_*.sql` (new), `storage/migrate.py` (new), `pyproject.toml` (package-data + console script)
- **Responsibility**: the schema of §2.3; list/verify/apply; the read-only version probe.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # parrot/handlers/studio/storage/migrate.py  (new)
  STUDIO_SCHEMA_REQUIRED: int = 5
  @dataclass(frozen=True)
  class StudioMigration: version: int; name: str; sql: str; checksum: str
  def list_migrations() -> list[StudioMigration]:
      """Read package data via importlib.resources, sorted by version."""
  async def applied_version(conn: Any) -> int | None:
      """SELECT max(version) FROM navigator.ai_studio_migrations; None when the table is missing. Never DDL."""
  async def apply_studio_migrations(pool: Any, *, dry_run: bool = False) -> list[int]:
      """Apply pending files in order, one transaction each; return versions applied."""
  def main(argv: list[str] | None = None) -> int:
      """CLI: --dsn, --dry-run, --verify, --print."""
  ```

### Module 2: storage models
- **Path**: `handlers/studio/storage/models.py` (new), `handlers/studio/storage/__init__.py` (new)
- **Responsibility**: §2.4 types (incl. `StudioAgentPatch`); errors `StudioNameConflict`, `StudioVersionConflict`, `StudioAssetTooLarge`, `StudioStorageUnavailable`.
- **Depends on**: none (imports `ToolkitSpec`, `AgentMCPServerSpec` from `parrot.tools.spec`; `CreateAgentRequest` from `handlers/studio/models.py`)

### Module 3: repositories
- **Path**: `handlers/studio/storage/repositories.py` (new); `handlers/studio/storage/testing.py` (new: `InMemoryStudioRepositories`, the fake FEAT-605 v0.2 tests use)
- **Responsibility**: §2.5 repositories over `app["database"]` (`async with await pool.acquire() as conn`, pattern `agents.py:63-68`), using the pg connection's `fetch_all` / `fetch_one` / `fetchval` / `execute` (unverified in this worktree's venv — check before use); transactions via the connection's transaction context.
- **Depends on**: M1, M2
- **Interface Skeleton**: as §2.5. Invariant: every SQL statement that touches a row carries `tenant IS NOT DISTINCT FROM $n` directly or through a join to `ai_agents`.

### Module 4: backend selection + partition hook
- **Path**: `handlers/studio/storage/backend.py` (new); `handlers/studio/__init__.py` (modify `setup_studio_routes`); `handlers/studio/_base.py` (modify: add `_studio_partition`, `_studio_storage`)
- **Depends on**: M1, M3
- **Interface Skeleton**:
  ```python
  STUDIO_STORAGE_APP_KEY = "studio_storage"
  class StudioStorage:
      backend: Literal["database", "filesystem", "unavailable"]
      repos: StudioRepositories | None
      services: StudioServices | None
      def require_for(self, part: StudioPartition) -> None:
          """Raise StudioStorageUnavailable when backend != 'database' and part.tenant is not None,
          or backend == 'unavailable'."""
  async def resolve_studio_storage(app: web.Application) -> StudioStorage:
      """on_startup hook registered by setup_studio_routes, appended once per app whatever the number
      of prefixes (FEAT-605 startup-hook guard): read PARROT_STUDIO_STORAGE, probe, store app key."""
  # _base.py
  async def _studio_partition(self) -> StudioPartition:   # returns StudioPartition.GLOBAL; FEAT-605 v0.2 W2.1 overrides
  def _studio_storage(self) -> StudioStorage: ...
  ```

### Module 5: agent / asset / tooling services
- **Path**: `handlers/studio/storage/services.py` (new); `handlers/studio/tooling_store.py` (modify: extract validation/secret split into reusable functions, add `source="studio"` branch)
- **Depends on**: M3
- **Interface Skeleton**: §2.5 (`StudioAgentService`, `StudioAssetService`, `StudioToolingService`, `StudioLimits`, `StudioClassAllowlist`).

### Module 6: draft + catalogue services
- **Path**: `handlers/studio/storage/services.py` (same module, split into `services/` package if it exceeds 500 lines); `handlers/models/skills_catalog.py` (modify: three new fields + docstring DDL)
- **Depends on**: M3, M5
- **Interface Skeleton**:
  ```python
  class StudioDraftService:
      def python_drafts_allowed(self, part: StudioPartition) -> bool:
          """part.tenant is None and STUDIO_PYTHON_DRAFTS is true. Single decision point."""
      async def save_bundle(self, part, *, owner: str, bundle: StudioAgentBundle) -> StudioDraftRecord: ...
      async def activate(self, part, name: str, *, owner: str, replace: bool = False) -> StudioAgentRecord: ...
  ```

### Module 7: runtime + builder + BotManager hooks
- **Path**: `packages/ai-parrot-server/src/parrot/manager/studio_runtime.py` (new); `manager/manager.py` (modify: `studio` attribute, `get_studio_bot`, `get_bot` tail fallback, setup wiring)
- **Depends on**: M3, M10
- **Interface Skeleton**:
  ```python
  class StudioAgentBuilder:
      def __init__(self, registry: AgentRegistry, runtime_dir: Path) -> None: ...
      async def build(self, record: StudioAgentRecord, assets: list[StudioAssetRecord],
                      tooling: list[StudioToolingRecord], app: web.Application) -> AbstractBot:
          """§2.7 build steps 1-5. Raises AgentReloadError-compatible errors on failure."""
  class StudioAgentRuntime:
      def __init__(self, manager: "BotManager", repos: StudioRepositories, builder: StudioAgentBuilder,
                   *, revalidate_ttl: float = 0.0) -> None: ...
      async def get(self, key: StudioAgentKey) -> AbstractBot | None:
          """§2.6 revalidate → return cached | rebuild (single flight) | evict."""
      async def build_fresh(self, key: StudioAgentKey, *, session_id: str) -> AbstractBot | None: ...
      async def reload(self, key: StudioAgentKey) -> ReloadResult: ...
      def evict(self, key: StudioAgentKey) -> None: ...
  # manager.py
  async def get_studio_bot(self, key: StudioAgentKey, *, new: bool = False, session_id: str = "",
                           request: Optional[web.Request] = None) -> Optional[AbstractBot]: ...
  ```

### Module 8: handler switch
- **Path**: `handlers/studio/{agents,files,drafts,skills_catalog,testing,toolkit_config,toolkits}.py` (modify)
- **Depends on**: M4, M5, M6, M7
- **Responsibility**: §2.8 and §2.9, with legacy bodies moved verbatim into `_legacy_*` methods.

### Module 9: assistant tools
- **Path**: `packages/ai-parrot/src/parrot/bots/studio/tools.py` (modify); `handlers/studio/meta_agent.py` (modify: toolset built per partition)
- **Depends on**: M5, M6
- **Responsibility**: route `create_yaml_agent`, `write_identity_file`, `write_kb_file`, `write_skill_file`, `publish_skill_to_catalog` through services in database mode; add `save_agent_bundle`; omit `save_agent_draft` on tenant partitions.

### Module 10: core KB directory hook
- **Path**: `packages/ai-parrot/src/parrot/bots/stores/local.py` (modify `_get_agent_kb_directory`)
- **Responsibility**: honour `self._agents_dir` when set (same priority rule as `SkillRegistryMixin._resolve_agents_dir`, `skills/mixin.py:81-96`), else `AGENTS_DIR` as today.
- **Depends on**: none

### Module 11 (phase 2): BYOK Postgres store
- **Path**: `storage/migrations/0006_ai_user_llm_keys.sql` (new), `handlers/studio/storage/byok_store.py` (new), `handlers/studio/byok.py` (modify), `packages/ai-parrot/src/parrot/auth/broker.py` (modify `_UserLLMKeyResolver` store selection), `storage/byok_copy.py` (new)
- **Depends on**: M1

---

## 4. Test Specification

**Request/session rule.** Every handler test builds a real aiohttp request: either
`aiohttp_client` against an app with the real `navigator_session` middleware, or
`make_mocked_request(..., app=app)` with the session installed the way the middleware stores
it: `request["NAV_SESSION"] = SessionData(data={"session": {...}})`. This is the pattern in
`tests/handlers/test_ui_surfaces_scope.py:78`. No `Mock`/`SimpleNamespace` with a hand-set
`.session` attribute. Each new assertion is mutation-checked: revert the code line it guards
and see it go red.

**Database rule.** Repository, runtime and migration tests run against a real Postgres from
`TEST_STUDIO_PG_DSN` (skip with a reason when unset, precedent `TEST_PGVECTOR_DSN` in
`tests/stores/test_multimodal_pgvector_integration.py:42`). Each test gets a throwaway schema
copy or a transaction rolled back at teardown. Pure logic (keys, models, limits, allowlist)
has DB-free unit tests.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_agent_key_qualified_roundtrip` | M2 | `studio:acme:sales` / `studio:-:sales` parse back; a name with `:` or a tenant `-` is rejected |
| `test_definition_from_create_request` | M2 | `CreateAgentRequest` → `StudioAgentDefinition` loses only `persist` |
| `test_definition_rejects_reserved_keys` | M5 | `config.tenant/created_by/visibility/allowed_groups` → validation error |
| `test_bundle_rejects_secret_fields` | M2/M6 | a toolkit param marked `x-secret` in a bundle → rejected |
| `test_limits_per_kind` | M5 | 64 KiB identity OK, 64 KiB + 1 → `StudioAssetTooLarge`; totals quota |
| `test_binary_content_type_refused` | M5 | `application/pdf` → 415 code |
| `test_class_allowlist_tenant_vs_global` | M5 | `bot_class="Foo"` resolvable via `parrot.agents.foo` is refused on a tenant partition and allowed on GLOBAL |
| `test_python_drafts_gate` | M6 | tenant → False regardless of setting; GLOBAL + setting false → False |
| `test_backend_resolution_matrix` | M4 | auto/database/filesystem × pool present/absent × ledger version below/at required |
| `test_kb_dir_honours_agents_dir` | M10 | `_agents_dir` set → `<dir>/<name>/kb`; unset → `AGENTS_DIR/<name>/kb` (unchanged) |

### Integration Tests (real Postgres)
| Test | Description |
|---|---|
| `test_migrations_apply_idempotent` | apply 0001–0005 twice on an empty DB; ledger has 5 rows; second run applies nothing |
| `test_migrations_on_feat467_db` | pre-create `ai_skills_catalog`/`studio_drafts` with FEAT-467 DDL and rows; apply; rows keep `tenant NULL`, `private`; per-partition uniqueness now holds |
| `test_probe_is_read_only` | `applied_version` on a DB without the ledger returns None and creates nothing (`pg_class` unchanged) |
| `test_unique_per_tenant` | `sales` in `acme` and `sales` in `beta` coexist; second `sales` in `acme` → `StudioNameConflict`; two tenant-NULL `sales` → conflict (partial index) |
| `test_partition_isolation` | every repository method called with partition `beta` on an `acme` agent returns None / False / empty; child tables unreachable by guessed `agent_id` |
| `test_version_bumps_on_child_write` | asset put / tooling replace / definition update each increment `ai_agents.version`; a raw `psql`-style UPDATE bumps it too |
| `test_create_is_atomic` | bundle with an invalid asset → no agent, no tooling rows |
| `test_cross_pod_revalidation` | two `BotManager` + `StudioAgentRuntime` instances ("pods") on one DB: pod A creates and edits KB; pod B's next `get()` returns an instance with the new version; delete on A → B returns None and evicts |
| `test_single_flight_rebuild` | 20 concurrent `get()` on a stale key → builder called once |
| `test_runtime_cache_not_in_agents_dir` | after build, nothing new exists under `AGENTS_DIR`; KB/skills files exist under `STUDIO_RUNTIME_DIR/<agent_id>/v<n>/` and the old version dir is removed on rebuild |
| `test_get_bot_never_resolves_tenant_rows` | `get_bot("sales")` and `get_bot("studio:acme:sales")` → None while `get_studio_bot(key)` returns the instance |
| `test_get_bot_global_fallback` | tenant-NULL Studio agent on a fresh pod is returned by `get_bot("sales")` |
| `test_patch_agent_general_fields` | PATCH description/llm/model_params/system_prompt/category → 200, `version` +1 (trigger), other pod sees it on next `get()`; `name` in body → 422 `name_immutable`; stale `expected_version` → 409 `version_conflict`; legacy agent → 409 `not_studio_agent`; filesystem → 503 |
| `test_handlers_shapes_database_mode` | `aiohttp_client` + real session: POST/GET/DELETE `/agents`, files PUT/GET, drafts bundle save + activate, toolkit-config GET/PUT; asserts §2.9 keys exactly (added keys present, no key removed vs the filesystem-mode snapshot) |
| `test_handlers_filesystem_mode_unchanged` | the existing `tests/studio/*` suite runs with `PARROT_STUDIO_STORAGE=filesystem` and passes unmodified |
| `test_tenant_partition_on_filesystem_is_503` | a partition with a tenant (test override of `_studio_partition`) on the filesystem backend → 503 `studio_storage_unavailable` |
| `test_tenant_python_draft_refused` | tenant partition, `{name, source}` → 422 `declarative_only`, no file written, nothing imported (`sys.modules` unchanged) |
| `test_assistant_toolset_per_partition` | tenant partition toolset lacks `save_agent_draft`, has `save_agent_bundle` |
| `test_toolkit_secrets_never_in_db` | PUT toolkit with a secret → `ai_agent_tooling.config` has no secret value, `secret_refs` has the vault name |
| `test_byok_pg_roundtrip` (phase 2) | put → row encrypted with `llm_key_context`; `resolve_user_api_key` returns plaintext with `BYOK_STORE=postgres`; DocumentDB ciphertext copied verbatim decrypts |

### Test Data / Fixtures
```python
@pytest.fixture
async def studio_pool():
    dsn = os.environ.get("TEST_STUDIO_PG_DSN")
    if not dsn:
        pytest.skip("TEST_STUDIO_PG_DSN not set; Studio storage integration tests need Postgres")
    pool = AsyncPool("pg", dsn=dsn); await pool.connect()
    await apply_studio_migrations(pool)
    yield pool
    await _truncate_studio_tables(pool); await pool.close()

def real_request(app, method, path, *, user_id="u1", groups=(), superuser=False, match_info=None):
    req = make_mocked_request(method, path, app=app, match_info=match_info or {})
    req["NAV_SESSION"] = SessionData(data={"session": {
        "user_id": user_id, "groups": list(groups), "superuser": superuser}})
    return req
```

---

## 5. Acceptance Criteria

- [ ] Migrations 0001–0005 apply cleanly on an empty DB and on a FEAT-467 DB, twice, with no errors; no code path executes DDL at startup (grep gate: no `CREATE`/`ALTER` outside `storage/migrations/*.sql` and `migrate.py`).
- [ ] With the backend `database`, creating/editing/deleting an agent, its assets, its tooling, a declarative draft and a catalogue skill writes nothing under `AGENTS_DIR` (asserted by test).
- [ ] Two BotManager instances against one DB observe each other's writes on the next lookup (`test_cross_pod_revalidation`).
- [ ] `UNIQUE(tenant, name)` holds for agents, drafts and skills, including tenant NULL.
- [ ] No repository method can read or write a row outside its partition (`test_partition_isolation`).
- [ ] On a tenant partition, no Python is imported and the Python draft endpoints/tools are refused or absent.
- [ ] Every response-shape change is additive and listed in §2.9; the existing `tests/studio/` suite passes unchanged in filesystem mode.
- [ ] `navigator.ai_bots` DDL and `_load_database_bots` are untouched (diff gate).
- [ ] `get_bot(name)` behaviour for every existing agent is unchanged; tenant rows are unreachable through it.
- [ ] New functions within ARCHITECTURE Rule 4 budgets (`flake8` complexity), modules ≤ 500 lines.
- [ ] Host guide `docs/agentstudio/db-storage.md`: settings, migration commands, FieldSync runner note.
- [ ] Phase 2 (separately): BYOK round-trips through Postgres with `BYOK_STORE=postgres`; DocumentDB not contacted (asserted by test).

---

## 6. Codebase Contract

Verified against worktree `sdd/agentstudio-host-integration` @ `3f0f2f726`.

### Verified Imports
```python
from parrot.registry.registry import BotConfig            # verified: studio/agents.py:31
from parrot.manager.manager import AgentNotFoundError, AgentReloadError, ReloadResult  # agents.py:34, models.py:19
from parrot.models.basic import ModelConfig               # agents.py:29
from parrot.clients.factory import LLMFactory             # agents.py:27
from parrot.utils.naming import slugify_name              # agents.py:32
from parrot.bots.prompts.identity import IDENTITY_FILES   # files.py:19 ; tuple at identity.py:27
from parrot.skills.parsers import parse_skill_file        # files.py:21
from parrot.skills.store import create_skill_registry     # skills_catalog.py:34 ; def at skills/store.py:934
from parrot.tools.spec import (ToolkitSpec, AgentMCPServerSpec, NormalizedTooling, normalize_tooling,
                               toolkit_vault_name, mcp_vault_name, SECRET_MASK, MCP_SECRET_FIELDS)  # tooling_store.py:23-33
from parrot.security.vault_utils import (store_vault_credential, retrieve_vault_credential,
                                         delete_vault_credential, get_vault_keyring)  # tooling_store.py:16-20, byok.py:25
from parrot.security.credentials_utils import encrypt_credential, decrypt_credential, llm_key_context  # byok.py:20-24
from parrot.conf import AGENTS_DIR                         # conf.py:181
from navigator_auth.decorators import is_authenticated, user_session   # agents.py:25
from navigator_session.data import SessionData             # tests/handlers/test_ui_surfaces_scope.py:18
from aiohttp.test_utils import make_mocked_request         # tests/studio/test_catalogs.py:17
```

### Existing Class Signatures
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:                                      # :183
    self._bots: Dict[str, AbstractBot]                 # :216
    self._botdef: Dict[str, Type]                      # :217
    self.registry: AgentRegistry = agent_registry      # :222
    def get_bot_class(self, bot_name: str) -> Optional[Type]           # :267 (imports parrot.agents.<name.lower()> :291-296)
    async def _load_database_bots(self, app) -> None                   # :610  (NOT modified)
    def add_bot(self, bot: AbstractBot) -> None                        # :738
    async def get_bot(self, name, new=False, session_id="", request=None, **kwargs)  # :744 ; returns None at tail
    def remove_bot(self, name: str) -> None                            # :870
    async def reload_agent(self, name: str) -> ReloadResult            # :880
    async def _safe_cleanup(self, name: str, bot: AbstractBot) -> bool # :1722

# packages/ai-parrot/src/parrot/registry/registry.py
class BotConfig(BaseModel):                            # :227 ; origin: Literal["repo","factory"] :235
class AgentRegistry:                                   # :258
    def create_agent_factory(self, config: BotConfig) -> AgentFactory  # :846 (does not register)
    def load_agent_definition_file(self, yaml_file: Path) -> bool      # :964
    def create_agent_definition(self, config, category="general") -> Path  # :1054

# packages/ai-parrot-server/src/parrot/handlers/studio/_base.py
class StudioBaseView(BaseView):                        # :121
    async def _get_user(self) -> StudioUser            # :164
    def _require_owner(self, resource_owner, user) -> None  # :230
    async def _pbac_gate(self, resource: str, action: str)   # :308

# packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py
class ToolingState:  tooling; editable; reason; owner; source: Literal["database","registry"]   # :47-54
class AgentToolingStore:                               # :78
    async def load(self, name: str) -> ToolingState    # :84
    async def _persist(self, name: str, state: ToolingState) -> None  # :292

# packages/ai-parrot/src/parrot/bots/abstract.py  — identity kwargs read at :427-431
# packages/ai-parrot/src/parrot/skills/mixin.py    — _resolve_agents_dir honours self._agents_dir :81-96 ; skill_paths :65
# packages/ai-parrot/src/parrot/bots/stores/local.py — _get_agent_kb_directory :42 ; hardcoded AGENTS_DIR :56
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| repositories | `app["database"]` pool | `async with await db.acquire() as conn` | `studio/agents.py:63-64` |
| `StudioAgentBuilder` | `AgentRegistry.create_agent_factory` | method call, no registration | `registry.py:846` |
| `StudioAgentRuntime` | `BotManager._bots`, `_safe_cleanup` | attribute + method | `manager.py:216`, `:1722` |
| `get_studio_bot` | `enforce_agent_access(evaluator, name, request)` | function call (evaluator None ⇒ allow) | `manager.py:772`, `auth/agent_guard.py:173-181` |
| `StudioToolingService` | `AgentToolingStore` validation / `_split_secrets` | extracted functions | `tooling_store.py:147-290` |
| backend resolver | `setup_studio_routes` | `app.on_startup.append` (same pattern as `reconcile_skills_catalog`) | `studio/__init__.py:88` |
| testing | `get_studio_bot(new=True)` | replaces `manager.get_bot(agent_name, new=True, …)` for Studio rows | `studio/testing.py:216` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.handlers.scope.RequestScope`~~ — introduced by FEAT-605 v0.2 (M1 there), not in this tree. This spec duck-types `.tenant` (`StudioPartition.from_scope`).
- ~~`navigator.ai_agents`, `ai_agent_assets`, `ai_agent_tooling`, `ai_agent_drafts`, `ai_studio_migrations`~~ — no code references any of them today (grep, 0 hits).
- ~~A migration runner in ai-parrot-server~~ — none. `packages/parrot-formdesigner/migrations/` is a precedent for numbered SQL, but not package data and not reusable here.
- ~~`CREATE TABLE` code for `studio_drafts` / `ai_skills_catalog`~~ — DDL exists only in model docstrings.
- ~~`BotConfig.origin == "studio"`~~ — `Literal["repo","factory"]` only. Builder uses `"factory"`; API responses say `"studio"`.
- ~~Tenant-aware `AgentRegistry`~~ — global, name-keyed.
- ~~A Postgres-backed vault~~ — `store_vault_credential` always uses DocumentDB (`vault_utils.py:30`, `:111`).
- ~~A KB directory override on `LocalKBMixin`~~ — added by M10.
- ~~`BotManager.get_studio_bot`, `BotManager.studio`~~ — added by M7.
- ~~`PATCH /astudio/agents/{name}`~~, ~~`StudioAgentPatch`~~ — added by M8 / M2 (§2.9a). ~~`InMemoryStudioRepositories`~~ — added by M3.
- ~~Config keys `PARROT_STUDIO_STORAGE`, `STUDIO_RUNTIME_DIR`, `STUDIO_PYTHON_DRAFTS`, `STUDIO_REVALIDATE_TTL_SECONDS`, `STUDIO_ASSET_MAX_BYTES_*`, `BYOK_STORE`~~ — all new.
- ~~`LISTEN/NOTIFY` usage anywhere in the repo~~ — none (grep).

### Edit Sites (Blueprint Anchors)

Verified against: `3f0f2f726`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/{__init__,models,repositories,services,backend,migrate}.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/000{1..5}_*.sql` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/manager/studio_runtime.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/pyproject.toml` | MODIFY | `"parrot.handlers.models" = ["*.sql"]` | `pyproject.toml:111` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | `def setup_studio_routes(app: web.Application) -> None:` | `__init__.py:26` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/_base.py` | MODIFY | `    async def _get_user(self) -> StudioUser:` | `_base.py:164` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/agents.py` | MODIFY | `class _StudioAgentsMixin:` / `    async def post(self):` (2×: `:209` create, `:450` reload — anchor with the enclosing class) | `agents.py:39`, `:209`, `:450` | 2 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/files.py` | MODIFY | `class _StudioFilesMixin:` | `files.py:76` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py` | MODIFY | `    def _drafts_dir(self) -> Path:` | `drafts.py:48` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` | MODIFY | `class AgentToolingStore:` ; `    async def _persist(self, name: str, state: ToolingState) -> None:` | `:78`, `:292` | 1 each |
| `packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py` | MODIFY | `def _get_shared_skill_registry(app: Any, org_id: str):` | `:51` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` | MODIFY | `        bot = await manager.get_bot(agent_name, new=True, session_id=session_id, request=self.request)` | `:216` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/meta_agent.py` | MODIFY | `    async def post(self):` | `:77` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/models/skills_catalog.py` | MODIFY | `    search_index_stale: bool = Field(required=False, default=False)` | `skills_catalog.py:69` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `    def add_bot(self, bot: AbstractBot) -> None:` ; `    async def get_bot(` | `:738`, `:744` | 1 each |
| `packages/ai-parrot/src/parrot/bots/stores/local.py` | MODIFY | `        kb_dir = Path(AGENTS_DIR) / safe_name / 'kb'` | `local.py:56` | 1 |
| `packages/ai-parrot/src/parrot/bots/studio/tools.py` | MODIFY | `async def save_agent_draft(name: str, source: str) -> dict:` ; `async def create_yaml_agent(` ; `async def _write_asset_file(agent_name: str, kind: str, filename: str, content: str) -> dict:` | `:162`, `:274`, `:342` | 1 each |
| `packages/ai-parrot-server/src/parrot/handlers/studio/byok.py` (phase 2) | MODIFY | `COLLECTION = "user_llm_keys"` | `byok.py:31` | 1 |
| `packages/ai-parrot/src/parrot/auth/broker.py` (phase 2) | MODIFY | `class _UserLLMKeyResolver(CredentialResolver):` | `broker.py:327` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async throughout; the pool is the host's `app["database"]`; no sync driver, no second pool.
- Raw parametrised SQL (`$1…$n`), never string interpolation of values; the schema name is a module constant.
- Pydantic for request/definition payloads, frozen dataclasses for records.
- `self.logger` in views; `logging.getLogger("Parrot.AgentStudio.Storage")` in services.
- Legacy branches are moved verbatim (no drive-by refactors) so the filesystem-mode diff is reviewable as a pure move.

### Known Risks / Gotchas
- **Auto-apply semantics.** In database mode an asset or tooling write reaches the live agent on the next lookup on every pod. FEAT-467's "explicit reload" gate is gone for Studio rows (`reload_required: false`). A published/working split is out of scope (Q2).
- **Test/assistant sessions are per pod.** In-memory `_instances` and the session-keyed test bot survive only on the pod that created them; without sticky sessions a conversation restarts on another pod. The definition is never lost. Host infra decision.
- **Catalogue search index is per pod** (derived `SkillRegistry`). It can lag Postgres until `resync`/reconcile. Listing and CRUD are always consistent (Q3).
- **Toolkit secrets still depend on the DocumentDB vault** (`user_credentials`). A host without DocumentDB can store secret-free tooling only; a secret write answers 503. Q5.
- **Unique-constraint swap on `ai_skills_catalog`** (0004) needs a short `ACCESS EXCLUSIVE` lock. The table is small; run in the deploy window.
- **Runtime cache disk use**: one directory per (agent, version) per pod; old versions are removed on rebuild; `STUDIO_RUNTIME_DIR` must be writable (ephemeral volume is fine).
- **`created_by` duplication**: stamped into `BotConfig.config` for legacy readers; row `owner` wins on any disagreement.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| PostgreSQL | ≥ 13 | `gen_random_uuid()` in core, `CREATE OR REPLACE TRIGGER` needs ≥ 14 (fallback: `DROP TRIGGER IF EXISTS` + `CREATE TRIGGER`, chosen if Q7 says PG13) |
| asyncdb | as pinned | pg pool/connection API already used by Studio |
| (no new Python packages) | — | — |

### Task breakdown (waves; no IDs)

| Wave | Title | Scope | Files | Depends on | Size |
|---|---|---|---|---|---|
| 0 | Studio migrations + runner | §2.3 files 0001–0005, ledger, `migrate.py`, CLI, package-data | `storage/migrations/*`, `storage/migrate.py`, `pyproject.toml`, `tests/studio/storage/test_migrations.py` | — | M |
| 0 | Storage models | §2.4 types + errors | `storage/models.py`, `storage/__init__.py`, `tests/studio/storage/test_models.py` | — | S |
| 0 | Core KB dir hook | `_agents_dir` honoured by `LocalKBMixin` | `bots/stores/local.py`, `tests/unit/bots/test_local_kb_dir.py` | — | S |
| 1 | Repositories | §2.5 repositories, partition invariant, `InMemoryStudioRepositories` fake (same test suite runs against both) | `storage/repositories.py`, `storage/testing.py`, `tests/studio/storage/test_repositories.py` | migrations, models | L |
| 1 | Backend selection + partition hook | §2.2 probe/settings, `StudioStorage`, `_studio_partition` | `storage/backend.py`, `studio/__init__.py`, `studio/_base.py`, tests | migrations, repositories (interface) | S |
| 2 | Agent/asset/tooling services | limits, allowlist, atomic create, `patch` + `update_visibility`, tooling extraction | `storage/services.py`, `studio/tooling_store.py`, tests | repositories | L |
| 2 | Draft + catalogue services | declarative drafts, Python gate, activation, `update_visibility`, catalogue model fields, derived index location | `storage/services.py` (or `services/` package), `models/skills_catalog.py`, tests | repositories, agent services | M |
| 2 | Runtime + builder + BotManager hooks | §2.6/§2.7, incl. the `BotManager.studio` startup step reused by FEAT-605's `setup_registry_only` | `manager/studio_runtime.py`, `manager/manager.py`, tests (cross-pod, single flight) | repositories, core KB hook | L |
| 3 | Handler switch: agents, files, tooling | §2.8 rows 1–5, §2.9, new `PATCH /agents/{name}` (§2.9a) | `studio/agents.py`, `files.py`, `tooling_store.py`, `toolkit_config.py`, `toolkits.py`, `toolkit_overrides.py`, tests | services, runtime, backend | L |
| 3 | Handler switch: drafts, catalogue, testing | §2.8 rows 6–8 | `studio/drafts.py`, `skills_catalog.py`, `testing.py`, tests | draft/catalogue services, runtime | M |
| 3 | Assistant tools on services | §2.8 row 9, per-partition toolset | `bots/studio/tools.py`, `studio/meta_agent.py`, tests | services | M |
| 4 | Shape snapshot + host guide | §2.9 snapshot test both modes; `docs/agentstudio/db-storage.md` | tests, docs | wave 3 | S |
| P2 | BYOK Postgres store | §2.10 migration 0006, store, switch, resolver | `storage/migrations/0006_*.sql`, `storage/byok_store.py`, `studio/byok.py`, `auth/broker.py`, tests | migrations | M |
| P2 | BYOK copy script | DocumentDB → Postgres one-shot, dry-run | `storage/byok_copy.py`, test | BYOK store | S |

FEAT-605 v0.2 Waves 0–1 need nothing from this spec. Its Wave 2 (access service, W2.1) starts
once this spec's W0 + W1 (models, repositories + fake, backend switch + partition hook) are
merged; W2.1 overrides `_studio_partition` and wraps the records returned by the services.
Every FEAT-605 or host-toolkits task that edits a handler file this spec's W2/W3 also edits
merges **after** this spec's task for that file and rebases on it (per file; see
"Cross-spec contract (package)").

### Contract changes vs sibling specs

Starting contract → final contract (siblings must use the right-hand names):

| Item | Starting contract | Final (this spec) | Why |
|---|---|---|---|
| Skills catalogue | new `navigator.ai_skills_catalog(skill_id, tenant, owner, visibility, allowed_groups, name, category, content, updated_at, UNIQUE(tenant,name))` | **existing** `navigator.ai_skills_catalog` extended in place (migration 0004). Column is **`body`** (not `content`); keeps `description`, `triggers`, `version`, `status`, `search_index_stale`, `created_at`; adds `tenant`, `visibility`, `allowed_groups text[]` | The table already exists with that name and FEAT-467 data; a second table of the same name is impossible |
| `allowed_groups` type | `text[]` | `text[]` everywhere (FEAT-605 v0.1 used `JSONB` for its ALTERs — v0.2 must use `text[]`) | one type across tables; GIN-indexable |
| `ai_agent_tooling` | `(agent_id, kind, slug, config, secret_refs, updated_at)` | **adds** `position int`, `vault_owner text`; PK `(agent_id, kind, slug)` | MCP server order; FEAT-593 `ToolkitSpec.vault_owner` |
| `ai_agent_assets` | `(…, content, content_type, size, updated_at)` | **adds** `storage_uri text NULL` (phase-S3 hook), `sha256 text` | decision 7 extension point; cheap change detection |
| `ai_agent_drafts` | `(draft_id, tenant, owner, name, definition, validation, status, …)` | **adds** `visibility`, `allowed_groups`, `activated_agent_id`, `UNIQUE(tenant,name)`; `definition` holds a `StudioAgentBundle` | FEAT-605 has `PATCH /drafts/{name}/visibility`; activation audit |
| `ai_agents` | as given | **adds** CHECKs (name/tenant format, `tenant IS NOT NULL OR visibility='private'`), partial unique index for tenant NULL, version trigger | uniqueness for NULL tenant; sync correctness |
| Legacy `navigator.studio_drafts` | — | kept for Python drafts only (non-tenant); baseline created by 0005 | decision 3 |
| Ledger | — | **new** `navigator.ai_studio_migrations` | decision 6 |
| Registry key | "tenant-qualified id" | `studio:<tenant>:<name>` / `studio:-:<name>` (`StudioAgentKey.qualified`) | unambiguous by the CHECKs |
| Scope object | "a scope object" | storage takes `StudioPartition` (tenant only), built from FEAT-605's `RequestScope` via `StudioPartition.from_scope` | storage never sees groups/superuser, so it cannot encode policy |

---

## Cross-spec contract (package)

This section is **identical** in the three package specs: STORAGE =
`agentstudio-db-storage.spec.md`, FEAT-605 = `agentstudio-tenant-visibility.spec.md` (v0.2),
TOOLKITS = `agentstudio-host-toolkits.spec.md`. Changing a row means changing it in all three.
STORAGE waves are W0–W4 and P2; FEAT-605 tasks are W0.1–W4.3; TOOLKITS waves are Wave 1–4.

| # | Item (exact names) | Provided by | Consumed by | Contract |
|---|---|---|---|---|
| X1 | Tables `navigator.ai_agents`, `navigator.ai_agent_assets`, `navigator.ai_agent_tooling`, `navigator.ai_agent_drafts`, `navigator.ai_studio_migrations`; the **existing** `navigator.ai_skills_catalog` extended in place (content column `body`; adds `tenant`, `visibility`, `allowed_groups text[]`) | STORAGE W0 (migrations 0001–0005) | FEAT-605, TOOLKITS (only through STORAGE services / `AgentToolingStore`) | `tenant text NULL`; `visibility` ∈ `private`/`tenant`/`groups`; `allowed_groups text[]`; `UNIQUE(tenant, name)` + partial unique `(name) WHERE tenant IS NULL`; `tenant IS NULL ⇒ visibility = 'private'` (CHECK). No DDL outside the migration files |
| X2 | Tenant-less rows (`tenant IS NULL`) | STORAGE | FEAT-605, TOOLKITS | They form the GLOBAL partition of hosts with **no** resolver. No resolver may return a NULL or empty tenant as valid; a NULL row never satisfies FEAT-605 `in_tenant`; a tenant-bound tool on such an agent refuses `agent_tenant_unset` |
| X3 | `ai_agent_tooling(agent_id, kind, slug, position, config, secret_refs, vault_owner, updated_at)`, PK `(agent_id, kind, slug)` | STORAGE W0 (table), W2/W3 (`StudioToolingService`, `AgentToolingStore` `source="studio"`) | TOOLKITS (M2, M4) | `position` = list order of `ToolkitSpec`/MCP specs; `config` = secret-free spec dump, never contains a TOOLKITS server-managed key; `secret_refs` = `{dotted.path: vault_name}`; `vault_owner` = `ToolkitSpec.vault_owner`. Secret **values** and per-user `/toolkits/{slug}/me` overrides stay in the DocumentDB vault until STORAGE P2 (STORAGE Q5) |
| X4 | `StudioPartition(tenant)`, `StudioPartition.GLOBAL`, `StudioPartition.from_scope(scope)` (duck-typed `.tenant`) | STORAGE W0 | FEAT-605 W2.1 | Storage addresses rows by tenant only; it never sees groups, superuser or visibility policy |
| X5 | `async StudioBaseView._studio_partition()` | STORAGE W1 (returns `GLOBAL`) | FEAT-605 W2.1 (override) | No resolver ⇒ `GLOBAL`. Resolver + tenant ⇒ `StudioPartition.from_scope(await self._scope())`. Resolver + no tenant ⇒ never `GLOBAL`: the handler answers empty / 404 / 422 `tenant_required` before any storage call |
| X6 | Records `StudioAgentRecord`, `StudioDraftRecord`, `StudioSkillRecord` (`owner`, `tenant`, `visibility`, `allowed_groups`, id, `name`); errors `StudioNameConflict`, `StudioVersionConflict`, `StudioStorageUnavailable`; services `StudioAgentService` (`create`, `patch`, `update_visibility`, …), `StudioDraftService` (`save_bundle`, `activate`, `update_visibility`, `python_drafts_allowed`), `StudioSkillCatalogService` (`publish`, `update_visibility`, …); test fake `InMemoryStudioRepositories` (`storage/testing.py`) | STORAGE W0 (records, errors), W1 (repositories, fake), W2 (services) | FEAT-605 (`StudioAccess`, handlers, tests) | Services validate data, never access. The fake enforces the same uniqueness and raises the same signals |
| X7 | Registry key `StudioAgentKey(tenant, name).qualified` = `studio:<tenant\|->:<name>`; `BotManager.get_studio_bot(key, *, new=False, session_id="", request=None)`; `BotManager.studio.reload(key)`; `bot._studio_key`, `bot._studio_version` | STORAGE W2 | FEAT-605 (test/ask, reload, activation), TOOLKITS M5 (identifies a Studio bot) | `get_bot(name)` never resolves a tenant row and never parses a qualified id; only tenant-NULL rows are reachable by bare name. Tenant agents outside Studio (chat, A2A, scheduler) are the P13 follow-up |
| X8 | `BotManager.studio` startup step | STORAGE W2 | FEAT-605 W0.2 (`setup_registry_only` extension point), host | Appended by both `BotManager.setup()` and `BotManager.setup_registry_only(app)`; runs after `resolve_studio_storage`; only when `app["studio_storage"].backend == "database"`; no eager load |
| X9 | `RequestScope(user_id, tenant, groups, is_superuser, may_author, may_administer, studio_enabled)`; `app["scope_resolver"]` (legacy `app["ui_surfaces_scope_resolver"]`); `get_scope_resolver(app)`; `has_installed_resolver(app)` | FEAT-605 W0.1 | STORAGE (duck-typed `.tenant` only), TOOLKITS M5 | "Opted-in host" := `has_installed_resolver(app)` |
| X10 | `setup_studio_routes(app, *, prefix=None, view_wrapper=None)`; `BotManager.setup(..., studio_routes=True)`; `BotManager.setup_registry_only(app)` | FEAT-605 W0.2 | STORAGE (registers `resolve_studio_storage` through it), host | Idempotent per prefix; every startup hook (FEAT-467 `reconcile_skills_catalog`, STORAGE `resolve_studio_storage`, the `BotManager.studio` step) appended at most once per app |
| X11 | `RequestContext.kwargs["studio_scope"]` = `StudioToolScope(caller: RequestScope, agent: StudioAgentRef \| None)`, built only by `build_tool_scope(scope, agent=None)` in `handlers/studio/access.py`; `StudioAgentRef(agent_id, name, owner, tenant, visibility)` | FEAT-605 W2.1 (builder); binds at test/ask (W3.4) and the meta-agent (W3.5) | TOOLKITS (`ToolScopeView` / `CallerView` / `AgentScopeView` Protocols; binds at `chat.py`, execute and options in M5); STORAGE assistant tools (partition = `StudioPartition.from_scope(studio_scope.caller)`) | Nothing is bound without a resolver. For an addressed agent `agent.tenant == caller.tenant` |
| X12 | Routes: `PATCH /agents/{name}` (General fields) | STORAGE W3 (route, `StudioAgentPatch`, version bump) | FEAT-605 W3.1 (policy row) | Name immutable (`name_immutable`); `can_manage` inside the tenant + `may_author`; 404 first |
| X13 | Routes: `GET /me`; `PATCH /agents/{name}/visibility`, `/drafts/{name}/visibility`, `/skills/{id}/visibility` | FEAT-605 (W1.2, W3.1–W3.3, W4.1) | UI, host | Persist through the X6 `update_visibility` service methods |
| X14 | Error codes | STORAGE: `studio_storage_unavailable` (503), `version_conflict`, `name_immutable`, `not_studio_agent`, `asset_too_large`, `agent_assets_quota`, `binary_assets_unsupported`. FEAT-605: `name_taken` (409, raised from `StudioNameConflict`), `declarative_only` (422, also the STORAGE tenant-path Python-draft refusal), `studio_disabled` (404), `tenant_mismatch`, `authoring_denied`, `reserved_config_key`, `tenant_required`, `groups_required`. TOOLKITS: `tool_scope_unavailable` (403 on execute) | all three | One code per condition across the package; no spec defines a synonym |
| X15 | `get_toolkit_resolver()` / `ToolkitResolver`; `server_managed_params`, `ServerParam`; `tenant_bound` | TOOLKITS Wave 1–3 | STORAGE (`StudioAgentBuilder` → `apply_tooling_specs` builds toolkits from `ai_agent_tooling` rows; `StudioToolingService` reuses the refusal of server-managed keys) | Storage-agnostic: the resolver and refusals work on either backend |
| X16 | Merge order | — | all three | FEAT-605 W0.1–W0.3, W1.1–W1.2 and TOOLKITS Wave 1 have no sibling dependency. FEAT-605 W2.1 needs STORAGE W0 + W1. Every task that edits a Studio handler file also edited by STORAGE W2/W3 (`agents.py`, `drafts.py`, `skills_catalog.py`, `files.py`, `testing.py`, `tooling_store.py`, `toolkit_config.py`, `toolkits.py`, `toolkit_overrides.py`, `meta_agent.py`, core `bots/studio/tools.py`) merges **after** the STORAGE task for that file, per file. `studio/_base.py`, `studio/__init__.py` and `manager/manager.py` (STORAGE W1/W2, FEAT-605 W0.2/W1.1) carry small non-overlapping edits: serialise, whichever merges first. TOOLKITS Wave 4 (M5) needs FEAT-605 W2.1 (builder) |

---

## 8. Open Questions (for Jesus)

- [ ] **Q1 — `filesystem` backend lifetime.** Keep it as deprecated, non-tenant only, for one minor release, then remove it along with the legacy-agent migration follow-up? *Recommendation: yes; remove in the release that ships the legacy migration.* — *Owner: Jesus*
- [ ] **Q2 — Live edits vs explicit reload.** DB mode applies asset/tooling edits on the next lookup (no reload gate). Accept for v1, or add a published/working split (`published_version`)? *Recommendation: accept; the split is a later feature if authors ask for staging.* — *Owner: Jesus*
- [ ] **Q3 — Catalogue search in tenant mode.** Keep the embedding `SkillRegistry` as a per-pod derived index, or use SQL search only in database mode? *Recommendation: keep it derived and rebuildable; fall back to SQL `ILIKE` when the index is flagged stale.* — *Owner: Jesus*
- [ ] **Q4 — BYOK key scope.** Per user (all tenants) or per (user, tenant)? *Recommendation: per user; it is the user's own provider key. A tenant column can be added later without breaking the PK contract if a host needs it.* — *Owner: Jesus + Juan*
- [ ] **Q5 — Toolkit secrets off DocumentDB.** Extend phase 2 with `navigator.ai_user_credentials` (same keyring, `credential_context` AAD) so `store_vault_credential` has a Postgres backend? *Recommendation: yes, in phase 2 behind the same `*_STORE` switch; otherwise FieldSync cannot store toolkit secrets without DocumentDB.* — *Owner: Jesus*
- [ ] **Q6 — Literal `navigator` vs `PARROT_SCHEMA`.** `ai_bots` honours `PARROT_SCHEMA`; the Studio tables are literal `navigator` (decision 2). Keep literal? *Recommendation: literal `navigator` in the SQL files (migrations cannot be templated safely by every runner). Document it; a host with a different schema sets `search_path` in its runner.* — *Owner: Jesus*
- [ ] **Q7 — Minimum Postgres version.** Is PG14+ guaranteed on every parrot deployment? *Recommendation: target PG13 compatibility (`DROP TRIGGER IF EXISTS` + `CREATE TRIGGER`), since it costs one line per trigger.* — *Owner: Jesus*
- [ ] **Q8 — Where the console script lives.** `parrot-studio-migrate` in ai-parrot-server, or a `parrot studio migrate` subcommand of the core `parrot` CLI? *Recommendation: ai-parrot-server script, because the SQL ships in that wheel and core must not import server code.* — *Owner: Jesus*
- [ ] **Q9 — Bare-name fallback in `get_bot` for tenant-NULL Studio rows.** Acceptable as the only change to `get_bot`? *Recommendation: yes; it keeps `/api/v1/chat/<name>` working for plain hosts and cannot reach tenant rows.* — *Owner: Jesus*
- [ ] **Q10 — Python drafts default on plain hosts.** Keep `STUDIO_PYTHON_DRAFTS=true` by default? *Recommendation: yes for compatibility, with a deprecation note; the tenant path refuses them regardless.* — *Owner: Jesus*

---

## 9. Design Research Cross-Check

Status: **skipped**. This spec was drafted from decisions already taken by the host owner
(command board D1–D7) as part of a three-spec package. A neutral `codex` design cross-check
over the host brainstorm is recommended before `/sdd-task`, with the §2.6 sync choice and the
§2.8 policy boundary as the review questions.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-30 | Juan Ruffato (with Claude) | Initial draft for the Agent Studio host-integration package |
| 0.1.1 | 2026-09-30 | Juan Ruffato (with Claude) | Package reconciliation: `PATCH /agents/{name}` (§2.9a), async `_studio_partition`, `InMemoryStudioRepositories`, `update_visibility` services, `BotManager.studio` startup step shared with `setup_registry_only`, `declarative_only` code, meta-agent partition from `studio_scope.caller`, per-file merge order, cross-spec contract section |
