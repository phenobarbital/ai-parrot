"""
Foundational base of every Chatbot and Agent in ai-parrot.
"""
from typing import Any, Union
from pathlib import Path, PurePath
import uuid
from aiohttp import web
# Navconfig
from datamodel.exceptions import ValidationError # pylint: disable=E0611
from navconfig import BASE_DIR
from navconfig.exceptions import ConfigError  # pylint: disable=E0611
from asyncdb.exceptions import NoDataFound
from ..utils import parse_toml_config
from ..conf import (
    default_dsn,
    EMBEDDING_DEFAULT_MODEL,
)
from ..handlers.models import BotModel
from .abstract import AbstractBot

class Chatbot(AbstractBot):
    """Represents an Bot (Chatbot, Agent) in Navigator.

    This class is the base for all chatbots and agents in the ai-parrot framework.
    """
    company_information: dict = {}

    def __init__(
        self,
        name: str = 'Nav',
        system_prompt: str = None,
        human_prompt: str = None,
        **kwargs
    ):
        """Initialize the Chatbot with the given configuration."""
        # Other Configuration
        self.confidence_threshold: float = kwargs.get('threshold', 0.5)
        # Text Documents
        self.documents_dir = kwargs.get(
            'documents_dir',
            None
        )
        # Company Information:
        self.company_information = kwargs.get(
            'company_information',
            self.company_information
        )
        super().__init__(
            name=name,
            system_prompt=system_prompt,
            human_prompt=human_prompt,
            **kwargs
        )
        if isinstance(self.documents_dir, str):
            self.documents_dir = Path(self.documents_dir)
        if not self.documents_dir:
            self.documents_dir = BASE_DIR.joinpath('documents')
        if not self.documents_dir.exists():
            self.documents_dir.mkdir(
                parents=True,
                exist_ok=True
            )

    def __repr__(self):
        return f"<ChatBot.{self.__class__.__name__}:{self.name}>"

    async def configure(self, app = None) -> None:
        """Load configuration for this Chatbot."""
        if (bot := await self.bot_exists(name=self.name, uuid=self.chatbot_id)):
            self.logger.notice(
                f"Loading Bot {self.name} from Database: {bot.chatbot_id}"
            )
            # Bot exists on Database, Configure from the Database
            await self.from_database(bot)
        else:
            raise ValueError(
                f'Bad configuration procedure for bot {self.name}'
            )
        # adding this configured chatbot to app:
        await super().configure(app)

    def _from_bot(self, bot, key, config, default) -> Any:
        value = getattr(bot, key, None)
        file_value = config.get(key, default)
        return value if value else file_value

    def _from_db(self, botobj, key, default = None) -> Any:
        value = getattr(botobj, key, default)
        return value if value else default

    async def bot_exists(
        self,
        name: str = None,
        uuid: uuid.UUID = None
    ) -> Union[BotModel, bool]:
        """Check if the Chatbot exists in the Database."""
        db = self.get_database('pg', dsn=default_dsn)
        async with await db.connection() as conn:  # pylint: disable=E1101
            BotModel.Meta.connection = conn
            try:
                if self.chatbot_id:
                    try:
                        bot = await BotModel.get(chatbot_id=uuid, enabled=True)
                    except Exception:
                        bot = await BotModel.get(name=name, enabled=True)
                else:
                    bot = await BotModel.get(name=self.name, enabled=True)
                if bot:
                    return bot
                else:
                    return False
            except NoDataFound:
                return False

    async def from_database(
        self,
        bot: Union[BotModel, None] = None
    ) -> None:
        """
        Load the Chatbot/Agent Configuration from the Database.
        If the bot is not found, it will raise a ConfigError.
        """
        if not bot:
            db = self.get_database('pg', dsn=default_dsn)
            async with await db.connection() as conn:  # pylint: disable=E1101
                # import model
                BotModel.Meta.connection = conn
                try:
                    if self.chatbot_id:
                        try:
                            bot = await BotModel.get(chatbot_id=self.chatbot_id, enabled=True)
                        except Exception:
                            bot = await BotModel.get(name=self.name, enabled=True)
                    else:
                        bot = await BotModel.get(name=self.name, enabled=True)
                except ValidationError as ex:
                    # Handle ValidationError
                    self.logger.error(
                        f"Validation error: {ex}"
                    )
                    raise ConfigError(
                        f"Chatbot {self.name} with errors: {ex.payload()}."
                    )
                except NoDataFound:
                    # Fallback to File configuration:
                    raise ConfigError(
                        f"Chatbot {self.name} not found in the database."
                    )
        # Start Bot configuration from Database:
        self.pre_instructions: list = self._from_db(
            bot, 'pre_instructions', default=[]
        )
        self.name = self._from_db(bot, 'name', default=self.name)
        self.chatbot_id = str(self._from_db(bot, 'chatbot_id', default=self.chatbot_id))
        self.description = self._from_db(bot, 'description', default=self.description)
        self.role = self._from_db(bot, 'role', default=self.role)
        self.goal = self._from_db(bot, 'goal', default=self.goal)
        self.rationale = self._from_db(bot, 'rationale', default=self.rationale)
        self.backstory = self._from_db(bot, 'backstory', default=self.backstory)
        # LLM Configuration:
        self._llm = self._from_db(bot, 'llm', default='google')
        self._llm_config = self._from_db(bot, 'llm_config', default={})
        # Embedding Model Configuration:
        self.embedding_model : dict = self._from_db(
            bot, 'embedding_model', None
        )
        # Database Configuration:
        self._use_vector = bot.use_vector_context
        self._vector_store = bot.vector_store_config
        self._metric_type = bot.vector_store_config.get(
            'metric_type',
            self._metric_type
        )
        # after configuration, setup the chatbot
        if bot.system_prompt_template:
            self.system_prompt_template = bot.system_prompt_template
        # Last: permissions:
        _default = self.default_permissions()
        _permissions = bot.permissions
        self._permissions = {**_default, **_permissions}
