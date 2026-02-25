"""
Tests for flow action registry and built-in actions.

Tests the ACTION_REGISTRY, action registration, and all 7 built-in action types.
"""
import pytest
import logging
from unittest.mock import AsyncMock, patch, MagicMock

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
)
from parrot.bots.flow.definition import (
    LogActionDef,
    NotifyActionDef,
    WebhookActionDef,
    MetricActionDef,
    SetContextActionDef,
    ValidateActionDef,
    TransformActionDef,
)


class TestActionRegistry:
    """Tests for ACTION_REGISTRY and registration."""

    def test_all_actions_registered(self):
        """All 7 built-in actions are in registry."""
        expected = {"log", "notify", "webhook", "metric", "set_context", "validate", "transform"}
        assert expected == set(ACTION_REGISTRY.keys())

    def test_registry_returns_classes(self):
        """Registry contains action classes, not instances."""
        for action_type, action_class in ACTION_REGISTRY.items():
            assert isinstance(action_class, type)
            assert issubclass(action_class, BaseAction)

    def test_runtime_registration(self):
        """Custom actions can be registered at runtime."""
        @register_action("custom_test")
        class CustomTestAction(BaseAction):
            async def __call__(self, node_name, payload, **ctx):
                pass

        assert "custom_test" in ACTION_REGISTRY
        assert ACTION_REGISTRY["custom_test"] is CustomTestAction

        # Cleanup
        del ACTION_REGISTRY["custom_test"]

    def test_registration_overwrites(self):
        """Re-registering same type overwrites."""
        @register_action("overwrite_test")
        class First(BaseAction):
            async def __call__(self, node_name, payload, **ctx):
                return "first"

        @register_action("overwrite_test")
        class Second(BaseAction):
            async def __call__(self, node_name, payload, **ctx):
                return "second"

        assert ACTION_REGISTRY["overwrite_test"] is Second

        # Cleanup
        del ACTION_REGISTRY["overwrite_test"]


class TestCreateAction:
    """Tests for create_action factory."""

    def test_creates_log_action(self):
        """Factory creates LogAction from config."""
        config = LogActionDef(level="info", message="Test")
        action = create_action(config)
        assert isinstance(action, LogAction)

    def test_creates_webhook_action(self):
        """Factory creates WebhookAction from config."""
        config = WebhookActionDef(url="https://example.com/hook")
        action = create_action(config)
        assert isinstance(action, WebhookAction)

    def test_unknown_type_raises(self):
        """Factory raises for unknown action type."""
        # Create a mock config with unknown type
        class UnknownActionDef:
            type = "unknown_type"

        with pytest.raises(ValueError, match="Unknown action type"):
            create_action(UnknownActionDef())


class TestLogAction:
    """Tests for LogAction."""

    @pytest.mark.asyncio
    async def test_template_formatting(self, caplog):
        """LogAction formats template variables."""
        caplog.set_level(logging.INFO)

        config = LogActionDef(level="info", message="Node {node_name} got: {result}")
        action = LogAction(config)

        await action("test_node", "hello world")

        assert "Node test_node got: hello world" in caplog.text

    @pytest.mark.asyncio
    async def test_log_level_debug(self, caplog):
        """LogAction respects debug level."""
        caplog.set_level(logging.DEBUG)

        config = LogActionDef(level="debug", message="Debug message")
        action = LogAction(config)
        await action("node", "payload")

        assert "Debug message" in caplog.text

    @pytest.mark.asyncio
    async def test_log_level_warning(self, caplog):
        """LogAction respects warning level."""
        caplog.set_level(logging.WARNING)

        config = LogActionDef(level="warning", message="Warning message")
        action = LogAction(config)
        await action("node", "payload")

        assert "Warning message" in caplog.text

    @pytest.mark.asyncio
    async def test_log_level_error(self, caplog):
        """LogAction respects error level."""
        caplog.set_level(logging.ERROR)

        config = LogActionDef(level="error", message="Error message")
        action = LogAction(config)
        await action("node", "payload")

        assert "Error message" in caplog.text

    @pytest.mark.asyncio
    async def test_missing_template_variable(self, caplog):
        """LogAction handles missing template variables gracefully."""
        caplog.set_level(logging.INFO)

        config = LogActionDef(level="info", message="Value: {missing_var}")
        action = LogAction(config)

        # Should not raise, should use fallback formatting
        await action("node", "payload")

    @pytest.mark.asyncio
    async def test_context_variables(self, caplog):
        """LogAction can use context variables."""
        caplog.set_level(logging.INFO)

        config = LogActionDef(level="info", message="User: {user_id}")
        action = LogAction(config)

        await action("node", "payload", user_id="user123")

        assert "User: user123" in caplog.text


