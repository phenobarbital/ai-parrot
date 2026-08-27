---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Agent Studio — Management API

**Feature ID**: FEAT-467
**Date**: 2026-08-27
**Author**: Jesus Lara
**Status**: approved
**Target version**: ai-parrot-server 0.28.x / ai-parrot 0.29.x (next minor)
**Brainstorm**: `sdd/proposals/agentstudio-management.brainstorm.md` (Option A)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

AI-Parrot has grown many agent-facing capabilities — skills, identity files,
KB files, tools/toolkits, vector stores, MCP servers, scheduler entries,
ephemeral agents, an agent factory — but each shipped as a **separate HTTP
surface** wired at different times by different features. A domain owner who
wants to "create an agent, give it skills and a KB, attach a toolkit, test
it, and schedule it" today has to stitch together at least eight unrelated
endpoints (`/api/v1/bots`, `/api/v1/agents/config`, `/api/v1/agents/test/*`,
`/api/v1/agents/factory`, `/api/v1/tools/catalog`, `/api/v1/ai/stores`,
`/api/v1/parrot/scheduler/*`, `/api/v1/users/credentials`) — none of which
share a lifecycle model, and several of which have no way to reload a
running agent after its files change.

**Agent Studio** is the control plane that unifies these into one coherent
backend API — routed under **`/api/v1/astudio/*`** — for building, testing,
and monitoring agents. It supersedes the current Bot Management handler as
the recommended surface without deprecating it.

### Goals

- One authenticated, ownership-aware namespace `/api/v1/astudio/*` covering
  the full agent-building loop: create → configure assets → assign
  tools/toolkits/stores → test → schedule.
- Simple agent creation registered into `AgentRegistry`, optionally
  persisted as an `agent:`-keyed YAML definition under
  `AGENTS_DIR/agents/<category>/`.
- A **draft → validate → activate** pipeline for LLM-generated Python
  agents: generated code never goes live without an explicit user action.
- **Hot reload** of a registered agent (identity/skills/kb/YAML changes take
  effect without a server restart, swapping the shared registry instance).
- The **AgentStudio meta-agent** (Anthropic `claude-opus-5`, config
  `STUDIO_AGENT_MODEL`) that scaffolds Python/YAML agents, skill files, and
  KB files from natural language — absorbing `AgentFactoryHandler`.
- **Shared skills catalog**: org-wide re-usable skills, listed ordered by
  category and filterable by owner, backed by the extended `SkillRegistry`
  plus a new Postgres table.
- **BYOK**: per-user LLM API keys persisted encrypted in the existing
  navigator-session vault, resolved via a new `CredentialBroker` resolver
  at client-build time for agent testing.
- Scheduler management completed with **run-now** and last-execution-result.
- Helper catalogs for the future UI: base classes, LLM clients, tools,
  vector stores, toolkit configuration schemas.
- Fix `AgentRegistry.create_agent_definition` so the YAML round-trip is
  lossless (currently drops `toolkits`, `prompt`, `vector_store`, `tags`,
  `policies`, `mcp_servers`, `priority`, `at_startup`, `config`).

### Non-Goals (explicitly out of scope)

- The interactive UI frontend — separate later spec consuming this API.
- Deprecating or changing behavior of existing surfaces (`/api/v1/bots`,
  `/api/v1/bot_management`, `/api/v1/agents/config`, …). No deprecation
  headers or logs are emitted (resolved in brainstorm: leave silent).
- A parallel `StudioManager` system-of-record beside
  `AgentRegistry`/`BotModel` (brainstorm Option B — rejected: standing
  desync risk).
- An MCP-server control plane (brainstorm Option D — deferred follow-up).
- Migrating existing agents to Studio ownership; existing agents keep
  their current lifecycle.
- Agent sharing between users (scaffold `handlers/agents/sharing.py`
  remains deferred to its own FEAT).

---

## 2. Architectural Design

### Overview

**Studio Facade** (brainstorm Option A): a new `handlers/studio/` package in
`ai-parrot-server` exposing the `/api/v1/astudio/*` namespace. Handlers are
deliberately thin — they validate payloads (Pydantic), resolve the session
user, enforce ownership/PBAC, and delegate to the components that already
own the behavior: `BotManager`, `AgentRegistry`, `AgentSchedulerManager`,
the tool discovery layer, `LLMFactory`, the skills registry, and the
navigator-session credentials vault. New capability code is written only
where nothing exists today:

- registry/manager primitives: `AgentRegistry.unregister()`, lossless
  `create_agent_definition`, `BotManager.reload_agent()`;
- the draft/activate pipeline (filesystem code + `navigator.studio_drafts`
  state table);
- asset-file CRUD for `AGENTS_DIR/<agent>/{identity,kb,skills}/`;
- the shared skills catalog (extended `SkillRegistry` + new
  `navigator.ai_skills_catalog` table);
- the BYOK resolver and key endpoints;
- scheduler `run_now`;
- toolkit config-schema introspection;
- the AgentStudio meta-agent (absorbing `AgentFactoryHandler`).

**Route prefix is `/api/v1/astudio/`** — NOT `/studio/` — because another
installed service already occupies "studio"-style routes on the same
deployment. Internal code naming (`handlers/studio/`, `AgentStudio*`
classes) is unaffected.

All Studio views are decorated `@is_authenticated()` / `@user_session()`
(navigator-auth), extend `navigator.views.BaseView` (CBV) or use
`BaseHandler`-style bare GET helpers for catalogs, and are registered inside
`BotManager.setup(app)` alongside the existing ~55 routes. PBAC resource ids
are namespaced `astudio:<area>` (`astudio:agents`, `astudio:skills`,
`astudio:keys`, …); superuser/admin bypasses ownership; the evaluator is
fail-open when no PDP is configured, but session-derived ownership is still
enforced (same posture as `_PBACHandlerMixin`).

Key resolved behaviors (from brainstorm — authoritative):

- **Draft safety gate**: generated `.py` saved to `AGENTS_DIR/_drafts/`;
  static validation (AST parse, import allowlist, exactly one `AbstractBot`
  subclass) runs on save; the module is imported and registered **only** on
  explicit `POST .../activate`. Lifecycle state/audit lives in
  `navigator.studio_drafts`.
- **Reload swaps the shared registered agent**: all consumers get the new
  behavior immediately; in-flight requests finish on the old instance; old
  singletons get best-effort `cleanup()`/`close()`.
- **Canonical YAML** is the `agent:`-keyed definition format read by
  `AgentRegistry.load_agent_definitions` (the per-agent-directory
  `config.yaml` seen in `agents/navigator/` is NOT a loaded format).
- **Meta-agent** defaults to `AnthropicClient` with `claude-opus-5`,
  overridable via new config setting `STUDIO_AGENT_MODEL` (parrot/conf.py);
  it reuses the `parrot/bots/factory/` builders and HITL finalize machinery;
  `/api/v1/agents/factory` remains routable as a thin alias.
- **BYOK**: keys AES-GCM-encrypted with the navigator-session vault master
  keys (NOT Fernet — Fernet does not exist in this codebase), hot copy in
  the Redis session vault, durable copy in DocumentDB (CredentialsHandler
  pattern); a new `CredentialBroker` resolver exposes them; test-run client
  construction passes the resolved key as `api_key` to `LLMFactory.create`.
  Keys are never returned in plaintext.
- **Skills catalog storage**: dual-write, PG-first. The extended
  `SkillRegistry` (shared org namespace, e.g. `"<org_id>/_shared"`, new
  `owner_user_id` field on `Skill`) keeps embedding search + git-like
  versioning; `navigator.ai_skills_catalog` is the durable record and SQL
  query plane (`ORDER BY category`, `WHERE owner`). Categories constrained
  to the `SkillCategory` enum; out-of-vocabulary → `general`. Drift repaired
  by a startup reconciliation pass + admin
  `POST /api/v1/astudio/skills/resync`.
