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

# Brainstorm: Tool Configuration for Agent Studio

**Date**: 2026-09-23
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

Operators can pick *which* tools an agent has, but nowhere can they configure
*how* a toolkit is built for that agent. Original request (verbatim):

> Tool-configuration support para AgentStudio
> - configuración de atributos per-Tool (por ejemplo Jira Toolkit > Jira
>   workspace, o si pongo QuerySlugToolkit > ¿cuáles WS?)
>   si hay un endpoint que retorna todas las tools activas: crear una UI para
>   configurarlo
> :: Mover el actual dataset config (del DatasetManager) y el MCP config a
>    Agent Studio.

Concretely, today:

- **The Admin UI agent form** (`/admin/agents/:name`, FEAT-475) offers the
  Capabilities tab: a checkbox list of tool *names* sourced from
  `GET /api/v1/agent_tools`. `BotModel.tools` is `List[str]`, so a database
  agent can say "jira" but never "jira against
  `https://troc.atlassian.net`, default project TROC". `JiraToolkit` therefore
  falls back to environment variables; `QuerysourceToolkit` gets no `programs`
  scope at all.
- **The Agent Studio backend** (`/api/v1/astudio/*`, FEAT-467) already exposes
  `GET /toolkits/{slug}/schema` (constructor introspection) and
  `POST /agents/{name}/toolkits` (`{slug, params}`) — but the assignment
  mutates only the live shared instance and answers `persisted: false`.
  Persistence was explicitly left out of TASK-2518. Nothing in the SPA
  consumes `/astudio` yet.
- **YAML agents** declare `toolkits: [str]` in `BotConfig`, but the loader loop
  that should register them is a `pass` stub (`registry.py:943-950`), and the
  `toolkits` kwarg the factory forwards is not consumed by `AbstractBot`. Only
  `tools: [str]` strings actually register toolkits (via
  `ToolInterface._initialize_tools` → `ToolkitRegistry.get(name)` →
  `register_toolkit(name)` with **no kwargs**).
- **Dataset and MCP configuration live inside the chat**: `DatasetTab.svelte`,
  `DatasetConfigModal.svelte` and `MCPServerTab.svelte` are mounted from
  `AgentChat.svelte`, backed by per-user, session-scoped state
  (`/api/v1/agents/datasets/{agent_id}` over a cloned `DatasetManager`;
  `GET /api/v1/agents/chat/{name}/mcp_servers` + `PATCH` over the session
  `ToolManager`, persisted per `(user, agent)` in DocumentDB by
  `MCPPersistenceService` and restored by
  `AgentTalk._restore_user_mcp_servers`). Operators have no agent-level surface
  for either.

**Who is affected**: operators building agents in the Admin UI (primary),
end users who need their own Jira credentials / query-slug scope (secondary),
and developers who today hand-edit YAML or write Python to wire a toolkit with
parameters.

**Why now**: FEAT-558 (`QuerysourceToolkit`, tenant-scoped `programs`) and
the Jira OAuth work make "which workspace / which tenants" a per-agent
decision that cannot be expressed in the UI; the Studio schema + assign
endpoints exist and are unused; the chat is accumulating configuration UI that
belongs to the agent, not the conversation.

## Constraints & Requirements

Decisions taken in discovery (Rounds 0–2):

- **Flow**: `type: feature`, `base_branch: dev`.
- **Persistence model — BOTH layers**: agent-level defaults set by the
  operator (persisted with the agent definition) **plus** per-user overrides.
- **Override policy**: the operator marks each param as `user_overridable` in
  Studio. Overrides are applied by building the toolkit for the *session*
  `ToolManager` (defaults + user overrides) — the shared bot instance is never
  mutated by a user override.
- **Secrets**: never stored in the agent's JSON/YAML. The schema marks params
  `secret`; values go to the encrypted vault (`parrot.security.vault_utils`,
  same AES-GCM keyring BYOK and MCP use) and the config keeps only a
  reference. `GET` returns masked values.
- **Registry (YAML) agents are editable when the YAML lives under
  `AGENTS_DIR`** (factory/Studio-written definitions): rewrite the `toolkits:`
  block via `AgentRegistry.create_agent_definition` and reload. Code (`.py`)
  agents stay read-only, as in FEAT-475.
- **UI target**: extend the existing `/admin/agents/:name` form with a new
  **Tools** tab that replaces the checkbox list (catalog of active tools +
  per-toolkit form rendered from the schema), plus **Datasets** and **MCP**
  sub-panels. The chat keeps a lighter "My settings" surface for per-user
  datasets, per-user MCP servers and per-user param overrides, on the
  per-user endpoints that already exist.
- **Agent-level datasets/MCP semantics**: Studio edits `mcp_servers` (already
  in `BotConfig`; **absent** from `BotModel`) and a new list of pre-registered
  datasources for the agent's `DatasetManager`. Per-user paths stay as today.
- **Declarative schema for complex toolkits**: constructor introspection is
  not enough for toolkits whose configuration is a *choice* (DatasetManager:
  a `query_slug`, **or** `table`+`schema`+`driver`(+`dsn`), **or** a CSV/Excel/
  Parquet path, **or** an Airtable base, **or** a Smartsheet sheet…). Such
  toolkits publish a JSON Schema (Draft 2020-12, generated from a Pydantic
  config model — precedent: `WikiConfig.model_json_schema()` already embedded
  by `_wiki_schema()` in `studio/toolkits.py:265`) with `oneOf` discriminated
  unions; the UI renders forms from the schema alone, never from
  toolkit-specific frontend code. Introspection stays as the fallback for
  simple toolkits.
- **Dynamic options**: toolkits may implement an optional
  `config_options(param, current_params)` hook; the schema advertises an
  `options_endpoint` and the UI renders a multi-select. `QuerysourceToolkit`
  (programs/tenants) and `JiraToolkit` (projects for a `server_url`)
  implement it; everything else stays free-form.
- Apply semantics follow FEAT-467: saving agent defaults returns
  `reload_required: true` with a **Reload** button (`POST /agents/{name}/reload`);
  no implicit reload.
- Hard cuts are acceptable (no external consumers): the checkbox list can be
  replaced, `BotWritePayload.tools: list[str]` may gain a sibling field
  rather than a shim.
- Non-negotiables: aiohttp handlers under `handlers/studio/`, Pydantic v2
  models, Svelte 5 runes, `pnpm generate` for TS types, secrets only in the
  vault, PBAC fail-open convention (`_pbac_gate`), ownership via
  `_require_owner`.

---

## Options Explored

### Option A: Toolkit config on the agent definition + session-scoped override layer

Extend the surfaces that already exist instead of introducing a new model
family.

- **Agent-level defaults** live in a new `toolkit_config` JSONB on `BotModel`
  (`{slug: {params, user_overridable: [...], secret_refs: {...}}}`) and in the
  YAML `toolkits:` block, whose entries become `str | {slug, params,
  user_overridable}` (`BotConfig.toolkits` widened; `create_agent_definition`
  round-trips it). A single `ToolkitSpec` Pydantic model in core defines the
  shape once.
- **Instantiation** flows through the one place toolkits are actually built:
  `ToolInterface._initialize_tools` learns to accept `ToolkitSpec` entries and
  calls `tool_manager.register_toolkit(slug, **params)` (which already accepts
  kwargs, `manager.py:1104`). The dead `toolkits` loop in
  `registry.py:943-950` is deleted in favour of this path.
- **Secrets**: the schema endpoint marks `secret` params (curated list per
  first-class toolkit + heuristics on names like `token`, `password`,
  `api_key`, `dsn`); on save the handler splits secrets out, stores them with
  `store_vault_credential(owner_id, f"toolkit_{slug}_{agent}", {...})` and
  keeps `secret_refs: {param: vault_name}` in the JSON. At build time the
  resolver hydrates them via `retrieve_vault_credential`.
