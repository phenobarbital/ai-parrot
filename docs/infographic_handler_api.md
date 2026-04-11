# Infographic Handler — Frontend API Contract

**Feature:** FEAT-095 · `get_infographic` handler
**Status:** Merged to `dev` (commits `418a83cb`, `432d9609`)
**Source spec:** `sdd/specs/get-infographic-handler.spec.md`
**Audience:** Frontend engineers building the Infographic feature in the navigator frontend project.

This document is the authoritative contract for talking to the Infographic HTTP API exposed by ai-parrot. It covers URL shapes, request payloads, response shapes, error codes, built-in templates/themes and the data blocks the LLM can return.

---

## 1. Base URL & Auth

- **Base path:** `/api/v1/agents/infographic`
- **Auth:** all endpoints require an authenticated session (Bearer token via standard Parrot auth). Generation and registration are PBAC-gated:
  - Generation (`POST /{agent_id}`) requires `agent:chat`.
  - Registration (`POST /templates`, `POST /themes`) requires `agent:configure`.
- **Content-Type:** `application/json` on all request bodies.

All endpoints live on `InfographicTalk`, which subclasses `AgentTalk`. Routes are registered in `BotManager.setup_app()` (`packages/ai-parrot/src/parrot/manager/manager.py:727-749`).

---

## 2. Endpoint Map

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/agents/infographic/{agent_id}` | Generate an infographic for an agent |
| `GET`  | `/api/v1/agents/infographic/templates` | List available templates |
| `GET`  | `/api/v1/agents/infographic/templates/{name}` | Get a template definition |
| `POST` | `/api/v1/agents/infographic/templates` | Register a custom template (global) |
| `GET`  | `/api/v1/agents/infographic/themes` | List available themes |
| `GET`  | `/api/v1/agents/infographic/themes/{name}` | Get a theme definition |
| `POST` | `/api/v1/agents/infographic/themes` | Register a custom theme (global) |

Implementation reference: `packages/ai-parrot/src/parrot/handlers/infographic.py`.

---

## 3. Content Negotiation (Generation)

The generation endpoint can return **HTML** or **JSON** depending on what the caller asks for. Negotiation logic lives in `_negotiate_accept()` (`handlers/infographic.py:384-404`).

Priority (highest wins):

1. Query parameter `?format=html` / `?format=json`
2. `Accept` header (`text/html` or `application/json`)
3. Default: `text/html`

Frontend recommendation:
- For **rendering an iframe or embedding raw HTML**: use `?format=html` (or `Accept: text/html`).
- For **custom React/Vue rendering** using the block model: use `?format=json` (or `Accept: application/json`).

---

## 4. `POST /api/v1/agents/infographic/{agent_id}` — Generate

Generate a structured infographic for the given agent based on a user query.

### Path params

| Param | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | ID of a registered agent/bot |

### Query params

| Param | Type | Default | Description |
|---|---|---|---|
| `format` | `html` \| `json` | — | Overrides `Accept` header |

### Request body

```jsonc
{
  "query": "Summarize Q4 2025 sales performance",   // required, non-empty
  "template": "executive",                            // optional, default "basic"
  "theme": "corporate",                               // optional
  "session_id": "sess_abc123",                        // optional
  "user_id": "user_42",                               // optional
  "use_vector_context": true,                         // optional, default true
  "use_conversation_history": false                   // optional, default false
  // any other fields are forwarded as **kwargs to bot.get_infographic()
}
```

**Validation rules** (`_generate_infographic`, lines 132-234):

- `query` is required and must be a non-empty string (whitespace-only is rejected).
- Body must be a JSON object (arrays/strings → 400).
- `template` must exist in the registry or the request returns 404.
- These keys are reserved and consumed by the handler, never forwarded as kwargs: `query`, `question`, `template`, `theme`, `accept`, `ctx`, `user_id`, `session_id`, `use_vector_context`, `use_conversation_history`, `agent_name`, `scope`.

### Successful response — JSON mode

`200 OK` · `Content-Type: application/json`

```json
{
  "infographic": {
    "template": "executive",
    "theme": "corporate",
    "blocks": [
      { "type": "title",     "title": "Q4 2025 Performance", "author": "Sales Analytics", "date": "2025-12-31" },
      { "type": "hero_card", "label": "Revenue", "value": "$2.5M", "trend": "up", "trend_value": "+18%" },
      { "type": "summary",   "content": "Strong close to the year driven by enterprise deals..." },
      { "type": "chart",     "chart_type": "line", "title": "Monthly revenue", "labels": ["Oct","Nov","Dec"], "series": [{"name":"2025","values":[780,920,800]}] }
    ],
    "metadata": {}
  }
}
```

The `blocks[]` array conforms to the block models in section 8.

### Successful response — HTML mode

`200 OK` · `Content-Type: text/html; charset=utf-8`

A self-contained HTML document (full `<html>…</html>` with inline `<style>`). Safe to drop into an iframe or render via `dangerouslySetInnerHTML`. UTF-8 is forced at the response level so em-dashes and non-Latin glyphs render correctly.

### Error responses

| Status | When | Body |
|---|---|---|
| `400` | Missing/empty `query` | `{"error": "Missing 'query' field in body."}` |
| `400` | Invalid JSON | `{"error": "Invalid JSON body."}` |
| `400` | Body is not a JSON object | `{"error": "Request body must be a JSON object."}` |
| `400` | Missing `agent_id` | `{"error": "Missing agent_id in URL."}` |
| `403` | PBAC denies `agent:chat` | PBAC error payload |
| `404` | Unknown template | `{"error": "Infographic template 'xyz' not found. Available templates: ..."}` |
| `500` | Generation failed (LLM/tool error) | `{"error": "Generation failed: <message>"}` |

### cURL examples

```bash
# JSON via query param
curl -X POST "https://api.example.com/api/v1/agents/infographic/sales_bot?format=json" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"Analyze Q4 2025","template":"executive","theme":"corporate"}'

