"""
Foundational base of every Chatbot and Agent in ai-parrot.
"""
from typing import Any, Union, Dict, List, Optional, ClassVar
from pathlib import Path
import uuid
from string import Template
import importlib
import asyncio
from contextlib import asynccontextmanager
# Navconfig
from datamodel.exceptions import ValidationError # pylint: disable=E0611
from navconfig import BASE_DIR
from navconfig.exceptions import ConfigError  # pylint: disable=E0611
from asyncdb.exceptions import NoDataFound
from asyncdb import AsyncPool
from ..conf import (
    default_dsn,
    EMBEDDING_DEFAULT_MODEL,
    KB_DEFAULT_MODEL
)
from ..handlers.models import BotModel
from .abstract import AbstractBot
from ..tools import (
    AbstractTool,
)

class Chatbot(AbstractBot):
    """Represents an Bot (Chatbot, Agent) in Navigator.

    This class is the base for all chatbots and agents in the ai-parrot framework.

    This class can be used in two ways:
        1. Manual creation: bot = Chatbot(name="MyBot", tools=[...])
        2. Database loading: bot = Chatbot(name="MyBot", from_database=True)
    """
    company_information: dict = {}
    # Shared database pool for BotModel operations
    _db_pool: ClassVar[Optional[AsyncPool]] = None
    _db_pool_lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    def __init__(
        self,
        name: str = 'Nav',
        system_prompt: str = None,
        human_prompt: str = None,
        from_database: bool = True,
        tools: List[Union[str, AbstractTool]] = None,
        **kwargs
    ):
        """
        Initialize the Chatbot with manual creation or database loading support.

        Args:
            name: Bot name
            system_prompt: Custom system prompt
            human_prompt: Custom human prompt
            from_database: Whether to load configuration from database
            tools: List of tools for manual creation
            **kwargs: Additional configuration
        """
        # Other Configuration
        self.confidence_threshold: float = kwargs.get('threshold', 0.5)
        self._from_database: bool = from_database
        self._max_tools: int = kwargs.get('max_tools', 10)
        # Text Documents
        self.documents_dir: Path = kwargs.get(
            'documents_dir',
            None
        )
        # Company Information:
        self.company_information = kwargs.get(
            'company_information',
            self.company_information
        )
        # Tool configuration
        self.available_tool_instances: Dict[str, Any] = {}
        super().__init__(
            name=name,
            system_prompt=system_prompt,
            human_prompt=human_prompt,
            tools= tools,
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

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------
    @classmethod
    async def _get_db_pool(cls) -> AsyncPool:
        """Return a shared async database pool for bot metadata."""
        if not default_dsn:
            raise ConfigError(
                "Database DSN is not configured; cannot load bots from database"
            )

        pool = cls._db_pool
        if pool is not None and pool.is_connected() and not pool.event_loop_is_closed():
            return pool

        async with cls._db_pool_lock:
            pool = cls._db_pool
            if pool is not None and pool.is_connected() and not pool.event_loop_is_closed():
                return pool

            pool = AsyncPool('pg', dsn=default_dsn)
            await pool.connect()  # pylint: disable=E1101 # noqa
            cls._db_pool = pool
            return pool

    @classmethod
    @asynccontextmanager
    async def _botmodel_connection(cls):
        """Context manager that yields a pooled connection for BotModel operations."""
        pool = await cls._get_db_pool()
        connection = None
        try:
            connection = await pool.acquire()
            yield connection
        finally:
            if connection is not None:
                await pool.release(connection)

    def __repr__(self):
        return f"<ChatBot.{self.__class__.__name__}:{self.name}>"

    async def configure(self, app=None) -> None:
        """Load configuration for this Chatbot."""
        if self._from_database:
            bot = None
            try:
                bot = await self.bot_exists(name=self.name, uuid=self.chatbot_id)
            except Exception as exc:  # pragma: no cover - defensive logging
                self.logger.error(
                    (
                        f"Failed to load bot '{self.name}' metadata from database: {exc}. "
                        "Falling back to manual configuration."
                    ),
                    exc_info=True,
                )
            if bot:
                self.logger.notice(
                    f"Loading Bot {self.name} from Database: {bot.chatbot_id}"
                )
                # Bot exists on Database, Configure from the Database
                await self.from_database(bot)
            else:
                self.logger.warning(
                    f"Bot {self.name} not found or database unavailable, falling back to manual configuration"
                )
                self._from_database = False
                await self.from_manual_config()
        else:
            # Manual configuration
            await self.from_manual_config()
        # Call parent configuration
        await super().configure(app)

    def _from_bot(self, bot, key, config, default) -> Any:
        value = getattr(bot, key, None)
        file_value = config.get(key, default)
        return value if value else file_value

    def _from_db(self, botobj, key, default = None) -> Any:
        value = getattr(botobj, key, default)
        return value if value else default

    def import_kb_class(self, kb_path: str):
        try:
            # Split the path to get module and class name
            module_path, class_name = kb_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            return getattr(module, class_name)
        except (ValueError, ImportError, AttributeError) as e:
            self.logger.error(
                f"Failed to import KB class from {kb_path}: {e}"
            )
            return None

    async def from_manual_config(self) -> None:
        """
        Configure the bot manually without database dependency.
        """
        self.logger.info(f"Configuring bot {self.name} manually")

        # Set up basic configuration with defaults
        self.pre_instructions: list = getattr(self, 'pre_instructions', [])
        self.description = getattr(self, 'description', f"AI Assistant: {self.name}")
        self.role = getattr(self, 'role', 'AI Assistant')
        self.goal = getattr(self, 'goal', 'Help users accomplish their tasks effectively')
        self.rationale = getattr(self, 'rationale', self.default_rationale())
        self.backstory = getattr(self, 'backstory', 'I am an AI assistant created to help users with various tasks.')
        self.capabilities = getattr(self, 'capabilities', 'I can engage in conversation, answer questions, and use tools when needed.')

        # LLM Configuration with defaults
        self._llm = getattr(self, '_llm', 'google')
        self._llm_model = getattr(self, '_llm_model', 'gemini-2.0-flash-001')
        self._llm_temp = getattr(self, '_llm_temp', 0.1)
        self._max_tokens = getattr(self, '_max_tokens', 1024)
        self._top_k = getattr(self, '_top_k', 41)
        self._top_p = getattr(self, '_top_p', 0.9)
        self._llm_config = getattr(self, '_llm_config', {})

        # Tool and agent configuration
        self.auto_tool_detection = getattr(self, 'auto_tool_detection', True)
        self.tool_threshold = getattr(self, 'tool_threshold', 0.7)
        self.operation_mode = getattr(self, 'operation_mode', 'adaptive')
        # Embedding Model Configuration
        self.embedding_model: dict = getattr(self, 'embedding_model', {
            'model_name': EMBEDDING_DEFAULT_MODEL,
            'model_type': 'huggingface'
        })

        # Vector store configuration
        self._use_vector = getattr(self, '_use_vector', False)
        self._vector_store = getattr(self, '_vector_store', {})
        self._metric_type = getattr(self, '_metric_type', 'COSINE')

        # Memory and conversation configuration
        self.memory_type = getattr(self, 'memory_type', 'memory')
        self.memory_config = getattr(self, 'memory_config', {})
        self.max_context_turns = getattr(self, 'max_context_turns', 5)
        self.use_conversation_history = getattr(self, 'use_conversation_history', True)

        # Context and retrieval settings
        self.context_search_limit = getattr(self, 'context_search_limit', 10)
        self.context_score_threshold = getattr(self, 'context_score_threshold', 0.7)

        # Security and permissions
        _default = self.default_permissions()
        _permissions = getattr(self, '_permissions', {})
        self._permissions = {**_default, **_permissions}

        # Other settings
        self.language = getattr(self, 'language', 'en')
        self.disclaimer = getattr(self, 'disclaimer', None)

        self.logger.info(
            f"Manual configuration complete: "
            f"tools_enabled={self.enable_tools}, "
            f"operation_mode={self.operation_mode}, "
            f"use_vector={self._use_vector}, "
            f"tools_count={self.tool_manager.tool_count()}"
        )

    async def bot_exists(
        self,
        name: str = None,
        uuid: uuid.UUID = None
    ) -> Union[BotModel, bool]:
        """Check if the Chatbot exists in the Database."""
        try:
            async with self._botmodel_connection() as conn:  # pylint: disable=E1101
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
                except NoDataFound:
                    return False
                except Exception as exc:  # pragma: no cover - unexpected database error
                    self.logger.error(
                        f"Error retrieving bot from database: {exc}",
                        exc_info=True,
                    )
        except Exception as exc:  # pragma: no cover - database unavailable
            self.logger.error(
                f"Database error while checking bot existence: {exc}",
                exc_info=True,
            )
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
            async with self._botmodel_connection() as conn:  # pylint: disable=E1101
                # import model
                BotModel.Meta.connection = conn
                try:
                    if self.chatbot_id:
                        try:
                            bot = await BotModel.get(chatbot_id=self.chatbot_id)
                        except Exception:
                            bot = await BotModel.get(name=self.name)
                    else:
                        bot = await BotModel.get(name=self.name)
                except ValidationError as ex:
                    # Handle ValidationError
                    self.logger.error(f"Validation error: {ex}")
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

        # Bot personality and behavior
        self.role = self._from_db(bot, 'role', default=self.role)
        self.goal = self._from_db(bot, 'goal', default=self.goal)
        self.rationale = self._from_db(bot, 'rationale', default=self.rationale)
        self.backstory = self._from_db(bot, 'backstory', default=self.backstory)
        self.capabilities = self._from_db(bot, 'capabilities', default='')

        # Prompt configuration
        if bot.system_prompt_template:
            self.system_prompt_template = bot.system_prompt_template
        if bot.human_prompt_template:
            self.human_prompt_template = bot.human_prompt_template

        # LLM Configuration
        self._llm = self._from_db(bot, 'llm', default='google')
        self._llm_model = self._from_db(bot, 'model_name', default='gemini-2.5-flash')
        self._llm_temp = self._from_db(bot, 'temperature', default=0.1)
        self._max_tokens = self._from_db(bot, 'max_tokens', default=1024)
        self._top_k = self._from_db(bot, 'top_k', default=41)
        self._top_p = self._from_db(bot, 'top_p', default=0.9)
        self._llm_config = self._from_db(bot, 'model_config', default={})

        # Tool and agent configuration
        self.enable_tools = self._from_db(bot, 'tools_enabled', default=True)
        self.auto_tool_detection = self._from_db(bot, 'auto_tool_detection', default=True)
        self.tool_threshold = self._from_db(bot, 'tool_threshold', default=0.7)
        self.operation_mode = self._from_db(bot, 'operation_mode', default='adaptive')

        # Load tools from database
        tool_names = self._from_db(bot, 'tools', default=[])
        if tool_names and self.enable_tools:
            self.tool_manager.register_tools(tool_names)

        # Embedding Model Configuration
        self.embedding_model: dict = self._from_db(
            bot, 'embedding_model', default={
                'model_name': EMBEDDING_DEFAULT_MODEL,
                'model_type': 'huggingface'
            }
        )

        # Vector store configuration
        self._use_vector = self._from_db(bot, 'use_vector', default=False)
        self._vector_store = self._from_db(bot, 'vector_store_config', default={})
        self._metric_type = self._vector_store.get('metric_type', self._metric_type)

        # Memory and conversation configuration
        self.memory_type = self._from_db(bot, 'memory_type', default='memory')
        self.memory_config = self._from_db(bot, 'memory_config', default={})
        self.max_context_turns = self._from_db(bot, 'max_context_turns', default=5)
        self.use_conversation_history = self._from_db(bot, 'use_conversation_history', default=True)

        # Context and retrieval settings
        self.context_search_limit = self._from_db(bot, 'context_search_limit', default=10)
        self.context_score_threshold = self._from_db(bot, 'context_score_threshold', default=0.7)

        # Security and permissions
        _default = self.default_permissions()
        _permissions = self._from_db(bot, 'permissions', default={})
        self._permissions = {**_default, **_permissions}

        # Knowledge Base:
        self.use_kb = self._from_db(bot, 'use_kb', default=False)
        self._kb = self._from_db(bot, 'kb', default=[])
        if self.use_kb:
            from ..stores.kb.store import KnowledgeBaseStore
            self.kb_store = KnowledgeBaseStore(
                embedding_model=KB_DEFAULT_MODEL,
                dimension=384
            )

        # Custom Knowledge Bases
        self.custom_kbs = self._from_db(bot, 'custom_kbs', default=[])
        if self.custom_kbs:
            for kb_path in self.custom_kbs:
                kb_class = self.import_kb_class(kb_path)
                if kb_class:
                    self.register_kb(kb_class)

        # Other settings
        self.language = self._from_db(bot, 'language', default='en')
        self.disclaimer = self._from_db(bot, 'disclaimer', default=None)

        self.logger.info(
            f"Loaded bot configuration: "
            f"tools_enabled={self.enable_tools}, "
            f"operation_mode={self.operation_mode}, "
            f"use_vector={self._use_vector}, "
            f"tools_count={self.tool_manager.tool_count()}"
        )

    def _define_prompt(self, config: dict = None, **kwargs):
        """
        Enhanced prompt definition that includes tools information.
        """
        # Setup the prompt variables
        if config:
            for key, val in config.items():
                setattr(self, key, val)

        # Build pre-context
        pre_context = ''
        if self.pre_instructions:
            pre_context = "IMPORTANT PRE-INSTRUCTIONS: \n"
            pre_context += "\n".join(f"- {a}." for a in self.pre_instructions)

        # Build tools context if tools are available
        tools_context = ''
        # Apply template substitution
        tmpl = Template(self.system_prompt_template)
        final_prompt = tmpl.safe_substitute(
            name=self.name,
            role=self.role,
            goal=self.goal,
            capabilities=self.capabilities,
            backstory=self.backstory,
            rationale=self.rationale,
            pre_context=pre_context,
            tools_context=tools_context,
            **kwargs
        )
        # Set the system prompt
        self.system_prompt_template = final_prompt
        if self._debug:
            print(' SYSTEM PROMPT ')
            print(final_prompt)

    async def update_database_config(self, **updates) -> bool:
        """
        Update bot configuration in database.

        Args:
            **updates: Configuration updates to apply

        Returns:
            bool: True if update was successful, False otherwise
        """
        try:
            async with self._botmodel_connection() as conn:  # pylint: disable=E1101 # noqa
                BotModel.Meta.connection = conn
                bot = await BotModel.get(chatbot_id=self.chatbot_id)

                # Apply updates
                for key, value in updates.items():
                    if hasattr(bot, key):
                        setattr(bot, key, value)

                # Save changes
                await bot.update()
                self.logger.info(f"Updated bot configuration in database: {list(updates.keys())}")
                return True

        except Exception as e:
            self.logger.error(f"Error updating bot configuration: {e}")
            return False

    async def save_to_database(self) -> bool:
        """
        Save current bot configuration to database.

        Returns:
            bool: True if save was successful, False otherwise
        """
        try:
            async with self._botmodel_connection() as conn:  # pylint: disable=E1101 # noqa
                BotModel.Meta.connection = conn

                # Create or update bot model
                bot_data = {
                    'chatbot_id': self.chatbot_id,
                    'name': self.name,
                    'description': self.description,
                    'role': self.role,
                    'goal': self.goal,
                    'backstory': self.backstory,
                    'rationale': self.rationale,
                    'capabilities': getattr(self, 'capabilities', ''),
                    'system_prompt_template': self.system_prompt_template,
                    'human_prompt_template': getattr(self, 'human_prompt_template', None),
                    'pre_instructions': self.pre_instructions,
                    'llm': self._llm,
                    'model_name': self._llm_model,
                    'temperature': self._llm_temp,
                    'max_tokens': self._max_tokens,
                    'top_k': self._top_k,
                    'top_p': self._top_p,
                    'model_config': self._llm_config,
                    'tools_enabled': getattr(self, 'enable_tools', True),
                    'auto_tool_detection': getattr(self, 'auto_tool_detection', True),
                    'tool_threshold': getattr(self, 'tool_threshold', 0.7),
                    'tools': [tool.name for tool in self.tool_manager.list_tools()] if self.tool_manager else [],
                    'operation_mode': getattr(self, 'operation_mode', 'adaptive'),
                    'use_vector': self._use_vector,
                    'vector_store_config': self._vector_store,
                    'embedding_model': self.embedding_model,
                    'context_search_limit': getattr(self, 'context_search_limit', 10),
                    'context_score_threshold': getattr(self, 'context_score_threshold', 0.7),
                    'memory_type': getattr(self, 'memory_type', 'memory'),
                    'memory_config': getattr(self, 'memory_config', {}),
                    'max_context_turns': getattr(self, 'max_context_turns', 5),
                    'use_conversation_history': getattr(self, 'use_conversation_history', True),
                    'permissions': self._permissions,
                    'language': getattr(self, 'language', 'en'),
                    'disclaimer': getattr(self, 'disclaimer', None),
                }

                try:
                    # Try to get existing bot
                    bot = await BotModel.get(chatbot_id=self.chatbot_id)
                    # Update existing
                    for key, value in bot_data.items():
                        setattr(bot, key, value)
                    await bot.update()
                    self.logger.info(f"Updated existing bot {self.name} in database")

                except NoDataFound:
                    # Create new bot
                    bot = BotModel(**bot_data)
                    await bot.save()
                    self.logger.info(f"Created new bot {self.name} in database")

                return True

        except Exception as e:
            self.logger.error(f"Error saving bot to database: {e}")
            return False

    def get_configuration_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the current bot configuration.

        Returns:
            Dict containing configuration summary
        """
        return {
            'name': self.name,
            'chatbot_id': self.chatbot_id,
            'operation_mode': getattr(self, 'operation_mode', 'adaptive'),
            'current_mode': self.get_operation_mode(),
            'tools_enabled': getattr(self, 'enable_tools', False),
            'tools_count': self.tool_manager.tool_count() if self.tool_manager else 0,
            'available_tools': self.tool_manager.list_tools() if self.tool_manager else [],
            'use_vector_store': self._use_vector,
            'vector_store_type': self._vector_store.get('name', 'none') if self._vector_store else 'none',
            'llm': self._llm,
            'model_name': self._llm_model,
            'memory_type': getattr(self, 'memory_type', 'memory'),
            'max_context_turns': getattr(self, 'max_context_turns', 5),
            'auto_tool_detection': getattr(self, 'auto_tool_detection', True),
            'tool_threshold': getattr(self, 'tool_threshold', 0.7),
            'language': getattr(self, 'language', 'en'),
        }

    async def test_configuration(self) -> Dict[str, Any]:
        """
        Test the current bot configuration and return status.

        Returns:
            Dict containing test results
        """
        results = {
            'status': 'success',
            'errors': [],
            'warnings': [],
            'info': []
        }

        try:
            # Test database connection
            if not await self.bot_exists(name=self.name):
                results['warnings'].append(f"Bot {self.name} not found in database")
            else:
                results['info'].append("Database connection: OK")

            # Test LLM configuration
            if not self._llm:
                results['errors'].append("No LLM configured")
            else:
                results['info'].append(f"LLM configured: {self._llm}")

            # Test tools configuration
            if getattr(self, 'enable_tools', False):
                if not self.tool_manager:
                    results['warnings'].append("Tools enabled but no tools loaded")
                else:
                    results['info'].append(f"Tools loaded: {len(self.tool_manager.list_tools())}")

                    # Test each tool
                    for tool in self.tool_manager.list_tools():
                        try:
                            # Basic tool validation
                            if not hasattr(tool, 'name'):
                                results['errors'].append(f"Tool {tool.__class__.__name__} missing name attribute")
                            else:
                                results['info'].append(f"Tool {tool.name}: OK")
                        except Exception as e:
                            results['errors'].append(f"Tool {tool.__class__.__name__} error: {e}")

            # Test vector store configuration
            if self._use_vector:
                if not self._vector_store:
                    results['errors'].append("Vector store enabled but not configured")
                else:
                    results['info'].append("Vector store configured")

            # Set overall status
            if results['errors']:
                results['status'] = 'error'
            elif results['warnings']:
                results['status'] = 'warning'

        except Exception as e:
            results['status'] = 'error'
            results['errors'].append(f"Configuration test failed: {e}")

        return results

    async def reload_from_database(self) -> bool:
        """
        Reload bot configuration from database.

        Returns:
            bool: True if reload was successful, False otherwise
        """
        try:
            if bot := await self.bot_exists(name=self.name, uuid=self.chatbot_id):
                await self.from_database(bot)
                self.logger.info(f"Reloaded bot {self.name} configuration from database")
                return True
            else:
                self.logger.error(f"Bot {self.name} not found in database for reload")
                return False
        except Exception as e:
            self.logger.error(f"Error reloading bot configuration: {e}")
            return False

    def __str__(self) -> str:
        """String representation of the bot."""
        mode = self.get_operation_mode()
        tools_info = f", {self.tool_manager.tool_count()} tools" if self.enable_tools else ", no tools"
        vector_info = ", vector store" if self._use_vector else ""
        return f"{self.name} ({mode} mode{tools_info}{vector_info})"