- **Per-user overrides**: a new `ToolkitConfigService` mirroring
  `MCPPersistenceService` (DocumentDB collection `user_toolkit_configs`,
  keyed `(user_id, agent_id, slug)`, non-secret params + vault ref). Applied
  in `AgentTalk._configure_tool_manager` next to `_restore_user_mcp_servers`:
  for each toolkit with an override, register a fresh instance on the
  *session* `ToolManager` (defaults ⊕ override, only `user_overridable`
  params honoured; extras rejected 422).
- **Studio API additions** (all under `/api/v1/astudio`):
  `GET /agents/{name}/toolkits` (effective agent config, secrets masked),
  `PUT /agents/{name}/toolkits/{slug}` (persist defaults; returns
  `reload_required: true`), `DELETE` (remove), `GET
  /toolkits/{slug}/options/{param}` (dynamic options via the hook),
  `GET|PUT /agents/{name}/mcp-servers` (agent-level `mcp_servers`) and
  `GET|PUT /agents/{name}/datasets` (agent-level datasource list). Per-user:
  `GET|PUT|DELETE /agents/{name}/toolkits/{slug}/me`.
- **Schema, two tiers**: (a) `AbstractToolkit.config_schema()` classmethod
  (optional) returns a JSON Schema built from a Pydantic `*Config` model —
  `oneOf` discriminated unions for choice-shaped config (DatasetManager
  datasources), `enum` from `Literal`, defaults, descriptions; vendor
  extensions `x-secret`, `x-user-overridable`, `x-options-endpoint`,
  `x-ui-help`, `x-server-managed`. (b) toolkits without one keep the current
  `_introspect_params` path, which the handler lifts into the same JSON Schema
  shape (`properties`/`required`) so the SPA has a single renderer. First-class
  config models: `dataset_manager` (datasource union), `jira`, `querysource`;
  `wiki` already has `WikiConfig`.
- **UI**: new `TabsTools.svelte` replaces `TabsCapabilities`' checkbox list:
  left column = active tools/toolkits (from the existing `listTools()` +
  `/astudio/catalog/tools`), right column = per-toolkit drawer with a
  schema-driven form (`SchemaForm.svelte`: string/int/bool/list/enum/secret/
  dynamic-select widgets + `user_overridable` toggles). Sub-panels
  **Datasets** and **MCP servers** reuse the vendored `DatasetCreatePane` /
  `MCPServerTab` form pieces against the new agent-level endpoints. The chat
  keeps a slimmed "My settings" modal for per-user overrides.

✅ **Pros:**
- Builds on `StudioToolkitsHandler`, `MCPPersistenceService`, the vault
  helpers, `create_agent_definition` and the FEAT-475 form store — no new
  persistence technology.
- Closes the real gap (persistence) exactly where TASK-2518 left it.
- Per-user overrides reuse the proven session-`ToolManager` pattern, so the
  shared instance stays untouched.
- Incremental: agent-level defaults are shippable before the override layer.

❌ **Cons:**
- Two parallel definitions of truth remain (DB `BotModel` vs YAML
  `BotConfig`); the `ToolkitSpec` model must be applied to both and kept in
  sync.
- Secret classification by name heuristics is fallible; first-class toolkits
  need a curated list.
- The Capabilities tab is a hard cut for the checkbox UX (accepted).

📊 **Effort:** High (≈ 5 backend modules, 2 persistence services, 1 UI tab
with 3 panels, codegen, tests).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 (already a dep) | `ToolkitSpec`, request/response models, `model_json_schema()` | no new dep |
| `navigator-session` vault (`KeyRing`) via `parrot.security.vault_utils` | AES-GCM secret storage | already used by BYOK/MCP |
| DocumentDB (`parrot.handlers.mcp_persistence` pattern) | per-user overrides | existing collection style |
| `json-schema-to-typescript` (`pnpm generate`) | TS types for new payloads | already wired in `ui/package.json` |
| shadcn-svelte `Tabs`/`Switch`/`Checkbox`/`Slider` (vendored) | form widgets | already in `$lib/ui/internal/shadcn` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py` — `_introspect_params`, `_resolve_toolkit_class`, `_missing_required_params`, `ToolkitAssignRequest`.
- `packages/ai-parrot-server/src/parrot/handlers/mcp_persistence.py` — service shape for `ToolkitConfigService`.
- `packages/ai-parrot/src/parrot/security/vault_utils.py` — `store_vault_credential` / `retrieve_vault_credential` / `delete_vault_credential`.
- `packages/ai-parrot-server/src/parrot/handlers/agent.py` — `_configure_tool_manager`, `_restore_user_mcp_servers` (override application point).
- `packages/ai-parrot/src/parrot/registry/registry.py` — `create_agent_definition` (YAML round-trip).
- `packages/ai-parrot-server/ui/src/pages/agents/form/TabsCapabilities.svelte`, `ui/src/lib/stores/agent-form.svelte.ts`, `ui/src/lib/agents/fields.ts` — form store + tab plumbing.
- `packages/ai-parrot-server/ui/src/lib/components/agents/{DatasetCreatePane,MCPServerTab}.svelte` — form pieces for the sub-panels.

---

### Option B: One structured `AgentToolsConfig` model replaces `tools: List[str]` everywhere

Introduce `parrot/tools/spec.py` with `ToolSpec` / `ToolkitSpec` /
`MCPServerSpec` / `DatasetSpec` and an `AgentToolsConfig` aggregate, then make
it *the* representation: `BotModel.tools` becomes JSONB of specs (with a
migration from the string list), `BotConfig.tools`/`toolkits`/`mcp_servers`
collapse into `BotConfig.tooling: AgentToolsConfig`, `BotWritePayload`
follows, `_initialize_tools` accepts only specs, and every Studio endpoint
reads/writes the aggregate. Per-user overrides are an `AgentToolsConfig`
diff stored per `(user, agent)` and merged at session build.

✅ **Pros:**
- Single source of truth; no DB/YAML divergence; MCP + datasets + toolkits
  share one model and one merge algorithm.
- Cleanest long-term shape for the Studio meta-agent (one tool to edit tooling).

❌ **Cons:**
- Wide blast radius: `BotModel.tools` (`is_agent_enabled`,
  `get_available_tool_names`, `to_bot_config`), `ToolList`, the FEAT-475 form,
  `agents.yaml` readers, tests across three packages, plus a DB migration.
- Blocks on a schema migration of a live table; harder to ship incrementally.
- Rewrites working per-user MCP/dataset flows that are not the pain point.

📊 **Effort:** High+ (everything in A plus a migration and a cross-package
refactor).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | spec models | — |
| `asyncdb`/`navigator` model layer (`BotModel.Meta`) | JSONB column change + migration | migration tooling is ad hoc in this repo |
| same vault/DocumentDB/codegen as A | — | — |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/models/basic.py` — `ToolConfig` (`tools`, `mcp_servers`, `toolkits`) is an embryo of the aggregate.
- Everything listed for Option A.

---

### Option C: Reusable "toolkit profiles" catalog (org-wide), agents reference profiles

Model configuration as first-class, shareable objects — the same pattern as
the FEAT-467 shared **skills catalog**: `GET|POST|PUT|DELETE
/astudio/toolkit-profiles` stores named profiles (`{slug, params,
secret_refs, owner, visibility}`) in Postgres; an agent's `toolkits:` lists
`{slug, profile: "jira-troc"}` (plus optional inline overrides); a per-user
override is simply a user-owned profile bound to `(user, agent, slug)`. The
Tools tab becomes "pick a profile or create one", and one Jira workspace
profile serves twenty agents.

