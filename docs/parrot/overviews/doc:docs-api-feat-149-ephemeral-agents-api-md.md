---
type: Wiki Overview
title: Ephemeral User Agents — Frontend Integration Handoff
id: doc:docs-api-feat-149-ephemeral-agents-api-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: An *ephemeral user agent* is a personal AI assistant that lives entirely
  in
relates_to:
- concept: mod:parrot_tools
  rel: mentions
- concept: mod:parrot_tools.ddgo
  rel: mentions
- concept: mod:parrot_tools.zipcode
  rel: mentions
---

# Ephemeral User Agents — Frontend Integration Handoff

**Feature**: FEAT-149  
**Date**: 2026-05-07  
**Audience**: `navigator-frontend-next` team  
**Purpose**: Input document for `/sdd-proposal` — paste as the **Problem Statement** and **Constraints & Requirements** body.

---

## 1. Context

### What Is an Ephemeral Agent?

An *ephemeral user agent* is a personal AI assistant that lives entirely in
memory for the duration of a user session. Unlike the regular bot-creation
flow — which writes a database row before the bot is usable — an ephemeral
agent is created instantly in memory, warmed up in the background, and only
persisted to the database if the user explicitly decides to "save" it.

This means a user can try out a custom AI assistant with specific tools, MCP
servers, and uploaded documents without committing to a permanent bot. If
they like it, one click saves it. If not, it simply disappears (or expires
after 24 hours).

### The Memory-First Lifecycle

The lifecycle has four named phases:

| Phase | Meaning |
|---|---|
| `creating` | The server received the request and scheduled the warm-up. |
| `warming` | Background setup is running: tool sync, MCP handshake, RAG index build. |
| `ready` | The bot is fully operational and can receive chat messages. |
| `error` | Setup failed. The `error` field contains a human-readable description. |

The `POST` that creates an ephemeral agent returns `201` *immediately* with a
`chatbot_id` and `status: "creating"`. The client then polls the status
endpoint until `status` reaches `"ready"` (or `"error"`).

### Why Memory-First?

Building a RAG index, connecting to external MCP servers, and loading tool
configurations can take several seconds. Blocking the user on all of this
during creation would feel slow. The memory-first approach lets the frontend
show a progress indicator ("Setting up your agent…") while warm-up runs in
the background.

### How It Differs from the Existing Bot Flow

| | Existing flow (`PUT /api/v1/user_agents`) | New ephemeral flow (`POST /api/v1/agents/user/`) |
|---|---|---|
| DB row created? | Immediately on PUT | Only when the user promotes via PUT |
| Bot ready? | Lazily on first chat | After polling `status == "ready"` |
| Can be discarded? | Only via DELETE | Yes, before and after promotion |
| TTL | No automatic expiry | 24 h (configurable server-side) |
| RAG store | pgvector collection | FAISS in-process (S3 on promote) |

Once an ephemeral agent is promoted via `PUT /api/v1/agents/user/{chatbot_id}`,
it becomes a regular persisted bot accessible at the same `chatbot_id` through
the existing chat endpoint (`POST /api/v1/agents/chat/{chatbot_id}`). No
client-side identity change is needed.

---

## 2. End-to-End UI Flow

The following numbered steps describe the screens and state transitions the
user goes through. This is a product-level description, not a wireframe spec.

1. **Open the "New Agent" dialog** — User taps "Create Agent". The UI shows a
   form with tabs: *General*, *Tools*, *MCP Servers*, *Documents*, *RAG Mode*.

2. **Fill in General settings** — Name, description, system prompt, LLM
   provider (e.g. `google`), model name (e.g. `gemini-2.0-flash`),
   operation mode (`adaptive` / `tool_only` / etc.).

3. **Pick tools** — The UI fetches `GET /api/v1/tools/catalog` and displays a
   searchable list of available tools. User checks the ones they want.

4. **Configure MCP servers (optional)** — User adds HTTP MCP server URLs with
   optional auth. Each entry is a `{type, url, ...}` JSON object.

