"""
WhatsApp Agent Wrapper.

Connects WhatsApp messages to AI-Parrot agents via Meta's Cloud API.
Uses pywa library in custom server mode with aiohttp webhook handlers.

Supports:
- Direct messages (private chats)
- Group messages with @mentions
- Text, image, and document responses
- Per-user conversation memory
- 24-hour messaging window tracking
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional, TYPE_CHECKING

from aiohttp import web
from pywa import WhatsApp
from pywa.handlers import MessageHandler as PyWaMessageHandler
from pywa.types import Message as WhatsAppMessage, MessageType

from .models import WhatsAppAgentConfig
from .handler import WhatsAppUserSession
from .utils import convert_markdown_to_whatsapp, split_message, sanitize_phone_number
from ..parser import parse_response, ParsedResponse
from ...models.outputs import OutputMode

if TYPE_CHECKING:
    from ...bots.abstract import AbstractBot
    from ...memory import ConversationMemory


_executor = ThreadPoolExecutor(max_workers=4)


class WhatsAppAgentWrapper:
    """
    Wraps an AI-Parrot Agent for WhatsApp integration.

    Features:
    - Webhook-based message reception (GET verification + POST updates)
    - Per-user conversation memory via WhatsAppUserSession
    - WhatsApp-compatible markdown formatting
    - Message splitting for long responses
    - Image and document sending
    - Phone number allowlist authorization
    - 24-hour messaging window tracking
    """

    def __init__(
        self,
        agent: 'AbstractBot',
        config: WhatsAppAgentConfig,
        app: web.Application,
    ):
        self.agent = agent
        self.config = config
        self.app = app
        self.logger = logging.getLogger(f"WhatsAppWrapper.{config.name}")

        # Per-user sessions (keyed by wa_id / phone number)
        self.sessions: Dict[str, WhatsAppUserSession] = {}

        # Initialize pywa client in custom server mode
        self.wa = WhatsApp(
            phone_id=config.phone_id,
            token=config.token,
            server=None,  # Custom server mode — we handle routes via aiohttp
            verify_token=config.verify_token,
            app_id=config.app_id,
            app_secret=config.app_secret,
            validate_updates=bool(config.app_secret),
        )

        # Register pywa message handler (sync callback — pywa requirement)
        self.wa.add_handlers(
            PyWaMessageHandler(
                callback=self._on_message,
            )
        )

        # Register aiohttp webhook routes
        safe_id = config.chatbot_id.replace(' ', '_').lower()
        self.route = config.webhook_path or f"/api/whatsapp/{safe_id}/webhook"

        # GET for Meta verification challenge
        app.router.add_get(self.route, self._handle_verify)
        # POST for incoming message webhooks
        app.router.add_post(self.route, self._handle_webhook)
        self.logger.info(f"Registered WhatsApp webhook at {self.route}")

        # Exclude route from auth middleware (same pattern as MS Teams)
        if auth := app.get("auth"):
            auth.add_exclude_list(self.route)
            self.logger.info(f"Excluded {self.route} from auth middleware")

    # =========================================================================
    # Webhook Handlers (aiohttp routes)
    # =========================================================================

    async def _handle_verify(self, request: web.Request) -> web.Response:
        """
        Handle GET webhook verification challenge from Meta.

        Meta sends:
            GET /webhook?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=<challenge>

        We must return the challenge string if the verify_token matches.
        """
        vt = request.query.get("hub.verify_token")
        ch = request.query.get("hub.challenge")
        self.logger.info(f"Webhook verification request: verify_token={'***' if vt else 'None'}")

        response_text, status_code = self.wa.webhook_challenge_handler(vt=vt, ch=ch)
        return web.Response(
            text=response_text,
            status=status_code,
            content_type="text/plain",
        )

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        """
        Handle POST webhook updates from Meta.

        Meta sends message events as JSON with X-Hub-Signature-256 header
        for payload validation.
        """
        body = await request.read()
        hmac_header = request.headers.get("X-Hub-Signature-256")

        # Delegate to pywa for signature validation + handler dispatch
        # This is synchronous — pywa calls _on_message synchronously
        loop = asyncio.get_event_loop()
        response_text, status_code = await loop.run_in_executor(
            _executor,
            lambda: self.wa.webhook_update_handler(
                update=body, hmac_header=hmac_header
            )
        )
        return web.Response(
            text=response_text,
            status=status_code,
            content_type="text/plain",
        )

    # =========================================================================
    # pywa Message Callback (sync, bridged to async)
    # =========================================================================

    def _on_message(self, client: WhatsApp, message: WhatsAppMessage) -> None:
        """
        Sync callback invoked by pywa when a message is received.

        pywa's sync client requires sync callbacks. We bridge to async
        by scheduling _process_message as a task on the running event loop.
        """
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(self._process_message(client, message))
        except RuntimeError:
            self.logger.error("No running event loop to schedule message processing")

    # =========================================================================
    # Async Message Processing
    # =========================================================================

    async def _process_message(
        self, client: WhatsApp, message: WhatsAppMessage
    ) -> None:
        """
        Process an incoming WhatsApp message through the AI-Parrot agent.

        Flow:
        1. Extract sender and message text
        2. Check authorization (allowed_numbers)
        3. Get/create user session with conversation memory
        4. Mark message as read (typing indicator)
        5. Call agent.ask() with conversation memory
        6. Parse and send formatted response
        """
        sender = message.from_user.wa_id
        msg_type = message.type

        # Extract text content based on message type
        text = self._extract_text(message)
        if not text:
            self.logger.debug(f"Ignoring non-text message from {sender} (type: {msg_type})")
            return

        # Authorization check
        if not self._is_authorized(sender):
            self.logger.info(f"Unauthorized message from {sender}")
            return

        # Get or create user session
        session = self._get_or_create_session(sender)
        session.touch()

        # Mark message as read (shows blue checkmarks to user)
        try:
            await asyncio.get_event_loop().run_in_executor(
                _executor, message.mark_as_read
            )
        except Exception as e:
            self.logger.debug(f"Failed to mark message as read: {e}")

        try:
            self.logger.info(f"Processing message from {sender}: {text[:50]}...")

            # Call the AI-Parrot agent
            response = await self.agent.ask(
                text,
                memory=session.conversation_memory,
                output_mode=OutputMode.WHATSAPP,
                session_id=sender,
                user_id=sender,
            )

            # Parse the agent response
            parsed = parse_response(response)

            # Send the formatted response back to WhatsApp
            await self._send_parsed_response(sender, parsed, client)

        except Exception as e:
            self.logger.error(
                f"Error processing message from {sender}: {e}",
                exc_info=True
            )
            try:
                await asyncio.get_event_loop().run_in_executor(
                    _executor,
                    lambda: client.send_message(
                        to=sender,
                        text="Sorry, I encountered an error processing your request. Please try again.",
                    )
                )
            except Exception:
                self.logger.error("Failed to send error message", exc_info=True)

    # =========================================================================
    # Response Sending
    # =========================================================================

    async def _send_parsed_response(
        self, to: str, parsed: ParsedResponse, client: WhatsApp
    ) -> None:
        """
        Send a parsed response to a WhatsApp user.

        Handles text (with markdown conversion and splitting), images,
        documents, code blocks, and tables.
        """
        loop = asyncio.get_event_loop()
        text_parts = []

        # Collect text content
        if parsed.text:
            text_parts.append(parsed.text)

        # Add code block if present
        if parsed.has_code:
            lang = parsed.code_language or ""
            code_block = f"```{lang}\n{parsed.code}\n```"
            text_parts.append(code_block)

        # Add table as text (WhatsApp has no native table support)
        if parsed.has_table and parsed.table_markdown:
            text_parts.append(f"```\n{parsed.table_markdown}\n```")

        # Send text messages
        if text_parts:
            full_text = "\n\n".join(text_parts)
            wa_text = convert_markdown_to_whatsapp(full_text)

            for chunk in split_message(wa_text, self.config.max_message_length):
                try:
                    await loop.run_in_executor(
                        _executor,
                        lambda c=chunk: client.send_message(to=to, text=c)
                    )
                except Exception as e:
                    self.logger.error(f"Failed to send text message to {to}: {e}")

        # Send images
        for image_path in parsed.images:
            try:
                await loop.run_in_executor(
                    _executor,
                    lambda p=image_path: client.send_image(
                        to=to, image=str(p)
                    )
                )
            except Exception as e:
                self.logger.error(f"Failed to send image to {to}: {e}")

        # Send charts as images
        if parsed.has_charts:
            for chart in parsed.charts:
                try:
                    chart_source = chart.public_url or str(chart.path)
                    await loop.run_in_executor(
                        _executor,
                        lambda src=chart_source: client.send_image(
                            to=to,
                            image=src,
                            caption=chart.title or None,
                        )
                    )
                except Exception as e:
                    self.logger.error(f"Failed to send chart to {to}: {e}")

        # Send documents
        for doc_path in parsed.documents:
            try:
                await loop.run_in_executor(
                    _executor,
                    lambda p=doc_path: client.send_document(
                        to=to,
                        document=str(p),
                        filename=p.name,
                    )
                )
            except Exception as e:
                self.logger.error(f"Failed to send document to {to}: {e}")

    # =========================================================================
    # Helpers
    # =========================================================================

    def _extract_text(self, message: WhatsAppMessage) -> Optional[str]:
        """Extract text content from a WhatsApp message."""
        if message.type == MessageType.TEXT and message.text:
            return message.text
        if message.caption:
            return message.caption
        return None

    def _is_authorized(self, wa_id: str) -> bool:
        """Check if a phone number is authorized to use this bot."""
        if self.config.allowed_numbers is None:
            return True
        cleaned = sanitize_phone_number(wa_id)
        return cleaned in [
            sanitize_phone_number(n) for n in self.config.allowed_numbers
        ]

    def _get_or_create_session(self, phone_number: str) -> WhatsAppUserSession:
        """Get or create a user session with conversation memory."""
        if phone_number not in self.sessions:
            from ...memory import InMemoryConversation
            self.sessions[phone_number] = WhatsAppUserSession(
                phone_number=phone_number,
                conversation_memory=InMemoryConversation(),
            )
        return self.sessions[phone_number]

    def clear_session(self, phone_number: str) -> None:
        """Clear a user's conversation session."""
        if phone_number in self.sessions:
            del self.sessions[phone_number]
