---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot-server, admin-ui, ai-parrot, ai-parrot-tools]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [agent-studio, toolkits, tool-config, json-schema, admin-ui, mcp, datasets, secrets]
---

# Feature Specification: Tool Configuration for Agent Studio

**Feature ID**: FEAT-593
**Date**: 2026-09-23
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 0.30.0 (tentative)
**Brainstorm**: `sdd/proposals/tool-configuration-agentstudio.brainstorm.md` (Option A, accepted)

---

## 1. Motivation & Business Requirements

### Problem Statement

Operators can pick *which* tools an agent has, but nowhere can they configure
*how* a toolkit is built for that agent. Original request (verbatim):

> Tool-configuration support para AgentStudio
> - configuración de atributos per-Tool (por ejemplo Jira Toolkit > Jira
>   workspace, o si pongo QuerySlugToolkit > ¿cuáles WS?)
>   si hay un endpoint que retorna todas las tools activas: crear una UI para
>   configurarlo
> :: Mover el actual dataset config (del DatasetManager) y el MCP config a
>    Agent Studio.

Today:

- **Admin UI agent form** (`/admin/agents/:name`, FEAT-475): the Capabilities
  tab is a checkbox list of tool *names* from `GET /api/v1/agent_tools`.
  `BotModel.tools` is `List[str]`, so a DB agent can say "jira" but never "jira
  against `https://troc.atlassian.net`, default project TROC". `JiraToolkit`
  falls back to env vars; `QuerysourceToolkit` gets no `programs` scope.
- **Agent Studio backend** (`/api/v1/astudio/*`, FEAT-467) exposes
  `GET /toolkits/{slug}/schema` (constructor introspection) and
  `POST /agents/{name}/toolkits` — but the assignment mutates only the live
  instance and answers `persisted: false`. Nothing in the SPA consumes `/astudio`.
- **YAML agents** declare `toolkits:` but the factory's toolkit loop is a `pass`
  stub, and the top-level `toolkits` / `mcp_servers` keys that
  `create_agent_definition` writes are **never read back** (the factory only
  reads `config.tools.toolkits` / `config.tools.mcp_servers`).
- **DB agents never register their `tools` column at build**:
  `BotManager._build_database_bot` passes `available_tools=bot_model.tools`, a
  kwarg nothing in `AbstractBot` consumes (verified 2026-09-23).
- **Dataset and MCP configuration live inside the chat** (`DataManagementModal`
  → `DatasetTab` / `MCPServerTab`), backed by per-user session state. Operators
  have no agent-level surface for either.

**Who is affected**: operators building agents in the Admin UI (primary), end
users needing their own Jira credentials / query-slug scope (secondary),
developers hand-editing YAML to wire toolkit params.

### Goals
- G1 — Persist per-toolkit parameters as **agent-level defaults** on the agent
  definition (DB JSONB column **and** YAML `toolkits:` entries), with one shared
  `ToolkitSpec` shape.
- G2 — Persist **per-user overrides** for params the operator marks
  `user_overridable`, applied on a **session** `ToolManager` view — the shared
  bot instance is never mutated by a user override.
- G3 — Secrets never land in JSON/YAML: `x-secret` params go to the per-user
  navigator-session vault (`parrot.security.vault_utils`), the config keeps only
  `secret_refs` + `vault_owner`, and every GET returns masked values.
- G4 — One **JSON Schema (Draft 2020-12) envelope** per toolkit drives the UI:
  Pydantic `*Config` models (`oneOf` discriminated unions for choice-shaped
  config such as `DatasetManager` datasources) where declared, constructor
  introspection lifted into the same shape otherwise.
- G5 — Dynamic options (Querysource `programs`, Jira `default_project`) via an
  optional toolkit hook, served by an agent-scoped, owner-gated endpoint.
- G6 — Admin UI: a new **Tools** tab on `/admin/agents/:name` (catalog + per-
  toolkit schema-driven drawer + Datasets and MCP sub-panels). The chat keeps a
  lighter per-user "My tool settings" surface.
- G7 — Fix the latent build-path bugs this feature depends on: dead YAML
  toolkit loop, unconsumed top-level `toolkits`/`mcp_servers`, unconsumed
  `available_tools` on DB agents.

### Non-Goals (explicitly out of scope)
- Reusable org-wide "toolkit profiles" (brainstorm Option C) — a second feature;
  `ToolkitSpec` stays open to a future `profile_ref` field.
- Collapsing `BotModel.tools` / `BotConfig.tools` into one aggregate model with a
  live-table migration (brainstorm Option B, rejected — see brainstorm).
- Persisting datasets beyond the spec: agent-level datasets are **in-memory
  only**, replayed on build/reload.
- Rewriting the existing per-user MCP (`MCPPersistenceService`) and per-user
  dataset (`/api/v1/agents/datasets/*`) flows.
- Editing `.py` (code) registry agents or YAML outside `AGENTS_DIR` — read-only.

---

## 2. Architectural Design

### Overview

**Option A — toolkit config on the agent definition + session-scoped override
layer**, extending the seams FEAT-467 and the MCP work already opened.

1. **One normalization boundary** (design research S1). Core
   `parrot.tools.spec` defines `ToolkitSpec` and `AgentMCPServerSpec`, plus
   `normalize_tooling(tools, toolkits, mcp_servers)` which turns every legacy
   input shape (bare strings in `tools`, strings or dicts in YAML top-level
   `toolkits`, strings in `ToolConfig.toolkits`, dicts in either `mcp_servers`
   list) into `(plain_tool_names, toolkit_specs, mcp_specs)`. A slug present
   both as a bare tool name and as a spec is emitted **once, as the spec**. Both
   the DB path (`BotManager._build_database_bot`) and the YAML factory call it.
2. **Deferred async build.** `AbstractBot.__init__` → `_initialize_tools` is
   synchronous, but vault reads and `DatasetManager.add_*` are async. So
   `_initialize_tools` only *records* `ToolkitSpec` entries, and a new
   `ToolInterface.apply_tooling_specs()` runs inside `AbstractBot.configure()`
   (right after `configure_conversation_memory()`). It hydrates secrets
   (`retrieve_vault_credential(spec.vault_owner, vault_name)`), resolves the
   class via `TOOL_REGISTRY` + `resolve_class` (never `ToolkitRegistry.get` —
   it filters on class names containing "Toolkit" and misses
   `dataset_manager`), passes only params the constructor accepts, and calls
   `tool_manager.register_toolkit(instance)`. It is idempotent (guarded flag),
   because `configure()` can be re-entered. A missing vault entry or a failing
   constructor skips that toolkit with a WARNING and never fails the boot.
   Agent-level MCP specs are hydrated the same way and registered with
   `add_mcp_server(MCPServerConfig(...))`.
3. **Datasets are the `dataset_manager` toolkit's params.**
   `DatasetManagerConfig` = constructor flags + `datasources:
   list[DatasourceSpec]` (a `kind`-discriminated union). The build pops
   `datasources`, constructs or reuses the manager, and calls
   `DatasetManager.replay_datasources(specs)`, which dispatches each kind to
   the existing `add_dataset` / `add_table_source` / `load_file` /
   `add_airtable_source` / `add_smartsheet_source` / `add_iceberg_source` /
   `add_mongo_source` / `add_deltatable_source` methods, building fresh sources
   each time (S3). When the bot already owns a `_dataset_manager` (PandasAgent),
   datasources replay into it and no second manager is registered. Otherwise
   the new manager is registered and assigned to `bot._dataset_manager`, so the
   chat's `_clone_agent_dm` copies it into each user's manager.
4. **Schema envelope** (S8, hard cut). `GET /astudio/toolkits/{slug}/schema`
   returns `{slug, class_name, source: "model"|"introspection", schema}` where
   `schema` is a Draft 2020-12 object schema. A toolkit with a `config_model`
   answers `config_model.model_json_schema()`, post-processed with vendor
   extensions. Otherwise `introspect_config_schema(cls)` lifts the constructor
   into `properties`/`required`. Extensions: `x-secret`, `x-user-overridable`
   (default toggle), `x-options` (dynamic options available), `x-ui-help`,
   `x-server-managed`. Secret classification is **name heuristics
   (`token`, `password`, `api_key`, `secret`, `dsn`, `credentials`,
   `access_token`, `private_key`) plus curated overlays plus an optional
   `secret_params` class attribute** (resolved by the user, 2026-09-23). Params
   whose type is not JSON-representable (objects, callables, resolvers) are
   marked `x-server-managed` and cannot be set.
5. **Persistence — single writer.** Only the Studio endpoints write
   `toolkit_config` / `mcp_servers`. `ChatbotHandler` create/update refuse those
   keys (400 `use_studio_endpoint`), because today its update loop
   `agent.set(key, val)` would store raw secrets (S9). A server-side
   `AgentToolingStore` validates params against the schema (Pydantic model when
   declared, else `jsonschema`), splits `x-secret` values into the vault under
   the **agent owner's** user id (`vault_owner`, S4), name
   `toolkit_{slug}_{agent}`, and writes either `BotModel.toolkit_config` (DB
   agents) or rewrites the exact YAML file at `metadata.file_path` (S10). The
   YAML must live under `AGENTS_DIR`, have a `bot_config`, and be named
   `{name}.yaml`. A PUT carrying the mask sentinel leaves that vault key
   untouched. Every successful write answers `reload_required: true`, and the
   UI offers **Reload** (`POST /agents/{name}/reload`) — there is no implicit
   reload.
6. **Per-user overrides.** `ToolkitConfigService` (DocumentDB
   `user_toolkit_configs`, keyed `(user_id, agent_id, slug)`) stores non-secret
   override params plus a vault ref under the **user's** id. Only params that
   are `user_overridable` **at save time** are accepted (otherwise 422). At
   build time only params overridable **now** are merged. A stale override
   (the operator later revoked overridability) is **kept but ignored**
   (resolved by the user, 2026-09-23).
7. **Session application — always on** (resolved by the user, 2026-09-23; no
   `enable_mcp_restore`-style flag). `AgentTalk._apply_user_toolkit_overrides`
   runs in the POST ask path (before PBAC tool filtering) and in the PATCH path
   (after MCP restore), for non-user bots. It builds the effective session view
   from `agent.tool_manager.clone()` (or the existing session TM), removes every
   tool whose `get_toolkit_owner()` is an instance of the overridden class,
   then registers a fresh instance built from `defaults ⊕ override` (S2). The
   session stores a marker `(tooling_revision, overrides_revision)`. A mismatch
   after an agent reload or an override save triggers a rebuild (S11).
8. **Dynamic options** (S7). `AbstractToolkit.config_options(param)` is async,
   optional, and raises `NotImplementedError` by default; it is excluded from
   LLM tool generation. `GET /astudio/agents/{name}/toolkits/{slug}/options/
   {param}` is owner-checked and PBAC-gated (`astudio:toolkits:options`). It
   builds the toolkit **only from the persisted spec** (hydrated secrets, never
   request-supplied URLs or credentials — no SSRF vector), calls the hook with a
   timeout, never registers the instance, and closes it afterwards. Jira
   implements `default_project`; Querysource implements `programs`. The UI
   enables the dynamic select once the toolkit has been saved, and falls back to
   free text on failure (502).

### User-Facing Behavior

