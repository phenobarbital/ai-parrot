"""
Foundational base of every Chatbot and Agent in ai-parrot.
"""
from typing import Any, Union
from pathlib import Path, PurePath
import uuid
import torch
from aiohttp import web
# Navconfig
from navconfig import BASE_DIR
from navconfig.exceptions import ConfigError  # pylint: disable=E0611
from asyncdb.exceptions import NoDataFound
from ..utils import parse_toml_config
from ..conf import (
    EMBEDDING_DEVICE,
    default_dsn,
    EMBEDDING_DEFAULT_MODEL,
)
from ..models import ChatbotModel
from .abstract import AbstractBot

class Chatbot(AbstractBot):
    """Represents an Bot (Chatbot, Agent) in Navigator.

        Each Chatbot has a name, a role, a goal, a backstory,
        and an optional language model (llm).
    """
    def __init__(self, **kwargs):
        """Initialize the Chatbot with the given configuration."""
        super().__init__(**kwargs)
        # For Chatbots, always use a database:
        # self._use_database = True
        # Configuration File:
        self.config_file: PurePath = kwargs.get('config_file', None)
        # Other Configuration
        self.confidence_threshold: float = kwargs.get('threshold', 0.5)
        # Text Documents
        self.documents_dir = kwargs.get(
            'documents_dir',
            None
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

    def _get_device(self, cuda_number: int = 0):
        torch.backends.cudnn.deterministic = True
        if torch.cuda.is_available():
            # Use CUDA GPU if available
            device = torch.device(f'cuda:{cuda_number}')
        elif torch.backends.mps.is_available():
            # Use CUDA Multi-Processing Service if available
            device = torch.device("mps")
        elif EMBEDDING_DEVICE == 'cuda':
            device = torch.device(f'cuda:{cuda_number}')
        else:
            device = torch.device(EMBEDDING_DEVICE)
        return device

    async def configure(self, app = None) -> None:
        if app is None:
            self.app = None
        else:
            if isinstance(app, web.Application):
                self.app = app  # register the app into the Extension
            else:
                self.app = app.get_app()  # Nav Application
        # Config File:
        config_file = BASE_DIR.joinpath(
            'etc',
            'config',
            'chatbots',
            self.name.lower(),
            "config.toml"
        )
        if config_file.exists():
            self.logger.notice(
                f"Loading Bot {self.name} from config: {config_file.name}"
            )
        if (bot := await self.bot_exists(name=self.name, uuid=self.chatbot_id)):
            self.logger.notice(
                f"Loading Bot {self.name} from Database: {bot.chatbot_id}"
            )
            # Bot exists on Database, Configure from the Database
            await self.from_database(bot, config_file)
        elif config_file.exists():
            # Configure from the TOML file
            await self.from_config_file(config_file)
        else:
            raise ValueError(
                f'Bad configuration procedure for bot {self.name}'
            )

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
    ) -> Union[ChatbotModel, bool]:
        """Check if the Chatbot exists in the Database."""
        db = self.get_database('pg', dsn=default_dsn)
        async with await db.connection() as conn:  # pylint: disable=E1101
            ChatbotModel.Meta.connection = conn
            try:
                if self.chatbot_id:
                    try:
                        bot = await ChatbotModel.get(chatbot_id=uuid)
                    except Exception:
                        bot = await ChatbotModel.get(name=name)
                else:
                    bot = await ChatbotModel.get(name=self.name)
                if bot:
                    return bot
            except NoDataFound:
                return False

    async def from_database(
        self,
        bot: Union[ChatbotModel, None] = None,
        config_file: PurePath = None
    ) -> None:
        """Load the Chatbot Configuration from the Database."""
        if not bot:
            db = self.get_database('pg', dsn=default_dsn)
            async with await db.connection() as conn:  # pylint: disable=E1101
                # import model
                ChatbotModel.Meta.connection = conn
                try:
                    if self.chatbot_id:
                        try:
                            bot = await ChatbotModel.get(chatbot_id=self.chatbot_id)
                        except Exception:
                            bot = await ChatbotModel.get(name=self.name)
                    else:
                        bot = await ChatbotModel.get(name=self.name)
                except NoDataFound:
                    # Fallback to File configuration:
                    raise ConfigError(
                        f"Chatbot {self.name} not found in the database."
                    )
        # Start Bot configuration from Database:
        if config_file and config_file.exists():
            file_config = await parse_toml_config(config_file)
            # Knowledge Base come from file:
            # Contextual knowledge-base
            self.kb = file_config.get('knowledge-base', [])
            if self.kb:
                self.knowledge_base = self.create_kb(
                    self.kb.get('data', [])
                )
        self.name = self._from_db(bot, 'name', default=self.name)
        self.chatbot_id = str(self._from_db(bot, 'chatbot_id', default=self.chatbot_id))
        self.description = self._from_db(bot, 'description', default=self.description)
        self.role = self._from_db(bot, 'role', default=self.role)
        self.goal = self._from_db(bot, 'goal', default=self.goal)
        self.rationale = self._from_db(bot, 'rationale', default=self.rationale)
        self.backstory = self._from_db(bot, 'backstory', default=self.backstory)
        # LLM Configuration:
        llm = self._from_db(bot, 'llm', default='VertexLLM')
        llm_config = self._from_db(bot, 'llm_config', default={})
        # Configuration of LLM:
        self._configure_llm(llm, llm_config)
        # Other models:
        embedding_model_name = self._from_db(
            bot, 'embedding_name', None
        )
        self.embedding_model = {
            'model': embedding_model_name,
            'model_type': 'transformers'
        }
        # Database Configuration:
        db_config = bot.database
        vector_db = db_config.pop('vector_database')
        await self.store_configuration(vector_db, db_config)
        # after configuration, setup the chatbot
        if bot.template_prompt:
            self.template_prompt = bot.template_prompt
        self._define_prompt(
            config={}
        )

    async def from_config_file(self, config_file: PurePath) -> None:
        """Load the Chatbot Configuration from the TOML file."""
        self.logger.debug(
            f"Using Config File: {config_file}"
        )
        file_config = await parse_toml_config(config_file)
        # getting the configuration from config
        self.config_file = config_file
        # basic config
        basic = file_config.get('chatbot', {})
        # Chatbot Name:
        self.name = basic.get('name', self.name)
        self.description = basic.get('description', self.description)
        self.role = basic.get('role', self.role)
        self.goal = basic.get('goal', self.goal)
        self.rationale = basic.get('rationale', self.rationale)
        self.backstory = basic.get('backstory', self.backstory)
        # Model Information:
        llminfo = file_config.get('llm')
        llm = llminfo.get('llm', 'VertexLLM')
        cfg = llminfo.get('config', {})
        # Configuration of LLM:
        self._configure_llm(llm, cfg)

        # Other models:
        models = file_config.get('models', {})
        embedding_model_name = models.get(
            'embedding',
            EMBEDDING_DEFAULT_MODEL
        )
        self.embedding_model = {
            'model': embedding_model_name,
            'model_type': 'transformers'
        }
        # pre-instructions
        instructions = file_config.get('pre-instructions')
        if instructions:
            self.pre_instructions = instructions.get('instructions', [])
        # Contextual knowledge-base
        self.kb = file_config.get('knowledge-base', [])
        if self.kb:
            self.knowledge_base = self.create_kb(
                self.kb.get('data', [])
            )
        vector_config = file_config.get('database', {})
        vector_db = vector_config.pop('vector_database')
        if vector_db:
            self._use_database = True
        # configure vector database:
        await self.store_configuration(
            vector_db,
            vector_config
        )
        # after configuration, setup the chatbot
        if 'template_prompt' in basic:
            self.template_prompt = basic.get('template_prompt')
        self._define_prompt(
            config=basic
        )
