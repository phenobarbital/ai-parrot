"""Tests for parrot.bots.flow.actions — Action Registry & built-in actions.

TASK-011: All 7 action types + registry + runtime registration.
"""
import logging

import pytest

from parrot.bots.flow.actions import (
    ACTION_REGISTRY,
    BaseAction,
    register_action,
    create_action,
    LogAction,
    NotifyAction,
    WebhookAction,
    MetricAction,
    SetContextAction,
    ValidateAction,
    TransformAction,
    LogActionDef,
    MetricActionDef,
    NotifyActionDef,
    SetContextActionDef,
    TransformActionDef,
    ValidateActionDef,
    WebhookActionDef,
)


# ---------------------------------------------------------------------------
# Registry Tests
# ---------------------------------------------------------------------------

class TestActionRegistry:
    def test_all_builtin_registered(self):
        expected = {"log", "notify", "webhook", "metric", "set_context", "validate", "transform"}
        assert expected == set(ACTION_REGISTRY.keys())

    def test_registry_returns_classes(self):
        for name, cls in ACTION_REGISTRY.items():
            assert issubclass(cls, BaseAction)

    def test_runtime_registration(self):
        @register_action("_test_custom")
        class CustomAction(BaseAction):
            async def __call__(self, node_name, payload, **ctx):
                pass

        assert "_test_custom" in ACTION_REGISTRY
        del ACTION_REGISTRY["_test_custom"]

    def test_create_action_factory(self):
        config = LogActionDef(level="info", message="test")
        action = create_action(config)
        assert isinstance(action, LogAction)

    def test_create_action_unknown_type(self):
        with pytest.raises(ValueError, match="Unknown action type"):
            from pydantic import BaseModel

            class FakeConfig(BaseModel):
                type: str = "nonexistent"

            create_action(FakeConfig())


# ---------------------------------------------------------------------------
# LogAction Tests
# ---------------------------------------------------------------------------

class TestLogAction:
    @pytest.mark.asyncio
    async def test_template_formatting(self, caplog):
        caplog.set_level(logging.INFO)
        config = LogActionDef(level="info", message="Node {node_name} got: {result}")
        action = LogAction(config)
        await action("test_node", "hello world")
        assert "Node test_node got: hello world" in caplog.text

    @pytest.mark.asyncio
    async def test_debug_level(self, caplog):
        caplog.set_level(logging.DEBUG)
        config = LogActionDef(level="debug", message="Debug message")
        action = LogAction(config)
        await action("node", "payload")
        assert "Debug message" in caplog.text

    @pytest.mark.asyncio
    async def test_safe_format_missing_key(self, caplog):
        caplog.set_level(logging.INFO)
        config = LogActionDef(level="info", message="Missing {unknown_key} here")
        action = LogAction(config)
        await action("node", "payload")
        # Should not raise, message logged with partial substitution
        assert "node" in caplog.text or "Missing" in caplog.text


# ---------------------------------------------------------------------------
# NotifyAction Tests
# ---------------------------------------------------------------------------

class TestNotifyAction:
    @pytest.mark.asyncio
    async def test_log_channel(self, caplog):
        caplog.set_level(logging.INFO)
        config = NotifyActionDef(channel="log", message="Alert for {node_name}")
        action = NotifyAction(config)
        await action("my_node", "result")
        assert "Alert for my_node" in caplog.text

    @pytest.mark.asyncio
    async def test_slack_channel(self, caplog):
        caplog.set_level(logging.DEBUG)
        config = NotifyActionDef(channel="slack", message="test", target="#general")
        action = NotifyAction(config)
        await action("node", "payload")
        assert "Slack" in caplog.text


# ---------------------------------------------------------------------------
# MetricAction Tests
# ---------------------------------------------------------------------------

class TestMetricAction:
    @pytest.mark.asyncio
    async def test_emits_metric(self, caplog):
        caplog.set_level(logging.INFO)
        config = MetricActionDef(name="flow.completed", tags={"env": "test"}, value=1.0)
        action = MetricAction(config)
        await action("node", "payload")
        assert "METRIC" in caplog.text
        assert "flow.completed" in caplog.text


# ---------------------------------------------------------------------------
# SetContextAction Tests
# ---------------------------------------------------------------------------

