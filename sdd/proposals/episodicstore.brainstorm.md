# EpisodicMemoryStore v2 — Brainstorm Spec
## Para consumo por Claude Code (SDD Workflow)

> **Contexto**: En febrero 2025 diseñamos un `EpisodicMemoryStore` basado en FAISS + Redis
> con reflexión automática via LLM. La implementación original funciona pero tiene limitaciones:
> FAISS es in-memory (no persiste sin archivos), el namespacing es plano, y no soporta
> queries por `room_id`. Esta v2 evoluciona el diseño para soportar episodios per-user
> y per-room usando PgVector como backend principal, manteniendo FAISS como opción local.

---

## 1. Problema que resuelve

Un agente de AI-Parrot atiende múltiples usuarios en múltiples rooms (Matrix, Telegram, Slack).
Necesita recordar:

1. **Per-user**: "La última vez que hablé con @jesus, pregunté por el schema de `orders` y no existía — debo verificar primero"
2. **Per-room**: "En el room !service-desk, el equipo decidió usar el workflow de 3 pasos para tickets P1"
3. **Per-agent (global)**: "Nunca debo llamar `get_schema` sin verificar que el schema está en `allowed_schemas`"
4. **Cross-agent (crew)**: "El ResearchAgent descubrió que la API de pricing tiene rate limit de 10 req/min"

El store episódico captura **qué hizo el agente, qué resultado obtuvo, y qué aprendió**,
permitiendo recall semántico con filtros dimensionales.

---

## 2. Modelo de datos

### 2.1 Episode (tabla principal)

```
parrot_episodic_memory (PgVector table)
├── episode_id: UUID (PK)
├── created_at: TIMESTAMPTZ
├── updated_at: TIMESTAMPTZ
├── expires_at: TIMESTAMPTZ (nullable, para TTL)
│
├── ── Dimensiones de namespace ──
├── tenant_id: VARCHAR(64)       # Aislamiento multi-tenant
├── agent_id: VARCHAR(128)       # Agente que generó el episodio
├── user_id: VARCHAR(128)        # Usuario con quien interactuó (nullable)
├── session_id: VARCHAR(128)     # Sesión de conversación (nullable)
├── room_id: VARCHAR(256)        # Room de Matrix/canal (nullable)
├── crew_id: VARCHAR(128)        # Crew al que pertenece (nullable)
│
├── ── Contenido del episodio ──
├── situation: TEXT               # Qué estaba pasando
├── action_taken: TEXT            # Qué hizo el agente
├── outcome: VARCHAR(16)          # success | failure | partial | timeout
├── outcome_details: TEXT         # Detalles del resultado
├── error_type: VARCHAR(128)      # Tipo de error (nullable)
├── error_message: TEXT           # Mensaje de error (nullable)
│
├── ── Reflexión (generada por LLM) ──
├── reflection: TEXT              # Análisis de lo ocurrido
├── lesson_learned: VARCHAR(512)  # Lección concisa
├── suggested_action: TEXT        # Qué hacer diferente
│
├── ── Clasificación ──
├── category: VARCHAR(32)         # tool_execution | query_resolution | error_recovery |
│                                 # user_preference | workflow_pattern | decision | handoff
├── importance: SMALLINT          # 1-10
├── is_failure: BOOLEAN           # Índice parcial para queries de warnings
├── related_tools: VARCHAR[]      # Array de nombres de tools involucrados
├── related_entities: VARCHAR[]   # Entidades mencionadas (usuarios, tablas, etc.)
│
├── ── Vector embedding ──
├── embedding: VECTOR(384)        # all-MiniLM-L6-v2 (384d) o configurable
│
├── ── Metadata extensible ──
└── metadata: JSONB               # Datos arbitrarios adicionales
```

### 2.2 Índices