**Operator — `/admin/agents/:name` → new "Tools" tab**
1. Lists every tool/toolkit the server knows (`listTools()` + `/astudio/catalog/
   tools`) with an on/off switch. A plain tool keeps today's behaviour (`tools:
   [...]`), and "just enable weather" stays one click.
2. Turning a **toolkit** on opens a drawer rendered from the schema envelope:
   typed inputs, defaults, required markers, `x-server-managed` params read-only
   ("wired by the server"), `x-secret` params as password fields (masked once
   saved, never echoed), and a **"users may override"** toggle per param.
3. `x-options` params render as a multi-select fed by the options endpoint once
   saved, with a free-text fallback.
4. **Save** persists agent defaults and shows "Reload required" with a **Reload
   agent** action. **Test** (optional) calls the existing live assignment
   (`POST /agents/{name}/toolkits`) and reports registered tool names or 422
   details.
5. **Datasets** sub-panel = the `dataset_manager` schema form: a **kind**
   selector (query slug · SQL · table · file · Airtable · Smartsheet · Iceberg ·
   Mongo · Delta) whose sub-form comes from the `oneOf` branch; saved as the
   toolkit's `datasources` param.
6. **MCP servers** sub-panel: the agent-level `mcp_servers` list (name,
   transport, url/command, allowed/blocked tools, headers, auth). Headers and
   auth values are secrets.
7. Registry agents with YAML under `AGENTS_DIR` get the same tab (writes go to
   the YAML). `.py` agents and YAML outside `AGENTS_DIR` show it read-only with
   an explanation.

**End user — chat → `DataManagementModal` → new "My tool settings" tab**
- Shows only toolkits with ≥1 currently-overridable param. Saving takes effect
  on the next request (the session marker is invalidated). Their secrets go to
  their own vault entries, and the operator never sees them.

### Component Diagram
```
Admin UI (TabsTools / SchemaForm / ToolkitDrawer / AgentMcpPanel)   Chat (MyToolkitSettings)
        │  lib/api/studio.ts                                                │
        ▼                                                                   ▼
/api/v1/astudio/toolkits/{slug}/schema ── config_schema() / introspect_config_schema()
/api/v1/astudio/agents/{name}/toolkits[/{slug}]  ─┐        /agents/{name}/toolkits/{slug}/me
/api/v1/astudio/agents/{name}/mcp-servers        ─┤                     │
/api/v1/astudio/agents/{name}/toolkits/{slug}/options/{param}          ▼
                                                  ▼          ToolkitConfigService (DocumentDB user_toolkit_configs)
                                  AgentToolingStore ── vault_utils (store/retrieve/delete)
                                   │            │
                     BotModel.toolkit_config    AgentRegistry.update_agent_tooling (YAML in place)
                     BotModel.mcp_servers
                                   │            │
                                   ▼            ▼
                          normalize_tooling()  (DB: BotManager._build_database_bot · YAML: factory)
                                   │
                                   ▼
             AbstractBot(tools=[..., ToolkitSpec], agent_mcp_servers=[AgentMCPServerSpec])
                                   │ configure()
                                   ▼
             ToolInterface.apply_tooling_specs() ── hydrate secrets ── register_toolkit / add_mcp_server
                                   │                                  └─ DatasetManager.replay_datasources
                                   ▼
             AgentTalk._apply_user_toolkit_overrides → session ToolManager (clone − slug tools + override)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `StudioToolkitsHandler` (`handlers/studio/toolkits.py`) | modifies | GET returns the schema envelope (hard cut); POST unchanged |
| `handlers/studio/__init__.py` | extends | new `add_view` routes under `STUDIO_PREFIX` |
| `BotModel` (`handlers/models/bots.py`) | modifies | `toolkit_config: dict`, `mcp_servers: list` (JSONB, additive) |
| `handlers/creation.sql` | extends | idempotent `ALTER TABLE … ADD COLUMN IF NOT EXISTS` |
| `ChatbotHandler` (`handlers/bots.py`) | modifies | refuse `toolkit_config`/`mcp_servers` in create/update |
| `BotManager._build_database_bot` (`manager/manager.py`) | modifies | `available_tools=` → normalized `tools=` + `agent_mcp_servers=` |
| `BotConfig` / factory / `create_agent_definition` (`registry/registry.py`) | modifies | widened `toolkits`, normalize, delete dead loop, new `update_agent_tooling` |
| `ToolInterface` (`interfaces/tools.py`) | modifies | record `ToolkitSpec`; new async `apply_tooling_specs()` |
| `AbstractBot.configure` (`bots/abstract.py`) | modifies | calls `apply_tooling_specs()`; pops `agent_mcp_servers` kwarg |
| `AbstractToolkit` (`tools/toolkit.py`) | extends | `config_model`, `secret_params`, `default_user_overridable`, `options_params` ClassVars; `config_schema()`; `config_options()`; exclusion tuple |
| `DatasetManager` (`tools/dataset_manager/tool.py`) | extends | `config_model = DatasetManagerConfig`; `replay_datasources()` |
| `JiraToolkit`, `QuerysourceToolkit`, `SlugCatalog` (`parrot_tools`) | extends | config models + `config_options` + `SlugCatalog.list_programs()` |
| `AgentTalk` (`handlers/agent.py`) | extends | `_apply_user_toolkit_overrides` in POST + PATCH paths |
| `parrot.security.vault_utils` | uses | store/retrieve/delete secrets |
| `scripts/generate_ts_types.py` | extends | Studio tooling models → `pnpm generate` |
| Admin UI form + chat modal | modifies / new | Tools tab, SchemaForm, panels, My tool settings |

### Data Models
```python
# packages/ai-parrot/src/parrot/tools/spec.py  (new)
SECRET_MASK: str = "********"

class ToolkitSpec(BaseModel):
    """Agent-level (or override) configuration of one toolkit."""
    model_config = ConfigDict(extra="forbid")
    slug: str
    params: dict[str, Any] = Field(default_factory=dict)          # non-secret only
    user_overridable: list[str] = Field(default_factory=list)
    secret_refs: dict[str, str] = Field(default_factory=dict)      # param -> vault_name
    vault_owner: str | None = None                                  # user id owning the vault entries

class AgentMCPServerSpec(BaseModel):
    """Agent-level MCP server; auth/header values live in the vault."""
    model_config = ConfigDict(extra="forbid")
    name: str
    transport: str = "http"
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    allowed_tools: list[str] | None = None
    blocked_tools: list[str] | None = None
    description: str | None = None
    auth_type: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)          # other non-secret MCPServerConfig kwargs
    secret_refs: dict[str, str] = Field(default_factory=dict)      # "headers"/"auth_config" -> vault_name
    vault_owner: str | None = None

class NormalizedTooling(BaseModel):
    tools: list[str]
    toolkits: list[ToolkitSpec]
    mcp_servers: list[AgentMCPServerSpec]

# packages/ai-parrot/src/parrot/tools/config_schema.py  (new)
class ConfigOption(BaseModel):
    value: str
    label: str

class ToolkitSchemaEnvelope(BaseModel):
    slug: str
    class_name: str
    source: Literal["model", "introspection"]
    schema_: dict[str, Any] = Field(alias="schema")

# packages/ai-parrot/src/parrot/tools/dataset_manager/config.py  (new)
class _DatasourceBase(BaseModel):
    name: str
    description: str | None = None
    metadata: dict[str, Any] | None = None
    is_active: bool = True
class QuerySlugDatasource(_DatasourceBase):  kind: Literal["query_slug"]; slug: str; permanent_filter: dict | None = None
class SqlDatasource(_DatasourceBase):        kind: Literal["sql"]; sql: str; driver: str; dsn: str | None = None; credentials: dict | None = None
class TableDatasource(_DatasourceBase):      kind: Literal["table"]; table: str; driver: str; dsn: str | None = None;
                                             credentials: dict | None = None; strict_schema: bool = True;
                                             permanent_filter: dict | None = None; allowed_columns: list[str] | None = None
class FileDatasource(_DatasourceBase):       kind: Literal["file"]; path: str   # .csv/.xls/.xlsx/.xlsm/.xlsb/.parquet
                                             delta_path: str | None = None  # parquet only; default Path(path).with_suffix('.delta')
class AirtableDatasource(_DatasourceBase):   kind: Literal["airtable"]; base_id: str; table: str; view: str | None = None; api_key: str | None = None
class SmartsheetDatasource(_DatasourceBase): kind: Literal["smartsheet"]; sheet_id: str; access_token: str | None = None
class IcebergDatasource(_DatasourceBase):    kind: Literal["iceberg"]; table_id: str; catalog_params: dict; factory: str = "pandas";
                                             credentials: dict | None = None; dsn: str | None = None
class MongoDatasource(_DatasourceBase):      kind: Literal["mongo"]; collection: str; database: str; credentials: dict | None = None;
                                             dsn: str | None = None; required_filter: bool = True
class DeltaTableDatasource(_DatasourceBase): kind: Literal["deltatable"]; path: str; table_name: str | None = None;
                                             mode: str = "error"; credentials: dict | None = None
DatasourceSpec = Annotated[Union[QuerySlugDatasource, SqlDatasource, TableDatasource, FileDatasource,
                                 AirtableDatasource, SmartsheetDatasource, IcebergDatasource,
                                 MongoDatasource, DeltaTableDatasource], Field(discriminator="kind")]
class DatasetManagerConfig(BaseModel):
    df_prefix: str = "df"
    generate_guide: bool = True
    include_summary_stats: bool = False
    auto_detect_types: bool = True
    usage_rules: str | None = None
    datasources: list[DatasourceSpec] = Field(default_factory=list)
# x-secret (json_schema_extra): dsn, credentials, api_key, access_token.
```
Secret values nested inside `datasources[i]` are split to the vault under
`toolkit_dataset_manager_{agent}` with keys `datasources.{i}.{field}`, and
`secret_refs` maps the same dotted key to the vault name.

### New Public Interfaces
See §3 Interface Skeletons. HTTP surface (all under `/api/v1/astudio`, all
`StudioError {message, code, details}` on failure):

| Method | Path | Behaviour |
|---|---|---|
| GET | `/toolkits/{slug}/schema` | envelope (hard cut of the `params` map) |
| GET | `/agents/{name}/toolkits` | `{agent, editable, reason?, toolkits: [ToolkitSpec (masked)], unavailable: [slug]}` |
| PUT | `/agents/{name}/toolkits/{slug}` | body `{params, user_overridable}` → `{agent, slug, reload_required: true, persisted: true}` |
| DELETE | `/agents/{name}/toolkits/{slug}` | removes spec + vault entry → `reload_required: true` |
| GET | `/agents/{name}/toolkits/{slug}/options/{param}` | `{options: [ConfigOption]}`; 404 unknown param, 409 not saved, 502 lookup failure |
| GET/PUT | `/agents/{name}/mcp-servers` | list of `AgentMCPServerSpec` (masked) / replace list → `reload_required: true` |
| GET/PUT/DELETE | `/agents/{name}/toolkits/{slug}/me` | per-user override (masked GET; PUT 422 on non-overridable params) |

Error codes: existing `invalid_json`, `invalid_request`, `not_found`,
`not_owner`, `unavailable`, `server_managed`, `invalid_params`,
`vault_unavailable` (503), plus new `read_only_definition` (409),
`not_overridable` (422), `not_configured` (409), `options_failed` (502),
`use_studio_endpoint` (400, on `ChatbotHandler`).
PBAC actions: `astudio:toolkits:persist`, `astudio:toolkits:options`,
`astudio:mcp:persist`, `astudio:toolkits:override`.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: tooling spec models | yes | Data Models + skeleton; `normalize_tooling` dedupe rule (spec wins) | — |
| M2: config-schema machinery | yes | envelope shape, extension names, heuristic list, exclusion tuple | — |
| M3: DatasetManager config + replay | yes | union fixed in §2; kind→method map fixed in skeleton | — |
| M4: DB persistence + guards | yes | 2 columns, ALTER text, 400 code, `tools=` fix | — |
| M5: deferred build path | no | — | touches `AbstractBot.configure` ordering + PandasAgent reuse; review-worthy |
| M6: registry YAML | yes | `update_agent_tooling` contract (in-place, atomic, containment) | — |
| M7: Studio agent-level API | no | — | largest surface: secret split, masking, YAML/DB branching, PBAC |
| M8: per-user override service + endpoints | yes | mirrors `MCPPersistenceService`; collection/key fixed | — |
| M9: session application | no | — | session TM swap semantics; revision marker |
| M10: Jira + Querysource config + options | yes | config models + hook contract fixed | — |
| M11: codegen | yes | model list fixed | — |
| M12: Admin UI Tools tab | no | — | UX composition of 4 new components |
| M13: Chat "My tool settings" | yes | one tab in `DataManagementModal` over `/me` endpoints | — |
| M14: docs | yes | three docs listed | — |

### Module 1: Tooling spec models + normalization + secret hydration
- **Path**: `packages/ai-parrot/src/parrot/tools/spec.py` (new)
- **Responsibility**: the one shape for toolkit/MCP config; normalize every
  legacy input; compute a stable revision hash; hydrate secrets from the vault.
