"""Unit tests for Slack interactive Block Kit handler."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web

from parrot.integrations.slack.interactive import (
    ActionRegistry,
    SlackInteractiveHandler,
    build_feedback_blocks,
    build_clear_button,
)


@pytest.fixture
def mock_wrapper():
    """Create a mock SlackAgentWrapper."""
    wrapper = MagicMock()
    wrapper.conversations = {}
    wrapper.config = MagicMock()
    wrapper.config.bot_token = "xoxb-test-token"
    return wrapper


class TestActionRegistry:
    """Tests for ActionRegistry."""

    def test_exact_match(self):
        """Exact action_id match returns handler."""
        registry = ActionRegistry()
        handler = MagicMock()
        registry.register("my_action", handler)

        assert registry.get_handler("my_action") is handler
        assert registry.get_handler("other") is None

    def test_prefix_match(self):
        """Prefix matching works for action_id patterns."""
        registry = ActionRegistry()
        handler = MagicMock()
        registry.register_prefix("feedback_", handler)

        assert registry.get_handler("feedback_positive") is handler
        assert registry.get_handler("feedback_negative") is handler
        assert registry.get_handler("other_action") is None

    def test_exact_takes_precedence(self):
        """Exact match takes precedence over prefix."""
        registry = ActionRegistry()
        exact = MagicMock()
        prefix = MagicMock()
        registry.register("feedback_special", exact)
        registry.register_prefix("feedback_", prefix)

        assert registry.get_handler("feedback_special") is exact
        assert registry.get_handler("feedback_other") is prefix

    def test_unregister(self):
        """Can unregister handlers."""
        registry = ActionRegistry()
        handler = MagicMock()
        registry.register("my_action", handler)
        assert registry.get_handler("my_action") is handler

        registry.unregister("my_action")
        assert registry.get_handler("my_action") is None

    def test_unregister_prefix(self):
        """Can unregister prefix handlers."""
        registry = ActionRegistry()
        handler = MagicMock()
        registry.register_prefix("feedback_", handler)
        assert registry.get_handler("feedback_positive") is handler

        registry.unregister_prefix("feedback_")
        assert registry.get_handler("feedback_positive") is None

    def test_multiple_prefix_handlers(self):
        """Multiple prefix handlers work correctly."""
        registry = ActionRegistry()
        feedback_handler = MagicMock()
        menu_handler = MagicMock()
        registry.register_prefix("feedback_", feedback_handler)
        registry.register_prefix("menu_", menu_handler)

        assert registry.get_handler("feedback_positive") is feedback_handler
        assert registry.get_handler("menu_select") is menu_handler
        assert registry.get_handler("other") is None


class TestSlackInteractiveHandler:
    """Tests for SlackInteractiveHandler."""

    def test_default_handlers_registered(self, mock_wrapper):
        """Default handlers are registered on init."""
        handler = SlackInteractiveHandler(mock_wrapper)

        assert handler.action_registry.get_handler("feedback_positive") is not None
        assert handler.action_registry.get_handler("feedback_negative") is not None
        assert handler.action_registry.get_handler("clear_conversation") is not None

    @pytest.mark.asyncio
    async def test_routes_block_actions(self, mock_wrapper):
        """block_actions payload routed to registered handler."""
        handler = SlackInteractiveHandler(mock_wrapper)
        custom_handler = AsyncMock()
        handler.action_registry.register("my_btn", custom_handler)

        payload = {
            "type": "block_actions",
            "actions": [{"action_id": "my_btn", "value": "clicked"}],
            "user": {"id": "U123"},
        }

        await handler.handle(payload)

        custom_handler.assert_called_once()
        call_args = custom_handler.call_args
        assert call_args[0][0] == payload
        assert call_args[0][1]["action_id"] == "my_btn"

    @pytest.mark.asyncio
    async def test_routes_multiple_actions(self, mock_wrapper):
        """Multiple actions in block_actions are all handled."""
        handler = SlackInteractiveHandler(mock_wrapper)
        handler1 = AsyncMock()
        handler2 = AsyncMock()
        handler.action_registry.register("btn1", handler1)
        handler.action_registry.register("btn2", handler2)

        payload = {
            "type": "block_actions",
            "actions": [
                {"action_id": "btn1", "value": "1"},
                {"action_id": "btn2", "value": "2"},
            ],
            "user": {"id": "U123"},
        }

        await handler.handle(payload)

        handler1.assert_called_once()
        handler2.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_view_submission(self, mock_wrapper):
        """view_submission payload routed to registered handler."""
        handler = SlackInteractiveHandler(mock_wrapper)
        modal_handler = AsyncMock(return_value=None)
        handler.action_registry.register("modal:my_form", modal_handler)

        payload = {
            "type": "view_submission",
            "view": {
                "callback_id": "my_form",
                "state": {"values": {}},
            },
            "user": {"id": "U123"},
        }

        await handler.handle(payload)

        modal_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_shortcut(self, mock_wrapper):
        """shortcut payload routed to registered handler."""
        handler = SlackInteractiveHandler(mock_wrapper)
        shortcut_handler = AsyncMock()
        handler.action_registry.register("shortcut:my_shortcut", shortcut_handler)

        payload = {
            "type": "shortcut",
            "callback_id": "my_shortcut",
            "user": {"id": "U123"},
        }

        await handler.handle(payload)

        shortcut_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_web_request(self, mock_wrapper):
        """Handles aiohttp web request with form-encoded payload."""
        handler = SlackInteractiveHandler(mock_wrapper)
        custom_handler = AsyncMock()
        handler.action_registry.register("my_btn", custom_handler)

        payload = {
            "type": "block_actions",
            "actions": [{"action_id": "my_btn", "value": "clicked"}],
            "user": {"id": "U123"},
        }

        request = MagicMock(spec=web.Request)
        request.post = AsyncMock(return_value={"payload": json.dumps(payload)})

        response = await handler.handle(request)

        assert response.status == 200
        custom_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_invalid_json(self, mock_wrapper):
        """Handles invalid JSON in web request gracefully."""
        handler = SlackInteractiveHandler(mock_wrapper)

        request = MagicMock(spec=web.Request)
        request.post = AsyncMock(return_value={"payload": "invalid json"})

        response = await handler.handle(request)

        assert response.status == 400

    @pytest.mark.asyncio
    async def test_unhandled_payload_type(self, mock_wrapper):
        """Unhandled payload types don't error."""
        handler = SlackInteractiveHandler(mock_wrapper)

        payload = {
            "type": "unknown_type",
        }

        # Should not raise
        await handler.handle(payload)


