---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Agent Studio — Management API

**Date**: 2026-08-27
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

AI-Parrot has grown many agent-facing capabilities — skills, identity files,
KB files, tools/toolkits, vector stores, MCP servers, scheduler entries,
ephemeral agents, an agent factory — but each shipped as a **separate HTTP
surface** wired at different times by different features. A domain owner who
wants to "create an agent, give it skills and a KB, attach a toolkit, test
it, and schedule it" today has to stitch together at least eight unrelated
endpoints (`/api/v1/bots`, `/api/v1/agents/config`, `/api/v1/agents/test/*`,
`/api/v1/agents/factory`, `/api/v1/tools/catalog`, `/api/v1/ai/stores`,
`/api/v1/parrot/scheduler/*`, `/api/v1/users/credentials`) — none of which
share a lifecycle model, and several of which have no way to reload a running
agent after its files change.

**Agent Studio** is the control plane that unifies these into one coherent
backend API for building, testing, and monitoring agents. This spec covers
the **backend API only** (HTTP handlers + the AgentStudio meta-agent); the
interactive UI frontend is a separate later spec that consumes this API.

**Who is affected**: domain owners / team leads building agents (primary),
platform operators (scheduler + deploy), and downstream UI developers.

**Why now**: the pieces exist but the seams do not — notably there is *no*
agent reload, *no* draft/activate lifecycle for generated code, *no* BYOK
for LLM keys, and *no* file-management API for identity/skills/kb assets.
Every new capability we add without a unifying surface deepens the
fragmentation this spec supersedes (without deprecating the existing
Bot Management handler).

## Constraints & Requirements

- **Backend API only** — no frontend in this spec. Handlers extend
  `navigator.views.BaseView` (CBV) and/or `BaseHandler` for bare GET helpers,
  matching every existing handler in `packages/ai-parrot-server`.
- **Auth + ownership-aware**: all Studio endpoints behind
  `@is_authenticated()` / `@user_session()`; agents created through the
  Studio carry their creator as owner (reuse the owner-aware patterns from
  TASK-1388 / `EphemeralRegistry` and the server-set `created_by` convention
  in `ChatbotHandler.put`). Only owners/admins may modify an agent.
- **Explicit activate step** for LLM-generated Python agents: generated `.py`
  is a *draft*; static validation (AST parse, import whitelist check) runs on
  save, but the module is only imported and registered into `AgentRegistry`
  when the user explicitly activates it.
- **Hot reload swaps the shared registered agent**: reload replaces the agent
  instance in `AgentRegistry`/`BotManager` so all consumers immediately get
  the new behavior — no server restart.
- **Scheduler**: CRUD **+ run-now/test** (trigger immediately, view last
  execution result). CRUD largely exists (`SchedulerJobsHandler`); run-now
  and last-result are the new parts.
- **BYOK**: user LLM API keys stored in the existing encrypted vault
  machinery (`navigator_session.vault` AES-GCM + `CredentialsHandler`
  pattern), resolved at client-build time via a new `CredentialBroker`
  resolver — NOT a new table, NOT Fernet (Fernet does not exist anywhere in
  this codebase; the house crypto is AES-GCM via `navigator_session.vault`).
- **Reuse before build**: every helper GET (tools list, base classes, LLM
  clients, vector stores) must reuse the existing catalogs
  (`TOOL_REGISTRY`/`discover_all()`, `SUPPORTED_CLIENTS`,
  `supported_stores`, `parrot.bots.__all__`) rather than new registries.
- Async-first, Pydantic models for payloads, Google-style docstrings,
  `self.logger` — per project standards.
- The existing Bot Management surface (`/api/v1/bots`, `BotManagement`) is
  **not deprecated** by this feature; Agent Studio supersedes it as the
  recommended surface but both remain routable.

---

## Options Explored

### Option A: Studio Facade — new `/api/v1/studio/*` namespace of thin handlers over existing managers, plus gap-filling modules

A new `handlers/studio/` package in `ai-parrot-server` exposing one coherent
namespace. Handlers are deliberately thin: they delegate to `BotManager`,
`AgentRegistry`, `AgentSchedulerManager`, `VectorStoreHandler`'s helpers, the
tool discovery layer, and the credentials vault. New *capability* code is
written only where nothing exists today:

1. **Agent lifecycle** (`studio/agents.py`): create simple agent (delegates
   to the same `BotModel`/registry paths as `ChatbotHandler.put`, persisting
   YAML via `AgentRegistry.create_agent_definition`), draft/activate for
   generated `.py` files, **reload endpoint** (new: re-run
   `load_agent_definitions` / re-import module, evict old instance from
   `BotManager._bots` + `BotMetadata._instance`).
2. **Asset file management** (`studio/files.py`): sandboxed CRUD for
   `AGENTS_DIR/<agent>/identity/*.md` (the five canonical
   role/goal/capabilities/backstory/rationale files), `kb/*.md`, and
   `skills/*` (single-file and composite SKILL.md layouts), with frontmatter
   validation via `parse_skill_file`. Path-traversal rejected (same policy as
   `read_skill_asset`).
3. **AgentStudio meta-agent** (`studio/meta_agent.py`): an `Agent` subclass
   defaulting to `AnthropicClient` + Opus tier, loaded with authored skills
   (agent-builder, skill-writer, kb-writer) that let it emit YAML agents,
   Python agents (into the draft store), skill files with frontmatter, and
   KB files on natural-language request. Follows the HITL-gated
   `finalize_agent_registration` pattern from the existing agent factory.
4. **Test surface** (`studio/testing.py`): deterministic tool execution
   (`tool.execute(**kwargs)` directly) and LLM-mediated testing
   (`agent.ask()` with the tool registered in `bot.tool_manager`), modeled
   on `BotConfigTestHandler` session-based test agents; vector-store
   retrieval test delegates to the existing `PATCH /api/v1/ai/stores`.
5. **Catalog GETs** (`studio/catalog.py`, `BaseHandler` bare functions):
   agent base classes + public configurable attributes (introspected from
   `parrot.bots` `__all__` + constructor signatures), supported LLM clients
   (`SUPPORTED_CLIENTS`), supported vector stores, toolkit config schemas
   for `LLMWikiToolkit`, `DatasetManager`, `InfographicToolkit` (introspected
   constructor params → JSON schema). Tools list reuses `ToolCatalogHandler`
   logic (`discover_all()`).