- **Depends on**: `parrot.security.vault_utils` (existing)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/tools/spec.py  (new)
  from parrot.security.vault_utils import retrieve_vault_credential  # verified: security/vault_utils.py:135

  def toolkit_vault_name(slug: str, agent_name: str) -> str:
      """Return ``f"toolkit_{slug}_{agent_name}"`` (precedent: ``mcp_{server}_{agent}``)."""

  def mcp_vault_name(server: str, agent_name: str) -> str:
      """Return ``f"mcp_agent_{server}_{agent_name}"`` (distinct from per-user ``mcp_{server}_{agent}``)."""

  def normalize_tooling(
      tools: Sequence[Any] | None,
      toolkits: Sequence[str | dict[str, Any] | ToolkitSpec] | None = None,
      mcp_servers: Sequence[dict[str, Any] | AgentMCPServerSpec] | None = None,
      *,
      toolkit_config: dict[str, dict[str, Any]] | None = None,
  ) -> NormalizedTooling:
      """Merge every legacy shape into (tools, toolkit specs, mcp specs).

      Bare strings in ``toolkits`` become ``ToolkitSpec(slug=s)``; dicts are validated.
      ``toolkit_config`` is the DB JSONB map ``{slug: spec-dict}``. A slug that is both a
      plain tool name and a spec is emitted once, as the spec. Duplicate specs for one
      slug: the last one wins, logged at WARNING. Invalid entries are dropped with a WARNING.
      """

  def tooling_revision(toolkits: Sequence[ToolkitSpec], mcp_servers: Sequence[AgentMCPServerSpec]) -> str:
      """sha256 of the canonical JSON of both lists (secret refs included, secret values never)."""

  async def hydrate_params(spec: ToolkitSpec) -> dict[str, Any]:
      """Return ``spec.params`` merged with vault secrets (dotted keys expanded into nested lists/dicts).

      Raises KeyError when a referenced vault entry is missing; RuntimeError when vault keys
      are unconfigured. Never logs secret values.
      """

  async def hydrate_mcp(spec: AgentMCPServerSpec) -> dict[str, Any]:
      """Return MCPServerConfig kwargs with ``headers``/``auth_config`` restored from the vault."""

  def mask_spec(spec: ToolkitSpec) -> dict[str, Any]:
      """Dump for API responses: every ``secret_refs`` key rendered as ``SECRET_MASK`` inside params."""
  ```

### Module 2: Config-schema machinery (AbstractToolkit hooks)
- **Path**: `packages/ai-parrot/src/parrot/tools/config_schema.py` (new);
  modifies `packages/ai-parrot/src/parrot/tools/toolkit.py`
- **Responsibility**: produce the JSON Schema envelope for any toolkit class;
  classify secrets; optional dynamic-options hook, never exposed as an LLM tool.
- **Depends on**: none (Pydantic)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/tools/config_schema.py  (new)
  SECRET_NAME_HINTS: frozenset[str] = frozenset(
      {"token", "password", "api_key", "secret", "dsn", "credentials", "access_token", "private_key"})

  def is_secret_name(name: str, curated: frozenset[str] = frozenset()) -> bool:
      """True when ``name`` is curated or contains any hint (case-insensitive substring)."""

  def introspect_config_schema(cls: type, *, server_managed: frozenset[str] = frozenset()) -> dict[str, Any]:
      """Lift ``cls.__init__`` into a Draft 2020-12 object schema.

      str/int/float/bool/list/dict/Literal/Optional map to JSON types; any other annotation
      (objects, callables, resolvers) → ``x-server-managed: true`` and omitted from ``required``.
      Adds ``x-secret`` via ``is_secret_name(name, cls.secret_params)``.
      """

  def model_config_schema(cls: type) -> dict[str, Any]:
      """``cls.config_model.model_json_schema()`` plus ``x-secret`` (from Field json_schema_extra
      or ``is_secret_name``), ``x-user-overridable`` (``cls.default_user_overridable``),
      ``x-options`` (``cls.options_params``)."""

  def build_schema_envelope(slug: str, cls: type, *, server_managed: frozenset[str] = frozenset()) -> ToolkitSchemaEnvelope:
      """``source='model'`` when ``cls.config_model`` is set, else ``'introspection'``."""

  def secret_paths(schema: dict[str, Any], params: dict[str, Any]) -> list[str]:
      """Dotted paths of every value in ``params`` that the schema marks ``x-secret``
      (walks ``oneOf`` branches by discriminator for list items)."""

  # packages/ai-parrot/src/parrot/tools/toolkit.py  (modifies :319 area — new ClassVars after
  # ``auto_open: bool = False``)                                    # verified: tools/toolkit.py:319
  class AbstractToolkit(ABC):                                        # verified: tools/toolkit.py:206
      config_model: ClassVar[type[BaseModel] | None] = None
      secret_params: ClassVar[frozenset[str]] = frozenset()
      default_user_overridable: ClassVar[frozenset[str]] = frozenset()
      options_params: ClassVar[frozenset[str]] = frozenset()

      @classmethod
      def config_schema(cls, slug: str) -> dict[str, Any]:
          """Return ``build_schema_envelope(slug, cls).model_dump(by_alias=True)``."""

      async def config_options(self, param: str) -> list[ConfigOption]:
          """Dynamic choices for ``param``. Default raises NotImplementedError."""
  # _generate_tools exclusion tuple gains "config_schema", "config_options"   # verified: tools/toolkit.py:551-561
  ```

### Module 3: DatasetManager config model + datasource replay
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/config.py`
  (new); modifies `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
- **Responsibility**: the `oneOf` datasource union (§2 Data Models) and replay
  into a manager.
- **Depends on**: M2 (`config_model` ClassVar)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py  (modifies)
  class DatasetManager(AbstractToolkit):                              # verified: dataset_manager/tool.py:501
      config_model = DatasetManagerConfig
      secret_params = frozenset({"dsn", "credentials", "api_key", "access_token"})

      async def replay_datasources(self, datasources: Sequence[DatasourceSpec]) -> list[str]:
          """Register each spec; returns names registered. Per-entry failure → WARNING, continue.

          query_slug/sql → add_dataset(name, query_slug=|sql=, driver, dsn, credentials, permanent_filter)  # :966
          table          → add_table_source(name, table, driver, dsn=, credentials=, strict_schema=,
                                            permanent_filter=, allowed_columns=)                           # :1459
          file (csv/excel) → load_file(name, path, metadata=)                                                # :1222
          file (.parquet)  → create_deltatable_from_parquet(name, path, delta_path or Path(path).with_suffix('.delta'),
                                                            mode="overwrite", description=)                 # :2103
          airtable       → add_airtable_source(name, base_id, table, api_key=, view=)                        # :1608
          smartsheet     → add_smartsheet_source(name, sheet_id, access_token=)                              # :1652
          iceberg        → add_iceberg_source(name, table_id, catalog_params, factory=, credentials=, dsn=)  # :1696
          mongo          → add_mongo_source(name, collection, database, credentials=, dsn=, required_filter=)# :1780
          deltatable     → add_deltatable_source(name, path, table_name=, mode=, credentials=)               # :1860
          """
  ```
  `replay_datasources` is added to the `exclude_tools` of `DatasetManager` so it
  is not an LLM tool.

### Module 4: DB persistence, write guards, and the DB build path
- **Path**: modifies `handlers/models/bots.py`, `handlers/creation.sql`,
  `handlers/bots.py`, `manager/manager.py` (all under
  `packages/ai-parrot-server/src/parrot/`)
- **Responsibility**: two additive JSONB columns; Studio as the single writer;
  DB agents actually receive their tools + specs.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # handlers/models/bots.py  (modifies, after ``tools`` field)        # verified: models/bots.py:184
  class BotModel(Model):
      toolkit_config: dict = Field(required=False, default_factory=dict,
          ui_help="Per-toolkit agent-level config {slug: ToolkitSpec}; secrets live in the vault (FEAT-593).")
      mcp_servers: list = Field(required=False, default_factory=list,
          ui_help="Agent-level MCP servers [AgentMCPServerSpec]; auth/headers live in the vault (FEAT-593).")
      def to_bot_config(self) -> dict:                                 # verified: models/bots.py:321
          """'tools' ← normalize_tooling(self.tools, toolkit_config=self.toolkit_config) plain names + specs;
          adds 'agent_mcp_servers'."""

  # handlers/creation.sql (append after :204)
  # ALTER TABLE navigator.ai_bots ADD COLUMN IF NOT EXISTS toolkit_config JSONB DEFAULT '{}'::JSONB;
  # ALTER TABLE navigator.ai_bots ADD COLUMN IF NOT EXISTS mcp_servers    JSONB DEFAULT '[]'::JSONB;

  # handlers/bots.py — ChatbotHandler._put_database (:865) and ._post_database (:1129):
  STUDIO_ONLY_FIELDS: frozenset[str] = frozenset({"toolkit_config", "mcp_servers"})
  # payload containing any → 400 {"message": ..., "code": "use_studio_endpoint"}

  # manager/manager.py — BotManager._build_database_bot (:434)
  #   available_tools=bot_model.tools   →   tools=<normalized plain names + ToolkitSpecs>,
  #                                         agent_mcp_servers=<AgentMCPServerSpecs>   # verified: manager.py:515
  ```

### Module 5: Deferred async build path
- **Path**: modifies `packages/ai-parrot/src/parrot/interfaces/tools.py`,
  `packages/ai-parrot/src/parrot/bots/abstract.py`
- **Responsibility**: record specs in the sync `__init__`, apply them in async
  `configure()`, idempotently.
- **Depends on**: M1, M3
- **Interface Skeleton**:
  ```python
  # interfaces/tools.py  (modifies)
  class ToolInterface:
      _pending_toolkit_specs: list[ToolkitSpec]
      _pending_mcp_specs: list[AgentMCPServerSpec]
      _tooling_applied: bool
      _tooling_revision: str | None

      def _initialize_tools(self, tools: List[Union[str, AbstractTool, ToolDefinition, ToolkitSpec]]) -> None:
          """ToolkitSpec entries are appended to ``_pending_toolkit_specs`` (not registered here);
          the rest behaves as today."""                                   # verified: interfaces/tools.py:27

      async def apply_tooling_specs(self) -> list[str]:
          """Hydrate + register pending specs once; returns registered tool names.

          Resolve class: discover_from_registry() + resolve_class() (case-insensitive slug).
          Filter params to the constructor signature (unknown params → WARNING, dropped).
          dataset_manager: pop 'datasources'; reuse ``self._dataset_manager`` when it is a
          DatasetManager, else construct + register_toolkit + assign ``self._dataset_manager``;
          then ``await dm.replay_datasources(...)``.
          Any failure for one spec → WARNING and continue. Sets ``_tooling_revision``.
          """

  # bots/abstract.py  (modifies)
  #   __init__: self._pending_mcp_specs = list(kwargs.pop("agent_mcp_servers", []) or [])
  #             (next to ``self._credentials = ...`` — verified: bots/abstract.py:402)
  #   configure(): ``await self.apply_tooling_specs()`` right after
  #                ``self.configure_conversation_memory()``          # verified: bots/abstract.py:1518
  ```

