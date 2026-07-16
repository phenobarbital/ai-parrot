---
type: Wiki Overview
title: 'Feature Specification: IntentRouterMixin — Embedding-Based Output-Mode Routing'
id: doc:sdd-specs-intent-router-mixin-embedding-routing-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: When a user asks a question, the *output mode* (pie chart, map, table, plain
relates_to:
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.bots.mixins
  rel: mentions
- concept: mod:parrot.bots.mixins.intent_router
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.registry.capabilities.models
  rel: mentions
- concept: mod:parrot.utils.helpers
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: IntentRouterMixin — Embedding-Based Output-Mode Routing

**Feature ID**: FEAT-224
**Date**: 2026-06-05
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD (next minor)

> **Source**: research-grounded proposal
> [`sdd/proposals/intent-router-mixin-embedding-routing.proposal.md`](../proposals/intent-router-mixin-embedding-routing.proposal.md)
> (supersedes `intent-router-mixin-brainstorm.md`). Full research audit at
> [`sdd/state/FEAT-224/`](../state/FEAT-224/).

---

## 1. Motivation & Business Requirements

### Problem Statement

When a user asks a question, the *output mode* (pie chart, map, table, plain
text, …) is frequently determined by the phrasing of the request itself
("hazme una gráfica de pastel", "muéstralo en un mapa"). Today there is no
deterministic mechanism to detect this intent **before** the expensive cloud
LLM call. Regex/keyword matching is brittle against paraphrase and informal
Spanish; a dedicated LLM classification call spends an LLM decision purely to
choose an output mode. We want a **fast, local, deterministic** intent layer
that runs *before* the LLM and sets the output mode on the request, using
**semantic similarity** rather than surface patterns.

Research established that this is an **enrichment of an existing subsystem**:
an `IntentRouterMixin` already exists (`parrot/bots/mixins/intent_router.py`)
but solves a *different* problem — pre-RAG **retrieval-strategy** routing over
`conversation()` via a keyword fast-path + LLM `invoke()`. This feature
**evolves that mixin** to add a deterministic **output-mode** router as a
second, clearly separated concern.

### Goals

- **G1** — Local, CPU-friendly, deterministic output-mode classification using
  a multilingual embedding model (`intfloat/multilingual-e5-small`), no cloud
  round-trip and no tokens on the hot path.
- **G2** — A **phrase bank** keyed by `OutputMode`: when a query matches a
  mode's reference utterances above threshold, the resolved `OutputMode` is set
  on the request.
- **G3** — Integrate via the **existing** `IntentRouterMixin`, hooking **both**
  `ask()` and `conversation()` through a single narrow extension point, with a
  **no-op default** in the base class (zero behavior change when absent).
- **G4** — Encoder + route embeddings loaded **once** (CONFIGURE phase); per-
  query routing runs per request (REQUEST phase); blocking `encode()` runs off
  the event loop.
- **G5** — LLM used **only as a tie-breaker** on genuine ambiguity, never as
  the default decision-maker.
- **G6** — No new hard runtime dependency (`sentence-transformers` already
  vendored).
- **G7** — Preserve all existing retrieval-strategy routing behavior (no
  regression).

### Non-Goals (explicitly out of scope)

- **Chart subtype inference** (pie vs bar vs line). The router resolves the
  `OutputMode` **only** (mode-only granularity, resolved in proposal §5/U4);
  subtype is decided downstream by the LLM/chart builder.
- **LLM fallback for below-threshold queries** beyond the bounded tie-breaker.
  Below threshold → abstain, leave `OutputMode.DEFAULT`.
- **Multi-intent decomposition** ("dame una tabla y luego un mapa"). Single
  best label only in v1.
- **A new `parrot/routing/` package** or a new `OutputModeRouterMixin` class —
  rejected in proposal §3 in favor of evolving the existing mixin (see
  `proposals/…proposal.md` §3 "Integration Risks").
- **Changing the `OutputMode` enum** — already complete; only consumed.
- **A remote/shared encoder inference service** (possible later optimization).

---

## 2. Architectural Design

### Overview

Three cooperating pieces, layered onto existing code:

1. **`EmbeddingIntentRouter`** (new, pure engine) — encodes a phrase bank
   (`dict[OutputMode, list[str]]`) once via e5; `route(query)` returns the best
   `OutputMode`, its score, and the runner-up gap so callers can detect
   ambiguity. No agent coupling.
2. **`IntentRouterMixin`** (evolve existing) — owns a new
   `configure_output_router()` (CONFIGURE: build the engine once) and overrides
   the base hook `_resolve_output_mode()` (REQUEST: route the query; apply the
   threshold + margin policy; consult the LLM tie-breaker only on ambiguity).
   The existing retrieval-strategy routing on `conversation()` is untouched.
3. **`AbstractBot`** (minimal edit) — declares the **no-op** extension point
   `_resolve_output_mode()` and calls it from both `ask()` and `conversation()`
   **only when the incoming `output_mode == OutputMode.DEFAULT`** (precedence:
   explicit caller arg > router > default). The resolved mode is written to the
   `output_mode` local **and** mirrored onto `ctx.output_mode` /
   `ctx.intent_score`.

**Decision policy (U2 — resolved "margin + threshold"):**

```
best, second = top-2 route scores
if best <  threshold:                      → abstain  (leave OutputMode.DEFAULT)
elif (best - second) < discrepancy_margin: → LLM tie-break among the close routes
else:                                      → use the embedding winner
```

### Component Diagram

```
ask()/conversation()  ──(output_mode == DEFAULT?)──► _resolve_output_mode(query, ctx)   [AbstractBot: no-op]
                                                              │  (overridden by mixin)
                                                              ▼
IntentRouterMixin._resolve_output_mode ──► EmbeddingIntentRouter.route(query)
        │                                          │ (e5, max-cosine per OutputMode)
        │  best≥thr & clear winner ◄───────────────┘
        │  best≥thr & ambiguous ──► self.invoke()  (LLM tie-break, candidates only)
        │  best<thr ──► abstain
        ▼
  output_mode (param) + ctx.output_mode + ctx.intent_score
        │
        ▼
  existing downstream rendering (data.py / visualizations) — unchanged
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `IntentRouterMixin` (`bots/mixins/intent_router.py`) | extends | Adds output-mode routing as a 2nd concern; retrieval routing preserved |
| `AbstractBot.ask` / `.conversation` (`bots/abstract.py`) | modifies | Add no-op `_resolve_output_mode` + call sites guarded by `output_mode == DEFAULT` |
| `IntentRouterConfig` (`registry/capabilities/models.py`) | extends | New fields for embedding model, phrase bank, threshold, margin |
| `RequestContext` (`utils/helpers.py`) | extends | Add `output_mode` / `intent_score` attributes (default `None`) |
| `OutputMode` (`models/outputs.py`) | uses | Consumed as route keys + result; not modified |
| `sentence-transformers` | uses | Already vendored; lazy-imported in the engine |
| `self.invoke()` (FEAT-069) | uses | LLM tie-breaker path; graceful abstain if unavailable |

### Data Models

```python
# parrot/registry/capabilities/models.py — EXTEND IntentRouterConfig
class IntentRouterConfig(BaseModel):
    # ... existing fields unchanged ...
    enable_output_mode_routing: bool = Field(False, description="Activate output-mode router")
    embedding_model: str = Field("intfloat/multilingual-e5-small")
    output_mode_routes: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Phrase bank: OutputMode value (str) -> reference utterances",
    )
    output_mode_threshold: float = Field(0.55, ge=0.0, le=1.0,
        description="Min max-cosine to accept a route; below -> abstain")
    discrepancy_margin: float = Field(0.05, ge=0.0, le=1.0,
        description="If (best - second) < margin, consult the LLM tie-breaker")
