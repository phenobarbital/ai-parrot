# Agent Studio — API Reference

REST API for building, configuring, testing, and scheduling agents through
a unified `/api/v1/astudio/*` surface (FEAT-467). Covers agent lifecycle,
the code-generation draft→activate pipeline, per-agent asset files
(identity/kb/skills), a shared org-wide skills catalog, BYOK per-user LLM
API keys, a deterministic + conversational testing surface, toolkit
configuration, reference catalogs, and the AgentStudio meta-agent. Also
documents the related scheduler run-now action, which lives under the
existing `/api/v1/parrot/scheduler/` prefix.

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
`not_owner`, `unavailable` (503, dependency not configured),
`server_managed` (422, missing app-context dependency),
`invalid_params`, `validation_failed`.

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
Refuses (`409 name_collision`) unless `replace: true` when a name is
already taken; refuses replacement of another user's agent unless
superuser (`409 not_owner`).

**Errors:** `409 missing_source`/`validation_failed`/`name_collision`/`not_owner`,
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