- **Wiki surface assignment**: reuse the bot's captured
  `_pageindex_toolkit`/`_graphindex_toolkit` when present; otherwise
  construct fresh instances from the submitted `WikiConfig`
  (`storage_dir` = the directory where the LLM wiki starts).

#### Endpoint map (summary)

| Area | Method + Route (under `/api/v1`) | Behavior |
|---|---|---|
| Agents | `POST /astudio/agents` | create simple agent (registry; `persist: true` → YAML definition) |
| Agents | `GET /astudio/agents[/{name}]` | list/read (registry + DB merged view) |
| Agents | `POST /astudio/agents/{name}/reload` | hot reload — swap shared instance |
| Agents | `DELETE /astudio/agents/{name}` | delete (factory-origin YAML agents; DB agents delegated) |
| Drafts | `GET /astudio/drafts[/{name}]` | list / read draft + validation report |
| Drafts | `POST /astudio/drafts` | save generated `.py` draft (validation runs) |
| Drafts | `POST /astudio/drafts/{name}/activate` | import + register (only path to live code) |
| Assistant | `POST /astudio/assistant` | converse with the AgentStudio meta-agent |
| Files | `GET/PUT/DELETE /astudio/agents/{name}/files/{kind}/{filename}` | `kind ∈ {identity, kb, skills}` CRUD |
| Testing | `POST /astudio/agents/{name}/test/ask` | LLM-path test (session test instance) |
| Testing | `POST /astudio/tools/{slug}/execute` | deterministic `tool.execute(**kwargs)` |
| Testing | `POST /astudio/agents/{name}/tools` | assign tool/toolkit to agent (`tool_manager`) |
| Toolkits | `GET /astudio/toolkits/{slug}/schema` | config schema (LLMWiki/DatasetManager/Infographic first) |
| Toolkits | `POST /astudio/agents/{name}/toolkits` | assign configured toolkit |
| Skills catalog | `GET /astudio/skills?category=&owner=` | org-wide list, ordered/grouped by category |
| Skills catalog | `POST /astudio/skills` | publish skill (owner = session user) |
| Skills catalog | `GET/PUT/DELETE /astudio/skills/{id}` | read / owner-or-admin mutate |
| Skills catalog | `POST /astudio/agents/{name}/skills/import/{id}` | copy into agent `skills/` dir |
| Skills catalog | `POST /astudio/skills/resync` | admin: PG → registry reconciliation |
| BYOK | `GET/POST /astudio/keys`, `DELETE /astudio/keys/{provider}` | masked list / store / remove |
| Catalogs | `GET /astudio/catalog/base-classes` | agent base classes + configurable attrs |
| Catalogs | `GET /astudio/catalog/llm-clients` | from `SUPPORTED_CLIENTS` |
| Catalogs | `GET /astudio/catalog/tools` | reuse `_build_catalog()` |
| Catalogs | `GET /astudio/catalog/vector-stores` | from stores dispatch/`VectorStoreHelper` |
| Scheduler | `PATCH /parrot/scheduler/schedules/{id}` `action="run_now"` | immediate trigger (existing handler, new action) |
| Scheduler | `GET .../schedules/{id}/last-result` | last execution result |
| Vector stores | (reuse `POST/PUT/PATCH /api/v1/ai/stores`) | create/upload/test — Studio adds agent-assignment only |

### Component Diagram

```
                 /api/v1/astudio/*  (BotManager.setup registers routes)
                        │
   ┌────────────────────┼───────────────────────────────────────────┐
   │      handlers/studio/  (thin CBVs — auth + ownership + PBAC)   │
   │  agents.py  drafts.py  files.py  testing.py  toolkits.py       │
   │  skills_catalog.py  byok.py  catalog.py  meta_agent.py         │
   └──┬───────┬─────────┬─────────┬──────────┬──────────┬───────────┘
      │       │         │         │          │          │
      ▼       ▼         ▼         ▼          ▼          ▼
 BotManager AgentRegistry AGENTS_DIR   ToolManager  SkillRegistry  vault
 .reload_agent .unregister  identity/  .register_   (+_shared ns,  (navigator_
 (NEW)        (NEW)         kb/ skills/ toolkit     owner_user_id) session
      │       │  create_agent_ _drafts/      │        │    │        AES-GCM)
      │       │  definition    │             │        │    ▼        │
      │       │  (round-trip   ▼             │        │  navigator. ▼
      │       │   FIX)   navigator.          │        │  ai_skills_ CredentialBroker
      │       │          studio_drafts (NEW) │        │  catalog    resolver (NEW)
      ▼       ▼                              ▼        ▼  (NEW)      │
   existing: AgentSchedulerManager(run_now NEW) · LLMFactory(api_key)┘
   VectorStoreHandler · ToolCatalogHandler · factory builders (meta-agent)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BotManager` (`manager/manager.py`) | extends | new `reload_agent(name)`; Studio routes registered in `setup()`; `app['bot_manager']` access pattern |
| `AgentRegistry` (`registry/registry.py`) | modifies | new `unregister(name)`; lossless `create_agent_definition`; reload-safe re-registration; `_import_module_from_path` reused for activation |
| `ChatbotHandler` (`handlers/bots.py`) | reuses logic | slugify/dedup, server-set `created_by`, `_provision_vector_store` — untouched, patterns reused |
| `BotConfigTestHandler` (`handlers/testing_handler.py`) | reuses pattern | session-based test-instance semantics for `test/ask` |
| `AgentFactoryHandler` + `parrot/bots/factory/` | absorbs | meta-agent reuses builders + HITL `finalize_agent_registration`; `/api/v1/agents/factory` becomes thin alias |
| `SchedulerJobsHandler` + `AgentSchedulerManager` | extends | `run_now` PATCH action + last-result endpoint |
| `VectorStoreHandler` (`handlers/stores/`) | uses | create/upload/search reused as-is; Studio only updates agent `vector_store_config` + reload |
| `ToolCatalogHandler` / `tools/discovery.py` | uses | `/catalog/tools` reuses `_build_catalog()` / `discover_all()` |
| `CredentialsHandler` pattern (`handlers/credentials.py`) | reuses pattern | BYOK sibling handler: session vault + DocumentDB, AES-GCM helpers |
| `CredentialBroker` (`parrot/auth/broker.py`) | extends | new user-LLM-key resolver type |
| `LLMFactory` (`clients/factory.py`) | uses | `SUPPORTED_CLIENTS` catalog; `api_key` kwarg pass-through on test runs |
| `SkillRegistry` (`skills/store.py`) + `skills/models.py` | modifies | shared org namespace, `owner_user_id` on `Skill`, PG persistence hooks |
| `parse_skill_file` / `SkillFileRegistry` (`skills/`) | uses | frontmatter validation on file CRUD + catalog publish/import |
| `IdentityMixin` / `load_identity` (`bots/`) | uses | identity file contract (5 canonical files); existing hot-reload seam |
| `LLMWikiToolkit` + `WikiConfig` (`knowledge/wiki/`) | uses | wiki surface assignment; deps reuse-else-build |
| `DatasetManager`, `InfographicToolkit` (core `tools/`) | uses | config-schema introspection; `artifact_store` wired from `app['artifact_store']` |
| PBAC (`app['abac']`, `_PBACHandlerMixin` pattern) | uses | `astudio:<area>` resource ids; admin bypass; fail-open w/o PDP |
| `parrot/conf.py` | extends | new `STUDIO_AGENT_MODEL` setting |

### Data Models