```

### New Public Interfaces

```python
# parrot/registry/routing/embedding_router.py  (NEW — pure engine, no agent coupling)
class RouteScore(NamedTuple):
    mode: OutputMode | None
    score: float
    runner_up: float          # second-best score (for margin/ambiguity checks)
    ambiguous: bool           # best>=thr and (best-runner_up)<margin

class EmbeddingIntentRouter:
    def __init__(self, model: str = "intfloat/multilingual-e5-small",
                 threshold: float = 0.55, margin: float = 0.05) -> None: ...
    def add_route(self, mode: OutputMode, utterances: list[str]) -> None: ...
    def route(self, query: str) -> RouteScore: ...   # CPU-bound; call via to_thread

# parrot/bots/mixins/intent_router.py  (EVOLVE existing IntentRouterMixin)
class IntentRouterMixin:
    def configure_output_router(self, config: IntentRouterConfig) -> None: ...
    async def _resolve_output_mode(self, query: str,
                                   ctx: "RequestContext | None") -> "OutputMode | None": ...

# parrot/bots/abstract.py  (NEW no-op extension point on AbstractBot)
class AbstractBot:
    async def _resolve_output_mode(self, query: str,
                                   ctx: "RequestContext | None") -> "OutputMode | None":
        """Extension point. Default no-op → keeps OutputMode.DEFAULT."""
        return None
