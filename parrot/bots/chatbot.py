"""
Foundational base of every Chatbot and Agent in ai-parrot.
"""
from typing import Any, Union, Dict, List
from pathlib import Path
import uuid
from string import Template
# Navconfig
from datamodel.exceptions import ValidationError # pylint: disable=E0611
from navconfig import BASE_DIR
from navconfig.exceptions import ConfigError  # pylint: disable=E0611
from asyncdb.exceptions import NoDataFound
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
        # Tool configuration
        self.available_tool_instances: Dict[str, Any] = {}
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

    async def configure(self, app=None) -> None:
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

    def _load_tool_instances(self, tool_names: List[str]) -> None:
        """
        Load actual tool instances from tool names.
        This method should be implemented to load your actual tool classes.
        """
        # use tool names with importlib to get the actual tool classes.
        self.tools = []
        tool_registry = {}

        for tool in tool_names:
            tool_file = tool.lower().replace('tool', '')
            try:
                module = __import__(f"parrot.tools.{tool_file}", fromlist=[tool])
                tool_registry[tool] = getattr(module, tool)
            except (ImportError, AttributeError) as e:
                self.logger.error(
                    f"Error loading tool {tool}: {e}"
                )

        self.tools = []
        self.available_tool_instances = {}

        for tool_name in tool_names:
            if tool_name in tool_registry:
                try:
                    tool_class = tool_registry[tool_name]
                    tool_instance = tool_class()
                    self.tools.append(tool_instance)
                    self.available_tool_instances[tool_name] = tool_instance
                    self.logger.info(
                        f"Loaded tool: {tool_name}"
                    )
                except Exception as e:
                    self.logger.error(
                        f"Error loading tool {tool_name}: {e}"
                    )
            else:
                self.logger.warning(
                    f"Unknown tool: {tool_name}"
                )

    def _build_tools_description(self) -> str:
        """Build a formatted description of available tools for the system prompt."""
        if not self.tools:
            return ""

        tools_desc = "Available Tools:\n"
        for tool in self.tools:
            # Now tools have consistent name and description
            tools_desc += f"- {tool.name}: {tool.description}\n"

            # Optionally include parameter info
            schema = tool.get_tool_schema()
            params = schema.get('parameters', {}).get('properties', {})
            if params:
                param_desc = ", ".join([f"{k}: {v.get('description', 'no description')}"
                                    for k, v in params.items()])
                tools_desc += f"  Parameters: {param_desc}\n"

        return tools_desc

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
        self._llm_model = self._from_db(bot, 'model_name', default='gemini-2.0-flash-001')
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
            self._load_tool_instances(tool_names)
            # Build tools description for system prompt
            self.tools_description = self._build_tools_description()
        else:
            self.tools = []
            self.tools_description = ""

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

        # Other settings
        self.language = self._from_db(bot, 'language', default='en')
        self.disclaimer = self._from_db(bot, 'disclaimer', default=None)

        self.logger.info(
            f"Loaded bot configuration: "
            f"tools_enabled={self.enable_tools}, "
            f"operation_mode={self.operation_mode}, "
            f"use_vector={self._use_vector}, "
            f"tools_count={len(self.tools)}"
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
        if hasattr(self, 'tools_description') and self.tools_description:
            tools_context = f"\n\nTOOLS AVAILABLE:\n{self.tools_description}"
            tools_context += "\nUse these tools when appropriate to help answer user questions."

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

        self.system_prompt_template = final_prompt

        self.logger.debug(
            f"System prompt configured with tools: {len(self.tools)} tools available"
        )

    def get_tool_by_name(self, tool_name: str) -> Any:
        """Get a tool instance by name."""
        return self.available_tool_instances.get(tool_name)

    def add_tool_instance(self, tool_name: str, tool_instance: Any) -> None:
        """Add a tool instance to the bot."""
        if tool_instance not in self.tools:
            self.tools.append(tool_instance)
            self.available_tool_instances[tool_name] = tool_instance
            # Rebuild tools description
            self.tools_description = self._build_tools_description()
            self.logger.info(f"Added tool instance: {tool_name}")

    def remove_tool_instance(self, tool_name: str) -> bool:
        """Remove a tool instance from the bot."""
        if tool_name in self.available_tool_instances:
            tool_instance = self.available_tool_instances[tool_name]
            if tool_instance in self.tools:
                self.tools.remove(tool_instance)
            del self.available_tool_instances[tool_name]
            # Rebuild tools description
            self.tools_description = self._build_tools_description()
            self.logger.info(f"Removed tool instance: {tool_name}")
            return True
        return False

    def list_available_tools(self) -> List[Dict[str, str]]:
        """List all available tools with their descriptions."""
        return [
            {
                'name': tool.name,
                'description': getattr(tool, 'description', 'No description available'),
                'class': tool.__class__.__name__
            }
            for tool in self.tools
        ]

    def is_agent_mode(self) -> bool:
        """Check if the bot is configured to operate in agent mode."""
        return (
            self.enable_tools and
            len(self.tools) > 0 and
            self.operation_mode in ['agentic', 'adaptive']
        )

    def is_conversational_mode(self) -> bool:
        """Check if the bot is configured for pure conversational mode."""
        return (
            not self.enable_tools or
            len(self.tools) == 0 or
            self.operation_mode == 'conversational'
        )

    def get_operation_mode(self) -> str:
        """Get the current operation mode of the bot."""
        if self.operation_mode == 'adaptive':
            # In adaptive mode, determine based on current configuration
            if self.enable_tools and len(self.tools) > 0:
                return 'agentic'
            else:
                return 'conversational'
        return self.operation_mode

    async def update_database_config(self, **updates) -> bool:
        """
        Update bot configuration in database.

        Args:
            **updates: Configuration updates to apply

        Returns:
            bool: True if update was successful, False otherwise
        """
        try:
            db = self.get_database('pg', dsn=default_dsn)
            async with await db.connection() as conn:  # pylint: disable=E1101 # noqa
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
            db = self.get_database('pg', dsn=default_dsn)
            async with await db.connection() as conn:  # pylint: disable=E1101 # noqa
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
                    'tools': [tool.name for tool in self.tools] if self.tools else [],
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
            'tools_count': len(self.tools) if self.tools else 0,
            'available_tools': [tool.name for tool in self.tools] if self.tools else [],
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
                if not self.tools:
                    results['warnings'].append("Tools enabled but no tools loaded")
                else:
                    results['info'].append(f"Tools loaded: {len(self.tools)}")

                    # Test each tool
                    for tool in self.tools:
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
        tools_info = f", {len(self.tools)} tools" if self.tools else ", no tools"
        vector_info = ", vector store" if self._use_vector else ""
        return f"{self.name} ({mode} mode{tools_info}{vector_info})"
