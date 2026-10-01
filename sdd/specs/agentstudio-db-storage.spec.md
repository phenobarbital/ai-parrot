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
**Status**: approved (v0.2.2, 2026-09-30) — open questions resolved or deferred as non-blocking; ready for `/sdd-task`. Feature ID to be reserved by the maintainer.
**Target version**: ai-parrot-server 1.0.7 (ai-parrot core 1.0.7 in lockstep, for the KB-directory hook, the tooling-identity helper and the assistant tools)
**Package**: one of three coordinated specs for "Agent Studio multi-tenant host integration":
this spec (**foundation: storage**), `agentstudio-tenant-visibility.spec.md` (FEAT-605 v0.2: access
rules on top of this storage), `agentstudio-host-toolkits.spec.md` (host toolkit discovery,
scope enforcement and the tenant tooling policy, parallel lane).
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
| Per-user toolkit overrides | DocumentDB `user_toolkit_configs`, keyed `(user_id, agent_id, slug)` where `agent_id` is the **bare agent name** | `handlers/toolkit_persistence.py:28-35`; `studio/toolkit_overrides.py:109,183` |
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
- Every name-derived identity collides across tenants: vault names
  (`toolkit_vault_name`/`mcp_vault_name`, `tools/spec.py:59-66`; per-user
  `f"toolkit_{slug}_{name}_user"`, `toolkit_overrides.py:170`), override keys, the
  session caches `f"{agent.name}_toolkit_overrides_rev"` / `f"{agent.name}_tool_manager"`
  (`handlers/agent.py:1102,1130`), and conversation memory (`AbstractBot.memory_key_id`
  falls back to `self.name` when no explicit `chatbot_id` was given, `abstract.py:1959-1983`).
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
4. Names are unique per tenant: `UNIQUE(tenant, name)` plus an internal uuid. The runtime
   keys Studio agents by a tenant-qualified id.
5. Pods stay in sync through a `version` / `updated_at` column (mechanism chosen in §2.6).
6. No startup DDL. Versioned SQL migrations, applied by the host.
7. KB assets are text in the DB with a size cap. Binaries (S3) are a later phase.
8. BYOK moves to Postgres in **phase 2** of this spec. v1 uses the org key. (v0.2 settles the
   rest of phase 2 in §2.10: the vault credentials and per-user overrides move with it.)

### Goals

- G1: A Postgres schema (`navigator.ai_agents` + child tables) that stores every piece of
  Studio state with `tenant`, `owner`, `visibility`, `allowed_groups` from day one, with
  executable, integrity-checked migrations (§2.3, §2.12).
- G2: An async repository + service layer over the host's asyncdb pool (`app["database"]`)
  that takes a **partition** derived from the request scope and never encodes access policy,
  with explicit row locking and transactions (§2.5a).
- G3: Studio handlers switch from files to services with no response-shape break for
  existing FEAT-467/FEAT-593 clients (every additive change is listed in §2.9).
- G4: A **separate** Studio runtime cache (`StudioRuntimeCache`, owned by
  `StudioAgentRuntime`) that no legacy `BotManager` lookup, enumeration, clone or cleanup
  path can reach (§2.7), with cross-pod consistency through the row `version`.
- G5: Versioned, idempotent SQL migrations shipped as package data, applied by the host
  (FieldSync runner, `psql`, or a small CLI shipped in ai-parrot-server). No DDL at startup.
- G6: Declarative-only drafts on the tenant path; the Python draft path survives only for
  non-tenant hosts, behind an explicit gate.
- G7 (phase 2): BYOK keys, vault credentials and per-user toolkit overrides in Postgres,
  encrypted with the vault keyring; no DocumentDB dependency for Studio (§2.10, M11, M12).
- G8: One immutable identity per Studio agent (`agent_id`) used, **in v1**, for the runtime
  memory key, vault credential names, override persistence keys and every session/revision
  cache key (§2.5c). Deleting and recreating a name never inherits credentials or memory.
- G9: A minimal, complete Studio runtime lifecycle — enforced expiry, shutdown cleanup,
  per-instance cleanup, deterministic startup order, in-flight retention (§2.7a) — that works
  under FEAT-605's `setup_registry_only` mount as well as under `BotManager.setup()`.
- G10: Every write that can change an agent's effective tooling, and every build, passes the
  host-owned tenant tooling policy on the final normalised configuration (§2.5b).

### Non-Goals (explicitly out of scope)

- Access rules (who sees or edits what). They belong to FEAT-605 v0.2. This spec stores and
  returns the visibility fields and exposes a partition-only API.
- **Defining** the tenant tooling policy. `TenantToolingPolicy`, its default rules and its
  registration API belong to `agentstudio-host-toolkits`; this spec only calls it (§2.5b).
- Assistant session partitioning (`meta_agent.py` session entry and instance cache). FEAT-605
  owns it; this spec only guarantees that a Studio agent's memory key is its `agent_id`.
- Migrating `navigator.ai_bots` rows, YAML agents or Python agents into `ai_agents`. Follow-up.
- Binary KB documents (PDF, images) and object storage (S3). A column is reserved (§2.3).
- Runtime use of tenant Studio agents outside Studio (public chat endpoints, surfaces,
  scheduler). `get_bot(name)` does not resolve tenant agents (§2.7). Separate follow-up (host P13).
- Sticky sessions for in-memory test/assistant sessions. They stay per pod; noted in §7.
- Tenant-awareness of the global `AgentRegistry` (`agent_registry` singleton). Studio agents
  never enter it.
- The plain-host draft fixes D1 (overwrite) and D3 (ownerless takeover). They are small,
  independent changes on the current FEAT-467 code owned by FEAT-605 (W1.4, W1.5) and do
  **not** depend on this storage conversion; §2.8 only moves the already-guarded bodies.

---

## 2. Architectural Design

### 2.1 Overview

```
Studio view (handlers/studio/*.py)
   │  partition = await self._studio_partition()  ← GLOBAL until FEAT-605 v0.2 derives it from RequestScope
   │  (FEAT-605 v0.2 applies can_see/owns on the records returned below, then writes with a StudioWriteGuard)
   ▼
Studio services (handlers/studio/storage/services.py)      validation, size caps, bot-class and config-key
   │                                                        allowlists, secret split, TenantToolingPolicy (§2.5b)
   ▼
Studio repositories (handlers/studio/storage/repositories.py)   raw parametrised SQL, asyncdb pool,
   │                                                             one partition argument on every method,
   │                                                             SELECT … FOR UPDATE + guard in one transaction
   ▼
Postgres (≥ 14)  navigator.ai_agents ─┬─ ai_agent_assets
                                      ├─ ai_agent_tooling
                 navigator.ai_agent_drafts   navigator.ai_skills_catalog (migrated in place)
                 navigator.ai_studio_migrations (ledger; checksums match migrations/MANIFEST.json)

BotManager.studio ── StudioAgentRuntime (manager/studio_runtime.py)
                        StudioRuntimeCache   (NOT BotManager._bots / _botdef)
                          base entries  "studio:<tenant|->:<name>"
                          session entries "studio:<tenant|->:<name>" + session_id (TTL)
                          leases, retirement, identity-based cleanup, own sweep task
                        revalidate: SELECT agent_id, version, status … on every lookup (§2.6)
                        build: one-statement snapshot → StudioAgentBuilder (explicit constructor map, §2.7)
                        assets: identity → constructor kwargs; kb/skills → per-pod versioned dir
                        identity: chatbot_id = str(agent_id); _tooling_ref = "studio-agent:<agent_id>"
```

### 2.2 Storage backend selection

A single setting, resolved once per app by `ensure_studio_storage(app)` (§2.7a), which both
the `resolve_studio_storage` startup hook and the runtime install step call:

| `PARROT_STUDIO_STORAGE` | Behaviour |
|---|---|
| `auto` (default) | Probe (below). Ledger **absent** → `filesystem`, logged at WARNING once. Ledger complete and checksums match → `database`. Ledger present but **incomplete or drifted**, or server older than PostgreSQL 14 → `unavailable`, logged at ERROR (never a silent fallback to disk once a host has started migrating). |
| `database` | Anything but "complete and matching" → `unavailable`, logged at ERROR; every Studio endpoint answers 503 `studio_storage_unavailable` (fail closed). |
| `filesystem` | Current FEAT-467 behaviour, unchanged. Non-tenant hosts only. **Deprecated** — kept so a plain host that has not applied the migrations keeps working. |

The resolved backend is stored at `app["studio_storage"]` (a `StudioStorage` object, §3 M4).
A request whose partition has a tenant is refused with 503 `studio_storage_unavailable`
when the backend is `filesystem`. A tenant is never stored on disk.

**Probe** (read-only; never DDL; three statements on one pooled connection):

1. `SHOW server_version_num` → `< 140000` ⇒ `unavailable` (§2.12 supported versions).
2. `SELECT to_regclass('navigator.ai_studio_migrations')` → `NULL` ⇒ ledger absent (no error
   is logged by the database for a missing table).
3. `SELECT version, checksum FROM navigator.ai_studio_migrations ORDER BY version` → complete
   iff every version `1..STUDIO_SCHEMA_REQUIRED` is present **and** each checksum equals the
   packaged `MANIFEST.json` entry. `max(version)` alone is never used (a gap is incompleteness).

### 2.3 Schema (owned by this spec; final executable DDL)

All tables live in schema `navigator` (literal, not `PARROT_SCHEMA`; see Q6). Types are
`text` + `CHECK` rather than enums so a future value is one migration, not an enum rewrite.
Every file below is the **complete body** of the shipped migration; §2.12 defines the file
format (body + ledger trailer), the checksum and how runners apply it. Minimum server:
PostgreSQL 14 (`CREATE OR REPLACE TRIGGER`; `gen_random_uuid()` is core since 13).

Every body starts with the same transaction-scoped advisory lock, so that any two runners
(parrot CLI, FieldSync runner, `psql -1`) applying Studio migrations to one database
serialise, whichever tool they are (§2.12 "Concurrent runners").

```sql
-- 0001_studio_migrations_ledger.sql
SELECT pg_advisory_xact_lock(4715391001);   -- STUDIO_MIGRATION_LOCK_KEY
CREATE SCHEMA IF NOT EXISTS navigator;
CREATE TABLE IF NOT EXISTS navigator.ai_studio_migrations (
    version     integer     PRIMARY KEY,
    name        text        NOT NULL,
    checksum    text        NOT NULL,          -- sha256 hex of the file BODY (§2.12), never of the trailer
    applied_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ai_studio_migrations_version_chk  CHECK (version > 0),
    CONSTRAINT ai_studio_migrations_checksum_chk CHECK (checksum ~ '^[0-9a-f]{64}$')
);
```

```sql
-- 0002_ai_agents.sql
SELECT pg_advisory_xact_lock(4715391001);
CREATE TABLE IF NOT EXISTS navigator.ai_agents (
    agent_id        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant          text        NULL,         -- NULL = non-tenant host (GLOBAL partition)
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
    CONSTRAINT ai_agents_definition_chk CHECK (jsonb_typeof(definition) = 'object'),
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
    kind          text        NOT NULL,
    name          text        NOT NULL,       -- relative path, e.g. 'role.md', 'faq.md', 'triage/SKILL.md'
    content       text        NULL,           -- v1: always set (text only)
    content_type  text        NOT NULL DEFAULT 'text/markdown',
    size          integer     NOT NULL,       -- octet_length(content) for text rows
    storage_uri   text        NULL,           -- reserved: phase-S3 binary documents (v1 never writes it)
    sha256        text        NOT NULL,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, kind, name),
    CONSTRAINT ai_agent_assets_kind_chk     CHECK (kind IN ('identity','kb','skills')),
    CONSTRAINT ai_agent_assets_body_chk     CHECK (content IS NOT NULL OR storage_uri IS NOT NULL),
    CONSTRAINT ai_agent_assets_hard_cap_chk CHECK (content IS NULL OR octet_length(content) <= 1048576),
    CONSTRAINT ai_agent_assets_size_chk     CHECK (size >= 0),
    CONSTRAINT ai_agent_assets_sha_chk      CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ai_agent_assets_name_chk     CHECK (name !~ '(^/|\.\.)')
);

CREATE TABLE IF NOT EXISTS navigator.ai_agent_tooling (
    agent_id     uuid        NOT NULL REFERENCES navigator.ai_agents(agent_id) ON DELETE CASCADE,
    kind         text        NOT NULL,
    slug         text        NOT NULL,        -- toolkit slug, or MCP server name
    position     integer     NOT NULL DEFAULT 0,
    config       jsonb       NOT NULL DEFAULT '{}'::jsonb,   -- secret-free spec dump (ToolkitSpec / AgentMCPServerSpec)
    secret_refs  jsonb       NOT NULL DEFAULT '{}'::jsonb,   -- {dotted.path: vault_name}; values never stored here
    vault_owner  text        NULL,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, kind, slug),
    CONSTRAINT ai_agent_tooling_kind_chk     CHECK (kind IN ('toolkit','mcp')),
    CONSTRAINT ai_agent_tooling_position_chk CHECK (position >= 0),
    CONSTRAINT ai_agent_tooling_config_chk   CHECK (jsonb_typeof(config) = 'object'),
    CONSTRAINT ai_agent_tooling_refs_chk     CHECK (jsonb_typeof(secret_refs) = 'object')
);

-- Version bump is enforced in the database so that no writer (Studio, a host backfill,
-- psql) can change a row without the other pods noticing (§2.6). Generic: reused by drafts.
CREATE OR REPLACE FUNCTION navigator.ai_studio_bump_version() RETURNS trigger AS $$
BEGIN
    NEW.version    := OLD.version + 1;
    NEW.updated_at := now();
    RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE OR REPLACE TRIGGER ai_agents_bump_version_trg
    BEFORE UPDATE ON navigator.ai_agents
    FOR EACH ROW EXECUTE FUNCTION navigator.ai_studio_bump_version();

-- A child write touches the parent, which bumps its version through the trigger above.
-- When the parent itself is being deleted (ON DELETE CASCADE) the UPDATE matches no row.
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
```

```sql
-- 0003_ai_agent_drafts.sql
SELECT pg_advisory_xact_lock(4715391001);
CREATE TABLE IF NOT EXISTS navigator.ai_agent_drafts (
    draft_id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant             text        NULL,
    owner              text        NOT NULL,
    name               text        NOT NULL,
    visibility         text        NOT NULL DEFAULT 'private',
    allowed_groups     text[]      NOT NULL DEFAULT '{}',
    definition         jsonb       NOT NULL,     -- StudioAgentBundle (definition + tooling + assets)
    validation         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status             text        NOT NULL DEFAULT 'draft',
    version            integer     NOT NULL DEFAULT 1,
    activated_agent_id uuid        NULL REFERENCES navigator.ai_agents(agent_id) ON DELETE SET NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ai_agent_drafts_visibility_chk CHECK (visibility IN ('private','tenant','groups')),
    CONSTRAINT ai_agent_drafts_status_chk     CHECK (status IN ('draft','validated','failed','activated')),
    CONSTRAINT ai_agent_drafts_name_chk       CHECK (name ~ '^[a-z0-9_-]{1,64}$'),
    CONSTRAINT ai_agent_drafts_tenant_chk     CHECK (tenant IS NULL OR tenant ~ '^[a-z0-9][a-z0-9_-]{0,62}$'),
    CONSTRAINT ai_agent_drafts_shared_needs_tenant_chk CHECK (tenant IS NOT NULL OR visibility = 'private'),
    CONSTRAINT ai_agent_drafts_definition_chk CHECK (jsonb_typeof(definition) = 'object'),
    CONSTRAINT ai_agent_drafts_tenant_name_key UNIQUE (tenant, name)
);
CREATE UNIQUE INDEX IF NOT EXISTS ai_agent_drafts_global_name_uq ON navigator.ai_agent_drafts (name) WHERE tenant IS NULL;
CREATE INDEX IF NOT EXISTS ai_agent_drafts_tenant_owner_idx ON navigator.ai_agent_drafts (tenant, owner);
CREATE OR REPLACE TRIGGER ai_agent_drafts_bump_version_trg
    BEFORE UPDATE ON navigator.ai_agent_drafts
    FOR EACH ROW EXECUTE FUNCTION navigator.ai_studio_bump_version();
```

```sql
-- 0004_ai_skills_catalog_tenancy.sql
-- The table already exists on hosts that ran FEAT-467 (DDL only in the model docstring,
-- models/skills_catalog.py). Baseline first (FEAT-467 columns; a fresh table gets no global
-- UNIQUE(name) and gen_random_uuid() instead of uuid_generate_v4(), so it needs no
-- uuid-ossp extension), then extend in place. An existing table keeps its own defaults.
SELECT pg_advisory_xact_lock(4715391001);
CREATE TABLE IF NOT EXISTS navigator.ai_skills_catalog (
    skill_id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    name               varchar     NOT NULL,
    description        text        NOT NULL,
    category           varchar     NOT NULL DEFAULT 'general',
    owner              varchar     NOT NULL,
    triggers           jsonb       DEFAULT '[]'::jsonb,
    body               text        NOT NULL,
    version            integer     NOT NULL DEFAULT 1,
    status             varchar     NOT NULL DEFAULT 'active',
    search_index_stale boolean     NOT NULL DEFAULT false,
    created_at         timestamptz DEFAULT now(),
    updated_at         timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ai_skills_catalog_category ON navigator.ai_skills_catalog (category);
CREATE INDEX IF NOT EXISTS idx_ai_skills_catalog_owner    ON navigator.ai_skills_catalog (owner);
ALTER TABLE navigator.ai_skills_catalog ADD COLUMN IF NOT EXISTS tenant         text   NULL;
ALTER TABLE navigator.ai_skills_catalog ADD COLUMN IF NOT EXISTS visibility     text   NOT NULL DEFAULT 'private';
ALTER TABLE navigator.ai_skills_catalog ADD COLUMN IF NOT EXISTS allowed_groups text[] NOT NULL DEFAULT '{}';
-- Drop the FEAT-467 global UNIQUE(name), whatever the host named it: every unique
-- constraint whose key is exactly the single column `name`.
DO $$
DECLARE
    c record;
BEGIN
    FOR c IN
        SELECT con.conname
          FROM pg_constraint con
          JOIN pg_attribute att
            ON att.attrelid = con.conrelid AND att.attname = 'name'
         WHERE con.conrelid = 'navigator.ai_skills_catalog'::regclass
           AND con.contype = 'u'
           AND con.conkey = ARRAY[att.attnum]::int2[]
    LOOP
        EXECUTE format('ALTER TABLE navigator.ai_skills_catalog DROP CONSTRAINT %I', c.conname);
    END LOOP;
END $$;
-- ADD CONSTRAINT has no IF NOT EXISTS: each one is guarded on pg_constraint.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'navigator.ai_skills_catalog'::regclass
                      AND conname = 'ai_skills_catalog_tenant_name_key') THEN
        ALTER TABLE navigator.ai_skills_catalog
            ADD CONSTRAINT ai_skills_catalog_tenant_name_key UNIQUE (tenant, name);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'navigator.ai_skills_catalog'::regclass
                      AND conname = 'ai_skills_catalog_visibility_chk') THEN
        ALTER TABLE navigator.ai_skills_catalog
            ADD CONSTRAINT ai_skills_catalog_visibility_chk CHECK (visibility IN ('private','tenant','groups'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'navigator.ai_skills_catalog'::regclass
                      AND conname = 'ai_skills_catalog_tenant_chk') THEN
        ALTER TABLE navigator.ai_skills_catalog
            ADD CONSTRAINT ai_skills_catalog_tenant_chk CHECK (tenant IS NULL OR tenant ~ '^[a-z0-9][a-z0-9_-]{0,62}$');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'navigator.ai_skills_catalog'::regclass
                      AND conname = 'ai_skills_catalog_shared_needs_tenant_chk') THEN
        ALTER TABLE navigator.ai_skills_catalog
            ADD CONSTRAINT ai_skills_catalog_shared_needs_tenant_chk CHECK (tenant IS NOT NULL OR visibility = 'private');
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS ai_skills_catalog_global_name_uq ON navigator.ai_skills_catalog (name) WHERE tenant IS NULL;
CREATE INDEX IF NOT EXISTS ai_skills_catalog_tenant_visibility_idx ON navigator.ai_skills_catalog (tenant, visibility);
-- Existing rows: tenant NULL, visibility 'private'; they satisfy every new CHECK, and the
-- former global UNIQUE(name) guarantees the partial index builds.
```

```sql
-- 0005_studio_drafts_baseline.sql
-- Legacy Python drafts (non-tenant only). Create-if-missing, FEAT-467 columns
-- (models/studio_drafts.py docstring), gen_random_uuid() default; no column changes.
SELECT pg_advisory_xact_lock(4715391001);
CREATE TABLE IF NOT EXISTS navigator.studio_drafts (
    draft_id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    name              varchar     NOT NULL UNIQUE,
    file_path         varchar     NOT NULL,
    status            varchar     NOT NULL DEFAULT 'draft',
    validation_report jsonb       DEFAULT '{}'::jsonb,
    base_class        varchar,
    owner_user_id     varchar     NOT NULL,
    created_at        timestamptz DEFAULT now(),
    updated_at        timestamptz DEFAULT now(),
    activated_at      timestamptz
);
CREATE INDEX IF NOT EXISTS idx_studio_drafts_status ON navigator.studio_drafts (status);
CREATE INDEX IF NOT EXISTS idx_studio_drafts_owner  ON navigator.studio_drafts (owner_user_id);
```

Phase 2 files (0006–0008) are in §2.10. Each file above is followed by its ledger trailer
(§2.12), for example:

```sql
-- @studio-ledger
INSERT INTO navigator.ai_studio_migrations (version, name, checksum)
VALUES (2, '0002_ai_agents', '<64 lowercase hex: sha256 of this file''s body>')
ON CONFLICT (version) DO NOTHING;
```

The hex is written by `parrot-studio-migrate --stamp` at release time and checked by CI
(§2.12); it is data about the body, never part of it.

### 2.4 Data Models

