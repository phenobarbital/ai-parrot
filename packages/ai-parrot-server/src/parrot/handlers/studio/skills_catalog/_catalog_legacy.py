"""Filesystem-mode (legacy) bodies of ``StudioSkillsCatalogHandler`` — the verbatim ``_legacy_*`` code, as a mixin."""

from __future__ import annotations

from typing import Any

from parrot.skills.models import SkillCategory
from pydantic import ValidationError

# the package module: patch-aware reads of ``_get_shared_skill_registry`` / ``create_skill_registry`` /
# ``AGENTS_DIR`` (tests patch ``studio.skills_catalog.<name>``); only attributes are read, at call time
from parrot.handlers.studio import skills_catalog as _sc

from ...models.skills_catalog import SkillCatalogEntry
from ..models import SkillPublishRequest


class _StudioSkillsCatalogLegacyMixin:
    """Legacy GET / POST / PUT / DELETE of the skills catalog plus the dual-write helpers."""

    async def _legacy_get(self):
        skill_id = self.request.match_info.get("id")
        if skill_id:
            return await self._get_one(skill_id)
        return await self._get_all()

    async def _get_all(self):
        qs = self.request.rel_url.query
        category_param = qs.get("category")
        owner_param = qs.get("owner")

        if category_param:
            valid_values = [c.value for c in SkillCategory]
            if category_param not in valid_values:
                return self._error(
                    f"Invalid category '{category_param}'; must be one of " f"{valid_values}.",
                    status=400,
                    code="invalid_category",
                )

        filters: dict[str, Any] = {}
        if category_param:
            filters["category"] = category_param
        if owner_param:
            filters["owner"] = owner_param

        try:
            entries = await self._list_entries(**filters)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to list skills: %s", exc)
            return self._error("Failed to list skills.", status=500, code="list_failed")

        entries = sorted(entries or [], key=lambda e: (e.category, e.name))

        grouped: dict[str, list[dict]] = {}
        for entry in entries:
            grouped.setdefault(entry.category, []).append(self._entry_to_dict(entry))

        return self.json_response({"skills": grouped, "count": len(entries)})

    async def _get_one(self, skill_id: str):
        entry = await self._get_entry_by_id(skill_id)
        if entry is None:
            return self._error(f"Skill '{skill_id}' not found.", status=404, code="not_found")
        data = self._entry_to_dict(entry)
        try:
            registry = _sc._get_shared_skill_registry(self.request.app, await self._get_org_id())
            data["versions"] = await registry.get_skill_versions(str(entry.skill_id))
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning(
                "Studio: failed to fetch registry versions for '%s': %s",
                skill_id,
                exc,
            )
            data["versions"] = []
        return self.json_response(data)

    async def _legacy_post(self):
        """Publish a new shared skill — PG insert first, registry
        best-effort (spec §7: "Never fail a publish because Redis is down")."""
        # PBAC (adversarial-review fix: gate was defined but never called).
        if (denied := await self._pbac_gate("skills", "astudio:skills:publish")) is not None:
            return denied

        if self.request.match_info.get("id"):
            return self._error(
                "Use POST /astudio/skills (no id in the URL) to publish.",
                status=400,
                code="invalid_route",
            )

        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")

        try:
            publish_request = SkillPublishRequest(**(payload or {}))
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

        existing = await self._get_entry_by_name(publish_request.name)
        if existing is not None:
            return self._error(
                f"Skill '{publish_request.name}' already exists.",
                status=409,
                code="duplicate",
            )

        if self.request.app.get("database") is None:
            return self._error("Database unavailable.", status=503, code="unavailable")

        user = await self._get_user()

        entry = SkillCatalogEntry(
            name=publish_request.name,
            description=publish_request.description,
            category=publish_request.category.value,
            owner=user.user_id,
            triggers=list(publish_request.triggers),
            body=publish_request.body,
            version=1,
            status="active",
            search_index_stale=False,
        )
        try:
            await self._insert_entry(entry)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error(
                "Studio: failed to insert skill catalog entry '%s': %s",
                publish_request.name,
                exc,
            )
            return self._error(f"Failed to publish skill: {exc}", status=500, code="publish_failed")

        stale = await self._dual_write_to_registry(entry, user.user_id)
        if stale:
            await self._flag_stale(entry)

        return self.json_response(self._entry_to_dict(entry), status=201)

    async def _legacy_put(self):
        # PBAC (adversarial-review fix: gate was defined but never called).
        if (denied := await self._pbac_gate("skills", "astudio:skills:update")) is not None:
            return denied

        skill_id = self.request.match_info.get("id")
        if not skill_id:
            return self._error("Skill id is required.", status=400, code="missing_id")

        entry = await self._get_entry_by_id(skill_id)
        if entry is None:
            return self._error(f"Skill '{skill_id}' not found.", status=404, code="not_found")

        user = await self._get_user()
        self._require_owner(entry.owner, user)  # raises 403 on denial

        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")
        try:
            publish_request = SkillPublishRequest(**(payload or {}))
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

        if self.request.app.get("database") is None:
            return self._error("Database unavailable.", status=503, code="unavailable")

        entry.set("description", publish_request.description)
        entry.set("category", publish_request.category.value)
        entry.set("triggers", list(publish_request.triggers))
        entry.set("body", publish_request.body)
        entry.set("version", entry.version + 1)
        try:
            await self._update_entry(entry)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to update skill '%s': %s", skill_id, exc)
            return self._error("Failed to update skill.", status=500, code="update_failed")

        stale = await self._dual_write_to_registry(entry, entry.owner)
        if stale and not entry.search_index_stale:
            await self._flag_stale(entry)

        return self.json_response(self._entry_to_dict(entry))

    async def _legacy_delete(self):
        # PBAC (adversarial-review fix: gate was defined but never called).
        if (denied := await self._pbac_gate("skills", "astudio:skills:delete")) is not None:
            return denied

        skill_id = self.request.match_info.get("id")
        if not skill_id:
            return self._error("Skill id is required.", status=400, code="missing_id")

        entry = await self._get_entry_by_id(skill_id)
        if entry is None:
            return self._error(f"Skill '{skill_id}' not found.", status=404, code="not_found")

        user = await self._get_user()
        self._require_owner(entry.owner, user)  # raises 403 on denial

        if self.request.app.get("database") is None:
            return self._error("Database unavailable.", status=503, code="unavailable")

        try:
            await self._delete_entry(entry)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to delete skill '%s': %s", skill_id, exc)
            return self._error("Failed to delete skill.", status=500, code="delete_failed")

        try:
            registry = _sc._get_shared_skill_registry(self.request.app, await self._get_org_id())
            await registry.revoke_skill(str(entry.skill_id), reason="deleted via Studio catalog")
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning("Studio: registry revoke failed for '%s': %s", skill_id, exc)

        return self.json_response({"skill_id": str(entry.skill_id), "deleted": True})

    # -- shared dual-write helpers ---------------------------------------

    async def _dual_write_to_registry(self, entry: SkillCatalogEntry, owner_user_id: str) -> bool:
        """Best-effort registry upload. Returns True on failure (caller
        flags ``search_index_stale``) — NEVER raises."""
        try:
            registry = _sc._get_shared_skill_registry(self.request.app, await self._get_org_id())
            await registry.upload_skill(
                name=entry.name,
                content=entry.body,
                agent_id=owner_user_id,
                description=entry.description,
                category=entry.category,
                triggers=list(entry.triggers or []),
                owner_user_id=owner_user_id,
                skill_id=str(entry.skill_id),
            )
            return False
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning(
                "Studio: registry dual-write failed for skill '%s': %s",
                entry.name,
                exc,
            )
            return True

    async def _flag_stale(self, entry: SkillCatalogEntry) -> None:
        entry.set("search_index_stale", True)
        try:
            await self._update_entry(entry)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error(
                "Studio: failed to flag search_index_stale for '%s': %s",
                entry.name,
                exc,
            )
