# Brainstorm: Finance Research Collective Memory

**Date**: 2026-03-03
**Author**: Claude
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

El sistema actual de Finance Research + Analyst tiene limitaciones arquitectónicas fundamentales:

1. **Ejecución secuencial ineficiente** — Los research crews corren uno tras otro, sin considerar que algunos datos (ej. FRED macro) no necesitan actualizarse cada hora.

2. **Acoplamiento rígido research → analyst** — Los analistas "reciben" los briefings pasivamente en lugar de "buscarlos" activamente, lo que impide:
   - Polinización cruzada efectiva (un analyst accediendo a research de otro dominio)
   - Comparación temporal (research actual vs. previo)
   - Deduplicación inteligente

3. **Dependencia de Redis** — El `ResearchBriefingStore` actual está 100% acoplado a Redis con pub/sub, lo que:
   - Aumenta la complejidad de deployment
   - Requiere infraestructura adicional para desarrollo local
   - No aprovecha la simplicidad de filesystem para datos que no requieren acceso distribuido

4. **Sin control de frecuencia granular** — Todos los crews corren en schedules predefinidos sin considerar si ya existe un research válido para el período.

**Quién está afectado:**
- **Research crews** — Ejecutan trabajo redundante cuando ya existe data fresca
- **Analysts** — No pueden explorar research de otros dominios fácilmente
- **Sistema** — Consume recursos innecesarios en API calls y LLM tokens
- **Desarrolladores** — Requieren Redis para desarrollo local

## Constraints & Requirements

- **Sin Redis para storage** — Persistencia en filesystem con caché en memoria
- **Fire-and-forget writes** — Escritura asíncrona a disco sin bloquear el pipeline
- **Deduplicación por período** — Research agents verifican existencia antes de ejecutar
- **Pull model** — Analysts buscan activamente en la memoria colectiva
- **Cross-pollination** — Acceso a research de cualquier crew, incluyendo histórico
- **Async-first** — Todo el I/O debe ser asíncrono (aiofiles)
- **Pydantic models** — Schemas validados para documentos
- **Backward compatibility** — El sistema debe funcionar sin breaking changes mayores

---

## Options Explored

### Option A: Document Repository con SQLite

Usar SQLite como backend de la memoria colectiva con WAL mode para escrituras concurrentes.

**Approach:**
- SQLite database file (`research_memory.db`)
- Tabla `research_documents` con columnas: id, crew_id, domain, period_key, content_json, created_at
- Índices en (crew_id, period_key) para deduplicación rápida
- aiosqlite para operaciones async
- In-memory cache (LRU) para reads frecuentes

**Schema:**
```sql
CREATE TABLE research_documents (
    id TEXT PRIMARY KEY,
    crew_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    period_key TEXT NOT NULL,  -- "2026-03-03" for daily, "2026-03-03T14" for hourly
    content_json TEXT NOT NULL,
    item_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(crew_id, period_key)
);
CREATE INDEX idx_domain_period ON research_documents(domain, period_key);
```

**Pros:**
- Queries SQL para búsquedas complejas (histórico, comparaciones)
- ACID guarantees para consistencia
- Single file, fácil de respaldar y mover
- WAL mode permite reads concurrentes durante writes
- aiosqlite es maduro y bien mantenido