# HTML via Accept header
curl -X POST "https://api.example.com/api/v1/agents/infographic/sales_bot" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: text/html" \
  -H "Content-Type: application/json" \
  -d '{"query":"Analyze Q4 2025"}'
```

---

## 5. Template Endpoints

### 5.1 `GET /templates` — list

Query params:

| Param | Type | Default | Description |
|---|---|---|---|
| `detailed` | `"true"` \| `"false"` | `"false"` | When `true`, return `{name, description}` objects |

**Simple response:**
```json
{ "templates": ["basic", "comparison", "dashboard", "executive", "minimal", "timeline"] }
```

**Detailed response:**
```json
{
  "templates": [
    { "name": "basic",     "description": "Simple overview infographic with title, key metrics, summary, chart, and takeaways." },
    { "name": "executive", "description": "Executive briefing with metrics, analysis, supporting data, and recommendations." }
  ]
}
```

### 5.2 `GET /templates/{name}` — detail

```json
{
  "template": {
    "name": "executive",
    "description": "Executive briefing with metrics, analysis, supporting data, and recommendations.",
    "block_specs": [
      { "block_type": "title",     "required": true, "description": "Report title, author, and date", "min_items": null, "max_items": null, "constraints": {} },
      { "block_type": "hero_card", "required": true, "description": "4-6 KPI cards with trend indicators", "min_items": 4, "max_items": 6, "constraints": {} },
      { "block_type": "chart",     "required": true, "description": "Primary trend chart", "min_items": null, "max_items": null, "constraints": { "chart_type": "line" } }
    ],
    "default_theme": "corporate"
  }
}
```

`404` if the template name is not registered.

### 5.3 `POST /templates` — register (global only in v1)

**Request body:**
```jsonc
{
  "template": {
    "name": "quarterly_board_report",
    "description": "Board-level quarterly deck",
    "block_specs": [
      { "block_type": "title",     "required": true },
      { "block_type": "hero_card", "required": true, "min_items": 3, "max_items": 5 },
      { "block_type": "summary",   "required": true },
      { "block_type": "chart",     "required": true, "constraints": { "chart_type": "line" } }
    ],
    "default_theme": "corporate"
  },
  "scope": "global"   // "session" → 403 in v1
}
```

**Success (`201 Created`):**
```json
{
  "message": "Template registered",
  "template": { "name": "quarterly_board_report", "description": "Board-level quarterly deck", "block_specs": [...], "default_theme": "corporate" }
}
```

**Error cases:**

| Status | When |
|---|---|
| `400` | Invalid JSON / not an object / missing `template` / Pydantic validation failed (payload includes `details`) |
| `403` | `scope: "session"` (deferred to v2) or PBAC denies `agent:configure` |

Validation error body example:
```json
{
  "error": "Invalid template payload",
  "details": [
    { "loc": ["block_specs", 0, "block_type"], "msg": "Input should be a valid enumeration", "type": "enum" }
  ]
}
```

---

## 6. Theme Endpoints

### 6.1 `GET /themes` — list

Query params: `detailed` (same semantics as templates).

**Simple response:**
```json
{ "themes": ["corporate", "dark", "light"] }
```

**Detailed response:**
```json
{
  "themes": [
    { "name": "corporate", "primary": "#1e40af", "neutral_bg": "#f9fafb", "body_bg": "#f3f4f6" },
    { "name": "dark",      "primary": "#818cf8", "neutral_bg": "#1e293b", "body_bg": "#0f172a" },
    { "name": "light",     "primary": "#6366f1", "neutral_bg": "#f8fafc", "body_bg": "#f1f5f9" }
  ]
}
```

### 6.2 `GET /themes/{name}` — detail

```json
{
  "theme": {
    "name": "light",
    "primary": "#6366f1",
    "primary_dark": "#4f46e5",
    "primary_light": "#818cf8",
    "accent_green": "#10b981",
    "accent_amber": "#f59e0b",
    "accent_red": "#ef4444",
    "neutral_bg": "#f8fafc",
    "neutral_border": "#e2e8f0",
    "neutral_muted": "#64748b",
    "neutral_text": "#0f172a",
    "body_bg": "#f1f5f9",
    "font_family": "-apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, Helvetica, Arial, sans-serif"
  }
}
```

`404` if the theme does not exist.

### 6.3 `POST /themes` — register (global only in v1)

**Request body:**
```jsonc
{
  "theme": {
    "name": "sunset",
    "primary": "#ff6b35"
    // any ThemeConfig field is accepted; unspecified fields fall back to defaults
  },
  "scope": "global"
}
```

Returns `201` with the fully-materialized `ThemeConfig` (all defaults filled in). Same error table as template registration; `scope: "session"` → 403.

---

## 7. Built-in Catalog

### 7.1 Templates

Source: `packages/ai-parrot/src/parrot/models/infographic_templates.py`.

| Name | Default theme | Content shape |
|---|---|---|
| `basic` | `light` | title → 3–5 hero cards → summary → chart → bullet list |
| `executive` | `corporate` | title → 4–6 KPI cards → summary → divider → line chart → table → callout → recommendations |
| `dashboard` | `dark` | title → 6–8 KPI cards → line chart → pie chart → table → optional progress |
| `comparison` | `light` | title → summary → comparison table → bar chart → callout → key differences |
| `timeline` | `light` | title → summary → 4+ timeline events → area chart → learnings |
| `minimal` | `light` | title → summary → key points |

### 7.2 Themes

Source: `packages/ai-parrot/src/parrot/models/infographic.py:455-499`.

| Name | Primary | `body_bg` | Use case |
|---|---|---|---|
| `light` | `#6366f1` (indigo) | `#f1f5f9` | Default, light backgrounds, dark text |
| `dark` | `#818cf8` (light indigo) | `#0f172a` | Dark dashboards |
| `corporate` | `#1e40af` (deep blue) | `#f3f4f6` | Formal/financial reports |

