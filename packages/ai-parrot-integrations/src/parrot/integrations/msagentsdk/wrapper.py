"""
Integration wrapper for the Microsoft 365 Agents SDK.

Owns the CloudAdapter lifecycle, registers the per-bot HTTP route on the
aiohttp application, and bridges incoming HTTP requests to
``ParrotM365Agent.on_turn()``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web
from navconfig.logging import logging

if TYPE_CHECKING:
    from parrot.bots.abstract import AbstractBot
    from .models import MSAgentSDKConfig


class MSAgentSDKWrapper:
    """ai-parrot integration wrapper for the Microsoft 365 Agents SDK.

    Registers a per-bot HTTP route at
    ``/api/msagentsdk/{safe_id}/messages`` on the aiohttp application,
    creates a ``CloudAdapter`` (with optional Azure AD auth), and delegates
    all POST requests to ``CloudAdapter.process()``.

    All ``microsoft_agents.*`` imports are lazy (inside ``__init__``) so
    the class can be instantiated even if the optional SDK is not installed
    — the error surfaces at startup rather than at import time.

    Attributes:
        agent: The ai-parrot bot instance.
        config: Configuration for this integration.
        app: The aiohttp application instance.
        route: The registered HTTP route path.
        m365_agent: The bridge agent wrapping ``agent``.
        adapter: The ``CloudAdapter`` instance.
        logger: Logger scoped to this wrapper.
    """

    def __init__(
        self,
        agent: AbstractBot,
        config: MSAgentSDKConfig,
        app: web.Application,
    ) -> None:
        """Initialise the wrapper, create adapter, and register HTTP route.

        Args:
            agent: Any ``AbstractBot`` subclass.
            config: ``MSAgentSDKConfig`` carrying auth credentials and options.
            app: The running aiohttp ``web.Application``.
        """
        self.agent = agent
        self.config = config
        self.app = app
        self.logger = logging.getLogger(
            f"MSAgentSDKWrapper.{config.name}"
        )

        # Create bridge agent (ParrotM365Agent's lazy imports are inside on_turn)
        from .agent import ParrotM365Agent

        self.m365_agent = ParrotM365Agent(
            parrot_agent=agent,
            welcome_message=config.welcome_message,
        )

        # Create CloudAdapter with auth configuration (lazy SDK import)
        from microsoft_agents.hosting.aiohttp import CloudAdapter

        if config.anonymous_auth:
            # Anonymous mode: no JWT validation — local development only
            self.adapter: CloudAdapter = CloudAdapter()
            self.logger.warning(
                "MS Agent SDK bot '%s' started in ANONYMOUS auth mode. "
                "Do NOT use in production.",
                config.name,
            )
        else:
            # Azure AD mode: pass credentials so CloudAdapter validates JWTs
            try:
                from microsoft_agents.hosting.core import AgentAuthConfiguration

                auth_config = AgentAuthConfiguration(
                    app_id=config.client_id,
                    app_password=config.client_secret,
                    tenant_id=config.tenant_id,
                )
                self.adapter = CloudAdapter(auth_config)
            except ImportError:
                # Older SDK versions may not have AgentAuthConfiguration;
                # fall back to keyword arguments.
                self.adapter = CloudAdapter(
                    app_id=config.client_id,
                    app_password=config.client_secret,
                )
                self.logger.debug(
                    "CloudAdapter created with keyword args (AgentAuthConfiguration not found)"
                )

        # Register per-bot HTTP route
        safe_id = config.name.replace(" ", "_").lower()
        self.route = f"/api/msagentsdk/{safe_id}/messages"
        self.app.router.add_post(self.route, self.handle_request)

        # Exclude from auth middleware (pattern from WhatsApp/MS Teams wrappers)
        if auth := self.app.get("auth"):
            auth.add_exclude_list(self.route)

        self.logger.info(
            "Registered MS Agent SDK route: %s (anonymous_auth=%s)",
            self.route,
            config.anonymous_auth,
        )

    async def handle_request(self, request: web.Request) -> web.Response:
        """Handle an incoming POST request from Copilot Studio / Teams.

        Delegates JWT validation, Activity parsing, and turn execution to
        the ``CloudAdapter``, then passes the turn to ``ParrotM365Agent``.

        Args:
            request: Incoming aiohttp ``web.Request``.

        Returns:
            ``web.Response`` produced by the ``CloudAdapter``.
        """
        return await self.adapter.process(request, self.m365_agent)

    async def stop(self) -> None:
        """Gracefully stop the MS Agent SDK wrapper.

        Called by ``IntegrationBotManager.shutdown()`` to allow any
        cleanup the wrapper needs to perform (e.g. closing connections).
        Currently a no-op but present for lifecycle symmetry.
        """
        self.logger.info(
            "Stopping MS Agent SDK wrapper: %s", self.config.name
        )