5. **Upload documents (optional)** — User drags in PDFs or text files. Up to
   50 MB per file (default; env-configurable). The UI selects a RAG mode:
   - `"vector"` — FAISS vector store (default for uploaded PDFs).
   - `"pageindex"` — Page-level index for large structured documents.

6. **Submit** — User clicks **Create**. The UI posts to
   `POST /api/v1/agents/user/` as multipart with a `config` JSON part and
   optional `files[]` parts. The server responds `201` with
   `{chatbot_id, status: "creating"}`.

7. **Show warm-up progress** — The UI polls `GET /api/v1/agents/user/{chatbot_id}/status`
   at decreasing intervals (see §4). It renders a per-subsystem progress bar:
   - `tools` — "Syncing tools…" / "Ready"
   - `mcp` — "Validating MCP servers…" / "Ready" / "Skipped"
   - `rag` — "Building index…" / "Ready" / "Skipped"

8. **Ready to chat** — When `phase == "ready"`, unlock the chat input. The
   user sends messages to `POST /api/v1/agents/chat/{chatbot_id}` exactly as
   they would with any other agent (no API change there).

9. **Save (optional)** — A persistent "Save Agent" button is available while
   the agent is ephemeral. Clicking it calls
   `PUT /api/v1/agents/user/{chatbot_id}` to promote it to the database.
   After promotion, the agent continues to exist at the same `chatbot_id`.

10. **Discard (optional)** — A "Discard" button (or closing the session)
    calls `DELETE /api/v1/agents/user/{chatbot_id}`. Uploaded documents are
    deleted from S3. If the user does nothing, the agent expires after 24 h.

---

## 3. HTTP Endpoints

### Auth

All five FEAT-149 endpoints require an authenticated session (session cookie).
The `user_id` is resolved server-side from the session — the client never
sends it explicitly.

**Error envelope** (used for all 4xx/5xx responses):
```json
{ "error": "Human-readable description of the problem." }
```

---

### POST `/api/v1/agents/user/` — Create ephemeral agent

**Auth**: session required  
**Content-Type**: `multipart/form-data` (recommended when uploading files) or `application/json`

#### Request — multipart/form-data

```
POST /api/v1/agents/user/
Content-Type: multipart/form-data; boundary=---boundary

-----boundary
Content-Disposition: form-data; name="config"
Content-Type: application/json

{
  "name": "trial-bot",
  "description": "My experimental assistant",
  "llm": "google",
  "model_config": {"model": "gemini-2.0-flash"},
  "system_prompt_template": "You are a helpful assistant.",
  "tools_config_plain": ["weather", "ddgo"],
  "mcp_config_plain": [
    {
      "type": "http",
      "url": "https://my-mcp-server.example.com",
      "name": "my-tools"
    }
  ],
  "use_vector": true,
  "vector_config": {"rag_mode": "vector"}
}
-----boundary
Content-Disposition: form-data; name="files[]"; filename="manual.pdf"
Content-Type: application/pdf

<binary PDF data>
-----boundary--
```

#### Request — application/json (no files)

```json
{
  "name": "trial-bot",
  "description": "My experimental assistant",
  "llm": "google",
  "model_config": {"model": "gemini-2.0-flash"},
  "system_prompt_template": "You are a helpful assistant.",
  "tools_config_plain": ["weather"],
  "mcp_config_plain": [],
  "use_vector": false,
  "vector_config": {}
}
```