✅ **Pros:**
- De-duplicates the common case (one Jira/Querysource workspace across many
  agents); credential rotation happens in one place.
- Ownership/visibility/PBAC already have a template (`skills_catalog.py`).
- Naturally unifies agent-level and per-user configuration as "profile
  bindings".

❌ **Cons:**
- Extra indirection to reason about (agent → binding → profile → vault);
  YAML agents need a profile resolver at load time.
- More UI surface (profile CRUD + binding picker) before the first value.
- Not what the request literally asks for; risks over-design for v1.

📊 **Effort:** High (catalog table + CRUD + binding resolution + UI).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Postgres via existing Studio patterns (`skills_catalog.py`) | profile rows | — |
| same vault/codegen as A | — | — |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py` — owner-filterable, category-ordered catalog CRUD.
- `handlers/studio/_base.py` — `_require_owner`, `_pbac_gate`.

---

## Recommendation

**Option A** is recommended because:

- It fixes the actual gap — *persistence* of per-toolkit params and a
  *sanctioned* per-user override path — by extending the exact seams FEAT-467
  and the MCP work already opened (`StudioToolkitsHandler`,
  `MCPPersistenceService`, vault helpers, session `ToolManager`), so the
  first shippable slice (agent-level defaults + Tools tab) does not depend on
  a data migration.
- Option B's single model is attractive, but its cost is a cross-package
  refactor of `BotModel.tools` and a live-table migration, for a divergence
  (DB vs YAML) that A contains with one shared `ToolkitSpec` model and one
  round-trip test. We trade some duplication for incremental delivery.
- Option C solves a real reuse problem, but it is a second feature. A keeps
  the JSON shape open to it: `ToolkitSpec` can grow a `profile_ref` later
  without touching the persistence or the override merge.
- The dead `toolkits` loader loop and the unconsumed `toolkits` kwarg are
  latent bugs A removes as a side effect.

What we knowingly give up: the checkbox simplicity of the Capabilities tab
(the Tools tab must still make "just enable weather" a one-click action) and
secret detection that is heuristic outside the curated toolkits.

---

## Feature Description

### User-Facing Behavior

**Operator (Admin UI, `/admin/agents/:name` → new "Tools" tab)**

1. The tab lists every tool/toolkit the server knows (`listTools()` today,
   enriched with the Studio `tools` catalog) with an on/off switch. Turning a
   plain tool on keeps today's behaviour (`tools: [...]`).
2. Turning a **toolkit** on opens a right-hand configuration drawer rendered
   from `GET /astudio/toolkits/{slug}/schema`: typed inputs, defaults,
   required markers, `server_managed` params shown read-only ("wired by the
   server"), secret params as password fields (masked once saved, never
   echoed), and a **"users may override"** toggle per param.
3. Params with dynamic options (Querysource `programs`, Jira
   `default_project` once `server_url` is set) render as a multi-select fed by
   `GET /astudio/toolkits/{slug}/options/{param}?…current params…`, with a
   free-text fallback when the lookup fails.
4. **Save** persists the agent-level defaults; the drawer shows "Reload
   required" with a **Reload agent** action. **Test** (optional) calls the
   existing live assignment (`POST /agents/{name}/toolkits`) on a session
   instance and reports registered tool names or the 422 details.
5. **Datasets** sub-panel: the `dataset_manager` toolkit's own schema form —
   a **kind** selector (query slug · SQL · table+schema+driver · CSV/Excel/
   Parquet file · Airtable · Smartsheet · Iceberg · Mongo · Delta) whose
   sub-form comes from the `oneOf` branch; the list is saved as the toolkit's
   params and loaded into memory on (re)build.
6. **MCP servers** sub-panel: the agent-level `mcp_servers` list (name,
   transport, url/command, allowed/blocked tools, headers) — same fields as
   the vendored `MCPServerTab`, persisted at agent level.
7. Registry agents whose YAML lives under `AGENTS_DIR` get the same tab
   (writes go to the YAML); `.py` agents show the tab read-only with an
   explanation.

**End user (chat, "My settings")**

- Sees only toolkits with at least one `user_overridable` param, the
  per-user datasets and per-user MCP servers. Saving an override takes effect
  on the next session (or immediately via the existing PATCH re-setup). Their
  secrets are stored in their own vault entries; the operator never sees them.

### Internal Behavior

1. **Shape**: `ToolkitSpec {slug, params: dict, user_overridable: list[str],
   secret_refs: dict[param, vault_name]}` (core Pydantic). `BotModel` gains
   `toolkit_config: dict[slug, ToolkitSpec-like]` and `mcp_servers: list[dict]`
   JSONB columns (nullable, default empty). No `datasets` column: agent-level
   datasources are the `params.datasources` list of the `dataset_manager`
   `ToolkitSpec`. `BotConfig.toolkits` accepts `str | ToolkitSpec`;
   `create_agent_definition` writes both.
2. **Schema**: `GET /astudio/toolkits/{slug}/schema` returns one JSON Schema
   document per toolkit. If the class defines `config_schema()` (Pydantic
   `*Config` model → `model_json_schema()`), that is the document; otherwise
   `_introspect_params` output is lifted into `properties`/`required`. Both
   carry `x-secret` / `x-user-overridable` / `x-options-endpoint` /
   `x-ui-help` / `x-server-managed`. The DatasetManager model is the reference
   case — `DatasetManagerConfig{datasources: list[DatasourceSpec], max_rows,
   …}` with `DatasourceSpec = Annotated[Union[...], Field(discriminator="kind")]`
   over the constructors that exist today:
   `query_slug{slug, permanent_filter?}`, `sql{sql, driver, dsn?|credentials?}`,
   `table{table, schema?, driver, dsn?|credentials?, allowed_columns?}`,
   `file{path (csv|xlsx|parquet), read_kwargs?}`, `airtable{base_id, table,
   view?, api_key*}`, `smartsheet{sheet_id, access_token*}`, plus
   `iceberg`/`mongo`/`deltatable` mirroring their `add_*_source` signatures
   (`*` = `x-secret`). The SPA renders `oneOf` as a kind selector + sub-form.
3. **Persist (agent level)**: `PUT /astudio/agents/{name}/toolkits/{slug}`
   validates params against the JSON Schema (server-side, `jsonschema` or
   the Pydantic model itself), splits `x-secret` values → the per-user
   navigator-session vault (`KeyRing` from the operator's user session) under
   the *agent owner's* user id with name `toolkit_{slug}_{agent}`, writes the
   spec to `BotModel.toolkit_config` (DB agents) or rewrites the YAML
   (`AGENTS_DIR` registry agents), and returns `reload_required: true`.
   Ownership + PBAC (`astudio:toolkits:persist`) as in the other Studio
   views.
4. **Build (agent level)**: `BotModel.to_bot_config()` and the registry
   factory both pass `ToolkitSpec` entries in `tools`; `_initialize_tools`
   resolves secrets (`retrieve_vault_credential`), then
   `tool_manager.register_toolkit(slug, **params)`. Missing vault → toolkit
   skipped with a WARNING (not a boot failure). Agent-level datasources are
   **in-memory only**: at build the `dataset_manager` spec is replayed into
   the agent's `_dataset_manager` (`add_dataset` / `add_table_source` /
   `load_file` / `add_airtable_source` / `add_smartsheet_source` …), nothing
   is persisted beyond the spec, and a reload rebuilds it (the chat's
   `_clone_agent_dm` already copies it into the user's manager); agent-level `mcp_servers`
   reuse the registry's existing `add_mcp_server` loop (the DB path gains the
   same loop).
5. **Override (user level)**: `ToolkitConfigService.save/load/remove` on
   DocumentDB collection `user_toolkit_configs`; only `user_overridable`
   params accepted (422 otherwise); user secrets → vault under the *user's*
   id. `AgentTalk._configure_tool_manager` (after MCP restore) loads
   overrides and registers `slug` on the **session** `ToolManager` with
   `defaults ⊕ override` (removing the agent-level tools of that slug from
   the session view first, since tool names collide).
6. **Dynamic options**: `AbstractToolkit.config_options(param,
   current_params) -> list[{value,label}]` (async, optional, default raises
   `NotImplementedError`). The handler instantiates the toolkit *lazily and
   read-only* with the current non-secret params + hydrated secrets, calls
   the hook with a timeout, and never registers it.
7. **Reload**: unchanged `BotManager.reload_agent`; UI surfaces
   `ReloadResult.warnings`.

### Edge Cases & Error Handling

- **Unknown slug / toolkit removed from the package**: schema 404; saved
  config is kept and shown as "unavailable" (mirrors the Capabilities tab's
  "unknown tools are never silently dropped" rule).
- **Constructor signature changed** (param disappeared): schema diff shows the
  stale param; build passes only known params and logs the rest.
- **Vault unavailable** at save → 503 `vault_unavailable` (BYOK convention);
  at build → toolkit skipped + warning, agent still boots.
- **Secret echo**: `GET` never returns plaintext; a `PUT` with the masked
  sentinel leaves the vault entry untouched.
- **Override of a non-overridable or `server_managed` param** → 422 with the
  offending names.
- **Tool name collision** between agent-level and user-level instances of the
  same toolkit: the session `ToolManager` view replaces, never duplicates.
- **`.py` registry agents**: 409 `read_only_definition` on `PUT`; the live
  assignment endpoint still works (non-persisted), as today.
- **Registry agents with YAML outside `AGENTS_DIR`** (repo-committed): treated
  as read-only (same safety check `DELETE /agents/{name}` applies).
- **Dynamic options failure** (network, bad credentials): 502 with a message;
  the UI degrades to free text.
- **`ToolkitRegistry` filters by class name containing "Toolkit"**, so
  `dataset_manager` is *not* a registry toolkit; the spec path must resolve
  through `TOOL_REGISTRY` + `resolve_class` (as `_resolve_toolkit_class`
  does), not `ToolkitRegistry.get`.

---

## Capabilities

### New Capabilities
- `toolkit-config-persistence`: `ToolkitSpec` model; `BotModel.toolkit_config`/`mcp_servers`; widened `BotConfig.toolkits`; YAML round-trip; build-time hydration in `_initialize_tools` (incl. in-memory datasource replay for `dataset_manager`).
- `toolkit-config-json-schema`: `AbstractToolkit.config_schema()` classmethod + Pydantic config models (`DatasetManagerConfig` with the `DatasourceSpec` discriminated union, `JiraToolkitConfig`, `QuerysourceToolkitConfig`); introspection fallback lifted to the same JSON Schema shape; `x-secret`/`x-user-overridable`/`x-options-endpoint`/`x-ui-help`/`x-server-managed` extensions; `config_options` hook on `AbstractToolkit` (+ Jira, Querysource implementations).
- `toolkit-config-studio-api`: `GET/PUT/DELETE /astudio/agents/{name}/toolkits[/{slug}]`, `GET /astudio/toolkits/{slug}/options/{param}`, agent-level `mcp-servers` and `datasets` endpoints.
- `toolkit-user-overrides`: `ToolkitConfigService` (DocumentDB) + `/…/toolkits/{slug}/me` endpoints + session-`ToolManager` application in `AgentTalk`.
- `admin-ui-tools-tab`: `TabsTools.svelte` with schema-driven `SchemaForm`, Datasets and MCP sub-panels; codegen of new payload types; nav/route unchanged.
- `agentchat-my-settings`: slimmed per-user settings modal in the chat replacing the mounted Dataset/MCP tabs.

### Modified Capabilities
- `agentstudio-management` (FEAT-467) — toolkit surfaces gain persistence; `StudioToolkitsHandler` extended.
- `ui-agent-management` (FEAT-475) — Capabilities tab's tools list is replaced by the Tools tab; `BotWritePayload` gains fields.
- `agentchat-migration` (FEAT-476) — `DatasetTab`/`MCPServerTab` mounting changes.
- `mcp-mixin-helper-handler` (TASK-771/772 lineage) — restore hook gains a sibling for toolkit overrides.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `handlers/studio/toolkits.py` (`StudioToolkitsHandler`) | extends | schema enrichment, persist/options/me endpoints |
| `handlers/studio/__init__.py` | extends | new `add_view` routes under `STUDIO_PREFIX` |
| `handlers/studio/models.py` | extends | request/response models (`ToolkitSpecPayload`, masked responses) |
| `handlers/models/bots.py` (`BotModel`, `to_bot_config`) | modifies | 3 new JSONB fields; passes specs into `tools` |
| `parrot/server/ui/models.py` (`BotWritePayload`, `BotAgentItem`) + `scripts/generate_ts_types.py` | extends | new fields → `pnpm generate` |
| `parrot/registry/registry.py` (`BotConfig`, factory, `create_agent_definition`) | modifies | widened `toolkits`, new `datasets`, delete dead loop |
| `parrot/interfaces/tools.py` (`_initialize_tools`) | modifies | accept `ToolkitSpec`, hydrate secrets, pass kwargs |
| `parrot/tools/toolkit.py` (`AbstractToolkit`) | extends | optional `config_schema()` classmethod + `config_options` hook (+ class attr for default overridables) |
| `parrot/tools/dataset_manager/tool.py` (`DatasetManager`) | extends | `DatasetManagerConfig` / `DatasourceSpec` Pydantic union + `config_schema()`; build-time replay of datasources |
| `parrot_tools/jiratoolkit.py`, `parrot_tools/querysource/toolkit.py` | extends | implement `config_options` |
| `handlers/agent.py` (`AgentTalk._configure_tool_manager`) | extends | apply user overrides on the session `ToolManager` |
| new `handlers/toolkit_persistence.py` (`ToolkitConfigService`) | new | DocumentDB per-user overrides (pattern: `mcp_persistence.py`) |
| `parrot/security/vault_utils.py` | depends on | store/retrieve/delete secrets |
| Admin UI: `pages/agents/AgentForm.svelte`, `form/TabsCapabilities.svelte` → `form/TabsTools.svelte`, `lib/agents/fields.ts`, `lib/stores/agent-form.svelte.ts`, `lib/api/agents.ts`, new `lib/api/studio.ts` | modifies / new | Tools tab, schema form, sub-panels |
| Admin UI chat: `components/agents/AgentChat.svelte`, `DatasetTab.svelte`, `MCPServerTab.svelte` | modifies | mount a "My settings" modal instead |
| DB | schema change | 2 nullable JSONB columns on the bots table (`toolkit_config`, `mcp_servers`; additive) |
| Docs: `docs/agent_studio_api.md`, `docs/admin-ui.md`, `docs/agent_config_creation.md` | extends | new endpoints / tab / YAML shape |

No new Python dependencies. Breaking change limited to the Capabilities tab
UX (accepted hard cut).

---

## Code Context

### User-Provided Code

```text
# Source: user-provided (invocation notes, verbatim)
# Tool-configuration support para AgentStudio
- configuración de atributos per-Tool (por ejemplo Jira Toolkit > Jira workspace,
  o si pongo QuerySlugToolkit > ?¿cuales WS?)
  si hay un endpoint que retorna todas las tools activas:
    crear una UI para configurarlo
