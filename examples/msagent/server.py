"""MSAgentSDK example: Fireflies + work.iq + Office 365 per-user auth.

FEAT-264 / TASK-1677

Demonstrates the unified credential broker end-to-end:
- A BasicAgent with WorkIQTool (OBO), Office365Toolkit (delegated 3LO)
  and a Fireflies stub tool (static key).
- Per-user credential resolution via declarative CredentialBroker config —
  no wire_*() calls.
- MSAgentSDK chat surface: OAuthCard for OBO misses, Adaptive Card for
  static-key misses, plus proactive resume after consent.
- Optional A2A sub-agent surface sharing the same broker config.
- OOB Fireflies API-key capture route (FEAT-264 / TASK-1677).

WorkIQ + Office 365 require an Entra app registration (see env vars below).
When ``O365_CLIENT_ID`` / ``O365_CLIENT_SECRET`` are not set, the example
degrades gracefully to a Fireflies-only demo — the ``obo`` broker strategy
fails fast at startup without its O365 deps, so the workiq provider and
the O365 tools are only wired when the registration is available.

MCP call stubs
--------------
The WorkIQTool and Fireflies stub return demo responses — they do NOT make
live MCP calls.  Real calls require:
  - WorkIQ: a valid Entra OBO token (run against a real M365 tenant).
  - Fireflies: a real API key and a running Fireflies MCP server.
Office365Toolkit calls Microsoft Graph for real once the user completes
the delegated sign-in.

Usage
-----
    source .venv/bin/activate
    python examples/msagent/server.py

Optional env vars
-----------------
  MSCOPILOTAGENT_MICROSOFT_APP_ID      Azure Bot app ID (prod only)
  MSCOPILOTAGENT_MICROSOFT_APP_PASSWORD
  MSCOPILOTAGENT_MICROSOFT_TENANT_ID
  HOST / PORT                          Default: 0.0.0.0 / 3978
  CAPTURE_BASE_URL                     Public base URL for OOB capture link
                                       (default: http://localhost:3978)
  O365_CLIENT_ID                       Entra app registration (enables
  O365_CLIENT_SECRET                   WorkIQ OBO + Office 365 toolkit)
  O365_TENANT_ID                       Default: common
  O365_REDIRECT_URI                    Default: {CAPTURE_BASE_URL}/api/auth/
                                       oauth2/o365/callback

Entra app registration (required for WorkIQ + Office 365)
----------------------------------------------------------
In https://entra.microsoft.com → App registrations → your app:
  1. Authentication → Add a platform → **Web** → Redirect URI:
     ``{CAPTURE_BASE_URL}/api/auth/oauth2/o365/callback``
     (must match O365_REDIRECT_URI byte-for-byte; add one entry per
     environment — e.g. the dev-tunnel URL and the production URL).
  2. Certificates & secrets → client secret → ``O365_CLIENT_SECRET``.
  3. API permissions (Microsoft Graph, **delegated**): User.Read,
     Mail.Read, Mail.Send, Files.Read, Files.ReadWrite, Sites.Read.All,
     Calendars.Read.
  4. For WorkIQ OBO: admin consent for
     ``api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask``.
  5. For the OAuthCard sign-in button (Teams/Copilot): the Azure **Bot
     resource** → Settings → Configuration → OAuth Connection Settings
     needs a connection **named after each provider** — ``o365`` and
     ``workiq`` — pointing at the same Entra app. The card triggers the
     Bot Framework Token Service flow through that connection; the
     ``auth_url`` consent link is the fallback for link-based surfaces
     (A2A, the web capture page).
The startup log echoes this checklist with the resolved values.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Ensure the repo root is on sys.path when running from the examples dir.
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aiohttp import web  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("msagent_example")


# ---------------------------------------------------------------------------
# In-memory Redis stub
# (Replace with a real redis.asyncio.Redis in production.)
# ---------------------------------------------------------------------------


class _MemRedis:
    """Minimal Redis-API-compatible in-memory store for demo purposes.

    Covers the surface used by :class:`parrot.auth.oauth2_base.AbstractOAuth2Manager`
    (``set``/``get``/``delete``/``ping``/``lock``) and
    :class:`parrot.human.suspended_store.SuspendedExecutionStore` (``setex``).
    TTLs are ignored — records live for the process lifetime.
    """

    def __init__(self) -> None:
        self._d: Dict[str, str] = {}

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> None:
        self._d[key] = value

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._d[key] = value

    async def get(self, key: str) -> Optional[str]:
        return self._d.get(key)

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self._d.pop(k, None)

    async def ping(self) -> bool:
        return True

    def lock(self, name: str, **kwargs: Any) -> Any:
        class _NullLock:
            async def acquire(self) -> bool:
                return True

            async def release(self) -> None:
                return None

        return _NullLock()

    async def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# In-memory vault stub
# (Replace with a real VaultTokenSync backed by DB + Redis in production.)
# ---------------------------------------------------------------------------


class _InMemoryVault:
    """Minimal in-memory vault for demo purposes.

    In production, replace this with:
        from parrot.services.vault_token_sync import VaultTokenSync
        vault = VaultTokenSync(db_pool=app["authdb"], redis=app["redis"])
    """

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}

    async def store_tokens(
        self, user_id: str, provider: str, tokens: Dict[str, Any]
    ) -> None:
        self._store.setdefault(user_id, {})[provider] = tokens

    async def read_tokens(
        self, user_id: str, provider: str
    ) -> Optional[Dict[str, Any]]:
        return self._store.get(user_id, {}).get(provider)


# ---------------------------------------------------------------------------
# Fireflies stub tool
# (credential_provider="fireflies" signals static-key broker routing.)
# ---------------------------------------------------------------------------


def _make_fireflies_tool() -> Any:
    """Return a minimal Fireflies stub AbstractTool.

    In production, replace this with an MCP tool that calls the Fireflies
    GraphQL API using the resolved api_key from ``kwargs["_credential"]``.
    """
    from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
    from pydantic import Field

    class _FirefliesArgs(AbstractToolArgsSchema):
        query: str = Field(..., description="Natural-language query about your meetings.")

    class _FirefliesTool(AbstractTool):
        name = "fireflies_search"
        description = (
            "Search Fireflies.ai meeting transcripts and summaries. "
            "Requires a Fireflies API key (one-time setup via the link provided)."
        )
        credential_provider: str = "fireflies"
        args_schema = _FirefliesArgs

        async def _execute(self, query: str = "", **kwargs: Any) -> str:  # noqa: D102
            # The resolved API key is injected by the broker seam in kwargs.
            # A real implementation would use it to call the Fireflies GraphQL API.
            api_key: str = (kwargs.get("_credential") or "")[:6] or "demo"
            logger.info(
                "FirefliesTool._execute: query=%r api_key_prefix=%s", query[:40], api_key
            )
            return (
                f"[DEMO — Fireflies stub] Searched for: {query!r}. "
                "Connect to a real Fireflies MCP server for live meeting data."
            )

    return _FirefliesTool()


# ---------------------------------------------------------------------------
# O365 infrastructure (Entra 3LO manager + OBO interface)
# ---------------------------------------------------------------------------


def build_o365_infra(
    app: web.Application,
    capture_base: str,
    vault: _InMemoryVault,
) -> Optional[tuple]:
    """Wire the O365 OAuth manager (3LO) and interface (OBO) from env vars.

    Requires ``O365_CLIENT_ID`` and ``O365_CLIENT_SECRET``; returns ``None``
    (Fireflies-only demo) when they are absent.  On success:

    - Mounts ``GET /api/auth/oauth2/o365/callback`` on *app* via
      ``O365OAuthManager.setup()``.
    - Bridges the manager's vault persistence into the demo *vault* under
      provider ``"o365"`` — exactly where
      :class:`~parrot.auth.oauth2.workiq_provider.WorkIQOBOCredentialResolver`
      looks for the Entra token to exchange (one sign-in covers o365 + workiq).

    Args:
        app: The aiohttp application (callback route target).
        capture_base: Public base URL used to derive the redirect URI.
        vault: Demo vault shared with the credential broker.

    Returns:
        ``(o365_manager, o365_interface)`` or ``None`` when not configured.
    """
    client_id = os.getenv("O365_CLIENT_ID")
    client_secret = os.getenv("O365_CLIENT_SECRET")
    if not client_id or not client_secret:
        logger.warning(
            "O365_CLIENT_ID / O365_CLIENT_SECRET not set — WorkIQ (OBO) and "
            "the Office 365 toolkit are DISABLED. Fireflies-only demo."
        )
        return None

    tenant_id = os.getenv("O365_TENANT_ID", "common")
    redirect_uri = os.getenv(
        "O365_REDIRECT_URI",
        f"{capture_base}/api/auth/oauth2/o365/callback",
    )

    from parrot.auth.o365_oauth import O365OAuthManager

    # Bridge the manager's vault persistence into the demo vault under
    # provider "o365" so the WorkIQ OBO resolver finds the Entra token
    # (vault.read_tokens(user_id, "o365") → {"access_token": ...}).
    async def _vault_writer(user_id: str, name: str, payload: Dict[str, Any]) -> None:
        await vault.store_tokens(user_id, "o365", payload)

    async def _vault_reader(user_id: str, name: str) -> Dict[str, Any]:
        tokens = await vault.read_tokens(user_id, "o365")
        if tokens is None:
            raise KeyError(name)
        return tokens

    async def _vault_deleter(user_id: str, name: str) -> None:
        await vault.store_tokens(user_id, "o365", None)  # type: ignore[arg-type]

    manager = O365OAuthManager(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        tenant_id=tenant_id,
        app=app,
        redis_client=_MemRedis(),
        vault_writer=_vault_writer,
        vault_reader=_vault_reader,
        vault_deleter=_vault_deleter,
    )
    manager.setup()

    try:
        from parrot.interfaces.o365 import O365Client

        o365_interface = O365Client(
            credentials={
                "client_id": client_id,
                "client_secret": client_secret,
                "tenant_id": tenant_id,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "O365Client construction failed (%s) — WorkIQ OBO exchange "
            "unavailable; Office 365 3LO toolkit still active.",
            exc,
        )
        return None

    logger.info(
        "O365 wired: tenant=%s redirect_uri=%s (WorkIQ OBO + Office 365 toolkit)",
        tenant_id,
        redirect_uri,
    )
    logger.info(
        "  ⚠ Entra app registration checklist (app %s):", client_id
    )
    logger.info(
        "    - Authentication → Web platform → Redirect URI: %s", redirect_uri
    )
    logger.info(
        "    - API permissions (delegated): User.Read, Mail.Read, Mail.Send, "
        "Files.Read, Files.ReadWrite, Sites.Read.All, Calendars.Read"
    )
    logger.info(
        "    - WorkIQ OBO additionally needs admin consent for "
        "api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask"
    )
    return manager, o365_interface


# ---------------------------------------------------------------------------
# Identity-aware bridge
#
# ParrotM365Agent already extracts the sender identity from each Activity
# (aad_object_id preferred, channel id fallback) and passes user_id to ask().
# This subclass additionally records the richer identity snapshot (display
# name, channel) on the parrot agent's ``user_directory`` BEFORE delegating,
# so the agent's ``get_user_context()`` hook can surface it in the system
# prompt on every turn.
#
# Note: the directory is keyed by the RAW extracted user id. If you wire a
# CanonicalIdentityMapper into the wrapper, key by the canonical id instead.
# ---------------------------------------------------------------------------


def _make_identity_bridge_class() -> type:
    """Return a ParrotM365Agent subclass that captures sender identity.

    Lazy import so the module stays importable without the MS Agent SDK
    integration installed (same pattern as :func:`_make_fireflies_tool`).
    """
    from parrot.integrations.msagentsdk.agent import ParrotM365Agent

    class IdentityCapturingBridge(ParrotM365Agent):
        """Bridge that publishes the sender's identity to the parrot agent."""

        async def _handle_message(self, context: Any) -> None:
            uc = self._build_user_context(context.activity)
            directory = getattr(self.parrot_agent, "user_directory", None)
            if directory is not None and uc.user_id:
                directory[uc.user_id] = {
                    "display_name": uc.display_name,
                    "channel": uc.channel,
                }
            await super()._handle_message(context)

    return IdentityCapturingBridge


