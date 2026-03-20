# Feature Specification: Finance Research Collective Memory

**Feature ID**: FEAT-010
**Date**: 2026-03-03
**Author**: Claude
**Status**: approved
**Target version**: next
**Brainstorm**: `sdd/proposals/finance-research.brainstorm.md`

---

## 1. Motivation & Business Requirements

> Rediseñar radicalmente el sistema Finance Research + Analyst para usar memoria colectiva con scheduler granular, deduplicación inteligente, y modelo pull para analysts.

### Problem Statement

El sistema actual de Finance Research tiene limitaciones arquitectónicas fundamentales:

1. **Ejecución secuencial ineficiente** — Los research crews corren uno tras otro, sin considerar que algunos datos (ej. FRED macro) no necesitan actualizarse cada hora.

2. **Acoplamiento rígido research → analyst** — Los analistas "reciben" los briefings pasivamente en lugar de "buscarlos" activamente, impidiendo:
   - Polinización cruzada efectiva (un analyst accediendo a research de otro dominio)
   - Comparación temporal (research actual vs. previo)
   - Deduplicación inteligente

3. **Dependencia de Redis** — El `ResearchBriefingStore` actual está 100% acoplado a Redis con pub/sub, requiriendo infraestructura adicional para desarrollo local.

4. **Sin control de frecuencia granular** — Todos los crews corren en schedules predefinidos sin considerar si ya existe un research válido para el período.

### Goals

- **Collective Memory Store**: Repository de documentos de research con filesystem persistence + in-memory cache
- **Scheduler granular**: Frecuencia configurable por crew (daily para FRED, 4h para crypto)
- **Deduplication tool**: Research agents verifican existencia antes de ejecutar
- **Pull model**: Analysts buscan activamente en memoria colectiva (latest, history, cross-domain)
- **Audit trail log**: Log append-only para responder "¿qué pasó ayer a las 3pm?"
- **Fire-and-forget writes**: Persistencia asíncrona sin bloquear pipeline
- **Sin Redis**: Filesystem + in-memory cache solamente

### Non-Goals (explicitly out of scope)

- Redis backend (explícitamente excluido por requisito)
- Migración de datos existentes (clean slate)
- Vector embeddings de research (feature separada)
- Notificaciones push a analysts (usan pull model)

---

## 2. Architectural Design

### Overview

Implementar un **Hybrid Memory Store** (patrón C del brainstorm) con únicamente FileSystem backend. Seguir el patrón establecido por `ConversationMemory` en `parrot/memory/abstract.py` con una clase abstracta `ResearchMemory` y una implementación `FileResearchMemory`.

