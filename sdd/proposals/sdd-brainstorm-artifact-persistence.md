# SDD Brainstorm: Conversation Artifact Persistence

**Feature ID:** FEAT-XXX
**Author:** Jesus
**Date:** 2025-04-16
**Status:** Brainstorm
**Scope:** `packages/ai-parrot` → `parrot.memory`, `parrot.models`, nueva capa `parrot.storage`

---

## 1. Problema

### 1.1 Qué se pierde hoy

Cada vez que un usuario interactúa con un agente, se generan artefactos que viven exclusivamente en la memoria del frontend y desaparecen al recargar la página:

- **Charts** — configuraciones de Chart.js o ECharts que el usuario crea a partir de la data que retorna el PandasAgent.
- **Canvas tabs** — colecciones de bloques tipo Notion/Jupyter que el usuario compone libremente; hay un tab `main` por defecto y N tabs adicionales creados a voluntad. Son per-conversation-thread, no per-message.
- **Infografías** — los objetos `InfographicResponse` (JSON) generados por `get_infographic()`.
- **DataFrames computados** — resultados intermedios que el PandasAgent guarda en memoria de ejecución pero que no sobreviven a un restart del backend.

Nada de esto se persiste. El usuario cierra la pestaña y pierde horas de trabajo curatorial.

### 1.2 Ineficiencia del approach actual

El conversation history se almacena en DocumentDB (MongoDB-compatible), y la recuperación requiere múltiples round-trips:

```
Flujo actual para abrir el chat:
  1. GET /conversations?user_id=X&agent_id=Y       → DocumentDB query (lista de sesiones)
  2. GET /conversation/{session_id}                  → DocumentDB query (el thread)
  3. GET /conversation/{session_id}/history           → DocumentDB query (los turns)
  4. Para cada turn con data > threshold → otro GET
```

El patrón de acceso es **siempre el mismo**: `user_id + agent_id` para listar conversaciones, y `session_id` para cargar un thread. Este patrón key-value puro está pagando el overhead de un motor de queries semi-relacional (DocumentDB) sin usar ninguna de sus capacidades de query.

### 1.3 Lo que necesitamos

Un modelo de datos donde una sola lectura al storage traiga:

- Los mensajes del thread (turns).
- Los artefactos que el usuario ha creado o que el agente ha generado.
- Los canvas tabs con su contenido.
- Metadata del thread (nombre, fecha, estado).

Y que el frontend pueda rehidratar la sesión completa con **una sola llamada API** en lugar de cuatro.

---

## 2. Arquitectura Actual — Estado del Código

### 2.1 Modelo de memoria (`parrot.memory.abstract`)

```python
@dataclass
class ConversationTurn:
    turn_id: str
    user_id: str
    user_message: str
    assistant_response: str
    context_used: Optional[str] = None
    tools_used: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ConversationHistory:
    session_id: str
    user_id: str
    chatbot_id: Optional[str] = None
    turns: List[ConversationTurn] = field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### 2.2 Backends de memoria

| Backend | Clase | Cómo persiste | Limitaciones |
|---------|-------|---------------|--------------|
| In-memory | `InMemoryConversation` | Dict en RAM | Se pierde al reiniciar |
| File | `FileConversationMemory` | JSON por session en disco | Lento, sin concurrencia |
| Redis | `RedisConversation` | Hash o string por session | Volátil (TTL), sin artifacts |

### 2.3 Flujo de escritura actual

```
ask() / conversation()
  ├── memory.get_history(user_id, session_id)
  ├── get_messages_for_api() → construir contexto LLM
  ├── LLM call → response
  └── memory.add_turn(user_id, session_id, turn)
        └── Redis: HSET conversation:{chatbot_id}:{user_id}:{session_id}
             mapping: { turns: serialize([...turns, new_turn]) }
```

### 2.4 Lo que NO existe hoy

- No hay concepto de "artifact" en el modelo de datos del backend.
- No hay manera de asociar un chart/canvas/infographic a un turn o a un thread.
- Los canvas tabs son estado local de React/Svelte, nunca tocan el backend.
- La lista de conversaciones (`list_sessions`) retorna solo `session_id`s sin metadata.

---

## 3. Propuesta: Migración a DynamoDB + Modelo de Artefactos

### 3.1 ¿Por qué DynamoDB?

| Criterio | DocumentDB | DynamoDB |
|----------|------------|----------|
| Patrón de acceso | Consultas semi-relacionales | Key-value / sort-key puro |
| Latencia p50 | 5-15ms | 1-5ms (single-digit) |
| Modelo de pricing | Instancia fija (siempre encendida) | Pay-per-request o provisioned |
| JSON nativo | BSON (close) | Atributos JSON nativos |
| Concurrencia | Locks implícitos | Conditional writes, atomic counters |
| Escala | Scale-up (vertical) | Infinito horizontal |
| Items grandes | 16MB por documento | 400KB por item (workaround con S3) |

Nuestro patrón de acceso calza perfectamente con DynamoDB:
- **PK** = `USER#{user_id}#AGENT#{agent_id}` — siempre sabemos el user y el agent.
- **SK** = sort key variable por tipo de registro.
- Un solo `Query(PK=...)` trae todas las conversaciones del usuario con ese agente.
- Un solo `GetItem(PK=..., SK=THREAD#{session_id})` trae el thread completo.