class TestNotifyAction:
    """Tests for NotifyAction."""

    @pytest.mark.asyncio
    async def test_notify_logs_message(self, caplog):
        """NotifyAction logs the notification."""
        caplog.set_level(logging.INFO)

        config = NotifyActionDef(channel="slack", message="Task completed", target="#alerts")
        action = NotifyAction(config)

        await action("test_node", "result")

        assert "SLACK" in caplog.text
        assert "#alerts" in caplog.text
        assert "Task completed" in caplog.text

    @pytest.mark.asyncio
    async def test_notify_channels(self, caplog):
        """NotifyAction handles different channels."""
        caplog.set_level(logging.INFO)

        for channel in ["slack", "teams", "email", "log"]:
            config = NotifyActionDef(channel=channel, message="Test")
            action = NotifyAction(config)
            await action("node", "result")

            assert channel.upper() in caplog.text

    @pytest.mark.asyncio
    async def test_notify_default_target(self, caplog):
        """NotifyAction uses default target when not specified."""
        caplog.set_level(logging.INFO)

        config = NotifyActionDef(channel="log", message="Test")
        action = NotifyAction(config)

        await action("node", "result")

        assert "default" in caplog.text


class TestWebhookAction:
    """Tests for WebhookAction."""

    @pytest.mark.asyncio
    async def test_makes_post_request(self):
        """WebhookAction makes POST request."""
        config = WebhookActionDef(
            url="https://example.com/hook",
            method="POST",
            body_template='{"node": "{node_name}"}'
        )
        action = WebhookAction(config)

        with patch("aiohttp.ClientSession") as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post = AsyncMock(return_value=mock_response)
            mock_session_instance = MagicMock()
            mock_session_instance.post = mock_post
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session.return_value = mock_session_instance

            await action("test_node", "result")

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "https://example.com/hook"

    @pytest.mark.asyncio
    async def test_makes_put_request(self):
        """WebhookAction makes PUT request when configured."""
        config = WebhookActionDef(
            url="https://example.com/hook",
            method="PUT"
        )
        action = WebhookAction(config)

        with patch("aiohttp.ClientSession") as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_put = AsyncMock(return_value=mock_response)
            mock_session_instance = MagicMock()
            mock_session_instance.put = mock_put
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session.return_value = mock_session_instance

            await action("test_node", "result")

            mock_put.assert_called_once()

    @pytest.mark.asyncio
    async def test_includes_headers(self):
        """WebhookAction includes custom headers."""
        config = WebhookActionDef(
            url="https://example.com/hook",
            headers={"Authorization": "Bearer token123"}
        )
        action = WebhookAction(config)

        with patch("aiohttp.ClientSession") as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post = AsyncMock(return_value=mock_response)
            mock_session_instance = MagicMock()
            mock_session_instance.post = mock_post
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session.return_value = mock_session_instance

            await action("test_node", "result")

            call_kwargs = mock_post.call_args[1]
            assert "Authorization" in call_kwargs["headers"]


class TestMetricAction:
    """Tests for MetricAction."""

    @pytest.mark.asyncio
    async def test_emits_metric(self, caplog):
        """MetricAction logs the metric."""
        caplog.set_level(logging.INFO)

        config = MetricActionDef(
            name="flow.node.completed",
            tags={"flow": "test_flow", "node": "{node_name}"},
            value=1.0
        )
        action = MetricAction(config)

        await action("my_node", "result")

        assert "METRIC" in caplog.text
        assert "flow.node.completed" in caplog.text
        assert "1.0" in caplog.text

    @pytest.mark.asyncio
    async def test_formats_tag_templates(self, caplog):
        """MetricAction formats tag templates."""
        caplog.set_level(logging.INFO)

        config = MetricActionDef(
            name="counter",
            tags={"node": "{node_name}"},
            value=5.0
        )
        action = MetricAction(config)

        await action("processed_node", "result")

        assert "processed_node" in caplog.text


class TestSetContextAction:
    """Tests for SetContextAction."""

    @pytest.mark.asyncio
    async def test_extracts_simple_value(self):
        """SetContextAction extracts simple value."""
        config = SetContextActionDef(key="decision", value_from="result.final")
        action = SetContextAction(config)

        ctx = {"shared_context": {}}
        await action("node", {"final": "approved"}, **ctx)

        assert ctx["shared_context"]["decision"] == "approved"

    @pytest.mark.asyncio
    async def test_extracts_nested_value(self):
        """SetContextAction extracts nested value."""
        config = SetContextActionDef(key="selected", value_from="result.decision.value")
        action = SetContextAction(config)

        ctx = {"shared_context": {}}
        result = {"decision": {"value": "option_a"}}
        await action("node", result, **ctx)

        assert ctx["shared_context"]["selected"] == "option_a"

    @pytest.mark.asyncio
    async def test_handles_missing_path(self, caplog):
        """SetContextAction handles missing path gracefully."""
        caplog.set_level(logging.DEBUG)

        config = SetContextActionDef(key="missing", value_from="result.nonexistent.path")
        action = SetContextAction(config)

        ctx = {"shared_context": {}}
        await action("node", {"other": "data"}, **ctx)

        # Should not raise, value should be None
        assert ctx["shared_context"]["missing"] is None

    @pytest.mark.asyncio
    async def test_warns_without_shared_context(self, caplog):
        """SetContextAction warns when no shared_context provided."""
        caplog.set_level(logging.WARNING)

        config = SetContextActionDef(key="test", value_from="result.value")
        action = SetContextAction(config)

        # No shared_context in ctx
        await action("node", {"value": "test"})

        assert "no shared_context" in caplog.text

    @pytest.mark.asyncio
    async def test_extracts_from_dict(self):
        """SetContextAction extracts from dict payload."""
        config = SetContextActionDef(key="name", value_from="result.user.name")
        action = SetContextAction(config)

        ctx = {"shared_context": {}}
        payload = {"user": {"name": "Alice", "id": 123}}
        await action("node", payload, **ctx)

        assert ctx["shared_context"]["name"] == "Alice"