Incluir un **Audit Trail Log** (`research_events.jsonl`) dentro del Document Store para tracking de actividad.

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Research Crews (Scheduled)                         │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐           │
│  │  Macro  │  │ Equity  │  │ Crypto  │  │ Sentim. │  │  Risk   │           │
│  │ (daily) │  │ (2x/day)│  │ (4h)    │  │ (6h)    │  │ (3x/day)│           │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘           │
│       │            │            │            │            │                 │
│       ▼            ▼            ▼            ▼            ▼                 │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                 DeduplicationTool.check_exists()                      │  │
│  │                 "Already completed for 2026-03-03? Skip."             │  │
│  └────────────────────────────────┬─────────────────────────────────────┘  │
│                                   │ If not exists                          │
│                                   ▼                                        │
│                        ┌────────────────────┐                              │
│                        │  Execute Research  │                              │
│                        └─────────┬──────────┘                              │
└──────────────────────────────────┼──────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                      CollectiveResearchMemory                                 │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                    ResearchMemory (Abstract)                           │  │
│  │   store() | get() | exists() | query() | get_history() | cleanup()    │  │
│  └────────────────────────────────┬───────────────────────────────────────┘  │
│                                   │                                          │
│               ┌───────────────────┼───────────────────┐                      │
│               ▼                   ▼                   ▼                      │
│  ┌────────────────────┐  ┌────────────────┐  ┌────────────────────┐         │
│  │ In-Memory Cache    │  │ FileBackend    │  │ AuditTrailLog      │         │
│  │ (dict + LRU)       │  │ (aiofiles)     │  │ (append-only JSONL)│         │
│  │                    │  │                │  │                    │         │
│  │ crew_id → period → │  │ {domain}/      │  │ research_events.   │         │
│  │   ResearchDocument │  │  {crew_id}/    │  │   jsonl            │         │
│  └────────────────────┘  │   {period}.json│  └────────────────────┘         │
│                          └────────────────┘                                  │
│                                   │                                          │
│                          Fire-and-forget                                     │
│                          asyncio.create_task()                               │
└──────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   │ Pull Model
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                           Analyst Agents                                      │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐            │
│  │  Macro  │  │ Equity  │  │ Crypto  │  │ Sentim. │  │  Risk   │            │
│  │ Analyst │  │ Analyst │  │ Analyst │  │ Analyst │  │ Analyst │            │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘            │
│       │            │            │            │            │                  │
│       ▼            ▼            ▼            ▼            ▼                  │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    ResearchQueryTools                                 │   │
│  │  get_latest_research(domain)                                         │   │
│  │  get_research_history(domain, last_n=2)                              │   │
│  │  get_cross_domain_research(domains=["macro", "sentiment"])           │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
research_memory/                          # Base directory (configurable)
├── _index.json                           # Quick lookup metadata index
├── _audit_log/
│   └── research_events.jsonl             # Append-only audit trail
├── _historical/                          # Archived documents (>7 days)
│   └── 2026-02/
│       └── macro/
│           └── research_crew_macro/
│               └── 2026-02-24.json
├── macro/
│   └── research_crew_macro/
│       ├── 2026-03-03.json               # Daily period
│       └── 2026-03-02.json
├── equity/
│   └── research_crew_equity/
│       ├── 2026-03-03.json
│       └── 2026-03-02.json
├── crypto/
│   └── research_crew_crypto/
│       ├── 2026-03-03T14:00:00.json      # ISO format for hourly
│       └── 2026-03-03T10:00:00.json
├── sentiment/
│   └── research_crew_sentiment/
│       └── 2026-03-03.json
└── risk/
    └── research_crew_risk/
        └── 2026-03-03.json
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/memory/abstract.py` | pattern reference | Follow `ConversationMemory` ABC pattern |
| `parrot/memory/file.py` | pattern reference | Reuse async file I/O patterns |
| `parrot/memory/cache.py` | pattern reference | Reuse fire-and-forget pattern |
| `parrot/finance/research/briefing_store.py` | **replaces** | New `CollectiveResearchMemory` |
| `parrot/finance/research/service.py` | modifies | Use new memory, remove Redis |
| `parrot/finance/research/trigger.py` | modifies | Check memory instead of Redis |
| `parrot/finance/agents/research.py` | modifies | Add deduplication tool |
| `parrot/finance/agents/analysts.py` | modifies | Add query tools |
| `parrot/finance/swarm.py` | modifies | Pull from memory |
| `parrot/pageindex/` | future integration | Potential use for indexing |

### Data Models

```python
# parrot/finance/research/memory/schemas.py

from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field
from parrot.finance.schemas import ResearchBriefing


class ResearchDocument(BaseModel):
    """A research document stored in collective memory."""

    id: str = Field(description="Unique document ID (UUID)")
    crew_id: str = Field(description="Research crew identifier")
    domain: str = Field(description="Research domain: macro, equity, crypto, sentiment, risk")
    period_key: str = Field(description="Period identifier in ISO format: 2026-03-03 or 2026-03-03T14:00:00")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    briefing: ResearchBriefing = Field(description="The actual research briefing content")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    @property
    def is_daily(self) -> bool:
        """Check if this is a daily-granularity document."""
        return "T" not in self.period_key


class ResearchScheduleConfig(BaseModel):
    """Configuration for research crew scheduling."""

    crew_id: str
    cron_expression: str = Field(description="Cron expression for scheduling")
    period_granularity: str = Field(
        default="daily",
        description="Period granularity: daily, 4h, 6h, hourly"
    )
    staleness_hours: int = Field(
        default=24,
        description="Hours after which research is considered stale"
    )