```sql
-- Similarity search con filtro dimensional
CREATE INDEX idx_episodes_embedding ON parrot_episodic_memory
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Queries por namespace (los más comunes)
CREATE INDEX idx_episodes_agent_user ON parrot_episodic_memory (tenant_id, agent_id, user_id);
CREATE INDEX idx_episodes_agent_room ON parrot_episodic_memory (tenant_id, agent_id, room_id);
CREATE INDEX idx_episodes_crew ON parrot_episodic_memory (tenant_id, crew_id);

-- Filtro de failures para warnings rápidos
CREATE INDEX idx_episodes_failures ON parrot_episodic_memory (agent_id, is_failure)
  WHERE is_failure = TRUE;

-- TTL cleanup
CREATE INDEX idx_episodes_expires ON parrot_episodic_memory (expires_at)
  WHERE expires_at IS NOT NULL;

-- Importancia para priorización
CREATE INDEX idx_episodes_importance ON parrot_episodic_memory (agent_id, importance DESC);
```

### 2.3 MemoryNamespace (Pydantic)

```python
class MemoryNamespace(BaseModel):
    """Namespace jerárquico para aislar episodios.
    
    Soporta queries a diferentes niveles de granularidad:
    - Global agent: (tenant_id, agent_id) → "todo lo que sabe este agente"
    - Per-user: (tenant_id, agent_id, user_id) → "episodios con este usuario"
    - Per-room: (tenant_id, agent_id, room_id) → "episodios en este room"
    - Per-session: (tenant_id, agent_id, user_id, session_id) → "esta conversación"
    - Per-crew: (tenant_id, crew_id) → "episodios compartidos del crew"
    """
    tenant_id: str = "default"
    agent_id: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    room_id: Optional[str] = None
    crew_id: Optional[str] = None

    def build_filter(self) -> Dict[str, Any]:
        """Genera filtro SQL WHERE para este namespace."""
        filters = {"tenant_id": self.tenant_id, "agent_id": self.agent_id}
        if self.user_id:
            filters["user_id"] = self.user_id
        if self.session_id:
            filters["session_id"] = self.session_id
        if self.room_id:
            filters["room_id"] = self.room_id
        if self.crew_id:
            filters["crew_id"] = self.crew_id
        return filters

    @property
    def scope_label(self) -> str:
        """Etiqueta legible del scope."""
        if self.session_id:
            return f"session:{self.session_id}"
        if self.room_id:
            return f"room:{self.room_id}"
        if self.user_id:
            return f"user:{self.user_id}"
        if self.crew_id:
            return f"crew:{self.crew_id}"
        return f"agent:{self.agent_id}"

    @property
    def redis_prefix(self) -> str:
        """Prefix para cache en Redis."""
        parts = [self.tenant_id, self.agent_id]
        if self.room_id:
            parts.append(f"room:{self.room_id}")
        elif self.user_id:
            parts.append(f"user:{self.user_id}")
        return ":".join(parts)
```

---

## 3. Arquitectura del Store

### 3.1 Backend Strategy

```
┌────────────────────────────────────┐
│        EpisodicMemoryStore         │
│                                    │
│  ┌──────────────────────────────┐  │
│  │    AbstractEpisodeBackend    │  │ ← Protocol/ABC
│  └─────────┬────────────────────┘  │
│            │                       │
│  ┌─────────▼──────┐ ┌───────────┐ │
│  │ PgVectorBackend│ │FAISSBackend│ │ ← Implementaciones
│  │  (production)  │ │  (local)   │ │
│  └────────────────┘ └───────────┘  │
│                                    │
│  ┌──────────────────────────────┐  │
│  │      ReflectionEngine        │  │ ← Genera lesson_learned via LLM
│  └──────────────────────────────┘  │
│                                    │
│  ┌──────────────────────────────┐  │
│  │     EmbeddingProvider        │  │ ← sentence-transformers (lazy load)
│  └──────────────────────────────┘  │
│                                    │
│  ┌──────────────────────────────┐  │
│  │       Redis (hot cache)      │  │ ← Cache de episodios recientes
│  └──────────────────────────────┘  │
└────────────────────────────────────┘
```

### 3.2 AbstractEpisodeBackend (Protocol)

