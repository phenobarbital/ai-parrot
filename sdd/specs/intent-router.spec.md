# Feature Specification: Intent Router & Capability Registry

**Feature ID**: FEAT-070
**Date**: 2026-03-30
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x
**Brainstorm**: `sdd/proposals/intent-router.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot agents that have a vector store assigned **always** attempt RAG on every query — even when the query is about structured data (a dataset), requires executing a tool, or should be delegated to the LLM directly. There is no mechanism to decide *who should answer* before retrieval begins.

Concrete failure case: an agent with a `DatasetManager` containing `warehouse_ops` and `active_employees` datasets. A query for "active employees by warehouse" causes the LLM to pick `warehouse_ops` because it has an `employee_id` field — lexical match wins over semantic intent. The system has no representation of what each resource is *designed to answer*, nor what it explicitly should *not* answer.

Additionally, two resolution paths are missing entirely:
1. **LLM Fallback**: When no tool, vector DB, dataset, page index, or graph can answer (e.g. "what is a Shed?"), there's no graceful fallback to the LLM's general knowledge with context about what was already tried.
2. **HITL Clarification**: When the system has low confidence across all strategies (e.g. "what's the price?" without specifying a product), there's no mechanism to return a clarifying question to the user within the same conversation.

### Goals
- Provide a `CapabilityRegistry` — a semantic registry of agent resources with embedding-based candidate search and `not_for` exclusions.
- Provide an `IntentRouterMixin` — a pre-RAG routing mixin that intercepts `conversation()`/`ask()` and routes to the best strategy using a lightweight `invoke()` call (FEAT-069).
- Support 7+ routing types: `GRAPH_PAGEINDEX`, `DATASET`, `VECTOR_SEARCH`, `TOOL_CALL`, `FREE_LLM`, `MULTI_HOP`, `FALLBACK`, `HITL`.
- Support cascade fallbacks: `RoutingDecision(primary, cascades=[...])`.
- Support exhaustive mode: try all strategies, concatenate all non-empty results, let LLM synthesize.
- Provide `RoutingTrace` for observability and LLM Fallback context.
- LLM Fallback uses agent's `ask()` (main model) with tried-and-failed summary.
- HITL returns a clarifying question as a normal response — no agent suspension.
- Demote `OntologyIntentResolver` from router to AQL query planner.
- Auto-detect available strategies from agent configuration.

### Non-Goals (explicitly out of scope)
- Plugin/registry pattern for adding new strategies dynamically (explicit list is acceptable for now).
- Persisting `CapabilityRegistry` to disk (v1 is in-memory only).
- Modifying existing `ask()` / `conversation()` behavior for agents that don't opt in.
- Replacing the Advisor — the Advisor is a specialized tool, not a fallback.
- Agent suspension / `HumanInteractionInterrupt` for HITL — clarification is a normal response.

---

## 2. Architectural Design

### Overview

Two-layer architecture: a **CapabilityRegistry** (semantic resource index) and an **IntentRouterMixin** (routing orchestrator). The registry knows about resources; the mixin knows about the bot pipeline.

The mixin intercepts `conversation()` before any RAG or tool dispatch occurs. It auto-detects available strategies from agent configuration, uses cosine similarity on registry entries for candidate retrieval, then delegates the final decision to `client.invoke()` (FEAT-069) → `RoutingDecision`. Strategies are executed with cascade fallbacks, and a `RoutingTrace` records all attempts.

### Component Diagram
```
IntentRouterMixin.conversation()
    │
    ├── Strategy Discovery (auto-detect from agent config)
    │
    ├── Fast Path: CapabilityRegistry keyword scan (~0ms)
    │       └── Direct route if trigger keyword matches
    │
    ├── LLM Path: client.invoke() → RoutingDecision (~100-300ms)
    │       ├── CapabilityRegistry.search(query) → top-K candidates
    │       └── invoke(query + candidates) → RoutingDecision(primary, cascades)
    │
    ├── Strategy Execution (primary, then cascades if needed)
    │       ├── GRAPH_PAGEINDEX → OntologyRAGMixin.ontology_process()
    │       │       └── OntologyIntentResolver (AQL planner only)
    │       ├── DATASET → DatasetManager query
    │       ├── VECTOR_SEARCH → existing RAG pipeline
    │       ├── TOOL_CALL → routing hint → LLM tool calling
    │       ├── FREE_LLM → no context injection, LLM with tools
    │       ├── MULTI_HOP → asyncio.gather(primary + secondary)
    │       ├── FALLBACK → ask() with RoutingTrace summary
    │       └── HITL → clarifying question as response
    │
    ├── RoutingTrace (records all attempts)
    │
    └── super().conversation(injected_context=...) → normal flow
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot.conversation()` | modifies | One `kwargs.pop()` + one conditional block for `injected_context` |
| `OntologyRAGMixin.ontology_process()` | uses | Called as GRAPH_PAGEINDEX strategy, unchanged |
| `OntologyIntentResolver` | modifies | Demoted: action field deprecated, vector_only fallback removed |
| `ResolvedIntent` (schema.py) | modifies | action field becomes optional/deprecated |
| `DatasetManager` | uses/extends | Queried as DATASET strategy; optional `routing_meta` field on DataSource |
| `ToolManager` | uses/extends | Tool count check for strategy discovery; optional `routing_meta` on tools |
| `PageIndexRetriever` | uses | Called as GRAPH_PAGEINDEX sub-strategy (lazy import) |
| `_build_vector_context()` | uses | Called as VECTOR_SEARCH strategy |
| FEAT-069 `invoke()` | depends on | Required for lightweight intent classification |

### Data Models

```python
# --- Enums ---
class ResourceType(str, Enum):
    DATASET = "dataset"
    TOOL = "tool"
    GRAPH_NODE = "graph_node"
    PAGEINDEX = "pageindex"
    VECTOR_COLLECTION = "vector_collection"

