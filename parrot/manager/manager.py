"""
Chatbot Manager.

Tool for instanciate, managing and interacting with Chatbot through APIs.
"""
from typing import Any, Dict, Type, Optional, Tuple
from importlib import import_module
import contextlib
from aiohttp import web
from datamodel.exceptions import ValidationError  # pylint: disable=E0611 # noqa
# Navigator:
from navconfig.logging import logging
from asyncdb.exceptions import NoDataFound
from ..bots.abstract import AbstractBot
from ..bots.basic import BasicBot
from ..bots.chatbot import Chatbot
from ..bots.agent import BasicAgent
from ..handlers.chat import ChatHandler, BotHandler
from ..handlers.agent import AgentTalk
from ..handlers import ChatbotHandler
from ..handlers.models import BotModel
from ..handlers.stream import StreamHandler
from ..registry import agent_registry, AgentRegistry
# Crew:
from ..bots.orchestration.crew import AgentCrew
from ..handlers.crew.models import CrewDefinition
from ..handlers.crew.handler import CrewHandler
from ..openapi.config import setup_swagger
from ..conf import ENABLE_SWAGGER


class BotManager:
    """BotManager.

    Manage Bots/Agents and interact with them through via aiohttp App.
    Deploy and manage chatbots and agents using a RESTful API.

    """
    app: web.Application = None

    def __init__(self) -> None:
        self.app = None
        self._bots: Dict[str, AbstractBot] = {}
        self.logger = logging.getLogger(
            name='Parrot.Manager'
        )
        self.registry: AgentRegistry = agent_registry
        self._crews: Dict[str, Tuple[AgentCrew, CrewDefinition]] = {}

    def get_bot_class(self, bot_name: str) -> Optional[Type]:
        """
        Get bot class by name, searching in:
        1. parrot.bots (core bots)
        2. parrot.agents (plugin agents)

        Args:
            bot_name: Name of the bot/agent class

        Returns:
            Bot class if found, None otherwise
        """
        # First, try to import from core bots
        with contextlib.suppress(ImportError, AttributeError):
            module = import_module("parrot.bots")
            if hasattr(module, bot_name):
                return getattr(module, bot_name)

        # Second, try to import from plugin agents
        with contextlib.suppress(ImportError, AttributeError):
            agent_module_name = f"parrot.agents.{bot_name.lower()}"
            module = import_module(agent_module_name)
            if hasattr(module, bot_name):
                return getattr(module, bot_name)

        # Third, try direct import from parrot.agents package
        # (in case the agent is defined in plugins/agents/__init__.py)
        with contextlib.suppress(ImportError, AttributeError):
            module = import_module("parrot.agents")
            if hasattr(module, bot_name):
                return getattr(module, bot_name)

        self.logger.warning(
            f"Warning: Bot class '{bot_name}' not found in parrot.bots or parrot.agents"
        )
        return None

    def get_or_create_bot(self, bot_name: str, **kwargs):
        """
        Get existing bot or create new one from class name.

        Args:
            bot_name: Name of the bot/agent class
            **kwargs: Arguments to pass to bot constructor

        Returns:
            Bot instance
        """
        # Check if already instantiated
        if bot_name in self._bots:
            return self._bots[bot_name]

        # Get the class and instantiate
        bot_class = self.get_bot_class(bot_name)
        if bot_class is None:
            raise ValueError(f"Bot class '{bot_name}' not found")

        return self.create_bot(class_name=bot_class, name=bot_name, **kwargs)

    def _log_final_state(self) -> None:
        """Log the final state of bot loading."""
        registry_info = self.registry.get_registration_info()
        self.logger.notice("=== Bot Loading Complete ===")
        self.logger.notice(f"Registered agents: {registry_info['total_registered']}")
        # self.logger.info(f"Startup agents: {startup_info['total_startup_agents']}")
        self.logger.notice(f"Active bots: {len(self._bots)}")

    async def _process_startup_results(self, startup_results: Dict[str, Any]) -> None:
        """Process startup instantiation results."""
        for agent_name, result in startup_results.items():
            if result["status"] == "success":
                if instance := result.get("instance"):
                    self._bots[agent_name] = instance
                    self.logger.info(
                        f"Added startup agent to active bots: {agent_name}"
                    )
            else:
                self.logger.error(
                    f"Startup agent {agent_name} failed: {result['error']}"
                )

    async def load_bots(self, app: web.Application) -> None:
        """Enhanced bot loading using the registry."""
        self.logger.info("Starting bot loading with global registry")

        # Step 1: Import modules to trigger decorator registration
        await self.registry.load_modules()

        # Step 2: Register config-based agents
        config_count = self.registry.discover_config_agents()
        self.logger.info(
            f"Registered {config_count} agents from config"
        )

        # Step 3: Instantiate startup agents
        startup_results = await self.registry.instantiate_startup_agents(app)
        await self._process_startup_results(startup_results)

        # Step 4: Load database bots
        await self._load_database_bots(app)

        # Step 5: Report final state
        self._log_final_state()

    async def _load_database_bots(self, app: web.Application) -> None:
        """Load bots from database."""
        try:
            # Import here to avoid circular imports
            from ..handlers.models import BotModel  # pylint: disable=import-outside-toplevel # noqa
            db = app['database']
            async with await db.acquire() as conn:
                BotModel.Meta.connection = conn
                try:
                    all_bots = await BotModel.filter(enabled=True)
                except Exception as e:
                    self.logger.error(
                        f"Failed to load bots from DB: {e}"
                    )
                    return

            for bot_model in all_bots:
                self.logger.notice(
                    f"Loading bot '{bot_model.name}' (mode: {bot_model.operation_mode})..."
                )
                if bot_model.name in self._bots:
                    self.logger.debug(
                        f"Bot {bot_model.name} already active, skipping"
                    )
                    continue
                try:
                    # Use the factory function from models.py or create bot directly
                    if hasattr(self, 'get_bot_class') and hasattr(bot_model, 'bot_class'):
                        # If you have a bot_class field and get_bot_class method
                        class_name = self.get_bot_class(getattr(bot_model, 'bot_class', None))
                    else:
                        # Default to BasicBot or your default bot class
                        class_name = BasicBot
                    bot_instance = class_name(
                        chatbot_id=bot_model.chatbot_id,
                        name=bot_model.name,
                        description=bot_model.description,
                        # LLM configuration
                        use_llm=bot_model.llm,
                        model_name=bot_model.model_name,
                        model_config=bot_model.model_config,
                        temperature=bot_model.temperature,
                        max_tokens=bot_model.max_tokens,
                        top_k=bot_model.top_k,
                        top_p=bot_model.top_p,
                        # Bot personality
                        role=bot_model.role,
                        goal=bot_model.goal,
                        backstory=bot_model.backstory,
                        rationale=bot_model.rationale,
                        capabilities=bot_model.capabilities,
                        # Prompt configuration
                        system_prompt=bot_model.system_prompt_template,
                        human_prompt=bot_model.human_prompt_template,
                        pre_instructions=bot_model.pre_instructions,
                        # Vector store configuration
                        embedding_model=bot_model.embedding_model,
                        use_vectorstore=bot_model.use_vector,
                        vector_store_config=bot_model.vector_store_config,
                        context_search_limit=bot_model.context_search_limit,
                        context_score_threshold=bot_model.context_score_threshold,
                        # Tool and agent configuration
                        tools_enabled=bot_model.tools_enabled,
                        auto_tool_detection=bot_model.auto_tool_detection,
                        tool_threshold=bot_model.tool_threshold,
                        available_tools=bot_model.tools,
                        operation_mode=bot_model.operation_mode,
                        # Memory configuration
                        memory_type=bot_model.memory_type,
                        memory_config=bot_model.memory_config,
                        max_context_turns=bot_model.max_context_turns,
                        use_conversation_history=bot_model.use_conversation_history,
                        # Security and permissions
                        permissions=bot_model.permissions,
                        # Metadata
                        language=bot_model.language,
                        disclaimer=bot_model.disclaimer,
                    )
                    # Set the model ID reference
                    bot_instance.model_id = bot_model.chatbot_id

                    await bot_instance.configure(app)
                    self.add_bot(bot_instance)
                    self.logger.info(
                        f"Successfully loaded bot '{bot_model.name}' "
                        f"with {len(bot_model.tools) if bot_model.tools else 0} tools"
                    )
                except ValidationError as e:
                        self.logger.error(
                            f"Invalid configuration for bot '{bot_model.name}': {e}"
                        )
                except Exception as e:
                    self.logger.error(
                        f"Failed to load database bot {bot_instance.name}: {str(e)}"
                    )
            self.logger.info(
                f":: Bots loaded successfully. Total active bots: {len(self._bots)}"
            )
        except Exception as e:
            self.logger.error(
                f"Database bot loading failed: {str(e)}"
            )

    # Alternative approach using the factory function from models.py
    async def load_bots_with_factory(self, app: web.Application) -> None:
        """Load all bots from DB using the factory function."""
        self.logger.info("Loading bots from DB...")
        db = app['database']
        async with await db.acquire() as conn:
            BotModel.Meta.connection = conn
            try:
                bot_models = await BotModel.filter(enabled=True)
            except Exception as e:
                self.logger.error(
                    f"Failed to load bots from DB: {e}"
                )
                return

            for bot_model in bot_models:
                self.logger.notice(
                    f"Loading bot '{bot_model.name}' (mode: {bot_model.operation_mode})..."
                )

                try:
                    # Use the factory function from models.py
                    # Determine bot class if you have custom classes
                    bot_class = None
                    if hasattr(self, 'get_bot_class') and hasattr(bot_model, 'bot_class'):
                        bot_class = self.get_bot_class(getattr(bot_model, 'bot_class', None))
                    else:
                        # Default to BasicBot or your default bot class
                        bot_class = BasicBot

                    # Create bot using factory function
                    chatbot = bot_class(bot_model, bot_class)

                    # Configure the bot
                    try:
                        await chatbot.configure(app=app)
                        self.add_bot(chatbot)
                        self.logger.info(
                            f"Successfully loaded bot '{bot_model.name}' "
                            f"with {len(bot_model.tools) if bot_model.tools else 0} tools"
                        )
                    except ValidationError as e:
                        self.logger.error(
                            f"Invalid configuration for bot '{bot_model.name}': {e}"
                        )
                    except Exception as e:
                        self.logger.error(
                            f"Failed to configure bot '{bot_model.name}': {e}"
                        )

                except Exception as e:
                    self.logger.error(
                        f"Failed to create bot instance for '{bot_model.name}': {e}"
                    )
                    continue

        self.logger.info(
            f":: Bots loaded successfully. Total active bots: {len(self._bots)}"
        )

    def create_bot(self, class_name: Any = None, name: str = None, **kwargs) -> AbstractBot:
        """Create a Bot and add it to the manager."""
        if class_name is None:
            class_name = Chatbot
        chatbot = class_name(**kwargs)
        chatbot.name = name
        return chatbot

    def add_bot(self, bot: AbstractBot) -> None:
        """Add a Bot to the manager."""
        self._bots[bot.name] = bot

    async def get_bot(self, name: str) -> AbstractBot:
        """Get a Bot by name."""
        if name in self._bots:
            return self._bots[name]
        if self.registry.has(name):
            print('::::: HERE > Getting bot from registry:', name)
            try:
                bot_instance = await self.registry.get_instance(name)
                if bot_instance:
                    if not bot_instance.is_configured:
                        await bot_instance.configure(self.app)
                    self.add_bot(bot_instance)
                    return bot_instance
            except Exception as e:
                self.logger.error(
                    f"Failed to get bot instance from registry: {e}"
                )
        return None

    def remove_bot(self, name: str) -> None:
        """Remove a Bot by name."""
        del self._bots[name]

    def get_bots(self) -> Dict[str, AbstractBot]:
        """Get all Bots declared on Manager."""
        return self._bots

    async def create_agent(self, class_name: Any = None, name: str = None, **kwargs) -> AbstractBot:
        if class_name is None:
            class_name = BasicAgent
        return class_name(name=name, **kwargs)

    def add_agent(self, agent: AbstractBot) -> None:
        """Add a Agent to the manager."""
        self._bots[str(agent.chatbot_id)] = agent

    def get_agent(self, name: str) -> AbstractBot:
        """Get a Agent by ID."""
        return self._bots.get(name)

    def remove_agent(self, agent: AbstractBot) -> None:
        """Remove a Bot by name."""
        del self._bots[str(agent.chatbot_id)]

    async def save_agent(self, name: str, **kwargs) -> None:
        """Save a Agent to the DB."""
        self.logger.info(f"Saving Agent {name} into DB ...")
        db = self.app['database']
        async with await db.acquire() as conn:
            BotModel.Meta.connection = conn
            try:
                try:
                    bot = await BotModel.get(name=name)
                except NoDataFound:
                    bot = None
                if bot:
                    self.logger.info(f"Bot {name} already exists.")
                    for key, val in kwargs.items():
                        bot.set(key, val)
                    await bot.update()
                    self.logger.info(f"Bot {name} updated.")
                else:
                    self.logger.info(f"Bot {name} not found. Creating new one.")
                    # Create a new Bot
                    new_bot = BotModel(
                        name=name,
                        **kwargs
                    )
                    await new_bot.insert()
                self.logger.info(f"Bot {name} saved into DB.")
                return True
            except Exception as e:
                self.logger.error(
                    f"Failed to Create new Bot {name} from DB: {e}"
                )
                return None

    def get_app(self) -> web.Application:
        """Get the app."""
        if self.app is None:
            raise RuntimeError("App is not set.")
        return self.app

    def setup(self, app: web.Application) -> web.Application:
        self.app = None
        if app:
            self.app = app if isinstance(app, web.Application) else app.get_app()
        # register signals for startup and shutdown
        self.app.on_startup.append(self.on_startup)
        self.app.on_shutdown.append(self.on_shutdown)
        # Add Manager to main Application:
        self.app['bot_manager'] = self
        ## Configure Routes
        router = self.app.router
        # Chat Information Router
        router.add_view(
            '/api/v1/chats',
            ChatHandler
        )
        router.add_view(
            '/api/v1/chat/{chatbot_name}',
            ChatHandler
        )
        router.add_view(
            '/api/v1/chat/{chatbot_name}/{method_name}',
            ChatHandler
        )
        # Talk with agents:
        router.add_view(
            '/api/v1/agents/chat/{agent_id}',
            AgentTalk
        )
        router.add_view(
            '/api/v1/agents/chat/{agent_id}/{method_name}',
            AgentTalk
        )
        # ChatBot Manager
        ChatbotHandler.configure(self.app, '/api/v1/bots')
        # Bot Handler
        router.add_view(
            '/api/v1/chatbots',
            BotHandler
        )
        router.add_view(
            '/api/v1/chatbots/{name}',
            BotHandler
        )
        # Streaming Handler:
        st = StreamHandler()
        # websocket endpoint
        router.add_get('/ws/stream/{bot_id}', st.stream_websocket)
        # sse endpoint
        router.add_post('/api/v1/stream/sse/{bot_id}', st.stream_sse)
        # ndjson endpoint
        router.add_post('/api/v1/stream/ndjson/{bot_id}', st.stream_ndjson)
        # chunked endpoint
        router.add_post('/api/v1/stream/chunked/{bot_id}', st.stream_chunked)
        # Crew Configuration
        CrewHandler.configure(self.app, '/api/v1/crew')
        if ENABLE_SWAGGER:
            self.logger.info("Setting up OpenAPI documentation...")
            setup_swagger(self.app)
        self.logger.info("""
✅ OpenAPI Documentation configured successfully!

Available documentation UIs:
- Swagger UI:  http://localhost:5000/api/docs
- ReDoc:       http://localhost:5000/api/docs/redoc
- RapiDoc:     http://localhost:5000/api/docs/rapidoc
- OpenAPI Spec: http://localhost:5000/api/docs/swagger.json
        """)
        return self.app

    async def on_startup(self, app: web.Application) -> None:
        """On startup."""
        # configure all pre-configured chatbots:
        await self.load_bots(app)

    async def on_shutdown(self, app: web.Application) -> None:
        """On shutdown."""
        pass

    def add_crew(
        self,
        name: str,
        crew: AgentCrew,
        crew_def: CrewDefinition
    ) -> None:
        """
        Register a crew in the manager.

        Args:
            name: Unique name for the crew
            crew: AgentCrew instance
            crew_def: Crew definition containing metadata

        Raises:
            ValueError: If crew with same name already exists
        """
        if name in self._crews:
            raise ValueError(f"Crew '{name}' already exists")

        self._crews[name] = (crew, crew_def)
        self.logger.info(
            f"Registered crew '{name}' with {len(crew.agents)} agents "
            f"in {crew_def.execution_mode.value} mode"
        )

    def get_crew(
        self,
        identifier: str
    ) -> Optional[Tuple[AgentCrew, CrewDefinition]]:
        """
        Get a crew by name or ID.

        Args:
            identifier: Crew name or crew_id

        Returns:
            Tuple of (AgentCrew, CrewDefinition) if found, None otherwise
        """
        # Try by name first
        if identifier in self._crews:
            return self._crews[identifier]

        return next(
            (
                (crew, crew_def)
                for name, (crew, crew_def) in self._crews.items()
                if crew_def.crew_id == identifier
            ),
            None,
        )

    def list_crews(self) -> Dict[str, Tuple[AgentCrew, CrewDefinition]]:
        """
        List all registered crews.

        Returns:
            Dictionary mapping crew names to (AgentCrew, CrewDefinition) tuples
        """
        return self._crews.copy()

    def remove_crew(self, identifier: str) -> bool:
        """
        Remove a crew from the manager.

        Args:
            identifier: Crew name or crew_id

        Returns:
            True if removed, False if not found
        """
        # Try by name first
        if identifier in self._crews:
            del self._crews[identifier]
            self.logger.info(f"Removed crew '{identifier}'")
            return True

        # Try by crew_id
        for name, (crew, crew_def) in list(self._crews.items()):
            if crew_def.crew_id == identifier:
                del self._crews[name]
                self.logger.info(f"Removed crew '{name}' (ID: {identifier})")
                return True

        return False

    def update_crew(
        self,
        identifier: str,
        crew: AgentCrew,
        crew_def: CrewDefinition
    ) -> bool:
        """
        Update an existing crew.

        Args:
            identifier: Crew name or crew_id
            crew: Updated AgentCrew instance
            crew_def: Updated crew definition

        Returns:
            True if updated, False if not found
        """
        # Find crew by name or ID
        crew_name = None
        if identifier in self._crews:
            crew_name = identifier
        else:
            for name, (_, def_) in self._crews.items():
                if def_.crew_id == identifier:
                    crew_name = name
                    break

        if crew_name:
            self._crews[crew_name] = (crew, crew_def)
            self.logger.info(f"Updated crew '{crew_name}'")
            return True

        return False

    def get_crew_stats(self) -> Dict[str, Any]:
        """
        Get statistics about registered crews.

        Returns:
            Dictionary with crew statistics
        """
        stats = {
            'total_crews': len(self._crews),
            'crews_by_mode': {
                'sequential': 0,
                'parallel': 0,
                'flow': 0
            },
            'total_agents': 0,
            'crews': []
        }

        for name, (crew, crew_def) in self._crews.items():
            mode = crew_def.execution_mode.value
            stats['crews_by_mode'][mode] = stats['crews_by_mode'].get(mode, 0) + 1
            stats['total_agents'] += len(crew.agents)

            stats['crews'].append({
                'name': name,
                'crew_id': crew_def.crew_id,
                'mode': mode,
                'agent_count': len(crew.agents)
            })

        return stats
