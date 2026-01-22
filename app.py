from navconfig.logging import logging
from navigator.handlers.types import AppHandler
# Tasker:
from navigator.background import BackgroundQueue
from navigator_auth import AuthHandler
from querysource.services import QuerySource
from parrot.scheduler import AgentSchedulerManager
from parrot.manager import BotManager
from parrot.conf import STATIC_DIR
from parrot.handlers.bots import (
    FeedbackTypeHandler,
    ChatbotFeedbackHandler,
    PromptLibraryManagement,
    ChatbotUsageHandler,
    ChatbotSharingQuestion,
    ToolList
)
from parrot.handlers.chat import (
    BotManagement
)
from parrot.handlers.o365_auth import (
    O365InteractiveAuthSessions,
    O365InteractiveAuthSessionDetail,
)
from parrot.services.mcp import ParrotMCPServer
from parrot.tools.workday import WorkdayToolkit
from parrot.services.o365_remote_auth import RemoteAuthManager
from parrot.handlers.jobs.worker import configure_redis_queue, configure_job_manager
from parrot.handlers.user import UserSocketManager
from resources.example import ExampleAsyncView
from resources.nextstop import NextStopAgent



class Main(AppHandler):
    """
    Main App Handler for Parrot Application.
    """
    app_name: str = 'Parrot'
    enable_static: bool = True
    enable_pgpool: bool = True
    staticdir: str = STATIC_DIR

    def _configure_logging(self):
        """Configuración explícita de logging para aiohttp server."""
        # Obtener el logger raíz
        root_logger = logging.getLogger()

        # Limpiar handlers existentes si los hay
        root_logger.handlers.clear()

        # Configurar el nivel del logger raíz
        root_logger.setLevel(logging.DEBUG)

    def configure(self):
        super(Main, self).configure()
        ### Auth System
        # create a new instance of Auth System
        auth = AuthHandler()
        auth.setup(self.app)
        # Tasker: Background Task Manager:
        tasker = BackgroundQueue(
            app=self.app,
            max_workers=5,
            queue_size=5
        )
        # Loading QUerySource
        qry = QuerySource(
            lazy=False,
            loop=self.event_loop()
        )
        qry.setup(self.app)
        # Chatbot System
        self.bot_manager = BotManager()
        self.bot_manager.setup(self.app)

        # Scheduler Manager (after bot manager):
        self._scheduler = AgentSchedulerManager(bot_manager=self.bot_manager)
        self._scheduler.setup(app=self.app)

        # Configure Redis RQ Queue for jobs
        configure_redis_queue(self.app)
        # Configure Job Manager
        configure_job_manager(self.app)

        # API of feedback types:
        self.app.router.add_view(
            '/api/v1/feedback_types/{feedback_type}',
            FeedbackTypeHandler
        )
        ChatbotFeedbackHandler.configure(self.app, '/api/v1/bot_feedback')
        # Prompt Library:
        PromptLibraryManagement.configure(self.app, '/api/v1/chatbots/prompt_library')
        # Questions (Usage handler, for sharing)
        ChatbotUsageHandler.configure(self.app, '/api/v1/chatbots_usage')
        self.app.router.add_view(
            '/api/v1/chatbots/questions/{sid}',
            ChatbotSharingQuestion
        )
        # Install Bot Management
        BotManagement.setup(self.app, r'/api/v1/bot_management{slash:/?}{bot:[^/]*}')
        # Tools List
        self.app.router.add_view(
            '/api/v1/agent_tools',
            ToolList,
            name='tools_list'
        )
        # # Office 365 delegated authentication endpoints
        # self.app['o365_auth_manager'] = RemoteAuthManager()
        # self.app.router.add_view(
        #     '/api/v1/o365/auth/sessions',
        #     O365InteractiveAuthSessions,
        #     name='o365_auth_sessions'
        # )
        # self.app.router.add_view(
        #     '/api/v1/o365/auth/sessions/{session_id}',
        #     O365InteractiveAuthSessionDetail,
        #     name='o365_auth_session_detail'
        # )
        # Example Async View for Queue:
        self.app.router.add_view(
            '/api/v1/example_async',
            ExampleAsyncView,
            name='example_async'
        )
        ## NextStop
        nextstop = NextStopAgent(app=self.app)
        nextstop.setup(self.app, '/api/v1/agents/nextstop')

        # # MCP server lifecycle management
        # mcp_server = ParrotMCPServer(
        #     transports=["sse", "http", "websocket"],
        #     tools=WorkdayToolkit(redis_url="redis://localhost:6379/4")
        # )
        # mcp_server.setup(self.app)
        ws_manager = UserSocketManager(
            self.app,
            route_prefix="/ws/userinfo",
            redis_url="redis://localhost:6379/4",
            default_channels=["information", "following"]
        )

    async def on_prepare(self, request, response):
        """
        on_prepare.
        description: Signal for customize the response while is prepared.
        """

    async def pre_cleanup(self, app):
        """
        pre_cleanup.
        description: Signal for running tasks before on_cleanup/shutdown App.
        """

    async def on_cleanup(self, app):
        """
        on_cleanup.
        description: Signal for customize the response when server is closing
        """

    async def on_startup(self, app):
        """
        on_startup.
        description: Signal for customize the response when server is started
        """
        app['websockets'] = []

    async def on_shutdown(self, app):
        """
        on_shutdown.
        description: Signal for customize the response when server is shutting down
        """
        manager = app.get('o365_auth_manager')
        if manager:
            await manager.shutdown()
