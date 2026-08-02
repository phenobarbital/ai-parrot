"""Standalone entrypoint for the parrot-integrations image.

Wires ``parrot.manager.BotManager`` onto a bare aiohttp app — the pattern
documented in docs/telegram-integration.md's Quick Start — instead of the
full company webserver (app.py/run.py), which additionally pulls in
QuerySource, navigator_auth, PBAC, Jira OAuth and FormDesigner.

On startup, ``BotManager`` lazily constructs an ``IntegrationBotManager``
that reads ``{SITE_ROOT}/env/integrations_bots.yaml`` and starts every
configured channel (Telegram, Slack, MS Teams, WhatsApp, Matrix, MS Agent
SDK — whichever extras were installed).
"""
import os
from aiohttp import web
from parrot.manager import BotManager


async def healthz(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/healthz", healthz)
    BotManager().setup(app)
    return app


if __name__ == "__main__":
    web.run_app(
        build_app(),
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
    )