```python
# NEW asyncdb Models (pattern: scheduler/models.py AgentSchedule — driver 'pg')

class StudioDraft(Model):
    """navigator.studio_drafts — lifecycle state/audit for generated agents.

    Draft .py content stays on disk at AGENTS_DIR/_drafts/<name>.py;
    this table holds state only."""
    draft_id: uuid (PK)
    name: str                      # slug, unique among drafts
    file_path: str                 # AGENTS_DIR/_drafts/<name>.py
    status: str                    # draft | validated | failed | activated
    validation_report: dict (JSONB)  # AST/import/subclass findings
    base_class: str                # detected AbstractBot subclass base
    owner_user_id: str
    created_at / updated_at / activated_at: datetime

class SkillCatalogEntry(Model):
    """navigator.ai_skills_catalog — durable record + SQL query plane."""
    skill_id: uuid (PK)            # mirrors SkillRegistry skill_id
    name: str (unique)
    description: str
    category: str                  # constrained to SkillCategory enum values
    owner: str                     # owning USER (the new filterable column)
    triggers: list (JSONB)
    body: str                      # skill markdown incl. frontmatter
    version: int
    status: str                    # SkillStatus values
    search_index_stale: bool       # set when registry dual-write failed
    created_at / updated_at: datetime

# Pydantic request/response models (handlers/studio/models.py) — examples:
class CreateAgentRequest(BaseModel):
    name: str; bot_class: str = "BasicBot"; llm: str | None = None
    description: str | None = None; persist: bool = False
    category: str = "general"; config: dict = {}
class ReloadResult(BaseModel):
    name: str; reloaded: bool; previous_instance_closed: bool; warnings: list[str]
class DraftValidationReport(BaseModel):
    passed: bool; errors: list[dict]  # {line, code, message}
class SkillPublishRequest(BaseModel):
    name: str; description: str; category: SkillCategory
    triggers: list[str] = []; body: str
class ByokKeyRequest(BaseModel):
    provider: str                  # validated against SUPPORTED_CLIENTS
    api_key: SecretStr
```

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/registry/registry.py  (additions)
class AgentRegistry:
    def unregister(self, name: str) -> bool:
        """Remove one agent from the registry (metadata + cached instance)."""
    # create_agent_definition(...) — same signature, now round-trips the
    # FULL BotConfig (toolkits, prompt, vector_store, tags, policies,
    # mcp_servers, priority, at_startup, config)

# packages/ai-parrot-server/src/parrot/manager/manager.py  (addition)
class BotManager:
    async def reload_agent(self, name: str) -> "ReloadResult":
        """Rebuild agent from YAML/definition/DB; swap registry instance;
        best-effort close of the previous instance. Never leaves the name
        unregistered on failure."""

# packages/ai-parrot-server/src/parrot/handlers/studio/  (new package)
class StudioAgentsHandler(BaseView): ...      # agents.py
class StudioDraftsHandler(BaseView): ...      # drafts.py
class StudioFilesHandler(BaseView): ...       # files.py
class StudioTestingHandler(BaseView): ...     # testing.py
class StudioToolkitsHandler(BaseView): ...    # toolkits.py
class StudioSkillsCatalogHandler(BaseView): ...  # skills_catalog.py
class StudioKeysHandler(BaseView): ...        # byok.py
class StudioAssistantHandler(BaseView): ...   # meta_agent.py
def setup_studio_routes(app: web.Application) -> None: ...  # __init__.py
    # called from BotManager.setup()

# packages/ai-parrot/src/parrot/auth/broker.py  (addition)
class _UserLLMKeyResolver(CredentialResolver):
    """Resolves a per-user provider API key from the session/DB vault."""

# packages/ai-parrot/src/parrot/skills/store.py  (additions)
class SkillRegistry:
    # namespace convention "<org_id>/_shared" for the org-wide catalog
    # Skill gains owner_user_id: str = "" (skills/models.py)
```

---

## 3. Module Breakdown

> Modules map to Task Artifacts. M1 is TASK #1 by resolved decision.

### Module 1: Registry primitives + lossless YAML round-trip
- **Path**: `packages/ai-parrot/src/parrot/registry/registry.py` (+ tests)
- **Responsibility**: fix `create_agent_definition` to serialize the full
  `BotConfig`; add `unregister(name)`; make re-registration replace-safe
  (drop stale `BotMetadata._instance`). Round-trip test:
  `BotConfig → create_agent_definition → load_agent_definitions → BotConfig`.
- **Depends on**: none (FIRST task — every persist path depends on it).

### Module 2: `BotManager.reload_agent`
- **Path**: `packages/ai-parrot-server/src/parrot/manager/manager.py`
- **Responsibility**: rebuild-and-swap for YAML/definition, decorator, and
  DB-origin agents; evict `self._bots[name]`; best-effort old-instance
  cleanup; failure leaves the previous registration intact (422 upstream).
- **Depends on**: Module 1.

### Module 3: Studio package scaffold + routes + PBAC + shared models
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/studio/`
  (`__init__.py`, `models.py`, `_base.py`), `manager/manager.py` (route
  block), PBAC ids `astudio:<area>`.
- **Responsibility**: `setup_studio_routes(app)` called from
  `BotManager.setup`; shared `StudioBaseView` with session/owner/PBAC
  helpers (pattern: `_PBACHandlerMixin` + `@is_authenticated()`/
  `@user_session()`); Pydantic request/response models.
- **Depends on**: none (parallel to M1/M2).

### Module 4: Agent lifecycle endpoints
- **Path**: `handlers/studio/agents.py`
- **Responsibility**: create (registry + optional YAML persist via M1),
  list/read merged view (pattern `ChatbotHandler._get_all`), reload (M2),
  delete (`delete_factory_agent` / DB delegate); ownership recorded
  (`created_by` server-set).
- **Depends on**: Modules 1–3.

### Module 5: Draft pipeline
- **Path**: `handlers/studio/drafts.py`,
  `handlers/models/studio_drafts.py` (`StudioDraft` asyncdb model),
  `handlers/studio/validation.py` (AST checks)
- **Responsibility**: save/list/read drafts under `AGENTS_DIR/_drafts/`;
  static validation (AST parse, import allowlist `parrot.*`/
  `parrot_tools.*`/stdlib, exactly one `AbstractBot` subclass); state rows
  in `navigator.studio_drafts`; activate = move file into discovery path +
  `_import_module_from_path` + register + owner stamp.
- **Depends on**: Modules 1–3.

### Module 6: Asset file management
- **Path**: `handlers/studio/files.py`
- **Responsibility**: sandboxed CRUD for
  `AGENTS_DIR/<agent>/{identity,kb,skills}/`; identity restricted to the
  five canonical `IDENTITY_FILES`; skills validated with
  `parse_skill_file`; traversal-safe path resolution; `reload_required`
  flag in responses.
- **Depends on**: Module 3.

### Module 7: Shared skills catalog
- **Path**: `handlers/studio/skills_catalog.py`,
  `handlers/models/skills_catalog.py` (`SkillCatalogEntry`),
  `packages/ai-parrot/src/parrot/skills/store.py` + `skills/models.py`
  (shared namespace + `owner_user_id`)
- **Responsibility**: publish (PG-first dual-write), list ordered by
  category with `?category=&owner=` filters, read, owner/admin
  update/delete, import-into-agent (materialize into
  `AGENTS_DIR/<agent>/skills/`), startup reconciliation + admin `resync`.
- **Depends on**: Modules 3, 6 (import path).

### Module 8: BYOK keys + broker resolver
- **Path**: `handlers/studio/byok.py`,
  `packages/ai-parrot/src/parrot/auth/broker.py` (resolver)
- **Responsibility**: store/list(masked)/delete per-user provider keys
  (session vault hot copy + DocumentDB durable, `encrypt_credential`
  AES-GCM); `_UserLLMKeyResolver`; test-run client construction passes
  resolved key as `api_key` via `LLMFactory.create`.
- **Depends on**: Module 3.