#### Config field reference

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | **yes** | — | Display name for the agent. |
| `description` | string | no | `""` | Short description. |
| `llm` | string | no | `"google"` | LLM provider slug (`google`, `openai`, `anthropic`, etc.). |
| `model_config` | object | no | `{}` | Provider-specific model params (e.g. `{"model": "gemini-2.0-flash"}`). |
| `system_prompt_template` | string | no | `""` | System prompt. Supports `{variable}` placeholders. |
| `human_prompt_template` | string | no | `null` | Optional human-turn template. |
| `tools_config_plain` | array of strings | no | `[]` | Tool slugs from the catalog (e.g. `["weather", "ddgo"]`). |
| `mcp_config_plain` | array of objects | no | `[]` | MCP server configs (see §7). |
| `use_vector` | bool | no | `false` | Whether to build a RAG index over uploaded files. |
| `vector_config` | object | no | `{}` | RAG config. Must include `rag_mode` when `use_vector` is true. |
| `vector_config.rag_mode` | `"vector"` \| `"pageindex"` | when `use_vector` | `"vector"` | RAG strategy. |
| `operation_mode` | string | no | `"adaptive"` | Agent reasoning mode. |
| `language` | string | no | `"en"` | Response language hint. |
| `max_context_turns` | int | no | `5` | Number of prior turns to include in context. |

#### Responses

**201 Created** — Agent created, warm-up scheduled:
```json
{
  "chatbot_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "creating"
}
```

**400 Bad Request** — Required field missing:
```json
{ "error": "Field 'name' is required." }
```

**401 Unauthorized** — No valid session:
```json
{ "error": "Authentication required." }
```

**503 Service Unavailable** — BotManager not ready:
```json
{ "error": "BotManager unavailable." }
```

**500 Internal Server Error**:
```json
{ "error": "Failed to create ephemeral agent: <detail>" }
```

**Idempotency**: NOT idempotent. Each call creates a new `chatbot_id`.

---

### GET `/api/v1/agents/user/{chatbot_id}/status` — Warm-up polling

**Auth**: session required  
**Content-Type**: none

#### Path parameters

| Parameter | Type | Description |
|---|---|---|
| `chatbot_id` | UUID string | The `chatbot_id` returned by POST. |

#### Responses

**200 OK** — Status snapshot:
```json
{
  "chatbot_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "phase": "warming",
  "progress": {
    "tools": "ready",
    "mcp": "validating",
    "rag": "building"
  },
  "error": null
}
```

When `phase == "error"`:
```json
{
  "chatbot_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "phase": "error",
  "progress": {
    "tools": "ready",
    "mcp": "ready",
    "rag": "building"
  },
  "error": "FAISS index build failed: out of memory"
}
```

**401 Unauthorized**:
```json
{ "error": "Authentication required." }
```

**404 Not Found** — Not in registry (wrong user, expired, or not yet created):
```json
{ "error": "Ephemeral agent not found." }
```

**Idempotency**: Safe to call repeatedly. Has no side effects.

---

### PUT `/api/v1/agents/user/{chatbot_id}` — Promote to persistent

**Auth**: session required  
**Content-Type**: none (no request body)

Promotes the ephemeral agent to a persistent database row. The agent keeps its
`chatbot_id` and becomes accessible through the normal user-bot resolution
path. The ephemeral registry entry is removed.

#### Path parameters

| Parameter | Type | Description |
|---|---|---|
| `chatbot_id` | UUID string | The ephemeral agent to promote. |

#### Responses

**200 OK** — Promoted successfully. Returns the persisted bot model:
```json
{
  "chatbot_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "user_id": 42,
  "name": "trial-bot",
  "description": "My experimental assistant",
  "llm": "google",
  "enabled": true,
  "use_vector": true,
  "vector_config": {
    "rag_mode": "vector",
    "faiss_persist_path": "faiss/3fa85f64-5717-4562-b3fc-2c963f66afa6.faiss"
  },
  "documents": [
    {
      "name": "manual.pdf",
      "path": "users_bots/42/3fa85f64.../manual.pdf",
      "url": "https://...",
      "size": 204800
    }
  ],
  "created_at": "2026-05-07T12:34:56",
  "updated_at": "2026-05-07T12:35:10"
}
```

**400 Bad Request** — Missing path parameter:
```json
{ "error": "Missing chatbot_id." }
```

**401 Unauthorized**:
```json
{ "error": "Authentication required." }
```

**404 Not Found** — Not in ephemeral registry:
```json
{ "error": "Ephemeral agent not found." }
```

