# Brainstorm: Intent Router & Capability Registry

**Date**: 2026-03-30
**Author**: Jesus Lara
**Status**: accepted
**Recommended Option**: Option A

---

## Problem Statement

AI-Parrot agents that have a vector store assigned **always** attempt RAG on every
query — even when the query is about structured data (a dataset), requires executing
a tool, or should be delegated to the LLM directly. There is no mechanism to decide
*who should answer* before retrieval begins.

Concrete failure case: an agent with a `DatasetManager` containing `warehouse_ops`
and `active_employees` datasets. A query for "active employees by warehouse" causes
the LLM to pick `warehouse_ops` because it has an `employee_id` field — lexical
match wins over semantic intent. The system has no representation of what each
resource is *designed to answer*, nor what it explicitly should *not* answer.

This problem generalises beyond RAG: the same lack of semantic dispatch affects
dataset routing, tool selection, graph/PageIndex navigation, and fallback honesty.
The fix is not a smarter LLM — it is a **structured registry of capabilities** that
a lightweight LLM can reason over deterministically.

---

## Constraints & Requirements

- Must not break any existing agent that does not opt in to this feature.
- `AbstractBot.ask()` / `conversation()` must remain unchanged for non-router agents.
- The routing LLM call must be **stateless, no-retry, cheap** — FEAT-069 `invoke()`
  is already approved for exactly this purpose.
- The registry must support **auto-registration** from existing DataSource and
  AbstractTool objects — developers should not have to duplicate metadata.
- Manual ontology entries (graph nodes, PageIndex trees) must be definable via YAML
  with no Python code required.
- No new external dependencies beyond what is already in the stack.
- Asyncio-first throughout. No sync fallbacks.
- Pydantic v2 for all models.

---

## Options Explored

### Option A: `CapabilityRegistry` + `IntentRouterMixin` (two-layer)

A standalone `CapabilityRegistry` lives in `parrot/registry/capabilities/`.
An `IntentRouterMixin` in `parrot/bots/mixins/` intercepts `conversation()` before
any RAG or tool dispatch occurs. The registry uses cosine similarity (numpy, no
FAISS) for candidate retrieval, then delegates the final structured decision to
`client.invoke()` (FEAT-069). Vector search is demoted from default behaviour to
an **explicit routing target** — one of seven possible dispatch outcomes.

✅ **Pros:**
- Clean separation: registry knows about resources, mixin knows about the bot pipeline.
- Fully opt-in: agents without the mixin behave exactly as today.
- `invoke()` already approved and specced — no new client-level work.
- Auto-registration from DataSource/AbstractTool requires zero metadata duplication.
- `not_for` exclusions solve the `warehouse_ops` vs `active_employees` problem
  at the prompt level rather than relying on model intelligence.
- Registry is reusable outside bots (e.g. A2A routing, MCP tool selection).

❌ **Cons:**
- Requires a minimal change to `AbstractBot.conversation()` (one `kwargs.pop()`).
- Cosine similarity on descriptions alone may mis-rank if descriptions are poorly
  written — quality of `not_for` and `canonical_questions` matters.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `numpy` | Cosine similarity for candidate ranking | Already a transitive dep |
| `pyyaml` | Loading manual ontology YAML files | Already in stack |
| `pydantic v2` | All registry and routing models | Already in stack |

🔗 **Existing Code to Reuse:**
- `parrot/clients/base.py` — `invoke()` from FEAT-069 (dependency, not reimplemented)
- `parrot/registry/__init__.py` — existing registry package to extend
- `parrot/loaders/pageindex/retriever.py` — `PageIndexRetriever` used by `_run_graph_pageindex()`
- `parrot/data/manager.py` — `DatasetManager` called by `_run_dataset_query()`

---

### Option B: Intent classifier as a standalone Tool

Package intent routing as an `AbstractTool` that the main LLM calls during its
normal tool-calling loop. The tool returns a routing recommendation which the LLM
uses to decide what to call next.

✅ **Pros:**
- No changes to `AbstractBot` at all.
- Fits naturally into the existing tool-calling loop.

❌ **Cons:**
- The main LLM (expensive, stateful) is in the routing loop — exactly what we want
  to avoid. Routing should happen *before* the main LLM, not inside it.
