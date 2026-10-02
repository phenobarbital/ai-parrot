"""Studio agent lifecycle endpoints (FEAT-467 TASK-2512).

Implements the core agent CRUD of the Studio API (spec §3 Module 4):

    POST   /api/v1/astudio/agents               — create a simple agent
    GET    /api/v1/astudio/agents                — list (registry + DB, merged)
    GET    /api/v1/astudio/agents/{name}          — single agent
    POST   /api/v1/astudio/agents/{name}/reload   — hot reload (TASK-2510)
    DELETE /api/v1/astudio/agents/{name}          — delete (factory-origin only)

Reuses the proven patterns of ``ChatbotHandler`` (``handlers/bots.py``) —
slugify/duplicate-check discipline, server-set ``created_by``, merged
registry+DB listing — WITHOUT touching ``bots.py`` itself (spec §7 "bots.py
untouched" regression-isolation constraint).

Package layout (oversize-module split, owner decision D1): the two views live
here with their verbs and PBAC gates; the shared helpers, the legacy
filesystem bodies, the database-mode bodies and the reload paths are mixins in
``_mixin.py`` / ``_legacy.py`` / ``_db.py`` / ``_reload.py``.
"""

from __future__ import annotations

from navigator_auth.decorators import is_authenticated, user_session
from parrot.conf import AGENTS_DIR  # re-exported: tests patch ``agents.AGENTS_DIR``

from .._base import StudioBaseView
from ._db import _StudioAgentsDbMixin
from ._legacy import _StudioAgentsLegacyMixin
from ._mixin import _StudioAgentsMixin
from ._reload import _StudioAgentReloadMixin

__all__ = ["AGENTS_DIR", "StudioAgentReloadHandler", "StudioAgentsHandler"]


@is_authenticated()
@user_session()
class StudioAgentsHandler(_StudioAgentsLegacyMixin, _StudioAgentsDbMixin, _StudioAgentsMixin, StudioBaseView):
    """``/api/v1/astudio/agents`` and ``/api/v1/astudio/agents/{name}``.

    GET (list/single), POST (create), DELETE (factory-origin only).
    """

    async def get(self):
        """List all agents, or return a single agent by name (database mode: Studio rows + legacy on GLOBAL)."""
        return await self._dispatch(self._legacy_get, self._db_get)

    async def post(self):
        """Create an agent: database mode persists a Studio row; filesystem mode registers (legacy)."""
        gate = lambda: self._pbac_gate("agents", "astudio:agents:create")  # noqa: E731
        return await self._dispatch(self._legacy_post, self._db_post, gate)

    async def delete(self):
        """Delete a Studio row (database mode) or a factory-origin YAML agent; DB agents are delegated."""
        gate = lambda: self._pbac_gate("agents", "astudio:agents:delete")  # noqa: E731
        return await self._dispatch(self._legacy_delete, self._db_delete, gate)

    async def patch(self):
        """``PATCH /agents/{name}`` — edit the General fields (database mode only, spec §2.9a)."""
        gate = lambda: self._pbac_gate("agents", "astudio:agents:update")  # noqa: E731
        return await self._dispatch(self._patch_unavailable, self._db_patch, gate)


@is_authenticated()
@user_session()
class StudioAgentReloadHandler(_StudioAgentReloadMixin, _StudioAgentsMixin, StudioBaseView):
    """``POST /api/v1/astudio/agents/{name}/reload`` — hot-swap an agent.

    Delegates to ``BotManager.reload_agent`` (FEAT-467 TASK-2510); this
    handler only maps the typed errors it raises to HTTP status codes.
    """

    async def post(self):
        """Reload a Studio agent through ``manager.studio`` (database mode) or ``reload_agent`` (legacy)."""
        gate = lambda: self._pbac_gate("agents", "astudio:agents:reload")  # noqa: E731
        return await self._dispatch(self._legacy_reload, self._db_reload, gate)