### Module 9: Testing surface
- **Path**: `handlers/studio/testing.py`
- **Responsibility**: `test/ask` session test instances (pattern
  `BotConfigTestHandler`), deterministic `tool.execute(**kwargs)`,
  tool/toolkit assignment via `bot.tool_manager.register_toolkit(...)` /
  `register_tools(...)`; BYOK-aware (M8).
- **Depends on**: Modules 3, 8.

### Module 10: Toolkit config surfaces
- **Path**: `handlers/studio/toolkits.py`
- **Responsibility**: config-schema introspection (constructor params →
  JSON schema) for `LLMWikiToolkit` (incl. `WikiConfig.storage_dir`),
  `DatasetManager`, `InfographicToolkit` (mark `artifact_store` as
  `server_managed`); assignment endpoint; wiki deps reuse-else-build from
  `WikiConfig`.
- **Depends on**: Modules 2, 3 (assignment triggers reload).

### Module 11: Catalog GET helpers
- **Path**: `handlers/studio/catalog.py`
- **Responsibility**: base classes + public configurable attributes
  (introspect `parrot.bots` `__all__` + ctor signatures), LLM clients
  (`SUPPORTED_CLIENTS`), tools (reuse `_build_catalog`), vector stores.
- **Depends on**: Module 3.

### Module 12: Scheduler run-now + last result
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/scheduler.py`,
  `scheduler/manager.py`
- **Responsibility**: `PATCH action="run_now"` (immediate one-shot trigger,
  409 on concurrent run-now, schedule state unchanged) + last-execution
  result read (from `navigator.agents_scheduler` columns `last_run` +
  result metadata).
- **Depends on**: none (independent of studio package).

### Module 13: AgentStudio meta-agent
- **Path**: `handlers/studio/meta_agent.py`,
  `packages/ai-parrot/src/parrot/bots/studio/` (agent + authored skills:
  agent-builder, skill-writer, kb-writer), `parrot/conf.py`
  (`STUDIO_AGENT_MODEL`)
- **Responsibility**: conversational assistant (default `AnthropicClient` +
  `claude-opus-5`, env-overridable, BYOK-aware); writes ONLY into drafts /
  asset dirs; absorbs `AgentFactoryHandler` (reuses
  `parrot/bots/factory/` builders + HITL `finalize_agent_registration`);
  `/api/v1/agents/factory` re-pointed as thin alias.
- **Depends on**: Modules 4, 5, 6, 7, 8.

### Module 14: Docs + integration tests
- **Path**: `docs/agent_studio_api.md`,
  `packages/ai-parrot-server/tests/studio/`
- **Responsibility**: API reference (pattern:
  `docs/vectorstore_handler_api.md`); end-to-end tests for the primary
  loop (create → files → reload → test → publish skill → import).
- **Depends on**: all modules.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_create_agent_definition_roundtrip` | M1 | Full `BotConfig` → YAML → `load_agent_definitions` equality (all previously-dropped fields) |
| `test_registry_unregister` | M1 | `unregister` removes metadata + cached instance; unknown name → False |
| `test_reload_agent_swaps_instance` | M2 | new `get_instance()` returns rebuilt agent; old instance closed |
| `test_reload_agent_failure_keeps_old` | M2 | bad YAML → previous registration intact, error surfaced |
| `test_studio_routes_registered` | M3 | `setup_studio_routes` adds all `/api/v1/astudio/*` routes (pattern: `tests/manager/test_botmanager_wiring.py`) |
| `test_studio_auth_required` | M3 | unauthenticated → 401 on every Studio route |
| `test_create_agent_persist_yaml` | M4 | `persist: true` writes `agent:`-keyed YAML under `AGENTS_DIR/agents/<cat>/` |
| `test_agent_ownership_enforced` | M4 | non-owner mutation → 403; admin bypass allowed |
| `test_draft_validation_report` | M5 | syntax error / forbidden import / zero-or-two bot subclasses → `passed=false` with line numbers |
| `test_draft_activate_gate` | M5 | activate on failed validation → 409; on clean draft → imported + registered + `studio_drafts.status='activated'` |
| `test_files_path_traversal` | M6 | `..`, absolute, symlink escapes → 400 |
| `test_identity_file_names` | M6 | non-canonical identity filename → 400 listing the five names |
| `test_skill_file_frontmatter` | M6 | invalid frontmatter → 422 with parser message |
| `test_skills_catalog_ordering_filtering` | M7 | list ordered by category; `?owner=` and `?category=` filters; invalid category → 400 |
| `test_skills_catalog_dual_write` | M7 | PG row created; registry write failure → `search_index_stale=true`, entry still served |
| `test_skills_catalog_import` | M7 | import materializes file in agent `skills/`; name collision → 409 unless `overwrite=true` |
| `test_byok_store_masked` | M8 | POST stores encrypted; GET returns masked only; unsupported provider → 400 |
| `test_byok_resolver` | M8 | `_UserLLMKeyResolver` returns key for user; test client built with `api_key` kwarg |
| `test_tool_execute_deterministic` | M9 | `tool.execute(**kwargs)` result returned; missing server-managed deps → 422 |
| `test_toolkit_schema_introspection` | M10 | LLMWiki/DatasetManager/Infographic schemas include required/`server_managed` markers |
| `test_scheduler_run_now` | M12 | `action="run_now"` triggers once, schedule state unchanged; concurrent → 409 |
| `test_meta_agent_writes_only_drafts` | M13 | assistant tools cannot write outside `_drafts/` + asset dirs |

### Integration Tests

| Test | Description |
|---|---|
| `test_studio_full_loop` | create agent → PUT identity/kb/skill files → reload → `test/ask` responds with new identity |
| `test_draft_to_live` | assistant scaffolds draft → validation → activate → agent listed + answers |
| `test_skills_catalog_share_flow` | user A publishes skill → user B lists by category/owner → imports into own agent → reload → skill triggers |
| `test_byok_test_run` | stored user key used for `test/ask` (assert provider client received user key, not server key) |
| `test_scheduler_run_now_e2e` | create schedule → run_now → last-result populated in `navigator.agents_scheduler` |
| `test_factory_alias` | `POST /api/v1/agents/factory` still functions via the absorbed meta-agent path |

### Test Data / Fixtures