```python
class AbstractEpisodeBackend(Protocol):
    """Backend de almacenamiento para episodios."""

    async def store(self, episode: EpisodicMemory) -> str:
        """Almacena un episodio. Retorna episode_id."""
        ...

    async def search_similar(
        self,
        embedding: List[float],
        namespace_filter: Dict[str, Any],
        top_k: int = 5,
        score_threshold: float = 0.3,
        include_failures_only: bool = False,
    ) -> List[EpisodeSearchResult]:
        """Búsqueda por similitud semántica con filtros."""
        ...

    async def get_recent(
        self,
        namespace_filter: Dict[str, Any],
        limit: int = 10,
        since: Optional[datetime] = None,
    ) -> List[EpisodicMemory]:
        """Episodios recientes por namespace."""
        ...

    async def get_failures(
        self,
        agent_id: str,
        tenant_id: str = "default",
        limit: int = 5,
    ) -> List[EpisodicMemory]:
        """Últimos failures de un agente (para warnings)."""
        ...

    async def delete_expired(self) -> int:
        """Limpia episodios expirados. Retorna cantidad eliminada."""
        ...

    async def count(self, namespace_filter: Dict[str, Any]) -> int:
        """Cuenta episodios en un namespace."""
        ...
```

### 3.3 PgVectorBackend

```python
class PgVectorBackend:
    """Backend PostgreSQL + pgvector para episodios.
    
    Usa asyncpg directamente (no SQLAlchemy) para máximo control.
    Schema-aware: cada tenant puede tener su propio schema PostgreSQL.
    
    Parámetros:
        dsn: PostgreSQL connection string
        schema: Schema name (default: "parrot_memory")
        table: Table name (default: "episodic_memory")
        pool_size: Connection pool size
    """

    async def configure(self) -> None:
        """Crea pool, schema, tabla e índices si no existen."""
        ...

    async def store(self, episode: EpisodicMemory) -> str:
        """INSERT con ON CONFLICT DO NOTHING (idempotente)."""
        ...

    async def search_similar(
        self,
        embedding: List[float],
        namespace_filter: Dict[str, Any],
        top_k: int = 5,
        score_threshold: float = 0.3,
        include_failures_only: bool = False,
    ) -> List[EpisodeSearchResult]:
        """
        Query:
            SELECT *, 1 - (embedding <=> $1::vector) AS score
            FROM {schema}.{table}
            WHERE tenant_id = $2 AND agent_id = $3
              AND (user_id = $4 OR $4 IS NULL)
              AND (room_id = $5 OR $5 IS NULL)
              AND ($6 = FALSE OR is_failure = TRUE)
            ORDER BY embedding <=> $1::vector
            LIMIT $7
        
        Score threshold aplicado post-query.
        """
        ...
```

### 3.4 FAISSBackend (para desarrollo local / sin PostgreSQL)

```python
class FAISSBackend:
    """Backend FAISS + dict en memoria para desarrollo local.
    
    Persiste opcionalmente a disco:
    - {persistence_path}/episodes.faiss → índice vectorial
    - {persistence_path}/episodes.jsonl → metadata de episodios
    
    No soporta queries SQL complejas — los filtros se aplican post-search.
    """
    ...
```

---

## 4. API del EpisodicMemoryStore

### 4.1 Recording

```python
class EpisodicMemoryStore:
    """Store principal — orquesta backend, reflection, embedding, cache."""

    async def record_episode(
        self,
        namespace: MemoryNamespace,
        situation: str,
        action_taken: str,
        outcome: EpisodeOutcome,
        *,
        outcome_details: Optional[str] = None,
        category: EpisodeCategory = EpisodeCategory.TOOL_EXECUTION,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        related_tools: Optional[List[str]] = None,
        related_entities: Optional[List[str]] = None,
        importance: Optional[int] = None,  # Auto-calculado si None
        generate_reflection: bool = True,  # Usa LLM para lesson_learned
        metadata: Optional[Dict[str, Any]] = None,
        ttl_days: Optional[int] = None,   # Override del default
    ) -> EpisodicMemory:
        """Registra un episodio completo.
        
        Flujo:
        1. Auto-calcula importancia si no se provee
           - Failures: base 7 + boost
           - Success: base 3
           - Con error_type conocido: +2
        2. Si generate_reflection y tenemos LLM: genera reflexión
        3. Embeds el texto searchable (situation + action + outcome)
        4. Almacena en backend
        5. Cachea en Redis si está disponible
        6. Retorna el episodio completo
        """
        ...

    async def record_tool_episode(
        self,
        namespace: MemoryNamespace,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_result: "ToolResult",
        user_query: str,
        *,
        generate_reflection: bool = True,
    ) -> Optional[EpisodicMemory]:
        """Convenience: registra episodio de ejecución de tool.
        
        Extrae automáticamente:
        - situation: del user_query
        - action_taken: "Called {tool_name} with {args_summary}"
        - outcome: del tool_result.status
        - error: del tool_result.error
        - importance: calculada según outcome + tool criticality
        
        Solo registra si es significativo (no registra tool calls triviales
        como 'get_time' que siempre son success).
        """
        ...

    async def record_crew_episode(
        self,
        namespace: MemoryNamespace,
        crew_result: "CrewResult",
        flow_description: str,
        *,
        per_agent: bool = True,  # Registrar también por agente individual
    ) -> List[EpisodicMemory]:
        """Registra episodio(s) de ejecución de crew.
        
        Crea:
        1. Un episodio global del crew (crew_id en namespace)
        2. Opcionalmente, un episodio por cada agente que participó
        """
        ...
```

