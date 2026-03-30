# TASK-489: Routing Models

**Feature**: intent-router
**Spec**: `sdd/specs/intent-router.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Implements Module 1 from the spec. All enums and Pydantic models for the intent routing
> system. These are the foundational types that CapabilityRegistry, IntentRouterMixin, and
> all other modules depend on.

---

## Scope

- Create `parrot/registry/capabilities/` package with `__init__.py` and `models.py`.
- Implement all enums and models:
  - `ResourceType` enum (DATASET, TOOL, GRAPH_NODE, PAGEINDEX, VECTOR_COLLECTION)
  - `RoutingType` enum (GRAPH_PAGEINDEX, DATASET, VECTOR_SEARCH, TOOL_CALL, FREE_LLM, MULTI_HOP, FALLBACK, HITL)
  - `CapabilityEntry` model (id, resource_type, description, not_for, canonical_questions, fields_preview, source_ref, routing_meta)
  - `RouterCandidate` model (entry, score)
  - `RoutingDecision` model (routing_type, cascades, confidence, reasoning, source_ref, secondary_ref)
  - `RoutingTrace` model (entries, mode)
  - `TraceEntry` model (strategy, result_count, confidence, execution_time_ms, error, produced_context)
  - `IntentRouterConfig` model (exhaustive, hitl_enabled, hitl_confidence_threshold, fallback_enabled, strategy_timeout_ms, top_k_candidates, confidence_threshold)
- Write unit tests for all models.

**NOT in scope**: CapabilityRegistry implementation, IntentRouterMixin, any strategy logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/registry/capabilities/__init__.py` | CREATE | Package init, export all models |
| `parrot/registry/capabilities/models.py` | CREATE | All enums and Pydantic models |
| `tests/registry/test_capability_models.py` | CREATE | Unit tests for all models |

---

## Implementation Notes

### Pattern to Follow
```python
# Use str Enum pattern consistent with codebase
class RoutingType(str, Enum):
    GRAPH_PAGEINDEX = "graph_pageindex"
    DATASET = "dataset"
    # ...

# Pydantic v2 models
class RoutingDecision(BaseModel):
    routing_type: RoutingType
    cascades: list[RoutingType] = []
    confidence: float
    reasoning: str
    source_ref: str | None = None
    secondary_ref: str | None = None
```

### Key Constraints
- Pydantic v2 throughout (BaseModel, Field).
- `RoutingTrace.mode` is `Literal["normal", "exhaustive"]`.
- `TraceEntry.produced_context` is bool — True if strategy contributed to final context.
- `IntentRouterConfig` defaults: exhaustive=False, hitl_enabled=False, hitl_confidence_threshold=0.3, fallback_enabled=True, strategy_timeout_ms=5000.0, top_k_candidates=5, confidence_threshold=0.4.

### References in Codebase
- `parrot/registry/__init__.py` — existing registry package to extend
- `parrot/knowledge/ontology/schema.py:279` — `ResolvedIntent` (similar model pattern)

---

## Acceptance Criteria

- [ ] All 8 model/enum classes defined in `models.py`
- [ ] `__init__.py` exports all models
- [ ] All tests pass: `pytest tests/registry/test_capability_models.py -v`
- [ ] Imports work: `from parrot.registry.capabilities import RoutingType, CapabilityEntry, RoutingDecision`

---

## Test Specification

```python
# tests/registry/test_capability_models.py
import pytest
from parrot.registry.capabilities.models import (
    ResourceType, RoutingType, CapabilityEntry, RouterCandidate,
    RoutingDecision, RoutingTrace, TraceEntry, IntentRouterConfig,
)

class TestEnums:
    def test_routing_type_all_values(self):
        assert len(RoutingType) == 8

    def test_resource_type_all_values(self):
        assert len(ResourceType) == 5

class TestCapabilityEntry:
    def test_minimal_entry(self):
        entry = CapabilityEntry(id="test", resource_type=ResourceType.DATASET, description="Test")
        assert entry.not_for == []
        assert entry.canonical_questions == []

    def test_full_entry(self):
        entry = CapabilityEntry(
            id="employees", resource_type=ResourceType.DATASET,
            description="Employee records",
            not_for=["warehouse", "inventory"],
            canonical_questions=["who are active employees?"],
            fields_preview=["id", "name", "dept"],
            source_ref="active_employees",
        )
        assert len(entry.not_for) == 2

class TestRoutingDecision:
    def test_with_cascades(self):
        d = RoutingDecision(
            routing_type=RoutingType.DATASET,
            cascades=[RoutingType.VECTOR_SEARCH, RoutingType.FALLBACK],
            confidence=0.85, reasoning="Dataset has employee data",
        )
        assert len(d.cascades) == 2
        assert d.routing_type == RoutingType.DATASET

class TestRoutingTrace:
    def test_exhaustive_mode(self):
        trace = RoutingTrace(mode="exhaustive", entries=[
            TraceEntry(strategy=RoutingType.DATASET, result_count=5,
                       confidence=0.9, execution_time_ms=120, produced_context=True),
            TraceEntry(strategy=RoutingType.VECTOR_SEARCH, result_count=0,
                       confidence=0.0, execution_time_ms=80, produced_context=False),
        ])
        assert trace.mode == "exhaustive"
        assert trace.entries[0].produced_context is True

class TestIntentRouterConfig:
    def test_defaults(self):
        config = IntentRouterConfig()
        assert config.exhaustive is False
        assert config.hitl_enabled is False
        assert config.hitl_confidence_threshold == 0.3
        assert config.fallback_enabled is True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-489-routing-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