:: Mover el actual dataset config (del DatasetManager) y el MCP config a Agent Studio.
```

### Verified Codebase References

All paths relative to the repo root; verified on `dev` @ `ab0532e15`
(2026-09-23).

#### Classes & Signatures

```python
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py
class ToolkitAssignRequest(BaseModel):                       # :62
    slug: str                                                # :65
    params: dict[str, Any] = Field(default_factory=dict)     # :66
def _introspect_params(cls: type, *, server_managed: frozenset[str] = frozenset()) -> dict[str, dict[str, Any]]:  # :107
def _missing_required_params(cls: type, provided: dict) -> list[str]:   # :139
def _resolve_toolkit_class(slug: str) -> type | None:                   # :154  (discover_from_registry + resolve_class)
def _validate_wiki_storage_dir(raw: Path) -> Path:                      # :181
class StudioToolkitsHandler(_StudioAgentsMixin, StudioBaseView):       # :219
    async def get(self): ...          # :235  GET /toolkits/{slug}/schema
    async def post(self): ...         # :286  POST /agents/{name}/toolkits — live only, persisted: False (:341-347)
    async def _assign_wiki(self, bot, params) -> tuple[list[str], dict]: ...          # :352
    def _assign_dataset_manager(self, bot, params) -> tuple[list[str], dict]: ...     # :410
    def _assign_infographic(self, bot, params) -> tuple[list[str], dict]: ...         # :424
    def _assign_generic(self, bot, slug, params) -> tuple[list[str], dict]: ...       # :445

# packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py
STUDIO_PREFIX = "/api/v1/astudio"                            # :23
app.router.add_view(f"{STUDIO_PREFIX}/agents/{{name}}/tools", StudioToolAssignHandler)   # :107
# toolkits schema/assign routes are registered right after (:108-111)

# packages/ai-parrot-server/src/parrot/handlers/studio/_base.py
class StudioBaseView:
    async def _resolve_session(self) -> Any: ...             # :141
    async def _get_user(self) -> StudioUser: ...             # :164
    def _require_owner(self, resource_owner: Any, user: StudioUser) -> None: ...   # :230  raises web.HTTPForbidden
    async def _pbac_allowed(self, resource: str, action: str) -> bool: ...          # :274  fail-open
    async def _pbac_gate(self, resource: str, action: str): ...                     # :308  returns a response or None

# packages/ai-parrot-server/src/parrot/handlers/studio/agents.py
class _StudioAgentsMixin:
    def _manager(self): ...                                  # :42   BotManager or None
    def _registry(self): ...                                 # :46   AgentRegistry or None
    async def _get_db_agent(self, name: str) -> BotModel | None: ...   # :51
    def _registry_agent_owner(meta: Any) -> str | None: ...  # :106 (static)
# persist path used by POST /agents: registry.create_agent_definition(bot_config, category=...)   # :330

# packages/ai-parrot-server/src/parrot/handlers/models/bots.py
class BotModel(Model):                                       # :20
    tools_enabled: bool = Field(default=True, ...)           # :158
    tools: List[str] = Field(default_factory=list, ...)      # :165  ← string-only today
    permissions: dict = Field(...)                           # :239
    def to_bot_config(self) -> dict: ...                     # :321  passes 'tools': self.tools at :340
def create_bot(bot_model: BotModel, bot_class=None): ...     # :613  bot_class(**bot_model.to_bot_config())

# packages/ai-parrot-server/src/parrot/server/ui/models.py
class BotAgentItem(BaseModel): ...                           # :20
class BotWritePayload(BaseModel):                            # :62
    tools: list[str] | None = None                           # :101

# packages/ai-parrot/src/parrot/registry/registry.py
class BotConfig(BaseModel):                                  # ~:224
    tools: Optional[ToolConfig] = Field(default=None)        # :235
    toolkits: List[str] = Field(default_factory=list)        # :236
    mcp_servers: List[Dict[str, Any]] = Field(default_factory=list)   # :237
# factory forwards merged_kwargs["toolkits"] (:120-121) — NOT consumed by AbstractBot.__init__
# post-instantiation toolkit loop is a `pass` stub (:943-950); mcp_servers loop uses bot.add_mcp_server (:938)
class AgentRegistry:
    def create_agent_definition(self, config: BotConfig, category: str = "general") -> Path: ...   # :1069
    # writes agent_section["toolkits"] = list(config.toolkits), ["mcp_servers"] = config.mcp_servers   # :1125-1126

# packages/ai-parrot/src/parrot/models/basic.py
class ToolConfig(BaseModel):                                 # :33
    tools: List[Dict[str, Any]]; mcp_servers: List[Dict[str, Any]]; toolkits: List[str]   # :35-37

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot:
    def __init__(self, name="Nav", system_prompt=None, llm=None, instructions=None,
                 tools: List[Union[str, AbstractTool, ToolDefinition]] = None, ...,  # :274-280
                 **kwargs): ...
    # self._initialize_tools(tools)                          # :405

# packages/ai-parrot/src/parrot/interfaces/tools.py
class ToolInterface:
    def _initialize_tools(self, tools: List[Union[str, AbstractTool, ToolDefinition]]) -> None: ...
    # str branch: ToolkitRegistry.get(tool.lower()) → self.tool_manager.register_toolkit(tool)  (no kwargs)
    #             else self.tool_manager.load_tool(tool)
    def _capture_knowledge_toolkit(self, toolkit: Any) -> None: ...

# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager:
    def load_tool(self, tool_name: str, **kwargs) -> bool: ...                                    # :1016
    def register_toolkit(self, toolkit: Union[str, "AbstractToolkit", type], **kwargs) -> List[AbstractTool]: ...  # :1104
    # str → ToolkitRegistry.get(name) → toolkit_class(**kwargs)   (:1140-1150)
    def list_tools(self) -> List[str]: ...                   # :1307
    def remove_tool(self, tool_name: str) -> None: ...       # :1342
    async def cleanup_toolkits(self) -> None: ...            # :2755
# packages/ai-parrot/src/parrot/tools/mcp_mixin.py
    self._mcp_configs: Dict[str, 'MCPServerConfig'] = {}    # :53
    async def add_mcp_server(self, config: 'MCPServerConfig', context: Optional['ReadonlyContext'] = None) -> List[str]: ...  # :57
    async def remove_mcp_server(self, server_name: str) -> bool: ...   # :363
    def list_mcp_servers(self) -> List[str]: ...             # :453

# packages/ai-parrot/src/parrot/tools/registry.py
def _discover_toolkits() -> Dict[str, Type["AbstractToolkit"]]: ...   # only classes whose name contains "Toolkit" (+ "openapi")
class ToolkitRegistry:
    @classmethod def get(cls, name: str) -> Type["AbstractToolkit"]: ...   # name.lower()

# packages/ai-parrot/src/parrot/tools/discovery.py
def discover_from_registry(...) -> Dict[str, str]: ...      # :31
def discover_all(...) -> Dict[str, str]: ...                # :111
def resolve_class(dotted_path: str) -> Type: ...            # :139

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                  # :206
    exclude_tools: tuple[str, ...] = ()                      # :243
    tool_prefix: str | None = None                           # :257
    credential_provider: str | None = None                   # :312
    auto_open: bool = False                                  # :319
    def __init__(self, **kwargs): ...                        # :321  stores self._init_kwargs = dict(kwargs)
    async def _open(self) / _close(self) / _ensure_open(self)   # :390 / :406 / :419
    def get_tools_sync(...) ...                              # :602
    def get_toolkit_info(self) -> dict[str, Any]: ...        # :693

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class JiraToolkit(AbstractToolkit):                          # :600
    def __init__(self, server_url=None, auth_type=None, username=None, password=None, token=None,
                 oauth_consumer_key=None, oauth_key_cert=None, oauth_access_token=None,
                 oauth_access_token_secret=None, default_project=None, credential_resolver: Any = None,
                 workflow_paths: Optional[Dict[str, Union[str, List[str]]]] = None,
                 verify_credentials: bool = True, **kwargs): ...        # :671-687

# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py
class QuerysourceToolkit(AbstractToolkit):                   # :56
    def __init__(self, programs: list[str] | None = None, allow_write: bool = False,
                 allow_raw_sql: bool = False, allow_external_sources: bool = True,
                 include_sql: bool = True, max_rows: int = 200,
                 forced_conditions: dict[str, Any] | None = None, dsn: str | None = None,
                 multiquery_timeout: float = 600.0, **kwargs: Any) -> None: ...   # :64-76

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetInfo(BaseModel):                                # :60   (LLM-facing OUTPUT model, not a config model)
    source_type: Literal["dataframe", "query_slug", "sql", "table", "airtable", "smartsheet",
                         "iceberg", "mongo", "deltatable", "composite"]   # :70-73
class DatasetManager(AbstractToolkit):                       # :501
    async def load_file(self, name: str, path: Union[str, Path], metadata=None,
                        max_rows_per_table: int = 200, output_format: str = "markdown") -> str: ...   # :1222  CSV/Excel
    async def add_table_source(...)      # :1459
    async def add_airtable_source(...)   # :1608
    async def add_smartsheet_source(...) # :1652
    async def add_iceberg_source(...)    # :1696
    async def add_mongo_source(...)      # :1780
    async def add_deltatable_source(...) # :1860
    async def create_deltatable_from_parquet(self, ..., parquet_path: str, ...)   # :2103

# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/  (each is the natural `oneOf` branch)
class QuerySlugSource: __init__(self, slug: str, prefetch_schema_enabled: bool = True, permanent_filter=None)   # query_slug.py:51-56
class TableSource:     __init__(self, table: str, driver: str, dsn: Optional[str] = None, credentials: Optional[Dict] = None,
                                strict_schema: bool = True, permanent_filter=None, allowed_columns: Optional[List[str]] = None)   # table.py:181-190
class AirtableSource(DataSource):   __init__(self, base_id: str, table: str, api_key: Optional[str] = None, view: Optional[str] = None)   # airtable.py:15-24  (api_key → x-secret)
class SmartsheetSource(DataSource): __init__(self, sheet_id: str, access_token: Optional[str] = None)   # smartsheet.py:14-17  (access_token → x-secret)
# also: sql.py, iceberg.py, mongo.py, deltatable.py, composite.py, memory.py

# packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py — JSON-Schema precedent + stub to replace
    @staticmethod
    def _wiki_schema() -> dict:                              # :262
        params = _introspect_params(LLMWikiToolkit, server_managed=frozenset({...}))
        if "config" in params:
            params["config"]["schema"] = WikiConfig.model_json_schema()   # :265  ← Pydantic → JSON Schema already used here
    @staticmethod
    def _dataset_manager_schema() -> dict:                   # :269  today: bare _introspect_params(DatasetManager)
# packages/ai-parrot/src/parrot/knowledge/wiki/models.py
class WikiConfig(BaseModel): ...                             # :52
    async def add_dataset(self, name: str, *, description=None, query_slug=None, query=None, table=None,
                          dataframe=None, driver=None, dsn=None, credentials=None, conditions=None,
                          sql=None, filter=None, metadata=None, is_active=True, permanent_filter=None,
                          computed_columns=None, usage_guidance=None) -> str: ...   # :966-985

# packages/ai-parrot-server/src/parrot/handlers/datasets.py
# routes (docstring :5-10): GET/PATCH/PUT/POST/DELETE /api/v1/agents/datasets/{agent_id}, GET .../{dataset_id}
def _clone_agent_dm(agent: object, logger: object) -> DatasetManager | None: ...   # :47  reads agent._dataset_manager (:61)
async def _resolve_dataset_manager(request, agent_id, session_key, logger) -> DatasetManager: ...   # :91
class DatasetManagerHandler(BaseView):                       # :141
    async def _get_dataset_manager(self, agent_id: str) -> DatasetManager: ...   # :162  session key via UserObjectsHandler.get_session_key(agent_id, "dataset_manager") (:173)

# packages/ai-parrot-server/src/parrot/handlers/agent.py  (AgentTalk)
    async def _filter_mcp_servers_for_user(self, mcp_server_configs: list) -> list: ...        # :355  PBAC filter
    async def _add_mcp_servers(self, agent: AbstractBot, mcp_configs: list): ...               # :634
    async def _add_mcp_servers_to_tool_manager(self, tool_manager: ToolManager, mcp_configs: list) -> None: ...   # :666
    async def _configure_tool_manager(...)                                                     # :690
    # PATCH: standalone mcp_servers → _add_mcp_servers (:999-1002); if agent.enable_mcp_restore → _restore_user_mcp_servers (:1006-1011)
    async def _restore_user_mcp_servers(self, tool_manager: Any, request_session: Any, agent_name: str) -> None: ...   # :1076
    # GET method_name == "mcp_servers": reads session[f"{agent_name}_tool_manager"]._mcp_configs   # :2202-2235

# packages/ai-parrot-server/src/parrot/handlers/mcp_persistence.py
class MCPPersistenceService:                                 # :36
    async def save_user_mcp_config(self, config: UserMCPServerConfig) -> None: ...             # :49
    async def load_user_mcp_configs(self, user_id: str, agent_id: str) -> List[UserMCPServerConfig]: ...   # :94
    async def remove_user_mcp_config(self, user_id: str, agent_id: str, server_name: str) -> bool: ...     # :136

# packages/ai-parrot/src/parrot/mcp/registry.py
class MCPParamType(str, Enum): STRING, INTEGER, BOOLEAN, SECRET   # :30-41  (SECRET ⇒ vault, masked input)
class MCPServerDescriptor(BaseModel): name, display_name, description, method_name, params, category   # :62
class UserMCPServerConfig(BaseModel): server_name, agent_id, user_id, params, vault_credential_name, active   # :96
class ActivateMCPServerRequest(BaseModel): server: str; params: Dict[str, Any]   # :131

# packages/ai-parrot/src/parrot/security/vault_utils.py
def get_vault_keyring() -> Any: ...                          # :49
async def store_vault_credential(user_id: str, vault_name: str, secret_params: Dict[str, Any]) -> None: ...   # :84
async def retrieve_vault_credential(user_id: str, vault_name: str) -> Dict[str, Any]: ...                     # :135
async def delete_vault_credential(user_id: str, vault_name: str) -> None: ...                                 # :172
# packages/ai-parrot/src/parrot/security/credentials_utils.py
def llm_key_context(user_id: Any, provider: str) -> VaultContext: ...   # :68
def encrypt_credential(...)                                  # :83
def decrypt_credential(...)                                  # :108
# packages/ai-parrot-server/src/parrot/handlers/studio/byok.py
async def resolve_user_api_key(app: Any, user_id: str, provider: str) -> str | None: ...   # :55

# packages/ai-parrot-server/src/parrot/manager/manager.py
class ReloadResult(BaseModel): name, reloaded, previous_instance_closed, warnings   # :159
class BotManager:
    async def get_bot(self, name: str, new: bool = False, session_id: str = "", request: Optional[web.Request] = None, **kwargs) -> AbstractBot: ...   # :728
    async def reload_agent(self, name: str) -> ReloadResult: ...   # :864

