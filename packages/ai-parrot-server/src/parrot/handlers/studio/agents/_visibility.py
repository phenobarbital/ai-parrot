"""``PATCH /agents/{name}/visibility`` — owner-controlled visibility of a Studio agent (FEAT-605 G4, AC9)."""

from __future__ import annotations

from aiohttp import web
from pydantic import ValidationError

from ..models import VisibilityUpdateRequest
from ..storage.models import StudioStorageUnavailable


class _StudioAgentVisibilityMixin:
    """Database-mode body of :class:`StudioAgentVisibilityHandler` (agents exist as rows only there)."""

    async def _visibility_unavailable(self):
        """Visibility has no filesystem implementation (503 ``studio_storage_unavailable``)."""
        return self._studio_error(StudioStorageUnavailable("PATCH /agents/{name}/visibility needs the database backend"))

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
        """404 invisible / 403 not manageable, then the 422 visibility rules, then the guarded write (X6)."""
        name, rec = await self._studio_name_lookup(storage, part)
        if not name:
            return self._error("Agent name is required.", status=400, code="missing_name")
        if rec is None:
            return self._not_found("agent", name)
        if (denied := await self._studio_authorize(rec, name, manage=True)) is not None:
            return denied
        update = await self._visibility_request()
        if isinstance(update, web.Response):
            return update
        access = await self._access()
        if (refused := self._visibility_refusal(access, update.visibility, update.allowed_groups)) is not None:
            return refused
        svc = storage.services.agents
        updated = await self._studio_write(
            lambda guard: svc.update_visibility(
                part, name, visibility=update.visibility, allowed_groups=update.allowed_groups, guard=guard
            ),
            record=rec, reread=lambda: svc.get(part, name), reauthorize=self._reauthorize("agent", name),
            expected_version=None,
        )
        if isinstance(updated, web.Response):
            return updated
        return self.json_response(self._studio_item_for(access, updated))