```

---

## 3. Module Breakdown

### Module 1: `EmbeddingIntentRouter` engine
- **Path**: `parrot/registry/routing/embedding_router.py` *(new; package already exists — hosts `llm_helper.py`)*
- **Responsibility**: Lazy-load e5 via `sentence-transformers`; encode the phrase
  bank once with `normalize_embeddings=True`; `route(query)` computes max-cosine
  per `OutputMode` and returns `RouteScore` (best, runner-up, ambiguous). Honors
  the e5 `query:` prefix convention.
- **Depends on**: `OutputMode` (existing), `sentence-transformers` (vendored).

### Module 2: Extend `IntentRouterConfig`
- **Path**: `parrot/registry/capabilities/models.py` *(modify)*
- **Responsibility**: Add `enable_output_mode_routing`, `embedding_model`,
  `output_mode_routes`, `output_mode_threshold`, `discrepancy_margin`. Existing
  fields untouched (no regression to retrieval routing config).
- **Depends on**: none new.

### Module 3: `RequestContext` fields
- **Path**: `parrot/utils/helpers.py` *(modify)*
- **Responsibility**: Add `self.output_mode = None` and `self.intent_score = None`
  in `__init__`; keep the plain-class shape. No Pydantic migration.
- **Depends on**: none.

### Module 4: `AbstractBot` extension point + call sites
- **Path**: `parrot/bots/abstract.py` *(modify)*
- **Responsibility**: Add the no-op `_resolve_output_mode()`; in `ask()` and
  `conversation()`, **when `output_mode == OutputMode.DEFAULT`**, call the hook,
  and if it returns a mode, assign it to the local `output_mode` and mirror onto
  `ctx.output_mode` / `ctx.intent_score`. Keep the edit minimal (template-method;
  avoid full override) to limit merge risk against the churning base.
- **Depends on**: Module 3 (ctx fields).

### Module 5: Evolve `IntentRouterMixin`
- **Path**: `parrot/bots/mixins/intent_router.py` *(modify)*
- **Responsibility**: `configure_output_router(config)` builds the engine once
  and encodes routes (CONFIGURE). Override `_resolve_output_mode()` (REQUEST):
  run `EmbeddingIntentRouter.route` via `asyncio.to_thread`; apply threshold +
  margin policy; on ambiguity call a bounded LLM tie-breaker
  (`self.invoke()`, candidates-only prompt, graceful abstain on failure/timeout);
  chain `await super()._resolve_output_mode(...)`. **Do not alter** the existing
  `conversation()` retrieval routing.
- **Depends on**: Modules 1, 2, 4.

### Module 6: Tests
- **Path**: `parrot/tests/routing/test_embedding_router.py`,
  `parrot/tests/bots/test_intent_router_output_mode.py` *(new)*
- **Responsibility**: engine thresholding/margin/abstain/multilingual; hook
  wiring on both `ask()` and `conversation()`; CONFIGURE/REQUEST phases;
  precedence; off-event-loop encode; retrieval-routing no-regression.
- **Depends on**: Modules 1–5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_route_above_threshold_es_en` | 1 | "hazme una gráfica de pastel" / "create a pie chart" → `STRUCTURED_CHART`, score ≥ threshold |
| `test_route_abstains_below_threshold` | 1 | Off-topic query → `mode is None` (RouteScore), no exception |
| `test_route_marks_ambiguous` | 1 | Two close modes → `ambiguous is True`, `runner_up` populated |
| `test_routes_encoded_once` | 1 | `add_route` encodes at config time; `route()` does not reload the model |
| `test_config_extra_fields_defaults` | 2 | New fields default correctly; existing fields unchanged |
| `test_requestcontext_new_fields_default_none` | 3 | `RequestContext().output_mode is None and .intent_score is None` |
| `test_resolve_output_mode_default_noop` | 4 | Base `_resolve_output_mode` returns `None`; behavior identical without mixin |
| `test_ask_fills_only_when_default` | 4/5 | Router sets mode when `output_mode == DEFAULT`; never overwrites an explicit caller mode |
| `test_margin_triggers_llm_tiebreak` | 5 | best≥thr & gap<margin → `invoke()` consulted once; clear winner → no LLM call |
| `test_encode_off_event_loop` | 5 | `_resolve_output_mode` dispatches `encode()` via `to_thread` (no blocking-call warning) |
| `test_super_chaining` | 5 | `_resolve_output_mode` calls `super()` (cooperative MRO) |