# packages/ai-parrot-server/src/parrot/handlers/bots.py
class _PBACHandlerMixin: ...                                 # :45
class ToolList(_PBACHandlerMixin, BaseView): ...             # :1345  GET /api/v1/agent_tools → {"tools": {name: {module_path, ...}}} (:1401), source discover_all()
# packages/ai-parrot-server/src/parrot/handlers/tools_catalog.py
def _build_catalog() -> List[Dict[str, Any]]: ...            # :44   GET /api/v1/tools/catalog — {slug, dotted_path, description?, category?}
```

```typescript
// packages/ai-parrot-server/ui/src/App.svelte — routes (:17-50): /admin/login, /admin/home, /admin/dashboard,
//   /admin/agents, /admin/agents/new, /admin/agents/:name, /admin/agents/:name/chat
// packages/ai-parrot-server/ui/src/pages/agents/AgentForm.svelte
const TABS: { id: TabId; label: string }[] = [ general, behavior, ai, capabilities, data_memory, advanced ];   // :90-97
<TabsContent value="capabilities"> <TabsCapabilities state={formState} {catalog} {tools} /> ...             // :198
// packages/ai-parrot-server/ui/src/pages/agents/form/TabsCapabilities.svelte
let { state, catalog, tools }: { state: AgentFormState; catalog: AdminCatalog; tools: Record<string, ToolInfo> } = $props();
// packages/ai-parrot-server/ui/src/lib/agents/fields.ts — FIELD → tab map: tools_enabled/auto_tool_detection/tool_threshold/tools → "capabilities"   // :123-126
// packages/ai-parrot-server/ui/src/lib/stores/agent-form.svelte.ts
export class AgentFormState { load(agent: BotAgentItem): void /*:118*/; validate(): boolean /*:167*/; diff(): Partial<BotWritePayload> /*:201*/; payload(): BotWritePayload /*:216*/ }   // :77
// packages/ai-parrot-server/ui/src/lib/api/agents.ts
export async function updateAgent(...)   // :58
export async function listTools(): Promise<ToolsListResponse>   // :81
export async function getCatalog(): Promise<AdminCatalog>       // :87
// packages/ai-parrot-server/ui/src/lib/api/agent.ts
const BASE_PATH = "/api/v1/agents/chat";                          // :11
export interface MCPServerEntry { name; url?; transport?; auth_type?; auth_config?; headers?; allowed_tools?; blocked_tools?; description?; connected?; tool_count? }   // :188-201
export const getAgentMCPServers = (agentName) => GET `${BASE_PATH}/${agentName}/mcp_servers`   // :203
export const saveAgentMCPServers = (agentName, mcpServers) => PATCH `${BASE_PATH}/${agentName}` { mcp_servers }   // :212
const DATASET_PATH = "/api/v1/agents/datasets";                    // :226
export const listDatasets / toggleDataset / uploadDataset / addQueryDataset / deleteDataset   // :229 / :241 / :256 / :271 / :285
// packages/ai-parrot-server/ui/src/lib/types/dataset.ts — DatasetEntry, DatasetAddRequest, DatasourceType ("query_slug"|"sql"|"table"|"smartsheet"|"airtable"|"dataframe")
// packages/ai-parrot-server/ui/src/lib/components/agents/{DatasetTab,DatasetConfigModal,DatasetCreatePane,DatasetInlinePreview,MCPServerTab,DataManagementModal}.svelte — vendored (FEAT-476), mounted from AgentChat.svelte
// Codegen: scripts/generate_ts_types.py — export_schemas() (:89) over the model map (:71-87) → ui/schemas/*.json → `pnpm generate` (ui/package.json:15)
```

#### Verified Imports
```python
from parrot.tools.discovery import discover_from_registry, resolve_class    # handlers/studio/toolkits.py:26
from parrot.tools.dataset_manager.tool import DatasetManager                # handlers/studio/toolkits.py:25
from parrot.knowledge.wiki import LLMWikiToolkit, WikiConfig                # handlers/studio/toolkits.py:27 (TASK-3263 keeps this import valid)
from parrot_tools import TOOL_REGISTRY                                      # handlers/tools_catalog.py (try/except ImportError)
from parrot.handlers.mcp_persistence import MCPPersistenceService           # handlers/mcp_helper.py:38
from parrot.mcp.registry import ActivateMCPServerRequest, MCPParamType, MCPServerRegistry, UserMCPServerConfig, get_factory_map   # handlers/mcp_helper.py:43-49
from parrot.security.vault_utils import get_vault_keyring                   # handlers/studio/byok.py:25
from parrot.security.credentials_utils import decrypt_credential, encrypt_credential, llm_key_context   # handlers/studio/byok.py:20-24
from parrot.handlers.vault_utils import delete_vault_credential, store_vault_credential   # handlers/mcp_helper.py:39-42 (thin re-export module in core: packages/ai-parrot/src/parrot/handlers/vault_utils.py)
from parrot.tools.manager import ToolManager                                # handlers/mcp_helper.py:50
from parrot.handlers.bots import ToolList                                   # tests/test_tools_list_route.py
from parrot.manager.manager import BotManager                               # tests/test_tools_list_route.py
```

#### Key Attributes & Constants
- `TOOL_REGISTRY["jira"] = "parrot_tools.jiratoolkit.JiraToolkit"` (packages/ai-parrot-tools/src/parrot_tools/__init__.py:83)
- `TOOL_REGISTRY["querysource"] = "parrot_tools.querysource.toolkit.QuerysourceToolkit"` (…/__init__.py:135)
- `TOOL_REGISTRY["dataset_manager"] = "parrot.tools.dataset_manager.DatasetManager"` (…/__init__.py:224) — **not** matched by `ToolkitRegistry` (class name lacks "Toolkit")
- Session keys: `f"{agent_name}_tool_manager"` (handlers/agent.py:2212, handlers/mcp_helper.py); `UserObjectsHandler.get_session_key(agent_id, "dataset_manager")` (handlers/datasets.py:173)
- Vault naming precedent: `f"mcp_{server}_{agent_id}"` (handlers/mcp_helper.py); BYOK collection `"user_llm_keys"`, session prefix `"_byok:"` (studio/byok.py:31-32)
- Agent-level MCP restore gate: `agent.enable_mcp_restore` (handlers/agent.py:1006)
- Bot capture attributes: `_pageindex_toolkit`, `_graphindex_toolkit`, `_llmwiki_toolkit` (interfaces/tools.py `_capture_knowledge_toolkit`); `_dataset_manager` (read by handlers/datasets.py:61)
- Studio error shape `StudioError {message, code, details}`; codes in use: `invalid_json`, `invalid_request`, `not_found`, `not_owner`, `unavailable`, `server_managed`, `invalid_params`, `vault_unavailable` (docs/agent_studio_api.md)
- Admin nav is data-only: `navEntries` in `ui/src/lib/nav.ts` (no change needed for a tab)

### Does NOT Exist (Anti-Hallucination)
- ~~`BotModel.mcp_servers`~~, ~~`BotModel.toolkits`~~, ~~`BotModel.toolkit_config`~~, ~~`BotModel.datasets`~~ — `BotModel` only has `tools: List[str]` (models/bots.py:165). `mcp_servers` exists on the YAML `BotConfig` (registry.py:237) only.
- ~~`BotConfig.datasets`~~ — no dataset field on YAML definitions.
- ~~A working YAML `toolkits:` loader~~ — `registry.py:943-950` is a `pass` stub; the `toolkits` kwarg forwarded at :120-121 is not read by `AbstractBot.__init__` or any `bots/*.py`.
- ~~`AbstractToolkit.config_schema`~~, ~~`DatasetManagerConfig`~~, ~~`DatasourceSpec`~~ — no Pydantic *config* model exists for `DatasetManager` (only the output model `DatasetInfo`); the datasource kinds are implied by `add_*_source` methods and `sources/*.py` constructors.
- ~~`AbstractToolkit.config_options`~~, ~~`AbstractToolkit.user_overridable`~~, ~~`AbstractToolkit.secret_params`~~ — no config-metadata hooks on the base class; only `credential_provider`, `auto_open`, `exclude_tools`, `tool_prefix`.
- ~~`ToolkitConfigService`~~, ~~`user_toolkit_configs` collection~~ — greenfield; only `MCPPersistenceService`/`user_mcp_configs` exist.
- ~~Any `/astudio` consumer in the Admin UI~~ — `grep astudio ui/src` returns nothing; no `lib/api/studio.ts`.
- ~~`/admin/studio` route~~, ~~`TabsTools.svelte`~~, ~~`SchemaForm.svelte`~~ — do not exist.
- ~~`GET /api/v1/astudio/agents/{name}/toolkits`~~ (read effective config), ~~`PUT …/toolkits/{slug}`~~, ~~`…/options/{param}`~~, ~~`…/mcp-servers`~~, ~~`…/datasets`~~ — only `GET /toolkits/{slug}/schema` and `POST /agents/{name}/toolkits` exist.
- ~~`persisted: true` from `POST /agents/{name}/toolkits`~~ — always `False` (toolkits.py:346).
- ~~`ToolkitRegistry.get("dataset_manager")`~~ — returns `None` (name filter); ~~`ToolkitRegistry.get("infographic")`~~ / ~~`("wiki")`~~ — not in `TOOL_REGISTRY` (per TASK-2518).
- ~~`MCPParamType` used by toolkit schemas~~ — it is MCP-registry specific; the toolkit schema has no `secret` flag today.
- ~~`parrot.handlers.vault_utils` as the implementation~~ — the implementation is `parrot.security.vault_utils`; the `handlers` module is a thin re-export (803 bytes).
- ~~Fernet~~ — the vault is AES-GCM via `navigator_session.vault.KeyRing` (byok.py header comment).
- ~~Agent-level dataset persistence~~ — `DatasetManagerHandler` operates on a per-user, session-scoped clone (`_clone_agent_dm`); nothing writes datasets back to the agent definition.

---

## Parallelism Assessment

- **Internal parallelism**: high once the core `ToolkitSpec` model and the
  schema enrichment land. Independent lanes afterwards: (1) `BotModel` +
  `to_bot_config` + `BotWritePayload` + codegen; (2) `BotConfig` widening +
  `create_agent_definition` + dead-loop removal; (3) `_initialize_tools`
  hydration; (4) Studio persist/options endpoints; (5) `ToolkitConfigService`
  + `AgentTalk` override application; (6) `config_options` implementations in
  `parrot_tools` (Jira, Querysource); (7) Admin UI Tools tab; (8) Datasets/MCP
  sub-panels + chat "My settings". Lanes 7–8 depend on 4's response shapes
  and on `pnpm generate` output from lane 1.
- **Cross-feature independence**: **FEAT-540 (graphindex-core-seams)**
  TASK-3263 relocates `LLMWikiToolkit` to `parrot_tools.wiki` and explicitly
  notes `handlers/studio/toolkits.py:27` needs no edit — but both features
  touch that file; merge order matters (rebase our toolkits.py changes on
  whichever lands first). TASK-3268 references `AbstractToolkit.get_tools`
  read-only. **FEAT-590 (tool-call-delegate)** works in `parrot/tools/` —
  verify it does not touch `toolkit.py`'s class attributes before adding
  `config_options`. No in-flight spec touches the Admin UI, `BotModel`,
  `handlers/agent.py` or `handlers/datasets.py`.
- **Recommended isolation**: `per-spec` (one worktree), with lanes 6 and 7
  as candidates for individual worktrees if the team wants parallel coders.
- **Rationale**: the backend lanes share `toolkits.py`, `bots.py` and
  `registry.py` and the UI lanes share `AgentForm.svelte`/`fields.ts`;
  sequential commits in one worktree avoid three-way merges on those hubs,
  while the `parrot_tools` hook implementations and the UI tab are file-
  disjoint enough to split off.

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus*: `type: feature`, `base_branch: dev`.
- [x] Where does per-toolkit config persist — *Owner: Jesus*: both layers — agent-level defaults on the agent definition (DB JSONB + YAML `toolkits:` entries) plus per-user overrides.
- [x] Secrets handling — *Owner: Jesus*: encrypted vault only (BYOK/MCP keyring), `secret_refs` in the config, masked on GET; never plaintext in JSON/YAML.
- [x] UI target and fate of chat-side dataset/MCP config — *Owner: Jesus*: extend `/admin/agents/:name` with a Tools tab (replacing the checkbox list) plus Datasets and MCP sub-panels; the chat keeps a lighter per-user "My settings" surface.
- [x] Who decides which params are user-overridable — *Owner: Jesus*: the operator, per param, via a toggle in Studio; overrides build a session-scoped toolkit instance, the shared bot is never mutated.
- [x] Registry (YAML/code) agents — *Owner: Jesus*: editable when the YAML lives under `AGENTS_DIR` (rewrite `toolkits:` + reload); `.py` agents stay read-only.
- [x] Agent-level meaning of datasets/MCP and location of user overrides — *Owner: Jesus*: agent = persisted defaults (`mcp_servers`, pre-registered datasources); user = chat, on the existing per-user endpoints.
- [x] Dynamic options for Querysource programs / Jira projects — *Owner: Jesus*: yes, via an optional `config_options(param, current_params)` toolkit hook advertised as `options_endpoint` in the schema; Jira and Querysource implement it.
- [x] Vault ownership for agent-level secrets — *Owner: Jesus*: the vault is **per-user** and it is the navigator-session vault (the `KeyRing` living in the user session, reached via `parrot.security.vault_utils`); agent-level secrets are stored under the agent owner's user id. No synthetic service principal.
- [ ] Secret classification for generic toolkits: name heuristics (`token`, `password`, `api_key`, `secret`, `dsn`) plus curated overlays — acceptable, or should every toolkit declare `secret_params` explicitly before it is configurable? — *Owner: Jesus*
- [x] Storage for agent-level datasets — *Owner: Jesus*: **in memory**. `dataset_manager` is configured like any other toolkit (its `DatasourceSpec` list is the toolkit's params, described by its JSON Schema); the datasets themselves live only in the agent's in-memory `DatasetManager`, replayed on build/reload. No `datasets` JSONB column.
- [x] Schema source for complex toolkits — *Owner: Jesus*: declarative JSON Schema (Pydantic model → `model_json_schema()`, `oneOf` for choice-shaped config) published per toolkit so the UI builds the form from it; introspection only as fallback.
- [ ] Should saving agent-level defaults auto-invalidate per-user overrides whose params are no longer `user_overridable` (drop silently, keep but ignore, or 409 on the operator's save)? — *Owner: Jesus*
- [ ] `enable_mcp_restore` is opt-in per agent today; should toolkit-override restore be always-on, or reuse the same flag? — *Owner: Jesus*
- [ ] Coordination with FEAT-540 (`graphindex-core-seams`, approved 2026-09-09, TASK-3256..3268 all **pending**, no worktree): TASK-3263 relocates `LLMWikiToolkit`/`CodeStructuralToolkit` to `parrot_tools.wiki` and repoints the import at `handlers/studio/toolkits.py:27`; this feature rewrites the same handler. Proposed: this feature imports `WikiConfig`/`LLMWikiToolkit` via `parrot_tools.wiki` if 3263 has landed, else keeps the current import and 3263 repoints one line — either order is a one-line conflict, but decide before `/sdd-task`. — *Owner: Jesus*