```python
@pytest.fixture
def studio_app(aiohttp_client):
    """aiohttp app with BotManager.setup + setup_studio_routes,
    mocked session (pattern: packages/ai-parrot/tests/handlers/conftest.py)."""

@pytest.fixture
def tmp_agents_dir(monkeypatch, tmp_path):
    """Patch AGENTS_DIR to tmp_path with agents/, _drafts/ and one seeded
    agent dir (identity/ kb/ skills/)."""

@pytest.fixture
def sample_draft_ok() / sample_draft_bad_import() / sample_draft_syntax_err():
    """Generated-agent .py bodies for the validation matrix."""

@pytest.fixture
def vault_keys(monkeypatch):
    """Deterministic navigator_session master keys for BYOK crypto tests."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All Studio routes live under `/api/v1/astudio/*` (grep: no new route
      registered under `/api/v1/studio`).
- [ ] Every Studio endpoint requires authentication and enforces ownership;
      admin bypass works; PBAC ids are `astudio:<area>`.
- [ ] `POST /astudio/agents` registers into `AgentRegistry`; with
      `persist: true` the written YAML round-trips **losslessly** through
      `load_agent_definitions` (M1 test green).
- [ ] A generated `.py` agent can NEVER be imported/registered without
      `POST /astudio/drafts/{name}/activate`; failed validation blocks
      activation with 409.
- [ ] `POST /astudio/agents/{name}/reload` swaps the shared instance without
      server restart; reload failure leaves the previous agent serving.
- [ ] Identity/kb/skills file CRUD is traversal-safe and frontmatter-
      validated; identity limited to the five canonical files.
- [ ] `GET /astudio/skills` returns entries ordered/grouped by category and
      filterable by `owner` and `category`; publish/import/resync flows work;
      categories constrained to `SkillCategory`.
- [ ] BYOK keys stored via navigator-session vault AES-GCM (no Fernet, no
      new crypto), never returned in plaintext, and used by `test/ask` when
      present.
- [ ] Scheduler supports `action="run_now"` + last-execution-result.
- [ ] Toolkit schema endpoints serve LLMWikiToolkit (incl. `storage_dir`),
      DatasetManager, InfographicToolkit; assignment works with
      reuse-else-build wiki deps.
- [ ] Meta-agent defaults to `claude-opus-5` via `STUDIO_AGENT_MODEL`;
      `/api/v1/agents/factory` still answers (alias).
- [ ] No behavior change to existing routes (`/api/v1/bots`,
      `/api/v1/bot_management`, `/api/v1/agents/config`, stores, scheduler
      CRUD) — no deprecation headers/logs added.
- [ ] All unit tests pass (`pytest packages/ai-parrot-server/tests/studio/ packages/ai-parrot/tests/ -v`)
- [ ] Integration tests pass.
- [ ] API documented in `docs/agent_studio_api.md`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Carried forward from the brainstorm Code Context and verified 2026-08-27
> against the working tree (branch `dev`). Server package root:
> `packages/ai-parrot-server/src/parrot/`; core package root:
> `packages/ai-parrot/src/parrot/`.

### Verified Imports

```python
from navigator.views import BaseView, BaseHandler, ModelView, FormModel  # handlers/bots.py:18-22
from navigator.views.abstract import AbstractModel                        # handlers/bots.py:23
from navigator_auth.decorators import is_authenticated, user_session     # stores/handler.py:11
from navigator_session import get_session                                # navigator/views/abstract.py:17
from navigator_session.vault.config import get_active_key_id, load_master_keys  # credentials.py:41
from parrot.registry import agent_registry, register_agent               # registry/__init__.py:7-12
from parrot.clients.factory import SUPPORTED_CLIENTS, LLMFactory         # factory.py:106,159
from parrot.tools.discovery import discover_all, resolve_class           # discovery.py:108,139
from parrot_tools import TOOL_REGISTRY                                   # parrot_tools/__init__.py:12
from parrot.knowledge.wiki import LLMWikiToolkit, WikiConfig             # wiki/__init__.py:45 (lazy)
from parrot.skills.parsers import parse_skill_file                       # skills/parsers.py:37
from parrot.bots.prompts.identity import IDENTITY_FILES, load_identity   # identity.py:27,51
from parrot.security.credentials_utils import encrypt_credential, decrypt_credential  # :19,:52
from parrot.skills.store import SkillRegistry, create_skill_registry     # store.py:132 (+factory)
from parrot.skills.models import Skill, SkillCategory, SkillStatus       # models.py:158,29,21
from asyncdb.models import Model, Field                                  # scheduler/models.py:4
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/registry/registry.py
class AgentRegistry:  # :252
    def __init__(self, agents_dir: Optional[Path] = None, *,
                 extra_agent_dirs: Optional[Iterable[Path]] = None): ...  # :291
    def setup(self, app: Any) -> None: ...                     # :355 (PBAC wiring)
    def register(self, name: str, factory: Type[AbstractBot], *, singleton=False,
                 tags=None, priority=0, dependencies=None, replace=False,
                 at_startup=False, startup_config=None,
                 bot_config: Optional["BotConfig"] = None, **kwargs) -> None: ...  # :522
    def register_instance(self, name, instance, *, tags=None,
                          priority=0, replace=False) -> None: ...  # :580
    async def get_instance(self, name: str, request: Optional[web.Request] = None,
                           **kwargs) -> Optional[AbstractBot]: ...  # :635
    def load_agent_definitions(self, definitions_dir: Optional[Path] = None) -> int: ...  # :962
        # default dir AGENTS_DIR/'agents' (:967); rglob("*.yaml"); requires `agent:` key
    def create_agent_definition(self, config: BotConfig,
                                category: str = "general") -> Path: ...  # :1053
        # writes AGENTS_DIR/agents/<category>/<name>.yaml; yaml.dump at :1086
        # CURRENTLY DROPS: toolkits, prompt, vector_store, tags, policies,
        # mcp_servers, at_startup, priority, config  ← M1 fixes this
    def delete_factory_agent(self, name: str) -> tuple[bool, str]: ...  # :1090
    def _import_module_from_path(self, path: Path, *, base_dir=None,
        package_hint: str = "parrot.dynamic_agents") -> ModuleType: ...  # :1131
    def _load_modules_from_directory(self, directory: Path) -> int: ...  # :1173
        # NON-recursive glob("*.py"); startup-only via load_modules() :1199
    def list_agents(self) -> List[BotMetadata]: ...            # :1310

class BotConfig(BaseModel):  # registry.py:222
    name: str; class_name: str; module: str; enabled: bool = True
    origin: Literal["repo", "factory"] = "repo"
    config: Dict[str, Any]; tools: Optional[ToolConfig]; toolkits: List[str]
    mcp_servers: List[Dict[str, Any]]; model: Optional[ModelConfig]
    system_prompt: Optional[Union[str, Dict]]; prompt: Optional[PromptConfig]
    vector_store: Optional[StoreConfig]; tags: Optional[Set[str]]
    singleton: bool = False; at_startup: bool = False
    startup_config: Dict[str, Any]; priority: int = 0
    policies: Optional[List["PolicyRuleConfig"]]

# packages/ai-parrot/src/parrot/conf.py:175
AGENTS_DIR = config.get('AGENTS_DIR', fallback=BASE_DIR.joinpath('agents'))
# mkdir'd if missing; inserted at sys.path[0] (:181-189)

# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:  # :109
    def __init__(self, enable_database_bots=ENABLE_DATABASE_BOTS,
                 enable_crews=ENABLE_CREWS, enable_registry_bots=ENABLE_REGISTRY_BOTS,
                 enable_swagger_api=ENABLE_SWAGGER) -> None: ...  # :118
    # self.registry: AgentRegistry = agent_registry  (:150, global singleton)
    async def load_bots(self, app: web.Application) -> None: ...  # :336
    def setup(self, app: web.Application) -> web.Application: ...  # :1686
        # self.app['bot_manager'] = self  (:1702); routes :1709-:2037
    async def create_ephemeral_user_bot(self, user_id=None, config=None,
        uploaded_paths=None, *, owner_id: Optional[str] = None,
        owner_kind: str = "user", ttl_seconds: int = 86400): ...  # :949 (TASK-1388)
    def remove_bot(self, name): ...  # :811 — del self._bots[name]; keeps class

# packages/ai-parrot-server/src/parrot/handlers/bots.py
class ChatbotHandler(_PBACHandlerMixin, AbstractModel):  # :424
    model = BotModel; pk = 'chatbot_id'  # :438-440
    async def get(self): ...     # :640   async def put(self): ...   # :756
    async def post(self): ...    # :1072  async def delete(self): ...# :1247
    async def _provision_vector_store(self, bot, vector_store_config: dict) -> dict: ...  # :910
# Registered: manager.py:1952 — ChatbotHandler.configure(self.app, '/api/v1/bots')
class _PBACHandlerMixin:  # bots.py:45 — _get_pbac_evaluator :56, _build_eval_context :68
_AGENT_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")  # bots.py:85

# packages/ai-parrot-server/src/parrot/handlers/testing_handler.py:29
class BotConfigTestHandler(BaseView):
    # PUT/POST/DELETE /api/v1/agents/test/{agent_name}  (:76/:128/:228)
    # route: manager/manager.py:2007

# packages/ai-parrot-server/src/parrot/handlers/agents/factory.py:107
class AgentFactoryHandler(BaseView):
    async def post(self) -> web.Response: ...  # :110
# route manager.py:1835 — POST /api/v1/agents/factory
# packages/ai-parrot/src/parrot/bots/factory/tools/finalize.py:31
async def finalize_agent_registration(definition: AgentDefinition,
                                      category: str = "general") -> Dict[str, Any]: ...
# stamps origin="factory" (:41-46); HITL-gated @tool (:64)

# packages/ai-parrot-server/src/parrot/handlers/scheduler.py
class SchedulerJobsHandler(BaseView):  # :53
    # manager property → request.app["scheduler_manager"] (:61-66)
    async def get(self): ...   # :71    async def post(self): ...  # :91
    async def patch(self): ... # :123 action ∈ {"pause","resume","update"} (:132-139)
    async def delete(self): ...# :148
# routes scheduler/manager.py:1704-1719
# packages/ai-parrot-server/src/parrot/scheduler/models.py:7
class AgentSchedule(Model):
    class Meta: driver='pg'; name="agents_scheduler"; schema="navigator"  # :59-64

# packages/ai-parrot-server/src/parrot/handlers/stores/handler.py:35-37
@is_authenticated()
@user_session()
class VectorStoreHandler(BaseView):
    # POST/PUT/PATCH /api/v1/ai/stores (:347/:529/:440); GET jobs (:248)
    @classmethod
    def setup(cls, app: web.Application) -> None: ...  # :58

# packages/ai-parrot-server/src/parrot/handlers/credentials.py:69-71
@is_authenticated()
@user_session()
class CredentialsHandler(BaseView):
    COLLECTION: str = "user_credentials"; SESSION_PREFIX: str = "_credentials:"  # :83-84
def setup_credentials_routes(app: web.Application) -> None: ...  # :506
# crypto: parrot/security/credentials_utils.py:19 encrypt_credential(...) AES-GCM
# transparent PG column crypto: handlers/models/_encrypted_field.py (seal/unseal)

# packages/ai-parrot/src/parrot/auth/broker.py
class CredentialBroker: ...                              # :326  (FEAT-264)
class _VaultStaticKeyResolver(CredentialResolver): ...   # :276
# bound at bots/abstract.py:1644 — self.tool_manager.set_broker(broker)

# packages/ai-parrot/src/parrot/clients/factory.py
SUPPORTED_CLIENTS = {...}  # :106
class LLMFactory:  # :159
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]: ...  # :169
    @staticmethod
    def create(llm: str, model_args: Optional[Dict[str, Any]] = None,
               tool_manager: Optional[Any] = None, **kwargs) -> AbstractClient: ...  # :191

# packages/ai-parrot/src/parrot/clients/claude.py
class AnthropicClient(AbstractClient):  # :67
    _default_model: str = 'claude-sonnet-4-5'  # :73
    def __init__(self, api_key: str = None, base_url="https://api.anthropic.com",
                 backend: AnthropicBackend = "direct", ..., **kwargs): ...  # :79
    # `model` flows via **kwargs → clients/base.py:315
    # api_key fallback: config.get('ANTHROPIC_API_KEY')  (:120)

# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager(MCPToolManagerMixin):  # :233
    def register_toolkit(self, toolkit: Union[str, "AbstractToolkit", type],
                         **kwargs) -> List[AbstractTool]: ...  # :1008
    def register_tool(self, tool=None, name=None, description=None,
                      input_schema=None, function=None) -> None: ...  # :718
    def get_tool(self, tool_name): ...   # :1215
    def list_tools(self) -> List[str]: ...  # :1235
    def unregister_tool(self, tool_name) -> bool: ...  # :1257
# Agent exposes it as `self.tool_manager` (bots/abstract.py:386)

# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):  # :235
    async def execute(self, *args, **kwargs) -> ToolResult: ...  # :797
    async def _execute(self, **kwargs) -> Any: ...  # :490 (@abstractmethod)

# Tool enumeration: parrot_tools/__init__.py:12 TOOL_REGISTRY (207 slugs);
# tools/discovery.py discover_from_registry :31 / discover_all :108 / resolve_class :139
# handlers/tools_catalog.py:85 ToolCatalogHandler; _build_catalog() :44;
# route /api/v1/tools/catalog (manager.py:1798)

# Identity — parrot/bots/prompts/identity.py
IDENTITY_FILES = ("role", "goal", "capabilities", "backstory", "rationale")  # :27
def load_identity(directory, *, escape_placeholders: bool = False) -> IdentityFields: ...  # :51
# parrot/bots/mixins/identity.py:40 IdentityMixin — hot-reload seam _build_prompt :202

# KB — parrot/bots/stores/local.py
def _get_agent_kb_directory(self) -> Optional[Path]: ...  # :41 → AGENTS_DIR/<name>/kb (:56)
async def configure_local_kb(self) -> None: ...  # :59 (invoked abstract.py:1508-1510)

# Skills — parrot/skills/
def parse_skill_file(file_path: Path) -> SkillDefinition: ...       # parsers.py:37
def parse_skill_directory(skill_dir: Path) -> SkillDefinition: ...  # parsers.py:109
# frontmatter: name*, description*, triggers* (key required; may be []),
#   version="1.0", category, priority=90; body ≤ MAX_TOKENS=1000 (models.py:76)
class SkillFileRegistry:  # file_registry.py:17
    def __init__(self, skills_dir: Path, learned_dir: Optional[Path] = None): ...  # :29
# per-agent dirs: AGENTS_DIR/{agent_id}/skills[/learned] (skills/mixin.py:141)

# DB-backed skill registry — parrot/skills/store.py
class SkillRegistry:  # Redis + file persistence, embedding search
    def __init__(self, namespace: str = "default",
                 embedding_model="sentence-transformers/all-mpnet-base-v2",
                 dimension: int = 768, redis_url: Optional[str] = None,
                 persistence_path: Optional[Path] = None,
                 extraction_llm=None, min_diff_threshold: int = 50): ...  # :132
    # namespace = "org_id/agent_id"; async upload_skill / read_skill /
    # search_skills / list_skills / get_skill_versions / deprecate_skill / revoke_skill

# parrot/skills/models.py
class SkillCategory(str, Enum): ...  # :29 — tool_usage, workflow, domain,
    # error_handling, user_preference, integration, optimization, general
class SkillStatus(str, Enum): ...    # :21 — active, deprecated, revoked, draft
@dataclass
class Skill:  # :158
    skill_id: str; namespace: str = "default"   # "org_id/agent_id"
    owner_agent_id: str = ""                    # AGENT owner — no user owner field
    metadata: SkillMetadata; status: SkillStatus
    current_version: int; version_count: int
    created_at: datetime; updated_at: datetime
    access_count: int; usefulness_score: float

# Wiki — parrot/knowledge/wiki/toolkit.py:54
class LLMWikiToolkit(AbstractToolkit):
    tool_prefix: str = "wiki"  # :81
    def __init__(self, pageindex_toolkit, graphindex_toolkit, okf_toolkit,
                 config: WikiConfig, agent_id: str = "agent",
                 store: Optional[BaseWikiStore] = None, **kwargs) -> None: ...  # :83
# WikiConfig (knowledge/wiki/models.py:52): wiki_name* (:83),
#   storage_dir: Path* (:84 — wiki plane root), source_dir (:85),
#   storage_backend: Literal["sqlite","memory","arangodb"]="sqlite" (:112)
# bots capture: interfaces/tools.py:190 stashes LLMWikiToolkit as bot._llmwiki_toolkit;
#   abstract.py:402-404 declares _pageindex_toolkit/_graphindex_toolkit/_llmwiki_toolkit

# parrot/tools/dataset_manager/tool.py:501 (core)
class DatasetManager(AbstractToolkit):
    def __init__(self, df_prefix="df", generate_guide=True,
                 include_summary_stats=False, auto_detect_types=True,
                 policy_guard=None, dataplane_guard=None,
                 usage_rules=None, **kwargs): ...  # :549

# parrot/tools/infographic_toolkit.py:178 (core)
class InfographicToolkit(AbstractToolkit):
    def __init__(self, *, artifact_store: ArtifactStore, template_dirs=None,
                 templates=None, emit_a2ui=False, recipe_store=None,
                 recipe_runner=None, dataset_manager=None, **kwargs) -> None: ...  # :211
# artifact_store REQUIRED keyword-only; server wires app['artifact_store'] (manager.py:2157)

# navigator (installed navigator-api 3.2.2) — .venv/.../navigator/views/
# base.py:619 BaseView(CorsViewMixin, BaseHandler, web.View); base.py:42 BaseHandler(ABC)
def json_response(self, response=None, reason=None, headers=None, status=200, ...): ...  # base.py:144
async def session(self): ...                            # base.py:89
async def get_userid(self, session, idx='user_id') -> int: ...  # base.py:99
async def post_data(self) -> dict: ...                  # base.py:673
def post_init(self, *args, **kwargs): ...               # base.py:79
@classmethod
def setup(cls, app, route: str) -> None: ...             # base.py:635
# abstract.py:190 AbstractModel.configure(cls, app, path, **kwargs)
#   — registers path AND catch-all r"{url}/{{id:.*}}" (:224-226): route-order sensitive

# Agent base classes (parrot/bots/): abstract.py:187 AbstractBot; base.py:69 BaseBot;
# basic.py:3 BasicBot; chatbot.py:30 Chatbot; agent.py:29 BasicAgent; agent.py:1236 Agent;
# data.py:355 PandasAgent; document.py:104 DocumentAgent; search.py:45 WebSearchAgent;
# chrome.py:290 WebAgent; mcp.py:11 MCPAgent; a2a_agent.py:6 A2AAgent;
# info.py:37 InfoAgent (lazy); voice.py:87 VoiceBot (lazy)
# bots/__init__.py:9 __all__ = ("AbstractBot","Agent","BaseBot","BasicAgent",
#   "BasicBot","Chatbot","InfoAgent","VoiceBot","WebAgent","WebSearchAgent")
# LLM declaration: abstract.py:283 llm kwarg; :826 _resolve_llm_config
#   (instance | class | model_config dict | "provider:model" | provider+model | defaults)

# Scaffolding CLI: parrot/setup/scaffolding.py:207
def scaffold_agent(agent_config, cwd) -> Path: ...  # writes AGENTS_DIR/<module>.py (:241-244)
```

### Integration Points (verified)

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `setup_studio_routes(app)` | `BotManager.setup()` | function call inside setup | manager/manager.py:1686-2037 |
| Studio handlers | `BotManager` | `self.request.app['bot_manager']` | manager/manager.py:1702 |
| `reload_agent` | `AgentRegistry.register(replace=True)` / `remove_bot` | method calls | registry.py:522 / manager.py:811 |
| Draft activation | `AgentRegistry._import_module_from_path` | method call | registry.py:1131 |
| YAML persist | `AgentRegistry.create_agent_definition` | method call (post-M1 fix) | registry.py:1053 |
| Test-run client | `LLMFactory.create(..., api_key=...)` | kwargs pass-through to client `__init__` | factory.py:191 / claude.py:79 |
| BYOK crypto | `encrypt_credential`/`decrypt_credential` | function calls | security/credentials_utils.py:19,52 |
| Toolkit assignment | `bot.tool_manager.register_toolkit(...)` | method call | tools/manager.py:1008 |
| Skills catalog PG | asyncdb `Model` on `app['database']` | same pattern as `AgentSchedule` | scheduler/models.py:7,59-64 |
| Scheduler run-now | `manager.scheduler` (APScheduler) job trigger | `request.app['scheduler_manager']` | handlers/scheduler.py:61-75 |
| Meta-agent finalize | `finalize_agent_registration` | HITL-gated tool | bots/factory/tools/finalize.py:31 |
| Infographic schema | `app['artifact_store']` | app-context wiring | manager/manager.py:2157 |

### Does NOT Exist (Anti-Hallucination)

- ~~Any "Agent Studio"/"astudio"/"playground" handler, route, class, or
  spec~~ — greenfield namespace ("studio" grep hits only Copilot Studio
  a2a, Odoo Studio, LM Studio, `google_ai_studio` observability).
- ~~`AgentRegistry.unregister(name)`~~ — NEW in M1; today only
  `delete_factory_agent` (origin-gated) and `clear_registry()` (test-only).
- ~~Any agent reload/restart method or endpoint~~ — NEW in M2;
  `importlib.reload` never called in `registry/`/`manager/`.
- ~~Draft/activate lifecycle~~ — NEW in M5; today the only gate is
  `BotConfig.enabled`.
- ~~A loader for `AGENTS_DIR/<name>/config.yaml`~~ — `agents/navigator/
  config.yaml` is read by NO code path; canonical loaded format is the
  `agent:`-keyed YAML of `load_agent_definitions`. No `NavigatorAgent`
  class exists.
- ~~`agents/agents/` directory in this repo~~ — `load_bots` Step 2b is a
  no-op until `create_agent_definition` first writes there.
- ~~Fernet / `cryptography.fernet` / HashiCorp Vault~~ — zero matches in
  `packages/*/src`; house crypto is AES-GCM via `navigator_session.vault`.
- ~~An LLM-API-key vault table or handler~~ — `CredentialsHandler` stores
  DATABASE connection credentials (`driver` + `params`) in DocumentDB
  collection `user_credentials`; no `api_keys`/`user_llm_keys` store exists.
- ~~`WikiToolkit`~~ — class is `LLMWikiToolkit`, core
  `parrot/knowledge/wiki/toolkit.py`, NOT in `parrot_tools`, NOT in
  `TOOL_REGISTRY` (three toolkit deps + `WikiConfig` required).
- ~~`InfographicToolkit` in `TOOL_REGISTRY`~~ — absent; keyword-only
  required `artifact_store` blocks zero-arg instantiation.
- ~~`AbstractBot.add_tool()` / `add_toolkit()` / `register_toolkit()`~~ —
  only `register_tools()` (abstract.py:4019); use
  `bot.tool_manager.register_toolkit(...)`.
- ~~`AnthropicClient(model=...)` explicit param / `DEFAULT_MODEL` const~~ —
  model flows via `**kwargs`; class attr `_default_model`.
- ~~`parrot.clients.SUPPORTED_CLIENTS`~~ — import from
  `parrot.clients.factory`.
- ~~`handlers/__init__.py` in the server package / central
  `setup_routes()`~~ — wiring is split across root `app.py:configure()`,
  `BotManager.setup()`, and per-handler `setup`/`configure`/
  `setup_*_routes` idioms.
- ~~Scheduler `run_now` / last-result endpoint~~ — NEW in M12; `patch`
  supports only `pause|resume|update`; global `POST /restart` exists but
  no per-job trigger.
- ~~Lossless YAML round-trip~~ — NEW in M1 (see dropped-field list above).
- ~~A Postgres table for skills~~ — NEW in M7; `SkillRegistry` persists to
  Redis + file only. `navigator.ai_skills_catalog` and
  `navigator.studio_drafts` are both NEW tables.
- ~~An owner-USER field on `Skill`~~ — only `owner_agent_id`
  (skills/models.py:168); `owner_user_id` is NEW in M7.
- ~~An org-wide shared skills namespace~~ — namespaces today are
  `"org_id/agent_id"` per-agent isolation (store.py:134,146).
- ~~`STUDIO_AGENT_MODEL` in `parrot/conf.py`~~ — NEW in M13.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Handler idiom: `@is_authenticated()` + `@user_session()` on `BaseView`
  subclasses; `post_init` sets `self.logger` via `_logger_name`; session →
  `await self.session()` then `await self.get_userid(...)` (see
  `handlers/stores/handler.py:35-37`, `handlers/credentials.py:69-71`).
- Route registration: one `setup_studio_routes(app)` module function
  (pattern: `setup_credentials_routes`, credentials.py:506) called from
  `BotManager.setup` — do NOT create `handlers/__init__.py` aggregation.
- Ownership + PBAC: follow `_PBACHandlerMixin` (bots.py:45) — fail-open
  when `app['abac']` absent, session ownership always enforced; server-set
  `created_by` (bots.py:864-869); slug validation via `_AGENT_SLUG_RE`
  equivalent (`^[a-z0-9_-]+$`).
- New tables: asyncdb `Model` with docstring DDL, `driver='pg'`,
  `schema='navigator'` (pattern: `scheduler/models.py`).
- Async-first throughout; Pydantic for every payload; Google-style
  docstrings; `self.logger`, never `print`.
- Meta-agent tools that write files must be HITL/confirmation-gated like
  `finalize_agent_registration` (`@tool` with confirmation), and constrained
  to `_drafts/` + asset dirs.
- Long-running test/vector operations: reuse `JobManagerMixin` /
  `JobManager` (handlers/jobs/) as VectorStoreHandler does — don't invent a
  new job system.

### Known Risks / Gotchas

- **`AbstractModel.configure` catch-all**: it registers `path/{id:.*}` —
  Studio uses plain `add_view` routes to avoid the route-ordering traps
  noted around manager.py:1976-1984.
- **Reload memory contract**: in-flight requests keep the old instance;
  working memory/conversation state of the old instance is NOT migrated —
  document in API reference. Old singleton `cleanup()` is best-effort.
- **Reload failure must not unregister**: swap only after successful
  rebuild; on failure return 422 and keep the previous registration.
- **Draft import side effects**: `_import_module_from_path` executes module
  top-level code — the AST allowlist must run BEFORE any import, and
  activation should import in the same process only after validation
  passes (the gate is the security boundary, per resolved decision).
- **`create_agent_definition` fix is load-bearing** (M1 first): until
  fixed, any Studio persist → reload cycle silently loses toolkits/
  vector-store config.
- **Dual-write drift** (skills catalog): PG-first, registry best-effort
  with `search_index_stale=true`; startup reconciliation + admin resync
  repair it. Never fail a publish because Redis is down.
- **BYOK security**: never log or return plaintext keys; masked GET only;
  provider validated against `SUPPORTED_CLIENTS`; missing vault master
  keys → 503 with operator guidance (pattern: credentials.py soft-import).
- **InfographicToolkit/LLMWikiToolkit instantiation**: required deps not
  client-suppliable — schema endpoint marks them `server_managed`;
  execute/assign returns 422 listing missing deps when the app context
  lacks them.
- **Route collision**: `/api/v1/astudio/` chosen precisely because
  `/api/v1/studio` belongs to another installed service — never register
  under `/studio`.
- **Concurrent run-now**: guard per-job (409) — APScheduler will happily
  double-fire otherwise.
- **`bots.py` untouched**: Studio reuses its *patterns*, not its code paths
  — no edits to `ChatbotHandler` (regression isolation).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navigator-api` | installed 3.2.2 | `BaseView`/`BaseHandler`/route registration |
