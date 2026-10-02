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

import logging
from collections.abc import Callable
from typing import Any

from aiohttp import web

STUDIO_PREFIX = "/api/v1/astudio"

_STUDIO_MOUNTS_APP_KEY = "_astudio_mounted_prefixes"
_STUDIO_STARTUP_APP_KEY = "_astudio_startup_installed"

ViewWrapper = Callable[[type[web.View]], "type[web.View] | None"]


def install_startup_hook_once(app: web.Application, hook: Any, *, signal: str = "on_startup") -> bool:
    """Append ``hook`` to ``app.<signal>`` at most once per app.

    Args:
        app: The aiohttp application.
        hook: The signal callback.
        signal: ``on_startup`` / ``on_shutdown`` / ``on_cleanup``.

    Returns:
        ``True`` when the hook was appended, ``False`` when already installed.
    """
    installed: set = app.setdefault(_STUDIO_STARTUP_APP_KEY, set())
    marker = (signal, getattr(hook, "__qualname__", repr(hook)))
    if marker in installed:
        return False
    installed.add(marker)
    getattr(app, signal).append(hook)
    return True


class _Registrar:
    """Applies ``prefix`` and ``view_wrapper`` (once per class) to every Studio route."""

    def __init__(self, app: web.Application, base: str, view_wrapper: ViewWrapper | None) -> None:
        self.app, self.base, self._wrapper = app, base.rstrip("/"), view_wrapper
        self._cache: dict[type, type | None] = {}

    def add(self, path: str, view: type[web.View]) -> None:
        """Register ``path`` for ``view`` (wrapped once per class; ``None`` skips)."""
        if view not in self._cache:
            self._cache[view] = view if self._wrapper is None else self._wrapper(view)
        target = self._cache[view]
        if target is not None:
            self.app.router.add_view(f"{self.base}{path}", target)


def _register_me(reg: _Registrar) -> None:
    # Capabilities (FEAT-605): the literal /me goes before every dynamic top-level route.
    from .me import StudioCapabilitiesHandler

    reg.add("/me", StudioCapabilitiesHandler)


def _register_agents(reg: _Registrar) -> None:
    # Agent lifecycle (FEAT-467 TASK-2512): create/list/read/reload/delete.
    from .agents import StudioAgentReloadHandler, StudioAgentsHandler

    reg.add("/agents", StudioAgentsHandler)
    reg.add("/agents/{name}", StudioAgentsHandler)
    reg.add("/agents/{name}/reload", StudioAgentReloadHandler)


def _register_drafts(reg: _Registrar) -> None:
    # Draft pipeline (FEAT-467 TASK-2513): save/list/read/activate/delete.
    from .drafts import StudioDraftActivateHandler, StudioDraftsHandler

    reg.add("/drafts", StudioDraftsHandler)
    reg.add("/drafts/{name}", StudioDraftsHandler)
    reg.add("/drafts/{name}/activate", StudioDraftActivateHandler)


def _register_files(reg: _Registrar) -> None:
    # Per-agent asset files (FEAT-467 TASK-2514): identity/kb/skills CRUD.
    from .files import StudioFilesHandler

    reg.add("/agents/{name}/files/{kind}", StudioFilesHandler)
    reg.add("/agents/{name}/files/{kind}/{filename:.*}", StudioFilesHandler)


def _register_skills(reg: _Registrar) -> None:
    # Shared skills catalog (FEAT-467 TASK-2515).
    from .skills_catalog import (
        StudioSkillsCatalogHandler,
        StudioSkillsImportHandler,
        StudioSkillsResyncHandler,
    )

    reg.add("/skills", StudioSkillsCatalogHandler)
    # NOTE: the literal /skills/resync route MUST be registered before the
    # dynamic /skills/{id} route — aiohttp matches in registration order and
    # {id} would otherwise swallow "resync" as an id.
    reg.add("/skills/resync", StudioSkillsResyncHandler)
    reg.add("/skills/{id}", StudioSkillsCatalogHandler)
    reg.add("/agents/{name}/skills/import/{id}", StudioSkillsImportHandler)


def _register_keys(reg: _Registrar) -> None:
    # BYOK — per-user LLM API keys (FEAT-467 TASK-2516).
    from .byok import StudioKeysHandler

    reg.add("/keys", StudioKeysHandler)
    reg.add("/keys/{provider}", StudioKeysHandler)