**Cons:**
- Overhead de SQL para operaciones simples
- Connection pooling más complejo que file I/O directo
- No es tan "fire-and-forget" — necesita gestión de conexiones
- Requiere migración si el schema cambia

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiosqlite` | Async SQLite operations | v0.17+, wrapper sobre sqlite3 |
| `pydantic` | Schema validation | Already in project |

**Existing Code to Reuse:**
- `parrot/memory/file.py` — Patrones de async file I/O
- `parrot/finance/schemas.py` — ResearchBriefing, ResearchItem dataclasses

---

### Option B: Filesystem Document Store con Write-Behind Cache

Usar filesystem directo con estructura de directorios semántica y caché en memoria con escritura asíncrona en background.

**Approach:**
- Directorio base: `./research_memory/` (configurable)
- Estructura: `{domain}/{crew_id}/{period_key}.json`
- In-memory dict como caché primaria
- Background asyncio.Task para persistir cambios a disco (fire-and-forget)
- Lock por documento para evitar escrituras concurrentes

**Directory Structure:**
```
research_memory/
├── macro/
│   └── research_crew_macro/
│       ├── 2026-03-03.json
│       └── 2026-03-02.json
├── equity/
│   └── research_crew_equity/
│       ├── 2026-03-03.json
│       └── 2026-03-02.json
├── crypto/
│   └── research_crew_crypto/
│       ├── 2026-03-03T14.json  # Hourly periods
│       └── 2026-03-03T10.json
└── _index.json  # Optional: quick lookup metadata
```

**Document Format:**
```json
{
  "id": "abc123",
  "crew_id": "research_crew_macro",
  "domain": "macro",
  "period_key": "2026-03-03",
  "generated_at": "2026-03-03T14:30:00Z",
  "briefing": { /* ResearchBriefing content */ },
  "metadata": {
    "item_count": 5,
    "sources": ["FRED", "MarketWatch"],
    "duration_ms": 45000
  }
}
```

**Pros:**
- Máxima simplicidad — filesystem es universal
- Fire-and-forget nativo con `asyncio.create_task()`
- Zero dependencies adicionales (solo aiofiles ya en proyecto)
- Archivos JSON legibles por humanos, fácil debugging
- Estructura de directorios semántica = navegación intuitiva
- No requiere gestión de conexiones ni pools
- Fácil de versionar con git si se desea

**Cons:**
- Sin queries SQL (debe iterar archivos para búsquedas complejas)
- File locking más manual (asyncio.Lock por path)
- Potencial race condition si no se maneja bien el caché
- No escala a millones de documentos (pero no es el caso de uso)

**Effort:** Low

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiofiles` | Async file I/O | Already in project |
| `pydantic` | Schema validation | Already in project |

**Existing Code to Reuse:**
- `parrot/memory/file.py` — `FileConversationMemory` pattern (path generation, async I/O)
- `parrot/memory/cache.py` — `cached_query` decorator pattern (fire-and-forget writes)
- `parrot/finance/schemas.py` — ResearchBriefing, ResearchItem dataclasses

---

### Option C: Hybrid Memory Store (Memory-First + Pluggable Backend)

Arquitectura de dos capas: memoria principal en-memory con backend de persistencia intercambiable (filesystem por defecto, Redis opcional).

**Approach:**
- `CollectiveMemory` clase abstracta define la interfaz
- `MemoryLayer` in-memory (dict + TTL) como capa primaria
- `PersistenceBackend` protocolo para filesystem/Redis/SQLite
- `FileBackend` implementación por defecto
- Write-through o write-behind configurable
- Observer pattern para notificar a backends

**Class Structure:**
```python
class CollectiveMemory(ABC):
    async def store(self, doc: ResearchDocument) -> str: ...
    async def get(self, crew_id: str, period_key: str) -> ResearchDocument | None: ...
    async def exists(self, crew_id: str, period_key: str) -> bool: ...
    async def query(self, **filters) -> list[ResearchDocument]: ...

class MemoryFirstStore(CollectiveMemory):
    def __init__(self, backend: PersistenceBackend): ...
    # Memory operations + async persist to backend

class PersistenceBackend(Protocol):
    async def write(self, doc: ResearchDocument) -> None: ...
    async def read(self, crew_id: str, period_key: str) -> ResearchDocument | None: ...
    async def list_periods(self, crew_id: str) -> list[str]: ...
```

**Pros:**
- Máxima flexibilidad — cambiar backend sin modificar consumidores
- Testing fácil con `InMemoryBackend`
- Permite migrar a Redis en el futuro si es necesario
- Separación clara de responsabilidades
- Patrón consistente con `AbstractClient` del proyecto

**Cons:**
- Over-engineering para el caso de uso actual
- Más código que mantener
- Abstracción adicional sin beneficio inmediato claro
- Complejidad de coordinación memory ↔ backend

