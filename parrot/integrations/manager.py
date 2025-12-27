"""
Integration Bot Manager.

Manages lifecycle of bots (Telegram, MS Teams) exposing AI-Parrot agents.
Loads configuration from {ENV_DIR}/integrations_bots.yaml (or telegram_bots.yaml fallback).
"""
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING, Union
import yaml

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from navconfig import BASE_DIR
from navconfig.logging import logging
from ..conf import AGENTS_DIR
from .models import (
    IntegrationBotConfig, 
    TelegramAgentConfig, 
    MSTeamsAgentConfig
)
from .telegram.wrapper import TelegramAgentWrapper
from .msteams.wrapper import MSTeamsAgentWrapper

if TYPE_CHECKING:
    from ..manager import BotManager
    from ..bots.abstract import AbstractBot


ENV_DIR = BASE_DIR.joinpath('env')


class IntegrationBotManager:
    """
    Manages bot integrations for exposed agents.
    
    Supports:
    - Telegram
    - MS Teams
    """
    
    def __init__(self, bot_manager: 'BotManager'):
        self.bot_manager = bot_manager
        self.logger = logging.getLogger("IntegrationBotManager")
        
        # Active bots
        self.telegram_bots: Dict[str, Tuple[Bot, Dispatcher, TelegramAgentWrapper]] = {}
        self.msteams_bots: Dict[str, MSTeamsAgentWrapper] = {}
        
        self._polling_tasks: List[asyncio.Task] = []
        self._config: Optional[IntegrationBotConfig] = None

    def _get_config_path(self) -> Path:
        """Get path to integrations_bots.yaml (preferred) or telegram_bots.yaml."""
        p = ENV_DIR / "integrations_bots.yaml"
        if p.exists():
            return p
        return ENV_DIR / "telegram_bots.yaml"

    async def load_config(self) -> Optional[IntegrationBotConfig]:
        """Load configuration."""
        config_path = self._get_config_path()
        
        if not config_path.exists():
            self.logger.debug("No integration config found.")
            return None
            
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                
            if not data:
                return None
                
            # Use the unified config parser
            config = IntegrationBotConfig.from_dict(data)
            
            errors = config.validate()
            if errors:
                for error in errors:
                    self.logger.error(f"Config Error: {error}")
                return None
                
            self._config = config
            return config
            
        except Exception as e:
            self.logger.error(f"Error loading integration config: {e}", exc_info=True)
            return None

    async def _get_agent(self, chatbot_id: str, system_prompt_override: Optional[str] = None) -> Optional['AbstractBot']:
        """Get agent instance from BotManager."""
        agent = await self.bot_manager.get_bot(chatbot_id)
        if not agent:
            self.logger.error(f"Agent '{chatbot_id}' not found.")
            return None
            
        if system_prompt_override and hasattr(agent, 'system_prompt'):
            agent.system_prompt = system_prompt_override
            
        return agent

    async def startup(self) -> None:
        """Start all configured bots."""
        self.logger.info("Starting Integration Manager...")
        
        config = await self.load_config()
        if not config:
            return

        for name, agent_config in config.agents.items():
            try:
                if isinstance(agent_config, TelegramAgentConfig):
                    await self._start_telegram_bot(name, agent_config)
                elif isinstance(agent_config, MSTeamsAgentConfig):
                    await self._start_msteams_bot(name, agent_config)
            except Exception as e:
                self.logger.error(f"Failed to start bot {name}: {e}", exc_info=True)

    async def _start_telegram_bot(self, name: str, config: TelegramAgentConfig):
        agent = await self._get_agent(config.chatbot_id, config.system_prompt_override)
        if not agent:
            return

        bot = Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
        dp = Dispatcher()
        wrapper = TelegramAgentWrapper(agent, bot, config)
        dp.include_router(wrapper.router)
        
        self.telegram_bots[name] = (bot, dp, wrapper)
        
        task = asyncio.create_task(
            self._run_polling(name, dp, bot),
            name=f"telegram_polling_{name}"
        )
        self._polling_tasks.append(task)
        self.logger.info(f"✅ Started Telegram bot '{name}'")

    async def _run_polling(self, name: str, dp: Dispatcher, bot: Bot):
        try:
            await dp.start_polling(
                bot,
                allowed_updates=["message", "callback_query"],
                handle_signals=False,
                close_bot_session=True
            )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"Polling error for {name}: {e}")

    async def _start_msteams_bot(self, name: str, config: MSTeamsAgentConfig):
        agent = await self._get_agent(config.chatbot_id)
        if not agent:
            return
            
        # Initialize Wrapper (which registers the route)
        wrapper = MSTeamsAgentWrapper(
            agent=agent,
            config=config,
            app=self.bot_manager.get_app(),
            forms_directory=config.forms_directory or AGENTS_DIR / "forms",
        )
        self.msteams_bots[name] = wrapper
        self.logger.info(f"✅ Started MS Teams bot '{name}'")

    async def shutdown(self) -> None:
        """Shutdown bots."""
        self.logger.info("Shutting down Integration Manager...")
        
        # First, cancel all polling tasks to stop the polling loops
        for task in self._polling_tasks:
            if not task.done():
                task.cancel()
        
        # Wait for all polling tasks to complete (with timeout)
        if self._polling_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._polling_tasks, return_exceptions=True),
                    timeout=5.0
                )
                self.logger.info("All polling tasks cancelled successfully")
            except asyncio.TimeoutError:
                self.logger.warning("Timeout waiting for polling tasks to cancel")
            except Exception as e:
                self.logger.error(f"Error while cancelling polling tasks: {e}")
        
        # Now close bot sessions
        for name, (bot, dp, _) in self.telegram_bots.items():
            try:
                self.logger.debug(f"Closing session for bot '{name}'")
                await bot.session.close()
            except Exception as e:
                self.logger.error(f"Error closing bot session for '{name}': {e}")
        
        # Clear data structures
        self.telegram_bots.clear()
        self.msteams_bots.clear()
        self._polling_tasks.clear()
        
        self.logger.info("Integration Manager shutdown complete")
