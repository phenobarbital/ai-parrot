"""``PATCH /skills/{id}/visibility`` — owner-controlled visibility of a catalogue skill (FEAT-605 G4, AC9)."""

from __future__ import annotations

from aiohttp import web
from pydantic import ValidationError

from ..models import VisibilityUpdateRequest
from ..storage.models import StudioNotFound, StudioStorageUnavailable


class _StudioSkillVisibilityMixin:
    """Database-mode body of :class:`StudioSkillVisibilityHandler` (catalogue rows exist only there)."""

    async def _visibility_unavailable(self):
        """Visibility has no filesystem implementation (503 ``studio_storage_unavailable``)."""
        return self._studio_error(StudioStorageUnavailable("PATCH /skills/{id}/visibility needs the database backend"))

    async def _visibility_request(self):
        """The parsed :class:`VisibilityUpdateRequest`, or a 400 ``invalid_json`` / ``invalid_request`` response."""
        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")
        try:
            return VisibilityUpdateRequest(**(payload if isinstance(payload, dict) else {"visibility": None}))
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

    async def _db_visibility(self, storage, part):
        """404 invisible / 403 not manageable, then the 422 visibility rules, then the write."""
        skill_id = self.request.match_info.get("id") or ""
        rec, denied = await self._db_skill(storage, part, skill_id, manage=True)
        if denied is not None:
            return denied
        update = await self._visibility_request()
        if isinstance(update, web.Response):
            return update
        access = await self._access()
        if (refused := self._visibility_refusal(access, update.visibility, update.allowed_groups)) is not None:
            return refused
        try:
            updated = await storage.services.skills.update_visibility(
                part, rec.skill_id, visibility=update.visibility, allowed_groups=update.allowed_groups
            )
        except StudioNotFound:
            return self._not_found("skill", skill_id)
        return self.json_response(self._skill_item_for(access, updated))
