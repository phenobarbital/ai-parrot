---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Crew Per-Agent Result Persistence & Deterministic Execution Document

**Feature ID**: FEAT-306
**Date**: 2026-07-14
**Author**: Jesus Lara
**Status**: approved
**Target version**: ai-parrot 0.26.0 (next minor)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Today `AgentCrew` persists only the crew-level `FlowResult` via `PersistenceMixin._save_result()`
into the pluggable `ResultStorage` backend (DocumentDB default, Redis, Postgres), collection
`crew_executions`. Per-agent execution results (`NodeResult`) live **only in memory** inside
`ExecutionMemory.results` (a plain dict) and are lost when the process ends. Additionally,
`FlowResult.to_dict()` stringifies per-agent responses (`serialised_responses`), losing structure.

Consequences:

1. There is no durable, queryable record of what each individual agent produced.
2. It is impossible to reconstruct — after the run, or from another process — a **complete,
   consistent execution document** containing every agent's result + the final crew output +
   the synthesis summary.
3. Any "full report" of a crew execution today requires re-running or an LLM call to
   re-synthesize; there is no deterministic, LLM-free assembly path.

### Goals

- **G1** — Persist each agent's `NodeResult` to the configured `ResultStorage` backend,
  **incrementally** (as each agent finishes, fire-and-forget), in a dedicated collection
  `crew_agent_results`, linked to the crew run by a new **crew-level `execution_id`**.
- **G2** — Persist a **consolidated execution document** in `crew_executions` that embeds the
  full list of per-agent results + the final output + the summary (superset of today's shape).
- **G3** — Extend `ResultStorage` with a **read API** (`fetch` by `execution_id`) implemented in
  all three backends (DocumentDB, Redis, Postgres), enabling reconstruction of the full
  document from storage at any later time, even from another process.
- **G4** — Provide a **deterministic, LLM-free** `CrewExecutionDocument` object with `to_dict()`
  (JSON-serialisable) and `to_markdown()` (template-based rendering) that assembles: all agent
  results (in execution order) + final result + summary.
- **G5** — Zero behaviour change for callers that don't opt out: persistence remains
  fire-and-forget, failures only log warnings, and the run's return value is unchanged
  (`FlowResult`).

### Non-Goals (explicitly out of scope)

- Wiring `AgentsFlow` (`flows/flow/flow.py`) to the new per-agent persistence — the mixin API
  is designed to be reusable by it, but the wiring is a follow-up feature.
- Changing how the LLM synthesis summary is *generated* (`SynthesisMixin` untouched) — this
  feature only *assembles* the already-generated summary deterministically.
- Persisting per-agent results for the single-shot `AgentCrew.run()` / `ask()` save sites
  (crew.py:3282 / :2772) — those persist a single synthesis response, not a multi-agent run.
- Migration of pre-existing stored documents — old `crew_executions` records simply lack
  `execution_id` and are not fetchable via the new read API.
- TTL/retention policy changes beyond reusing the existing Redis TTL setting.

---

## 2. Architectural Design

### Overview

A crew-level `execution_id` (uuid4) is generated at the start of each of the four run modes
(`run_sequential`, `run_parallel`, `run_flow`, `run_loop`) and stamped into
`FlowResult.metadata["execution_id"]`.

Persistence happens on two planes, both gated by the existing `self._persist_results` flag
(plus a new granular `persist_agent_results` flag):

1. **Incremental per-agent writes** — every time a `NodeResult` is added to `ExecutionMemory`
   inside a run mode, a background task also calls the new
   `PersistenceMixin._save_agent_result(node_result, execution_id=..., method=...)`, which
   writes one document per agent to collection `crew_agent_results`. Same fire-and-forget +
   `self._persist_tasks` tracking pattern as `_save_result` (so `aclose()` drains them).
2. **Consolidated final write** — at the end of the run, instead of persisting the bare
   `FlowResult`, the crew builds a `CrewExecutionDocument` (from `ExecutionMemory` + the
   `FlowResult` + summary) and persists **its** `to_dict()` to `crew_executions`. The document
   dict is a **superset** of today's `FlowResult.to_dict()` shape (adds `execution_id`,
   `agent_results` with full structured `NodeResult` dicts, `execution_order`).

