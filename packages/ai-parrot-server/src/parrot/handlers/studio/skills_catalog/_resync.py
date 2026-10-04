"""Admin resync (database + legacy bodies of ``StudioSkillsResyncHandler``), as mixins."""

from __future__ import annotations



# the package module: patch-aware reads of ``_get_shared_skill_registry`` / ``create_skill_registry`` /
# ``AGENTS_DIR`` (tests patch ``studio.skills_catalog.<name>``); only attributes are read, at call time
from parrot.handlers.studio import skills_catalog as _sc

from ._helpers import _rebuild_index


class _StudioSkillsResyncDbMixin:
    """Database-mode resync."""

    async def _db_post(self, storage, part):
        """Admin-only: rebuild the partition's derived index from every catalogue row."""
        user = await self._get_user()
        is_superuser = (await self._scope()).is_superuser if self._opted_in() else user.is_superuser
        if not is_superuser:
            return self._error("Admin privileges required.", status=403, code="admin_required")
        svc = storage.services.skills
        rows = await svc.list(part)
        registry = await self._db_registry(part) if rows else None  # nothing to index: load no model
        resynced, failed = await _rebuild_index(svc, part, registry, rows)
        return self.json_response({"resynced": resynced, "failed": failed, "total": len(rows)})


class _StudioSkillsResyncLegacyMixin:
    """Legacy resync."""

    async def _legacy_post(self):
        # PBAC (adversarial-review fix: gate was defined but never called).
        if (denied := await self._pbac_gate("skills", "astudio:skills:resync")) is not None:
            return denied

        user = await self._get_user()
        is_superuser = (await self._scope()).is_superuser if self._opted_in() else user.is_superuser
        if not is_superuser:
            return self._error("Admin privileges required.", status=403, code="admin_required")

        if self.request.app.get("database") is None:
            return self._error("Database unavailable.", status=503, code="unavailable")

        try:
            stale_entries = await self._list_entries(search_index_stale=True)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: resync failed to query stale entries: %s", exc)
            return self._error("Failed to query stale entries.", status=500, code="resync_failed")

        resynced = 0
        failed = 0
        org_id = await self._get_org_id()
        for entry in stale_entries:
            try:
                registry = _sc._get_shared_skill_registry(self.request.app, org_id)
                await registry.upload_skill(
                    name=entry.name,
                    content=entry.body,
                    agent_id=entry.owner,
                    description=entry.description,
                    category=entry.category,
                    triggers=list(entry.triggers or []),
                    owner_user_id=entry.owner,
                    skill_id=str(entry.skill_id),
                )
                entry.set("search_index_stale", False)
                await self._update_entry(entry)
                resynced += 1
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.warning("Studio: resync failed for skill '%s': %s", entry.name, exc)
                failed += 1

        return self.json_response({"resynced": resynced, "failed": failed, "total": len(stale_entries)})