### 4.2 Recall

```python
    async def recall_similar(
        self,
        query: str,
        namespace: MemoryNamespace,
        *,
        top_k: int = 5,
        score_threshold: float = 0.3,
        include_failures_only: bool = False,
        categories: Optional[List[EpisodeCategory]] = None,
        since: Optional[datetime] = None,
    ) -> List[EpisodeSearchResult]:
        """Búsqueda semántica de episodios similares.
        
        El namespace determina el scope:
        - Solo agent_id → busca en todo lo que sabe el agente
        - Con user_id → solo episodios con ese usuario
        - Con room_id → solo episodios en ese room
        """
        ...

    async def get_failure_warnings(
        self,
        namespace: MemoryNamespace,
        current_query: str,
        *,
        max_warnings: int = 3,
    ) -> str:
        """Genera texto de warnings para inyectar en system prompt.
        
        Retorna algo como:
            ⚠️ MISTAKES TO AVOID:
            - Tool 'get_schema' failed for schema 'analytics' — verify schema exists first
            - API rate limit hit on pricing service — add 1s delay between calls
            
            ✓ SUCCESSFUL APPROACHES:
            - For database questions, always run schema discovery first
        """
        ...

    async def get_user_preferences(
        self,
        namespace: MemoryNamespace,  # Debe incluir user_id
    ) -> List[EpisodicMemory]:
        """Recupera episodios de categoría USER_PREFERENCE para un usuario.
        
        Útil para recordar: "Este usuario prefiere respuestas en español",
        "Este usuario es técnico, no necesita explicaciones básicas", etc.
        """
        ...

    async def get_room_context(
        self,
        namespace: MemoryNamespace,  # Debe incluir room_id
        *,
        limit: int = 10,
        categories: Optional[List[EpisodeCategory]] = None,
    ) -> List[EpisodicMemory]:
        """Recupera episodios recientes de un room.
        
        Útil para que un agente que entra a un room sepa qué ha pasado:
        decisiones tomadas, workflows ejecutados, errores encontrados.
        """
        ...
```

### 4.3 Maintenance

```python
    async def cleanup_expired(self) -> int:
        """Elimina episodios expirados. Llamar periódicamente (cron/scheduler)."""
        ...

    async def compact_namespace(
        self,
        namespace: MemoryNamespace,
        keep_top_n: int = 100,
        keep_all_failures: bool = True,
    ) -> int:
        """Compacta un namespace manteniendo los N más importantes.
        
        Failures siempre se mantienen (son las más valiosas).
        """
        ...

    async def export_episodes(
        self,
        namespace: MemoryNamespace,
        format: str = "jsonl",
    ) -> str:
        """Exporta episodios de un namespace (para debugging/audit)."""
        ...
```

---

## 5. Integración con AbstractBot

### 5.1 EpisodicMemoryMixin (evolución de v1)

