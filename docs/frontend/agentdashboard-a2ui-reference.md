# AgentDashboard — A2UI v1.0 Technical Reference for `navigator-frontend-next`

**Audience**: the `navigator-frontend-next` team (SvelteKit, Svelte 5 runes, shadcn-svelte / bits-ui, Tailwind v4).
**Goal**: build a new **AgentDashboard** service (derived from `AgentChat`) that asks an ai-parrot agent for **dashboards, infographics and widgets**, receives them as **A2UI v1.0 surfaces**, and renders them with a **new Svelte 5 + shadcn renderer** — while also offering the backend-rendered **interactive HTML** of the same surface.
**Verified against**: `ai-parrot` branch `dev` at `a1eca82b4` (2026-09-02), which includes the merged features below. Every path in this document is relative to the repo root; core source lives under `packages/ai-parrot/src/parrot/`, server handlers under `packages/ai-parrot-server/src/parrot/`, concrete renderers under `packages/ai-parrot-visualizations/src/parrot/`.

| Feature | Spec | What it contributes to this document |
|---|---|---|
| FEAT-470 A2UI v1.0 dialect | `sdd/specs/a2ui-v1-dialect.spec.md` | The wire format, Basic Catalog (18 primitives + 14 functions), Parrot presentation catalog, renderer contract |
| FEAT-473 structured outputs → A2UI | `sdd/specs/a2ui-v1-structured-outputs.spec.md` | `structured_chart` / `structured_table` / `structured_map` responses now dual-emit an A2UI envelope + `artifacts[]` v2 |
| FEAT-469 agent functions runtime | `sdd/specs/a2ui-agent-functions.spec.md` | The renderer→agent RPC leg: `action`, `callAgentFunction`, SSE `callRendererFunction`, deep links, `A2UIHandler` |
| FEAT-491 FlexDashboard agent | `sdd/specs/flex-agent-infographic-a2ui.spec.md` | The reference agent (`agents/flex_dashboard.py`): datasets, skills, recipe, `refresh_dashboard` |
| FEAT-492 surface rehydration | `sdd/specs/a2ui-surface-rehydration.spec.md` | Persistent, bookmarkable surfaces (`dashboard` / `infographic` / `widget`), share tokens, refresh, JSON/HTML negotiation |
| FEAT-493 HTML design system | `sdd/specs/html-renderer-design-system.spec.md`, `docs/design-system.md` | The `interactive-html` renderer: themes × layouts, rich DataTable, KPI grid, `FilterBar` + client-side filtering |

Related existing docs: `docs/outputs/a2ui-v1.md`, `docs/outputs/a2ui-agent-functions.md`, `docs/outputs/infographic-recipes.md`, `docs/design-system.md`, `docs/agent.md` (partially stale, see §11), `examples/agents/a2ui/README.md`.

A Postman collection covering every route in this document ships alongside it: `docs/postman/a2ui-agentdashboard.postman_collection.json`.

---

## Table of contents

