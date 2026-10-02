"""Database-mode bodies of ``StudioSkillsCatalogHandler``, as a mixin."""

from __future__ import annotations


from aiohttp import web
from parrot.skills.models import SkillCategory

# the package module: patch-aware reads of ``_get_shared_skill_registry`` / ``create_skill_registry`` /
# ``AGENTS_DIR`` (tests patch ``studio.skills_catalog.<name>``); only attributes are read, at call time

from ..access import _store_record
from ..storage.models import StudioNameConflict


class _StudioSkillsCatalogDbMixin:
    """Database-mode GET / POST / PUT / DELETE of the skills catalog."""

    async def _db_get(self, storage, part):
        """One skill (``/skills/{id}``, with the index versions) or the category-grouped list."""
        skill_id = self.request.match_info.get("id")
        if not skill_id:
            return await self._db_list(storage, part)
        rec, denied = await self._db_skill(storage, part, skill_id, manage=False)
        if denied is not None:
            return denied
        data = self._skill_item_for(await self._access(), rec)
        try:
            data["versions"] = await (await self._db_registry(part)).get_skill_versions(str(rec.skill_id))
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning("Studio: failed to fetch registry versions for '%s': %s", skill_id, exc)
            data["versions"] = []
        return self.json_response(data)

    async def _db_list(self, storage, part):
        """The visible skills grouped by category (optional ``category`` / ``owner`` filters)."""
        qs = self.request.rel_url.query
        valid = [c.value for c in SkillCategory]
        if qs.get("category") and qs["category"] not in valid:
            return self._error(f"Invalid category '{qs['category']}'; must be one of {valid}.", status=400,
                               code="invalid_category")
        recs = await storage.services.skills.list(part, category=qs.get("category") or None,
                                                  owner=qs.get("owner") or None)
        access = await self._access()
        recs = sorted((r for r in recs if access.can_see(_store_record("skill", r.skill_id, r))),
                      key=lambda r: (r.category, r.name))
        grouped: dict[str, list[dict]] = {}
        for rec in recs:
            grouped.setdefault(rec.category, []).append(self._skill_item_for(access, rec))
        return self.json_response({"skills": grouped, "count": len(recs)})

    async def _db_publish_request(self):
        """The :class:`SkillPublishRequest` of a publish, or the refusal (route, author gate, body)."""
        if self.request.match_info.get("id"):
            return self._error("Use POST /astudio/skills (no id in the URL) to publish.", status=400,
                               code="invalid_route")
        if (denied := await self._require_author()) is not None:
            return denied
        return await self._db_request(allow_visibility=True)

    async def _db_post(self, storage, part):
        """Publish: Postgres first, the derived index best-effort."""
        req = await self._db_publish_request()
        if isinstance(req, web.Response):
            return req
        access = await self._access()
        if (refused := self._visibility_refusal(access, req.visibility, req.allowed_groups)) is not None:
            return refused
        stamp = access.stamp(visibility=req.visibility, allowed_groups=req.allowed_groups)
        svc = storage.services.skills
        try:
            rec = await svc.publish(part, owner=stamp["owner"], name=req.name, description=req.description,
                                    body=req.body, category=req.category.value, triggers=list(req.triggers),
                                    visibility=stamp["visibility"], allowed_groups=stamp["allowed_groups"])
        except StudioNameConflict:
            return self._name_taken(req.name)
        return self.json_response(self._skill_item_for(access, await self._db_index(svc, part, rec)), status=201)

    async def _db_put(self, storage, part):
        """Update description/category/triggers/body of a manageable skill."""
        skill_id = self.request.match_info.get("id")
        if not skill_id:
            return self._error("Skill id is required.", status=400, code="missing_id")
        if (denied := await self._require_author()) is not None:
            return denied
        rec, denied = await self._db_skill(storage, part, skill_id, manage=True)
        if denied is not None:
            return denied
        req = await self._db_request()
        if isinstance(req, web.Response):
            return req
        svc = storage.services.skills
        rec = await svc.update(part, rec.skill_id, description=req.description, category=req.category.value,
                               triggers=list(req.triggers), body=req.body)
        return self.json_response(self._skill_item_for(await self._access(), await self._db_index(svc, part, rec)))

    async def _db_delete(self, storage, part):
        """Delete a manageable skill and revoke it from the derived index (best-effort)."""
        skill_id = self.request.match_info.get("id")
        if not skill_id:
            return self._error("Skill id is required.", status=400, code="missing_id")
        if (refused := self._refuse_expected_version(self.request.query)) is not None:
            return refused
        if (denied := await self._require_author()) is not None:
            return denied
        rec, denied = await self._db_skill(storage, part, skill_id, manage=True)
        if denied is not None:
            return denied
        if not await storage.services.skills.delete(part, rec.skill_id):
            return self._error(f"Skill '{skill_id}' not found.", status=404, code="not_found")
        try:
            await (await self._db_registry(part)).revoke_skill(str(rec.skill_id), reason="deleted via Studio catalog")
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning("Studio: registry revoke failed for '%s': %s", skill_id, exc)
        return self.json_response({"skill_id": str(rec.skill_id), "deleted": True})
