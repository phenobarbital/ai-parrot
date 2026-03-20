# TASK-011: Action Registry

**Feature**: AgentsFlow Persistency
**Spec**: `sdd/specs/agentsflow-persistency.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-009
**Assigned-to**: fdc88691-08f0-4537-968c-cbf4a40a46a6

---

## Context

> Actions are lifecycle hooks that execute before/after nodes (logging, notifications, webhooks, etc.). The spec defines 7 built-in actions that must be serializable and resolvable at load time. Implements Module 2 from the spec.

---

## Scope

> Implement `ACTION_REGISTRY` and all 7 built-in action classes.

- Implement `BaseAction` abstract base class with `async def __call__(node_name, payload, **ctx)`
- Implement `LogAction` — logs messages with template variables `{node_name}`, `{result}`, `{prompt}`
- Implement `NotifyAction` — sends notifications to slack/teams/email/log channels
- Implement `WebhookAction` — makes HTTP calls with templated body
- Implement `MetricAction` — emits metrics (prepare interface, actual backend is out of scope)
- Implement `SetContextAction` — extracts value from result and sets in shared context
- Implement `ValidateAction` — validates result against JSON schema
- Implement `TransformAction` — applies safe expression to transform result
- Create `ACTION_REGISTRY` dict mapping type strings to classes
- Support runtime registration of custom actions
- Write unit tests for all actions

**NOT in scope**:
- Actual Slack/Teams API integration (stub/log only)
- Metric backend implementation (interface only)
- Attaching actions to nodes (TASK-013)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/flow/actions.py` | CREATE | All action classes + registry |
| `parrot/bots/flow/__init__.py` | MODIFY | Export `ACTION_REGISTRY`, `BaseAction` |
| `tests/test_flow_actions.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/bots/flow/actions.py
from abc import ABC, abstractmethod
from typing import Any, Dict, Type

class BaseAction(ABC):
    """Base class for all flow lifecycle actions."""

    def __init__(self, config: "ActionDefinition"):
        self.config = config

    @abstractmethod
    async def __call__(
        self,
        node_name: str,
        payload: Any,
        **ctx: Any
    ) -> None:
        """Execute the action.

        Args:
            node_name: Name of the node triggering this action
            payload: Result/prompt depending on pre/post
            **ctx: Additional context (session_id, user_id, etc.)
        """


class LogAction(BaseAction):
    """Log a message with template variables."""

    async def __call__(self, node_name: str, payload: Any, **ctx) -> None:
        message = self.config.message.format(
            node_name=node_name,
            result=payload,
            prompt=payload,
            **ctx
        )
        logger = logging.getLogger(f"parrot.action.{node_name}")
        getattr(logger, self.config.level)(message)


# Registry with runtime registration support
ACTION_REGISTRY: Dict[str, Type[BaseAction]] = {}

def register_action(action_type: str):
    """Decorator to register an action class."""
    def decorator(cls: Type[BaseAction]) -> Type[BaseAction]:
        ACTION_REGISTRY[action_type] = cls
        return cls
    return decorator
```

### Key Constraints
- Actions must be async (`async def __call__`)
- Template variables: `{node_name}`, `{result}`, `{prompt}`, plus any ctx keys
- `ValidateAction` should use `jsonschema` library (already in project)
- `TransformAction` must use safe evaluation (no `eval()` — use simple attribute access)
- Registry must support runtime registration per spec Section 7

### References in Codebase
- `parrot/bots/flow/node.py` — `add_pre_action()` / `add_post_action()` interface
- `parrot/tools/abstract.py` — Pattern for ABC with `__call__`

---

## Acceptance Criteria

- [ ] `BaseAction` ABC defined with `async def __call__`
- [ ] All 7 action types implemented: log, notify, webhook, metric, set_context, validate, transform
- [ ] `ACTION_REGISTRY` contains all built-in actions
- [ ] `register_action()` decorator enables runtime registration
- [ ] `LogAction` formats template variables correctly
- [ ] `WebhookAction` makes HTTP calls with aiohttp
- [ ] `ValidateAction` validates against JSON schema
- [ ] All tests pass: `pytest tests/test_flow_actions.py -v`
- [ ] Import works: `from parrot.bots.flow import ACTION_REGISTRY, BaseAction`

---

## Test Specification