### 3.2 Diseño de tabla — Single Table Design

Una sola tabla DynamoDB con múltiples tipos de registros discriminados por el sort key:

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Table: parrot-conversations                                          │
├───────────────────────────────┬─────────────────────────────────────────┤
│  PK (Partition Key)           │  SK (Sort Key)                         │
├───────────────────────────────┼─────────────────────────────────────────┤
│  USER#u123#AGENT#sales-bot    │  THREAD#sess-abc                       │ ← Thread metadata
│  USER#u123#AGENT#sales-bot    │  THREAD#sess-abc#TURN#001              │ ← Turn individual
│  USER#u123#AGENT#sales-bot    │  THREAD#sess-abc#TURN#002              │
│  USER#u123#AGENT#sales-bot    │  THREAD#sess-abc#ARTIFACT#chart-x1     │ ← Chart artifact
│  USER#u123#AGENT#sales-bot    │  THREAD#sess-abc#ARTIFACT#canvas-main  │ ← Canvas tab
│  USER#u123#AGENT#sales-bot    │  THREAD#sess-abc#ARTIFACT#infog-r1     │ ← Infographic
│  USER#u123#AGENT#sales-bot    │  THREAD#sess-def                       │ ← Otro thread
│  USER#u123#AGENT#sales-bot    │  THREAD#sess-def#TURN#001              │
│  ...                          │  ...                                    │
└───────────────────────────────┴─────────────────────────────────────────┘
```

#### 3.2.1 Patrones de acceso

| Operación | DynamoDB Query | Items devueltos |
|-----------|----------------|-----------------|
| Listar threads de un usuario/agente | `PK = USER#u123#AGENT#bot AND SK begins_with THREAD# AND SK NOT contains #` | Solo los registros THREAD (metadata) |
| Cargar thread completo con turns + artifacts | `PK = ... AND SK begins_with THREAD#sess-abc` | Thread + todos sus turns + artifacts |
| Cargar solo turns | `PK = ... AND SK begins_with THREAD#sess-abc#TURN#` | Solo turns |
| Cargar solo artifacts | `PK = ... AND SK begins_with THREAD#sess-abc#ARTIFACT#` | Solo artifacts |
| Obtener un artifact específico | `GetItem(PK=..., SK=THREAD#sess-abc#ARTIFACT#chart-x1)` | Un solo item |
| Agregar turn | `PutItem(PK=..., SK=THREAD#sess-abc#TURN#003, ...)` | Escritura atómica |
| Guardar/actualizar artifact | `PutItem(PK=..., SK=THREAD#sess-abc#ARTIFACT#chart-x2, ...)` | Escritura atómica |

**Ventaja clave vs DocumentDB**: Listar threads y cargar un thread son **una sola query cada uno**, no múltiples round-trips.

### 3.3 Alternativa considerada: Modelo de documento gordo (fat document)

En vez de registros separados por turn/artifact, meter todo dentro de un solo item DynamoDB por thread:

```json
{
  "PK": "USER#u123#AGENT#sales-bot",
  "SK": "THREAD#sess-abc",
  "title": "Análisis Q4",
  "turns": [ { "turn_id": "001", ... }, { "turn_id": "002", ... } ],
  "artifacts": { "charts": [...], "canvas": [...], "infographics": [...] },
  "created_at": "...",
  "updated_at": "..."
}
```

| Criterio | Single items (3.2) | Fat document |
|----------|--------------------|----|
| Lectura de thread completo | 1 Query (N items) | 1 GetItem (1 item) |
| Escritura de un turn | 1 PutItem | 1 UpdateItem con SET list_append |
| Escritura de un artifact | 1 PutItem | 1 UpdateItem con SET en map nested |
| Límite de tamaño | 400KB por item (cada turn/artifact) | 400KB TOTAL para el thread entero |
| Concurrencia | Sin conflictos (items independientes) | Contention en writes simultáneos |
| Lectura parcial (solo artifacts) | 1 Query con SK filter | 1 GetItem + filtrar en cliente |
| Costo de lectura | Mayor (múltiples items = más RCU) | Menor (1 item = 1 RCU si < 4KB) |
| Conversaciones largas | Escala linealmente | Puede exceder 400KB |

