# TASK-4846: Metric match context, tenant resolution and MetricMatcher

**Feature**: FEAT-756 — Metric Definition Registry
**Spec**: `sdd/specs/metric-definition-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4843
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (`context.py`, `matching.py`), risks R1/R3/R4, D3. The registry (TASK-4847) uses
`MetricMatcher` to resolve a question to a metric id; the routing mixin (TASK-4853) and the suggestion
provider read the stashed match through the ContextVar defined here; the toolkit uses
`resolve_metric_tenant`.

**Drift since the spec** (FEAT-755 merged on `dev`): `EmbeddingIntentRouter.add_route` now accepts
`OutputMode | str` labels — no `# type: ignore` needed (R1 resolved). But `route()` runs
`parse_route_label` over the winning label, which raises on a metric id, so the matcher MUST use
`route_label_scores()` and apply threshold/margin itself.

---

## Scope

- `context.py`: `current_metric_match`, `bind_metric_match`, `reset_metric_match`, `resolve_metric_tenant`.
- `matching.py`: `MetricMatcher` (lexical alias lane → embedding lane), `parse_period`, `parse_dimension`.
- `test_matching.py` covering both modules.

**NOT in scope**: `MetricView`/`MetricRegistry` (TASK-4847); the threshold sweep of Q8 beyond a note;
editing `parrot/metrics/__init__.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/metrics/context.py` | CREATE | ContextVar + tenant resolution |
| `packages/ai-parrot/src/parrot/metrics/matching.py` | CREATE | Phrase → metric id matcher |
| `packages/ai-parrot/tests/unit/metrics/test_matching.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.metrics.models import MetricMatch, DimensionSpec, PeriodPreset          # TASK-4843
from parrot.skills.tenancy import current_skill_tenant, validate_tenant_id          # verified: skills/tenancy.py:94, :42
from parrot.registry.routing.embedding_router import EmbeddingIntentRouter          # verified: embedding_router.py (class ~L62, __init__ L70)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/registry/routing/embedding_router.py
class EmbeddingIntentRouter:
    def __init__(self, model: str = "intfloat/multilingual-e5-small", threshold: float = 0.85,
                 margin: float = 0.05, *, encoder: Any | None = None) -> None          # L70-77
    self._routes: dict[str, np.ndarray]                                                 # L96
    def _ensure_encoder(self)                                                           # L98 — lazy SentenceTransformer
    def add_route(self, label: OutputMode | str, utterances: list[str]) -> None         # L116 — str label stored as-is; no-op on empty utterances
    def route_label_scores(self, query: str) -> list[tuple[str, float]]                 # L134 — sorted desc, [] when no routes, NO threshold
    def route(self, query: str) -> RouteScore                                           # L180 — DO NOT USE: parses labels as output modes

# packages/ai-parrot/src/parrot/skills/mixin.py:135 — order to mirror (minus the tenant_based gate):
#   candidates = (explicit, ctx.kwargs.get("tenant") if isinstance(getattr(ctx,"kwargs",None), dict),
#                 current_skill_tenant(), instance default); first non-None → validate_tenant_id

# packages/ai-parrot/src/parrot/skills/tenancy.py
def current_skill_tenant() -> Optional[str]      # L94 (ContextVar aliased to observability current_tenant)

# packages/ai-parrot/src/parrot/registry/capabilities/models.py — IntentRouterConfig defaults:
#   embedding_model "intfloat/multilingual-e5-small", output_mode_threshold 0.85, discrepancy_margin 0.05
```

