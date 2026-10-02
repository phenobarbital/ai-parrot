"""Studio draft pipeline — save/list/read/activate/delete (FEAT-467 TASK-2513).

Implements the draft -> validate -> activate safety gate (spec §3 Module
5): a generated Python agent is saved to ``AGENTS_DIR/_drafts/`` and
statically validated (``validation.validate_draft``) on save. It is
imported and registered into the live ``AgentRegistry`` ONLY on an
explicit ``POST .../activate`` call — the ONLY path from generated code
to live code (spec §7 "Draft import side effects": the AST allowlist
must run BEFORE any import).

Package layout (oversize-module split, owner decision D1): the two views live
here with their verbs and PBAC gates; the request models, shared helpers, the
legacy filesystem bodies and the database-mode bodies are in ``_models.py`` /
``_mixin.py`` / ``_legacy.py`` / ``_db.py``.
"""

from __future__ import annotations

from navigator_auth.decorators import is_authenticated, user_session
from parrot.conf import AGENTS_DIR  # re-exported: tests patch ``drafts.AGENTS_DIR``

from ...models.studio_drafts import StudioDraft  # re-exported: tests patch ``drafts.StudioDraft``
from .._base import StudioBaseView
from ._db import _StudioDraftActivateDbMixin, _StudioDraftsDbMixin
from ._legacy import _StudioDraftActivateLegacyMixin, _StudioDraftsLegacyMixin
from ._mixin import _StudioDraftsMixin
from ._models import DRAFTS_SUBDIR, ActivateDraftRequest, SaveDraftRequest
from ._visibility import _StudioDraftVisibilityMixin

__all__ = [
    "AGENTS_DIR",
    "ActivateDraftRequest",
    "DRAFTS_SUBDIR",
    "SaveDraftRequest",
    "StudioDraft",
    "StudioDraftActivateHandler",
    "StudioDraftVisibilityHandler",
    "StudioDraftsHandler",
]


@is_authenticated()
@user_session()
class StudioDraftsHandler(_StudioDraftsLegacyMixin, _StudioDraftsDbMixin, _StudioDraftsMixin, StudioBaseView):
    """``/api/v1/astudio/drafts`` and ``/api/v1/astudio/drafts/{name}``.

    GET (list/single incl. source + validation report), POST (save +
    validate), DELETE (owner-enforced).
    """

    async def get(self):
        """List/read drafts: the declarative store (database mode) plus legacy Python drafts on GLOBAL."""
        if not self.request.match_info.get("name") and await self._tenantless():
            return self.json_response({"drafts": [], "count": 0})  # an opted-in caller with no tenant sees nothing
        return await self._dispatch(self._legacy_get, self._db_get)

    async def post(self):
        """Save a draft: a declarative ``bundle`` (database mode) or legacy Python ``source``."""
        gate = lambda: self._pbac_gate("drafts", "astudio:drafts:create")  # noqa: E731
        return await self._dispatch(self._legacy_post, self._db_post, gate)

    async def delete(self):
        """Delete a declarative draft (database mode) or a legacy Python draft."""
        gate = lambda: self._pbac_gate("drafts", "astudio:drafts:delete")  # noqa: E731
        return await self._dispatch(self._legacy_delete, self._db_delete, gate)


@is_authenticated()
@user_session()
class StudioDraftActivateHandler(
    _StudioDraftActivateLegacyMixin, _StudioDraftActivateDbMixin, _StudioDraftsMixin, StudioBaseView
):
    """``POST /api/v1/astudio/drafts/{name}/activate``.

    The ONLY path from a generated draft to a live, registered agent.
    Refuses (409) unless the draft's LATEST on-disk content re-validates
    clean, and unless any registered-name collision is explicitly
    consented to (``replace=true``) by the owner (or an admin).
    """

    async def post(self):
        """Activate a declarative draft atomically (database mode) or import a Python draft (legacy)."""
        gate = lambda: self._pbac_gate("drafts", "astudio:drafts:activate")  # noqa: E731
        return await self._dispatch(self._legacy_post, self._db_post, gate)


@is_authenticated()
@user_session()
class StudioDraftVisibilityHandler(_StudioDraftVisibilityMixin, _StudioDraftsMixin, StudioBaseView):
    """``PATCH /api/v1/astudio/drafts/{name}/visibility`` — change who can see a declarative draft."""

    async def patch(self):
        """Set ``visibility`` / ``allowed_groups`` of a declarative draft (404 invisible, 403 not manageable, 422)."""
        return await self._dispatch(self._visibility_unavailable, self._db_visibility)
