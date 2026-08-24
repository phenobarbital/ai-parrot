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
from typing import TYPE_CHECKING, Dict

import aiohttp
from aiohttp import web

from ...models.outputs import OutputMode
from ..parser import ParsedResponse, parse_response
from .bridge_config import WhatsAppBridgeConfig, normalize_phone_number
from .handler import WhatsAppUserSession
from .utils import convert_markdown_to_whatsapp, split_message

if TYPE_CHECKING:
    from ...bots.abstract import AbstractBot


def _agent_exposes_submit_operation(agent: "AbstractBot") -> bool:
    """Best-effort check: does *agent* have a registered ``BusinessAutomationToolkit``
    with at least one ``OperationKind.SUBMIT`` operation?

    Financial control (FEAT-453 TASK-2397): this decides whether an empty
    WhatsApp ``allowed_numbers`` must fail closed. ``parrot_tools`` (the
    ``ai-parrot-tools`` distribution) is not a declared dependency of
    ``ai-parrot-integrations`` — importing it is deferred here and guarded
    so a bot with no such toolkit installed is unaffected (returns
    ``False``, preserving the existing permissive default).

    Walks from the agent's ``ToolManager`` to each toolkit instance the
    same way :meth:`~parrot.tools.manager.ToolManager.cleanup_toolkits`
    already does (via ``ToolkitTool.bound_method.__self__``) rather than
    inventing a new toolkit-introspection path.
    """
    try:
        from parrot_tools.business_automation.models import OperationKind
        from parrot_tools.business_automation.toolkit import BusinessAutomationToolkit
    except ImportError:
        return False

    from ...tools.toolkit import ToolkitTool

    tool_manager = getattr(agent, "tool_manager", None)
    tools = getattr(tool_manager, "_tools", None)
    if not tools:
        return False

    seen: set = set()
    for tool in tools.values():
        if not isinstance(tool, ToolkitTool):
            continue
        bound = getattr(tool, "bound_method", None)
        toolkit = getattr(bound, "__self__", None)
        if toolkit is None or id(toolkit) in seen:
            continue
        seen.add(id(toolkit))
        if not isinstance(toolkit, BusinessAutomationToolkit):
            continue
        operations = getattr(toolkit, "_operations", None) or {}
        if any(op.kind == OperationKind.SUBMIT for op in operations.values()):
            return True
    return False


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
        # Fail-closed financial control (FEAT-453 TASK-2397): an empty
        # allowlist is a convenience for a general assistant, but for an
        # agent that can spend money / file tax-relevant records it means
        # anyone who learns the number can instruct it. Refuse to wire up
        # the webhook route at all rather than start open.
        if not config.normalized_allowed_numbers and _agent_exposes_submit_operation(agent):
            raise ValueError(
                f"WhatsAppBridgeConfig(name={config.name!r}, "
                f"chatbot_id={config.chatbot_id!r}) has an empty "
                "allowed_numbers, but the bound agent exposes at least one "
                "OperationKind.SUBMIT operation. Refusing to start "
                "(fail-closed financial control) — set allowed_numbers to a "
                "non-empty allowlist before exposing this agent over WhatsApp."
            )

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
        self.logger.warning(
            "🔔 Webhook received: %s %s (from %s)",
            request.method,
            request.path,
            request.remote,
        )
        try:
            data = await request.json()
            self.logger.info("📨 Webhook payload: %s", data)
        except json.JSONDecodeError:
            self.logger.error("❌ Invalid JSON in webhook payload")
            return web.json_response({"error": "Invalid JSON"}, status=400)

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
        from_server: str = data.get("from_server", "")
        content: str = data.get("content", "")
        msg_type: str = data.get("type", "text")
        from_name: str = data.get("from_name", from_phone)

        self.logger.info(
            "📋 Message fields: from=%r, content=%r, type=%r, name=%r",
            from_phone,
            content[:80] if content else content,
            msg_type,
            from_name,
        )

        if not from_phone or not content:
            self.logger.warning(
                "⚠️ Dropping message: from_phone=%r, content=%r (empty)",
                from_phone,
                content,
            )
            return

        # Only text messages
        if msg_type != "text":
            self.logger.warning(
                "⚠️ Ignoring non-text message from %s (type: %s)",
                from_phone,
                msg_type,
            )
            return

        # Authorization check
        if not self._is_authorized(from_phone):
            self.logger.warning(
                "🚫 Unauthorized message from %s (allowed: %s)",
                from_phone,
                self.config.allowed_numbers,
            )
            return

        # Handle built-in commands
        content_lower = content.strip().lower()
        if content_lower == "/clear":
            self.clear_session(from_phone)
            await self._send_text(from_phone, "✅ Conversation cleared.", server=from_server)
            return

        if content_lower == "/help":
            await self._send_help(from_phone, server=from_server)
            return

        # Get or create session
        self.logger.info("🔧 Creating/getting session for %s", from_phone)
        session = self._get_or_create_session(from_phone)
        session.touch()
        if from_server:
            session.jid_server = from_server

        # Send welcome message on first contact
        if session.message_count == 1 and self.config.welcome_message:
            await self._send_text(from_phone, self.config.welcome_message)

        try:
            self.logger.warning(
                "📱 Calling agent.ask() from %s (%s): '%s'",
                from_name,
                from_phone,
                content[:80],
            )

            # Call the agent
            response = await self.agent.ask(
                content,
                memory=session.conversation_memory,
                output_mode=OutputMode.WHATSAPP,
                session_id=from_phone,
                user_id=from_phone,
            )

            self.logger.warning(
                "✅ Agent response received: %s",
                str(response)[:200],
            )

            # Parse and send formatted response
            parsed = parse_response(response)
            await self._send_parsed_response(from_phone, parsed, server=from_server)

        except Exception as exc:
            self.logger.error(
                f"Error processing message from {from_phone}: {exc}",
                exc_info=True,
            )
            await self._send_text(
                from_phone,
                "Sorry, I encountered an error processing your request. " "Please try again.",
                server=from_server,
            )

    # ── Response Sending ─────────────────────────────────────────────

    async def _send_parsed_response(
        self,
        phone: str,
        parsed: ParsedResponse,
        *,
        server: str = "",
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

            for chunk in split_message(wa_text, self.config.max_message_length):
                await self._send_text(phone, chunk, server=server)

    async def _send_text(
        self,
        phone: str,
        message: str,
        *,
        server: str = "",
    ) -> bool:
        """Send a text message via the Go bridge's /send endpoint."""
        self.logger.info(
            "📤 Sending to %s (server=%s) via %s: '%s'",
            phone,
            server or "default",
            self.config.bridge_url,
            message[:100],
        )
        payload = {"phone": phone, "message": message}
        if server:
            payload["server"] = server
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.config.bridge_url}/send",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get("success"):
                            return True
                        self.logger.error(f"Bridge error: {result.get('error')}")
                        return False
                    self.logger.error(f"Bridge returned status {resp.status}")
                    return False
        except Exception as exc:
            self.logger.error("Failed to send WhatsApp message: %s", exc)
            return False

    async def _send_help(
        self,
        phone: str,
        *,
        server: str = "",
    ) -> None:
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
        await self._send_text(phone, help_text, server=server)

    # ── Session & Auth ───────────────────────────────────────────────

    def _is_authorized(self, phone: str) -> bool:
        """Check if a phone number is authorized.

        Both sides of the comparison are normalized to digits-only
        (FEAT-453 TASK-2397) — a literal string compare against
        ``allowed_numbers`` silently rejects a legitimate number formatted
        with a leading ``+`` or internal spaces/dashes.
        """
        allowed = self.config.normalized_allowed_numbers
        if not allowed:
            return True
        return normalize_phone_number(phone) in allowed

    def _get_or_create_session(self, phone_number: str) -> WhatsAppUserSession:
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