**Decisión: Modelo híbrido.**

- **Thread metadata** → un solo item con metadata ligera + lista de artifact IDs (no el contenido).
- **Turns** → items individuales para no chocar con el límite de 400KB en threads largos.
- **Artifacts** → items individuales porque pueden ser grandes (un chart ECharts o un canvas puede pesar 50-200KB).

El resultado: listar threads es 1 query, cargar un thread es 1 query, y agregar un turn o artifact es 1 PutItem sin tocar los otros items.

### 3.4 Estructura de cada tipo de registro

#### Thread metadata item

```python
{
    "PK": "USER#u123#AGENT#sales-bot",
    "SK": "THREAD#sess-abc",
    "type": "thread",
    "title": "Análisis de ventas Q4",
    "description": "Conversación sobre métricas de rendimiento...",
    "created_at": "2025-04-15T10:30:00Z",
    "updated_at": "2025-04-15T14:22:00Z",
    "turn_count": 12,
    "artifact_count": 5,
    "artifact_summary": [
        # Lista ligera para que el frontend sepa qué hay sin cargarlos
        {"id": "chart-x1", "type": "chart", "title": "Revenue by Region"},
        {"id": "canvas-main", "type": "canvas", "title": "Main"},
        {"id": "canvas-qa", "type": "canvas", "title": "QA Report"},
        {"id": "infog-r1", "type": "infographic", "title": "Executive Summary"},
    ],
    "pinned": false,
    "archived": false,
    "tags": ["sales", "q4"],
    # GSI para buscar por fecha
    "GSI1PK": "USER#u123",
    "GSI1SK": "2025-04-15T14:22:00Z",
    # TTL opcional para auto-cleanup
    "ttl": null
}
```

#### Turn item

```python
{
    "PK": "USER#u123#AGENT#sales-bot",
    "SK": "THREAD#sess-abc#TURN#001",
    "type": "turn",
    "turn_id": "001",
    "user_message": "¿Cuáles fueron las ventas del Q4 por región?",
    "assistant_response": "Aquí están los resultados...",
    "timestamp": "2025-04-15T10:31:00Z",
    "tools_used": ["python_repl_pandas"],
    "metadata": {
        "model": "gemini-2.5-pro",
        "usage": {"input_tokens": 1200, "output_tokens": 800},
        "response_time": 3.2
    },
    # ── Nuevo: data del turn ──
    "data": {
        # Si < 200KB, inline
        "columns": ["region", "revenue", "growth"],
        "rows": [["NA", 1250000, 12.5], ["LATAM", 890000, 8.3]],
    },
    # Si > 200KB, puntero a S3
    "data_ref": null,
    # ── Nuevo: artifacts generados en este turn ──
    "artifact_refs": ["chart-x1", "infog-r1"]
}
```

#### Artifact item (genérico con `artifact_type` discriminador)

```python
{
    "PK": "USER#u123#AGENT#sales-bot",
    "SK": "THREAD#sess-abc#ARTIFACT#chart-x1",
    "type": "artifact",
    "artifact_id": "chart-x1",
    "artifact_type": "chart",       # discriminador: chart | canvas | infographic | dataframe | export
    "title": "Revenue by Region — Bar Chart",
    "created_at": "2025-04-15T10:35:00Z",
    "updated_at": "2025-04-15T10:35:00Z",
    "source_turn_id": "001",        # turn que originó este artifact (nullable)
    "created_by": "user",           # "user" | "agent" | "system"
    # ── Payload: varía por artifact_type ──
    "definition": { ... },          # El contenido real del artifact
    # Si el artifact excede 200KB:
    "definition_ref": null,         # "s3://parrot-artifacts/USER#u123/sess-abc/chart-x1.json"
}
```

---

## 4. ¿Qué se guarda en cada tipo de artifact?

### 4.1 Chart artifact (`artifact_type: "chart"`)

**Pregunta central:** ¿Guardamos la especificación declarativa del chart, o el resultado renderizado?

**Respuesta: La definición declarativa.** El frontend es el que renderiza. Lo que guardamos es la "receta" que el frontend usa para construir el chart.