**Effort:** Medium-High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiofiles` | Async file I/O | Already in project |
| `pydantic` | Schema validation | Already in project |

**Existing Code to Reuse:**
- `parrot/clients/abstract_client.py` — Pattern de abstracción
- `parrot/memory/abstract.py` — `ConversationMemory` interface pattern
- `parrot/memory/file.py` — File backend implementation

---

### Option D: Event-Sourced Document Log

Usar un log append-only de eventos con snapshots periódicos. Cada research es un evento; el estado actual se reconstruye del log.

**Approach:**
- Archivo de log append-only: `research_events.jsonl`
- Eventos: `ResearchStored`, `ResearchExpired`, `ResearchAccessed`
- Snapshots periódicos del estado actual
- Replay del log al startup para reconstruir memoria

**Event Format:**
```json
{"type": "ResearchStored", "crew_id": "...", "period_key": "...", "briefing": {...}, "ts": "..."}
{"type": "ResearchAccessed", "crew_id": "...", "period_key": "...", "accessor": "equity_analyst", "ts": "..."}
```

**Pros:**
- Audit trail completo de toda la actividad
- Fácil debugging temporal ("¿qué pasó ayer a las 3pm?")
- Permite analytics sobre patrones de acceso
- Append-only es write-optimal

**Cons:**
- Log puede crecer indefinidamente → requiere compaction
- Startup lento si el log es grande
- Complejidad de replay y snapshots
- Over-engineering significativo para el caso de uso

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiofiles` | Async file append | Already in project |
| Custom compaction logic | Log management | Would need to build |

**Existing Code to Reuse:**
- Limited — this is a different paradigm

---

## Recommendation

**Option B (Filesystem Document Store con Write-Behind Cache)** es la recomendación porque:

1. **Simplicidad alineada con el requisito** — El usuario explícitamente pidió "filesystem con caché en memoria y sistema fire-and-forget". Esta opción implementa exactamente eso sin sobre-ingeniería, esto no significa que podamos implementar un Log para audit-trail, que aunque no se la parte "principal" (no se use para memoria), sirva para contetar preguntas como "¿qué pasó ayer a las 3 pm?", dicho log para audit-trail debería ocurrir dentro del Document Store.

2. **Zero dependencies adicionales** — Usa únicamente `aiofiles` que ya está en el proyecto. No requiere SQLite, no requiere configuración de bases de datos.

3. **Estructura semántica intuitiva** — La jerarquía `{domain}/{crew_id}/{period_key}.json` hace que el debugging sea trivial: `cat research_memory/macro/research_crew_macro/2026-03-03.json`.

4. **Fire-and-forget nativo** — `asyncio.create_task(self._persist(doc))` es exactamente lo que se pidió, sin complicaciones de transacciones o consistency guarantees que no se necesitan.

5. **Patrones existentes en el proyecto** — `FileConversationMemory` ya demuestra este approach funciona bien para AI-Parrot, pero FileConversationMemory hace uso de un patrón "C": Hybrid Memory Store con InMemoryConversation, FileConversation y RedisConversation, deberíamos pensar en usar Opción "C" pero solamente construyendo el FileSystem Store.

**Trade-off aceptado:** No hay queries SQL, pero las búsquedas serán:
- Por crew_id + period_key → O(1) file lookup
- Últimos N periods → `glob.glob()` + sort by date
- Cross-domain → iterate over domain dirs
- En un Futuro: implementar concepto de PageIndex para indexar el directorio de archivos.

Esto es aceptable porque el volumen de datos es bajo (~5 crews × ~3 periods/día = ~15 documentos/día).

**IMPORTANTE**: el patrón "C" es más usado dentro de Parrot, y considero que comenzar desde ya, sería un gran avance a pesar de la complejidad.

---

## Feature Description

### User-Facing Behavior

**Para Research Crews:**
1. Antes de ejecutar, el crew invoca `check_research_exists(crew_id, period_key)` tool
2. Si existe → skip con mensaje "Research already completed for this period"
3. Si no existe → ejecuta normalmente
4. Al completar → `store_research(briefing)` persiste en memoria colectiva

**Para Analysts:**
1. Invocan `get_latest_research(domain)` para obtener el briefing más reciente
2. Invocan `get_research_history(domain, last_n=2)` para comparación temporal
3. Invocan `get_cross_domain_research(domains=["macro", "sentiment"])` para polinización
4. Los tools retornan `ResearchDocument` con contenido y metadata

**Configuración de Schedules:**
```python
RESEARCH_SCHEDULES = {
    "research_crew_macro": {
        "cron": "0 6,14 * * *",  # 2x/day (6am, 2pm UTC)
        "period_granularity": "daily",  # Solo 1 por día
    },
    "research_crew_crypto": {
        "cron": "0 */4 * * *",  # Every 4 hours
        "period_granularity": "4h",  # Permite múltiples por día
    },
    # ...
}
```