**409 Conflict** — Agent is not ready yet, or already promoted:
```json
{ "error": "Agent is not ready for promotion (phase='warming')." }
```

**500 Internal Server Error**:
```json
{ "error": "Failed to promote agent: <detail>" }
```

**Idempotency**: NOT idempotent. Second call after successful promotion
returns `409` (agent no longer in the ephemeral registry).

---

### DELETE `/api/v1/agents/user/{chatbot_id}` — Discard ephemeral

**Auth**: session required  
**Content-Type**: none

Discards an ephemeral agent. Removes it from the in-memory registry and
deletes any uploaded documents from S3 (best-effort).

If the agent has already been promoted (it is no longer ephemeral), this
endpoint returns `404`. Use the existing `DELETE /api/v1/user_agents/{chatbot_id}`
to delete promoted bots.

#### Path parameters

| Parameter | Type | Description |
|---|---|---|
| `chatbot_id` | UUID string | The ephemeral agent to discard. |

#### Responses

**204 No Content** — Discarded successfully (no body).

**400 Bad Request**:
```json
{ "error": "Missing chatbot_id." }
```

**401 Unauthorized**:
```json
{ "error": "Authentication required." }
```

**404 Not Found** — Not in ephemeral registry (may already be promoted):
```json
{
  "error": "Ephemeral agent not found. Use UserAgentHandler to delete persisted agents."
}
```

**Idempotency**: Safe to call once; a second call returns `404`.

---

### GET `/api/v1/tools/catalog` — Tool catalog

**Auth**: session required  
**Content-Type**: none

Returns the list of all available tools. The frontend uses this to populate
the tool-picker when creating an ephemeral agent.

#### Responses

**200 OK** — Tool catalog array sorted by `slug`:
```json
[
  {
    "slug": "ddgo",
    "dotted_path": "parrot_tools.ddgo.DuckDuckGoToolkit",
    "description": "DuckDuckGo search toolkit.",
    "category": "search"
  },
  {
    "slug": "weather",
    "dotted_path": "parrot_tools.weather.WeatherTool",
    "description": "Get the current weather for a location."
  },
  {
    "slug": "zipcode",
    "dotted_path": "parrot_tools.zipcode.ZipcodeAPIToolkit"
  }
]
```

Fields:

| Field | Type | Always present | Description |
|---|---|---|---|
| `slug` | string | yes | Identifier used in `tools_config_plain`. Stable contract. |
| `dotted_path` | string | yes | Python import path. Stable contract. |
| `description` | string | no | First line of the tool class docstring (if available). May be enriched in future. |
| `category` | string | no | Category string from the tool class, if defined. |

**Note**: `description` and `category` are best-effort; they may be absent
for some entries. `slug` and `dotted_path` are guaranteed stable.

**401 Unauthorized**:
```json
{ "error": "Authentication required." }
```

**Idempotency**: Safe to call repeatedly. Response is cached server-side for
the process lifetime after the first request.

---

### Cross-reference: Existing routes (do NOT re-document here)

These routes continue to work for persisted bots and are unchanged:

| Method | Path | Description |
|---|---|---|
| `PUT` | `/api/v1/user_agents` | Create a persisted bot (synchronous DB-first flow). |
| `PATCH` | `/api/v1/user_agents/{chatbot_id}` | Partially update a persisted bot. |
| `GET` | `/api/v1/user_agents` | List all persisted bots for the current user. |
| `GET` | `/api/v1/user_agents/{chatbot_id}` | Fetch one persisted bot. |
| `DELETE` | `/api/v1/user_agents/{chatbot_id}` | Delete a persisted bot (removes S3 docs). |
| `POST` | `/api/v1/agents/chat/{chatbot_id}` | Send a chat message (works for both ephemeral-ready and persisted bots). |

---

## 4. Polling Guidance

### Recommended Polling Strategy

