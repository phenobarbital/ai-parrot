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

> Foundation task for FEAT-070. Defines all enums and Pydantic models that the entire intent-router feature depends on.
> Implements spec Section 3 — Module 1 (Routing Models).
> Every subsequent task imports from this module, so it must be implemented first.

---

## Scope

- Create the `parrot/registry/capabilities/` package with `__init__.py` and `models.py`.
- Define enum `ResourceType` with 5 values: `DATASET`, `TOOL`, `GRAPH_NODE`, `PAGEINDEX`, `VECTOR_COLLECTION`.
- Define enum `RoutingType` with 8 values: `GRAPH_PAGEINDEX`, `DATASET`, `VECTOR_SEARCH`, `TOOL_CALL`, `FREE_LLM`, `MULTI_HOP`, `FALLBACK`, `HITL`.
- Define Pydantic models:
  - `CapabilityEntry` — describes a registered capability (name, description, resource_type, embedding vector, metadata, not_for list).
  - `RouterCandidate` — a scored match from capability search (entry, score, resource_type).
  - `RoutingDecision` — the router's output (routing_type, candidates, cascades: list of RoutingType, confidence, reasoning).
  - `RoutingTrace` — full trace of a routing session (mode: Literal["normal", "exhaustive"], entries: list[TraceEntry], elapsed_ms).
  - `TraceEntry` — one step in the trace (routing_type, produced_context: bool, context_snippet, error, elapsed_ms).
  - `IntentRouterConfig` — configuration model (confidence_threshold, hitl_threshold, strategy_timeout_s, exhaustive_mode, max_cascades).
- Export all public names from `__init__.py`.

**NOT in scope**: CapabilityRegistry implementation (TASK-490), IntentRouterMixin (TASK-491), integration with AbstractBot (TASK-492).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/registry/capabilities/__init__.py` | CREATE | Package init; re-export all public models and enums |
| `parrot/registry/capabilities/models.py` | CREATE | All enums and Pydantic models for intent routing |
| `tests/registry/test_capability_models.py` | CREATE | Unit tests for enums and model validation |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/registry/capabilities/models.py
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field
import numpy as np
from numpy.typing import NDArray


class ResourceType(str, Enum):
    """Type of resource registered in the capability index."""
    DATASET = "dataset"
    TOOL = "tool"
    GRAPH_NODE = "graph_node"
    PAGEINDEX = "pageindex"
    VECTOR_COLLECTION = "vector_collection"


class RoutingType(str, Enum):
    """Strategy the intent router can select."""
    GRAPH_PAGEINDEX = "graph_pageindex"
    DATASET = "dataset"
    VECTOR_SEARCH = "vector_search"
    TOOL_CALL = "tool_call"
    FREE_LLM = "free_llm"
    MULTI_HOP = "multi_hop"
    FALLBACK = "fallback"
    HITL = "hitl"


class CapabilityEntry(BaseModel):
    """A registered capability in the semantic index."""
    name: str = Field(..., description="Unique name of the capability")
    description: str = Field(..., description="Human-readable description (used for embedding)")
    resource_type: ResourceType
    embedding: Optional[list[float]] = Field(None, description="Pre-computed embedding vector")
    metadata: dict = Field(default_factory=dict)
    not_for: list[str] = Field(default_factory=list, description="Query patterns this should NOT match")

    model_config = {"arbitrary_types_allowed": True}


class RouterCandidate(BaseModel):
    """A scored match from capability search."""
    entry: CapabilityEntry
    score: float = Field(..., ge=0.0, le=1.0)
    resource_type: ResourceType


class RoutingDecision(BaseModel):
    """The router's selected strategy and candidates."""
    routing_type: RoutingType
    candidates: list[RouterCandidate] = Field(default_factory=list)
    cascades: list[RoutingType] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reasoning: str = Field("", description="LLM explanation for routing choice")


class TraceEntry(BaseModel):
    """One step in the routing trace."""
    routing_type: RoutingType
    produced_context: bool = False
    context_snippet: Optional[str] = None
    error: Optional[str] = None
    elapsed_ms: float = 0.0


class RoutingTrace(BaseModel):
    """Full trace of a routing session."""
    mode: Literal["normal", "exhaustive"] = "normal"
    entries: list[TraceEntry] = Field(default_factory=list)
    elapsed_ms: float = 0.0


class IntentRouterConfig(BaseModel):
    """Configuration for the IntentRouter."""
    confidence_threshold: float = Field(0.7, ge=0.0, le=1.0, description="Min confidence to accept a route")
    hitl_threshold: float = Field(0.3, ge=0.0, le=1.0, description="Below this, ask the human")
    strategy_timeout_s: float = Field(30.0, gt=0.0, description="Per-strategy timeout in seconds")
    exhaustive_mode: bool = Field(False, description="Run all strategies and concatenate results")
    max_cascades: int = Field(3, ge=1, le=10, description="Max cascade steps before fallback")
```

### Key Constraints
- All enums inherit from `str, Enum` for JSON serialization compatibility.
- Pydantic v2 style (`model_config` dict, not `class Config`).
- `CapabilityEntry.embedding` is `Optional[list[float]]` (not numpy array) for Pydantic serialization; conversion to numpy happens in the registry.
- Keep models pure data — no business logic.