Reconstruction is possible via two deterministic paths (no LLM involved):

- **In-process**: `AgentCrew.build_execution_document()` — assembles from
  `self.execution_memory` + `self.last_crew_result`.
- **From storage**: `CrewExecutionDocument.from_storage(storage, execution_id)` — uses the new
  `ResultStorage.fetch()` to read the crew doc + the N agent docs and joins them by
  `execution_id`, ordering agents by `ExecutionMemory.execution_order` (persisted in the
  consolidated doc) falling back to per-agent timestamps.

`CrewExecutionDocument.to_markdown()` renders a complete report — header (crew, method,
timing, status), one section per agent (name, task, result, execution time), the final
result, and the summary — using pure string templating.

### Component Diagram

```
AgentCrew.run_*()
   │  (generates execution_id = uuid4)
   ├─ per agent finished ──→ ExecutionMemory.add_result(NodeResult)          [in-memory, unchanged]
   │                     └─→ PersistenceMixin._save_agent_result(...)  ──→ ResultStorage.save("crew_agent_results", doc)
   │
   └─ run end ──→ CrewExecutionDocument.from_memory(...)
                       └─→ PersistenceMixin._save_result(doc, ...)     ──→ ResultStorage.save("crew_executions", doc)

Later / other process:
   CrewExecutionDocument.from_storage(storage, execution_id)
       └─→ ResultStorage.fetch("crew_executions", execution_id)     → 1 doc
       └─→ ResultStorage.fetch("crew_agent_results", execution_id)  → N docs
       └─→ .to_dict() / .to_markdown()   (deterministic, LLM-free)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AgentCrew` (crew/crew.py) | modifies | New `persist_agent_results` param; execution_id generation; per-agent persist wiring in 4 run modes; consolidated final persist; `build_execution_document()` accessor |
| `PersistenceMixin` (core/storage/persistence.py) | extends | New `_save_agent_result()` method; `_save_result()` unchanged in signature (extra fields via existing `**kwargs`) |
| `ResultStorage` ABC (backends/base.py) | extends | New `fetch()` method with default `NotImplementedError` body (non-abstract, keeps 3rd-party subclasses working) |
| `DocumentDbResultStorage` | extends | `fetch()` = query by `execution_id` field |
| `RedisResultStorage` | extends | New key scheme for new writes: `{collection}:{execution_id}:{suffix}`; `fetch()` via SCAN pattern |
| `PostgresResultStorage` | extends | DDL adds `execution_id text` column + index (`ADD COLUMN IF NOT EXISTS` for existing tables); `fetch()` = SELECT by execution_id |
| `NodeResult` (core/result.py) | extends | New `to_dict()` method with safe result-value serialisation |
| `ExecutionMemory` (core/storage/memory.py) | uses | Read-only source for document assembly (no changes needed) |
| `SynthesisMixin` | uses | `result.summary` consumed as-is; no changes |

### Data Models

```python
# parrot/bots/flows/core/storage/document.py  (NEW — dataclass, following the
# established dataclass pattern of result.py; NOT Pydantic, for consistency)

@dataclass
class CrewExecutionDocument:
    """Deterministic, LLM-free consolidated record of one crew execution."""
    execution_id: str
    crew_name: str
    method: str                              # "run_sequential" | "run_parallel" | ...
    status: str                              # FlowStatus value string
    output: Any                              # final crew output (JSON-safe or str())
    summary: str                             # LLM summary already generated (may be "")
    agent_results: List[Dict[str, Any]]      # NodeResult.to_dict() per agent, in execution order
    execution_order: List[str]               # node_ids in the order they ran
    errors: Dict[str, str]
    total_time: float
    timestamp: float                         # epoch seconds of the final write
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]: ...          # JSON-serialisable superset of FlowResult.to_dict()
    def to_markdown(self) -> str: ...                 # pure-template rendering, no LLM

    @classmethod
    def from_memory(
        cls, *, execution_id: str, crew_name: str, method: str,
        memory: "ExecutionMemory", result: "FlowResult",
        user_id: Optional[str] = None, session_id: Optional[str] = None,
    ) -> "CrewExecutionDocument": ...

    @classmethod
    async def from_storage(
        cls, storage: "ResultStorage", execution_id: str, *,
        crew_collection: str = "crew_executions",
        agent_collection: str = "crew_agent_results",
    ) -> Optional["CrewExecutionDocument"]: ...
```