# ---------------------------------------------------------------------------
# Agent builder
# ---------------------------------------------------------------------------


async def build_agent(o365_manager: Any = None) -> Any:
    """Build a BasicAgent wired with Fireflies + (optionally) WorkIQ and O365.

    Args:
        o365_manager: A configured
            :class:`~parrot.auth.o365_oauth.O365OAuthManager`.  When present,
            the agent gains :class:`~parrot.tools.workiq_tool.WorkIQTool`
            (OBO-gated through the broker) and the
            :class:`~parrot_tools.o365.oauth_toolkit.Office365Toolkit`
            (delegated Graph access through the manager's token store).
            When ``None``, only the Fireflies stub is registered.

    Returns:
        A configured :class:`~parrot.bots.agent.BasicAgent`.
    """
    from parrot.bots.agent import BasicAgent
    from parrot.clients.google import GoogleGenAIClient, GoogleModel

    class IdentityAwareAgent(BasicAgent):
        """BasicAgent that injects the caller's identity into the system prompt.

        ``BaseBot.ask()`` calls :meth:`get_user_context` on every turn and
        interpolates the returned text into the system prompt (inside the
        ``<user_provided_context>`` block). The ``user_directory`` is populated
        by :class:`IdentityCapturingBridge` from each inbound Activity.
        """

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            # raw user_id → {"display_name": ..., "channel": ...}
            self.user_directory: Dict[str, Dict[str, Any]] = {}

        async def get_user_context(self, user_id: str, session_id: str) -> str:
            if not user_id:
                return ""
            info = self.user_directory.get(user_id) or {}
            lines = [f"user_id: {user_id}"]
            if info.get("display_name"):
                lines.append(f"display_name: {info['display_name']}")
            if info.get("channel"):
                lines.append(f"channel: {info['channel']}")
            if session_id:
                lines.append(f"conversation_id: {session_id}")
            return (
                "Identity of the user you are currently talking to "
                "(from the Microsoft 365 channel):\n" + "\n".join(lines)
            )

    tools: list = [_make_fireflies_tool()]
    capabilities = "You can search meeting transcripts with Fireflies."

    if o365_manager is not None:
        from parrot.auth.credentials import OAuthCredentialResolver
        from parrot.tools.workiq_tool import WorkIQTool
        from parrot_tools.o365.oauth_toolkit import Office365Toolkit

        tools.append(WorkIQTool())
        tools.append(
            Office365Toolkit(
                credential_resolver=OAuthCredentialResolver(o365_manager),
                tenant_id=getattr(o365_manager, "tenant_id", "common"),
            )
        )
        capabilities = (
            "You can search meeting transcripts with Fireflies, query Work IQ "
            "for M365 data, and use the Office 365 tools (mail, OneDrive, "
            "SharePoint, calendar) on the user's behalf."
        )

    llm = GoogleGenAIClient(model=GoogleModel.GEMINI_3_5_FLASH)
    agent: Any = IdentityAwareAgent(
        name="MSCopilotAgent",
        llm=llm,
        system_prompt=(
            "You are a helpful enterprise assistant. "
            f"{capabilities} "
            "Ask the user to authorise their accounts on first use. "
            "When the user's identity appears in the User Context section, "
            "address them by name and treat that identity as the account "
            "owner for all per-user tools."
        ),
        tools=tools,
        use_tools=True
    )
    await agent.configure()
    return agent


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------