```python
"definition": {
    "engine": "echarts",         # "echarts" | "chartjs" | "plotly"
    "version": "5.5",            # versión del engine
    "spec": {
        # ECharts option object completo
        "title": {"text": "Revenue by Region"},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": ["NA", "LATAM", "EMEA", "APAC"]},
        "yAxis": {"type": "value"},
        "series": [{
            "name": "Revenue",
            "type": "bar",
            "data": [1250000, 890000, 720000, 550000]
        }]
    },
    # Metadata de presentación que el frontend usa
    "display": {
        "width": "100%",
        "height": "400px",
        "theme": "midnight"      # tema de infographic aplicado
    }
}
```

**Para Chart.js:**
```python
"definition": {
    "engine": "chartjs",
    "version": "4.4",
    "spec": {
        "type": "bar",
        "data": {
            "labels": ["NA", "LATAM", "EMEA", "APAC"],
            "datasets": [{
                "label": "Revenue",
                "data": [1250000, 890000, 720000, 550000],
                "backgroundColor": ["#60a5fa", "#4ade80", "#f59e0b", "#f87171"]
            }]
        },
        "options": {
            "responsive": true,
            "plugins": {"legend": {"display": true}}
        }
    }
}
```

**Ventaja de guardar la spec:** El frontend puede re-renderizar el chart con una versión más nueva del engine, cambiar el tema, o editar la configuración. Si guardáramos una imagen PNG o un SVG estático, perderíamos toda esa flexibilidad.

**Riesgo:** Las specs de ECharts pueden ser grandes (100KB+ con data inline). Si la data es mucha, la spec debería referenciar la data del turn (`source_turn_id`) en vez de duplicarla.

```python
# Chart con data referenciada en vez de inline:
"definition": {
    "engine": "echarts",
    "spec": {
        "dataset": {"source_turn": "001", "columns": ["region", "revenue"]},
        # ^ el frontend resuelve esto buscando el turn y extrayendo la data
        "series": [{"type": "bar", "encode": {"x": "region", "y": "revenue"}}]
    }
}
```

### 4.2 Canvas artifact (`artifact_type: "canvas"`)

Un canvas tab es una colección ordenada de bloques heterogéneos — exactamente como un documento de Notion.

```python
"definition": {
    "tab_id": "main",
    "title": "Main",
    "blocks": [
        {
            "block_id": "blk-001",
            "block_type": "markdown",
            "content": "## Análisis de ventas Q4\n\nEste reporte cubre..."
        },
        {
            "block_id": "blk-002",
            "block_type": "chart_ref",
            "artifact_ref": "chart-x1"   # referencia a otro artifact
        },
        {
            "block_id": "blk-003",
            "block_type": "data_table",
            "source_turn_id": "001",     # datos del turn
            "display_options": {
                "max_rows": 20,
                "sortable": true,
                "searchable": true
            }
        },
        {
            "block_id": "blk-004",
            "block_type": "agent_response",
            "source_turn_id": "002",     # respuesta completa del agente
            "excerpt": true              # solo el texto, sin re-ejecutar
        },
        {
            "block_id": "blk-005",
            "block_type": "infographic_ref",
            "artifact_ref": "infog-r1"
        },
        {
            "block_id": "blk-006",
            "block_type": "note",
            "content": "Pendiente: validar con el equipo de finanzas"
        }
    ],
    "layout": "vertical",              # "vertical" | "grid" | "columns"
    "export_config": {
        "format": ["html", "pdf"],
        "include_header": true,
        "include_timestamp": true
    }
}
```

**Canvas block types propuestos:**

| Block type | Contenido | Fuente |
|------------|-----------|--------|
| `markdown` | Texto libre del usuario | User-created |
| `heading` | Título de sección | User-created |
| `chart_ref` | Referencia a un chart artifact | Referencia cruzada |
| `data_table` | Tabla de datos de un turn | Referencia a turn |
| `agent_response` | Respuesta renderizada de un turn | Referencia a turn |
| `infographic_ref` | Referencia a infographic artifact | Referencia cruzada |
| `note` | Nota/callout del usuario | User-created |
| `code` | Bloque de código (python, SQL, etc.) | User-created o extraído de turn |
| `image` | Imagen embebida o referencia | User-uploaded o generada |
| `divider` | Separador visual | User-created |

**Observación clave:** Los canvas tabs usan **referencias** a otros artifacts y turns, no duplican la data. Esto es crítico para que una actualización del chart se refleje automáticamente en todos los canvas que lo referencian.

### 4.3 Infographic artifact (`artifact_type: "infographic"`)

Ya tenemos el modelo completo para esto — es literalmente el `InfographicResponse` serializado:

```python
"definition": {
    "template": "executive",
    "theme": "midnight",
    "blocks": [
        {"type": "title", "title": "Executive Summary Q4", "subtitle": "..."},
        {"type": "hero_card", "label": "Total Revenue", "value": "$3.4M", ...},
        # ... toda la estructura InfographicResponse
    ],
    "metadata": {
        "generated_by": "get_infographic()",
        "source_query": "Genera un reporte ejecutivo de Q4"
    }
}
```