| `navigator-auth` | installed 0.22.11 | `@is_authenticated()`, `@user_session()` |
| `navigator-session` | installed 0.10.1 | AES-GCM vault for BYOK (no new crypto dep) |
| `asyncdb` | installed 2.15.10 | new `Model`s for `studio_drafts` / `ai_skills_catalog` |
| `python-frontmatter` | installed | skill frontmatter parse/write (already used by skills/parsers.py) |
| `apscheduler` | installed | run-now trigger via existing `AgentSchedulerManager` |
| `ast` (stdlib) | — | draft static validation |

No NEW third-party dependencies are introduced.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks sequential in ONE
  worktree (`.claude/worktrees/feat-467-agentstudio-management`).
- **Rationale**: dependency shape is a diamond — core primitives (M1–M3) →
  many independent modules (M4–M13) → shared route wiring. The
  `BotManager.setup` route block and `handlers/studio/` scaffold are merge
  magnets; parallel worktrees would collide there repeatedly. Within the
  single worktree, M4–M12 remain independently committable tasks.
- **Cross-feature dependencies**: none blocking — FEAT-149 (ephemeral),
  FEAT-049 (bot creation), FEAT-264 (credential broker), FEAT-208/TASK-1388
  (ownership) are all merged. Before cutting the worktree, check
  `/sdd-status` for any in-flight feature touching `manager/manager.py`,
  `registry/registry.py`, or `handlers/scheduler.py`.