```python
# tests/test_flow_actions.py
import pytest
from parrot.bots.flow.actions import (
    ACTION_REGISTRY, BaseAction, register_action,
    LogAction, NotifyAction, WebhookAction, MetricAction,
    SetContextAction, ValidateAction, TransformAction
)
from parrot.bots.flow.definition import LogActionDef, WebhookActionDef, ValidateActionDef


class TestActionRegistry:
    def test_all_actions_registered(self):
        """All 7 built-in actions are in registry."""
        expected = {"log", "notify", "webhook", "metric", "set_context", "validate", "transform"}
        assert expected == set(ACTION_REGISTRY.keys())

    def test_runtime_registration(self):
        """Custom actions can be registered at runtime."""
        @register_action("custom")
        class CustomAction(BaseAction):
            async def __call__(self, node_name, payload, **ctx):
                pass

        assert "custom" in ACTION_REGISTRY
        del ACTION_REGISTRY["custom"]  # cleanup


class TestLogAction:
    @pytest.mark.asyncio
    async def test_template_formatting(self, caplog):
        """LogAction formats template variables."""
        config = LogActionDef(level="info", message="Node {node_name} got: {result}")
        action = LogAction(config)

        await action("test_node", "hello world")

        assert "Node test_node got: hello world" in caplog.text

    @pytest.mark.asyncio
    async def test_log_levels(self, caplog):
        """LogAction respects log level."""
        import logging
        caplog.set_level(logging.DEBUG)

        config = LogActionDef(level="debug", message="Debug message")
        action = LogAction(config)
        await action("node", "payload")

        assert "DEBUG" in caplog.text


class TestWebhookAction:
    @pytest.mark.asyncio
    async def test_makes_http_call(self, httpx_mock):
        """WebhookAction makes HTTP POST."""
        httpx_mock.add_response(url="https://example.com/hook", method="POST")

        config = WebhookActionDef(
            url="https://example.com/hook",
            body_template='{"node": "{node_name}"}'
        )
        action = WebhookAction(config)
        await action("test_node", "result")

        # Verify call was made (mock assertion)


class TestValidateAction:
    @pytest.mark.asyncio
    async def test_valid_data_passes(self):
        """ValidateAction passes valid data."""
        config = ValidateActionDef(
            schema={"type": "object", "required": ["decision"]},
            on_failure="raise"
        )
        action = ValidateAction(config)

        # Should not raise
        await action("node", {"decision": "approved"})

    @pytest.mark.asyncio
    async def test_invalid_data_raises(self):
        """ValidateAction raises on invalid data."""
        config = ValidateActionDef(
            schema={"type": "object", "required": ["decision"]},
            on_failure="raise"
        )
        action = ValidateAction(config)

        with pytest.raises(ValueError):
            await action("node", {"other": "field"})

    @pytest.mark.asyncio
    async def test_invalid_data_skip(self):
        """ValidateAction can skip on invalid data."""
        config = ValidateActionDef(
            schema={"type": "object", "required": ["decision"]},
            on_failure="skip"
        )
        action = ValidateAction(config)

        # Should not raise, just skip
        await action("node", {"other": "field"})


class TestSetContextAction:
    @pytest.mark.asyncio
    async def test_extracts_nested_value(self):
        """SetContextAction extracts value via dot notation."""
        from parrot.bots.flow.definition import SetContextActionDef

        config = SetContextActionDef(key="selected", value_from="result.decision.value")
        action = SetContextAction(config)

        ctx = {}
        result = {"decision": {"value": "approved"}}
        await action("node", result, shared_context=ctx)

        assert ctx["selected"] == "approved"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-persistency.spec.md` Section 2 (Data Models - actions)
2. **Check dependencies** — verify TASK-009 is complete (need action definition models)
3. **Read existing code** at `parrot/bots/flow/node.py` for action callback interface
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-011-action-registry.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: fdc88691-08f0-4537-968c-cbf4a40a46a6
**Date**: 2026-02-22
**Notes**: Implementation was already complete in `parrot/bots/flow/actions.py` (553 lines) with all 7 built-in actions, `BaseAction` ABC, `ACTION_REGISTRY`, `register_action()` decorator, and `create_action()` factory. Tests were already complete in `tests/test_flow_actions.py` (591 lines, 39 tests). All 39 tests pass.

**Deviations from spec**: none
