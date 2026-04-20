# TASK-791: Additive `store_rankings` Field on `TraceEntry`

**Feature**: FEAT-111 — Router-Based Adaptive RAG (Store-Level)
**Spec**: `sdd/specs/router-based-adaptive-rag.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-785
**Assigned-to**: unassigned

---

## Context

Implements **Module 9** of FEAT-111. When the store router is active, we want the existing `RoutingTrace` / `TraceEntry` observability machinery to carry store-level detail too. This is an additive Pydantic field with a `None` default — zero impact on existing callers.

---

## Scope

- Add `store_rankings: Optional[list[StoreScore]] = None` to `TraceEntry` in `parrot/registry/capabilities/models.py`.
- Update the import block at the top of the file to import `StoreScore` from `parrot.registry.routing` lazily (TYPE_CHECKING block + string annotation) OR add a local import to avoid a circular import risk. Use whichever pattern keeps `parrot.registry.capabilities.models` free of a runtime dependency on `parrot.registry.routing`.
- Extend the existing `TraceEntry` unit test (wherever it lives) to verify:
  - Default value is `None`.
  - Existing serialization of a `TraceEntry` without store rankings is byte-compatible.
  - A `TraceEntry` with a populated list round-trips correctly.

**NOT in scope**: modifying how `IntentRouterMixin` writes `TraceEntry`s. The field is just available; the `StoreRouter` (TASK-792) will populate it when it builds the trace.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/capabilities/models.py` | MODIFY | Add `store_rankings` to `TraceEntry` |
| `packages/ai-parrot/tests/unit/registry/capabilities/test_models.py` *(or existing test file — inspect first)* | MODIFY or CREATE | Round-trip tests for the new field |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import TYPE_CHECKING, Optional
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from parrot.registry.routing import StoreScore   # forward reference only; avoids import cycle
```

### Existing Signatures to Use
```python
# parrot/registry/capabilities/models.py:99
class TraceEntry(BaseModel):
    routing_type: RoutingType                    # line 110
    produced_context: bool = False               # line 111
    context_snippet: Optional[str] = None        # line 112
    error: Optional[str] = None                  # line 113
    elapsed_ms: float = 0.0                      # line 114
```

### Does NOT Exist
- ~~`TraceEntry.store_rankings`~~ — this task creates it.
- ~~`store_rankings` on `RoutingTrace` itself~~ — only `TraceEntry` gets it (per-step detail).

---

## Implementation Notes

### Key Constraints
- The field is fully optional. Default `None`. Existing code that constructs `TraceEntry(routing_type=..., produced_context=...)` must continue to work unchanged.
- Avoid a runtime import cycle: `parrot.registry.capabilities.models` should NOT import from `parrot.registry.routing` at module top level. Use `TYPE_CHECKING` and string annotations (`Optional["list[StoreScore]"]`), with `TraceEntry.model_rebuild()` called lazily where needed, OR import inside the field declaration via a late-binding trick if Pydantic v2 supports it. The implementer chooses the cleanest approach that satisfies all tests.
- Do NOT use `from __future__ import annotations` if it isn't already in the file — maintain the file's existing style.

### References in Codebase
- `packages/ai-parrot/src/parrot/registry/capabilities/models.py:99` — current `TraceEntry`
- `packages/ai-parrot/src/parrot/registry/capabilities/models.py:117` — `RoutingTrace`

---

## Acceptance Criteria

- [ ] `TraceEntry()` with only required fields still validates.
- [ ] `TraceEntry(routing_type=RoutingType.VECTOR_SEARCH, produced_context=True, store_rankings=[...])` validates.
- [ ] `TraceEntry` serialization of an entry WITHOUT `store_rankings` contains either no field or `store_rankings: None` (document which and test it consistently).
- [ ] No import cycle — `python -c "from parrot.registry.capabilities.models import TraceEntry"` succeeds from a fresh interpreter.
- [ ] Existing `IntentRouterMixin` tests still pass unmodified.

---

## Test Specification

```python
from parrot.registry.capabilities.models import TraceEntry, RoutingType
from parrot.registry.routing import StoreScore
from parrot.tools.multistoresearch import StoreType


def test_default_store_rankings_is_none():
    t = TraceEntry(routing_type=RoutingType.VECTOR_SEARCH)
    assert t.store_rankings is None


def test_store_rankings_roundtrip():
    t = TraceEntry(
        routing_type=RoutingType.VECTOR_SEARCH,
        produced_context=True,
        store_rankings=[StoreScore(store=StoreType.PGVECTOR, confidence=0.9)],
    )
    restored = TraceEntry.model_validate(t.model_dump())
    assert restored.store_rankings[0].store == StoreType.PGVECTOR


def test_no_import_cycle():
    # Smoke test — fails at import time if there's a cycle
    from parrot.registry.capabilities.models import TraceEntry  # noqa
    from parrot.registry.routing import StoreScore              # noqa
```

---

## Agent Instructions

1. Read the spec (§3 Module 9, §7 Implementation Notes regarding backward compatibility).
2. Inspect `parrot/registry/capabilities/models.py:99` to confirm the current `TraceEntry` signature before editing.
3. Add the field using the `TYPE_CHECKING` + forward-reference pattern (or equivalent) to avoid runtime cycles.
4. Run the existing `IntentRouterMixin` / capabilities tests to confirm no regression.
5. Add the new tests.
6. Move this file to `sdd/tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*
