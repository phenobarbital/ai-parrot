"""CrewAgentWrapper — per-agent message handler for crew context.

Bridges an AI-Parrot agent with the Telegram crew protocol.
Handles @mention routing, silent tool call execution, @mention-tagged
responses, document send/receive, typing indicators, and status
updates to the coordinator.

Uses composition (NOT inheritance) from TelegramAgentWrapper.
"""
import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from aiogram import Bot, Router
from aiogram.enums import ChatAction
from aiogram.types import Message, FSInputFile

from .agent_card import AgentCard
from .coordinator import CoordinatorBot
from .mention import format_reply, mention_from_username
from .payload import DataPayload
from ..filters import BotMentionedFilter
from ..utils import extract_query_from_mention
from ...parser import parse_response, ParsedResponse
from ....models.outputs import OutputMode

if TYPE_CHECKING:
    from ....bots.abstract import AbstractBot

logger = logging.getLogger(__name__)

# Telegram message length limit
_MAX_MESSAGE_LENGTH = 4096

# Rate limit delay between consecutive sends (seconds)
_SEND_DELAY = 0.3


def _chunk_text(text: str, max_length: int = _MAX_MESSAGE_LENGTH) -> list[str]:
    """Split text into chunks under *max_length*, preserving word boundaries.

    Args:
        text: The text to split.
        max_length: Maximum length per chunk.

    Returns:
        List of text chunks, each under *max_length* characters.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        # If a single line exceeds max_length, split at word boundary
        if len(line) > max_length:
            if current:
                chunks.append(current)
                current = ""
            while len(line) > max_length:
                split_at = line.rfind(" ", 0, max_length)
                if split_at == -1:
                    split_at = max_length
                chunks.append(line[:split_at])
                line = line[split_at:].lstrip()
            if line:
                current = line
            continue

        if len(current) + len(line) + 1 > max_length:
            if current:
                chunks.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line

    if current:
        chunks.append(current)
    return chunks


class CrewAgentWrapper:
    """Per-agent wrapper that handles @mention messages in a crew supergroup.

    Responsibilities:
    - Registers aiogram handlers for @mention and document messages.
    - Routes incoming queries to the agent via ``agent.ask()``.
    - Prefixes every response with the sender's @mention.
    - Sends typing indicator while the agent processes.
    - Notifies the :class:`CoordinatorBot` of busy/ready status transitions.
    - Chunks long messages to stay under Telegram's 4096-char limit.
    - Downloads documents via :class:`DataPayload` and passes them to the agent.

    Args:
        bot: The aiogram ``Bot`` instance for this agent.
        agent: An AI-Parrot agent (``AbstractBot`` subclass).
        card: The ``AgentCard`` describing this agent.
        group_id: Telegram supergroup chat ID.
        coordinator: The ``CoordinatorBot`` managing the pinned registry.
        config: Optional dict with extra configuration overrides.
        payload: Optional :class:`DataPayload` for file handling.
    """

    def __init__(
        self,
        bot: Bot,
        agent: "AbstractBot",
        card: AgentCard,
        group_id: int,
        coordinator: CoordinatorBot,
        config: Optional[dict] = None,
        payload: Optional[DataPayload] = None,
    ) -> None:
        self.bot = bot
        self.agent = agent
        self.card = card
        self.group_id = group_id
        self.coordinator = coordinator
        self.config = config or {}
        self.payload = payload
        self.router = Router()
        self.logger = logging.getLogger(
            f"{__name__}.{card.telegram_username}"
        )
        self._register_handlers()

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def _register_handlers(self) -> None:
        """Register aiogram message handlers on the router."""
        # @mention handler for text messages in groups/supergroups
        self.router.message.register(
            self._handle_mention,
            BotMentionedFilter(),
        )

        # Document handler for file messages directed at this bot
        # (documents in the group — we process all, the coordinator
        #  or transport layer can add additional filtering if needed)
        self.router.message.register(
            self._handle_document,
            lambda message: message.document is not None,
        )

    # ------------------------------------------------------------------
    # Mention handler
    # ------------------------------------------------------------------

    async def _handle_mention(self, message: Message) -> None:
        """Process an @mention message, route to the agent, and reply.

        Steps:
        1. Extract the query text (strip @mention and /command).
        2. Send typing indicator.
        3. Notify coordinator: busy.
        4. Call ``agent.ask()`` with ``OutputMode.TELEGRAM``.
        5. Parse the response and send chunked reply with sender @mention.
        6. Notify coordinator: ready.
        """
        query = await extract_query_from_mention(message, self.bot)
        if not query:
            return  # Empty mention — ignore silently

        sender_mention = self._get_sender_mention(message)
        chat_id = message.chat.id

        # Start typing indicator
        typing_task = asyncio.create_task(
            self._typing_indicator(chat_id)
        )

        try:
            # Notify coordinator: busy
            await self.coordinator.on_agent_status_change(
                self.card.telegram_username,
                "busy",
                query[:60],
            )

            # Call the agent (tool calls happen silently — not published)
            response = await self.agent.ask(
                query,
                output_mode=OutputMode.TELEGRAM,
            )

            # Parse the response
            parsed = parse_response(response)

            # Stop typing before sending
            typing_task.cancel()

            # Send text response with sender mention prefix
            await self._send_response(
                chat_id, parsed, sender_mention, message.message_id
            )

        except Exception as e:
            typing_task.cancel()
            self.logger.error(
                "Error processing mention from %s: %s",
                sender_mention, e,
                exc_info=True,
            )
            error_text = format_reply(
                sender_mention,
                "Sorry, I encountered an error processing your request.",
            )
            await self.bot.send_message(
                chat_id=chat_id,
                text=error_text,
                reply_to_message_id=message.message_id,
            )
        finally:
            typing_task.cancel()
            # Notify coordinator: ready
            try:
                await self.coordinator.on_agent_status_change(
                    self.card.telegram_username, "ready"
                )
            except Exception:
                pass  # Best effort

    # ------------------------------------------------------------------
    # Document handler
    # ------------------------------------------------------------------

    async def _handle_document(self, message: Message) -> None:
        """Download a document and pass it to the agent for processing.

        Uses :class:`DataPayload` for download and validation.
        """
        if self.payload is None:
            self.logger.debug("No DataPayload configured — ignoring document")
            return

        sender_mention = self._get_sender_mention(message)
        chat_id = message.chat.id
        caption = message.caption or "Analyze this document"

        typing_task = asyncio.create_task(
            self._typing_indicator(chat_id)
        )

        try:
            # Notify coordinator: busy
            await self.coordinator.on_agent_status_change(
                self.card.telegram_username,
                "busy",
                "processing document",
            )

            # Download the document
            file_path = await self.payload.download_document(
                self.bot, message
            )
            if file_path is None:
                typing_task.cancel()
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=format_reply(
                        sender_mention,
                        "Could not download the document.",
                    ),
                    reply_to_message_id=message.message_id,
                )
                return

            # Call the agent with the file context
            query = f"{caption}\n\n[Document: {file_path}]"
            response = await self.agent.ask(
                query,
                output_mode=OutputMode.TELEGRAM,
            )

            parsed = parse_response(response)
            typing_task.cancel()

            await self._send_response(
                chat_id, parsed, sender_mention, message.message_id
            )

            # Cleanup the downloaded file
            self.payload.cleanup_file(file_path)

        except Exception as e:
            typing_task.cancel()
            self.logger.error(
                "Error processing document: %s", e, exc_info=True
            )
            error_text = format_reply(
                sender_mention,
                "Sorry, I couldn't process that document.",
            )
            await self.bot.send_message(
                chat_id=chat_id,
                text=error_text,
                reply_to_message_id=message.message_id,
            )
        finally:
            typing_task.cancel()
            try:
                await self.coordinator.on_agent_status_change(
                    self.card.telegram_username, "ready"
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Response sending
    # ------------------------------------------------------------------

    async def _send_response(
        self,
        chat_id: int,
        parsed: ParsedResponse,
        sender_mention: str,
        reply_to_message_id: Optional[int] = None,
    ) -> None:
        """Send a parsed response to the group with sender @mention prefix.

        Long text is chunked under 4096 characters. Attachments (images,
        documents, media) are sent as separate messages.

        Args:
            chat_id: Target chat ID.
            parsed: The parsed agent response.
            sender_mention: The @mention of the original sender.
            reply_to_message_id: Optional message to reply to.
        """
        # Build text from parsed response
        text = parsed.text or ""
        if text:
            full_text = format_reply(sender_mention, text)
        else:
            full_text = sender_mention

        # Send text chunks
        chunks = _chunk_text(full_text)
        for i, chunk in enumerate(chunks):
            await self.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                reply_to_message_id=reply_to_message_id if i == 0 else None,
            )
            if i < len(chunks) - 1:
                await asyncio.sleep(_SEND_DELAY)

        # Send attachments (images)
        for image_path in parsed.images:
            try:
                await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=FSInputFile(image_path),
                    caption=image_path.name[:200],
                )
                await asyncio.sleep(_SEND_DELAY)
            except Exception as e:
                self.logger.error("Failed to send image %s: %s", image_path, e)

        # Send documents
        for doc_path in parsed.documents:
            try:
                await self.bot.send_document(
                    chat_id=chat_id,
                    document=FSInputFile(doc_path),
                    caption=doc_path.name[:200],
                )
                await asyncio.sleep(_SEND_DELAY)
            except Exception as e:
                self.logger.error("Failed to send document %s: %s", doc_path, e)

        # Send media (videos, audio)
        for media_path in parsed.media:
            try:
                await self.bot.send_document(
                    chat_id=chat_id,
                    document=FSInputFile(media_path),
                )
                await asyncio.sleep(_SEND_DELAY)
            except Exception as e:
                self.logger.error("Failed to send media %s: %s", media_path, e)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_sender_mention(message: Message) -> str:
        """Extract sender @mention from a Telegram message.

        Falls back to a display name if no username is set.

        Args:
            message: The incoming Telegram message.

        Returns:
            An @mention string for the sender.
        """
        if message.from_user and message.from_user.username:
            return mention_from_username(message.from_user.username)
        if message.from_user:
            name = message.from_user.full_name or f"User {message.from_user.id}"
            return name
        return "User"

    async def _typing_indicator(self, chat_id: int) -> None:
        """Background task that sends typing indicator every 4 seconds."""
        try:
            while True:
                await self.bot.send_chat_action(
                    chat_id=chat_id, action=ChatAction.TYPING
                )
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
