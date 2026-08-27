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
    app.router.add_view(f"{STUDIO_PREFIX}/agents/{{name}}/reload", StudioAgentReloadHandler)

    # Draft pipeline (FEAT-467 TASK-2513): save/list/read/activate/delete.
    from .drafts import StudioDraftActivateHandler, StudioDraftsHandler

    app.router.add_view(f"{STUDIO_PREFIX}/drafts", StudioDraftsHandler)
    app.router.add_view(f"{STUDIO_PREFIX}/drafts/{{name}}", StudioDraftsHandler)
    app.router.add_view(f"{STUDIO_PREFIX}/drafts/{{name}}/activate", StudioDraftActivateHandler)

    # Per-agent asset files (FEAT-467 TASK-2514): identity/kb/skills CRUD.
    from .files import StudioFilesHandler

    app.router.add_view(f"{STUDIO_PREFIX}/agents/{{name}}/files/{{kind}}", StudioFilesHandler)
    app.router.add_view(
        f"{STUDIO_PREFIX}/agents/{{name}}/files/{{kind}}/{{filename:.*}}",
        StudioFilesHandler,
    )

    # Shared skills catalog (FEAT-467 TASK-2515): org-wide publish/list/
    # read/update/delete/import/resync.
    from .skills_catalog import (
        StudioSkillsCatalogHandler,
        StudioSkillsImportHandler,
        StudioSkillsResyncHandler,
        reconcile_skills_catalog,
    )

    app.router.add_view(f"{STUDIO_PREFIX}/skills", StudioSkillsCatalogHandler)
    # NOTE: the literal /skills/resync route MUST be registered before the
    # dynamic /skills/{id} route below — aiohttp's UrlDispatcher matches
    # routes in registration order, and {id} would otherwise swallow
    # "resync" as an id.
    app.router.add_view(f"{STUDIO_PREFIX}/skills/resync", StudioSkillsResyncHandler)
    app.router.add_view(f"{STUDIO_PREFIX}/skills/{{id}}", StudioSkillsCatalogHandler)
    app.router.add_view(
        f"{STUDIO_PREFIX}/agents/{{name}}/skills/import/{{id}}",
        StudioSkillsImportHandler,
    )
    # Startup reconciliation pass: repair any search_index_stale rows
    # left over from a prior registry outage (spec §7 "Dual-write drift").
    app.on_startup.append(reconcile_skills_catalog)

    # BYOK — per-user LLM API keys (FEAT-467 TASK-2516).
    from .byok import StudioKeysHandler

    app.router.add_view(f"{STUDIO_PREFIX}/keys", StudioKeysHandler)
    app.router.add_view(f"{STUDIO_PREFIX}/keys/{{provider}}", StudioKeysHandler)

    # Testing surface (FEAT-467 TASK-2517): session-scoped test/ask,
    # deterministic tool execute, tool/toolkit assignment.
    from .testing import (
        StudioTestingHandler,
        StudioToolAssignHandler,
        StudioToolExecuteHandler,
    )

    app.router.add_view(f"{STUDIO_PREFIX}/agents/{{name}}/test/ask", StudioTestingHandler)
    app.router.add_view(f"{STUDIO_PREFIX}/agents/{{name}}/test", StudioTestingHandler)
    app.router.add_view(f"{STUDIO_PREFIX}/tools/{{slug}}/execute", StudioToolExecuteHandler)
    app.router.add_view(f"{STUDIO_PREFIX}/agents/{{name}}/tools", StudioToolAssignHandler)

    # Toolkit config surfaces (FEAT-467 TASK-2518): schema introspection +
    # assignment (wiki/dataset_manager/infographic first-class + generic).
    from .toolkits import StudioToolkitsHandler

    app.router.add_view(f"{STUDIO_PREFIX}/toolkits/{{slug}}/schema", StudioToolkitsHandler)
    app.router.add_view(f"{STUDIO_PREFIX}/agents/{{name}}/toolkits", StudioToolkitsHandler)

    # Reference catalogs (FEAT-467 TASK-2519): base classes, LLM clients,
    # tools, vector stores — all reuse existing sources of truth.
    from .catalog import StudioCatalogHandler

    app.router.add_view(f"{STUDIO_PREFIX}/catalog/{{kind}}", StudioCatalogHandler)

    # AgentStudio meta-agent (FEAT-467 TASK-2521): conversational assistant.
    from .meta_agent import StudioAssistantHandler

    app.router.add_view(f"{STUDIO_PREFIX}/assistant", StudioAssistantHandler)
