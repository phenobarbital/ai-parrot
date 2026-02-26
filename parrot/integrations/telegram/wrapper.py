"""
Telegram Agent Wrapper.

Connects Telegram messages to AI-Parrot agents with per-chat conversation memory.
Supports:
- Direct messages (private chats)
- Group messages with @mentions
- Group commands (/ask)
- Channel posts (optional)
"""
from typing import Dict, Any, Optional, TYPE_CHECKING, Callable
from pathlib import Path
import asyncio
import tempfile
import re
import json
import markdown2
from aiogram import Bot, Router, F
from aiogram.types import (
    Message, ContentType, FSInputFile, BotCommand,
    ReplyKeyboardMarkup, ReplyKeyboardRemove,
    KeyboardButton, WebAppInfo,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatAction, ChatType
from navconfig.logging import logging
from .callbacks import (
    CallbackRegistry,
    CallbackContext,
    CallbackResult
)
from .models import TelegramAgentConfig
from .auth import TelegramUserSession, NavigatorAuthClient
from .filters import BotMentionedFilter
from .utils import extract_query_from_mention
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
        config: TelegramAgentConfig,
        agent_commands: list = None,
    ):
        self.agent = agent
        self.bot = bot
        self.config = config
        self.router = Router()
        self.conversations: Dict[int, 'ConversationMemory'] = {}
        self.logger = logging.getLogger(f"TelegramWrapper.{config.name}")

        # Agent-declared commands (from @telegram_command decorator)
        self._agent_commands: list = agent_commands or []
        # Per-user session cache (keyed by Telegram user ID)
        self._user_sessions: Dict[int, TelegramUserSession] = {}

        # Navigator auth client (if auth_url is configured)
        self._auth_client: Optional[NavigatorAuthClient] = None
        if config.auth_url:
            self._auth_client = NavigatorAuthClient(config.auth_url)

        # ─── NEW: Callback infrastructure ───
        self._callback_registry = CallbackRegistry()
        discovered = self._callback_registry.discover_from_agent(self.agent)
        if discovered:
            self.logger.info(
                f"Discovered {discovered} callback handler(s): "
                f"{', '.join(self._callback_registry.prefixes)}"
            )
        # Give the agent a back-reference to the wrapper (for proactive messaging)
        if hasattr(self.agent, 'set_wrapper'):
            self.agent.set_wrapper(self)

        # Register message handlers
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register aiogram message handlers on the router."""
        # /start command (works in both private and group chats)
        self.router.message.register(
            self.handle_start,
            CommandStart()
        )

        # /help command — briefing with available options
        self.router.message.register(
            self.handle_help,
            Command("help")
        )

        # /whoami — agent name and description
        self.router.message.register(
            self.handle_whoami,
            Command("whoami")
        )

        # /commands — list all registered commands
        self.router.message.register(
            self.handle_commands,
            Command("commands")
        )

        # /clear command to reset conversation
        self.router.message.register(
            self.handle_clear,
            Command("clear")
        )

        # /skill <name> [args] — invoke a tool by name
        self.router.message.register(
            self.handle_skill,
            Command("skill")
        )

        # /function <method> [key=val ...] — invoke agent method with kwargs
        self.router.message.register(
            self.handle_function,
            Command("function")
        )

        # /question <text> — pure LLM query without tools
        self.router.message.register(
            self.handle_question,
            Command("question")
        )

        # /call command to invoke agent methods (backward compat)
        self.router.message.register(
            self.handle_call,
            Command("call")
        )

        # /login — authenticate against Navigator API (if enabled)
        if self.config.enable_login and self._auth_client:
            self.router.message.register(
                self.handle_login,
                Command("login")
            )
            self.router.message.register(
                self.handle_logout,
                Command("logout")
            )
            # Handle WebApp data returned from login page
            self.router.message.register(
                self.handle_web_app_data,
                F.web_app_data,
            )

        # Register custom commands from config YAML
        for cmd_name, method_name in self.config.commands.items():
            self._register_custom_command(cmd_name, method_name)

        # Register agent-declared commands (@telegram_command decorator)
        self._register_agent_commands()

        # ─── Group/Channel Handlers (must be before generic text handler) ───

        # /ask command in groups (e.g., "/ask what is Python?" or "/ask@botname query")
        if self.config.enable_group_commands:
            self.router.message.register(
                self.handle_group_ask,
                Command("ask"),
                F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
            )

        # @mention in group messages
        if self.config.enable_group_mentions:
            self.router.message.register(
                self.handle_group_mention,
                BotMentionedFilter(),
                F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
            )

        # Channel post handlers (if enabled)
        if self.config.enable_channel_posts:
            self.router.channel_post.register(
                self.handle_channel_mention,
                BotMentionedFilter()
            )

        # ─── Private Chat Handlers ───

        # Private chat text messages
        self.router.message.register(
            self.handle_message,
            F.chat.type == ChatType.PRIVATE,
            F.content_type == ContentType.TEXT
        )

        # Photo messages (private only for now)
        self.router.message.register(
            self.handle_photo,
            F.chat.type == ChatType.PRIVATE,
            F.content_type == ContentType.PHOTO
        )

        # Document messages (private only for now)
        self.router.message.register(
            self.handle_document,
            F.chat.type == ChatType.PRIVATE,
            F.content_type == ContentType.DOCUMENT
        )

        # ─── NEW: Callback Query Handler ───
        if self._callback_registry:
            self.router.callback_query.register(
                self._handle_callback_query
            )
            self.logger.info(
                f"Registered callback_query handler for prefixes: "
                f"{self._callback_registry.prefixes}"
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

    def _register_agent_commands(self) -> None:
        """Register commands declared via @telegram_command on the agent."""
        for cmd_info in self._agent_commands:
            cmd_name = cmd_info["command"]
            method = cmd_info["method"]
            parse_mode = cmd_info.get("parse_mode", "raw")

            async def agent_cmd_handler(
                message: Message,
                _method=method,
                _parse_mode=parse_mode,
            ) -> None:
                chat_id = message.chat.id
                if not self._is_authorized(chat_id):
                    await message.answer("⛔ You are not authorized to use this bot.")
                    return
                text = (message.text or "").split(maxsplit=1)
                raw_args = text[1] if len(text) > 1 else ""
                typing_task = asyncio.create_task(self._typing_indicator(chat_id))
                try:
                    if _parse_mode == "keyword":
                        kwargs = self._parse_kwargs(raw_args)
                        result = await _method(**kwargs) if asyncio.iscoroutinefunction(_method) else _method(**kwargs)
                    elif _parse_mode == "positional":
                        args = raw_args.split() if raw_args else []
                        result = await _method(*args) if asyncio.iscoroutinefunction(_method) else _method(*args)
                    else:  # raw
                        result = await _method(raw_args) if asyncio.iscoroutinefunction(_method) else _method(raw_args)
                    typing_task.cancel()
                    parsed = self._parse_response(result)
                    await self._send_parsed_response(message, parsed)
                except Exception as e:
                    typing_task.cancel()
                    self.logger.error(f"Error in agent command /{cmd_name}: {e}", exc_info=True)
                    await message.answer(f"❌ Error: {str(e)[:200]}")
                finally:
                    typing_task.cancel()

            self.router.message.register(agent_cmd_handler, Command(cmd_name))
            self.logger.info(
                f"Registered agent command /{cmd_name} -> {cmd_info['method_name']}()"
            )

    def get_bot_commands(self) -> list:
        """Build list of BotCommand for Telegram set_my_commands API."""
        commands = [
            BotCommand(command="start", description="Start conversation"),
            BotCommand(command="help", description="Show help and available options"),
            BotCommand(command="whoami", description="Agent name and description"),
            BotCommand(command="commands", description="List all available commands"),
            BotCommand(command="clear", description="Reset conversation memory"),
            BotCommand(command="skill", description="Call a tool by name"),
            BotCommand(command="function", description="Call an agent method"),
            BotCommand(command="question", description="Ask the LLM directly (no tools)"),
        ]
        # Authentication commands (when enabled)
        if self.config.enable_login and self._auth_client:
            commands.append(BotCommand(command="login", description="Sign in with Navigator"))
            commands.append(BotCommand(command="logout", description="Sign out"))
        # Custom commands from YAML config
        for cmd_name, method_name in self.config.commands.items():
            commands.append(
                BotCommand(command=cmd_name, description=f"Calls {method_name}()")
            )
        # Agent-declared commands from decorator
        for cmd_info in self._agent_commands:
            commands.append(
                BotCommand(
                    command=cmd_info["command"],
                    description=cmd_info["description"][:256],
                )
            )
        return commands

    @staticmethod
    def _parse_kwargs(text: str) -> dict:
        """Parse 'key=val key2=val2' or 'arg1 arg2' into kwargs/args dict."""
        if not text.strip():
            return {}
        # Support both space and comma separators
        parts = [p.strip() for p in text.replace(",", " ").split() if p.strip()]
        kwargs: dict = {}
        positional_idx = 0
        for part in parts:
            if "=" in part:
                key, _, val = part.partition("=")
                kwargs[key.strip()] = val.strip()
            else:
                kwargs[f"arg{positional_idx}"] = part
                positional_idx += 1
        return kwargs

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

    def _get_user_session(self, message: Message) -> TelegramUserSession:
        """Get or create a user session from a Telegram message."""
        tg_user = message.from_user
        tg_id = tg_user.id if tg_user else 0
        if tg_id not in self._user_sessions:
            self._user_sessions[tg_id] = TelegramUserSession(
                telegram_id=tg_id,
                telegram_username=tg_user.username if tg_user else None,
                telegram_first_name=tg_user.first_name if tg_user else None,
                telegram_last_name=tg_user.last_name if tg_user else None,
            )
        return self._user_sessions[tg_id]

    @staticmethod
    def _enrich_question(
        question: str, session: TelegramUserSession
    ) -> str:
        """Append user identity context to a question for the LLM."""
        parts = []
        name = session.display_name
        if name:
            parts.append(f"name: {name}")
        if session.nav_email:
            parts.append(f"email: {session.nav_email}")
        elif session.telegram_username:
            parts.append(f"telegram: @{session.telegram_username}")
        if not parts:
            return question
        identity = ", ".join(parts)
        return f"{question}\n\n -- I am -- {identity}"

    async def _check_authentication(self, message: Message) -> bool:
        """
        Check if user is authenticated if force_authentication is enabled.
        
        Returns:
            True if authenticated or auth not forced.
            False if not authenticated and auth is forced.
        """
        if not self.config.force_authentication:
            return True
        
        session = self._get_user_session(message)
        if session.authenticated:
            return True
            
        await message.answer("⛔ Debes iniciar sesión con /login para hablar conmigo.")
        return False

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
        """Handle /help command — briefing description with available options."""
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        agent_desc = getattr(self.agent, 'description', '') or ''
        help_text = (
            f"📚 *{self.config.name}*\n"
        )
        if agent_desc:
            help_text += f"{agent_desc}\n"
        help_text += (
            "\n*Built-in Commands:*\n"
            "/start - Start conversation\n"
            "/help - Show this help message\n"
            "/whoami - Agent name and description\n"
            "/commands - List all available commands\n"
            "/clear - Reset conversation memory\n"
            "/skill <name> [args] - Call a tool by name\n"
            "/function <method> [key=val ...] - Call agent method\n"
            "/question <text> - Ask the LLM directly (no tools)\n"
            "/call <method> [args] - Call agent method (legacy)\n"
        )

        # Add custom commands if any
        if self.config.commands:
            help_text += "\n*Custom Commands:*\n"
            for cmd_name, method_name in self.config.commands.items():
                help_text += f"/{cmd_name} - Calls {method_name}()\n"

        # Agent-declared commands
        if self._agent_commands:
            help_text += "\n*Agent Commands:*\n"
            for cmd_info in self._agent_commands:
                help_text += f"/{cmd_info['command']} - {cmd_info['description']}\n"

        help_text += (
            "\nSend any message directly for a conversation with the agent."
        )

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

        if not await self._check_authentication(message):
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

    async def handle_whoami(self, message: Message) -> None:
        """Handle /whoami — returns agent name and description."""
        chat_id = message.chat.id
        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        agent_name = getattr(self.agent, 'name', self.config.name)
        agent_desc = getattr(self.agent, 'description', '') or 'No description available.'
        agent_id = getattr(self.agent, 'agent_id', '') or ''
        model = getattr(self.agent, 'model', '') or ''

        text = f"🤖 *{agent_name}*\n"
        if agent_id:
            text += f"ID: `{agent_id}`\n"
        text += f"\n{agent_desc}\n"
        if model:
            text += f"\nModel: `{model}`\n"

        # Tools count
        if hasattr(self.agent, 'get_tools_count'):
            text += f"Tools: {self.agent.get_tools_count()}\n"

        # User identity
        session = self._get_user_session(message)
        text += f"\n👤 *Your Identity:*\n"
        text += f"Name: {session.display_name}\n"
        text += f"User ID: `{session.user_id}`\n"
        if session.authenticated:
            text += "Status: ✅ Authenticated\n"
        elif self._auth_client:
            text += "Status: 🔓 Not authenticated (use /login)\n"

        await self._send_safe_message(message, text)

    async def handle_commands(self, message: Message) -> None:
        """Handle /commands — list all registered commands and functions."""
        chat_id = message.chat.id
        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        if not await self._check_authentication(message):
            return

        text = f"📋 *{self.config.name} — Commands*\n\n"

        # Built-in commands
        text += "*Built-in:*\n"
        for bc in self.get_bot_commands():
            text += f"/{bc.command} - {bc.description}\n"

        # Available tools (for /skill)
        if hasattr(self.agent, 'get_available_tools'):
            tools = self.agent.get_available_tools()
            if tools:
                text += f"\n*Tools (/skill):* {len(tools)} available\n"
                for tool_name in tools[:15]:
                    text += f"• `{tool_name}`\n"
                if len(tools) > 15:
                    text += f"... and {len(tools) - 15} more\n"

        # Callable methods (for /function)
        callable_methods = self._get_callable_methods()
        if callable_methods:
            text += f"\n*Methods (/function):* {len(callable_methods)} available\n"
            for method in callable_methods[:15]:
                text += f"• `{method}`\n"
            if len(callable_methods) > 15:
                text += f"... and {len(callable_methods) - 15} more\n"

        await self._send_safe_message(message, text)

    async def handle_skill(self, message: Message) -> None:
        """Handle /skill <name> [args] — invoke a tool by name."""
        chat_id = message.chat.id
        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        if not await self._check_authentication(message):
            return

        text = message.text or ""
        parts = text.split(maxsplit=2)  # ["/skill", "tool_name", "args..."]

        if len(parts) < 2:
            # Show available tools
            tools = []
            if hasattr(self.agent, 'get_available_tools'):
                tools = self.agent.get_available_tools()
            usage = "Usage: /skill <tool_name> [arguments]\n\n"
            if tools:
                usage += "Available tools:\n"
                for t in tools[:20]:
                    usage += f"• `{t}`\n"
                if len(tools) > 20:
                    usage += f"... and {len(tools) - 20} more\n"
            else:
                usage += "No tools registered on this agent.\n"
            await message.answer(usage, parse_mode=None)
            return

        tool_name = parts[1]
        args_text = parts[2] if len(parts) > 2 else ""

        # Check tool exists
        if not hasattr(self.agent, 'tool_manager') or not self.agent.tool_manager:
            await message.answer("❌ No tool manager available on this agent.")
            return

        tool = self.agent.tool_manager.get_tool(tool_name)
        if not tool:
            await message.answer(
                f"❌ Tool `{tool_name}` not found.\n"
                f"Use /skill without arguments to see available tools."
            )
            return

        typing_task = asyncio.create_task(self._typing_indicator(chat_id))
        try:
            self.logger.info(f"Chat {chat_id}: Calling tool {tool_name}({args_text})")
            # Use agent.ask to let the LLM invoke the tool properly
            question = f"Use the tool `{tool_name}` with the following input: {args_text}" if args_text else f"Use the tool `{tool_name}`"
            response = await self.agent.ask(
                question,
                output_mode=OutputMode.TELEGRAM,
            )
            typing_task.cancel()
            parsed = self._parse_response(response)
            await self._send_parsed_response(
                message, parsed,
                prefix=f"🔧 *{tool_name}* result:\n\n"
            )
        except Exception as e:
            typing_task.cancel()
            self.logger.error(f"Error calling tool {tool_name}: {e}", exc_info=True)
            await message.answer(f"❌ Error calling tool `{tool_name}`: {str(e)[:200]}")
        finally:
            typing_task.cancel()

    async def handle_function(self, message: Message) -> None:
        """Handle /function <method> [key=val ...] — invoke agent method with kwargs."""
        chat_id = message.chat.id
        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        if not await self._check_authentication(message):
            return

        text = message.text or ""
        parts = text.split(maxsplit=2)  # ["/function", "method", "key=val ..."]

        if len(parts) < 2:
            await message.answer(
                "Usage: /function <method_name> [key=val ...]\n\n"
                "Examples:\n"
                "/function create_ticket summary=Bug description=Crash\n"
                "/function search_all_tickets\n\n"
                "Use /commands to see available methods."
            )
            return

        method_name = parts[1]
        args_text = parts[2] if len(parts) > 2 else ""

        # Check if method exists
        if not hasattr(self.agent, method_name):
            await message.answer(f"❌ Method `{method_name}` not found on agent.")
            return

        method = getattr(self.agent, method_name)
        if not callable(method):
            await message.answer(f"❌ `{method_name}` is not callable.")
            return

        typing_task = asyncio.create_task(self._typing_indicator(chat_id))
        try:
            self.logger.info(f"Chat {chat_id}: /function {method_name}({args_text})")

            kwargs = self._parse_kwargs(args_text)

            if asyncio.iscoroutinefunction(method):
                result = await method(**kwargs) if kwargs else await method()
            else:
                result = method(**kwargs) if kwargs else method()

            typing_task.cancel()
            parsed = self._parse_response(result)
            await self._send_parsed_response(
                message, parsed,
                prefix=f"✅ *{method_name}* result:\n\n"
            )
        except Exception as e:
            typing_task.cancel()
            self.logger.error(f"Error in /function {method_name}: {e}", exc_info=True)
            await message.answer(f"❌ Error calling {method_name}: {str(e)[:200]}")
        finally:
            typing_task.cancel()

    async def handle_question(self, message: Message) -> None:
        """Handle /question <text> — pure LLM query without tools."""
        chat_id = message.chat.id
        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        if not await self._check_authentication(message):
            return

        text = message.text or ""
        parts = text.split(maxsplit=1)
        question = parts[1] if len(parts) > 1 else ""

        if not question:
            await message.answer(
                "Usage: /question <your question>\n\n"
                "Sends your question directly to the LLM (no tool usage)."
            )
            return

        typing_task = asyncio.create_task(self._typing_indicator(chat_id))
        try:
            memory = self._get_or_create_memory(chat_id)
            session = self._get_user_session(message)
            self.logger.info(f"Chat {chat_id}: /question {question[:50]}...")

            response = await self.agent.ask(
                self._enrich_question(question, session),
                user_id=session.user_id,
                session_id=session.session_id,
                memory=memory,
                output_mode=OutputMode.TELEGRAM,
                use_tools=False,
            )

            typing_task.cancel()
            parsed = self._parse_response(response)
            await self._send_parsed_response(message, parsed)
        except Exception as e:
            typing_task.cancel()
            self.logger.error(f"Error in /question: {e}", exc_info=True)
            await message.answer(
                "❌ Sorry, I encountered an error. Please try again."
            )
        finally:
            typing_task.cancel()

    async def handle_login(self, message: Message) -> None:
        """Handle /login — show Navigator login WebApp button."""
        chat_id = message.chat.id
        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        session = self._get_user_session(message)
        if session.authenticated:
            await message.answer(
                f"✅ Already authenticated as *{session.display_name}* "
                f"(`{session.nav_user_id}`).\n\n"
                "Use /logout to sign out.",
                parse_mode="Markdown"
            )
            return

        if not self.config.auth_url:
            await message.answer("❌ Authentication is not configured for this bot.")
            return

        # Build login URL with auth_url as query parameter
        # The static login.html page reads auth_url from the query string
        login_page_url = self.config.login_page_url
        if not login_page_url:
            await message.answer(
                "❌ Login page URL not configured. "
                "Set `login_page_url` in your bot config."
            )
            return

        # Append auth_url as query param for the WebApp JS
        from urllib.parse import urlencode
        full_url = f"{login_page_url}?{urlencode({'auth_url': self.config.auth_url})}"

        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(
                    text="🔐 Sign in to Navigator",
                    web_app=WebAppInfo(url=full_url),
                )]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

        await message.answer(
            "🔐 *Navigator Authentication*\n\n"
            "Tap the button below to sign in with your Navigator credentials.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    async def handle_logout(self, message: Message) -> None:
        """Handle /logout — clear authentication state."""
        chat_id = message.chat.id
        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        session = self._get_user_session(message)
        if not session.authenticated:
            await message.answer("ℹ️ You are not currently authenticated.")
            return

        old_name = session.display_name
        session.clear_auth()
        await message.answer(
            f"👋 Logged out. Was authenticated as *{old_name}*.\n"
            "Your Telegram ID will be used for identification.",
            parse_mode="Markdown"
        )

    async def handle_web_app_data(self, message: Message) -> None:
        """Handle data returned from the login WebApp."""
        if not message.web_app_data or not message.from_user:
            return

        try:
            data = json.loads(message.web_app_data.data)
        except (json.JSONDecodeError, TypeError):
            await message.answer("❌ Invalid login response data.")
            return

        nav_user_id = data.get('user_id')
        token = data.get('token', '')
        display_name = data.get('display_name', '')

        if not nav_user_id:
            await message.answer("❌ Login failed: no user ID received.")
            return

        session = self._get_user_session(message)
        session.set_authenticated(
            nav_user_id=str(nav_user_id),
            session_token=token,
            display_name=display_name,
            email=data.get('email', ''),
        )

        self.logger.info(
            f"User tg:{session.telegram_id} authenticated as "
            f"nav:{nav_user_id} ({display_name})"
        )

        await message.answer(
            f"✅ Authenticated as *{session.display_name}* "
            f"(`{session.nav_user_id}`).\n\n"
            "Your Navigator identity will be used for all interactions.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )

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

        if not await self._check_authentication(message):
            return

        user_text = message.text
        if not user_text:
            return

        # Start continuous typing indicator
        typing_task = asyncio.create_task(self._typing_indicator(chat_id))

        try:
            # Get conversation memory and user session
            memory = self._get_or_create_memory(chat_id)
            session = self._get_user_session(message)

            # Call the agent
            self.logger.info(
                f"Chat {chat_id} (user {session.user_id}): "
                f"Processing message: {user_text[:50]}..."
            )

            response = await self.agent.ask(
                self._enrich_question(user_text, session),
                user_id=session.user_id,
                session_id=session.session_id,
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

    # ─── Group/Channel Message Handlers ──────────────────────────────────

    async def handle_group_ask(self, message: Message) -> None:
        """
        Handle /ask command in group chats.

        Usage:
            /ask what is Python?
            /ask@botname explain machine learning

        Strips the /ask command and processes the remaining query.
        """
        await self._process_group_query(message)

    async def handle_group_mention(self, message: Message) -> None:
        """
        Handle @mention in group chats.

        Usage:
            @botname what is AI?
            Hey @botname tell me about Python

        Responds when the bot is explicitly mentioned.
        """
        await self._process_group_query(message)

    async def handle_channel_mention(self, message: Message) -> None:
        """
        Handle @mention in channel posts.

        Note: Channel posts don't have a from_user by default.
        The bot must be an admin of the channel.
        """
        await self._process_group_query(message, is_channel=True)

    async def _process_group_query(
        self,
        message: Message,
        is_channel: bool = False
    ) -> None:
        """
        Process a group/channel query and send the response.

        Args:
            message: The incoming Telegram message
            is_channel: True if this is a channel post (no from_user)
        """
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.reply("⛔ You are not authorized to use this bot.")
            return

        if not await self._check_authentication(message):
            return

        # Extract the actual query (strips @mention and /command)
        query = await extract_query_from_mention(message, self.bot)

        if not query:
            if is_channel:
                return  # Silent skip for empty channel mentions
            await message.reply(
                "You mentioned me but didn't ask anything! "
                "Try: @me your question here"
            )
            return

        # Start typing indicator
        typing_task = asyncio.create_task(self._typing_indicator(chat_id))

        try:
            # Get/create conversation memory and user session
            memory = self._get_or_create_memory(chat_id)
            session = self._get_user_session(message)

            self.logger.info(
                f"Group {chat_id} (user {session.user_id}): "
                f"Processing query: {query[:50]}..."
            )

            # Call the agent
            response = await self.agent.ask(
                self._enrich_question(query, session),
                user_id=session.user_id,
                session_id=session.session_id,
                memory=memory,
                output_mode=OutputMode.TELEGRAM
            )

            # Parse response
            parsed = self._parse_response(response)

            # Stop typing before sending
            typing_task.cancel()

            # Send response (reply in thread if configured)
            await self._send_group_response(message, parsed)

        except Exception as e:
            typing_task.cancel()
            self.logger.error(f"Error processing group query: {e}", exc_info=True)
            await message.reply(
                "❌ Sorry, I encountered an error processing your request."
            )
        finally:
            typing_task.cancel()

    async def _send_group_response(
        self,
        message: Message,
        parsed: ParsedResponse
    ) -> None:
        """
        Send response to a group message.

        Uses reply (thread) mode if configured, otherwise sends directly.
        """
        if self.config.reply_in_thread:
            # Reply to the original message (creates/continues thread)
            await self._send_parsed_response_reply(message, parsed)
        else:
            # Send as regular message
            await self._send_parsed_response(message, parsed)

    async def _send_parsed_response_reply(
        self,
        message: Message,
        parsed: ParsedResponse,
        prefix: str = ""
    ) -> None:
        """Send parsed response as a reply to the original message."""
        # Build the text response
        text_parts = []

        if prefix:
            text_parts.append(prefix)

        if parsed.text:
            text_to_add = parsed.text
            if self.config.use_html:
                # Convert Markdown to HTML
                text_to_add = self._markdown_to_html(text_to_add)
            else:
                # Convert Headers to Bold for Legacy Markdown
                text_to_add = self._convert_headers_to_bold(text_to_add)
            text_parts.append(text_to_add)

        # Add code block if present
        if parsed.has_code:
            lang = parsed.code_language or ""
            if self.config.use_html:
                code_block = f"<pre><code class=\"language-{lang}\">\n{parsed.code}\n</code></pre>"
            else:
                code_block = f"```{lang}\n{parsed.code}\n```"
            text_parts.append(code_block)

        # Add table if present (as markdown)
        if parsed.has_table and parsed.table_markdown:
            if self.config.use_html:
                 # Tables are tricky in Telegram HTML. Best to use <pre> block for alignment.
                 text_parts.append(f"<pre>\n{parsed.table_markdown}\n</pre>")
            else:
                text_parts.append(f"```\n{parsed.table_markdown}\n```")

        # Send the text message as reply
        full_text = "\n\n".join(text_parts)
        
        parse_mode = "HTML" if self.config.use_html else "Markdown"
        
        
        if full_text.strip():
            await self._send_long_reply(message, full_text, parse_mode=parse_mode)

        # Send attachments (images, documents, media, charts)
        # These are sent as separate messages but still in reply context
        await self._send_attachments(message.chat.id, parsed)

    async def _send_long_reply(
        self,
        message: Message,
        text: str,
        max_length: int = 4096,
        parse_mode: str = "Markdown",
    ) -> None:
        """Send a long message as reply, splitting if necessary."""
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

        # First chunk as reply, rest as regular messages
        for i, chunk in enumerate(chunks):
            if i == 0:
                await self._send_safe_reply(message, chunk, parse_mode=parse_mode)
            else:
                await self._send_safe_message(message, chunk, parse_mode=parse_mode)
            await asyncio.sleep(0.3)  # Rate limiting

    async def _send_safe_reply(
        self,
        message: Message,
        text: str,
        parse_mode: Optional[str] = None
    ) -> None:
        """Send a reply with retry logic for markdown errors."""
        async def _reply(txt, mode):
            await message.reply(txt, parse_mode=mode)
            
        await self._try_send_message(_reply, text, parse_mode)

    async def _send_safe_message(
        self,
        message: Message,
        text: str,
        parse_mode: Optional[str] = None
    ) -> None:
        """Send a message with retry logic for markdown errors."""
        async def _answer(txt, mode):
            await message.answer(txt, parse_mode=mode)
            
        await self._try_send_message(_answer, text, parse_mode)

    async def _try_send_message(
        self,
        send_func: Callable,
        text: str,
        parse_mode: Optional[str] = None
    ) -> None:
        """
        Attempt to send a message with error handling and plaintext fallback.

        On a Telegram 'can't parse entities' error the formatted text is
        stripped of all Markdown/HTML and re-sent as plain text.  LLM output
        frequently contains unbalanced `*`, `` ` `` or `_` characters that
        Telegram's legacy Markdown parser cannot recover from, so we do not
        attempt to re-send with the same parse_mode.
        """
        safe_text = (text or "...")[:4096]

        try:
            await send_func(safe_text, parse_mode)
            return

        except Exception as e:
            is_parse_error = (
                "can't parse entities" in str(e)
                or "Bad Request" in str(e)
            )

            if is_parse_error and parse_mode:
                # Strip all markup and deliver as plain text.
                plain = self._strip_markdown(safe_text)
                self.logger.info(
                    f"Telegram parse error (mode={parse_mode}), "
                    f"falling back to plain text. Error: {e}"
                )
                try:
                    await send_func(plain, None)
                    return
                except Exception as fallback_e:
                    self.logger.error(
                        f"Plain-text fallback also failed: {fallback_e}",
                        exc_info=True,
                    )
            else:
                self.logger.warning(
                    f"Failed to send message (mode={parse_mode}): {e}"
                )
                # Non-parse error: still try bare plaintext as last resort.
                try:
                    await send_func(safe_text, None)
                except Exception as fallback_e:
                    self.logger.error(
                        f"Final fallback failed: {fallback_e}",
                        exc_info=True,
                    )

    async def _send_attachments(
        self,
        chat_id: int,
        parsed: ParsedResponse
    ) -> None:
        """Send attachments (images, documents, media, charts) to a chat."""
        # Send charts
        if hasattr(parsed, 'charts') and parsed.charts:
            for chart in parsed.charts:
                try:
                    image_path = chart.path

                    # SVG not supported by Telegram - convert to PNG
                    if chart.format.lower() == "svg" or image_path.suffix.lower() == '.svg':
                        self.logger.info(f"Converting SVG chart to PNG: {chart.path.name}")
                        image_path = await self._convert_svg_to_png(chart.path)

                    caption = f"📊 {chart.title}"
                    if chart.chart_type and chart.chart_type != "unknown":
                        caption += f" ({chart.chart_type.replace('_', ' ').title()})"

                    if image_path.exists():
                        await self.bot.send_photo(
                            chat_id=chat_id,
                            photo=FSInputFile(image_path),
                            caption=caption[:200]
                        )
                        await asyncio.sleep(0.3)
                except Exception as e:
                    self.logger.error(f"Failed to send chart '{chart.title}': {e}")

        # Send images
        for image_path in parsed.images:
            try:
                await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=FSInputFile(image_path),
                    caption=image_path.name[:200] if len(parsed.images) > 1 else None
                )
                await asyncio.sleep(0.3)
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
                await asyncio.sleep(0.3)
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
                await asyncio.sleep(0.3)
            except Exception as e:
                self.logger.error(f"Failed to send media {media_path}: {e}")

    async def handle_photo(self, message: Message) -> None:
        """Handle photo messages."""
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        if not await self._check_authentication(message):
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

            # Get conversation memory and user session
            memory = self._get_or_create_memory(chat_id)
            session = self._get_user_session(message)

            # Call agent with image (if supported)
            if hasattr(self.agent, 'ask_with_image'):
                response = await self.agent.ask_with_image(
                    self._enrich_question(caption, session),
                    image_path=tmp_path,
                    user_id=session.user_id,
                    session_id=session.session_id,
                    memory=memory
                )
            else:
                response = await self.agent.ask(
                    self._enrich_question(f"[Image received] {caption}", session),
                    user_id=session.user_id,
                    session_id=session.session_id,
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

        if not await self._check_authentication(message):
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

    async def _convert_svg_to_png(self, svg_path: Path) -> Path:
        """
        Convert SVG to PNG for Telegram compatibility.
        
        Telegram Bot API does not support SVG images, so we must convert
        to a rasterized format.
        
        Args:
            svg_path: Path to the SVG file
            
        Returns:
            Path to the converted PNG file
            
        Note:
            Requires one of: cairosvg, svglib+reportlab, or wand
        """
        png_path = svg_path.with_suffix('.png')
        
        # If PNG already exists (cached), use it
        if png_path.exists():
            return png_path
        
        # Try conversion backends
        loop = asyncio.get_event_loop()
        
        def _do_convert():
            # Backend 1: cairosvg (best quality)
            try:
                import cairosvg
                cairosvg.svg2png(
                    url=str(svg_path), 
                    write_to=str(png_path),
                    dpi=150,
                    output_width=1200  # Good resolution for mobile
                )
                return png_path
            except ImportError:
                pass
            except Exception as e:
                self.logger.warning(f"cairosvg failed: {e}")
            
            # Backend 2: svglib + reportlab
            try:
                from svglib.svglib import svg2rlg
                from reportlab.graphics import renderPM
                
                drawing = svg2rlg(str(svg_path))
                if drawing:
                    # Scale for good resolution
                    scale = 2.0
                    drawing.width *= scale
                    drawing.height *= scale
                    drawing.scale(scale, scale)
                    
                    renderPM.drawToFile(
                        drawing, 
                        str(png_path), 
                        fmt="PNG",
                        dpi=150
                    )
                    return png_path
            except ImportError:
                pass
            except Exception as e:
                self.logger.warning(f"svglib failed: {e}")
            
            # Backend 3: wand (ImageMagick)
            try:
                from wand.image import Image as WandImage
                
                with WandImage(filename=str(svg_path), resolution=150) as img:
                    img.format = 'png'
                    img.save(filename=str(png_path))
                return png_path
            except ImportError:
                pass
            except Exception as e:
                self.logger.warning(f"wand failed: {e}")
            
            raise ImportError(
                "No SVG conversion backend available. "
                "Install one of: cairosvg, svglib, or wand (imagemagick)"
            )
        
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                return await loop.run_in_executor(executor, _do_convert)
        except ImportError as e:
            self.logger.error(f"SVG conversion failed: {e}")
            raise

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
            text_to_add = parsed.text
            if self.config.use_html:
                # Convert Markdown to HTML
                text_to_add = self._markdown_to_html(text_to_add)
            else:
                # Convert Headers to Bold for Legacy Markdown
                text_to_add = self._convert_headers_to_bold(text_to_add)
            text_parts.append(text_to_add)
        
        # Add code block if present
        if parsed.has_code:
            lang = parsed.code_language or ""
            if self.config.use_html:
                code_block = f"<pre><code class=\"language-{lang}\">\n{parsed.code}\n</code></pre>"
            else:
                code_block = f"```{lang}\n{parsed.code}\n```"
            text_parts.append(code_block)
        
        # Add table if present (as markdown)
        if parsed.has_table and parsed.table_markdown:
            if self.config.use_html:
                 # Tables are tricky in Telegram HTML. Best to use <pre> block for alignment.
                 text_parts.append(f"<pre>\n{parsed.table_markdown}\n</pre>")
            else:
                text_parts.append(f"```\n{parsed.table_markdown}\n```")
        
        # Send the text message
        full_text = "\n\n".join(text_parts)
        
        parse_mode = "HTML" if self.config.use_html else "Markdown"
        
        if full_text.strip():
            await self._send_long_message(message, full_text, parse_mode=parse_mode)
        
        # Send charts
        if hasattr(parsed, 'charts') and parsed.charts:
            for chart in parsed.charts:
                try:
                    image_path = chart.path
                    
                    # SVG not supported by Telegram - convert to PNG
                    if chart.format.lower() == "svg" or image_path.suffix.lower() == '.svg':
                        self.logger.info(f"Converting SVG chart to PNG: {chart.path.name}")
                        image_path = await self._convert_svg_to_png(chart.path)
                    
                    # Send chart with title as caption
                    caption = f"📊 {chart.title}"
                    if chart.chart_type and chart.chart_type != "unknown":
                        caption += f" ({chart.chart_type.replace('_', ' ').title()})"
                    
                    if image_path.exists():
                        await self.bot.send_photo(
                            chat_id=chat_id,
                            photo=FSInputFile(image_path),
                            caption=caption[:200]  # Telegram caption limit
                        )
                        await asyncio.sleep(0.3)  # Rate limiting
                        
                        self.logger.info(f"Sent chart to Telegram: {chart.title}")
                except Exception as e:
                    self.logger.error(f"Failed to send chart '{chart.title}': {e}")
                    # Send error message instead
                    await message.answer(f"⚠️ Could not display chart: {chart.title}")
        
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
        max_length: int = 4096,
        parse_mode: str = "Markdown",
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
            await self._send_safe_message(message, chunk, parse_mode=parse_mode)
            await asyncio.sleep(0.3)  # Rate limiting



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
                await message.answer_photo(FSInputFile(path))
            else:
                await message.answer_document(FSInputFile(path))

    def _markdown_to_html(self, text: str) -> str:
        """
        Convert Markdown text to Telegram-supported HTML.
        
        Telegram HTML support:
        <b>bold</b>, <strong>bold</strong>
        <i>italic</i>, <em>italic</em>
        <u>underline</u>, <ins>underline</ins>
        <s>strikethrough</s>, <strike>strikethrough</strike>, <del>strikethrough</del>
        <span class="tg-spoiler">spoiler</span>
        <a href="http://www.example.com/">inline URL</a>
        <code>inline fixed-width code</code>
        <pre>pre-formatted fixed-width code block</pre>
        """
        if not text:
            return ""
        
        try:
            # Convert markdown to HTML with basic extras
            html = markdown2.markdown(
                text, 
                extras=["strike", "tables", "fenced-code-blocks", "code-friendly"]
            )
            
            # Clean up HTML for Telegram
            
            # 1. Remove <p> tags (replace with double newline)
            html = html.replace("<p>", "").replace("</p>", "\n\n")
            
            # 2. Replace headers <h1>-<h6> with <b> (bold) + newline
            html = re.sub(r'<h[1-6]>(.*?)</h[1-6]>', r'<b>\1</b>\n', html)
            
            # 3. Handle lists <ul><li> -> • ...
            # Remove <ul> / </ul> wrapper
            html = html.replace("<ul>", "").replace("</ul>", "")
            # Replace <li> with bullet point
            html = html.replace("<li>", "• ").replace("</li>", "\n")

            # 3b. Handle ordered lists <ol><li> -> "1. ..." lines
            # Remove <ol> wrapper
            html = html.replace("<ol>", "").replace("</ol>", "")

            # Replace </li> with newline (same as unordered)
            html = html.replace("</li>", "\n")

            # Convert <li> items in ordered lists to "1. ", "2. "...
            n = 0
            def repl_li(_m):
                nonlocal n
                n += 1
                return f"{n}. "
            html = re.sub(r"<li>", repl_li, html)
            
            # 4. <br> -> \n
            html = html.replace("<br>", "\n").replace("<br />", "\n")
            
            return html.strip()
        except Exception as e:
            self.logger.warning(f"Error converting Markdown to HTML: {e}")
            return text

    def _convert_headers_to_bold(self, text: str) -> str:
        """
        Convert Markdown headers to Bold for legacy Markdown support.
        
        Legacy Markdown doesn't support # Headers, so we convert them to *Bold*.
        ### Header -> *Header*
        """
        if not text:
            return ""
        # Match lines starting with 1-6 hashes, capturing content
        return re.sub(r'^#{1,6}\s+(.*)', r'*\1*', text, flags=re.MULTILINE)

    def _strip_markdown(self, text: str) -> str:
        """
        Remove Markdown formatting characters to produce safe plain text.

        Used as the plaintext fallback when Telegram's parser rejects the
        formatted message.  All common markup tokens (* _ ` [] fenced blocks)
        are stripped, leaving the raw content readable.
        """
        if not text:
            return ""

        # Remove fenced code blocks (```...```) — keep inner content
        result = re.sub(r'```[\w]*\n?(.*?)```', r'\1', text, flags=re.DOTALL)
        # Remove inline code (`...`)
        result = re.sub(r'`([^`]*)`', r'\1', result)
        # Remove bold/italic markers (**text**, *text*, __text__, _text_)
        result = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', result, flags=re.DOTALL)
        result = re.sub(r'_{1,2}(.*?)_{1,2}', r'\1', result, flags=re.DOTALL)
        # Remove Markdown links [text](url) → text
        result = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', result)
        # Remove any remaining lone special chars that trip the parser
        result = re.sub(r'(?<!\\)[*_`\[\]]', '', result)
        return result

    # Backward-compat alias — kept so any external callers don't break.
    _escape_markdown_legacy = _strip_markdown

    # ─── NEW: Callback Handling Methods ───

    async def _handle_callback_query(self, callback_query: CallbackQuery) -> None:
        """
        Route incoming CallbackQuery to the correct agent handler.

        This is the single aiogram callback_query handler that routes
        all inline button clicks to the appropriate @telegram_callback
        handler on the agent.
        """
        data = callback_query.data
        if not data:
            await callback_query.answer("⚠️ Empty callback data")
            return

        # Match callback_data against registered prefixes
        match = self._callback_registry.match(data)
        if not match:
            self.logger.warning(
                f"Unhandled callback_data: {data!r} "
                f"(known prefixes: {self._callback_registry.prefixes})"
            )
            await callback_query.answer("⚠️ Unknown action")
            return

        handler_meta, payload = match
        user = callback_query.from_user

        # Build context for the handler
        context = CallbackContext(
            prefix=handler_meta.prefix,
            payload=payload,
            chat_id=(
                callback_query.message.chat.id
                if callback_query.message else 0
            ),
            user_id=user.id if user else 0,
            message_id=(
                callback_query.message.message_id
                if callback_query.message else 0
            ),
            username=user.username if user else None,
            first_name=user.first_name if user else None,
            raw_query=callback_query,
        )

        self.logger.info(
            f"Callback [{handler_meta.prefix}] from user "
            f"{context.user_id} ({context.display_name}): "
            f"payload={payload}"
        )

        try:
            # Answer the callback query immediately to prevent
            # Telegram's 30-second timeout for long-running handlers.
            try:
                await callback_query.answer("⏳ Processing…")
            except Exception:
                pass  # Best-effort; already expired is fine

            # Invoke the agent's callback handler
            result = await handler_meta.method(context)

            # Normalize result
            if not isinstance(result, CallbackResult):
                if isinstance(result, str):
                    result = CallbackResult(answer_text=result)
                else:
                    result = CallbackResult(answer_text="✅")

            # Apply the result to Telegram (skip re-answering the callback)
            await self._apply_callback_result(
                callback_query, result, already_answered=True,
            )

        except Exception as e:
            self.logger.error(
                f"Error in callback [{handler_meta.prefix}]: {e}",
                exc_info=True,
            )
            # Send error as a new message instead of callback answer
            # (the callback was already answered above).
            if callback_query.message:
                try:
                    await self.bot.send_message(
                        chat_id=callback_query.message.chat.id,
                        text=f"❌ Error: {str(e)[:500]}",
                    )
                except Exception:
                    pass

    async def _apply_callback_result(
        self,
        callback_query: CallbackQuery,
        result: CallbackResult,
        already_answered: bool = False,
    ) -> None:
        """Apply a CallbackResult to the Telegram conversation."""

        # 1. Answer the callback (dismisses loading spinner on the button)
        if not already_answered:
            try:
                await callback_query.answer(
                    text=result.answer_text or "",
                    show_alert=result.show_alert,
                )
            except Exception as e:
                self.logger.debug(f"Callback answer skipped: {e}")

        # 2. Edit the original message if requested
        if result.edit_message and callback_query.message:
            try:
                edit_kwargs = {
                    "chat_id": callback_query.message.chat.id,
                    "message_id": callback_query.message.message_id,
                    "text": result.edit_message,
                    "parse_mode": result.edit_parse_mode,
                }
                if result.remove_keyboard:
                    edit_kwargs["reply_markup"] = None
                elif result.reply_markup is not None:
                    edit_kwargs["reply_markup"] = result.reply_markup

                await self.bot.edit_message_text(**edit_kwargs)
            except Exception as e:
                self.logger.warning(f"Failed to edit message: {e}")

        # 3. Send a new reply message if requested
        if result.reply_text and callback_query.message:
            try:
                await self.bot.send_message(
                    chat_id=callback_query.message.chat.id,
                    text=result.reply_text,
                    parse_mode=result.reply_parse_mode,
                )
            except Exception as e:
                self.logger.warning(f"Failed to send reply: {e}")

    async def send_interactive_message(
        self,
        chat_id: int,
        text: str,
        keyboard: dict,
        parse_mode: str = "Markdown",
    ) -> int | None:
        """
        Send a proactive message with inline keyboard to a specific chat.

        Used by agents for CRON-triggered notifications (not user-initiated).

        Args:
            chat_id: Target Telegram chat ID.
            text: Message text.
            keyboard: InlineKeyboardMarkup dict from build_inline_keyboard().
            parse_mode: Parse mode for the text.

        Returns:
            Message ID of the sent message, or None on failure.
        """
        try:
            # Convert raw dict to aiogram InlineKeyboardMarkup
            if isinstance(keyboard, dict) and "inline_keyboard" in keyboard:
                markup = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(**btn) for btn in row]
                        for row in keyboard["inline_keyboard"]
                    ]
                )
            else:
                markup = keyboard

            msg = await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=markup,
                parse_mode=parse_mode,
            )
            return msg.message_id
        except Exception as e:
            self.logger.error(
                f"Failed to send interactive message to chat {chat_id}: {e}"
            )
            return None