### References in Codebase
- `parrot/models/` — existing Pydantic model patterns (e.g., `parrot/models/google.py`)
- `parrot/registry/` — existing registry package structure
- `parrot/knowledge/ontology/schema.py` — `IntentDecision`, `ResolvedIntent` (related models being demoted in TASK-494)

---

## Acceptance Criteria

- [ ] `ResourceType` enum has exactly 5 members
- [ ] `RoutingType` enum has exactly 8 members
- [ ] All 6 Pydantic models instantiate with valid defaults
- [ ] `RoutingDecision` serializes/deserializes with `model_dump()` / `model_validate()`
- [ ] `RoutingTrace` mode field only accepts "normal" or "exhaustive"
- [ ] `IntentRouterConfig` enforces field constraints (ge, le, gt)
- [ ] `from parrot.registry.capabilities import ResourceType, RoutingType, CapabilityEntry, RouterCandidate, RoutingDecision, RoutingTrace, TraceEntry, IntentRouterConfig` works
- [ ] No linting errors: `ruff check parrot/registry/capabilities/`

---

## Test Specification

```python
# tests/registry/test_capability_models.py
import pytest
from parrot.registry.capabilities.models import (
    ResourceType, RoutingType, CapabilityEntry, RouterCandidate,
    RoutingDecision, RoutingTrace, TraceEntry, IntentRouterConfig,
)


class TestResourceType:
    def test_has_five_members(self):
        assert len(ResourceType) == 5

    def test_values(self):
        expected = {"dataset", "tool", "graph_node", "pageindex", "vector_collection"}
        assert {e.value for e in ResourceType} == expected


class TestRoutingType:
    def test_has_eight_members(self):
        assert len(RoutingType) == 8

    def test_values(self):
        expected = {
            "graph_pageindex", "dataset", "vector_search", "tool_call",
            "free_llm", "multi_hop", "fallback", "hitl",
        }
        assert {e.value for e in RoutingType} == expected


class TestCapabilityEntry:
    def test_minimal(self):
        entry = CapabilityEntry(
            name="sales_data",
            description="Monthly sales dataset",
            resource_type=ResourceType.DATASET,
        )
        assert entry.embedding is None
        assert entry.not_for == []
        assert entry.metadata == {}

    def test_with_embedding(self):
        entry = CapabilityEntry(
            name="weather_tool",
            description="Get weather",
            resource_type=ResourceType.TOOL,
            embedding=[0.1, 0.2, 0.3],
        )
        assert len(entry.embedding) == 3


class TestRoutingDecision:
    def test_defaults(self):
        decision = RoutingDecision(routing_type=RoutingType.DATASET)
        assert decision.candidates == []
        assert decision.cascades == []
        assert decision.confidence == 0.0

    def test_with_cascades(self):
        decision = RoutingDecision(
            routing_type=RoutingType.GRAPH_PAGEINDEX,
            cascades=[RoutingType.VECTOR_SEARCH, RoutingType.FALLBACK],
            confidence=0.85,
        )
        assert len(decision.cascades) == 2

    def test_serialization_roundtrip(self):
        decision = RoutingDecision(
            routing_type=RoutingType.TOOL_CALL,
            confidence=0.9,
            reasoning="User asked to call a tool",
        )
        data = decision.model_dump()
        restored = RoutingDecision.model_validate(data)
        assert restored.routing_type == decision.routing_type


class TestRoutingTrace:
    def test_mode_literal(self):
        trace = RoutingTrace(mode="normal")
        assert trace.mode == "normal"
        trace2 = RoutingTrace(mode="exhaustive")
        assert trace2.mode == "exhaustive"

    def test_invalid_mode_rejected(self):
        with pytest.raises(Exception):
            RoutingTrace(mode="invalid")


class TestTraceEntry:
    def test_produced_context_default_false(self):
        entry = TraceEntry(routing_type=RoutingType.VECTOR_SEARCH)
        assert entry.produced_context is False

    def test_with_error(self):
        entry = TraceEntry(
            routing_type=RoutingType.DATASET,
            error="Connection refused",
            elapsed_ms=150.0,
        )
        assert entry.error is not None


class TestIntentRouterConfig:
    def test_defaults(self):
        config = IntentRouterConfig()
        assert config.confidence_threshold == 0.7
        assert config.hitl_threshold == 0.3
        assert config.strategy_timeout_s == 30.0
        assert config.exhaustive_mode is False
        assert config.max_cascades == 3

    def test_invalid_threshold_rejected(self):
        with pytest.raises(Exception):
            IntentRouterConfig(confidence_threshold=1.5)

    def test_invalid_timeout_rejected(self):
        with pytest.raises(Exception):
            IntentRouterConfig(strategy_timeout_s=-1)
```

---

## Agent Instructions

1. Read this task file completely before starting.
2. Read the spec at `sdd/specs/intent-router.spec.md` for full context on Module 1.
3. Implement the code changes described in **Scope** and **Files to Create / Modify**.
4. Follow the patterns in **Implementation Notes** exactly.
5. Run `ruff check` on all modified/created files.
6. Run the tests in **Test Specification** with `pytest`.
7. Do NOT implement anything outside the **Scope** section.
8. When done, fill in the **Completion Note** below and commit.

---

## Completion Note

*(Agent fills this in when done)*
