# TASK-029: Slack Socket Mode Handler

**Feature**: Slack Wrapper Integration Enhancements
**Spec**: `sdd/specs/slack-wrapper-integration.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-023, TASK-024, TASK-025, TASK-026
**Assigned-to**: claude-session

---

## Context

> This task adds Socket Mode for local development without public URLs.
> Reference: Spec Section 4 (Socket Mode) and Section 3 (Module 6).

HTTP webhooks require a public URL, complicating local development. Socket Mode uses WebSocket connections initiated from the client, eliminating the need for ngrok or similar tools.

---

## Scope

- Create `parrot/integrations/slack/socket_handler.py` module
- Implement `SlackSocketHandler` class using `slack-sdk` SocketModeClient
- Route events to existing wrapper methods
- Support slash commands and interactive payloads
- Update `IntegrationBotManager` to start Socket Mode connections
- Default to Socket Mode in development environments

**NOT in scope**:
- Replacing webhook mode for production
- Socket Mode for Agents & AI Apps (handled in TASK-029)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/slack/socket_handler.py` | CREATE | Socket Mode handler |
| `parrot/integrations/manager.py` | MODIFY | Support Socket Mode startup |
| `tests/unit/test_slack_socket.py` | CREATE | Unit tests |
| `parrot/integrations/slack/__init__.py` | MODIFY | Export handler |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/integrations/slack/socket_handler.py
"""Socket Mode handler for Slack integration."""
import asyncio
import logging
from typing import TYPE_CHECKING

from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

if TYPE_CHECKING:
    from .wrapper import SlackAgentWrapper

logger = logging.getLogger("SlackSocketMode")


class SlackSocketHandler:
    """
    Handles Slack events via Socket Mode (WebSocket connection).

    Recommended for: local development, environments behind firewalls.
    For production, prefer webhook mode.
    """

    def __init__(self, wrapper: 'SlackAgentWrapper'):
        self.wrapper = wrapper
        self.client = SocketModeClient(
            app_token=wrapper.config.app_token,
            web_client=AsyncWebClient(token=wrapper.config.bot_token),
        )
        self.client.socket_mode_request_listeners.append(self._handle_request)

    async def start(self) -> None:
        """Connect to Slack via WebSocket."""
        logger.info("Starting Slack Socket Mode for '%s'", self.wrapper.config.name)
        await self.client.connect()
        logger.info("Slack Socket Mode connected for '%s'", self.wrapper.config.name)

    async def stop(self) -> None:
        """Disconnect from Slack."""
        await self.client.disconnect()
        logger.info("Slack Socket Mode disconnected for '%s'", self.wrapper.config.name)

    async def _handle_request(self, client: SocketModeClient, req: SocketModeRequest):
        """Route Socket Mode requests to appropriate handlers."""
        # Acknowledge immediately (equivalent to HTTP 200)
        response = SocketModeResponse(envelope_id=req.envelope_id)
        await client.send_socket_mode_response(response)

        if req.type == "events_api":
            await self._handle_event(req.payload)
        elif req.type == "slash_commands":
            await self._handle_slash_command(req.payload)
        elif req.type == "interactive":
            await self._handle_interactive(req.payload)

    async def _handle_event(self, payload: dict) -> None:
        """Process events_api payloads."""
        event = payload.get("event", {})
        event_type = event.get("type")

        # Deduplication
        event_id = payload.get("event_id")
        if self.wrapper._dedup.is_duplicate(event_id):
            return

        # Skip bot messages
        if event_type not in {"app_mention", "message"}:
            return
        if event.get("subtype") == "bot_message":
            return

        channel = event.get("channel")
        if not channel or not self.wrapper._is_authorized(channel):
            return

        text = (event.get("text") or "").strip()
        user = event.get("user") or "unknown"
        thread_ts = event.get("thread_ts") or event.get("ts")
        files = event.get("files")

        asyncio.create_task(
            self.wrapper._safe_answer(
                channel=channel, user=user, text=text,
                thread_ts=thread_ts, session_id=f"{channel}:{user}", files=files,
            )
        )

    async def _handle_slash_command(self, payload: dict) -> None:
        """Process slash command payloads."""
        channel = payload.get("channel_id", "")
        user = payload.get("user_id", "unknown")
        text = (payload.get("text") or "").strip()
        response_url = payload.get("response_url")

        # Handle built-in commands
        if text.lower() in {"help", "clear", "commands"} and response_url:
            from aiohttp import ClientSession
            async with ClientSession() as session:
                if text.lower() == "help":
                    body = {"response_type": "ephemeral", "text": self.wrapper._help_text()}
                elif text.lower() == "clear":
                    self.wrapper.conversations.pop(f"{channel}:{user}", None)
                    body = {"response_type": "ephemeral", "text": "Conversation cleared."}
                else:
                    body = {"response_type": "ephemeral", "text": "Commands: help, clear, commands"}
                await session.post(response_url, json=body)
            return

        asyncio.create_task(
            self.wrapper._safe_answer(
                channel=channel, user=user, text=text,
                thread_ts=None, session_id=f"{channel}:{user}",
            )
        )

    async def _handle_interactive(self, payload: dict) -> None:
        """Route interactive payloads to handler."""
        if hasattr(self.wrapper, '_interactive_handler'):
            await self.wrapper._interactive_handler.handle(payload)
