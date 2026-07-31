---
type: Wiki Overview
title: 'TASK-1633: TransitionAction Model & Config'
id: doc:sdd-tasks-completed-task-1633-transition-action-model-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task creates the data models that Module 1 (classification) and Module
  3
relates_to:
- concept: mod:parrot.core.hooks.models
  rel: mentions
---

# TASK-1633: TransitionAction Model & Config

**Feature**: FEAT-258 — JiraSpecialist Webhook Transition Detection
**Spec**: `sdd/specs/jiraspecialist-webhooks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task creates the data models that Module 1 (classification) and Module 3
(dispatch) both depend on. It implements Spec §2 "Data Models" — the
`TransitionActionType` enum, `TransitionAction` Pydantic model, and the new
`transition_actions` field on `JiraWebhookConfig`.

---

## Scope

- Add `TransitionActionType` str enum to `models.py` with values:
  `NOTIFY_CHANNEL`, `TRIGGER_AGENT`, `CALL_HANDLER`, `LOG`.
- Add `TransitionAction` Pydantic model to `models.py` with fields:
  `from_status`, `to_status`, `action_type`, `action_config`, `project_key`,
  `enabled`. Include `model_validator` that rejects both-wildcards.
- Add `transition_actions: List[TransitionAction]` field to
  `JiraWebhookConfig` with `default_factory=list`.

**NOT in scope**: Classification changes (TASK-1634), dispatch logic (TASK-1635),
or tests (TASK-1636).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/hooks/models.py` | MODIFY | Add `TransitionActionType`, `TransitionAction`, update `JiraWebhookConfig` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already imported in models.py (verified: models.py:1-6)
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/core/hooks/models.py:110-118
class JiraWebhookConfig(BaseModel):
    name: str = "jira_webhook"          # line 112
    enabled: bool = True                # line 113
    url: str = "/api/v1/hooks/jira"     # line 114
    secret_token: Optional[str] = None  # line 115
    target_type: str = "agent"          # line 116
    target_id: str = ""                 # line 117
    metadata: Dict[str, Any] = Field(default_factory=dict)  # line 118
```

### Does NOT Exist

- ~~`parrot.core.hooks.models.TransitionAction`~~ — does not exist yet (this task creates it)
- ~~`parrot.core.hooks.models.TransitionActionType`~~ — does not exist yet
- ~~`JiraWebhookConfig.transition_actions`~~ — field does not exist yet

---

## Implementation Notes

### Pattern to Follow

Place the new models **before** `JiraWebhookConfig` in the file (around line 108)
so the config class can reference `TransitionAction` without a forward reference.

```python
# Insert before JiraWebhookConfig (line 110)

class TransitionActionType(str, Enum):
    """Supported action types for transition handlers."""
    NOTIFY_CHANNEL = "notify_channel"
    TRIGGER_AGENT = "trigger_agent"
    CALL_HANDLER = "call_handler"
    LOG = "log"


class TransitionAction(BaseModel):
    """A single transition-to-action mapping."""
    from_status: str = Field(
        default="*",
        description="Source status to match (case-insensitive), or '*' for any",
    )
    to_status: str = Field(
        ...,
        description="Target status to match (case-insensitive), or '*' for any",
    )
    action_type: TransitionActionType
    action_config: Dict[str, Any] = Field(default_factory=dict)
    project_key: Optional[str] = Field(default=None)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_not_both_wildcards(self):
        if self.from_status == "*" and self.to_status == "*":
            raise ValueError(
                "At least one of from_status or to_status must be non-wildcard"
            )
        return self
```

Then update `JiraWebhookConfig` to add:
```python
    transition_actions: List[TransitionAction] = Field(default_factory=list)
