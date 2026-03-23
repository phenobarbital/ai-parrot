"""TelegramCrewTransport — top-level orchestrator for multi-agent crew.

Manages the full lifecycle of a multi-agent crew in a Telegram supergroup:
coordinator bot startup, agent wrapper creation, agent registration,
aiogram polling, and graceful shutdown.

Usage::

    config = TelegramCrewConfig.from_yaml("crew.yaml")
    async with TelegramCrewTransport(config) as transport:
        # transport is running — agents respond to @mentions
        await asyncio.Event().wait()  # or your application loop
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, TYPE_CHECKING

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .agent_card import AgentCard, AgentSkill
from .config import TelegramCrewConfig, CrewAgentEntry
from .coordinator import CoordinatorBot
from .crew_wrapper import CrewAgentWrapper
from .mention import format_reply
from .payload import DataPayload
from .registry import CrewRegistry

if TYPE_CHECKING:
    from ....bots.abstract import AbstractBot

logger = logging.getLogger(__name__)

# Rate limit delay between consecutive bot startups (seconds)
_STARTUP_DELAY = 0.3


class TelegramCrewTransport:
    """Orchestrator for a multi-agent crew in a Telegram supergroup.

    Manages the lifecycle of all bots: a coordinator bot and one aiogram
    ``Bot`` + ``CrewAgentWrapper`` per configured agent.

    Args:
        config: The ``TelegramCrewConfig`` describing the crew setup.
        bot_manager: Optional ``BotManager`` instance for retrieving agents
            by ``chatbot_id``.  When provided, ``start()`` will look up
            agent instances automatically.
    """

    def __init__(
        self,
        config: TelegramCrewConfig,
        bot_manager: Optional[object] = None,
    ) -> None:
        self.config = config
        self.bot_manager = bot_manager
        self.registry = CrewRegistry()
        self.coordinator: Optional[CoordinatorBot] = None
        self._wrappers: Dict[str, CrewAgentWrapper] = {}
        self._bots: Dict[str, Bot] = {}
        self._dispatchers: Dict[str, Dispatcher] = {}
        self._polling_tasks: List[asyncio.Task] = []
        self._payload: Optional[DataPayload] = None
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        config: TelegramCrewConfig,
        bot_manager: Optional[object] = None,
    ) -> "TelegramCrewTransport":
        """Construct a transport from a ``TelegramCrewConfig``.

        Args:
            config: Validated crew configuration.
            bot_manager: Optional ``BotManager`` for agent retrieval.

        Returns:
            A new ``TelegramCrewTransport`` instance (not yet started).
        """
        return cls(config=config, bot_manager=bot_manager)

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "TelegramCrewTransport":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the crew transport.

        1. Create a shared ``DataPayload`` for file exchange.
        2. Start the ``CoordinatorBot`` (sends + pins the registry message).
        3. For each agent in config, create a ``Bot``, ``Dispatcher``,
           ``CrewAgentWrapper``, build an ``AgentCard``, register with the
           coordinator, and start aiogram polling.
        """
        self.logger.info(
            "Starting TelegramCrewTransport for group %d with %d agents",
            self.config.group_id,
            len(self.config.agents),
        )

        # Shared DataPayload for file exchange
        self._payload = DataPayload(
            temp_dir=self.config.temp_dir,
            max_file_size_mb=self.config.max_file_size_mb,
            allowed_mime_types=self.config.allowed_mime_types,
        )

        # Start coordinator bot
        self.coordinator = CoordinatorBot(
            token=self.config.coordinator_token,
            group_id=self.config.group_id,
            registry=self.registry,
            username=self.config.coordinator_username,
        )
        await self.coordinator.start()
        self.logger.info("CoordinatorBot started")

        # Start each agent
        for agent_name, entry in self.config.agents.items():
            try:
                await self._start_agent(agent_name, entry)
                await asyncio.sleep(_STARTUP_DELAY)
            except Exception as e:
                self.logger.error(
                    "Failed to start agent %s: %s", agent_name, e, exc_info=True
                )

        self.logger.info(
            "TelegramCrewTransport started: %d agents online",
            len(self._wrappers),
        )

    async def _start_agent(
        self, agent_name: str, entry: CrewAgentEntry
    ) -> None:
        """Start a single agent bot, wrapper, and polling task.

        Args:
            agent_name: Human-readable agent name (from config dict key).
            entry: The ``CrewAgentEntry`` config for this agent.
        """
        # Retrieve the AI agent instance
        agent = await self._get_agent(agent_name, entry)

        # Create aiogram Bot
        bot = Bot(
            token=entry.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
        )
        self._bots[entry.username] = bot

        # Get bot user info for the AgentCard
        bot_user = await bot.me()

        # Build AgentCard
        skills = [
            AgentSkill(name=s.get("name", ""), description=s.get("description", ""))
            for s in entry.skills
        ]
        now = datetime.now(timezone.utc)
        card = AgentCard(
            agent_id=entry.chatbot_id,
            agent_name=agent_name,
            telegram_username=entry.username,
            telegram_user_id=bot_user.id,
            model=getattr(agent, "model", "unknown") if agent else "unknown",
            skills=skills,
            tags=entry.tags,
            accepts_files=entry.accepts_files,
            emits_files=entry.emits_files,
            joined_at=now,
            last_seen=now,
        )

        # Create wrapper
        wrapper = CrewAgentWrapper(
            bot=bot,
            agent=agent,
            card=card,
            group_id=self.config.group_id,
            coordinator=self.coordinator,
            payload=self._payload,
        )
        self._wrappers[entry.username] = wrapper

        # Register with coordinator
        await self.coordinator.on_agent_join(card)

        # Create dispatcher and include wrapper router
        dp = Dispatcher()
        dp.include_router(wrapper.router)
        self._dispatchers[entry.username] = dp

        # Start polling in background
        task = asyncio.create_task(
            self._run_polling(entry.username, bot, dp),
            name=f"polling-{entry.username}",
        )
        self._polling_tasks.append(task)

        self.logger.info(
            "Agent @%s (%s) started and registered",
            entry.username, agent_name,
        )

    async def _get_agent(
        self, agent_name: str, entry: CrewAgentEntry
    ) -> Optional["AbstractBot"]:
        """Retrieve an agent instance from the BotManager.

        Args:
            agent_name: Display name of the agent.
            entry: The ``CrewAgentEntry`` config.

        Returns:
            The agent instance, or ``None`` if not available.
        """
        if self.bot_manager is None:
            self.logger.warning(
                "No BotManager provided — agent %s will have a stub agent",
                agent_name,
            )
            return None

        try:
            agent = await self.bot_manager.get_bot(entry.chatbot_id)
        except Exception as e:
            self.logger.error(
                "Failed to get agent %s from BotManager: %s",
                entry.chatbot_id, e,
            )
            return None

        if not agent:
            self.logger.error(
                "Agent '%s' (chatbot_id=%s) not found in BotManager",
                agent_name, entry.chatbot_id,
            )
            return None

        # Apply system prompt override if specified
        if entry.system_prompt_override and hasattr(agent, "system_prompt"):
            agent.system_prompt = entry.system_prompt_override

        return agent

    async def _run_polling(
        self, username: str, bot: Bot, dp: Dispatcher
    ) -> None:
        """Run aiogram polling for a single bot (background task).

        Args:
            username: Telegram username of the bot.
            bot: The aiogram ``Bot`` instance.
            dp: The aiogram ``Dispatcher``.
        """
        try:
            self.logger.info("Starting polling for @%s", username)
            await dp.start_polling(bot)
        except asyncio.CancelledError:
            self.logger.info("Polling cancelled for @%s", username)
        except Exception as e:
            self.logger.error(
                "Polling error for @%s: %s", username, e, exc_info=True
            )

    async def stop(self) -> None:
        """Stop the crew transport gracefully.

        1. Cancel all polling tasks.
        2. Unregister all agents from the coordinator.
        3. Stop the coordinator bot.
        4. Close all bot sessions.
        5. Clean up payload temp files.
        """
        self.logger.info("Stopping TelegramCrewTransport")

        # Cancel polling tasks
        for task in self._polling_tasks:
            task.cancel()
        if self._polling_tasks:
            await asyncio.gather(*self._polling_tasks, return_exceptions=True)
        self._polling_tasks.clear()

        # Stop dispatchers
        for username, dp in self._dispatchers.items():
            try:
                await dp.stop_polling()
            except Exception:
                pass

        # Unregister agents from coordinator
        if self.coordinator:
            for username in list(self._wrappers.keys()):
                try:
                    await self.coordinator.on_agent_leave(username)
                except Exception as e:
                    self.logger.warning(
                        "Error unregistering @%s: %s", username, e
                    )

            # Stop coordinator
            try:
                await self.coordinator.stop()
            except Exception as e:
                self.logger.warning("Error stopping coordinator: %s", e)

        # Close all bot sessions
        for username, bot in self._bots.items():
            try:
                await bot.session.close()
            except Exception as e:
                self.logger.warning(
                    "Error closing session for @%s: %s", username, e
                )

        # Clean up temp files
        if self._payload:
            self._payload.cleanup_all()

        self._wrappers.clear()
        self._bots.clear()
        self._dispatchers.clear()

        self.logger.info("TelegramCrewTransport stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_message(
        self,
        from_username: str,
        mention: str,
        text: str,
        reply_to_message_id: Optional[int] = None,
    ) -> None:
        """Send a text message from a specific agent bot.

        Args:
            from_username: Telegram username of the sending agent.
            mention: @mention to include in the message.
            text: The message text.
            reply_to_message_id: Optional message ID to reply to.

        Raises:
            KeyError: If ``from_username`` is not a registered agent.
        """
        bot = self._get_bot(from_username)
        full_text = format_reply(mention, text)
        await bot.send_message(
            chat_id=self.config.group_id,
            text=full_text,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_document(
        self,
        from_username: str,
        mention: str,
        file_path: str,
        caption: str = "",
        reply_to_message_id: Optional[int] = None,
    ) -> None:
        """Send a document from a specific agent bot.

        Args:
            from_username: Telegram username of the sending agent.
            mention: @mention to include in the caption.
            file_path: Path to the file to send.
            caption: Optional caption text.
            reply_to_message_id: Optional message ID to reply to.

        Raises:
            KeyError: If ``from_username`` is not a registered agent.
        """
        if self._payload is None:
            raise RuntimeError("DataPayload not initialized — call start() first")

        bot = self._get_bot(from_username)
        full_caption = format_reply(mention, caption) if caption else mention
        await self._payload.send_document(
            bot=bot,
            chat_id=self.config.group_id,
            file_path=file_path,
            caption=full_caption,
            reply_to_message_id=reply_to_message_id,
        )

    def list_online_agents(self) -> List[AgentCard]:
        """Return a list of currently active (non-offline) agents.

        Returns:
            List of ``AgentCard`` instances for agents that are online.
        """
        return self.registry.list_active()

    def get_wrapper(self, username: str) -> Optional[CrewAgentWrapper]:
        """Get the ``CrewAgentWrapper`` for a specific agent.

        Args:
            username: Telegram username of the agent (without @).

        Returns:
            The wrapper instance, or ``None`` if not found.
        """
        return self._wrappers.get(username.lstrip("@"))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_bot(self, username: str) -> Bot:
        """Get the aiogram Bot for a given username.

        Args:
            username: Telegram username of the agent.

        Returns:
            The aiogram ``Bot`` instance.

        Raises:
            KeyError: If the username is not registered.
        """
        clean = username.lstrip("@")
        if clean not in self._bots:
            raise KeyError(
                f"No bot registered for @{clean}. "
                f"Available: {list(self._bots.keys())}"
            )
        return self._bots[clean]
