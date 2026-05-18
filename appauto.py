"""Main application entry point for Parrot."""
from pathlib import Path
from navconfig.logging import logging
from navigator.handlers.types import AppHandler
# Tasker:
from navigator.background import BackgroundQueue
from navigator_auth import AuthHandler
from parrot.scheduler import AgentSchedulerManager
from parrot.manager import BotManager
from parrot.conf import (
    STATIC_DIR,
)
from parrot.handlers.jobs.worker import configure_job_manager
from parrot.bots.github_reviewer import GitHubReviewer


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
        """Configure the application.
        """
        super(Main, self).configure()
        # Tasker: Background Task Manager:
        BackgroundQueue(
            app=self.app,
            max_workers=5,
            queue_size=5
        )
        # Chatbot System
        self.bot_manager = BotManager()
        self.bot_manager.setup(self.app)

        # Scheduler Manager (after bot manager):
        self._scheduler = AgentSchedulerManager(
            bot_manager=self.bot_manager
        )
        self._scheduler.setup(
            app=self.app
        )
        # Configure Job Manager (Redis-backed for durable persistence)
        configure_job_manager(self.app, use_redis=True)
        # GitHub Reviewer webhook route — must be registered here, while
        # the aiohttp router is still mutable. post_configure() runs on
        # the on_startup signal (router already frozen) so it can't add
        # routes itself; it just appends its listener to the dispatcher.
        github_hook = GitHubReviewer.setup_webhook_route(self.app)
        ### Auth System
        # create a new instance of Auth System
        auth = AuthHandler()
        auth.setup(self.app)  # configure this Auth system into App.
        # GitHub signs its webhook deliveries with HMAC-SHA256, not Bearer
        # tokens, so navigator-auth must let them through. The hook itself
        # verifies the X-Hub-Signature-256 header (see
        # parrot.core.hooks.github_webhook.GitHubWebhookHook).
        auth.add_exclude_list(github_hook.url)
