# Agent Studio — API Reference

REST API for building, configuring, testing, and scheduling agents through
a unified `/api/v1/astudio/*` surface (FEAT-467). Covers agent lifecycle,
the code-generation draft→activate pipeline, per-agent asset files
(identity/kb/skills), a shared org-wide skills catalog, BYOK per-user LLM
API keys, a deterministic + conversational testing surface, toolkit
configuration, reference catalogs, and the AgentStudio meta-agent. Also
documents the related scheduler run-now action, which lives under the
existing `/api/v1/parrot/scheduler/` prefix.

**Feature**: FEAT-593 — Tool Configuration for Agent Studio

**Base URL:** `/api/v1/astudio`

**Authentication:** Every endpoint requires a valid session
(`@is_authenticated()` + `@user_session()`). Mutating endpoints
additionally enforce **ownership** (the resource's `created_by`/`owner`
must match the caller, unless the caller is a superuser) — see
[Ownership & PBAC](#ownership--pbac).

**Route prefix note:** `/api/v1/astudio/` (not `/api/v1/studio/`) —
another installed service on this deployment already occupies
`studio`-style routes. Internal code naming (`AgentStudio*` classes,
`handlers/studio/` package) is unaffected.

---

## Table of Contents

- [Endpoints Overview](#endpoints-overview)
- [Common Error Shape](#common-error-shape)
- [Ownership & PBAC](#ownership--pbac)
- [Agent Lifecycle](#agent-lifecycle)
- [Draft Pipeline (draft → activate)](#draft-pipeline-draft--activate)
- [Per-Agent Asset Files](#per-agent-asset-files)
- [Shared Skills Catalog](#shared-skills-catalog)
- [BYOK — Per-User LLM API Keys](#byok--per-user-llm-api-keys)
- [Testing Surface](#testing-surface)
- [Toolkit Configuration](#toolkit-configuration)
- [Reference Catalogs](#reference-catalogs)
- [AgentStudio Meta-Agent (Assistant)](#agentstudio-meta-agent-assistant)
- [Scheduler Run-Now (related surface)](#scheduler-run-now-related-surface)
- [`/api/v1/agents/factory` Alias Note](#apiv1agentsfactory-alias-note)
- [Reload Semantics & Working-Memory Contract](#reload-semantics--working-memory-contract)

---

## Endpoints Overview

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/agents` | List agents (registry + DB, merged) |
| `GET` | `/agents/{name}` | Get one agent |
| `POST` | `/agents` | Create a simple agent |
| `POST` | `/agents/{name}/reload` | Hot-reload an agent from its current definition |
| `DELETE` | `/agents/{name}` | Delete a factory-origin agent |
| `GET` | `/drafts` | List drafts |
| `GET` | `/drafts/{name}` | Get one draft (+ source + validation report) |
| `POST` | `/drafts` | Save + statically validate a draft |
| `POST` | `/drafts/{name}/activate` | Import + register a validated draft |
| `DELETE` | `/drafts/{name}` | Delete a draft |
| `GET` | `/agents/{name}/files/{kind}` | List asset files of a kind |
| `GET` | `/agents/{name}/files/{kind}/{filename}` | Read one asset file |
| `PUT` | `/agents/{name}/files/{kind}/{filename}` | Write an asset file |
| `DELETE` | `/agents/{name}/files/{kind}/{filename}` | Delete an asset file |
| `GET` | `/skills` | List shared catalog skills (grouped by category) |
| `GET` | `/skills/{id}` | Get one shared skill (+ registry versions) |
| `POST` | `/skills` | Publish a new shared skill |
| `PUT` | `/skills/{id}` | Update a shared skill (owner/admin) |
| `DELETE` | `/skills/{id}` | Delete a shared skill (owner/admin) |
| `POST` | `/agents/{name}/skills/import/{id}` | Import a shared skill onto an agent |
| `POST` | `/skills/resync` | Repair `search_index_stale` registry rows |
| `GET` | `/keys` | List the caller's stored provider keys (masked) |
| `POST` | `/keys` | Store a provider API key (encrypted) |
| `DELETE` | `/keys/{provider}` | Delete a stored provider key |
| `POST` | `/agents/{name}/test/ask` | Query a session-scoped test instance (BYOK-aware) |
| `DELETE` | `/agents/{name}/test` | End the test session |
| `POST` | `/tools/{slug}/execute` | Deterministically execute one tool |
| `POST` | `/agents/{name}/tools` | Assign tools/toolkits onto a live agent |
| `GET` | `/toolkits/{slug}/schema` | Get a toolkit's configuration schema |
| `POST` | `/agents/{name}/toolkits` | Assign a configured toolkit onto a live agent |
| `GET` | `/agents/{name}/toolkit-config` | List agent's toolkit configurations |
| `GET` | `/agents/{name}/toolkits/{slug}` | Get one toolkit configuration |
| `PUT` | `/agents/{name}/toolkits/{slug}` | Persist toolkit configuration for an agent |
| `DELETE` | `/agents/{name}/toolkits/{slug}` | Remove toolkit configuration from an agent |
| `GET` | `/agents/{name}/toolkits/{slug}/options/{param}` | Get dynamic options for a toolkit parameter |
| `GET` | `/agents/{name}/mcp-servers` | List agent's MCP server configurations |
| `PUT` | `/agents/{name}/mcp-servers` | Persist MCP server configurations for an agent |
| `GET` | `/agents/{name}/toolkits/{slug}/me` | Get user's override for a toolkit |
| `PUT` | `/agents/{name}/toolkits/{slug}/me` | Persist user's override for a toolkit |
| `DELETE` | `/agents/{name}/toolkits/{slug}/me` | Remove user's override for a toolkit |
| `GET` | `/catalog/{kind}` | Reference catalog (`base-classes`\|`llm-clients`\|`tools`\|`vector-stores`) |
| `POST` | `/assistant` | Converse with the AgentStudio meta-agent |
| `DELETE` | `/assistant` | End the assistant's session instance |

Related, outside `/api/v1/astudio`:

| Method | Route | Purpose |
|---|---|---|
| `PATCH` | `/api/v1/parrot/scheduler/schedules/{schedule_id}` (`action="run_now"`) | Trigger one immediate execution |
| `GET` | `/api/v1/parrot/scheduler/schedules/{schedule_id}/last-result` | Last execution's result/error metadata |
| `POST` | `/api/v1/agents/factory` | Code-generation agent factory (unchanged; see alias note) |

---

## Common Error Shape

Every non-2xx Studio response is a `StudioError`:

```json
{
  "message": "Human-readable description.",
  "code": "machine_readable_code",
  "details": { "...": "optional structured detail (e.g. {\"missing\": [\"artifact_store\"]})" }
}
```

Common `code` values across endpoints: `invalid_json`, `invalid_request`,
`missing_name`/`missing_id`, `invalid_name`, `not_found`, `duplicate`,
`not_owner`, `name_taken` (409; drafts save/activate today, see the FEAT-605
section), `unavailable` (503, dependency not configured),
`server_managed` (422, missing app-context dependency),
`invalid_params`, `validation_failed`, `read_only_definition`,
`not_overridable`, `not_configured`, `options_failed`, `vault_unavailable`,
`use_studio_endpoint`.

---

## Ownership & PBAC

- **Ownership**: every mutable resource stamps `created_by`/`owner_user_id`/
  `owner` at creation time (server-set from the session — never
  client-supplied). Mutating it later requires the caller to match that
  value, or be a superuser. Violations raise `403 Forbidden`
  (`StudioBaseView._require_owner`).
- **PBAC** (optional): when a Policy Decision Point is configured
  (`app['abac']`), Studio checks resource ids namespaced
  `astudio:<area>` (e.g. `astudio:agents`, `astudio:skills`,
  `astudio:keys`). **Fail-open** — when no PDP is configured, or on any
  evaluator error, access is allowed (matches `handlers/bots.py`'s
  `_PBACHandlerMixin` convention).
  Mutating agent verbs use `astudio:agents:<verb>`: `create`, `update` (`PATCH /agents/{name}`),
  `delete`, `reload`, `assign_tools`. Neither FEAT-605 nor the storage spec names a PATCH id; `update` follows the
  `astudio:<area>:update` verb already used by `PUT /skills/{id}` (`astudio:skills:update`).
- **Superuser bypass**: a caller whose session marks
  `superuser`/`is_superuser`, or who belongs to the `superuser` group,
  bypasses ownership checks everywhere.

---

## Agent Lifecycle

### `GET /agents`

Lists every agent (registry-origin YAML/Python + database-origin,
merged, DB-origin taking precedence on name collision).

**Response `200`:**
```json
{ "agents": [ { "name": "...", "source": "registry|database", "origin": "repo|factory|database", "owner": "1", "enabled": true, "...": "..." } ], "count": 1 }
```

### `GET /agents/{name}`

Single-agent form of the above. `404 not_found` if absent.

### `POST /agents`

Create a simple, non-code-generated agent (`CreateAgentRequest`):

```json
{
  "name": "my-agent",
  "bot_class": "BasicBot",
  "llm": "anthropic:claude-sonnet-4-5",
  "description": "...",
  "persist": true,
  "category": "general",
  "config": {}
}
```

- `persist: true` additionally writes a lossless `agent:`-keyed YAML
  definition under `AGENTS_DIR/agents/<category>/` and re-registers from
  it (so `file_path` reflects the on-disk definition of record).
- Ownership is stamped from the session (`config['created_by']`) —
  never client-supplied.

**Response `201`:** `{ "name": "...", "persisted": true, "source": "registry", "file_path": "..." }`

**Errors:** `400 invalid_name`/`invalid_bot_class`, `409 duplicate`.

### `POST /agents/{name}/reload`

Hot-swaps a registered agent from its CURRENT on-disk/registry
definition (YAML or `.py` origin) — delegates to
`BotManager.reload_agent` (`ReloadResult`:
`name`, `reloaded`, `previous_instance_closed`, `warnings`). See
[Reload Semantics](#reload-semantics--working-memory-contract).

**Errors:** `404 not_found`, `422 reload_failed`.

### `DELETE /agents/{name}`

Deletes a **factory-origin** agent whose on-disk YAML lives under
`AGENTS_DIR` (safety check — refuses to unlink anything else, e.g. a
bot class's own framework source file). DB-origin agents are delegated
(`409 delegated` — use `/api/v1/bots` instead). Requires ownership.

**Errors:** `403` (not owner), `409 delegated`/`no_definition`/`delete_refused`.

---

## Draft Pipeline (draft → activate)

The ONLY path from generated Python source to a live, registered agent.
A draft is saved + statically validated (AST allowlist — **never**
imported/executed) under `AGENTS_DIR/_drafts/`; it becomes live code
only via an explicit, separate `activate` call.

### `POST /drafts`

```json
{ "name": "my-generated-agent", "source": "<full python source>" }
```

Saved regardless of validation outcome; the response and stored row
always carry the `validation_report`.

**Response `201`:**
```json
{ "name": "...", "status": "validated|failed", "file_path": "...", "validation_report": { "passed": true, "errors": [] } }
```

### `GET /drafts` / `GET /drafts/{name}`

List/read drafts, including current source and validation report.

### `POST /drafts/{name}/activate`

```json
{ "replace": false }
```

Re-validates the **current on-disk** content (it may have been edited
since save) before importing — a stale validation report is never
trusted. Moves the file into `AGENTS_DIR/<name>.py` (so the startup
loader also finds it on next boot), imports it, and registers ownership.
Refuses (`409 name_taken`) unless `replace: true` when a name is
already taken; refuses replacement of an ownerless or another user's agent
unless superuser (`409 name_taken`, no owner disclosed).

**Errors:** `409 missing_source`/`validation_failed`/`name_taken`,
`422 import_failed`/`not_registered`, `503 unavailable`.

### `DELETE /drafts/{name}`

Owner-enforced; removes both the row and the on-disk file.

---

## Per-Agent Asset Files

Sandboxed CRUD for `AGENTS_DIR/<agent>/{identity,kb,skills}/`. Mutating
responses always flag `reload_required: true` — this endpoint **never**
triggers a reload itself.

### `GET /agents/{name}/files/{kind}`

Lists files under that kind's directory (`{"kind": "...", "files": [...]}`).
`kind` ∈ `identity`, `kb`, `skills`.

### `GET /agents/{name}/files/{kind}/{filename}`

Reads one file: `{"path": "...", "kind": "...", "size": N, "content": "..."}`.

### `PUT /agents/{name}/files/{kind}/{filename}`

```json
{ "content": "..." }
```

Per-kind filename rules:
- `identity`: must be one of the five canonical identity filenames.
- `kb`: flat `.md`/`.txt` file (no subdirectories).
- `skills`: single-file `<name>.md`, or composite `<name>/SKILL.md` +
  `<name>/<asset>`. Definition files (`<name>.md` or `<name>/SKILL.md`)
  are validated against the skill frontmatter contract (via a
  scratch-tmp-file parse) BEFORE the real file is written — `422
  invalid_frontmatter` on failure, real file untouched.

**Response `200`:** `{ "path": "...", "kind": "...", "size": N, "reload_required": true }`

### `DELETE /agents/{name}/files/{kind}/{filename}`

Always allowed, even for a file the live agent currently uses
(resolved decision — deleting an in-use file is not blocked).

---

## Shared Skills Catalog

Org-wide, Postgres-first skill sharing with a best-effort dual-write
into the existing `SkillRegistry` (Redis+file, embedding search). A
registry-write failure NEVER fails the publish — the row is flagged
`search_index_stale: true` instead (repaired later by resync).

### `GET /skills`

Optional query params `?category=<SkillCategory>` / `?owner=<user_id>`.

**Response `200`:** `{ "skills": { "<category>": [ {...} ] }, "count": N }`

### `GET /skills/{id}`

Single entry + `versions` (fetched live from the shared `SkillRegistry`,
`[]` on any registry error).

### `POST /skills`

```json
{
  "name": "resumen",
  "description": "Resume long texts into bullet points",
  "category": "general",
  "triggers": ["/resumen"],
  "body": "---\nname: resumen\n...\n---\n\n<body>"
}
```

**Response `201`:** the created entry. **Errors:** `409 duplicate`, `503 unavailable`.

### `PUT /skills/{id}` / `DELETE /skills/{id}`

Owner-or-admin enforced updates/deletes; `PUT` accepts the same shape
as the publish payload.

### `POST /agents/{name}/skills/import/{id}`

Imports a shared skill onto a specific agent's own `skills/` directory
(composes the entry's stored `body` into a valid skill markdown file —
`source: authored` in frontmatter, never an invalid `shared_catalog`
value).

### `POST /skills/resync`

Startup-equivalent reconciliation pass, callable on demand: re-attempts
the registry dual-write for every `search_index_stale: true` row.

---

## BYOK — Per-User LLM API Keys

Per-user LLM API keys, AES-GCM encrypted (navigator-session vault — NOT
Fernet), stored as a session-vault hot copy + a DocumentDB durable copy.
**Plaintext is never returned** — `GET` only ever shows a masked preview
(`sk-…1234`, first 3 + last 4 chars).

### `GET /keys`

**Response `200`:** `{ "keys": [ { "provider": "anthropic", "masked": "sk-…1234", "created_at": "..." } ], "count": 1 }`

### `POST /keys`

```json
{ "provider": "anthropic", "api_key": "sk-ant-..." }
```

`provider` validated against `parrot.clients.factory.SUPPORTED_CLIENTS`;
normalized lowercase. **Response `201`:** `{ "provider": "anthropic", "masked": "sk-…1234" }`.

**Errors:** `400 invalid_provider`, `503 vault_unavailable`.

### `DELETE /keys/{provider}`

Removes both the session-vault and DocumentDB copies.

**Consumers**: the [Testing Surface](#testing-surface)'s `test/ask` and
the [Meta-Agent](#agentstudio-meta-agent-assistant)'s `/assistant`
both resolve a stored key via the same helper
(`parrot.handlers.studio.byok.resolve_user_api_key`) and pass it as
`api_key=` when building the LLM client — **never** silently falling
back to the server's default key when a genuinely stored key fails
auth (the provider error surfaces as-is).

---

## Testing Surface

### `POST /agents/{name}/test/ask`

```json
{ "query": "...", "use_byok": true }
```

Session-scoped test instance — created once per (session, agent) via
`manager.get_bot(name, new=True, session_id=...)`, reused across calls.
When `use_byok` and a stored key exists for the agent's LLM provider
(derived from its `"provider:model"` configuration string), the test
client is rebuilt with that key for this call.

**Response `200`:** `{ "agent_name": "...", "query": "...", "response": "...", "metadata": {} }`

**Errors:** `404 not_found`, `502 query_failed`, `503 unavailable`.

### `DELETE /agents/{name}/test`

Ends the session instance (no-op, `200`, if none was active).

### `POST /tools/{slug}/execute`

```json
{ "args": { "...": "..." } }
```

Resolves `slug` via the tool registry (`discover_all()` +
`resolve_class()`), instantiates it (zero-arg, or wired from a small
known app-context-dependency map — e.g. `artifact_store`), validates
`args` against the tool's own schema BEFORE executing, then calls
`await tool.execute(**args)`.

**Response `200`:** the tool's `ToolResult`, serialized (`.model_dump()`).

**Errors:** `404 not_found` (unknown slug), `422 invalid_args`/`server_managed`
(with `details.missing` listing the unresolvable constructor params).

### `POST /agents/{name}/tools`

```json
{ "tools": ["weather", "arxiv"], "toolkits": [ { "slug": "jira", "params": {} } ] }
```

Assigns onto the LIVE agent instance's `tool_manager` — mutates shared
state, does not persist to YAML (`persisted: false` in the response;
toolkit config persistence is the
[Toolkit Configuration](#toolkit-configuration) surface's job).
Ownership enforced.

**Response `200`:** `{ "agent": "...", "registered_tools": ["..."], "persisted": false }`
(+ `"errors": [...]` per-toolkit if any slug failed to resolve/register).

---

## Toolkit Configuration

### `GET /toolkits/{slug}/schema`

Configuration schema for a toolkit's constructor. Three toolkits get
first-class, hand-curated treatment (non-client-suppliable params
marked `server_managed: true`):

- `wiki` (`LLMWikiToolkit`) — `pageindex_toolkit`/`graphindex_toolkit`/
  `okf_toolkit` are `server_managed`; `config` embeds the full
  `WikiConfig.model_json_schema()`.
- `dataset_manager` (`DatasetManager`) — all params optional, none
  `server_managed`.
- `infographic` (`InfographicToolkit`) — `artifact_store` is required
  AND `server_managed`.

Any other slug resolves generically via `TOOL_REGISTRY` +
constructor-signature introspection.

**Response `200`:** `{ "slug": "...", "class_name": "...", "params": { "<name>": { "required": true, "server_managed": false, "type": "str", "default": "..." } } }`

**Errors:** `404 not_found` (unknown generic slug).

### `POST /agents/{name}/toolkits`

```json
{ "slug": "wiki", "params": { "wiki_name": "docs", "storage_dir": "..." } }
```

- **`wiki`** — **reuse-else-build**: checks
  `bot._pageindex_toolkit`/`bot._graphindex_toolkit` first; builds fresh
  from `WikiConfig` only when absent (`pageindex_source`/
  `graphindex_source`: `"reused"`/`"built"` in the response).
  `storage_dir` must be absolute (system-path denylist applies) or
  relative (sandboxed under a server-configured root).
- **`infographic`** — wires `app['artifact_store']`; `422
  server_managed` (`details.missing: ["artifact_store"]`) when absent.
- **`dataset_manager`** / generic — instantiated with `params` directly;
  missing required params are reported proactively as `422
  server_managed` before even attempting construction.

**Response `200`:** `{ "agent": "...", "slug": "...", "registered_tools": ["..."], "reload_required": false, "persisted": false }`
(+ toolkit-specific extras like `pageindex_source` for `wiki`).

---

## Agent-Level Toolkit Persistence (FEAT-593)

Agent-level toolkit configurations and MCP server configurations can be
persisted to the agent definition (DB JSONB column or YAML `toolkits:`
entries) through dedicated endpoints.

### `GET /agents/{name}/toolkit-config`

List all toolkit configurations persisted for an agent.

**Response `200`:**
```json
{
  "agent": "my-agent",
  "editable": true,
  "reason": null,
  "toolkits": [
    {
      "slug": "jira",
      "params": { "server_url": "https://example.atlassian.net" },
      "user_overridable": ["token"],
      "secret_refs": { "token": "toolkit_jira_my-agent" },
      "vault_owner": "42"
    }
  ],
  "unavailable": []
}
```

- `editable: false` with `reason: "read_only_definition"` for registry
  (YAML/code) agents outside `AGENTS_DIR`.
- `unavailable` lists toolkit slugs that were configured but cannot be
  resolved (unknown slug, missing package, etc.).

**Errors:** `404 not_found`.

### `GET /agents/{name}/toolkits/{slug}`

Get one toolkit configuration for an agent.

**Response `200`:** Same shape as one entry in the list response above.

**Errors:** `404 not_found` (agent or toolkit).

### `PUT /agents/{name}/toolkits/{slug}`

```json
{
  "params": { "server_url": "https://example.atlassian.net", "default_project": "TROC" },
  "user_overridable": ["token", "default_project"]
}
```

Persists toolkit configuration to the agent definition. Secrets in
`params` are extracted and stored in the vault under the agent owner's
user id; the response and all future GETs show only `secret_refs`.

**Response `200`:**
```json
{
  "agent": "my-agent",
  "slug": "jira",
  "reload_required": true,
  "persisted": true
}
```

- `reload_required: true` indicates the agent must be reloaded for the
  changes to take effect.
- `persisted: true` confirms the configuration was stored.

**Errors:** `403 read_only_definition` (registry agent outside
`AGENTS_DIR`), `400 invalid_params` (malformed request), `422
validation_failed` (params fail schema validation), `503
vault_unavailable` (vault service error).

### `DELETE /agents/{name}/toolkits/{slug}`

Remove a toolkit configuration from an agent.

**Response `200`:** `{ "agent": "...", "slug": "...", "reload_required": true, "persisted": true }`

**Errors:** `403 read_only_definition`, `404 not_found`.

### `GET /agents/{name}/toolkits/{slug}/options/{param}`

Get dynamic options for a toolkit parameter (e.g. Jira projects,
Querysource programs). Uses only the persisted toolkit configuration —
request-supplied parameters are ignored to prevent SSRF.

**Response `200`:**
```json
{
  "options": [
    { "value": "TROC", "label": "TROC - Troc Platform" },
    { "value": "OPS", "label": "OPS - Operations" }
  ]
}
```

**Errors:** `404 not_configured` (toolkit not configured for this agent),
`403 not_owner` (not the agent owner), `502 options_failed` (lookup
failed).

### `GET /agents/{name}/mcp-servers`

List all MCP server configurations persisted for an agent.

**Response `200`:**
```json
[
  {
    "name": "filesystem",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/allowed_dir"],
    "secret_refs": { "headers": "mcp_agent_filesystem_my-agent" },
    "vault_owner": "42"
  }
]
```

### `PUT /agents/{name}/mcp-servers`

```json
[
  {
    "name": "filesystem",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/allowed_dir"],
    "allowed_tools": null,
    "blocked_tools": null,
    "description": "Filesystem access",
    "auth_type": null,
    "params": {},
    "secret_refs": {},
    "vault_owner": null
  }
]
```

Persists MCP server configurations to the agent definition. Secrets in
`headers` or `auth_config` are extracted and stored in the vault.

**Response `200`:** `{ "agent": "...", "reload_required": true, "persisted": true }`

**Errors:** `403 read_only_definition`, `400 invalid_json`.

### Per-User Toolkit Overrides

Users can override toolkit parameters marked as `user_overridable` by
the agent operator.

### `GET /agents/{name}/toolkits/{slug}/me`

Get the current user's override for a toolkit.

**Response `200`:** `{ "server_url": "https://example.atlassian.net", "token": "********" }`

Masked secrets are returned as `"********"`; non-secrets are returned as-is.

### `PUT /agents/{name}/toolkits/{slug}/me`

```json
{ "token": "my-personal-token", "default_project": "PERSONAL" }
```

Persist the current user's override for a toolkit. Only parameters
marked `user_overridable` in the agent's toolkit configuration are
accepted.

**Response `200`:** `{}`

**Errors:** `422 not_overridable` (attempting to override a non-overridable parameter).

### `DELETE /agents/{name}/toolkits/{slug}/me`

Remove the current user's override for a toolkit.

**Response `200`:** `{}`

---

## Reference Catalogs

### `GET /catalog/{kind}`

`kind` ∈ `base-classes`, `llm-clients`, `tools`, `vector-stores`. All
four reuse existing sources of truth — no new registries.

- **`base-classes`** — introspects `parrot.bots.__all__`; lazy exports
  (`VoiceBot`/`InfoAgent`) that fail to import (missing optional deps)
  degrade to `{"available": false, "lazy": true, "error": "..."}`
  instead of raising. Configurable params kept only when they carry a
  default or a type annotation.
- **`llm-clients`** — resolves `SUPPORTED_CLIENTS`; lazy-loader entries
  (Bedrock/Nova/Mantle) are called to resolve the real class, with the
  same graceful `available: false` degradation on a missing extra.
  `default_model` read from `_default_model` when present.
- **`tools`** — delegates to (and shares the SAME process-wide cache
  as) the existing `GET /api/v1/tools/catalog` endpoint — identical
  shape, never built twice.
- **`vector-stores`** — wraps `parrot.stores.supported_stores`
  (`{slug, class_name}` rows).

**Errors:** `404 not_found` (unknown `kind`).

---

## AgentStudio Meta-Agent (Assistant)

A conversational agent (`AgentStudioAgent`, `AnthropicClient` +
`STUDIO_AGENT_MODEL`, default `claude-opus-5`) that builds agents,
skills, and KB files through natural language — internally, its tools
call the SAME underlying service functions the endpoints above use (no
duplicated logic), and every mutating tool requires HITL confirmation.

### `POST /assistant`

```json
{ "query": "Build me a weather-reporting agent", "use_byok": true }
```

Session-scoped instance (created once per session, reused — the same
discipline as `test/ask`, but keyed in a small per-app cache since this
agent is never registered with `BotManager`). `use_byok` resolves the
caller's stored Anthropic key and passes it as `api_key=` at instance
build time.

**Response `200`:** `{ "response": "...", "metadata": {} }`

**Errors:** `500 build_failed`, `502 query_failed`.

### `DELETE /assistant`

Ends the session's assistant instance.

**Absorbed AgentFactory flow**: the assistant's `create_yaml_agent` tool
calls `parrot.bots.factory.tools.finalize.finalize_agent_registration`
directly — the identical function `POST /api/v1/agents/factory`'s
orchestrator calls at its own finalize step. See the
[alias note](#apiv1agentsfactory-alias-note) below.

---

## Scheduler Run-Now (related surface)

Lives under the existing `/api/v1/parrot/scheduler/` prefix (not
`/astudio`) — extends the pre-existing scheduler CRUD rather than
adding a parallel surface.

### `PATCH /api/v1/parrot/scheduler/schedules/{schedule_id}`

```json
{ "action": "run_now" }
```

Triggers exactly one immediate, out-of-band execution via the SAME
`_execute_agent_job` coroutine — and therefore the same
`job_success`/`job_status` event handling, callbacks, `send_result`
emails, and `last_run`/`run_count`/`last_result` stamping — as a
normally scheduled run. Does **not** touch `enabled`/`schedule_config`/
the stored trigger; a paused/disabled schedule still runs once and
stays paused. An in-memory guard refuses a second concurrent run-now
for the same schedule.

**Response `200`:** the (unmodified) schedule, serialized (`_serialize_job`).

**Errors:** `409` (a run-now is already active for this schedule).

### `GET /api/v1/parrot/scheduler/schedules/{schedule_id}/last-result`

**Response `200`:**
```json
{
  "status": "success",
  "schedule_id": "...",
  "last_run": "2026-01-01T00:00:00",
  "next_run": "2026-01-02T00:00:00",
  "run_count": 5,
  "last_status": "success",
  "last_result": "<formatted result, capped at 10k chars>",
  "last_result_time": "...",
  "last_error": null,
  "last_error_time": null
}
```

Populated after either a normally scheduled run OR a run-now — both go
through the identical completion path.

---

## `/api/v1/agents/factory` Alias Note

`POST /api/v1/agents/factory`'s request/response contract is preserved
**byte-for-byte** — it remains the code-generation entry point via
`AgentFactoryOrchestrator` (HITL-gated router → specialist → finalize
pipeline). The AgentStudio meta-agent's `create_yaml_agent` tool
absorbs the SAME underlying YAML-agent write path by calling
`finalize_agent_registration` directly (the identical function the
orchestrator's own finalize step calls), so both surfaces write agents
through one code path. `/api/v1/agents/factory` itself is otherwise
untouched by FEAT-467.

---

## Reload Semantics & Working-Memory Contract

`POST /agents/{name}/reload` (agent lifecycle) hot-swaps a registered
agent's instance from its current on-disk/registry definition:

- **YAML-origin** agents: re-read from the `.yaml` file and
  re-registered.
- **`.py`-origin** agents: the module is re-imported and re-registered.
- The **previous instance's `cleanup()`** is awaited best-effort — a
  raising `cleanup()` is swallowed and surfaced as a `warnings` entry
  in the `ReloadResult`, never as a failure of the reload itself.
- **Working memory is NOT migrated** across the swap — the new instance
  starts with a fresh `AnswerMemory`/conversation state. Any in-flight
  session referencing the OLD instance continues against that instance
  until its own session ends; only NEW `get_bot()` lookups see the
  reloaded instance. Per-agent asset file writes
  ([above](#per-agent-asset-files)) always report
  `reload_required: true` precisely because they take effect only
  through this explicit reload, never automatically.


---

## Tenant scope & visibility (FEAT-605)

> **Status of the early subset.** Only the scope-only parts (request-scope seam, mount hooks, the
> `/me` endpoint, scope-only gates and the draft-overwrite / ownerless-takeover fixes) are in place.
> This is **not tenant-ready**: a host that installs it keeps `studio_enabled=False` for its tenants
> until the release gate below is met.

An **opted-in host** is one where `app["scope_resolver"]` (or the legacy
`app["ui_surfaces_scope_resolver"]`) is installed. The **tenant path** is an opted-in host. Resolver
lookup precedence: `scope_resolver` → `ui_surfaces_scope_resolver` → the session default.

### Host modes

opted-in host; every Studio record it reads or writes is a row of the
storage spec's tables (assumption A1, §6).

| Host state | Reads | Create | PATCH visibility | New gates (reload, files GET, tool execute) |
|---|---|---|---|---|
| no resolver installed | FEAT-467 unchanged (list-all, read-any) on the storage spec's GLOBAL partition (`tenant IS NULL`, always `private` by CHECK) or its filesystem backend; visibility fields reported as `access: "global"` | FEAT-467 unchanged (+ D1/D3 fixes, `name_taken` code) | 422 `tenant_required` for non-private | **not applied** (G9) |
| resolver installed, `scope.tenant is None` (unprefixed mount, multi-programme user) | empty lists; addressed routes 404 | 422 `tenant_required` | 422 `tenant_required` | applied |
| resolver installed, prefixed mount, `match_info["tenant"] != scope.tenant` | 403 `tenant_mismatch` before any record access | same | same | same |

### Access rule

```
For a record `r` (agent, draft or skill row) and scope `s`:

```
in_tenant(r)   := s.tenant is not None and r.tenant is not None and r.tenant == s.tenant
owns(r)        := in_tenant(r) and r.owner == s.user_id
administers(r) := in_tenant(r) and (s.may_administer or s.is_superuser)
grants(r)      := in_tenant(r) and (r.visibility == "tenant"
                   or (r.visibility == "groups" and set(r.allowed_groups) & s.groups))
can_see(r)     := owns(r) or administers(r) or grants(r)
can_manage(r)  := owns(r) or administers(r)
access_tag(r)  := "owner" | "admin" | "tenant" | "groups"    ("global" with no resolver)
```

```

Handlers never re-implement this rule; they call the Studio access service. A tenant-NULL row is
invisible and unmanageable in every opted-in host. No branch crosses tenants, not even a superuser's.

### Route policy (relative to the mount prefix)

"404" = `can_see` false (identical body to absent). "403" = visible but not `can_manage`. All rows
also pass `tenant_mismatch` and `studio_disabled` first (except `/me`).

behaviour without a resolver.

| Route | Invisible | Visible, not manageable | Manageable | Notes |
|---|---|---|---|---|
| `GET /me` | — | — | — | scope only; exempt from `studio_disabled` |
| `GET /agents`, `/drafts`, `/skills` (list) | omitted | included, `access` tag | included | response items carry the visibility fields |
| `GET /agents/{name}`, `/drafts/{name}`, `/skills/{id}` | 404 | 200 | 200 | returns `tenant, owner, visibility, allowed_groups, access, can_manage` (C14) |
| `POST /agents`, `/drafts`, `/skills` | — | — | — | `may_author` else 403 `authoring_denied`; `name_taken` in tenant; reserved keys 400; Python `source` on `/drafts` ⇒ 422 `declarative_only` (tenant path); tenant path: any toolkit/MCP configuration in the body or bundle must pass `TenantToolingPolicy` (TOOLKITS) before anything is written (C35) |
| `PATCH /agents/{name}` (General fields; route and body owned by the storage spec §2.9a) | 404 | 403 | allowed | + `may_author` else 403 `authoring_denied`; reserved keys 400; `name` in body ⇒ 422 `name_immutable` (storage); tooling in the patch ⇒ `TenantToolingPolicy` (C35) |
| `POST /agents/{name}/test/ask`, `POST /agents/{name}/test`, `DELETE /agents/{name}/test` | 404 | allowed | allowed | binds `studio_scope` with `.agent` set (C16); re-checked on every ask; tenant path runs the request inside storage's `manager.studio.use(StudioAgentKey(scope.tenant, name), session_id=…, request=…)` (the `get_studio_bot(key, new=True, …)` lookup plus a lease), never `get_bot(name)`; host write tools run only after an approval from the TOOLKITS confirmation mechanism, zero writes when none is available (C36) |
| `POST /agents/{name}/skills/import/{id}` | 404 (agent or skill) | 403 on the agent | skill must be visible | copies into the agent's assets (storage spec) |
| `GET /agents/{name}/files/{kind}[/{filename}]` | 404 | **403, opted-in only** | allowed | FEAT-467 GET stays ungated without a resolver (`test_files.py:350`) |
| `PUT/DELETE /agents/{name}/files/...` | 404 | 403 | allowed | |
| `POST /agents/{name}/reload` | 404 | **403, opted-in only** | allowed | tenant path: `manager.studio.reload(StudioAgentKey(scope.tenant, name))`; legacy path unchanged |
| `DELETE /agents/{name}` | 404 | 403 | allowed | |
| `POST /agents/{name}/tools`, `/agents/{name}/toolkits`; `GET/PUT/DELETE /agents/{name}/toolkit-config`, `/agents/{name}/toolkits/{slug}`, `/agents/{name}/toolkits/{slug}/options/{param}`, `/agents/{name}/mcp-servers` | 404 | 403 | allowed | tooling rows in `ai_agent_tooling` (storage). Tenant path: every write (incl. `/mcp-servers` and bundle activation) accepts only configuration allowed by the host-owned `TenantToolingPolicy` (TOOLKITS), applied to the final normalised config (so `transport`/`command` inside `params` count); tenant-supplied local/stdio execution is denied by default; refused before persistence and before any process starts (C35). `options/{param}`: runs the TOOLKITS mandatory scope check before `config_options()` acquires any resource (C36) |
| `GET/PUT/DELETE /agents/{name}/toolkits/{slug}/me` | 404 | allowed (own override) | allowed | per-user secrets unchanged |
| `POST /drafts/{name}/activate` | 404 | 403 | allowed | + `may_author`; declarative (tenant path); `name_taken` rules above; the draft's tooling re-checked against `TenantToolingPolicy` at activation (C35) |
| `DELETE /drafts/{name}` | 404 | 403 | allowed | |
| `PUT /skills/{id}`, `DELETE /skills/{id}` | 404 | 403 | allowed | 404 check runs before today's `_require_owner` (`skills_catalog.py:411`, `:456`) |
| `PATCH /agents/{name}/visibility`, `/drafts/{name}/visibility`, `/skills/{id}/visibility` | 404 | 403 | allowed | 422 `tenant_required` / `groups_required` |
| `POST /skills/resync` | — | — | — | opted-in: global `is_superuser` from the scope only (not `may_administer`); rebuilds the storage spec's derived per-pod search index for the caller's partition from Postgres |
| `POST /tools/{slug}/execute` | — | — | — | opted-in: `may_author` else 403 `authoring_denied`, then existing PBAC (C13), then the TOOLKITS mandatory scope check for standalone tools (refusal before any side effect, `tool_scope_unavailable`) (C36). A host write tool is refused here with zero writes, because this endpoint has no confirmation channel (fail closed, C36) |
| `GET /toolkits/{slug}/schema` | — | — | — | no record; `studio_enabled` only |
| `GET /catalog/{kind}` | — | — | — | global catalogues unchanged; tenant-safe toolkit listing is `agentstudio-host-toolkits` |
| `GET/POST/DELETE /keys[/{provider}]` | — | — | — | per-user, unchanged; BYOK is out of scope (host may skip via `view_wrapper`) |
| `POST /assistant`, `DELETE /assistant` | — | — | — | not gated by `may_author` (questions allowed); its writing tools are (M10), and they pass `TenantToolingPolicy` when they write tooling. Session, instance and conversational identity partitioned by (tenant, user); DELETE resets only the current partition (C30) |

### Error codes

| Code | HTTP | Owner |
|---|---|---|
| `name_taken` | 409 | FEAT-605 (body `{"code": "name_taken", "message": "Name '<slug>' is not available."}`) |
| `declarative_only` | 422 | FEAT-605 (also the storage tenant-path Python-draft refusal) |
| `studio_disabled` | 404 | FEAT-605 |
| `tenant_mismatch` | 403 | FEAT-605 |
| `authoring_denied` | 403 | FEAT-605 |
| `reserved_config_key` | 400 | FEAT-605 (`owner`, `created_by`, `tenant`, `visibility`, `allowed_groups` in `config`/`definition`) |
| `tenant_required` | 422 | FEAT-605 |
| `groups_required` | 422 | FEAT-605 |
| `groups_not_allowed` | 422 | FEAT-605 (open question: `allowed_groups` outside the owner's groups) |
| `tooling_not_permitted` | 422 write / 403 execute | TOOLKITS (pass-through) |
| `confirmation_required` | 403 | TOOLKITS (pass-through) |
| `server_managed` | 422 | TOOLKITS (pass-through) |
| `tool_scope_unavailable` | 403 | TOOLKITS (pass-through) |

Storage codes (`version_conflict`, `name_immutable`, `studio_storage_unavailable`, …) pass through
unchanged; see the storage host guide (FEAT-621).

### `GET {prefix}/me`

Returns the resolved scope: `{"user_id", "tenant", "may_author", "may_administer", "enabled", "is_superuser"}`
(`enabled = scope.studio_enabled`). Exempt from `studio_disabled`, still subject to `tenant_mismatch`,
needs no record and no storage. Without a resolver it returns the default scope with `enabled: true` and
`may_administer: false`. The literal `/me` is registered before any dynamic top-level route.

### Visibility

`PATCH /agents/{name}/visibility`, `/drafts/{name}/visibility`, `/skills/{id}/visibility` take
`VisibilityUpdateRequest`:

```json
{"visibility": "private | tenant | groups", "allowed_groups": ["..."]}
```

`groups` with an empty `allowed_groups` ⇒ 422 `groups_required`; non-private without a tenant ⇒ 422
`tenant_required`. Single-record GETs return `tenant`, `owner`, `visibility`, `allowed_groups`, `access`
(`owner | admin | tenant | groups | global`) and `can_manage`.

### Mounting Studio in a host

```python
setup_studio_routes(app, *, prefix=None, view_wrapper=None)
BotManager.setup(app, ..., studio_routes=True)           # False skips the default /api/v1/astudio mount
BotManager.setup_registry_only(app, *, import_modules=False, load_definitions=False)
```

- `prefix` may contain `{tenant}`; the router value is compared with `scope.tenant` before any record
  access (403 `tenant_mismatch`).
- `view_wrapper` is called once per distinct view class; its result is registered for every route of that
  class; `None` skips them. `_scope()` is resolved lazily so the wrapper's prologue runs first.
- `setup_studio_routes` is idempotent per prefix; startup hooks are installed once per app.
- `setup_registry_only` is idempotent, registers no route and runs no startup agents.
  It installs the Studio runtime hooks (`add_studio_runtime_hooks`) once, so it is recommended for tenant
  hosts; the documented order and its reverse behave the same.
  With an installed resolver, `import_modules=True` / `load_definitions=True` raise `RuntimeError`.
- Documented mount order: install the resolver → `setup_registry_only` → `setup_studio_routes`.
- The host reserves `astudio` as a tenant segment itself.

### Request context for tools

`RequestContext.kwargs["studio_scope"]` is a `StudioToolScope`: `caller` (the caller's `RequestScope`) and
`agent` (`StudioAgentRef(agent_id, name, owner, tenant, visibility)` or `None` on agent-less calls),
built by `build_tool_scope(scope, agent=None)`. With no resolver installed nothing is bound.

### Behaviour on a plain host (no resolver)

FEAT-467 behaviour is unchanged (list-all, read-any), the new gates (reload, files GET, tool execute) are
not applied, visibility fields report `access: "global"`, non-private visibility is 422 `tenant_required`,
and duplicate-name responses on the draft routes (`POST /drafts`, `POST /drafts/{name}/activate`) already use
`name_taken` (409) instead of `name_collision` / `not_owner` (TASK-3962, TASK-3963). The agents and skills
create routes still answer `duplicate` until TASK-3966 (agents) and TASK-3968 (skills) switch them to `name_taken`.

### Release gate

No release is tenant-ready while only the early subset, toolkit discovery or route flags are done. A
tenant-ready release requires: every FEAT-605 task through the docs wave (including the registry-only
lifecycle and the assistant partition), the storage work (FEAT-621, W0–W4) and the toolkits work (FEAT-622,
Waves 1–4). Until then keep `studio_enabled=False` for tenants.
