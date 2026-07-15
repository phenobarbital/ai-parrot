---
type: Wiki Overview
title: Guía Técnica de Artefactos Estructurados para Frontend
id: doc:docs-frontend-structured-artifacts-frontend-guide-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: '1. [Modelo mental: el contrato común](#1-modelo-mental-el-contrato-común)'
---

# Guía Técnica de Artefactos Estructurados para Frontend

**Audiencia**: equipo de Frontend que construye la UI de visualización (tablas, gráficos y mapas) sobre AI-Parrot.
**Ámbito**: `STRUCTURED_TABLE` (FEAT-218), `STRUCTURED_CHART` (FEAT-215) y `STRUCTURED_MAP` (FEAT-221), homologados bajo el contrato común de FEAT-223 (`structured-artifact-contract`).
**Endpoint**: AgentTalk (`/api/v1/agents/chat/...`).

> Este documento está fundamentado en el código real del repositorio. Las rutas
> de archivo y números de línea referenciados son anclas de verificación
> (anti-alucinación) y pueden moverse con el tiempo; el contrato semántico es el
> que importa.

---

## 0. Índice

1. [Modelo mental: el contrato común](#1-modelo-mental-el-contrato-común)
2. [El envelope de respuesta de AgentTalk](#2-el-envelope-de-respuesta-de-agenttalk)
   - [2.5 Ubicación canónica de la config (contrato definitivo)](#25-ubicación-canónica-de-la-config-contrato-definitivo)
3. [Endpoints de AgentTalk](#3-endpoints-de-agenttalk)
4. [STRUCTURED_TABLE](#4-structured_table-feat-218)
5. [STRUCTURED_CHART](#5-structured_chart-feat-215)
6. [STRUCTURED_MAP](#6-structured_map-feat-221)
7. [Vocabularios compartidos (tipos y formatos)](#7-vocabularios-compartidos)
8. [Streaming](#8-streaming)
9. [Errores, casos límite y degradación](#9-errores-casos-límite-y-degradación)
10. [Checklist de integración Frontend](#10-checklist-de-integración-frontend)

---

## 1. Modelo mental: el contrato común

Las tres estructuras (`table`, `chart`, `map`) comparten **un único contrato de
envelope** (FEAT-223). Entenderlo una vez aplica a las tres.

Cada artefacto se divide en **dos mitades**:

| Mitad | Qué es | Quién la produce | Dónde viaja (**contrato canónico**) |
|---|---|---|---|
| **Presentación (config / `definition`)** | Cómo pintar: tipo de gráfico, columnas, ejes, tooltips, viewport, paleta… | LLM y/o reglas deterministas | Dentro del envelope de artefacto **`response.artifacts[]`**, en el campo `definition` — **sin las filas** |
| **Datos (rows)** | Las filas / features reales | Determinista (el DataFrame que computó el agente, o el resultado espacial) | En el campo **`response.data`** |

> **Lee primero la [§2.5 — Ubicación canónica de la config](#25-ubicación-canónica-de-la-config-contrato-definitivo).**
> El **contrato canónico implementado (FEAT-224)** es el envelope de artefacto en
> `response.artifacts[]`. La config viaja en `artifacts[].definition` (camelCase,
> sin `data`). `response.output` sigue como mirror depreciado (G6); `response.code`
> ya no lleva config en el path chart. Ver §2.5 para el estado completo.

Reglas invariantes que el backend **garantiza** (verificado en
`packages/ai-parrot-visualizations/.../structured_base.py` y en los tests de
homologación `tests/outputs/formats/test_structured_parity.py`):

1. **La config (`definition`) NUNCA incluye la clave `data`.** Se serializa con
   `model_dump(mode="json", by_alias=True, exclude={"data"})`. Si ves `data`
   dentro de la config, es un bug.
2. **Las filas SIEMPRE van en `response.data`.** Nunca dentro de la config.
3. **El renderer nunca lanza excepción.** En caso de fallo devuelve
   `(None, mensaje_de_error)` — la config será `null` y el texto de error queda
   disponible. El frontend debe contemplar config ausente.
4. **Nombres de campo en `camelCase`** en el JSON de salida (gracias a
   `populate_by_name=True` + alias). Internamente el modelo Python usa
   `snake_case`, pero **lo que recibes por la API es camelCase**.
5. **Una explicación en prosa** acompaña al artefacto (el `wrapped` / `response`),
   pensada para mostrarse como el mensaje de texto junto a la visualización.

```
┌─────────────────────────── Respuesta AgentTalk (canónico) ────────────────────┐
│  artifacts[] → [{ type, artifactId, definition }]  ← CONFIG (cómo pintar)      │
│                  definition = config SIN filas, camelCase                      │
│  data        → ROWS / FEATURES (qué pintar)                                    │
│  response    → Texto explicativo (prosa para el usuario)                       │
│  output_mode → "structured_table" | "structured_chart" | "structured_map"     │
│  artifact_id → id del artefacto principal del turno                            │
│  metadata    → modelo, provider, tokens, session_id, turn_id, ...              │
└────────────────────────────────────────────────────────────────────────────────┘
```

> **Implicación clave para el Frontend**: para renderizar cualquier artefacto
> estructurado necesitas combinar **dos campos**: la config (`definition` del
> artefacto) + `response.data` (filas). No vienen pre-mezclados (a propósito:
> mantiene el payload acotado y permite hasta ~879k features sin inflar la config).

**Definición de `OutputMode`** (`packages/ai-parrot/src/parrot/models/outputs.py:37`):

```python
class OutputMode(str, Enum):
    ...
    STRUCTURED_CHART = "structured_chart"  # FEAT-215 — config de gráfico agnóstica de librería
    STRUCTURED_TABLE = "structured_table"  # FEAT-218 — config de tabla agnóstica de framework
    STRUCTURED_MAP   = "structured_map"    # FEAT-221 — config de mapa agnóstica de framework
```

**`ArtifactType`** (cuando el artefacto se persiste —
`packages/ai-parrot/src/parrot/storage/models.py:244`):

```python
class ArtifactType(str, Enum):
    CHART = "chart"
    MAP = "map"            # añadido por FEAT-223 / TASK-1457
    CANVAS = "canvas"
    INFOGRAPHIC = "infographic"
    DATAFRAME = "dataframe"
    EXPORT = "export"
```

---

## 2. El envelope de respuesta de AgentTalk

Todas las respuestas de chat (formato JSON) se serializan desde el modelo
`AIMessage` (`packages/ai-parrot/src/parrot/models/responses.py:72`). El
envelope JSON que recibe el frontend tiene esta forma:

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

### 2.1 Campos relevantes para artefactos estructurados

| Campo | Para artefactos estructurados |
|---|---|
| `output_mode` | **Discriminador de modo**. `structured_table\|chart\|map`. Conmuta tu renderer por este valor. |
| `artifacts[]` | **Contenedor canónico de la config** (`{type, artifactId, definition}`). `definition` = config sin `data`. Ver §2.5. |
| `artifact_id` | Id del **artefacto principal** del turno (para recuperarlo / referenciarlo). |
| `data` | Contiene las **filas** (table/chart) o **payloads por capa** (map). |
| `response` | Texto en prosa para mostrar al usuario junto a la visualización. |
| `output` | Compat: hoy el backend aún deja aquí la config serializada (ver §2.5). |
| `code` | **Reservado a código interpretable** (Python/TS) o `null`. **No** debe llevar config (ver §2.5). |

---

### 2.5 Ubicación canónica de la config (contrato definitivo)

> Esta sección es el **acuerdo de contrato** entre backend y frontend para FEAT-223.
> Decidida explícitamente; sustituye a cualquier inferencia previa sobre `output`/`code`.

#### Contrato canónico (OBJETIVO — al que debe converger el frontend)

La config de **todo** artefacto estructurado viaja en **`response.artifacts[]`**,
un envelope por artefacto cuya forma espeja el modelo persistido `Artifact`
(`storage/models.py`):

```json
{
  "artifacts": [
    {
      "type": "chart",                  // "chart" | "map" | "table"  (ArtifactType)
      "artifactId": "art_abc123",       // id estable del artefacto
      "definition": {                   // = la CONFIG, camelCase, SIN la clave data
        "type": "bar",
        "x": "month",
        "y": ["sales"],
        "title": "Monthly Sales"
      }
    }
  ],
  "data": [ { "month": "Jan", "sales": 100 } ],   // filas/features (o payloads por capa en map)
  "response": "Las ventas crecieron de forma sostenida...",  // prosa
  "output_mode": "structured_chart",
  "artifact_id": "art_abc123"           // eco del artefacto principal del turno
}
```

Reglas del contrato canónico:

1. **`artifacts[].definition` es la única fuente de verdad de la config.** Es el
   `model_dump(by_alias=True, exclude={"data"})` del `Structured*Config`
   correspondiente. CamelCase, sin filas.
2. **`artifacts[].type`** usa el vocabulario de `ArtifactType`: `"chart"`,
   `"map"`, `"table"`. Es el discriminador fino que te dice qué forma tiene
   `definition` (`StructuredChartConfig` / `StructuredMapConfig` /
   `StructuredTableConfig`).
3. **`response.data`** sigue llevando las filas (table/chart) o los payloads por
   capa (map). Igual que antes.
4. **`response.code`** queda **`null`** salvo que el turno produzca código real
   destinado a ser interpretado por el frontend (p.ej. un snippet TypeScript) o
   el código de análisis pandas. **Nunca** lleva la config del artefacto.
5. **`artifact_id`** (nivel raíz) replica el id del artefacto principal del turno,
   para deep-link / persistencia.

> **Nota sobre `ArtifactType.TABLE`**: a fecha de hoy `ArtifactType` define
> `CHART` y `MAP` pero **no** `TABLE` (`storage/models.py:244`). El contrato
> canónico asume que se añadirá `TABLE = "table"` como parte del refactor de
> homologación. Hasta entonces, una tabla podría llegar tipada como `dataframe`
> — confírmalo con backend antes de fijar el enum en el cliente.

#### Estado actual del backend — contrato implementado (FEAT-224)

El pipeline (`bots/data.py` + `structured_chart.py`) implementa el contrato
canónico desde **FEAT-224**. Los tres modos producen:

| Modo | `response.output` | `response.data` | `response.code` | `artifacts[]` |
|---|---|---|---|---|
| `structured_table` | ⚠️ mirror depreciado (G6) — config tabla (dict) | filas (records) | código pandas o `null` | ✅ **`[{type:"table", artifactId, definition}]`** |
| `structured_map` | ⚠️ mirror depreciado (G6) — config mapa (dict) | payloads por capa | normalmente `null` | ✅ **`[{type:"map", artifactId, definition}]`** |
| `structured_chart` | ⚠️ mirror depreciado (G6) — config reconciliada | filas (records) | ✅ `null` (config ya no duplicada) | ✅ **`[{type:"chart", artifactId, definition}]`** |

Contrato implementado:

- **Config**: canónicamente en `response.artifacts[].definition` (camelCase, sin `data`).
- **Chart `code`**: `null` — la config ya no se duplica aquí (FEAT-224 G3); el
  `StructuredChartRenderer` lee su input de `response.output`/`structured_output`.
- **`artifacts[]`/`artifact_id`**: poblados para los tres modos estructurados.
- **`response.output`**: sigue espejando la config durante la ventana de migración
  (G6) para no romper consumidores existentes; **deprecado** — migrar a `artifacts[]`.
- **Persistencia (FEAT-103)**: el handler auto-save persiste `definition` (la config,
  no las filas) con `ArtifactType` correcto por modo.

#### Estrategia de lectura recomendada para el Frontend (resiliente a la migración)

Implementa un **selector de config tolerante** que prefiera el contrato canónico
y caiga al estado actual, para no romperte ni hoy ni tras el refactor:

```ts
function extractArtifact(resp) {
  // 1) Canónico: artifacts[] con definition
  const art = (resp.artifacts ?? []).find(a => a.definition);
  if (art) return { type: art.type, config: art.definition };

  // 2) Compat actual: config en response.output, discriminada por output_mode
  const typeByMode = {
    structured_chart: "chart",
    structured_map:   "map",
    structured_table: "table",
  };
  const type = typeByMode[resp.output_mode];
  if (type && resp.output && typeof resp.output === "object") {
    return { type, config: resp.output };
  }

  // 3) Último recurso (chart legacy): config en response.code
  if (resp.output_mode === "structured_chart" && resp.code && typeof resp.code === "object") {
    return { type: "chart", config: resp.code };
  }
  return null;   // sin config → degradar a texto (resp.response)
}

// Las filas SIEMPRE de response.data, en cualquiera de los dos contratos:
const rows = resp.data ?? [];
```

> Cuando el backend complete el refactor, la rama (1) cubrirá el 100% de los casos
> y podrás retirar (2) y (3). Hasta entonces, mantén las tres.

---

## 3. Endpoints de AgentTalk

Handler: `AgentTalk(BaseView)` en
`packages/ai-parrot-server/src/parrot/handlers/agent.py`. Está protegido por
`@is_authenticated()` y `@user_session()`.

Registro de rutas (`manager.py`):

```python
router.add_view('/api/v1/agents/chat/{agent_id}', AgentTalk)
router.add_view('/api/v1/agents/chat/{agent_id}/{method_name}', AgentTalk)
```

| Método | Ruta | Propósito |
|---|---|---|
| `POST` | `/api/v1/agents/chat/{agent_id}` | **Conversar** con el agente (la ruta principal para producir artefactos). |
| `POST` | `/api/v1/agents/chat/{agent_id}/{method_name}` | Invocar un método custom del agente. |
| `PATCH` | `/api/v1/agents/chat/{agent_id}` | Configurar tools / servidores MCP de la sesión. |
| `PUT` | `/api/v1/agents/chat/{agent_id}` | Subir datos o consultar slugs. |
| `GET` | `/api/v1/agents/chat/` | Info / debug / listado de servidores MCP. |

### 3.1 Autenticación y cabeceras

```
Authorization: Bearer <token>
Content-Type: application/json        (POST/PATCH/PUT)
Accept: application/json | text/html | text/markdown | text/plain   (opcional)
```

Negociación de formato (prioridad): parámetro explícito `output_mode`/`output_format`
en el body > query string `?output_format=` > cabecera `Accept` > por defecto `json`.

Para artefactos estructurados, **trabaja siempre en JSON** y fija `output_mode`
explícitamente.

### 3.2 `POST /api/v1/agents/chat/{agent_id}` — petición

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

Campos clave para el Frontend de visualización:

- **`output_mode`**: fija el tipo de artefacto que quieres (`structured_table`,
  `structured_chart`, `structured_map`). Si lo omites, el agente decide su modo
  por defecto y podrías no recibir una config estructurada.
- **`session_id`**: mantén el mismo valor entre turnos para conservar el hilo de
  conversación.
- **`message_id`**: id generado por el cliente para deduplicar reintentos.

### 3.3 Respuestas especiales (no son artefactos, pero el Frontend debe manejarlas)

El POST puede devolver, con **HTTP 200**, envelopes que NO son una respuesta de
chat normal:

**HITL en pausa** (`PausedEnvelope`, FEAT-204): el agente necesita input humano.

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

Para reanudar, reenvía un POST con `hitl_response`:

```json
{ "hitl_response": { "turn_id": "<interaction_id>", "value": "<respuesta>", "response_type": "string (opcional)" } }
```

**Autorización requerida** (`AuthRequiredEnvelope`): una tool necesita OAuth.

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

> El Frontend debe detectar `status == "paused"` y `type == "auth_required"`
> ANTES de intentar parsear un artefacto. Ambas llegan con 200.

---

## 4. `STRUCTURED_TABLE` (FEAT-218)

### 4.1 Para qué sirve

Devolver una **tabla agnóstica de framework**: el contrato mínimo que cualquier
librería de grid necesita (clave de columna, tipo de almacenamiento, etiqueta
legible y pista de formato opcional), más las filas en `response.data`.

La presentación (tipos de columna) es **determinista** (se infiere del DataFrame
real vía `base_column_types`). Una pasada LLM opcional puede **refinar** las
pistas de formato de columnas ambiguas — pero **lo determinista siempre gana** y
los tipos duros (`number`, `datetime`, `boolean`) nunca se mutan.

### 4.2 Modelos (`packages/ai-parrot/src/parrot/models/outputs.py`)

```python
class TableColumn(BaseModel):
    name: str               # clave de columna — coincide con una key en cada fila
    type: str               # tipo de almacenamiento (ver §7)
    title: str              # etiqueta legible
    format: Optional[str]   # pista de display opcional (ver §7); NO cambia el tipo base

class StructuredTableConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    columns: List[TableColumn]
    data: List[dict]               # INPUT-ONLY — excluido del output, va a response.data
    explanation: Optional[str]     # prosa de cómo se derivó la tabla (best-effort)
    total_rows: Optional[int]      # total de filas ANTES de truncar
    truncated: bool = False        # True si se recortó al row_limit (default 1000)
```

### 4.3 Atributos — explicación

| Atributo (camelCase) | Tipo | Descripción |
|---|---|---|
| `columns` | `TableColumn[]` | Contrato por columna. **El orden importa** — úsalo como orden de columnas en el grid. |
| `columns[].name` | `string` | Clave que coincide con la key de cada objeto fila en `response.data`. |
| `columns[].type` | `string` | Tipo de almacenamiento (§7). Determina parseo/alineación/orden. |
| `columns[].title` | `string` | Cabecera legible para humanos. |
| `columns[].format` | `string?` | Pista de presentación (`currency`, `percent`, `email`, `uri`, `enum`, `id`, `code`). Solo una **pista**; no cambia el tipo base. |
| `explanation` | `string?` | Descripción en prosa del origen de la tabla. Ausente → omitir. |
| `totalRows` | `int?` | Total real antes de truncar. Útil para indicar "mostrando 1000 de N". |
| `truncated` | `bool` | `true` si se recortó al `row_limit`. Muestra aviso de truncamiento. |

### 4.4 Payload de ejemplo

**Config** = `artifacts[].definition` (canónico) / `response.output` (compat hoy) — sin `data`, camelCase:

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

**Filas** (en `response.data`):

```json
[
  { "id": 1, "price": 29.99, "created_at": "2026-06-01T10:30:00Z" },
  { "id": 2, "price": 49.99, "created_at": "2026-06-02T14:15:00Z" }
]
```

### 4.5 Renderizado en Frontend (pseudocódigo)

```ts
function renderTable(resp) {
  const { config: cfg } = extractArtifact(resp);  // ver §2.5 (canónico + compat)
  const rows = resp.data ?? [];                    // filas reales
  const grid = cfg.columns.map(c => ({
    field: c.name,
    header: c.title,
    formatter: pickFormatter(c.type, c.format),  // ver §7
  }));
  if (cfg.truncated) showBanner(`Mostrando ${rows.length} de ${cfg.totalRows}`);
  return <DataGrid columns={grid} rows={rows} caption={cfg.explanation} />;
}
```

---

## 5. `STRUCTURED_CHART` (FEAT-215)

### 5.1 Para qué sirve

Devolver una **config de gráfico agnóstica de librería** (espejo del
`AppChartConfig` del frontend). Aquí la **presentación la decide el LLM** (tipo
de gráfico, columnas x/y, paleta, título, descripción), mientras que las **filas
vienen deterministamente** del DataFrame que el agente computó (inyectado en
`response.data`).

**Salvaguarda anti-alucinación**: si el LLM elige una columna que no existe en
los datos reales, el renderer aplica un *fallback* determinista (primera columna
no numérica como `x`, primera numérica como `y`) para que el frontend **nunca**
reciba una config inválida. Las filas se leen **siempre de `response.data`**,
nunca de `cfg.data`.

### 5.2 Modelo (`StructuredChartConfig`)

```python
ChartType = Literal["bar", "horizontalBar", "line", "area", "scatter",
                    "pie", "donut", "radar", "map"]
XAxisMode = Literal["category", "time"]

class StructuredChartConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    type: ChartType                       # tipo de gráfico
    x: str                                # columna de etiqueta/categoría
    y: List[str]                          # una o más columnas de valor (multi-serie)
    stacked: Optional[bool]
    trendline: Optional[bool]
    split_series: Optional[bool]          # alias: splitSeries
    show_legend: Optional[bool]           # alias: showLegend
    x_axis_mode: Optional[XAxisMode]      # alias: xAxisMode
    palette: Optional[List[str]]          # lista de colores hex
    color_by_sign: Optional[bool]         # alias: colorBySign
    negative_color: Optional[str]         # alias: negativeColor
    positive_color: Optional[str]         # alias: positiveColor
    x_axis_label: Optional[str]           # alias: xAxisLabel
    y_axis_label: Optional[str]           # alias: yAxisLabel
    map_name: Optional[str]               # alias: mapName (REQUERIDO si type="map")
    title: Optional[str]
    description: Optional[str]
    data: List[dict]                      # INPUT-ONLY — excluido del output
    data_variable: Optional[str]          # alias: dataVariable
```

### 5.3 Atributos — explicación

| Atributo (camelCase) | Tipo | Descripción |
|---|---|---|
| `type` | `enum` | `bar`, `horizontalBar`, `line`, `area`, `scatter`, `pie`, `donut`, `radar`, `map`. |
| `x` | `string` | Nombre de la columna categórica / de etiqueta. Es **un nombre de columna**, debe existir en `response.data`. |
| `y` | `string[]` | Una o más columnas de valor (multi-serie). |
| `stacked` | `bool?` | Apilar series (bar/area/line). |
| `trendline` | `bool?` | Mostrar línea de tendencia. |
| `splitSeries` | `bool?` | Renderizar cada serie `y` como gráfico separado. |
| `showLegend` | `bool?` | Mostrar leyenda. |
| `xAxisMode` | `enum?` | `"category"` (etiquetas) o `"time"` (requiere strings ISO 8601 en `x`). |
| `palette` | `string[]?` | Lista de colores hex. |
| `colorBySign` | `bool?` | Colorear barras/puntos por signo (positivo/negativo). |
| `negativeColor` / `positiveColor` | `string?` | Hex para valores negativos/positivos cuando `colorBySign=true`. |
| `xAxisLabel` / `yAxisLabel` | `string?` | Etiqueta legible del eje (sobrescribe el nombre de columna). |

…(truncated)…