### Does NOT Exist
- ~~`EmbeddingIntentRouter.route()` for metric ids~~ — raises via `parse_route_label` on non-mode labels; use `route_label_scores`.
- ~~`RequestContext.tenant`~~ — tenant is in `ctx.kwargs["tenant"]`.
- ~~`EmbeddingIntentRouter.clear_routes()` / `remove_route()`~~ — not present; `configure()` builds a NEW router instance.
- ~~Async API on the router~~ — sync, CPU-bound; callers wrap `match()` in `asyncio.to_thread`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/metrics/context.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/metrics/matching.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/metrics/test_matching.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/registry/routing/embedding_router.py#EmbeddingIntentRouter",
    "sym:packages/ai-parrot/src/parrot/registry/routing/embedding_router.py#EmbeddingIntentRouter.add_route",
    "sym:packages/ai-parrot/src/parrot/registry/routing/embedding_router.py#EmbeddingIntentRouter.route_label_scores",
    "sym:packages/ai-parrot/src/parrot/skills/tenancy.py#current_skill_tenant",
    "sym:packages/ai-parrot/src/parrot/skills/tenancy.py#validate_tenant_id",
    "sym:packages/ai-parrot/src/parrot/skills/mixin.py#SkillRegistryMixin._resolve_tenant"
  ]
}
```

---

## Implementation Notes

- Normalisation: casefold, strip accents (`unicodedata.normalize("NFKD")` + drop combining marks), collapse whitespace, strip punctuation.
- Alias lane (questions ≥ 2 tokens): exact normalized match → score 1.0; word-boundary contains of a term (longest term wins) → score 0.95. Two different metric ids tied on the longest term → `ambiguous=True`.
- Embedding lane (questions ≥ 3 tokens, `enable_embeddings`): best label score ≥ threshold → match; `ambiguous = (best - runner_up) < margin`.
- Encoder cold start must never happen on the alias lane (R3): build the router lazily inside `configure` only when `enable_embeddings`; the encoder itself loads on first `add_route` — so `configure` must defer `add_route` until the first embedding-lane call (store the bank, encode lazily). Accept an injected `encoder` for tests.
- `parse_period` lexicon (EN/ES): this month/este mes → this_month; last month/mes pasado/el mes pasado → last_month; today/hoy; yesterday/ayer; this week/esta semana; last week/semana pasada; ytd/year to date/en lo que va del año; mtd/month to date; qtd; last 7|30|90 days/últimos N días; this year/este año; last year/año pasado. Ambiguous (two presets) → None.
- `parse_dimension`: "by <x>" / "por <x>" where x matches a dimension name or alias (normalized) → dimension `name`.

---

## Implementation Blueprint

### Steps (in order)
1. Write `context.py` — *why*: tiny, used by tests and later tasks.
2. Write `matching.py` with lazy embedding bank — *why*: alias hits must never load an encoder.
3. Tests with the `stub_encoder` fixture (TASK-4843 conftest).

### `packages/ai-parrot/src/parrot/metrics/context.py` (CREATE)
```python
"""Per-task metric match ContextVar and tenant resolution (FEAT-756 M3, D3)."""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

from parrot.metrics.models import MetricMatch
from parrot.skills.tenancy import current_skill_tenant, validate_tenant_id  # verified: tenancy.py:94, :42

_metric_match: ContextVar[MetricMatch | None] = ContextVar("parrot_metric_match", default=None)


def current_metric_match() -> MetricMatch | None:
    """Return the match bound to the current task, or ``None``."""
    return _metric_match.get()


def bind_metric_match(match: MetricMatch | None) -> Token:
    """Bind ``match`` for the current task; returns the reset token."""
    return _metric_match.set(match)


def reset_metric_match(token: Token) -> None:
    """Undo ``bind_metric_match``."""
    _metric_match.reset(token)


def resolve_metric_tenant(explicit: str | None = None, ctx: Any | None = None, default: str | None = None) -> str | None:
    """explicit → ``ctx.kwargs["tenant"]`` → ``current_skill_tenant()`` → ``default``; validates the first
    non-empty candidate with ``validate_tenant_id`` (skills/mixin.py:135-150 order, verbatim)."""
    ctx_tenant = None
    ctx_kwargs = getattr(ctx, "kwargs", None) if ctx is not None else None
    if isinstance(ctx_kwargs, dict):
        ctx_tenant = ctx_kwargs.get("tenant")
    chosen = next((c for c in (explicit, ctx_tenant, current_skill_tenant(), default) if c), None)
    return validate_tenant_id(chosen) if chosen else None
```

### `packages/ai-parrot/src/parrot/metrics/matching.py` (CREATE)
```python
"""Phrase → metric id matching: lexical alias lane, then embeddings (FEAT-756 M3)."""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Mapping, Sequence

from parrot.metrics.models import DimensionSpec, PeriodPreset

_LOGGER = logging.getLogger(__name__)


