---
type: Wiki Overview
title: IntentRouterMixin — Deterministic Output-Mode Routing
id: doc:sdd-proposals-intent-router-mixin-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: When a user asks a question, the *output mode* (pie chart, map, table, plain
relates_to:
- concept: mod:parrot
  rel: mentions
---

---
type: brainstorm
title: "IntentRouterMixin — deterministic output-mode routing over RequestContext"
feat_id: TBD            # assigned at /sdd-spec
base_branch: dev
status: brainstorm
author: Jesus Lara
created: 2026-06-05
target_packages:
  - packages/ai-parrot
---

# IntentRouterMixin — Deterministic Output-Mode Routing

## 1. Problem Statement

When a user asks a question, the *output mode* (pie chart, map, table, plain
text, …) is frequently determined by the phrasing of the request itself
("hazme una gráfica de pastel", "muéstralo en un mapa"). Today there is no
deterministic mechanism to detect this intent before the expensive cloud LLM
call.

Two naive approaches are inadequate:

- **Regex / keyword matching** — high false-positive rate, brittle against
  paraphrase, typos, and informal Spanish phrasing. Mixes surface form with
  semantic meaning.
- **A cloud LLM classification call** — spends an LLM decision (latency + tokens)
  purely to decide whether to switch output mode. We pay for an LLM to avoid an
  LLM.

We want a **fast, local, deterministic** intent layer that runs *before* the
LLM and sets the output mode on the request, using semantic similarity rather
than surface patterns. The mechanism must integrate into an agent's `ask()`
flow **without** embedding routing logic inside `ask()` itself, and **without**
forcing the LLM to invoke a tool to trigger it.

## 2. Goals / Non-Goals

### Goals
- Local, CPU-friendly intent classification (no cloud round-trip, no tokens).
- Multilingual (Spanish-first) detection of a small, fixed set of output-mode
  intents per agent.
- Integration via mixin, attached to any agent, with a **single, minimal,
  named extension point** added to the base `ask()` — not a full override.
- Deterministic-only behavior: below the confidence threshold the mixin does
  **nothing** and lets the normal flow proceed (LLM fallback is out of this
  path's scope).
- Encoder + reference utterances loaded once (CONFIGURE phase), per-query
  routing done per `ask()` (REQUEST phase).
- Async-safe: blocking `encode()` must not stall the event loop.

### Non-Goals
- LLM-based fallback routing for below-threshold queries (separate concern; the
  mixin simply abstains).
- Multi-intent decomposition ("dame una tabla y luego un mapa"). Single best
  label only in v1; documented as a known limitation.
- Serving the encoder as a remote/shared inference service (possible future
  optimization, see §7 Open Questions).
- Modifying how the LLM renders each output mode — the mixin only *sets* the
  mode; downstream rendering already consumes it.

## 3. Constraints & Architectural Principles (must respect)

- **Asyncio-first.** `SentenceTransformer.encode()` is CPU-bound and synchronous;
  it must be dispatched off the event loop (`asyncio.to_thread` or a dedicated
  executor).
- **Two-phase rendering distinction.** Encoder construction and route encoding
  are static → CONFIGURE phase (`configure()`). The per-query decision is
  dynamic → REQUEST phase (inside `ask()`). Do not load the model per request.
- **Separation of transport vs semantic concerns.** *How* the query is routed
  (encoder, similarity, threshold) is transport; *what* the resulting mode means
  is semantic and lives in the base contract (`output_mode` field). The mixin
  owns only the routing transport.
- **Deterministic paths stay free of LLM decision-making.** No LLM call inside
  the mixin. Threshold-based abstention only.
- **Pydantic v2 at I/O boundaries.** If `RequestContext` is (or becomes) a
  Pydantic model, the new `output_mode` / `intent_score` fields follow v2 rules.
- **Threshold is the load-bearing hyperparameter.** Without per-route threshold
  tuning, the router confidently misroutes ambiguous traffic. Must be
  configurable per agent and ideally per route.

## 4. Codebase Contract

> ⚠️ **VERIFY BEFORE SPEC.** The items below are *assumed* from prior design
> conversation and have **not** been confirmed against the repo. Confirm each
> with the listed `grep` anchor string (not line numbers) before `/sdd-spec`.
> Anything that fails verification becomes a design decision, not a silent
> hallucination.

### 4.1 Existing — verify these exist with these shapes

| Symbol | Purpose | grep anchor (confirm path + signature) |
|---|---|---|
| `BasicAgent.ask()` | Main entry; where the hook is inserted | `grep -rn "async def ask(" packages/ai-parrot` |
| `BasicAgent.configure()` | CONFIGURE-phase setup | `grep -rn "async def configure(" packages/ai-parrot` |
| `RenderPhase` | CONFIGURE vs REQUEST enum | `grep -rn "class RenderPhase" packages/ai-parrot` |
| Request state carrier | Where per-`ask()` state lives | `grep -rn "RequestContext\|request_context\|ctx" packages/ai-parrot` |
| Embedding/encoder usage | Existing HF/sentence-transformers loader to reuse | `grep -rn "SentenceTransformer\|HuggingFace.*Embedding" packages/ai-parrot` |

> **Critical open contract question (blocks design):** does a named
> `RequestContext` object exist, or is per-request state passed as `**kwargs` /
> a dict / attributes on `self`? The hook signature and where `output_mode`
> lives depend entirely on this. If no carrier exists, introducing one (or a
> minimal `RequestState` dataclass/Pydantic model) becomes part of this work.

### 4.2 New — to be created

| Symbol | Location (proposed — verify package layout) | Notes |
|---|---|---|
| `IntentRouter` | `parrot/routing/intent_router.py` *(verify `parrot/` root pkg name)* | Pure engine: encode routes, score query, return `(label\|None, score)` |
| `IntentRouterMixin` | `parrot/agents/mixins/intent_router.py` *(verify mixins dir)* | Wires `IntentRouter` into the agent lifecycle via the hook |
| `BasicAgent._resolve_output_mode()` | same module as `BasicAgent` | New **no-op** extension point called by `ask()` |
| `output_mode`, `intent_score` fields | on the request-state carrier (§4.1) | Default `output_mode=None` → unchanged behavior |

## 5. Architectural Options

There are **two orthogonal decision axes**: (A) the *integration pattern* and
(B) the *router engine*.

### Axis A — Integration pattern

#### A1. Toolkit (`AbstractToolkit`) — REJECTED
The LLM must *decide* to call the routing tool. This defeats the purpose: we
spend an LLM decision to avoid an LLM decision, and routing becomes
non-deterministic and post-hoc.
- Pros: zero base changes; uses existing tool plumbing.
- Cons: requires LLM invocation; non-deterministic; runs *after* the LLM, not
  before; cannot pre-set output mode. **Disqualifying.**

#### A2. Full `ask()` override in the mixin
Mixin overrides `ask()`, routes the query, then calls `super().ask(...)`.
- Pros: zero changes to the base class.
- Cons: couples the mixin to the *entire* `ask()` signature and internal order.
  New params, streaming changes, or reordering silently break the mixin. Fragile
  MRO composition. Hard to test in isolation.

#### A3. Template-method hook — RECOMMENDED
Base `ask()` calls one narrow, named, no-op extension point
(`_resolve_output_mode`). Mixin overrides only that 5-line method.
- Pros: mixin touches a tiny stable surface, not a 100-line method; the
  `output_mode` contract lives in the base (semantic concern) while routing
  lives in the mixin (transport concern); trivially unit-testable; multiple
  mixins can chain via `super()`.
- Cons: requires a **one-time, minimal** edit to the base (`ask()` call site +
  the no-op method + the carrier field). This is *declaring an extension point*,
  not *putting routing logic in `ask()`* — qualitatively different.

### Axis B — Router engine

#### B1. Roll-your-own embeddings + cosine — RECOMMENDED for v1
Reuse the existing HF/sentence-transformers stack. Encode N reference utterances
per route at CONFIGURE; at REQUEST encode the query and take max cosine
similarity per route; abstain below threshold.
- Pros: **zero new runtime dependency** (infra already present for RAG);
  millisecond latency; full control of threshold; trivial to reason about.
- Cons: hand-rolled threshold tuning; no built-in eval harness.

#### B2. `semantic-router` (aurelio-labs) with local `HuggingFaceEncoder`
- Pros: threshold tuning, dynamic routes, and LLM-fallback hooks built in.
- Cons: new dependency; its vector-index integrations lean toward
  Qdrant/Pinecone (in-memory index is fine at our utterance scale, but it is one
  more thing to vendor and pin). Reconsider if route count grows large.

#### B3. SetFit (few-shot trained head) — EVOLUTION PATH
Fine-tune a multilingual Sentence Transformer + classification head on 5–10
labeled examples per intent. Adopt when B1 starts confusing semantically close
intents or once real labeled traffic exists.
- Pros: more robust separation; still tiny and local; multilingual by swapping
  the ST body.
- Cons: introduces a training step + artifact management; overkill for the first
  small, well-separated intent set.

#### B4. Zero-shot NLI (`MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`)
- Pros: no reference utterances to maintain; multilingual.
- Cons: heavier per-query latency (~50–150 ms CPU with several labels). Useful as
  a fallback engine, not the default fast path.

### Recommended encoder
`intfloat/multilingual-e5-small` (Spanish-first, fast). Lighter alternative:
`paraphrase-multilingual-MiniLM-L12-v2`. Higher-quality/heavier:
`BAAI/bge-m3`. Pin the choice in spec; document that swapping the encoder
invalidates the tuned threshold (embedding-space drift).

## 6. Recommendation

**Axis A → A3 (template-method hook). Axis B → B1 (roll-your-own embeddings),
with B3/SetFit documented as the evolution path.**

### Sketch (illustrative; final signatures per verified Codebase Contract)

```python
# parrot/routing/intent_router.py  — pure engine, no agent coupling
import numpy as np
from sentence_transformers import SentenceTransformer


class IntentRouter:
    """Embedding-based, deterministic output-mode router. No cloud LLM."""

    def __init__(self, model: str = "intfloat/multilingual-e5-small",
                 threshold: float = 0.55):
        self.encoder = SentenceTransformer(model)
        self.threshold = threshold
        self._routes: dict[str, np.ndarray] = {}

    def add_route(self, name: str, utterances: list[str]) -> None:
        emb = self.encoder.encode(utterances, normalize_embeddings=True)
        self._routes[name] = emb  # keep all centroids, not just the mean

    def route(self, query: str) -> tuple[str | None, float]:
        q = self.encoder.encode([query], normalize_embeddings=True)[0]
        best_name, best_score = None, -1.0
        for name, emb in self._routes.items():
            score = float(np.max(emb @ q))      # max-sim vs reference utterances
            if score > best_score:
                best_name, best_score = name, score
        if best_score < self.threshold:
            return None, best_score              # abstain → flow unchanged
        return best_name, best_score
```

```python
# base class — ONE-TIME minimal edit
class BasicAgent:
    async def ask(self, query: str, **kwargs):
        ctx = self._build_request_context(query, **kwargs)   # verify carrier
        await self._resolve_output_mode(query, ctx)          # ← single new hook
        # ... existing flow unchanged; REQUEST-phase render consumes ctx.output_mode
        ...

    async def _resolve_output_mode(self, query, ctx) -> None:
        """Extension point. Default no-op: keeps default output_mode."""
        return None
```

```python
# parrot/agents/mixins/intent_router.py
import asyncio
from parrot.routing.intent_router import IntentRouter


class IntentRouterMixin:
    INTENT_ROUTES: dict[str, list[str]] = {}
    INTENT_MODEL: str = "intfloat/multilingual-e5-small"
    INTENT_THRESHOLD: float = 0.55
    _router: IntentRouter | None = None

    async def configure(self, *args, **kwargs):
        await super().configure(*args, **kwargs)
        # CONFIGURE phase: encoder + routes loaded ONCE
        self._router = IntentRouter(self.INTENT_MODEL, self.INTENT_THRESHOLD)
        for name, utts in self.INTENT_ROUTES.items():
            self._router.add_route(name, utts)

    async def _resolve_output_mode(self, query, ctx) -> None:
        # REQUEST phase: route this query; encode() runs off the event loop
        intent, score = await asyncio.to_thread(self._router.route, query)
        if intent is not None:                  # above threshold only
            ctx.output_mode = intent
            ctx.intent_score = score
        # below threshold: leave ctx untouched → normal flow / LLM decides
        await super()._resolve_output_mode(query, ctx)
```

```python
class ChartAgent(IntentRouterMixin, BasicAgent):
    INTENT_ROUTES = {
        "pie_chart": ["hazme una gráfica de pastel", "gráfico circular de esto"],
        "map":       ["muéstrame esto en un mapa", "ubícalo geográficamente"],
        "table":     ["dame una tabla", "formato tabular"],
    }
```

## 7. Module Layout (proposed — confirm against repo)

```
packages/ai-parrot/
  parrot/
    routing/
      __init__.py
      intent_router.py          # IntentRouter (engine)
    agents/
      mixins/
        intent_router.py        # IntentRouterMixin
      basic_agent.py            # + _resolve_output_mode() hook + ask() call site
    <request-state module>      # + output_mode / intent_score fields
  tests/
    routing/
      test_intent_router.py     # engine: thresholding, abstain, multilingual
    agents/
      test_intent_router_mixin.py   # hook wiring, CONFIGURE/REQUEST phases
```

## 8. Open Questions / Risks

1. **RequestContext existence** (blocks design — see §4.1). Named carrier vs
   kwargs/dict? Drives the hook signature and where `output_mode` lives.
2. **Threshold tuning & eval.** Need a small labeled eval set of Spanish
   utterances per intent to sweep `threshold`. Where does this live —
   `tests/fixtures`? Re-sweep policy when encoder changes (embedding drift).
3. **Encoder load cost & memory.** One `SentenceTransformer` per agent vs a
   shared/process-wide singleton. With many concurrent agents, consider a shared
   encoder or a dedicated executor pool to avoid GIL contention; possibly a
   remote encoder service later (Non-Goal in v1).
4. **`asyncio.to_thread` vs dedicated executor.** `to_thread` uses the default
   thread pool; under parallel routing it may saturate. Decide if a bounded
   `ThreadPoolExecutor` is warranted.
5. **Multi-intent** queries collapse to a single label (Non-Goal v1). Document;
   revisit with multi-label scoring if needed.
6. **Cold-start / lazy load.** Should the encoder load eagerly in `configure()`
   or lazily on first `ask()`? Eager keeps REQUEST latency predictable (matches
   the two-phase principle) but raises agent boot cost.
7. **Interaction with explicit user override.** If the caller passes an explicit
   `output_mode` in `**kwargs`, the mixin must not overwrite it. Define
   precedence: explicit caller arg > router > default.

## 9. Acceptance Criteria

- [ ] `IntentRouter.route()` returns `(label, score)` above threshold and
      `(None, score)` below, for both Spanish and English utterances.
- [ ] Encoder and route embeddings are constructed exactly once, in
      `configure()` (CONFIGURE phase); no model load occurs during `ask()`.
- [ ] `ask()` calls `_resolve_output_mode()` exactly once per request; default
      base implementation is a verified no-op (behavior identical to pre-change
      when the mixin is absent).
- [ ] When the mixin is mixed in and the query matches a route above threshold,
      the request carrier's `output_mode` is set accordingly; below threshold it
      is left untouched.
- [ ] An explicit caller-provided `output_mode` is **not** overwritten by the
      router (precedence per §8.7).
- [ ] `encode()` does not run on the event loop (verified via the dispatch
      mechanism; no blocking-call warning under an async test).
- [ ] Unit tests cover: thresholding, abstention, multilingual routing, hook
      wiring, and `super()` chaining of `_resolve_output_mode`.
- [ ] No new hard runtime dependency beyond the already-present
      sentence-transformers stack (B1).

## 10. Revision History

| Date | Author | Change |
|---|---|---|
| 2026-06-05 | Jesus Lara | Initial brainstorm |
