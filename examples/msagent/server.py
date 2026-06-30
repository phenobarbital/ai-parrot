"""MSAgentSDK example: Fireflies + work.iq per-user auth on both surfaces.

FEAT-264 / TASK-1677

Demonstrates the unified credential broker end-to-end:
- A BasicAgent with WorkIQTool (OBO) and a Fireflies stub tool (static key).
- Per-user credential resolution via declarative CredentialBroker config —
  no wire_*() calls.
- MSAgentSDK chat surface: OAuthCard for OBO misses, Adaptive Card for
  static-key misses, plus proactive resume after consent.
- Optional A2A sub-agent surface sharing the same broker config.
- OOB Fireflies API-key capture route (FEAT-264 / TASK-1677).

MCP call stubs
--------------
The WorkIQTool and Fireflies stub return demo responses — they do NOT make
live MCP calls.  Real calls require:
  - WorkIQ: a valid Entra OBO token (run against a real M365 tenant).
  - Fireflies: a real API key and a running Fireflies MCP server.

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
# Agent builder
# ---------------------------------------------------------------------------


async def build_agent() -> Any:
    """Build a BasicAgent wired with WorkIQTool + Fireflies stub.

    Returns:
        A configured :class:`~parrot.bots.agent.BasicAgent`.
    """
    from parrot.bots.agent import BasicAgent
    from parrot.clients.openai import OpenAIClient
    from parrot.tools.workiq_tool import WorkIQTool

    llm = OpenAIClient(model="gpt-4o-mini")
    agent: Any = BasicAgent(
        name="MSCopilotAgent",
        llm=llm,
        system_prompt=(
            "You are a helpful enterprise assistant. "
            "You can search meeting transcripts with Fireflies and query Work IQ for M365 data. "
            "Ask the user to authorise their accounts on first use."
        ),
        use_tools=[WorkIQTool(), _make_fireflies_tool()],
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
      │  └──────────────────────────────┘  └──────────────────────┘ │
      │  GET/POST /auth/fireflies/capture                            │
      └──────────────────────────────────────────────────────────────┘

    Args:
        host: Bind address.
        port: Bind port.
        anonymous: Use anonymous auth (local dev). Set ``False`` in production.
        endpoint: Custom messaging endpoint path (e.g. ``"/api/messages"``).
        welcome_message: Bot greeting for new conversation members.
        debug: Enable verbose request logging.
    """
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # ── Vault (in-memory stub) ─────────────────────────────────────────────
    vault = _InMemoryVault()

    # ── Capture URL for OOB Fireflies API-key form ────────────────────────
    capture_base = os.getenv("CAPTURE_BASE_URL", f"http://localhost:{port}")
    oob_capture_url = f"{capture_base}/auth/fireflies/capture"

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

    broker = CredentialBroker.from_config(
        configs=[
            ProviderCredentialConfig(
                provider="fireflies",
                auth="static_key",
                options={"capture_url": oob_capture_url},
            ),
            ProviderCredentialConfig(
                provider="workiq",
                auth="obo",
                options={},
            ),
        ],
        vault=vault,
        audit_ledger=audit_ledger,
    )
    # Register Fireflies explicitly so we hold a reference to the resolver
    # (needed for store_key in the capture route).
    broker.register("fireflies", fireflies_resolver)

    # ── Build agent ────────────────────────────────────────────────────────
    parrot_agent = await build_agent()

    # ── MSAgentSDK config ──────────────────────────────────────────────────
    from parrot.integrations.msagentsdk.models import MSAgentSDKConfig
    from parrot.integrations.msagentsdk.wrapper import MSAgentSDKWrapper

    config = MSAgentSDKConfig(
        name="MSCopilotAgent",
        chatbot_id="main_agent",
        anonymous_auth=anonymous,
        endpoint=endpoint,
        welcome_message=welcome_message or (
            "Hello! I can search your Fireflies meetings and query Work IQ. "
            "First use will ask you to authorise each service."
        ),
    )

    app = web.Application()

    # ── Wire the MSAgentSDK wrapper with broker ────────────────────────────
    wrapper = MSAgentSDKWrapper(
        agent=parrot_agent,
        config=config,
        app=app,
        broker=broker,
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

        class _MemRedis:
            """Minimal Redis-API-compatible in-memory store for demo."""
            def __init__(self) -> None:
                self._d: dict = {}
            async def setex(self, key: str, ttl: int, value: str) -> None:
                self._d[key] = value
            async def get(self, key: str) -> Optional[str]:
                return self._d.get(key)
            async def delete(self, *keys: str) -> None:
                for k in keys:
                    self._d.pop(k, None)

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
    logger.info(
        "  Credential surfaces: fireflies (static_key→Adaptive Card + OOB capture), "
        "workiq (obo→OAuthCard)"
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
            debug=args.debug,
        )
    )