async def run_server(
    host: str = "0.0.0.0",
    port: int = 3978,
    anonymous: bool = True,
    endpoint: Optional[str] = None,
    welcome_message: Optional[str] = None,
    api_key: Optional[str] = None,
    debug: bool = False,
) -> None:
    """Build the aiohttp app with MSAgentSDK + capture route + optional A2A.

    Architecture (FEAT-264):
      ┌──────────────────────────────────────────────────────────────┐
      │  aiohttp app                                                 │
      │  ┌──────────────────────────────┐  ┌──────────────────────┐ │
      │  │ MSAgentSDKWrapper            │  │ A2AServer (optional) │ │
      │  │  broker ──▶ fireflies (sk)   │  │  same broker         │ │
      │  │         ──▶ workiq   (obo)   │  │                      │ │
      │  │         ──▶ o365     (oauth2)│  │                      │ │
      │  └──────────────────────────────┘  └──────────────────────┘ │
      │  GET/POST /auth/fireflies/capture                            │
      │  GET      /api/auth/oauth2/o365/callback (Entra redirect)    │
      └──────────────────────────────────────────────────────────────┘

    Args:
        host: Bind address.
        port: Bind port.
        anonymous: Use anonymous auth (local dev). Set ``False`` in production.
        endpoint: Custom messaging endpoint path (e.g. ``"/api/messages"``).
        welcome_message: Bot greeting for new conversation members.
        api_key: Shared secret for API-Key inbound auth. When set (and not
            anonymous), the wrapper accepts requests carrying this value in the
            ``x-api-key`` header in addition to Bot Framework JWTs. Required by
            Copilot Studio's "Microsoft 365 Agents SDK" connection, which does
            not accept the "None" auth option. Falls back to the
            ``MSCOPILOTAGENT_API_KEY`` env var when omitted.
        debug: Enable verbose request logging.
    """
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # The app is created FIRST — the O365 OAuth manager mounts its callback
    # route on it during setup(), before the wrapper and the catch-all.
    app = web.Application()

    # ── Vault (in-memory stub) ─────────────────────────────────────────────
    vault = _InMemoryVault()

    # ── Capture URL for OOB Fireflies API-key form ────────────────────────
    capture_base = os.getenv("CAPTURE_BASE_URL", f"http://localhost:{port}")
    oob_capture_url = f"{capture_base}/auth/fireflies/capture"

    # ── O365 infra (Entra 3LO + OBO) — optional, env-driven ───────────────
    o365_infra = build_o365_infra(app, capture_base, vault)
    o365_manager = o365_infra[0] if o365_infra else None
    o365_interface = o365_infra[1] if o365_infra else None

    # ── Declarative credential config (FEAT-264 — no wire_*) ─────────────
    from parrot.auth.credentials import ProviderCredentialConfig
    from parrot.auth.broker import CredentialBroker
    from parrot.security.audit_ledger import AuditLedger
    from parrot.integrations.mcp.fireflies_a2a import FirefliesCredentialResolver

    audit_ledger = AuditLedger()

    # Build the Fireflies resolver (used for both broker registration and the
    # capture route's store_key call).
    fireflies_resolver = FirefliesCredentialResolver(
        vault_token_sync=vault,
        oob_capture_url=oob_capture_url,
    )

    configs = [
        ProviderCredentialConfig(
            provider="fireflies",
            auth="static_key",
            options={"capture_url": oob_capture_url},
        ),
    ]
    broker_deps: Dict[str, Any] = {
        "vault": vault,
        "audit_ledger": audit_ledger,
    }
    if o365_manager is not None and o365_interface is not None:
        # auth='obo' fails fast at startup without these deps — they are
        # only supplied (and the provider only declared) when O365 is wired.
        configs.append(
            ProviderCredentialConfig(provider="workiq", auth="obo", options={})
        )
        # 'o365' routes the Office365Toolkit tools (credential_provider="o365")
        # through the broker seam: a token miss raises CredentialRequired and
        # the MSAgentSDK surface renders a native OAuthCard (same UX as
        # workiq) instead of the plain authorization_required ToolResult.
        configs.append(
            ProviderCredentialConfig(provider="o365", auth="oauth2", options={})
        )
        broker_deps["o365_interface"] = o365_interface
        broker_deps["o365_oauth_manager"] = o365_manager
        broker_deps["oauth_managers"] = {"o365": o365_manager}

    broker = CredentialBroker.from_config(configs=configs, **broker_deps)
    # Register Fireflies explicitly so we hold a reference to the resolver
    # (needed for store_key in the capture route).
    broker.register("fireflies", fireflies_resolver)

    # ── Build agent ────────────────────────────────────────────────────────
    parrot_agent = await build_agent(o365_manager=o365_manager)

    # ── MSAgentSDK config ──────────────────────────────────────────────────
    from parrot.integrations.msagentsdk.models import MSAgentSDKConfig
    from parrot.integrations.msagentsdk.wrapper import MSAgentSDKWrapper

    config = MSAgentSDKConfig(
        name="MSCopilotAgent",
        chatbot_id="main_agent",
        anonymous_auth=anonymous,
        api_key=api_key,
        endpoint=endpoint,
        welcome_message=welcome_message or (
            "Hello! I can search your Fireflies meetings, query Work IQ and "
            "use Office 365 on your behalf. "
            "First use will ask you to authorise each service."
        ),
    )

    # ── Wire the MSAgentSDK wrapper with broker ────────────────────────────
    # agent_class: identity-capturing bridge — records the sender's display
    # name/channel on parrot_agent.user_directory before each ask(), so the
    # agent's get_user_context() surfaces it in the system prompt.
    wrapper = MSAgentSDKWrapper(
        agent=parrot_agent,
        config=config,
        app=app,
        broker=broker,
        agent_class=_make_identity_bridge_class(),
    )

    # ── Wire suspend/resume stores into the bridge agent (FEAT-264 / TASK-1674) ──
    # Production: replace with MsaConversationRefStore(redis=redis_client)
    #             and SuspendedExecutionStore(redis=redis_client).
    from parrot.integrations.msagentsdk.resume import MsaConversationRefStore

    wrapper.m365_agent._conv_ref_store = MsaConversationRefStore()  # in-memory for demo
    wrapper.m365_agent._adapter = wrapper.adapter
    wrapper.m365_agent._agent_app_id = config.client_id or ""

    # SuspendedExecutionStore requires a Redis client.
    # For demo: use an in-memory dict-based store so resume_by_nonce works
    # without a real Redis.  In production, pass a real redis.asyncio.Redis.
    try:
        from parrot.human.suspended_store import SuspendedExecution, SuspendedExecutionStore  # noqa: F401

        wrapper.m365_agent._suspended_store = SuspendedExecutionStore(_MemRedis())
    except Exception as exc:
        logger.warning("SuspendedExecutionStore not available: %s — resume disabled", exc)

    # ── Fireflies OOB capture route ────────────────────────────────────────
    from capture import register_capture_routes  # type: ignore[import]

    register_capture_routes(
        app,
        fireflies_resolver=fireflies_resolver,
        m365_agent=wrapper.m365_agent,
    )

    # ── Optional A2A sub-agent surface (same broker config) ───────────────
    try:
        from parrot.a2a.server import A2AServer

        a2a_server = A2AServer(
            agent=parrot_agent,
            broker=broker,
        )
        app.router.add_post("/a2a/rpc", a2a_server.handle)
        logger.info("A2A sub-agent surface mounted at POST /a2a/rpc")
    except Exception as exc:
        logger.debug("A2A surface not mounted (optional): %s", exc)

    # ── Diagnostic catch-all (registered LAST so real routes win) ──────────
    # Copilot Studio's custom connector 404s when its OpenAPI host+path do not
    # resolve to a registered route (trailing slash, wrong casing, /api/messages
    # vs the per-bot path, or a double-joined host). aiohttp emits that 404 at
    # the router BEFORE handle_request runs, so nothing gets logged. This
    # fallback matches ANY method/path that no real route claimed, logs the full
    # request, and still returns 404 — so behaviour is unchanged but the actual
    # URL Copilot Studio hit becomes visible.
    async def _diagnostic_catch_all(request: web.Request) -> web.Response:
        forwarded = (
            request.headers.get("CF-Connecting-IP")
            or request.headers.get("X-Forwarded-For")
            or request.headers.get("X-Real-IP")
        )
        try:
            body = await request.text()
        except Exception:  # noqa: BLE001
            body = "<unreadable>"
        logger.warning(
            "UNMATCHED %s %s%s peer=%s forwarded=%s ua=%r auth=%s ctype=%s "
            "body[:400]=%r",
            request.method,
            request.path,
            f"?{request.query_string}" if request.query_string else "",
            request.remote,
            forwarded,
            request.headers.get("User-Agent"),
            "yes" if request.headers.get("Authorization") else "no",
            request.headers.get("Content-Type"),
            body[:400],
        )
        return web.json_response(
            {
                "error": "not found",
                "hint": (
                    "This path is not a registered messaging route. Point your "
                    "Copilot Studio connector at one of the routes listed on "
                    "server startup (exact path, POST, no trailing slash)."
                ),
                "registered_routes": wrapper.routes,
            },
            status=404,
        )

    app.router.add_route("*", "/{tail:.*}", _diagnostic_catch_all)

    # ── Start server ───────────────────────────────────────────────────────
    auth_mode = "ANONYMOUS (dev)" if anonymous else "Azure AD JWT"
    routes = wrapper.routes
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    logger.info("MS Agent SDK + broker example running on http://%s:%s", host, port)
    logger.info("  Auth mode:  %s", auth_mode)
    for route in routes:
        logger.info("  Messaging:  POST http://%s:%s%s", host, port, route)
    logger.info("  Fireflies:  GET/POST http://%s:%s/auth/fireflies/capture", host, port)
    if o365_manager is not None:
        logger.info(
            "  O365 OAuth: GET http://%s:%s/api/auth/oauth2/o365/callback", host, port
        )
        logger.info(
            "  Entra redirect URI to register (Web platform): %s",
            os.getenv(
                "O365_REDIRECT_URI",
                f"{capture_base}/api/auth/oauth2/o365/callback",
            ),
        )
        logger.info(
            "  Credential surfaces: fireflies (static_key→Adaptive Card + OOB "
            "capture), workiq (obo→OAuthCard), o365 (oauth2→OAuthCard)"
        )
    else:
        logger.info(
            "  Credential surfaces: fireflies (static_key→Adaptive Card + OOB "
            "capture) — set O365_CLIENT_ID/O365_CLIENT_SECRET to enable "
            "workiq (OBO) and the Office 365 toolkit"
        )

    # Block until Ctrl-C
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MSAgentSDK example with FEAT-264 broker")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "3978")))
    parser.add_argument(
        "--production",
        action="store_true",
        help="Enable Azure AD JWT auth (requires MSCOPILOTAGENT_MICROSOFT_APP_* env vars)",
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="Custom messaging endpoint (e.g. /api/messages)",
    )
    parser.add_argument(
        "--welcome",
        default=None,
        help="Override the welcome message",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("MSCOPILOTAGENT_API_KEY"),
        help=(
            "Shared secret for API-Key inbound auth (Copilot Studio "
            "'Microsoft 365 Agents SDK' connection). Sent in the 'x-api-key' "
            "header. Defaults to the MSCOPILOTAGENT_API_KEY env var."
        ),
    )
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(
        run_server(
            host=args.host,
            port=args.port,
            anonymous=not args.production,
            endpoint=args.endpoint,
            welcome_message=args.welcome,
            api_key=args.api_key,
            debug=args.debug,
        )
    )