class TestFeedbackHandler:
    """Tests for built-in feedback handler."""

    @pytest.mark.asyncio
    async def test_feedback_sends_thanks(self, mock_wrapper):
        """Feedback handler sends ephemeral thanks."""
        handler = SlackInteractiveHandler(mock_wrapper)

        with patch('parrot.integrations.slack.interactive.ClientSession') as MockSession:
            mock_session = MagicMock()
            mock_post = AsyncMock()
            mock_session.post = mock_post
            mock_context = MagicMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_session)
            mock_context.__aexit__ = AsyncMock()
            MockSession.return_value = mock_context

            payload = {
                "type": "block_actions",
                "user": {"id": "U123"},
                "response_url": "https://hooks.slack.com/xxx",
                "actions": [{"action_id": "feedback_positive", "value": "msg_123"}],
            }

            await handler.handle(payload)

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "hooks.slack.com" in call_args[0][0]
            call_json = call_args[1]["json"]
            assert "Thanks" in call_json["text"]
            assert call_json["response_type"] == "ephemeral"

    @pytest.mark.asyncio
    async def test_feedback_positive_shows_checkmark(self, mock_wrapper):
        """Positive feedback shows checkmark emoji."""
        handler = SlackInteractiveHandler(mock_wrapper)

        with patch('parrot.integrations.slack.interactive.ClientSession') as MockSession:
            mock_session = MagicMock()
            mock_post = AsyncMock()
            mock_session.post = mock_post
            mock_context = MagicMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_session)
            mock_context.__aexit__ = AsyncMock()
            MockSession.return_value = mock_context

            payload = {
                "type": "block_actions",
                "user": {"id": "U123"},
                "response_url": "https://hooks.slack.com/xxx",
                "actions": [{"action_id": "feedback_positive", "value": "msg_123"}],
            }

            await handler.handle(payload)

            call_json = mock_post.call_args[1]["json"]
            assert ":white_check_mark:" in call_json["text"]

    @pytest.mark.asyncio
    async def test_feedback_negative_shows_x(self, mock_wrapper):
        """Negative feedback shows X emoji."""
        handler = SlackInteractiveHandler(mock_wrapper)

        with patch('parrot.integrations.slack.interactive.ClientSession') as MockSession:
            mock_session = MagicMock()
            mock_post = AsyncMock()
            mock_session.post = mock_post
            mock_context = MagicMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_session)
            mock_context.__aexit__ = AsyncMock()
            MockSession.return_value = mock_context

            payload = {
                "type": "block_actions",
                "user": {"id": "U123"},
                "response_url": "https://hooks.slack.com/xxx",
                "actions": [{"action_id": "feedback_negative", "value": "msg_123"}],
            }

            await handler.handle(payload)

            call_json = mock_post.call_args[1]["json"]
            assert ":x:" in call_json["text"]