Per-agent stored document shape (collection `crew_agent_results`):

```python
{
    "execution_id": "<crew-run uuid4>",        # join key to crew_executions
    "crew_name": "<crew name>",
    "method": "run_sequential",
    "node_id": "<agent id>",
    "node_execution_id": "<NodeResult.execution_id>",
    "timestamp": <epoch float>,
    "user_id": "...", "session_id": "...",
    "result": { ...NodeResult.to_dict()... },
}
```

### New Public Interfaces

```python
# backends/base.py — ResultStorage gains (default impl raises NotImplementedError):
async def fetch(self, collection: str, execution_id: str) -> list[dict[str, Any]]:
    """Return all persisted documents in *collection* whose execution_id matches."""

# core/storage/persistence.py — PersistenceMixin gains:
async def _save_agent_result(
    self, node_result: Any, *, execution_id: str, method: str,
    collection: str = "crew_agent_results", **kwargs: Any,
) -> None: ...

# core/result.py — NodeResult gains:
def to_dict(self) -> Dict[str, Any]: ...   # safe serialisation (see §7 for result-value rules)

# crew/crew.py — AgentCrew gains:
def build_execution_document(self) -> Optional[CrewExecutionDocument]:
    """Assemble the document for the LAST run from in-process state (LLM-free)."""

# AgentCrew.__init__ gains:
persist_agent_results: bool = True   # granular opt-out; also gated by persist_results
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

### Module 1: NodeResult serialisation
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/core/result.py`
- **Responsibility**: Add `NodeResult.to_dict()` with a `_serialise_result_value()` helper:
  primitives/list/dict pass through (JSON-checked), DataFrame → `str()` of a bounded preview,
  anything else → `str()`. Include `node_id`, `node_name`, `agent_id`/`agent_name` aliases,
  `task`, `result`, `metadata`, `execution_time`, `timestamp` (isoformat),
  `parent_execution_id`, `execution_id`.
- **Depends on**: nothing (pure addition)

### Module 2: ResultStorage read API (fetch by execution_id)
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/{base,documentdb,redis,postgres}.py`
- **Responsibility**:
  - `base.py`: add non-abstract `fetch()` raising `NotImplementedError` (backward compatible).
  - `documentdb.py`: `fetch()` queries by `execution_id` field.
  - `redis.py`: new writes use key `{collection}:{execution_id}:{suffix}` when the document
    carries an `execution_id` (suffix = `node_execution_id` for agent docs, `"crew"` for the
    consolidated doc); documents without `execution_id` keep the legacy
    `{collection}:{crew_name}:{ts_ms}` key. `fetch()` uses cursor-based `SCAN` with pattern
    `{collection}:{execution_id}:*` (never `KEYS`).
  - `postgres.py`: DDL gains `execution_id text` column + index; `_ensure_table` also issues
    `ALTER TABLE ... ADD COLUMN IF NOT EXISTS execution_id text` for pre-existing tables;
    `save()` extracts `execution_id` into the named column; `fetch()` = `SELECT` by it.
- **Depends on**: nothing (parallel-safe with Module 1)

### Module 3: PersistenceMixin._save_agent_result
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/core/storage/persistence.py`
- **Responsibility**: New method mirroring `_save_result` semantics (opt-out check on BOTH
  `_persist_results` and `_persist_agent_results` via `getattr` with default `True`, lazy
  backend resolution, warning-only failure). Builds the per-agent document shape from §2.
