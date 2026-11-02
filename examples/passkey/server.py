"""Passkey (WebAuthn) end-to-end example: Admin UI + one chat agent.

Run from the repository root (see docs/examples/passkey-e2e.md)::

    python examples/passkey/server.py

Then open http://localhost:5000 and sign in as ``demo`` / ``demo-password``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from env_defaults import PORT, apply_defaults  # noqa: E402

apply_defaults()

from aiohttp import web  # noqa: E402
from navigator_auth import AuthHandler  # noqa: E402

from parrot.bots.agent import BasicAgent  # noqa: E402
from parrot.manager import BotManager  # noqa: E402

# Any "provider:model" string AbstractBot accepts; the matching API key must be in the environment.
DEMO_LLM = os.environ.get("DEMO_LLM", "google:gemini-2.5-flash")


class HelloAgent(BasicAgent):
    """A small general-purpose agent used to prove the signed-in chat works."""

    name = "hello-agent"
    description = "Friendly demo agent for the passkey example."
    system_prompt = "You are a concise, friendly assistant. Answer in at most three sentences."


async def _register_agent(app: web.Application) -> None:
    """Configure the demo agent and add it to the BotManager once the app starts."""
    agent = HelloAgent(name="hello-agent", llm=DEMO_LLM)
    await agent.configure(app)
    # The registry is what GET /api/v1/bots lists and what the chat page resolves.
    app["bot_manager"].registry.register_instance(agent.name, agent)


def create_app() -> web.Application:
    """Build the aiohttp application: BotManager (+ embedded Admin UI) and navigator-auth."""
    app = web.Application()
    manager = BotManager(enable_database_bots=False)
    manager.setup(app)  # mounts the API routes and the embedded Admin UI (/login, /agents, /account, /admin)
    app["bot_manager"] = manager
    # Explicit backends: a developer's settings/settings.py may override AUTHENTICATION_BACKENDS at import time.
    AuthHandler(
        backends=["navigator_auth.backends.BasicAuth", "navigator_auth.backends.PasskeyAuth"],
        authz_backends=[],  # require authentication for every request (no host/IP allow-listing)
    ).setup(app)
    app.on_startup.append(_register_agent)
    return app


if __name__ == "__main__":
    print(f"Passkey demo on http://localhost:{PORT}  (user: demo / demo-password)")
    web.run_app(create_app(), host="127.0.0.1", port=int(PORT))