class TestValidateAction:
    """Tests for ValidateAction."""

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
        """ValidateAction raises on invalid data with on_failure=raise."""
        config = ValidateActionDef(
            schema={"type": "object", "required": ["decision"]},
            on_failure="raise"
        )
        action = ValidateAction(config)

        with pytest.raises(ValueError, match="Validation failed"):
            await action("node", {"other": "field"})

    @pytest.mark.asyncio
    async def test_invalid_data_skip(self, caplog):
        """ValidateAction skips on invalid data with on_failure=skip."""
        caplog.set_level(logging.WARNING)

        config = ValidateActionDef(
            schema={"type": "object", "required": ["decision"]},
            on_failure="skip"
        )
        action = ValidateAction(config)

        # Should not raise
        await action("node", {"other": "field"})

        assert "skipping" in caplog.text

    @pytest.mark.asyncio
    async def test_invalid_data_fallback(self, caplog):
        """ValidateAction handles fallback mode."""
        caplog.set_level(logging.WARNING)

        config = ValidateActionDef(
            schema={"type": "object", "required": ["decision"]},
            on_failure="fallback",
            fallback_value={"decision": "default"}
        )
        action = ValidateAction(config)

        # Should not raise
        await action("node", {"other": "field"})

        assert "fallback" in caplog.text

    @pytest.mark.asyncio
    async def test_validates_string_type(self):
        """ValidateAction validates string type."""
        config = ValidateActionDef(
            schema={"type": "string"},
            on_failure="raise"
        )
        action = ValidateAction(config)

        # Valid string
        await action("node", "hello")

        # Invalid - not a string (dict)
        with pytest.raises(ValueError):
            await action("node", {"not": "string"})

    @pytest.mark.asyncio
    async def test_validates_array_type(self):
        """ValidateAction validates array type."""
        config = ValidateActionDef(
            schema={"type": "array", "items": {"type": "string"}},
            on_failure="raise"
        )
        action = ValidateAction(config)

        # Valid array
        await action("node", ["a", "b", "c"])


class TestTransformAction:
    """Tests for TransformAction."""

    @pytest.mark.asyncio
    async def test_calls_string_method(self):
        """TransformAction calls string method."""
        config = TransformActionDef(expression="result.lower()")
        action = TransformAction(config)

        ctx = {"shared_context": {}}
        result = await action("node", "HELLO WORLD", **ctx)

        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_calls_upper(self):
        """TransformAction calls upper()."""
        config = TransformActionDef(expression="result.upper()")
        action = TransformAction(config)

        ctx = {"shared_context": {}}
        result = await action("node", "hello", **ctx)

        assert result == "HELLO"

    @pytest.mark.asyncio
    async def test_calls_strip(self):
        """TransformAction calls strip()."""
        config = TransformActionDef(expression="result.strip()")
        action = TransformAction(config)

        ctx = {"shared_context": {}}
        result = await action("node", "  padded  ", **ctx)

        assert result == "padded"

    @pytest.mark.asyncio
    async def test_stores_in_context(self):
        """TransformAction stores result in shared context."""
        config = TransformActionDef(expression="result.lower()")
        action = TransformAction(config)

        ctx = {"shared_context": {}}
        await action("node", "TEST", **ctx)

        assert ctx["shared_context"]["_transformed_result"] == "test"

    @pytest.mark.asyncio
    async def test_handles_dict_access(self):
        """TransformAction handles dict value access."""
        config = TransformActionDef(expression="result.status")
        action = TransformAction(config)

        ctx = {"shared_context": {}}
        result = await action("node", {"status": "complete"}, **ctx)

        assert result == "complete"

    @pytest.mark.asyncio
    async def test_handles_none_gracefully(self):
        """TransformAction handles None input."""
        config = TransformActionDef(expression="result.value")
        action = TransformAction(config)

        ctx = {"shared_context": {}}
        result = await action("node", None, **ctx)

        assert result is None


class TestImports:
    """Test that imports work correctly."""

    def test_import_from_flow_module(self):
        """Can import actions from parrot.bots.flow."""
        from parrot.bots.flow import (
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
        )

        # Verify they are the expected types
        assert isinstance(ACTION_REGISTRY, dict)
        assert LogAction.__name__ == "LogAction"
        assert callable(register_action)
        assert callable(create_action)
