"""
Chatbot Manager.

Tool for instanciate, managing and interacting with Chatbot through APIs.
"""
from typing import Any, Dict, Type
from importlib import import_module
from aiohttp import web
from datamodel.exceptions import ValidationError  # pylint: disable=E0611 # noqa
# Navigator:
from navconfig.logging import logging
from asyncdb.exceptions import NoDataFound
from .bots.abstract import AbstractBot
from .bots.basic import BasicBot
from .bots.chatbot import Chatbot
from .bots.agent import BasicAgent
from .handlers.chat import ChatHandler, BotHandler
from .handlers import ChatbotHandler
from .handlers.models import BotModel


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

    def get_bot_class(self, class_name: str) -> Type[AbstractBot]:
        """
        Dynamically import a Bot class based on the class name
        from the relative module '.bots'.
        Args:
        class_name (str): The name of the Bot class to be imported.
        Returns:
        Type[AbstractBot]: A Bot class derived from AbstractBot.
        """
        module = import_module('.bots', __package__)
        try:
            return getattr(module, class_name)
        except AttributeError:
            raise ImportError(
                f"No class named '{class_name}' found in the module 'bots'."
            )

    async def load_bots(self, app: web.Application) -> None:
        """Load all bots from DB using the new unified BotModel."""
        self.logger.info("Loading bots from DB...")
        db = app['database']
        async with await db.acquire() as conn:
            BotModel.Meta.connection = conn
            try:
                bots = await BotModel.filter(enabled=True)
            except Exception as e:
                self.logger.error(
                    f"Failed to load bots from DB: {e}"
                )
                return

            for bot_model in bots:
                self.logger.notice(
                    f"Loading bot '{bot_model.name}' (mode: {bot_model.operation_mode})..."
                )

                try:
                    # Use the factory function from models.py or create bot directly
                    if hasattr(self, 'get_bot_class') and hasattr(bot_model, 'bot_class'):
                        # If you have a bot_class field and get_bot_class method
                        class_name = self.get_bot_class(getattr(bot_model, 'bot_class', None))
                    else:
                        # Default to BasicBot or your default bot class
                        class_name = BasicBot

                    # Create bot using the model's configuration
                    # bot_config = bot_model.to_bot_config()

                    # Initialize the bot with the configuration
                    chatbot = class_name(
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
                    chatbot.model_id = bot_model.chatbot_id

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
        self.add_bot(chatbot)
        if 'llm' in kwargs:
            llm = kwargs['llm']
            if isinstance(llm, dict):
                llm_name = llm.pop('name')
                model = llm.pop('model')
            else:
                llm_name = llm
                model = None
            llm = chatbot.load_llm(
                llm_name, model=model, **llm
            )
            chatbot.llm = llm
        return chatbot

    def add_bot(self, bot: AbstractBot) -> None:
        """Add a Bot to the manager."""
        self._bots[bot.name] = bot

    def get_bot(self, name: str) -> AbstractBot:
        """Get a Bot by name."""
        return self._bots.get(name)

    def remove_bot(self, name: str) -> None:
        """Remove a Bot by name."""
        del self._bots[name]

    def get_bots(self) -> Dict[str, AbstractBot]:
        """Get all Bots declared on Manager."""
        return self._bots

    async def create_agent(self, class_name: Any = None, name: str = None, **kwargs) -> AbstractBot:
        if class_name is None:
            class_name = BasicAgent
        agent = class_name(name=name, **kwargs)
        self.add_agent(agent)
        if 'llm' in kwargs:
            llm = kwargs['llm']
            llm_name = llm.pop('name')
            model = llm.pop('model')
            llm = agent.load_llm(
                llm_name, model=model, **llm
            )
            agent.llm = llm
        return agent

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
        if isinstance(app, web.Application):
            self.app = app  # register the app into the Extension
        else:
            self.app = app.get_app()  # Nav Application
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
        return self.app

    async def on_startup(self, app: web.Application) -> None:
        """On startup."""
        # configure all pre-configured chatbots:
        await self.load_bots(app)

    async def on_shutdown(self, app: web.Application) -> None:
        """On shutdown."""
        pass