class TestClearHandler:
    """Tests for built-in clear conversation handler."""

    @pytest.mark.asyncio
    async def test_clear_removes_conversation(self, mock_wrapper):
        """Clear handler removes conversation from memory."""
        mock_wrapper.conversations = {"C123:U456": MagicMock()}
        handler = SlackInteractiveHandler(mock_wrapper)

        with patch('parrot.integrations.slack.interactive.ClientSession') as MockSession:
            mock_session = MagicMock()
            mock_post = AsyncMock()
            mock_session.post = mock_post
            mock_context = MagicMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_session)
            mock_context.__aexit__ = AsyncMock()
            MockSession.return_value = mock_context

            payload = {
                "type": "block_actions",
                "user": {"id": "U456"},
                "channel": {"id": "C123"},
                "response_url": "https://hooks.slack.com/xxx",
                "actions": [{"action_id": "clear_conversation", "value": ""}],
            }

            await handler.handle(payload)

            assert "C123:U456" not in mock_wrapper.conversations

    @pytest.mark.asyncio
    async def test_clear_sends_confirmation(self, mock_wrapper):
        """Clear handler sends confirmation message."""
        handler = SlackInteractiveHandler(mock_wrapper)

        with patch('parrot.integrations.slack.interactive.ClientSession') as MockSession:
            mock_session = MagicMock()
            mock_post = AsyncMock()
            mock_session.post = mock_post
            mock_context = MagicMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_session)
            mock_context.__aexit__ = AsyncMock()
            MockSession.return_value = mock_context

            payload = {
                "type": "block_actions",
                "user": {"id": "U456"},
                "channel": {"id": "C123"},
                "response_url": "https://hooks.slack.com/xxx",
                "actions": [{"action_id": "clear_conversation", "value": ""}],
            }

            await handler.handle(payload)

            call_json = mock_post.call_args[1]["json"]
            assert "cleared" in call_json["text"].lower()


class TestBuildFeedbackBlocks:
    """Tests for build_feedback_blocks utility."""

    def test_returns_valid_blocks(self):
        """Produces valid Block Kit JSON structure."""
        blocks = build_feedback_blocks("msg_123")

        assert len(blocks) == 2
        assert blocks[0]["type"] == "divider"
        assert blocks[1]["type"] == "actions"
        assert len(blocks[1]["elements"]) == 2

    def test_buttons_have_correct_action_ids(self):
        """Buttons have feedback_positive and feedback_negative action_ids."""
        blocks = build_feedback_blocks()
        action_ids = [e["action_id"] for e in blocks[1]["elements"]]

        assert "feedback_positive" in action_ids
        assert "feedback_negative" in action_ids

    def test_positive_button_is_primary(self):
        """Positive button has primary style."""
        blocks = build_feedback_blocks()
        positive_btn = next(
            e for e in blocks[1]["elements"]
            if e["action_id"] == "feedback_positive"
        )

        assert positive_btn["style"] == "primary"

    def test_message_id_in_value(self):
        """Message ID is stored in button values."""
        blocks = build_feedback_blocks("test_msg_123")

        for element in blocks[1]["elements"]:
            assert element["value"] == "test_msg_123"

    def test_empty_message_id(self):
        """Works with empty message ID."""
        blocks = build_feedback_blocks("")

        assert len(blocks) == 2
        for element in blocks[1]["elements"]:
            assert element["value"] == ""


