---
type: Wiki Overview
title: 'TASK-1499: Agent-identity ContextVar module'
id: doc:sdd-tasks-active-task-1499-agent-identity-contextvar-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation of FEAT-228 (spec §2 Overview, §3 Module 1). The per-agent metric
relates_to:
- concept: mod:parrot.observability
  rel: mentions
- concept: mod:parrot.observability.context
  rel: mentions
---

# TASK-1499: Agent-identity ContextVar module

**Feature**: FEAT-228 — Per-Agent Cost & Usage Metrics
**Spec**: `sdd/specs/per-agent-cost-usage-metrics.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation of FEAT-228 (spec §2 Overview, §3 Module 1). The per-agent metric
attribution is carried by a `contextvars.ContextVar` that the bot sets around
each invocation and the LLM client reads when building its lifecycle events.
This task creates that carrier; every other task in the feature depends on it
either directly or transitively.

---

## Scope

- Create a new module `parrot/observability/context.py`.
- Define a module-level `current_agent_name: ContextVar[Optional[str]]` with
  default `None`.
- Define an `@contextmanager` helper `agent_identity(name)` that does a
  token-based `set()`/`reset()` so nested scopes restore the prior value.
- Re-export `current_agent_name` and `agent_identity` from
  `parrot/observability/__init__.py`.

**NOT in scope**: wrapping bot methods (TASK-1501), reading the var in the
client (TASK-1502), event-schema changes (TASK-1500), metric/span labels
(TASK-1503/1504).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/context.py` | CREATE | ContextVar + `agent_identity` context manager |
| `packages/ai-parrot/src/parrot/observability/__init__.py` | MODIFY | Export `current_agent_name`, `agent_identity` |
| `packages/ai-parrot/tests/unit/observability/test_context.py` | CREATE | Unit tests (set/reset, nesting, default) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# stdlib only — no third-party dependency
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/__init__.py
#   Existing module exporting ObservabilityConfig, setup_telemetry,
#   ensure_observability_bootstrapped, etc. (verified: __init__.py:34,70).
#   Append the two new names to its imports and __all__.
```

### Does NOT Exist
- ~~`parrot.observability.context`~~ — this task CREATES it. Confirm absence first
  (`grep -r "observability/context" packages/`).
- ~~any existing agent-identity ContextVar~~ — only unrelated `current_agent_id`
  params exist in `memory/unified/routing.py` and a `_current_agent_id` attr read
  in `tools/infographic_toolkit.py`; do not reuse those.

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/observability/context.py
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

current_agent_name: ContextVar[Optional[str]] = ContextVar(
    "parrot_current_agent_name", default=None
)


@contextmanager
def agent_identity(name: Optional[str]) -> Iterator[None]:
    """Bind ``name`` as the active agent for the duration of the block."""
    token = current_agent_name.set(name)
    try:
        yield
    finally:
        current_agent_name.reset(token)
```

### Key Constraints
- Pure stdlib; no import of the OTel SDK here (keeps the lightweight path clean).
- Token-based reset is mandatory — do NOT `set(None)` on exit, that loses the
  prior nested value.

---

## Acceptance Criteria

- [ ] `from parrot.observability.context import current_agent_name, agent_identity` works.
- [ ] `from parrot.observability import current_agent_name, agent_identity` works (re-export).
- [ ] Default value is `None` outside any block.
- [ ] Inside `agent_identity("a")` the var reads `"a"`; after the block it reverts.
- [ ] Nested `agent_identity("a")` → `agent_identity("b")` reads `"b"` inside, `"a"` after inner exits, `None` after outer.
- [ ] `ruff check` passes on the new module.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/observability/test_context.py
from parrot.observability.context import current_agent_name, agent_identity


def test_default_is_none():
    assert current_agent_name.get() is None


def test_set_and_reset():
    with agent_identity("porygon"):
        assert current_agent_name.get() == "porygon"
    assert current_agent_name.get() is None


def test_nested_restores_outer():
    with agent_identity("outer"):
        assert current_agent_name.get() == "outer"
        with agent_identity("inner"):
            assert current_agent_name.get() == "inner"
        assert current_agent_name.get() == "outer"
    assert current_agent_name.get() is None
```

---

## Agent Instructions

Standard SDD flow. Verify the contract, implement, run
`pytest packages/ai-parrot/tests/unit/observability/test_context.py -v`, move
this file to `sdd/tasks/completed/`, update the per-spec index to `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