```

### Key Constraints

- Use `str, Enum` for `TransitionActionType` (same pattern as `HookType` at line 9).
- `model_validator(mode="after")` is used elsewhere in the codebase (models.py already
  imports `model_validator` at line 6).
- Keep `default_factory=list` for `transition_actions` to ensure backward compat
  (existing code that creates `JiraWebhookConfig()` without this field must still work).

### References in Codebase

- `packages/ai-parrot/src/parrot/core/hooks/models.py:9-28` — `HookType` enum pattern
- `packages/ai-parrot/src/parrot/core/hooks/models.py:31-43` — `HookEvent` Pydantic model pattern

---

## Acceptance Criteria

- [ ] `TransitionActionType` enum has 4 values: `NOTIFY_CHANNEL`, `TRIGGER_AGENT`, `CALL_HANDLER`, `LOG`
- [ ] `TransitionAction` model validates: `from_status="*", to_status="*"` raises `ValidationError`
- [ ] `TransitionAction` model validates: `from_status="*", to_status="Done"` succeeds
- [ ] `TransitionAction` model validates: `from_status="Open", to_status="*"` succeeds
- [ ] `JiraWebhookConfig()` still works without `transition_actions` (backward compat)
- [ ] `JiraWebhookConfig(transition_actions=[...])` populates the list
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/core/hooks/models.py`

---

## Test Specification

```python
# tests/core/hooks/test_transition_action_model.py
import pytest
from pydantic import ValidationError
from parrot.core.hooks.models import TransitionAction, TransitionActionType, JiraWebhookConfig


class TestTransitionActionType:
    def test_enum_values(self):
        assert TransitionActionType.NOTIFY_CHANNEL == "notify_channel"
        assert TransitionActionType.TRIGGER_AGENT == "trigger_agent"
        assert TransitionActionType.CALL_HANDLER == "call_handler"
        assert TransitionActionType.LOG == "log"


class TestTransitionAction:
    def test_both_wildcards_rejected(self):
        with pytest.raises(ValidationError, match="non-wildcard"):
            TransitionAction(
                from_status="*",
                to_status="*",
                action_type=TransitionActionType.LOG,
            )

    def test_single_wildcard_from_ok(self):
        action = TransitionAction(
            from_status="*",
            to_status="Done",
            action_type=TransitionActionType.NOTIFY_CHANNEL,
        )
        assert action.from_status == "*"
        assert action.to_status == "Done"

    def test_single_wildcard_to_ok(self):
        action = TransitionAction(
            from_status="Open",
            to_status="*",
            action_type=TransitionActionType.LOG,
        )
        assert action.from_status == "Open"

    def test_defaults(self):
        action = TransitionAction(
            to_status="Done",
            action_type=TransitionActionType.LOG,
        )
        assert action.from_status == "*"
        assert action.project_key is None
        assert action.enabled is True
        assert action.action_config == {}


class TestJiraWebhookConfigTransitionActions:
    def test_default_empty_list(self):
        config = JiraWebhookConfig()
        assert config.transition_actions == []

    def test_with_actions(self):
        config = JiraWebhookConfig(
            transition_actions=[
                TransitionAction(
                    to_status="In Progress",
                    action_type=TransitionActionType.NOTIFY_CHANNEL,
                    action_config={"channel_id": "123"},
                )
            ]
        )
        assert len(config.transition_actions) == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jiraspecialist-webhooks.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `JiraWebhookConfig` signature at `models.py:110-118`
4. **Update status** in per-spec index → `"in-progress"`
5. **Implement** the models and config field
6. **Run tests**: `pytest tests/core/hooks/test_transition_action_model.py -v`
7. **Verify** all acceptance criteria
8. **Move this file** to `sdd/tasks/completed/`
9. **Update per-spec index** → `"done"`

---

## Completion Note

Implemented by sdd-worker on 2026-06-24.

Added `TransitionActionType` (str enum, 4 values) and `TransitionAction`
(Pydantic model with `model_validator` rejecting both-wildcard configurations)
to `packages/ai-parrot/src/parrot/core/hooks/models.py`. Added
`transition_actions: List[TransitionAction]` field to `JiraWebhookConfig`
with `default_factory=list` for backward compatibility. All acceptance
criteria verified: enum values correct, both-wildcard validation raises
`ValidationError`, single-wildcard passes, `JiraWebhookConfig()` still works
without transition_actions, linting clean.