```python
# handlers/studio/storage/models.py  (new)

STUDIO_KEY_PREFIX: Final = "studio:"                # qualified runtime key
STUDIO_TOOLING_REF_PREFIX: Final = "studio-agent:"  # immutable tooling / vault identity (§2.5c)

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
        ':' can never appear in a name (name CHECK, STUDIO_SLUG_RE)."""
    @classmethod
    def parse(cls, qualified: str) -> "StudioAgentKey": ...

class StudioModelParams(BaseModel):
    """LLM sampling settings. The ONLY source of these values for a Studio agent (§2.7 map)."""
    model_config = ConfigDict(extra="forbid")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    top_k: int | None = Field(default=None, gt=0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)

STUDIO_MODEL_PARAM_KEYS: Final = frozenset({"temperature", "max_tokens", "top_k", "top_p"})
STUDIO_TENANT_CONFIG_KEYS: Final = frozenset()   # extra constructor kwargs a tenant may set: EMPTY in v1;
                                                 # adding a key is a spec change (it reaches the constructor)

class StudioAgentDefinition(BaseModel):
    """What POST /agents accepts, minus transport flags and the name. Stored in ai_agents.definition."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    bot_class: str = "BasicBot"
    llm: str | None = None                          # "provider:model", as CreateAgentRequest.llm
    model_params: StudioModelParams = Field(default_factory=StudioModelParams)
    system_prompt: str | None = None
    description: str | None = None
    category: str = "general"                       # kept for UI grouping; no longer a path segment
    tools: list[str] = Field(default_factory=list)  # built-in tool names; checked by TenantToolingPolicy
    config: dict[str, Any] = Field(default_factory=dict)
        # extra constructor kwargs. Never contains STUDIO_MODEL_PARAM_KEYS, "system_prompt", "tools",
        # "llm", "model", "model_config", "chatbot_id", "name", "mcp_servers", "toolkits",
        # "vector_store_config" (moved or refused by normalise). FEAT-605 reserved keys → 400.
        # Tenant partition: only STUDIO_TENANT_CONFIG_KEYS, else 422 unsupported_config_key.
        # GLOBAL partition: today's pass-through for any other key.

    @classmethod
    def from_create_request(cls, req: CreateAgentRequest) -> "StudioAgentDefinition":
        """Normalise the FEAT-467 payload: req.config["temperature"|"max_tokens"|"top_k"|"top_p"]
        → model_params; req.config["system_prompt"] → system_prompt; req.config["tools"] → tools;
        everything else stays in config. Drops `persist` and `name` (the name is a column)."""

class StudioAgentPatch(BaseModel):
    """PATCH /agents/{name} body (§2.9a). Merge-patch of the General fields; omitted = unchanged."""
    model_config = ConfigDict(extra="forbid")      # unknown key (incl. `name`, `bot_class`) → 422
    description: str | None = None
    llm: str | None = None
    model_params: StudioModelParams | None = None  # field-wise merge into definition.model_params
    system_prompt: str | None = None
    category: str | None = None
    expected_version: int | None = None

class StudioAssetInput(BaseModel):
    kind: Literal["identity", "kb", "skills"]
    name: str
    content: str
    content_type: str = "text/markdown"

class StudioAgentBundle(BaseModel):
    """What the assistant emits and a draft stores: name + definition + tooling + assets.
    Secret-bearing fields are refused (secrets are entered in the Tools tab)."""
    name: str
    definition: StudioAgentDefinition
    toolkits: list[ToolkitSpec] = Field(default_factory=list)
    mcp_servers: list[AgentMCPServerSpec] = Field(default_factory=list)
    assets: list[StudioAssetInput] = Field(default_factory=list)

@dataclass(frozen=True, slots=True)
class StudioAgentHead:
    """Result of the per-lookup revalidation query (§2.6) and of the row lock (§2.5a)."""
    agent_id: UUID; version: int; status: str

@dataclass(frozen=True, slots=True)
class StudioWriteGuard:
    """Preconditions checked under the agent (or draft) row lock, in the write transaction.
    authorized_version: version of the record the handler's access decision was made on
        (always set by handlers once FEAT-605 lands; None only for programmatic callers).
    expected_version: the client's optimistic-concurrency token (§2.9 supported routes)."""
    authorized_version: int | None = None
    expected_version: int | None = None

@dataclass(frozen=True, slots=True)
class StudioAgentRecord:
    agent_id: UUID; tenant: str | None; name: str; owner: str
    visibility: str; allowed_groups: tuple[str, ...]
    definition: StudioAgentDefinition; status: str; version: int
    created_at: datetime; updated_at: datetime
    @property
    def key(self) -> StudioAgentKey: ...
    @property
    def tooling_ref(self) -> str:
        """f"studio-agent:{self.agent_id}" (canonical lowercase hyphenated UUID). §2.5c."""

@dataclass(frozen=True, slots=True)
class StudioAssetRecord:   agent_id: UUID; kind: str; name: str; content: str | None
                           content_type: str; size: int; sha256: str; storage_uri: str | None; updated_at: datetime
@dataclass(frozen=True, slots=True)
class StudioToolingRecord: agent_id: UUID; kind: str; slug: str; position: int
                           config: dict; secret_refs: dict; vault_owner: str | None; updated_at: datetime
@dataclass(frozen=True, slots=True)
class StudioAgentSnapshot:
    """One consistent read of an agent and all its children (one SQL statement, §2.5a)."""
    record: StudioAgentRecord
    assets: tuple[StudioAssetRecord, ...]           # content included
    tooling: tuple[StudioToolingRecord, ...]        # ordered by (kind, position)
@dataclass(frozen=True, slots=True)
class StudioDraftRecord:   draft_id: UUID; tenant: str | None; owner: str; name: str
                           visibility: str; allowed_groups: tuple[str, ...]; bundle: StudioAgentBundle
                           validation: dict; status: str; version: int; activated_agent_id: UUID | None
                           created_at: datetime; updated_at: datetime
@dataclass(frozen=True, slots=True)
class StudioSkillRecord:   skill_id: UUID; tenant: str | None; owner: str; visibility: str
                           allowed_groups: tuple[str, ...]; name: str; description: str; category: str
                           triggers: list; body: str; version: int; status: str
                           search_index_stale: bool; created_at: datetime; updated_at: datetime

# Errors (M2)
class StudioNameConflict(Exception): ...           # 409 (duplicate → name_taken with FEAT-605)
class StudioVersionConflict(Exception): ...        # 409 version_conflict (client expected_version)
class StudioStaleAuthorization(Exception): ...     # internal: authorized_version moved; handler re-authorises once
class StudioNotFound(Exception): ...               # row vanished under the lock → 404
class StudioAssetTooLarge(Exception): ...          # 413 asset_too_large / agent_assets_quota
class StudioToolingRefused(Exception): ...         # 422 tooling_not_permitted, wraps TOOLKITS' TenantToolingRefused (§2.5b)
class StudioStorageUnavailable(Exception): ...     # 503 studio_storage_unavailable
class StudioStorageError(Exception): ...           # a statement failed (asyncdb error tuple, §2.5a) → 500
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

@asynccontextmanager
async def studio_transaction(pool: Any) -> AsyncIterator[Any]:
    """The ONLY way repositories open a transaction (§2.5a). Real asyncdb pg API:
    acquire a pooled `pg` connection, `await conn.transaction()` (starts it; returns the
    driver, NOT a context manager), then `await conn.commit()` or `await conn.rollback()`.
    This is the asyncdb `pg` driver (`asyncdb/drivers/pg.py` `transaction`/`commit`/`rollback`).
    Do NOT copy raw-asyncpg code (e.g. `task_memory/store/postgres.py`), where
    `connection.transaction()` returns a Transaction that needs `await tx.start()`.
    W1 ships an executable fixture test of this helper against a real Postgres."""

async def _exec(conn: Any, sql: str, *args: Any) -> Any:
    """`conn.execute` wrapper: raises StudioStorageError when asyncdb returns an error tuple."""

class StudioAgentRepository:
    def __init__(self, pool: Any) -> None: ...    # app["database"] (asyncdb pg pool)
    async def get(self, part: StudioPartition, name: str) -> StudioAgentRecord | None
    async def get_version(self, part: StudioPartition, name: str) -> StudioAgentHead | None
        # SELECT agent_id, version, status … (§2.6 revalidation); no row lock
    async def load_snapshot(self, part: StudioPartition, name: str) -> StudioAgentSnapshot | None
        # ONE statement (row + json_agg of assets + json_agg of tooling) = one MVCC snapshot
    async def list(self, part: StudioPartition, *, owner: str | None = None) -> list[StudioAgentRecord]
    async def lock(self, conn, part, name, guard: StudioWriteGuard) -> StudioAgentHead
        # SELECT agent_id, version, status … FOR UPDATE; StudioNotFound / StudioVersionConflict /
        # StudioStaleAuthorization per §2.5a. Every agent-scoped write below calls it first.
    async def insert(self, conn, part, *, name: str, owner: str, definition: StudioAgentDefinition,
                     visibility: str, allowed_groups: Sequence[str]) -> StudioAgentRecord
        # StudioNameConflict on either unique index (asyncdb re-raises UniqueViolationError)
    async def update_definition(self, conn, part, name, definition) -> StudioAgentRecord
    async def update_visibility(self, conn, part, name, *, visibility: str,
                                allowed_groups: Sequence[str]) -> StudioAgentRecord
    async def set_status(self, conn, part, name, status: str) -> StudioAgentRecord
    async def delete(self, conn, part, name) -> StudioAgentSnapshot | None
        # returns what was deleted (tooling rows needed for vault clean-up, §2.5c); cascades

class StudioAssetRepository:
    async def list(self, part, agent_name, kind: str | None = None) -> list[StudioAssetRecord]   # content omitted
    async def get(self, part, agent_name, kind, name) -> StudioAssetRecord | None
    async def total_size(self, conn, agent_id: UUID) -> int           # under the agent lock (quota)
    async def put(self, conn, agent_id: UUID, asset: StudioAssetInput, *, sha256: str) -> StudioAssetRecord
    async def delete(self, conn, agent_id: UUID, kind, name) -> bool
    async def replace_all(self, conn, agent_id: UUID, assets: Sequence[StudioAssetInput]) -> None

class StudioToolingRepository:
    async def list(self, part, agent_name) -> list[StudioToolingRecord]
    async def list_locked(self, conn, agent_id: UUID) -> list[StudioToolingRecord]
    async def replace(self, conn, agent_id: UUID, *, toolkits: Sequence[StudioToolingRecord],
                      mcp_servers: Sequence[StudioToolingRecord]) -> None

class StudioDraftRepository:
    get / list(owner=) / lock(conn, part, name, guard) / insert / update_bundle / set_status /
    update_visibility / delete        # partitioned; drafts carry `version` (0003) and use the same guard

class StudioSkillCatalogRepository:
    get(part, skill_id) / get_by_name / list(category=, owner=) / insert / update / update_visibility /
    delete / mark_stale / list_stale  # no StudioWriteGuard.expected_version (§2.9)

class InMemoryStudioRepositories:  # storage/testing.py — same method set as the five repositories;
    # enforces UNIQUE(tenant, name) including the tenant-NULL partial index, the
    # tenant-NULL ⇒ private CHECK, the version bump (agents and drafts) and the guard checks,
    # and raises the same StudioNameConflict / StudioVersionConflict / StudioStaleAuthorization /
    # None-for-absent signals. For FEAT-605 tests. Concurrency itself is only tested on Postgres.

# Every method that takes a partition joins through ai_agents with the partition predicate
#   WHERE a.name = $n AND a.tenant IS NOT DISTINCT FROM $t
# Methods that take an agent_id receive it ONLY from lock()/insert() in the same transaction,
# or from load_snapshot(), so an agent_id from another tenant is unreachable by construction.
```

```python
# handlers/studio/storage/services.py  (new)
class StudioAgentService:
    def __init__(self, repos: StudioRepositories, *, limits: StudioLimits,
                 class_allowlist: StudioClassAllowlist, tooling: "StudioToolingService",
                 tooling_gate: "StudioToolingGate") -> None
    async def create(self, part, *, name: str, owner: str, definition: StudioAgentDefinition,
                     visibility: str = "private", allowed_groups: Sequence[str] = (),
                     toolkits: Sequence[ToolkitSpec] = (), mcp_servers: Sequence[AgentMCPServerSpec] = (),
                     assets: Sequence[StudioAssetInput] = ()) -> StudioAgentRecord
        # plain POST /agents passes name/definition/visibility/allowed_groups only. Validates name
        # slug, bot_class (allowlist when part.tenant is not None), config keys, visibility domain
        # (+ tenant None ⇒ 'private'), secret-free tooling, TenantToolingPolicy (§2.5b) on the final
        # normalised tooling; inserts agent + tooling + assets in ONE transaction.
        # FEAT-605 decides WHICH visibility/groups the caller may stamp; this method stores them.
    async def create_from_bundle(self, part, *, owner: str, bundle: StudioAgentBundle,
                                 visibility: str = "private", allowed_groups: Sequence[str] = ()) -> StudioAgentRecord
    async def patch(self, part, name, patch: StudioAgentPatch, *, guard: StudioWriteGuard) -> StudioAgentRecord
        # lock → merge into the stored definition → validate as create → policy → update_definition
    async def update_visibility(self, part, name, *, visibility: str, allowed_groups: Sequence[str],
                                guard: StudioWriteGuard) -> StudioAgentRecord   # FEAT-605 PATCH …/visibility
    async def delete(self, part, name, *, guard: StudioWriteGuard) -> bool      # + §2.5c clean-up after commit
    async def get(self, part, name) -> StudioAgentRecord | None
    async def get_version(self, part, name) -> StudioAgentHead | None
    async def list(self, part, *, owner=None) -> list[StudioAgentRecord]

class StudioAssetService:      put / delete (guard=) / get / list — enforces StudioLimits under the agent lock
                               (quota = total_size + new − old), text-only (415), identity filenames
                               (IDENTITY_FILES), kb .md/.txt, skills paths + parse_skill_file; every write
                               re-checks the agent's tooling with the policy (§2.5b)
class StudioToolingService:    load / put_toolkit / delete_toolkit / put_mcp_servers (guard=) — the FEAT-593
                               validation, masking and secret split of AgentToolingStore, vault names from
                               record.tooling_ref (§2.5c), persisted to ai_agent_tooling under the agent lock
class StudioDraftService:      save_bundle(guard=) / get / list / delete(guard=) / update_visibility(guard=) /
                               activate(part, name, *, owner, replace=False, guard: StudioWriteGuard,
                                        target_guard: StudioWriteGuard | None = None)
                               activate = one transaction over draft + agent (§2.5a); stamps activated_agent_id
class StudioSkillCatalogService: publish / update / update_visibility / delete / list / import_to_agent(part, skill_id,
                                 agent_name, *, guard)   # import writes an asset row under the agent lock
```

**Policy boundary.** Services validate *data* (shape, size, allowlists, uniqueness, the
host's tooling policy). They do not decide *access*. Handlers keep their existing ownership
calls (`_require_owner`) until FEAT-605 v0.2 replaces them with `StudioAccess.can_see/owns`
applied to the records returned here, and pass the decided record's `version` as
`StudioWriteGuard.authorized_version` (§2.5a). Listing is partition-scoped in SQL and
visibility-filtered in Python by FEAT-605. That is cheap because a tenant partition holds tens
to hundreds of rows, and it keeps every policy branch in one module. SQL push-down is a later
optimisation behind the same service signature.

**Limits** (`StudioLimits`, from config, defaults):

| Setting | Default | Error |
|---|---|---|
| `STUDIO_ASSET_MAX_BYTES_IDENTITY` | 64 KiB per file | 413 `asset_too_large` |
| `STUDIO_ASSET_MAX_BYTES_KB` | 256 KiB per file | 413 |
| `STUDIO_ASSET_MAX_BYTES_SKILLS` | 128 KiB per file | 413 |
| `STUDIO_AGENT_MAX_ASSET_BYTES` | 4 MiB total per agent | 413 `agent_assets_quota` (checked under the agent row lock) |
| DB hard ceiling | 1 MiB per row (`CHECK`) | 500 if bypassed; the service caps are always lower |

**Bot-class allowlist.** On a tenant partition, `bot_class` must be one of the classes
exported by `parrot.bots.__all__` (the source the catalog already uses,
`studio/catalog.py:96-104`) plus any the host adds via
`app["studio_class_allowlist"]`. `BotManager.get_bot_class` alone is not enough: it imports
`parrot.agents.<bot_class.lower()>` from a client-supplied string (`manager.py:291-296`).
Non-tenant partitions keep today's `get_bot_class` resolution.

### 2.5a Transactions, locking and snapshots (asyncdb API, verified)

**Lock order (deadlock rule).** Every transaction that locks more than one row takes locks
in this fixed order and never the reverse: draft row → agent row → child rows
(`ai_agent_assets`, `ai_agent_tooling`) ordered by `(kind, name)` → catalogue rows by
`skill_id`. A child row is never locked before its parent. Activation with `replace=true`
locks the draft, then the target agent, in that order.

**The real driver API.** `app["database"]` is an asyncdb `pgPool` (asyncdb 2.16.2, the floor
pinned by `packages/ai-parrot/pyproject.toml:127`; read in the installed
`asyncdb/drivers/pg.py`):

| Call | Behaviour | Line |
|---|---|---|
| `async with pool.acquire() as conn` (also `async with await pool.acquire()`) | yields a `pg` driver bound to one asyncpg connection; released on exit | `pg.py:443`, `:180-193` |
| `await conn.transaction()` | calls `self._connection.transaction()` then `await …start()`; **returns the driver**, not a context manager; no isolation/read-only arguments | `:1069-1074` |
| `await conn.commit()` / `await conn.rollback()` | commit/rollback the stored transaction, then clear it | `:1076-1086` |
| `await conn.execute(sql, *args)` | re-raises `UniqueViolationError`, `ForeignKeyViolationError`, `NotNullViolationError`, `StatementError`, `QueryCanceledError`; **every other `PostgresError` (CHECK violation, lock timeout, deadlock, serialization failure) is returned as `[result, error]`, not raised** | `:937-975` |
| `fetch_one` / `fetchval` | raise `StatementError` / `ProviderError` | `:1036-1067` |
| `fetch_all` | raises on error; returns **`None`** (not `[]`) for zero rows | `:1013-1031` |
| `copy_to_table` / `copy_into_table` | **commit an open transaction** before copying | `:1188-1214` |

Therefore: repositories open transactions only through `studio_transaction(pool)`
(`await conn.transaction()` … `commit()`; `rollback()` then re-raise on any exception, including
`CancelledError`); every `execute` goes through `_exec`, which raises `StudioStorageError`
when the error slot is set (so a failed statement can never be followed by a commit);
`fetch_all` results are normalised to `[]`; COPY is never used inside a Studio transaction.

**Row locking and the write guard.** Every agent-scoped mutation (definition, visibility,
status, delete, any asset or tooling write, catalogue import into an agent, draft activation
with `replace`) runs in one `studio_transaction` whose first statement is

```sql
SELECT agent_id, version, status FROM navigator.ai_agents
 WHERE tenant IS NOT DISTINCT FROM $1 AND name = $2
 FOR UPDATE
```

and then, under that lock and before any other statement:

1. no row → `StudioNotFound` (404);
2. `guard.expected_version is not None and != version` → `StudioVersionConflict` (409
   `version_conflict`, nothing written);
3. `guard.authorized_version is not None and != version` → `StudioStaleAuthorization`. The
   handler re-reads the record, re-runs the FEAT-605 access decision and retries the write
   **once** with the new `authorized_version`; a second stale result → 409 `version_conflict`.
   This closes the cross-pod check-then-write race: an access decision is only ever applied to
   the exact row version it was made on, and the lock excludes concurrent writers until commit;
4. the write itself; the version triggers bump `version` (one or more times; readers only ever
   compare for equality); the post-commit `version` is returned to the handler.

Drafts use the same protocol on `navigator.ai_agent_drafts` (which has its own `version` and
bump trigger, 0003). Create relies on the unique indexes (a concurrent create of the same
name raises `StudioNameConflict` on commit), not on a lock. Vault writes (DocumentDB until
phase 2) happen inside the transaction after the lock and before the DB write; if the DB
write then fails, the vault holds the new secret under the same deterministic name and the
next successful write overwrites it (no secret is ever referenced by a row that was not
committed).

**Draft activation** (`StudioDraftService.activate`) is one transaction:

1. lock the draft row (`FOR UPDATE`, partition + name) and apply its guard; status must be
   `draft` or `validated`, else 409 `version_conflict` (already activated by someone else);
2. validate the bundle and run the tooling policy on its final normalised tooling (§2.5b);
3. `replace=false`: insert the agent, its tooling and its assets (a name clash raises
   `StudioNameConflict`, rolled back); `replace=true`: lock the target agent with
   `target_guard`, `update_definition`, then `replace_all` assets and `replace` tooling with
   exactly the bundle's rows (**atomic bundle replacement** — no mix of old and new children);
4. `UPDATE ai_agent_drafts SET status = 'activated', activated_agent_id = $id`;
5. commit. Any failure rolls back all of it: the agent and the draft are unchanged. After
   commit, vault entries of tooling slugs the replacement removed are deleted best-effort
   (§2.5c).

Two concurrent activations of one draft serialise on the draft lock; the second sees
`status = 'activated'` and gets 409.

**Runtime build snapshot.** The builder never assembles an agent from several queries.
`StudioAgentRepository.load_snapshot` is **one** statement — the agent row plus
`json_agg` sub-selects over `ai_agent_assets` and `ai_agent_tooling` — so it reads one MVCC
snapshot even under `READ COMMITTED`: definition and children always belong to the same
committed state. The built entry is keyed by the snapshot's `(agent_id, version)`, which may
be newer than the head the revalidation saw (harmless: the next lookup compares against it).

### 2.5b Tenant tooling policy at write and build (R1)

A declarative MCP entry can start a process: `AgentMCPServerSpec` accepts `transport`,
`command`, `args` and free `params` (`tools/spec.py:32-47`), `hydrate_mcp` lets `params`
override the top-level fields (`base.update(spec.params)`, `tools/spec.py:185-196`), and the
stdio transport runs `asyncio.create_subprocess_exec` with the server environment
(`server/mcp/transports/stdio.py:153`). This spec therefore calls the **host-owned tenant
tooling policy** defined by `agentstudio-host-toolkits` (`parrot/tools/tooling_policy.py`). It
uses exactly these names from that spec and defines none of its own rules:

```python
# owned by TOOLKITS (definition, default `TenantToolingPolicy.deny_all()`, registration):
enforce_tenant_tooling(app, tooling: NormalizedTooling, *, subject: ToolingSubject) -> None
    # the write/activation hook; pure, no I/O; raises TenantToolingRefused (code "tooling_not_permitted")
ToolingSubject(tenant=part.tenant, agent_id=record.agent_id | None, actor=user_id | None,
               phase="write" | "activate" | "build")
get_tenant_tooling_policy(app) -> TenantToolingPolicy
AbstractBot.apply_tooling_specs(*, tooling_policy=..., tooling_subject=...)   # the build hook

# storage side, handlers/studio/storage/services.py
class StudioToolingGate:
    def __init__(self, app: web.Application) -> None: ...
    def enforce(self, part: StudioPartition, tooling: NormalizedTooling, *, agent_id: UUID | None,
                actor: str | None, phase: Literal["write", "activate", "build"]) -> None:
        """enforce_tenant_tooling on the FINAL normalised tooling; re-raises TenantToolingRefused
        as StudioToolingRefused (422 tooling_not_permitted)."""
```

- **What is checked**: the complete tooling the agent will have after the write, produced by
  the same `normalize_tooling` the builder uses, with `definition.tools` as its `tools` list
  (built-in tools are not assumed safe). TOOLKITS evaluates MCP entries through
  `effective_mcp_config` (top-level dump overlaid with `params`), so `transport`/`command`
  placed inside `params` are part of what the policy sees. Vault names in `secret_refs` must lie
  in the agent's `tooling_ref` namespace (§2.5c), which TOOLKITS checks as
  `secret_ref_not_permitted`.
- **On every write**: `create`/`create_from_bundle`, `patch`, every asset put/delete and
  catalogue import (re-checks the agent's current tooling under the row lock, so an agent that a
  tightened policy now refuses cannot be edited around it), `put_toolkit`, `delete_toolkit`,
  `put_mcp_servers` (the MCP editing route), `save_bundle` (draft save) and `activate`
  (`phase="activate"`; all others `phase="write"`). The check
  runs inside the write transaction, after the lock and **before** any vault or row write; a
  refusal writes nothing.
- **On every build**: `StudioAgentBuilder.build` runs the gate with `phase="build"` on the
  snapshot's tooling before calling the factory or `configure()`, and binds
  `get_tenant_tooling_policy(app)` and `ToolingSubject(part.tenant, agent_id, None, "build")` on
  the instance with `bot.bind_tooling_policy(...)` before `configure()`, whose unchanged
  no-argument `apply_tooling_specs()` call (TOOLKITS' build hook) picks them up (the plumbing is
  specified in TOOLKITS §2 "Build-hook plumbing"), so rows written behind Studio's back (psql, an older pod, a policy
  tightened after the write) never start a process. A refused build raises
  `StudioToolingRefused`; the runtime returns no instance and logs one WARNING per
  `(agent_id, version)`; handlers answer 422 `tooling_not_permitted`.