def normalize(text: str) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace."""
    # FILL IN: per Implementation Notes
    raise NotImplementedError


class MetricMatcher:
    """Phrase → metric id. Lexical first (exact / word-boundary contains on normalized terms), then embeddings."""

    def __init__(self, *, embedding_model: str = "intfloat/multilingual-e5-small", threshold: float = 0.85,
                 margin: float = 0.05, enable_embeddings: bool = True, encoder: Any | None = None) -> None:
        """Defaults equal ``IntentRouterConfig`` so one calibration serves both routers.
        ``encoder`` is forwarded to ``EmbeddingIntentRouter`` (tests inject a stub)."""
        self.embedding_model = embedding_model
        self.threshold = threshold
        self.margin = margin
        self.enable_embeddings = enable_embeddings
        self._encoder = encoder
        self._terms: dict[str, list[str]] = {}       # metric_id -> normalized terms
        self._bank: dict[str, list[str]] = {}        # metric_id -> raw terms (embedding utterances)
        self._router: Any | None = None              # EmbeddingIntentRouter, built lazily

    def configure(self, bank: Mapping[str, Sequence[str]]) -> None:
        """Store ``{metric_id: terms}`` and drop any previous router; encoding is deferred to the first
        embedding-lane call (``EmbeddingIntentRouter.add_route`` per id — embedding_router.py:116)."""
        # FILL IN: self._bank = {k: list(v)}; self._terms = normalized; self._router = None
        raise NotImplementedError

    def _ensure_router(self) -> Any:
        if self._router is None:
            from parrot.registry.routing.embedding_router import EmbeddingIntentRouter  # lazy: numpy/ST optional
            router = EmbeddingIntentRouter(self.embedding_model, self.threshold, self.margin, encoder=self._encoder)
            for metric_id, utterances in self._bank.items():
                router.add_route(metric_id, list(utterances))   # str labels accepted since FEAT-755
            self._router = router
        return self._router

    def match(self, question: str) -> tuple[str, float, str, bool] | None:
        """Return ``(metric_id, score, lane, ambiguous)`` or ``None``. CPU-bound: callers use ``asyncio.to_thread``."""
        # FILL IN: tokens = normalize(question).split(); alias lane if len ≥ 2 → return (id, score, "alias", amb)
        # FILL IN: embedding lane if enable_embeddings and len ≥ 3 and bank: scores = self._ensure_router()
        #          .route_label_scores(question)  — NEVER .route() (parse_route_label rejects metric ids);
        #          best < threshold → None; ambiguous = (best - runner_up) < margin; return (label, best, "embedding", amb)
        # FILL IN: any exception in the embedding lane → _LOGGER.warning(...) and return None
        return None

    @staticmethod
    def parse_period(question: str) -> PeriodPreset | None:
        """Small EN/ES lexicon: "this month"/"este mes" → this_month, "last month"/"mes pasado" → last_month, "ytd", …"""
        # FILL IN: lexicon per Implementation Notes; check longer phrases first ("last month" before "month")
        raise NotImplementedError

    @staticmethod
    def parse_dimension(question: str, dimensions: Sequence[DimensionSpec]) -> str | None:
        """"by <dimension-or-alias>" / "por <…>" → dimension name."""
        # FILL IN: normalized regex r"\b(?:by|por)\s+(.+)$"; longest name/alias prefix of the captured text wins
        raise NotImplementedError
```
**Why this shape**: spec skeleton fixes `configure`/`match`/static parsers; `encoder=` and the lazy router
are the minimal additions needed for R3 (no encoder load on the alias lane) and hermetic tests.

### FILL IN checklist
- [ ] `normalize`, `configure`, `match` (both lanes), `parse_period`, `parse_dimension`
- [ ] Q8: note in the Completion Note the scores seen for the Flex vocabulary with the real encoder if available (optional; do not block)
- [ ] tests

---

## Acceptance Criteria

- [ ] Alias fast path matches "worked hours this month" with an encoder that raises when called (proves no encoder load).
- [ ] Embedding lane with `stub_encoder`: score ≥ threshold → match; below → `None`; close runner-up → `ambiguous=True`.
- [ ] Single-token questions never match; 2-token only via aliases.
- [ ] `parse_period` / `parse_dimension` EN + ES cases.
- [ ] `resolve_metric_tenant`: explicit > ctx.kwargs > ContextVar (`bind_skill_tenant`) > default; invalid → `ValueError`.
- [ ] `bind_metric_match` / `reset_metric_match` round-trip.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/metrics/test_matching.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/metrics/test_matching.py
import pytest
from types import SimpleNamespace
from parrot.metrics.context import bind_metric_match, current_metric_match, reset_metric_match, resolve_metric_tenant
from parrot.metrics.matching import MetricMatcher
from parrot.skills.tenancy import bind_skill_tenant, reset_skill_tenant   # verified: tenancy.py:99, :104


class _ExplodingEncoder:
    def encode(self, *a, **k):
        raise AssertionError("encoder must not be called on the alias lane")


def test_matcher_alias_fast_path_no_encoder(worked_hours_def): ...    # FILL IN
def test_matcher_embedding_lane_threshold(stub_encoder): ...           # FILL IN (tune threshold e.g. 0.5 for bag-of-words)
def test_matcher_short_questions_abstain(): ...                        # FILL IN
def test_matcher_parse_period_and_dimension(worked_hours_def): ...     # FILL IN
def test_resolve_metric_tenant_order(): ...                            # FILL IN
def test_metric_match_contextvar(worked_hours_def): ...                # FILL IN
```

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4843 is `done`.
2. Verify contract (re-grep `route_label_scores`, `add_route` signature); mark in-progress; implement.
3. Validate with `PYTHONPATH=packages/ai-parrot/src`; commit listed files only; `scripts/sdd/close_task.sh TASK-4846 metric-definition-registry verified`.

---

## Completion Note

*(Agent fills this in when done)*