### Integration Tests

| Test | Description |
|---|---|
| `test_pie_chart_sets_structured_chart_via_ask` | End-to-end: `agent.ask("create a pie chart of Q1 sales")` → `ctx.output_mode == STRUCTURED_CHART` and `response.output_mode == STRUCTURED_CHART` |
| `test_map_phrase_via_conversation` | Same path through `conversation()` |
| `test_retrieval_routing_unchanged` | Existing `_route()` keyword/LLM strategy routing produces identical decisions (no regression) |

### Test Data / Fixtures

```python
@pytest.fixture
def output_mode_routes() -> dict[str, list[str]]:
    return {
        "structured_chart": ["hazme una gráfica de pastel", "create a pie chart",
                             "gráfico de barras de esto", "show this as a chart"],
        "structured_map":   ["muéstralo en un mapa", "plot it on a map"],
        "structured_table": ["dame una tabla", "show it as a table"],
    }
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `EmbeddingIntentRouter.route()` returns a `RouteScore` with the best
      `OutputMode` above threshold (Spanish **and** English) and `mode is None`
      below threshold; `ambiguous` is set when `best ≥ threshold` and
      `(best − runner_up) < discrepancy_margin`.
- [ ] Encoder + route embeddings are constructed **exactly once** in
      `configure_output_router()` (CONFIGURE); **no model load occurs during
      `ask()`/`conversation()`**.
- [ ] `ask()` **and** `conversation()` each call `_resolve_output_mode()` exactly
      once per request, and **only when the incoming `output_mode ==
      OutputMode.DEFAULT`**.
- [ ] The base `AbstractBot._resolve_output_mode()` is a verified **no-op**:
      behavior is byte-for-byte identical to pre-change when the mixin is absent.
- [ ] An explicit caller-provided `output_mode` (≠ `DEFAULT`) is **never**
      overwritten by the router (precedence: explicit > router > default).
- [ ] On a match above threshold with a clear winner, the resolved mode is set
      on the `output_mode` param **and** mirrored to `ctx.output_mode` /
      `ctx.intent_score`; below threshold both are left untouched.
- [ ] The LLM tie-breaker is consulted **only** on ambiguity (best ≥ threshold &
      gap < margin), never below threshold and never on a clear winner; it abstains
      gracefully if `invoke()` is unavailable or times out.
- [ ] Mode-only granularity: "create a pie chart …" → `STRUCTURED_CHART`; the
      router does **not** attempt pie/bar/line subtype selection.
- [ ] `encode()` does not run on the event loop (verified via the dispatch
      mechanism; no blocking-call warning under an async test).
- [ ] Existing retrieval-strategy routing (`conversation()` keyword + LLM path)
      is unchanged — `test_retrieval_routing_unchanged` passes.
- [ ] No new hard runtime dependency beyond the already-present
      `sentence-transformers` stack.
- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/routing/ packages/ai-parrot/tests/bots/test_intent_router_output_mode.py -v`).
- [ ] All integration tests pass.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Re-verified 2026-06-05 against
> `dev`. All paths are under `packages/ai-parrot/src/`.

