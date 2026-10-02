"""Shared skills catalog — org-wide, category-ordered, owner-filterable
(FEAT-467 TASK-2515).

Hybrid storage (spec §3 Module 7, resolved decision): Postgres
(``navigator.ai_skills_catalog`` / :class:`SkillCatalogEntry`) is the
system-of-record and SQL query plane (``ORDER BY category``,
``WHERE owner``); the shared-namespace ``SkillRegistry`` (``"<org_id>/
_shared"``) is a best-effort secondary index for embedding search and
git-like versioning. PG write always happens FIRST; the registry write
is wrapped so a Redis/embedding outage never fails a publish — it only
flags ``search_index_stale=True`` for later repair (startup
reconciliation pass, or the admin ``/skills/resync`` endpoint).

Package layout (oversize-module split, owner decision D1): the three views live
here with their verbs; the module-level helpers, the shared mixin and the
database / legacy bodies are in ``_helpers.py`` / ``_mixin.py`` /
``_catalog_db.py`` / ``_catalog_legacy.py`` / ``_import.py`` / ``_resync.py``.
Shared code reads ``_get_shared_skill_registry`` / ``create_skill_registry`` /
``AGENTS_DIR`` through this package at call time, so patching them here works.
"""

from __future__ import annotations

from navigator_auth.decorators import is_authenticated, user_session
from parrot.conf import AGENTS_DIR  # re-exported: tests patch ``skills_catalog.AGENTS_DIR``
from parrot.skills.store import create_skill_registry  # re-exported: tests patch ``skills_catalog.create_skill_registry``

from .._base import StudioBaseView
from ..files import _StudioFilesMixin
from ._catalog_db import _StudioSkillsCatalogDbMixin
from ._catalog_legacy import _StudioSkillsCatalogLegacyMixin
from ._helpers import (
    _REGISTRIES_APP_KEY,
    DEFAULT_ORG_ID,
    SHARED_NAMESPACE_SUFFIX,
    _compose_skill_markdown,
    _get_shared_skill_registry,
    _rebuild_index,
    _reconcile_database,
    _shared_index,
    _shared_namespace,
    _skill_dict,
    _upload_to_index,
    _validate_skill_markdown,
    index_published_skill,
    logger,
    org_id_from_session,
    reconcile_skills_catalog,
)
from ._import import _StudioSkillsImportDbMixin, _StudioSkillsImportLegacyMixin
from ._mixin import _StudioSkillsMixin
from ._resync import _StudioSkillsResyncDbMixin, _StudioSkillsResyncLegacyMixin

__all__ = [
    "AGENTS_DIR",
    "DEFAULT_ORG_ID",
    "SHARED_NAMESPACE_SUFFIX",
    "StudioSkillsCatalogHandler",
    "StudioSkillsImportHandler",
    "StudioSkillsResyncHandler",
    "_REGISTRIES_APP_KEY",
    "_compose_skill_markdown",
    "_get_shared_skill_registry",
    "_rebuild_index",
    "_reconcile_database",
    "_shared_index",
    "_shared_namespace",
    "_skill_dict",
    "_upload_to_index",
    "_validate_skill_markdown",
    "create_skill_registry",
    "index_published_skill",
    "logger",
    "org_id_from_session",
    "reconcile_skills_catalog",
]


@is_authenticated()
@user_session()
class StudioSkillsCatalogHandler(
    _StudioSkillsCatalogLegacyMixin, _StudioSkillsCatalogDbMixin, _StudioSkillsMixin, StudioBaseView
):
    """``/api/v1/astudio/skills`` and ``/api/v1/astudio/skills/{id}``.

    GET (list ordered/grouped by category, or one entry + registry
    versions), POST (publish — PG first, registry best-effort), PUT/
    DELETE (owner-or-admin).
    """

    # -- verbs: database backend through StudioSkillCatalogService, else the legacy bodies ---------

    async def get(self):
        """List / read skills (database mode: ``StudioSkillCatalogService``)."""
        return await self._dispatch(self._legacy_get, self._db_get)

    async def post(self):
        """Publish a skill (database mode: ``StudioSkillCatalogService``)."""
        gate = lambda: self._pbac_gate("skills", "astudio:skills:publish")  # noqa: E731
        return await self._dispatch(self._legacy_post, self._db_post, gate)

    async def put(self):
        """Update a skill (database mode: ``StudioSkillCatalogService``)."""
        gate = lambda: self._pbac_gate("skills", "astudio:skills:update")  # noqa: E731
        return await self._dispatch(self._legacy_put, self._db_put, gate)

    async def delete(self):
        """Delete a skill (database mode: ``StudioSkillCatalogService``)."""
        gate = lambda: self._pbac_gate("skills", "astudio:skills:delete")  # noqa: E731
        return await self._dispatch(self._legacy_delete, self._db_delete, gate)


@is_authenticated()
@user_session()
class StudioSkillsImportHandler(
    _StudioSkillsImportLegacyMixin, _StudioSkillsImportDbMixin, _StudioSkillsMixin, _StudioFilesMixin, StudioBaseView
):
    """``POST /api/v1/astudio/agents/{name}/skills/import/{id}``.

    Materializes a catalog entry as
    ``AGENTS_DIR/<agent>/skills/<name>.md`` — collision refused (409)
    unless ``overwrite=true``. Owner-enforced: only the target agent's
    owner (or a superuser) may import onto it — reuses
    ``_StudioFilesMixin._resolve_agent``, the same lookup the file-CRUD
    endpoints use (adversarial-review fix: this handler previously wrote
    into ANY agent's skills directory with no ownership check at all).
    """

    async def post(self):
        """Import a catalogue skill into an agent (database mode: an ``ai_agent_assets`` row)."""
        gate = lambda: self._pbac_gate("skills", "astudio:skills:import")  # noqa: E731
        return await self._dispatch(self._legacy_post, self._db_post, gate)


@is_authenticated()
@user_session()
class StudioSkillsResyncHandler(
    _StudioSkillsResyncLegacyMixin, _StudioSkillsResyncDbMixin, _StudioSkillsMixin, StudioBaseView
):
    """``POST /api/v1/astudio/skills/resync`` — admin-only.

    Re-uploads every ``search_index_stale`` catalog row into the shared
    registry; returns counts. Same routine the startup hook runs
    automatically (:func:`reconcile_skills_catalog`), exposed here for an
    on-demand admin retry.
    """

    async def post(self):
        """Resync the derived index (database mode: rebuilt from Postgres)."""
        gate = lambda: self._pbac_gate("skills", "astudio:skills:resync")  # noqa: E731
        return await self._dispatch(self._legacy_post, self._db_post, gate)