class RoutingType(str, Enum):
    GRAPH_PAGEINDEX = "graph_pageindex"
    DATASET = "dataset"
    VECTOR_SEARCH = "vector_search"
    TOOL_CALL = "tool_call"
    FREE_LLM = "free_llm"
    MULTI_HOP = "multi_hop"
    FALLBACK = "fallback"
    HITL = "hitl"

# --- Registry Models ---
class CapabilityEntry(BaseModel):
    id: str                                    # unique resource identifier
    resource_type: ResourceType
    description: str                           # what this resource answers
    not_for: list[str] = []                    # what it should NOT be used for
    canonical_questions: list[str] = []        # example questions it handles well
    fields_preview: list[str] = []             # column/field names for context
    source_ref: str | None = None              # DataSource name, tool name, etc.
    routing_meta: dict[str, Any] = {}          # arbitrary metadata

class RouterCandidate(BaseModel):
    entry: CapabilityEntry
    score: float                               # cosine similarity score

# --- Routing Decision ---
class RoutingDecision(BaseModel):
    routing_type: RoutingType                  # primary strategy
    cascades: list[RoutingType] = []           # fallback strategies if primary fails
    confidence: float                          # 0.0–1.0
    reasoning: str                             # LLM's explanation
    source_ref: str | None = None              # primary resource reference
    secondary_ref: str | None = None           # for MULTI_HOP

# --- Routing Trace ---
class RoutingTrace(BaseModel):
    entries: list[TraceEntry] = []
    mode: Literal["normal", "exhaustive"] = "normal"

class TraceEntry(BaseModel):
    strategy: RoutingType
    result_count: int                          # 0 = empty / no match
    confidence: float
    execution_time_ms: float
    error: str | None = None
    produced_context: bool                     # True if contributed to final context

# --- Configuration ---
class IntentRouterConfig(BaseModel):
    exhaustive: bool = False
    hitl_enabled: bool = False
    hitl_confidence_threshold: float = 0.3
    fallback_enabled: bool = True
    strategy_timeout_ms: float = 5000.0
    top_k_candidates: int = 5
    confidence_threshold: float = 0.4          # below this → FALLBACK or HITL