class TestBuildClearButton:
    """Tests for build_clear_button utility."""

    def test_returns_button_element(self):
        """Returns a valid button element."""
        button = build_clear_button()

        assert button["type"] == "button"
        assert button["action_id"] == "clear_conversation"

    def test_has_danger_style(self):
        """Button has danger style."""
        button = build_clear_button()

        assert button["style"] == "danger"

    def test_has_confirmation_dialog(self):
        """Button has confirmation dialog."""
        button = build_clear_button()

        assert "confirm" in button
        assert button["confirm"]["title"]["type"] == "plain_text"


class TestBuildFormBlocks:
    """Tests for _build_form_blocks method."""

    def test_text_field(self, mock_wrapper):
        """Text field generates correct block."""
        handler = SlackInteractiveHandler(mock_wrapper)
        fields = [
            {"id": "name", "label": "Your Name", "type": "text"}
        ]

        blocks = handler._build_form_blocks(fields)

        assert len(blocks) == 1
        assert blocks[0]["type"] == "input"
        assert blocks[0]["block_id"] == "name"
        assert blocks[0]["element"]["type"] == "plain_text_input"

    def test_select_field(self, mock_wrapper):
        """Select field generates correct block."""
        handler = SlackInteractiveHandler(mock_wrapper)
        fields = [
            {
                "id": "color",
                "label": "Favorite Color",
                "type": "select",
                "options": [
                    {"label": "Red", "value": "red"},
                    {"label": "Blue", "value": "blue"},
                ],
            }
        ]

        blocks = handler._build_form_blocks(fields)

        assert len(blocks) == 1
        assert blocks[0]["element"]["type"] == "static_select"
        assert len(blocks[0]["element"]["options"]) == 2

    def test_date_field(self, mock_wrapper):
        """Date field generates correct block."""
        handler = SlackInteractiveHandler(mock_wrapper)
        fields = [
            {"id": "dob", "label": "Date of Birth", "type": "date"}
        ]

        blocks = handler._build_form_blocks(fields)

        assert len(blocks) == 1
        assert blocks[0]["element"]["type"] == "datepicker"

    def test_multiline_text_field(self, mock_wrapper):
        """Multiline text field sets multiline flag."""
        handler = SlackInteractiveHandler(mock_wrapper)
        fields = [
            {"id": "bio", "label": "Bio", "type": "text", "multiline": True}
        ]

        blocks = handler._build_form_blocks(fields)

        assert blocks[0]["element"]["multiline"] is True

    def test_optional_field(self, mock_wrapper):
        """Optional field sets optional flag."""
        handler = SlackInteractiveHandler(mock_wrapper)
        fields = [
            {"id": "nickname", "label": "Nickname", "type": "text", "optional": True}
        ]

        blocks = handler._build_form_blocks(fields)

        assert blocks[0]["optional"] is True


