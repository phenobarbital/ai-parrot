"""
Chatbot Manager.

Tool for instanciate, managing and interacting with Chatbot through APIs.
"""
from typing import Any, Dict, Type, Optional, Tuple, List
from importlib import import_module
import contextlib
import time
import asyncio
import copy
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
from ..handlers.crew.models import CrewDefinition, ExecutionMode
from ..handlers.crew.handler import CrewHandler
from ..handlers.crew.redis_persistence import CrewRedis
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
        self._botdef: Dict[str, Type] = {}  # Store class definitions for each bot
        self._bot_expiration: Dict[str, float] = {}  # Track expiration timestamps for temporary bots
        self._cleanup_task: Optional[asyncio.Task] = None  # Background cleanup task
        self.logger = logging.getLogger(
            name='Parrot.Manager'
        )
        self.registry: AgentRegistry = agent_registry
        self._crews: Dict[str, Tuple[AgentCrew, CrewDefinition]] = {}
        # Initialize Redis persistence for crews
        self.crew_redis = CrewRedis()

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
            print('===========================================')
            print('Agent startup result:', agent_name, result)
            print('===========================================')
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
        # Store the class definition for future instance creation
        self._botdef[bot.name] = bot.__class__

    async def get_bot(
        self,
        name: str,
        new: bool = False,
        session_id: str = "",
        **kwargs
    ) -> AbstractBot:
        """Get a Bot by name.
        
        Args:
            name: Name of the bot to get
            new: If True, create a new instance instead of returning existing one
            session_id: Session identifier for creating unique temporary instances
            **kwargs: Additional arguments to pass to bot constructor when new=True
            
        Returns:
            Bot instance (existing or newly created)
        """
        # Handle new instance creation
        if new:
            # Get the class definition for this bot
            cls = self._botdef.get(name, BasicAgent)
            
            # Create unique name to avoid duplicates
            new_name = f"{name}_{session_id}" if session_id else f"{name}_{int(time.time())}"
            
            # Prepare configuration to inherit from base bot
            base_bot = self._bots.get(name)
            bot_kwargs = kwargs.copy()
            
            if base_bot:
                # 1. Inherit LLM Configuration if not explicitly provided
                if 'use_llm' not in bot_kwargs and hasattr(base_bot, '_llm_raw'):
                    bot_kwargs['use_llm'] = base_bot._llm_raw
                
                if 'model' not in bot_kwargs and hasattr(base_bot, '_llm_model'):
                    bot_kwargs['model'] = base_bot._llm_model
                
                # 2. Clone Tools
                if 'tools' not in bot_kwargs and hasattr(base_bot, 'tool_manager'):
                    try:
                        # Deep copy tools to ensure isolation
                        base_tools = base_bot.tool_manager.get_all_tools()
                        new_tools = []
                        for tool in base_tools:
                            try:
                                # Attempt deep copy
                                new_tool = copy.deepcopy(tool)
                                new_tools.append(new_tool)
                            except Exception as e:
                                self.logger.warning(
                                    f"Failed to copy tool {tool.name}, sharing instance. Error: {e}"
                                )
                                # Fallback to shared instance
                                new_tools.append(tool)
                        bot_kwargs['tools'] = new_tools
                    except Exception as e:
                        self.logger.error(f"Error cloning tools from {name}: {e}")
                
                # 3. Clone Vector Store Configuration
                if 'vector_store_config' not in bot_kwargs and hasattr(base_bot, '_vector_store'):
                    try:
                        if base_bot._vector_store:
                             bot_kwargs['vector_store_config'] = copy.deepcopy(base_bot._vector_store)
                    except Exception as e:
                        self.logger.warning(f"Failed to copy vector store config: {e}")
                        bot_kwargs['vector_store_config'] = base_bot._vector_store
                
                if 'use_vectorstore' not in bot_kwargs and hasattr(base_bot, '_use_vector'):
                    bot_kwargs['use_vectorstore'] = getattr(base_bot, '_use_vector', False)
                    
            # Create new instance with merged configuration
            bot = cls(name=new_name, **bot_kwargs)
            
            # Configure the bot
            await bot.configure(self.app)
            
            # Add to bots dictionary
            self._bots[new_name] = bot
            
            # Set expiration time (1 hour from now)
            self._bot_expiration[new_name] = time.time() + 3600
            
            self.logger.info(
                f"Created new temporary bot instance '{new_name}' from '{name}' "
                f"(expires in 1 hour)"
            )
            
            return bot
        
        # Existing behavior for getting/creating bots
        if name not in self._bots:
            self.logger.warning(
                f"Bot '{name}' not in _bots. Available: {list(self._bots.keys())}"
            )
        if name in self._bots:
            _bot = self._bots[name]
            if not getattr(_bot, 'is_configured', False):
                self.logger.warning(f"Bot '{name}' found in _bots and is not configured.")
                await _bot.configure(self.app)
            return self._bots[name]
        if self.registry.has(name):
            try:
                # Get instance (returns singleton if at_startup=True)
                bot_instance = await self.registry.get_instance(name)
                if bot_instance:
                    # Only configure if NOT already configured
                    if not getattr(bot_instance, 'is_configured', False):
                        self.logger.info(f"Configuring bot {name} on demand.")
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
        # Clean up expiration tracking if it exists (but keep class definition)
        self._bot_expiration.pop(name, None)

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
        st.configure_routes(self.app)
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

    async def _cleanup_expired_bots(self) -> None:
        """Background task to cleanup expired temporary bot instances.
        
        Runs every 5 minutes to check for and remove bot instances that have
        exceeded their expiration time (typically 1 hour after creation).
        """
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                current_time = time.time()
                
                # Find all expired bots
                expired = [
                    name for name, expiry in self._bot_expiration.items()
                    if current_time > expiry
                ]
                
                # Remove expired bots
                for name in expired:
                    try:
                        self.logger.info(f"Removing expired bot instance: {name}")
                        self.remove_bot(name)
                        del self._bot_expiration[name]
                    except Exception as e:
                        self.logger.error(
                            f"Error removing expired bot '{name}': {e}"
                        )
                        # Remove from expiration tracking even if removal failed
                        self._bot_expiration.pop(name, None)
                
                if expired:
                    self.logger.info(
                        f"Cleaned up {len(expired)} expired bot instance(s). "
                        f"Active bots: {len(self._bots)}, "
                        f"Tracked expirations: {len(self._bot_expiration)}"
                    )
            except asyncio.CancelledError:
                self.logger.info("Cleanup task cancelled")
                raise
            except Exception as e:
                self.logger.error(
                    f"Error in cleanup task: {e}",
                    exc_info=True
                )
                # Continue running even if there's an error

    async def on_startup(self, app: web.Application) -> None:
        """On startup."""
        # configure all pre-configured chatbots:
        await self.load_bots(app)
        # Load crews from Redis
        await self.load_crews()
        # Start background cleanup task for expired bots
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_bots())
        self.logger.info("Started background cleanup task for temporary bot instances")

    async def on_shutdown(self, app: web.Application) -> None:
        """On shutdown."""
        # Cancel background cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self.logger.info("Stopped background cleanup task")

    async def add_crew(
        self,
        name: str,
        crew: AgentCrew,
        crew_def: CrewDefinition
    ) -> None:
        """
        Register a crew in the manager and persist to Redis.

        Args:
            name: Unique name for the crew
            crew: AgentCrew instance
            crew_def: Crew definition containing metadata

        Raises:
            ValueError: If crew with same name already exists
        """
        if name in self._crews:
            raise ValueError(f"Crew '{name}' already exists")

        # Add to memory
        self._crews[name] = (crew, crew_def)

        # Persist to Redis
        try:
            await self.crew_redis.save_crew(crew_def)
            self.logger.info(
                f"Registered crew '{name}' with {len(crew.agents)} agents "
                f"in {crew_def.execution_mode.value} mode and saved to Redis"
            )
        except Exception as e:
            self.logger.error(f"Failed to save crew '{name}' to Redis: {e}")
            # Don't fail the operation if Redis fails, crew is still in memory
            self.logger.info(
                f"Crew '{name}' registered in memory only (Redis persistence failed)"
            )

    async def get_crew(
        self,
        identifier: str
    ) -> Optional[Tuple[AgentCrew, CrewDefinition]]:
        """
        Get a crew by name or ID. Loads from Redis if not in memory.

        Args:
            identifier: Crew name or crew_id

        Returns:
            Tuple of (AgentCrew, CrewDefinition) if found, None otherwise
        """
        # Try by name first in memory
        if identifier in self._crews:
            return self._crews[identifier]

        # Try by crew_id in memory
        for name, (crew, crew_def) in self._crews.items():
            if crew_def.crew_id == identifier:
                return (crew, crew_def)

        # Not in memory - try to load from Redis
        try:
            # Try to load by name first
            crew_def = await self.crew_redis.load_crew(identifier)

            # If not found by name, try by ID
            if not crew_def:
                crew_def = await self.crew_redis.load_crew_by_id(identifier)

            if crew_def:
                # Reconstruct the crew from definition
                crew = await self._create_crew_from_definition(crew_def)

                # Cache in memory
                self._crews[crew_def.name] = (crew, crew_def)

                self.logger.info(
                    f"Loaded crew '{crew_def.name}' from Redis "
                    f"(ID: {crew_def.crew_id})"
                )
                return (crew, crew_def)
        except Exception as e:
            self.logger.error(
                f"Error loading crew '{identifier}' from Redis: {e}"
            )

        return None

    def list_crews(self) -> Dict[str, Tuple[AgentCrew, CrewDefinition]]:
        """
        List all registered crews.

        Returns:
            Dictionary mapping crew names to (AgentCrew, CrewDefinition) tuples
        """
        return self._crews.copy()

    async def remove_crew(self, identifier: str) -> bool:
        """
        Remove a crew from the manager and Redis.

        Args:
            identifier: Crew name or crew_id

        Returns:
            True if removed, False if not found
        """
        crew_name = None
        crew_def = None

        # Try by name first
        if identifier in self._crews:
            crew_name = identifier
            _, crew_def = self._crews[identifier]
            del self._crews[identifier]
        else:
            # Try by crew_id
            for name, (crew, def_) in list(self._crews.items()):
                if def_.crew_id == identifier:
                    crew_name = name
                    crew_def = def_
                    del self._crews[name]
                    break

        if crew_name and crew_def:
            # Remove from Redis
            try:
                await self.crew_redis.delete_crew(crew_def.name)
                self.logger.info(
                    f"Removed crew '{crew_name}' (ID: {crew_def.crew_id}) "
                    f"from memory and Redis"
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to delete crew '{crew_name}' from Redis: {e}"
                )
                self.logger.info(
                    f"Crew '{crew_name}' removed from memory only"
                )
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

    async def load_crews(self) -> None:
        """
        Load all crews from Redis on startup.

        This method is called during application startup to restore
        all previously saved crews from Redis into memory.
        """
        try:
            # Check Redis connection
            if not await self.crew_redis.ping():
                self.logger.warning("Redis connection failed, skipping crew loading")
                return

            # Get all crew definitions from Redis
            crew_defs = await self.crew_redis.get_all_crews()

            if not crew_defs:
                self.logger.info("No crews found in Redis")
                return

            self.logger.info(f"Loading {len(crew_defs)} crews from Redis...")

            loaded_count = 0
            for crew_def in crew_defs:
                try:
                    # Reconstruct the crew from definition
                    crew = await self._create_crew_from_definition(crew_def)

                    # Add to memory (without saving back to Redis)
                    self._crews[crew_def.name] = (crew, crew_def)

                    loaded_count += 1
                    self.logger.info(
                        f"Loaded crew '{crew_def.name}' with {len(crew_def.agents)} agents "
                        f"in {crew_def.execution_mode.value} mode"
                    )
                except Exception as e:
                    self.logger.error(
                        f"Failed to load crew '{crew_def.name}': {e}",
                        exc_info=True
                    )

            self.logger.info(
                f":: Crews loaded successfully. Total active crews: {loaded_count}"
            )
        except Exception as e:
            self.logger.error(
                f"Failed to load crews from Redis: {e}",
                exc_info=True
            )

    async def _create_crew_from_definition(
        self,
        crew_def: CrewDefinition
    ) -> AgentCrew:
        """
        Create an AgentCrew instance from a CrewDefinition.

        This method reconstructs a crew from its JSON definition,
        creating all agents and setting up flow relations.

        Args:
            crew_def: Crew definition

        Returns:
            AgentCrew instance
        """
        from typing import List, Any

        # Create agents
        agents = []
        for agent_def in crew_def.agents:
            # Get agent class
            agent_class = self.get_bot_class(agent_def.agent_class)
            if not agent_class:
                self.logger.warning(
                    f"Agent class '{agent_def.agent_class}' not found, "
                    f"using BasicAgent as fallback"
                )
                agent_class = BasicAgent

            # Collect tools
            tools = []
            if agent_def.tools:
                tools.extend(iter(agent_def.tools))

            # Create agent instance
            agent = agent_class(
                name=agent_def.name or agent_def.agent_id,
                tools=tools,
                **agent_def.config
            )

            # Set system prompt if provided
            if agent_def.system_prompt:
                agent.system_prompt = agent_def.system_prompt

            agents.append(agent)

        # Create crew
        crew = AgentCrew(
            name=crew_def.name,
            agents=agents,
            max_parallel_tasks=crew_def.max_parallel_tasks
        )

        # Add shared tools
        for tool_name in crew_def.shared_tools:
            # Try to get tool from registry or bot manager
            # This is a placeholder - implement tool retrieval as needed
            try:
                # You may need to implement get_tool method
                # For now, we'll skip tools that aren't available
                self.logger.debug(
                    f"Shared tool '{tool_name}' for crew '{crew_def.name}' "
                    f"(implement tool retrieval as needed)"
                )
            except Exception as e:
                self.logger.warning(
                    f"Could not add shared tool '{tool_name}': {e}"
                )

        # Setup flow relations if in flow mode
        if crew_def.execution_mode == ExecutionMode.FLOW and crew_def.flow_relations:
            for relation in crew_def.flow_relations:
                try:
                    # Convert agent IDs to agent objects
                    source_agents = self._get_agents_by_ids(
                        crew,
                        relation.source if isinstance(relation.source, list) else [relation.source]
                    )
                    target_agents = self._get_agents_by_ids(
                        crew,
                        relation.target if isinstance(relation.target, list) else [relation.target]
                    )

                    # Setup flow
                    crew.task_flow(
                        source_agents if len(source_agents) > 1 else source_agents[0],
                        target_agents if len(target_agents) > 1 else target_agents[0]
                    )
                except Exception as e:
                    self.logger.error(
                        f"Failed to setup flow relation for crew '{crew_def.name}': {e}"
                    )

        return crew

    def _get_agents_by_ids(
        self,
        crew: AgentCrew,
        agent_ids: List[str]
    ) -> List[Any]:
        """
        Get agent objects from crew by their IDs.

        Args:
            crew: AgentCrew instance
            agent_ids: List of agent IDs

        Returns:
            List of agent objects
        """
        agents = []
        for agent_id in agent_ids:
            if agent := crew.agents.get(agent_id):
                agents.append(agent)
            else:
                self.logger.warning(f"Agent '{agent_id}' not found in crew")
        return agents

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