```

### New Public Interfaces

```python
# --- CapabilityRegistry ---
class CapabilityRegistry:
    def register(self, entry: CapabilityEntry) -> None: ...
    def register_from_datasource(self, source: DataSource, name: str) -> None: ...
    def register_from_tool(self, tool: AbstractTool) -> None: ...
    def register_from_yaml(self, path: str) -> None: ...
    async def build_index(self, embedding_fn: Callable) -> None: ...
    async def search(self, query: str, top_k: int = 5,
                     resource_types: list[ResourceType] | None = None
                     ) -> list[RouterCandidate]: ...

# --- IntentRouterMixin ---
class IntentRouterMixin:
    async def configure_router(self, registry: CapabilityRegistry,
                               client: AbstractClient,
                               config: IntentRouterConfig | None = None,
                               embedding_fn: Callable | None = None) -> None: ...
    async def conversation(self, question: str, **kwargs) -> AIMessage: ...
    # Internal:
    async def _route(self, query: str, user_context: dict) -> RoutingDecision: ...
    async def _execute_strategy(self, strategy: RoutingType, query: str,
                                decision: RoutingDecision) -> str: ...
    async def _build_fallback_prompt(self, query: str, trace: RoutingTrace) -> str: ...
    async def _build_hitl_question(self, query: str, trace: RoutingTrace) -> str: ...