### Module 6: Registry YAML round-trip + factory normalization
- **Path**: modifies `packages/ai-parrot/src/parrot/registry/registry.py`
- **Responsibility**: widened `BotConfig.toolkits`; factory consumes top-level
  `toolkits` + `mcp_servers` + `tools.toolkits` + `tools.mcp_servers` through
  `normalize_tooling`; dead loop removed; exact-file YAML rewrite.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  class BotConfig(BaseModel):                                        # verified: registry.py:224
      toolkits: List[Union[str, ToolkitSpec]] = Field(default_factory=list)   # was List[str] :237

  class AgentRegistry:
      def update_agent_tooling(
          self, name: str, *, toolkits: list[ToolkitSpec] | None = None,
          mcp_servers: list[AgentMCPServerSpec] | None = None,
      ) -> Path:
          """Rewrite ``agent.toolkits`` / ``agent.mcp_servers`` of the YAML at ``metadata.file_path``
          in place (tmp file + os.replace) and refresh ``metadata.bot_config``.

          Raises PermissionError when the agent has no ``bot_config``, the file is not
          ``.yaml``/``.yml``, is not under ``AGENTS_DIR``, or is not named ``{name.lower()}.yaml``.
          Raises KeyError for an unknown agent. Other YAML keys are preserved verbatim.
          """
  # create_agent_definition (:1069) writes toolkits as ``[t if isinstance(t, str) else
  #   t.model_dump(exclude_defaults=True) for t in config.toolkits]`` (:1125).
  # factory (:858): merged_args["tools"] = plain names + ToolkitSpecs (:907);
  #   merged_args["agent_mcp_servers"] = mcp specs; the post-init MCP loop (:933-939)
  #   and the dead toolkit loop (:942-950) are deleted.
  ```

### Module 7: Studio agent-level API
- **Path**: new `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py`,
  new `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py`;
  modifies `handlers/studio/toolkits.py` (GET envelope only),
  `handlers/studio/__init__.py` (routes), `handlers/studio/models.py`
- **Responsibility**: read/persist agent-level toolkit and MCP config, secret
  split + masking, options lookups.
- **Depends on**: M1, M2, M4, M6
- **Interface Skeleton**:
  ```python
  # handlers/studio/models.py  (extends)
  class ToolkitConfigPutRequest(BaseModel):
      params: dict[str, Any] = Field(default_factory=dict)
      user_overridable: list[str] = Field(default_factory=list)
  class AgentToolkitsResponse(BaseModel):
      agent: str; editable: bool; reason: str | None = None
      toolkits: list[dict[str, Any]]; unavailable: list[str] = Field(default_factory=list)
  class ToolkitPersistResponse(BaseModel):
      agent: str; slug: str; reload_required: bool = True; persisted: bool = True
  class AgentMcpServersPutRequest(BaseModel):
      servers: list[dict[str, Any]]
  class ToolkitOptionsResponse(BaseModel):
      options: list[ConfigOption]

  # handlers/studio/tooling_store.py  (new)
  class AgentToolingStore:
      """Single writer of agent-level toolkit/MCP config (DB row or YAML file)."""
      def __init__(self, handler: "StudioBaseView") -> None: ...
      async def load(self, name: str) -> tuple[NormalizedTooling, bool, str | None, str | None]:
          """(tooling, editable, read_only_reason, vault_owner). Raises LookupError when unknown."""
      async def put_toolkit(self, name: str, slug: str, req: ToolkitConfigPutRequest) -> ToolkitSpec:
          """Validate (config_model or jsonschema), keep masked secrets, split new secrets to the vault
          (merge into existing entry), persist. Raises PermissionError (read-only), ValueError (invalid),
          RuntimeError (vault unavailable)."""
      async def delete_toolkit(self, name: str, slug: str) -> None:
          """Remove the spec and delete its vault entry."""
      async def put_mcp_servers(self, name: str, servers: list[dict[str, Any]]) -> list[AgentMCPServerSpec]:
          """Same secret split for ``headers`` / ``auth_config``; replaces the whole list."""

  # handlers/studio/toolkit_config.py  (new) — all @is_authenticated() @user_session(),
  # subclass (_StudioAgentsMixin, StudioBaseView)                  # verified: studio/toolkits.py:217-219
  class StudioAgentToolkitsHandler: ...    # GET list; PUT/DELETE {slug}  — PBAC astudio:toolkits:persist
  class StudioToolkitOptionsHandler: ...   # GET options — PBAC astudio:toolkits:options
  class StudioAgentMcpServersHandler: ...  # GET/PUT — PBAC astudio:mcp:persist
  # Ownership: owner = str(db_agent.created_by) or _registry_agent_owner(meta);
  #   self._require_owner(owner, user)                                # verified: studio/_base.py:230
  # vault_owner = that same owner id (DB: created_by; registry: _registry_agent_owner(meta)).

  # handlers/studio/toolkits.py GET (:235) now answers
  #   AbstractToolkit subclasses → cls.config_schema(slug); wiki/infographic keep their
  #   server_managed sets via build_schema_envelope(..., server_managed=...).
  ```

### Module 8: Per-user override service + endpoints
- **Path**: new `packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py`,
  new `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py`
- **Responsibility**: DocumentDB CRUD for overrides; `/me` endpoints.
- **Depends on**: M1, M7 (route file + store for reading agent defaults)
- **Interface Skeleton**:
  ```python
  # handlers/toolkit_persistence.py  (new; pattern: handlers/mcp_persistence.py:36)
  COLLECTION: str = "user_toolkit_configs"
  class UserToolkitOverride(BaseModel):
      user_id: str; agent_id: str; slug: str
      params: dict[str, Any] = Field(default_factory=dict)
      secret_refs: dict[str, str] = Field(default_factory=dict)
      updated_at: str
  class ToolkitConfigService:
      async def save(self, override: UserToolkitOverride) -> None: ...        # upsert by (user_id, agent_id, slug)
      async def load(self, user_id: str, agent_id: str) -> list[UserToolkitOverride]: ...
      async def remove(self, user_id: str, agent_id: str, slug: str) -> bool: ...
      async def revision(self, user_id: str, agent_id: str) -> str: ...      # max(updated_at) or ""

  # handlers/studio/toolkit_overrides.py  (new)
  class StudioUserToolkitOverrideHandler:   # GET/PUT/DELETE /agents/{name}/toolkits/{slug}/me
      """Any authenticated user who may chat with the agent (no owner check); PBAC
      astudio:toolkits:override. PUT: keys ⊄ spec.user_overridable → 422 not_overridable.
      User secrets → vault under the user's id, name f"toolkit_{slug}_{agent}_user".
      Clears the session marker f"{agent}_toolkit_overrides_rev"."""
  ```

### Module 9: Session application in AgentTalk
- **Path**: modifies `packages/ai-parrot-server/src/parrot/handlers/agent.py`
- **Responsibility**: build the effective session ToolManager with overrides;
  revision-based rebuild.
- **Depends on**: M1, M5, M8
- **Interface Skeleton**:
  ```python
  class AgentTalk:
      async def _apply_user_toolkit_overrides(
          self, agent: AbstractBot, request_session: Any, tool_manager: ToolManager | None,
      ) -> ToolManager | None:
          """Return the session ToolManager to use (possibly unchanged).

          No overrides → return ``tool_manager`` untouched (no clone). Otherwise, when the
          stored marker ``(agent._tooling_revision, service.revision(...))`` differs: base =
          ``tool_manager or agent.tool_manager.clone()``; for each override whose merged params
          differ from defaults, drop tools whose ``get_toolkit_owner()`` is an instance of the
          resolved class, build ``cls(**filter(defaults ⊕ override_overridable_now))``,
          ``register_toolkit``; store TM under f"{agent.name}_tool_manager" and the marker.
          Failures → WARNING, return the input manager.
          """
  # Call sites: POST path right before ``await self._filter_tools_for_user(user_tool_manager)``
  #   (:1558, inside ``if request_session and not is_user_bot``), and PATCH path after the
  #   ``if getattr(agent, "enable_mcp_restore", False):`` block (:1007).
  ```

### Module 10: Jira + Querysource config models and dynamic options
- **Path**: new `packages/ai-parrot-tools/src/parrot_tools/jira_config.py`,
  new `packages/ai-parrot-tools/src/parrot_tools/querysource/config.py`;
  modifies `jiratoolkit.py`, `querysource/toolkit.py`, `querysource/catalog.py`
- **Responsibility**: first-class config models + `config_options`.
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  class JiraToolkitConfig(BaseModel):   # fields mirror JiraToolkit.__init__ (jiratoolkit.py:671-687)
      server_url: str | None = None
      auth_type: Literal["basic_auth", "token_auth", "oauth"] | None = None   # verify values vs JiraInterface
      username: str | None = None
      password: str | None = None          # x-secret
      token: str | None = None             # x-secret
      default_project: str | None = None   # x-options
      verify_credentials: bool = True
  # oauth_* , credential_resolver, workflow_paths → not in the model (server-managed / advanced)
  class JiraToolkit(AbstractToolkit):                                 # verified: jiratoolkit.py:600
      config_model = JiraToolkitConfig
      options_params = frozenset({"default_project"})
      default_user_overridable = frozenset({"username", "password", "token"})
      async def config_options(self, param: str) -> list[ConfigOption]:
          """default_project → projects from ``self._read_interface.list_projects()`` (jiratoolkit.py:2267)."""

  class QuerysourceToolkitConfig(BaseModel):   # mirrors querysource/toolkit.py:64-76
      programs: list[str] | None = None       # x-options
      allow_write: bool = False; allow_raw_sql: bool = False; allow_external_sources: bool = True
      include_sql: bool = True; max_rows: int = 200
      forced_conditions: dict[str, Any] | None = None
      dsn: str | None = None                  # x-secret
      multiquery_timeout: float = 600.0
  class QuerysourceToolkit(AbstractToolkit):                          # verified: querysource/toolkit.py:56
      config_model = QuerysourceToolkitConfig
      options_params = frozenset({"programs"})
      async def config_options(self, param: str) -> list[ConfigOption]:
          """programs → ``await self._catalog.list_programs()`` (after ``await self._open()``)."""
  class SlugCatalog:                                                  # verified: querysource/catalog.py:131
      async def list_programs(self) -> list[str]:
          """Distinct ``program_slug`` values across the catalog, sorted (unfiltered by TenantGuard)."""
  ```

### Module 11: Codegen for Studio tooling payloads
- **Path**: modifies `scripts/generate_ts_types.py`; regenerates
  `packages/ai-parrot-server/ui/schemas/*.json` +
  `ui/src/lib/types/generated/*` via `pnpm generate`
- **Responsibility**: TS types for `ToolkitSchemaEnvelope`, `ToolkitSpec`,
  `AgentMCPServerSpec`, `ConfigOption`, and the M7/M8 request/response models.
- **Depends on**: M1, M2, M7, M8
- **Interface Skeleton**: add entries to the model map returned before
  `export_schemas()` (next to `"AgentToolCall": AgentToolCall,` —
  verified: `scripts/generate_ts_types.py:85`).

### Module 12: Admin UI Tools tab
- **Path**: new `ui/src/lib/api/studio.ts`,
  `ui/src/lib/components/schema-form/SchemaForm.svelte`,
  `ui/src/pages/agents/form/TabsTools.svelte`,
  `ui/src/pages/agents/form/ToolkitDrawer.svelte`,
  `ui/src/pages/agents/form/AgentMcpPanel.svelte`; modifies
  `ui/src/pages/agents/AgentForm.svelte`, `ui/src/lib/agents/fields.ts`,
  `ui/src/pages/agents/form/TabsCapabilities.svelte` (all under
  `packages/ai-parrot-server/`)
- **Responsibility**: Tools tab (catalog switches → `tools` field of the form;
  toolkit drawer → Studio endpoints); SchemaForm renders string/number/bool/
  enum/array/object/`oneOf`(kind selector)/secret/dynamic-select widgets from the
  schema alone; the Datasets panel is the `dataset_manager` drawer; AgentMcpPanel
  edits the agent-level MCP list; Reload action surfaces `ReloadResult.warnings`.
- **Depends on**: M11
- **Interface Skeleton**:
  ```ts
  // ui/src/lib/api/studio.ts (new) — uses apiClient from "$lib/api/http" (verified: lib/api/agents.ts:16)
  export async function getToolkitSchema(slug: string): Promise<ToolkitSchemaEnvelope>;
  export async function getAgentToolkits(name: string): Promise<AgentToolkitsResponse>;
  export async function putAgentToolkit(name: string, slug: string, body: ToolkitConfigPutRequest): Promise<ToolkitPersistResponse>;
  export async function deleteAgentToolkit(name: string, slug: string): Promise<ToolkitPersistResponse>;
  export async function getToolkitOptions(name: string, slug: string, param: string): Promise<ToolkitOptionsResponse>;
  export async function getAgentMcpServers(name: string): Promise<AgentMCPServerSpec[]>;
  export async function putAgentMcpServers(name: string, servers: AgentMCPServerSpec[]): Promise<ToolkitPersistResponse>;
  export async function reloadAgent(name: string): Promise<{ reloaded: boolean; warnings: string[] }>;
  export async function getMyToolkitOverride(name: string, slug: string): Promise<Record<string, unknown>>;
  export async function putMyToolkitOverride(name: string, slug: string, params: Record<string, unknown>): Promise<void>;
  export async function deleteMyToolkitOverride(name: string, slug: string): Promise<void>;
  // SchemaForm.svelte props: { schema: JsonSchema; value: Record<string, unknown>;
  //   overridable?: string[]; showOverridable?: boolean; optionsLoader?: (param: string) => Promise<ConfigOption[]>;
  //   readonly?: boolean; onchange: (value, overridable) => void }
  // fields.ts: TabId gains "tools"; FIELD_TAB.tools → "tools" (was "capabilities", :126)
  // AgentForm.svelte TABS gains { id: "tools", label: "Tools" } after capabilities (:94)
  // TabsCapabilities.svelte keeps tools_enabled / auto_tool_detection / tool_threshold only.
  ```

