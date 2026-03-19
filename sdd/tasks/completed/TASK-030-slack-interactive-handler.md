# TASK-030: Slack Block Kit Interactive Handler

**Feature**: Slack Wrapper Integration Enhancements
**Spec**: `sdd/specs/slack-wrapper-integration.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-026
**Assigned-to**: claude-session

---

## Context

> This task enables interactive Block Kit components (buttons, menus, modals).
> Reference: Spec Section 7 (Block Kit Interactivo) and Section 3 (Module 7).

Block Kit is Slack's UI framework (equivalent to Adaptive Cards in MS Teams). This task adds support for interactive elements: buttons, select menus, date pickers, and modals.

---

## Scope

- Create `parrot/integrations/slack/interactive.py` module
- Implement `ActionRegistry` for handler registration
- Implement `SlackInteractiveHandler` class
- Add feedback button handlers (thumbs up/down)
- Add modal opening and submission handling
- Register interactive route in wrapper
- Add `build_feedback_blocks()` utility

**NOT in scope**:
- Form orchestrator (complex multi-step forms)
- Workflow builder integration
- Home tab (App Home)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/slack/interactive.py` | CREATE | Interactive handler module |
| `parrot/integrations/slack/wrapper.py` | MODIFY | Register interactive route |
| `tests/unit/test_slack_interactive.py` | CREATE | Unit tests |
| `parrot/integrations/slack/__init__.py` | MODIFY | Export classes |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/integrations/slack/interactive.py
"""Interactive Block Kit handler for Slack integration."""
import json
import logging
from typing import Callable, Dict, Optional, TYPE_CHECKING
from aiohttp import web, ClientSession

if TYPE_CHECKING:
    from .wrapper import SlackAgentWrapper

logger = logging.getLogger("SlackInteractive")


class ActionRegistry:
    """Registry for Block Kit action handlers. Maps action_id patterns to handlers."""

    def __init__(self):
        self._handlers: Dict[str, Callable] = {}
        self._prefix_handlers: Dict[str, Callable] = {}

    def register(self, action_id: str, handler: Callable) -> None:
        """Register handler for exact action_id match."""
        self._handlers[action_id] = handler

    def register_prefix(self, prefix: str, handler: Callable) -> None:
        """Register handler for action_id prefix match."""
        self._prefix_handlers[prefix] = handler

    def get_handler(self, action_id: str) -> Optional[Callable]:
        """Find handler for action_id (exact match first, then prefix)."""
        if action_id in self._handlers:
            return self._handlers[action_id]
        for prefix, handler in self._prefix_handlers.items():
            if action_id.startswith(prefix):
                return handler
        return None


