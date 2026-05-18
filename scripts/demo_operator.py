"""End-to-end demo: OperatorAgent + Office365 OAuth2 against a real tenant.

Run this script against a real Microsoft tenant to validate the entire
flow described in the planning doc:

    1. Per-user OperatorAgent instance via ``BotManager.get_bot``.
    2. Office365 OAuth2 PKCE consent via the REST endpoint
       ``POST /api/v1/agents/integrations/operator/o365/connect``.
    3. Token persisted in the navigator-session vault (encrypted) AND in
       Redis (hot cache, 90-day TTL).
    4. ``POST /api/v1/agents/chat/operator`` returns real mailbox data
       through the user's delegated access.
    5. Restarting the server preserves credentials because the vault
       survives Redis flushes.

Required env vars
=================

    O365_CLIENT_ID
    O365_CLIENT_SECRET
    O365_TENANT_ID         (e.g. "common", "organizations", or a GUID)
    O365_REDIRECT_URI      (default: http://localhost:5000/api/auth/oauth2/o365/callback)
    OAUTH2_REDIS_URL       (default: redis://localhost:6379/4)
    WEB_OAUTH_ALLOWED_ORIGINS (comma-separated, e.g. "http://localhost:3000")

Usage
=====

    source .venv/bin/activate
    python scripts/demo_operator.py

The script prints curl commands to walk through the manual validation
sequence. It does NOT auto-open a browser — the user must visit the
``auth_url`` returned by step 2 to grant consent.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from aiohttp import web

# Make the local agents/ package importable so OperatorAgent registers.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parrot.auth.credentials import OAuthCredentialResolver  # noqa: E402
from parrot.auth.o365_oauth import O365OAuthManager  # noqa: E402
from parrot.conf import (  # noqa: E402
    O365_CLIENT_ID,
    O365_CLIENT_SECRET,
    O365_REDIRECT_URI,
    O365_TENANT_ID,
    OAUTH2_REDIS_URL,
)
from parrot.integrations.oauth2.o365_provider import O365OAuth2Provider  # noqa: E402
from parrot.integrations.oauth2.registry import register_oauth2_provider  # noqa: E402
from parrot.manager import BotManager  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("demo_operator")


REQUIRED_ENV = ("O365_CLIENT_ID", "O365_CLIENT_SECRET", "O365_TENANT_ID")


def _check_env() -> None:
    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        logger.error(
            "Missing required env vars: %s\n"
            "Set them in your shell and retry. See "
            "docs/integrations/office365-oauth2.md for the Azure AD setup.",
            ", ".join(missing),
        )
        sys.exit(2)


async def _build_app() -> web.Application:
    """Construct an aiohttp app with O365 OAuth2 + OperatorAgent wired."""
    app = web.Application()

    # 1. Office365 OAuth2 manager (PKCE + client_secret), mounts callback route.
    manager = O365OAuthManager(
        client_id=O365_CLIENT_ID,
        client_secret=O365_CLIENT_SECRET,
        redirect_uri=O365_REDIRECT_URI,
        tenant_id=O365_TENANT_ID,
        app=app,
        redis_url=OAUTH2_REDIS_URL,
    )
    manager.setup()

    # 2. Register provider so IntegrationsService.start_connect resolves it.
    register_oauth2_provider(O365OAuth2Provider(manager=manager))

    # 3. Bring up the BotManager so OperatorAgent and friends register.
    bot_manager = BotManager(
        enable_database_bots=False,
        enable_crews=False,
        enable_registry_bots=True,
    )

    # Importing the agent runs the @register_agent decorator side effect.
    from agents import operator  # noqa: F401

    await bot_manager.setup(app) if hasattr(bot_manager, "setup") else None
    app["bot_manager"] = bot_manager

    return app


def _print_walkthrough() -> None:
    base = "http://localhost:5000"
    print()
    print("=" * 78)
    print("OperatorAgent + Office365 OAuth2 — manual validation walkthrough")
    print("=" * 78)
    print()
    print("1. Authenticate against the Navigator session layer (cookie required).")
    print(f"   Use your normal /login flow; in tests you can curl with --cookie-jar.")
    print()
    print("2. First chat — creates / caches the per-user OperatorAgent instance:")
    print(
        f"   curl -sS -b cookies -X POST {base}/api/v1/agents/chat/operator "
        '-H "Content-Type: application/json" '
        '-d \'{"query":"What can you do?"}\''
    )
    print()
    print("3. Start the OAuth2 connect flow (gets the consent URL):")
    print(
        f"   curl -sS -b cookies -X POST "
        f"{base}/api/v1/agents/integrations/operator/o365/connect "
        '-H "Content-Type: application/json" '
        '-d \'{"return_origin":"http://localhost:3000"}\''
    )
    print()
    print("4. Open the returned auth_url in a browser, grant consent. The popup")
    print("   redirects back here and shows web_oauth_success.html.")
    print()
    print("5. Verify the token was persisted:")
    print(f"   redis-cli -u {OAUTH2_REDIS_URL} keys 'oauth2:o365:*'")
    print('   # documentdb shell: db.user_credentials.find({"name":/^oauth2_o365_/})')
    print()
    print("6. Real usage — should return the user's actual mailbox:")
    print(
        f"   curl -sS -b cookies -X POST {base}/api/v1/agents/chat/operator "
        '-H "Content-Type: application/json" '
        '-d \'{"query":"Read my 3 most recent inbox messages"}\''
    )
    print()
    print("7. Vault hydration test — flush Redis, repeat step 6:")
    print(f"   redis-cli -u {OAUTH2_REDIS_URL} flushdb && # repeat curl from step 6")
    print()
    print("8. Forced re-auth test — flush BOTH Redis and the vault row:")
    print(f"   redis-cli -u {OAUTH2_REDIS_URL} flushdb")
    print('   # documentdb: db.user_credentials.deleteMany({"name":/^oauth2_o365_/})')
    print("   # The next chat call must raise AuthorizationRequired with auth_url.")
    print()
    print("=" * 78)
    print()


async def main() -> None:
    _check_env()
    app = await _build_app()
    _print_walkthrough()

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 5000)
    await site.start()
    logger.info("Demo server listening on http://0.0.0.0:5000")
    logger.info("Callback path: %s", O365_REDIRECT_URI)

    try:
        # Block forever until Ctrl-C.
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down...")
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