### Module 13: Chat "My tool settings"
- **Path**: new `ui/src/lib/components/agents/MyToolkitSettings.svelte`;
  modifies `ui/src/lib/components/agents/DataManagementModal.svelte`
- **Responsibility**: one more `AppTabs` tab listing toolkits with ≥1
  overridable param; SchemaForm restricted to those params over the `/me`
  endpoints.
- **Depends on**: M11, M12 (`SchemaForm`, `studio.ts`)
- **Interface Skeleton**: `<MyToolkitSettings {agentId} />` mounted beside
  `<MCPServerTab {agentId} />` (verified: `DataManagementModal.svelte:337`).

### Module 14: Documentation
- **Path**: `docs/agent_studio_api.md`, `docs/admin-ui.md`,
  `docs/agent_config_creation.md`
- **Responsibility**: new endpoints + envelope + error codes; Tools tab; YAML
  `toolkits:` entry shape (`str | {slug, params, user_overridable}`) and the
  vault-only secret rule.
- **Depends on**: M7, M8, M12

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_normalize_tooling_dedupes_slug` | M1 | `tools=["jira"]` + spec for jira → one spec, no plain name |
| `test_normalize_tooling_all_legacy_shapes` | M1 | strings/dicts in toolkits, ToolConfig.toolkits, both mcp lists |
| `test_tooling_revision_stable_and_secret_free` | M1 | same input → same hash; secret values never enter the hash |
| `test_hydrate_params_dotted_datasource_secrets` | M1 | `datasources.0.dsn` restored into nested list |
| `test_mask_spec_masks_every_secret_ref` | M1 | GET never contains plaintext |
| `test_introspect_schema_types_and_server_managed` | M2 | resolver/object params → `x-server-managed`, not required |
| `test_secret_heuristics_plus_curated` | M2 | `token`/`dsn` flagged; `secret_params` overlay honoured |
| `test_config_options_not_an_llm_tool` | M2 | `config_options`/`config_schema` absent from `get_tools()` |
| `test_dataset_manager_schema_oneof_kinds` | M3 | 9 `oneOf` branches, discriminator `kind` |
| `test_replay_datasources_dispatch` | M3 | each kind calls the right `add_*` (mocked) with mapped kwargs |
| `test_replay_datasources_continues_on_failure` | M3 | one bad entry → WARNING, others registered |
| `test_chatbot_handler_rejects_studio_only_fields` | M4 | create/update with `toolkit_config` → 400 `use_studio_endpoint` |
| `test_build_database_bot_passes_tools` | M4 | `tools=` (not `available_tools=`) carries names + specs |
| `test_apply_tooling_specs_registers_with_params` | M5 | JiraToolkit built with persisted params + hydrated secret |
| `test_apply_tooling_specs_idempotent` | M5 | second `configure()` does not re-register (no collision) |
| `test_apply_tooling_specs_missing_vault_skips` | M5 | KeyError → WARNING, agent still configured |
| `test_dataset_manager_reuses_pandas_agent_dm` | M5 | PandasAgent: replay into existing `_dataset_manager` |
| `test_factory_consumes_top_level_toolkits_and_mcp` | M6 | YAML top-level keys reach the bot |
| `test_update_agent_tooling_in_place_atomic` | M6 | exact file rewritten, other keys preserved |
| `test_update_agent_tooling_refuses_outside_agents_dir` | M6 | PermissionError for repo YAML / `.py` agents |
| `test_create_agent_definition_roundtrips_specs` | M6 | BotConfig → YAML → BotConfig lossless with dict entries |
| `test_schema_envelope_contract` | M7 | wiki / dataset_manager / generic / jira envelopes |
| `test_put_toolkit_splits_secrets_to_vault` | M7 | vault write under owner id; JSON has only `secret_refs` |
| `test_put_toolkit_mask_sentinel_keeps_vault` | M7 | masked value → vault untouched |
| `test_put_toolkit_read_only_409` | M7 | `.py` agent → 409 `read_only_definition` |
| `test_put_toolkit_vault_unavailable_503` | M7 | RuntimeError → 503 `vault_unavailable` |
| `test_options_uses_persisted_spec_only` | M7 | query params ignored; unsaved toolkit → 409 `not_configured` |
| `test_mcp_servers_put_splits_auth_headers` | M7 | `auth_config`/`headers` never persisted raw |
| `test_override_put_rejects_non_overridable` | M8 | 422 `not_overridable` with offending names |
| `test_stale_override_kept_but_ignored` | M9 | revoked param stored but not merged |
| `test_session_view_replaces_not_duplicates` | M9 | one instance of the overridden toolkit's tools in session TM |
| `test_session_rebuild_on_revision_change` | M9 | reload (new `_tooling_revision`) → rebuild |
| `test_jira_config_options_projects` | M10 | mocked `list_projects` → options |
| `test_querysource_list_programs` | M10 | distinct sorted program slugs |

### Integration Tests
| Test | Description |
|---|---|
| `test_studio_toolkit_persist_reload_roundtrip` | PUT jira config on a DB agent → reload → bot has JiraToolkit with those params |
| `test_yaml_agent_toolkit_persist_roundtrip` | same for a factory YAML agent under a tmp `AGENTS_DIR` |
| `test_dataset_manager_datasources_in_memory` | PUT 2 datasources → reload → both in `bot._dataset_manager`; nothing else persisted |
| `test_user_override_session_isolation` | two users, one override → only that user's session sees the override |
| UI vitest: `SchemaForm.test.ts`, `TabsTools.test.ts` | oneOf kind switch, secret masking, overridable toggles, options fallback |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_vault(monkeypatch):
    """In-memory store/retrieve/delete_vault_credential keyed (user_id, vault_name)."""

@pytest.fixture
def tmp_agents_dir(tmp_path, monkeypatch):
    """AGENTS_DIR → tmp_path; writes agents/general/<name>.yaml with bot_config."""

@pytest.fixture
def jira_spec() -> ToolkitSpec:
    return ToolkitSpec(slug="jira", params={"server_url": "https://example.atlassian.net",
                       "default_project": "TROC"}, secret_refs={"token": "toolkit_jira_agent1"},
                       vault_owner="42", user_overridable=["token"])
```
Test locations: core → `packages/ai-parrot/tests/tools/` and
`packages/ai-parrot/tests/registry/`; server → `packages/ai-parrot-server/tests/studio/`
(extend `test_toolkits.py`, new `test_toolkit_config.py`, `test_toolkit_overrides.py`);
tools → `packages/ai-parrot-tools/tests/querysource/` and `tests/test_jira_config.py`.

---

## 5. Acceptance Criteria

- [ ] AC1 — `PUT /astudio/agents/{name}/toolkits/{slug}` persists agent-level params to `BotModel.toolkit_config` (DB) or the agent's own YAML (`AGENTS_DIR`), returns `reload_required: true, persisted: true`; after `POST /agents/{name}/reload` the toolkit is instantiated with those params (brainstorm: both layers; apply semantics).
- [ ] AC2 — No plaintext secret ever lands in `toolkit_config`, `mcp_servers`, YAML, logs, or any GET response; secrets are stored with `store_vault_credential(vault_owner, …)` and GET returns `SECRET_MASK` (brainstorm: vault only).
- [ ] AC3 — Agent-level secrets are stored under the **agent owner's** user id (DB `created_by` / registry owner) — no synthetic service principal (brainstorm: vault ownership).
- [ ] AC4 — `ChatbotHandler` create/update reject `toolkit_config`/`mcp_servers` with 400 `use_studio_endpoint`.
- [ ] AC5 — `.py` registry agents and YAML outside `AGENTS_DIR` answer 409 `read_only_definition` on PUT/DELETE; the live `POST /agents/{name}/toolkits` still works unpersisted (brainstorm: registry agents).
- [ ] AC6 — `GET /toolkits/{slug}/schema` returns `{slug, class_name, source, schema}` with a Draft 2020-12 schema; `dataset_manager` exposes a `kind`-discriminated `oneOf` for datasources; toolkits without `config_model` are introspected into the same shape (brainstorm: declarative JSON Schema).
- [ ] AC7 — Secret classification = name heuristics + curated overlays + optional `secret_params` (user decision 2026-09-23); non-JSON-typed ctor params are `x-server-managed`.
- [ ] AC8 — Agent-level datasources are replayed into the agent's in-memory `DatasetManager` on build/reload; no `datasets` column or other dataset persistence exists (brainstorm: in memory).
- [ ] AC9 — Per-user overrides accept only currently `user_overridable` params (422 otherwise), are applied only on the session ToolManager view, and never mutate the shared bot; a user's secrets live under the user's id (brainstorm: override policy).
- [ ] AC10 — A stored override for a param no longer overridable is kept but ignored at build (user decision 2026-09-23).
- [ ] AC11 — Override application runs for every non-user-bot session with overrides — no opt-in flag (user decision 2026-09-23).
- [ ] AC12 — `GET …/options/{param}` works for Jira `default_project` and Querysource `programs`, uses only the persisted spec, is owner + PBAC gated, and 502s cleanly on lookup failure (brainstorm: dynamic options).
- [ ] AC13 — YAML top-level `toolkits` and `mcp_servers` are consumed by the factory; the dead toolkit loop is gone; DB agents receive their `tools` via `tools=`.
- [ ] AC14 — Admin UI: Tools tab replaces the checkbox list; toolkit drawer renders from the schema alone (no toolkit-specific frontend code); Datasets and MCP sub-panels persist at agent level; Reload action present (brainstorm: UI target).
- [ ] AC15 — Chat `DataManagementModal` has a "My tool settings" tab over the `/me` endpoints; existing per-user dataset/MCP tabs keep working.
- [ ] AC16 — `pnpm generate` output committed; `pnpm build` and `vitest` pass.
- [ ] AC17 — All new tests in §4 pass: `pytest packages/ai-parrot/tests/tools packages/ai-parrot/tests/registry packages/ai-parrot-server/tests/studio packages/ai-parrot-tools/tests -v`; `ruff check` clean on touched files.
- [ ] AC18 — Docs updated: `docs/agent_studio_api.md`, `docs/admin-ui.md`, `docs/agent_config_creation.md`.
- [ ] AC19 — No new Python dependency (`jsonschema>=4.20` is already a core dependency — `packages/ai-parrot/pyproject.toml:91`).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Re-verified on `dev` @ `b689a2e5e`
> (2026-09-23). Paths are repo-relative.

### Verified Imports
```python
from parrot.tools.discovery import discover_from_registry, resolve_class    # handlers/studio/toolkits.py:29
from parrot.tools.dataset_manager.tool import DatasetManager                # handlers/studio/toolkits.py:28
from parrot.knowledge.wiki import LLMWikiToolkit, WikiConfig                # handlers/studio/toolkits.py:27
from parrot.tools.infographic_toolkit import InfographicToolkit             # handlers/studio/toolkits.py:30
from parrot_tools import TOOL_REGISTRY                                      # handlers/tools_catalog.py (try/except ImportError)
from parrot.handlers.mcp_persistence import MCPPersistenceService           # handlers/mcp_helper.py:38
from parrot.interfaces.documentdb import DocumentDb                         # handlers/mcp_persistence.py:26
from parrot.security.vault_utils import (store_vault_credential, retrieve_vault_credential,
                                         delete_vault_credential, get_vault_keyring)   # security/vault_utils.py:84/135/172/49
from parrot.tools.manager import ToolManager, get_toolkit_owner, ToolNameCollisionError   # tools/manager.py:53, :43
from parrot.mcp import MCPServerConfig                                      # registry/registry.py:32 (lazy, parrot/mcp/__init__.py:38)
from parrot.conf import AGENTS_DIR                                          # handlers/studio/toolkits.py:23
from navigator_auth.decorators import is_authenticated, user_session        # handlers/studio/toolkits.py:22
from ._base import StudioBaseView, resolve_safe_path                        # handlers/studio/toolkits.py:33
from .agents import _StudioAgentsMixin                                      # handlers/studio/toolkits.py:34
from .models import StudioError                                             # handlers/studio/toolkits.py:35
```

