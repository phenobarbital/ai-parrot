---
type: Wiki Overview
title: 'TASK-1484: EmbeddingIntentRouter engine (pure, e5-based)'
id: doc:sdd-tasks-completed-task-1484-embedding-intent-router-engine-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 1. The pure, agent-decoupled embedding engine that
relates_to:
- concept: mod:parrot._imports
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.registry.routing.embedding_router
  rel: mentions
---

# TASK-1484: EmbeddingIntentRouter engine (pure, e5-based)

**Feature**: FEAT-224 — IntentRouterMixin Embedding-Based Output-Mode Routing
**Spec**: `sdd/specs/intent-router-mixin-embedding-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1. The pure, agent-decoupled embedding engine that
encodes a phrase bank keyed by `OutputMode` and scores a query by max-cosine
similarity. This is the deterministic core (G1/G2) the mixin (TASK-1488) calls.
No agent coupling — testable in isolation.

---

## Scope

- Implement `EmbeddingIntentRouter` and the `RouteScore` result type in a NEW
  module `parrot/registry/routing/embedding_router.py`.
- Lazy-import `sentence_transformers` (do not import at module top level).
- `add_route(mode, utterances)` encodes utterances once with
  `normalize_embeddings=True` and stores per-mode embedding matrices.
- `route(query)` encodes the query (with the e5 `"query: "` prefix), computes
  **max cosine** per `OutputMode`, and returns a `RouteScore(mode, score,
  runner_up, ambiguous)`:
  - `mode is None` when `best < threshold` (abstain).
  - `ambiguous = (best >= threshold) and (best - runner_up) < margin`.
  - when `best >= threshold`, `mode` is the best route even if `ambiguous`
    (caller decides whether to tie-break).
- Write unit tests in `parrot/tests/routing/test_embedding_router.py`.

**NOT in scope**: the mixin wiring, config model changes, RequestContext fields,
any LLM tie-break (that lives in TASK-1488), `ask()`/`conversation()` edits.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/routing/embedding_router.py` | CREATE | `EmbeddingIntentRouter` + `RouteScore` |
| `packages/ai-parrot/tests/routing/test_embedding_router.py` | CREATE | thresholding / margin / abstain / multilingual / encode-once |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.outputs import OutputMode   # verified: models/outputs.py:37 (re-export outputs/__init__.py:27)
# lazy, INSIDE methods only:
#   import sentence_transformers as _st         # pattern: memory/episodic/embedding.py:64, skills/store.py:201
import numpy as np                              # numpy already present in the stack
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/outputs.py:37
class OutputMode(str, Enum):
    DEFAULT = "default"               # line 39
    STRUCTURED_CHART = "structured_chart"   # line 69
    STRUCTURED_TABLE = "structured_table"   # line 70
    STRUCTURED_MAP = "structured_map"       # line 71
    MAP = "map"; TABLE = "table"; CHART = "chart"; INFOGRAPHIC = "infographic"

# Lazy-load + normalize pattern to mirror (memory/episodic/embedding.py:64):
#   import sentence_transformers as _st
#   self._model = _st.SentenceTransformer(model_name)
#   emb = self._model.encode(texts, normalize_embeddings=True)
```

### Does NOT Exist
- ~~`parrot/routing/`~~ — package does not exist. Use the EXISTING
  `parrot/registry/routing/` package (it already contains `llm_helper.py`).
- ~~`parrot.registry.routing.embedding_router`~~ — this module does not exist yet; you are creating it.
- ~~`IntentRouter`~~ as a standalone class — does not exist. Name the engine `EmbeddingIntentRouter`.
- ~~`SentenceTransformer` imported at module top~~ — existing code lazy-imports `sentence_transformers as _st` to keep import time low; follow that.

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot/src/parrot/registry/routing/embedding_router.py
from __future__ import annotations
from typing import NamedTuple, Optional
import numpy as np
from parrot.models.outputs import OutputMode


class RouteScore(NamedTuple):
    mode: Optional[OutputMode]
    score: float
    runner_up: float
    ambiguous: bool


class EmbeddingIntentRouter:
    """Deterministic, embedding-based output-mode router. No cloud LLM."""

    def __init__(self, model: str = "intfloat/multilingual-e5-small",
                 threshold: float = 0.55, margin: float = 0.05) -> None:
        self._model_name = model
        self.threshold = threshold
        self.margin = margin
        self._encoder = None                      # lazy
        self._routes: dict[OutputMode, np.ndarray] = {}

    def _ensure_encoder(self):
        if self._encoder is None:
            import sentence_transformers as _st    # lazy import
            self._encoder = _st.SentenceTransformer(self._model_name)
        return self._encoder

    def add_route(self, mode: OutputMode, utterances: list[str]) -> None:
        enc = self._ensure_encoder()
        texts = [f"query: {u}" for u in utterances]   # e5 prefix convention
        emb = enc.encode(texts, normalize_embeddings=True)
        self._routes[mode] = np.asarray(emb)

    def route(self, query: str) -> RouteScore:
        if not self._routes:
            return RouteScore(None, -1.0, -1.0, False)
        enc = self._ensure_encoder()
        q = np.asarray(enc.encode([f"query: {query}"], normalize_embeddings=True))[0]
        scored = sorted(
            ((m, float(np.max(emb @ q))) for m, emb in self._routes.items()),
            key=lambda kv: kv[1], reverse=True,
        )
        best_mode, best = scored[0]
        runner_up = scored[1][1] if len(scored) > 1 else -1.0
        if best < self.threshold:
            return RouteScore(None, best, runner_up, False)
        ambiguous = (best - runner_up) < self.margin
        return RouteScore(best_mode, best, runner_up, ambiguous)
```