```python
class EpisodicMemoryMixin:
    """Mixin para AbstractBot que añade memoria episódica automática.
    
    Cambios vs v1:
    - Soporta room_id (Matrix, Slack, etc.)
    - Backend pluggable (PgVector o FAISS)
    - Cache en Redis para episodios hot
    - Integración con AgentsFlow (crew_id)
    """

    # ── Config (override en subclass o via kwargs) ──
    enable_episodic_memory: bool = True
    episodic_backend: str = "pgvector"  # "pgvector" | "faiss"
    episodic_dsn: Optional[str] = None  # Para PgVector
    episodic_schema: str = "parrot_memory"
    episodic_reflection_enabled: bool = True
    episodic_inject_warnings: bool = True
    episodic_max_warnings: int = 3
    episodic_trivial_tools: Set[str] = {"get_time", "get_date"}  # No registrar

    async def _configure_episodic_memory(self) -> None:
        """Auto-called durante configure()."""
        ...

    async def _build_episodic_context(
        self,
        query: str,
        user_id: Optional[str] = None,
        room_id: Optional[str] = None,
    ) -> str:
        """Construye contexto episódico para inyectar en system prompt.
        
        Combina:
        1. Failure warnings relevantes al query actual
        2. User preferences (si hay user_id)
        3. Room context reciente (si hay room_id)
        """
        ...

    async def _record_post_tool(
        self,
        tool_name: str,
        tool_args: Dict,
        tool_result: "ToolResult",
        user_query: str,
        user_id: str,
        session_id: str,
        room_id: Optional[str] = None,
    ) -> None:
        """Hook post-tool que registra episodio si es significativo."""
        ...

    async def _record_post_ask(
        self,
        query: str,
        response: "BotResponse",
        user_id: str,
        session_id: str,
        room_id: Optional[str] = None,
    ) -> None:
        """Hook post-ask para registrar episodios de nivel conversación."""
        ...
```

### 5.2 Integración en el ask() loop

```python
# En BaseAgent.ask() — pseudo-código del flujo modificado:

async def ask(self, question, user_id=None, session_id=None, room_id=None, **kwargs):
    # 1. Build episodic context ANTES del LLM call
    if self.enable_episodic_memory and self._episodic_store:
        episodic_context = await self._build_episodic_context(
            query=question,
            user_id=user_id,
            room_id=room_id,
        )
        # Inyectar en system prompt
        if episodic_context:
            system_prompt += f"\n\n{episodic_context}"

    # 2. LLM call normal...
    response = await self._llm_client.ask(...)

    # 3. Record tool episodes DESPUÉS de cada tool call
    for tool_call in response.tool_calls:
        await self._record_post_tool(
            tool_name=tool_call.name,
            tool_args=tool_call.arguments,
            tool_result=tool_call.result,
            user_query=question,
            user_id=user_id,
            session_id=session_id,
            room_id=room_id,
        )

    # 4. Record conversation episode si es significativo
    await self._record_post_ask(
        query=question,
        response=response,
        user_id=user_id,
        session_id=session_id,
        room_id=room_id,
    )

    return response
```

---

## 6. Integración con Matrix Crew Rooms

### 6.1 Cuando un agente opera en un Matrix room

```python
# El MatrixCrewOrchestrator establece room_id en el namespace:

namespace = MemoryNamespace(
    tenant_id=tenant_id,
    agent_id=agent.name,
    room_id="!service-desk:parrot.local",
    crew_id="service_desk_crew",
)

# Cada agente del crew registra sus episodios con room_id
# Cuando un nuevo agente se une al room, puede hacer:

room_context = await store.get_room_context(
    namespace=MemoryNamespace(
        tenant_id=tenant_id,
        agent_id=new_agent.name,
        room_id="!service-desk:parrot.local",
    ),
    limit=20,
)
# → Obtiene: decisiones tomadas, errores encontrados, preferencias del room
```

### 6.2 Episodios de handoff entre agentes

```python
# Cuando TriageAgent hace handoff a ResolverAgent:

await store.record_episode(
    namespace=MemoryNamespace(
        tenant_id=tenant_id,
        agent_id="TriageAgent",
        room_id="!service-desk:parrot.local",
        crew_id="service_desk_crew",
    ),
    situation="Ticket #4521: usuario necesita acceso a producción",
    action_taken="Handoff a ResolverAgent con contexto de política RBAC",
    outcome=EpisodeOutcome.SUCCESS,
    category=EpisodeCategory.HANDOFF,
    related_entities=["ResolverAgent", "user:@carlos", "ticket:4521"],
    metadata={
        "handoff_reason": "requires_provisioning",
        "context_passed": "RBAC policy check passed for staging, needs approval for prod",
    },
)
```