class AuditEvent(BaseModel):
    """An event in the audit trail log."""

    event_type: str = Field(description="Event type: stored, accessed, expired, cleaned")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    crew_id: str
    period_key: str
    domain: str
    actor: Optional[str] = Field(None, description="Who triggered the event (crew_id or analyst_id)")
    details: dict[str, Any] = Field(default_factory=dict)


# Schedule configurations (default)
DEFAULT_RESEARCH_SCHEDULES: dict[str, ResearchScheduleConfig] = {
    "research_crew_macro": ResearchScheduleConfig(
        crew_id="research_crew_macro",
        cron_expression="0 6,14 * * *",      # 2x/day (6am, 2pm UTC)
        period_granularity="daily",
        staleness_hours=24,
    ),
    "research_crew_equity": ResearchScheduleConfig(
        crew_id="research_crew_equity",
        cron_expression="0 7,13 * * 1-5",    # 2x/day weekdays
        period_granularity="daily",
        staleness_hours=12,
    ),
    "research_crew_crypto": ResearchScheduleConfig(
        crew_id="research_crew_crypto",
        cron_expression="0 */4 * * *",       # Every 4 hours
        period_granularity="4h",
        staleness_hours=4,
    ),
    "research_crew_sentiment": ResearchScheduleConfig(
        crew_id="research_crew_sentiment",
        cron_expression="0 */6 * * *",       # Every 6 hours
        period_granularity="6h",
        staleness_hours=6,
    ),
    "research_crew_risk": ResearchScheduleConfig(
        crew_id="research_crew_risk",
        cron_expression="0 8,14,20 * * *",   # 3x/day
        period_granularity="daily",
        staleness_hours=8,
    ),
}
```

### New Public Interfaces

```python
# parrot/finance/research/memory/abstract.py

from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime


class ResearchMemory(ABC):
    """Abstract base class for research memory storage.

    Follows the pattern established by ConversationMemory in parrot/memory/abstract.py.
    """

    @abstractmethod
    async def store(self, document: ResearchDocument) -> str:
        """Store a research document. Returns document ID."""
        pass

    @abstractmethod
    async def get(
        self,
        crew_id: str,
        period_key: str,
    ) -> Optional[ResearchDocument]:
        """Get a specific research document by crew and period."""
        pass

    @abstractmethod
    async def exists(
        self,
        crew_id: str,
        period_key: str,
    ) -> bool:
        """Check if a research document exists for the given crew and period."""
        pass

    @abstractmethod
    async def get_latest(
        self,
        domain: str,
    ) -> Optional[ResearchDocument]:
        """Get the most recent research document for a domain."""
        pass

    @abstractmethod
    async def get_history(
        self,
        domain: str,
        last_n: int = 5,
    ) -> list[ResearchDocument]:
        """Get the N most recent documents for a domain."""
        pass

    @abstractmethod
    async def query(
        self,
        domains: Optional[list[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> list[ResearchDocument]:
        """Query documents with filters."""
        pass

    @abstractmethod
    async def cleanup(
        self,
        retention_days: int = 7,
    ) -> int:
        """Archive documents older than retention period. Returns count archived."""
        pass

    @abstractmethod
    async def get_audit_events(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        event_type: Optional[str] = None,
    ) -> list[AuditEvent]:
        """Query audit trail events."""
        pass


# parrot/finance/research/memory/file.py

class FileResearchMemory(ResearchMemory):
    """Filesystem-based research memory with in-memory cache.

    Features:
    - In-memory cache (dict) for fast reads
    - Fire-and-forget writes to filesystem
    - Append-only audit trail log
    - Automatic cleanup/archival of old documents
    - Cache warming at startup
    """

    def __init__(
        self,
        base_path: str = "./research_memory",
        cache_max_size: int = 100,
        warmup_on_init: bool = True,
    ):
        """Initialize the file-based research memory.

        Args:
            base_path: Base directory for storage
            cache_max_size: Maximum documents to keep in memory cache
            warmup_on_init: Load existing documents into cache at startup
        """
        ...

    async def start(self) -> None:
        """Initialize the memory store (create dirs, warm cache, run cleanup)."""
        ...

    async def stop(self) -> None:
        """Graceful shutdown (flush pending writes)."""
        ...


# parrot/finance/research/memory/tools.py

from parrot.tools import tool

@tool
def check_research_exists(crew_id: str, period_key: str) -> dict:
    """Check if research already exists for this crew and period.

    Use this BEFORE executing research to avoid duplicate work.

    Args:
        crew_id: The research crew identifier (e.g., "research_crew_macro")
        period_key: The period in ISO format (e.g., "2026-03-03" for daily)

    Returns:
        {"exists": bool, "message": str, "document_id": str | None}
    """
    ...


@tool
def store_research(briefing: dict, crew_id: str, domain: str) -> dict:
    """Store a completed research briefing in collective memory.

    Args:
        briefing: The research briefing content (ResearchBriefing dict)
        crew_id: The research crew identifier
        domain: The research domain (macro, equity, crypto, sentiment, risk)

    Returns:
        {"success": bool, "document_id": str, "period_key": str}
    """
    ...


@tool
def get_latest_research(domain: str) -> dict:
    """Get the most recent research for a domain.

    Use this to pull the latest research from collective memory.

    Args:
        domain: The research domain (macro, equity, crypto, sentiment, risk)

    Returns:
        The ResearchDocument or {"error": "No research found for domain"}
    """
    ...


@tool
def get_research_history(domain: str, last_n: int = 2) -> list[dict]:
    """Get recent research history for a domain.

    Useful for comparing current research with previous periods.

    Args:
        domain: The research domain
        last_n: Number of recent documents to retrieve (default: 2)

    Returns:
        List of ResearchDocument dicts ordered by date descending
    """
    ...


@tool
def get_cross_domain_research(domains: list[str]) -> dict[str, dict]:
    """Get the latest research from multiple domains.

    Use this for cross-pollination analysis across different research areas.

    Args:
        domains: List of domains to query (e.g., ["macro", "sentiment"])

    Returns:
        Dict mapping domain → latest ResearchDocument
    """
    ...
```

---

## 3. Module Breakdown

### Module 1: Data Models
- **Path**: `parrot/finance/research/memory/schemas.py`
- **Responsibility**: Pydantic models for `ResearchDocument`, `ResearchScheduleConfig`, `AuditEvent`. Define schedule configurations.
- **Depends on**: `pydantic`, `parrot/finance/schemas.py`

### Module 2: Abstract Memory Interface
- **Path**: `parrot/finance/research/memory/abstract.py`
- **Responsibility**: `ResearchMemory` ABC defining the interface. Follows `ConversationMemory` pattern.
- **Depends on**: Module 1

### Module 3: File Memory Implementation
- **Path**: `parrot/finance/research/memory/file.py`
- **Responsibility**: `FileResearchMemory` implementation with in-memory cache, fire-and-forget writes, audit trail, and cleanup.
- **Depends on**: Module 1, Module 2, `aiofiles`

### Module 4: Research Tools
- **Path**: `parrot/finance/research/memory/tools.py`
- **Responsibility**: Tools for crews (`check_research_exists`, `store_research`) and analysts (`get_latest_research`, `get_research_history`, `get_cross_domain_research`).
- **Depends on**: Module 3, `parrot/tools`

### Module 5: Service Integration
- **Path**: `parrot/finance/research/service.py` (modify existing)
- **Responsibility**: Replace `ResearchBriefingStore` usage with `FileResearchMemory`. Update schedules to use `ResearchScheduleConfig`.
- **Depends on**: Module 3

### Module 6: Crew Integration
- **Path**: `parrot/finance/agents/research.py` (modify existing)
- **Responsibility**: Add deduplication tool to each research crew. Update prompts to use check-before-execute pattern.
- **Depends on**: Module 4

### Module 7: Analyst Integration
- **Path**: `parrot/finance/agents/analysts.py` (modify existing)
- **Responsibility**: Add query tools to each analyst. Update prompts for pull model.
- **Depends on**: Module 4

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_research_document_validation` | Module 1 | Validates required fields, period_key format |
| `test_schedule_config_defaults` | Module 1 | Default schedules load correctly |
| `test_file_memory_store_and_get` | Module 3 | Store document, retrieve by crew+period |
| `test_file_memory_exists_check` | Module 3 | Returns True for existing, False for missing |
| `test_file_memory_get_latest` | Module 3 | Returns most recent document for domain |
| `test_file_memory_get_history` | Module 3 | Returns N most recent documents ordered |
| `test_file_memory_query_filters` | Module 3 | Query with domain, since, until filters |
| `test_file_memory_cache_hit` | Module 3 | Second read comes from cache (no file I/O) |
| `test_file_memory_fire_and_forget` | Module 3 | Store returns immediately, file written async |
| `test_audit_trail_logging` | Module 3 | Events appended to JSONL file |
| `test_cleanup_archives_old` | Module 3 | Documents >7 days moved to _historical |
| `test_cache_warmup_on_init` | Module 3 | Existing files loaded into cache at startup |
| `test_tool_check_exists_true` | Module 4 | Returns exists=True when document present |
| `test_tool_check_exists_false` | Module 4 | Returns exists=False when missing |
| `test_tool_store_research` | Module 4 | Stores and returns document_id |
| `test_tool_get_latest_research` | Module 4 | Returns latest document for domain |
| `test_tool_cross_domain` | Module 4 | Returns documents from multiple domains |

### Integration Tests
| Test | Description |
|---|---|
| `test_research_crew_deduplication` | Crew skips when research exists for period |
| `test_analyst_pull_model` | Analyst retrieves research via tools |
| `test_cross_pollination_flow` | Analyst accesses research from different domain |
| `test_full_research_to_deliberation` | Research stored → analyst pulls → deliberation runs |
| `test_cleanup_on_startup` | Service startup triggers cleanup before warmup |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_research_document() -> ResearchDocument:
    """Sample research document for testing."""
    return ResearchDocument(
        id="test-123",
        crew_id="research_crew_macro",
        domain="macro",
        period_key="2026-03-03",
        briefing=ResearchBriefing(
            id="briefing-123",
            analyst_id="macro_analyst",
            domain="macro",
            generated_at=datetime.now(timezone.utc),
            research_items=[],
            portfolio_snapshot={},
        ),
        metadata={"sources": ["FRED"]},
    )


@pytest.fixture
def temp_research_memory(tmp_path) -> FileResearchMemory:
    """Temporary file research memory for testing."""
    return FileResearchMemory(
        base_path=str(tmp_path / "research_memory"),
        warmup_on_init=False,
    )


@pytest.fixture
def populated_research_memory(temp_research_memory, sample_research_document):
    """Memory pre-populated with sample documents."""
    # Add documents for multiple domains and periods
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

### Core Memory Store
- [ ] `FileResearchMemory` stores documents in filesystem with structure `{domain}/{crew_id}/{period_key}.json`
- [ ] In-memory cache provides O(1) lookups for cached documents
- [ ] `store()` returns immediately; file write happens asynchronously (fire-and-forget)
- [ ] `exists()` checks cache first, then filesystem
- [ ] `get_latest()` returns most recent document for a domain
- [ ] `get_history()` returns N most recent documents ordered by date

### Deduplication
- [ ] `check_research_exists` tool correctly identifies existing research for a period
- [ ] Research crews use tool at start of execution and skip if exists
- [ ] Skip message logged: "Research already completed for {crew_id} period {period_key}"

### Pull Model for Analysts
- [ ] `get_latest_research` tool retrieves from collective memory
- [ ] `get_research_history` tool retrieves multiple periods for comparison
- [ ] `get_cross_domain_research` tool retrieves from multiple domains
- [ ] Analysts no longer "receive" briefings; they actively pull

### Audit Trail
- [ ] All store/access events logged to `_audit_log/research_events.jsonl`
- [ ] Events include: event_type, timestamp, crew_id, period_key, domain, actor
- [ ] `get_audit_events()` queries log with filters

### Lifecycle Management
- [ ] Cleanup runs at startup BEFORE cache warmup
- [ ] Documents older than 7 days moved to `_historical/{year-month}/` (not deleted)
- [ ] Cache warms from current documents after cleanup

### Scheduling
- [ ] Schedules configurable per crew via `ResearchScheduleConfig`
- [ ] Period key format is ISO 8601: `2026-03-03` (daily) or `2026-03-03T14:00:00` (hourly)
- [ ] Default schedules match crew data volatility (macro=daily, crypto=4h)

### Tests
- [ ] All unit tests pass: `pytest tests/test_research_memory.py -v`
- [ ] All integration tests pass: `pytest tests/test_research_memory_integration.py -v`
- [ ] No Redis dependency in test suite

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

1. **ABC Pattern** (from `ConversationMemory`):
   ```python
   class ResearchMemory(ABC):
       @abstractmethod
       async def store(self, document: ResearchDocument) -> str: ...

   class FileResearchMemory(ResearchMemory):
       async def store(self, document: ResearchDocument) -> str:
           # Implementation
   ```

2. **Fire-and-Forget** (from `parrot/memory/cache.py`):
   ```python
   async def store(self, document: ResearchDocument) -> str:
       # Update cache immediately
       self._cache[crew_id][period_key] = document
       # Fire-and-forget disk write
       asyncio.create_task(self._persist_to_disk(document))
       # Log audit event
       asyncio.create_task(self._log_audit_event("stored", document))
       return document.id
   ```

3. **Path Generation** (from `FileConversationMemory`):
   ```python
   def _get_file_path(self, domain: str, crew_id: str, period_key: str) -> Path:
       return self.base_path / domain / crew_id / f"{period_key}.json"
   ```

4. **Async Lock per Path**:
   ```python
   self._locks: dict[str, asyncio.Lock] = {}

   async def _persist_to_disk(self, document: ResearchDocument) -> None:
       path = self._get_file_path(...)
       lock = self._locks.setdefault(str(path), asyncio.Lock())
       async with lock:
           async with aiofiles.open(path, 'w') as f:
               await f.write(document.model_dump_json(indent=2))
   ```

### Period Key Generation

```python
def generate_period_key(granularity: str) -> str:
    """Generate period key based on granularity."""
    now = datetime.now(timezone.utc)

    if granularity == "daily":
        return now.strftime("%Y-%m-%d")
    elif granularity == "4h":
        hour = (now.hour // 4) * 4
        return now.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()
    elif granularity == "6h":
        hour = (now.hour // 6) * 6
        return now.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()
    elif granularity == "hourly":
        return now.replace(minute=0, second=0, microsecond=0).isoformat()
    else:
        raise ValueError(f"Unknown granularity: {granularity}")
```

### Known Risks / Gotchas

1. **Race condition on cache write** — Mitigate with asyncio.Lock per document path
2. **Disk full** — Fire-and-forget will silently fail; add monitoring/logging
3. **Large audit log** — Rotate `research_events.jsonl` monthly or by size
4. **Slow cache warmup** — For many documents, warmup may delay startup; make configurable

### Future Considerations

- **PageIndex integration** (`parrot/pageindex/`) for semantic search over research history
- **Redis backend** can be added later via new `RedisResearchMemory` class
- **Vector embeddings** of research for similarity search

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiofiles` | `>=23.0` | Already in project |
| `pydantic` | `>=2.0` | Already in project |

---

## 7. Open Questions

> Questions resolved during brainstorm review:

- [x] **Period key format** — Use ISO format. *Resolution: `2026-03-03` for daily, `2026-03-03T14:00:00` for hourly*

- [x] **Cache warming at startup** — Load at startup. *Resolution: Yes, warm cache after cleanup completes*

- [x] **Index file** — Use `_index.json` for quick metadata lookups. *Resolution: Implement, consider PageIndex for future*

- [x] **Retention policy** — Auto-cleanup after 7 days. *Resolution: Move to `_historical/` folder, not delete*

- [x] **Migration path** — Clean slate. *Resolution: No migration from Redis, start fresh*

### Remaining Questions

- [ ] **Audit log rotation** — Should audit log rotate by size (e.g., 10MB) or by time (monthly)? *Owner: Ops*: by size.

- [ ] **Cache eviction policy** — When cache exceeds `cache_max_size`, which documents to evict? LRU by access time? *Owner: Implementation*: LRU is ok

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-03 | Claude | Initial draft from brainstorm |