- Tool-calling adds 1-2 extra LLM turns before any answer. Latency unacceptable
  for conversational agents.
- The main LLM can ignore or misuse a routing tool recommendation.

📊 **Effort:** Low (implementation) but High (operational cost and reliability)

---

### Option C: Hardcoded routing rules in YAML

Define routing rules declaratively: if query matches pattern X, use resource Y.
No LLM involved in routing.

✅ **Pros:**
- Fully deterministic. Zero LLM cost for routing.
- Simple to implement and audit.

❌ **Cons:**
- Pattern matching cannot handle paraphrase, ambiguity, or language variation.
- Requires exhaustive manual rule authoring — maintenance nightmare at scale.
- Completely fails for novel query formulations not anticipated in rules.

📊 **Effort:** Low (first version) / High (maintenance)

---

## Recommendation

**Option A** is recommended because it is the only approach that:
1. Routes *before* the expensive LLM turn (unlike Option B).
2. Handles natural language variation (unlike Option C).
3. Uses the already-approved `invoke()` from FEAT-069 — no new client work.
4. Is strictly opt-in with a single minimal touch to `AbstractBot`.

The `not_for` exclusion field is the key differentiator over pure vector search:
it gives developers a first-class way to express disambiguation rules that an LLM
can reason over explicitly, rather than hoping embedding distance handles it.

---

## Feature Description

### User-Facing Behavior

A developer opts into intent routing by:
1. Mixing `IntentRouterMixin` into their agent class.
2. Calling `await self.configure_router(registry, client, ...)` in `configure()`.
3. Registering resources in the registry — either auto (from DataSource/Tool objects)
   or manually (from a YAML file for graph nodes and PageIndex trees).

From that point, every `conversation()` call is intercepted. The router makes one
cheap `invoke()` call, decides who should answer, and either injects context or
signals the appropriate handler. The end user sees no change in the API — only
faster and more accurate responses.

If the router is not configured, the agent behaves exactly as today.

### Internal Behavior

**Registry build (at configure time):**
1. Developer registers resources via `register_from_tool()`, `register_from_dataset()`,
   `register_from_yaml()`, or manual `register()`.
2. `build_index()` is called once. It vectorises all `description + canonical_questions`
   texts using the injected `embedding_fn` and stores the vectors in memory.
3. The index is invalidated (`_index_built = False`) whenever a new resource is registered,
   and lazily rebuilt on the next `search()` call.

**Per-conversation routing (two phases):**

*Phase 1 — candidate search (sync-fast):*
- The query is vectorised with the same `embedding_fn`.
- Cosine similarity against all registry entries (numpy, in-memory).
- Top-K `RouterCandidate` objects returned, sorted by score descending.
- Filtered by `resource_types` if specified.

*Phase 2 — structured resolution (one `invoke()` call):*
- A prompt is constructed with the query + formatted candidates (id, description,
  canonical_questions, not_for, fields_preview).
- Available resource IDs are injected as an explicit closed vocabulary.
- `client.invoke(prompt, output_type=RoutingDecision, ...)` returns a `RoutingDecision`.
- If `confidence < threshold`, `routing_type` is forced to `FALLBACK`.
- If `invoke()` raises `InvokeError`, the mixin catches it and returns `FREE_LLM`
  with `confidence=0.0` — always a valid degraded path.