6. **BYOK** (`studio/byok.py`): extend the `CredentialsHandler` storage
   pattern (session vault + DocumentDB, AES-GCM `encrypt_credential`) with a
   `llm_api_key` credential kind + a new `CredentialBroker` resolver so
   `LLMFactory.create()`/client construction can consume a per-user key when
   testing an agent.
7. **Scheduler run-now**: added to the existing `SchedulerJobsHandler`
   (`PATCH action="run_now"` alongside pause/resume/update) rather than a
   parallel handler.

✅ **Pros:**
- Maximum reuse — ~70% of required behavior already exists behind other
  routes; this option writes only the genuinely missing seams (reload,
  draft/activate, file CRUD, BYOK resolver, run-now, config-schema GETs).
- One coherent, documentable namespace for the future UI, without breaking
  or duplicating the existing surfaces (supersede-not-deprecate satisfied).
- Thin handlers keep business logic in `BotManager`/`AgentRegistry` where
  the rest of the server already finds it; low regression risk.
- Each module is independently testable and largely independently
  implementable (good task decomposition).

❌ **Cons:**
- Facade discipline requires touching several existing modules
  (`registry.py` gains unregister/reload primitives; `scheduler.py` gains an
  action; `create_agent_definition` must stop dropping fields) — cross-module
  coordination.
- Two agent-creation surfaces coexist (`/api/v1/bots` and
  `/api/v1/studio/agents`) until a later deprecation decision.
- The meta-agent overlaps conceptually with the existing
  `AgentFactoryHandler` — must be positioned as its evolution, sharing the
  builder/finalize machinery, or we fork that logic.

📊 **Effort:** High (large surface, but mostly integration work)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-api` (installed 3.2.2) | `BaseView`, `BaseHandler`, `AbstractModel.configure` | already the base of every handler |
| `navigator-auth` (0.22.11) | `@is_authenticated()`, `@user_session()` | existing auth decorators |
| `navigator-session` (0.10.1) | AES-GCM vault (`encrypt_for_db`/`decrypt_for_db`) | BYOK crypto — no new crypto dependency |
| `python-frontmatter` (installed) | skill frontmatter parse/write | already used by `parrot.skills.parsers` |
| `ast` (stdlib) | static validation of generated agent `.py` drafts | parse + import-whitelist check |
| `apscheduler` (installed) | run-now via `manager.scheduler` job trigger | already the scheduler backend |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/handlers/bots.py` — `ChatbotHandler`
  create/update flows, slugify/dedup, server-set `created_by`, eager vector
  store provisioning (`_provision_vector_store`).
- `packages/ai-parrot-server/src/parrot/handlers/testing_handler.py` —
  `BotConfigTestHandler` session-based test agents (nearest existing thing
  to a Studio test-run endpoint).
- `packages/ai-parrot-server/src/parrot/handlers/agents/factory.py` —
  `AgentFactoryHandler` + `parrot/bots/factory/` builders/orchestrator and
  the HITL-gated `finalize_agent_registration` tool.
- `packages/ai-parrot-server/src/parrot/handlers/credentials.py` —
  `CredentialsHandler` vault storage pattern (session vault + DocumentDB).
- `packages/ai-parrot-server/src/parrot/handlers/scheduler.py` +
  `scheduler/manager.py` — job CRUD, `AgentSchedulerManager`,
  `navigator.agents_scheduler` table.
- `packages/ai-parrot-server/src/parrot/handlers/stores/` —
  `VectorStoreHandler` (create/load/search) and `VectorStoreHelper` metadata.
- `packages/ai-parrot-server/src/parrot/handlers/tools_catalog.py` —
  `ToolCatalogHandler` / `_build_catalog()`.
- `packages/ai-parrot/src/parrot/registry/registry.py` — YAML definition
  loader/writer, dynamic module import machinery.
- `packages/ai-parrot/src/parrot/tools/discovery.py` +
  `parrot_tools.TOOL_REGISTRY` (207 entries) — tool enumeration.
- `packages/ai-parrot/src/parrot/clients/factory.py` — `SUPPORTED_CLIENTS`,
  `LLMFactory.create`.
- `packages/ai-parrot/src/parrot/auth/broker.py` — `CredentialBroker` +
  resolver factory for BYOK key resolution.
- `packages/ai-parrot/src/parrot/bots/prompts/identity.py` +
  `bots/mixins/identity.py` — identity file contract and its existing
  hot-reload seam (`_build_prompt` re-reads files each call).
- `packages/ai-parrot/src/parrot/skills/` — `parse_skill_file`,
  `SkillFileRegistry`, per-agent `AGENTS_DIR/{agent_id}/skills/` layout.

---

### Option B: Full AgentStudio subsystem — new service layer + own persistence, replacing Bot Management

Build `handlers/studio/` *plus* a first-class `StudioManager` service (peer
of `BotManager`) with its own Postgres tables (`navigator.studio_agents`,
`navigator.studio_drafts`, `navigator.studio_events`) recording the full
lifecycle (draft → validated → active → retired), an event log per agent,
and its own copies of the create/test flows. The Studio becomes the system
of record; `/api/v1/bots` reads through it.

✅ **Pros:**
- Clean-room lifecycle model — draft/activate/versioning/audit are
  first-class from day one, not bolted onto `BotConfig.enabled`.
- One owner for all Studio state; the future UI gets a single consistent
  data model with history ("who changed this skill and when").
- Avoids compromising existing handlers — zero changes to `bots.py`,
  `scheduler.py`, `registry.py` behavior.

❌ **Cons:**
- Duplicates a large amount of proven logic (creation normalization, vector
  store provisioning, test sessions, tool cataloging) — double maintenance
  and drift risk, exactly the fragmentation this feature is meant to end.
- New tables + migration burden; the agent's real state still lives in
  `AgentRegistry`/`BotModel`, so the Studio DB becomes a second source of
  truth that can desynchronize.
- Much larger scope; delays the usable API considerably.

📊 **Effort:** Very High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` (2.15.10) | new `Model` classes for studio tables | same pattern as `AgentSchedule` |
| everything from Option A | — | superset |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/scheduler/models.py` —
  `AgentSchedule` as the asyncdb `Model` + docstring-DDL pattern for new
  tables.
- `packages/ai-parrot-server/src/parrot/manager/manager.py` — `BotManager`
  as the structural template for a `StudioManager` (setup/app-key/route
  registration lifecycle).

---

### Option C: Extend existing handlers in place — no new namespace