### 4.4 DataFrame artifact (`artifact_type: "dataframe"`)

Para DataFrames grandes que se quieren preservar más allá de la sesión del PandasAgent:

```python
"definition": {
    "name": "q4_sales_by_region",
    "shape": [1500, 12],
    "columns": ["region", "store_id", "revenue", ...],
    "dtypes": {"region": "object", "revenue": "float64", ...},
    "preview": {
        "columns": ["region", "store_id", "revenue"],
        "rows": [["NA", "TCTX-001", 45000.00], ...]   # primeras 5 filas
    },
    # Data completa siempre en S3 (los DataFrames suelen ser grandes)
    "data_ref": "s3://parrot-artifacts/USER#u123/sess-abc/q4_sales.parquet",
    "format": "parquet",                     # "parquet" | "csv" | "json"
    "size_bytes": 245000
}
```

### 4.5 Export artifact (`artifact_type: "export"`)

Cuando el usuario exporta un canvas o un infographic a HTML/PDF:

```python
"definition": {
    "source_artifact": "canvas-main",
    "format": "html",                       # "html" | "pdf"
    "generated_at": "2025-04-15T14:20:00Z",
    "file_ref": "s3://parrot-exports/USER#u123/sess-abc/canvas-main.html",
    "size_bytes": 85000,
    "expires_at": "2025-05-15T14:20:00Z"   # Exports expiran en 30 días
}
```

---

## 5. El límite de 400KB y la estrategia S3

### 5.1 El problema

DynamoDB tiene un límite de **400KB por item**. Un turn con mucha data, un chart ECharts con miles de datapoints, o un canvas con muchos bloques pueden excederlo.

### 5.2 Estrategia de overflow a S3

```
┌─────────────────────┐
│   DynamoDB item      │
│   (< 400KB)          │
│                      │
│   definition: {...}  │  ← Si cabe, inline
│       OR             │
│   definition_ref:    │  ← Si no cabe, puntero a S3
│   "s3://bucket/..."  │
└──────────┬───────────┘
           │ (si definition_ref != null)
           ▼
┌─────────────────────┐
│   S3 Object          │
│   parrot-artifacts/  │
│   USER#u123/         │
│   sess-abc/          │
│   chart-x1.json      │ ← JSON completo del artifact
└─────────────────────┘
```

**Regla de decisión:**
```python
INLINE_THRESHOLD = 200 * 1024   # 200KB — margen de seguridad vs 400KB

async def save_artifact(self, artifact: Artifact) -> None:
    definition_json = json.dumps(artifact.definition)
    
    if len(definition_json) < INLINE_THRESHOLD:
        # Inline en DynamoDB
        item = {
            "PK": ..., "SK": ...,
            "definition": artifact.definition
        }
    else:
        # Overflow a S3
        s3_key = f"USER#{artifact.user_id}/{artifact.session_id}/{artifact.artifact_id}.json"
        await self.s3.put_object(
            Bucket="parrot-artifacts",
            Key=s3_key,
            Body=definition_json
        )
        item = {
            "PK": ..., "SK": ...,
            "definition": None,
            "definition_ref": f"s3://parrot-artifacts/{s3_key}"
        }
    
    await self.dynamodb.put_item(TableName="parrot-conversations", Item=item)
```

**Para DataFrames:** Siempre van a S3 en formato Parquet (consistente con la serialización Redis existente en `DatasetManager`). El item DynamoDB solo guarda el preview y el puntero.

### 5.3 Lectura con resolución lazy de S3

```python
async def load_thread(self, user_id, agent_id, session_id) -> ThreadDocument:
    """Carga thread completo: metadata + turns + artifacts."""
    # 1. Un solo Query a DynamoDB
    response = await self.dynamodb.query(
        TableName="parrot-conversations",
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
        ExpressionAttributeValues={
            ":pk": f"USER#{user_id}#AGENT#{agent_id}",
            ":sk_prefix": f"THREAD#{session_id}"
        }
    )
    
    thread = ThreadDocument()
    s3_refs = []
    
    for item in response["Items"]:
        if item["type"] == "thread":
            thread.metadata = item
        elif item["type"] == "turn":
            thread.turns.append(item)
        elif item["type"] == "artifact":
            if item.get("definition_ref"):
                # Marcar para resolución lazy
                s3_refs.append(item)
                thread.artifacts.append(item)  # con definition=None
            else:
                thread.artifacts.append(item)
    
    # 2. Resolver S3 refs en paralelo (solo si el frontend los pide)
    #    El frontend recibe artifact_summary en metadata y pide
    #    el contenido completo bajo demanda.
    
    return thread
```

