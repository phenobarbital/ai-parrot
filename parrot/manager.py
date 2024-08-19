"""
Chatbot Manager.

Tool for instanciate, managing and interacting with Chatbot through APIs.
"""
from typing import Any, Dict, Type
from importlib import import_module
from aiohttp import web
from navconfig.logging import logging
from .chatbots import (
    AbstractChatbot,
    Chatbot
)
from .handlers.chat import ChatHandler # , BotHandler
from .handlers import ChatbotHandler
from .models import ChatbotModel
# Manual Load of Copilot Agent:
from parrot.chatbots.copilot import CopilotAgent

class ChatbotManager:
    """ChatbotManager.

    Manage chatbots and interact with them through via aiohttp App.

    """
    app: web.Application = None
    chatbots: Dict[str, AbstractChatbot] = {}

    def __init__(self) -> None:
        self.app = None
        self.chatbots = {}
        self.logger = logging.getLogger(name='Parrot.Manager')

    def get_chatbot_class(self, class_name: str) -> Type[AbstractChatbot]:
        """
        Dynamically import a chatbot class based on the class name from the relative module '.chatbots'.
        Args:
        class_name (str): The name of the chatbot class to be imported.
        Returns:
        Type[AbstractChatbot]: A chatbot class derived from AbstractChatbot.
        """
        module = import_module('.chatbots', __package__)
        try:
            return getattr(module, class_name)
        except AttributeError:
            raise ImportError(f"No class named '{class_name}' found in the module 'chatbots'.")

    async def load_bots(self, app: web.Application) -> None:
        """Load all chatbots from DB."""
        self.logger.info("Loading chatbots from DB...")
        db = app['database']
        async with await db.acquire() as conn:
            ChatbotModel.Meta.connection = conn
            bots = await ChatbotModel.all()
            for bot in bots:
                if bot.bot_type == 'chatbot':
                    self.logger.notice(
                        f"Loading chatbot '{bot.name}'..."
                    )
                    cls_name = bot.custom_class
                    if cls_name is None:
                        class_name = Chatbot
                    else:
                        class_name = self.get_chatbot_class(cls_name)
                    chatbot = class_name(
                        chatbot_id=bot.chatbot_id,
                        name=bot.name
                    )
                    try:
                        await chatbot.configure()
                    except Exception as e:
                        self.logger.error(
                            f"Failed to configure chatbot '{chatbot.name}': {e}"
                        )
                elif bot.bot_type == 'agent':
                    self.logger.notice(
                        f"Loading Agent '{bot.name}'..."
                    )
                    # TODO: extract the list of tools from Agent config
                    try:
                        tools = CopilotAgent.default_tools()
                        chatbot = CopilotAgent(
                            name=bot.name,
                            llm=bot.llm,
                            tools=tools
                        )
                    except Exception as e:
                        print('AQUI >>> ', e)
                        self.logger.error(
                            f"Failed to configure Agent '{bot.name}': {e}"
                        )
                self.add_chatbot(chatbot)
        self.logger.info(
            ":: Chatbots loaded successfully."
        )

    def create_chatbot(self, class_name: Any = None, name: str = None, **kwargs) -> AbstractChatbot:
        """Create a chatbot and add it to the manager."""
        if class_name is None:
            class_name = Chatbot
        chatbot = class_name(**kwargs)
        chatbot.name = name
        self.add_chatbot(chatbot)
        if 'llm' in kwargs:
            llm = kwargs['llm']
            llm_name = llm.pop('name')
            model = llm.pop('model')
            llm = chatbot.load_llm(
                llm_name, model=model, **llm
            )
            chatbot.llm = llm
        return chatbot

    def add_chatbot(self, chatbot: AbstractChatbot) -> None:
        """Add a chatbot to the manager."""
        self.chatbots[chatbot.name] = chatbot

    def get_chatbot(self, name: str) -> AbstractChatbot:
        """Get a chatbot by name."""
        return self.chatbots.get(name)

    def remove_chatbot(self, name: str) -> None:
        """Remove a chatbot by name."""
        del self.chatbots[name]

    def get_chatbots(self) -> Dict[str, AbstractChatbot]:
        """Get all chatbots."""
        return self.chatbots

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
        self.app['chatbot_manager'] = self
        ## Configure Routes
        router = self.app.router
        router.add_view(
            '/api/v1/chat',
            ChatHandler
        )
        router.add_view(
            '/api/v1/chat/{chatbot_name}',
            ChatHandler
        )
        ChatbotHandler.configure(self.app, '/api/v1/bots')
        return self.app

    async def on_startup(self, app: web.Application) -> None:
        """On startup."""
        # configure all pre-configured chatbots:
        await self.load_bots(app)

    async def on_shutdown(self, app: web.Application) -> None:
        """On shutdown."""
        pass