No `/api/v1/studio/*`. Add the missing endpoints to the handlers that almost
do the job already: `bots.py` gains reload + draft/activate verbs;
`scheduler.py` gains `run_now`; `credentials.py` gains an `llm_api_key`
credential kind; `config_handler.py` gains file-asset CRUD;
`testing_handler.py` gains deterministic tool execution; a small new
`catalog.py` adds the base-classes/clients/toolkit-schema GETs. The "Studio"
is then only documentation: a described composition of existing routes.

✅ **Pros:**
- Smallest diff; every change lands next to the code it extends; fastest to
  ship.
- No duplicate creation surface, no facade to keep in sync.

❌ **Cons:**
- Does not deliver the actual product goal: there is no coherent control
  plane for a UI to target — the fragmentation (different auth idioms,
  different payload conventions, different error shapes across 8 handlers)
  remains the UI's problem.
- `bots.py` is already 1,395 lines with no module docstring and mixed
  concerns; loading lifecycle + drafts + reload into it makes the worst file
  worse.
- No natural home for the AgentStudio meta-agent and its skills.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| same as Option A minus new package scaffolding | — | — |

🔗 **Existing Code to Reuse:** identical list to Option A (by definition).

---

### Option D (unconventional): Studio as an MCP server — tool-first control plane

Instead of (or before) REST, expose every Studio operation as MCP tools on a
`parrot-studio` MCP stdio/SSE server (the repo already ships an MCP server
implementation under `parrot/mcp/` and a wikitoolkit MCP server as
precedent). `studio_create_agent`, `studio_write_identity_file`,
`studio_reload_agent`, `studio_test_tool`, etc. The interactive "UI" for v1
is then any MCP client — including Claude Code and the AgentStudio meta-agent
itself, which gets its capabilities for free as MCP tools instead of bespoke
skills. A thin REST shim can be generated later for the web UI.

✅ **Pros:**
- The meta-agent and human power-users share one tool surface; dogfoods the
  framework's own MCP stack.
- Tool-first design forces precise, schema-validated operations (good spec
  hygiene) and is naturally scriptable.

❌ **Cons:**
- The stated consumer is a web UI on aiohttp sessions with
  navigator-auth — MCP has no story for `@is_authenticated()` browser
  sessions, ownership, or PBAC as deployed here.
- Doesn't remove the need for the REST layer; it adds a second protocol to
  secure and maintain.
- Higher conceptual risk for the team's immediate goal.

