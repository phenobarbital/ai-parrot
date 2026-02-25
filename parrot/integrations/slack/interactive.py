"""Interactive Block Kit handler for Slack integration.

Handles all interactive payloads from Slack Block Kit including:
- Button clicks (block_actions)
- Modal submissions (view_submission)
- Shortcuts and message actions
- Feedback collection

Part of FEAT-010: Slack Wrapper Integration Enhancements.
"""
import json
import logging
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from aiohttp import web, ClientSession

if TYPE_CHECKING:
    from .wrapper import SlackAgentWrapper

logger = logging.getLogger("SlackInteractive")


class ActionRegistry:
    """Registry for Block Kit action handlers.

    Maps action_id patterns to async handler functions.
    Supports both exact matching and prefix matching.

    Examples:
        registry = ActionRegistry()
        registry.register("approve_request", handle_approve)
        registry.register_prefix("feedback_", handle_feedback)
    """

    def __init__(self):
        self._handlers: Dict[str, Callable] = {}
        self._prefix_handlers: Dict[str, Callable] = {}

    def register(self, action_id: str, handler: Callable) -> None:
        """Register handler for exact action_id match.

        Args:
            action_id: The exact action_id to match.
            handler: Async function to call when action is triggered.
        """
        self._handlers[action_id] = handler

    def register_prefix(self, prefix: str, handler: Callable) -> None:
        """Register handler for action_id prefix match.

        Args:
            prefix: The prefix to match (e.g., "feedback_").
            handler: Async function to call when action matches prefix.
        """
        self._prefix_handlers[prefix] = handler

    def get_handler(self, action_id: str) -> Optional[Callable]:
        """Find handler for action_id.

        Exact match takes precedence over prefix match.

        Args:
            action_id: The action_id from the Slack payload.

        Returns:
            Handler function if found, None otherwise.
        """
        # Exact match first
        if action_id in self._handlers:
            return self._handlers[action_id]

        # Then prefix match
        for prefix, handler in self._prefix_handlers.items():
            if action_id.startswith(prefix):
                return handler

        return None

    def unregister(self, action_id: str) -> None:
        """Remove an exact match handler.

        Args:
            action_id: The action_id to unregister.
        """
        self._handlers.pop(action_id, None)

    def unregister_prefix(self, prefix: str) -> None:
        """Remove a prefix match handler.

        Args:
            prefix: The prefix to unregister.
        """
        self._prefix_handlers.pop(prefix, None)