### Key Constraints
- `route()` is CPU-bound and synchronous by design — callers dispatch it via
  `asyncio.to_thread` (TASK-1488). Do NOT add async here.
- Encoder loads at most once (lazy `_ensure_encoder`), reused across routes/queries.
- Keep `numpy` math on normalized vectors (cosine == dot product).

### References in Codebase
- `packages/ai-parrot/src/parrot/memory/episodic/embedding.py:64` — lazy ST load + normalize.
- `packages/ai-parrot/src/parrot/registry/routing/llm_helper.py` — sibling module in the same package.

---

## Acceptance Criteria

- [ ] `EmbeddingIntentRouter` + `RouteScore` implemented in the new module.
- [ ] Above-threshold ES & EN utterances ("hazme una gráfica de pastel" / "create
      a pie chart") route to `STRUCTURED_CHART` with `score >= threshold`.
- [ ] Off-topic query returns `RouteScore(mode=None, ...)` (abstain), no exception.
- [ ] Two close modes yield `ambiguous is True` with `runner_up` populated.
- [ ] Encoder is loaded once (assert `_ensure_encoder` does not reinstantiate).
- [ ] `pytest packages/ai-parrot/tests/routing/test_embedding_router.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/registry/routing/embedding_router.py` clean.
- [ ] `from parrot.registry.routing.embedding_router import EmbeddingIntentRouter, RouteScore` works.

---

## Test Specification

```python
# packages/ai-parrot/tests/routing/test_embedding_router.py
import pytest
from parrot.models.outputs import OutputMode
from parrot.registry.routing.embedding_router import EmbeddingIntentRouter, RouteScore


@pytest.fixture(scope="module")
def router():
    r = EmbeddingIntentRouter(threshold=0.5, margin=0.05)
    r.add_route(OutputMode.STRUCTURED_CHART,
                ["hazme una gráfica de pastel", "create a pie chart", "show this as a chart"])
    r.add_route(OutputMode.STRUCTURED_MAP, ["muéstralo en un mapa", "plot it on a map"])
    r.add_route(OutputMode.STRUCTURED_TABLE, ["dame una tabla", "show it as a table"])
    return r


class TestEmbeddingIntentRouter:
    def test_pie_chart_es_en(self, router):
        assert router.route("hazme un gráfico de pastel de ventas").mode == OutputMode.STRUCTURED_CHART
        assert router.route("create a pie chart of Q1 sales").mode == OutputMode.STRUCTURED_CHART

    def test_map_route(self, router):
        assert router.route("muéstrame las tiendas en un mapa").mode == OutputMode.STRUCTURED_MAP

    def test_abstains_off_topic(self, router):
        rs = router.route("¿cuál es la política de devoluciones?")
        assert rs.mode is None

    def test_empty_routes_abstain(self):
        assert EmbeddingIntentRouter().route("anything").mode is None
```

---

## Agent Instructions

Standard SDD flow: verify the contract, implement per scope, make tests pass,
move this file to `sdd/tasks/completed/`, update the per-spec index to `done`,
fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Opus)
**Date**: 2026-06-05
**Notes**: Implemented `EmbeddingIntentRouter` + `RouteScore` in
`registry/routing/embedding_router.py`. Used the project `parrot._imports.lazy_import`
helper (extra="embeddings") instead of a bare `import sentence_transformers as _st`
(review fix — friendly error + house style). 8 unit tests pass against the real
`multilingual-e5-small` model; model-dependent tests skip gracefully when offline.
**Deviations from spec**: Default `threshold` changed 0.55 -> 0.85. Empirically,
e5 cosine scores cluster high (on-topic ~0.92-0.95, off-topic ~0.77-0.82); 0.55
accepted every query and made the abstain path dead. 0.85 cleanly separates.
Sanctioned by spec §7 ("threshold tuning is load-bearing; re-sweep when encoder changes").