class SlackInteractiveHandler:
    """Handles all interactive payloads from Slack Block Kit."""

    def __init__(self, wrapper: 'SlackAgentWrapper'):
        self.wrapper = wrapper
        self.action_registry = ActionRegistry()
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register built-in handlers."""
        self.action_registry.register_prefix("feedback_", self._handle_feedback)
        self.action_registry.register("clear_conversation", self._handle_clear)

    async def handle(self, request_or_payload) -> web.Response | None:
        """Entry point — accepts aiohttp Request (webhook) or dict (socket)."""
        if isinstance(request_or_payload, web.Request):
            form_data = await request_or_payload.post()
            payload = json.loads(form_data.get("payload", "{}"))
        else:
            payload = request_or_payload

        payload_type = payload.get("type")
        if payload_type == "block_actions":
            await self._handle_block_actions(payload)
        elif payload_type == "view_submission":
            await self._handle_view_submission(payload)
        elif payload_type in ("shortcut", "message_action"):
            await self._handle_shortcut(payload)

        if isinstance(request_or_payload, web.Request):
            return web.json_response({"ok": True})
        return None

    async def _handle_block_actions(self, payload: dict) -> None:
        """Route block_actions to registered handlers."""
        for action in payload.get("actions", []):
            action_id = action.get("action_id", "")
            handler = self.action_registry.get_handler(action_id)
            if handler:
                await handler(payload, action)

    async def _handle_view_submission(self, payload: dict) -> None:
        """Route modal submissions to registered handlers."""
        callback_id = payload.get("view", {}).get("callback_id", "")
        handler = self.action_registry.get_handler(f"modal:{callback_id}")
        if handler:
            await handler(payload)

    async def _handle_shortcut(self, payload: dict) -> None:
        """Route shortcuts to registered handlers."""
        callback_id = payload.get("callback_id", "")
        handler = self.action_registry.get_handler(f"shortcut:{callback_id}")
        if handler:
            await handler(payload)

    # === Default handlers ===

    async def _handle_feedback(self, payload: dict, action: dict) -> None:
        """Handle feedback button clicks."""
        feedback_type = action.get("action_id", "").replace("feedback_", "")
        user = payload.get("user", {}).get("id", "unknown")
        message_ts = action.get("value", "")
        logger.info("Feedback: %s from %s on %s", feedback_type, user, message_ts)

        response_url = payload.get("response_url")
        if response_url:
            emoji = ":white_check_mark:" if feedback_type == "positive" else ":x:"
            async with ClientSession() as session:
                await session.post(response_url, json={
                    "response_type": "ephemeral",
                    "text": f"{emoji} Thanks for your feedback!",
                    "replace_original": False,
                })

    async def _handle_clear(self, payload: dict, action: dict) -> None:
        """Handle clear conversation button."""
        user = payload.get("user", {}).get("id", "unknown")
        channel = payload.get("channel", {}).get("id", "")
        self.wrapper.conversations.pop(f"{channel}:{user}", None)

        response_url = payload.get("response_url")
        if response_url:
            async with ClientSession() as session:
                await session.post(response_url, json={
                    "response_type": "ephemeral",
                    "text": "Conversation cleared.",
                })

    async def open_modal(self, trigger_id: str, form_definition: dict) -> bool:
        """Open a Slack modal dialog."""
        view = {
            "type": "modal",
            "callback_id": form_definition.get("id", "generic_form"),
            "title": {"type": "plain_text", "text": form_definition.get("title", "Form")[:24]},
            "submit": {"type": "plain_text", "text": "Submit"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": self._build_form_blocks(form_definition.get("fields", [])),
        }

        headers = {
            "Authorization": f"Bearer {self.wrapper.config.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        async with ClientSession() as session:
            async with session.post(
                "https://slack.com/api/views.open",
                headers=headers,
                data=json.dumps({"trigger_id": trigger_id, "view": view}),
            ) as resp:
                data = await resp.json()
                return data.get("ok", False)

    def _build_form_blocks(self, fields: list[dict]) -> list[dict]:
        """Convert form field definitions to Block Kit input blocks."""
        blocks = []
        for field in fields:
            ft = field.get("type", "text")
            block = {
                "type": "input",
                "block_id": field["id"],
                "label": {"type": "plain_text", "text": field["label"]},
                "optional": field.get("optional", False),
            }
            if ft == "text":
                block["element"] = {
                    "type": "plain_text_input",
                    "action_id": field["id"],
                    "multiline": field.get("multiline", False),
                }
            elif ft == "select":
                block["element"] = {
                    "type": "static_select",
                    "action_id": field["id"],
                    "options": [
                        {"text": {"type": "plain_text", "text": o["label"]}, "value": o["value"]}
                        for o in field.get("options", [])
                    ],
                }
            elif ft == "date":
                block["element"] = {"type": "datepicker", "action_id": field["id"]}
            blocks.append(block)
        return blocks


def build_feedback_blocks(message_id: str = "") -> list[dict]:
    """Feedback buttons to append to agent responses."""
    return [
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":thumbsup: Helpful"},
                    "action_id": "feedback_positive",
                    "value": message_id,
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":thumbsdown: Not helpful"},
                    "action_id": "feedback_negative",
                    "value": message_id,
                },
            ],
        },
    ]
```

### Integration in wrapper.__init__()
```python
from .interactive import SlackInteractiveHandler

class SlackAgentWrapper:
    def __init__(self, ...):
        # ... existing init ...

        # Interactive handler
        self._interactive_handler = SlackInteractiveHandler(self)
        self.interactive_route = f"/api/slack/{safe_id}/interactive"
        app.router.add_post(self.interactive_route, self._interactive_handler.handle)
        if auth := app.get("auth"):
            auth.add_exclude_list(self.interactive_route)
```

### Key Constraints
- Interactive payloads come as form-encoded with `payload` key containing JSON
- `response_url` is for ephemeral responses without revealing bot token
- Modals require `trigger_id` from the originating interaction (valid ~3 seconds)
- Action handlers must be async

### References in Codebase
- Slack Block Kit Builder: https://app.slack.com/block-kit-builder
- `parrot/integrations/msteams/forms.py` — similar pattern for Adaptive Cards

---

## Acceptance Criteria

- [ ] `ActionRegistry` supports exact and prefix matching
- [ ] `handle()` routes block_actions, view_submission, shortcuts
- [ ] Feedback buttons send ephemeral "Thanks" message
- [ ] `build_feedback_blocks()` produces valid Block Kit JSON
- [ ] `open_modal()` opens modal with form fields
- [ ] Interactive route registered in wrapper
- [ ] All tests pass: `pytest tests/unit/test_slack_interactive.py -v`

---

## Test Specification

```python
# tests/unit/test_slack_interactive.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.integrations.slack.interactive import (
    ActionRegistry, SlackInteractiveHandler, build_feedback_blocks
)


class TestActionRegistry:
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


class TestSlackInteractiveHandler:
    @pytest.mark.asyncio
    async def test_routes_block_actions(self, mock_wrapper):
        """block_actions payload routed to registered handler."""
        handler = SlackInteractiveHandler(mock_wrapper)
        custom_handler = AsyncMock()
        handler.action_registry.register("my_btn", custom_handler)

        payload = {
            "type": "block_actions",
            "actions": [{"action_id": "my_btn", "value": "clicked"}],
        }

        await handler.handle(payload)

        custom_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_feedback_sends_thanks(self, mock_wrapper):
        """Feedback handler sends ephemeral thanks."""
        handler = SlackInteractiveHandler(mock_wrapper)

        with patch('aiohttp.ClientSession') as MockSession:
            mock_session = AsyncMock()
            MockSession.return_value.__aenter__.return_value = mock_session

            payload = {
                "type": "block_actions",
                "user": {"id": "U123"},
                "response_url": "https://hooks.slack.com/xxx",
                "actions": [{"action_id": "feedback_positive", "value": "msg_123"}],
            }

            await handler.handle(payload)

            mock_session.post.assert_called_once()
            call_data = mock_session.post.call_args[1]["json"]
            assert "Thanks" in call_data["text"]


class TestBuildFeedbackBlocks:
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
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-024 is in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-030-slack-interactive-handler.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-24
**Notes**:
- Created `parrot/integrations/slack/interactive.py` with full Block Kit interactive handler
- Implemented `ActionRegistry` class with exact and prefix matching for action handlers
- Implemented `SlackInteractiveHandler` with routing for:
  - `block_actions` (button clicks, menu selections)
  - `view_submission` (modal form submissions)
  - `shortcut` / `message_action` (shortcuts)
  - `view_closed` (modal dismissal)
- Built-in handlers for:
  - `feedback_positive` / `feedback_negative` - sends ephemeral "Thanks" message
  - `clear_conversation` - clears user's conversation memory
- `open_modal()` and `update_modal()` for programmatic modal management
- `_build_form_blocks()` supports multiple field types: text, select, multi_select, date, time, checkbox, radio
- `extract_form_values()` for parsing view_submission payloads
- Added utility functions: `build_feedback_blocks()`, `build_clear_button()`
- Registered interactive route in wrapper: `/api/slack/{bot_id}/interactive`
- Updated `__init__.py` to export all new classes and functions
- Created 41 comprehensive unit tests
- All 110 Slack tests pass (69 existing + 41 new)

**Deviations from spec**:
- Added `update_modal()` method (not in spec but useful for multi-step modals)
- Added `build_clear_button()` utility (not in spec but complements feedback buttons)
- Added `extract_form_values()` method for easier form data extraction
- Expanded field type support beyond spec (time, checkbox, radio, multi_select)
- Added view_closed handling for better logging