Every theme ships the full token set (`primary`, `primary_dark`, `primary_light`, three accents, four neutrals, `body_bg`, `font_family`) — see section 6.2 for the exact shape.

---

## 8. Block Model (JSON responses)

When `format=json`, each item in `infographic.blocks` is one of the following discriminated types (`type` field). Reference: `packages/ai-parrot/src/parrot/models/infographic.py:38-304`.

### 8.1 Enums

```
BlockType      = title | hero_card | summary | chart | bullet_list | table | image | quote | callout | divider | timeline | progress
ChartType      = bar | line | pie | donut | area | scatter | radar | heatmap | treemap | funnel | gauge | waterfall
TrendDirection = up | down | flat
CalloutLevel   = info | success | warning | error | tip
```

### 8.2 Block shapes

```ts
// TitleBlock
{ type: "title", title: string, subtitle?: string, author?: string, date?: string, logo_url?: string }

// HeroCardBlock
{
  type: "hero_card",
  label: string,
  value: string,
  icon?: string,                // e.g. "money", "users", "chart"
  trend?: "up" | "down" | "flat",
  trend_value?: string,         // e.g. "+12.5%"
  comparison_period?: string,   // e.g. "vs last month"
  color?: string                // CSS color
}

// SummaryBlock
{ type: "summary", title?: string, content: string /* markdown allowed */, highlight?: boolean }

// ChartBlock
{
  type: "chart",
  chart_type: ChartType,
  title?: string,
  description?: string,
  labels: string[],             // x-axis or slice labels
  series: Array<{ name: string, values: Array<number|null>, color?: string }>,
  x_axis_label?: string,
  y_axis_label?: string,
  stacked?: boolean,
  show_legend?: boolean
}

// BulletListBlock
{ type: "bullet_list", title?: string, items: string[], ordered?: boolean, icon?: string }

// TableBlock
{ type: "table", title?: string, columns: string[], rows: any[][], highlight_first_column?: boolean, sortable?: boolean }

// ImageBlock
{ type: "image", url?: string, base64?: string, alt: string, caption?: string, width?: string }

// QuoteBlock
{ type: "quote", text: string, author?: string, source?: string }

// CalloutBlock
{ type: "callout", level?: CalloutLevel, title?: string, content: string }

// DividerBlock
{ type: "divider", style?: "solid" | "dashed" | "dotted" | "gradient" }

// TimelineBlock
{
  type: "timeline",
  title?: string,
  events: Array<{ date: string, title: string, description?: string, icon?: string, color?: string }>
}

// ProgressBlock
{
  type: "progress",
  title?: string,
  items: Array<{ label: string, value: number /* 0-100 */, color?: string, target?: number }>
}
```