| Time since POST | Interval |
|---|---|
| 0–10 s | Every 1 s |
| 10–60 s | Every 3 s |
| 60 s–5 min | Every 5 s |
| > 5 min | Stop and show timeout error to the user |

The 5-minute ceiling is a client-side safety valve. A healthy warm-up
completes within 10–30 seconds for most configurations. Only very large RAG
indexes (multi-hundred MB) may take longer.

### Phase Meanings in UX Terms

| `phase` | UX Label | Description |
|---|---|---|
| `creating` | "Starting up…" | Server confirmed the request. Warm-up is about to begin. |
| `warming` | "Getting ready…" | Tools, MCP, and RAG setup are in progress. |
| `ready` | "Ready to chat!" | All subsystems initialized. Unlock the chat input. |
| `error` | "Setup failed" | Something went wrong. Show `error` field. Let user retry or discard. |

### Progress Keys for a Per-Subsystem Progress Bar

The `progress` object in the status response contains per-subsystem keys.
Each value cycles through the states below:

| Key | Possible values | UX label |
|---|---|---|
| `tools` | `"syncing"` → `"ready"` | Tool sync |
| `mcp` | `"validating"` → `"ready"` \| `"skipped"` | MCP server connection |
| `rag` | `"building"` → `"ready"` \| `"skipped"` | Document index build |

`"skipped"` means the subsystem had nothing to do (e.g. no MCP servers
configured, no documents uploaded). Show "Skipped" or simply hide that row.

---

## 5. File Upload Protocol

### Multipart Layout

```
POST /api/v1/agents/user/
Content-Type: multipart/form-data; boundary=<boundary>

Part 1  — name="config",  Content-Type="application/json"  → config JSON (required)
Part 2+ — name="files[]", Content-Type="<mime-type>",
           filename="<original-filename>"                   → file binary (0 or more)
```

- The `config` part MUST appear first.
- Each file part uses the field name `files[]`.
- There is no enforced limit on the number of files, but per-file size is
  capped at **50 MB** by default (configurable via `MAX_UPLOAD_BYTES` env var
  on the server).

### MIME Types by RAG Mode

| `rag_mode` | Accepted MIME types |
|---|---|
| `"vector"` | `application/pdf`, `text/plain`, `text/markdown`, `text/html`, any text-based type |
| `"pageindex"` | `application/pdf` (requires a document with a table of contents) |

### No-File Shortcut

If there are no files, use `application/json` directly with the config
object as the request body. The server auto-detects content type.

---

## 6. Tool Catalog Payload

The `GET /api/v1/tools/catalog` response is a JSON array sorted by `slug`.
Full shape described in §3.

**Stable contract fields** (guaranteed across versions):
- `slug` — use this in `tools_config_plain` when creating an agent.
- `dotted_path` — internal import path; do not call directly.

**Enrichment fields** (may evolve):
- `description` — sourced from docstrings, subject to wording changes.
- `category` — may be added to more tools in future releases.

**Open question**: The catalog currently exposes all installed tools with no
filtering by user permissions. A future update may scope the catalog to tools
the user's plan allows. See §9 Open Questions.

---

## 7. MCP Server Config Payload

An MCP server entry (one item in `mcp_config_plain`) has this shape:

```json
{
  "type": "http",
  "name": "my-tools",
  "url": "https://mcp-server.example.com",
  "api_key": "sk-...",
  "timeout": 30
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | `"http"` | yes | Transport type. Only `"http"` is supported for ephemeral agents. |
| `name` | string | yes | Display name for the MCP server connection. |
| `url` | string | yes | Base URL of the HTTP MCP server. |
| `api_key` | string | no | API key for the MCP server (stored encrypted). |
| `timeout` | int | no | Connection timeout in seconds (default: 30). |

### Handshake Validation During Warm-up

During warm-up, the server connects to each MCP server and lists tools once.
If the connection is refused, times out, or returns an unexpected response,
warm-up sets `phase = "error"` with an `error` message like:

```
MCP handshake failed for https://mcp-server.example.com: Connection refused
```

A failing MCP handshake prevents promotion. The user should check the server
URL and API key, then discard and recreate the agent.

**HTTP-only**: `stdio`-transport and local MCP servers are NOT supported for
ephemeral agents in FEAT-149.

---

## 8. Saving / Promoting

When the user promotes an ephemeral agent via `PUT /api/v1/agents/user/{chatbot_id}`:

1. The agent's in-memory state is written to the `navigator.users_bots`
   database table with the **same `chatbot_id`**. No new ID is generated.

2. If the agent uses FAISS vector RAG, the index is serialized and uploaded
   to S3. The path is stored in `vector_config.faiss_persist_path` in the DB
   row. On future restarts, the index is reloaded from S3 automatically.

3. The agent is removed from the ephemeral registry. From this point it is a
   regular persisted bot.

4. The frontend should refresh its "My Bots" list view after a successful
   promote (re-fetch from `GET /api/v1/user_agents`).

5. The promoted agent remains chateable at exactly the same endpoint:
   `POST /api/v1/agents/chat/{chatbot_id}`. No URL change.

**What the frontend should re-fetch after promote**:
- The "My Bots" list: `GET /api/v1/user_agents`
- The individual bot details: `GET /api/v1/user_agents/{chatbot_id}`

**What stays the same**: `chatbot_id`, active chat session, chat history
stored in the session.

---

## 9. Open Questions for the Frontend Team

These are product decisions the backend cannot make unilaterally:

1. **Discard button**: Should the UI show a "Discard" button next to "Save"
   while the agent is ephemeral and ready? Discarding removes S3 docs. What
   confirmation UX is appropriate?

2. **Error recovery**: When `phase == "error"`, should the UI offer a "Retry"
   button (which would require a new POST + fresh chatbot_id) or only "Discard"?

3. **Promote during warm-up**: The backend returns 409 if the user tries to
   promote while `phase != "ready"`. Should the UI disable the "Save" button
   until ready, or show a tooltip explaining the wait?

4. **Permissions field**: `UserBotModel` has a `permissions` dict for future
   team-sharing features. The create form currently does not expose it. Should
   v1 let advanced users set permissions at creation time?

5. **Tool catalog filtering**: Should tools be filtered by some criteria (e.g.
   user plan, installed plugins) before being shown to the user? Today the
   catalog returns everything installed on the server.

6. **Share-key flow** (FEAT-149 §8, deferred): A future feature will allow
   sharing an agent with another user via a permission entry on
   `users_bots.permissions`. Do not implement share UI in v1 — leave a
   placeholder for FEAT-XXX.

7. **Warm-up ceiling**: If the user closes the "create" dialog while warm-up
   is still in progress, the bot continues warming in the background. Should
   the UI show a notification when warm-up completes (e.g. "Your bot is ready"
   badge)?

8. **Multiple ephemeral agents**: Can a user have more than one ephemeral
   agent running simultaneously? The backend supports it (each gets its own
   `chatbot_id`). Should the UI cap this at 1, or allow N?

---

## 10. Out-of-Scope Reminders

The following capabilities are explicitly NOT part of FEAT-149 and should not
be assumed in the frontend spec:

- **Agent sharing** — per-user permission lists on `users_bots.permissions`
  are a post-FEAT-149 deliverable. No sharing endpoint exists yet.

- **stdio MCP servers** — only HTTP-transport MCP is supported for ephemeral
  agents. Local/stdio MCP is a different feature.

- **Runtime tool authoring** — users cannot define new tools through the UI
  in FEAT-149. They can only select from `TOOL_REGISTRY`.

- **Streaming warm-up status** — the status endpoint is a poll-only snapshot.
  A WebSocket or SSE stream for live progress is a possible follow-up.

- **Per-agent quotas or rate limits** — no per-ephemeral resource accounting
  is implemented in FEAT-149.

- **Multi-tenant agent pools** — ephemeral agents are strictly per-user.
  There is no concept of a "shared" ephemeral pool in this feature.