```

### Integration in manager.py
```python
async def _start_slack_bot(self, name: str, config: SlackAgentConfig):
    agent = await self._get_agent(config.chatbot_id)
    if not agent:
        return

    wrapper = SlackAgentWrapper(agent=agent, config=config, app=self.bot_manager.get_app())
    self.slack_bots[name] = wrapper

    if config.connection_mode == "socket":
        from .slack.socket_handler import SlackSocketHandler
        handler = SlackSocketHandler(wrapper)
        wrapper._socket_handler = handler
        task = asyncio.create_task(handler.start(), name=f"slack_socket_{name}")
        self._polling_tasks.append(task)
        self.logger.info(f"Started Slack bot '{name}' (Socket Mode)")
    else:
        self.logger.info(f"Started Slack bot '{name}' (Webhook Mode)")
```

### Key Constraints
- Requires `app_token` (xapp-...) from Slack app settings
- Must acknowledge requests immediately via `SocketModeResponse`
- Reuse wrapper methods (`_safe_answer`, `_dedup`, etc.)
- Handle graceful shutdown

### References in Codebase
- Slack SDK Socket Mode: https://slack.dev/python-slack-sdk/socket-mode/
- `parrot/integrations/telegram/wrapper.py` — polling pattern

---

## Acceptance Criteria

- [x] Socket Mode connects successfully with valid app_token
- [x] Events routed to wrapper's `_safe_answer()`
- [x] Slash commands work via response_url
- [x] Deduplication shared with webhook mode
- [x] Graceful start/stop lifecycle
- [x] `IntegrationBotManager` starts Socket Mode when configured
- [x] All tests pass: `pytest tests/unit/test_slack_socket.py -v` (22 tests)

---

## Test Specification

```python
# tests/unit/test_slack_socket.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.integrations.slack.socket_handler import SlackSocketHandler


@pytest.fixture
def mock_wrapper():
    wrapper = MagicMock()
    wrapper.config.app_token = "xapp-test-token"
    wrapper.config.bot_token = "xoxb-test-token"
    wrapper.config.name = "test_bot"
    wrapper._dedup.is_duplicate = MagicMock(return_value=False)
    wrapper._is_authorized = MagicMock(return_value=True)
    wrapper._safe_answer = AsyncMock()
    return wrapper


class TestSlackSocketHandler:
    @pytest.mark.asyncio
    async def test_acknowledges_request(self, mock_wrapper):
        """Requests are acknowledged immediately."""
        handler = SlackSocketHandler(mock_wrapper)

        mock_client = AsyncMock()
        mock_req = MagicMock()
        mock_req.envelope_id = "env_123"
        mock_req.type = "events_api"
        mock_req.payload = {"event": {"type": "other"}}

        await handler._handle_request(mock_client, mock_req)

        mock_client.send_socket_mode_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_message_event(self, mock_wrapper):
        """Message events are routed to _safe_answer."""
        handler = SlackSocketHandler(mock_wrapper)

        payload = {
            "event_id": "evt_123",
            "event": {
                "type": "message",
                "channel": "C123",
                "user": "U456",
                "text": "Hello",
                "ts": "123.456",
            }
        }

        await handler._handle_event(payload)
        await asyncio.sleep(0.1)  # Allow task to start

        mock_wrapper._safe_answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_deduplicates_events(self, mock_wrapper):
        """Duplicate events are not processed."""
        mock_wrapper._dedup.is_duplicate = MagicMock(return_value=True)
        handler = SlackSocketHandler(mock_wrapper)

        payload = {"event_id": "evt_123", "event": {"type": "message"}}

        await handler._handle_event(payload)

        mock_wrapper._safe_answer.assert_not_called()

    @pytest.mark.asyncio
    async def test_slash_command_help(self, mock_wrapper):
        """Help command returns help text via response_url."""
        handler = SlackSocketHandler(mock_wrapper)
        mock_wrapper._help_text = MagicMock(return_value="Help text")

        with patch('aiohttp.ClientSession') as MockSession:
            mock_session = AsyncMock()
            MockSession.return_value.__aenter__.return_value = mock_session
            mock_session.post = AsyncMock()

            payload = {
                "channel_id": "C123",
                "user_id": "U456",
                "text": "help",
                "response_url": "https://hooks.slack.com/response/xxx"
            }

            await handler._handle_slash_command(payload)

            mock_session.post.assert_called_once()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-023, TASK-024, TASK-025, TASK-026 are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-029-slack-socket-mode.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-24
**Notes**:
- Created `parrot/integrations/slack/socket_handler.py` with `SlackSocketHandler` class
- Implemented WebSocket-based event handling using `slack-sdk` SocketModeClient
- Routes events to wrapper's `_safe_answer()` for processing
- Supports slash commands with response_url responses
- Reuses wrapper's deduplication, authorization, and background task tracking
- Supports interactive payloads (routed to interactive handler if present)
- Updated `parrot/integrations/manager.py` to start Socket Mode when `connection_mode="socket"`
- Exports `SlackSocketHandler` from `parrot/integrations/slack/__init__.py`
- Created 22 comprehensive unit tests covering all functionality

**Deviations from spec**:
- Lazy imports `slack-sdk` modules inside `__init__` to make the dependency optional (allows webhook mode without slack-sdk installed)
- Added `_send_response()` helper method for sending responses to Slack response_url
- Interactive payload routing checks for `_interactive_handler` attribute on wrapper