### 8.3 Envelope

```ts
type InfographicResponse = {
  template?: string;
  theme?: string;
  blocks: Block[];
  metadata?: Record<string, unknown>; // free-form (e.g. data_sources, generated_at)
};
```

The JSON generation endpoint wraps this in `{ "infographic": InfographicResponse }`.

---

## 9. Known Limitations (v1)

1. **No session-scoped registration.** `POST /templates` and `POST /themes` return `403` if `scope: "session"`. Only `scope: "global"` (default) is accepted in v1.
2. **No DELETE.** Registered custom templates/themes cannot be removed via API — only by restarting the process.
3. **No persistence.** Custom templates/themes live in memory only and are lost on restart.
4. **HTML only for rendered output.** No PDF/PNG/SVG export endpoints.
5. **No streaming.** Synchronous request/response, no partial block streaming / WebSocket.

These are relevant if the frontend plans to expose template/theme management UI — treat it as read-only + create-global-only for now.

---

## 10. Suggested Frontend Integration Flow

This is a suggestion for the frontend spec, not a binding contract:

1. **Boot-time:** `GET /api/v1/agents/infographic/templates?detailed=true` and `GET /api/v1/agents/infographic/themes?detailed=true` to populate template/theme pickers.
2. **User submits a query:**
   - Call `POST /api/v1/agents/infographic/{agent_id}?format=json` with `{ query, template, theme, session_id, user_id }`.
   - Handle loading state (generation can take several seconds).
3. **Render:**
   - Preferred: walk `blocks[]` and render via a component per block type (`TitleBlock`, `HeroCard`, `Chart`, …). This allows interactivity, theming at the component level, and drill-downs.
   - Fallback / quick win: call again with `?format=html` and embed the returned HTML in an iframe / sanitized container.
4. **Error handling:** surface `error` field from non-2xx responses. `404` on unknown template should invalidate the picker cache and re-fetch templates.
5. **Admin / power users:** gate template/theme registration behind `agent:configure`; expose a simple form that POSTs to `/templates` or `/themes` with `scope: "global"`.

---

## 11. Source References

| Concern | File |
|---|---|
| Handler class & routes | `packages/ai-parrot/src/parrot/handlers/infographic.py` |
| Route registration | `packages/ai-parrot/src/parrot/manager/manager.py:727-749` |
| SDK helpers (`list_templates`, `register_template`, …) | `packages/ai-parrot/src/parrot/helpers/infographics.py` |
| Block / envelope models | `packages/ai-parrot/src/parrot/models/infographic.py` |
| Built-in templates | `packages/ai-parrot/src/parrot/models/infographic_templates.py` |
| Handler tests | `packages/ai-parrot/tests/handlers/test_infographic_handler.py` |
| Helper tests | `packages/ai-parrot/tests/helpers/test_infographics_helpers.py` |
| Feature spec | `sdd/specs/get-infographic-handler.spec.md` |