### Existing Class Signatures
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py
class ToolkitAssignRequest(BaseModel): slug: str; params: dict[str, Any]              # :63
class _ToolkitAssignError(Exception): __init__(self, status, code, message, details=None)   # :70
def _introspect_params(cls, *, server_managed=frozenset()) -> dict[str, dict[str, Any]]:   # :107
def _missing_required_params(cls, provided: dict) -> list[str]:                       # :139
def _resolve_toolkit_class(slug: str) -> type | None:                                  # :154
@is_authenticated() @user_session()
class StudioToolkitsHandler(_StudioAgentsMixin, StudioBaseView):                       # :217-219
    def _error(self, message, *, status, code=None, details=None): ...                 # :227
    async def get(self): ...          # :235 — returns {"slug","class_name","params"} today (:250-254)
    def _wiki_schema() -> dict: ...   # :259 (WikiConfig.model_json_schema() at :265)
    def _dataset_manager_schema() -> dict: ...   # :269
    def _infographic_schema() -> dict: ...       # :277 (server_managed artifact_store)
    async def post(self): ...         # :286 — PBAC "astudio:toolkits:assign" (:288); "persisted": False (:345)
# handlers/studio/__init__.py
STUDIO_PREFIX = "/api/v1/astudio"                                                      # :23
app.router.add_view(f"{STUDIO_PREFIX}/toolkits/{{slug}}/schema", StudioToolkitsHandler)   # :113
app.router.add_view(f"{STUDIO_PREFIX}/agents/{{name}}/toolkits", StudioToolkitsHandler)   # :114
app.router.add_view(f"{STUDIO_PREFIX}/agents/{{name}}/reload", StudioAgentReloadHandler)  # :48
# handlers/studio/_base.py
class StudioUser: ...                                            # :102
class StudioBaseView(BaseView):                                  # :121
    async def _resolve_session(self) -> Any: ...                 # :141
    async def _get_user(self) -> StudioUser: ...                 # :164
    def _require_owner(self, resource_owner, user) -> None: ...  # :230 raises web.HTTPForbidden
    async def _pbac_allowed(self, resource, action) -> bool: ... # :274 fail-open
    async def _pbac_gate(self, resource, action): ...            # :308 response or None
# handlers/studio/agents.py
class _StudioAgentsMixin:
    def _manager(self) / _registry(self) / async _get_db_agent(name) -> BotModel | None   # :42 / :46 / :51
    @staticmethod def _registry_agent_owner(meta) -> str | None                            # :106
# DELETE safety precedent: Path(file_path).resolve().is_relative_to(AGENTS_DIR.resolve())  # agents.py:417

# packages/ai-parrot-server/src/parrot/handlers/models/bots.py
class BotModel(Model):                                           # :20  (DDL docstring; table PARROT_SCHEMA.PARROT_BOTS_TABLE :394-395)
    tools_enabled: bool   # :177
    tools: List[str] = Field(default_factory=list, required=False, ui_help="The bot’s tools.")   # :184
    permissions: dict     # :258
    created_by: Optional[int]   # :291
    def to_bot_config(self) -> dict: ...   # :321 ('tools': self.tools at :340)
    def is_agent_enabled(self) / get_available_tool_names(self)   # :357 / :361
def create_bot(bot_model: BotModel, bot_class=None): ...          # :613
# packages/ai-parrot-server/src/parrot/handlers/creation.sql — FEAT-133 idempotent ALTER precedent :198-204
# packages/ai-parrot-server/src/parrot/handlers/bots.py
class ChatbotHandler(_PBACHandlerMixin, AbstractModel):          # :424
    async def _put_database(self, payload: dict): ...             # :865 — BotModel(**payload) at :887
    async def _post_database(self, agent: BotModel, payload: dict): ...   # :1129 — loop agent.set(key, val) :1143-1146
class ToolList(_PBACHandlerMixin, BaseView): ...                  # GET /api/v1/agent_tools
# packages/ai-parrot-server/src/parrot/manager/manager.py
class ReloadResult(BaseModel): name, reloaded, previous_instance_closed, warnings   # :159
class BotManager:
    async def _build_database_bot(self, bot_model, app) -> AbstractBot: ...   # :434 — available_tools=bot_model.tools (:515); configure (:540)
    async def get_bot(self, name, new=False, session_id="", request=None, **kwargs): ...   # :728
    async def reload_agent(self, name) -> ReloadResult: ...   # :864

# packages/ai-parrot/src/parrot/registry/registry.py
@dataclass(slots=True) class BotMetadata: name, factory, module_path, file_path: Path, ..., bot_config: Optional[Any]   # :46-64
class BotConfig(BaseModel):                                       # :224
    origin: Literal["repo", "factory"]                            # :232
    tools: Optional[ToolConfig]                                   # :236
    toolkits: List[str] = Field(default_factory=list)             # :237
    mcp_servers: List[Dict[str, Any]] = Field(default_factory=list)   # :238
# factory (create_agent_factory) :858 — tools_list from config.tools.tools (:896-905), merged_args["tools"] (:907),
#   post-init MCP loop over config.tools.mcp_servers (:933-939), dead toolkit loop (:942-950)
# load_agent_definition_file: BotMetadata(file_path=yaml_file, bot_config=config)   # :1052 (file_path/bot_config set in that call)
class AgentRegistry:
    def get_metadata(self, name) -> Optional[BotMetadata]: ...    # :648
    def create_agent_definition(self, config: BotConfig, category="general") -> Path: ...   # :1069 (toolkits :1125, mcp_servers :1126)
# packages/ai-parrot/src/parrot/models/basic.py
class ToolConfig(BaseModel): tools: List[Dict]; mcp_servers: List[Dict]; toolkits: List[str]   # :33-37

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot:
    def __init__(self, name="Nav", system_prompt=None, llm=None, instructions=None, tools=None, ..., **kwargs)   # :274-296
    #   self._credentials = list(kwargs.pop("credentials", []) or [])   # :402
    #   if tools: self._initialize_tools(tools)                        # :404-405
    async def configure(self, app=None) -> None: ...   # :1500 — self.configure_conversation_memory() at :1518
# NOTE: no ``available_tools`` kwarg is consumed anywhere in AbstractBot / ToolInterface / bots/*.py
# packages/ai-parrot/src/parrot/bots/data.py
class PandasAgent(IntentRouterMixin, BasicAgent):                 # :384 — self._dataset_manager = DatasetManager() :477; attach_dm :512
# packages/ai-parrot/src/parrot/interfaces/tools.py
class ToolInterface:
    def _initialize_tools(self, tools) -> None: ...   # :27 (sync) — str branch :40-52: ToolkitRegistry.get → register_toolkit(tool) no kwargs
    def _capture_knowledge_toolkit(self, toolkit) -> None: ...   # :164
# packages/ai-parrot/src/parrot/tools/manager.py
class ToolNameCollisionError(ValueError): ...                     # :43
def get_toolkit_owner(tool) -> Optional[AbstractToolkit]: ...     # :53
class ToolManager:
    def register_tool(...)                                        # :770
    def register_tools(self, tools) -> None: ...                  # :986
    def load_tool(self, tool_name: str, **kwargs) -> bool: ...    # :1016
    def register_toolkit(self, toolkit, **kwargs) -> List[AbstractTool]: ...   # :1104
    def get_tool(self, tool_name) -> Optional[Any]: ...           # :1287
    def list_tools(self) -> List[str]: ...                        # :1307
    def remove_tool(self, tool_name: str) -> None: ...            # :1342
    def tool_count(self) -> int: ...                              # :2628
    def clone(self, *, include_search_tool=False) -> "ToolManager": ...   # :2632 — shares tool instances by reference
    async def cleanup_toolkits(self) -> None: ...                 # :2755
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                       # :206
    exclude_tools: tuple[str, ...] = ()   # :243
    tool_prefix: str | None = None        # :257
    credential_provider: str | None       # :312
    auto_open: bool = False               # :319
    def __init__(self, **kwargs): ...     # :321 (self._init_kwargs :351)
    # _generate_tools: skips names starting "_" (:547) and the management tuple (:551-561)
    def get_toolkit_info(self) -> dict: ...   # :693
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):    # :501; __init__(df_prefix="df", generate_guide=True, include_summary_stats=False,
                                          #   auto_detect_types=True, policy_guard=None, dataplane_guard=None, usage_rules=None, **kwargs)  # :549-558
    async def add_dataset(self, name, *, description=None, query_slug=None, query=None, table=None, dataframe=None,
                          driver=None, dsn=None, credentials=None, conditions=None, sql=None, filter=None,
                          metadata=None, is_active=True, permanent_filter=None, computed_columns=None,
                          usage_guidance=None) -> str   # :966
    async def load_file(self, name, path, metadata=None, max_rows_per_table=200, output_format="markdown")   # :1222 — csv | xls/xlsx/xlsm/xlsb only
    async def add_table_source(self, name, table, driver, *, description=None, dsn=None, credentials=None, metadata=None,
                               cache_ttl=3600, strict_schema=True, permanent_filter=None, query_filter=None,
                               allowed_columns=None, no_cache=False, computed_columns=None, ...)   # :1459
    async def add_airtable_source(self, name, base_id, table, api_key=None, view=None, description=None, metadata=None, ...)   # :1608
    async def add_smartsheet_source(self, name, sheet_id, access_token=None, description=None, metadata=None, ...)   # :1652
    async def add_iceberg_source(self, name, table_id, catalog_params, *, description=None, factory="pandas",
                                 credentials=None, dsn=None, metadata=None, ...)   # :1696
    async def add_mongo_source(self, name, collection, database, *, description=None, credentials=None, dsn=None,
                               required_filter=True, metadata=None, ...)   # :1780
    async def add_deltatable_source(self, name, path, *, description=None, table_name=None, mode="error",
                                    credentials=None, metadata=None, ...)   # :1860
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class JiraToolkit(AbstractToolkit):       # :600; __init__(server_url=None, auth_type=None, username=None, password=None, token=None,
    #   oauth_consumer_key=None, oauth_key_cert=None, oauth_access_token=None, oauth_access_token_secret=None,
    #   default_project=None, credential_resolver=None, workflow_paths=None, verify_credentials=True, **kwargs)   # :671-687
    # project listing: await self._read_interface.list_projects()   # :2267
# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py
class QuerysourceToolkit(AbstractToolkit):   # :56; __init__(programs=None, allow_write=False, allow_raw_sql=False,
    #   allow_external_sources=True, include_sql=True, max_rows=200, forced_conditions=None, dsn=None,
    #   multiquery_timeout=600.0, **kwargs)   # :64-76; self._catalog = SlugCatalog(...) :107
# packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py
class TenantGuard: __init__(self, programs: list[str] | None)   # :97
class SlugCatalog:                                                # :131
    async def list(self, *, search, program, limit) -> list[SlugRecord]: ...   # :167 (QueryModel.filter(program_slug=...))
# packages/ai-parrot-server/src/parrot/handlers/agent.py  (AgentTalk)
    async def _filter_tools_for_user(self, tool_manager) -> None: ...          # :219
    async def _configure_tool_manager(self, data, request_session, agent_name=None): ...   # :690 → UserObjectsHandler
    async def _setup_agent_tools(self, agent, data, request_session): ...      # :975 (PATCH) — MCP restore gate :1007
    async def _restore_user_mcp_servers(self, tool_manager, request_session, agent_name) -> None: ...   # :1076 (user_id from session attrs user_id/id/username)
    # POST: user_tool_manager = request_session.get(f"{agent.name}_tool_manager") :1552-1553 (only when not is_user_bot);
    #       PBAC filter :1558; swap agent.tool_manager = user_tool_manager :1683-1686; restore :1936-1937