- **Depends on**: Module 1 (uses `NodeResult.to_dict()`)

### Module 4: CrewExecutionDocument
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/core/storage/document.py` (NEW file)
- **Responsibility**: Dataclass from §2 with `to_dict()`, `to_markdown()`, `from_memory()`,
  `from_storage()`. Re-export from `core/storage/__init__.py`. `to_markdown()` sections:
  title + metadata table, per-agent sections in `execution_order`, final result, summary,
  errors (if any). Deterministic: same inputs → same output string.
- **Depends on**: Modules 1, 2

### Module 5: AgentCrew wiring
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
- **Responsibility**:
  - `__init__`: accept `persist_agent_results: bool = True` → `self._persist_agent_results`.
  - Each of the 4 run modes generates `execution_id = str(uuid.uuid4())` at start and stamps
    `result.metadata["execution_id"]`.
  - At every `execution_memory.add_result(...)` site inside the 4 run modes, schedule a
    tracked background task calling `_save_agent_result(...)` (same
    `self._persist_tasks.add` + `add_done_callback(discard)` pattern as the final save).
  - Final persist: build `CrewExecutionDocument.from_memory(...)` and pass it to the existing
    `_save_result(document, method, execution_id=..., user_id=..., session_id=...)` call
    (the document exposes `to_dict()`, so `_save_result` needs no signature change).
  - Add `build_execution_document()` public accessor.
- **Depends on**: Modules 1, 3, 4

### Module 6: Tests & documentation
- **Path**: `packages/ai-parrot/tests/` + `docs/`
- **Responsibility**: Unit + integration tests per §4; update crew persistence docs.
- **Depends on**: Modules 1–5

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_node_result_to_dict_primitives` | Module 1 | dict/list/str/int results pass through JSON-safe |
| `test_node_result_to_dict_dataframe` | Module 1 | DataFrame result serialised to bounded string, no raise |
| `test_node_result_to_dict_arbitrary_object` | Module 1 | non-serialisable object falls back to `str()` |
| `test_result_storage_fetch_default_raises` | Module 2 | base `fetch()` raises `NotImplementedError` |
| `test_redis_key_scheme_with_execution_id` | Module 2 | new key `{col}:{exec_id}:{suffix}`; legacy key when absent |
| `test_redis_fetch_scan_pattern` | Module 2 | fetch returns all docs for an execution_id (mocked conn) |
| `test_postgres_ddl_has_execution_id` | Module 2 | DDL + ALTER include execution_id column and index |
| `test_documentdb_fetch_filters_by_execution_id` | Module 2 | query built with `{"execution_id": ...}` (mocked) |
| `test_save_agent_result_respects_opt_out` | Module 3 | no write when `persist_results=False` OR `persist_agent_results=False` |
| `test_save_agent_result_document_shape` | Module 3 | persisted doc matches §2 per-agent shape |
| `test_save_agent_result_failure_warns_only` | Module 3 | backend exception → warning log, no raise |
| `test_document_from_memory_ordering` | Module 4 | agents appear in `execution_order` order |
| `test_document_to_markdown_deterministic` | Module 4 | two calls on same doc → identical string; no LLM client touched |
| `test_document_to_dict_superset_of_flowresult` | Module 4 | contains every key of `FlowResult.to_dict()` plus new ones |
| `test_document_from_storage_joins_by_execution_id` | Module 4 | crew doc + N agent docs (mock storage) → complete document |
| `test_crew_run_stamps_execution_id` | Module 5 | `result.metadata["execution_id"]` set on all 4 run modes |
| `test_crew_incremental_agent_persist` | Module 5 | mock storage receives one `crew_agent_results` save per agent |
| `test_build_execution_document_after_run` | Module 5 | in-process accessor returns complete document |