### Verified Imports

```python
from parrot.bots.mixins import IntentRouterMixin          # verified: bots/mixins/__init__.py:6 (+ __all__)
from parrot.bots.agent import BasicAgent                   # verified: bots/agent.py:37
from parrot.registry.capabilities.models import IntentRouterConfig  # verified: registry/capabilities/models.py:149
from parrot.models.outputs import OutputMode               # verified: models/outputs.py:37 (re-export: outputs/__init__.py:27; used bots/data.py:28)
from parrot.utils.helpers import RequestContext, current_context, _current_ctx  # verified: utils/helpers.py:7,47,51
# sentence-transformers, lazy: import sentence_transformers as _st  # pattern: memory/episodic/embedding.py:64, skills/store.py:201
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/mixins/intent_router.py
class IntentRouterMixin:                                              # line 118
    _router_active: bool = False                                     # line 132
    _router_config: Optional[IntentRouterConfig] = None              # line 133
    _capability_registry: Optional[CapabilityRegistry] = None        # line 134
    def __init__(self, **kwargs: Any) -> None: ...                   # line 136 (cooperative super().__init__)
    def configure_router(self, config: IntentRouterConfig,
                         registry: CapabilityRegistry) -> None: ...   # line 149
    async def conversation(self, prompt: str, **kwargs: Any) -> Any: ...  # line 166 (retrieval routing — DO NOT alter)

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(...):
    async def configure(self, app=None) -> None: ...                 # line 1231 (CONFIGURE phase)
    async def conversation(self, question: str, ..., ctx: Optional[RequestContext] = None,
                           output_mode: OutputMode = OutputMode.DEFAULT, ...): ...  # line 3107
    async def ask(self, question: str, ..., ctx: Optional[RequestContext] = None,
                  output_mode: OutputMode = OutputMode.DEFAULT, ...): ...           # line 3660

# packages/ai-parrot/src/parrot/bots/agent.py
class BasicAgent(Chatbot, NotificationMixin): ...                    # line 37

# packages/ai-parrot/src/parrot/registry/capabilities/models.py
class IntentRouterConfig(BaseModel):                                  # line 149
    confidence_threshold: float = 0.7                                # line ~171
    hitl_threshold: float = 0.3
    strategy_timeout_s: float = 30.0
    exhaustive_mode: bool = False
    max_cascades: int = 3
    custom_keywords: dict[str, str] = {}                             # (existing — unchanged)

# packages/ai-parrot/src/parrot/utils/helpers.py
class RequestContext:                                                 # line 7
    def __init__(self, request=None, app=None, llm=None,
                 user_id=None, session_id=None, **kwargs): ...        # line 20 (fields: request, app, llm, user_id, session_id, kwargs)
def current_context() -> Optional[RequestContext]: ...               # line 51
_current_ctx: ContextVar[Optional[RequestContext]]                   # line 47

# packages/ai-parrot/src/parrot/models/outputs.py
class OutputMode(str, Enum):                                          # line 37
    DEFAULT = "default"; STRUCTURED_CHART = "structured_chart"        # lines 39, 69
    STRUCTURED_TABLE = "structured_table"; STRUCTURED_MAP = "structured_map"  # lines 70, 71
    MAP = "map"; TABLE = "table"; CHART = "chart"; INFOGRAPHIC = "infographic"
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `EmbeddingIntentRouter` | `OutputMode` | route keys + return type | `models/outputs.py:37` |
| `IntentRouterMixin._resolve_output_mode` | `AbstractBot._resolve_output_mode` | `super()` override (no-op base) | `bots/abstract.py` (new hook) |
| `ask()` / `conversation()` | `_resolve_output_mode` | call when `output_mode == DEFAULT` | `bots/abstract.py:3660,3107` |
| router result | `RequestContext.output_mode/intent_score` | attribute write | `utils/helpers.py:7` (fields to add) |
| router result | existing render path | `response.output_mode = output_mode` | `bots/base.py:409,1158,1171`; `bots/data.py:1857` |
| LLM tie-break | `self.invoke()` | method call (graceful abstain) | `bots/mixins/intent_router.py:394` (existing pattern) |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot/routing/`~~ — package does not exist. Engine lives in the existing
  `parrot/registry/routing/` package (alongside `llm_helper.py`).