---

## 8. Open Questions

> All questions raised during exploration were resolved in the brainstorm
> (`sdd/proposals/agentstudio-management.brainstorm.md`). Decision trail:

- [x] Flow type / base branch — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] Deliverable scope — *Resolved in brainstorm*: backend API only; interactive UI is a separate later spec.
- [x] Meta-agent in this spec? — *Resolved in brainstorm*: yes — HTTP surface + meta-agent + its skills.
- [x] BYOK storage — *Resolved in brainstorm*: persisted encrypted per-user via the existing navigator-session AES-GCM vault + new `CredentialBroker` resolver; NOT a new Fernet table.
- [x] Safety gate for generated Python agents — *Resolved in brainstorm*: explicit activate step; static validation on save; import+register only on activation.
- [x] Reload scope — *Resolved in brainstorm*: reload swaps the shared registered agent; all consumers get new behavior immediately.
- [x] Scheduler depth — *Resolved in brainstorm*: CRUD + run-now/test with last execution result.
- [x] Access model — *Resolved in brainstorm*: any authenticated user; ownership-aware (creator owns; owners/admins modify).
- [x] Route prefix — *Resolved in brainstorm*: `/api/v1/astudio/` (another installed service occupies "studio" routes); internal code naming stays `studio`/`AgentStudio`.
- [x] Shared skills catalog storage — *Resolved in brainstorm*: extend `SkillRegistry` (org-wide shared namespace + owner-user field) AND persist entries in the new Postgres table for SQL ordering/filtering.
- [x] Relationship to `AgentFactoryHandler` — *Resolved in brainstorm*: Studio meta-agent absorbs it; reuses `parrot/bots/factory/` builders + HITL finalize; `/api/v1/agents/factory` stays as a thin alias.
- [x] Default model id for the meta-agent — *Resolved in brainstorm*: `claude-opus-5`, overridable via `STUDIO_AGENT_MODEL` in `parrot/conf.py`.
- [x] Canonical agent-YAML schema — *Resolved in brainstorm*: the `agent:`-keyed definition format; `create_agent_definition` round-trip fix is TASK #1 (Module 1).
- [x] `LLMWikiToolkit` dependency construction — *Resolved in brainstorm*: reuse the bot's captured `_pageindex_toolkit`/`_graphindex_toolkit` when present; else construct fresh from the submitted `WikiConfig`.
- [x] Draft store location/state — *Resolved in brainstorm*: `.py` content on disk (`AGENTS_DIR/_drafts/`); lifecycle state/audit in the new `navigator.studio_drafts` table.
- [x] PBAC policy naming — *Resolved in brainstorm*: `astudio:<area>` resource ids; superuser/admin bypasses ownership; fail-open without a PDP (session ownership still enforced).
- [x] Deprecation signal for old Bot Management — *Resolved in brainstorm*: leave silent; no headers or logs; revisit later.
- [x] Skills catalog category vocabulary — *Resolved in brainstorm*: constrained to the `SkillCategory` enum; out-of-vocabulary → `general`.
- [x] Skills catalog re-sync — *Resolved in brainstorm*: startup reconciliation pass + admin `POST /api/v1/astudio/skills/resync`; exact column list finalized in this spec (§2 Data Models).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-27 | Jesus Lara | Initial draft from brainstorm (Option A, all questions resolved) |