### Integration Tests
| Test | Description |
|---|---|
| `test_end_to_end_persist_and_reconstruct` | Run a 2-agent sequential crew with a fake `ResultStorage` instance → fetch by execution_id → `from_storage()` document equals `from_memory()` document (field-by-field) |
| `test_aclose_drains_agent_persist_tasks` | In-flight per-agent saves are awaited by `aclose()` |
| `test_backward_compat_flowresult_unchanged` | Run modes still return `FlowResult`; existing consumers of `result.output`/`result.summary` unaffected |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_storage():
    """In-memory ResultStorage capturing save() calls and answering fetch()."""
    class FakeStorage(ResultStorage):
        def __init__(self): self.docs = defaultdict(list)
        async def save(self, collection, document): self.docs[collection].append(document)
        async def fetch(self, collection, execution_id):
            return [d for d in self.docs[collection] if d.get("execution_id") == execution_id]
        async def close(self): pass
    return FakeStorage()

@pytest.fixture
def echo_agents():
    """Two stub agents whose ask() returns deterministic strings (no LLM)."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] Each agent's `NodeResult` is persisted to collection `crew_agent_results` incrementally
      (as the agent finishes), linked by crew-level `execution_id` (G1).
- [ ] The consolidated document (all agent results + final output + summary) is persisted to
      `crew_executions` and its dict is a superset of the previous `FlowResult.to_dict()`
      shape (G2).
- [ ] `ResultStorage.fetch(collection, execution_id)` is implemented in DocumentDB, Redis, and
      Postgres backends; base class provides a non-abstract `NotImplementedError` default (G3).
- [ ] `CrewExecutionDocument.to_markdown()` and `to_dict()` are deterministic and make zero
      LLM calls; `from_memory()` and `from_storage()` produce equal documents for the same
      run (G4).
- [ ] `persist_results=False` disables ALL persistence; `persist_agent_results=False` disables
      only the per-agent writes; defaults preserve current behaviour plus the new writes (G5).
- [ ] Persistence failures never propagate to the caller — warning logs only (G5).
- [ ] `aclose()` awaits in-flight per-agent persist tasks (existing `_persist_tasks` contract).
- [ ] All 4 run modes (`run_sequential`, `run_parallel`, `run_flow`, `run_loop`) are wired.
- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/ -v` for the new test modules).
- [ ] Integration tests pass with the fake-storage fixture (no external DB required in CI).
- [ ] No breaking changes to existing public API (`FlowResult` return type, `_save_result`
      signature, `ResultStorage` subclasses without `fetch`).
- [ ] Documentation updated (crew persistence section).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All paths relative to `packages/ai-parrot/src/` unless noted.

### Verified Imports
```python
from parrot.bots.flows.core.storage.backends import (        # backends/__init__.py exports all 5
    ResultStorage, get_result_storage,
    DocumentDbResultStorage, RedisResultStorage, PostgresResultStorage,
)
from parrot.bots.flows.core.storage import (                 # storage/__init__.py exports all 5
    ExecutionMemory, VectorStoreMixin, PersistenceMixin, SynthesisMixin, synthesize_results,
)
from parrot.bots.flows.core.result import NodeResult, FlowResult, NodeExecutionInfo  # result.py:39,273,190
from parrot.conf import CREW_RESULT_STORAGE                  # conf.py:309
```

### Existing Class Signatures
```python
# parrot/bots/flows/core/storage/backends/base.py
class ResultStorage(ABC):                                        # line 8
    async def save(self, collection: str, document: dict[str, Any]) -> None  # line 18 (abstract)
    async def close(self) -> None                                # line 27 (abstract)
    # NO other methods — fetch() does NOT exist yet.

# parrot/bots/flows/core/storage/backends/factory.py
_REGISTRY: dict[str, str]                                        # line 12 — "redis"/"postgres"/"documentdb"
def get_result_storage(name_or_instance=None) -> ResultStorage   # line 34

# parrot/bots/flows/core/storage/backends/redis.py
class RedisResultStorage(ResultStorage):                         # line 21
    # key = f"{collection}:{crew_name}:{ts_ms}"                  # line 67 — legacy scheme to preserve
    async def save(self, collection, document) -> None           # line 53; json.dumps(document, default=str)
    # TTL: self._ttl from CREW_RESULT_STORAGE_REDIS_TTL (conf.py:312, default 604800)
    # conn: AsyncDB("redis", dsn=...) — asyncdb wrapper; raw commands via conn.execute("SET", ...)

# parrot/bots/flows/core/storage/backends/postgres.py
class PostgresResultStorage(ResultStorage):                      # line 23
    async def _ensure_table(self, conn, table) -> None           # line 54 — idempotent DDL
    # columns: id uuid PK, crew_name, method, user_id, session_id, timestamp, payload jsonb
    # NO execution_id column yet. _NAMED_COLUMNS set controls payload extraction (save():85)

# parrot/bots/flows/core/storage/persistence.py
class PersistenceMixin:                                          # line 29
    def _ensure_result_storage(self) -> ResultStorage            # line 45
    async def _save_result(self, result, method, *, collection="crew_executions", **kwargs) -> None  # line 65
        # uses result.to_dict() if available else str(result)    # line 96-98
        # extra **kwargs merged into document (user_id, session_id — and execution_id will pass through)
    async def aclose(self) -> None                               # line 110 — drains self._persist_tasks

# parrot/bots/flows/core/storage/memory.py
@dataclass
class ExecutionMemory(VectorStoreMixin):                         # line 19
    original_query: Optional[str]
    results: Dict[str, NodeResult]                               # line 33
    execution_graph: Dict[str, List[str]]
    execution_order: List[str]                                   # line 35 — populated by run modes
    def add_result(self, result: NodeResult, vectorize=True)     # line 55
    def get_results_by_agent(self, agent_id) -> Optional[NodeResult]  # line 79
    def get_snapshot(self) -> Dict[str, Any]                     # line 134 — stringifies results (NOT the shape we want)

# parrot/bots/flows/core/result.py
@dataclass
class NodeResult:                                                # line 39
    node_id: str; node_name: str; task: str; result: Any
    ai_message: Optional[Any]; metadata: Dict[str, Any]
    execution_time: float; timestamp: datetime                   # tz-aware UTC
    parent_execution_id: Optional[str]
    execution_id: str                                            # line 72 — uuid4 PER NODE (≠ crew execution_id)
    def to_text(self) -> str                                     # line 88 — for FAISS, NOT serialisation

@dataclass
class NodeExecutionInfo:                                         # line 190
    def to_dict(self) -> Dict[str, Any]                          # line 244

@dataclass
class FlowResult:                                                # line 273
    output: Any; responses: Dict[str, Any]; summary: str
    nodes: List[NodeExecutionInfo]; execution_log: List[Dict]
    total_time: float; status: FlowStatus; errors: Dict[str, str]
    metadata: Dict[str, Any]                                     # line 312 — stamp execution_id HERE
    def to_dict(self) -> Dict[str, Any]                          # line 454 — responses stringified (line 465-472)

# parrot/bots/flows/crew/crew.py
class AgentCrew(PersistenceMixin, SynthesisMixin):               # line 93
    def __init__(..., persist_results: bool = True,
                 result_storage: Union[str, ResultStorage, None] = None, **kwargs)  # line 132
    # persistence attrs initialised at lines ~218-223:
    #   self._persist_results, self._result_storage_arg, self._result_storage, self._persist_tasks
    self.execution_memory = ExecutionMemory(...)                 # line 194 — RE-CREATED at start of each run mode
    self.last_crew_result: Optional[FlowResult]                  # line 211
    # _save_result call sites (all use the create_task + _persist_tasks pattern):
    #   run_sequential → line 1488 | run_loop → 1954 | run_parallel → 2277 | run_flow → 2514
    #   run → 2772, ask → 3282  (OUT OF SCOPE — single-shot, no multi-agent memory)
    # execution_memory.add_result sites (verified): 1376, 1438 (sequential); 1687, 1808, 1868 (loop);
    #   809, 867 (flow-node helper via context.shared_data['execution_memory']).
    #   Agents MUST `grep -n "add_result" crew/crew.py` for the complete current list before wiring.
    # session_id defaults to str(uuid.uuid4()) per run (lines 1234, 1573) — it is NOT an execution id.

# parrot/bots/flows/core/storage/synthesis.py
class SynthesisMixin:                                            # line 40
    async def _synthesize_results(self, crew_result, synthesis_prompt=None, *, llm=None, ...) -> Optional[str]  # line 49

# parrot/conf.py
CREW_RESULT_STORAGE = config.get('CREW_RESULT_STORAGE', fallback='documentdb')       # line 309
CREW_RESULT_STORAGE_PG_DSN                                                            # line 310
CREW_RESULT_STORAGE_REDIS_URL                                                         # line 311
CREW_RESULT_STORAGE_REDIS_TTL (int, default 604800)                                   # line 312
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_save_agent_result()` | `PersistenceMixin._ensure_result_storage()` | method call | `persistence.py:45` |
| `_save_agent_result()` | `NodeResult.to_dict()` (Module 1) | method call | new — result.py |
| Crew wiring | `self._persist_tasks` add/discard pattern | copy of existing pattern | `crew.py:1487-1496` |
| `CrewExecutionDocument.from_memory` | `ExecutionMemory.results` + `.execution_order` | attribute read | `memory.py:33,35` |
| `CrewExecutionDocument.from_storage` | `ResultStorage.fetch()` (Module 2) | async call | new — base.py |
| Consolidated persist | `_save_result(document, method, **kwargs)` | existing signature — document has `to_dict()` | `persistence.py:96-98` |
| execution_id stamp | `FlowResult.metadata` | dict assignment | `result.py:312` |

### Does NOT Exist (Anti-Hallucination)
- ~~`NodeResult.to_dict()`~~ — does NOT exist yet (only `to_text()`); Module 1 creates it.
- ~~`ResultStorage.fetch()`~~ / ~~`.get()`~~ / ~~`.query()`~~ — no read API exists; Module 2 creates `fetch()`.
- ~~crew-level `execution_id`~~ — no such attribute/variable exists in `AgentCrew`; only per-node `NodeResult.execution_id` and loop-iteration string ids like `f"{agent_id}#iteration{n}"` (crew.py:1641). Module 5 introduces it.
- ~~`crew_agent_results` collection~~ — never written today; only `"crew_executions"`.
- ~~`execution_id` column in Postgres DDL~~ — table has no such column (postgres.py:66-77).
- ~~`CrewExecutionDocument`~~ / ~~`core/storage/document.py`~~ — do not exist; Module 4 creates them.
- ~~`persist_agent_results` param~~ / ~~`self._persist_agent_results`~~ — do not exist; Module 5 adds.
- ~~`FlowResult.to_dict()` structured responses~~ — responses are STRINGIFIED (result.py:465-472); do not rely on them for structured per-agent data — that is exactly what `crew_agent_results` fixes.
- ~~`ExecutionMemory.to_dict()`~~ — does not exist; `get_snapshot()` exists but stringifies results.
- ~~`AgentsFlow` per-agent persistence~~ — out of scope; do not modify `flows/flow/flow.py`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Fire-and-forget + tracked tasks**: copy the exact pattern at `crew.py:1487-1496`
  (`create_task` → `self._persist_tasks.add` → `add_done_callback(discard)`), so `aclose()`
  (persistence.py:110) drains per-agent writes too.
- **Warning-only failure**: every persistence path wraps in `try/except Exception` and logs
  `logger.warning` — never raise into the run (persistence.py:103-108, redis.py:73-78).
- **`getattr` with safe defaults** for mixin-host attributes (persistence.py module docstring)
  — `_save_agent_result` must read `_persist_agent_results` via
  `getattr(self, "_persist_agent_results", True)`.
- Dataclasses (not Pydantic) for the new document model — consistency with `result.py` /
  `memory.py`.
- Async-first throughout; `AsyncDB` for backend connections (never `requests`/`httpx`).
- Google-style docstrings + strict type hints on everything new.

### Known Risks / Gotchas
- **Redis SCAN cost**: `fetch()` must use cursor-based `SCAN` (never `KEYS`) with pattern
  `{collection}:{execution_id}:*`; document that fetch on Redis is O(keyspace scan).
- **Redis key-scheme coexistence**: legacy keys (`{collection}:{crew_name}:{ts_ms}`) remain
  valid and simply aren't fetchable; only NEW writes carrying `execution_id` use the new
  scheme. TTL applies identically to agent docs (they expire together with the crew doc).
- **Postgres schema migration**: `_ensure_table` runs `CREATE TABLE IF NOT EXISTS` — an
  existing table skips creation, so the new column requires an explicit
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS execution_id text` in the same idempotent block.
- **Non-serialisable results**: `NodeResult.result` can be a DataFrame or arbitrary object.
  `to_dict()` must never raise — fall back to `str()`; bound DataFrame previews (e.g. head(10))
  to avoid megabyte documents.
- **Ordering vs fire-and-forget**: per-agent writes may land AFTER the consolidated write or
  out of order. `from_storage()` must not assume arrival order — it re-orders via the
  consolidated doc's `execution_order`, falling back to agent-doc timestamps. Prefer the
  consolidated doc's embedded `agent_results` as primary; per-agent docs fill gaps (e.g.
  crash-interrupted runs that never wrote the consolidated doc).
- **`run_loop` id collisions**: loop mode uses synthetic ids `{agent_id}#iteration{n}`
  (crew.py:1641) — `ExecutionMemory.results` is keyed by these, so per-agent docs must use the
  same key as `node_id` to stay joinable.
- **Double write volume**: N+1 writes per run instead of 1. Redis/DocumentDB absorb this fine;
  fire-and-forget keeps latency off the critical path. `persist_agent_results=False` is the
  relief valve.
- **`_save_result` passes `**kwargs` into the document** (persistence.py:92-100) — pass
  `execution_id=...` there so the consolidated doc carries the join key without signature
  changes.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| (none new) | — | Everything builds on existing `asyncdb`, stdlib `uuid`/`json`/`dataclasses` |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Storage layout — *Resolved by user (2026-07-14)*: separate `crew_agent_results`
      collection (one doc per agent, linked by `execution_id`) PLUS a consolidated document
      in `crew_executions` embedding everything.
- [x] Write timing — *Resolved by user (2026-07-14)*: incremental — each `NodeResult`
      persists as soon as the agent finishes (fire-and-forget), crash-resilient.
- [x] Read API — *Resolved by user (2026-07-14)*: yes — extend `ResultStorage` with `fetch()`
      by `execution_id`, implemented in DocumentDB, Redis, and Postgres.
- [x] Document format — *Resolved by user (2026-07-14)*: structured dict/JSON via `to_dict()`
      PLUS deterministic template-based `to_markdown()` — no LLM in either path.
- [x] Should `AgentsFlow` (flows/flow/flow.py, also a `PersistenceMixin` host) adopt
      `_save_agent_result` in a follow-up feature? — *Owner: Jesus Lara*: yes
- [x] Should `crew_agent_results` get its own Redis TTL setting, or is sharing
      `CREW_RESULT_STORAGE_REDIS_TTL` acceptable long-term? — *Owner: Jesus Lara* (implementation
      defaults to sharing; decide during review): defaults to sharing
- [x] Expose `from_storage()` reconstruction via an HTTP handler in `ai-parrot-server`
      (e.g. alongside `handlers/crew/`)?: — *Owner: Jesus Lara*: Yes, Exposed

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all tasks run sequentially in ONE worktree.
- Rationale: Modules 3–5 all touch `core/storage/` and `crew/crew.py` with tight coupling
  (Module 5 wires Modules 1+3+4); parallel worktrees would conflict. Modules 1 and 2 are
  technically parallelizable but too small to justify separate worktrees.
- **Cross-feature dependencies**: none — no other in-flight spec touches
  `core/storage/backends/` or the crew persistence path.
- Worktree branch: `feat-306-crew-per-agent-result-persistence` from `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-14 | Jesus Lara | Initial draft |