---

## 7. ReflectionEngine

```python
class ReflectionEngine:
    """Genera reflexiones usando un LLM ligero.
    
    El LLM analiza el episodio y extrae:
    - reflection: Análisis breve de qué pasó
    - lesson_learned: Lección concisa (< 100 chars idealmente)
    - suggested_action: Qué hacer diferente la próxima vez
    
    Usa un prompt especializado y structured output.
    """

    REFLECTION_PROMPT = """Analyze this agent interaction episode and extract a concise lesson.

Episode:
- Situation: {situation}
- Action taken: {action_taken}
- Outcome: {outcome}
- Error (if any): {error_message}

Respond with:
1. reflection: Brief analysis of what happened (1-2 sentences)
2. lesson_learned: Concise actionable lesson (max 100 characters)
3. suggested_action: What to do differently next time (1 sentence)

Focus on ACTIONABLE insights the agent can use in future similar situations."""

    def __init__(
        self,
        llm_client: Optional["AbstractClient"] = None,
        llm_provider: str = "google",
        model: str = "gemini-2.5-flash",
        fallback_to_heuristic: bool = True,
    ):
        ...

    async def reflect(
        self,
        situation: str,
        action_taken: str,
        outcome: EpisodeOutcome,
        error_message: Optional[str] = None,
    ) -> ReflectionResult:
        """Genera reflexión via LLM o heurística fallback."""
        ...

    def _heuristic_reflect(
        self,
        situation: str,
        action_taken: str,
        outcome: EpisodeOutcome,
        error_message: Optional[str] = None,
    ) -> ReflectionResult:
        """Reflexión heurística cuando no hay LLM disponible.
        
        Patrones conocidos:
        - tool_not_found → "Verify tool exists before calling"
        - timeout → "Consider reducing scope or adding timeout"
        - rate_limit → "Add delay between API calls"
        - permission_denied → "Check permissions before action"
        """
        ...
```

---

## 8. Embedding Provider

```python
class EpisodeEmbeddingProvider:
    """Lazy-loading embedding provider para episodios.
    
    Usa sentence-transformers con lazy import para no afectar startup.
    Default model: all-MiniLM-L6-v2 (384d, rápido, bueno para retrieval)
    
    Alternativa configurable: all-mpnet-base-v2 (768d, más preciso, más lento)
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        dimension: int = 384,
        device: str = "cpu",
        batch_size: int = 32,
    ):
        self._model = None  # Lazy
        ...

    async def embed(self, text: str) -> List[float]:
        """Genera embedding para un texto (usa asyncio.to_thread)."""
        ...

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Batch embedding para múltiples textos."""
        ...

    def _get_searchable_text(self, episode: EpisodicMemory) -> str:
        """Construye texto para embedding.
        
        Formato: "{situation} | {action_taken} | {lesson_learned}"
        Prioriza situation y lesson para mejor retrieval.
        """
        ...
```

---

## 9. Redis Hot Cache

```python
class EpisodeRedisCache:
    """Cache de episodios recientes en Redis para acceso rápido.
    
    Estrategia:
    - Los últimos N episodios por namespace se cachean como hash en Redis
    - TTL de 1 hora por default (configurable)
    - get_failure_warnings usa este cache primero
    - Invalidación: al escribir un nuevo episodio, el cache del namespace se invalida
    
    Keys:
    - episodic:{tenant}:{agent}:recent → ZSET (scored by timestamp)
    - episodic:{tenant}:{agent}:{episode_id} → HASH (episode data)
    - episodic:{tenant}:{agent}:failures → LIST (últimos failures)
    """
    ...
```

---

## 10. Ubicación en el proyecto

