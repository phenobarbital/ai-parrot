"""WhatsApp Bridge Agent Wrapper.

Connects AI-Parrot agents to WhatsApp via the Go whatsmeow bridge.
The bridge POSTs incoming messages to a webhook; this wrapper processes
them through the agent and replies via the bridge's /send endpoint.

Architecture::

    WhatsApp ─► Go Bridge ─(HTTP POST)─► WhatsAppBridgeWrapper
                                               │
                                          agent.ask()
                                               │
    WhatsApp ◄─ Go Bridge ◄─(POST /send)──────┘
"""
import asyncio
import json
import logging
from typing import Dict, Optional, TYPE_CHECKING

import aiohttp
from aiohttp import web

from .bridge_config import WhatsAppBridgeConfig
from .handler import WhatsAppUserSession
from .utils import convert_markdown_to_whatsapp, split_message
from ..parser import parse_response, ParsedResponse
from ...models.outputs import OutputMode

if TYPE_CHECKING:
    from ...bots.abstract import AbstractBot
    from ...memory import ConversationMemory


class WhatsAppBridgeWrapper:
    """Wraps an AI-Parrot Agent for WhatsApp Bridge integration.

    Features:
    - Webhook endpoint receives messages from the Go bridge
    - Per-phone conversation memory (like Telegram per-chat)
    - Calls agent.ask() directly — no Redis intermediary
    - Replies via bridge's HTTP /send endpoint
    - Phone allowlist, /clear and /help commands

    Usage::

        wrapper = WhatsAppBridgeWrapper(
            agent=my_agent,
            config=WhatsAppBridgeConfig(
                name="helper",
                chatbot_id="HelperAgent",
                bridge_url="http://localhost:8765",
            ),
            app=aiohttp_app,
        )
    """

    def __init__(
        self,
        agent: "AbstractBot",
        config: WhatsAppBridgeConfig,
        app: web.Application,
    ) -> None:
        self.agent = agent
        self.config = config
        self.app = app
        self.logger = logging.getLogger(f"WhatsAppBridge.{config.name}")

        # Per-phone sessions (keyed by phone number string)
        self.sessions: Dict[str, WhatsAppUserSession] = {}

        # Register aiohttp webhook route
        safe_id = config.chatbot_id.replace(" ", "_").lower()
        self.route = config.webhook_path or f"/api/whatsapp/{safe_id}/webhook"
        app.router.add_post(self.route, self._handle_webhook)
        self.logger.info(f"Registered WhatsApp Bridge webhook at {self.route}")

        # Exclude route from auth middleware
        if auth := app.get("auth"):
            auth.add_exclude_list(self.route)

    # ── Webhook Handler ──────────────────────────────────────────────

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        """Handle POST from the Go bridge with an incoming message."""
        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response(
                {"error": "Invalid JSON"}, status=400
            )

        # Fire-and-forget so the bridge doesn't time out
        asyncio.create_task(self._process_message(data))
        return web.json_response({"status": "ok"})

    # ── Message Processing ───────────────────────────────────────────

    async def _process_message(self, data: dict) -> None:
        """Process an incoming WhatsApp message through the agent.

        Flow:
        1. Extract phone and text from bridge payload
        2. Check authorization
        3. Handle slash commands (/clear, /help)
        4. Get/create session with conversation memory
        5. Call agent.ask()
        6. Format and send response back via bridge
        """
        from_phone: str = data.get("from", "")
        content: str = data.get("content", "")
        msg_type: str = data.get("type", "text")
        from_name: str = data.get("from_name", from_phone)

        if not from_phone or not content:
            return

        # Only text messages
        if msg_type != "text":
            self.logger.debug(
                f"Ignoring non-text message from {from_phone} (type: {msg_type})"
            )
            return

        # Authorization check
        if not self._is_authorized(from_phone):
            self.logger.info(f"Unauthorized message from {from_phone}")
            return

        # Handle built-in commands
        content_lower = content.strip().lower()
        if content_lower == "/clear":
            self.clear_session(from_phone)
            await self._send_text(from_phone, "✅ Conversation cleared.")
            return

        if content_lower == "/help":
            await self._send_help(from_phone)
            return

        # Get or create session
        session = self._get_or_create_session(from_phone)
        session.touch()

        # Send welcome message on first contact
        if session.message_count == 1 and self.config.welcome_message:
            await self._send_text(from_phone, self.config.welcome_message)

        try:
            self.logger.info(
                f"📱 Processing from {from_name} ({from_phone}): "
                f"'{content[:50]}...'"
            )

            # Call the agent
            response = await self.agent.ask(
                content,
                memory=session.conversation_memory,
                output_mode=OutputMode.WHATSAPP,
                session_id=from_phone,
                user_id=from_phone,
            )

            # Parse and send formatted response
            parsed = parse_response(response)
            await self._send_parsed_response(from_phone, parsed)

        except Exception as exc:
            self.logger.error(
                f"Error processing message from {from_phone}: {exc}",
                exc_info=True,
            )
            await self._send_text(
                from_phone,
                "Sorry, I encountered an error processing your request. "
                "Please try again.",
            )

    # ── Response Sending ─────────────────────────────────────────────

    async def _send_parsed_response(
        self, phone: str, parsed: ParsedResponse
    ) -> None:
        """Format and send a parsed response via the bridge."""
        text_parts = []

        if parsed.text:
            text_parts.append(parsed.text)

        if parsed.has_code:
            lang = parsed.code_language or ""
            text_parts.append(f"```{lang}\n{parsed.code}\n```")

        if parsed.has_table and parsed.table_markdown:
            text_parts.append(f"```\n{parsed.table_markdown}\n```")

        if text_parts:
            full_text = "\n\n".join(text_parts)
            wa_text = convert_markdown_to_whatsapp(full_text)

            for chunk in split_message(
                wa_text, self.config.max_message_length
            ):
                await self._send_text(phone, chunk)

    async def _send_text(self, phone: str, message: str) -> bool:
        """Send a text message via the Go bridge's /send endpoint."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.config.bridge_url}/send",
                    json={"phone": phone, "message": message},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get("success"):
                            return True
                        self.logger.error(
                            f"Bridge error: {result.get('error')}"
                        )
                        return False
                    self.logger.error(
                        f"Bridge returned status {resp.status}"
                    )
                    return False
        except Exception as exc:
            self.logger.error(f"Failed to send WhatsApp message: {exc}")
            return False

    async def _send_help(self, phone: str) -> None:
        """Send available commands help text."""
        help_text = (
            f"*{self.config.name}* — WhatsApp Agent\n\n"
            "Available commands:\n"
            "• /help — Show this message\n"
            "• /clear — Reset conversation memory\n"
        )

        # Add custom commands
        for cmd, description in self.config.commands.items():
            help_text += f"• /{cmd} — {description}\n"

        help_text += "\nSend any text to chat with the agent."
        await self._send_text(phone, help_text)

    # ── Session & Auth ───────────────────────────────────────────────

    def _is_authorized(self, phone: str) -> bool:
        """Check if a phone number is authorized."""
        if not self.config.allowed_numbers:
            return True
        return phone in self.config.allowed_numbers

    def _get_or_create_session(
        self, phone_number: str
    ) -> WhatsAppUserSession:
        """Get or create a user session with conversation memory."""
        if phone_number not in self.sessions:
            from ...memory import InMemoryConversation

            memory = InMemoryConversation()
            self.sessions[phone_number] = WhatsAppUserSession(
                phone_number=phone_number,
                conversation_memory=memory,
            )
        return self.sessions[phone_number]

    def clear_session(self, phone_number: str) -> None:
        """Clear a user's conversation session."""
        if phone_number in self.sessions:
            del self.sessions[phone_number]