# packages/ai-parrot-server/src/parrot/handlers/user_objects.py
class UserObjectsHandler:
    async def configure_tool_manager(self, data, request_session, agent_name=None, user_id=None, agent_id=None): ...   # :99 (reuses session TM or ToolManager(debug=True))
    async def _hydrate_oauth_toolkits(self, user_id, agent_id, session_key, request_session): ...   # :196 (user_agent_toolkits)
    async def configure_dataset_manager(self, request_session, agent, agent_name=None) -> DatasetManager: ...   # :254
# packages/ai-parrot-server/src/parrot/handlers/datasets.py
def _clone_agent_dm(agent, logger) -> DatasetManager | None: ...   # :47 (reads agent._dataset_manager :61)
# packages/ai-parrot-server/src/parrot/handlers/mcp_persistence.py
COLLECTION = "user_mcp_configs"   # :31
class MCPPersistenceService:       # :36 — save_user_mcp_config :49 (update_one upsert :85) / load_user_mcp_configs :94 / remove_user_mcp_config :136
# packages/ai-parrot/src/parrot/security/vault_utils.py — process KeyRing (KeyRing.from_env), DocumentDB "user_credentials";
#   works without a request session (safe at build time)
# packages/ai-parrot-server/src/parrot/server/ui/models.py
class BotAgentItem(BaseModel): model_config = ConfigDict(extra="allow")   # :20/:33
class BotWritePayload(BaseModel): model_config = ConfigDict(populate_by_name=True, extra="forbid"); tools: list[str] | None   # :62/:77/:101
# scripts/generate_ts_types.py — model map :71-86 ("AgentToolCall": AgentToolCall at :85); export_schemas() :89
```
```typescript
// packages/ai-parrot-server/ui/src/pages/agents/AgentForm.svelte — import TabsCapabilities :48; TABS :90-97
//   ({ id: "capabilities", label: "Capabilities" } :94); <TabsCapabilities state={formState} {catalog} {tools} /> :199
// ui/src/lib/agents/fields.ts — export type TabId = "general"|"behavior"|"ai"|"capabilities"|"data_memory"|"advanced" (:15-21);
//   FIELD_TAB tools_enabled/auto_tool_detection/tool_threshold/tools → "capabilities" (:123-126)
// ui/src/lib/stores/agent-form.svelte.ts — class AgentFormState :77 (load :118, validate :167, diff :201, payload :216)
// ui/src/lib/api/agents.ts — import apiClient from "$lib/api/http" (:16); listTools; getCatalog
// ui/src/pages/agents/form/TabsCapabilities.svelte — knownToolNames :31, selectedTools :32, unknownTools :35
// ui/src/lib/components/agents/DataManagementModal.svelte — AppTabs :167; <MCPServerTab {agentId} /> :337
// ui/src/lib/components/agents/AgentChat.svelte — lazy DataManagementModal :2672-2677
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `normalize_tooling` | `BotManager._build_database_bot` | replaces `available_tools=` kwarg | `manager/manager.py:515` |
| `normalize_tooling` | registry factory | `merged_args["tools"]` | `registry/registry.py:907` |
| `ToolInterface.apply_tooling_specs` | `AbstractBot.configure` | call after `configure_conversation_memory()` | `bots/abstract.py:1518` |
| `apply_tooling_specs` | `ToolManager.register_toolkit` | instance registration | `tools/manager.py:1104` |
| `apply_tooling_specs` | `add_mcp_server` | `MCPServerConfig(**hydrated)` | `registry/registry.py:936-938` (pattern) |
| `hydrate_params` | `retrieve_vault_credential` | await | `security/vault_utils.py:135` |
| `AgentToolingStore` | `store_vault_credential` / `delete_vault_credential` | await | `security/vault_utils.py:84` / `:172` |
| `AgentToolingStore` | `AgentRegistry.update_agent_tooling` | new method | `registry/registry.py:1069` (sibling) |
| `_apply_user_toolkit_overrides` | `ToolManager.clone` + `get_toolkit_owner` + `remove_tool` | method calls | `tools/manager.py:2632`, `:53`, `:1342` |
| Studio routes | `setup_studio_routes` | `app.router.add_view` | `handlers/studio/__init__.py:113-114` |
| `ChatbotHandler` guard | `_put_database` / `_post_database` | early 400 | `handlers/bots.py:865`, `:1129` |

### Does NOT Exist (Anti-Hallucination)
- ~~`BotModel.toolkit_config`~~, ~~`BotModel.mcp_servers`~~, ~~`BotModel.toolkits`~~, ~~`BotModel.datasets`~~ — only `tools: List[str]` (bots.py:184).
- ~~`BotConfig.datasets`~~; ~~a working YAML toolkit loader~~ (registry.py:942-950 is `pass`); ~~any reader of top-level `BotConfig.toolkits` / `BotConfig.mcp_servers`~~ (only `config.tools.*` is read).
- ~~`available_tools` as a consumed AbstractBot kwarg~~ — it falls into `**kwargs` unused.
- ~~`AbstractToolkit.config_schema` / `.config_options` / `.config_model` / `.secret_params` / `.user_overridable`~~ — none exist today; only `exclude_tools`, `tool_prefix`, `credential_provider`, `auto_open`.
- ~~`DatasetManagerConfig`~~, ~~`DatasourceSpec`~~, ~~`DatasetManager.replay_datasources`~~ — greenfield (only the output model `DatasetInfo` :60 exists).
- ~~`ToolkitConfigService`~~, ~~`user_toolkit_configs`~~, ~~`AgentToolingStore`~~, ~~`AgentRegistry.update_agent_tooling`~~ — greenfield. (`user_agent_toolkits` exists but is the unrelated OAuth-enablement collection — do NOT reuse it.)
- ~~`SlugCatalog.list_programs`~~ — greenfield.
- ~~`ToolManager.replace_toolkit` / `remove_toolkit`~~ — no such API; use `get_toolkit_owner` + `remove_tool`.
- ~~`ToolkitRegistry.get("dataset_manager")`~~ — returns None (name filter); ~~`TOOL_REGISTRY["wiki"]` / `["infographic"]`~~ — not registered.
- ~~Any `/astudio` consumer in the SPA~~, ~~`ui/src/lib/api/studio.ts`~~, ~~`TabsTools.svelte`~~, ~~`SchemaForm.svelte`~~ — do not exist.
- ~~`GET /astudio/agents/{name}/toolkits`~~, ~~`PUT …/toolkits/{slug}`~~, ~~`…/options/{param}`~~, ~~`…/mcp-servers`~~, ~~`…/me`~~ — only schema GET + assignment POST exist.
- ~~`parrot.handlers.vault_utils` as the implementation~~ — thin re-export; implementation is `parrot.security.vault_utils`. ~~Fernet~~ — AES-GCM `KeyRing`.
- ~~Parquet support in `DatasetManager.load_file`~~ — CSV/Excel only; parquet goes through `create_deltatable_from_parquet(name, parquet_path, delta_path, *, table_name=None, mode="overwrite", description=None)` (tool.py:2103).
- ~~A `migrations/` dir for `ai_bots`~~ — additive DDL goes into `handlers/creation.sql` (FEAT-133 precedent).

### Edit Sites (Blueprint Anchors)

Verified against: `b689a2e5e`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/tools/spec.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/tools/config_schema.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/tools/toolkit.py` | MODIFY | `    auto_open: bool = False` | `toolkit.py:319` | 1 |
| `packages/ai-parrot/src/parrot/tools/toolkit.py` | MODIFY | `                "cleanup",` (inside the `_generate_tools` management tuple, followed by `*self.exclude_tools,`) | `toolkit.py:559` | 1 |
| `packages/ai-parrot/src/parrot/tools/dataset_manager/config.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | `class DatasetManager(AbstractToolkit):` | `tool.py:501` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/tools.py` | MODIFY | `                if isinstance(tool, str):` | `tools.py:40` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/tools.py` | MODIFY | `    def _capture_knowledge_toolkit` (add `apply_tooling_specs` before it) | `tools.py:164` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `            self.configure_conversation_memory()` | `abstract.py:1518` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        self._credentials: list = list(kwargs.pop("credentials", []) or [])` | `abstract.py:402` | 1 |
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | `    toolkits: List[str] = Field(default_factory=list)` | `registry.py:237` | 1 |
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | `            merged_args["tools"] = tools_list` | `registry.py:907` | 1 |
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | `            if config.tools and config.tools.mcp_servers:` (MCP loop :933-939 + `# Handle Toolkits` loop :942-950 deleted) | `registry.py:933` | 1 |
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | `            "toolkits": list(config.toolkits),` | `registry.py:1125` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/models/bots.py` | MODIFY | `    tools: List[str] = Field(default_factory=list, required=False, ui_help="The bot’s tools.")` | `bots.py:184` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/models/bots.py` | MODIFY | `            'tools': self.tools,` | `bots.py:340` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/creation.sql` | MODIFY | `COMMENT ON COLUMN navigator.ai_bots.parent_searcher_config` | `creation.sql:204` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/bots.py` | MODIFY | `                    if key in ('chatbot_id', 'created_at', 'created_by'):` | `bots.py:1144` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/bots.py` | MODIFY | `    async def _put_database(self, payload: dict):` | `bots.py:865` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `            available_tools=bot_model.tools,` | `manager.py:515` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py` | MODIFY | `            schema = {` (generic branch of `get`) and `    def _dataset_manager_schema() -> dict:` | `toolkits.py:250`, `:269` | 1 / 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | `    app.router.add_view(f"{STUDIO_PREFIX}/agents/{{name}}/toolkits", StudioToolkitsHandler)` | `__init__.py:114` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/models.py` | MODIFY | `class StudioError(BaseModel):` (append models after the module's last class) | `models.py:23` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `            await self._filter_tools_for_user(user_tool_manager)` | `agent.py:1558` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `        if getattr(agent, "enable_mcp_restore", False):` | `agent.py:1007` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jira_config.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | `class JiraToolkit(AbstractToolkit):` | `jiratoolkit.py:600` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/config.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | `class QuerysourceToolkit(AbstractToolkit):` | `toolkit.py:56` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py` | MODIFY | `    async def list(self, *, search: str \| None, program: str \| None, limit: int) -> list[SlugRecord]:` | `catalog.py:167` | 1 |
| `scripts/generate_ts_types.py` | MODIFY | `        "AgentToolCall": AgentToolCall,` | `generate_ts_types.py:85` | 1 |
| `packages/ai-parrot-server/ui/src/lib/api/studio.ts` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/components/schema-form/SchemaForm.svelte` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/pages/agents/form/TabsTools.svelte` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/pages/agents/form/ToolkitDrawer.svelte` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/pages/agents/form/AgentMcpPanel.svelte` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/pages/agents/AgentForm.svelte` | MODIFY | `    { id: "capabilities", label: "Capabilities" },` | `AgentForm.svelte:94` | 1 |
| `packages/ai-parrot-server/ui/src/pages/agents/AgentForm.svelte` | MODIFY | `      <TabsCapabilities state={formState} {catalog} {tools} />` | `AgentForm.svelte:199` | 1 |
| `packages/ai-parrot-server/ui/src/lib/agents/fields.ts` | MODIFY | `  tools: "capabilities",` | `fields.ts:126` | 1 |
| `packages/ai-parrot-server/ui/src/pages/agents/form/TabsCapabilities.svelte` | MODIFY | `  const knownToolNames = $derived(Object.keys(tools).sort());` | `TabsCapabilities.svelte:31` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/MyToolkitSettings.svelte` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/components/agents/DataManagementModal.svelte` | MODIFY | `      <MCPServerTab {agentId} />` | `DataManagementModal.svelte:337` | 1 |
| `docs/agent_studio_api.md`, `docs/admin-ui.md`, `docs/agent_config_creation.md` | MODIFY | (append sections — no anchor) | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Studio handlers: `@is_authenticated()` + `@user_session()`, `(_StudioAgentsMixin, StudioBaseView)`, `self._error(...)` with `StudioError`, `_pbac_gate` first, then `_require_owner` (copy `StudioToolkitsHandler.post` :286-316).
- Per-user persistence: mirror `MCPPersistenceService` (`DocumentDb` upsert by compound key).
- Vault naming mirrors `mcp_{server}_{agent}`; agent-level MCP uses the distinct `mcp_agent_` prefix so it never collides with per-user MCP entries.
- JSONB additive DDL in `creation.sql` with `ADD COLUMN IF NOT EXISTS` + `COMMENT ON COLUMN … 'FEAT-593 — …'` (FEAT-133 precedent).
- Admin UI: Svelte 5 runes only; `$lib` imports; `pnpm generate` for types (never hand-edit `types/generated/`); shadcn-svelte vendored widgets; tests next to the code.
- Hard cuts allowed (no external consumers): schema GET shape, Capabilities tab tools list, `BotConfig.toolkits` type.

### Known Risks / Gotchas
- **Sync `__init__` vs async secrets** — never call vault or `add_*` from `_initialize_tools`; everything async runs in `apply_tooling_specs()` under `configure()`.
- **`configure()` re-entry** raises `ToolNameCollisionError` on re-registration — `_tooling_applied` guard is mandatory.
- **Enabling DB `tools` for real** (fixing `available_tools=`) changes behaviour of DB agents whose `tools` column was silently ignored — they will now get those tools. Call out in the PR; `tools_enabled=False` still disables them.
- **Session TM swap is wholesale** (agent.py:1686): a session TM built from scratch drops agent tools, so override application must start from `agent.tool_manager.clone()`. Pre-existing PATCH-created session TMs (fresh `ToolManager(debug=True)`) already lack agent tools — out of scope, but do not make it worse.
- **`clone()` shares tool instances** — the override instance must be a new object, never a mutation of the shared toolkit.
- **Tool-name collision** between agent-level and override instance of one toolkit: remove owner-matched tools before registering.
- **Stale override** (param no longer overridable): kept in DocumentDB, filtered at merge (resolved policy).
- **Unknown slug / toolkit removed from the package**: schema 404; `GET /agents/{name}/toolkits` lists it under `unavailable` — never silently dropped.
- **Constructor signature drift**: build passes only params the signature accepts; unknown params logged at WARNING and kept in the stored spec.
- **Vault unavailable**: save → 503 `vault_unavailable`; build → toolkit skipped + WARNING, agent still boots.
- **Secret heuristics are fallible** (brainstorm-accepted trade-off; S6 rejected): first-class toolkits carry curated `secret_params`; non-JSON-typed params are `x-server-managed` so objects/resolvers can never be set from the UI.
- **Dynamic options SSRF** (S7): options use the persisted spec only; request query params are ignored.
- **`_clone_agent_dm` shares source objects** between agent and user managers (pre-existing, datasets.py) — replay creates fresh sources per build, but the per-user clone path is unchanged; note in PR.
- **YAML rewrite** targets `metadata.file_path` exactly and is atomic; a YAML not named `{name}.yaml` is read-only (would fork the definition via `create_agent_definition`'s path rule).
- **`ChatbotHandler` update loop** stores any payload key — the Studio-only guard must land in the same task as the column (M4), before any UI writes.
- **FEAT-540 overlap** on `handlers/studio/toolkits.py:27` (wiki import): this feature only changes the GET branch + schema helpers and keeps the current import; whichever lands second resolves a one-line conflict.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` v2 | existing | models + `model_json_schema()` |
| `navigator-session` vault (`KeyRing`) | existing | AES-GCM secrets via `parrot.security.vault_utils` |
| `jsonschema` | `>=4.20` (existing core dep, pyproject.toml:91) | server-side validation of introspected schemas (Draft 2020-12) |
| `json-schema-to-typescript` | existing (`pnpm generate`) | TS types |

