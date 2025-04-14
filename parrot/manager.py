"""
Chatbot Manager.

Tool for instanciate, managing and interacting with Chatbot through APIs.
"""
from typing import Any, Dict, Type
from importlib import import_module
from aiohttp import web
from navconfig.logging import logging
from .bots.abstract import AbstractBot
from .bots.basic import BasicBot
from .bots.chatbot import Chatbot
from .bots.pd import PandasAgent
from .handlers.chat import ChatHandler, BotHandler
from .handlers.agents import AgentHandler
from .handlers import ChatbotHandler
from .models import ChatbotModel


class BotManager:
    """BotManager.

    Manage Bots/Agents and interact with them through via aiohttp App.
    Deploy and manage chatbots and agents using a RESTful API.

    """
    app: web.Application = None

    def __init__(self) -> None:
        self.app = None
        self._bots: Dict[str, AbstractBot] = {}
        self._agents: Dict[str, AbstractBot] = {}
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
        """Load all chatbots from DB."""
        self.logger.info("Loading chatbots from DB...")
        db = app['database']
        async with await db.acquire() as conn:
            ChatbotModel.Meta.connection = conn
            try:
                bots = await ChatbotModel.filter(enabled=True)
            except Exception as e:
                self.logger.error(
                    f"Failed to load chatbots from DB: {e}"
                )
                return
            for bot in bots:
                if bot.bot_type == 'chatbot':
                    self.logger.notice(
                        f"Loading chatbot '{bot.name}'..."
                    )
                    cls_name = bot.bot_class
                    if cls_name is None:
                        class_name = Chatbot
                    else:
                        class_name = self.get_bot_class(cls_name)
                    chatbot = class_name(
                        chatbot_id=bot.chatbot_id,
                        name=bot.name,
                        description=bot.description,
                        use_llm=bot.llm,
                        model_name=bot.model_name,
                        model_config=bot.model_config,
                        embedding_model=bot.embedding_model,
                        use_vectorstore=bot.vector_store,
                        vector_store=bot.database,
                        config_file=bot.config_file,
                        role=bot.role,
                        goal=bot.goal,
                        backstory=bot.backstory,
                        rationale=bot.rationale,
                        pre_instructions=bot.pre_instructions,
                        company_information=bot.company_information,
                        vector_info=bot.database,
                        permissions=bot.permissions,
                        attributes=bot.attributes,
                    )
                    try:
                        await chatbot.configure(
                            app=app
                        )
                    except Exception as e:
                        self.logger.error(
                            f"Failed to configure chatbot '{chatbot.name}': {e}"
                        )
                elif bot.bot_type == 'agent':
                    self.logger.notice(
                        f"Unsupported kind of Agent '{bot.name}'..."
                    )
                    chatbot = None
                if chatbot:
                    self.add_bot(chatbot)
        self.logger.info(
            ":: Chatbots loaded successfully."
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
            llm_name = llm.pop('name')
            model = llm.pop('model')
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
            class_name = PandasAgent
        agent = class_name(**kwargs)
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
        self._agents[agent.chatbot_id] = agent

    def get_agent(self, name: str) -> AbstractBot:
        """Get a Agent by ID."""
        return self._agents.get(name)

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
        # Agent Handler:
        router.add_view(
            '/api/v1/agent',
            AgentHandler
        )
        router.add_view(
            '/api/v1/agent/{agent_name}',
            AgentHandler
        )
        # ChatBot Manager
        ChatbotHandler.configure(self.app, '/api/v1/bots')
        return self.app

    async def on_startup(self, app: web.Application) -> None:
        """On startup."""
        # configure all pre-configured chatbots:
        await self.load_bots(app)

    async def on_shutdown(self, app: web.Application) -> None:
        """On shutdown."""
        pass