class TestExtractFormValues:
    """Tests for extract_form_values method."""

    def test_extracts_text_input(self, mock_wrapper):
        """Extracts text input value."""
        handler = SlackInteractiveHandler(mock_wrapper)
        payload = {
            "view": {
                "state": {
                    "values": {
                        "name": {
                            "name": {
                                "type": "plain_text_input",
                                "value": "John Doe",
                            }
                        }
                    }
                }
            }
        }

        values = handler.extract_form_values(payload)

        assert values["name"] == "John Doe"

    def test_extracts_select_value(self, mock_wrapper):
        """Extracts select value."""
        handler = SlackInteractiveHandler(mock_wrapper)
        payload = {
            "view": {
                "state": {
                    "values": {
                        "color": {
                            "color": {
                                "type": "static_select",
                                "selected_option": {"value": "blue"},
                            }
                        }
                    }
                }
            }
        }

        values = handler.extract_form_values(payload)

        assert values["color"] == "blue"

    def test_extracts_date_value(self, mock_wrapper):
        """Extracts date value."""
        handler = SlackInteractiveHandler(mock_wrapper)
        payload = {
            "view": {
                "state": {
                    "values": {
                        "dob": {
                            "dob": {
                                "type": "datepicker",
                                "selected_date": "2024-01-15",
                            }
                        }
                    }
                }
            }
        }

        values = handler.extract_form_values(payload)

        assert values["dob"] == "2024-01-15"

    def test_extracts_multi_select_values(self, mock_wrapper):
        """Extracts multi-select values as list."""
        handler = SlackInteractiveHandler(mock_wrapper)
        payload = {
            "view": {
                "state": {
                    "values": {
                        "colors": {
                            "colors": {
                                "type": "multi_static_select",
                                "selected_options": [
                                    {"value": "red"},
                                    {"value": "blue"},
                                ],
                            }
                        }
                    }
                }
            }
        }

        values = handler.extract_form_values(payload)

        assert values["colors"] == ["red", "blue"]


class TestOpenModal:
    """Tests for open_modal method."""

    @pytest.mark.asyncio
    async def test_opens_modal_successfully(self, mock_wrapper):
        """Opens modal with correct API call."""
        handler = SlackInteractiveHandler(mock_wrapper)

        with patch('parrot.integrations.slack.interactive.ClientSession') as MockSession:
            mock_response = MagicMock()
            mock_response.json = AsyncMock(return_value={"ok": True})
            mock_session = MagicMock()
            mock_post = MagicMock()
            mock_post.__aenter__ = AsyncMock(return_value=mock_response)
            mock_post.__aexit__ = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_post)
            mock_context = MagicMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_session)
            mock_context.__aexit__ = AsyncMock()
            MockSession.return_value = mock_context

            form_def = {
                "id": "my_form",
                "title": "Test Form",
                "fields": [
                    {"id": "name", "label": "Name", "type": "text"},
                ],
            }

            result = await handler.open_modal("trigger_123", form_def)

            assert result is True
            mock_session.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_false_on_api_error(self, mock_wrapper):
        """Returns False when API returns error."""
        handler = SlackInteractiveHandler(mock_wrapper)

        with patch('parrot.integrations.slack.interactive.ClientSession') as MockSession:
            mock_response = MagicMock()
            mock_response.json = AsyncMock(return_value={"ok": False, "error": "trigger_expired"})
            mock_session = MagicMock()
            mock_post = MagicMock()
            mock_post.__aenter__ = AsyncMock(return_value=mock_response)
            mock_post.__aexit__ = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_post)
            mock_context = MagicMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_session)
            mock_context.__aexit__ = AsyncMock()
            MockSession.return_value = mock_context

            result = await handler.open_modal("expired_trigger", {"id": "form", "title": "Form"})

            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_without_token(self, mock_wrapper):
        """Returns False when bot_token is not configured."""
        mock_wrapper.config.bot_token = None
        handler = SlackInteractiveHandler(mock_wrapper)

        result = await handler.open_modal("trigger_123", {"id": "form", "title": "Form"})

        assert result is False


class TestImports:
    """Tests for module imports."""

    def test_import_from_interactive_module(self):
        """Can import directly from interactive module."""
        from parrot.integrations.slack.interactive import (
            ActionRegistry,
            SlackInteractiveHandler,
            build_feedback_blocks,
            build_clear_button,
        )

        assert ActionRegistry is not None
        assert SlackInteractiveHandler is not None
        assert build_feedback_blocks is not None
        assert build_clear_button is not None

    def test_import_from_slack_package(self):
        """Can import from slack package."""
        from parrot.integrations.slack import (
            ActionRegistry,
            SlackInteractiveHandler,
            build_feedback_blocks,
            build_clear_button,
        )

        assert ActionRegistry is not None
        assert SlackInteractiveHandler is not None
        assert build_feedback_blocks is not None
        assert build_clear_button is not None
