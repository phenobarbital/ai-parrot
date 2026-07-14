"""
Integration wrapper for the Microsoft 365 Agents SDK.

Owns the CloudAdapter lifecycle, registers the per-bot HTTP route on the
aiohttp application, and bridges incoming HTTP requests to
``ParrotM365Agent.on_turn()``.
"""
from __future__ import annotations

import re
import secrets
from typing import TYPE_CHECKING, Optional

from aiohttp import web
from navconfig.logging import logging

if TYPE_CHECKING:
    from parrot.bots.abstract import AbstractBot
    from parrot.auth.broker import CredentialBroker
    from parrot.auth.identity import CanonicalIdentityMapper
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
    ``/api/msagentsdk/{safe_id}/messages`` on the aiohttp application (plus an
    optional custom ``config.endpoint`` such as ``/api/messages``), creates a
    ``CloudAdapter`` (with optional Azure AD auth), and delegates all POST
    requests to ``CloudAdapter.process()``.

    All ``microsoft_agents.*`` imports are lazy (inside ``__init__``) so
    the class can be instantiated even if the optional SDK is not installed
    — the error surfaces at startup rather than at import time.

    Attributes:
        agent: The ai-parrot bot instance.
        config: Configuration for this integration.
        app: The aiohttp application instance.
        route: The primary HTTP route path operators configure in the channel
            (the custom ``endpoint`` when set, else the per-bot default).
        routes: All HTTP route paths registered for this bot.
        m365_agent: The bridge agent wrapping ``agent``.
        adapter: The ``CloudAdapter`` instance.
        logger: Logger scoped to this wrapper.
    """

    def __init__(
        self,
        agent: AbstractBot,
        config: MSAgentSDKConfig,
        app: web.Application,
        broker: Optional["CredentialBroker"] = None,
        identity_mapper: Optional["CanonicalIdentityMapper"] = None,
        agent_class: Optional[type] = None,
    ) -> None:
        """Initialise the wrapper, create adapter, and register HTTP route.

        Args:
            agent: Any ``AbstractBot`` subclass.
            config: ``MSAgentSDKConfig`` carrying auth credentials and options.
            app: The running aiohttp ``web.Application``.
            broker: Optional :class:`~parrot.auth.broker.CredentialBroker`
                (FEAT-264).  When supplied, per-user credential resolution
                flows through the broker during tool invocations.
            identity_mapper: Optional
                :class:`~parrot.auth.identity.CanonicalIdentityMapper` for
                cross-surface identity normalisation (FEAT-264 / TASK-1671).
            agent_class: Optional :class:`~.agent.ParrotM365Agent` subclass to
                use as the bridge instead of the default. Lets callers hook
                the turn pipeline (e.g. capture sender identity from the
                Activity before delegating to ``ask()``). Must accept the
                same constructor arguments as ``ParrotM365Agent``.
        """
        self.agent = agent
        self.config = config
        self.app = app
        self._anonymous = config.anonymous_auth
        self._api_key = config.api_key
        self._api_key_header = config.api_key_header
        self.logger = logging.getLogger(
            f"MSAgentSDKWrapper.{config.name}"
        )

        # Create bridge agent (ParrotM365Agent's lazy imports are inside on_turn)
        from .agent import ParrotM365Agent

        # Wire per-user OAuth resolver and audit ledger when oauth_connections
        # is configured. When empty, the bridge operates exactly as before
        # (no user-token acquisition — backward compatible).
        resolver = None
        audit_ledger = None
        if config.oauth_connections:
            from .auth import BFTokenServiceResolver
            from parrot.auth.audit import AuditLedger

            audit_ledger = AuditLedger()
            resolver = BFTokenServiceResolver(
                oauth_connections=config.oauth_connections,
                obo_scopes=config.obo_scopes,
                audit_ledger=audit_ledger,
            )
            self.logger.info(
                "BFTokenServiceResolver wired for connections: %s",
                list(config.oauth_connections.keys()),
            )

        bridge_cls = agent_class or ParrotM365Agent
        self.m365_agent = bridge_cls(
            parrot_agent=agent,
            welcome_message=config.welcome_message,
            resolver=resolver,
            audit_ledger=audit_ledger,
            broker=broker,
            identity_mapper=identity_mapper,
            enable_semantic_cards=getattr(config, "enable_semantic_cards", True),
            max_table_rows=getattr(config, "max_table_rows", 15),
            max_card_bytes=getattr(config, "max_card_bytes", 25_000),
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

        # Apply runtime SDK patches now that the SDK is importable. Notably,
        # this makes the Copilot Studio (pva-studio) reply path tolerate the
        # runtime's empty/non-JSON 200 acknowledgement instead of crashing.
        from ._patches import patch_mcs_connector_empty_response

        patch_mcs_connector_empty_response()

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

        # Register HTTP route(s). The per-bot path is always registered so the
        # bot is addressable by its canonical URL. A custom ``endpoint`` (e.g.
        # the Bot Framework standard ``/api/messages`` that Copilot Studio,
        # Teams and the Emulator POST to by default) is registered as an extra
        # route pointing at the same handler — this is what fixes the 404 when
        # the channel cannot be pointed at the per-bot URL.
        safe_id = re.sub(r"[^a-z0-9_]", "_", config.name.lower())
        default_route = f"/api/msagentsdk/{safe_id}/messages"
        # ``self.route`` is the address operators configure in the channel —
        # the custom endpoint when set, otherwise the per-bot default.
        self.route = config.endpoint or default_route

        # De-duplicated, order-preserving list of paths to register.
        self.routes = list(dict.fromkeys([self.route, default_route]))
        auth = self.app.get("auth")
        for path in self.routes:
            self.app.router.add_post(path, self.handle_request)
            # Exclude from auth middleware (pattern from WhatsApp/MS Teams wrappers)
            if auth:
                auth.add_exclude_list(path)

        self.logger.info(
            "Registered MS Agent SDK route(s): %s (anonymous_auth=%s)",
            ", ".join(self.routes),
            config.anonymous_auth,
        )

        # Surface which INBOUND auth methods are accepted, so a 401 is easy to
        # diagnose. In production both schemes coexist on the same route: a Bot
        # Framework JWT (Azure Bot Service channels) OR an API key (Copilot
        # Studio's direct connector). The API-key path is silently unavailable
        # until ``api_key`` is configured — the most common cause of a 401.
        if not config.anonymous_auth:
            methods = ["Bot Framework JWT"]
            if self._api_key:
                methods.append(f"API key (header '{self._api_key_header}')")
            self.logger.info(
                "Inbound auth accepted: %s", " | ".join(methods)
            )
            if not self._api_key:
                self.logger.warning(
                    "API-key inbound auth is DISABLED (no api_key configured). "
                    "Channels that send neither a Bot Framework JWT nor an API "
                    "key (e.g. Copilot Studio's direct connector) will get 401. "
                    "Set %s_API_KEY to enable it.",
                    config.name.upper(),
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
        # Visibility for remote connections (e.g. Copilot Studio reaching us
        # through a cloudflared/ngrok tunnel). Behind a proxy ``request.remote``
        # is the tunnel's local socket, so the real client IP lives in the
        # forwarding headers. A concise one-liner is logged at INFO for every
        # matched request so successful Copilot Studio / Teams calls are visible
        # without enabling full DEBUG noise.
        forwarded = (
            request.headers.get("CF-Connecting-IP")
            or request.headers.get("X-Forwarded-For")
            or request.headers.get("X-Real-IP")
        )
        self.logger.info(
            "Incoming %s %s peer=%s forwarded=%s ua=%r auth=%s len=%s",
            request.method,
            request.path,
            request.remote,
            forwarded,
            request.headers.get("User-Agent"),
            "yes" if request.headers.get("Authorization") else "no",
            request.headers.get("Content-Length"),
        )
        # The full body peek stays at DEBUG (guarded so it is only parsed when
        # DEBUG is on).
        if self.logger.isEnabledFor(logging.DEBUG):
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

        # Production inbound auth. Two schemes are accepted on the same route:
        #   1. Bot Framework JWT (Teams / Web Chat / Telegram via Azure Bot).
        #   2. API Key (Copilot Studio's "Microsoft 365 Agents SDK" connection,
        #      which does not accept "None"). Either is sufficient.
        auth_header = request.headers.get("Authorization")
        if auth_header:
            try:
                parts = auth_header.split(" ", 1)
                if len(parts) != 2 or not parts[1].strip():
                    raise ValueError(f"Malformed Authorization header: {auth_header!r}")
                token = parts[1].strip()
                request["claims_identity"] = (
                    await self._token_validator.validate_token(token)
                )
            except (ValueError, IndexError) as exc:
                self.logger.warning("JWT validation failed: %s", exc)
                return web.json_response({"error": str(exc)}, status=401)
        elif self._api_key:
            provided = request.headers.get(self._api_key_header)
            if not provided or not secrets.compare_digest(provided, self._api_key):
                self.logger.warning(
                    "API-Key validation failed (header=%s)", self._api_key_header
                )
                return web.json_response({"error": "Invalid API key"}, status=401)
            # Authenticated (non-anonymous) identity with no version claim →
            # the adapter resolves the outbound scope/audience to the Bot
            # Connector and mints a REAL token via the MSAL connection manager
            # (not the anonymous empty-token path).
            from microsoft_agents.hosting.core import ClaimsIdentity

            request["claims_identity"] = ClaimsIdentity(
                claims={}, is_authenticated=True, authentication_type="apikey"
            )
        else:
            # No Bot Framework JWT was sent. If API-key auth were configured we
            # would have taken the elif branch, so reaching here means the key
            # is unset — tell the operator exactly how to enable that path.
            self.logger.warning(
                "Rejected unauthenticated request to %s: no Authorization "
                "header and API-key auth is not configured (set %s_API_KEY).",
                request.path,
                self.config.name.upper(),
            )
            return web.json_response(
                {
                    "error": (
                        "No valid authentication. Provide a Bot Framework JWT "
                        "(Authorization: Bearer <token>) or an API key. API-key "
                        "auth is not configured on this bot."
                    )
                },
                status=401,
            )

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