📊 **Effort:** High (and doesn't replace Option A/C work)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot/mcp/` (in-repo) | MCP server machinery | already exposes agents as MCP |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/mcp/` — server implementation.
- `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` — precedent
  for a domain MCP server.

---

## Recommendation

**Option A** is recommended.

- It is the only option that delivers the product goal (one coherent control
  plane for the UI) **and** honors the codebase reality that ~70% of the
  behavior already exists behind other routes. Option C ships fastest but
  leaves the UI facing eight inconsistent surfaces — the problem statement
  itself. Option B's clean-room lifecycle is attractive, but a second source
  of truth beside `AgentRegistry`/`BotModel` is a standing desync bug; we can
  get draft/activate semantics with a far smaller draft-store (filesystem
  `AGENTS_DIR/_drafts/` + a small state file or table) inside Option A.
- What we trade off: facade discipline (thin handlers, logic stays in
  managers) needs review vigilance, and we accept two coexisting creation
  surfaces until a separate deprecation decision — explicitly required by
  the motivation ("supersede, not deprecate").
- Option D is worth keeping in mind as a *follow-up*: once the Studio API
  exists with clean internal service functions, wrapping them as MCP tools
  is cheap; nothing in Option A blocks it.

---

## Feature Description

### User-Facing Behavior

All endpoints under `/api/v1/studio/*`, authenticated
(`@is_authenticated()` / `@user_session()`), ownership-aware. Proposed
surface (final routes belong to the spec):

- **Agents** — `POST /studio/agents` creates a simple agent (registered into
  `AgentRegistry`; `persist: true` also writes the YAML definition into
  `AGENTS_DIR/agents/<category>/<name>.yaml`); `GET /studio/agents[/{name}]`
  lists/reads (merging registry + DB views like `ChatbotHandler._get_all`);
  `POST /studio/agents/{name}/reload` re-reads YAML/identity/skills/kb and
  swaps the shared registered instance; `DELETE` for factory-origin agents.
- **Drafts** — the meta-agent (or the user directly) saves generated Python
  agent files as drafts (`AGENTS_DIR/_drafts/<name>.py`);
  `GET /studio/drafts`, `GET /studio/drafts/{name}` (content + validation
  report), `POST /studio/drafts/{name}/activate` moves the file into
  `AGENTS_DIR/` and imports+registers it; activation is the only path from
  generated code to live code.
- **Meta-agent** — `POST /studio/assistant` converses with the AgentStudio
  agent (default `AnthropicClient`, Opus tier, BYOK-aware). It can scaffold
  Python agents inheriting any catalog base class (→ drafts), create
  YAML-based agents, and author skill files (frontmatter-validated) and KB
  files on natural-language request.
- **Files** — `GET/PUT/DELETE /studio/agents/{name}/files/{kind}/{filename}`
  for `kind ∈ {identity, kb, skills}`; identity restricted to the five
  canonical names; skills validated with `parse_skill_file` before write;
  responses include whether a reload is needed to take effect.
- **Testing** — `POST /studio/agents/{name}/test/ask` (LLM path, session
  test-instance semantics like `BotConfigTestHandler`);
  `POST /studio/tools/{slug}/execute` (deterministic `tool.execute(**kwargs)`
  with args); `POST /studio/agents/{name}/tools` assigns a tool/toolkit
  (registered via `bot.tool_manager.register_toolkit(...)`); vector-store
  retrieval tests delegate to the existing stores API.
- **Toolkit surfaces** — `GET /studio/toolkits/{slug}/schema` returns the
  configuration schema (constructor params → JSON schema) starting with
  `LLMWikiToolkit` (incl. `WikiConfig.storage_dir` — "in which directory the
  LLM wiki starts"), `DatasetManager`, `InfographicToolkit`;
  `POST /studio/agents/{name}/toolkits` assigns a configured toolkit.
- **Scheduler** — reuse `GET/POST/PATCH/DELETE
  /api/v1/parrot/scheduler/schedules*`; add `PATCH action="run_now"` and a
  last-execution-result read.
- **Vector stores** — reuse `POST/PUT/PATCH /api/v1/ai/stores` for
  create/upload/test; Studio adds only agent-assignment
  (`vector_store_config` update + reload).
- **BYOK** — `POST /studio/keys` stores a provider API key in the user's
  encrypted vault; `GET /studio/keys` lists (masked); `DELETE` removes.
  Test runs resolve the caller's key through the broker when present.
- **Catalogs** — `GET /studio/catalog/base-classes` (agent base classes +
  public configurable attributes), `/catalog/llm-clients`
  (`SUPPORTED_CLIENTS`), `/catalog/tools` (reuse `_build_catalog`),
  `/catalog/vector-stores`, `/catalog/skills/{agent}`.

### Internal Behavior

- **Thin handlers, fat managers**: handlers validate payloads (Pydantic),
  resolve session/owner, and delegate. New primitives land where they
  belong: `AgentRegistry` gains `unregister(name)` and a
  reload-safe re-registration path; `BotManager` gains
  `reload_agent(name)` that evicts `self._bots[name]` and the old
  `BotMetadata._instance`, then rebuilds from YAML/definition/DB.
- **Draft pipeline**: save → AST parse (syntax) → import-whitelist check
  (only `parrot.*`, `parrot_tools.*`, stdlib allowlist) → detect exactly one
  `AbstractBot` subclass → validation report persisted next to the draft.
  Activate → move file into a registry discovery path → import via the
  existing `_import_module_from_path` machinery → decorator/explicit
  registration → owner recorded.
- **Meta-agent**: an `Agent` subclass with authored composite skills
  (agent-builder, skill-writer, kb-writer) and tools that write ONLY into
  the draft store / asset directories (never directly into live code),
  mirroring the HITL gate of `finalize_agent_registration`. Default LLM
  Anthropic Opus tier; per-user BYOK key honored.
- **BYOK resolution**: key stored AES-GCM-encrypted (vault master keys),
  hot copy in the Redis session vault; a `CredentialBroker` resolver exposes
  it; agent test-instantiation passes it as `api_key` to `LLMFactory.create`.
  Keys are never returned in plaintext by any GET.
- **Reload semantics**: replace-in-registry. In-flight requests holding the
  old instance finish on it; new `get_instance()` calls get the new one.
  Old singletons get their `cleanup()`/`close()` invoked best-effort.

### Edge Cases & Error Handling

- **Draft fails validation** → draft saved anyway, `validation.passed=false`
  with per-error line numbers; activation refused (409) until clean.
- **Activate name collision** with an existing registry agent → 409 unless
  `replace=true` and caller owns the existing agent.
- **Reload of an agent mid-conversation** → old instance serves in-flight
  calls; document that memory/working-state of the old instance is not
  migrated. Reload of a DB-origin agent re-reads `BotModel`.
- **Reload failure** (bad YAML, import error) → old instance stays
  registered; 422 with the loader error; never leave the name unregistered.
- **File CRUD**: path traversal (`..`, absolute paths, symlinks) → 400;
  unknown identity filename → 400 listing the five canonical names; skill
  frontmatter invalid → 422 with parser message; deleting a file that the
  live agent uses → allowed, flagged `reload_required`.
- **BYOK**: missing vault master keys (`navigator_session` misconfigured)
  → 503 with a clear operator message; key for unsupported provider → 400
  against `SUPPORTED_CLIENTS`; test run with revoked/invalid key → surface
  the provider auth error, do not fall back silently to the server key.
- **Tool deterministic execution**: toolkit constructors with required deps
  that the server cannot supply (e.g. `InfographicToolkit.artifact_store`)
  are wired from app context where available; otherwise the schema endpoint
  marks them `server_managed` and execute returns 422 listing missing deps.
- **Scheduler run-now** on a paused/disabled job → runs once without
  changing its schedule state; concurrent run-now on the same job → 409.
- **Ownership**: non-owner mutation attempts → 403 via the PBAC evaluator
  when configured (`_PBACHandlerMixin` fail-open pattern preserved for
  installs without a PDP, but ownership checks still enforced from session).

---

## Capabilities

### New Capabilities
- `agentstudio-management`: the `/api/v1/studio/*` handler namespace
  (agents, drafts, files, testing, catalogs, keys) — this spec.
- `agent-draft-activation`: draft store + static validation + explicit
  activate pipeline for generated Python agents.
- `agent-hot-reload`: registry/manager primitives to unregister and swap a
  registered agent instance at runtime.
- `studio-meta-agent`: the AgentStudio agent + its authored skills
  (agent-builder, skill-writer, kb-writer).
- `byok-llm-keys`: per-user encrypted LLM API keys + CredentialBroker
  resolver + client-build integration.
- `scheduler-run-now`: immediate trigger + last-execution-result on the
  existing scheduler handler.
- `toolkit-config-surfaces`: config-schema introspection + assignment for
  `LLMWikiToolkit`, `DatasetManager`, `InfographicToolkit`.

### Modified Capabilities
- `vectorstore-handler-api` (FEAT existing): consumed as-is; possible small
  addition for agent-assignment convenience.
- `unified-credential-broker` (FEAT-264): gains an `llm_api_key` resolver.
- Scheduler handler (`handlers/scheduler.py`): gains `run_now` action.
- `registry.create_agent_definition`: must be fixed to round-trip the full
  `BotConfig` (today it drops `toolkits`, `prompt`, `vector_store`, `tags`,
  `policies`, `mcp_servers`, `priority`, `at_startup`, `config`).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/` (new) | new package | all Studio handlers |
| `packages/ai-parrot/src/parrot/registry/registry.py` | modifies | add `unregister`, reload-safe re-registration; fix `create_agent_definition` field loss |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | extends | `reload_agent(name)`; register studio routes in `BotManager.setup` |
| `packages/ai-parrot-server/src/parrot/handlers/scheduler.py` | extends | `run_now` action + last-result |
| `packages/ai-parrot-server/src/parrot/handlers/credentials.py` pattern | extends | BYOK key kind reusing vault helpers (likely a sibling handler, not edits) |
| `packages/ai-parrot/src/parrot/auth/broker.py` | extends | new resolver type for user LLM keys |
| `packages/ai-parrot/src/parrot/bots/factory/` | depends on / extends | meta-agent reuses builders + HITL finalize |
| `parrot/skills/parsers.py`, `skills/file_registry.py` | depends on | skill file validation + discovery |
| `parrot/bots/prompts/identity.py`, `bots/mixins/identity.py` | depends on | identity file contract + hot-reload seam |
| `parrot/tools/discovery.py`, `parrot_tools.TOOL_REGISTRY` | depends on | tool catalogs |
| `parrot/clients/factory.py` | depends on | LLM client catalog + BYOK `api_key` pass-through |
| `handlers/stores/` (VectorStoreHandler) | depends on | store create/upload/test reused as-is |
| `agents/` (AGENTS_DIR) on-disk layout | extends | adds `_drafts/`; formalizes `<agent>/{identity,kb,skills}/` |
| DB | none new | no new tables in recommended option (drafts on filesystem; keys in existing vault/DocumentDB) |

No breaking changes to existing routes. Deployment: no new services; new
routes registered inside `BotManager.setup(app)`.

---

## Code Context

### User-Provided Code

None — the user provided requirements prose only (see Problem Statement).

### Verified Codebase References

All verified 2026-08-27 against the working tree (branch `dev`). Server
package root: `packages/ai-parrot-server/src/parrot/`; core package root:
`packages/ai-parrot/src/parrot/`.

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/registry/registry.py
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
        # default dir AGENTS_DIR/'agents' (:967); rglob("*.yaml"); requires top-level `agent:` key
    def create_agent_definition(self, config: BotConfig,
                                category: str = "general") -> Path: ...  # :1053
        # writes AGENTS_DIR/agents/<category>/<name>.yaml; yaml.dump at :1086
        # DROPS: toolkits, prompt, vector_store, tags, policies, mcp_servers,
        #        at_startup, priority, config  ← must fix for Studio round-trip
    def delete_factory_agent(self, name: str) -> tuple[bool, str]: ...  # :1090
        # refuses unless bot_config.origin == "factory"; unlinks file, pops registry
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
```

```python
# From packages/ai-parrot/src/parrot/registry/__init__.py:7-12
agent_registry = AgentRegistry(agents_dir=AGENTS_DIR,
                               extra_agent_dirs=[PLUGINS_DIR / "agents"])
register_agent = agent_registry.register_bot_decorator

# From packages/ai-parrot/src/parrot/conf.py:175
AGENTS_DIR = config.get('AGENTS_DIR', fallback=BASE_DIR.joinpath('agents'))
# mkdir'd if missing; inserted at sys.path[0] (:181-189)
```

```python
# From packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:  # :109
    def __init__(self, enable_database_bots=ENABLE_DATABASE_BOTS,
                 enable_crews=ENABLE_CREWS, enable_registry_bots=ENABLE_REGISTRY_BOTS,
                 enable_swagger_api=ENABLE_SWAGGER) -> None: ...  # :118
    # self.registry: AgentRegistry = agent_registry  (:150, global singleton)
    async def load_bots(self, app: web.Application) -> None: ...  # :336
        # registry.setup(app) :352 → load_modules() :355 → discover_config_agents() :358
        # → load_agent_definitions(AGENTS_DIR/'agents') :364-366 (guarded is_dir())
        # → instantiate_startup_agents :368 → _load_database_bots :376
    def setup(self, app: web.Application) -> web.Application: ...  # :1686
        # self.app['bot_manager'] = self  (:1702) — how handlers reach the manager
        # ~55 router.add_view calls :1709-:2037 — Studio routes register here
    async def create_ephemeral_user_bot(self, user_id=None, config=None,
        uploaded_paths=None, *, owner_id: Optional[str] = None,
        owner_kind: str = "user", ttl_seconds: int = 86400): ...  # :949 (TASK-1388)
    def remove_bot(self, name): ...  # :811 — del self._bots[name]; keeps class
    # NOTE: no reload_agent / restart primitives exist (verified) — Studio adds them
```

```python
# From packages/ai-parrot-server/src/parrot/handlers/bots.py
class ChatbotHandler(_PBACHandlerMixin, AbstractModel):  # :424
    model = BotModel; pk = 'chatbot_id'  # :438-440; no class-level auth decorator
    async def get(self): ...     # :640  GET  /api/v1/bots[/ {id}]
    async def put(self): ...     # :756  create; storage ∈ {'database','registry'} (:780)
                                 # created_by server-set from session (:864-869)
    async def post(self): ...    # :1072 update
    async def delete(self): ...  # :1247 delete (DB agent only)
    async def _provision_vector_store(self, bot, vector_store_config: dict) -> dict: ...  # :910
# Registered: manager.py:1952 — ChatbotHandler.configure(self.app, '/api/v1/bots')
```

```python
# From packages/ai-parrot-server/src/parrot/handlers/testing_handler.py:29
class BotConfigTestHandler(BaseView):
    # PUT  /api/v1/agents/test/{agent_name} — create test agent session   (:76)
    # POST /api/v1/agents/test/{agent_name} — send query to test agent    (:128)
    # DELETE                                — stop test session           (:228)
# Route: manager/manager.py:2007 — nearest existing Studio test-run surface

# From packages/ai-parrot-server/src/parrot/handlers/agents/factory.py:107
class AgentFactoryHandler(BaseView):
    async def post(self) -> web.Response: ...  # :110
# Route manager.py:1835 — POST /api/v1/agents/factory (NL → drafted+registered agent)
# Builders: parrot/bots/factory/builders/{rag_builder,tool_agent_builder,clone_builder}.py

# From packages/ai-parrot/src/parrot/bots/factory/tools/finalize.py
async def finalize_agent_registration(definition: AgentDefinition,
                                      category: str = "general") -> Dict[str, Any]: ...  # :31
# stamps origin="factory" (:41-46), writes YAML, re-scans dir via
# agent_registry.load_agent_definitions(yaml_path.parent) (:51); HITL-gated @tool (:64)
```

```python
# From packages/ai-parrot-server/src/parrot/handlers/scheduler.py
class SchedulerJobsHandler(BaseView):  # :53 "CRUD handler for scheduler jobs
                                       #  persisted in APScheduler and Postgres"
    # manager property → request.app["scheduler_manager"] (:61-66)
    async def get(self) -> web.Response: ...    # :71
    async def post(self) -> web.Response: ...   # :91  (201)
    async def patch(self) -> web.Response: ...  # :123 action ∈ {"pause","resume","update"} (:132-139)
    async def delete(self) -> web.Response: ... # :148
# Routes (scheduler/manager.py:1704-1719): /api/v1/parrot/scheduler/schedules[,/{schedule_id}],
#   /callbacks, POST /restart

# From packages/ai-parrot-server/src/parrot/scheduler/models.py:7
class AgentSchedule(Model):  # asyncdb Model
    class Meta:  # :59-64
        driver = 'pg'; name = "agents_scheduler"; schema = "navigator"
# POST payload keys (handlers/scheduler.py:98-112): agent_name*, schedule_type*,
#   schedule_config*, prompt, method_name, created_by, created_email, metadata,
#   agent_id, is_crew, send_result, scheduler_type, callbacks
```

```python
# From packages/ai-parrot-server/src/parrot/handlers/stores/handler.py
@is_authenticated()
@user_session()
class VectorStoreHandler(BaseView):  # :35-37
    # POST  /api/v1/ai/stores — create/prepare collection        (:347)
    # PUT   /api/v1/ai/stores — load data (multipart/JSON/URLs)  (:529)
    # PATCH /api/v1/ai/stores — test search (body: query)        (:440)
    # GET   .../jobs/{job_id} — job status                        (:248)
    @classmethod
    def setup(cls, app: web.Application) -> None: ...  # :58 self-registration idiom
```

```python
# From packages/ai-parrot-server/src/parrot/handlers/credentials.py
@is_authenticated()
@user_session()
class CredentialsHandler(BaseView):  # :69-71
    COLLECTION: str = "user_credentials"      # :83 (DocumentDB)
    SESSION_PREFIX: str = "_credentials:"     # :84 (Redis session vault hot copy)
    # GET/POST /api/v1/users/credentials; GET/PUT/DELETE .../{name}
def setup_credentials_routes(app: web.Application) -> None: ...  # :506

# Crypto (AES-GCM via navigator_session — NOT Fernet):
# packages/ai-parrot/src/parrot/security/credentials_utils.py:19
def encrypt_credential(credential: dict, key_id: int, master_key: bytes) -> str: ...
def decrypt_credential(encrypted: str, master_keys: dict[int, bytes]) -> dict: ...  # :52
# navigator_session.vault.config: load_master_keys() -> dict[int, bytes]; get_active_key_id()
# Transparent PG column encryption: handlers/models/_encrypted_field.py (seal/unseal)

# From packages/ai-parrot/src/parrot/auth/broker.py
class CredentialBroker: ...                 # :326  (FEAT-264)
class _VaultStaticKeyResolver(CredentialResolver): ...  # :276
# bound on the tool manager at bots/abstract.py:1644 — self.tool_manager.set_broker(broker)
```

```python
# From packages/ai-parrot/src/parrot/clients/factory.py
SUPPORTED_CLIENTS = {...}  # :106 — keys incl. claude, anthropic, bedrock, google,
                           # openai, groq, grok, zai, openrouter, nvidia, moonshot,
                           # local, ollama, vllm, claude-agent, codex-agent, ...
class LLMFactory:  # :159
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]: ...  # :169
    @staticmethod
    def create(llm: str, model_args: Optional[Dict[str, Any]] = None,
               tool_manager: Optional[Any] = None, **kwargs) -> AbstractClient: ...  # :191
# NOTE: parrot.clients.__init__ does NOT re-export SUPPORTED_CLIENTS/LLMFactory —
# import from parrot.clients.factory.

# From packages/ai-parrot/src/parrot/clients/claude.py
class AnthropicClient(AbstractClient):  # :67
    _default_model: str = 'claude-sonnet-4-5'  # :73 (class attr, no DEFAULT_MODEL const)
    def __init__(self, api_key: str = None, base_url="https://api.anthropic.com",
                 backend: AnthropicBackend = "direct", ..., **kwargs): ...  # :79
    # `model` is NOT an explicit param — flows via **kwargs to clients/base.py:315
    # api_key fallback: config.get('ANTHROPIC_API_KEY')  (:120)
```

```python
# From packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager(MCPToolManagerMixin):  # :233
    def register_toolkit(self, toolkit: Union[str, "AbstractToolkit", type],
                         **kwargs) -> List[AbstractTool]: ...  # :1008
    def register_tool(self, tool=None, name=None, description=None,
                      input_schema=None, function=None) -> None: ...  # :718
    def get_tool(self, tool_name): ...   # :1215
    def list_tools(self) -> List[str]: ...  # :1235
    def unregister_tool(self, tool_name) -> bool: ...  # :1257
# Agent exposes it as `self.tool_manager` (bots/abstract.py:386).
# NO AbstractBot.add_tool()/add_toolkit() wrappers exist — go through tool_manager.

# From packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):  # :235
    async def execute(self, *args, **kwargs) -> ToolResult: ...  # :797 (public wrapper)
    async def _execute(self, **kwargs) -> Any: ...  # :490 (@abstractmethod)

# Tool enumeration:
# packages/ai-parrot-tools/src/parrot_tools/__init__.py:12 — TOOL_REGISTRY (207 slugs → dotted paths)
# packages/ai-parrot/src/parrot/tools/discovery.py —
#   discover_from_registry() :31, discover_all() :108, resolve_class(dotted) :139
# Existing endpoint: handlers/tools_catalog.py:85 ToolCatalogHandler
#   (route /api/v1/tools/catalog, manager.py:1798); _build_catalog() :44
```

```python
# Identity files — packages/ai-parrot/src/parrot/bots/prompts/identity.py
IDENTITY_FILES: tuple[str, ...] = ("role", "goal", "capabilities",
                                   "backstory", "rationale")  # :27  (five .md files)
def load_identity(directory, *, escape_placeholders: bool = False) -> IdentityFields: ...  # :51

# packages/ai-parrot/src/parrot/bots/mixins/identity.py
class IdentityMixin:  # :40 — enable_identity: bool = False; identity_dir = None
    def _build_prompt(self, *args, **kwargs): ...  # :202 hot-reload seam:
        # re-runs load_identity each call, swaps builder if fields differ
# Only in-repo adopter: agents/porygon.py:29-30

# KB files — packages/ai-parrot/src/parrot/bots/stores/local.py
def _get_agent_kb_directory(self) -> Optional[Path]: ...  # :41
    # Path(AGENTS_DIR) / safe_name / 'kb'  (:56); *.md + *.txt (:20)
async def configure_local_kb(self) -> None: ...  # :59
# invoked from bots/abstract.py:1508-1510 when self._use_local_kb

# Skills — packages/ai-parrot/src/parrot/skills/
def parse_skill_file(file_path: Path) -> SkillDefinition: ...       # parsers.py:37
def parse_skill_directory(skill_dir: Path) -> SkillDefinition: ...  # parsers.py:109
# frontmatter: name*, description*, triggers* (key required; may be []),
#   version="1.0", category, priority=90; body ≤ MAX_TOKENS=1000 (models.py:76)
class SkillFileRegistry:  # file_registry.py:17
    def __init__(self, skills_dir: Path, learned_dir: Optional[Path] = None): ...  # :29
# per-agent dirs: AGENTS_DIR/{agent_id}/skills[/learned] (skills/mixin.py:141)
```

```python
# Toolkit config surfaces
# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:54 (core, NOT parrot_tools)
class LLMWikiToolkit(AbstractToolkit):
    tool_prefix: str = "wiki"  # :81
    def __init__(self, pageindex_toolkit, graphindex_toolkit, okf_toolkit,
                 config: WikiConfig, agent_id: str = "agent",
                 store: Optional[BaseWikiStore] = None, **kwargs) -> None: ...  # :83
# WikiConfig (knowledge/wiki/models.py:52): wiki_name* (:83),
#   storage_dir: Path* (:84 — the wiki plane root directory),
#   source_dir (:85, default {storage_dir}/sources),
#   storage_backend: Literal["sqlite","memory","arangodb"]="sqlite" (:112)

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:501 (core)
class DatasetManager(AbstractToolkit):
    def __init__(self, df_prefix="df", generate_guide=True,
                 include_summary_stats=False, auto_detect_types=True,
                 policy_guard=None, dataplane_guard=None,
                 usage_rules=None, **kwargs): ...  # :549
# Existing handler: handlers/datasets.py:141 DatasetManagerHandler(BaseView)

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py:178 (core)
class InfographicToolkit(AbstractToolkit):
    def __init__(self, *, artifact_store: ArtifactStore, template_dirs=None,
                 templates=None, emit_a2ui=False, recipe_store=None,
                 recipe_runner=None, dataset_manager=None, **kwargs) -> None: ...  # :211
# artifact_store REQUIRED, keyword-only → cannot be zero-arg instantiated;
# server wires it from app['artifact_store'] (manager/manager.py:2157)
```

```python
# Handler base facilities — navigator (navigator-api 3.2.2, installed)
# navigator/views/base.py:619 — class BaseView(CorsViewMixin, BaseHandler, web.View)
# navigator/views/base.py:42  — class BaseHandler(ABC)
def json_response(self, response=None, reason=None, headers=None,
                  status: int = 200, ...): ...          # base.py:144
async def session(self): ...                            # base.py:89 (get_session(request))
async def get_userid(self, session, idx='user_id') -> int: ...  # base.py:99
async def post_data(self) -> dict: ...                  # base.py:673
def post_init(self, *args, **kwargs): ...               # base.py:79 (logger hook)
@classmethod
def setup(cls, app, route: str) -> None: ...             # base.py:635
# navigator/views/abstract.py:190 — AbstractModel.configure(cls, app, path, **kwargs)
#   registers path AND catch-all r"{url}/{{id:.*}}" (:224-226) — route-order sensitive
# Auth decorators: from navigator_auth.decorators import is_authenticated, user_session
```

```python
# Agent base classes catalog (packages/ai-parrot/src/parrot/bots/)
# abstract.py:187 AbstractBot; base.py:69 BaseBot; basic.py:3 BasicBot;
# chatbot.py:30 Chatbot; agent.py:29 BasicAgent; agent.py:1236 Agent;
# data.py:355 PandasAgent; document.py:104 DocumentAgent; search.py:45 WebSearchAgent;
# chrome.py:290 WebAgent; mcp.py:11 MCPAgent; a2a_agent.py:6 A2AAgent;
# info.py:37 InfoAgent (lazy); voice.py:87 VoiceBot (lazy)
# bots/__init__.py:9 __all__ = ("AbstractBot","Agent","BaseBot","BasicAgent",
#   "BasicBot","Chatbot","InfoAgent","VoiceBot","WebAgent","WebSearchAgent")
# LLM declaration: abstract.py:283 llm kwarg; :826 _resolve_llm_config
#   (instance | class | model_config dict | "provider:model" | provider+model | defaults)
```

```python
# Agent scaffolding CLI (existing .py writer into AGENTS_DIR)
# packages/ai-parrot/src/parrot/setup/scaffolding.py:207
def scaffold_agent(agent_config, cwd) -> Path: ...  # writes AGENTS_DIR/<module>.py (:241-244)
```

#### Verified Imports

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
```

#### Key Attributes & Constants

- `app['bot_manager']` → `BotManager` (manager/manager.py:1702)
- `app['scheduler_manager']` → `AgentSchedulerManager` (handlers/scheduler.py:63)
- `app['artifact_store']` → ArtifactStore for InfographicToolkit (manager.py:2157)
- `AbstractBot.tool_manager` → `ToolManager` (bots/abstract.py:386)
- `AGENTS_DIR` → Path, default `BASE_DIR/agents`, on `sys.path[0]` (conf.py:175-189)
- `BotModel.Meta` → table `navigator.ai_bots` (models/bots.py:393-395; conf.py:115-116)
- `AgentSchedule.Meta` → table `navigator.agents_scheduler` (scheduler/models.py:59-64)
- `SkillDefinition.MAX_TOKENS = 1000` (skills/models.py:76)
- `_AGENT_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")` (handlers/bots.py:85)
- `ClaudeModel` enum incl. `FABLE_5 = "claude-fable-5"`, `OPUS_4_5 = "claude-opus-4-5-20251101"` (models/claude.py:13,24)

### Does NOT Exist (Anti-Hallucination)

- ~~Any "Agent Studio"/"playground" handler, route, class, or spec~~ — grep
  for "studio" hits only Copilot Studio (a2a), Odoo Studio, LM Studio,
  `google_ai_studio` observability. Greenfield namespace.
- ~~`AgentRegistry.unregister(name)`~~ — no per-agent unregister; only
  `delete_factory_agent` (origin-gated) and `clear_registry()` (test-only).
- ~~Any agent reload/restart method or endpoint~~ — no `reload_agent`,
  `restart_bot`, hot-reload anywhere in `manager/` or `handlers/`;
  `importlib.reload` never called in `registry/`/`manager/`.
- ~~Draft/activate lifecycle~~ — the only gate is `BotConfig.enabled`; no
  `draft` state anywhere.
- ~~A loader for `AGENTS_DIR/<name>/config.yaml`~~ — `agents/navigator/
  config.yaml` is read by NO code path; the loaded format is the
  `agent:`-keyed YAML of `load_agent_definitions`. There is also no
  `NavigatorAgent` class.
- ~~`agents/agents/` directory in this repo~~ — `load_bots` Step 2b is
  currently a no-op; `create_agent_definition` creates it on first write.
- ~~Fernet / `cryptography.fernet` / HashiCorp Vault~~ — zero matches in
  `packages/*/src`; house crypto is AES-GCM via `navigator_session.vault`.
- ~~An LLM-API-key vault table or handler~~ — `CredentialsHandler` stores
  *database connection* credentials (`driver` + `params`) in DocumentDB
  collection `user_credentials`; no `api_keys`/`user_llm_keys` table exists.
- ~~`WikiToolkit`~~ — the class is `LLMWikiToolkit`, in core
  `parrot/knowledge/wiki/toolkit.py`, NOT in `parrot_tools`, and NOT in
  `TOOL_REGISTRY` (cannot be instantiated by slug; requires three toolkit
  deps + `WikiConfig`).
- ~~`InfographicToolkit` in `TOOL_REGISTRY`~~ — absent; requires
  `artifact_store` (keyword-only) so the generic zero-arg path fails.
- ~~`AbstractBot.add_tool()` / `add_toolkit()` / `register_toolkit()`~~ —
  only `register_tools()` (abstract.py:4019); toolkit registration goes
  through `bot.tool_manager.register_toolkit(...)`.
- ~~`AnthropicClient(model=...)` explicit param / `DEFAULT_MODEL` const~~ —
  model flows via `**kwargs`; default is class attr `_default_model`.
- ~~`parrot.clients.SUPPORTED_CLIENTS`~~ — not re-exported; import from
  `parrot.clients.factory`.
- ~~`handlers/__init__.py` in the server package / central `setup_routes()`~~
  — wiring is split across root `app.py:configure()`, `BotManager.setup()`,
  and per-handler `setup`/`configure`/`setup_*_routes` idioms.
- ~~Scheduler `run_now`~~ — `SchedulerJobsHandler.patch` supports only
  `pause|resume|update`; there is a global `POST /restart` but no per-job
  immediate trigger or last-execution-result endpoint.
- ~~Full-fidelity YAML round-trip~~ — `create_agent_definition` drops
  `toolkits`, `prompt`, `vector_store`, `tags`, `policies`, `mcp_servers`,
  `priority`, `at_startup`, `config`.

---

## Parallelism Assessment

- **Internal parallelism**: Good after a small sequential core. The
  registry/manager primitives (unregister + reload + YAML round-trip fix)
  and the `handlers/studio/` package scaffold must land first; after that,
  Files CRUD, Catalog GETs, BYOK, Scheduler run-now, Toolkit surfaces,
  Testing endpoints, and the Meta-agent are mutually independent modules
  touching disjoint files.
- **Cross-feature independence**: Touches `registry.py`, `manager.py`, and
  `handlers/scheduler.py`, which are hot files for other in-flight work —
  check `/sdd-status` for open features over `manager/manager.py` before
  cutting the worktree. No conflicts with the (completed) FEAT-149/-049/
  -264/-1388 lineages this builds on.
- **Recommended isolation**: `per-spec` (one worktree, tasks sequential) —
  the shared scaffold + `BotManager.setup` route-registration block is a
  merge magnet; parallel worktrees would collide there repeatedly.
- **Rationale**: dependency shape is a diamond (core primitives → many
  independent modules → route wiring); within one worktree the independent
  middle tier can still be separate tasks/commits, but separate worktrees
  buy little and cost repeated conflicts on `manager.py`.

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus*: `type: feature`, `base_branch: dev`.
- [x] Deliverable scope — *Owner: Jesus*: backend API only; interactive UI is a separate later spec.
- [x] Is the AgentStudio meta-agent in this spec? — *Owner: Jesus*: yes, included (HTTP surface + meta-agent + its skills).
- [x] BYOK storage — *Owner: Jesus*: persisted encrypted per-user, reusing the existing vault (`navigator_session` AES-GCM) + a new `CredentialBroker` resolver; NOT a new Fernet table.
- [x] Safety gate for generated Python agents — *Owner: Jesus*: explicit activate step; static validation on save, import+register only on user activation.
- [x] Reload scope — *Owner: Jesus*: reload swaps the shared registered agent (all consumers get new behavior immediately).
- [x] Scheduler depth — *Owner: Jesus*: CRUD + run-now/test with last execution result.
- [x] Access model — *Owner: Jesus*: any authenticated user; ownership-aware (creator owns; owners/admins modify).
- [ ] Relationship to `AgentFactoryHandler` (`/api/v1/agents/factory`): does the Studio meta-agent **replace** it (route kept as alias), or do both meta-agents coexist? Recommendation: Studio agent absorbs it, sharing `parrot/bots/factory/` builders. — *Owner: Jesus*
- [ ] Default model id for the meta-agent: notes say "Opus-5"; `ClaudeModel` has `FABLE_5`/`OPUS_4_5`. Pin which id, and make it env-overridable (`STUDIO_AGENT_MODEL`)? — *Owner: Jesus*
- [ ] Canonical agent-YAML schema for Studio writes: the `agent:`-keyed definition format (the one actually loaded) — confirm; and does fixing `create_agent_definition` field loss belong to this feature's first task or a separate prerequisite fix? — *Owner: Jesus*
- [ ] `LLMWikiToolkit` server-side construction: who builds its three toolkit deps (`pageindex_toolkit`, `graphindex_toolkit`, `okf_toolkit`) when a user assigns a wiki surface — reuse the bot's `_pageindex_toolkit`/`_graphindex_toolkit` capture or construct fresh from `WikiConfig`? — *Owner: dev during spec*
- [ ] Draft store location/state: filesystem `AGENTS_DIR/_drafts/` + JSON state file vs. a small DB table (auditability vs. zero-migration). — *Owner: Jesus*
- [ ] PBAC policy naming for `/api/v1/studio/*` (new resource ids for the PDP) and whether admins bypass ownership. — *Owner: Jesus*
- [ ] Deprecation signal for the old Bot Management surface: mark `/api/v1/bot_management` responses with a `Deprecation` header once Studio ships, or leave silent? — *Owner: Jesus*