```

---

## 3. Module Breakdown

### Module 1: Routing Models
- **Path**: `parrot/registry/capabilities/models.py`
- **Responsibility**: Define all enums (`ResourceType`, `RoutingType`) and Pydantic models (`CapabilityEntry`, `RouterCandidate`, `RoutingDecision`, `RoutingTrace`, `TraceEntry`, `IntentRouterConfig`).
- **Depends on**: None

### Module 2: CapabilityRegistry
- **Path**: `parrot/registry/capabilities/registry.py`
- **Responsibility**: Implement `CapabilityRegistry` — resource registration (manual, from DataSource, from Tool, from YAML), embedding-based index build, cosine similarity search, `not_for` exclusion support.
- **Depends on**: Module 1

### Module 3: IntentRouterMixin
- **Path**: `parrot/bots/mixins/intent_router.py`
- **Responsibility**: Implement the routing mixin — strategy discovery (auto-detect from agent config), fast path (keyword scan), LLM path (`invoke()` → `RoutingDecision`), strategy execution with cascade, `RoutingTrace` collection, LLM Fallback (build fallback prompt, call `ask()`), HITL (build clarifying question, return as response), exhaustive mode (try all, concatenate, synthesize).
- **Depends on**: Module 1, Module 2, FEAT-069 (`invoke()`)

### Module 4: AbstractBot Touch-Point
- **Path**: `parrot/bots/base.py`
- **Responsibility**: Add `injected_context` / `routing_decision` kwarg handling to `conversation()` — one `kwargs.pop()` + one conditional block. When `injected_context` is provided, use it instead of running RAG.
- **Depends on**: Module 3

### Module 5: Auto-Registration Hooks
- **Path**: `parrot/tools/dataset_manager/tool.py`, `parrot/tools/manager.py`, `parrot/tools/base.py` (or equivalent for DataSource/AbstractTool)
- **Responsibility**: Add optional `routing_meta: dict` field to `DataSource` and `AbstractTool`. Add optional `capability_registry` parameter to `DatasetManager.add_source()` and `ToolManager.register()` so resources are auto-registered when a registry is present.
- **Depends on**: Module 2

### Module 6: OntologyIntentResolver Demotion
- **Path**: `parrot/knowledge/ontology/intent.py`, `parrot/knowledge/ontology/schema.py`
- **Responsibility**: Demote `OntologyIntentResolver` from router to AQL query planner. Deprecate `action` field on `IntentDecision` and `ResolvedIntent`. Remove the `vector_only` fallback case — when called, the graph decision has already been made by IntentRouter. `_try_fast_path()` and `_try_llm_path()` remain for deciding WHICH pattern/AQL to execute.
- **Depends on**: Module 3 (router must exist before demoting resolver)

### Module 7: Unit Tests
- **Path**: `tests/registry/test_capability_models.py`, `tests/registry/test_capability_registry.py`, `tests/bots/test_intent_router.py`
- **Responsibility**: Unit tests for models, registry (registration, search, not_for exclusions, auto-registration), and mixin (routing, cascade, fallback, HITL, exhaustive mode, strategy discovery).
- **Depends on**: Modules 1-6

### Module 8: Integration Tests
- **Path**: `tests/bots/test_intent_router_e2e.py`
- **Responsibility**: End-to-end routing scenarios: query → routing → strategy execution → response. Covers HITL cycle (question → clarification → re-route), LLM Fallback with trace, exhaustive mode multi-source synthesis, cascade on primary failure, OntologyIntentResolver demotion (graph strategy flows through demoted resolver).
- **Depends on**: Modules 1-6

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_routing_type_enum` | Module 1 | All 8 routing types defined |
| `test_capability_entry_validation` | Module 1 | CapabilityEntry with not_for and canonical_questions |
| `test_routing_decision_with_cascades` | Module 1 | RoutingDecision primary + cascades list |
| `test_routing_trace_mode` | Module 1 | RoutingTrace with normal and exhaustive modes |
| `test_trace_entry_produced_context` | Module 1 | TraceEntry.produced_context flag |
| `test_intent_router_config_defaults` | Module 1 | Config defaults: exhaustive=False, hitl_enabled=False |
| `test_registry_register_manual` | Module 2 | Manual CapabilityEntry registration |
| `test_registry_register_from_datasource` | Module 2 | Auto-registration from DataSource |
| `test_registry_register_from_tool` | Module 2 | Auto-registration from AbstractTool |
| `test_registry_register_from_yaml` | Module 2 | YAML-based registration for graph nodes |
| `test_registry_build_index` | Module 2 | Embedding index built, search returns ranked candidates |
| `test_registry_search_top_k` | Module 2 | Top-K results with cosine similarity scores |
| `test_registry_not_for_exclusion` | Module 2 | `not_for` entries reduce score or exclude candidates |
| `test_strategy_discovery` | Module 3 | Auto-detect available strategies from agent config |
| `test_fast_path_keyword_match` | Module 3 | Keyword scan routes directly, skips LLM |
| `test_llm_path_invoke` | Module 3 | invoke() returns RoutingDecision with primary + cascades |
| `test_cascade_on_primary_failure` | Module 3 | Primary returns 0 results → cascade to next |
| `test_fallback_prompt_with_trace` | Module 3 | Fallback prompt includes RoutingTrace summary |
| `test_hitl_clarifying_question` | Module 3 | Low confidence → returns clarifying question |
| `test_hitl_disabled` | Module 3 | hitl_enabled=False → skip HITL, go to FALLBACK |
| `test_exhaustive_mode_all_strategies` | Module 3 | Exhaustive mode tries all, concatenates results |
| `test_exhaustive_mode_synthesis_labels` | Module 3 | Concatenated results have strategy labels |
| `test_invoke_error_graceful_degradation` | Module 3 | InvokeError → fall back to FREE_LLM |
| `test_injected_context_passthrough` | Module 4 | conversation() uses injected_context when present |
| `test_no_router_unchanged` | Module 4 | Without router, conversation() behaves as today |
| `test_auto_register_datasource` | Module 5 | DatasetManager.add_source() auto-registers |
| `test_auto_register_tool` | Module 5 | ToolManager.register() auto-registers |
| `test_resolver_demoted_no_vector_only` | Module 6 | OntologyIntentResolver no longer returns vector_only |
| `test_resolver_aql_planning` | Module 6 | Resolver still decides pattern/aql/post_action |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_dataset_routing` | Query about dataset data → DATASET strategy → DatasetManager → result |
| `test_e2e_graph_routing` | Query about graph entity → GRAPH_PAGEINDEX → ontology pipeline → result |
| `test_e2e_vector_fallback` | Query with no dataset/graph match → VECTOR_SEARCH → existing RAG |
| `test_e2e_llm_fallback_with_trace` | No strategy has results → FALLBACK with trace summary → LLM general knowledge |
| `test_e2e_hitl_cycle` | Ambiguous query → HITL question → user reply → re-route with context |
| `test_e2e_cascade` | Primary fails → cascade to secondary → success |
| `test_e2e_exhaustive_synthesis` | exhaustive=True → all strategies → concatenated context → LLM synthesis |
| `test_e2e_no_strategies_available` | Bare agent → skip routing → normal ask() |

### Test Data / Fixtures

```python
@pytest.fixture
def capability_registry():
    """Registry with sample entries for datasets, tools, graph nodes."""
    registry = CapabilityRegistry()
    registry.register(CapabilityEntry(
        id="active_employees",
        resource_type=ResourceType.DATASET,
        description="Active employee records with department, role, start date",
        not_for=["warehouse operations", "inventory"],
        canonical_questions=["who are the active employees?", "employees by department"],
        fields_preview=["employee_id", "name", "department", "role", "start_date"],
        source_ref="active_employees",
    ))
    registry.register(CapabilityEntry(
        id="warehouse_ops",
        resource_type=ResourceType.DATASET,
        description="Warehouse operations: inventory levels, shipments, stock movements",
        not_for=["employee data", "HR"],
        canonical_questions=["inventory by warehouse", "recent shipments"],
        fields_preview=["warehouse_id", "product_id", "quantity", "employee_id"],
        source_ref="warehouse_ops",
    ))
    return registry

