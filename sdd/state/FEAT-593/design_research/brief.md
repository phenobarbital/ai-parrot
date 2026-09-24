<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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

### Recommended option / probable scope
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

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot-server/src/parrot/handlers/agent.py
packages/ai-parrot-server/src/parrot/handlers/bots.py
packages/ai-parrot-server/src/parrot/handlers/datasets.py
packages/ai-parrot-server/src/parrot/handlers/mcp_persistence.py
packages/ai-parrot-server/src/parrot/handlers/models/bots.py
packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py
packages/ai-parrot-server/src/parrot/handlers/studio/_base.py
packages/ai-parrot-server/src/parrot/handlers/studio/agents.py
packages/ai-parrot-server/src/parrot/handlers/studio/byok.py
packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py
packages/ai-parrot-server/src/parrot/handlers/tools_catalog.py
packages/ai-parrot-server/src/parrot/manager/manager.py
packages/ai-parrot-server/src/parrot/server/ui/models.py
packages/ai-parrot-server/ui/src/App.svelte
packages/ai-parrot-server/ui/src/lib/agents/fields.ts
packages/ai-parrot-server/ui/src/lib/api/agent.ts
packages/ai-parrot-server/ui/src/lib/api/agents.ts
packages/ai-parrot-server/ui/src/lib/stores/agent-form.svelte.ts
packages/ai-parrot-server/ui/src/lib/types/dataset.ts
packages/ai-parrot-server/ui/src/pages/agents/AgentForm.svelte
packages/ai-parrot-server/ui/src/pages/agents/form/TabsCapabilities.svelte
packages/ai-parrot-tools/src/parrot_tools/__init__.py
packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py
packages/ai-parrot/src/parrot/bots/abstract.py
packages/ai-parrot/src/parrot/handlers/vault_utils.py
packages/ai-parrot/src/parrot/interfaces/tools.py
packages/ai-parrot/src/parrot/knowledge/wiki/models.py
packages/ai-parrot/src/parrot/mcp/registry.py
packages/ai-parrot/src/parrot/models/basic.py
packages/ai-parrot/src/parrot/registry/registry.py
packages/ai-parrot/src/parrot/security/credentials_utils.py
packages/ai-parrot/src/parrot/security/vault_utils.py
packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
packages/ai-parrot/src/parrot/tools/discovery.py
packages/ai-parrot/src/parrot/tools/manager.py
packages/ai-parrot/src/parrot/tools/mcp_mixin.py
packages/ai-parrot/src/parrot/tools/registry.py
packages/ai-parrot/src/parrot/tools/toolkit.py

### Questions still open in the exploration document
- [ ] Secret classification for generic toolkits: name heuristics (`token`, `password`, `api_key`, `secret`, `dsn`) plus curated overlays — acceptable, or should every toolkit declare `secret_params` explicitly before it is configurable? — *Owner: Jesus*
- [ ] Should saving agent-level defaults auto-invalidate per-user overrides whose params are no longer `user_overridable` (drop silently, keep but ignore, or 409 on the operator's save)? — *Owner: Jesus*
- [ ] `enable_mcp_restore` is opt-in per agent today; should toolkit-override restore be always-on, or reuse the same flag? — *Owner: Jesus*
- [ ] Coordination with FEAT-540 (`graphindex-core-seams`, approved 2026-09-09, TASK-3256..3268 all **pending**, no worktree): TASK-3263 relocates `LLMWikiToolkit`/`CodeStructuralToolkit` to `parrot_tools.wiki` and repoints the import at `handlers/studio/toolkits.py:27`; this feature rewrites the same handler. Proposed: this feature imports `WikiConfig`/`LLMWikiToolkit` via `parrot_tools.wiki` if 3263 has landed, else keeps the current import and 3263 repoints one line — either order is a one-line conflict, but decide before `/sdd-task`. — *Owner: Jesus*

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