```
parrot/
└── memory/
    ├── __init__.py
    ├── abstract.py          # ConversationMemory (existente)
    ├── mem.py               # InMemoryConversation (existente)
    ├── redis.py             # RedisConversation (existente)
    ├── file.py              # FileConversation (existente)
    └── episodic/            # NUEVO (módulo completo)
        ├── __init__.py      # Exports públicos
        ├── models.py        # EpisodicMemory, MemoryNamespace, enums, schemas Pydantic
        ├── store.py         # EpisodicMemoryStore (orquestador principal)
        ├── backends/
        │   ├── __init__.py
        │   ├── abstract.py  # AbstractEpisodeBackend (Protocol)
        │   ├── pgvector.py  # PgVectorBackend
        │   └── faiss.py     # FAISSBackend (local/dev)
        ├── reflection.py    # ReflectionEngine
        ├── embedding.py     # EpisodeEmbeddingProvider
        ├── cache.py         # EpisodeRedisCache
        ├── tools.py         # EpisodicMemorySearchTool, RecordTool, WarningsTool
        └── mixin.py         # EpisodicMemoryMixin para AbstractBot
```

---

## 11. Tareas SDD sugeridas

### Task 1: `models.py` — Modelos y enums
- EpisodicMemory dataclass con to_dict/from_dict
- MemoryNamespace con build_filter y scope_label
- EpisodeOutcome, EpisodeCategory, MemoryImportance enums
- EpisodeSearchResult, ReflectionResult
- Pydantic schemas para tools (RecordEpisodeArgs, SearchEpisodesArgs)

### Task 2: `backends/abstract.py` + `backends/pgvector.py` — Backend PgVector
- AbstractEpisodeBackend Protocol
- PgVectorBackend con asyncpg pool
- Auto-create schema/table/indexes en configure()
- search_similar con filtros dimensionales
- get_recent, get_failures, delete_expired, count
- Tests con PostgreSQL real

### Task 3: `backends/faiss.py` — Backend FAISS local
- FAISSBackend con HNSW index
- Persistencia a disco (faiss + jsonl)
- Post-search filtering (no tiene SQL)
- Tests unitarios

### Task 4: `embedding.py` + `reflection.py` — Embedding y Reflexión
- EpisodeEmbeddingProvider con lazy loading
- ReflectionEngine con structured output
- Heuristic fallback cuando no hay LLM
- Tests con mocks

### Task 5: `store.py` — EpisodicMemoryStore principal
- Orquesta backend + reflection + embedding + cache
- record_episode, record_tool_episode, record_crew_episode
- recall_similar, get_failure_warnings, get_user_preferences, get_room_context
- cleanup_expired, compact_namespace, export_episodes
- Tests de integración

### Task 6: `cache.py` — Redis hot cache
- EpisodeRedisCache con ZSET + HASH
- Invalidación por namespace
- Failure warnings cache dedicado
- Tests con Redis mock

### Task 7: `tools.py` — Tools para agentes
- EpisodicMemorySearchTool (buscar episodios similares)
- EpisodicMemoryRecordTool (registrar aprendizaje explícito)
- GetFailureWarningsTool (obtener warnings)
- Integración con ToolManager

### Task 8: `mixin.py` — EpisodicMemoryMixin
- Auto-configure en configure()
- _build_episodic_context para system prompt
- _record_post_tool y _record_post_ask hooks
- Integración con room_id y crew_id
- Tests de integración con BasicAgent

---

## 12. Decisiones de diseño clave

| Decisión | Opción elegida | Razón |
|----------|---------------|-------|
| Backend primario | PgVector | Ya lo usamos para RAG, persiste, soporta filtros SQL complejos |
| Backend secundario | FAISS | Para desarrollo local sin PostgreSQL |
| Embedding model | all-MiniLM-L6-v2 (384d) | Balance velocidad/calidad para textos cortos |
| Dimensión vector | 384 | Match con all-MiniLM-L6-v2 |
| Reflexión | LLM + heuristic fallback | No depender 100% del LLM para funcionar |
| Cache | Redis ZSET + HASH | Ya tenemos Redis en la infra |
| Aislamiento | Schema PostgreSQL por tenant | Mismo patrón que usamos en Ontological RAG |
| Score threshold | 0.3 default | Sentence-transformers con cosine funciona bien con umbrales bajos |
| Trivial tool filter | Set configurable | Evita llenar la DB con episodios irrelevantes |
| TTL | 90 días default, configurable | Balance entre retención y tamaño |