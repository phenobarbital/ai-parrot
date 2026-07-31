---
type: Wiki Overview
title: 'TASK-1475: Data Models for Computer-Use'
id: doc:sdd-tasks-completed-task-1475-computer-use-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation task — all other FEAT-227 tasks depend on these data models.
relates_to:
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot_tools.computer.models
  rel: mentions
---

# TASK-1475: Data Models for Computer-Use

**Feature**: FEAT-227 — Computer-Use Agent
**Spec**: `sdd/specs/computer-use-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation task — all other FEAT-227 tasks depend on these data models.
Implements spec §2 Data Models. Pure Pydantic models with no external
dependencies beyond pydantic itself.

---

## Scope

- Create the `parrot_tools/computer/` package with `__init__.py`
- Implement `EnvState` — screenshot bytes + URL returned by every action
- Implement `ComputerUseConfig` — configuration for the ComputerUse tool type
- Implement `ComputerTask` — reusable sequence of NL instructions
- Implement `TaskResult` — result of a single task execution
- Implement `LoopResult` — result of a loop execution with stop_reason enum

**NOT in scope**: backend logic, toolkit logic, agent logic, Google client changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/computer/__init__.py` | CREATE | Package init with exports |
| `packages/ai-parrot-tools/src/parrot_tools/computer/models.py` | CREATE | All Pydantic models |
| `packages/ai-parrot-tools/tests/computer/__init__.py` | CREATE | Test package init |
| `packages/ai-parrot-tools/tests/computer/test_models.py` | CREATE | Model tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field  # verified: standard pydantic
from typing import Optional, Literal, Any  # verified: stdlib
```

### Existing Signatures to Use
```python
# No existing classes to extend — these are new standalone models.
```

### Does NOT Exist
- ~~`parrot_tools/computer/`~~ — directory does not exist yet (you create it)
- ~~`parrot.tools.computer`~~ — NOT in core package; must be in parrot_tools

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the pattern from parrot_tools/scraping/models.py for action/result models
from pydantic import BaseModel, Field
from typing import Optional, Literal

class EnvState(BaseModel):
    """State returned after each computer-use action."""
    screenshot: bytes
    url: str
```

### Key Constraints
- All models use Pydantic v2 BaseModel
- `LoopResult.stop_reason` must be a Literal type, not a free string
- `EnvState.screenshot` is raw PNG bytes (not base64 encoded)
- `ComputerTask.steps` is a list of natural-language strings, not structured actions

---

## Acceptance Criteria

- [ ] All 5 models defined: `EnvState`, `ComputerUseConfig`, `ComputerTask`, `TaskResult`, `LoopResult`
- [ ] Models validate correctly with valid and invalid input
- [ ] `LoopResult.stop_reason` restricted to: `"count"`, `"condition_met"`, `"max_reached"`, `"aborted"`, `"error"`
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/computer/test_models.py -v`
- [ ] Package importable: `from parrot_tools.computer.models import EnvState`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/computer/test_models.py
import pytest
from parrot_tools.computer.models import (
    EnvState, ComputerUseConfig, ComputerTask, TaskResult, LoopResult
)

class TestEnvState:
    def test_valid(self):
        state = EnvState(screenshot=b"\x89PNG...", url="https://example.com")
        assert state.screenshot == b"\x89PNG..."
        assert state.url == "https://example.com"

class TestComputerTask:
    def test_valid(self):
        task = ComputerTask(
            name="fill_form",
            description="Fill registration form",
            steps=["Click name field", "Type name", "Click submit"]
        )
        assert len(task.steps) == 3

class TestLoopResult:
    def test_stop_reason_enum(self):
        result = LoopResult(
            task_name="test", iterations_completed=3,
            stop_reason="count", results=[], errors=[]
        )
        assert result.stop_reason == "count"

    def test_invalid_stop_reason(self):
        with pytest.raises(Exception):
            LoopResult(
                task_name="test", iterations_completed=0,
                stop_reason="invalid_reason", results=[], errors=[]
            )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm parrot_tools/computer/ doesn't exist yet
4. **Implement** following the scope and models from spec §2
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-1475-computer-use-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

Implemented all 5 Pydantic v2 models: `EnvState`, `ComputerUseConfig`, `ComputerTask`, `TaskResult`, `LoopResult`.
Created the `parrot_tools/computer/` package with lazy-import `__init__.py` to avoid circular imports.
All 18 unit tests pass. Package importable as `from parrot_tools.computer.models import EnvState`.
