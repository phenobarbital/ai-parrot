# TASK-785: Store Router Config & Decision Models

**Feature**: FEAT-111 — Router-Based Adaptive RAG (Store-Level)
**Spec**: `sdd/specs/router-based-adaptive-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of FEAT-111. All other modules (rules engine, YAML loader, cache, ontology adapter, StoreRouter core, AbstractBot integration) import these models, so this task must land first.

---

## Scope

- Create a new package `parrot/registry/routing/` with `__init__.py`.
- Implement Pydantic v2 data models in `parrot/registry/routing/models.py`:
  - `StoreFallbackPolicy` — `str` enum (`FAN_OUT`, `FIRST_AVAILABLE`, `EMPTY`, `RAISE`).
  - `StoreRule` — single heuristic rule (pattern, store, weight, regex flag).
  - `StoreRouterConfig` — full router configuration (margin_threshold, confidence_floor, llm_timeout_s, top_n, fallback_policy, cache_size, enable_ontology_signal, custom_rules).
  - `StoreScore` — one ranked store entry (store, confidence, reason).
  - `StoreRoutingDecision` — complete routing decision (rankings, fallback_used, cache_hit, ontology_annotations, path, elapsed_ms).
- Reuse the existing `StoreType` enum from `parrot/tools/multistoresearch.py` (do NOT define a new one).
- Write unit tests under `tests/unit/registry/routing/test_models.py`.

**NOT in scope**: YAML loading, rules execution, cache, router orchestration, bot integration, tracing extension.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/routing/__init__.py` | CREATE | Package init; re-export public symbols |
| `packages/ai-parrot/src/parrot/registry/routing/models.py` | CREATE | Pydantic v2 data models for this feature |
| `packages/ai-parrot/tests/unit/registry/routing/__init__.py` | CREATE | Empty test package init |
| `packages/ai-parrot/tests/unit/registry/routing/test_models.py` | CREATE | Unit tests for all models |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.multistoresearch import StoreType  # verified: packages/ai-parrot/src/parrot/tools/multistoresearch.py:30
from pydantic import BaseModel, Field                 # project-wide
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/multistoresearch.py:30
class StoreType(Enum):
    PGVECTOR = "pgvector"
    FAISS    = "faiss"
    ARANGO   = "arango"
```

### Does NOT Exist
- ~~`parrot.registry.routing` package~~ — this task creates it.
- ~~`StoreFallbackPolicy`, `StoreRule`, `StoreRouterConfig`, `StoreScore`, `StoreRoutingDecision`~~ — this task creates them.
- ~~Any `StoreType` class in `parrot.registry.routing`~~ — reuse the one in `parrot.tools.multistoresearch`.
- ~~`parrot.rag` package or `BaseRetriever`~~ — do not create, do not import.

---

## Implementation Notes

### Pattern to Follow
Mirror the shape and conventions of `IntentRouterConfig` in `packages/ai-parrot/src/parrot/registry/capabilities/models.py:131` (Pydantic v2, `Field(..., description=...)` with validation bounds, sensible defaults).

### Key Constraints
- Use Pydantic v2 (`BaseModel` + `Field`, not dataclasses).
- `str` enum subclasses for `StoreFallbackPolicy` so values serialize as strings.
- Default values from spec §2 Data Models:
  - `margin_threshold=0.15`, `confidence_floor=0.2`, `llm_timeout_s=1.0`, `top_n=1`, `fallback_policy=FAN_OUT`, `cache_size=256`, `enable_ontology_signal=True`, `custom_rules=[]`.
- `StoreScore.confidence` bounded `[0.0, 1.0]` via `ge=0.0, le=1.0`.
- `StoreRouterConfig.cache_size` accepts `0` to mean "disabled".
- `StoreRoutingDecision.path` is a free-form string field but conventional values are `"fast" | "llm" | "cache" | "fallback"`.
- Re-export the public symbols from `parrot/registry/routing/__init__.py`.

### References in Codebase
- `packages/ai-parrot/src/parrot/registry/capabilities/models.py:131` — `IntentRouterConfig` shape to mirror
- `packages/ai-parrot/src/parrot/tools/multistoresearch.py:30` — `StoreType` enum (reused)

---

## Acceptance Criteria

- [ ] `from parrot.registry.routing import StoreFallbackPolicy, StoreRule, StoreRouterConfig, StoreScore, StoreRoutingDecision` works.
- [ ] `StoreRouterConfig()` (no args) validates with the defaults listed in Implementation Notes.
- [ ] `StoreRule(regex=True, pattern=".*", store=StoreType.PGVECTOR)` round-trips cleanly via `.model_dump()` / `.model_validate()`.
- [ ] Invalid confidence values (< 0.0 or > 1.0) raise `ValidationError`.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/unit/registry/routing/test_models.py -v`.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/registry/routing/`.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/registry/routing/test_models.py
import pytest
from pydantic import ValidationError
from parrot.registry.routing import (
    StoreFallbackPolicy, StoreRule, StoreRouterConfig,
    StoreScore, StoreRoutingDecision,
)
from parrot.tools.multistoresearch import StoreType


class TestStoreRouterConfig:
    def test_defaults(self):
        cfg = StoreRouterConfig()
        assert cfg.margin_threshold == 0.15
        assert cfg.fallback_policy == StoreFallbackPolicy.FAN_OUT
        assert cfg.cache_size == 256
        assert cfg.top_n == 1
        assert cfg.custom_rules == []

    def test_cache_disabled_when_zero(self):
        cfg = StoreRouterConfig(cache_size=0)
        assert cfg.cache_size == 0


class TestStoreRule:
    def test_regex_flag(self):
        rule = StoreRule(pattern=".*graph.*", store=StoreType.ARANGO, regex=True)
        assert rule.regex is True
        assert rule.store == StoreType.ARANGO

    def test_default_weight(self):
        rule = StoreRule(pattern="exact", store=StoreType.PGVECTOR)
        assert rule.weight == 1.0


class TestStoreScore:
    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            StoreScore(store=StoreType.PGVECTOR, confidence=1.5)
        with pytest.raises(ValidationError):
            StoreScore(store=StoreType.PGVECTOR, confidence=-0.1)


class TestStoreRoutingDecision:
    def test_roundtrip(self):
        d = StoreRoutingDecision(
            rankings=[StoreScore(store=StoreType.PGVECTOR, confidence=0.9)],
            path="fast",
        )
        restored = StoreRoutingDecision.model_validate(d.model_dump())
        assert restored.rankings[0].store == StoreType.PGVECTOR
        assert restored.path == "fast"
```

---

## Agent Instructions

1. Read the spec (§2 Architectural Design → Data Models) for full context.
2. Verify the Codebase Contract: confirm `StoreType` still exists at `multistoresearch.py:30`.
3. Implement the package and models.
4. Run `pytest packages/ai-parrot/tests/unit/registry/routing/test_models.py -v`.
5. Move this file to `sdd/tasks/completed/` and update `sdd/tasks/.index.json` to `"done"`.

---

## Completion Note

*(Agent fills this in when done)*
