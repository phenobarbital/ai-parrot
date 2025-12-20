"""
Telegram Bot Manager.

Manages lifecycle of Telegram bots exposing AI-Parrot agents.
Loads configuration from {ENV_DIR}/telegram_bots.yaml and starts
aiogram polling for each configured bot.
"""
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

import yaml
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from navconfig import BASE_DIR
from navconfig.logging import logging

from .models import TelegramAgentConfig, TelegramBotsConfig
from .wrapper import TelegramAgentWrapper

if TYPE_CHECKING:
    from ...manager import BotManager
    from ...bots.abstract import AbstractBot


# Environment directory path (matches project convention: {BASE_DIR}/env/)
ENV_DIR = BASE_DIR.joinpath('env')


class TelegramBotManager:
    """
    Manages Telegram bot lifecycle for exposed agents.

    Responsibilities:
    - Load configuration from {ENV_DIR}/telegram_bots.yaml
    - Get agent instances from BotManager using chatbot_id
    - Start aiogram polling in background tasks
    - Handle graceful shutdown

    Usage:
        manager = TelegramBotManager(bot_manager)
        await manager.startup()
        # ... application runs ...
        await manager.shutdown()
    """

    def __init__(self, bot_manager: 'BotManager'):
        self.bot_manager = bot_manager
        self.logger = logging.getLogger("TelegramBotManager")

        # Active bots: name -> (Bot, Dispatcher, Wrapper)
        self.bots: Dict[str, Tuple[Bot, Dispatcher, TelegramAgentWrapper]] = {}

        # Background polling tasks
        self._polling_tasks: List[asyncio.Task] = []

        # Configuration
        self._config: Optional[TelegramBotsConfig] = None

    def _get_config_path(self) -> Path:
        """Get path to telegram_bots.yaml configuration file."""
        return ENV_DIR / "telegram_bots.yaml"

    async def load_config(self) -> Optional[TelegramBotsConfig]:
        """
        Load telegram_bots.yaml from ENV_DIR.

        Returns:
            TelegramBotsConfig if file exists and is valid, None otherwise.
        """
        config_path = self._get_config_path()

        if not config_path.exists():
            self.logger.debug(
                f"Telegram config not found at {config_path}, "
                f"skipping Telegram integration"
            )
            return None

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if not data:
                self.logger.warning(f"Empty config file: {config_path}")
                return None

            telegram_config = TelegramBotsConfig.from_dict(data)

            # Validate configuration
            errors = telegram_config.validate()
            if errors:
                for error in errors:
                    self.logger.error(f"Config validation error: {error}")
                return None

            self._config = telegram_config
            return telegram_config

        except yaml.YAMLError as e:
            self.logger.error(f"YAML parsing error in {config_path}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error loading Telegram config: {e}", exc_info=True)
            return None

    async def _get_agent(
        self,
        agent_config: TelegramAgentConfig
    ) -> Optional['AbstractBot']:
        """
        Get agent instance from BotManager using chatbot_id.

        Args:
            agent_config: Telegram agent configuration

        Returns:
            Agent instance or None if not found
        """
        agent = await self.bot_manager.get_bot(agent_config.chatbot_id)

        if not agent:
            self.logger.error(
                f"Agent '{agent_config.chatbot_id}' not found in BotManager. "
                f"Make sure the bot is registered before starting Telegram integration."
            )
            return None

        # Apply system prompt override if specified
        if agent_config.system_prompt_override and hasattr(agent, 'system_prompt'):
            agent.system_prompt = agent_config.system_prompt_override

        self.logger.info(f"Using agent: {agent_config.chatbot_id}")
        return agent

    async def _start_bot(
        self,
        name: str,
        agent_config: TelegramAgentConfig
    ) -> bool:
        """
        Start a single Telegram bot.

        Args:
            name: Bot name (from config)
            agent_config: Bot configuration

        Returns:
            True if started successfully
        """
        if not agent_config.bot_token:
            self.logger.error(f"No bot token for {name}")
            return False

        try:
            # Get agent instance from BotManager
            agent = await self._get_agent(agent_config)
            if not agent:
                return False

            # Create aiogram Bot
            bot = Bot(
                token=agent_config.bot_token,
                default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
            )

            # Create Dispatcher
            dp = Dispatcher()

            # Create wrapper with handlers
            wrapper = TelegramAgentWrapper(agent, bot, agent_config)

            # Include wrapper's router in dispatcher
            dp.include_router(wrapper.router)

            # Store for later cleanup
            self.bots[name] = (bot, dp, wrapper)

            # Start polling in background task
            task = asyncio.create_task(
                self._run_polling(name, dp, bot),
                name=f"telegram_polling_{name}"
            )
            self._polling_tasks.append(task)

            self.logger.info(
                f"✅ Started Telegram bot '{name}' "
                f"(chatbot_id: {agent_config.chatbot_id})"
            )
            return True

        except Exception as e:
            self.logger.error(f"Failed to start bot {name}: {e}", exc_info=True)
            return False

    async def _run_polling(
        self,
        name: str,
        dp: Dispatcher,
        bot: Bot
    ) -> None:
        """Run polling for a single bot."""
        try:
            self.logger.info(f"Starting polling for bot: {name}")
            await dp.start_polling(
                bot,
                allowed_updates=["message", "callback_query"]
            )
        except asyncio.CancelledError:
            self.logger.info(f"Polling cancelled for bot: {name}")
            raise
        except Exception as e:
            self.logger.error(f"Polling error for bot {name}: {e}", exc_info=True)

    async def startup(self) -> None:
        """
        Start all configured Telegram bots.

        Called from BotManager.on_startup().
        """
        self.logger.info("Starting Telegram bot integration...")

        config = await self.load_config()
        if not config:
            self.logger.info("No Telegram bots configured")
            return

        self.logger.info(f"Found {len(config.agents)} agent(s) to expose via Telegram")

        started = 0
        for name, agent_config in config.agents.items():
            if await self._start_bot(name, agent_config):
                started += 1

        if started > 0:
            self.logger.info(
                f"🤖 Telegram integration active: {started} bot(s) polling"
            )
        else:
            self.logger.warning("No Telegram bots were started successfully")

    async def shutdown(self) -> None:
        """
        Stop all Telegram bot polling tasks.

        Called from BotManager.on_shutdown().
        """
        if not self.bots:
            return

        self.logger.info("Shutting down Telegram bots...")

        # Stop all dispatchers first (this stops polling gracefully)
        for name, (bot, dp, wrapper) in self.bots.items():
            try:
                await dp.stop_polling()
                self.logger.debug(f"Stopped polling for bot: {name}")
            except Exception as e:
                self.logger.warning(f"Error stopping polling for {name}: {e}")

        # Cancel any remaining polling tasks
        for task in self._polling_tasks:
            if not task.done():
                task.cancel()

        # Wait for cancellation with timeout
        if self._polling_tasks:
            try:
                await asyncio.wait(
                    self._polling_tasks,
                    timeout=3.0,
                    return_when=asyncio.ALL_COMPLETED
                )
            except Exception as e:
                self.logger.warning(f"Error waiting for tasks: {e}")

        # Close bot sessions
        for name, (bot, dp, wrapper) in self.bots.items():
            try:
                await bot.session.close()
                self.logger.debug(f"Closed bot session: {name}")
            except Exception as e:
                self.logger.warning(f"Error closing bot {name}: {e}")

        self.bots.clear()
        self._polling_tasks.clear()

        self.logger.info("Telegram bots shutdown complete")

    def get_active_bots(self) -> List[str]:
        """Get names of currently active bots."""
        return list(self.bots.keys())

    def is_running(self, name: str) -> bool:
        """Check if a specific bot is running."""
        return name in self.bots