class SlackInteractiveHandler:
    """Handles all interactive payloads from Slack Block Kit.

    Routes different payload types to appropriate handlers:
    - block_actions: Button clicks, menu selections
    - view_submission: Modal form submissions
    - shortcut/message_action: Global and message shortcuts

    Attributes:
        wrapper: The parent SlackAgentWrapper instance.
        action_registry: Registry for custom action handlers.
    """

    def __init__(self, wrapper: 'SlackAgentWrapper'):
        """Initialize the interactive handler.

        Args:
            wrapper: The parent SlackAgentWrapper instance.
        """
        self.wrapper = wrapper
        self.action_registry = ActionRegistry()
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register built-in action handlers."""
        self.action_registry.register_prefix("feedback_", self._handle_feedback)
        self.action_registry.register("clear_conversation", self._handle_clear)

    async def handle(self, request_or_payload: web.Request | dict) -> Optional[web.Response]:
        """Entry point for interactive payloads.

        Accepts either an aiohttp Request (from webhook) or a dict (from Socket Mode).

        Args:
            request_or_payload: Either a web.Request or a payload dict.

        Returns:
            web.Response for webhook requests, None for Socket Mode.
        """
        # Parse payload from request or use directly
        if isinstance(request_or_payload, web.Request):
            form_data = await request_or_payload.post()
            payload_str = form_data.get("payload", "{}")
            try:
                payload = json.loads(payload_str)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON in interactive payload")
                return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
        else:
            payload = request_or_payload

        payload_type = payload.get("type")
        logger.debug("Interactive payload type: %s", payload_type)

        try:
            if payload_type == "block_actions":
                await self._handle_block_actions(payload)
            elif payload_type == "view_submission":
                result = await self._handle_view_submission(payload)
                if result:
                    # Return view update or errors
                    if isinstance(request_or_payload, web.Request):
                        return web.json_response(result)
                    return result
            elif payload_type in ("shortcut", "message_action"):
                await self._handle_shortcut(payload)
            elif payload_type == "view_closed":
                # Modal was closed by user
                logger.debug("View closed by user")
            else:
                logger.debug("Unhandled payload type: %s", payload_type)

        except Exception as exc:
            logger.error("Error handling interactive payload: %s", exc, exc_info=True)

        if isinstance(request_or_payload, web.Request):
            return web.json_response({"ok": True})
        return None

    async def _handle_block_actions(self, payload: dict) -> None:
        """Route block_actions to registered handlers.

        Args:
            payload: The full Slack payload.
        """
        for action in payload.get("actions", []):
            action_id = action.get("action_id", "")
            handler = self.action_registry.get_handler(action_id)
            if handler:
                try:
                    await handler(payload, action)
                except Exception as exc:
                    logger.error("Error in action handler for %s: %s", action_id, exc)
            else:
                logger.debug("No handler registered for action: %s", action_id)

    async def _handle_view_submission(self, payload: dict) -> Optional[dict]:
        """Route modal submissions to registered handlers.

        Args:
            payload: The full Slack payload.

        Returns:
            Optional dict for view updates or validation errors.
        """
        view = payload.get("view", {})
        callback_id = view.get("callback_id", "")
        handler = self.action_registry.get_handler(f"modal:{callback_id}")

        if handler:
            try:
                return await handler(payload)
            except Exception as exc:
                logger.error("Error in view submission handler for %s: %s", callback_id, exc)
        else:
            logger.debug("No handler registered for modal: %s", callback_id)

        return None

    async def _handle_shortcut(self, payload: dict) -> None:
        """Route shortcuts to registered handlers.

        Args:
            payload: The full Slack payload.
        """
        callback_id = payload.get("callback_id", "")
        handler = self.action_registry.get_handler(f"shortcut:{callback_id}")

        if handler:
            try:
                await handler(payload)
            except Exception as exc:
                logger.error("Error in shortcut handler for %s: %s", callback_id, exc)
        else:
            logger.debug("No handler registered for shortcut: %s", callback_id)

    # =========================================================================
    # Default Handlers
    # =========================================================================

    async def _handle_feedback(self, payload: dict, action: dict) -> None:
        """Handle feedback button clicks.

        Logs the feedback and sends an ephemeral "Thanks" message.

        Args:
            payload: The full Slack payload.
            action: The specific action that was triggered.
        """
        action_id = action.get("action_id", "")
        feedback_type = action_id.replace("feedback_", "")
        user = payload.get("user", {}).get("id", "unknown")
        message_ts = action.get("value", "")

        logger.info(
            "Feedback: %s from %s on message %s",
            feedback_type, user, message_ts
        )

        # Send ephemeral response via response_url
        response_url = payload.get("response_url")
        if response_url:
            emoji = ":white_check_mark:" if feedback_type == "positive" else ":x:"
            try:
                async with ClientSession() as session:
                    await session.post(
                        response_url,
                        json={
                            "response_type": "ephemeral",
                            "text": f"{emoji} Thanks for your feedback!",
                            "replace_original": False,
                        },
                    )
            except Exception as exc:
                logger.error("Failed to send feedback response: %s", exc)

    async def _handle_clear(self, payload: dict, action: dict) -> None:
        """Handle clear conversation button.

        Clears the conversation memory for the user.

        Args:
            payload: The full Slack payload.
            action: The specific action that was triggered.
        """
        user = payload.get("user", {}).get("id", "unknown")
        channel = payload.get("channel", {}).get("id", "")
        session_id = f"{channel}:{user}"

        self.wrapper.conversations.pop(session_id, None)
        logger.info("Cleared conversation for %s", session_id)

        # Send ephemeral confirmation
        response_url = payload.get("response_url")
        if response_url:
            try:
                async with ClientSession() as session:
                    await session.post(
                        response_url,
                        json={
                            "response_type": "ephemeral",
                            "text": "Conversation cleared.",
                            "replace_original": False,
                        },
                    )
            except Exception as exc:
                logger.error("Failed to send clear response: %s", exc)

    # =========================================================================
    # Modal Operations
    # =========================================================================

    async def open_modal(
        self,
        trigger_id: str,
        form_definition: dict,
    ) -> bool:
        """Open a Slack modal dialog.

        Args:
            trigger_id: The trigger_id from the originating interaction.
                        Valid for ~3 seconds.
            form_definition: Definition of the form to display.
                Expected keys: id, title, fields

        Returns:
            True if modal opened successfully, False otherwise.
        """
        if not self.wrapper.config.bot_token:
            logger.warning("Cannot open modal: bot_token not configured")
            return False

        # Build the view
        view = {
            "type": "modal",
            "callback_id": form_definition.get("id", "generic_form"),
            "title": {
                "type": "plain_text",
                "text": form_definition.get("title", "Form")[:24],  # Max 24 chars
            },
            "submit": {"type": "plain_text", "text": "Submit"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": self._build_form_blocks(form_definition.get("fields", [])),
        }

        # Add private_metadata if provided
        if metadata := form_definition.get("metadata"):
            view["private_metadata"] = json.dumps(metadata) if isinstance(metadata, dict) else str(metadata)

        headers = {
            "Authorization": f"Bearer {self.wrapper.config.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        try:
            async with ClientSession() as session:
                async with session.post(
                    "https://slack.com/api/views.open",
                    headers=headers,
                    data=json.dumps({"trigger_id": trigger_id, "view": view}),
                ) as resp:
                    data = await resp.json()
                    if not data.get("ok"):
                        logger.error("Failed to open modal: %s", data.get("error"))
                        return False
                    return True
        except Exception as exc:
            logger.error("Error opening modal: %s", exc)
            return False

    async def update_modal(
        self,
        view_id: str,
        form_definition: dict,
    ) -> bool:
        """Update an existing modal.

        Args:
            view_id: The view_id of the modal to update.
            form_definition: Updated form definition.

        Returns:
            True if modal updated successfully, False otherwise.
        """
        if not self.wrapper.config.bot_token:
            logger.warning("Cannot update modal: bot_token not configured")
            return False

        view = {
            "type": "modal",
            "callback_id": form_definition.get("id", "generic_form"),
            "title": {
                "type": "plain_text",
                "text": form_definition.get("title", "Form")[:24],
            },
            "submit": {"type": "plain_text", "text": "Submit"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": self._build_form_blocks(form_definition.get("fields", [])),
        }

        headers = {
            "Authorization": f"Bearer {self.wrapper.config.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        try:
            async with ClientSession() as session:
                async with session.post(
                    "https://slack.com/api/views.update",
                    headers=headers,
                    data=json.dumps({"view_id": view_id, "view": view}),
                ) as resp:
                    data = await resp.json()
                    if not data.get("ok"):
                        logger.error("Failed to update modal: %s", data.get("error"))
                        return False
                    return True
        except Exception as exc:
            logger.error("Error updating modal: %s", exc)
            return False

    def _build_form_blocks(self, fields: List[dict]) -> List[dict]:
        """Convert form field definitions to Block Kit input blocks.

        Args:
            fields: List of field definitions.
                Each field should have: id, label, type, optional, options, etc.

        Returns:
            List of Block Kit block elements.
        """
        blocks: List[dict] = []

        for field in fields:
            field_type = field.get("type", "text")
            field_id = field.get("id", "")

            block: Dict[str, Any] = {
                "type": "input",
                "block_id": field_id,
                "label": {"type": "plain_text", "text": field.get("label", field_id)},
                "optional": field.get("optional", False),
            }

            # Add hint if provided
            if hint := field.get("hint"):
                block["hint"] = {"type": "plain_text", "text": hint}

            # Build element based on field type
            if field_type == "text":
                element = {
                    "type": "plain_text_input",
                    "action_id": field_id,
                    "multiline": field.get("multiline", False),
                }
                if placeholder := field.get("placeholder"):
                    element["placeholder"] = {"type": "plain_text", "text": placeholder}
                if initial := field.get("initial_value"):
                    element["initial_value"] = str(initial)
                if max_length := field.get("max_length"):
                    element["max_length"] = max_length
                block["element"] = element

            elif field_type == "select":
                options = [
                    {
                        "text": {"type": "plain_text", "text": opt.get("label", opt.get("value", ""))},
                        "value": str(opt.get("value", opt.get("label", ""))),
                    }
                    for opt in field.get("options", [])
                ]
                element = {
                    "type": "static_select",
                    "action_id": field_id,
                    "options": options,
                }
                if placeholder := field.get("placeholder"):
                    element["placeholder"] = {"type": "plain_text", "text": placeholder}
                if initial := field.get("initial_value"):
                    for opt in options:
                        if opt["value"] == str(initial):
                            element["initial_option"] = opt
                            break
                block["element"] = element

            elif field_type == "multi_select":
                options = [
                    {
                        "text": {"type": "plain_text", "text": opt.get("label", opt.get("value", ""))},
                        "value": str(opt.get("value", opt.get("label", ""))),
                    }
                    for opt in field.get("options", [])
                ]
                block["element"] = {
                    "type": "multi_static_select",
                    "action_id": field_id,
                    "options": options,
                }

            elif field_type == "date":
                element = {
                    "type": "datepicker",
                    "action_id": field_id,
                }
                if initial := field.get("initial_value"):
                    element["initial_date"] = str(initial)
                if placeholder := field.get("placeholder"):
                    element["placeholder"] = {"type": "plain_text", "text": placeholder}
                block["element"] = element

            elif field_type == "time":
                element = {
                    "type": "timepicker",
                    "action_id": field_id,
                }
                if initial := field.get("initial_value"):
                    element["initial_time"] = str(initial)
                block["element"] = element

            elif field_type == "checkbox":
                options = [
                    {
                        "text": {"type": "plain_text", "text": opt.get("label", opt.get("value", ""))},
                        "value": str(opt.get("value", opt.get("label", ""))),
                    }
                    for opt in field.get("options", [])
                ]
                block["element"] = {
                    "type": "checkboxes",
                    "action_id": field_id,
                    "options": options,
                }

            elif field_type == "radio":
                options = [
                    {
                        "text": {"type": "plain_text", "text": opt.get("label", opt.get("value", ""))},
                        "value": str(opt.get("value", opt.get("label", ""))),
                    }
                    for opt in field.get("options", [])
                ]
                block["element"] = {
                    "type": "radio_buttons",
                    "action_id": field_id,
                    "options": options,
                }

            else:
                # Default to plain text input
                block["element"] = {
                    "type": "plain_text_input",
                    "action_id": field_id,
                }

            blocks.append(block)

        return blocks

    def extract_form_values(self, payload: dict) -> Dict[str, Any]:
        """Extract form values from a view_submission payload.

        Args:
            payload: The view_submission payload from Slack.

        Returns:
            Dict mapping field IDs to their values.
        """
        values: Dict[str, Any] = {}
        state_values = payload.get("view", {}).get("state", {}).get("values", {})

        for block_id, block_data in state_values.items():
            for action_id, action_data in block_data.items():
                value = None
                action_type = action_data.get("type")

                if action_type == "plain_text_input":
                    value = action_data.get("value")
                elif action_type == "static_select":
                    selected = action_data.get("selected_option")
                    value = selected.get("value") if selected else None
                elif action_type == "multi_static_select":
                    selected = action_data.get("selected_options", [])
                    value = [opt.get("value") for opt in selected]
                elif action_type == "datepicker":
                    value = action_data.get("selected_date")
                elif action_type == "timepicker":
                    value = action_data.get("selected_time")
                elif action_type == "checkboxes":
                    selected = action_data.get("selected_options", [])
                    value = [opt.get("value") for opt in selected]
                elif action_type == "radio_buttons":
                    selected = action_data.get("selected_option")
                    value = selected.get("value") if selected else None

                values[block_id] = value

        return values


def build_feedback_blocks(message_id: str = "") -> List[dict]:
    """Build feedback buttons to append to agent responses.

    Creates a divider and action buttons for thumbs up/down feedback.

    Args:
        message_id: Optional message timestamp to track which message
                   the feedback is for.

    Returns:
        List of Block Kit blocks (divider + actions).
    """
    return [
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":thumbsup: Helpful", "emoji": True},
                    "action_id": "feedback_positive",
                    "value": message_id,
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":thumbsdown: Not helpful", "emoji": True},
                    "action_id": "feedback_negative",
                    "value": message_id,
                },
            ],
        },
    ]


def build_clear_button() -> dict:
    """Build a clear conversation button.

    Returns:
        A Block Kit button element for clearing conversation.
    """
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": "Clear Conversation", "emoji": True},
        "action_id": "clear_conversation",
        "style": "danger",
        "confirm": {
            "title": {"type": "plain_text", "text": "Clear Conversation?"},
            "text": {"type": "plain_text", "text": "This will clear your conversation history with this bot."},
            "confirm": {"type": "plain_text", "text": "Clear"},
            "deny": {"type": "plain_text", "text": "Cancel"},
        },
    }