1. [Concepts in one page](#1-concepts-in-one-page)
2. [Backend actors and naming](#2-backend-actors-and-naming)
3. [HTTP API reference](#3-http-api-reference)
4. [A2UI v1.0 wire format](#4-a2ui-v10-wire-format)
5. [Component catalog](#5-component-catalog)
6. [Dashboards, infographics and widgets](#6-dashboards-infographics-and-widgets)
7. [The interactive HTML lane (FEAT-493)](#7-the-interactive-html-lane-feat-493)
8. [Frontend design: AgentDashboard service + Svelte renderer](#8-frontend-design-agentdashboard-service--svelte-renderer)
9. [TypeScript wire types](#9-typescript-wire-types)
10. [Conformance fixtures and testing](#10-conformance-fixtures-and-testing)
11. [Known gaps, bugs and doc/code disagreements](#11-known-gaps-bugs-and-doccode-disagreements)

---

## 1. Concepts in one page

**A2UI** (Agent-to-UI) is a declarative UI protocol: the agent does not send HTML, it sends a **surface** — a flat list of typed components plus a JSON **data model** — and the renderer (your Svelte code, or the backend HTML renderer) turns it into UI. ai-parrot implements the upstream v1.0 protocol (`google/A2UI`, SHA `90157ec1`) plus its own **presentation catalog** (`Chart`, `DataTable`, `Map`, `KPICard`, `InfoCard`, `Timeline`, `Report`, `Infographic`, `FilterBar`).

**Envelope** — every message on the wire is `{"version": "v1.0", "<messageKey>": {...}}`, exactly two keys. Agent→renderer keys: `createSurface`, `updateComponents`, `updateDataModel`, `deleteSurface`, `callRendererFunction`, `agentFunctionResponse`. Renderer→agent keys: `action`, `callAgentFunction`, `rendererFunctionResponse`, `error`.

**Surface** — identified by `surfaceId`. `createSurface.components` is a flat adjacency list; exactly one component has `id: "root"`. Parent→child links are by id (`child`, `children`, `tabs[].child`). Props are top-level on the component object. Dynamic values are JSON-pointer bindings `{"path": "/rows"}` into `dataModel`, or catalog function calls `{"call": "formatCurrency", "args": {...}}`.

**Catalogs** — `catalogId` on the surface (or per component) says which vocabulary a component name belongs to. Two catalogs exist:

| Catalog | id | Contents |
|---|---|---|
| Basic (upstream, official) | `https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json` | 18 primitives (`Text`, `Row`, `Column`, `Card`, `Tabs`, `Button`, `ChoicePicker`, …) + 14 functions |
| Parrot (presentation) | `https://parrot.dev/catalogs/v1` | 9 composites (`Chart`, `DataTable`, `Map`, `KPICard`, `InfoCard`, `Timeline`, `Report`, `Infographic`, `FilterBar`). Every composite can be **lowered** to Basic primitives. |

**Kinds** — `dashboard`, `infographic`, `widget`. There is **no `kind` field on the wire**. The kind is an attribute of how the surface was produced and how it is persisted (`UISurfaceKind` in the ui_surfaces plane). §6.2 gives the frontend heuristic.

**Two delivery lanes for the same surface**:

| Lane | What you get | Who renders | How |
|---|---|---|---|
| A2UI JSON | `a2ui_envelope` in the chat response, or `envelope` from the surfaces API | **Your Svelte renderer** | `POST /api/v1/agents/chat/{agent_id}` with `output_mode: "a2ui"`; `GET /api/v1/ui/surfaces/{id}` |
| Interactive HTML | A single self-contained `text/html` document (inlined Chart.js, design-system CSS, vanilla JS) | **Backend `interactive-html` renderer** (FEAT-493) | `GET /api/v1/ui/surfaces/{id}?format=html` (or `Accept: text/html`); mirror at `GET /api/v1/agents/{agent_id}/a2ui/surfaces/{id}` |

The HTML lane requires the surface to be **persisted** first (`POST /api/v1/ui/surfaces`) — the chat endpoint never returns rendered HTML for an A2UI response. §8.3 describes the "two buttons" flow built on this.

**RPC leg** — a rendered surface can talk back: `action` (a user event), `callAgentFunction` (invoke an agent tool by name), and the agent can push `callRendererFunction` over SSE. Endpoint: `/api/v1/agents/{agent_id}/a2ui`.

---

## 2. Backend actors and naming

### 2.1 `AgentTalk` vs `AgentHandler`

The request said "AgentHandler (based on AgentTalk)". In the codebase these are two different classes:

| Class | File | Role |
|---|---|---|
| **`AgentTalk`** | `packages/ai-parrot-server/src/parrot/handlers/agent.py:110` | **The HTTP chat handler the frontend calls**, mounted at `/api/v1/agents/chat/{agent_id}`. Decorated `@is_authenticated()` `@user_session()`. This is the class that serves `output_mode: "a2ui"` responses. |
| `AgentHandler` | `packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py:168` | Abstract base for bespoke, self-registering agent REST handlers (`base_route`, `additional_routes`, `setup(app)`). Not mounted by `BotManager`; exposes no dashboard surface. |
| **`A2UIHandler`** | `packages/ai-parrot-server/src/parrot/handlers/a2ui.py:70` | Subclass of `AgentTalk` (reuses only agent/user/session resolution) that owns the A2UI RPC routes under `/api/v1/agents/{agent_id}/a2ui`. |
| **`UISurfacesHandler`** | `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | The persistent surfaces plane, `/api/v1/ui/surfaces…`. |

Throughout this document "the chat endpoint" means `AgentTalk`.

### 2.2 The FlexDashboard agent (FEAT-491)

`agents/flex_dashboard.py` — `@register_agent(name="flex_dashboard")`, class `FlexDashboard(NarrativeMixin, InfographicAuthoringMixin, PandasAgent)`, `llm = "google:gemini-3.5-flash"`. Reference it by its registry name **`flex_dashboard`** (a dotted import of `agents.flex_dashboard` fails, by design — see the module docstring). It is the reference implementation for every kind:

- **Dashboard** — the published deterministic recipe `flex-program-dashboard` (`DASHBOARD_RECIPE_NAME`), replayed by `RecipeRunner` or refreshed via the `refresh_dashboard` agent function. Five sections → five tabs (Payroll hero KPIs, month series charts, pay-code tables, rep-utilization table, proximity-staffing map + coverage table).
- **Infographic** — the `/infographic` skill trigger: ad-hoc, LLM-authored, via `InfographicToolkit`.
- **Widget** — the `/widget` skill trigger: one named KPI as a single `Chart` / `DataTable` / `Map` / `KPICard` surface.

Details in §6.4.

### 2.3 The server stack in one diagram

```
Svelte AgentDashboard ──POST /api/v1/agents/chat/{agent}  (output_mode: a2ui)──▶ AgentTalk ──▶ Agent.ask() ──▶ a2ui_envelope
        │                                                                                              │
        │  POST /api/v1/ui/surfaces  (pin: kind + title + envelope) ─────────────▶ UISurfacesHandler ──▶ navigator.ui_surfaces (Postgres)
        │  GET  /api/v1/ui/surfaces/{id}            → JSON envelope   (Svelte renderer)                  │
        │  GET  /api/v1/ui/surfaces/{id}?format=html → interactive HTML (InteractiveHTMLRenderer, FEAT-493)
        │
        │  POST /api/v1/agents/{agent}/a2ui   action | callAgentFunction | rendererFunctionResponse | error ──▶ A2UIHandler ──▶ A2UIRuntime ──▶ ToolManager
        │  GET  /api/v1/agents/{agent}/a2ui   SSE: callRendererFunction
        └─ GET  /api/v1/agents/{agent}/a2ui/capabilities
```

---

## 3. HTTP API reference

### 3.1 Authentication and identity

- All routes below except the public artifact URL and the deep-link landing page require an authenticated user. The Navigator auth middleware accepts either the **session cookie** or `Authorization: Bearer <token>`. The frontend's existing `http.ts` interceptor already injects the bearer token; `getAuthHeaders()` does the same for `fetch`.
- Unauthenticated → `401`, reason `Access Denied`, `Content-Type: application/json`, **empty body**.
- CORS is global (`allow_credentials=True`, origin echoed), so cookie auth from the SvelteKit dev origin works.
- **Identity precedence gotcha**: on the chat endpoint, `user_id` and `session_id` in the request body take priority over the session (`agent.py:886`). On `A2UIHandler`, the body is a protocol-strict envelope, so `user_id`, `session_id` and `agent_name` are read from the **query string**. `session_id` is the conversation id and is **never** derived from the browser session — the client owns it (mint a `uuid4` and persist it, exactly as `AgentChat` does).

### 3.2 Chat: `POST /api/v1/agents/chat/{agent_id}`

`AgentTalk.post` (`agent.py:1441`). Also `POST /api/v1/agents/chat/{agent_id}/{method_name}` to invoke a named agent method instead of `ask()`.

Request body (JSON, or `multipart/form-data` for uploads). Fields the handler consumes:

| Field | Type | Default | Notes |
|---|---|---|---|
| `query` | string | — | Required. Use skill triggers (`/widget …`, `/infographic …`) to steer the FlexDashboard agent. |
| `session_id` | string | fresh `uuid4().hex` | Conversation id. Send it on every turn. |
| `user_id` | string | session user | Overrides the authenticated user (see gotcha above). |
| `message_id` | string | — | Client-minted turn id, persisted as `turn_id`. |
| **`output_mode`** | string | `"default"` | **Send `"a2ui"`** to request an A2UI surface. Other relevant values: `structured_chart`, `structured_table`, `structured_map`, `infographic`, `interactive`. Unknown values fall back to `default` with a warning. **Body only — the `?output_mode=` query parameter is dead code.** |
| `output_format` | `json\|html\|markdown\|text` | negotiated from `Accept` | HTTP serialization. Irrelevant for A2UI responses (always JSON). |
| `stream` | bool | `false` | Chunked streaming (§3.2.3). Force-disabled for `infographic` / `interactive`. |
| `format_kwargs` | object | `{}` | `include_sources`, `include_tool_calls`, `interactive`. **Do not send AgentChat's `{output_format:"html", html_mode, table_mode}` for A2UI turns.** |
| `turn_id` + `data` | string + any | — | Follow-up on a previous turn (`bot.followup()`). |
| `use_conversation_history` / `use_vector_context` / `return_sources` / `search_type` | | `true` / `true` / `true` / `similarity` | |
| `ws_channel_id` | string | — | WebSocket channel to ping when the answer is ready. |
| `hitl_response` | object | — | `{turn_id, value, response_type?}` to resume a paused human-in-the-loop turn. |
| `tools`, `mcp_servers`, `tool_config` | | | **Deprecated, silently dropped** — use `PATCH`. |
| anything else | | | Forwarded verbatim as `**kwargs` to `agent.ask()`. |

There is **no** `theme`, `layout`, `dataset`, `dataset_id` or `hints` field. Dataset choice happens inside the prompt (FlexDashboard resolves its six dataset aliases itself); theme and layout belong to the persisted surface / recipe (§7.2).

#### 3.2.1 A2UI response (non-streaming)

When the turn produced an A2UI surface (`response.output_mode == "a2ui"`), the handler returns **this shape and nothing else**, regardless of `Accept` (`agent.py:2717-2725`):

```json
{
  "input": "/widget worked hours by month",
  "output": "Worked hours per month for the current filter scope.",
  "output_mode": "a2ui",
  "a2ui_envelope": {
    "version": "v1.0",
    "createSurface": {
      "surfaceId": "structured_chart-a1b2c3d4",
      "catalogId": "https://parrot.dev/catalogs/v1",
      "sendDataModel": false,
      "components": [
        {"id": "root", "component": "Chart", "type": "line", "x": "month", "y": ["worked_hours"],
         "title": "Worked hours by month", "showLegend": true, "data": {"path": "/rows"}}
      ],
      "dataModel": {"rows": [{"month": "2025-07", "worked_hours": 18234.5}, {"month": "2025-08", "worked_hours": 19011.0}]}
    }
  }
}
```

- `a2ui_envelope` is a **single envelope object or a list of envelopes** — handle both.
- `output` is the prose caption (may be empty).
- **Degradation**: if `output_mode: "a2ui"` was requested but the agent produced no surface, it downgrades to `default`. You then receive the standard envelope (§3.2.2) with `output_mode: "default"` and **no** `a2ui_envelope`. Always branch on the presence of `a2ui_envelope`, not on what you asked for.

#### 3.2.2 Standard JSON response (all other modes)

```json
{
  "input": "…", "output": "…or structured config…", "data": "…rows or null…", "response": "…markdown…",
  "output_mode": "structured_chart",
  "code": null,
  "metadata": {"model": "…", "provider": "…", "session_id": "…", "turn_id": "…", "user_id": "…",
               "response_time": 1234, "usage": null, "finish_reason": null, "stop_reason": null, "created_at": null},
  "sources": [], "tool_calls": [{"name": "…", "status": "…", "output": "…", "arguments": {}}],
  "artifacts": [{"type": "chart", "artifactId": "structured_chart-a1b2c3d4", "surfaceId": "structured_chart-a1b2c3d4",
                 "schemaVersion": 2, "definition": {"id": "root", "component": "Chart", "…": "…"}}],
  "a2ui_envelope": {"version": "v1.0", "createSurface": {"…": "…"}}
}
```

Since FEAT-473, `structured_chart` / `structured_table` / `structured_map` responses **also** carry `a2ui_envelope` (dual emission) and an `artifacts[]` entry whose `definition` is the envelope's root component. `output` and `data` are byte-identical to the pre-A2UI contract plus one new key `surfaceId` on `output`. This means the existing `ChatBubble` branches keep working, and the new renderer can consume `a2ui_envelope` from the same message.

`output_mode: "infographic"` (the pre-A2UI HTML lane) returns the block-model JSON, or `text/html` when `Accept: text/html` or `?format=html`, with `metadata.html_url`, `html_inline_omitted`, `artifact_id`, `template_name`, `theme` — the fields `AgentChat.maybeOpenInfographicCanvas` already reads.

Two special `200` envelopes can arrive instead of an answer: `{"provider","tool_name","auth_url","scopes","message"}` (OAuth needed; `AgentChat` already renders `ConnectIntegrationPill`) and `{"status":"paused","turn_id","interaction_id","interaction_type","question","context","options","form_schema",…}` (human-in-the-loop pause).

#### 3.2.3 Streaming (`stream: true`)

Not SSE. HTTP chunked `text/plain; charset=utf-8` with header `X-Parrot-Stream: chunked-aimessage`: UTF-8 text chunks, then the separator `\n\x00`, then one JSON object `{"input","output","metadata":{…},"sources","tool_calls","a2ui_envelope"?}`. The frontend's `stream.ts` already parses this; the A2UI envelope arrives in the trailing JSON. On failure the trailer is `\n\x00{"error":"…"}`.

#### 3.2.4 Errors on the chat endpoint

| Status | Body | Note |
|---|---|---|
| `400` | `Missing Agent Name` / `{"error":"query is required"}` | The first is a **raw string** body under `Content-Type: application/json` — guard `JSON.parse` |
| `403` | `{"error":"Access Denied","reason":"…"}` | PBAC policy denial |
| `404` | `Agent 'x' not found.` | Raw string body |
| `500` | `Error retrieving agent: …` / `{"error":"BotManager is not installed."}` | |

### 3.3 A2UI RPC: `A2UIHandler` under `/api/v1/agents/{agent_id}/a2ui`

Registered in `manager.py:2047-2052`, literal sub-routes first.

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/v1/agents/{agent_id}/a2ui?session_id=…[&user_id=…][&agent_name=…]` | Dispatch one renderer→agent envelope, a JSON array of them, or JSONL |
| `GET` | `/api/v1/agents/{agent_id}/a2ui?session_id=…` | **SSE** stream of queued `callRendererFunction` envelopes for that session |
| `GET` | `/api/v1/agents/{agent_id}/a2ui/capabilities` | `{"v1.0":{"supportedCatalogIds":[parrot, basic],"acceptsInlineCatalogs":false}}` |
| `GET` | `/api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id}[?format=html\|json][&share=token]` | Mirror of the persisted-surface GET (§3.4), same negotiation service |

**POST semantics** (`a2ui.py:135-204`):

- `session_id` in the query string is required in practice: it scopes surface state and pending calls.
- Response: one message → `200` with the **bare envelope**, `Content-Type: application/a2ui+json`. Several → `200 {"messages":[…]}` (`application/json`). A single request whose only result is an `error` → **`400`** with that error envelope.
- `action` messages return `[]` messages by themselves, but the handler then runs a user turn on the agent (`agent.ask(question=user_turn, a2ui_surface_state=…)`) and appends the resulting `a2ui_envelope` if the agent produced one. So an `action` POST may come back with a fresh `createSurface`.
- Malformed JSON → `400 {"version":"v1.0","error":{"code":"INVALID_FUNCTION_CALL","message":"Malformed JSON body.","functionCallId":"unknown"}}`; empty body → same with `"Empty request body."`.
- No agent → `404 {"error":"Agent not found."}`; no resolvable user → `401 {"error":"Authentication required."}`.
- Every tool on the agent's `ToolManager` is invocable via `callAgentFunction` by default (opt-out via `a2ui_hidden = True` on the tool). The only barrier is the user's `PermissionContext` built with `channel="a2ui"` and **no roles**, so role-gated policies deny by default.
- Error codes you may receive: `INVALID_FUNCTION_CALL`, `UNALLOWED_PARENT`, `UNALLOWED_CHILD`, `FORBIDDEN`, `NOT_FOUND`, `INTERNAL`, `TIMEOUT`.

**SSE stream** (`a2ui.py:274-315`): `Content-Type: text/event-stream`, frames `data: {"version":"v1.0","callRendererFunction":{…}}\n\n`, keepalive comment `: keepalive` every 15 s. Records are only marked delivered after a successful write, so a dropped connection redelivers on reconnect. Use `EventSource` (cookie auth) or a `fetch` reader (bearer auth) — `EventSource` cannot set headers.

### 3.4 Persistent surfaces: `UISurfacesHandler` (FEAT-492)

Kinds: `UISurfaceKind = "dashboard" | "infographic" | "widget"`. Table `navigator.ui_surfaces` (+ `ui_surface_shares`). Every route requires an authenticated user; errors are always `{"status":"error","message":"…"}`.

| Method | Route | Body / params | Response |
|---|---|---|---|
| `GET` | `/api/v1/ui/surfaces[?kind=dashboard\|infographic\|widget]` | — | `{"status":"success","count":N,"surfaces":[{surface_id, kind, title, refreshable, created_at, updated_at, catalog_id, agent_id, access:"owner"\|"shared"}]}` |
| `GET` | `/api/v1/ui/surfaces/{surface_id}[?share=token][&format=json\|html]` | `Accept: text/html` also selects HTML; `?format=` wins; default JSON | JSON: `{"status":"success","envelope":{…createSurface…},"metadata":{…same fields as list…}}` · HTML: `text/html` rendered on the fly by `InteractiveHTMLRenderer` |
| `POST` | `/api/v1/ui/surfaces` | `PublishSurfaceRequest` (below) | `201 {"status":"success","surface_id":"<uuid4>"}` |
| `POST` | `/api/v1/ui/surfaces/{surface_id}/refresh[?share=token]` | `{"params":{…}}` | The **negotiated** (JSON or HTML) refreshed surface |
| `POST` | `/api/v1/ui/surfaces/{surface_id}/share` | `{"expires_at": iso8601\|null, "ttl": false}` | `201 {"status":"success","token":"…","expires_at":…,"permissions":"read+refresh"}` |
| `DELETE` | `/api/v1/ui/surfaces/{surface_id}` | — | `{"status":"success"}` |
| `DELETE` | `/api/v1/ui/surfaces/{surface_id}/share/{token}` | — | `{"status":"success"}` |

`PublishSurfaceRequest` (`ui_surfaces.py:58-76`):

```jsonc
{
  "kind": "dashboard",                 // required: dashboard | infographic | widget
  "title": "Flex Program Dashboard",   // required
  "envelope": { "surfaceId": "…", "components": [...], "dataModel": {...} },   // the createSurface PAYLOAD (not the {version, createSurface} wrapper)
  "source_artifact_id": null,          // XOR with envelope; needs agent_id + session_id
  "agent_id": "flex_dashboard",
  "session_id": "…",
  "recipe_name": "flex-program-dashboard",   // optional: makes the surface refreshable
  "recipe_owner": null,
  "recipe_params": {"month": "2025-10"}
}
```

Rules that matter to the client:

- `envelope` is validated as `CreateSurface` (the **inner** object). Pass `a2ui_envelope.createSurface`, not the whole `{version, createSurface}` envelope. Validation failure → `400 {"status":"error","message":"Invalid envelope","errors":[…pydantic…]}`.
- The stored `surface_id` is **always a fresh uuid4** — it differs from the envelope's own `surfaceId`. Key your UI state on the stored id; keep the envelope's `surfaceId` for RPC messages.
- Access: owner, or anyone presenting a valid `?share=` token. Unknown / foreign-without-token → `404` (no existence oracle). Token supplied but revoked/expired/mismatched → `410`. A token is **claimed** by the first authenticated user who opens it and then appears in that user's list with `access: "shared"`.
- `refreshable` is `true` iff `recipe_name` is set. Refresh precedence: request `params` > stored `recipe_params` > recipe defaults. Refresh runs under the **owner's** permission context even for share bearers. Non-refreshable → `409 {"status":"error","message":"Surface has no recipe_ref and cannot be refreshed","refreshable":false}`. Recipe failure → `422` (or `502` when the failing stage is `data`) with `RecipeRunError` fields (`recipe, stage, transformer, dataset, missing_columns, detail`).
- HTML lane unavailable (visualizations package not installed) → `501`.

### 3.5 Deep-link resume (FEAT-469)

`GET /api/v1/a2ui/resume/web?token=…` → `text/html` confirmation page, does **not** consume the token (safe for link prescanners). `POST /api/v1/a2ui/resume/web?token=…` → consumes the single-use token (Redis, TTL 900 s), dispatches the stored `action`, injects the turn: `200 {"status":"resumed","session_id":"…","result":{…}}` · `400 {"status":"error","detail":"Missing token."}` · `410 {"status":"expired","detail":"…"}`. Routes are mounted only when `app["redis"]` exists. Deep links appear on `RenderedArtifact.deep_links[]` of static renders (PDF, SSR) for actions that cannot dispatch there; a live Svelte renderer never needs them.

### 3.6 Infographic recipes (dashboards as deterministic replays)

| Method | Route | Body | Response |
|---|---|---|---|
| `GET` | `/api/v1/infographic_recipes` | — | owner-scoped list |
| `GET` | `/api/v1/infographic_recipes/{name}` | — | full `InfographicRecipe` |
| `PUT` / `DELETE` | `/api/v1/infographic_recipes/{name}` | recipe YAML/JSON | |
| `POST` | `/api/v1/infographic_recipes/{name}/run` | `{"params": {"month": "2025-10"}}` | `{"status":"success","artifact":{"artifact_id","filename","mime_type":"text/html","size","storage_ref"}}` — **metadata only, never the HTML bytes**. Undeclared param → `422` with `RecipeRunError`. |

For the frontend, the recipe lane is indirect: a dashboard surface pinned with `recipe_name` is refreshed through `POST /api/v1/ui/surfaces/{id}/refresh`, which runs the recipe and returns the surface. See §11 for a cold-start bug affecting `/run` with the default `interactive-html` profile.

### 3.7 Artifacts (session-scoped and public HTML)

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/v1/threads/{session_id}/artifacts?agent_id=…` | `{"artifacts":[…],"count":N}` |
| `GET` | `/api/v1/threads/{session_id}/artifacts/{artifact_id}?agent_id=…` | JSON `{"artifact":{…}}`; **HTML** when `Accept: text/html`, `?format=html` or `?download=1` (adds `Content-Disposition: attachment`) |
| `GET` | `/api/v1/artifacts/public/{expiry}.{sig}/{artifact_id}.html` | **Unauthenticated** signed URL (HMAC-SHA256 over `"{artifact_id}|{expiry}"`, default TTL 7 days). This is what `metadata.html_url` on infographic responses contains. CSP `frame-ancestors` defaults to `'self'` — set `INFOGRAPHIC_FRAME_ANCESTORS` on the backend to iframe it cross-origin. |

### 3.8 Infographic lane (pre-A2UI, still live)

`POST /api/v1/agents/infographic/{agent_id}` (`?format=html|json`, default **HTML**; body `query`, `template`, `theme`, `session_id`, …), `GET /api/v1/agents/infographic/templates[/{name}]`, `GET /api/v1/agents/infographic/themes[/{name}]` (registered themes: `light`, `dark`, `corporate`, `midnight`, `petrol` — the same five the A2UI design system uses), `POST /api/v1/agents/infographic/render` (deterministic, LLM-free; `async: true` → `202 {"job_id"}` + `GET …/render/jobs/{job_id}`). The frontend's `infographic.ts` already wraps these. They are documented in `docs/infographic_handler_api.md`; they remain the path for the legacy block-model infographics.

---

## 4. A2UI v1.0 wire format

Source of truth: `packages/ai-parrot/src/parrot/outputs/a2ui/models.py` (Pydantic, `extra="forbid"` on every message), `serialization.py`, and the six vendored upstream JSON Schemas under `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/spec/` (`agent_to_renderer.json`, `renderer_to_agent.json`, `common_types.json`, `catalog.json`, `catalog_definition.json`, `agent_capabilities.json`). The frontend should vendor those six files as its conformance schemas.

### 4.1 Envelope invariants

- `{"version": "v1.0", "<key>": {...}}` — exactly two keys (`minProperties: 2`, `maxProperties: 2`). `version` is always the literal `"v1.0"`.
- Serialization uses camelCase aliases and **omits absent optionals** (`exclude_none`), so treat a missing key as "default". Exception: `updateDataModel.value` and function-response `value` may be an explicit `null`.
- Ordering of `components[]` is **not** meaningful (builders emit root first, the lowering pass emits root last). Index by `id`, start at `"root"`. Order **is** meaningful inside `children[]`, `tabs[]`, `layers[]`, `sections[]` and `Timeline.events[]`.
- Legacy dialect detection: a pre-v1.0 envelope has a top-level `messageType` key and props nested under `properties`. The backend never emits it any more (`deserialize` normalizes it with a `DeprecationWarning`). Your renderer only needs v1.0.

### 4.2 Agent → renderer messages

| Key | Fields | Notes |
|---|---|---|
| `createSurface` | `surfaceId` (req), `catalogId?`, `sendDataModel` (default `false`), `components[]` (min 1), `dataModel` (default `{}`), `metadata?: {extensions}` | Implicitly instantiates the reserved `Surface` container with `child: "root"`. `Surface` never appears in `components[]`. |
| `updateComponents` | `surfaceId`, `components[]` | Add/replace components by id on an existing surface. `root` must still exist across the union. |
| `updateDataModel` | `surfaceId`, `path?`, `value` (req, may be `null`) | **Targeted write at a JSON pointer** — not a deep merge, not a whole replace. `path` omitted or `"/"` = entire model. `value: null` **deletes** the key. Re-render every component whose bindings touch that subtree. |
| `deleteSurface` | `surfaceId` | |
| `callRendererFunction` | `functionCallId`, `callFunction: {call, args, catalogId (required here)}` | Arrives over SSE. Reply with `rendererFunctionResponse`. |
| `agentFunctionResponse` | `functionCallId`, exactly one of `value` / `error: {code, message}` | Reply to your `callAgentFunction`. |
| `error` | see §4.3 | **Not declared on the agent→renderer schema**, but the runtime does return `error` envelopes to the renderer (they validate against the renderer→agent schema). Your parser must accept it. |

`metadata.extensions` on the surface is where **`parrot_theme`** and **`parrot_layout`** live (§7.2).

### 4.3 Renderer → agent messages

```jsonc
// User event from a component that declared action.event
{"version": "v1.0", "action": {
  "name": "filters_changed",                 // copied from action.event.name
  "userMessage": "Filtered to October",      // optional, RESOLVED string; becomes a visible user turn
  "surfaceId": "flex-program-dashboard-infographic",
  "sourceComponentId": "filter-bar",
  "timestamp": "2026-09-02T10:00:00Z",       // ISO 8601, required
  "context": {"month": "2025-10"},           // action.event.context with all bindings RESOLVED
  "metadata": {"extensions": {"client_build": "1.4.2"}},   // optional
  "dataModel": {"filters": {"month": "2025-10"}}            // ONLY when createSurface.sendDataModel was true (or you want to push surface state)
}}

// Invoke an agent tool by name
{"version": "v1.0", "callAgentFunction": {
  "surfaceId": "flex-program-dashboard-infographic",
  "functionCallId": "fc-8d2e…",              // client-minted, unique
  "callFunction": {"call": "refresh_dashboard", "args": {"month": "2025-10"},
                   "catalogId": "https://parrot.dev/catalogs/v1"}   // ALWAYS send catalogId (see §11)
}}

// Reply to callRendererFunction
{"version": "v1.0", "rendererFunctionResponse": {"functionCallId": "…", "value": {"done": true}}}
{"version": "v1.0", "rendererFunctionResponse": {"functionCallId": "…", "error": {"code": "X", "message": "…"}}}

// Error — two shapes
{"version": "v1.0", "error": {"code": "UNALLOWED_PARENT", "surfaceId": "s-1", "path": "/components/3", "message": "…"}}  // VALIDATION_FAILED | UNALLOWED_PARENT | UNALLOWED_CHILD: surfaceId + path, no functionCallId
{"version": "v1.0", "error": {"code": "TIMEOUT", "functionCallId": "fc-9", "message": "…"}}                                // any other code: exactly ONE of surfaceId / functionCallId
```

Server-side effects of `action` (`runtime/dispatch.py`): if `userMessage` is present it becomes a visible user turn with that text; otherwise a system turn `{"type":"a2ui_action","action":{…envelope minus dataModel…}}`. `context` and `dataModel` never appear in the turn text. A supplied `dataModel` is persisted as the session's **surface state** (`SurfaceState{surface_id, catalog_id, data_model}`), capped at 1 MiB (`A2UI_MAX_DATA_MODEL_BYTES`), and later tools read it via `current_a2ui_surface_state()` — this is how `refresh_dashboard` picks up `dataModel.filters` (§6.4).

### 4.4 The `Component` object

```jsonc
{
  "id": "kpi-1",                    // required, unique within the surface
  "component": "KPICard",           // required, catalog type name
  "catalogId": "…",                 // optional per-component override
  "child": "other-id",              // single-child reference
  "children": ["a", "b"]            // OR a ChildTemplate: {"componentId": "row-tpl", "path": "/rows"}
  "weight": 2,                      // flex-grow; only valid as a direct child of Row/Column
  "accessibility": {"label": "…", "description": "…", "live": "off|polite|assertive", "hidden": false},
  "checks": [{"condition": {"call": "required", "args": {"value": {"path": "/form/email"}}}, "message": "Email is required."}],
  "action": {"event": {"name": "submit", "userMessage": "…", "context": {"email": {"path": "/form/email"}}}}
            // OR {"functionCall": {"call": "openUrl", "args": {"url": "https://…"}}} — exactly one of event/functionCall
  "metadata": {"extensions": {"parrot_variant": "kpi", "parrot_role": "value", "parrot_unit": "USD"}},
  // …all catalog props are TOP-LEVEL on this object (extra="allow")…
  "label": "Revenue", "value": {"path": "/payroll_hero/revenue_total"}
}
```

`metadata.extensions` keys must be UAX #31 identifiers; `a2ui_` is reserved; every parrot key is `parrot_*`. Keys actually emitted:

| Key | Emitted on | Values / meaning |
|---|---|---|
| `parrot_variant` | the root of every lowered Parrot composite | `chart`, `table`, `kpi`, `card`, `map`, `timeline`, `report`, `infographic`, `filter-bar` — **pick your wrapper component from this** |
| `parrot_role` | lowered `Text` / `Row` / `Column` nodes | `title`, `subtitle`, `caption`, `label`, `value`, `delta`, `axis`, `axis-label`, `trendline`, `series`, `series-list`, `header`, `column-header`, `row`, `rows`, `cell`, `description`, `layer`, `layer-summary`, `timestamp`, `event`, `event-title`, `event-description`, `heading`, `body`, `badge`, `footer`, `summary`, `filter`, `notice` (degradation placeholder) — **pick your typographic slot from this** |
| `parrot_unit`, `parrot_trend` | lowered KPICard texts | unit string; `up` / `down` / `flat` |
| `parrot_total_rows`, `parrot_truncated` | lowered DataTable | int; `true` |
| `parrot_series_data`, `parrot_layer_data` | lowered Chart / Map | the original `{"path": …}` binding, so a smarter renderer can still find the rows after lowering |
| `parrot_filter_column` | lowered FilterBar pickers | the data-model column the filter applies to |
| `parrot_component_id` | lowered DataTable | the pre-lowering id |
| `parrot_optional` | surface/component | list of pointers allowed to fail resolution (omit the prop instead of erroring) |
| `parrot_theme`, `parrot_layout` | **surface** `metadata.extensions` | design-system axes (§7.2) |

### 4.5 Dynamic values and data binding

Any dynamic prop position accepts one of three shapes. There is **no** `literalString` wrapper — a literal is the raw JSON value:

```jsonc
"Hello"                                                            // literal
{"path": "/user/name"}                                             // DataBinding — the ONLY key is "path"
{"call": "formatCurrency", "args": {"value": {"path": "/total"}, "currency": "USD"}}   // FunctionCall (+ optional catalogId)
```

Detection rule to copy (`baking.py:81-88`): a dict whose key set is exactly `{"path"}` is a binding; a dict containing `"call"` is a function call; anything else is a literal object.

**Path syntax is RFC 6901 JSON Pointer** (`^(?:/(?:[^/~\s]|~[01])*)*$`): `""` = whole document; `~0` → `~`, `~1` → `/`. Resolution walks tokens; on a list the token is an integer index; on an object a **missing key is an error** (not `undefined`) unless the pointer is listed in `parrot_optional`. A pointer **without** a leading `/` is **relative to the current template scope** (§4.6) — DataTable cells bind `{"path": "region"}`.

Typed unions from the schema: `DynamicString`, `DynamicNumber`, `DynamicBoolean`, `DynamicStringList` (string[] | binding | call), `DynamicValue` (any JSON, or binding/call; a plain object argument must not itself have a `path` or `call` key).

### 4.6 `ChildTemplate` — dynamic lists

```json
{"id": "rows", "component": "Column", "children": {"componentId": "row-tpl", "path": "/rows"}}
```

Renderer algorithm (`baking.py:261-353`):

1. Resolve `path`; it must be a list.
2. For each item `i`, **clone the entire subtree** rooted at `componentId` (not only that node), suffixing every id with `-<i>` and rewriting the clone's `child` / list-`children` references with the same suffix.
3. Inside a clone the scope path is `"<path>/<i>"`; relative pointers resolve against it; the system function `@index` (optional `offset` arg) returns `i`.
4. The template pattern component is **never rendered standalone**.
5. **Nested templates are not supported** — stop subtree collection at any nested `ChildTemplate`.

### 4.7 Catalog functions available inside bindings

Basic Catalog functions (`catalog/basic/functions.py`): validation `required`, `regex` (uses `re.search`), `length`, `numeric`, `email` → `{valid, code?, message?, severity: "error"|"warning"|"info"}`; formatting `formatString`, `formatNumber` (`decimals` default 0, `grouping` default true), `formatCurrency` (`USD $ / EUR € / GBP £ / JPY ¥`, else `"<CODE> "` prefix, `decimals` default 2), `formatDate` (`yyyy yy MMMM MMM MM dd EEEE E HH hh mm ss a`; accepts ISO or epoch), `pluralize` (`zero`/`one`/`other`); logic `and`, `or`, `not` (`values` min 2); side effect `openUrl` (`requiresUserActivation: true`); system `@index` (template scope only).

`formatString` grammar: `${/absolute/pointer}`, `${relative/pointer}`, `${fn(argName: value, other: 'literal')}` with **named** args, nested `${…}` allowed inside args, `\${` escapes a literal. Booleans stringify as `true`/`false`.

The Parrot catalog adds **agent functions**: every tool on the agent's `ToolManager`, exported by `GET …/a2ui/capabilities`-adjacent `export_functions()` as `{"<name>": {"type":"object","properties":{"call":{"const":"<name>"},"args":{…tool JSON-Schema…}},"returnType":"any","allowedCallers":"rendererOrAgent","requiresUserActivation":false}}`. Invoke them with `callAgentFunction`, never inline in a binding.

---

## 5. Component catalog

### 5.1 Basic Catalog — 18 primitives (`catalog/basic/spec/catalog.json`)

`weight: number` is available on all of them (valid only as a direct child of `Row`/`Column`). All `checks`-bearing inputs also accept `checks: CheckRule[]`.

| Type | Props (required in **bold**) | Enums / defaults | shadcn-svelte / navigator mapping |
|---|---|---|---|
| `Text` | **`text`**: DynamicString, `variant` | `variant ∈ caption, body` (default `body`). Simple Markdown, no HTML/links/images | `<p>` / `<span>`; pick heading styles from `parrot_role` (`title`, `heading`, `label`, `value`, …); run text through `markdownToHtml()` (DOMPurify) |
| `Image` | **`url`**, `description`, `fit`, `variant` | `fit ∈ contain, cover, fill (default), none, scaleDown`; `variant ∈ icon, avatar, smallFeature, mediumFeature (default), largeFeature, header` | `<img>`; `avatar` → `Avatar` |
| `Icon` | **`name`** | 57-name enum (`accountCircle, add, arrowBack, …, warning`) **or** `{"svgPath": …}` **or** a binding | `@iconify/svelte` with a name map (`mdi:*`) |
| `Video` | **`url`**, `posterUrl` | | `<video controls>` |
| `AudioPlayer` | **`url`**, `description` | | `<audio controls>` |
| `Row` | **`children`**: ChildList, `justify`, `align` | `justify ∈ center, end, spaceAround, spaceBetween, spaceEvenly, start (default), stretch`; `align ∈ start, center, end, stretch (default)` | `flex flex-row` + Tailwind justify/align map; if all children are `parrot_variant: kpi` cards → KPI grid (§7.3) |
| `Column` | **`children`**, `justify`, `align` | same enums | `flex flex-col` |
| `List` | **`children`**, `direction`, `align` | `direction ∈ vertical (default), horizontal` | `<ul>` / flex |
| `Card` | **`child`** (single id) | wrap multiples in a Column | `Card` + `CardContent`; variant styling from `parrot_variant` |
| `Tabs` | **`tabs`**: `[{title: DynamicString, child: id}]` (min 1) | | `AppTabs` / `AppTabItem` (bits-ui) — no shadcn `tabs` dir exists yet |
| `Modal` | **`trigger`**: id, **`content`**: id | | `AppDialog` with the trigger rendered inside a snippet |
| `Divider` | `axis` | `horizontal (default), vertical` | `Separator` |
| `Button` | **`child`**: id, **`action`**, `variant` | `variant ∈ default, primary, borderless` | `Button` (`variant: default→outline, primary→default, borderless→ghost`); on click → dispatch `action` (§8.6) |
| `TextField` | **`label`**, `value`: DynamicString, `placeholder`, `variant` | `variant ∈ shortText (default), longText, number, obscured` | `Input` / `Textarea` / `type=number` / `type=password`; write back to `dataModel` at the bound path |
| `CheckBox` | **`label`**, **`value`**: DynamicBoolean | | `Checkbox` + `Label` |
| `ChoicePicker` | `label`, **`options`**: `[{label, value}]`, **`value`**: DynamicStringList, `variant`, `displayStyle`, `filterable` | `variant ∈ mutuallyExclusive (default), multipleSelection`; `displayStyle ∈ checkbox (default), chips`; `filterable` default `false` | `Select` (single), `Command` + `Popover` + `Badge` chips (multi/filterable). **This is the multiselect** — there is no separate primitive. With `parrot_role: filter` it is a FilterBar control (§7.4) |
| `Slider` | `label`, `min` (default 0), **`max`**, **`value`**: DynamicNumber, `steps` (int ≥ 1) | | `Slider` |
| `DateTimeInput` | **`value`**: DynamicString (ISO 8601), `enableDate`, `enableTime`, `min`, `max`, `label` | both flags default `false` | `AppDatePicker` / `Calendar` |

### 5.2 Parrot presentation catalog — 9 composites (`catalog/parrot/*.py`)

All are display-only from the LLM's point of view (an LLM-origin envelope may never carry `action`, and may never inline rows — rows always arrive via a binding into `dataModel`). Each composite has a deterministic `lower()` to Basic primitives; the backend renderers **intercept** `Chart`, `DataTable`, `Infographic` (and FilterBar) before lowering and lower the rest. **Do the same**: render these natively, lower anything you do not support.

#### `Chart` (`chart.py`) — required `type`, `x`, `y`

| Prop | Type | Notes |
|---|---|---|
| `type` | `bar, horizontalBar, line, area, scatter, pie, donut, radar, map` | Same enum as the frontend's `chart-contract.ts` `ChartType` |
| `x` | string | category column |
| `y` | string[] | one or more value columns (multi-series) |
| `data` | `{"path": …}` | row set binding (structured outputs use `/rows`; recipes use `/<section>/series`) |
| `title`, `description`, `stacked`, `splitSeries`, `trendline`, `showLegend`, `xAxisMode` (`category`\|`time`), `xAxisLabel`, `yAxisLabel`, `palette` (hex[]), `colorBySign`, `negativeColor`, `positiveColor`, `mapName`, `dataVariable` | | all optional |

**There is no ECharts option on the wire.** `Chart` is the same declarative config the frontend already renders through `AppChart.svelte` (`AppChartConfig`) — map `Chart` props 1:1 onto `AppChartConfig` and feed it the bound rows. The lowered fallback is `Card{Column[Text title, Text "Chart (<type>)", axis texts, series list]}` with `parrot_series_data` preserving the binding.

#### `DataTable` (`datatable.py`) — required `columns`

`columns: [{name, type, title, format?}]` with `type ∈ string, integer, number, boolean, date, datetime, time, duration, any` and `format ∈ currency, percent, email, uri, enum, id, code`; `data: {"path": …}`; `totalRows`, `truncated` (rows are capped at 1000 in structured outputs — the full set is in the chat response `data`), `explanation`, `title`. Lowering produces the row-template pattern (header `Row` of `column-header` texts + a `Column` whose `children` is a `ChildTemplate` over the rows, cells binding column-relative). Render natively with `DataTable.svelte` (or a new shadcn data-table — none exists in the frontend yet). Mirror the FEAT-493 rich table: numeric alignment + `tabular-nums` for `integer`/`number`, `currency`/`percent` formatting, sticky header, "showing N of M" when `truncated`, and search + pagination only above 100 rows.

#### `Map` (`map.py`) — required `layers`

`layers: [{layer (source id), columns: [{name,type,title,format?}], data: {"path": "/layers/<i>/features"}, dataShape: geojson (default) | rows, tooltipTemplate (str.format_map over feature.properties), labelField, markerColor, geodesic, totalCount, capped}]`, `viewport: {bbox?: [minLng,minLat,maxLng,maxLat], center?: [lat,lng], zoom?}`, `query: {point: [lat,lng], radius, unit: mi|km|m}`, `baseLayer` (tile URL or style id), `title`, `description`, `explanation`. **No Folium/Leaflet payload on the wire** — render with the frontend's Leaflet (`StructuredMap.svelte` already consumes the same `StructuredMapConfig` shape). Lowered fallback: titled per-layer summary.

#### `KPICard` (`kpicard.py`) — required `label`, `value`

`label`, `value` (number | string | binding), `unit`, `delta` (number | string | binding), `trend ∈ up, down, flat`. Lowering: `Card{Column[Text label, Text value(+parrot_unit), Text delta|trend(+parrot_trend)]}`, `parrot_variant: kpi`. On the un-lowered wire `value` is the raw number; on the lowered tree it is stringified. Map onto the existing `HeroCardBlock` / `InfographicHeroCardBlock` design (`{label, value, icon?, trend?, trend_value?}`).

#### `InfoCard` (`infocard.py`) — required `title`

`title`, `subtitle`, `body`, `image` (URL or binding), `badge`, `footer`. Lowering order `image, title, subtitle, badge, body, footer`, `parrot_variant: card`. → shadcn `Card` + `Badge`.

#### `Timeline` (`timeline.py`) — required `events`

`title`, `events: [{timestamp?, title, description?}]`. Events are never re-sorted. `parrot_variant: timeline`.

#### `Report` (`report.py`) and `Infographic` (`infographic.py`) — required `title`, `sections`

`allowed_parents = ["root", "Column"]`. `sections: [{heading?, text?, components?: [{component, properties}]}]` (+ `subtitle`, `theme` on Infographic; `reportMetadata`, `summary` on Report). **Inside `sections[].components[]` the descriptor shape is `{"component": name, "properties": {...}}`** — the authored-descriptor form, unique to these two composites. Nested descriptors may name a Parrot composite (lowered through its own `lower()`) or a Basic primitive (props pass through; nested `child`/`children`/`tabs` lowered recursively).

Lowering: `Card{Column[Text title (parrot_role: title), Text subtitle?, Tabs | Column, Text summary?]}` — **more than one section ⇒ a `Tabs` node, one tab per section (`title = heading or "Section N"`); exactly one section ⇒ an inline `Column`.** Each section lowers to `Column[Text heading (parrot_role: heading), Text body?, …components]`. `parrot_variant: infographic` / `report`. **This is how multi-tab dashboards work** — the Flex dashboard's five sections become five tabs. Render `Infographic` natively as a page: title bar, tab strip (`AppTabs`), and one section per pane; `Infographic.theme` is a palette hint (§7.2).

#### `FilterBar` (`filterbar.py`, FEAT-493) — required `filters`

```json
{"id": "filters", "component": "FilterBar", "title": "Filters",
 "filters": [{"column": "region", "label": "Region", "multiple": true,
              "options": [{"label": "West", "value": "West"}, {"label": "East", "value": "East"}]}]}
```

Lowers to `Row{parrot_variant: "filter-bar"}` of `ChoicePicker`s (`id = "<bar-id>-f<i>"`, `variant = multipleSelection | mutuallyExclusive`, `value = [only option]` when exactly one option else `[]` meaning "all"), each tagged `parrot_role: "filter"` + `parrot_filter_column`. Display-only on the wire; the **client-side filtering contract** is in §7.4.

#### Forms — composed, not a component

`build_form()` (`catalog/parrot/form.py`) emits a flat fragment: a root `Column` (id = prefix), title, one Basic input per field (`text→TextField shortText`, `textarea→longText`, `number→number`, `select→ChoicePicker`, `checkbox→CheckBox`, `date→DateTimeInput enableDate`), each binding `value: {"path": "/<prefix>/<name>"}` and, when required, `checks: [{condition: {call: "required", …}, message}]`, then a submit `Button` whose `action.event.context` maps field names to those bindings. Nothing special to implement: it is just primitives + one action.

### 5.3 Renderer capabilities contract to mirror

Core defines `RendererCapabilities{interactive, supports_actions, supports_updates, output, supported_catalog_ids, supported_components}` (`outputs/a2ui/renderers/__init__.py`). The backend renderers registered today:

| id | interactive | actions | updates | output | supported components |
|---|---|---|---|---|---|
| `interactive-html` | ✓ | ✗ | ✗ | `text/html` | 18 Basic + `Chart`, `DataTable`, `Infographic` (+ FilterBar handled via lowering) |
| `ssr_html` | ✗ | ✗ | ✗ | `text/html` | 18 Basic |
| `pdf` | ✗ | ✗ | ✗ | `application/pdf` | SSR minus `Video`, `AudioPlayer` |
| `echarts` | ✗ | ✗ | ✗ | `application/json` | `Chart` |
| `folium_map` | ✗ | ✗ | ✗ | `text/html` | `Map` |
| `adaptive_cards` | ✗ | ✓ | ✗ | Adaptive Cards | Text, Image, Row, Column, Card, TextField, CheckBox, ChoicePicker, Slider, DateTimeInput, Button |

The Svelte renderer will be the first one with `interactive: true, supports_actions: true, supports_updates: true, output: "live"`. Rule inherited from `renderers/degrade.py`: **never throw on an unsupported component** — render a visible notice `Text` (`"[<Component> not supported here: <reason>]"`, `parrot_role: notice`) that **keeps the original id** so references still resolve, and collect `{id, component, reason}` records (`degraded[]`) for telemetry.

---

## 6. Dashboards, infographics and widgets

### 6.1 How each kind is produced

| Kind | Produced by | Root component | Typical `surfaceId` | Rows |
|---|---|---|---|---|
| **Widget** | a structured-output turn (`structured_chart` / `_table` / `_map`, dual-emitted as A2UI) or a `KPICard` builder | `Chart`, `DataTable`, `Map`, `KPICard` | `structured_chart-<8hex>`, `chart`, `kpi` | `dataModel.rows` (cap 1000) or `dataModel.layers[i].features` |
| **Infographic** | an LLM-authored `Infographic` surface (`InfographicToolkit`, producer loop with catalog validation and up to 3 attempts) | `Infographic` | `infographic-<12hex>` | `dataModel.charts.<id>`, `dataModel.tables.<id>` |
| **Dashboard** | a **recipe** (`InfographicRecipe`, deterministic: datasets → transforms → `LayoutSpec` → envelope), replayed by `RecipeRunner` or the `refresh_dashboard` agent function | `Infographic` (multi-section → `Tabs`) | `<recipe-name>-infographic` | `dataModel.<section>/…` as declared by the layout bindings |

All three ride the **same `createSurface` message**. Persisting to the ui_surfaces plane is where the kind becomes explicit (`kind` in `PublishSurfaceRequest`).

### 6.2 Frontend heuristic for the kind of an incoming envelope

Because there is no `kind` on the wire, derive it when you receive `a2ui_envelope` from a chat turn:

```ts
function inferKind(surface: CreateSurface): SurfaceKind {
  const root = surface.components.find(c => c.id === "root");
  if (!root) return "widget";
  if (root.component === "Infographic" || root.component === "Report") {
    const sections = (root as any).sections?.length ?? 0;
    return sections > 1 || surface.surfaceId.endsWith("-infographic") ? "dashboard" : "infographic";
  }
  return "widget";   // Chart | DataTable | Map | KPICard | InfoCard | Timeline | any single primitive
}
```

Refine with context you already have: the skill trigger the user typed (`/widget` → widget, `/infographic` → infographic), and `metadata.kind` when the surface came back from `GET /api/v1/ui/surfaces/{id}` (authoritative). Store the kind you decided on when you pin the surface so the backend record carries it from then on.

### 6.3 Request recipes (what to send per kind)

| Goal | Request | Where the surface is |
|---|---|---|
| Widget | `POST /api/v1/agents/chat/flex_dashboard` `{"query": "/widget worked hours by month", "session_id": "…", "output_mode": "a2ui"}` — or omit `output_mode` and let the agent's embedding router pick `structured_chart` / `_table` / `_map` from phrasing | `a2ui_envelope` (and `artifacts[0].definition`) |
| Infographic | `{"query": "/infographic summarize this month's payroll picture", "session_id": "…", "output_mode": "a2ui"}` | `a2ui_envelope`; prose caption in `output` |
| Dashboard (first open) | Do **not** ask conversationally. Either list pinned dashboards (`GET /api/v1/ui/surfaces?kind=dashboard`) and open one, or (backend-published) run the recipe and pin the result; or ask the agent `refresh the dashboard for October 2025`, which calls `refresh_dashboard` and returns a fresh surface | `GET /api/v1/ui/surfaces/{id}` `envelope` |
| Dashboard (filter change) | `POST /api/v1/agents/flex_dashboard/a2ui?session_id=…` with an `action` carrying `dataModel.filters`, then a `callAgentFunction` `refresh_dashboard` — **or**, for a pinned refreshable surface, `POST /api/v1/ui/surfaces/{id}/refresh {"params": {"month": "2025-10"}}` (simpler, and it returns the surface directly) | response of the refresh call |

### 6.4 FlexDashboard specifics (FEAT-491)

**Datasets** (six lazy `QuerySlugSource`s registered with `add_query`, never eagerly fetched): `msl` → `flex_msl_brian_bi`, `finance` → `Finance_results_bi`, `hours` → `flex_hours_query_pbi`, `employees` → `flex_empolyees_brian_bi` (the typo is real), `region_utilization` → `fm_regions_avg_employees_html`, `rep_utilization` → `fm_rep_utilization`.

**Skills / triggers** (`agents/flex_dashboard/skills/`): `/widget <kpi name> [filters]` and `/infographic <ask>`. The widget skill maps KPIs to shapes: month-series KPIs → `Chart` line (`x: "month"`); Pay Code and Rep Utilization → `DataTable`; Proximity Staffing → `Map` (store + employee layers, defaults `radius_miles=50`, `nearest_n=3`); hero totals (Worked Hours, Payroll, P&L Revenue, Payroll % to Revenue) → one `KPICard` each. Hard rules: never invent numbers, never widen a KPI's own filter scope, always state applied filters.

**Example prompts**: `/widget worked hours by month` · `/widget proximity staffing radius_miles=25 nearest_n=5` · `/widget payroll % to revenue` · `/widget pay code hours for month 2025-10` · `/widget rep utilization by region, category=Merch` · `/infographic an infographic of this month's payroll picture` · `refresh the dashboard for October 2025` · `how is Rep Utilization computed?`

**KPI definitions** (put them in tooltips): Payroll % to Revenue = `sum(Payroll) / sum(Revenue)` (denominator is Revenue alone); Worked Hours = `sum(hours)` from `hours`; Rep Utilization = `employees_worked / average_active` per region/category/month; Proximity Staffing = per-store nearest-N employees by haversine distance within a radius.

**The dashboard recipe `flex-program-dashboard`** — params (all strings; `""` means unset): `month`, `flex_type`, `pay_code`, `cost_center`, `category`, `radius_miles` (default `"50"`), `nearest_n` (default `"3"`). Layout: `Infographic` titled "Flex Program Dashboard" with five sections → **five tabs**:

| Tab | Components | Bindings |
|---|---|---|
| Payroll Contribution — Hero | 4 × `KPICard` (Worked Hours, Payroll, P&L Revenue, Payroll % to Revenue) | `/payroll_hero/{worked_hours_total,payroll_total,revenue_total,payroll_pct}` |
| Payroll Contribution — Month Series | 4 × `Chart` line, `x: "month"` | `/{worked_hours,payroll,revenue,payroll_pct}_by_month/series` |
| Pay Code | 2 × `DataTable` (`[pay_code, hours]`, `[pay_code, hours, share_pct]`) | `/pay_code_hours/records`, `/pay_code_allocation/records` |
| Rep Utilization | 1 × `DataTable` (`[region, category, month, utilization, cross_check_utilization]`) | `/rep_utilization_by_region/records` |
| Proximity Staffing | 1 × `Map` (layers `stores` `#1f77b4`, `employees` `#ff7f0e`, `dataShape: rows`) + 1 × `DataTable` (`[store_name, nearest_employees, employees_within_radius]`) | `/proximity_staffing/{store_layer,employee_layer,coverage}` |

The narrative section declared by the recipe **never reaches the envelope** (a known core bug, §11) — do not expect prose in the dashboard.

**`refresh_dashboard` agent function** (`RefreshDashboardTool`, registered only when the backend calls `agent.build_refresh_tool(pctx)`): args `month`, `flex_type`, `pay_code`, `cost_center`, `category`, `radius_miles`, `nearest_n` (all optional). Filter precedence: explicit args → surface state `dataModel.filters` (pushed by a prior `action`) → recipe defaults. It returns `{"filters": {...}, "filter_source": "args"|"surface_state"|"defaults", "artifact_id": "…", "bytes": N}` — **an artifact reference, not an envelope**. After calling it, re-fetch the surface (`GET /api/v1/ui/surfaces/{id}`) or prefer the ui_surfaces `refresh` route, which returns the surface in one round trip.

**Function discovery**: `GET /api/v1/agents/flex_dashboard/a2ui/capabilities` returns the catalogs; the per-agent function map is the same document published on the A2A Agent Card. Every tool on the agent is renderer-invocable unless marked `a2ui_hidden`; `requiresUserActivation` is a renderer-enforced hint only.

---

## 7. The interactive HTML lane (FEAT-493)

### 7.1 What you receive

`GET /api/v1/ui/surfaces/{id}?format=html` (or the `/a2ui/surfaces/{id}` mirror) renders the stored envelope with `InteractiveHTMLRenderer` and returns **one self-contained HTML document**:

- No external references at all — no `<script src>`, no `<link>`, no `@import`, no CDN, no fonts (asserted by `test_interactive_html.py`). Chart.js 4.5.1 UMD (~200 KB) is inlined. The design-system CSS is inlined. Safe to open in a new tab from a `blob:` URL or to `srcdoc` into an iframe.
- Body wrapped in `<div class="ds-page" data-layout="<layout>" data-theme="<theme>">`; `<meta name="viewport">` present.
- The data model is embedded as `<script type="application/json" id="report-data">…</script>` and the vanilla-JS runtime drives: charts (`[data-chart-config]` on a `<canvas>`), chart day-tabs and metric toggles, sortable tables (`[data-sort-table]`, raw values in `td[data-v]`), table search + pager (`[data-table-search]`, `[data-table-pager]`, only above 100 rows), generic tabs (`[data-tabs]` / `[data-tabs-panes]`), and the **FilterBar runtime** (`[data-filterbar]`, `[data-filter-column]`, `[data-msf-toggle]`, `[data-msf-search]`, `[data-act="all"|"none"]`, `[data-filter-reset]`, `[data-filter-chips]`, `[data-filter-summary]`).
- The response has **no `charset` parameter and no CSP headers** on this route (see §11) — when you inject it via `srcdoc`, the document's own `<meta charset="utf-8">` applies; when you open it via `blob:` URL, create the Blob with `{type: "text/html;charset=utf-8"}`.

The same renderer produces the artifact for `POST /api/v1/infographic_recipes/{name}/run` and for `refresh_dashboard`; those return artifact **metadata**, and the HTML itself is fetched through the artifacts API (`GET /api/v1/threads/{session_id}/artifacts/{artifact_id}?format=html`) or a signed public URL.

### 7.2 Theme and layout — two orthogonal axes

| Axis | Values | Controls |
|---|---|---|
| `theme` | `light` (default), `dark`, `corporate`, `midnight`, `petrol` | Palette: `ThemeConfig.to_css_variables()` → `:root { --primary, --surface-bg, --content-width, --radius, --density, --shadow, --mono-family, --panel-bg, --panel-border, --header-bg, --header-text, … }` |
| `layout` | `analytics` (default), `report`, `print` | Density/structure: page width, sticky table headers, KPI grid density, print page rules. `report` reproduces the pre-FEAT-493 infographic look; `print` is forced by the PDF renderer |

Resolution precedence (`DesignSystem.resolve`, highest first): **1.** `createSurface.metadata.extensions.parrot_theme` / `parrot_layout` → **2.** the top-level `Infographic` component's `theme` prop (theme axis only) → **3.** the renderer's constructor kwargs (what `RenderSpec.theme` / `RenderSpec.layout` on a recipe set) → **4.** class defaults. Unknown names never raise: they are logged and fall through.

**How the frontend selects them**: there is no query parameter on the surfaces routes. Set `metadata.extensions.parrot_theme` / `parrot_layout` on the envelope **before pinning** (or when re-pinning), e.g. map the app's active theme (`themeStore`) to `dark`/`light`. For a Svelte-rendered surface the same two keys are the hint your renderer should honour (map them onto the app's semantic tokens rather than hardcoding palettes).

### 7.3 Semantic classes the HTML emits (mirror them in Svelte)

`_semantics.py` maps the lowered tree onto stable class names: `a2ui-card-<variant>` from `parrot_variant`; `a2ui-text a2ui-<role>` from `parrot_role`; a `Row` whose children are all `parrot_variant: kpi` cards becomes a **`kpi-grid`**, and each KPI card emits `kpi-card` / `kpi-label` / `kpi-value` / `kpi-unit` plus `data-trend="up|down|flat"`; rich tables emit `td.num[data-v]`, `tr.total-row`, `tr.group-row`. Reusing this vocabulary as Tailwind component classes in the Svelte renderer keeps both lanes visually aligned.

### 7.4 Client-side filtering contract (FilterBar, TASK-2716)

What the backend runtime does — and what the Svelte renderer must do identically:

1. Filtering operates on the **already-embedded `dataModel`** — no fetch, no server round trip. (Server-side refresh with new params is FEAT-491's `refresh_dashboard` lane; keep them separate in the UI: "Filter" is instant and local, "Refresh" re-runs the recipe.)
2. Vocabulary: a `Row` with `parrot_variant: "filter-bar"`; each child `ChoicePicker` with `parrot_role: "filter"` and `parrot_filter_column`. `value: []` means "all".
3. **Scoping rule**: a filter applies **only** to charts/tables whose bound rows actually contain that column. A section without the column is left completely untouched — never blanked, never zeroed. Derive this from the data, not from a hardcoded map.
4. Re-render affected charts from the filtered rows; re-emit affected table bodies with **identical cell formatting** to the unfiltered render (the backend only shows/hides `tr[data-row]` and re-filters each chart's original embedded rows).
5. A filter that excludes every row shows an explicit "no rows match" state.
6. UI: searchable multiselect per filter, select-all / clear, selection chips, a global reset, and a summary line reflecting the current selection (`all` for unconstrained filters).
7. Out of scope by decision: URL / localStorage persistence of filter state, cross-surface filter state.
8. On non-interactive surfaces (SSR, PDF) the bar degrades to a static summary line + a `degradation_record`, never a dead control.

---

## 8. Frontend design: AgentDashboard service + Svelte renderer

This section maps the backend contract onto the current `navigator-frontend-next` architecture (branch `dev`, package `parrot-ui`: Svelte 5 runes, SvelteKit 2, Tailwind v4 CSS-first, shadcn vendored at `src/lib/ui/internal/shadcn/ui/`, public barrel `$lib/ui/components`). Today there is **no A2UI code in the frontend** — the closest precedents are the infographic block renderer (`src/lib/components/agents/canvas/infographic/`: a discriminated-union types file + a `Map<type, Component>` registry + one component per block) and the interactive-artifact iframe canvas.

### 8.1 Service registration

Services are `Submodule` entries in `src/lib/data/manual-data.ts` rendered by `src/routes/program/[slug]/[module]/[submodule]/+page.svelte` through `import.meta.glob("/src/lib/components/**/*.svelte")`. Register the new service as:

```ts
{ id: "sub-flex-agent-dashboard", slug: "agent-dashboard", name: "Flex Dashboard", icon: "mdi:view-dashboard-variant",
  type: "component", path: "modules/AgentDashboard/AgentDashboardService.svelte",
  parameters: { agent_id: "flex_dashboard", chatbotId: "<uuid>" }, order: 2 }
```

`normalizeComponentParameters` delivers `agent_id` as both `agent_id` and `agentId`. Avoid the name `AgentDashboard.svelte` — three components already carry it (`agents/`, `modules/Operations/`, `modules/Finance/`), all of which degrade responses to text/html/markdown and have nothing to do with A2UI.

### 8.2 Component tree

```
src/lib/components/modules/AgentDashboard/
├── AgentDashboardService.svelte      # page: AgentChat-derived chat pane + surface list sidebar (pinned dashboards/widgets)
├── agent-dashboard.variants.ts       # tv() recipes bound to --agent-dashboard-* slots (copy agent-chat.variants.ts)
├── SurfaceMessageCard.svelte         # the chat bubble for an A2UI turn: caption + kind badge + the TWO buttons (§8.3)
├── SurfaceViewer.svelte              # renders a CreateSurface inline (widgets) — wraps the renderer
└── surfaces.svelte.ts                # runes store: pinned surfaces, active surface, filter state

src/lib/components/agents/canvas/a2ui/
├── A2uiCanvas.svelte                 # CanvasTab type "a2ui": full-size dashboard/infographic view
├── a2ui-registry.ts                  # Map<componentName, Component> + registerA2uiComponent()
├── a2ui-engine.svelte.ts             # class A2uiSurface: components index, dataModel ($state), resolve(), applyUpdate(), expandTemplates()
├── a2ui-functions.ts                 # the 14 Basic Catalog functions + @index
└── components/                       # one Svelte component per catalog type (Basic + Parrot)
    ├── basic/{Text,Image,Icon,Video,AudioPlayer,Row,Column,List,Card,Tabs,Modal,Divider,Button,TextField,CheckBox,ChoicePicker,Slider,DateTimeInput}.svelte
    ├── parrot/{Chart,DataTable,Map,KPICard,InfoCard,Timeline,Report,Infographic,FilterBar}.svelte
    └── Degraded.svelte               # visible notice, keeps the original id

src/lib/api/a2ui.ts                   # A2UIHandler + ui_surfaces clients (§8.5)
src/lib/types/a2ui.ts                 # wire types (§9)
```

Wire into the existing chat machinery exactly as `sdd/specs/interactive-artifacts-chat.spec.md` §2 prescribes for a new canvas type:

1. `ChatInput.svelte` output-mode list: add `{ value: "a2ui", label: "Dashboard" }`. In `AgentChat.svelte` the `internalFormatKwargs` computation forces `{output_format:"html", html_mode:"complete", table_mode:"grid"}` for every non-default mode except `interactive` — add `a2ui` to that exclusion (or pass `formatKwargs` from the parent; caller-supplied keys win).
2. `AgentMessage` (`src/lib/types/agent.ts`): add `a2ui_envelope?: A2uiEnvelope | A2uiEnvelope[]` and `artifacts?: AgentArtifact[]`; widen `AgentChatResponse.output_mode` with `"a2ui"`.
3. `canvas-tab-manager.svelte.ts`: extend `CanvasTabType` with `"a2ui"`; `canvas-registry.ts`: `registry.set("a2ui", A2uiCanvas)`.
4. `AgentChat.svelte`: add `maybeOpenA2uiCanvas(message)` next to `maybeOpenInfographicCanvas` / `maybeOpenInteractiveArtifactCanvas` and call it in **all three** response-assembly sites (streaming ≈ line 975, non-streaming ≈ 1290, retry ≈ 1475) — today the two existing hooks only run on the non-streaming path. For widgets, do not open the canvas: render inline in the bubble (§8.3).
5. `ChatBubble.svelte`: a new branch `output_mode === "a2ui" || message.a2ui_envelope` that renders `SurfaceMessageCard`.

If `AgentDashboardService` embeds `AgentChat` (like `UserAgentChatPane` does) the steps above are the whole integration. If it re-implements the chat loop, reuse `streamChatWithAgent` / `chatWithAgent` from `$lib/api` unchanged: the A2UI envelope rides the same response.

### 8.3 The two-buttons flow

When a response carries `a2ui_envelope` (dict or list — normalize to a list and take each `createSurface`):

```
SurfaceMessageCard
┌─────────────────────────────────────────────────────────────┐
│ [kind badge]  caption (message.output / response)           │
│ ┌───────────────────────────────────────────────────────┐   │
│ │ inline SurfaceViewer  — ONLY when kind === "widget"   │   │
│ └───────────────────────────────────────────────────────┘   │
│  [ Open dashboard ]   [ Open interactive HTML ]   [ Pin ]   │
└─────────────────────────────────────────────────────────────┘
```

**Button 1 — internal renderer.** `kind === "widget"` → the surface is already inline; the button toggles a maximized dialog. `kind === "dashboard" | "infographic"` → open in a **new tab**: `window.open(`/program/${program}/${module}/agent-dashboard/surface/${localId}`, "_blank", "noopener")` where the target route (`src/routes/program/[slug]/[module]/agent-dashboard/surface/[id]/+page.svelte`, or an `embed`-style `+layout@.svelte` reset route) loads the envelope. Because a new tab has no in-memory state, the surface must be reachable by id: either **pin it first** (`POST /api/v1/ui/surfaces` → `surface_id`; the new tab does `GET /api/v1/ui/surfaces/{surface_id}` and renders `envelope`) or stash the envelope in `sessionStorage`/IndexedDB (`ChatService` already persists messages) under a local id and fall back to the pinned id when present. Pinning is the recommended default: it makes the dashboard bookmarkable, shareable and refreshable for free. Set `metadata.extensions.parrot_theme`/`parrot_layout` from the app theme before pinning.

**Button 2 — interactive HTML in a new browser tab.** Requires the pinned `surface_id`. Fetch `GET /api/v1/ui/surfaces/{surface_id}?format=html` with the bearer header (a plain `<a target=_blank>` to the API cannot carry the `Authorization` header unless cookie auth is active), then:

```ts
const html = await res.text();
const url = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
const tab = window.open(url, "_blank", "noopener");
setTimeout(() => URL.revokeObjectURL(url), 60_000);
```

`window.open` must be called synchronously inside the click handler to survive popup blockers: open a blank tab first (`const tab = window.open("", "_blank")`), then set `tab.location = url` after the fetch resolves (the `InfographicCanvas.handleSave` / `handlePrint` code already uses this pattern). When cookie auth is active (`apiWithCredentials`), a direct `window.open(\`${config.apiBaseUrl}/api/v1/ui/surfaces/${id}?format=html\`)` also works. For an in-app preview instead of a tab, reuse the `InteractiveArtifactCanvas` iframe recipe: `srcdoc`, `sandbox="allow-scripts allow-forms allow-modals allow-popups"` (no `allow-same-origin`), `referrerpolicy="no-referrer"`.

**Pin** is what makes both buttons durable: `POST /api/v1/ui/surfaces {kind, title, envelope: surface, agent_id, session_id, recipe_name?, recipe_params?}` → store `surface_id` on the message (`ChatService.saveMessage`). Auto-pin dashboards on arrival; make it explicit for widgets.

### 8.4 The renderer engine (`a2ui-engine.svelte.ts`)

```ts
export class A2uiSurface {
  surfaceId: string;
  catalogId: string;
  components = $state.raw<Map<string, A2uiComponent>>(new Map());
  dataModel = $state<Record<string, unknown>>({});
  sendDataModel = false;
  degraded: DegradationRecord[] = [];

  constructor(cs: CreateSurface) { /* index by id, assert root exists, snapshot dataModel */ }
  resolve<T>(value: Dynamic<T>, scope?: string): T          // literal | {path} | {call} — §4.5 detection rule; relative pointer → scope
  applyUpdate(msg: UpdateDataModel | UpdateComponents)      // pointer set/delete; component upsert
  children(node): A2uiComponent[]                           // static list, or ChildTemplate expansion per §4.6 (clone subtree, suffix ids, set scope)
  dispatchAction(node, event: EventAction): ActionMessage   // resolve context/userMessage, attach dataModel if sendDataModel
}
```

Design rules:

- **`$state.raw` for the component map, `$state` for the data model.** Components are replaced wholesale on `updateComponents`; the data model is mutated at pointers and Svelte's deep reactivity re-renders exactly the bound components.
- **Resolve at render time**, not at load time (a live renderer must not bake). Cache pointer lookups per render pass if profiling shows the need.
- **Intercept `Chart`, `DataTable`, `Map`, `KPICard`, `Infographic`, `Report`, `FilterBar`** and render natively; for `InfoCard` and `Timeline` either native or lowered — both are cheap. Unknown component or unknown catalog → `Degraded.svelte` with the original id, and push `{id, component, reason}` to `degraded`.
- **Recursion is by id**: `<A2uiNode {surface} id="root" />` looks up the component, picks the Svelte component from the registry, and passes `surface`, `node`, `scope`. Children render through the same `A2uiNode`, so `Row`/`Column`/`Card`/`Tabs` never import concrete leaf components.
- **Infographic sections use the `{component, properties}` descriptor shape**, not the wire shape: when rendering `Infographic.sections[i].components[j]`, spread `properties` onto a synthetic node with a deterministic id (`${root.id}-s${i}-c${j}`) before handing it to the registry.
- **Chart / Map / DataTable feed existing components**: `Chart` → `AppChart.svelte` with an `AppChartConfig` built from the props and `rows = resolve(data)`; `Map` → `StructuredMap.svelte`; `DataTable` → `DataTable.svelte` (or a shadcn data-table) with `columns` from the typed column list. Lazy-import these exactly like `ChatBubble.svelte` does so the global FloatingChat does not pull ECharts/Leaflet.
- **Inputs write back**: `TextField`, `CheckBox`, `ChoicePicker`, `Slider`, `DateTimeInput` bind to `dataModel` at their `value.path` (two-way through `resolve` + a `setAtPointer`). That is what makes `Button.action.event.context` bindings and `checks` work.
- **Checks**: evaluate `checks[]` on change; render the `ValidationResult.message` (fallback `CheckRule.message`) under the input; `severity` maps onto `Alert` variants.
- **Theme**: read `metadata.extensions.parrot_theme` as a hint only; the renderer uses the app's semantic tokens (`--card`, `--muted`, `--primary`, …). Introduce `--agent-dashboard-*` slots only if needed, and if you do, add them to `src/lib/styles/themes/_schema.css` **and all four theme files** or `pnpm check` fails.
- **Markdown in `Text`**: `markdownToHtml(text)` — it already sanitizes with DOMPurify. Never `{@html}` unsanitized wire text.

### 8.5 API client (`src/lib/api/a2ui.ts`)

```ts
const A2UI = (agent: string) => `/api/v1/agents/${agent}/a2ui`;
const SURFACES = "/api/v1/ui/surfaces";

export const a2uiApi = {
  capabilities: (agent) => http.get(`${A2UI(agent)}/capabilities`),
  send: (agent, sessionId, envelopes: RendererMessage[]) =>
    http.post(A2UI(agent), envelopes.length === 1 ? envelopes[0] : envelopes, { params: { session_id: sessionId } }),
  //   → one AgentMessage (Content-Type application/a2ui+json) or {messages: AgentMessage[]}; 400 carries an error envelope
  stream: (agent, sessionId, onMessage, signal) => sseReader(`${config.apiBaseUrl}${A2UI(agent)}?session_id=${sessionId}`, getAuthHeaders(), onMessage, signal),
  //   fetch-based SSE reader: split on "\n\n", ignore lines starting with ":", JSON.parse after "data: "

  listSurfaces: (kind?) => http.get(SURFACES, { params: kind ? { kind } : {} }),
  getSurface:   (id, share?) => http.get(`${SURFACES}/${id}`, { params: { format: "json", ...(share && { share }) } }),
  getSurfaceHtml: (id, share?) => fetch(`${config.apiBaseUrl}${SURFACES}/${id}?format=html${share ? `&share=${share}` : ""}`, { headers: getAuthHeaders() }).then(r => r.text()),
  pin:     (body: PublishSurfaceRequest) => http.post(SURFACES, body),          // 201 {surface_id}
  refresh: (id, params, share?) => http.post(`${SURFACES}/${id}/refresh`, { params }, { params: share ? { share } : {} }),
  share:   (id, opts: { expires_at?: string; ttl?: boolean }) => http.post(`${SURFACES}/${id}/share`, opts),
  revoke:  (id, token) => http.delete(`${SURFACES}/${id}/share/${token}`),
  remove:  (id) => http.delete(`${SURFACES}/${id}`),
};
```

Use the shared Axios singleton (`$lib/api/http.ts`) so the bearer interceptor and the `ApiError` mapping apply; use raw `fetch` only for the SSE stream and the HTML body. Remember that a **`401` that does not mention "policy" clears the token and redirects to `/login`** in the interceptor.

### 8.6 Actions and agent functions from the renderer

- A `Button` (or any component) with `action.event` → `surface.dispatchAction(node, event)` builds the `action` envelope (§4.3) and posts it via `a2uiApi.send`. The response may contain a new `createSurface` (the agent answered the turn with a surface) — treat it like a chat response: render it in place or as a new message.
- `action.functionCall` with `call: "openUrl"` → `window.open(args.url, "_blank", "noopener")`; any other Basic function → evaluate locally; a Parrot/agent function → `callAgentFunction` with **`catalogId` always set** to the surface catalog.
- `callAgentFunction` responses: `agentFunctionResponse.value` (JSON-safe) or an `error` envelope. For `refresh_dashboard` the value is an artifact reference — follow up with `getSurface` / `refresh` to obtain the new envelope.
- Keep one SSE connection per `(agent, session)` while a surface is mounted; on `callRendererFunction` evaluate the named function (Basic functions, or your own renderer functions) and answer with `rendererFunctionResponse` echoing `functionCallId`.
- Surface state: before calling `refresh_dashboard` with no explicit args, push the current filters with an `action` whose `dataModel` is `{filters: {...}}` so the tool reports `filter_source: "surface_state"`.

### 8.7 Pinned-surfaces sidebar and sharing

`GET /api/v1/ui/surfaces?kind=dashboard` for the sidebar (`access: owner|shared`, `refreshable`, `updated_at`); refresh button only when `refreshable`; share dialog → `POST …/share` → copy `${appUrl}/…/surface/${surface_id}?share=${token}` (the target page forwards `?share=` to `getSurface`/`getSurfaceHtml`); revoke via `DELETE …/share/{token}`. A `410` on open means the share was revoked or expired; `404` means unknown or not yours.

### 8.8 Testing

Vitest (`src/**/*.test.ts`, jsdom for component tests). Unit-test the engine against the fixtures in §10: pointer resolution (absolute, relative, `~0`/`~1`, missing key → error unless `parrot_optional`), `ChildTemplate` expansion (id suffixing, `@index`), `updateDataModel` delete-on-null, `formatString` grammar, the FilterBar scoping rule (a section without the column stays untouched), and the `error` envelope shapes. Component-test `KPICard`, `Chart` (config mapping only), `DataTable` (typed formatting), `Infographic` (sections → tabs). Run `pnpm check`, `pnpm test`, `pnpm build`, `prettier --write .` before committing.

---

## 9. TypeScript wire types

Drop-in for `src/lib/types/a2ui.ts` (derived from `models.py` and the vendored schemas):

```ts
export type A2uiVersion = "v1.0";
export type JsonPointer = string;                                  // RFC 6901; relative (no leading "/") inside template scope
export interface DataBinding { path: JsonPointer }                 // the ONLY key
export interface FunctionCall { call: string; args?: Record<string, unknown>; catalogId?: string }
export type Dynamic<T> = T | DataBinding | FunctionCall;
export type DynamicString = Dynamic<string>;  export type DynamicNumber = Dynamic<number>;
export type DynamicBoolean = Dynamic<boolean>; export type DynamicStringList = Dynamic<string[]>;

export interface ChildTemplate { componentId: string; path: JsonPointer }
export type ChildList = string[] | ChildTemplate;
export interface EventAction { name: string; userMessage?: DynamicString; context?: Record<string, Dynamic<unknown>> }
export type Action = { event: EventAction; functionCall?: never } | { functionCall: FunctionCall; event?: never };
export interface CheckRule { condition: FunctionCall | DataBinding; message?: string }
export interface ValidationResult { valid: boolean; code?: string; message?: string; severity?: "error" | "warning" | "info" }
export interface Accessibility { label?: string; description?: string; live?: "off" | "polite" | "assertive"; hidden?: boolean }
export interface Extensions {
  parrot_variant?: "chart" | "table" | "kpi" | "card" | "map" | "timeline" | "report" | "infographic" | "filter-bar";
  parrot_role?: string; parrot_unit?: string | null; parrot_trend?: "up" | "down" | "flat" | null;
  parrot_total_rows?: number; parrot_truncated?: boolean; parrot_series_data?: DataBinding; parrot_layer_data?: DataBinding;
  parrot_filter_column?: string; parrot_component_id?: string; parrot_optional?: JsonPointer[];
  parrot_theme?: "light" | "dark" | "corporate" | "midnight" | "petrol"; parrot_layout?: "analytics" | "report" | "print";
  [key: string]: unknown;
}
export interface ComponentMetadata { extensions?: Extensions }

export interface A2uiComponent {
  id: string; component: string; catalogId?: string;
  child?: string; children?: ChildList; weight?: number;
  accessibility?: Accessibility; checks?: CheckRule[]; action?: Action; metadata?: ComponentMetadata;
  [prop: string]: unknown;                                          // catalog props are top-level
}

export interface CreateSurface { surfaceId: string; catalogId?: string; sendDataModel?: boolean; components: A2uiComponent[]; dataModel?: Record<string, unknown>; metadata?: ComponentMetadata }
export interface UpdateComponents { surfaceId: string; components: A2uiComponent[] }
export interface UpdateDataModel { surfaceId: string; path?: JsonPointer; value: unknown }   // value null = delete
export interface DeleteSurface { surfaceId: string }
export interface CallRendererFunction { functionCallId: string; callFunction: FunctionCall & { catalogId: string } }
export interface FunctionCallError { code: string; message: string }
export type AgentFunctionResponse = { functionCallId: string; value: unknown; error?: never } | { functionCallId: string; error: FunctionCallError; value?: never };
export type ErrorMessage =
  | { code: "VALIDATION_FAILED" | "UNALLOWED_PARENT" | "UNALLOWED_CHILD"; surfaceId: string; path: string; message: string }
  | { code: string; surfaceId: string; functionCallId?: never; message: string }
  | { code: string; functionCallId: string; surfaceId?: never; message: string };

export type AgentMessage = { version: A2uiVersion } & (
  | { createSurface: CreateSurface } | { updateComponents: UpdateComponents } | { updateDataModel: UpdateDataModel }
  | { deleteSurface: DeleteSurface } | { callRendererFunction: CallRendererFunction }
  | { agentFunctionResponse: AgentFunctionResponse } | { error: ErrorMessage });   // error is returned to renderers even though the A→R schema omits it

export interface ActionMessage { name: string; userMessage?: string; surfaceId: string; sourceComponentId: string; timestamp: string; context: Record<string, unknown>; metadata?: ComponentMetadata; dataModel?: Record<string, unknown> }
export interface CallAgentFunction { surfaceId: string; functionCallId: string; callFunction: FunctionCall }
export type RendererFunctionResponse = AgentFunctionResponse;
export type RendererMessage = { version: A2uiVersion } & (
  | { action: ActionMessage } | { callAgentFunction: CallAgentFunction } | { rendererFunctionResponse: RendererFunctionResponse } | { error: ErrorMessage });

export type A2uiEnvelope = AgentMessage;
export type SurfaceKind = "dashboard" | "infographic" | "widget";
export interface SurfaceMetadata { surface_id: string; kind: SurfaceKind; title: string; refreshable: boolean; created_at: string; updated_at: string; catalog_id: string | null; agent_id: string; access?: "owner" | "shared" }
export interface SurfaceResponse { status: "success"; envelope: CreateSurface; metadata: SurfaceMetadata }
export interface SurfaceListResponse { status: "success"; count: number; surfaces: SurfaceMetadata[] }
export interface PublishSurfaceRequest { kind: SurfaceKind; title: string; envelope?: CreateSurface; source_artifact_id?: string; agent_id?: string; session_id?: string; recipe_name?: string; recipe_owner?: string; recipe_params?: Record<string, unknown> }
export interface ShareResponse { status: "success"; token: string; expires_at: string | null; permissions: "read+refresh" }
export interface ApiErrorBody { status: "error"; message: string; errors?: unknown[]; refreshable?: boolean }
export interface AgentArtifact { type: "chart" | "table" | "map"; artifactId: string; surfaceId?: string; schemaVersion?: 2; definition: A2uiComponent | Record<string, unknown> }
export interface Capabilities { "v1.0": { supportedCatalogIds: string[]; acceptsInlineCatalogs: false } }
export interface DegradationRecord { id: string; component: string; reason: string }
```

Parrot component prop interfaces (`ChartProps`, `DataTableProps`, `MapProps`, `KPICardProps`, `InfoCardProps`, `TimelineProps`, `ReportProps`, `InfographicProps`, `FilterBarProps`) follow §5.2 verbatim; the existing `AppChartConfig` (`chart-contract.ts`) and `StructuredMapConfig` types already cover `Chart` and `Map`.

---

## 10. Conformance fixtures and testing

**Schemas to vendor** (copy into the frontend, e.g. `src/lib/components/agents/canvas/a2ui/schema/`): `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/spec/{agent_to_renderer,renderer_to_agent,common_types,catalog,catalog_definition,agent_capabilities}.json`. The Parrot catalog document is generated, not stored — regenerate it with:

```bash
source .venv/bin/activate
python -c "from pathlib import Path; from parrot.outputs.a2ui.catalog.export import write_catalog_definition; write_catalog_definition(Path('a2ui-parrot-catalog.json'))"
```

**Golden lowered trees** (byte-stable, `component_id` un-aliased because they are model dumps): `packages/ai-parrot/tests/outputs/a2ui/golden/{chart,datatable,infocard,infographic,kpicard,map,report,timeline,filterbar}_lowered.json`.

**Real end-to-end envelopes**: `artifacts/a2ui_dashboard/02_envelope_v1.json` (Infographic with charts + tables + dataModel), `06_live_envelope.json`, `03_baked_components.json` (templates expanded, zero bindings — tests the post-bake path), `artifacts/a2ui_deterministic_refresh/03_capabilities.json` (a real exported function map). Run `python examples/agents/a2ui/flex_dashboard_demo.py --serve` (port 8092) to produce `01_dashboard_default.html`, `02_dashboard_2025-10_field-time.html`, `03_capabilities.json` for the Flex dashboard offline — the same HTML the surfaces route serves. `InMemorySurfaceStore` / `InMemoryPendingCalls` in that demo are minimal reference implementations useful for mocking the RPC leg in frontend tests.

**Backend conformance suite** (the authoritative "is this legal on the wire" gate): `packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py` (every builder, adapter, recipe layout, bake output and renderer input validated two ways), `test_runtime_envelopes.py` (every RPC envelope), `test_benchmark.py`. Renderer tests: `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/` (`test_interactive_html.py`, `test_filterbar_interactive.py`, `test_rich_datatable.py`, `test_semantic_classes.py`, `test_document_shell.py`).

**Postman**: `docs/postman/a2ui-agentdashboard.postman_collection.json` — variables `baseUrl`, `token`, `agentId`, `sessionId`, `surfaceId`, `shareToken`, `artifactId`, `recipeName`, `deeplinkToken`; the "Pin surface" request captures `surface_id` and the "Mint share" request captures `token` into collection variables automatically.

---

## 11. Known gaps, bugs and doc/code disagreements

Verified on `dev @ a1eca82b4`. Items marked **backend** need a backend fix; the rest are things the frontend must tolerate.

1. **`interactive-html` cannot be resolved from a cold registry** (backend). The renderer registers as `"interactive-html"` (hyphen) while its module is `interactive_html.py`; `get_a2ui_renderer("interactive-html")` raises `ImportError` unless the module was already imported in the process, and `get_a2ui_renderer("interactive_html")` fails because that name is not registered. `RenderSpec.profile` defaults to `"interactive-html"`, so `POST /api/v1/infographic_recipes/{name}/run` and `refresh_dashboard` fail on a fresh worker until something imports the module (the ui_surfaces HTML route does, function-locally). Reproduced with a one-line script this session. Fix: eager-import in `a2ui_renderers/__init__.py`, or register an alias.
2. **`A2UIHandler` does not re-apply `@is_authenticated()`** (backend, security review needed). It overrides `post`/`get`, so the decorators applied to `AgentTalk`'s methods are not inherited; its only gate is the 401 on an unresolvable user, and `user_id` is accepted from the `?user_id=` query string. Whether the global auth middleware rejects unauthenticated requests before the handler was not verified in this session — confirm before exposing the route publicly.
3. **HTML surface response lacks `charset` and CSP headers** (backend): `SurfaceNegotiationService._respond_html` returns `web.Response(body=…, content_type="text/html")` — unlike every other HTML path (`agent.py`, `infographic.py`, `artifacts.py`). Non-ASCII content relies on the document's `<meta charset>`; the response is iframe-embeddable with no `frame-ancestors` restriction.
4. **Narrative never reaches the Flex dashboard envelope** (backend, documented in `agents/flex_dashboard.py:549-575`): `RecipeRunner._assemble_envelope_or_raise` drops `layout.metadata` (and `parrot_optional`) on the Infographic path, so any layout binding to an absent `/narrative` raises `BakeError`; the recipe therefore does not bind it.
5. **`callFunction.catalogId` is effectively mandatory** for `callAgentFunction`: the dispatcher resolves the catalog from the call's `catalogId` or a previously persisted surface state and never falls back to the runtime default. Always send it.
6. **`requiresUserActivation` is not enforced at dispatch**: `export_functions()` advertises such tools as `rendererOnly`, but `ToolManagerExecutor.list_functions()` reports every tool as `rendererOrAgent` and dispatch checks the latter. Enforce user activation in the renderer.
7. **`error` is not on the agent→renderer schema**, yet the runtime returns `error` envelopes to renderers. Accept it.
8. **Persisted `surface_id` ≠ envelope `surfaceId`**: pinning always mints a fresh uuid4 (recipe envelopes use `<recipe>-infographic`, not a UUID). Use the stored id for the surfaces API and the envelope id for RPC messages.
9. **Chat error bodies may be raw strings** under `Content-Type: application/json` (`Missing Agent Name`, `Agent 'x' not found.`, `Error retrieving agent: …`) because `BaseView.error(<str>)` does not JSON-encode; and its status whitelist (`400/401/403/404/406/412/428`) silently downgrades other codes to `400`. The ui_surfaces and A2UI handlers build their responses directly and are not affected.
10. **`?output_mode=` query parameter is dead** on the chat endpoint (`_get_output_mode()` is never called); only the body field works.
11. **Streaming is chunked, not SSE**, on the chat endpoint; the only SSE route is `GET /api/v1/agents/{agent_id}/a2ui`.
12. **Surface-state concurrency is process-local** (`asyncio.Lock` per session inside `ConversationMemorySurfaceStore`); a multi-worker deployment can race the same session. Pending renderer calls expire after 900 s; surface state has no TTL.
13. **`refresh_dashboard` is not registered by default** on `FlexDashboard` — the backend must call `agent.build_refresh_tool(pctx)` with a real `PermissionContext` (`RecipeRunner.run` fails open on a falsy one). Check `…/a2ui/capabilities`-adjacent function export before showing a "Refresh via agent" control; prefer the ui_surfaces `refresh` route.
14. **Docs drift**: `docs/agent.md` documents a non-existent bare `POST /api/v1/agents/chat/` route, a `{success, content}` response shape that is dead code, and `mcp_servers` in the POST body (stripped; use `PATCH`); it never mentions `output_mode`, `a2ui`, streaming, or HITL. `docs/infographic_handler_api.md` points at `packages/ai-parrot/…/handlers/infographic.py` (the file is in `ai-parrot-server`) and omits the `/render` and `/render/jobs/{id}` routes. `sdd/specs/flex-agent-infographic-a2ui.spec.md` says datasets are registered with `add_dataset(query_slug=…)`; the code uses `add_query` (deliberately, to avoid eager fetches). `handlers/artifacts.py` documents the public route as `{artifact_id}.html`; the registered pattern is `{artifact_id_html}` with the suffix stripped in code.
15. **No `docs/outputs/` page exists for FEAT-492** (surfaces); the spec and source are the only documentation besides this file.
16. **`AGENTS.md` in the frontend is stale** (claims Flowbite, Playwright, `svelte-echarts`, Chart.js — none are dependencies); `CLAUDE.md` §"Chat System" and §"API Client Layer" are accurate. There is no shadcn `table`, `tabs`, `tooltip`, `dropdown-menu` or `scroll-area` directory yet — `AppTabs`, `AppTooltip`, `AppDropdown` (bits-ui wrappers) and `DataTable.svelte` / `SimpleTable` are the current substitutes.