- ~~`parrot.bots.mixins.intent_router.IntentRouter`~~ — no standalone embedding
  engine exists yet (only `IntentRouterMixin`). Create `EmbeddingIntentRouter`.
- ~~`OutputModeRouterMixin`~~ — does not exist; **evolve `IntentRouterMixin`** instead.
- ~~`RequestContext.output_mode`~~ / ~~`RequestContext.intent_score`~~ — do not
  exist yet (Module 3 adds them).
- ~~`IntentRouterConfig.embedding_model` / `.output_mode_routes` /
  `.output_mode_threshold` / `.discrepancy_margin`~~ — do not exist yet (Module 2 adds them).
- ~~`AbstractBot._resolve_output_mode`~~ — does not exist yet (Module 4 adds the no-op).
- ~~`RenderPhase` as a general lifecycle dispatcher~~ — `RenderPhase`
  (`bots/prompts/layers.py:35`) exists but is scoped to prompt-layer caching;
  do not wire routing through it. CONFIGURE = `configure_*()`, REQUEST = `ask()/conversation()`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Lazy ST import + load-once**: `import sentence_transformers as _st` inside the
  engine; instantiate in `configure_output_router()` only (pattern:
  `memory/episodic/embedding.py:64`, `skills/store.py:201`).
- **Off the event loop**: wrap the blocking `route()`/`encode()` in
  `await asyncio.to_thread(...)`.
- **Cooperative MRO**: `IntentRouterMixin` must precede the concrete bot
  (`class MyAgent(IntentRouterMixin, BasicAgent)`); `_resolve_output_mode` calls
  `await super()._resolve_output_mode(...)`.
- **e5 prefix convention**: prefix queries with `"query: "` (and bank utterances
  per e5 docs) consistently; document that swapping the encoder invalidates the
  tuned threshold (embedding-space drift).
- **Minimal base edit**: in `abstract.py`, add only the no-op method + two guarded
  call sites; do not restructure `ask()`/`conversation()`.

### Known Risks / Gotchas

- **Conceptual overload** — one mixin now performs two routing jobs (retrieval +
  output mode). *Mitigation*: separate config flag (`enable_output_mode_routing`),
  separate `configure_output_router()`, separate `_resolve_output_mode()`; leave
  `_route()`/`conversation()` untouched.
- **Clause dilution** — output-mode intent is often a small clause inside a long
  data question ("…and show it as a pie chart"); encoding the whole query can
  dilute the signal below threshold. *Mitigation*: phrase the bank as realistic
  full requests; the margin-based LLM tie-breaker covers the ambiguous tail; a
  future option is clause/segment-level encoding (not in v1).
- **Active churn on `abstract.py`** (visualizations work, late May 2026).
  *Mitigation*: keep the base edit tiny and named.
- **Threshold/margin tuning** — load-bearing. Needs a small labeled eval set of
  Spanish/English utterances per mode; re-sweep when the encoder changes. Lives
  under `packages/ai-parrot/tests/routing/fixtures/` (open item, see §8).
- **`invoke()` availability** — the LLM tie-breaker depends on `self.invoke()`
  (FEAT-069); abstain to the embedding winner if absent/timed-out.

### External Dependencies

| Package | Version | Reason |
|---|---|---|

…(truncated)…