@pytest.fixture
def router_config():
    return IntentRouterConfig(
        exhaustive=False,
        hitl_enabled=True,
        hitl_confidence_threshold=0.3,
        fallback_enabled=True,
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `CapabilityRegistry` supports manual, DataSource, Tool, and YAML registration
- [ ] `CapabilityRegistry.search()` returns ranked candidates with cosine similarity
- [ ] `not_for` exclusions reduce or eliminate irrelevant candidates
- [ ] `IntentRouterMixin` auto-detects available strategies from agent configuration
- [ ] Fast path (keyword scan) routes directly without LLM call
- [ ] LLM path uses `invoke()` (FEAT-069) to return `RoutingDecision(primary, cascades)`
- [ ] Cascade fallbacks execute in order when primary returns no results
- [ ] Exhaustive mode tries all strategies, concatenates non-empty results with strategy labels, passes to LLM for synthesis
- [ ] `RoutingTrace` records all attempts with `mode`, `produced_context`, and timing
- [ ] LLM Fallback calls agent's `ask()` with `RoutingTrace` summary in prompt
- [ ] HITL returns clarifying question as normal response (no suspension) when confidence below threshold
- [ ] HITL conversation context works: user reply continues naturally via conversation history
- [ ] `OntologyIntentResolver` demoted: `action` field deprecated, `vector_only` fallback removed
- [ ] `OntologyRAGMixin.ontology_process()` unchanged — called by IntentRouter as GRAPH strategy
- [ ] `AbstractBot.conversation()` accepts `injected_context` kwarg — minimal touch
- [ ] Agents without IntentRouter behave exactly as today — zero overhead
- [ ] `configure_router()` not called → mixin passes through to `super()` unchanged
- [ ] `InvokeError` during classification → graceful degradation to `FREE_LLM`
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] No breaking changes to existing public API

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- `IntentRouterMixin` follows the same cooperative inheritance pattern as `OntologyRAGMixin` — `super().__init__(**kwargs)` and explicit method calls.
- MRO must be correct: `class MyAgent(IntentRouterMixin, OntologyRAGMixin, BasicAgent)` — IntentRouterMixin first so its `conversation()` intercepts before others.
- Cosine similarity uses numpy (already a transitive dependency) — no FAISS needed.
- Embedding function is passed by developer (same callable used by vector store), not built-in.
- YAML loading uses PyYAML (already in stack) for manual graph node / PageIndex entries.
- `PageIndexRetriever` import is lazy — PageIndex is optional.
- Strategy execution uses `asyncio.wait_for(coro, timeout=config.strategy_timeout_ms/1000)` per strategy.