---

## 6. Modelo Pydantic para el backend

### 6.1 Modelos de artifact

```python
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field
from datetime import datetime


class ArtifactType(str, Enum):
    CHART = "chart"
    CANVAS = "canvas"
    INFOGRAPHIC = "infographic"
    DATAFRAME = "dataframe"
    EXPORT = "export"


class ArtifactCreator(str, Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class ChartEngine(str, Enum):
    ECHARTS = "echarts"
    CHARTJS = "chartjs"
    PLOTLY = "plotly"


class ArtifactSummary(BaseModel):
    """Resumen ligero de un artifact — incluido en el thread metadata."""
    id: str
    type: ArtifactType
    title: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class Artifact(BaseModel):
    """Artifact completo con su definición."""
    artifact_id: str
    artifact_type: ArtifactType
    title: str
    created_at: datetime
    updated_at: datetime
    source_turn_id: Optional[str] = None
    created_by: ArtifactCreator = ArtifactCreator.USER
    definition: Optional[Dict[str, Any]] = None
    definition_ref: Optional[str] = None        # S3 URI si overflow


class ThreadMetadata(BaseModel):
    """Metadata de un conversation thread."""
    session_id: str
    user_id: str
    agent_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    turn_count: int = 0
    artifact_count: int = 0
    artifact_summary: List[ArtifactSummary] = Field(default_factory=list)
    pinned: bool = False
    archived: bool = False
    tags: List[str] = Field(default_factory=list)


class ThreadDocument(BaseModel):
    """Thread completo: metadata + turns + artifacts."""
    metadata: ThreadMetadata
    turns: List[ConversationTurn] = Field(default_factory=list)
    artifacts: List[Artifact] = Field(default_factory=list)
```

### 6.2 Canvas block model

```python
class CanvasBlockType(str, Enum):
    MARKDOWN = "markdown"
    HEADING = "heading"
    CHART_REF = "chart_ref"
    DATA_TABLE = "data_table"
    AGENT_RESPONSE = "agent_response"
    INFOGRAPHIC_REF = "infographic_ref"
    NOTE = "note"
    CODE = "code"
    IMAGE = "image"
    DIVIDER = "divider"


class CanvasBlock(BaseModel):
    """Un bloque individual dentro de un canvas tab."""
    block_id: str
    block_type: CanvasBlockType
    content: Optional[str] = None           # Para markdown, note, code, heading
    artifact_ref: Optional[str] = None      # Para chart_ref, infographic_ref
    source_turn_id: Optional[str] = None    # Para data_table, agent_response
    display_options: Optional[Dict[str, Any]] = None
    position: int = 0                       # Orden dentro del canvas


class CanvasDefinition(BaseModel):
    """Definición completa de un canvas tab."""
    tab_id: str
    title: str
    blocks: List[CanvasBlock] = Field(default_factory=list)
    layout: str = "vertical"
    export_config: Optional[Dict[str, Any]] = None
```

---

## 7. Backend API layer — `ConversationStore`

### 7.1 Interfaz abstracta

```python
class ConversationStore(ABC):
    """Abstracción para persistencia de conversaciones con artifacts.
    
    Reemplaza ConversationMemory para el storage persistente.
    ConversationMemory sigue existiendo para el hot cache en Redis.
    """
    
    # ── Thread lifecycle ──
    @abstractmethod
    async def create_thread(self, user_id, agent_id, title=None) -> ThreadMetadata: ...
    
    @abstractmethod
    async def get_thread(self, user_id, agent_id, session_id) -> ThreadDocument: ...
    
    @abstractmethod
    async def list_threads(self, user_id, agent_id, limit=20, cursor=None) -> List[ThreadMetadata]: ...
    
    @abstractmethod
    async def update_thread_metadata(self, user_id, agent_id, session_id, **updates) -> None: ...
    
    @abstractmethod
    async def delete_thread(self, user_id, agent_id, session_id) -> bool: ...
    
    # ── Turns ──
    @abstractmethod
    async def add_turn(self, user_id, agent_id, session_id, turn: ConversationTurn) -> None: ...
    
    @abstractmethod
    async def get_turns(self, user_id, agent_id, session_id, limit=None) -> List[ConversationTurn]: ...
    
    # ── Artifacts ──
    @abstractmethod
    async def save_artifact(self, user_id, agent_id, session_id, artifact: Artifact) -> None: ...
    
    @abstractmethod
    async def get_artifact(self, user_id, agent_id, session_id, artifact_id: str) -> Artifact: ...
    
    @abstractmethod
    async def list_artifacts(self, user_id, agent_id, session_id) -> List[ArtifactSummary]: ...
    
    @abstractmethod
    async def delete_artifact(self, user_id, agent_id, session_id, artifact_id: str) -> bool: ...
    
    @abstractmethod
    async def update_artifact(self, user_id, agent_id, session_id, artifact_id: str, definition: dict) -> None: ...
```

