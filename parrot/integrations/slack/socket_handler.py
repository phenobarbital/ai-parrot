"""Socket Mode handler for Slack integration.

Allows Slack integration without public webhook URLs by using WebSocket connections.
Recommended for: local development, environments behind firewalls.
For production, prefer webhook mode.
"""
import asyncio
import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

from aiohttp import ClientSession

if TYPE_CHECKING:
    from .wrapper import SlackAgentWrapper


logger = logging.getLogger("SlackSocketMode")


class SlackSocketHandler:
    """Handle Slack events via Socket Mode (WebSocket connection).

    Socket Mode allows receiving events from Slack without exposing
    a public HTTP endpoint. It uses a WebSocket connection initiated
    from the client side.

    Requires:
    - App-level token (xapp-...) with connections:write scope
    - Socket Mode enabled in Slack app settings

    Attributes:
        wrapper: The SlackAgentWrapper instance to route events to.
        client: The SocketModeClient for WebSocket communication.
    """

    def __init__(self, wrapper: 'SlackAgentWrapper'):
        """Initialize the Socket Mode handler.

        Args:
            wrapper: The SlackAgentWrapper instance to route events to.
        """
        # Lazy import to avoid requiring slack-sdk when not using Socket Mode
        try:
            from slack_sdk.socket_mode.aiohttp import SocketModeClient
            from slack_sdk.web.async_client import AsyncWebClient
        except ImportError as exc:
            raise ImportError(
                "slack-sdk is required for Socket Mode. "
                "Install it with: pip install slack-sdk"
            ) from exc

        self.wrapper = wrapper
        self._running = False
        self._connection_task: Optional[asyncio.Task] = None

        # Create the Socket Mode client
        self.client = SocketModeClient(
            app_token=wrapper.config.app_token,
            web_client=AsyncWebClient(token=wrapper.config.bot_token),
        )
        # Register our handler for all Socket Mode requests
        self.client.socket_mode_request_listeners.append(self._handle_request)

    async def start(self) -> None:
        """Connect to Slack via WebSocket.

        This method establishes the WebSocket connection and starts
        listening for events. It should be called as a background task.
        """
        if self._running:
            logger.warning(
                "Socket Mode already running for '%s'",
                self.wrapper.config.name,
            )
            return

        self._running = True
        logger.info(
            "Starting Slack Socket Mode for '%s'",
            self.wrapper.config.name,
        )

        try:
            await self.client.connect()
            logger.info(
                "Slack Socket Mode connected for '%s'",
                self.wrapper.config.name,
            )

            # Keep the connection alive
            while self._running:
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.debug("Socket Mode connection cancelled")
            raise
        except Exception as exc:
            logger.error(
                "Socket Mode connection error for '%s': %s",
                self.wrapper.config.name,
                exc,
                exc_info=True,
            )
            raise
        finally:
            await self._disconnect()

    async def stop(self) -> None:
        """Disconnect from Slack."""
        if not self._running:
            return

        self._running = False
        await self._disconnect()

    async def _disconnect(self) -> None:
        """Internal method to disconnect the client."""
        try:
            await self.client.disconnect()
            logger.info(
                "Slack Socket Mode disconnected for '%s'",
                self.wrapper.config.name,
            )
        except Exception as exc:
            logger.debug("Error during Socket Mode disconnect: %s", exc)

    async def _handle_request(self, client: Any, req: Any) -> None:
        """Route Socket Mode requests to appropriate handlers.

        This is called for every incoming Socket Mode request.
        We must acknowledge immediately (equivalent to HTTP 200).

        Args:
            client: The SocketModeClient instance.
            req: The SocketModeRequest containing the event data.
        """
        from slack_sdk.socket_mode.response import SocketModeResponse

        # Acknowledge immediately (equivalent to HTTP 200)
        response = SocketModeResponse(envelope_id=req.envelope_id)
        await client.send_socket_mode_response(response)

        # Route based on request type
        if req.type == "events_api":
            await self._handle_event(req.payload)
        elif req.type == "slash_commands":
            await self._handle_slash_command(req.payload)
        elif req.type == "interactive":
            await self._handle_interactive(req.payload)
        else:
            logger.debug("Unhandled Socket Mode request type: %s", req.type)

    async def _handle_event(self, payload: Dict[str, Any]) -> None:
        """Process events_api payloads.

        Args:
            payload: The event payload from Slack.
        """
        event = payload.get("event", {})
        event_type = event.get("type")

        # Deduplication - use the wrapper's deduplicator
        event_id = payload.get("event_id")
        if self.wrapper._dedup.is_duplicate(event_id):
            logger.debug("Duplicate event ignored: %s", event_id)
            return

        # Handle Agents & AI Apps events if assistant mode is enabled
        if hasattr(self.wrapper, '_assistant_handler') and self.wrapper._assistant_handler:
            if event_type == "assistant_thread_started":
                task = asyncio.create_task(
                    self.wrapper._assistant_handler.handle_thread_started(event, payload)
                )
                self.wrapper._background_tasks.add(task)
                task.add_done_callback(self.wrapper._background_tasks.discard)
                return

            if event_type == "assistant_thread_context_changed":
                task = asyncio.create_task(
                    self.wrapper._assistant_handler.handle_context_changed(event)
                )
                self.wrapper._background_tasks.add(task)
                task.add_done_callback(self.wrapper._background_tasks.discard)
                return

            # Handle DM messages in assistant mode
            if event_type == "message" and event.get("channel_type") == "im":
                # Skip bot messages
                if not event.get("subtype") and not event.get("bot_id"):
                    task = asyncio.create_task(
                        self.wrapper._assistant_handler.handle_user_message(event)
                    )
                    self.wrapper._background_tasks.add(task)
                    task.add_done_callback(self.wrapper._background_tasks.discard)
                    return

        # Skip non-message events
        if event_type not in {"app_mention", "message"}:
            return

        # Skip bot messages (including our own)
        if event.get("subtype") == "bot_message" or event.get("bot_id"):
            return

        # Check channel authorization
        channel = event.get("channel")
        if not channel or not self.wrapper._is_authorized(channel):
            return

        text = (event.get("text") or "").strip()
        user = event.get("user") or "unknown"
        thread_ts = event.get("thread_ts") or event.get("ts")
        files = event.get("files")
        session_id = f"{channel}:{user}"

        # Process in background using the wrapper's safe_answer
        task = asyncio.create_task(
            self.wrapper._safe_answer(
                channel=channel,
                user=user,
                text=text,
                thread_ts=thread_ts,
                session_id=session_id,
                files=files,
            )
        )
        # Track the task for graceful shutdown
        self.wrapper._background_tasks.add(task)
        task.add_done_callback(self.wrapper._background_tasks.discard)

    async def _handle_slash_command(self, payload: Dict[str, Any]) -> None:
        """Process slash command payloads.

        Args:
            payload: The slash command payload from Slack.
        """
        channel = payload.get("channel_id", "")
        user = payload.get("user_id", "unknown")
        text = (payload.get("text") or "").strip()
        response_url = payload.get("response_url")

        # Check channel authorization
        if channel and not self.wrapper._is_authorized(channel):
            if response_url:
                await self._send_response(
                    response_url,
                    {"response_type": "ephemeral", "text": "Unauthorized channel."},
                )
            return

        # Handle built-in commands
        if text.lower() in {"help", "/help"}:
            if response_url:
                await self._send_response(
                    response_url,
                    {"response_type": "ephemeral", "text": self.wrapper._help_text()},
                )
            return

        if text.lower() in {"clear", "/clear"}:
            self.wrapper.conversations.pop(f"{channel}:{user}", None)
            if response_url:
                await self._send_response(
                    response_url,
                    {"response_type": "ephemeral", "text": "Conversation cleared."},
                )
            return

        if text.lower() in {"commands", "/commands"}:
            if response_url:
                await self._send_response(
                    response_url,
                    {
                        "response_type": "ephemeral",
                        "text": "Available commands: help, clear, commands",
                    },
                )
            return

        # Process in background using the wrapper's safe_answer
        task = asyncio.create_task(
            self.wrapper._safe_answer(
                channel=channel,
                user=user,
                text=text,
                thread_ts=None,
                session_id=f"{channel}:{user}",
            )
        )
        # Track the task for graceful shutdown
        self.wrapper._background_tasks.add(task)
        task.add_done_callback(self.wrapper._background_tasks.discard)

    async def _handle_interactive(self, payload: Dict[str, Any]) -> None:
        """Route interactive payloads to handler.

        Args:
            payload: The interactive payload from Slack (buttons, menus, modals).
        """
        # Check if wrapper has an interactive handler
        if hasattr(self.wrapper, "_interactive_handler"):
            handler = getattr(self.wrapper, "_interactive_handler")
            if handler:
                await handler.handle(payload)
        else:
            logger.debug(
                "Interactive payload received but no handler configured: %s",
                payload.get("type"),
            )

    async def _send_response(self, response_url: str, body: Dict[str, Any]) -> None:
        """Send a response to a Slack response_url.

        Args:
            response_url: The Slack response URL.
            body: The response body to send.
        """
        try:
            async with ClientSession() as session:
                async with session.post(response_url, json=body) as resp:
                    if resp.status >= 400:
                        logger.warning(
                            "Failed to send response to Slack: %s",
                            await resp.text(),
                        )
        except Exception as exc:
            logger.error("Error sending response to Slack: %s", exc)