### Strategy Discovery (auto-detect)
```python
# Checked at configure_router() time and cached:
available = set()
if getattr(self, '_ont_graph_store', None):     available.add(GRAPH_PAGEINDEX)
if getattr(self, '_vector_store', None) or getattr(self, '_use_vector', False):
                                                  available.add(VECTOR_SEARCH)
if hasattr(self, 'dataset_manager'):              available.add(DATASET)
if hasattr(self, '_pageindex_retriever'):          available.add(GRAPH_PAGEINDEX)
if self.tool_manager.tool_count() > 0:            available.add(TOOL_CALL)
# Always available:
available.add(FREE_LLM)
if config.fallback_enabled:                       available.add(FALLBACK)
if config.hitl_enabled:                           available.add(HITL)
```

### OntologyIntentResolver Demotion
- `IntentDecision.action` field: keep for backwards compat but ignore when called from IntentRouter.
- `OntologyIntentResolver.resolve()` still works standalone for agents NOT using IntentRouter — no breaking change.
- When called via IntentRouter (GRAPH_PAGEINDEX strategy), the action decision is irrelevant — the router already decided to use the graph.

### Exhaustive Mode Synthesis
- Each strategy result that produces output is labelled: `### Graph context\n{result}`, `### Dataset context\n{result}`, etc.
- All labelled results are concatenated into a single context block.
- The main LLM receives an instruction to synthesize and integrate multiple sources.
- Do NOT rank heterogeneous result types against each other — graph data, dataset rows, and vector fragments are incomparable. Synthesis is the LLM's job.

### Known Risks / Gotchas
- **MRO ordering**: If developer mixes in `IntentRouterMixin` after `BasicAgent`, the router's `conversation()` is shadowed. Document the correct MRO prominently.
- **Embedding quality**: Cosine similarity on descriptions depends on description quality. Poor `description` and `canonical_questions` → bad routing. `not_for` mitigates but doesn't eliminate.
- **HITL conversational context**: The clarifying question is a normal response. If the user ignores it and asks something unrelated, the conversation continues normally — no stuck state.
- **FEAT-069 dependency**: IntentRouterMixin requires `invoke()`. If FEAT-069 is not merged, the LLM path cannot work. Fast path (keyword) and exhaustive mode (no classification) still work.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `numpy` | existing | Cosine similarity for candidate ranking |
| `pyyaml` | existing | Loading manual YAML capability entries |
| `pydantic` | `>=2.0` | All models (existing) |
| FEAT-069 `invoke()` | — | Lightweight LLM classification (cross-feature dep) |

---

## 7. Open Questions

- [x] **Embedding function source** — Pass a dedicated embedding callable (same as vector store model). — *Resolved: Jesus*
- [x] **Registry persistence** — No for v1 (in-memory only). — *Resolved: Jesus*
- [x] **PageIndexRetriever adapter** — Lazy import for now. — *Resolved: Jesus*
- [x] **Advisor interface** — Advisor is a specialized tool, NOT the fallback. FALLBACK is a direct LLM call via `ask()` with `RoutingTrace` context. — *Resolved: Jesus*
- [ ] Should `RoutingTrace` be exposed in the `AIMessage` response (e.g. as metadata) so integration handlers (Telegram, Slack) can optionally display routing info? — *Owner: Jesus*: Yes

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Modules have a strict dependency chain (models → registry → mixin → bot touch-point → auto-registration → resolver demotion). The mixin (Module 3) touches multiple files and depends on both the registry and FEAT-069. Sequential execution avoids merge conflicts.
- **Cross-feature dependencies**: FEAT-069 (`invoke()`) must be merged to `dev` before Module 3 begins. Modules 1, 2, and 5 can start immediately.
- **Task order**: Module 1 → Module 2 → Module 3 → Module 4 → Module 5 → Module 6 → Module 7 → Module 8.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-30 | Jesus Lara | Initial draft from brainstorm Option A + refinements (HITL, Fallback, Cascade, Exhaustive, Resolver demotion) |