### 7.2 Relación con ConversationMemory existente

```
                    ┌─────────────────────────────────────┐
                    │         ConversationMemory           │
                    │  (hot cache — Redis)                 │
                    │  • Últimos N turns en memoria rápida │
                    │  • Para contexto del LLM             │
                    │  • TTL = duración de la sesión       │
                    └─────────────┬───────────────────────┘
                                  │ flush on session end
                                  ▼
                    ┌─────────────────────────────────────┐
                    │       ConversationStore              │
                    │  (persistent — DynamoDB + S3)        │
                    │  • Thread metadata                   │
                    │  • Turns históricos                  │
                    │  • Artifacts (charts, canvas, etc.)  │
                    │  • Exports                           │
                    └─────────────────────────────────────┘
```

**No se reemplaza ConversationMemory**, se complementa. Redis sigue siendo el hot path para el ciclo de `ask()` porque el LLM necesita los turns recientes con latencia mínima. DynamoDB es el cold storage persistente al que se le escriben los turns al finalizar cada uno (fire-and-forget async) y del que se lee al abrir un thread existente.

### 7.3 Punto de integración en AbstractBot

```python
# En abstract.py, nuevos métodos:

async def save_conversation_artifact(
    self,
    user_id: str,
    session_id: str,
    artifact: Artifact,
) -> None:
    """Persiste un artifact en el ConversationStore."""
    if not self.conversation_store:
        return
    agent_id = str(getattr(self, 'chatbot_id', self.name))
    await self.conversation_store.save_artifact(
        user_id, agent_id, session_id, artifact
    )

async def get_conversation_artifacts(
    self,
    user_id: str,
    session_id: str,
) -> List[ArtifactSummary]:
    """Lista artifacts de un thread."""
    if not self.conversation_store:
        return []
    agent_id = str(getattr(self, 'chatbot_id', self.name))
    return await self.conversation_store.list_artifacts(
        user_id, agent_id, session_id
    )
```

---

## 8. Frontend API Endpoints

```
# ── Thread management ──
GET    /api/v1/threads?agent_id=X                    → list_threads()
POST   /api/v1/threads                               → create_thread()
GET    /api/v1/threads/{session_id}                   → get_thread()       # metadata + turns + artifact summary
PATCH  /api/v1/threads/{session_id}                   → update_thread_metadata()
DELETE /api/v1/threads/{session_id}                   → delete_thread()

# ── Artifact CRUD ──
GET    /api/v1/threads/{session_id}/artifacts         → list_artifacts()
POST   /api/v1/threads/{session_id}/artifacts         → save_artifact()
GET    /api/v1/threads/{session_id}/artifacts/{id}    → get_artifact()     # full definition
PUT    /api/v1/threads/{session_id}/artifacts/{id}    → update_artifact()
DELETE /api/v1/threads/{session_id}/artifacts/{id}    → delete_artifact()

# ── S3 retrieval para objetos grandes ──
GET    /api/v1/threads/{session_id}/data/{turn_id}    → get_turn_data()    # resuelve data_ref de S3
```

El `user_id` viene del JWT/session en todos los casos — nunca se pasa como parámetro.

---

## 9. Migración y Coexistencia

### 9.1 Fase 1 — Dual write (semanas 1-2)

- Los turns se siguen escribiendo en Redis (hot cache) Y en DynamoDB (persistent).
- DocumentDB sigue activo para lectura de históricos.
- Nuevos artifacts se escriben solo en DynamoDB.

### 9.2 Fase 2 — Lectura desde DynamoDB (semanas 3-4)

- El endpoint `list_threads` lee de DynamoDB.
- El endpoint `get_thread` lee de DynamoDB.
- DocumentDB solo para threads históricos que no se han migrado.

### 9.3 Fase 3 — Migración batch + decomission (semana 5+)

- Script de migración batch: DocumentDB → DynamoDB.
- Decomission del DocumentDB cluster (ahorro de costos significativo).

---

## 10. Preguntas Abiertas

1. **¿TTL en artifacts?** — ¿Los exports a HTML/PDF deberían expirar a los 30 días? ¿Los charts y canvas son permanentes hasta que el usuario los elimine?

2. **¿Versionado de artifacts?** — Si el usuario edita un chart, ¿guardamos el historial de versiones o solo el estado actual? El versionado añade complejidad pero permite undo.