### Internal Behavior

**CollectiveResearchMemory class:**
```
store_document(doc)
    → validate with Pydantic
    → add to in-memory cache (dict[crew_id][period_key])
    → fire asyncio.create_task(_persist_to_disk(doc))
    → return immediately

_persist_to_disk(doc)
    → acquire asyncio.Lock for path
    → async write JSON to {domain}/{crew_id}/{period_key}.json
    → update _index.json if enabled
    → log success/failure

get_document(crew_id, period_key)
    → check in-memory cache first
    → if miss: async read from disk, populate cache
    → return document or None

exists(crew_id, period_key)
    → check cache keys
    → if miss: check file exists on disk
    → return bool
```

**Research Crew Integration:**
```
ResearchAgent.execute()
    → tool: check_research_exists(my_crew_id, today's_period_key)
    → if exists: return "Already completed"
    → else: proceed with normal research
    → tool: store_research(briefing)
```

**Analyst Integration:**
```
AnalystAgent.deliberate()
    → tool: get_latest_research("macro")  # My domain
    → tool: get_latest_research("sentiment")  # Cross-pollination
    → tool: get_research_history("macro", last_n=2)  # Comparison
    → analyze and produce recommendations
```

### Edge Cases & Error Handling

| Scenario | Behavior |
|---|---|
| Cache miss + file not found | Return None, log debug message |
| Disk write fails | Log error, document remains in memory (transient) |
| Corrupted JSON on disk | Log warning, return None, mark for cleanup |
| Concurrent writes same period | Lock prevents race; second write updates document |
| Memory pressure | Optional: LRU eviction of old periods from cache |
| Startup with existing files | Optionally warm cache from disk (configurable) |
| Period key format mismatch | Validate with regex before file operations |

---

## Capabilities

### New Capabilities
- `research-collective-memory`: Core memory store (CollectiveResearchMemory class)
- `research-deduplication-tool`: Tool for crews to check if research exists
- `research-query-tools`: Tools for analysts to query memory (latest, history, cross-domain)
- `research-schedule-config`: Configurable schedules with period granularity

### Modified Capabilities
- `finance-research-service`: Replace Redis briefing store with CollectiveResearchMemory
- `finance-research-crews`: Add deduplication check at start of execution
- `finance-analysts`: Change from "receive" to "pull" briefings via tools

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/finance/research/briefing_store.py` | **replace** | New CollectiveResearchMemory implementation |
| `parrot/finance/research/service.py` | modifies | Use new memory store, remove Redis dependency |
| `parrot/finance/research/trigger.py` | modifies | Check memory store instead of Redis for freshness |
| `parrot/finance/agents/research.py` | modifies | Add deduplication tool to each crew |
| `parrot/finance/agents/analysts.py` | modifies | Add query tools for pulling from memory |
| `parrot/finance/swarm.py` | modifies | CommitteeDeliberation pulls from memory |
| `parrot/finance/prompts.py` | modifies | Update prompts to instruct dedup and pull behavior |
| `parrot/tools/` | new file | `research_memory_tools.py` with check/store/query tools |

---

## Open Questions

- [ ] **Period key format** — Should crypto use ISO format ("2026-03-03T14:00") or simplified ("2026-03-03-14h")? *Owner: Design*: Use ISO Format.

- [ ] **Cache warming at startup** — Should the memory load existing files at startup or lazy-load on demand? Trade-off: startup time vs. first-access latency. *Owner: Implementation*: load at startup.

- [ ] **Index file** — Should `_index.json` exist for quick metadata queries, or always scan directories? *Owner: Implementation*: index file (check `parrot/pageindex` to evaluate if we can use it for indexing and retrieval).

- [ ] **Retention policy** — How long to keep old research files? Auto-cleanup after N days? *Owner: Product*: Auto-cleanup after a week (7 days), a method for cleanup-compaction need to be executed during startup BEFORE loading the existing documents, cleanup process, instead deleting, will move the files to an historical folder for historical research.

- [ ] **Migration path** — Should we support reading existing Redis data during transition, or clean slate? *Owner: Ops*: clean slate.