class TestSetContextAction:
    @pytest.mark.asyncio
    async def test_extracts_dict_value(self):
        config = SetContextActionDef(key="selected", value_from="result.decision")
        action = SetContextAction(config)
        ctx = {}
        await action("node", {"decision": "approved"}, shared_context=ctx)
        assert ctx["selected"] == "approved"

    @pytest.mark.asyncio
    async def test_extracts_nested_value(self):
        config = SetContextActionDef(key="val", value_from="result.decision.value")
        action = SetContextAction(config)
        ctx = {}
        await action("node", {"decision": {"value": "deep"}}, shared_context=ctx)
        assert ctx["val"] == "deep"

    @pytest.mark.asyncio
    async def test_no_shared_context(self, caplog):
        caplog.set_level(logging.WARNING)
        config = SetContextActionDef(key="key", value_from="result.x")
        action = SetContextAction(config)
        await action("node", {"x": 1})
        assert "shared_context" in caplog.text

    @pytest.mark.asyncio
    async def test_missing_path_returns_none(self):
        config = SetContextActionDef(key="val", value_from="result.missing.deep")
        action = SetContextAction(config)
        ctx = {}
        await action("node", {"other": "data"}, shared_context=ctx)
        assert ctx["val"] is None


# ---------------------------------------------------------------------------
# ValidateAction Tests
# ---------------------------------------------------------------------------

class TestValidateAction:
    @pytest.mark.asyncio
    async def test_valid_data_passes(self):
        config = ValidateActionDef(
            schema={"type": "object", "required": ["decision"]},
            on_failure="raise",
        )
        action = ValidateAction(config)
        await action("node", {"decision": "approved"})

    @pytest.mark.asyncio
    async def test_invalid_data_raises(self):
        config = ValidateActionDef(
            schema={"type": "object", "required": ["decision"]},
            on_failure="raise",
        )
        action = ValidateAction(config)
        with pytest.raises(ValueError, match="Validation failed"):
            await action("node", {"other": "field"})

    @pytest.mark.asyncio
    async def test_invalid_data_skip(self, caplog):
        caplog.set_level(logging.WARNING)
        config = ValidateActionDef(
            schema={"type": "object", "required": ["decision"]},
            on_failure="skip",
        )
        action = ValidateAction(config)
        await action("node", {"other": "field"})
        assert "skipping" in caplog.text

    @pytest.mark.asyncio
    async def test_fallback_mode(self, caplog):
        caplog.set_level(logging.WARNING)
        config = ValidateActionDef(
            schema={"type": "object", "required": ["decision"]},
            on_failure="fallback",
            fallback_value="default",
        )
        action = ValidateAction(config)
        await action("node", {"other": "field"})
        assert "fallback" in caplog.text


# ---------------------------------------------------------------------------
# TransformAction Tests
# ---------------------------------------------------------------------------

class TestTransformAction:
    @pytest.mark.asyncio
    async def test_method_call(self):
        config = TransformActionDef(expression="result.upper()")
        action = TransformAction(config)
        result = await action("node", "hello")
        assert result == "HELLO"

    @pytest.mark.asyncio
    async def test_attribute_access(self):
        config = TransformActionDef(expression="result.value")
        action = TransformAction(config)

        class Obj:
            value = 42

        result = await action("node", Obj())
        assert result == 42

    @pytest.mark.asyncio
    async def test_stores_in_context(self):
        config = TransformActionDef(expression="result.lower()")
        action = TransformAction(config)
        ctx = {}
        await action("node", "HELLO", shared_context=ctx)
        assert ctx["_transformed_result"] == "hello"


# ---------------------------------------------------------------------------
# WebhookAction Tests (no real HTTP)
# ---------------------------------------------------------------------------

class TestWebhookAction:
    @pytest.mark.asyncio
    async def test_handles_connection_error(self, caplog):
        caplog.set_level(logging.WARNING)
        config = WebhookActionDef(url="http://localhost:99999/nonexistent")
        action = WebhookAction(config)
        await action("node", "payload")
        assert "WebhookAction failed" in caplog.text


# ---------------------------------------------------------------------------
# Import Tests
# ---------------------------------------------------------------------------

class TestImports:
    def test_import_from_package(self):
        from parrot.bots.flow import ACTION_REGISTRY as AR
        from parrot.bots.flow import BaseAction as BA

        assert AR is ACTION_REGISTRY
        assert BA is BaseAction
