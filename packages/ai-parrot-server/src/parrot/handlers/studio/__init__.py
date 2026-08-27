"""Agent Studio — ``/api/v1/astudio/*`` route registration (FEAT-467).

``setup_studio_routes(app)`` is called once from ``BotManager.setup()``
(pattern: ``setup_credentials_routes``, credentials.py:506) and registers
every Studio view under the ``/api/v1/astudio/`` prefix.

Route prefix is deliberately ``/api/v1/astudio/`` — NOT ``/api/v1/studio/``
— because another installed service already occupies "studio"-style
routes on this deployment (spec §2, resolved in brainstorm). Internal
code naming (this package, ``AgentStudio*`` classes) is unaffected.

Each functional area (agents, drafts, files, testing, toolkits,
skills_catalog, byok, catalog, meta_agent) is added by its own follow-up
task (TASK-2512 through TASK-2521). TASK-2511 scaffolded the package and
this registration function; TASK-2512 is the first to add concrete
routes (agent lifecycle).
"""
from __future__ import annotations

from aiohttp import web

STUDIO_PREFIX = "/api/v1/astudio"


def setup_studio_routes(app: web.Application) -> None:
    """Register all ``/api/v1/astudio/*`` routes.

    Each handler module is imported lazily (inside this function, not at
    module import time) so that a not-yet-implemented area never breaks
    app startup. Later tasks add their own ``app.router.add_view(...)``
    calls here as they land.

    Deliberately uses plain ``app.router.add_view()`` (not
    ``AbstractModel.configure()``) for every Studio route — the latter
    registers a catch-all ``{id:.*}`` route that creates route-ordering
    traps (spec §7 "Known Risks").

    Args:
        app: The aiohttp Application (the same instance ``BotManager
            .setup`` operates on).
    """
    # Agent lifecycle (FEAT-467 TASK-2512): create/list/read/reload/delete.
    from .agents import StudioAgentReloadHandler, StudioAgentsHandler

    app.router.add_view(f"{STUDIO_PREFIX}/agents", StudioAgentsHandler)
    app.router.add_view(f"{STUDIO_PREFIX}/agents/{{name}}", StudioAgentsHandler)
    app.router.add_view(
        f"{STUDIO_PREFIX}/agents/{{name}}/reload", StudioAgentReloadHandler
    )