No new Python dependencies.

---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-593-tool-configuration-agentstudio` (from `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edge = imports / consumes):
  - M3 → M2 (`config_model` ClassVar on `AbstractToolkit`)
  - M10 → M2 (same)
  - M4 → M1 (`normalize_tooling` in `to_bot_config` / `_build_database_bot`)
  - M5 → M1 (`ToolkitSpec`, `hydrate_params`), M3 (`replay_datasources`)
  - M6 → M1 (`ToolkitSpec` in `BotConfig.toolkits`)
  - M7 → M1, M2 (`secret_paths`, envelope), M4 (BotModel columns), M6 (`update_agent_tooling`)
  - M8 → M1, M7 (reads agent defaults through `AgentToolingStore`; shares `studio/__init__.py`)
  - M9 → M1, M5 (`_tooling_revision`), M8 (`ToolkitConfigService`)
  - M11 → M1, M2, M7, M8 (models to export)
  - M12 → M11; M13 → M11, M12 (`SchemaForm`, `studio.ts`); M14 → M7, M8, M12
  - Roots with no edge between them: **M1, M2** (run concurrently); then M3/M10/M4/M6 concurrently.
- **Shared files** (tasks serialized): `handlers/studio/__init__.py` (M7, M8); `ui/src/pages/agents/AgentForm.svelte` + `fields.ts` (M12 only); `registry/registry.py` (M6 only); `tools/toolkit.py` (M2 only).
- **Exclusive resources**: M11 runs `pnpm generate` (rewrites `ui/schemas/` + `ui/src/lib/types/generated/`) → `parallel: false`. No lockfile changes; the DDL is a file edit, not an applied migration.
- **Cross-feature dependencies**: none blocking. FEAT-540 (all pending) touches `studio/toolkits.py` import line only; FEAT-590 (in flight) does not touch `tools/toolkit.py`, `interfaces/tools.py`, `registry.py` or the Admin UI (verified against its branch diff).

---

## 8. Open Questions

- [x] Flow type / base branch — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] Where does per-toolkit config persist — *Resolved in brainstorm*: both layers — agent-level defaults on the agent definition (DB JSONB + YAML `toolkits:` entries) plus per-user overrides.
- [x] Secrets handling — *Resolved in brainstorm*: encrypted vault only (BYOK/MCP keyring), `secret_refs` in the config, masked on GET; never plaintext in JSON/YAML.
- [x] UI target and fate of chat-side dataset/MCP config — *Resolved in brainstorm*: extend `/admin/agents/:name` with a Tools tab (replacing the checkbox list) plus Datasets and MCP sub-panels; the chat keeps a lighter per-user "My settings" surface.
- [x] Who decides which params are user-overridable — *Resolved in brainstorm*: the operator, per param, via a toggle in Studio; overrides build a session-scoped toolkit instance, the shared bot is never mutated.
- [x] Registry (YAML/code) agents — *Resolved in brainstorm*: editable when the YAML lives under `AGENTS_DIR` (rewrite `toolkits:` + reload); `.py` agents stay read-only.
- [x] Agent-level meaning of datasets/MCP and location of user overrides — *Resolved in brainstorm*: agent = persisted defaults (`mcp_servers`, pre-registered datasources); user = chat, on the existing per-user endpoints.
- [x] Dynamic options for Querysource programs / Jira projects — *Resolved in brainstorm*: yes, via an optional `config_options(param, current_params)` toolkit hook advertised in the schema; Jira and Querysource implement it. *(Spec refinement, S7: evaluated on the persisted spec only, so the hook signature is `config_options(param)` on an instance built from saved params.)*
- [x] Vault ownership for agent-level secrets — *Resolved in brainstorm*: the vault is per-user (navigator-session vault via `parrot.security.vault_utils`); agent-level secrets are stored under the agent owner's user id. No synthetic service principal.
- [x] Secret classification for generic toolkits — *Resolved 2026-09-23 (user, /sdd-spec)*: name heuristics (`token`, `password`, `api_key`, `secret`, `dsn`, …) plus curated overlays plus optional `secret_params`; no explicit-declaration requirement.
- [x] Storage for agent-level datasets — *Resolved in brainstorm*: in memory; `dataset_manager` is configured like any other toolkit (its `DatasourceSpec` list is the toolkit's params), replayed on build/reload. No `datasets` JSONB column.
- [x] Schema source for complex toolkits — *Resolved in brainstorm*: declarative JSON Schema (Pydantic model → `model_json_schema()`, `oneOf` for choice-shaped config) published per toolkit; introspection only as fallback.
- [x] Stale overrides after the operator revokes overridability — *Resolved 2026-09-23 (user, /sdd-spec)*: keep but ignore; only currently-overridable params merge at build.
- [x] Toolkit-override restore flag — *Resolved 2026-09-23 (user, /sdd-spec)*: always on; the operator's `user_overridable` marking is the opt-in.
- [x] Coordination with FEAT-540 — *Resolved 2026-09-23 (user, /sdd-task)*: keep the current `parrot.knowledge.wiki` import in `handlers/studio/toolkits.py`; whichever feature lands second resolves the one-line conflict. No dependency on TASK-3263.
- [x] Parquet in the `file` datasource kind — *Resolved 2026-09-23 (user, /sdd-task)*: map `.parquet` to `create_deltatable_from_parquet`, `delta_path` defaulting to `Path(path).with_suffix('.delta')`, `mode="overwrite"` so replay on reload is idempotent.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: completed
> · Transcript: `sdd/state/FEAT-593/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make ToolkitSpec the single normalization boundary (architecture) | CONFIRM | Verified: top-level `BotConfig.toolkits`/`mcp_servers` are never read, the toolkit loop is `pass`, and the DB path passes an unconsumed `available_tools=` (manager.py:515). One `normalize_tooling()` feeds both paths. | §2 Overview, §3 M1/M4/M5/M6 |
| S2 | Rebuild session ToolManagers instead of registering into reused managers (architecture) | CONFIRM | The session TM is reused and swapped in wholesale (agent.py:1686). The effective view starts from `agent.tool_manager.clone()`, and owner-matched tools are removed via `get_toolkit_owner()`. | §2 Overview, §3 M9 |
| S3 | Persist datasource descriptors, not DatasetManager ctor params (architecture) | CONFIRM | `DatasetManagerConfig` separates ctor flags from `datasources: list[DatasourceSpec]`, and replay builds fresh sources via `add_*`. The shared source in `_clone_agent_dm` predates this feature and is noted. | §3 M3, §7 |
| S4 | Define vault ownership for agent-level secrets explicitly (risk) | CONFIRM | Explicit `vault_owner` on every spec; hydration runs server-side at build; delete/rotate semantics defined. | §2 Data Models, §3 M1/M7 |
| S5 | Do not persist agent-level MCP auth_config raw (risk) | CONFIRM | `AgentMCPServerSpec` splits `auth_config`/`headers` into the vault. | §2 Data Models, §3 M1/M7 |
| S6 | Require explicit config metadata for generic toolkits (risk) | REJECT | Contradicts the user's 2026-09-23 decision (heuristics + overlays). Partial mitigation kept: non-JSON-typed params are `x-server-managed`. | §7 Risks |
| S7 | Authorize and constrain dynamic option lookups (risk) | CONFIRM | Agent-scoped, owner + PBAC gated endpoint that evaluates only the persisted spec — no request-supplied URLs or credentials. | §2 Overview (8), §3 M7, §7 |
| S8 | One top-level JSON Schema envelope (api) | CONFIRM | Hard cut to `{slug, class_name, source, schema}`, contract-tested. | §2 Overview (4), §3 M2/M7 |
| S9 | Real persistence contract + migration before exposing toolkit_config (api) | CONFIRM | Verified `ChatbotHandler._post_database` stores every payload key (bots.py:1143) and `_put_database` does `BotModel(**payload)` (:887). Both refuse Studio-only fields; additive DDL. | §3 M4, §5 AC4 |
| S10 | Preserve the actual YAML path when editing (risk) | CONFIRM | `update_agent_tooling()` rewrites `metadata.file_path` in place, atomically, after a containment check. | §3 M6 |
| S11 | Version session overrides across reloads (architecture) | CONFIRM | Session marker `(tooling_revision, overrides_revision)`; a mismatch rebuilds. | §3 M9, §7 |

Summary: **10** confirmed · **1** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-23 | Jesus Lara (with Claude) | Initial draft from accepted brainstorm (Option A) + codex design research |
| 0.2 | 2026-09-23 | Jesus Lara (with Claude) | Approved; §8 FEAT-540 + parquet resolved (parquet → deltatable) |