3. **¿Canvas collaboration?** — ¿Múltiples usuarios pueden editar el mismo canvas? Si sí, necesitamos CRDTs o al menos optimistic locking con version numbers.

4. **¿Shared artifacts?** — ¿Un artifact creado en una conversación puede ser referenciado desde otra? Esto rompe el modelo de PK por thread.

5. **¿Compresión en S3?** — ¿Usamos gzip para los JSON en S3? El ahorro de almacenamiento vs el overhead de CPU del decompress.

6. **¿GSI adicionales?** — ¿Necesitamos buscar threads por tag, por fecha global (cross-agent), o por artifact type? Cada GSI tiene costo.

7. **¿Cuota de artifacts por thread?** — ¿Limitamos a N artifacts por thread para evitar que un solo thread acumule 500 charts?

8. **¿Chart spec versionada?** — Si ECharts actualiza su API y la spec guardada ya no es compatible, ¿cómo migramos? ¿Guardamos la versión del engine?

9. **¿Data dedup?** — Si el usuario crea 3 charts sobre el mismo DataFrame del turn 001, ¿la data se duplica 3 veces en S3 o los charts referencian un solo data artifact?

10. **¿El PandasAgent auto-genera artifacts?** — ¿Cada vez que `ask()` devuelve data, se crea automáticamente un dataframe artifact, o solo bajo petición explícita del usuario?

---

## 11. Estimación de Costos DynamoDB

### Asunciones

- 1000 usuarios activos
- 10 agentes promedio por usuario
- 20 threads promedio por usuario/agente
- 15 turns promedio por thread
- 3 artifacts promedio por thread

### Cálculo de items

```
Threads:     1000 × 10 × 20          = 200,000 thread items
Turns:       200,000 × 15            = 3,000,000 turn items
Artifacts:   200,000 × 3             = 600,000 artifact items
Total items:                         ≈ 3,800,000
```

### Storage

```
Thread item:     ~1KB     → 200,000 × 1KB     ≈ 200 MB
Turn item:       ~2KB avg → 3,000,000 × 2KB   ≈ 6 GB
Artifact item:   ~5KB avg → 600,000 × 5KB     ≈ 3 GB
Total DynamoDB:                                ≈ 9.2 GB

S3 overflow (est. 10% artifacts):
600,000 × 10% × 100KB avg ≈ 6 GB
```

### Costo mensual estimado (us-east-1, on-demand)

```
DynamoDB storage:  9.2 GB × $0.25/GB             ≈ $2.30/mes
DynamoDB writes:   ~500K writes/day × 30 × $1.25/M WCU   ≈ $18.75/mes
DynamoDB reads:    ~200K reads/day × 30 × $0.25/M RCU    ≈ $1.50/mes
S3 storage:        6 GB × $0.023/GB               ≈ $0.14/mes
S3 requests:       ~50K/mes × $0.005/1K            ≈ $0.25/mes
────────────────────────────────────────────────────
Total estimado:                                   ≈ $23/mes
```

vs DocumentDB cluster actual (db.r6g.large): **~$400/mes** (instancia + storage).

**Ahorro potencial: ~95%** (si se decomissiona DocumentDB).

---

## 12. Diagrama de Dependencias

```
parrot.storage (NUEVO)
  ├── abstract.py           ← ConversationStore ABC
  ├── dynamodb.py           ← DynamoDBConversationStore
  ├── s3_overflow.py        ← S3OverflowManager (inline vs S3 decision)
  └── models.py             ← ArtifactType, Artifact, ThreadMetadata, etc.
       │
       ▼
parrot.memory (EXISTENTE — sin cambios breaking)
  ├── abstract.py           ← ConversationMemory (Redis hot cache, sin cambios)
  ├── redis.py              ← RedisConversation (sigue como hot cache)
  └── ...
       │
       ▼
parrot.bots.abstract (EXTENDER)
  ├── conversation_store: Optional[ConversationStore]
  ├── save_conversation_artifact()     ← nuevo
  ├── get_conversation_artifacts()     ← nuevo
  └── save_conversation_turn()         ← extiende para dual-write
       │
       ▼
API layer (aiohttp views)
  ├── ThreadListView           ← GET /api/v1/threads
  ├── ThreadDetailView         ← GET/PATCH/DELETE /api/v1/threads/{id}
  ├── ArtifactListView         ← GET/POST /api/v1/threads/{id}/artifacts
  ├── ArtifactDetailView       ← GET/PUT/DELETE /api/v1/threads/{id}/artifacts/{aid}
  └── TurnDataView             ← GET /api/v1/threads/{id}/data/{turn_id}
```
