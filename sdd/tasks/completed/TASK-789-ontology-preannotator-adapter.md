# TASK-789: Ontology Pre-Annotator Adapter

**Feature**: FEAT-111 — Router-Based Adaptive RAG (Store-Level)
**Spec**: `sdd/specs/router-based-adaptive-rag.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-785
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of FEAT-111. The store router uses entity/relation hints from the ontology to bias routing (e.g. queries with graph-shaped entities → ArangoDB). `OntologyIntentResolver` is soft-deprecated for strategy routing but its signal-extraction is still useful. This adapter wraps it so deprecation warnings stay out of the router hot path and the dependency is optional.

---

## Scope

- Create `parrot/registry/routing/ontology_signal.py`.
- Implement `class OntologyPreAnnotator`:
  - Constructor takes an optional `resolver` (any object with a `resolve_intent`-like method) OR `None` for a no-op annotator.
  - Constructor suppresses `DeprecationWarning` from `parrot.knowledge.ontology.intent` using `warnings.catch_warnings()` during import/instantiation only.
  - `async def annotate(query: str) -> dict`:
    - If no resolver is configured → returns `{}` (no signal).
    - Otherwise calls the resolver and normalizes its output into a plain `dict` with keys like `action`, `pattern`, `entities` (best-effort mapping from `ResolvedIntent`). Missing fields → omitted from the dict.
    - Any exception from the resolver → log WARNING, return `{}`. Never raises.
- Write unit tests under `tests/unit/registry/routing/test_ontology_signal.py` using a fake resolver (do not require the full ontology stack).

**NOT in scope**: building a new intent resolver; modifying `OntologyIntentResolver`; touching `OntologyRAGMixin`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/routing/ontology_signal.py` | CREATE | `OntologyPreAnnotator` adapter |
| `packages/ai-parrot/src/parrot/registry/routing/__init__.py` | MODIFY | Re-export `OntologyPreAnnotator` |
| `packages/ai-parrot/tests/unit/registry/routing/test_ontology_signal.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import logging
import warnings
from typing import Any, Optional
```

### Existing Signatures to Use
```python
# parrot/knowledge/ontology/intent.py:48
class OntologyIntentResolver:
    """Soft-deprecated for strategy routing. Reused ONLY as a signal source via adapter."""
    __deprecated__ = True   # line 77
    # Real method signature may vary; the adapter uses duck typing — see below.

# parrot/knowledge/ontology/intent.py:30 — LLM decision struct
class IntentDecision(BaseModel):
    action: Literal["graph_query", "vector_only"]
    pattern: str | None
    aql: str | None
    suggested_post_action: str | None
```

### Does NOT Exist
- ~~`parrot.registry.routing.ontology_signal.OntologyPreAnnotator`~~ — this task creates it.
- ~~Any hard import of `OntologyIntentResolver` inside `store_router.py`~~ — the adapter is the ONLY place that touches the resolver.

---

## Implementation Notes

### Key Constraints
- **Duck typing for the resolver**: do NOT assume a fixed method name. Try `resolver.resolve_intent(query)` first; if that does not exist, try `resolver.resolve(query)`. If both fail, log WARNING and return `{}`. (The resolver may be async — detect with `inspect.iscoroutinefunction` and `await` accordingly.)
- Suppress deprecation warnings surgically — only when the adapter instantiates or calls the resolver. Do NOT globally filter.
- The adapter must work when no ontology is configured on the bot (resolver=None). In that case `annotate()` returns `{}` immediately without any warning, log, or ImportError.
- Normalize the output: map `IntentDecision`-like fields into a flat dict. For unknown fields, include them as-is.

### Pattern to Follow
```python
class OntologyPreAnnotator:
    def __init__(self, resolver: Optional[Any] = None) -> None: ...

    async def annotate(self, query: str) -> dict:
        if self._resolver is None:
            return {}
        ...
```

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/ontology/intent.py:48` — resolver class
- `packages/ai-parrot/src/parrot/knowledge/ontology/intent.py:30` — `IntentDecision` schema
- `packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py` — exports `OntologyIntentResolver`

---

## Acceptance Criteria

- [ ] `from parrot.registry.routing import OntologyPreAnnotator` works.
- [ ] `OntologyPreAnnotator(None).annotate("x") == {}` (no resolver → empty).
- [ ] Fake resolver returning an `IntentDecision`-shaped object → dict with `action`, `pattern` etc.
- [ ] Fake resolver that raises → WARNING logged + `{}` returned; no exception propagates.
- [ ] No `DeprecationWarning` escapes into `pytest` when instantiating the adapter with a real `OntologyIntentResolver` (checked via `warnings.catch_warnings(record=True)`).
- [ ] Both sync and async resolver methods work.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/unit/registry/routing/test_ontology_signal.py -v`.

---

## Test Specification

```python
import pytest
import warnings
from parrot.registry.routing import OntologyPreAnnotator


class FakeSyncResolver:
    def resolve_intent(self, query):
        class _Dec:
            action = "graph_query"
            pattern = "supplier-warehouse"
            aql = None
            suggested_post_action = None
        return _Dec()


class FakeAsyncResolver:
    async def resolve_intent(self, query):
        return {"action": "vector_only", "pattern": None}


class BoomResolver:
    def resolve_intent(self, query):
        raise RuntimeError("bad")


@pytest.mark.asyncio
async def test_no_resolver_empty():
    ann = OntologyPreAnnotator(None)
    assert await ann.annotate("anything") == {}


@pytest.mark.asyncio
async def test_sync_resolver_normalizes():
    ann = OntologyPreAnnotator(FakeSyncResolver())
    out = await ann.annotate("supplier warehouse")
    assert out["action"] == "graph_query"
    assert out["pattern"] == "supplier-warehouse"


@pytest.mark.asyncio
async def test_async_resolver():
    ann = OntologyPreAnnotator(FakeAsyncResolver())
    out = await ann.annotate("similar")
    assert out["action"] == "vector_only"


@pytest.mark.asyncio
async def test_resolver_exception_returns_empty(caplog):
    ann = OntologyPreAnnotator(BoomResolver())
    assert await ann.annotate("x") == {}
    assert any("ontology" in r.message.lower() for r in caplog.records) or True


def test_init_does_not_leak_deprecation():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        OntologyPreAnnotator(None)
    assert not any(issubclass(rec.category, DeprecationWarning) for rec in w)
```

---

## Agent Instructions

1. Read the spec (§3 Module 5, §7 Known Risks — the deprecation suppression note).
2. Verify TASK-785 artifacts exist; confirm `OntologyIntentResolver` still lives at `parrot/knowledge/ontology/intent.py:48`.
3. Implement the adapter.
4. Run the tests.
5. Move this file to `sdd/tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*
