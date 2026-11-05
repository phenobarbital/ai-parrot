# Technical Guide to Structured Artifacts for Frontend

**Audience**: the Frontend team building the visualization UI (tables, charts and maps) on top of AI-Parrot.
**Scope**: `STRUCTURED_TABLE` (FEAT-218), `STRUCTURED_CHART` (FEAT-215) and `STRUCTURED_MAP` (FEAT-221), unified under the common contract of FEAT-223 (`structured-artifact-contract`).
**Endpoint**: AgentTalk (`/api/v1/agents/chat/...`).

> This document is grounded in the actual code of the repository. The file
> paths and line numbers referenced are verification anchors
> (anti-hallucination) and may move over time; the semantic contract is what
> matters.

---

## 0. Index

1. [Mental model: the common contract](#1-mental-model-the-common-contract)
2. [The AgentTalk response envelope](#2-the-agenttalk-response-envelope)
   - [2.5 Canonical config location (definitive contract)](#25-canonical-config-location-definitive-contract)
   - [2.6 A2UI v1.0 envelope (FEAT-473 — dual-emit)](#26-envelope-a2ui-v10-feat-473--dual-emit)
3. [AgentTalk endpoints](#3-agenttalk-endpoints)
4. [STRUCTURED_TABLE](#4-structured_table-feat-218)
5. [STRUCTURED_CHART](#5-structured_chart-feat-215)
6. [STRUCTURED_MAP](#6-structured_map-feat-221)
7. [Shared vocabularies (types and formats)](#7-shared-vocabularies)
8. [Streaming](#8-streaming)
9. [Errors, edge cases and degradation](#9-errors-edge-cases-and-degradation)
10. [Frontend integration checklist](#10-frontend-integration-checklist)

---

## 1. Mental model: the common contract

The three structures (`table`, `chart`, `map`) share a **single envelope
contract** (FEAT-223). Understanding it once applies to all three.

Each artifact is split into **two halves**:

| Half | What it is | Who produces it | Where it travels (**canonical contract**) |
|---|---|---|---|
| **Presentation (config / `definition`)** | How to paint: chart type, columns, axes, tooltips, viewport, palette… | LLM and/or deterministic rules | Inside the artifact envelope **`response.artifacts[]`**, in the `definition` field — **without the rows** |
| **Data (rows)** | The actual rows / features | Deterministic (the DataFrame the agent computed, or the spatial result) | In the **`response.data`** field |

> **Read [§2.5 — Canonical config location](#25-canonical-config-location-definitive-contract) first.**
> The **implemented canonical contract (FEAT-224)** is the artifact envelope in
> `response.artifacts[]`. The config travels in `artifacts[].definition` (camelCase,
> without `data`). `response.output` remains as a deprecated mirror (G6); `response.code`
> no longer carries config in the chart path. See §2.5 for the full status.

Invariant rules that the backend **guarantees** (verified in
`packages/ai-parrot-visualizations/.../structured_base.py` and in the parity
tests `tests/outputs/formats/test_structured_parity.py`):

1. **The config (`definition`) NEVER includes the `data` key.** It is serialized with
   `model_dump(mode="json", by_alias=True, exclude={"data"})`. If you see `data`
   inside the config, it is a bug.
2. **Rows ALWAYS go in `response.data`.** Never inside the config.
3. **The renderer never raises an exception.** On failure it returns
   `(None, error_message)` — the config will be `null` and the error text remains
   available. The frontend must handle a missing config.
4. **Field names in `camelCase`** in the output JSON (thanks to
   `populate_by_name=True` + alias). Internally the Python model uses
   `snake_case`, but **what you receive over the API is camelCase**.
5. **A prose explanation** accompanies the artifact (the `wrapped` / `response`),
   meant to be shown as the text message next to the visualization.

```
┌─────────────────────────── AgentTalk response (canonical) ────────────────────┐
│  artifacts[] → [{ type, artifactId, definition }]  ← CONFIG (how to paint)     │
│                  definition = config WITHOUT rows, camelCase                   │
│  data        → ROWS / FEATURES (what to paint)                                 │
│  response    → Explanatory text (prose for the user)                           │
│  output_mode → "structured_table" | "structured_chart" | "structured_map"     │
│  artifact_id → id of the turn's primary artifact                               │
│  metadata    → model, provider, tokens, session_id, turn_id, ...               │
└────────────────────────────────────────────────────────────────────────────────┘
```

> **Key implication for the Frontend**: to render any structured artifact you
> need to combine **two fields**: the config (the artifact's `definition`) +
> `response.data` (rows). They do not arrive pre-merged (on purpose: it keeps
> the payload bounded and allows up to ~879k features without inflating the config).

**`OutputMode` definition** (`packages/ai-parrot/src/parrot/models/outputs.py:37`):

```python
class OutputMode(str, Enum):
    ...
    STRUCTURED_CHART = "structured_chart"  # FEAT-215 — library-agnostic chart config
    STRUCTURED_TABLE = "structured_table"  # FEAT-218 — framework-agnostic table config
    STRUCTURED_MAP   = "structured_map"    # FEAT-221 — framework-agnostic map config
```

**`ArtifactType`** (when the artifact is persisted —
`packages/ai-parrot/src/parrot/storage/models.py:244`):

```python
class ArtifactType(str, Enum):
    CHART = "chart"
    MAP = "map"            # added by FEAT-223 / TASK-1457
    CANVAS = "canvas"
    INFOGRAPHIC = "infographic"
    DATAFRAME = "dataframe"
    EXPORT = "export"
```

---

## 2. The AgentTalk response envelope

All chat responses (JSON format) are serialized from the `AIMessage` model
(`packages/ai-parrot/src/parrot/models/responses.py:72`). The JSON envelope the
frontend receives has this shape:

```json
{
  "input": "string — la consulta original del usuario",
  "output": "any — el artefacto / texto / config principal",
  "response": "string — respuesta textual del modelo (prosa explicativa)",
  "data": "any — datos estructurados (filas/features) cuando aplica",
  "code": "string — código Python o definición JSON (charts)",
  "output_mode": "structured_table | structured_chart | structured_map | json | html | ...",
  "metadata": {
    "model": "gpt-4",
    "provider": "openai",
    "session_id": "string",
    "turn_id": "string",
    "user_id": "string | null",
    "response_time": 1234,
    "usage": {
      "prompt_tokens": 0,
      "completion_tokens": 0,
      "total_tokens": 0
    },
    "finish_reason": "stop",
    "stop_reason": "string",
    "created_at": "ISO-8601 (opcional)"
  },
  "sources": [
    {
      "source": "string",
      "filename": "string",
      "url": "string (opcional)",
      "page_number": 0,
      "score": 0.0,
      "metadata": {}
    }
  ],
  "tool_calls": [
    { "name": "string", "status": "completed", "output": "any", "arguments": "any" }
  ]
}
```

### 2.1 Fields relevant to structured artifacts

| Field | For structured artifacts |
|---|---|
| `output_mode` | **Mode discriminator**. `structured_table\|chart\|map`. Switch your renderer on this value. |
| `artifacts[]` | **Canonical config container** (`{type, artifactId, definition}`). `definition` = config without `data`. See §2.5. |
| `artifact_id` | Id of the turn's **primary artifact** (to retrieve / reference it). |
| `data` | Contains the **rows** (table/chart) or **per-layer payloads** (map). |
| `response` | Prose text to show the user next to the visualization. |
| `output` | Compat: today the backend still leaves the serialized config here (see §2.5). |
| `code` | **Reserved for interpretable code** (Python/TS) or `null`. It must **not** carry config (see §2.5). |

---

### 2.5 Canonical config location (definitive contract)

> This section is the **contract agreement** between backend and frontend for FEAT-223.
> Explicitly decided; it supersedes any previous inference about `output`/`code`.

#### Canonical contract (TARGET — the one the frontend must converge to)

The config of **every** structured artifact travels in **`response.artifacts[]`**,
one envelope per artifact whose shape mirrors the persisted `Artifact` model
(`storage/models.py`):

```json
{
  "artifacts": [
    {
      "type": "chart",                  // "chart" | "map" | "table"  (ArtifactType)
      "artifactId": "art_abc123",       // stable artifact id
      "definition": {                   // = the CONFIG, camelCase, WITHOUT the data key
        "type": "bar",
        "x": "month",
        "y": ["sales"],
        "title": "Monthly Sales"
      }
    }
  ],
  "data": [ { "month": "Jan", "sales": 100 } ],   // rows/features (or per-layer payloads in map)
  "response": "Las ventas crecieron de forma sostenida...",  // prose
  "output_mode": "structured_chart",
  "artifact_id": "art_abc123"           // echo of the turn's primary artifact
}
```

Rules of the canonical contract:

1. **`artifacts[].definition` is the single source of truth for the config.** It is the
   `model_dump(by_alias=True, exclude={"data"})` of the corresponding
   `Structured*Config`. CamelCase, no rows.
2. **`artifacts[].type`** uses the `ArtifactType` vocabulary: `"chart"`,
   `"map"`, `"table"`. It is the fine-grained discriminator that tells you the
   shape of `definition` (`StructuredChartConfig` / `StructuredMapConfig` /
   `StructuredTableConfig`).
3. **`response.data`** keeps carrying the rows (table/chart) or the per-layer
   payloads (map). Same as before.
4. **`response.code`** stays **`null`** unless the turn produces real code
   intended to be interpreted by the frontend (e.g. a TypeScript snippet) or
   the pandas analysis code. It **never** carries the artifact's config.
5. **`artifact_id`** (root level) replicates the id of the turn's primary
   artifact, for deep-linking / persistence.

> **Note on `ArtifactType.TABLE`**: as of today `ArtifactType` defines
> `CHART` and `MAP` but **not** `TABLE` (`storage/models.py:244`). The canonical
> contract assumes `TABLE = "table"` will be added as part of the unification
> refactor. Until then, a table might arrive typed as `dataframe` — confirm it
> with the backend before fixing the enum in the client.

#### Current backend status — implemented contract (FEAT-224)

The pipeline (`bots/data.py` + `structured_chart.py`) implements the canonical
contract since **FEAT-224**. All three modes produce:

| Mode | `response.output` | `response.data` | `response.code` | `artifacts[]` |
|---|---|---|---|---|
| `structured_table` | ⚠️ deprecated mirror (G6) — table config (dict) | rows (records) | pandas code or `null` | ✅ **`[{type:"table", artifactId, definition}]`** |
| `structured_map` | ⚠️ deprecated mirror (G6) — map config (dict) | per-layer payloads | usually `null` | ✅ **`[{type:"map", artifactId, definition}]`** |
| `structured_chart` | ⚠️ deprecated mirror (G6) — reconciled config | rows (records) | ✅ `null` (config no longer duplicated) | ✅ **`[{type:"chart", artifactId, definition}]`** |

Implemented contract:

- **Config**: canonically in `response.artifacts[].definition` (camelCase, without `data`).
- **Chart `code`**: `null` — the config is no longer duplicated here (FEAT-224 G3); the
  `StructuredChartRenderer` reads its input from `response.output`/`structured_output`.
- **`artifacts[]`/`artifact_id`**: populated for all three structured modes.
- **`response.output`**: still mirrors the config during the migration window
  (G6) so existing consumers don't break; **deprecated** — migrate to `artifacts[]`.
- **Persistence (FEAT-103)**: the auto-save handler persists `definition` (the config,
  not the rows) with the correct `ArtifactType` per mode.

#### Recommended read strategy for the Frontend (resilient to the migration)

Implement a **tolerant config selector** that prefers the canonical contract
and falls back to the current state, so that nothing breaks today or after the refactor:

```ts
function extractArtifact(resp) {
  // 1) Canonical: artifacts[] with definition
  const art = (resp.artifacts ?? []).find(a => a.definition);
  if (art) return { type: art.type, config: art.definition };

  // 2) Current compat: config in response.output, discriminated by output_mode
  const typeByMode = {
    structured_chart: "chart",
    structured_map:   "map",
    structured_table: "table",
  };
  const type = typeByMode[resp.output_mode];
  if (type && resp.output && typeof resp.output === "object") {
    return { type, config: resp.output };
  }

  // 3) Last resort (legacy chart): config in response.code
  if (resp.output_mode === "structured_chart" && resp.code && typeof resp.code === "object") {
    return { type: "chart", config: resp.code };
  }
  return null;   // no config → degrade to text (resp.response)
}

// Rows ALWAYS from response.data, under either contract:
const rows = resp.data ?? [];
```

> Once the backend completes the refactor, branch (1) will cover 100% of cases
> and you can retire (2) and (3). Until then, keep all three.

---

### 2.6 A2UI v1.0 envelope (FEAT-473 — dual-emit)

> **FEAT-473** adds a **third channel**, purely additive, to the three
> `structured_*` modes: alongside the §2.5 contract (`artifacts[]`/`output`/`data`,
> unchanged), the response can now **also** carry a spec-conformant
> [A2UI v1.0](https://a2ui.org/specification/v1_0) envelope, built
> **deterministically, without an LLM** by the adapter
> `parrot.outputs.a2ui.adapters.structured`.

#### What changes (and what does NOT change)

| Field | Before FEAT-473 | With FEAT-473 |
|---|---|---|
| `response.output` | Config (dict) | **Same** + one new key: `surfaceId` |
| `response.data` | Rows / per-layer payloads | **Unchanged** |
| `response.artifacts[]` | `{type, artifactId, definition}` (v1) | `{type, artifactId, surfaceId, schemaVersion: 2, definition}` (v2) — `definition` is now an **A2UI v1.0 component node**, not the config dict |
| `response.a2ui_envelope` | Did not exist for `structured_*` modes | **New**: `{"version": "v1.0", "createSurface": {...}}` |
| `response.artifact_id` | Id of the v1 artifact | Same, but now `== surfaceId` |

> **The only modification to `response.output` is the `surfaceId` key.** If your
> client strictly validates the shape of `output` (closed JSON Schema),
> add `surfaceId` as an optional property before deploying this change.

#### `artifacts[]` v2 contract

```json
{
  "type": "chart",
  "artifactId": "structured_chart-a1b2c3d4",
  "surfaceId": "structured_chart-a1b2c3d4",
  "schemaVersion": 2,
  "definition": {
    "id": "root",
    "component": "Chart",
    "catalogId": "https://parrot.dev/catalogs/v1",
    "type": "bar",
    "x": "month",
    "y": ["sales"],
    "title": "Monthly Sales",
    "data": { "path": "/rows" }
  }
}
```

Rules:

1. **`schemaVersion: 2`** discriminates the new shape from v1 (`schemaVersion`
   absent or `1`). Use `compat.is_legacy_artifact(entry)` (backend) or check
   the key yourself in the client.
2. **`surfaceId == artifactId == response.artifact_id`.**
3. **`definition`** is now an **A2UI v1.0 `Component` node** (`id`,
   `component`, `catalogId`, top-level camelCase props, `data` as a
   `{"path": ...}` binding) — **not** the flat config dict of v1. Its props
   match the config 1:1 (`StructuredChartConfig`/`StructuredTableConfig`/
   `StructuredMapConfig`), but the shape of the object changed.
4. If your client is **not** ready for v2, use the compatibility shim
   (next subsection) — supported until **0.31**, removed in **0.32**.

#### Compatibility shim (`artifact_definition_to_legacy`)

While you migrate, the backend exposes a pure helper (Python, backend side) that
downgrades a v2 `definition` to the exact v1 shape of FEAT-224 — useful if you
have persistence/BFF logic that still expects v1:

```python
from parrot.outputs.a2ui.compat import is_legacy_artifact, artifact_definition_to_legacy

for entry in response.artifacts:
    definition = (
        entry["definition"] if is_legacy_artifact(entry)
        else artifact_definition_to_legacy(entry)
    )
    # `definition` is now always the v1 dict (camelCase, without id/component/catalogId/data)
```

On the client (TypeScript), the equivalent is simply to **omit** the A2UI
wrapper keys of the component node:

```ts
function toLegacyDefinition(v2Definition: Record<string, any>) {
  const { id, component, catalogId, data, datasets, ...config } = v2Definition;
  return config;   // == the v1 config (camelCase, no rows)
}
```

#### Consuming `response.a2ui_envelope`

`response.a2ui_envelope` is a complete A2UI v1.0 message — the same
format consumed by the satellite renderers (`echarts`, `folium_map`, `pdf`,
`ssr_html`, `interactive_html`, `adaptive_cards`) and any external
spec-conformant A2UI renderer. General shape:

```json
{
  "version": "v1.0",
  "createSurface": {
    "surfaceId": "string",
    "catalogId": "https://parrot.dev/catalogs/v1",
    "components": [ { "id": "root", "component": "Chart|DataTable|Map", "...": "props top-level" } ],
    "dataModel": { "...": "filas/features, ver forma por componente abajo" }
  }
}
```

Rows/features of the `dataModel`, per component:

| Component | Binding pointer | `dataModel` shape |
|---|---|---|
| `Chart` / `DataTable` | `{"path": "/rows"}` | `{"rows": [ {...}, ... ]}` |
| `Map` | per layer: `{"path": "/layers/<i>/features"}` | `{"layers": [ {"features": [ {...}, ... ]}, ... ]}` |

Overflow beyond the `row_limit` (1000 by default, same as in §4.3/§9.3):
`Chart`/`DataTable` carry no separate flag (the cap only applies to the
`dataModel`, `response.data` keeps the full set); `DataTable` does
expose `totalRows`/`truncated` as props (same as in v1); each `Map` layer
exposes `totalCount`/`capped` (same as `MapLayer` in v1 — see §6.3).

**Complete, valid examples** (all three pass `validate_message` on their
"lowered" form, the same two-layer check used by the rest of the backend —
see Appendix B):

- Chart → Appendix B.1
- Table → Appendix B.2
- Map (multi-layer) → Appendix B.3

#### Recommended consumption (resilient, without breaking the v1 contract)

```ts
function renderStructuredResponse(resp) {
  // The v1 contract (§2.5) keeps working unchanged — use extractArtifact()
  // if you haven't migrated yet. If you want the native A2UI path (external renderers,
  // deep links, PDF/SSR/Adaptive Cards), use the envelope when present:
  if (resp.a2ui_envelope) {
    return renderA2UISurface(resp.a2ui_envelope);   // your A2UI v1.0 renderer
  }
  return renderStructuredLegacy(resp);              // fallback: extractArtifact() from §2.5
}
```

---

## 3. AgentTalk endpoints

Handler: `AgentTalk(BaseView)` in
`packages/ai-parrot-server/src/parrot/handlers/agent.py`. It is protected by
`@is_authenticated()` and `@user_session()`.

Route registration (`manager.py`):

```python
router.add_view('/api/v1/agents/chat/{agent_id}', AgentTalk)
router.add_view('/api/v1/agents/chat/{agent_id}/{method_name}', AgentTalk)
```

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/v1/agents/chat/{agent_id}` | **Chat** with the agent (the main route for producing artifacts). |
| `POST` | `/api/v1/agents/chat/{agent_id}/{method_name}` | Invoke a custom agent method. |
| `PATCH` | `/api/v1/agents/chat/{agent_id}` | Configure the session's tools / MCP servers. |
| `PUT` | `/api/v1/agents/chat/{agent_id}` | Upload data or query slugs. |
| `GET` | `/api/v1/agents/chat/` | Info / debug / MCP server listing. |

### 3.1 Authentication and headers

```
Authorization: Bearer <token>
Content-Type: application/json        (POST/PATCH/PUT)
Accept: application/json | text/html | text/markdown | text/plain   (optional)
```

Format negotiation (priority): explicit `output_mode`/`output_format` parameter
in the body > `?output_format=` query string > `Accept` header > default `json`.

For structured artifacts, **always work in JSON** and set `output_mode`
explicitly.

### 3.2 `POST /api/v1/agents/chat/{agent_id}` — request

```json
{
  "query": "string (REQUERIDO) — la pregunta / instrucción",
  "agent_name": "string (opcional)",
  "session_id": "string (opcional; se genera un UUID si falta)",
  "user_id": "string (opcional)",
  "stream": false,
  "output_mode": "structured_table | structured_chart | structured_map",
  "search_type": "similarity",
  "return_sources": true,
  "use_vector_context": true,
  "use_conversation_history": true,
  "message_id": "string (opcional; id de cliente para deduplicación)",
  "turn_id": "string (opcional; para follow-up)",
  "data": "any (opcional; datos de follow-up)",
  "ws_channel_id": "string (opcional; canal WebSocket para notificaciones)",
  "format_kwargs": {
    "show_metadata": true,
    "show_sources": true,
    "include_sources": true,
    "include_tool_calls": true,
    "interactive": true
  }
}
```

Key fields for the visualization Frontend:

- **`output_mode`**: sets the type of artifact you want (`structured_table`,
  `structured_chart`, `structured_map`). If you omit it, the agent decides its
  default mode and you might not receive a structured config.
- **`session_id`**: keep the same value across turns to preserve the
  conversation thread.
- **`message_id`**: client-generated id to deduplicate retries.

### 3.3 Special responses (not artifacts, but the Frontend must handle them)

The POST can return, with **HTTP 200**, envelopes that are NOT a normal chat
response:

**HITL paused** (`PausedEnvelope`, FEAT-204): the agent needs human input.

```json
{
  "status": "paused",
  "turn_id": "string (interaction_id)",
  "interaction_id": "string",
  "interaction_type": "single_choice | free_text | form",
  "question": "string",
  "context": "string (opcional)",
  "options": [{ "label": "string", "value": "string", "description": "string" }],
  "form_schema": { "...": "JSON Schema (opcional)" },
  "default_response": "any (opcional)",
  "deadline": "ISO-8601 (opcional)",
  "source_agent": "string"
}
```

To resume, resend a POST with `hitl_response`:

```json
{ "hitl_response": { "turn_id": "<interaction_id>", "value": "<respuesta>", "response_type": "string (opcional)" } }
```

**Authorization required** (`AuthRequiredEnvelope`): a tool needs OAuth.

```json
{
  "type": "auth_required",
  "provider": "jira",
  "tool_name": "string (opcional)",
  "auth_url": "string (opcional)",
  "scopes": ["..."],
  "message": "string legible"
}
```

> The Frontend must detect `status == "paused"` and `type == "auth_required"`
> BEFORE trying to parse an artifact. Both arrive with 200.

---

## 4. `STRUCTURED_TABLE` (FEAT-218)

### 4.1 What it is for

Return a **framework-agnostic table**: the minimal contract that any grid
library needs (column key, storage type, human-readable label and optional
format hint), plus the rows in `response.data`.

The presentation (column types) is **deterministic** (inferred from the actual
DataFrame via `base_column_types`). An optional LLM pass can **refine** the
format hints of ambiguous columns — but **the deterministic result always wins** and
hard types (`number`, `datetime`, `boolean`) are never mutated.

### 4.2 Models (`packages/ai-parrot/src/parrot/models/outputs.py`)

```python
class TableColumn(BaseModel):
    name: str               # column key — matches a key in every row
    type: str               # storage type (see §7)
    title: str              # human-readable label
    format: Optional[str]   # optional display hint (see §7); does NOT change the base type

class StructuredTableConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    columns: List[TableColumn]
    data: List[dict]               # INPUT-ONLY — excluded from the output, goes to response.data
    explanation: Optional[str]     # prose on how the table was derived (best-effort)
    total_rows: Optional[int]      # total rows BEFORE truncation
    truncated: bool = False        # True if trimmed to row_limit (default 1000)
```

### 4.3 Attributes — explanation

| Attribute (camelCase) | Type | Description |
|---|---|---|
| `columns` | `TableColumn[]` | Per-column contract. **Order matters** — use it as the column order in the grid. |
| `columns[].name` | `string` | Key that matches the key of each row object in `response.data`. |
| `columns[].type` | `string` | Storage type (§7). Determines parsing/alignment/sorting. |
| `columns[].title` | `string` | Human-readable header. |
| `columns[].format` | `string?` | Presentation hint (`currency`, `percent`, `email`, `uri`, `enum`, `id`, `code`). Only a **hint**; it does not change the base type. |
| `explanation` | `string?` | Prose description of the table's origin. Absent → omit. |
| `totalRows` | `int?` | Real total before truncation. Useful to indicate "showing 1000 of N". |
| `truncated` | `bool` | `true` if trimmed to `row_limit`. Show a truncation notice. |

### 4.4 Example payload

**Config** = `artifacts[].definition` (canonical) / `response.output` (compat today) — without `data`, camelCase:

```json
{
  "columns": [
    { "name": "id", "type": "integer", "title": "ID" },
    { "name": "price", "type": "number", "title": "Price", "format": "currency" },
    { "name": "created_at", "type": "datetime", "title": "Created" }
  ],
  "explanation": "Fetched from the orders table.",
  "totalRows": 5000,
  "truncated": true
}
```

**Rows** (in `response.data`):

```json
[
  { "id": 1, "price": 29.99, "created_at": "2026-06-01T10:30:00Z" },
  { "id": 2, "price": 49.99, "created_at": "2026-06-02T14:15:00Z" }
]
```

### 4.5 Frontend rendering (pseudocode)

```ts
function renderTable(resp) {
  const { config: cfg } = extractArtifact(resp);  // see §2.5 (canonical + compat)
  const rows = resp.data ?? [];                    // actual rows
  const grid = cfg.columns.map(c => ({
    field: c.name,
    header: c.title,
    formatter: pickFormatter(c.type, c.format),  // see §7
  }));
  if (cfg.truncated) showBanner(`Mostrando ${rows.length} de ${cfg.totalRows}`);
  return <DataGrid columns={grid} rows={rows} caption={cfg.explanation} />;
}
```

---

## 5. `STRUCTURED_CHART` (FEAT-215)

### 5.1 What it is for

Return a **library-agnostic chart config** (mirror of the frontend's
`AppChartConfig`). Here the **presentation is decided by the LLM** (chart type,
x/y columns, palette, title, description), while the **rows come
deterministically** from the DataFrame the agent computed (injected into
`response.data`).

**Anti-hallucination safeguard**: if the LLM picks a column that does not exist in
the actual data, the renderer applies a deterministic *fallback* (first
non-numeric column as `x`, first numeric as `y`) so the frontend **never**
receives an invalid config. Rows are **always** read from `response.data`,
never from `cfg.data`.

### 5.2 Model (`StructuredChartConfig`)

```python
ChartType = Literal["bar", "horizontalBar", "line", "area", "scatter",
                    "pie", "donut", "radar", "map"]
XAxisMode = Literal["category", "time"]

class StructuredChartConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    type: ChartType                       # chart type
    x: str                                # label/category column
    y: List[str]                          # one or more value columns (multi-series)
    stacked: Optional[bool]
    trendline: Optional[bool]
    split_series: Optional[bool]          # alias: splitSeries
    show_legend: Optional[bool]           # alias: showLegend
    x_axis_mode: Optional[XAxisMode]      # alias: xAxisMode
    palette: Optional[List[str]]          # list of hex colors
    color_by_sign: Optional[bool]         # alias: colorBySign
    negative_color: Optional[str]         # alias: negativeColor
    positive_color: Optional[str]         # alias: positiveColor
    x_axis_label: Optional[str]           # alias: xAxisLabel
    y_axis_label: Optional[str]           # alias: yAxisLabel
    map_name: Optional[str]               # alias: mapName (REQUIRED if type="map")
    title: Optional[str]
    description: Optional[str]
    data: List[dict]                      # INPUT-ONLY — excluded from the output
    data_variable: Optional[str]          # alias: dataVariable
```

### 5.3 Attributes — explanation

| Attribute (camelCase) | Type | Description |
|---|---|---|
| `type` | `enum` | `bar`, `horizontalBar`, `line`, `area`, `scatter`, `pie`, `donut`, `radar`, `map`. |
| `x` | `string` | Name of the categorical / label column. It is **a column name**, it must exist in `response.data`. |
| `y` | `string[]` | One or more value columns (multi-series). |
| `stacked` | `bool?` | Stack series (bar/area/line). |
| `trendline` | `bool?` | Show a trend line. |
| `splitSeries` | `bool?` | Render each `y` series as a separate chart. |
| `showLegend` | `bool?` | Show legend. |
| `xAxisMode` | `enum?` | `"category"` (labels) or `"time"` (requires ISO 8601 strings in `x`). |
| `palette` | `string[]?` | List of hex colors. |
| `colorBySign` | `bool?` | Color bars/points by sign (positive/negative). |
| `negativeColor` / `positiveColor` | `string?` | Hex for negative/positive values when `colorBySign=true`. |
| `xAxisLabel` / `yAxisLabel` | `string?` | Human-readable axis label (overrides the column name). |
| `mapName` | `string?` | GeoJSON map identifier. **REQUIRED if `type="map"`** (choropleth-type chart). |
| `title` | `string?` | Short title (≤1 line), card header. |
| `description` | `string?` | Short natural-language paragraph summarizing how to read the chart; shown as the message text. |
| `dataVariable` | `string?` | Name of the source DataFrame variable (disambiguates when there were multiple DataFrames). |

> Model validation: the **only** hard constraint is that `type="map"`
> requires `mapName`. The alignment of `x`/`y` with the actual columns is NOT
> validated in the model (the renderer reconciles it with a *fallback*). Trust
> that `x`/`y` point to existing columns in `response.data` when you receive it.

### 5.4 Example payload

**Config** = `artifacts[].definition` (canonical) / today in `response.output` and duplicated in `response.code` (see §2.5) — without `data`, camelCase:

```json
{
  "type": "bar",
  "x": "month",
  "y": ["sales"],
  "title": "Monthly Sales",
  "description": "Sales trend over the past 6 months showing steady growth.",
  "showLegend": true,
  "xAxisMode": "category",
  "palette": ["#1f77b4", "#ff7f0e"]
}
```

**Rows** (in `response.data`):

```json
[
  { "month": "Jan", "sales": 100 },
  { "month": "Feb", "sales": 120 },
  { "month": "Mar", "sales": 115 }
]
```

### 5.5 Multi-series and `time`

```json
{
  "type": "line",
  "x": "date",
  "y": ["revenue", "cost"],
  "xAxisMode": "time",
  "showLegend": true,
  "yAxisLabel": "USD"
}
```

With `xAxisMode="time"`, the `x` values in `response.data` will be ISO
8601 strings; parse them to dates on the time axis.

---

## 6. `STRUCTURED_MAP` (FEAT-221)

### 6.1 What it is for

Return **everything the frontend needs to paint a Leaflet map** — without
the backend rendering anything (invariant inherited from FEAT-219: *"the backend
returns only data, never a map"*).

The result is organized into **one layer per dataset**. Each layer brings its own
data schema (columns) + presentation schema (tooltip, label,
`dataShape`) + capping metadata. At the map level: viewport, query
geometry, base layer hint and prose.

Same as table: **deterministic** presentation (from `DatasetSpatialProfile`) +
optional LLM refine (deterministic wins). Rows/features go to
`response.data` as **a list of per-layer payloads**.

### 6.2 Models

```python
class MapColumn(BaseModel):           # same vocabulary as TableColumn
    name: str
    type: str
    title: str
    format: Optional[str]

class MapLayer(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    layer: str                            # Leaflet layer id / GeoJSON source discriminator
    columns: List[MapColumn]
    tooltip_template: Optional[str]       # alias: tooltipTemplate (str.format_map over properties)
    label_field: Optional[str]            # alias: labelField (property key for the marker label)
    data_shape: Literal["geojson","rows"] # alias: dataShape (payload shape of this layer)
    total_count: int = 0                  # alias: totalCount (real count before capping)
    capped: bool = False                  # True if truncated to the per-dataset cap
    geodesic: Optional[bool]              # True = geodesic path; False = spherical approx.

class MapViewport(BaseModel):
    bbox: Optional[List[float]]           # [min_lng, min_lat, max_lng, max_lat]
    center: Optional[Tuple[float,float]]  # (lat, lng) — optional, the front can derive it from bbox
    zoom: Optional[int]

class MapQuery(BaseModel):
    point: Tuple[float, float]            # (lat, lng) — echo of the SpatialFilterSpec
    radius: float
    unit: Literal["mi","km","m"]

class StructuredMapConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    layers: List[MapLayer]
    data: List[dict]                      # INPUT-ONLY — excluded; goes to response.data
    viewport: Optional[MapViewport]
    query: Optional[MapQuery]
    base_layer: Optional[str]             # alias: baseLayer (tile/style hint)
    title: Optional[str]
    description: Optional[str]
    explanation: Optional[str]            # longer prose about the spatial result
```

### 6.3 Attributes — explanation

**Map level (`StructuredMapConfig`)**

| Attribute (camelCase) | Type | Description |
|---|---|---|
| `layers` | `MapLayer[]` | One layer per dataset. |
| `viewport` | `MapViewport?` | Framing hints, computed from the features' bounds. |
| `query` | `MapQuery?` | Echo of the original spatial query (point/radius/unit). Useful for drawing the search circle. |
| `baseLayer` | `string?` | Tile/style hint (e.g. OSM tile URL or Mapbox style id). |
| `title` | `string?` | Short map title. |
| `description` | `string?` | Brief description. |
| `explanation` | `string?` | Longer prose explanation of the spatial result. |

**Layer level (`MapLayer`)**

| Attribute (camelCase) | Type | Description |
|---|---|---|
| `layer` | `string` | Layer id / source discriminator. Matches the entry in `response.data`. |
| `columns` | `MapColumn[]` | Per-column contract over `feature.properties` (same vocabulary as table). |
| `tooltipTemplate` | `string?` | `str.format_map` template for a **client-side** tooltip over the properties (compact — not per-item pre-rendered strings). |
| `labelField` | `string?` | Property key for the marker label. |
| `dataShape` | `enum` | `"geojson"` (FeatureCollection as is) or `"rows"` (flat rows + geometry ref). |
| `totalCount` | `int` | Real per-dataset count **before** capping. |
| `capped` | `bool` | `true` if this layer was truncated to the cap. |
| `geodesic` | `bool?` | `true` = geodesic path; `false` = spherical approximation. |

**`MapViewport`**: `bbox` = `[min_lng, min_lat, max_lng, max_lat]`; `center` =
`(lat, lng)`; `zoom` = optional integer.

**`MapQuery`**: `point` = `(lat, lng)`; `radius` = number; `unit` = `"mi"|"km"|"m"`.

### 6.4 Shape of `response.data` (maps)

Unlike table/chart (flat list of rows), in maps `response.data` is
**a list of payloads, one per layer** (verified in
`structured_map.py`):

```json
[
  {
    "dataset": "places",
    "layer": "places",
    "data_shape": "geojson",
    "payload": {
      "type": "FeatureCollection",
      "features": [
        {
          "type": "Feature",
          "geometry": { "type": "Point", "coordinates": [-74.0, 40.71] },
          "properties": { "name": "Place A", "rating": 4.8 }
        }
      ]
    }
  }
]
```

When `dataShape="rows"`, the `payload` is not a FeatureCollection but:

```json
{
  "rows": [
    { "name": "Place A", "rating": 4.8, "_geometry": { "type": "Point", "coordinates": [-74.0, 40.71] } }
  ],
  "truncated": false
}
```

That is: each flat row **includes a `_geometry` key** with the GeoJSON
geometry, so the frontend can place the marker without a FeatureCollection.

### 6.5 Example config payload

**Config** = `artifacts[].definition` (canonical) / `response.output` (compat today) — without `data`, camelCase:

```json
{
  "layers": [
    {
      "layer": "places",
      "columns": [
        { "name": "name", "type": "string", "title": "Place Name" },
        { "name": "rating", "type": "number", "title": "Rating" }
      ],
      "tooltipTemplate": "{name} — Rating: {rating}",
      "labelField": "name",
      "dataShape": "geojson",
      "totalCount": 125,
      "capped": false,
      "geodesic": true
    }
  ],
  "viewport": {
    "bbox": [-74.01, 40.71, -73.99, 40.72],
    "center": [40.715, -74.0],
    "zoom": 13
  },
  "query": { "point": [40.715, -74.0], "radius": 5.0, "unit": "mi" },
  "title": "Nearby Places",
  "description": "Popular places within 5 miles of your location.",
  "explanation": "Found 125 places matching your spatial filter."
}
```

### 6.6 Frontend rendering (Leaflet pseudocode)

```ts
function renderMap(resp) {
  const { config: cfg } = extractArtifact(resp);  // see §2.5 (canonical + compat)
  const payloads = resp.data ?? [];               // [{dataset, layer, data_shape, payload}, ...]
  const map = L.map('map');

  if (cfg.viewport?.bbox) {
    const [minLng, minLat, maxLng, maxLat] = cfg.viewport.bbox;
    map.fitBounds([[minLat, minLng], [maxLat, maxLng]]);
  }

  for (const layerCfg of cfg.layers) {
    const entry = payloads.find(p => p.layer === layerCfg.layer);
    const features = layerCfg.dataShape === 'geojson'
      ? entry.payload.features
      : entry.payload.rows.map(rowToFeature);   // use _geometry
    const leafletLayer = L.geoJSON(features, {
      onEachFeature: (f, lyr) => {
        if (layerCfg.tooltipTemplate)
          lyr.bindTooltip(formatTemplate(layerCfg.tooltipTemplate, f.properties));
      }
    }).addTo(map);
    if (layerCfg.capped) showBanner(`${layerCfg.layer}: mostrando cap de ${layerCfg.totalCount}`);
  }

  if (cfg.query) drawSearchCircle(map, cfg.query);   // point + radius + unit
}
```

> **Tooltips**: `tooltipTemplate` is a Python `str.format_map`-style template
> (`{key}` placeholders filled from `feature.properties`). The
> frontend must implement the replacement of `{field}` with
> `feature.properties[field]`. It is deliberately compact so as not to inflate
> the payload with thousands of strings.

---

## 7. Shared vocabularies

### 7.1 Storage types (`columns[].type`)

Shared by `TableColumn` and `MapColumn`. Inferred deterministically from the
actual DataFrame (`base_column_types`).

| `type` | Meaning | Render suggestion |
|---|---|---|
| `string` | Text | Left alignment |
| `integer` | Integers | Right alignment, no decimals |
| `number` | Floats/decimals | Right alignment, decimals/locale |
| `boolean` | true/false | Check / chip |
| `date` | Date without time (ISO 8601) | Local date format |
| `datetime` | Date + time (ISO 8601) | Local datetime format |
| `time` | Time of day | Time format |
| `duration` | Time interval | Duration format |
| `any` | Unknown / fallback | Raw text |

### 7.2 Format hints (`columns[].format`)

**Optional** and only applied to ambiguous columns by the LLM refine pass
(hard types never change). They are a **display hint**, they do not alter the
base type.

| `format` | Suggested render |
|---|---|
| `currency` | Currency symbol + separators |
| `percent` | `%` suffix |
| `email` | `mailto:` link |
| `uri` | Hyperlink |
| `enum` | Categorical chip / badge |
| `id` | Monospaced, copyable |
| `code` | Monospaced |

### 7.3 snake_case → camelCase alias map

The output JSON uses **camelCase**. Quick reference:

| Python (snake_case) | API (camelCase) |
|---|---|
| `split_series` | `splitSeries` |
| `show_legend` | `showLegend` |
| `x_axis_mode` | `xAxisMode` |
| `x_axis_label` | `xAxisLabel` |
| `y_axis_label` | `yAxisLabel` |
| `color_by_sign` | `colorBySign` |
| `negative_color` | `negativeColor` |
| `positive_color` | `positiveColor` |
| `map_name` | `mapName` |
| `data_variable` | `dataVariable` |
| `tooltip_template` | `tooltipTemplate` |
| `label_field` | `labelField` |
| `data_shape` | `dataShape` |
| `total_count` | `totalCount` |
| `base_layer` | `baseLayer` |
| `total_rows` | `totalRows` |

---

## 8. Streaming

If you send `"stream": true`, AgentTalk responds with **HTTP chunked transfer**
(not classic SSE). Headers:

```
Content-Type: text/plain; charset=utf-8
Transfer-Encoding: chunked
X-Parrot-Stream: chunked-aimessage
X-Accel-Buffering: no
```

Stream format:

1. **Text chunks** — the textual content is emitted as is while it is generated.
2. **Binary separator** — the sentinel sequence `\n\x00`.
3. **Final envelope** — a JSON with the `AIMessage` metadata (model, provider,
   session_id, turn_id, usage, sources, tool_calls).

Client-side parsing: accumulate bytes until you find `\n\x00`; **everything before** is
the streamed text, **everything after** is the final JSON envelope.

> **Recommendation for structured artifacts**: use the **non-streaming** mode
> (`stream:false`). The config + data payload is a single object that you need
> complete to render; streaming is designed for incremental text, not
> for structured configs.

---

## 9. Errors, edge cases and degradation

### 9.1 Missing config (`null`)

The renderer **never raises**; on failure it returns `(None, error_message)`. In
the envelope this translates into a missing/null config and an error text in
the prose. **The frontend must handle a `null` config** and fall back to showing the
explanatory text (`response`) or a graceful error message.

### 9.2 Empty data

- Table/chart: `response.data` may be `[]`. Show an empty state.
- Map: a layer with zero features is preserved as an empty layer (not dropped);
  `columns` may come from the profile even if there are no features.

### 9.3 Truncation

- Table: `truncated:true` + `totalRows` → "showing N of total" banner.
- Map: per layer `capped:true` + `totalCount` → per-layer banner. The default
  `row_limit` of the table renderer is 1000.

### 9.4 HTTP codes

| Code | When |
|---|---|
| `200 OK` | Successful chat, **or** `PausedEnvelope` (HITL), **or** `AuthRequiredEnvelope`. |
| `202 Accepted` | PUT (file upload / slug in background). |
| `204 No Content` | PATCH with no refresh result. |
| `400 Bad Request` | Missing `agent_name`/`query`, invalid JSON. |
| `403 Forbidden` | PBAC denies access, or unauthenticated HITL resume. |
| `404 Not Found` | Agent not found. |
| `500 Internal Server Error` | LLM/tool error, corrupt HITL state. |

### 9.5 Recommended check order on the client

```ts
const r = await postChat(...);
if (r.status === 'paused')        return handleHITL(r);          // §3.3
if (r.type === 'auth_required')   return handleAuth(r);          // §3.3
const art = extractArtifact(r);                                   // §2.5
if (!art) return renderText(r.response ?? r.output);             // no config → text
switch (art.type) {                                               // "chart" | "map" | "table"
  case 'table': return renderTable(r);
  case 'chart': return renderChart(r);
  case 'map':   return renderMap(r);
  default:      return renderText(r.response ?? r.output);
}
```

> The `switch` is done on `art.type` (`ArtifactType` vocabulary), which is
> equivalent to switching on `output_mode`. Use whichever is available depending on the
> contract (canonical → `art.type`; compat → `output_mode`).

---

## 10. Frontend integration checklist

- [ ] Send an explicit `output_mode` (`structured_table|chart|map`) in the POST.
- [ ] Keep `session_id` stable across turns; use `message_id` for dedup.
- [ ] **Read the config with `extractArtifact()` (§2.5)**: prefer `artifacts[].definition` (canonical) and fall back to `response.output` / `response.code` (current compat). Combine with the rows from `response.data` — they do not arrive merged.
- [ ] Treat all config field names as **camelCase**.
- [ ] Detect `status:"paused"` and `type:"auth_required"` (both arrive with 200) **before** parsing artifacts.
- [ ] Handle a `null` config (graceful degradation → show `response`).
- [ ] Table: respect the order of `columns`; map `type`/`format` to formatters; handle `truncated`/`totalRows`.
- [ ] Chart: switch on `type`; support multi-series (`y[]`); handle `xAxisMode:"time"`; `type:"map"` requires `mapName`.
- [ ] Map: match `cfg.layers[].layer` with `response.data[].layer`; support `dataShape` `geojson` and `rows` (with `_geometry`); render `tooltipTemplate` client-side; frame with `viewport.bbox`; draw `query` (point/radius/unit).
- [ ] Streaming is discouraged for structured artifacts; if used, parse with the `\n\x00` sentinel.
- [ ] **(FEAT-473, optional)** If you consume the native A2UI envelope, read
      `response.a2ui_envelope` when present (§2.6); remember that
      `response.output` only gains the `surfaceId` key — nothing else changes.
      If your backend/BFF still expects `artifacts[].definition` v1, use the
      `artifact_definition_to_legacy` shim (§2.6) until 0.32.

---

## Appendix A — Verification anchors in the code

| Component | Path |
|---|---|
| `OutputMode` enum | `packages/ai-parrot/src/parrot/models/outputs.py:37` |
| `StructuredChartConfig` | `packages/ai-parrot/src/parrot/models/outputs.py:309` |
| `TableColumn` / `StructuredTableConfig` | `packages/ai-parrot/src/parrot/models/outputs.py:483,520` |
| `MapColumn`/`MapLayer`/`MapViewport`/`MapQuery`/`StructuredMapConfig` | `packages/ai-parrot/src/parrot/models/outputs.py:592–820` |
| `ArtifactType` enum | `packages/ai-parrot/src/parrot/storage/models.py:244` |
| Common contract mixin | `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_base.py` |
| Chart renderer | `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py` |
| Table renderer | `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_table.py` |
| Map renderer | `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_map.py` |
| Parity tests | `packages/ai-parrot/tests/outputs/formats/test_structured_parity.py` |
| Config/data routing (PandasAgent) | `packages/ai-parrot/src/parrot/bots/data.py:1561-1606` (map/chart staging), `:1869-1872` (final assignment to `output`/`response`) |
| Chart renderer input read | `packages/ai-parrot-visualizations/.../structured_chart.py` (steps 1a/1b: reads `response.code`) |
| Persisted `Artifact` model (mirror of `artifacts[].definition`) | `packages/ai-parrot/src/parrot/storage/models.py:273` (`from_chart_config`, `definition`) |
| AgentTalk handler | `packages/ai-parrot-server/src/parrot/handlers/agent.py` |
| `AIMessage` (envelope) | `packages/ai-parrot/src/parrot/models/responses.py:72` |
| FEAT-215 spec | `sdd/specs/structured-chart-output.spec.md` |
| FEAT-218 spec | `sdd/specs/structured-table.spec.md` |
| FEAT-221 spec | `sdd/specs/structured-map-output.spec.md` |
| FEAT-223 spec (common contract) | `sdd/specs/structured-artifact-contract.spec.md` |
| A2UI v1.0 adapter (FEAT-473) | `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/structured.py` |
| `_route_envelope` hook (dual-emit, FEAT-473) | `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_base.py` |
| `artifacts[]` v1↔v2 compatibility shim | `packages/ai-parrot/src/parrot/outputs/a2ui/compat.py` |
| `attach_structured_artifact` helper | `packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py` |
| FEAT-473 spec | `sdd/specs/a2ui-v1-structured-outputs.spec.md` |
| FEAT-473 migration note | `wiki/migration/feat-473-structured-a2ui.md` |

---

## Appendix B — Validated A2UI v1.0 envelope examples

The three envelopes below are **real** output of
`parrot.outputs.a2ui.adapters.structured` (not handwritten) — each one
passes `validate_envelope(origin=TOOL)` and, in its "lowered" form (see
`adapters/structured.py`'s `_validate_wire`), `validate_message` against the
official JSON Schema `agent_to_renderer.json`.

### B.1 — Chart

```json a2ui-envelope
{
  "version": "v1.0",
  "createSurface": {
    "surfaceId": "structured_chart-a1b2c3d4",
    "catalogId": "https://parrot.dev/catalogs/v1",
    "sendDataModel": false,
    "components": [
      {
        "id": "root",
        "component": "Chart",
        "type": "bar",
        "x": "month",
        "y": ["sales"],
        "showLegend": true,
        "xAxisMode": "category",
        "palette": ["#1f77b4", "#ff7f0e"],
        "title": "Monthly Sales",
        "description": "Sales trend over the past 6 months showing steady growth.",
        "data": { "path": "/rows" }
      }
    ],
    "dataModel": {
      "rows": [
        { "month": "Jan", "sales": 100 },
        { "month": "Feb", "sales": 120 },
        { "month": "Mar", "sales": 115 }
      ]
    }
  }
}
```

### B.2 — Table

```json a2ui-envelope
{
  "version": "v1.0",
  "createSurface": {
    "surfaceId": "structured_table-b2c3d4e5",
    "catalogId": "https://parrot.dev/catalogs/v1",
    "sendDataModel": false,
    "components": [
      {
        "id": "root",
        "component": "DataTable",
        "columns": [
          { "name": "id", "type": "integer", "title": "ID", "format": null },
          { "name": "price", "type": "number", "title": "Price", "format": "currency" }
        ],
        "truncated": false,
        "totalRows": 2,
        "data": { "path": "/rows" }
      }
    ],
    "dataModel": {
      "rows": [
        { "id": 1, "price": 29.99 },
        { "id": 2, "price": 49.99 }
      ]
    }
  }
}
```

### B.3 — Map (multi-layer)

```json a2ui-envelope
{
  "version": "v1.0",
  "createSurface": {
    "surfaceId": "structured_map-c3d4e5f6",
    "catalogId": "https://parrot.dev/catalogs/v1",
    "sendDataModel": false,
    "components": [
      {
        "id": "root",
        "component": "Map",
        "layers": [
          {
            "layer": "places",
            "columns": [
              { "name": "name", "type": "string", "title": "Place Name", "format": null },
              { "name": "rating", "type": "number", "title": "Rating", "format": null }
            ],
            "tooltipTemplate": "{name} — Rating: {rating}",
            "labelField": "name",
            "dataShape": "geojson",
            "totalCount": 1,
            "capped": false,
            "geodesic": null,
            "markerColor": null,
            "data": { "path": "/layers/0/features" }
          }
        ],
        "viewport": {
          "bbox": [-74.01, 40.71, -73.99, 40.72],
          "center": [40.715, -74.0],
          "zoom": 13
        },
        "title": "Nearby Places",
        "description": "Popular places within 5 miles of your location."
      }
    ],
    "dataModel": {
      "layers": [
        {
          "features": [
            {
              "name": "Place A",
              "rating": 4.8,
              "_geometry": { "type": "Point", "coordinates": [-74.0, 40.71] }
            }
          ]
        }
      ]
    }
  }
}
```

---

*Document generated for the AI-Parrot Frontend team. Source: code on the
`dev` branch as of 2026-06-04, extended for FEAT-473 (A2UI v1.0 envelope,
dual-emit) as of 2026-08-29. For changes to the field names of the map
contract (pending frontend confirmation in FEAT-221 §8), coordinate with the
backend before fixing types in the client.*
