from pathlib import Path
from navconfig import config
from navigator.handlers.types import AppHandler
# Tasker:
from navigator.background import BackgroundQueue
from navigator_auth import AuthHandler
from querysource.services import QuerySource
from parrot.scheduler import AgentSchedulerManager
from parrot.manager import BotManager
from parrot.conf import STATIC_DIR
from parrot.auth.pbac import setup_pbac
from parrot.auth.resolver import PBACPermissionResolver
from parrot.handlers.bots import (
    FeedbackTypeHandler,
    ChatbotFeedbackHandler,
    PromptLibraryManagement,
    UserPromptsManagement,
    ChatbotUsageHandler,
    ChatbotSharingQuestion,
    ToolList
)
from parrot.handlers.chat import (
    BotManagement
)
from parrot.handlers.artifacts import (
    ArtifactListView,
    ArtifactDetailView,
    ArtifactPublicHTMLView,
)
from parrot.handlers.jobs.worker import configure_job_manager
from parrot.handlers.user import UserSocketManager
from parrot.handlers.llm import LLMClient
from parrot.handlers.google_generation import GoogleGeneration
from parrot.handlers.programs import ProgramsUserHandler
## New Handlers:
from parrot.handlers.video_reel import VideoReelHandler
from parrot.handlers.lyria_music import LyriaMusicHandler
from parrot.handlers.understanding import UnderstandingHandler
from parrot.handlers.mediagen import MediaGen
from parrot.handlers.stores import VectorStoreHandler
# AgentCrew handlers are registered inside BotManager.setup() (gated on
# ENABLE_CREWS); no direct import/registration is needed here.
## Jira Integration:
from parrot.auth.jira_oauth import JiraOAuthManager
from parrot.integrations.telegram.combined_callback import setup_combined_auth_routes
from parrot.conf import (
    JIRA_CLIENT_ID,
    JIRA_CLIENT_SECRET,
    JIRA_REDIRECT_URI,
    default_dsn
)
from parrot.clients.factory import LLMFactory
from parrot.bots.github_reviewer import GitHubReviewer
from parrot_formdesigner.api import setup_form_api
from parrot_formdesigner.ui import setup_form_ui
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.storage import PostgresFormStorage
# Audio form voice modes (FEAT-224/FEAT-236): STT transcriber + WS JWT validator.
# TokenValidator is shared WS auth infra in parrot.core (not parrot.voice.handler)
# so we don't drag in the VoiceBot / Gemini Live stack.
from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend
from parrot.core.ws_auth import TokenValidator
from parrot_pipelines.handlers import PlanogramComplianceHandler


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
        import logging
        root_logger = logging.getLogger()

        # Limpiar handlers existentes si los hay
        root_logger.handlers.clear()

        # Configurar el nivel del logger raíz
        root_logger.setLevel(logging.DEBUG)

    def configure(self):
        super(Main, self).configure()
        # Serve Telegram integration assets (azure_login.html, login_multi.html,
        # etc.) straight from the source tree so the HTMLs never drift from the
        # package. Uses a dedicated /telegram/ prefix to avoid colliding with
        # the framework's /static/ route.
        from parrot.integrations.telegram import __file__ as _tg_pkg_file
        telegram_static = Path(_tg_pkg_file).parent / 'static'
        self.app.router.add_static(
            '/telegram/',
            path=telegram_static,
            name='telegram_static',
            show_index=False,
            follow_symlinks=False,
        )
        # Tasker: Background Task Manager:
        tasker = BackgroundQueue(
            app=self.app,
            max_workers=5,
            queue_size=5
        )
        # Loading QUerySource
        qry = QuerySource(lazy=False)
        qry.setup(self.app)
        # Chatbot System
        self.bot_manager = BotManager(enable_database_bots=True)
        self.bot_manager.setup(self.app)

        ## Jira OAuth Manager setup (reuses app['redis'] published by BotManager):
        JiraOAuthManager(
            client_id=JIRA_CLIENT_ID,
            client_secret=JIRA_CLIENT_SECRET,
            redirect_uri=JIRA_REDIRECT_URI,
            app=self.app,
        ).setup()
        setup_combined_auth_routes(self.app)

        ## End of Jira OAuth setup.
        # Scheduler Manager (after bot manager):
        self._scheduler = AgentSchedulerManager(
            bot_manager=self.bot_manager
        )
        self._scheduler.setup(app=self.app)
        # Configure Job Manager (with Redis persistence)
        configure_job_manager(self.app, use_redis=True)

        # API of feedback types:
        self.app.router.add_view(
            '/api/v1/feedback_types/{feedback_type}',
            FeedbackTypeHandler
        )
        ChatbotFeedbackHandler.configure(self.app, '/api/v1/bot_feedback')
        # Prompt Library:
        PromptLibraryManagement.configure(self.app, '/api/v1/chatbots/prompt_library')
        UserPromptsManagement.configure(self.app, '/api/v1/agents/user_prompts')
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
        # Video Understanding API:
        self.app.router.add_view(
            '/api/v1/google/understanding',
            UnderstandingHandler,
        )
        # Google Media Generation (Imagen/Veo) API:
        MediaGen.setup(self.app, "/api/v1/google/media")
        # # Example Async View for Queue:
        # self.app.router.add_view(
        #     '/api/v1/example_async',
        #     ExampleAsyncView,
        #     name='example_async'
        # )
        # MCP server lifecycle management
        # mcp_server = ParrotMCPServer(
        #     transports=["sse", "http", "websocket"],
        #     tools=WorkdayToolkit(redis_url="redis://localhost:6379/4")
        # )
        # mcp_server.setup(self.app)
        # LLM Client Routes
        self.app.router.add_view(
            '/api/v1/ai/client',
            LLMClient,
            name='llm_client'
        )
        self.app.router.add_view(
            '/api/v1/ai/client/{client_name}',
            LLMClient,
            name='llm_client_detail'
        )
        self.app.router.add_view(
            '/api/v1/ai/clients',
            LLMClient,
            name='llm_clients_list'
        )
        self.app.router.add_view(
            '/api/v1/ai/clients/models',
            LLMClient,
            name='llm_clients_models'
        )
        self.app.router.add_view(
            '/api/v1/ai/google/generation',
            GoogleGeneration,
            name='google_generation'
        )
        ws = UserSocketManager(
            self.app,
            route_prefix="/ws/userinfo",
            redis_url="redis://localhost:6379/4",
            default_channels=["information", "following"]
        )
        self.app['user_socket_manager'] = ws
        # Programs API
        self.app.router.add_view(
            '/api/v1/programs_user',
            ProgramsUserHandler,
            name='programs_user'
        )
        ## implement Video Reel Handler:
        VideoReelHandler.setup(self.app)
        ## Vector Store Handler API:
        VectorStoreHandler.setup(self.app)
        # AgentCrew Handlers are registered by BotManager.setup() when
        # ENABLE_CREWS is True (see manager.py). It owns the full crew route
        # set — CrewHandler (/api/v1/crew), CrewExecutionHandler
        # (/api/v1/crews), plus /api/v1/crew/tools and
        # /api/v1/crew/special_nodes registered *before* CrewHandler's
        # `{id:.*}` catch-all so they aren't shadowed. Registering them here
        # too would double-add the routes and raise at startup.
        # Lyria:
        self.app.router.add_view(
            "/api/v1/google/generation/music", LyriaMusicHandler
        )
        # Planogram Compliance:
        PlanogramComplianceHandler.setup(self.app)

        # Artifact persistence + public infographic HTML serving (FEAT-197).
        # - list/detail: session-scoped, authenticated CRUD over artifacts.
        # - public: serves signed, frozen infographic HTML for <iframe>
        #   embedding (no session); the signed URL is minted by
        #   InfographicToolkit at persist time. ``app['artifact_store']`` is
        #   published by BotManager.setup() above, so it is already available.
        self.app.router.add_view(
            '/api/v1/threads/{session_id}/artifacts',
            ArtifactListView,
            name='artifacts_list',
        )
        self.app.router.add_view(
            '/api/v1/threads/{session_id}/artifacts/{artifact_id}',
            ArtifactDetailView,
            name='artifacts_detail',
        )
        self.app.router.add_view(
            '/api/v1/artifacts/public/{signature}/{artifact_id_html}',
            ArtifactPublicHTMLView,
            name='artifacts_public_html',
        )

        # parrot-formdesigner: shared FormRegistry + REST API + HTML/Telegram UI.
        # protect_pages=False — page auth is handled client-side via JWT in
        # localStorage (see examples/forms/form_server.py).
        # FormRegistry self-registers as app['form_registry'] and hooks
        # on_startup / on_shutdown signals automatically (FEAT-185).
        storage = PostgresFormStorage(
            dsn=default_dsn,
            schema="navigator",
            table_name="form_schemas",
            tenant=None,
        )
        form_registry = FormRegistry(app=self.app, storage=storage)
        form_llm_client = LLMFactory.create(
            "google"
        )
        # FEAT-236: pass transcriber + token_validator so the audio WS endpoint
        # (/api/v1/forms/{form_id}/audio/ws) is actually mounted. Without any of
        # synthesizer/transcriber/token_validator the route guard in
        # setup_form_api skips registration. The Whisper model loads lazily on
        # the first audio frame, and TokenValidator() validates the WS JWT
        # against navigator_auth's SECRET_KEY (same token as the login session).
        setup_form_api(
            self.app,
            form_registry,
            client=form_llm_client,
            base_path="/api/v1",
            transcriber=FasterWhisperBackend(
                model_size=config.get("WHISPER_MODEL_SIZE", fallback="base"),
                device=config.get("WHISPER_DEVICE", fallback="cuda"),
                compute_type=config.get("WHISPER_COMPUTE_TYPE", fallback="float16"),
            ),
            token_validator=TokenValidator(),
        )
        setup_form_ui(
            self.app,
            form_registry,
            base_path="",
            protect_pages=False,
        )
        # GitHub Reviewer webhook route — must be registered here, while
        github_hook = GitHubReviewer.setup_webhook_route(self.app)

        ### Auth System
        # create a new instance of Auth System
        auth = AuthHandler()
        auth.setup(self.app)  # configure this Auth system into App.

        # FEAT-197: the public infographic HTML route authorises requests with
        # an HMAC signature, not a session — exclude it from the auth/ABAC
        # middlewares so the frontend can embed it in an <iframe> without a
        # session cookie. fnmatch pattern; '*' spans the signature + id.html.
        auth.add_exclude_list('/api/docs*')
        auth.add_exclude_list('/api/v1/artifacts/public/*')
        auth.add_exclude_list(github_hook.url)
        # FEAT-236: the audio form WebSocket authenticates itself via the
        # Sec-WebSocket-Protocol subprotocol (a browser WS cannot send an
        # Authorization: Bearer header). Exclude it from the auth/ABAC chain so
        # the upgrade reaches AudioFormWSHandler, which does its own JWT check.
        auth.add_exclude_list('/api/v1/forms/*/audio/ws')
        # MS Agent SDK (Bot Framework) messaging endpoints authenticate inbound
        # requests with a Bot Framework JWT or an API key (x-api-key) inside
        # MSAgentSDKWrapper.handle_request — NOT a navigator session/ABAC
        # identity. Exclude them so ABAC does not flag Copilot Studio / Teams /
        # Emulator POSTs as unauthenticated. Covers every msagentsdk bot's
        # canonical route (/api/msagentsdk/<safe_id>/messages) plus the fixed
        # ``/api/messages`` path that Microsoft Copilot Studio requires (the
        # standard Bot Framework endpoint a bot exposes via ``endpoint``).
        # Exclude the whole MS Agent SDK surface, not just the messaging
        # endpoints: health/manifest/card probes and any future sub-routes
        # authenticate themselves (Bot Framework JWT / x-api-key) rather than
        # via the navigator session/ABAC chain.
        auth.add_exclude_list('/api/msagentsdk/*')
        auth.add_exclude_list('/api/messages')
        # A2A protocol + discovery surface. These static patterns cover the
        # default ``/a2a`` base_path and the root-level well-known URIs.
        # Non-default base_paths (custom config or collision-avoidance
        # suffixes) are added dynamically by IntegrationBotManager when each
        # A2A agent is mounted — see ``_start_a2a_bot()`` in manager.py.
        auth.add_exclude_list('/a2a')
        auth.add_exclude_list('/a2a/*')
        auth.add_exclude_list('/.well-known/*')

        # PBAC setup — navigator-auth Rust evaluator bug is now fixed.
        # setup_pbac() MUST be called BEFORE BotManager.setup(app) so that
        # app['abac'] is registered before AgentRegistry.setup(app) reads it.
        policy_dir = self.app.get('policy_dir') or config.get('POLICY_DIR', fallback='policies')
        pdp, evaluator, guardian = setup_pbac(
            self.app,
            policy_dir=policy_dir,
            cache_ttl=int(config.get('PBAC_CACHE_TTL', fallback=30)),
        )
        if evaluator is not None:
            resolver = PBACPermissionResolver(evaluator=evaluator)
            self.app['pbac_resolver'] = resolver
            self.logger.info(
                "PBAC enabled: Guardian registered, PBACPermissionResolver active."
            )
        else:
            self.logger.info(
                "PBAC not configured — using default resolver (AllowAll)."
            )

    async def on_startup(self, app):
        """
        on_startup.
        description: Signal for customize the response when server is started
        """
        app['websockets'] = []
        # FormRegistry lifecycle (pool creation, DDL, cache hydration) is
        # handled automatically by FormRegistry.on_startup via aiohttp signals
        # (FEAT-185). No manual form-storage setup needed here.

    async def on_shutdown(self, app):
        """
        on_shutdown.
        description: Signal for customize the response when server is shutting down
        """
        if manager := app.get('o365_auth_manager'):
            await manager.shutdown()