- **Partitions**: called for every partition with `tenant=part.tenant` (`None` on GLOBAL);
  TOOLKITS makes it a no-op for `None` unless the host sets `apply_to_global`.

### 2.5c Immutable identity: tooling ref, vault names, override keys, caches (R3, R4)

Storage owns identity. `ai_agents.agent_id` never changes and is never reused; every
per-agent identity below derives from it **in v1** (not phase 2). Legacy agents (registry,
YAML, `ai_bots`) keep their bare-name identities unchanged, byte for byte.

| Identity | Studio agent (any partition, incl. GLOBAL) | Legacy agent |
|---|---|---|
| tooling ref — `StudioAgentRecord.tooling_ref`; on the instance `bot._tooling_ref`; read through core `agent_tooling_ref(bot)` | `studio-agent:<agent_id>` | `bot.name` |
| agent toolkit vault name — `toolkit_vault_name(slug, ref)` | `toolkit_<slug>_studio-agent:<agent_id>` | `toolkit_<slug>_<name>` (today) |
| agent MCP vault name — `mcp_vault_name(server, ref)` | `mcp_agent_<server>_studio-agent:<agent_id>` | `mcp_agent_<server>_<name>` (today) |
| per-user override vault name — new `toolkit_override_vault_name(slug, ref)` | `toolkit_<slug>_studio-agent:<agent_id>_user` | `toolkit_<slug>_<name>_user` (today, `toolkit_overrides.py:170,200`) |
| per-user override document key (`user_toolkit_configs`) | `{user_id, agent_id: "studio-agent:<agent_id>", slug}` | `{user_id, agent_id: <name>, slug}` (today) |
| session caches in `handlers/agent.py` | `studio-agent:<agent_id>_toolkit_overrides_rev`, `studio-agent:<agent_id>_tool_manager` | `<name>_…` (today, `:1102,1130`) |
| conversation memory (`AbstractBot.memory_key_id`) | explicit `chatbot_id=str(agent_id)` ⇒ `_chatbot_id_explicit` (`abstract.py:348-355,1982`) | unchanged (explicit id or `name`) |
| Studio assistant (not a Studio agent; owned by FEAT-605) | `chatbot_id = "agent_studio:<tenant\|->"`, explicit `user_id` / `session_id` on `ask`, partitioned by `(tenant or "-", user_id)` | — |
| runtime cache key | `StudioAgentKey.qualified` (`studio:<tenant\|->:<name>`) in `StudioRuntimeCache` only | `BotManager._bots[name]` |

- The vault's AAD is `credential_context(user_id, vault_name)` (`vault_utils.py:104-108`), so a
  vault name is part of the ciphertext binding; deriving it from the UUID means a same-named
  agent in another tenant, or the same user owning both, can never read or overwrite the other's
  entry. `':'` cannot occur in any Studio or legacy slug (`STUDIO_SLUG_RE`, `_base.py:48`), so a
  Studio ref can never equal a legacy name; `BotManager.get_bot` refuses both prefixes (§2.7).
- `toolkit_vault_name`/`mcp_vault_name` keep their bodies; their second parameter is renamed
  `agent_ref` and every caller passes the ref (`ToolingState.tooling_ref`, §2.8), never the URL
  name. Hydration needs no change of its own: `hydrate_params`/`hydrate_mcp` read the vault
  names already stored in `secret_refs`.
- The tooling revision marker (`tooling_revision`, `tools/spec.py:134`) hashes specs whose
  `secret_refs` now carry UUID-derived names, and the session keys that hold it are keyed by the
  ref, so a revision cached for one tenant's agent never satisfies another's.
- **Delete and recreate never inherit.** A recreated name gets a new `agent_id`, hence new vault
  names, override keys, memory key and cache keys; nothing of the deleted agent is reachable
  even if clean-up failed. Clean-up is still done, after the delete commits and best-effort
  (logged, never failing the request): delete each vault name in the deleted tooling rows'
  `secret_refs` under their `vault_owner`; `ToolkitConfigService.purge_agent(ref)` removes every
  user's override documents for the ref and returns them so their `…_user` vault entries are
  deleted under each `user_id`.
- Existing data needs no re-keying: Studio rows are new, and legacy identities do not change.

### 2.6 Cross-pod synchronisation — chosen mechanism

**Chosen: read-through revalidation on every lookup, keyed on `ai_agents.version`
(bumped by trigger). No `LISTEN/NOTIFY` in v1.**

On every `StudioAgentRuntime.get(key)` / `use(key)`:

1. `get_version`: `SELECT agent_id, version, status FROM navigator.ai_agents WHERE tenant IS NOT DISTINCT FROM $1 AND name = $2`
   (served by the `(tenant, name)` unique index).
2. Row missing or `status='disabled'` → retire the cached entry (§2.7a), return `None`.
3. Cached base entry with the same `(agent_id, version)` → return it.
4. Otherwise rebuild under a per-key `asyncio.Lock` (single flight): `load_snapshot` (one
   statement, §2.5a) → `StudioAgentBuilder.build` → install the new entry; the replaced entry is
   **retired**, not cleaned immediately (§2.7a). A different `agent_id` with the same name
   (delete + recreate) is always a rebuild, never a reuse.

What this guarantees, precisely: a lookup never returns an instance older than the row
version committed before the lookup's step-1 query started (with the default TTL of 0). It
does **not** make an instance already handed to an in-flight request change under it: that
request finishes on the version it started with (§2.7a), and only the next lookup sees the
new version.

Why this and not `LISTEN/NOTIFY`:

- **No drift from missed events.** A missed notification (reconnect, pod start during a write,
  notify dropped when the transaction rolls back) cannot cause drift, because nothing depends
  on notifications.
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

### 2.7 Registry integration (`BotManager`) — a separate Studio cache (R2)

Studio instances are **never** stored in `BotManager._bots` or `_botdef`. Today `get_bot`
returns `_bots[name]` for any key present (`manager.py:842-849`) before it looks anywhere else,
`get_bot(new=True)` clones `_bots[name]`/`_botdef[name]` (`:767-837`), and `get_bots()` returns
the map itself (`:1170-1172`); a qualified id placed in that map would be reachable through all
three regardless of how obscure it is.

- **`StudioRuntimeCache`** (`manager/studio_runtime.py`) is a private attribute of
  `StudioAgentRuntime`, which is installed as `BotManager.studio` by the lifecycle hooks of
  §2.7a. It holds base entries (key `StudioAgentKey.qualified`) and session entries (key
  `(qualified, session_id)`), each a `StudioCacheEntry` (instance, `agent_id`, `version`,
  asset dir, lease count, expiry, retired/cleaned flags). No `BotManager` method reads it
  except the explicit Studio methods below.
- **Legacy paths cannot reach it**:
  - `get_bot(name, new=…)` returns `None` at its first line for any name starting with
    `studio:` or `studio-agent:` (both prefixes contain `:`, which no legacy slug can), before
    touching `_bots`, `_botdef` or the registry; this covers qualified base ids, qualified
    session ids and refs, with `new=True` or not.
  - `add_bot(bot)` raises `ValueError` for an instance carrying `_studio_key`, so no code path
    can copy a Studio instance into `_bots`.
  - `get_bots()`, `_cleanup_all_bots`, `_cleanup_expired_bots`, `reload_agent` and
    `remove_bot` operate on `_bots` only and therefore never see Studio instances.
  - The **only** additive fallback: when `get_bot(name)` (with `new=False`) finds the name
    nowhere else, the backend is `database`, and the app has no installed scope resolver, it
    returns `await self.studio.get(StudioAgentKey(None, name))`, the GLOBAL partition only
    (Q9). The instance stays in `StudioRuntimeCache`; it is not added to `_bots`.
    `get_bot(name, new=True)` never consults the Studio cache (unchanged behaviour).
  - Tenant rows are unreachable through every `get_bot` form. Exposing them to name-keyed
    runtime callers (chat, A2A, scheduler) needs a scope check and is the P13 follow-up.
- **Studio methods**:
  - `await manager.get_studio_bot(key, *, new=False, session_id="", request=None)`:
    `new=False` → `studio.get(key)` (revalidating, §2.6), then
    `enforce_agent_access(evaluator, key.qualified, request)`. `new=True` (test chat) →
    `studio.get_session(key, session_id)`: returns the session entry when its
    `(agent_id, version)` still matches the row, otherwise builds a **fresh instance from the
    current snapshot** (never a clone of the cached one) with the session TTL. PBAC is enforced
    before any build (the FEAT-153 ordering, `manager.py:768-772`).
  - `async with manager.studio.use(key, *, session_id=None, request=None) as bot:` — the same
    lookup, holding a **lease** for the duration of the block (§2.7a). Studio handlers that
    run a request on an instance (`testing.py` ask) use `use`, so the instance they hold cannot
    be cleaned under them.
- `reload_agent(name)` is unchanged. The Studio reload handler in DB mode calls
  `studio.reload(key)` (forced rebuild, same `ReloadResult` shape, `name` = bare name).
- `_load_database_bots` is not modified (it reads `ai_bots` only). Studio agents are loaded
  lazily on first lookup; no eager load, so boot time does not grow with tenants.

**Instance build** (`StudioAgentBuilder`, §3 M7). The builder calls
`agent_registry.create_agent_factory(bot_config)` (the declarative translation,
`registry.py:846-940`) **without registering** anything, and then awaits
`factory(**constructor_kwargs)`. Normal registration bridges `BotConfig.config` into the
constructor through `BotMetadata.startup_config` (`registry.py:1044`, merged at `:102` and
`:860`); a direct factory call has no such bridge, so nothing is ever put in
`BotConfig.config` or `startup_config` — every value reaches the constructor through the
explicit map below. The factory overwrites some kwargs after merging them (`registry.py:863-924`):
`system_prompt` from `BotConfig.system_prompt`; `llm`, `temperature`, `max_tokens` from
`BotConfig.model` (with `ModelConfig` defaults 0.1 / 8192, `models/basic.py:40-45`); `tools`
and `agent_mcp_servers` from `BotConfig.tools`/`toolkits`/`mcp_servers`. The map therefore
routes each value through exactly one channel:

| Constructor value | Source (definition / row / asset) | Channel |
|---|---|---|
| `name` | `record.name` (bare) | `BotConfig.name` (factory sets `merged_args["name"]`) |
| `chatbot_id` | `str(record.agent_id)` — the memory partition (R4) | kwarg |
| class | `definition.bot_class` → allowlisted class | `BotConfig.class_name` / `module` |
| `llm` | `definition.llm` (`"provider:model"`); unset → class default | kwarg (**`BotConfig.model` is always `None`**, so the factory's `ModelConfig` branch never runs) |
| `model_config` | non-`None` fields of `definition.model_params` (`temperature`, `max_tokens`, `top_k`, `top_p`) | kwarg — `AbstractBot`'s canonical source, which wins over bare kwargs and class attributes (`abstract.py:461-522`) |
| `system_prompt`, `prompt_builder` | `definition.system_prompt` | `BotConfig.system_prompt` (the factory also builds `PromptBuilder.from_system_prompt`, `registry.py:879-882`) |
| `description` | `definition.description` | kwarg |
| `role`, `goal`, `capabilities`, `backstory`, `rationale` | identity assets (`IDENTITY_FILES`) | kwargs (`abstract.py:427-431`); no identity directory |
| built-in tools | `definition.tools` | `BotConfig.tools = ToolConfig(tools=[{"name": t} …])` |
| toolkit specs | `ai_agent_tooling` rows, `kind='toolkit'`, by `position` | `BotConfig.toolkits = [ToolkitSpec…]` |
| MCP specs | rows `kind='mcp'`, by `position` | `BotConfig.mcp_servers = [AgentMCPServerSpec(...).model_dump(mode="json") …]` — the `List[Dict[str, Any]]` shape `BotConfig.mcp_servers` declares (`registry.py:241`), re-validated by `normalize_tooling` |
| `created_by` | `record.owner` | kwarg (compat for `_registry_agent_owner` readers; the row wins) |
| other kwargs | `definition.config` (tenant: `STUDIO_TENANT_CONFIG_KEYS` only) | kwargs; keys the factory overwrites are refused by `StudioAgentDefinition` normalisation |

Build steps:

1. Tooling gate (`phase="build"`) on the snapshot's normalised tooling incl. `definition.tools` (§2.5b).
2. Build `BotConfig(name, class_name, module, origin="factory", tools, toolkits, mcp_servers,
   system_prompt, model=None, config={}, startup_config={})` and the kwargs above; `factory =
   agent_registry.create_agent_factory(bot_config)`; `bot = await factory(**constructor_kwargs)`.
3. KB and skills assets → written to the entry's versioned directory
   `STUDIO_RUNTIME_DIR/<agent_id>/v<version>/<name>/{kb,skills}/` (default root
   `<tempdir>/parrot-studio-<pid>`, **never under `AGENTS_DIR`**). `bot._agents_dir =
   STUDIO_RUNTIME_DIR/<agent_id>/v<version>` before `configure()`. The skills mixin already
   honours `_agents_dir` (`skills/mixin.py:82-96`); `LocalKBMixin` does not
   (`stores/local.py:56` hardcodes `AGENTS_DIR`), so core gets a small hook (§3 M10).
4. `bot._studio_key`, `bot._studio_version`, `bot._studio_agent_id`, `bot._tooling_ref =
   record.tooling_ref` are set; `bot.bind_tooling_policy(get_tenant_tooling_policy(app),
   ToolingSubject(tenant=part.tenant, agent_id=record.agent_id, actor=None, phase="build"))`
   (TOOLKITS §2 "Build-hook plumbing"); `app["studio_confirmation_guard"]`, when the host set
   one, is installed with `bot.tool_manager.set_confirmation_guard(...)`; then `await
   bot.configure(app)`, whose existing no-argument `apply_tooling_specs()` call
   (`bots/abstract.py:1524` → `interfaces/tools.py:188`) applies the bound policy.

A build failure (policy refusal, factory error, `configure()` error) cleans the half-built
instance once, removes its directory, and raises an `AgentReloadError`-compatible error.

**Build refusal vs. unavailable tooling (one rule, both specs).** A persisted tooling entry
that the tenant policy refuses at build (a row written before TOOLKITS M7, or a policy
tightened after the write) **fails the whole build closed** with `tooling_not_permitted`:
the agent is not served and the owner must fix its configuration. A toolkit that is merely
**unresolvable** (not installed, discovery `unavailable`, host toolkit gated until M3b) is
**skipped** and reported `unavailable` in the FEAT-593 list response; the agent still
builds. In neither case is a process started or a connection opened.

### 2.7a Studio runtime lifecycle (R8)

`setup_registry_only` (FEAT-605) deliberately starts no `_cleanup_expired_bots` task, and that
task never calls `cleanup()` anyway (it calls `remove_bot`, `manager.py:2643-2654`);
`_safe_cleanup` guards by **name** (`self._cleaned_up: set[str]`, `manager.py:220,1737-1755`),
so a second version under one key would be skipped. The Studio runtime therefore owns its own
lifecycle and exposes these hooks (M7; module-level functions in `manager/studio_runtime.py`
unless noted):

| Hook | Kind | Contract |
|---|---|---|
| `ensure_studio_storage(app) -> StudioStorage` (`storage/backend.py`) | coroutine | Idempotent, memoised on `app["studio_storage"]` behind an `asyncio.Lock`: runs the §2.2 probe once per app. `resolve_studio_storage` (the `on_startup` hook `setup_studio_routes` registers) is a thin wrapper around it. |
| `add_studio_runtime_hooks(app)` | sync | Appends `install_studio_runtime` to `app.on_startup` and `shutdown_studio_runtime` to `app.on_cleanup`, **once per app** (guard key `"_astudio_runtime_hooks_installed"`). Called by `BotManager.setup()` and by FEAT-605's `BotManager.setup_registry_only(app)`. Must be called before the app freezes its signals. |
| `install_studio_runtime(app)` | `on_startup` | `storage = await ensure_studio_storage(app)` **first** (so storage resolution precedes runtime construction whatever order the host appended hooks in); if `storage.backend == "database"`, builds `StudioAgentRuntime`, sets `app["bot_manager"].studio`, and `await runtime.start()`; else `studio` stays `None` and Studio lookups raise `StudioStorageUnavailable`. |
| `StudioAgentRuntime.start()` | coroutine | Creates the runtime root directory and the sweep task (`asyncio.Task`, every `STUDIO_SWEEP_INTERVAL_SECONDS`, default 60). |
| `StudioAgentRuntime.sweep(now=None) -> int` | coroutine | One pass (also callable by tests with a fake clock): cleans session entries past `STUDIO_SESSION_TTL_SECONDS` (default 3600, the legacy 1 h) with no lease; retires base entries idle for `STUDIO_IDLE_TTL_SECONDS` (default 3600); cleans retired entries whose lease count is 0 and that were retired at least `STUDIO_RETIRE_GRACE_SECONDS` (default 300) ago. Returns the number cleaned. |
| `shutdown_studio_runtime(app)` → `StudioAgentRuntime.shutdown()` | `on_cleanup` | Cancels and awaits the sweep task; cleans **every** entry not yet cleaned (base, session, retired; leases are ignored because the app is stopping), each exactly once; removes the runtime root directory. Runs in `on_cleanup` before the host closes the pool; instance clean-up needs no database. |
| `cleanup_bot_instance(bot, *, label) -> bool` (`manager.py`, module level) | coroutine | Extracted from `_safe_cleanup` (`BOT_CLEANUP_TIMEOUT`, timeout and exception isolation, never raises). `_safe_cleanup` keeps its name guard and calls it; the Studio cache calls it with an **identity** guard (`StudioCacheEntry.cleaned`), so three successive versions under one key are each cleaned once. |

**Retirement and in-flight requests.** Replacing an entry (new version, delete, disable,
idle, reload) *retires* it: it is removed from lookup immediately, but its instance and its
`v<version>` directory stay alive while its lease count is above zero, and for at least
`STUDIO_RETIRE_GRACE_SECONDS` after retirement (the grace protects lease-less callers such as
the GLOBAL `get_bot` fallback). Asset directories are reference-counted per
`(agent_id, version)` across base and session entries and removed only when the last entry
using them is cleaned. A request that started on v1 therefore completes on v1 with its KB and
skills files intact even if another request installs v2 meanwhile.

Mount order (owned by FEAT-605): the host calls `setup_studio_routes` (appends
`resolve_studio_storage`) and `BotManager.setup_registry_only(app)` or `BotManager.setup()`
(appends the two runtime hooks through `add_studio_runtime_hooks`), in either order, before
`web.run_app`. Correctness does not depend on that order because `install_studio_runtime`
awaits `ensure_studio_storage` itself.

### 2.8 Handler switch (files → services)

Each handler verb resolves `storage = self.request.app["studio_storage"]`. When
`storage.backend == "filesystem"`, the **existing body runs unchanged** (moved into a
`_legacy_<verb>` method, verbatim, including the FEAT-605 W1.4/W1.5 draft guards if those have
merged first). Otherwise the service path runs. No handler grows past Rule-4 budgets: the
service path is a few lines per verb. Every service-path write passes a `StudioWriteGuard`
(`authorized_version` = version of the record the access decision was made on;
`expected_version` from the body on the §2.9 supported routes) and retries once on
`StudioStaleAuthorization` (§2.5a).

| Handler | Database-mode behaviour |
|---|---|
| `agents.py` `StudioAgentsHandler` | POST → `StudioAgentService.create(part, name=slug, owner=user_id, definition=StudioAgentDefinition.from_create_request(req), visibility=…, allowed_groups=…)` (always persisted; `persist`/`category` accepted, `category` stored in definition; visibility/groups default `private`/`()` until FEAT-605 stamps them). Duplicate check: `ai_agents` partition, plus, for the GLOBAL partition only, the legacy registry and `ai_bots` names (keeps FEAT-467's 409 across stores). GET → service list/get; the GLOBAL partition still merges legacy DB and registry agents (as today), a tenant partition returns Studio rows only (decision 2). DELETE → service delete (guard; §2.5c clean-up); the legacy `delegated`/`no_definition` branches apply only to legacy agents. **New** `patch` verb (`PATCH /agents/{name}`, §2.9a) → `StudioAgentService.patch`; database mode only. |
| `agents.py` `StudioAgentReloadHandler` | Studio agent → `manager.studio.reload(key)`; legacy → `manager.reload_agent(name)` as today. |
| `files.py` | `StudioAssetService`; same validation rules; `write_text` and `resolve_safe_path` disappear from the DB path. |
| `tooling_store.py` / `toolkit_config.py` / `toolkits.py` (assign) | `AgentToolingStore.load()` gains a first branch: Studio row → `ToolingState(source="studio", tooling_ref=record.tooling_ref)`; `ToolingState` gains `tooling_ref: str` (= `name` for the `database`/`registry` sources, so legacy vault names are unchanged). `_split_secrets`, `put_mcp_servers` and `delete_toolkit` compute vault names from `state.tooling_ref`, never from the URL name. `_persist` on the Studio source → `StudioToolingService` (lock, guard, policy, `StudioToolingRepository.replace`). Validation, masking and secret split are otherwise reused unchanged. |
| `toolkit_overrides.py` | Agent lookup through `AgentToolingStore.load` (Studio branch). Override documents, the `…_user` vault name and the session revision key use `state.tooling_ref` (`toolkit_override_vault_name(slug, ref)`; `ToolkitConfigService().load/save/remove(user_id, ref, …)`; `session.pop(f"{ref}_toolkit_overrides_rev")`) instead of the URL name (`:109,157,170,183,186,199,200,204`). Legacy agents: `ref == name`, byte-identical keys. |
| `handlers/agent.py` `_apply_user_toolkit_overrides` | `ref = agent_tooling_ref(agent)` replaces `agent.name` in `svc.load`/`svc.revision` and in the two session keys (`:1099-1103`, `:1130`). No behaviour change for legacy agents. |
| `toolkit_persistence.py` | `ToolkitConfigService.purge_agent(agent_ref) -> list[UserToolkitOverride]` (new; delete clean-up, §2.5c). The `(user_id, agent_id, slug)` document key is unchanged; `agent_id` now holds the ref. |
| `drafts.py` | POST accepts either `{name, source}` (Python, legacy) or `{name, bundle}` (declarative). Declarative → `StudioDraftService.save_bundle` (validation = Pydantic + allowlist + tooling schema + tooling policy). Activate on a declarative draft → `StudioDraftService.activate` (one transaction, §2.5a; create, or replace when `replace: true`). |
| `skills_catalog.py` | `StudioSkillCatalogService`; the shared `SkillRegistry` becomes a derived search index: namespace `<tenant or org_id>/_shared`, persistence path under `STUDIO_RUNTIME_DIR/_shared/<partition>/skills` (not `AGENTS_DIR`), rebuilt by `resync`/startup reconcile from Postgres. Import-to-agent writes an `ai_agent_assets` row under the agent lock. |
| `testing.py` | Studio agents: `async with manager.studio.use(key, session_id=…, request=self.request)`; the session key is `f"studio_test:{key.qualified}"` → `session_id`; the session entry lives in `StudioRuntimeCache`, not `manager._bots` (`testing.py:203-208` reads `_bots` today — Studio rows skip that path); stale version ⇒ fresh build (§2.7). |
| `meta_agent.py` + core `bots/studio/tools.py` | Tools call the services (`create_yaml_agent` → `StudioAgentService.create`, `write_*_file` → `StudioAssetService.put`, new `save_agent_bundle` → `StudioDraftService.save_bundle`). Partition = `StudioPartition.from_scope(current_context().kwargs["studio_scope"].caller)` when FEAT-605 v0.2 binds `studio_scope` (built by its `build_tool_scope`; the tenant lives on `.caller`, not on the scope object), else GLOBAL. Assistant session/instance partitioning is FEAT-605's. |
| `byok.py` | v1 unchanged (DocumentDB, or org key when the host does not mount `/keys`). Phase 2: §2.10. |
| `catalog.py` | Unchanged. |

**Python drafts gate.** The Python path (`source`, `save_agent_draft`, activate-by-import)
runs only when **all** hold: partition is GLOBAL, `STUDIO_PYTHON_DRAFTS` is true (default
`true` for backward compatibility), and the caller passes the existing superuser/owner
checks. On a tenant partition: 422 `declarative_only` (the FEAT-605 v0.2 code; one code for both
specs), and the assistant's tool list is built **without** `save_agent_draft` (so the LLM is
never offered it). This is checked by `StudioDraftService.python_drafts_allowed(part)`, the
single decision point.

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
| `POST /agents` → 201 | `source: "studio"` (was `"registry"`); `persisted: true` always; `file_path: null`; **added** `agent_id`, `version`, `tenant`; **added** `warnings: [..]` when `persist: false` was sent ("ignored: database storage always persists"). New errors: 422 `unsupported_config_key` (tenant partition, `config` key outside `STUDIO_TENANT_CONFIG_KEYS`), 422 `tooling_not_permitted`. |
| `GET /agents` items | new item kind with `source: "studio"`, `origin: "studio"`; **added** keys `agent_id`, `tenant`, `version`, `updated_at`, `visibility`, `allowed_groups` on Studio items only. Tenant partition: legacy `"registry"`/`"database"` items are not listed. |
| `GET /agents/{name}` | same keys as a list item. |
| `DELETE /agents/{name}` | same `{name, deleted}`; `409 no_definition` / `409 delegated` never returned for Studio rows. |
| `POST /agents/{name}/reload` | same `ReloadResult`. |
| `GET/PUT/DELETE /agents/{name}/files/...` | `reload_required` is `false` (writes apply on the next lookup on every pod, §2.6); **added** `version` (agent version after the write) and `sha256`. New errors: 413 `asset_too_large`, 413 `agent_assets_quota`, 415 `binary_assets_unsupported`, 422 `tooling_not_permitted` (§2.5b). List stays `{kind, files: [str]}`. |
| `POST /drafts` | request **added** alternative body `{name, bundle}`; response `file_path: null` and **added** `kind: "declarative"`, `version` for bundle drafts (`kind: "python"` added on legacy drafts). Tenant partition + `source` → 422 `declarative_only`. |
| `GET /drafts[/{name}]` | **added** `kind`, `bundle` (declarative only), `tenant`, `visibility`, `allowed_groups`, `version`. |
| `POST /drafts/{name}/activate` | declarative: `{name, activated: true, file_path: null}` + **added** `agent_id`, `version`; 409 `version_conflict` when the draft was already activated concurrently. |
| `toolkit-config`, `toolkits/{slug}`, `mcp-servers` | none on success. `editable` is true for Studio rows with an owner. New error 422 `tooling_not_permitted`. |
| `/toolkits/{slug}/me` (per-user overrides) | none. Keys now derive from the agent's tooling ref (§2.5c); a Studio agent recreated under the same name starts with `configured: false`. |
| `/skills*` | **added** `tenant`, `visibility`, `allowed_groups` on items. Name uniqueness becomes per partition. The 409 is raised from `StudioNameConflict`; its body code is today's `duplicate` **only as a pre-merge implementation state** until FEAT-605 v0.2 lands; the final contract (X14) is `name_taken` in every host (FEAT-605 C4, AC3). The same applies to the `POST /agents` 409. |
| `expected_version` (optional, **supported routes only**) | Accepted — body field, or query parameter on `DELETE` — on: `PATCH /agents/{name}`, `DELETE /agents/{name}`, `PUT`/`DELETE /agents/{name}/files/...`, `PUT /agents/{name}/toolkit-config`, `PUT`/`DELETE /agents/{name}/toolkits/{slug}`, `PUT /agents/{name}/mcp-servers`, `POST /drafts` (update of an existing draft; compared to the draft `version`), `POST /drafts/{name}/activate` (draft `version`; with `replace: true`, `target_expected_version` for the agent), and FEAT-605's `PATCH /agents/{name}/visibility` and `PATCH /drafts/{name}/visibility`. Mismatch → 409 `version_conflict`, nothing written. On any other mutating route (`/skills*`, reload, `/keys`, `/toolkits/{slug}/me`) it is refused with 400 `expected_version_unsupported` rather than silently ignored. |
| All | 503 `studio_storage_unavailable` (new code) when the backend is unusable for the request. |
| `PATCH /agents/{name}` | **new route** (§2.9a). Nothing existing changes. |

### 2.9a `PATCH /agents/{name}` — edit an agent's General fields

- **Route**: `PATCH {prefix}/agents/{name}`, a new `patch` verb on the existing
  `StudioAgentsHandler` view (same `add_view` path as GET/DELETE `/agents/{name}`, so no new
  route line and no ordering issue with FEAT-605's `/agents/{name}/visibility`).
- **Body**: `StudioAgentPatch` (§2.4). Updatable: `description`, `llm`, `model_params`
  (field-wise merge into `definition.model_params`; `null` for a field leaves it unchanged),
  `system_prompt` (`definition.system_prompt`), `category`. Optional `expected_version` → 409
  `version_conflict` on mismatch. Unknown keys inside `model_params` → 422 (the model forbids
  extras), so FEAT-605 reserved keys can never enter through it.
- **Not updatable**: `name` → 422 `name_immutable`. `bot_class` → 422 (unknown key; a class
  change is a re-create, because the allowlist and the config shape depend on it). Identity
  files (`role.md`, …), KB, skills and tooling keep their own routes; this PATCH never writes
  assets or tooling (it still re-checks the tooling policy on the agent's current tooling,
  §2.5b).
- **Why the name is immutable**: the name is part of the runtime key
  (`studio:<tenant|->:<name>`), of the partition predicate every child-table method joins on,
  of test-session keys and of the per-tenant `UNIQUE(tenant, name)` / `name_taken` rule. A
  rename would have to evict caches on every pod and re-check uniqueness under a lock, so it is
  a separate operation, out of scope for v1 (follow-up `POST /agents/{name}/rename`). Vault,
  override and memory identities do not depend on the name (§2.5c), so a rename would not move
  them.
- **Versioning**: lock + guard, one `UPDATE navigator.ai_agents SET definition = …`; the
  `ai_agents_bump_version_trg` bumps `version` and `updated_at`, so every pod rebuilds on its
  next lookup (§2.6), with the constructor values of the §2.7 map. No reload needed.
- **Response**: 200 with the same keys as `GET /agents/{name}` (Studio item, incl. `version`).
- **Backward compatibility**: additive. Filesystem backend → 503 `studio_storage_unavailable`.
  A legacy agent (registry / YAML / `ai_bots`) on the GLOBAL partition → 409
  `not_studio_agent`; it keeps its legacy edit paths. No existing response changes.
- **Access**: this spec validates data only. FEAT-605 v0.2 owns the policy row
  (`can_manage` inside the tenant, `may_author` required, 404 first).

### 2.10 Phase 2 — Studio secrets and overrides off DocumentDB (separate wave, separately releasable)

**Scope, settled (v0.2).** Phase 2 moves **all three** DocumentDB collections Studio uses to
Postgres, behind one switch per store, with byte-compatible ciphertexts so each move is a copy,
not a re-encryption:

| Store | DocumentDB today | Postgres (phase 2) | Module | Switch |
|---|---|---|---|---|
| BYOK keys | `user_llm_keys` (`byok.py:31`) | `navigator.ai_user_llm_keys` (0006) | M11 | `BYOK_STORE = documentdb \| postgres` |
| Vault credentials (agent toolkit/MCP secrets, per-user override secrets) | `user_credentials` (`vault_utils.py:41`) | `navigator.ai_user_credentials` (0007) | M12 | `VAULT_STORE = documentdb \| postgres` |
| Per-user toolkit overrides | `user_toolkit_configs` (`toolkit_persistence.py:14`) | `navigator.ai_user_toolkit_overrides` (0008) | M12 | `TOOLKIT_OVERRIDES_STORE = documentdb \| postgres` |

Defaults stay `documentdb` until a host opts in; FieldSync sets all three to `postgres`. The
identity scheme of §2.5c is already in force in v1, so phase 2 changes **where** credentials
live, never **what they are called**.

```sql
-- 0006_ai_user_llm_keys.sql
SELECT pg_advisory_xact_lock(4715391001);
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

-- 0007_ai_user_credentials.sql
SELECT pg_advisory_xact_lock(4715391001);
CREATE TABLE IF NOT EXISTS navigator.ai_user_credentials (
    user_id     text        NOT NULL,
    name        text        NOT NULL,    -- vault name, e.g. toolkit_<slug>_studio-agent:<uuid>
    credential  text        NOT NULL,    -- encrypt_credential(secret_params, credential_context(user_id, name), keyring)
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, name)
);

-- 0008_ai_user_toolkit_overrides.sql
SELECT pg_advisory_xact_lock(4715391001);
CREATE TABLE IF NOT EXISTS navigator.ai_user_toolkit_overrides (
    user_id      text        NOT NULL,
    agent_ref    text        NOT NULL,   -- tooling ref (§2.5c): 'studio-agent:<uuid>' or a legacy bare name
    slug         text        NOT NULL,
    params       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    secret_refs  jsonb       NOT NULL DEFAULT '{}'::jsonb,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, agent_ref, slug),
    CONSTRAINT ai_user_toolkit_overrides_params_chk CHECK (jsonb_typeof(params) = 'object'),
    CONSTRAINT ai_user_toolkit_overrides_refs_chk   CHECK (jsonb_typeof(secret_refs) = 'object')
);
CREATE INDEX IF NOT EXISTS ai_user_toolkit_overrides_agent_idx ON navigator.ai_user_toolkit_overrides (agent_ref);
```

- Same AAD contexts as today (`llm_key_context`, `credential_context`,
  `credentials_utils.py:53-80`), so DocumentDB ciphertexts copy to Postgres byte for byte.
- M11: `PgUserLLMKeyStore` (get/put/delete/list_masked); `resolve_user_api_key` and
  `_UserLLMKeyResolver` (`auth/broker.py:327`) read from the configured store. The session hot
  copy is unchanged. Keys are per user, not per tenant (a user's own provider key; Q4).
- M12: `store_vault_credential` / `retrieve_vault_credential` / `delete_vault_credential`
  (`vault_utils.py:84-190`) dispatch on `VAULT_STORE` to a `PgVaultCredentialStore` over the
  host pool (same signatures, so every caller — Studio, MCP, OAuth2 — is unchanged);
  `ToolkitConfigService` dispatches on `TOOLKIT_OVERRIDES_STORE` to a `PgToolkitOverrideStore`
  (same methods, incl. `purge_agent`).
- One-shot copy: `python -m parrot.handlers.studio.storage.secrets_copy --dry-run
  [--byok] [--vault] [--overrides]` (idempotent upserts; reports counts; never logs values).
- Keyring provisioning (`VAULT_MASTER_KEY_v{N}`, `VAULT_ACTIVE_KEY_ID` in pod env) stays a host
  responsibility. Without a keyring, `/keys` and secret writes answer 503 `vault_unavailable`
  as today.
- v1 (before phase 2): hosts may leave `/keys` unmounted (testing and the assistant fall back to
  the org/server key, `testing.py:288-305`); toolkit/MCP secrets need the DocumentDB vault, and
  a host without it can store secret-free tooling only (a secret write answers 503).
- `STUDIO_SCHEMA_REQUIRED` stays 5 for v1; a host that enables any phase-2 switch needs 8
  (`STUDIO_SCHEMA_REQUIRED_PHASE2`), checked by the same probe.

### 2.11 Non-tenant host behaviour (plain ai-parrot-server)

| Situation | Behaviour |
|---|---|
| Migrations not applied, `auto` | `filesystem` backend, exactly FEAT-467/593 today, one WARNING at startup. |
| Migrations partly applied or drifted | `unavailable`: Studio answers 503 until the host completes/repairs them (`parrot-studio-migrate --verify` names the gap). |
| Migrations applied, `auto` | `database` backend on the GLOBAL partition (`tenant IS NULL`). New Studio agents go to `ai_agents`. Legacy registry/YAML/`ai_bots` agents stay listed and editable through their legacy paths. Python drafts still available (gate §2.8). New agents are reachable by bare name through `get_bot` (fallback §2.7), so `/api/v1/chat/<name>` keeps working; their instances live in `StudioRuntimeCache`, not `_bots`. |
| Multi-pod | Consistent (§2.6). |
| No scope resolver | Partition is always GLOBAL; `visibility` is always `private` (CHECK). |

### 2.12 Migrations — format, integrity, runners

- **Location**: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/NNNN_<slug>.sql`
  plus `migrations/MANIFEST.json`, shipped as package data (`pyproject.toml`
  `[tool.setuptools.package-data]` gains `"parrot.handlers.studio.storage.migrations" = ["*.sql", "MANIFEST.json"]`,
  next to the existing `"parrot.handlers.models" = ["*.sql"]`).
- **File format**: UTF-8, LF line endings, no BOM, no transaction-control statements. A file is
  its **body** followed by exactly one **trailer**: the line `-- @studio-ledger` and the
  single ledger `INSERT` of §2.3. The marker appears nowhere else in the file.
- **Checksum (exact bytes)**: `sha256` over the body = every byte from the start of the file up
  to and including the `\n` that ends the line before `-- @studio-ledger`. The trailer is not
  hashed, so the checksum it carries is not self-referential.
- **Manifest**: `MANIFEST.json` = `{"required": 5, "required_phase2": 8, "migrations":
  [{"version": 1, "name": "0001_studio_migrations_ledger", "sha256": "<hex>"}, …]}`. Versions are
  contiguous from 1. CI (`test_migration_files_match_manifest`) recomputes every body hash and
  fails when a body, its trailer hex and the manifest disagree, when a version is missing, or
  when `required` is not covered.
- **Properties**: forward-only, idempotent (`IF NOT EXISTS`, `CREATE OR REPLACE`, guarded `DO`
  blocks, `ON CONFLICT DO NOTHING`); each file runs in **one transaction**; each body takes
  `pg_advisory_xact_lock(4715391001)` (`STUDIO_MIGRATION_LOCK_KEY`) first. No Python migrations.
- **Concurrent runners**: the advisory lock serialises any two runners, of any kind, on one
  database for the duration of a file's transaction. The parrot runner additionally re-reads the
  ledger after taking the lock and skips a version already recorded; another runner that
  re-executes a recorded file is harmless (idempotent body, `ON CONFLICT DO NOTHING`). A file run
  outside a transaction (autocommit) releases the lock immediately, which is why runners **must**
  wrap each file in a transaction (`psql -1`).
- **Supported PostgreSQL**: 14 or later (tested on 14 and 16). The probe (§2.2) and the CLI refuse
  older servers with a clear message.
- **Schema name**: literal `navigator`. `PARROT_SCHEMA` and `search_path` cannot redirect these
  statements, because every one is schema-qualified (`navigator.*`); a host that needs another
  schema is unsupported in v1 (Q6).
- **Plain host**: `parrot-studio-migrate --dsn "$DSN" [--dry-run | --verify | --print | --stamp]`
  (new console script in ai-parrot-server). `--verify` reports missing versions, checksum drift
  (ledger vs manifest) and unknown ledger rows, exit code 1 on any; `--print` emits the pending
  files (body + trailer) for review or `psql -1 -v ON_ERROR_STOP=1 -f`; `--stamp` (release tooling,
  repository only) rewrites trailers and the manifest from the bodies. Also callable as
  `await apply_studio_migrations(pool)` from the host's own deploy hook. **Never called by
  `setup()` or `on_startup`.**
- **FieldSync**: its own runner applies the files as-is (read via `importlib.resources` from the
  pinned wheel, or vendored byte-for-byte into FieldSync's migration tree under its own numbers),
  each in one transaction. Because each file records itself through its trailer, parrot's probe
  sees the same ledger, with the same checksums, whichever runner applied it
  (`test_host_runner_records_same_checksums`).
- **Required version**: `STUDIO_SCHEMA_REQUIRED = 5` in v1 (`STUDIO_SCHEMA_REQUIRED_PHASE2 = 8`),
  constants in `storage/migrate.py` equal to the manifest's `required`/`required_phase2`, checked
  by the §2.2 probe as "every version up to it present, checksums matching".

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: migrations + runner | yes | DDL, file format, checksum bytes, manifest, advisory lock, PG ≥ 14, CLI flags fixed in §2.3/§2.12 | — |
| M2: storage models | yes | dataclasses, Pydantic models, errors, key/ref prefixes fixed in §2.4 | — |
| M3: repositories | yes | method list, partition predicate, `studio_transaction`/`_exec`, lock + guard, one-statement snapshot fixed in §2.5/§2.5a | — |
| M4: backend selection + partition hook | yes | settings, probe, `ensure_studio_storage`, app keys, error code fixed in §2.2/§2.7a/§2.8 | — |
| M5: agent/asset/tooling services | yes | limits, allowlists, guard, policy gate, vault names from the ref, transaction boundaries fixed in §2.5–§2.5c | — |
| M6: draft + catalogue services | yes | Python gate, activation transaction, index location fixed in §2.5a/§2.8 | — |
| M7: runtime + cache + lifecycle + builder + BotManager hooks | no | — | single-flight locking, leases/retirement and cleanup ordering need the thinking model |
| M8: handler switch | yes | per-handler table §2.8 and shape table §2.9 | — |
| M9: assistant tools | yes | tool mapping fixed §2.8 | — |
| M10: core hooks (KB directory, tooling ref, override vault name) | yes | one attribute, one branch, two pure functions | — |
| M11 (phase 2): BYOK Postgres store | yes | table, AAD, switch fixed §2.10 | — |
| M12 (phase 2): vault credentials + overrides Postgres stores | yes | tables, AAD, switches, copy script fixed §2.10 | — |
| M13: tooling identity plumbing (legacy-neutral) | yes | `ToolingState.tooling_ref`, ref-keyed overrides/session keys, `purge_agent`, §2.5c table | — |

### Module 1: migrations + runner
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0001…0005_*.sql` + `MANIFEST.json` (new), `storage/migrate.py` (new), `pyproject.toml` (package-data + console script)
- **Responsibility**: the schema of §2.3; list/verify/apply/print/stamp; the read-only probe; checksum canonicalisation; completeness; PG version gate.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # parrot/handlers/studio/storage/migrate.py  (new)
  STUDIO_SCHEMA_REQUIRED: int = 5
  STUDIO_SCHEMA_REQUIRED_PHASE2: int = 8
  STUDIO_MIGRATION_LOCK_KEY: int = 4715391001
  STUDIO_MIN_SERVER_VERSION_NUM: int = 140000
  LEDGER_MARKER: str = "-- @studio-ledger"
  @dataclass(frozen=True)
  class StudioMigration: version: int; name: str; body: bytes; trailer: bytes; checksum: str
  def split_body(raw: bytes) -> tuple[bytes, bytes]:
      """Body = bytes up to and incl. the LF before the marker line; raises when the marker is absent or repeated."""
  def body_checksum(raw: bytes) -> str: ...          # sha256(split_body(raw)[0]).hexdigest()
  def list_migrations() -> list[StudioMigration]:
      """Package data via importlib.resources, sorted; validates against MANIFEST.json (contiguous, hashes)."""
  @dataclass(frozen=True)
  class LedgerState: present: bool; applied: dict[int, str]; server_version_num: int
      def complete_for(self, required: int, manifest: Mapping[int, str]) -> bool: ...
      def problems(self, required: int, manifest: Mapping[int, str]) -> list[str]: ...  # missing / drift / unknown
  async def read_ledger(conn: Any) -> LedgerState:
      """SHOW server_version_num; to_regclass(...); SELECT version, checksum ... Never DDL."""
  async def apply_studio_migrations(pool: Any, *, dry_run: bool = False) -> list[int]:
      """Per pending file: studio_transaction → advisory lock (the body's first statement) →
      re-read ledger → skip if recorded → execute body + trailer → commit. Returns versions applied."""
  def main(argv: list[str] | None = None) -> int:
      """CLI: --dsn, --dry-run, --verify, --print, --stamp."""
  ```

### Module 2: storage models
- **Path**: `handlers/studio/storage/models.py` (new), `handlers/studio/storage/__init__.py` (new)
- **Responsibility**: §2.4 types (incl. `StudioModelParams`, `StudioAgentHead`, `StudioWriteGuard`, `StudioAgentSnapshot`, `StudioAgentPatch`, `tooling_ref`), key/ref prefixes, `from_create_request` normalisation, errors.
- **Depends on**: none (imports `ToolkitSpec`, `AgentMCPServerSpec` from `parrot.tools.spec`; `CreateAgentRequest` from `handlers/studio/models.py`)

### Module 3: repositories
- **Path**: `handlers/studio/storage/repositories.py` (new); `handlers/studio/storage/testing.py` (new: `InMemoryStudioRepositories`, the fake FEAT-605 v0.2 tests use)
- **Responsibility**: §2.5 repositories over `app["database"]`, `studio_transaction` and `_exec` exactly as §2.5a (asyncdb 2.16.2 `pg` driver: `transaction()`/`commit()`/`rollback()`, error-tuple `execute`, `None`-for-empty `fetch_all`), `lock()` + guard, `load_snapshot()` as one statement.
- **Depends on**: M1, M2
- **Interface Skeleton**: as §2.5. Invariant: every SQL statement that touches a row carries `tenant IS NOT DISTINCT FROM $n` directly or through a join to `ai_agents`, or uses an `agent_id` obtained from `lock`/`insert`/`load_snapshot`.

### Module 4: backend selection + partition hook
- **Path**: `handlers/studio/storage/backend.py` (new); `handlers/studio/__init__.py` (modify `setup_studio_routes`); `handlers/studio/_base.py` (modify: add `_studio_partition`, `_studio_storage`)
- **Depends on**: M1, M3
- **Interface Skeleton**:
  ```python
  STUDIO_STORAGE_APP_KEY = "studio_storage"
  class StudioStorage:
      backend: Literal["database", "filesystem", "unavailable"]
      reason: str | None                     # e.g. "ledger incomplete: missing 4" (logged, never returned to clients)
      repos: StudioRepositories | None
      services: StudioServices | None
      def require_for(self, part: StudioPartition) -> None:
          """Raise StudioStorageUnavailable when backend != 'database' and part.tenant is not None,
          or backend == 'unavailable'."""
  async def ensure_studio_storage(app: web.Application) -> StudioStorage:
      """Idempotent, lock-guarded, memoised on app[STUDIO_STORAGE_APP_KEY]; runs the §2.2 probe once."""
  async def resolve_studio_storage(app: web.Application) -> None:
      """on_startup hook registered by setup_studio_routes, appended once per app whatever the number
      of prefixes (FEAT-605 startup-hook guard): await ensure_studio_storage(app)."""
  # _base.py
  async def _studio_partition(self) -> StudioPartition:   # returns StudioPartition.GLOBAL; FEAT-605 v0.2 W2.1 overrides
  def _studio_storage(self) -> StudioStorage: ...
  ```

### Module 5: agent / asset / tooling services
- **Path**: `handlers/studio/storage/services.py` (new); `handlers/studio/tooling_store.py` (modify: extract validation/secret split into reusable functions, add `source="studio"` branch; vault names from `state.tooling_ref`)
- **Depends on**: M3, M10, M13; the TOOLKITS task that ships `parrot/tools/tooling_policy.py` (`enforce_tenant_tooling`, `ToolingSubject`, `TenantToolingRefused`, the `apply_tooling_specs` build hook)
- **Interface Skeleton**: §2.5 (`StudioAgentService`, `StudioAssetService`, `StudioToolingService`, `StudioLimits`, `StudioClassAllowlist`), §2.5b (`StudioToolingGate`).

### Module 6: draft + catalogue services
- **Path**: `handlers/studio/storage/services.py` (same module, split into a `services/` package if it exceeds 500 lines); `handlers/models/skills_catalog.py` (modify: three new fields + docstring DDL)
- **Depends on**: M3, M5
- **Interface Skeleton**:
  ```python
  class StudioDraftService:
      def python_drafts_allowed(self, part: StudioPartition) -> bool:
          """part.tenant is None and STUDIO_PYTHON_DRAFTS is true. Single decision point."""
      async def save_bundle(self, part, *, owner: str, bundle: StudioAgentBundle,
                            visibility: str = "private", allowed_groups: Sequence[str] = (),
                            guard: StudioWriteGuard = StudioWriteGuard()) -> StudioDraftRecord: ...
      async def activate(self, part, name: str, *, owner: str, replace: bool = False,
                         guard: StudioWriteGuard, target_guard: StudioWriteGuard | None = None) -> StudioAgentRecord:
          """One transaction over draft + agent (§2.5a)."""
  ```

### Module 7: runtime + cache + lifecycle + builder + BotManager hooks
- **Path**: `packages/ai-parrot-server/src/parrot/manager/studio_runtime.py` (new); `manager/manager.py` (modify: `studio` attribute, `get_studio_bot`, `get_bot` prefix guard + GLOBAL tail fallback, `add_bot` refusal, `cleanup_bot_instance` extraction, `add_studio_runtime_hooks` call in `setup()`)
- **Depends on**: M3, M4, M10
- **Interface Skeleton**:
  ```python
  @dataclass
  class StudioCacheEntry:
      qualified: str; session_id: str | None; agent_id: UUID; version: int
      bot: AbstractBot; asset_dir: Path | None
      leases: int = 0; expires_at: float | None = None; last_used: float = 0.0
      retired_at: float | None = None; cleaned: bool = False

  class StudioRuntimeCache:
      """Private to StudioAgentRuntime. Never shared with BotManager._bots/_botdef."""
      def current(self, qualified: str) -> StudioCacheEntry | None: ...
      def session(self, qualified: str, session_id: str) -> StudioCacheEntry | None: ...
      def install(self, entry: StudioCacheEntry) -> StudioCacheEntry | None:
          """Install as current (or as the session entry); return the replaced entry, now retired."""
      def retire(self, entry: StudioCacheEntry, *, now: float) -> None: ...
      def reclaimable(self, *, now: float, grace: float, session_ttl: float, idle_ttl: float) -> list[StudioCacheEntry]: ...
      def all_entries(self) -> list[StudioCacheEntry]: ...

  class StudioAgentBuilder:
      def __init__(self, registry: AgentRegistry, runtime_dir: Path, tooling_gate: StudioToolingGate) -> None: ...
      async def build(self, snapshot: StudioAgentSnapshot, app: web.Application, *, part: StudioPartition) -> tuple[AbstractBot, Path]:
          """§2.7 map and build steps. Raises StudioToolingRefused or an AgentReloadError-compatible error."""

  class StudioAgentRuntime:
      def __init__(self, manager: "BotManager", repos: StudioRepositories, builder: StudioAgentBuilder,
                   *, revalidate_ttl: float = 0.0, session_ttl: float = 3600.0, idle_ttl: float = 3600.0,
                   retire_grace: float = 300.0, sweep_interval: float = 60.0) -> None: ...
      async def get(self, key: StudioAgentKey) -> AbstractBot | None: ...           # §2.6
      async def get_session(self, key: StudioAgentKey, session_id: str) -> AbstractBot | None: ...
      @asynccontextmanager
      async def use(self, key: StudioAgentKey, *, session_id: str | None = None,
                    request: Optional[web.Request] = None) -> AsyncIterator[AbstractBot]: ...  # lease
      async def reload(self, key: StudioAgentKey) -> ReloadResult: ...
      def evict(self, key: StudioAgentKey) -> None: ...                             # retire, never immediate cleanup
      async def start(self) -> None: ...
      async def sweep(self, now: float | None = None) -> int: ...
      async def shutdown(self) -> None: ...

  def add_studio_runtime_hooks(app: web.Application) -> None: ...
  async def install_studio_runtime(app: web.Application) -> None: ...
  async def shutdown_studio_runtime(app: web.Application) -> None: ...

  # manager.py
  async def cleanup_bot_instance(bot: AbstractBot, *, label: str) -> bool: ...     # module level
  async def get_studio_bot(self, key: StudioAgentKey, *, new: bool = False, session_id: str = "",
                           request: Optional[web.Request] = None) -> Optional[AbstractBot]: ...
  ```

### Module 8: handler switch
- **Path**: `handlers/studio/{agents,files,drafts,skills_catalog,testing,toolkit_config,toolkits}.py` (modify)
- **Depends on**: M4, M5, M6, M7, M13
- **Responsibility**: §2.8 and §2.9, with legacy bodies moved verbatim into `_legacy_*` methods; `expected_version` on the supported routes, 400 `expected_version_unsupported` elsewhere; the one stale-authorisation retry.

### Module 9: assistant tools
- **Path**: `packages/ai-parrot/src/parrot/bots/studio/tools.py` (modify); `handlers/studio/meta_agent.py` (modify: toolset built per partition)
- **Depends on**: M5, M6
- **Responsibility**: route `create_yaml_agent`, `write_identity_file`, `write_kb_file`, `write_skill_file`, `publish_skill_to_catalog` through services in database mode; add `save_agent_bundle`; omit `save_agent_draft` on tenant partitions.

### Module 10: core hooks
- **Path**: `packages/ai-parrot/src/parrot/bots/stores/local.py` (modify `_get_agent_kb_directory`); `packages/ai-parrot/src/parrot/tools/spec.py` (modify: rename the second parameter of `toolkit_vault_name`/`mcp_vault_name` to `agent_ref`; add `toolkit_override_vault_name`, `agent_tooling_ref`)
- **Responsibility**: honour `self._agents_dir` when set (same priority rule as `SkillRegistryMixin._resolve_agents_dir`, `skills/mixin.py:82-96`), else `AGENTS_DIR` as today; the identity helpers of §2.5c:
  ```python
  def toolkit_override_vault_name(slug: str, agent_ref: str) -> str:   # f"toolkit_{slug}_{agent_ref}_user"
  def agent_tooling_ref(bot: Any) -> str:                              # getattr(bot, "_tooling_ref", None) or bot.name
  ```
- **Depends on**: none

### Module 11 (phase 2): BYOK Postgres store
- **Path**: `storage/migrations/0006_ai_user_llm_keys.sql` (new), `handlers/studio/storage/byok_store.py` (new), `handlers/studio/byok.py` (modify), `packages/ai-parrot/src/parrot/auth/broker.py` (modify `_UserLLMKeyResolver` store selection)
- **Depends on**: M1

### Module 12 (phase 2): vault credentials + per-user overrides in Postgres
- **Path**: `storage/migrations/0007_ai_user_credentials.sql`, `0008_ai_user_toolkit_overrides.sql` (new); `packages/ai-parrot/src/parrot/security/vault_utils.py` (modify: `VAULT_STORE` dispatch; the Postgres store receives the pool through a registration call made by the server at startup, since core must not import server code); `handlers/studio/storage/vault_store.py`, `overrides_store.py` (new); `handlers/toolkit_persistence.py` (modify: `TOOLKIT_OVERRIDES_STORE` dispatch); `storage/secrets_copy.py` (new; also covers BYOK); a `navigator_session.vault_targets` entry for the new table, next to `parrot_users_bots` (`pyproject.toml:92-93`), so keyring rotation covers it
- **Depends on**: M1, M13

### Module 13: tooling identity plumbing (legacy-neutral, v1)
- **Path**: `handlers/studio/tooling_store.py` (`ToolingState.tooling_ref`), `handlers/studio/toolkit_overrides.py`, `handlers/toolkit_persistence.py` (`purge_agent`), `handlers/agent.py` (`_apply_user_toolkit_overrides`)
- **Responsibility**: every vault name, override key and session key of §2.5c derives from the tooling ref. For legacy agents the ref is the bare name, so this module changes no key and no behaviour on its own; it lands before any Studio row can exist.
- **Depends on**: M10

---

## 4. Test Specification

**Request/session rule.** Every handler test builds a real aiohttp request: either
`aiohttp_client` against an app with the real `navigator_session` middleware, or
`make_mocked_request(..., app=app)` with the session installed the way the middleware stores
it: `request["NAV_SESSION"] = SessionData(data={"session": {...}})`. This is the pattern in
`tests/handlers/test_ui_surfaces_scope.py:78`. No `Mock`/`SimpleNamespace` with a hand-set
`.session` attribute. Each new assertion is mutation-checked: revert the code line it guards
and see it go red (the mutation named in each row below).

**Database rule.** Repository, runtime and migration tests run against a real Postgres ≥ 14
from `TEST_STUDIO_PG_DSN` (skip with a reason when unset, precedent `TEST_PGVECTOR_DSN` in
`tests/stores/test_multimodal_pgvector_integration.py:42`). Each test gets a throwaway schema
copy or a transaction rolled back at teardown; concurrency tests use real separate
connections. Pure logic (keys, refs, models, limits, allowlists, checksum split) has DB-free
unit tests. **Constructor rule** (R5): runtime tests assert on the built instance
(`bot._llm_kwargs`, `bot._llm_raw`, `bot.system_prompt_template`/prompt builder output,
`bot.role`, `bot.memory_key_id`, `bot._pending_mcp_specs`), never on the returned JSON or the
row alone. **Process rule** (R1): policy tests patch `asyncio.create_subprocess_exec` to fail
the test if called.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_agent_key_qualified_roundtrip` | M2 | `studio:acme:sales` / `studio:-:sales` parse back; a name with `:` or a tenant `-` is rejected |
| `test_tooling_ref_scheme` | M2/M10 | `record.tooling_ref == f"studio-agent:{agent_id}"`; `agent_tooling_ref(legacy_bot) == bot.name`; no slug matching `STUDIO_SLUG_RE` can equal a ref |
| `test_vault_names_from_ref` | M10 | `toolkit_vault_name`, `mcp_vault_name`, `toolkit_override_vault_name` with a ref and with a bare name (legacy strings unchanged) |
| `test_definition_from_create_request` | M2 | `config.temperature/max_tokens/top_k/top_p` → `model_params`; `config.system_prompt` → `system_prompt`; `config.tools` → `tools`; `persist`, `name` dropped |
| `test_definition_rejects_reserved_and_overwritten_keys` | M2/M5 | `config.tenant/created_by/visibility/allowed_groups` → 400 `reserved_config_key`; `config.llm/model_config/chatbot_id/mcp_servers` → rejected |
| `test_tenant_config_keys_allowlist` | M5 | tenant partition + any `config` key → 422 `unsupported_config_key`; GLOBAL passes through |
| `test_bundle_rejects_secret_fields` | M2/M6 | a toolkit param marked `x-secret` in a bundle → rejected |
| `test_limits_per_kind` | M5 | 64 KiB identity OK, 64 KiB + 1 → `StudioAssetTooLarge`; totals quota |
| `test_binary_content_type_refused` | M5 | `application/pdf` → 415 code |
| `test_class_allowlist_tenant_vs_global` | M5 | `bot_class="Foo"` resolvable via `parrot.agents.foo` is refused on a tenant partition and allowed on GLOBAL |
| `test_python_drafts_gate` | M6 | tenant → False regardless of setting; GLOBAL + setting false → False |
| `test_backend_resolution_matrix` | M4 | auto/database/filesystem × pool present/absent × ledger absent / complete / incomplete / drifted × server 13/14 |
| `test_checksum_body_split` | M1 | body excludes the trailer; editing the trailer hex does not change the checksum; editing one body byte does; a missing or repeated marker raises |
| `test_migration_files_match_manifest` | M1 | every shipped body hash == trailer hex == manifest entry; versions contiguous; `required` covered (CI gate) |
| `test_exec_raises_on_error_tuple` | M3 | a driver double whose `execute` returns `[None, "Postgres Error: …"]` (the real asyncdb shape) → `StudioStorageError`, and `studio_transaction` calls `rollback`, never `commit` (mutation: ignore the error slot ⇒ RED) |
| `test_get_bot_refuses_studio_prefixes` | M7 | `get_bot("studio:acme:sales")`, `get_bot("studio:-:x_ab12")`, `get_bot("studio-agent:<uuid>")`, each with `new=False` and `new=True` → `None`; `_bots`/`_botdef` untouched |
| `test_add_bot_refuses_studio_instance` | M7 | `add_bot(bot_with__studio_key)` raises `ValueError` |
| `test_cleanup_bot_instance_isolation` | M7 | timeout and exception each return False without raising; `_safe_cleanup` keeps its name guard |
| `test_kb_dir_honours_agents_dir` | M10 | `_agents_dir` set → `<dir>/<name>/kb`; unset → `AGENTS_DIR/<name>/kb` (unchanged) |

### Integration Tests (real Postgres)
| Test | Description |
|---|---|
| `test_migrations_apply_twice` | apply 0001–0005 twice on an empty DB **and** on a FEAT-467 DB (`ai_skills_catalog`/`studio_drafts` pre-created with the docstring DDL, incl. `uuid_generate_v4()`, and rows); ledger has 5 rows with manifest checksums; second run applies nothing; `--verify` exits 0 both times; FEAT-467 rows keep `tenant NULL`, `private`; per-partition uniqueness holds |
| `test_migrations_detect_altered_and_missing` | alter a ledger checksum → `--verify` reports drift, probe → `unavailable`; delete ledger row 3 → "missing 3", probe → `unavailable` (never `filesystem`); unknown version 99 reported |
| `test_migrations_concurrent_runners` | two `apply_studio_migrations` calls on separate connections at once (and one parrot runner racing a raw per-file-transaction runner) → no error, each version recorded once (mutation: drop the advisory lock ⇒ intermittent failure caught by a 20× loop) |
| `test_host_runner_records_same_checksums` | a generic runner that executes each packaged file's raw bytes in one transaction (the FieldSync path, and `--print` piped to `psql -1`) leaves ledger checksums identical to the manifest; parrot's probe then resolves `database` |
| `test_constraints_raw_sql` | raw `INSERT`s bypassing services are refused: catalogue `visibility='public'`; catalogue `tenant NULL` + `visibility='tenant'`; catalogue tenant `'Bad Tenant'`; draft tenant `'-x'`; draft `tenant NULL` + `'groups'`; agent name `'a:b'`; asset `size -1`; tooling `config` array |
| `test_delete_cascades_with_touch_trigger` | deleting an agent with assets and tooling succeeds in one statement (touch trigger on cascaded child deletes) |
| `test_probe_is_read_only` | probe on a DB without the ledger returns "absent" and creates nothing (`pg_class` unchanged) |
| `test_unique_per_tenant` | `sales` in `acme` and `sales` in `beta` coexist; second `sales` in `acme` → `StudioNameConflict`; two tenant-NULL `sales` → conflict (partial index) |
| `test_partition_isolation` | every repository method called with partition `beta` on an `acme` agent returns None / False / empty; child tables unreachable by guessed `agent_id` |
| `test_version_bumps_on_child_write` | asset put / tooling replace / definition update / draft update each increment `version`; a raw `psql`-style UPDATE bumps it too |
| `test_create_without_bundle` | `StudioAgentService.create(part, name=, owner=, definition=, visibility=, allowed_groups=)` with no tooling/assets → row with those columns; `POST /agents` plain body → 201 |
| `test_create_is_atomic` | bundle with an invalid asset → no agent, no tooling rows |
| `test_stale_child_writes` | stale `expected_version` on files PUT/DELETE, toolkit PUT/DELETE, mcp-servers PUT, PATCH, visibility PATCH, draft update → 409 `version_conflict`, rows and vault unchanged; `/skills/{id}` with `expected_version` → 400 `expected_version_unsupported` |
| `test_stale_authorization_retry` | visibility changed on pod B between pod A's access read and its write → `StudioStaleAuthorization` → one re-read/re-authorise → the new decision applies (denied ⇒ 404, nothing written) (mutation: skip the `authorized_version` check ⇒ RED) |
| `test_concurrent_activation` | two activations of one declarative draft on two connections → exactly one 200, one 409; one agent; its children are exactly the bundle's; draft `activated` once |
| `test_activation_replace_is_atomic` | `replace=true` whose bundle fails mid-transaction (asset over the DB cap) → target agent's definition, assets and tooling unchanged; draft status unchanged |
| `test_concurrent_quota` | two concurrent asset PUTs each under the per-file cap but together over `STUDIO_AGENT_MAX_ASSET_BYTES` → one 413 `agent_assets_quota` (mutation: check the quota before the lock ⇒ RED) |
| `test_snapshot_during_edit` | 50 builds while another connection alternates definition+asset writes: every built instance's `_studio_version` matches the version its definition and assets came from (mutation: three separate queries ⇒ RED) |
| `test_cross_pod_revalidation` | two `BotManager` + `StudioAgentRuntime` instances ("pods") on one DB: pod A creates and edits KB; pod B's next `get()` returns an instance with the new version; delete on A → B returns None and retires its entry |
| `test_single_flight_rebuild` | 20 concurrent `get()` on a stale key → builder called once |
| `test_warm_cache_unreachable_from_legacy` (R2) | **warm** the Studio cache first: tenant `acme/sales` base entry, a test-session entry, and a GLOBAL `helper` entry. Then `get_bot("sales")`, `get_bot("studio:acme:sales")`, `get_bot("studio:acme:sales_<sid>")`, the same three with `new=True`, `get_bots()`, `_botdef`, `reload_agent("sales")` and `_cleanup_all_bots` → none returns, clones, lists or cleans a Studio instance; `get_bot("helper")` (no resolver) returns the GLOBAL instance without adding it to `_bots` (mutation: store entries in `_bots` ⇒ RED) |
| `test_builder_constructor_settings` (R5) | create with `llm="openai:gpt-4o-mini"`, `model_params={temperature: 0.3, max_tokens: 1000}`, `system_prompt`, `role.md`, one MCP spec → PATCH `temperature 0.7`, new `system_prompt` → rebuild on the **second runtime**: `bot._llm_raw`, `bot._llm_kwargs["temperature"] == 0.7`, `["max_tokens"] == 1000` (not the `ModelConfig` 8192), prompt builder carries the new prompt, `bot.role` from the asset, `bot._pending_mcp_specs` == the spec (mutation: call `factory()` with no kwargs, or set `BotConfig.model` ⇒ RED) |
| `test_memory_partitioned_by_agent_id` (R4) | `acme/sales` and `beta/sales` against one shared conversation-memory backend: `memory_key_id == str(agent_id)` for each and differ; a turn saved through one is absent from the other; delete + recreate `acme/sales` starts with empty history (mutation: omit `chatbot_id` ⇒ RED) |
| `test_cross_tenant_tooling_identity` (R3) | one user owns `sales` in `acme` and in `beta`, both with toolkit `jira` (secret) and MCP `docs` (secret header), and saves a `/toolkits/jira/me` override on each: independent create/read/update/delete on each side (masked values, vault documents under distinct names, override documents under distinct `agent_id`s, distinct session revision keys); deleting `acme/sales` leaves every `beta` secret and override intact; recreating `acme/sales` shows `configured: false`, no secret refs and the old vault names unreachable (mutation: pass the bare name to `toolkit_vault_name` ⇒ RED) |
| `test_tooling_policy_on_write_and_build` (R1) | tenant partition: PUT mcp-servers with `transport: "stdio"`; with `transport: "http"` and `params: {transport: "stdio", command: "/bin/sh"}`; the same inside a bundle via create, draft save and draft activate; an asset PUT on an agent whose row was given a stdio MCP by raw SQL → each 422 `tooling_not_permitted`, nothing written, no vault write; the raw-SQL agent's build is refused before `configure()`; no subprocess started; a host-approved config is accepted and built (mutation: check only the top-level `transport` ⇒ RED) |
| `test_lifecycle_registry_only_mount` (R8) | an app that appends `add_studio_runtime_hooks` **before** `setup_studio_routes` (reverse order) and never calls `BotManager.setup()`: startup resolves storage first and installs the runtime; lookups work |
| `test_session_expiry` | fake clock: a session entry past `STUDIO_SESSION_TTL_SECONDS` with no lease is cleaned once by `sweep()` and its directory removed; with a lease it survives until released |
| `test_three_versions_cleanup_once` | three successive versions under one key, then shutdown: each instance's `cleanup()` runs exactly once, none skipped (mutation: reuse `_safe_cleanup`'s name guard ⇒ RED) |
| `test_inflight_survives_replacement` | hold `studio.use(key)` on v1; PATCH on another connection; `get(key)` returns v2; v1 is not cleaned and `…/v1/` exists until the lease is released and the grace elapses; then v1 is cleaned once and its directory removed |
| `test_shutdown_cleans_all` | base, session and retired entries each cleaned once on `on_cleanup`; sweep task cancelled; runtime root removed |
| `test_runtime_cache_not_in_agents_dir` | after build, nothing new exists under `AGENTS_DIR`; KB/skills files exist under `STUDIO_RUNTIME_DIR/<agent_id>/v<n>/` |
| `test_get_bot_global_fallback` | tenant-NULL Studio agent on a fresh pod is returned by `get_bot("sales")`; with a scope resolver installed it is not |
| `test_patch_agent_general_fields` | PATCH description/llm/model_params/system_prompt/category → 200, `version` bumped, other pod sees it on next `get()`; `name` in body → 422 `name_immutable`; stale `expected_version` → 409 `version_conflict`; legacy agent → 409 `not_studio_agent`; filesystem → 503 |
| `test_handlers_shapes_database_mode` | `aiohttp_client` + real session: POST/GET/DELETE `/agents`, files PUT/GET, drafts bundle save + activate, toolkit-config GET/PUT; asserts §2.9 keys exactly (added keys present, no key removed vs the filesystem-mode snapshot) |
| `test_handlers_filesystem_mode_unchanged` | the existing `tests/studio/*` suite runs with `PARROT_STUDIO_STORAGE=filesystem` and passes unmodified |
| `test_tenant_partition_on_filesystem_is_503` | a partition with a tenant (test override of `_studio_partition`) on the filesystem backend → 503 `studio_storage_unavailable` |
| `test_tenant_python_draft_refused` | tenant partition, `{name, source}` → 422 `declarative_only`, no file written, nothing imported (`sys.modules` unchanged) |
| `test_assistant_toolset_per_partition` | tenant partition toolset lacks `save_agent_draft`, has `save_agent_bundle` |
| `test_toolkit_secrets_never_in_db` | PUT toolkit with a secret → `ai_agent_tooling.config` has no secret value, `secret_refs` has the ref-derived vault name |
| `test_legacy_identities_unchanged` | registry/YAML/`ai_bots` agent: vault names, override documents and session keys are byte-identical to today's |
| `test_byok_pg_roundtrip` (phase 2) | put → row encrypted with `llm_key_context`; `resolve_user_api_key` returns plaintext with `BYOK_STORE=postgres`; DocumentDB ciphertext copied verbatim decrypts |
| `test_vault_and_overrides_pg_roundtrip` (phase 2) | with `VAULT_STORE=postgres` and `TOOLKIT_OVERRIDES_STORE=postgres`, `test_cross_tenant_tooling_identity` passes and DocumentDB is never contacted; `secrets_copy` copies ciphertexts verbatim and they decrypt |

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

@pytest.fixture
def no_subprocess(monkeypatch):
    async def _refuse(*a, **k):
        raise AssertionError("a process was started")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _refuse)
```

---

## 5. Acceptance Criteria

- [ ] Migrations 0001–0005 apply cleanly on an empty DB and on a FEAT-467 DB, twice, with no errors, on PostgreSQL 14 and 16; no code path executes DDL at startup (grep gate: no `CREATE`/`ALTER` outside `storage/migrations/*.sql` and `migrate.py`).
- [ ] Migration integrity: body checksums equal trailers and `MANIFEST.json` (CI); `--verify` and the probe detect missing, altered and unknown versions; a partly migrated database resolves `unavailable`, never `filesystem`; two concurrent runners succeed; a generic host runner records the same checksums (`test_migrations_*`, `test_host_runner_records_same_checksums`).
- [ ] Every X1 constraint holds under raw SQL for agents, drafts and the catalogue: visibility domain, `tenant IS NULL ⇒ private`, tenant format (`test_constraints_raw_sql`).
- [ ] With the backend `database`, creating/editing/deleting an agent, its assets, its tooling, a declarative draft and a catalogue skill writes nothing under `AGENTS_DIR` (asserted by test).
- [ ] Two BotManager instances against one DB observe each other's writes on the next lookup (`test_cross_pod_revalidation`); a build never mixes definition and children of different versions (`test_snapshot_during_edit`).
- [ ] `UNIQUE(tenant, name)` holds for agents, drafts and skills, including tenant NULL.
- [ ] No repository method can read or write a row outside its partition (`test_partition_isolation`).
- [ ] Writes lock the row and apply the guard: stale client versions, stale authorisation, concurrent activation and concurrent quota updates behave as §2.5a (`test_stale_*`, `test_concurrent_*`, `test_activation_replace_is_atomic`); `create` works without a bundle (`test_create_without_bundle`).
- [ ] Studio instances are never in `BotManager._bots`/`_botdef`; with a warm cache, no legacy lookup, clone, enumeration, reload or cleanup reaches them (`test_warm_cache_unreachable_from_legacy`).
- [ ] Constructor settings reflect create → PATCH → rebuild on another runtime (`test_builder_constructor_settings`).
- [ ] A Studio agent's memory key is `str(agent_id)`; same-named agents in two tenants and a recreated agent share no history (`test_memory_partitioned_by_agent_id`).
- [ ] Vault names, override keys and session caches of Studio agents derive from `studio-agent:<agent_id>`; one user across two tenants gets independent secrets and overrides; delete/recreate inherits nothing; legacy identities are byte-identical (`test_cross_tenant_tooling_identity`, `test_legacy_identities_unchanged`).
- [ ] The tenant tooling policy refuses tenant stdio/command MCP configuration, including inside `params`, on every write path and at build, before any row, vault write or process; host-approved configuration works (`test_tooling_policy_on_write_and_build`).
- [ ] Lifecycle: registry-only mount works in either hook order; session instances expire; three successive versions and shutdown each clean up exactly once; an in-flight call survives replacement with its asset directory (`test_lifecycle_*`, `test_session_expiry`, `test_three_versions_cleanup_once`, `test_inflight_survives_replacement`, `test_shutdown_cleans_all`).
- [ ] On a tenant partition, no Python is imported and the Python draft endpoints/tools are refused or absent.
- [ ] Every response-shape change is additive and listed in §2.9; the existing `tests/studio/` suite passes unchanged in filesystem mode.
- [ ] `navigator.ai_bots` DDL and `_load_database_bots` are untouched (diff gate).
- [ ] `get_bot(name)` behaviour for every existing agent is unchanged; tenant rows are unreachable through it.
- [ ] New functions within ARCHITECTURE Rule 4 budgets (`flake8` complexity), modules ≤ 500 lines.
- [ ] Host guide `docs/agentstudio/db-storage.md`: settings, supported PostgreSQL, migration commands and file format, FieldSync runner note, lifecycle hooks and mount order.
- [ ] Phase 2 (separately): BYOK, vault credentials and per-user overrides round-trip through Postgres with the three switches set; DocumentDB not contacted (asserted by test).

---

## 6. Codebase Contract

Verified against worktree `sdd/agentstudio-host-integration` @ `8268c0911` (application code
identical to `3f0f2f726`; `manager.py` line numbers also identical on `dev` @ `6b37e639b`) and,
for asyncdb, the installed package `asyncdb 2.16.2` (`asyncdb/drivers/pg.py`).

### Verified Imports
```python
from parrot.registry.registry import BotConfig            # verified: studio/agents.py:31
from parrot.models.basic import ModelConfig, ToolConfig   # agents.py:29 ; registry.py:36 ; basic.py:33,40
from parrot.manager.manager import AgentNotFoundError, AgentReloadError, ReloadResult  # agents.py:34, models.py:19
from parrot.clients.factory import LLMFactory             # agents.py:27 ; parse_llm_string factory.py:174
from parrot.utils.naming import slugify_name              # agents.py:32
from parrot.bots.prompts.identity import IDENTITY_FILES   # files.py:19 ; tuple at identity.py:27
from parrot.skills.parsers import parse_skill_file        # files.py:21
from parrot.skills.store import create_skill_registry     # skills_catalog.py:34 ; def at skills/store.py:934
from parrot.tools.spec import (ToolkitSpec, AgentMCPServerSpec, NormalizedTooling, normalize_tooling,
                               toolkit_vault_name, mcp_vault_name, SECRET_MASK, MCP_SECRET_FIELDS,
                               tooling_revision)          # tooling_store.py:23-33 ; spec.py:134
from parrot.security.vault_utils import (store_vault_credential, retrieve_vault_credential,
                                         delete_vault_credential, get_vault_keyring)  # tooling_store.py:16-20, byok.py:25
from parrot.security.credentials_utils import (encrypt_credential, decrypt_credential,
                                               llm_key_context, credential_context)   # credentials_utils.py:53,68,83,108
from parrot.handlers.toolkit_persistence import ToolkitConfigService, UserToolkitOverride  # toolkit_overrides.py:18
from parrot.conf import AGENTS_DIR, BOT_CLEANUP_TIMEOUT   # conf.py:181 ; :223
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
    self._bot_expiration: Dict[str, float]             # :218
    self._cleaned_up: set[str]                         # :220  (name-keyed guard)
    self.registry: AgentRegistry = agent_registry      # :222
    def get_bot_class(self, bot_name: str) -> Optional[Type]           # :267 (imports parrot.agents.<name.lower()> :291-296)
    async def _load_database_bots(self, app) -> None                   # :610  (NOT modified)
    def add_bot(self, bot: AbstractBot) -> None                        # :738  (self._bots[bot.name] = bot)
    async def get_bot(self, name, new=False, session_id="", request=None, **kwargs)  # :744 ; new branch :767-837
                                                                       #   (PBAC :772, clone _botdef/_bots, 1 h expiry :833);
                                                                       #   `_bots[name]` returned :842-849; registry :850-867; None at tail
    def remove_bot(self, name: str) -> None                            # :870
    async def reload_agent(self, name: str) -> ReloadResult            # :880
    def get_bots(self) -> Dict[str, AbstractBot]                       # :1170 (returns self._bots)
    async def _cleanup_all_bots(self, app) -> None                     # :1693 (on_cleanup, :2288)
    async def _safe_cleanup(self, name: str, bot: AbstractBot) -> bool # :1722 (guard by name :1737, :1755)
    async def _cleanup_expired_bots(self) -> None                      # :2631 (remove_bot only, no cleanup(); started :2776 by setup's startup)

# packages/ai-parrot/src/parrot/registry/registry.py
class BotMetadata: startup_config; async def get_instance(self, *args, **kwargs)   # :50 (startup_config :67) ; :85 (merges startup_config :102)
class BotConfig(BaseModel):                            # :227 ; origin :235 ; config :236 ; tools :239 ; toolkits :240 ;
                                                       # mcp_servers: List[Dict[str, Any]] :241 ; model :242 ; system_prompt :243 ; startup_config :250
class AgentRegistry:                                   # :258
    def create_agent_factory(self, config: BotConfig) -> AgentFactory  # :846 (does not register; merged_args = {**startup_config, **kwargs} :860;
                                                       #   system_prompt :863-882; ModelConfig overwrite of llm/temperature/max_tokens;
                                                       #   tools/agent_mcp_servers from normalize_tooling; vector store :918-924)
    def load_agent_definition_file(self, yaml_file: Path) -> bool      # :964 (bridge startup_config=config.config :1044)
    def create_agent_definition(self, config, category="general") -> Path  # :1054

# packages/ai-parrot/src/parrot/bots/abstract.py
#   chatbot_id kwarg :348 ; _chatbot_id_explicit :355 ; identity kwargs :427-431 ; model_config canonical :461 ;
#   _resolve_llm_kwarg (model_config → kwarg → class attr) :505-522 ; memory_key_id :1959 (explicit id else name :1982)

# packages/ai-parrot/src/parrot/tools/spec.py
#   AgentMCPServerSpec :32 ; toolkit_vault_name :59 ; mcp_vault_name :64 ; normalize_tooling :69 ;
#   tooling_revision :134 ; hydrate_params :166 ; hydrate_mcp :185 (params override top-level fields)
# packages/ai-parrot/src/parrot/interfaces/tools.py — apply_tooling_specs :188 (hydrate + MCPServerConfig + add_mcp_server)
# packages/ai-parrot/src/parrot/security/vault_utils.py — VAULT_CRED_COLLECTION :41 ; store :84 (AAD credential_context) ; retrieve :135 ; delete :172

# packages/ai-parrot-server/src/parrot/handlers/studio/_base.py
STUDIO_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")         # :48
class StudioBaseView(BaseView):                        # :121
    async def _get_user(self) -> StudioUser            # :164
    def _require_owner(self, resource_owner, user) -> None  # :230
    async def _pbac_gate(self, resource: str, action: str)   # :308

# packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py
class ToolingState:  tooling; editable; reason; owner; source: Literal["database","registry"]   # :47-54
class AgentToolingStore:                               # :78
    async def load(self, name: str) -> ToolingState    # :84
    async def delete_toolkit(self, name, slug)         # :193 (toolkit_vault_name(slug, name) :201)
    async def put_mcp_servers(self, name, servers)     # :204 (mcp_vault_name(candidate.name, name) :221)
    async def _split_secrets(...)                      # :250 (toolkit_vault_name(slug, name) :263)
    async def _persist(self, name: str, state: ToolingState) -> None  # :292

# packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py
class UserToolkitOverride(BaseModel): user_id; agent_id; slug; params; secret_refs; updated_at   # :17
class ToolkitConfigService:                            # :28 ; save :31 ; load :37 ; remove :53 ; revision :63 — COLLECTION :14

# packages/ai-parrot-server/src/parrot/handlers/agent.py
#   _apply_user_toolkit_overrides :1082 (svc.load(…, agent.name) :1099 ; marker_key :1102 ; revision :1103 ; f"{agent.name}_tool_manager" :1130)

# packages/ai-parrot/src/parrot/skills/mixin.py    — _resolve_agents_dir honours self._agents_dir :82-96
# packages/ai-parrot/src/parrot/bots/stores/local.py — _get_agent_kb_directory :42 ; hardcoded AGENTS_DIR :56

# asyncdb 2.16.2 — asyncdb/drivers/pg.py
class pgPool:  def acquire(self) -> _pgAcquireContext  # :443 (async with / await / async with await)
class pg:
    async def execute(self, sentence, *args, **kwargs)  # :937 — returns [result, error]; raises only Unique/FK/NotNull/Statement/QueryCanceled
    async def fetch_all(self, sentence, *args)          # :1013 — None for zero rows
    async def fetch_one(self, sentence, *args)          # :1036
    async def fetchval(self, sentence, *args, column=0) # :1052
    async def transaction(self)                         # :1069 — starts; returns self
    async def commit(self) / rollback(self)             # :1076 / :1083
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| repositories | `app["database"]` pool | `async with pool.acquire() as conn`; `await conn.transaction()` / `commit()` / `rollback()` | `pg.py:443,1069-1086`; `studio/agents.py:63-64` |
| `StudioAgentBuilder` | `AgentRegistry.create_agent_factory` | `await factory(**constructor_kwargs)`, no registration | `registry.py:846-940` |
| `StudioAgentRuntime` | `BotManager.studio`; `cleanup_bot_instance` | attribute + extracted function (never `_bots`) | `manager.py:216`, `:1722` |
| `get_studio_bot` | `enforce_agent_access(evaluator, key.qualified, request)` | function call (evaluator None ⇒ allow) | `manager.py:772`, `auth/agent_guard.py:173-181` |
| lifecycle hooks | `app.on_startup` / `app.on_cleanup` | `add_studio_runtime_hooks` from `setup()` and FEAT-605 `setup_registry_only` | `manager.py:2284-2288` (pattern) |
| `StudioToolingService` | `AgentToolingStore` validation / `_split_secrets` | extracted functions, `state.tooling_ref` | `tooling_store.py:147-290` |
| `StudioToolingGate` / builder | TOOLKITS `enforce_tenant_tooling(app, tooling, subject=)`; `bot.bind_tooling_policy(policy, subject)` read by `apply_tooling_specs` | function call / instance binding before `configure()` | TOOLKITS spec (new, §2 "Build-hook plumbing"); `interfaces/tools.py:188`, `bots/abstract.py:1524` |
| backend resolver | `setup_studio_routes` | `app.on_startup.append` (same pattern as `reconcile_skills_catalog`) | `studio/__init__.py:88` |
| testing | `manager.studio.use(key, session_id=…)` | replaces `manager.get_bot(agent_name, new=True, …)` and `manager._bots.get(...)` for Studio rows | `studio/testing.py:203-216` |
| override runtime | `agent_tooling_ref(agent)` | replaces `agent.name` in keys | `handlers/agent.py:1099-1130` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.handlers.scope.RequestScope`~~ — introduced by FEAT-605 v0.2 (M1 there), not in this tree. This spec duck-types `.tenant` (`StudioPartition.from_scope`).
- ~~`TenantToolingPolicy`, `enforce_tenant_tooling`, `ToolingSubject`, `TenantToolingRefused`, `get_tenant_tooling_policy`, `AbstractBot.bind_tooling_policy`~~ — introduced by `agentstudio-host-toolkits` (`parrot/tools/tooling_policy.py`, `interfaces/tools.py`); this spec only calls them.
- ~~`BotManager.setup_registry_only`~~ — introduced by FEAT-605 W0.2; it calls this spec's `add_studio_runtime_hooks`.
- ~~`navigator.ai_agents`, `ai_agent_assets`, `ai_agent_tooling`, `ai_agent_drafts`, `ai_studio_migrations`, `ai_user_credentials`, `ai_user_toolkit_overrides`~~ — no code references any of them today (grep, 0 hits).
- ~~A migration runner in ai-parrot-server~~ — none. `packages/parrot-formdesigner/migrations/` is a precedent for numbered SQL, but not package data and not reusable here.
- ~~`CREATE TABLE` code for `studio_drafts` / `ai_skills_catalog`~~ — DDL exists only in model docstrings.
- ~~`BotConfig.origin == "studio"`~~ — `Literal["repo","factory"]` only. Builder uses `"factory"`; API responses say `"studio"`.
- ~~Tenant-aware `AgentRegistry`~~ — global, name-keyed.
- ~~A Postgres-backed vault~~ — `store_vault_credential` always uses DocumentDB (`vault_utils.py:30`, `:111`); added by M12 (phase 2).
- ~~An asyncpg-style `async with conn.transaction():` on the asyncdb `pg` driver~~ — its `transaction()` is a coroutine that starts a transaction and returns the driver (`pg.py:1069`).
- ~~A KB directory override on `LocalKBMixin`~~ — added by M10.
- ~~`BotManager.get_studio_bot`, `BotManager.studio`, `StudioRuntimeCache`, `cleanup_bot_instance`~~ — added by M7.
- ~~`agent_tooling_ref`, `toolkit_override_vault_name`, `ToolingState.tooling_ref`, `ToolkitConfigService.purge_agent`~~ — added by M10 / M13.
- ~~`PATCH /astudio/agents/{name}`~~, ~~`StudioAgentPatch`~~ — added by M8 / M2 (§2.9a). ~~`InMemoryStudioRepositories`~~ — added by M3.
- ~~Config keys `PARROT_STUDIO_STORAGE`, `STUDIO_RUNTIME_DIR`, `STUDIO_PYTHON_DRAFTS`, `STUDIO_REVALIDATE_TTL_SECONDS`, `STUDIO_SESSION_TTL_SECONDS`, `STUDIO_IDLE_TTL_SECONDS`, `STUDIO_RETIRE_GRACE_SECONDS`, `STUDIO_SWEEP_INTERVAL_SECONDS`, `STUDIO_ASSET_MAX_BYTES_*`, `BYOK_STORE`, `VAULT_STORE`, `TOOLKIT_OVERRIDES_STORE`~~ — all new.
- ~~`LISTEN/NOTIFY` usage anywhere in the repo~~ — none (grep).

### Edit Sites (Blueprint Anchors)

Verified against: `8268c0911`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/{__init__,models,repositories,services,backend,migrate,testing}.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/000{1..5}_*.sql`, `MANIFEST.json` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/manager/studio_runtime.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/pyproject.toml` | MODIFY | `"parrot.handlers.models" = ["*.sql"]` ; `[project.scripts]` | `pyproject.toml:111`, `:87` | 1 each |
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | `def setup_studio_routes(app: web.Application) -> None:` | `__init__.py:26` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/_base.py` | MODIFY | `    async def _get_user(self) -> StudioUser:` | `_base.py:164` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/agents.py` | MODIFY | `class _StudioAgentsMixin:` / `    async def post(self):` (2×: `:209` create, `:450` reload — anchor with the enclosing class) | `agents.py:39`, `:209`, `:450` | 2 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/files.py` | MODIFY | `class _StudioFilesMixin:` | `files.py:76` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py` | MODIFY | `    def _drafts_dir(self) -> Path:` | `drafts.py:48` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` | MODIFY | `class ToolingState:` ; `class AgentToolingStore:` ; `        vault_name = toolkit_vault_name(slug, name)` ; `            vault_name = mcp_vault_name(candidate.name, name)` ; `        await delete_vault_credential(state.owner, toolkit_vault_name(slug, name))` ; `    async def _persist(self, name: str, state: ToolingState) -> None:` | `:47`, `:78`, `:263`, `:221`, `:201`, `:292` | 1 each |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py` | MODIFY | `        vault_name = f"toolkit_{slug}_{name}_user"` ; `            await delete_vault_credential(user.user_id, f"toolkit_{slug}_{name}_user")` ; `        session.pop(f"{name}_toolkit_overrides_rev", None)` | `:170`, `:200`, `:186`/`:204` | 1, 1, 2 |
| `packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py` | MODIFY | `    async def remove(self, user_id: str, agent_id: str, slug: str) -> bool:` | `:53` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `            overrides = await svc.load(str(user_id), agent.name)` ; `            request_session[f"{agent.name}_tool_manager"] = base` | `:1099`, `:1130` | 1 each |
| `packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py` | MODIFY | `def _get_shared_skill_registry(app: Any, org_id: str):` | `:51` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` | MODIFY | `        bot = await manager.get_bot(agent_name, new=True, session_id=session_id, request=self.request)` | `:216` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/meta_agent.py` | MODIFY | `    async def post(self):` | `:77` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/models/skills_catalog.py` | MODIFY | `    search_index_stale: bool = Field(required=False, default=False)` | `skills_catalog.py:69` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `    def add_bot(self, bot: AbstractBot) -> None:` ; `    async def get_bot(` ; `    async def _safe_cleanup(self, name: str, bot: AbstractBot) -> bool:` ; `        self.app.on_cleanup.append(self._cleanup_all_bots)` | `:738`, `:744`, `:1722`, `:2288` | 1 each |
| `packages/ai-parrot/src/parrot/tools/spec.py` | MODIFY | `def toolkit_vault_name(slug: str, agent_name: str) -> str:` ; `def mcp_vault_name(server: str, agent_name: str) -> str:` | `:59`, `:64` | 1 each |
| `packages/ai-parrot/src/parrot/bots/stores/local.py` | MODIFY | `        kb_dir = Path(AGENTS_DIR) / safe_name / 'kb'` | `local.py:56` | 1 |
| `packages/ai-parrot/src/parrot/bots/studio/tools.py` | MODIFY | `async def save_agent_draft(name: str, source: str) -> dict:` ; `async def create_yaml_agent(` ; `async def _write_asset_file(agent_name: str, kind: str, filename: str, content: str) -> dict:` | `:162`, `:274`, `:342` | 1 each |
| `packages/ai-parrot-server/src/parrot/handlers/studio/byok.py` (phase 2) | MODIFY | `COLLECTION = "user_llm_keys"` | `byok.py:31` | 1 |
| `packages/ai-parrot/src/parrot/auth/broker.py` (phase 2) | MODIFY | `class _UserLLMKeyResolver(CredentialResolver):` | `broker.py:327` | 1 |
| `packages/ai-parrot/src/parrot/security/vault_utils.py` (phase 2) | MODIFY | `VAULT_CRED_COLLECTION: str = "user_credentials"` | `vault_utils.py:41` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async throughout; the pool is the host's `app["database"]`; no sync driver, no second pool.
- Raw parametrised SQL (`$1…$n`), never string interpolation of values; the schema name is a module constant.
- Transactions only through `studio_transaction`; statements only through `_exec` (§2.5a).
- Pydantic for request/definition payloads, frozen dataclasses for records.
- `self.logger` in views; `logging.getLogger("Parrot.AgentStudio.Storage")` in services and the runtime.
- Legacy branches are moved verbatim (no drive-by refactors) so the filesystem-mode diff is reviewable as a pure move.

### Known Risks / Gotchas
- **Auto-apply semantics.** In database mode an asset or tooling write reaches the live agent on the next lookup on every pod. FEAT-467's "explicit reload" gate is gone for Studio rows (`reload_required: false`). A published/working split is out of scope (Q2).
- **Test/assistant sessions are per pod.** Session entries in `StudioRuntimeCache` and assistant instances survive only on the pod that created them; without sticky sessions a conversation restarts on another pod (memory, keyed by `agent_id`, is shared if the host's memory backend is). Host infra decision.
- **Catalogue search index is per pod** (derived `SkillRegistry`). It can lag Postgres until `resync`/reconcile. Listing and CRUD are always consistent (Q3).
- **Toolkit secrets depend on the DocumentDB vault until phase 2** (`user_credentials`, M12). A v1 host without DocumentDB can store secret-free tooling only; a secret write answers 503.
- **Lease-less callers** (the GLOBAL `get_bot` fallback used by public chat) are protected from clean-up only by `STUDIO_RETIRE_GRACE_SECONDS`; a call longer than the grace can lose its instance's KB files. Studio's own handlers use leases.
- **Several version bumps per write.** Child triggers bump the parent once per touched row; `version` is monotonic but not a write count. Clients must treat it as an opaque token.
- **Unique-constraint swap on `ai_skills_catalog`** (0004) needs a short `ACCESS EXCLUSIVE` lock. The table is small; run in the deploy window. A host-created unique **index** (not constraint) on `name` alone is not dropped by 0004 and would keep names globally unique; `--verify` warns about it.
- **Runtime cache disk use**: one directory per (agent, version) per pod, removed when its last entry is cleaned; `STUDIO_RUNTIME_DIR` must be writable (ephemeral volume is fine).
- **`created_by` duplication**: passed to the constructor for legacy readers; row `owner` wins on any disagreement.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| PostgreSQL | ≥ 14 (tested 14 and 16) | `CREATE OR REPLACE TRIGGER`; `gen_random_uuid()` core; refused below by probe and CLI |
| asyncdb | ≥ 2.16.2 (current floor) | the `pg` driver API of §2.5a; re-verify `transaction()`/`execute()` semantics on any floor bump |
| (no new Python packages) | — | — |

### Task breakdown (waves; no IDs)

| Wave | Title | Scope | Files | Depends on | Size |
|---|---|---|---|---|---|
| 0 | Studio migrations + runner | §2.3 files 0001–0005, body/trailer format, `MANIFEST.json`, advisory lock, ledger probe, PG gate, `migrate.py`, CLI (`--verify`/`--print`/`--stamp`), package-data | `storage/migrations/*`, `storage/migrate.py`, `pyproject.toml`, `tests/studio/storage/test_migrations.py` | — | M |
| 0 | Storage models | §2.4 types, prefixes, `tooling_ref`, normalisation, errors | `storage/models.py`, `storage/__init__.py`, `tests/studio/storage/test_models.py` | — | S |
| 0 | Core hooks | `_agents_dir` honoured by `LocalKBMixin`; `agent_tooling_ref`, `toolkit_override_vault_name`, `agent_ref` parameter rename | `bots/stores/local.py`, `tools/spec.py`, `tests/unit/bots/test_local_kb_dir.py`, `tests/unit/tools/test_tooling_ref.py` | — | S |
| 1 | Tooling identity plumbing (M13) | `ToolingState.tooling_ref`; ref-keyed overrides, vault names and session keys; `purge_agent`; legacy byte-identical. Merges **first** on its four files: TOOLKITS M9 (R3 consumer) follows on each and makes no edit to `toolkit_persistence.py` / `handlers/agent.py` (package X16) | `studio/tooling_store.py`, `studio/toolkit_overrides.py`, `handlers/toolkit_persistence.py`, `handlers/agent.py`, `tests/studio/test_tooling_identity.py` | core hooks | S |
| 1 | Repositories | §2.5/§2.5a: repositories, `studio_transaction`, `_exec`, `lock` + guard, one-statement snapshot, `InMemoryStudioRepositories` fake (same suite runs against both) | `storage/repositories.py`, `storage/testing.py`, `tests/studio/storage/test_repositories.py` | migrations, models | L |
| 1 | Backend selection + partition hook | §2.2 probe/settings, `ensure_studio_storage`, `StudioStorage`, `_studio_partition` | `storage/backend.py`, `studio/__init__.py`, `studio/_base.py`, tests | migrations, repositories (interface) | S |
| 2 | Agent/asset/tooling services | limits, allowlists, guard, atomic create, `patch` + `update_visibility`, tooling extraction, `StudioToolingGate` | `storage/services.py`, `studio/tooling_store.py`, tests | repositories, tooling identity, TOOLKITS `tooling_policy.py` task | L |
| 2 | Draft + catalogue services | declarative drafts, Python gate, activation transaction, `update_visibility`, catalogue model fields, derived index location | `storage/services.py` (or `services/` package), `models/skills_catalog.py`, tests | repositories, agent services | M |
| 2 | Runtime + cache + lifecycle + builder + BotManager hooks | §2.6/§2.7/§2.7a: `StudioRuntimeCache`, leases/retirement, sweep, hooks (`add_studio_runtime_hooks`, called from `setup()` here and from FEAT-605's `setup_registry_only` by its W2.2), constructor map, policy binding before `configure()`, `get_bot` guard + fallback, `add_bot` refusal, `cleanup_bot_instance` | `manager/studio_runtime.py`, `manager/manager.py`, tests (warm cache, cross-pod, single flight, lifecycle, constructor, memory) | repositories, backend, core hooks, agent services (gate), TOOLKITS Wave 1 (M7 core: build hook + `bind_tooling_policy`) | L |
| 3 | Handler switch: agents, files, tooling | §2.8 rows 1–7, §2.9 (incl. `expected_version` scope), new `PATCH /agents/{name}` (§2.9a) | `studio/agents.py`, `files.py`, `tooling_store.py`, `toolkit_config.py`, `toolkits.py`, `toolkit_overrides.py`, tests | services, runtime, backend | L |
| 3 | Handler switch: drafts, catalogue, testing | §2.8 rows 8–10 | `studio/drafts.py`, `skills_catalog.py`, `testing.py`, tests | draft/catalogue services, runtime | M |
| 3 | Assistant tools on services | §2.8 row 11, per-partition toolset | `bots/studio/tools.py`, `studio/meta_agent.py`, tests | services | M |
| 4 | Shape snapshot + host guide | §2.9 snapshot test both modes; `docs/agentstudio/db-storage.md` | tests, docs | wave 3 | S |
| P2 | BYOK Postgres store (M11) | 0006, store, switch, resolver | `storage/migrations/0006_*.sql`, `storage/byok_store.py`, `studio/byok.py`, `auth/broker.py`, tests | migrations | M |
| P2 | Vault credentials + overrides in Postgres (M12) | 0007–0008, `VAULT_STORE` / `TOOLKIT_OVERRIDES_STORE` dispatch, stores, vault rotation target | `storage/migrations/0007_*.sql`, `0008_*.sql`, `storage/vault_store.py`, `storage/overrides_store.py`, `security/vault_utils.py`, `handlers/toolkit_persistence.py`, `pyproject.toml`, tests | migrations, tooling identity | M |
| P2 | Secrets copy script | DocumentDB → Postgres one-shot for all three stores, dry-run | `storage/secrets_copy.py`, test | BYOK store, vault/overrides stores | S |

FEAT-605's early subset — exactly W0.1, W0.2, W0.3, W1.1, W1.2, W1.3, W1.4, W1.5 — needs
nothing from this spec. Its W1.3 (`testing.py` execute gate, `skills_catalog.py` resync), W1.4
(D1, draft overwrite) and W1.5 (D3, ownerless takeover) are small independent fixes on the
current FEAT-467 code that merge **before** this spec's W3 handler-switch tasks for those files,
which rebase on them and move the guarded bodies into `_legacy_*` verbatim. FEAT-605 W2.2 (the
registry-only mount calling `add_studio_runtime_hooks`) starts after this spec's W2 runtime task. FEAT-605 Wave 2
(access service, W2.1) starts once this spec's W0 + W1 (models, repositories + fake, backend
switch + partition hook) are merged; W2.1 overrides `_studio_partition`, wraps the records
returned by the services and supplies `StudioWriteGuard.authorized_version`. Every other
FEAT-605 or host-toolkits task that edits a handler file this spec's W1/W2/W3 also edits merges
**after** this spec's task for that file and rebases on it (per file; see "Cross-spec contract
(package)").

### Contract changes vs sibling specs

Starting contract → final contract (siblings must use the right-hand names):

| Item | Starting contract | Final (this spec) | Why |
|---|---|---|---|
| Skills catalogue | new `navigator.ai_skills_catalog(skill_id, tenant, owner, visibility, allowed_groups, name, category, content, updated_at, UNIQUE(tenant,name))` | **existing** `navigator.ai_skills_catalog` extended in place (migration 0004). Column is **`body`** (not `content`); keeps `description`, `triggers`, `version`, `status`, `search_index_stale`, `created_at`; adds `tenant`, `visibility`, `allowed_groups text[]` and the visibility / tenant-format / `tenant IS NULL ⇒ private` CHECKs | The table already exists with that name and FEAT-467 data; a second table of the same name is impossible |
| `allowed_groups` type | `text[]` | `text[]` everywhere (FEAT-605 v0.1 used `JSONB` for its ALTERs — v0.2 must use `text[]`) | one type across tables; GIN-indexable |
| `ai_agent_tooling` | `(agent_id, kind, slug, config, secret_refs, updated_at)` | **adds** `position int`, `vault_owner text`; PK `(agent_id, kind, slug)` | MCP server order; FEAT-593 `ToolkitSpec.vault_owner` |
| `ai_agent_assets` | `(…, content, content_type, size, updated_at)` | **adds** `storage_uri text NULL` (phase-S3 hook), `sha256 text` | decision 7 extension point; cheap change detection |
| `ai_agent_drafts` | `(draft_id, tenant, owner, name, definition, validation, status, …)` | **adds** `visibility`, `allowed_groups`, `version` (+ bump trigger), `activated_agent_id`, tenant-format CHECK, `UNIQUE(tenant,name)`; `definition` holds a `StudioAgentBundle` | FEAT-605 has `PATCH /drafts/{name}/visibility`; activation audit; guarded writes |
| `ai_agents` | as given | **adds** CHECKs (name/tenant format, `tenant IS NOT NULL OR visibility='private'`), partial unique index for tenant NULL, version trigger | uniqueness for NULL tenant; sync correctness |
| Legacy `navigator.studio_drafts` | — | kept for Python drafts only (non-tenant); baseline created by 0005 | decision 3 |
| Ledger | — | **new** `navigator.ai_studio_migrations`; checksum over the file body; `MANIFEST.json`; advisory lock `4715391001`; PG ≥ 14 | decision 6; R9 |
| Runtime key | "tenant-qualified id" | `studio:<tenant>:<name>` / `studio:-:<name>` (`StudioAgentKey.qualified`), in `StudioRuntimeCache` only, **never** in `BotManager._bots` | R2 |
| Agent identity | bare name | `agent_id`; `tooling_ref = "studio-agent:<agent_id>"` for vault names, override keys and session caches; `chatbot_id = str(agent_id)` for memory | R3, R4 |
| Write preconditions | `expected_version` on every mutating body | `StudioWriteGuard(authorized_version, expected_version)`; client `expected_version` only on the §2.9 routes, 400 `expected_version_unsupported` elsewhere | R10 |
| Tooling policy | — | storage calls TOOLKITS' `TenantToolingPolicy` on every write and build (§2.5b) | R1 |
| Lifecycle hooks | "`BotManager.studio` startup step" | `add_studio_runtime_hooks(app)` → `install_studio_runtime` (on_startup; awaits `ensure_studio_storage` first) + `shutdown_studio_runtime` (on_cleanup) | R8 |
| Scope object | "a scope object" | storage takes `StudioPartition` (tenant only), built from FEAT-605's `RequestScope` via `StudioPartition.from_scope` | storage never sees groups/superuser, so it cannot encode policy |

---

## Cross-spec contract (package)

This section is **identical** in the three package specs: STORAGE =
`agentstudio-db-storage.spec.md` (v0.2.1), FEAT-605 = `agentstudio-tenant-visibility.spec.md` (v0.2.1),
TOOLKITS = `agentstudio-host-toolkits.spec.md` (v0.2.1). Changing a row means changing it in all three.
STORAGE waves are W0–W4 and P2 (modules M1–M13); FEAT-605 tasks are W0.1–W4.3; TOOLKITS waves are
Wave 1–4 (modules M1–M9). The owner named in "Provided by" wins any naming conflict. Rows X17 and X18
were appended in the v0.2.1 reconciliation; X1–X16 keep their numbers so existing references stay valid.

| # | Item (exact names) | Provided by | Consumed by | Contract |
|---|---|---|---|---|
| X1 | Tables `navigator.ai_agents`, `navigator.ai_agent_assets`, `navigator.ai_agent_tooling`, `navigator.ai_agent_drafts` (with its own `version`), `navigator.ai_studio_migrations`; the **existing** `navigator.ai_skills_catalog` extended in place (content column `body`; adds `tenant`, `visibility`, `allowed_groups text[]`); phase 2: `navigator.ai_user_llm_keys`, `navigator.ai_user_credentials`, `navigator.ai_user_toolkit_overrides` | STORAGE W0 (migrations 0001–0005, M1); P2 (migrations 0006–0008, M11/M12) | FEAT-605, TOOLKITS (only through STORAGE services / `AgentToolingStore`) | `tenant text NULL`; agents, drafts **and** catalogue each carry the visibility-domain CHECK (`private`/`tenant`/`groups`), the tenant-format CHECK and the `tenant IS NULL ⇒ visibility = 'private'` CHECK; `allowed_groups text[]`; `UNIQUE(tenant, name)` + partial unique `(name) WHERE tenant IS NULL`; `ai_agents.version` and `ai_agent_drafts.version` bumped by trigger. Each migration file = body + one `-- @studio-ledger` trailer; the checksum is sha256 over the body only (never the trailer) and equals the trailer hex and `migrations/MANIFEST.json`; every body first takes `pg_advisory_xact_lock(4715391001)`; one transaction per file; PostgreSQL ≥ 14; required versions 1..5 (1..8 with any phase-2 switch), a gap or drift ⇒ backend `unavailable`. Literal schema `navigator` (`search_path` cannot redirect qualified names). No DDL outside the migration files, never at startup |
| X2 | Tenant-less rows (`tenant IS NULL`) | STORAGE | FEAT-605, TOOLKITS | They form the GLOBAL partition of hosts with **no** resolver; there is no sentinel tenant. No resolver may return a NULL or empty tenant as valid; a NULL row never satisfies FEAT-605 `in_tenant`; a tenant-bound tool on such an agent refuses `agent_tenant_unset` |
| X3 | `ai_agent_tooling(agent_id, kind, slug, position, config, secret_refs, vault_owner, updated_at)`, PK `(agent_id, kind, slug)` | STORAGE W0 (table), W1 (M13 identity plumbing), W2/W3 (`StudioToolingService`, `AgentToolingStore` `source="studio"`) | TOOLKITS (M2, M4, M7, M9) | `position` = list order of `ToolkitSpec`/MCP specs; `config` = secret-free spec dump, never contains a TOOLKITS server-managed key; `secret_refs` = `{dotted.path: vault_name}`, every vault name derived from `record.tooling_ref` (X17), never from the URL name; `vault_owner` = the row owner. Secret **values** and per-user `/toolkits/{slug}/me` overrides stay in DocumentDB (`user_credentials`, `user_toolkit_configs`) until STORAGE M12 moves them to Postgres under the same names; override documents are keyed `{user_id, agent_id: <tooling_ref>, slug}`. Agent delete purges, best-effort after commit, the deleted id's owner-vault names, its override documents (`ToolkitConfigService.purge_agent(ref)`) and their `…_user` vault entries; isolation never depends on the purge |
| X4 | `StudioPartition(tenant)`, `StudioPartition.GLOBAL`, `StudioPartition.from_scope(scope)` (duck-typed `.tenant`) | STORAGE W0 | FEAT-605 W2.1 | Storage addresses rows by tenant only; it never sees groups, superuser or visibility policy |
| X5 | `async StudioBaseView._studio_partition()` | STORAGE W1 (returns `GLOBAL`) | FEAT-605 W2.1 (override) | No resolver ⇒ `GLOBAL`. Resolver + tenant ⇒ `StudioPartition.from_scope(await self._scope())`. Resolver + no tenant ⇒ never `GLOBAL`: the handler answers empty / 404 / 422 `tenant_required` before any storage call |
| X6 | Records `StudioAgentRecord` (incl. `tooling_ref`), `StudioDraftRecord`, `StudioSkillRecord` (`owner`, `tenant`, `visibility`, `allowed_groups`, id, `name`); `StudioAgentHead(agent_id, version, status)`; `StudioWriteGuard(authorized_version, expected_version)`; errors `StudioNameConflict`, `StudioVersionConflict`, `StudioStaleAuthorization`, `StudioToolingRefused`, `StudioStorageUnavailable`; services `StudioAgentService` (`create(part, *, name, owner, definition, visibility="private", allowed_groups=(), toolkits=(), mcp_servers=(), assets=())`, `create_from_bundle`, `patch(…, guard=)`, `update_visibility(…, guard=)`, `delete(…, guard=)`, `get_version(part, name) -> StudioAgentHead \| None`), `StudioDraftService` (`save_bundle`, `activate(part, name, *, owner, replace=False, guard, target_guard=None)`, `update_visibility`, `python_drafts_allowed`), `StudioSkillCatalogService` (`publish`, `update_visibility`, …); test fake `InMemoryStudioRepositories` (`storage/testing.py`) | STORAGE W0 (records, errors), W1 (repositories, fake), W2 (services) | FEAT-605 (`StudioAccess`, handlers, tests) | Services validate data, never access. A plain `POST /agents` creates without a bundle. Every agent/draft write locks the row (`FOR UPDATE`) and applies the guard in one transaction; FEAT-605 passes the version its access decision was made on as `authorized_version`; `StudioStaleAuthorization` ⇒ re-read, re-authorise and retry once, then 409 `version_conflict`; the client `expected_version` is accepted only on the STORAGE §2.9 routes. Draft activation and `replace=true` are one transaction with atomic bundle replacement. The fake enforces the same uniqueness, CHECKs, version bump and guard, and raises the same signals |
| X7 | Registry key `StudioAgentKey(tenant, name).qualified` = `studio:<tenant\|->:<name>`; `BotManager.get_studio_bot(key, *, new=False, session_id="", request=None)`; `BotManager.studio` = `StudioAgentRuntime` (`get`, `get_session`, `use(key, *, session_id=None, request=None)`, `reload(key)`), whose instances live only in its private `StudioRuntimeCache`; on every Studio instance `bot._studio_key`, `bot._studio_version`, `bot._studio_agent_id`, `bot._tooling_ref` | STORAGE W2 | FEAT-605 (test/ask through `studio.use()` / `get_studio_bot`, reload, activation), TOOLKITS M5 (identifies a Studio bot by `_studio_key`), M9 (`agent_tooling_ref`) | Studio instances are never stored in `BotManager._bots` or `_botdef`. `get_bot(name, …)` returns `None` for any name starting with `studio:` or `studio-agent:` (with or without `new=True`) before touching `_bots`, `_botdef` or the registry; `add_bot` raises `ValueError` for an instance carrying `_studio_key`; `get_bots()`, `reload_agent` and the legacy cleanup paths never see a Studio instance. The only fallback: `get_bot(name)` with `new=False`, backend `database` and no installed resolver returns `studio.get(StudioAgentKey(None, name))` (GLOBAL only) without adding it to `_bots`. Tenant rows are unreachable by name (chat, A2A, scheduler: the P13 follow-up). Studio handlers that run a request on an instance hold a lease through `studio.use()`. Runtime memory identity: `chatbot_id = str(agent_id)` (X17) |
| X8 | Storage and runtime lifecycle hooks: `ensure_studio_storage(app)` (memoised probe; `resolve_studio_storage` is its `on_startup` wrapper, registered once by `setup_studio_routes`); `add_studio_runtime_hooks(app)` → `install_studio_runtime` (`on_startup`) + `shutdown_studio_runtime` (`on_cleanup`); `StudioAgentRuntime.start()` / `sweep(now=None)` / `shutdown()` / `use()`; `StudioRuntimeCache`; `cleanup_bot_instance(bot, *, label)` | STORAGE W1 (`ensure_studio_storage`), W2 (runtime, hooks) | `BotManager.setup()` (STORAGE M7), FEAT-605 W2.2 (`setup_registry_only` calls `add_studio_runtime_hooks`), host | `install_studio_runtime` awaits `ensure_studio_storage` **first**, so storage resolution precedes runtime construction whatever order the hooks were appended in; it installs `BotManager.studio` only when `app["studio_storage"].backend == "database"`; no eager load. `add_studio_runtime_hooks` appends each hook at most once per app. Studio expiry (session TTL, idle TTL, retirement grace), identity-based once-only cleanup, leases, in-flight retention and versioned asset directories are STORAGE's alone. FEAT-605's manager-level lifecycle in registry-only mode (`registry.setup`, the legacy `_cleanup_expired_bots` task, `_cleanup_all_bots`) applies to non-Studio bots only and never touches a Studio instance |
| X9 | `RequestScope(user_id, tenant, groups, is_superuser, may_author, may_administer, studio_enabled)`; `app["scope_resolver"]` (legacy `app["ui_surfaces_scope_resolver"]`); `get_scope_resolver(app)`; `has_installed_resolver(app)` | FEAT-605 W0.1 | STORAGE (duck-typed `.tenant` only), TOOLKITS M5 | "Opted-in host" := `has_installed_resolver(app)` |
| X10 | `setup_studio_routes(app, *, prefix=None, view_wrapper=None)`; `BotManager.setup(..., studio_routes=True)`; `BotManager.setup_registry_only(app)` | FEAT-605 W0.2 (routes, mount, manager-level lifecycle), W2.2 (`setup_registry_only` calls STORAGE `add_studio_runtime_hooks(app)`) | STORAGE (`setup_studio_routes` registers `resolve_studio_storage`), host | Idempotent per prefix; every hook (FEAT-467 `reconcile_skills_catalog`, STORAGE `resolve_studio_storage` and the X8 runtime hooks, FEAT-605's assistant clean-up) appended at most once per app, whatever the number of prefixes or calls. `setup_registry_only` registers no route, imports no `AGENTS_DIR` module or YAML definition, and is not recommended to tenant hosts until W2.2 has merged. Documented mount order: resolver → `setup_registry_only` → `setup_studio_routes`; the reverse order behaves the same (X8) |
| X11 | `RequestContext.kwargs["studio_scope"]` = `StudioToolScope(caller: RequestScope, agent: StudioAgentRef \| None)`, built only by `build_tool_scope(scope, agent=None)` in `handlers/studio/access.py`; `StudioAgentRef(agent_id, name, owner, tenant, visibility)` | FEAT-605 W2.1 (builder); binds at test/ask (W3.4) and the meta-agent (W3.5) | TOOLKITS (`ToolScopeView` / `CallerView` / `AgentScopeView` Protocols; binds at `chat.py`, execute and options in M5); STORAGE assistant tools (partition = `StudioPartition.from_scope(studio_scope.caller)`) | Nothing is bound without a resolver. For an addressed agent `agent.tenant == caller.tenant` |
| X12 | Routes: `PATCH /agents/{name}` (General fields) | STORAGE W3 (route, `StudioAgentPatch`, version bump) | FEAT-605 W3.1 (policy row) | Name immutable (422 `name_immutable`); legacy agent 409 `not_studio_agent`; `can_manage` inside the tenant + `may_author`; 404 first; tooling policy re-checked (X18) |
| X13 | Routes: `GET /me`; `PATCH /agents/{name}/visibility`, `/drafts/{name}/visibility`, `/skills/{id}/visibility` | FEAT-605 (W1.2, W3.1–W3.3, W4.1) | UI, host | Persist through the X6 `update_visibility` service methods, with a `StudioWriteGuard` |
| X14 | Error codes (code — HTTP status — owner) | STORAGE: `studio_storage_unavailable` 503; `version_conflict` 409; `expected_version_unsupported` 400; `unsupported_config_key` 422; `name_immutable` 422; `not_studio_agent` 409; `asset_too_large` 413; `agent_assets_quota` 413; `binary_assets_unsupported` 415. FEAT-605: `name_taken` 409 (raised from `StudioNameConflict`); `declarative_only` 422 (also STORAGE's tenant-path Python-draft refusal); `studio_disabled` 404; `tenant_mismatch` 403; `authoring_denied` 403; `reserved_config_key` 400; `tenant_required` 422; `groups_required` 422. TOOLKITS: `tooling_not_permitted` 422 on write, activation, attach and a refused build, 403 on execute (STORAGE maps `StudioToolingRefused` to it); `confirmation_required` 403 on execute; `server_managed` 422 (a client-supplied server-managed key on PUT, `/me`, assign or the execute body, or a server dependency the endpoint cannot supply); `tool_scope_unavailable` 403 on execute and options | all three | One owner, one code and one HTTP status per condition across the package; no spec defines a synonym. Inside an agent run, TOOLKITS refusals are a `ToolResult` (`status` `error`/`forbidden`) carrying the same `metadata.error_code`. `ScopeRefusal` and `ToolingRefusal` values (e.g. the scope reason `tenant_mismatch`) travel in `details.reason` / `metadata.reason` and are never top-level codes |
| X15 | `get_toolkit_resolver()` / `ToolkitResolver`; `server_managed_params`, `ServerParam`; `tenant_bound`; `TenantToolingPolicy`, `enforce_tenant_tooling(app, tooling, *, subject)`, `get_tenant_tooling_policy(app)`; the build hook `apply_tooling_specs(*, tooling_policy=, tooling_subject=)` with `AbstractBot.bind_tooling_policy(policy, subject)`; `ensure_tool_scope(cls)`; STORAGE `StudioToolingGate` (calls TOOLKITS) | TOOLKITS Wave 1 (M1, M3a, M7 core incl. the build hook and `bind_tooling_policy`), Wave 3 (M4); STORAGE W2 (`StudioToolingGate`) | STORAGE (`StudioToolingGate.enforce` on every write and activation; `StudioAgentBuilder` runs the gate with `phase="build"`, then `bot.bind_tooling_policy(get_tenant_tooling_policy(app), ToolingSubject(part.tenant, agent_id, None, "build"))` before `configure()`, whose existing `apply_tooling_specs()` call picks the binding up; `StudioToolingService` reuses the refusal of server-managed keys) | Storage-agnostic: resolver, policy and refusals work on either backend. `bind_tooling_policy` is valid only before tooling is applied (else `RuntimeError`); a bound tenant subject without a policy behaves as `deny_all()` |
| X16 | Merge order and release gate | — | all three | **No sibling dependency** (early): FEAT-605 W0.1–W0.3 and W1.1–W1.5 (its whole early subset), TOOLKITS Wave 1, STORAGE W0 and W1. **Before STORAGE W3**: FEAT-605 W1.3 (`testing.py` execute, `skills_catalog.py` resync), W1.4 and W1.5 (`drafts.py`) merge first and STORAGE W3 rebases on them (its `_legacy_*` bodies carry the D1/D3 guards); these are the only exceptions to the per-file rule. **Identity files**: STORAGE W1 "Tooling identity plumbing" (M13) merges **first** on `studio/tooling_store.py`, `studio/toolkit_overrides.py`, `handlers/toolkit_persistence.py` and `handlers/agent.py`; TOOLKITS M9 (R3 consumer) follows on every one of them: on `toolkit_persistence.py` and `agent.py` M9 makes no edit (M13 owns the key plumbing; M9 only tests it, and P2 M12 later edits `toolkit_persistence.py` after M9), on `tooling_store.py` and `toolkit_overrides.py` it merges after STORAGE W3 like every other TOOLKITS edit there. **Per-file rule**: every other FEAT-605 or TOOLKITS task that edits a Studio handler file also edited by STORAGE W2/W3 (`agents.py`, `drafts.py`, `skills_catalog.py`, `files.py`, `testing.py`, `tooling_store.py`, `toolkit_config.py`, `toolkits.py`, `toolkit_overrides.py`, `meta_agent.py`, core `bots/studio/tools.py`) merges **after** the STORAGE task for that file and rebases on it. `studio/_base.py`, `studio/__init__.py` and `manager/manager.py` (STORAGE W1/W2; FEAT-605 W0.2, W1.1, W2.1, W2.2, W3.6) carry small non-overlapping edits: serialise, whichever merges first, except that FEAT-605 W2.2 needs STORAGE W2 (runtime + hooks). Core `interfaces/tools.py`: TOOLKITS M7 core (Wave 1) before STORAGE W2 (builder), then TOOLKITS M2/M4 serialise. **Cross-spec waits**: FEAT-605 W2.1 needs STORAGE W0 + W1; STORAGE W2 services need TOOLKITS Wave 1 (M7 core); TOOLKITS Wave 2 lands M6 together with M8 (no build resolves host write tools without M8); TOOLKITS Wave 4 (M3b + M5) needs FEAT-605 W2.1 (`build_tool_scope`) and STORAGE W2 (runtime identity), and W3.4/W3.5 for the asserted bindings; FEAT-605 W3.6 (assistant partitioning) needs W3.5 and STORAGE W3 "Assistant tools on services" (`meta_agent.py`). **Release gate**: no release is called, documented or enabled as tenant-ready until every spec's gate is met — FEAT-605 §3 "Release gate" (through W4.3, incl. W2.2 and W3.6), STORAGE W0–W4 (W4 = shape snapshot + host guide), TOOLKITS Waves 1–4 (§9 there). Early subsets (FEAT-605's, TOOLKITS discovery, STORAGE on plain hosts) never ship as tenant-ready; tenant hosts keep `studio_enabled=False` until the gate is met |
| X17 | Identity scheme: `agent_id` (immutable uuid, never reused); tooling ref `studio-agent:<agent_id>` (`StudioAgentRecord.tooling_ref`, `bot._tooling_ref`, core `agent_tooling_ref(bot)`); vault names `toolkit_<slug>_studio-agent:<uuid>` (`toolkit_vault_name(slug, ref)`), `mcp_agent_<server>_studio-agent:<uuid>` (`mcp_vault_name(server, ref)`), `toolkit_<slug>_studio-agent:<uuid>_user` (`toolkit_override_vault_name(slug, ref)`); override document key `{user_id, agent_id: <ref>, slug}`; session keys `<ref>_toolkit_overrides_rev`, `<ref>_tool_manager`; runtime `chatbot_id = str(agent_id)`; registry key `studio:<tenant\|->:<name>`; the Studio assistant's `chatbot_id = "agent_studio:<tenant\|->"` | STORAGE W0 (M2 records, M10 core helpers), W1 (M13 plumbing), W2 (builder stamps `chatbot_id`, `_tooling_ref`, `_studio_agent_id`); FEAT-605 W3.6 (assistant identity) | TOOLKITS (M5, M7 build-time namespace check, M9), FEAT-605 (test chat, assistant, AC25) | Legacy agents keep their bare-name identities byte for byte (`agent_tooling_ref(bot) == bot.name`). `:` never occurs in a Studio or legacy slug, so a ref never equals a legacy name. Every key read or write receives the ref from the partitioned lookup, never from the URL name. Delete + recreate yields a new `agent_id`: no credential, override, memory or cache is inherited. The registry key is used only inside `StudioRuntimeCache` and test-session keys; it never names a vault entry, an override or a memory. The assistant is not a Studio agent: FEAT-605 partitions it by `(tenant or "-", user_id)` and passes explicit `user_id` / `session_id` to `ask` |
| X18 | Policy, enforcement and confirmation: `TenantToolingPolicy` (default `deny_all()`), `set_tenant_tooling_policy(app, policy)` (once, before startup), `get_tenant_tooling_policy(app)`, `enforce_tenant_tooling(app, tooling, *, subject)`, `ToolingSubject(tenant, agent_id, actor, phase)`; `require_tool_scope` / `ensure_tool_scope` and the automatic gate in `AbstractTool.execute` and the wrapped `config_options`; the approval token set only by `ToolManager` after a `ConfirmationGuard` `confirmed` decision; `app["studio_confirmation_guard"]` | TOOLKITS Wave 1 (M7 core, M3a), Wave 2 (M6 + M8, M7 wiring), Wave 4 (M3b, M5) | STORAGE (`StudioToolingGate` on every write, activation and build; the builder binds the policy and installs `app["studio_confirmation_guard"]` on the bot's `ToolManager` when present), FEAT-605 (route rows C35/C36: tooling writes, activation, test/ask, execute, options, meta-agent writing tools) | Applies when `subject.tenant is not None` (GLOBAL only with `apply_to_global`). Evaluated on the **final normalised** configuration (the `params` overlay and vault fields included) before any row, vault write, process start or connection; tenant-supplied local execution (stdio/unix, `command`/`args`/`env`/`socket_path`) is denied by default; client- or bundle-supplied `secret_refs`/`vault_owner` are refused; at build every vault name must be the ref-derived name of X17. Tenant-bound tools and options providers refuse a missing or mismatched scope before any side effect. A `confirmation_enforced` host write runs only with a matching approval token: no guard, no channel or direct execute ⇒ zero writes. Codes: X14 |

---

## 8. Open Questions and resolved requirements

### Product questions (for Jesus / Juan)

- [x] **Q1 — `filesystem` backend lifetime.** **Decided 2026-09-30 (Juan, with Jesus's go-ahead; revisit in PR #1524 if needed): recommendation adopted.** Keep it as deprecated, non-tenant only, for one minor release, then remove it along with the legacy-agent migration follow-up? *Recommendation: yes; remove in the release that ships the legacy migration.* — *Owner: Jesus*
- [x] **Q2 — Live edits vs explicit reload.** **Decided 2026-09-30 (Juan, with Jesus's go-ahead; revisit in PR #1524 if needed): recommendation adopted.** DB mode applies asset/tooling edits on the next lookup (no reload gate). Accept for v1, or add a published/working split (`published_version`)? *Recommendation: accept; the split is a later feature if authors ask for staging.* — *Owner: Jesus*
- [x] **Q3 — Catalogue search in tenant mode.** **Decided 2026-09-30 (Juan, with Jesus's go-ahead; revisit in PR #1524 if needed): recommendation adopted.** Keep the embedding `SkillRegistry` as a per-pod derived index, or use SQL search only in database mode? *Recommendation: keep it derived and rebuildable; fall back to SQL `ILIKE` when the index is flagged stale.* — *Owner: Jesus*
- [x] **Q4 — BYOK key scope.** **Decided 2026-09-30 (Juan, with Jesus's go-ahead; revisit in PR #1524 if needed): recommendation adopted.** Per user (all tenants) or per (user, tenant)? *Recommendation: per user; it is the user's own provider key. A tenant column can be added later without breaking the PK contract if a host needs it.* — *Owner: Jesus + Juan*
- [x] **Q8 — Where the console script lives.** **Decided 2026-09-30 (Juan, with Jesus's go-ahead; revisit in PR #1524 if needed): recommendation adopted.** `parrot-studio-migrate` in ai-parrot-server, or a `parrot studio migrate` subcommand of the core `parrot` CLI? *Recommendation: ai-parrot-server script, because the SQL ships in that wheel and core must not import server code.* — *Owner: Jesus*
- [x] **Q9 — Bare-name fallback in `get_bot` for tenant-NULL Studio rows.** **Decided 2026-09-30 (Juan, with Jesus's go-ahead; revisit in PR #1524 if needed): recommendation adopted.** Acceptable as the only lookup change to `get_bot` besides the `studio:`/`studio-agent:` refusal (§2.7)? *Recommendation: yes; it keeps `/api/v1/chat/<name>` working for plain hosts, cannot reach tenant rows, and never places the instance in `_bots`.* — *Owner: Jesus*
- [x] **Q10 — Python drafts default on plain hosts.** **Decided 2026-09-30 (Juan, with Jesus's go-ahead; revisit in PR #1524 if needed): recommendation adopted.** Keep `STUDIO_PYTHON_DRAFTS=true` by default? *Recommendation: yes for compatibility, with a deprecation note; the tenant path refuses them regardless.* — *Owner: Jesus*
- [x] **Q11 — Grace period for lease-less callers.** **Deferred 2026-09-30 — non-blocking follow-up:** keep the grace period in v1; leasing the chat path ships with the P13 runtime follow-up. Is `STUDIO_RETIRE_GRACE_SECONDS=300` enough for the GLOBAL `get_bot` fallback (public chat on plain hosts), or should that path take a lease too (a small change in the chat handler)? *Recommendation: keep the grace in v1; lease the chat path with the P13 follow-up.* — *Owner: Jesus*

### Resolved correctness requirements (not open)

These are fixed in the sections cited; they are not up for decision.

- [x] **Q5 — Toolkit secrets off DocumentDB.** *Resolved in v0.2 (R-package):* committed as phase-2 module M12 (§2.10): `navigator.ai_user_credentials` and `navigator.ai_user_toolkit_overrides` behind `VAULT_STORE` / `TOOLKIT_OVERRIDES_STORE`, same AAD, copy script. Tenant-safe identities are **not** phase 2: they ship in v1 (§2.5c).
- [x] **Q6 — Literal `navigator` vs `PARROT_SCHEMA`.** *Resolved in v0.2 (R9):* literal `navigator`. The v0.1 recommendation ("a host with a different schema sets `search_path`") was wrong: every statement is schema-qualified, and `search_path` never redirects a qualified name. A host that needs another schema is unsupported in v1; supporting it would need templated migrations and is a separate change.
- [x] **Q7 — Minimum Postgres version.** *Resolved in v0.2 (R9):* PostgreSQL 14 or later, enforced by the probe and the CLI (§2.12); PG13 is past upstream end of life.
- [x] **R-P1 — Build-hook plumbing** (was unspecified in v0.2 §2.7). The builder binds TOOLKITS' policy on the instance with `bot.bind_tooling_policy(...)` before `configure()`, whose no-argument `apply_tooling_specs()` call reads it (§2.5b, §2.7 step 4; TOOLKITS §2 "Build-hook plumbing").
- [x] **R-P2 — Identity scheme and merge order.** `studio-agent:<agent_id>` for every per-agent key in v1 (§2.5c, X17); M13 (W1) merges first on its four files, before TOOLKITS M9 (X16).
- [x] **R-P3 — Lifecycle ownership.** Studio expiry, cleanup, leases and the runtime hooks are this spec's; FEAT-605's `setup_registry_only` only calls `add_studio_runtime_hooks` (§2.7a, X8, X10).

---

## 9. Design Research Cross-Check

Status: **skipped**. This spec was drafted from decisions already taken by the host owner
(command board D1–D7) as part of a three-spec package, then corrected after the owner's
review (R1–R10, 2026-09-30). A neutral `codex` design cross-check over the corrected package
is recommended before `/sdd-task`, with §2.5a (locking/guard), §2.7 (separate cache) and
§2.7a (lifecycle) as the review questions.

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
| 0.2 | 2026-09-30 | Juan Ruffato (with Claude) | Corrections after Jesus's review. **R1**: host-owned `TenantToolingPolicy` (TOOLKITS) applied through `StudioToolingGate` to the final normalised tooling on every write (create/bundle, PATCH, assets, catalogue import, toolkit PUT/DELETE, MCP PUT, draft save/activate) and every build; `definition.tools` included; `transport`/`command` inside `params` covered (§2.5b, G10, tests, AC). **R2**: Studio instances moved out of `BotManager._bots` into `StudioRuntimeCache`; `get_bot` refuses `studio:`/`studio-agent:` names, `add_bot` refuses Studio instances, only the GLOBAL `new=False` fallback remains; warm-cache regression test (§2.7, G4, M7). **R3**: immutable `agent_id` identity in v1 — `tooling_ref = "studio-agent:<agent_id>"` for agent/MCP/override vault names, override document keys and session revision caches; legacy bare names unchanged; delete/recreate inherits nothing; new M13 (§2.5c, §2.8). **R4 (storage side)**: `chatbot_id = str(agent_id)` so memory is partitioned; assistant session partitioning left to FEAT-605 (§2.5c, §2.7). **R5**: explicit definition→constructor map (prompt, `llm` + `model_config` precedence with `BotConfig.model` always `None`, identity assets, owner, `chatbot_id`, tools, MCP specs dumped to the `List[Dict]` shape); `StudioAgentDefinition` gains `model_params`, `system_prompt`, `tools`; tenant `config` allowlist (§2.4, §2.7). **R8 (storage side)**: minimal lifecycle — own sweep with enforced session/idle expiry, shutdown clean-up, identity-based per-instance clean-up (`cleanup_bot_instance`), `ensure_studio_storage` before runtime construction, leases + retirement grace + ref-counted versioned asset dirs; hooks `add_studio_runtime_hooks`/`install_studio_runtime`/`shutdown_studio_runtime` for FEAT-605's mount (§2.7a). **R9**: final executable DDL for 0001–0005 (no placeholders), checksum over the file body with a non-hashed ledger trailer plus `MANIFEST.json`, required-version completeness (incomplete/drifted ⇒ `unavailable`), catalogue visibility/tenant/`tenant IS NULL ⇒ private` CHECKs and draft tenant CHECK, PostgreSQL ≥ 14, advisory-lock concurrent-runner behaviour, Q6/Q7 corrected (§2.2, §2.3, §2.12). **R10**: `create` takes name/visibility/groups and no bundle; `get_version` returns `StudioAgentHead` (with status); `expected_version` narrowed to listed routes (400 `expected_version_unsupported` elsewhere); `StudioWriteGuard` with row locks (`FOR UPDATE`) and a stale-authorisation retry; atomic draft activation and bundle replacement; one-statement runtime snapshot; the verified asyncdb `transaction()`/`commit()`/`rollback()` API and its error-tuple `execute` (§2.5, §2.5a). **Package**: phase 2 settled as committed modules M11 + M12 (BYOK, vault credentials, per-user overrides off DocumentDB; Q5 closed); D1/D3 plain-host draft fixes stated as independent of this conversion (§1 non-goals, §7). Cross-spec contract section left unchanged for the reconciliation pass. |
| 0.2.1 | 2026-09-30 | Juan Ruffato (with Claude) | **Package reconciliation** (this spec's names win for identity, runtime and schema; TOOLKITS' for policy plumbing): the builder now binds the tenant tooling policy with TOOLKITS' `bot.bind_tooling_policy(...)` before an unchanged `configure()` and installs `app["studio_confirmation_guard"]` when present (§2.5b, §2.7 step 4; the plumbing gap flagged in v0.2 is specified in TOOLKITS §2 "Build-hook plumbing"); §2.5c states the assistant's separate identity (`chatbot_id = "agent_studio:<tenant\|->"`, explicit `user_id`/`session_id`, FEAT-605) next to the runtime `chatbot_id = str(agent_id)`; M13 marked merge-first on `tooling_store.py`, `toolkit_overrides.py`, `toolkit_persistence.py` and `handlers/agent.py` ahead of TOOLKITS M9; the runtime task depends on TOOLKITS Wave 1 (M7 core); FEAT-605's early subset named exactly (W0.1–W0.3, W1.1–W1.5) instead of "Waves 0–1"; §8 split into product questions and resolved correctness requirements (R-P1–R-P3 added); "Cross-spec contract (package)" rewritten (identical in the three specs, new rows X17 identity and X18 policy/enforcement/confirmation) |
| 0.2.2 | 2026-09-30 | Juan Ruffato (with Claude) | Adversarial-review follow-ups: one build-refusal rule (policy refusal fails the build closed with `tooling_not_permitted`; only unresolvable toolkits are skipped); `duplicate` marked as pre-merge state only; asyncdb-vs-raw-asyncpg transaction note + executable fixture test; lock-order rule. |
