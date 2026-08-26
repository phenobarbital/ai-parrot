# TASK-2472: GenAI SemConv Attribute Additions

**Feature**: FEAT-462 — Unified Telemetry Bus
**Spec**: `sdd/specs/unified-telemetry-bus.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Fills the 2 remaining gaps between our GenAI SemConv span attributes and what
the OpenLIT dashboard expects. Without these, OpenLIT dashboards would render
our spans but miss operation type classification and cost tracking.

Implements spec §3 Module 3.

---

## Scope

- Add `gen_ai.operation.name` = `"chat"` to `build_before_client_attrs()` return dict
- Add `gen_ai.usage.cost` alongside existing `parrot.cost.usd` in `build_after_client_attrs()` (emit both)
- Write unit tests for both additions

**NOT in scope**: Modifying `GenAIOpenTelemetrySubscriber` (it already uses these
builder functions and will pick up the new attributes automatically).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/attributes.py` | MODIFY | Add 2 attributes to builder functions |
| `packages/ai-parrot/tests/unit/observability/test_attributes_semconv.py` | CREATE | Unit tests (corrected path — see TASK-2470) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.attributes import (
    resolve_gen_ai_system,
    build_before_client_attrs,
    build_after_client_attrs,
    PROVIDER_TO_GEN_AI_SYSTEM,
)  # attributes.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/attributes.py:143
# CORRECTED — no gen_ai_system kwarg exists; the contract's signature was
# stale. Actual signature (verified 2026-08-26):
def build_before_client_attrs(event: BeforeClientCallEvent) -> dict[str, Any]:
    """Build OTel attribute dict from a BeforeClientCallEvent."""
    # Returns dict with keys like:
    #   "gen_ai.system", "gen_ai.provider.name",
    #   "gen_ai.request.model", "gen_ai.request.has_tools", etc.

# packages/ai-parrot/src/parrot/observability/attributes.py:182
def build_after_client_attrs(
    event,  # AfterClientCallEvent
    *,
    cost_usd: float | None = None,
) -> dict[str, Any]:
    """Build OTel attribute dict from an AfterClientCallEvent."""
    # Returns dict with keys like:
    #   "gen_ai.response.model", "gen_ai.usage.input_tokens",
    #   "gen_ai.usage.output_tokens", "gen_ai.response.finish_reasons",
    #   "parrot.cost.usd" (when cost_usd is not None)
```

### OpenLIT Expected Attributes
```python
# From openlit/semcov/__init__.py — what the dashboard reads:
"gen_ai.operation.name"   # line 172 — "chat", "embed", etc.
"gen_ai.usage.cost"       # line 518 — USD cost (vendor extension)
```

### Does NOT Exist
- ~~`gen_ai.operation.name` in attributes.py~~ — not emitted today; must be added
- ~~`gen_ai.usage.cost` in attributes.py~~ — not emitted today; only `parrot.cost.usd`

---

## Implementation Notes

### Pattern to Follow
```python
# In build_before_client_attrs(), add to the returned dict:
attrs["gen_ai.operation.name"] = "chat"

# In build_after_client_attrs(), add alongside existing cost:
if cost_usd is not None:
    attrs["parrot.cost.usd"] = cost_usd        # existing — keep for backward compat
    attrs["gen_ai.usage.cost"] = cost_usd       # NEW — OpenLIT SemConv standard
```

### Key Constraints
- `gen_ai.operation.name` defaults to `"chat"` — this covers 95%+ of our calls.
  Future enhancement could derive from event metadata (embed, etc.) but for now
  hardcoded is correct.
- Both `parrot.cost.usd` and `gen_ai.usage.cost` must be emitted with the same
  value. `gen_ai.usage.cost` is the OpenLIT standard; `parrot.cost.usd` is the
  legacy name kept for backward compat.
- The `build_after_client_attrs()` function only emits cost attrs when `cost_usd`
  is not None — this guard applies to both attributes.

---

## Acceptance Criteria

- [ ] `build_before_client_attrs(event)` returns a dict containing `"gen_ai.operation.name": "chat"`
- [ ] `build_after_client_attrs(event, cost_usd=0.002)` returns both `"gen_ai.usage.cost": 0.002` and `"parrot.cost.usd": 0.002`
- [ ] `build_after_client_attrs(event, cost_usd=None)` does NOT include either cost key
- [ ] All tests pass: `pytest packages/ai-parrot/tests/observability/test_attributes_semconv.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/observability/attributes.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/observability/test_attributes_semconv.py
import pytest
from unittest.mock import MagicMock
from parrot.observability.attributes import (
    build_before_client_attrs,
    build_after_client_attrs,
)


@pytest.fixture
def mock_before_event():
    event = MagicMock()
    event.provider = "openai"
    event.model = "gpt-4o"
    event.max_tokens = 1000
    event.temperature = None
    event.top_p = None
    return event


@pytest.fixture
def mock_after_event():
    event = MagicMock()
    event.provider = "openai"
    event.model = "gpt-4o"
    event.input_tokens = 100
    event.output_tokens = 50
    event.finish_reason = "stop"
    return event


class TestGenAiOperationName:
    def test_present_in_before_attrs(self, mock_before_event):
        attrs = build_before_client_attrs(mock_before_event)
        assert attrs.get("gen_ai.operation.name") == "chat"


class TestDualCostAttributes:
    def test_both_cost_attrs_present(self, mock_after_event):
        attrs = build_after_client_attrs(mock_after_event, cost_usd=0.005)
        assert attrs["gen_ai.usage.cost"] == 0.005
        assert attrs["parrot.cost.usd"] == 0.005

    def test_no_cost_when_none(self, mock_after_event):
        attrs = build_after_client_attrs(mock_after_event, cost_usd=None)
        assert "gen_ai.usage.cost" not in attrs
        assert "parrot.cost.usd" not in attrs
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/unified-telemetry-bus.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — read `attributes.py` and confirm the exact lines where `build_before_client_attrs` and `build_after_client_attrs` build their return dicts
4. **Update status** in `sdd/tasks/index/unified-telemetry-bus.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2472-genai-semconv-attributes.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-26
**Notes**: Added `"gen_ai.operation.name": "chat"` (unconditional) to
`build_before_client_attrs()`'s returned dict. Added `"gen_ai.usage.cost"`
alongside the existing `"parrot.cost.usd"` in `build_after_client_attrs()`,
guarded by the same `if cost_usd is not None:` block so both are present or
both are absent together. 5 new unit tests added, built against real
`BeforeClientCallEvent`/`AfterClientCallEvent` instances (matching this
test package's existing convention in `test_attributes.py`, rather than
the task's illustrative `MagicMock`-based fixtures). Full
`tests/unit/observability/` suite (149 tests) passes. `ruff check` on
`attributes.py` shows the same single pre-existing `UP045` violation as
before this change (an `Optional[float]` on code untouched by this task) —
0 new violations.

Also fixed an SDD bookkeeping bug found while working this task: the
"sdd: complete TASK-2470/2471" commits had moved those task files to
`completed/` on disk but never staged the deletion from `active/` — HEAD's
tree still carried stale duplicate copies in `active/`. Fixed with a
dedicated commit (`sdd: fix missing deletions of TASK-2470/2471 from
active/`) before continuing this task.

**Deviations from spec**: Test file path corrected to
`tests/unit/observability/` (same correction as TASK-2470/2471). Test
fixtures use real lifecycle event instances instead of `MagicMock` to match
the existing `test_attributes.py` convention.
