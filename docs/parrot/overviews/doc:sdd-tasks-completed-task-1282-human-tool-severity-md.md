---
type: Wiki Overview
title: 'TASK-1282: HumanTool severity input field'
id: doc:sdd-tasks-completed-task-1282-human-tool-severity-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 module **C9**. Exposes `severity` to the LLM as a
---

# TASK-1282: HumanTool severity input field

**Feature**: FEAT-194 — HITL Multi-Tier Escalation Policy
**Spec**: `sdd/specs/hitl-escalation-tier.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1274
**Assigned-to**: unassigned

---

## Context

Implements §3 module **C9**. Exposes `severity` to the LLM as a
constrained input field on `ask_human`, and propagates it onto the
built `HumanInteraction`. The manager (TASK-1277) consumes it to pick
the starting tier.

---

## Scope

- Add `severity: str` field to `HumanToolInput` with allowed values
  `low | normal | high | critical` (use `Literal` for validation).
- Default value: `"normal"`.
- In `HumanTool._execute`, convert the string to `Severity` enum and
  pass to `HumanInteraction(..., severity=severity_enum)`.
- On invalid value, return an actionable error string to the LLM
  (consistent with existing structured-error return pattern in
  `HumanTool._execute`).
- Update the tool's `description` so the LLM learns when to use each
  level — be specific about "critical" (irreversible / compliance /
  time-critical).

**NOT in scope**: Wiring policy_id (already shipped). Manager
starting-tier logic (TASK-1277). Documentation update (TASK-1286).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/human/tool.py` | MODIFY | Add `severity` to `HumanToolInput`; convert + propagate in `_execute`; update tool description |
| `packages/ai-parrot/tests/human/test_tool_severity.py` | CREATE | Severity propagates; invalid value returns actionable error |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing in tool.py:
from .models import (
    ChoiceOption, HumanInteraction, InteractionResult,
    InteractionStatus, InteractionType,
)                                                          # tool.py:10-16
# New (from TASK-1274):
from .models import Severity
# Already there:
from pydantic import BaseModel, Field
from typing import Literal                                  # add if not present
```

### Existing Signatures to Use

```python
# parrot/human/tool.py:29-123 — HumanToolInput
class HumanToolInput(AbstractToolArgsSchema):
    question: str
    interaction_type: str = Field(default="free_text", ...)
    options: Optional[List[Union[str, Dict[str, Any]]]] = None
    context: Optional[str] = Field(default=None, max_length=280, ...)
    timeout: float = Field(default=7200.0, gt=0, le=_MAX_TIMEOUT_SECONDS, ...)
    form_schema: Optional[Dict[str, Any]] = None
    default_response: Any = None
    target_humans: Optional[List[str]] = None
    policy_id: Optional[str] = Field(default=None, ...)        # line 120-123

# parrot/human/tool.py:230-321 — _execute
async def _execute(self, **kwargs: Any) -> Any:
    # ...
    policy_id: Optional[str] = kwargs.get("policy_id")        # line 248
    # ...
    interaction = HumanInteraction(
        question=question,
        # ...
        policy_id=policy_id,                                  # line 298
    )
```

### Does NOT Exist

- ~~`HumanToolInput.severity`~~ — to be added.
- ~~Auto-severity inference from question content~~ — explicit value only.

---

## Implementation Notes

### Pattern to Follow

```python
class HumanToolInput(AbstractToolArgsSchema):
    # ... existing fields ...
    severity: Literal["low", "normal", "high", "critical"] = Field(
        default="normal",
        description=(
            "Optional declared criticality. The agent's escalation policy "
            "(if any) uses this to pick the STARTING tier — higher severity "
            "may skip lower tiers. Use 'high' for irreversible or "
            "compliance-sensitive actions; 'critical' only for "
            "production-down / safety / data-loss situations. Default 'normal'."
        ),
    )

# In _execute:
raw_severity = kwargs.get("severity", "normal")
try:
    severity_enum = Severity(raw_severity)
except ValueError:
    return f"HumanTool error: unknown severity '{raw_severity}'. Must be one of: low, normal, high, critical"
# ...
interaction = HumanInteraction(
    # ...
    policy_id=policy_id,
    severity=severity_enum,
)
```

### Key Constraints

- `Literal` constrains at schema level — Pydantic will reject invalid
  values before `_execute` is called. The defensive `try/except` is
  for cases where the LLM bypasses validation (rare with `args_schema`,
  but keeps the structured-error pattern consistent).
- Description language must teach the LLM when to use each level — not
  just enumerate values.

### References in Codebase

- `parrot/human/tool.py:120-123` (`policy_id` field shape — mirror it
  for `severity`).
- `parrot/human/tool.py:250-259` (structured-error return pattern for
  bad `interaction_type`).

---

## Acceptance Criteria

- [ ] `ask_human(question="...", severity="critical")` propagates
  `Severity.CRITICAL` onto the built `HumanInteraction`.
- [ ] Default `severity="normal"` when not provided.
- [ ] Invalid severity (e.g., `"urgent"`) returns an actionable error
  string starting with `HumanTool error: unknown severity`.
- [ ] Tool description includes guidance for each level.
- [ ] Existing tests on `HumanTool` (without severity) continue to pass.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/human/test_tool_severity.py -v`.

---

## Test Specification

```python
# tests/human/test_tool_severity.py
async def test_severity_critical_propagates(): ...
async def test_default_severity_is_normal(): ...
async def test_invalid_severity_returns_actionable_error(): ...
async def test_tool_description_mentions_severity_levels(): ...
```

---

## Agent Instructions

1. Read spec §3 C9.
2. Verify TASK-1274 completed.
3. Implement; mirror the `policy_id` field shape.
4. Test, lint.
5. Move to completed.

---

## Completion Note

Implemented 2026-05-22 by sdd-worker (FEAT-194).

- Added `severity: Literal["low", "normal", "high", "critical"]` field to `HumanToolInput` with detailed description teaching the LLM when to use each level.
- In `_execute`: reads `raw_severity`, validates with `Severity(raw_severity)`, returns `"HumanTool error: unknown severity '<val>'. Must be one of: low, normal, high, critical"` on ValueError.
- Passes `severity=severity_enum` to `HumanInteraction` constructor.
- 7 tests all pass: all 4 severity levels propagate, invalid value returns actionable error with value in message, schema has severity field, description mentions all 4 levels.
