"""
Integration wrapper for the Microsoft 365 Agents SDK.

Owns the CloudAdapter lifecycle, registers the per-bot HTTP route on the
aiohttp application, and bridges incoming HTTP requests to
``ParrotM365Agent.on_turn()``.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from aiohttp import web
from navconfig.logging import logging

if TYPE_CHECKING:
    from parrot.bots.abstract import AbstractBot
    from .models import MSAgentSDKConfig


class _AnonymousConnectionManager:
    """Minimal ``Connections`` provider for anonymous / local-dev outbound.

    The Microsoft 365 Agents SDK ``CloudAdapter`` always needs a
    ``connection_manager`` to obtain a token when it sends the reply back to
    the channel — even with no auth. This provider returns the SDK's
    ``AnonymousTokenProvider`` (empty bearer token), which is what the Bot
    Framework Emulator and other unauthenticated local channels expect.

    Do NOT use in production: real channels reject empty tokens.

    Implements the ``microsoft_agents.hosting.core.authorization.Connections``
    protocol structurally (no inheritance needed — it's a runtime ``Protocol``).
    SDK imports are deferred to ``__init__`` to keep the module importable
    without the optional dependency.
    """

    def __init__(self) -> None:
        from microsoft_agents.hosting.core import (
            AgentAuthConfiguration,
            AnonymousTokenProvider,
        )

        self._provider = AnonymousTokenProvider()
        self._config = AgentAuthConfiguration(anonymous_allowed=True)

    def get_token_provider(self, claims_identity, service_url):
        return self._provider

    def get_default_connection(self):
        return self._provider

    def get_connection(self, name):
        return self._provider

    def get_default_connection_configuration(self):
        return self._config


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
        self._anonymous = config.anonymous_auth
        self.logger = logging.getLogger(
            f"MSAgentSDKWrapper.{config.name}"
        )

        # Create bridge agent (ParrotM365Agent's lazy imports are inside on_turn)
        from .agent import ParrotM365Agent

        self.m365_agent = ParrotM365Agent(
            parrot_agent=agent,
            welcome_message=config.welcome_message,
        )

        # Create CloudAdapter with auth configuration (lazy SDK import).
        #
        # The Microsoft 365 Agents SDK (>=0.9) reworked authentication: the
        # CloudAdapter no longer accepts an auth config positionally. It takes a
        # keyword ``connection_manager`` (a concrete ``Connections`` provider)
        # used to obtain outbound channel tokens, and inbound JWT validation is
        # done at the HTTP layer (the adapter reads ``request["claims_identity"]``,
        # which we populate per-request in ``handle_request``).
        from microsoft_agents.hosting.aiohttp import CloudAdapter
        from microsoft_agents.hosting.core import (
            AgentAuthConfiguration,
            JwtTokenValidator,
        )

        if config.anonymous_auth:
            # Anonymous mode: inbound requests get anonymous claims, and
            # outbound replies use an empty (anonymous) token. Local dev only.
            self._auth_config = AgentAuthConfiguration(anonymous_allowed=True)
            connection_manager = _AnonymousConnectionManager()
            self.logger.warning(
                "MS Agent SDK bot '%s' started in ANONYMOUS auth mode. "
                "Do NOT use in production.",
                config.name,
            )
        else:
            # Azure AD mode: build an MSAL connection manager from the app
            # credentials and hand it to the CloudAdapter for outbound auth.
            from microsoft_agents.authentication.msal import (
                MsalConnectionManager,
            )

            # Outbound token authority. A MULTI-TENANT Bot Framework app must
            # mint its reply token against the shared ``botframework.com``
            # authority, NOT the bot's home tenant — otherwise the Bot Connector
            # rejects the reply with HTTP 401 (notably on Teams) even though the
            # inbound turn validated fine. We keep ``tenant_id`` set so inbound
            # issuer validation still works; ``_resolve_authority`` honours the
            # explicit authority verbatim (it only rewrites a /common or /<guid>
            # segment, which ``botframework.com`` is not).
            authority = config.authority
            if (config.app_type or "").lower() == "multitenant" and not authority:
                authority = "https://login.microsoftonline.com/botframework.com"

            self._auth_config = AgentAuthConfiguration(
                client_id=config.client_id,
                client_secret=config.client_secret,
                tenant_id=config.tenant_id,
                authority=authority,
            )
            connection_manager = MsalConnectionManager(
                connections_configurations={
                    "SERVICE_CONNECTION": self._auth_config
                }
            )

        self.adapter: CloudAdapter = CloudAdapter(
            connection_manager=connection_manager
        )
        # Per-bot token validator (bound to THIS bot's auth config) — avoids the
        # app-global ``agent_configuration`` the SDK decorator relies on, so
        # multiple msagentsdk bots can coexist on one aiohttp app.
        self._token_validator = JwtTokenValidator(self._auth_config)

        # Register per-bot HTTP route
        safe_id = re.sub(r"[^a-z0-9_]", "_", config.name.lower())
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

        # Surface the effective outbound-auth config (masked) — useful when an
        # inbound turn succeeds but the *reply* is rejected by the channel
        # (HTTP 401 from the Bot Connector), which points at an Azure app-type /
        # tenant mismatch rather than a code problem.
        if not config.anonymous_auth:
            cid = self._auth_config.CLIENT_ID or ""
            masked = f"{cid[:8]}…" if cid else "(none)"
            self.logger.debug(
                "Outbound auth: client_id=%s tenant_id=%s auth_type=%s "
                "authority=%s",
                masked,
                self._auth_config.TENANT_ID or "(multi-tenant/none)",
                getattr(self._auth_config, "AUTH_TYPE", "?"),
                self._auth_config.AUTHORITY or "(default)",
            )

    async def handle_request(self, request: web.Request) -> web.Response:
        """Handle an incoming POST request from Copilot Studio / Teams.

        Performs inbound JWT validation bound to this bot's auth config,
        populates ``request["claims_identity"]`` (anonymous claims when running
        in anonymous mode), then delegates Activity parsing and turn execution
        to the ``CloudAdapter``, which routes to ``ParrotM365Agent``.

        Args:
            request: Incoming aiohttp ``web.Request``.

        Returns:
            ``web.Response`` produced by the ``CloudAdapter``, or a ``401`` JSON
            response when authentication fails.
        """
        # DEBUG visibility for remote connections (e.g. Copilot Studio reaching
        # us through a cloudflared/ngrok tunnel). Behind a proxy ``request.remote``
        # is the tunnel's local socket, so the real client IP lives in the
        # forwarding headers. Guarded so the body is only parsed when DEBUG is on.
        if self.logger.isEnabledFor(logging.DEBUG):
            forwarded = (
                request.headers.get("CF-Connecting-IP")
                or request.headers.get("X-Forwarded-For")
                or request.headers.get("X-Real-IP")
            )
            self.logger.debug(
                "Incoming %s %s peer=%s forwarded=%s ua=%r auth=%s len=%s",
                request.method,
                request.path,
                request.remote,
                forwarded,
                request.headers.get("User-Agent"),
                "yes" if request.headers.get("Authorization") else "no",
                request.headers.get("Content-Length"),
            )
            try:
                # aiohttp caches the parsed body, so the CloudAdapter can still
                # read it afterwards — this peek is non-destructive.
                activity = await request.json()
                self.logger.debug(
                    "Incoming activity type=%s id=%s channel=%s conversation=%s",
                    activity.get("type"),
                    activity.get("id"),
                    activity.get("channelId"),
                    (activity.get("conversation") or {}).get("id"),
                )
            except Exception:  # noqa: BLE001 — body may be empty/non-JSON (probes)
                self.logger.debug("Incoming request has no JSON body (probe?)")

        if self._anonymous:
            # Anonymous mode: never validate — even if the channel sends a
            # bearer token (e.g. Bot Framework Web Chat does). Always attach
            # anonymous claims so the adapter uses the empty-token callback.
            request["claims_identity"] = (
                self._token_validator.get_anonymous_claims()
            )
            return await self.adapter.process(request, self.m365_agent)

        # Production: a valid Azure AD / Bot Framework JWT is required.
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return web.json_response(
                {"error": "Authorization header not found"}, status=401
            )
        try:
            token = auth_header.split(" ")[1]
            request["claims_identity"] = (
                await self._token_validator.validate_token(token)
            )
        except ValueError as exc:
            self.logger.warning("JWT validation failed: %s", exc)
            return web.json_response({"error": str(exc)}, status=401)

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