def _register_testing(reg: _Registrar) -> None:
    # Testing surface (FEAT-467 TASK-2517).
    from .testing import (
        StudioTestingHandler,
        StudioToolAssignHandler,
        StudioToolExecuteHandler,
    )

    reg.add("/agents/{name}/test/ask", StudioTestingHandler)
    reg.add("/agents/{name}/test", StudioTestingHandler)
    reg.add("/tools/{slug}/execute", StudioToolExecuteHandler)
    reg.add("/agents/{name}/tools", StudioToolAssignHandler)


def _register_toolkits(reg: _Registrar) -> None:
    # Toolkit config surfaces (FEAT-467 TASK-2518) + FEAT-593 persistence.
    from .toolkit_config import (
        StudioAgentMcpServersHandler,
        StudioAgentToolkitsHandler,
        StudioToolkitOptionsHandler,
    )
    from .toolkit_overrides import StudioUserToolkitOverrideHandler
    from .toolkits import StudioToolkitsHandler

    reg.add("/toolkits/{slug}/schema", StudioToolkitsHandler)
    reg.add("/agents/{name}/toolkits", StudioToolkitsHandler)
    # The existing toolkit route has a wildcard POST view, so the GET list
    # needs a distinct resource path rather than an unreachable second view.
    reg.add("/agents/{name}/toolkit-config", StudioAgentToolkitsHandler)
    reg.add("/agents/{name}/toolkits/{slug}", StudioAgentToolkitsHandler)
    reg.add("/agents/{name}/toolkits/{slug}/options/{param}", StudioToolkitOptionsHandler)
    reg.add("/agents/{name}/mcp-servers", StudioAgentMcpServersHandler)
    reg.add("/agents/{name}/toolkits/{slug}/me", StudioUserToolkitOverrideHandler)


def _register_catalog(reg: _Registrar) -> None:
    # Reference catalogs (FEAT-467 TASK-2519).
    from .catalog import StudioCatalogHandler

    reg.add("/catalog/{kind}", StudioCatalogHandler)


def _register_assistant(reg: _Registrar) -> None:
    # AgentStudio meta-agent (FEAT-467 TASK-2521).
    from .meta_agent import StudioAssistantHandler

    reg.add("/assistant", StudioAssistantHandler)


def setup_studio_routes(
    app: web.Application,
    *,
    prefix: str | None = None,
    view_wrapper: ViewWrapper | None = None,
) -> None:
    """Register all Studio routes under ``prefix`` (default :data:`STUDIO_PREFIX`).

    Handler modules are imported lazily so a not-yet-implemented area never
    breaks app startup. Uses plain ``app.router.add_view()`` (never
    ``AbstractModel.configure()``: its catch-all ``{id:.*}`` creates
    route-ordering traps).

    Calling twice with the same prefix is a logged no-op. Startup hooks are
    installed once per app regardless of the number of prefixes.

    Args:
        app: The aiohttp Application.
        prefix: Mount prefix, may contain ``{tenant}``; ``None`` ⇒ default.
        view_wrapper: Called once per distinct view class; its result is
            registered for every route of that class, ``None`` skips them.
    """
    base = prefix or STUDIO_PREFIX
    mounted: set = app.setdefault(_STUDIO_MOUNTS_APP_KEY, set())
    if base in mounted:
        logging.getLogger("Parrot.AgentStudio").info("setup_studio_routes: %s already mounted", base)
        return
    mounted.add(base)
    reg = _Registrar(app, base, view_wrapper)
    for register in (
        _register_me,
        _register_agents,
        _register_drafts,
        _register_files,
        _register_skills,
        _register_keys,
        _register_testing,
        _register_toolkits,
        _register_catalog,
        _register_assistant,
    ):
        register(reg)
    # Startup reconciliation pass: repair any search_index_stale rows left
    # over from a prior registry outage (spec §7 "Dual-write drift").
    from .skills_catalog import reconcile_skills_catalog

    install_startup_hook_once(app, reconcile_skills_catalog)
    # Studio storage resolution (FEAT-621 §2.7): memoises ``studio_storage``
    # on the app; installed once per app regardless of the number of prefixes.
    from .storage.backend import install_studio_storage_cleanup, resolve_studio_storage

    install_startup_hook_once(app, resolve_studio_storage)
    from .meta_agent import cleanup_studio_assistants

    install_startup_hook_once(app, cleanup_studio_assistants, signal="on_cleanup")  # assistant instances, every mode
    install_studio_storage_cleanup(app)  # unregisters the Postgres stores at cleanup