**Dispatch:**
- `VECTOR_SEARCH` → `injected_context = ""`, `AbstractBot` does its current RAG.
- `DATASET` → `DatasetManager` is queried with `source_ref`; result serialised as str.
- `GRAPH_PAGEINDEX` → `PageIndexRetriever.retrieve(query)` on the cached tree.
- `TOOL_CALL` → a routing hint string is injected; main LLM calls the tool normally.
- `FREE_LLM` → `injected_context = ""`; main LLM with its registered tools.
- `MULTI_HOP` → primary + secondary resources dispatched in parallel via `asyncio.gather()`.
- `FALLBACK` → **direct LLM call** via agent's `ask()` method (main model, full
  context) with a `RoutingTrace` summary injected into the prompt. The trace lists
  which strategies were tried and what they returned (e.g. "Vector search: 0 results,
  Graph: no matching pattern, Dataset: no coverage"). The LLM is warned about
  hallucination risk. The Advisor is a specialized tool for product selection — it
  is NOT the fallback and NOT directly referenced by IntentRouter.
- `HITL` → when confidence is below `hitl_confidence_threshold` (developer-configurable)
  across all attempted strategies, the router formulates a clarifying question and
  returns it as a **normal response** in the same conversation — no
  `HumanInteractionInterrupt`, no agent suspension. The next user message continues
  the conversation naturally via conversation history. Example: query "what's the
  price?" → HITL response "Price of which product?" → user replies "Cabo" → router
  re-routes with enriched context.

**`AbstractBot` touch-point (minimal):**
```python
# AbstractBot.conversation() — only change:
injected_context = kwargs.pop("injected_context", None)
kwargs.pop("routing_decision", None)

if injected_context is not None:
    context = injected_context          # router resolved it
elif self._vector_store is not None:
    context = await self._retrieve(query)  # existing RAG behaviour
else:
    context = ""
```
No other method in `AbstractBot` is touched.

### Edge Cases & Error Handling

- **Empty registry**: `search()` returns `[]`. Router prompt receives no candidates
  and returns `FREE_LLM`. Agent behaves as if router were not present.
- **`invoke()` failure**: `InvokeError` caught in `_route()`. Returns
  `RoutingDecision(routing_type=FREE_LLM, confidence=0.0, reasoning="Router error: {e}")`.
  The main conversation continues uninterrupted.
- **Confidence below threshold**: `routing_type` forced to `FALLBACK` post-decision.
  The original `reasoning` from the LLM is preserved for observability.
- **`MULTI_HOP` partial failure**: `asyncio.gather()` with individual try/except per
  resource. Failed resources are logged as warnings; successful ones are concatenated.
  If all fail, falls back to `""` (FREE_LLM behaviour).
- **`GRAPH_PAGEINDEX` with no cached tree**: logs warning, returns `""`.
  Tree loading is the agent's responsibility in `configure()` — the mixin does no I/O.
- **Incorrect MRO** (`class MyAgent(BasicAgent, IntentRouterMixin)`):
  `IntentRouterMixin.conversation()` is shadowed by `BasicAgent.conversation()`.
  Router is silently inactive. The docstring must include the correct MRO example
  and the risk of getting it wrong.
- **`configure_router()` not called**: `_router_active` is never set to `True`.
  `conversation()` detects this via `getattr(self, "_router_active", False)` and
  passes through to `super()` unchanged.
- **HITL + Fallback conflict**: If both are possible, HITL takes priority — ask
  for clarification before attempting general knowledge. HITL only triggers when
  `hitl_enabled=True` and confidence is below `hitl_confidence_threshold`.
- **HITL conversation context**: The clarifying question is returned as a normal
  response. The user's reply enters `ask()` naturally. The LLM sees the Q&A in
  conversation history and understands the context (e.g. "What's the price?" →
  "Price of which product?" → "Cabo" → LLM understands "Cabo" is the product).

---

## OntologyIntentResolver Demotion

`OntologyIntentResolver` transitions from a router to a **query planner for ArangoDB**.
Its `action: graph_query | vector_only` decision is superseded by `IntentRouterMixin` —
when execution reaches `OntologyIntentResolver`, the decision to use the graph has
already been made by the router.

**Layering:**
```
IntentRouterMixin._route()          ← the universal router
    ↓
    Fast path: CapabilityRegistry keyword scan   (analogous to _try_fast_path)
    LLM path:  client.invoke() → RoutingDecision (analogous to _try_llm_path)
    ↓
    routing_type = GRAPH_PAGEINDEX
    ↓
OntologyRAGMixin.ontology_process() ← unchanged
    ↓
OntologyIntentResolver              ← demoted role:
                                       no longer decides IF graph,
                                       only decides WHAT traversal to run
```

**Changes to OntologyIntentResolver:**
- `action: Literal["graph_query", "vector_only"]` becomes irrelevant — always `graph_query` when called.
- `_try_fast_path()` and `_try_llm_path()` still decide WHICH pattern/AQL to use.
- The `vector_only` fallback case is removed — the router already handles that upstream.
- `IntentDecision.action` field can be deprecated.
- `OntologyRAGMixin.ontology_process()` continues to work unchanged — it's just called
  by IntentRouterMixin instead of directly by the agent.

---

## Exhaustive Mode & Cascade Strategies

**RoutingDecision** includes a primary strategy and a cascade list:
```python
class RoutingDecision(BaseModel):
    routing_type: RoutingType          # primary strategy
    cascades: list[RoutingType] = []   # fallback strategies if primary fails
    confidence: float
    reasoning: str
    source_ref: str | None = None
    secondary_ref: str | None = None
```

**Normal mode** (`exhaustive=False`):
- LLM classifies intent → returns `RoutingDecision(primary=DATASET, cascades=[VECTOR_SEARCH, FREE_LLM])`.
- Execute primary. If it returns adequate results, done.
- If primary fails, cascade through fallback strategies in order.
- Cascade adds latency only on primary failure.

**Exhaustive mode** (`exhaustive=True`):
- Skip LLM classification. Try ALL available strategies in fixed order:
  `GRAPH_PAGEINDEX → DATASET → VECTOR_SEARCH → TOOL_CALL → FREE_LLM → FALLBACK`.
- Collect ALL non-empty results from every strategy that produces output.
- Concatenate them into a single context block, separated by strategy label
  (e.g. `### Graph context`, `### Dataset context`, `### Vector context`).
- Pass the full concatenated context to the main LLM with an explicit instruction
  to synthesise and integrate the multiple sources into a coherent answer.
- Do NOT attempt to rank or score heterogeneous result types against each other —
  graph data (structured traversal), dataset rows, and vector fragments are
  incomparable by a single metric. Synthesis is the LLM's responsibility.
- `RoutingTrace` records every strategy attempted, whether it produced results,
  and its execution time — giving full observability into what was tried.
- Slower but thorough — useful for debugging, critical queries, or agents where
  completeness matters more than latency.

---

## Routing Trace

`RoutingTrace` records what strategies were tried during a routing cycle:
```python
class RoutingTrace(BaseModel):
    entries: list[TraceEntry] = []
    mode: Literal["normal", "exhaustive"] = "normal"

class TraceEntry(BaseModel):
    strategy: RoutingType
    result_count: int          # 0 = empty / no match
    confidence: float
    execution_time_ms: float
    error: str | None = None
    produced_context: bool     # True if this entry contributed to final context
```

The trace serves three purposes:
1. **LLM Fallback prompt** (normal mode): "The following sources were checked:
   Vector search (0 results), Graph (no matching pattern), Dataset (no coverage).
   Answer from general knowledge with appropriate caveats about accuracy."
2. **Exhaustive mode synthesis prompt**: The trace identifies which strategies
   produced non-empty context (`produced_context=True`), which are labelled and
   concatenated before being handed to the main LLM for integration.
3. **Observability/debugging**: Developers can inspect the trace to understand
   why a particular strategy was chosen or why exhaustive mode produced a given
   set of sources.

---

## Capabilities

### New Capabilities
- `capability-registry`: Dynamic semantic registry of agent resources with embedding-based search
- `intent-router-mixin`: Pre-RAG routing mixin for AbstractBot subclasses
- `routing-trace`: Per-request trace of strategy attempts (`mode`, `produced_context`) for fallback context, exhaustive synthesis, and observability
- `llm-fallback-strategy`: Direct LLM call with tried-and-failed context summary (normal mode) or multi-source synthesis prompt (exhaustive mode)
- `hitl-clarification`: Clarifying question returned in same conversation without agent suspension
- `intent-router-config`: Developer-configurable thresholds, exhaustive mode, HITL toggle

### Modified Capabilities
- `abstract-bot-conversation`: Accepts optional `injected_context` kwarg; RAG is
  now conditional on routing decision rather than unconditional.
- `ontology-intent-resolver`: Demoted from router to AQL query planner. `action` field
  deprecated — when called, it's always for graph traversal. Keeps pattern/aql/post_action.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/registry/` | extends | New `capabilities/` subpackage added |
| `parrot/bots/mixins/` | new | New `intent_router.py` module |
| `AbstractBot.conversation()` | modifies | One `kwargs.pop()` + one conditional block |
| `DatasetManager.add_source()` | extends | Optional `capability_registry` kwarg |
| `ToolManager.register()` | extends | Optional `capability_registry` kwarg |
| `DataSource` | extends | Optional `routing_meta: dict` field |
| `AbstractTool` | extends | Optional `routing_meta: dict` field |
| `parrot/knowledge/ontology/intent.py` | modifies | OntologyIntentResolver demoted: action field deprecated, vector_only fallback removed |
| `parrot/knowledge/ontology/schema.py` | modifies | ResolvedIntent.action becomes optional/deprecated |
| FEAT-069 `invoke()` | depends on | Required — must be merged before this feature |

---

## File Layout

```
parrot/
  registry/
    capabilities/
      __init__.py        # exports: CapabilityRegistry, CapabilityEntry,
                         #          ResourceType, RoutingType, RoutingDecision,
                         #          RouterCandidate
      models.py          # Enums (ResourceType, RoutingType) +
                         # Pydantic models (CapabilityEntry, RoutingDecision,
                         # RouterCandidate, RoutingTrace, TraceEntry,
                         # IntentRouterConfig)
      registry.py        # CapabilityRegistry class
  bots/
    mixins/
      __init__.py        # exports: IntentRouterMixin
      intent_router.py   # IntentRouterMixin class (routing, cascade,
                         # fallback, HITL, exhaustive mode)

tests/
  registry/
    test_capability_models.py    # T1 — model validation
    test_capability_registry.py  # T2 — registry behaviour + search
  bots/
    test_intent_router.py        # T3 — mixin pipeline + dispatch
    test_intent_router_e2e.py    # T4 — end-to-end routing scenarios
                                 #      (including HITL, fallback, cascade)
```

---

## Task Breakdown

```
T1 — models.py                  (no deps)
     RoutingType, ResourceType, CapabilityEntry, RoutingDecision,
     RouterCandidate, RoutingTrace, TraceEntry, IntentRouterConfig
T2 — registry.py                (deps: T1)
T3 — IntentRouterMixin          (deps: T1, T2, FEAT-069)
     Routing, cascade, fallback, HITL, exhaustive mode
T4 — AbstractBot touch-point    (deps: T3)
T5 — Auto-registration hooks    (deps: T2)
     DatasetManager.add_source()
     ToolManager.register()
     DataSource.routing_meta
     AbstractTool.routing_meta
T6 — OntologyIntentResolver     (deps: T3)
     demotion
     Demote action field, remove vector_only fallback
```

T1, T5 can run in separate worktrees.
T2 requires T1. T3 requires T1 + T2 + FEAT-069 merged.
T6 requires T3 (router must exist before demoting resolver).

**Worktree strategy**: `per-feature` — single worktree `parrot-intent-router`
branched from `dev` after FEAT-069 is merged. Tasks run sequentially within the
worktree given the dependency chain.

**Cross-feature dependency**: FEAT-069 (`invoke()`) must be merged to `dev` before
T3 begins. T1, T2, T5 (AbstractBot touch-point and model/registry work) can start
immediately.

---

## Open Questions

- [ ] **Embedding function source** — the registry needs an `embedding_fn`. Should
  the mixin default to using `client.invoke()` itself for embedding (prompting the
  lightweight model to embed), or expect the developer to pass a dedicated embedding
  callable (e.g. HuggingFace sentence-transformers)? The second is faster and cheaper
  at search time. — *Owner: Jesus*: pass a dedicated embedding callable that is also in the Vector Store model.

- [ ] **Registry persistence** — should `CapabilityRegistry` optionally serialise
  its entries (without embeddings) to a JSON/YAML file so the developer can inspect
  what was auto-registered? Useful for debugging `not_for` and `canonical_questions`.
  Out of scope for v1 but worth noting. — *Owner: Jesus*: No for v1.

- [ ] **`PageIndexRetriever` adapter** — `_run_graph_pageindex()` needs the
  `PageIndexRetriever` from `parrot/loaders/pageindex/`. The mixin should not import
  it directly if PageIndex is an optional feature. Should this use a lazy import or
  a registered adapter pattern? — *Owner: Jesus*: lazy-import for now.

- [x] **Advisor interface** — Resolved: The Advisor is a **specialized tool** for product
  selection. It is NOT the fallback and NOT directly referenced by IntentRouter. FALLBACK
  is a direct LLM call via `ask()` with `RoutingTrace` context. The Advisor is invoked
  by the agent's normal tool-calling mechanism when appropriate. — *Resolved: Jesus*