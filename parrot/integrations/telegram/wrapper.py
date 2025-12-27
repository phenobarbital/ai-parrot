"""
Telegram Agent Wrapper.

Connects Telegram messages to AI-Parrot agents with per-chat conversation memory.
"""
import asyncio
from typing import Dict, Optional, Any, TYPE_CHECKING
from pathlib import Path
import tempfile

from aiogram import Bot, Router, F
from aiogram.types import Message, ContentType, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode, ChatAction
from navconfig.logging import logging

from .models import TelegramAgentConfig
from ..parser import parse_response, ParsedResponse
from ...models.outputs import OutputMode

if TYPE_CHECKING:
    from ...bots.abstract import AbstractBot
    from ...memory import ConversationMemory


class TelegramAgentWrapper:
    """
    Wraps an Agent/AgentCrew/AgentFlow for Telegram integration.

    Manages:
    - Per-chat conversation memory
    - Message routing from Telegram to agent
    - Response formatting for Telegram
    - File/image handling

    Attributes:
        agent: The AI-Parrot agent instance
        bot: The aiogram Bot instance
        config: Telegram configuration for this agent
        router: aiogram Router with registered handlers
        conversations: Per-chat conversation memories
    """

    def __init__(
        self,
        agent: 'AbstractBot',
        bot: Bot,
        config: TelegramAgentConfig
    ):
        self.agent = agent
        self.bot = bot
        self.config = config
        self.router = Router()
        self.conversations: Dict[int, 'ConversationMemory'] = {}
        self.logger = logging.getLogger(f"TelegramWrapper.{config.name}")

        # Register message handlers
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register aiogram message handlers on the router."""
        # /start command
        self.router.message.register(
            self.handle_start,
            CommandStart()
        )

        # /help command
        self.router.message.register(
            self.handle_help,
            Command("help")
        )

        # /clear command to reset conversation
        self.router.message.register(
            self.handle_clear,
            Command("clear")
        )

        # /call command to invoke agent methods
        self.router.message.register(
            self.handle_call,
            Command("call")
        )

        # Register custom commands from config
        for cmd_name, method_name in self.config.commands.items():
            self._register_custom_command(cmd_name, method_name)

        # All other text messages (must be last)
        self.router.message.register(
            self.handle_message,
            F.content_type == ContentType.TEXT
        )

        # Photo messages
        self.router.message.register(
            self.handle_photo,
            F.content_type == ContentType.PHOTO
        )

        # Document messages
        self.router.message.register(
            self.handle_document,
            F.content_type == ContentType.DOCUMENT
        )

    def _register_custom_command(self, cmd_name: str, method_name: str) -> None:
        """Register a custom command that calls an agent method."""
        async def custom_handler(message: Message) -> None:
            await self._execute_agent_method(message, method_name, message.text or "")

        self.router.message.register(
            custom_handler,
            Command(cmd_name)
        )
        self.logger.info(f"Registered custom command /{cmd_name} -> {method_name}()")

    def _is_authorized(self, chat_id: int) -> bool:
        """Check if chat is authorized to use this bot."""
        if self.config.allowed_chat_ids is None:
            return True
        return chat_id in self.config.allowed_chat_ids

    def _get_or_create_memory(self, chat_id: int) -> 'ConversationMemory':
        """Get or create conversation memory for a chat."""
        if chat_id not in self.conversations:
            # Use in-memory conversation storage per chat
            from ...memory import InMemoryConversation
            self.conversations[chat_id] = InMemoryConversation()
        return self.conversations[chat_id]

    async def handle_start(self, message: Message) -> None:
        """Handle /start command with welcome message."""
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        # Clear any existing conversation
        if chat_id in self.conversations:
            del self.conversations[chat_id]

        welcome = self.config.welcome_message or (
            f"👋 Hello! I'm {self.config.name}, your AI assistant.\n\n"
            f"Send me a message and I'll help you out!\n"
            f"Use /clear to reset our conversation."
        )
        await message.answer(welcome)

    async def handle_clear(self, message: Message) -> None:
        """Handle /clear command to reset conversation memory."""
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        if chat_id in self.conversations:
            del self.conversations[chat_id]

        await message.answer("🔄 Conversation cleared. Starting fresh!")

    async def handle_help(self, message: Message) -> None:
        """Handle /help command to show available commands."""
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        # Build help message
        help_text = (
            f"📚 *{self.config.name} - Help*\n\n"
            "*Built-in Commands:*\n"
            "/start - Start conversation\n"
            "/help - Show this help message\n"
            "/clear - Reset conversation memory\n"
            "/call <method> [args] - Call agent method\n"
        )

        # Add custom commands if any
        if self.config.commands:
            help_text += "\n*Custom Commands:*\n"
            for cmd_name, method_name in self.config.commands.items():
                help_text += f"/{cmd_name} - Calls {method_name}()\n"

        # List available agent methods
        callable_methods = self._get_callable_methods()
        if callable_methods:
            help_text += f"\n*Callable Methods (/call):*\n"
            for method in callable_methods[:10]:  # Limit to 10
                help_text += f"• {method}\n"
            if len(callable_methods) > 10:
                help_text += f"... and {len(callable_methods) - 10} more\n"

        await self._send_safe_message(message, help_text)

    def _get_callable_methods(self) -> list:
        """Get list of public callable methods on the agent."""
        methods = []
        for name in dir(self.agent):
            if name.startswith('_'):
                continue
            attr = getattr(self.agent, name, None)
            if callable(attr) and asyncio.iscoroutinefunction(attr):
                methods.append(name)
        return sorted(methods)

    async def handle_call(self, message: Message) -> None:
        """Handle /call command to invoke an agent method."""
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        # Parse command: /call method_name arg1 arg2 ...
        text = message.text or ""
        parts = text.split(maxsplit=2)  # ["/call", "method", "args..."]

        if len(parts) < 2:
            await message.answer(
                "Usage: /call <method_name> [arguments]\n\n"
                "Example: /call custom_report Q4 2024"
            )
            return

        method_name = parts[1]
        args_text = parts[2] if len(parts) > 2 else ""

        await self._execute_agent_method(message, method_name, args_text)

    async def _execute_agent_method(
        self,
        message: Message,
        method_name: str,
        args_text: str
    ) -> None:
        """Execute an agent method and send the result."""
        chat_id = message.chat.id

        # Check if method exists
        if not hasattr(self.agent, method_name):
            await message.answer(f"❌ Method '{method_name}' not found on agent.")
            return

        method = getattr(self.agent, method_name)
        if not callable(method):
            await message.answer(f"❌ '{method_name}' is not callable.")
            return

        # Start typing indicator
        typing_task = asyncio.create_task(self._typing_indicator(chat_id))

        try:
            self.logger.info(f"Chat {chat_id}: Calling {method_name}({args_text})")

            # Parse arguments (simple space-separated for now)
            args = args_text.split() if args_text else []

            # Call the method
            if asyncio.iscoroutinefunction(method):
                if args:
                    result = await method(*args)
                else:
                    result = await method()
            else:
                if args:
                    result = method(*args)
                else:
                    result = method()

            # Stop typing
            typing_task.cancel()

            # Format and send result using parsed response
            parsed = self._parse_response(result)
            await self._send_parsed_response(
                message, 
                parsed, 
                prefix=f"✅ *{method_name}* result:\n\n"
            )

        except Exception as e:
            typing_task.cancel()
            self.logger.error(f"Error calling {method_name}: {e}", exc_info=True)
            await message.answer(f"❌ Error calling {method_name}: {str(e)[:200]}")
        finally:
            typing_task.cancel()

    async def _typing_indicator(self, chat_id: int) -> None:
        """Background task that sends typing indicator every 4 seconds."""
        try:
            while True:
                await self.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    async def handle_message(self, message: Message) -> None:
        """
        Process incoming text message and send agent response.

        Steps:
        1. Check authorization
        2. Get/create conversation memory for this chat
        3. Call agent.ask() with the message
        4. Send response back to Telegram
        """
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        user_text = message.text
        if not user_text:
            return

        # Start continuous typing indicator
        typing_task = asyncio.create_task(self._typing_indicator(chat_id))

        try:
            # Get conversation memory
            memory = self._get_or_create_memory(chat_id)

            # Call the agent
            self.logger.info(f"Chat {chat_id}: Processing message: {user_text[:50]}...")

            response = await self.agent.ask(
                user_text,
                memory=memory,
                output_mode=OutputMode.TELEGRAM
            )

            # Parse and extract response content
            parsed = self._parse_response(response)

            # Stop typing indicator before sending response
            typing_task.cancel()

            # Send parsed response (handles text, images, documents, tables, code)
            await self._send_parsed_response(message, parsed)

        except Exception as e:
            self.logger.error(f"Error processing message: {e}", exc_info=True)
            await message.answer(
                "❌ Sorry, I encountered an error processing your request. "
                "Please try again."
            )
        finally:
            # Ensure typing indicator is stopped
            typing_task.cancel()

    async def handle_photo(self, message: Message) -> None:
        """Handle photo messages."""
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        # Get the largest photo
        photo = message.photo[-1]  # Last element is highest resolution
        caption = message.caption or "Describe this image"

        await self.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        try:
            # Download photo to temp file
            file = await self.bot.get_file(photo.file_id)
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                await self.bot.download_file(file.file_path, tmp)
                tmp_path = Path(tmp.name)

            # Get conversation memory
            memory = self._get_or_create_memory(chat_id)

            # Call agent with image (if supported)
            if hasattr(self.agent, 'ask_with_image'):
                response = await self.agent.ask_with_image(
                    caption,
                    image_path=tmp_path,
                    memory=memory
                )
            else:
                response = await self.agent.ask(
                    f"[Image received] {caption}",
                    memory=memory,
                    output_mode=OutputMode.TELEGRAM
                )

            parsed = self._parse_response(response)
            await self._send_parsed_response(message, parsed)

            # Cleanup temp file
            tmp_path.unlink(missing_ok=True)

        except Exception as e:
            self.logger.error(f"Error processing photo: {e}", exc_info=True)
            await message.answer("❌ Sorry, I couldn't process that image.")

    async def handle_document(self, message: Message) -> None:
        """Handle document messages."""
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        document = message.document
        caption = message.caption or f"Analyze this document: {document.file_name}"

        await message.answer(
            f"📄 Received document: {document.file_name}\n"
            f"Document processing is not yet fully implemented."
        )

    def _parse_response(self, response: Any) -> ParsedResponse:
        """Parse agent response into structured content."""
        return parse_response(response)

    def _extract_response_text(self, response: Any) -> str:
        """Extract text content from agent response (backward compatibility)."""
        parsed = self._parse_response(response)
        return parsed.text

    async def _send_parsed_response(
        self,
        message: Message,
        parsed: ParsedResponse,
        prefix: str = ""
    ) -> None:
        """
        Send parsed response content to Telegram.
        
        Handles text, images, documents, code blocks, and tables.
        """
        chat_id = message.chat.id
        
        # Build the text response
        text_parts = []
        
        if prefix:
            text_parts.append(prefix)
        
        if parsed.text:
            text_parts.append(parsed.text)
        
        # Add code block if present
        if parsed.has_code:
            lang = parsed.code_language or ""
            code_block = f"```{lang}\n{parsed.code}\n```"
            text_parts.append(code_block)
        
        # Add table if present (as markdown)
        if parsed.has_table and parsed.table_markdown:
            text_parts.append(parsed.table_markdown)
        
        # Send the text message
        full_text = "\n\n".join(text_parts)
        if full_text.strip():
            await self._send_long_message(message, full_text)
        
        # Send images as photos
        for image_path in parsed.images:
            try:
                await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=FSInputFile(image_path),
                    caption=image_path.name[:200] if len(parsed.images) > 1 else None
                )
                await asyncio.sleep(0.3)  # Rate limiting
            except Exception as e:
                self.logger.error(f"Failed to send image {image_path}: {e}")
        
        # Send documents
        for doc_path in parsed.documents:
            try:
                await self.bot.send_document(
                    chat_id=chat_id,
                    document=FSInputFile(doc_path),
                    caption=doc_path.name[:200]
                )
                await asyncio.sleep(0.3)  # Rate limiting
            except Exception as e:
                self.logger.error(f"Failed to send document {doc_path}: {e}")
        
        # Send media (videos, audio)
        for media_path in parsed.media:
            try:
                suffix = media_path.suffix.lower()
                if suffix in ('.mp4', '.avi', '.mov', '.webm', '.mkv'):
                    await self.bot.send_video(
                        chat_id=chat_id,
                        video=FSInputFile(media_path),
                        caption=media_path.name[:200]
                    )
                elif suffix in ('.mp3', '.wav', '.ogg', '.m4a'):
                    await self.bot.send_audio(
                        chat_id=chat_id,
                        audio=FSInputFile(media_path),
                        caption=media_path.name[:200]
                    )
                else:
                    await self.bot.send_document(
                        chat_id=chat_id,
                        document=FSInputFile(media_path)
                    )
                await asyncio.sleep(0.3)  # Rate limiting
            except Exception as e:
                self.logger.error(f"Failed to send media {media_path}: {e}")

    async def _send_long_message(
        self,
        message: Message,
        text: str,
        max_length: int = 4096
    ) -> None:
        """Send a long message, splitting if necessary."""
        if not text:
            text = "..."

        # Split into chunks if needed
        if len(text) <= max_length:
            chunks = [text]
        else:
            chunks = []
            current = ""
            for line in text.split('\n'):
                if len(current) + len(line) + 1 > max_length:
                    if current:
                        chunks.append(current)
                    current = line
                else:
                    current += ('\n' if current else '') + line
            if current:
                chunks.append(current)

        for chunk in chunks:
            await self._send_safe_message(message, chunk)
            await asyncio.sleep(0.3)  # Rate limiting

    async def _send_safe_message(self, message: Message, text: str) -> None:
        """Send a message with fallback for markdown parsing errors."""
        # Try plain text first to avoid markdown parsing issues
        try:
            await message.answer(text)
            return
        except Exception as e:
            self.logger.warning(f"Failed to send message: {e}")
            # Try with escaped text as last resort
            try:
                # Remove any problematic characters
                clean_text = text.replace('`', "'").replace('*', '').replace('_', '')
                await message.answer(clean_text[:4096])
            except Exception:
                await message.answer("I have a response but couldn't format it properly.")

    async def _send_response_files(self, message: Message, response: Any) -> None:
        """Send any file attachments from the agent response."""
        if not hasattr(response, 'files'):
            return

        files = response.files or []
        for file_path in files:
            path = Path(file_path)
            if not path.exists():
                continue

            # Determine file type and send appropriately
            suffix = path.suffix.lower()
            if suffix in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
                from aiogram.types import FSInputFile
                await message.answer_photo(FSInputFile(path))
            else:
                from aiogram.types import FSInputFile
                await message.answer_document(FSInputFile(path))
