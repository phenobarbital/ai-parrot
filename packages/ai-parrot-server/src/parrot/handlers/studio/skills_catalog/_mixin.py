"""Shared helpers of the skills-catalog views (``_StudioSkillsMixin``)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from aiohttp import web
from asyncdb.exceptions import NoDataFound
from pydantic import ValidationError

# the package module: patch-aware reads of ``_get_shared_skill_registry`` / ``create_skill_registry`` /
# ``AGENTS_DIR`` (tests patch ``studio.skills_catalog.<name>``); only attributes are read, at call time
from parrot.handlers.studio import skills_catalog as _sc

from ...models.skills_catalog import SkillCatalogEntry
from ..access import _store_record
from ..files import _StudioFilesMixin
from ..models import SkillPublishRequest, StudioError
from ._helpers import DEFAULT_ORG_ID, index_published_skill, org_id_from_session


class _StudioSkillsMixin:
    """Shared helpers for the skills-catalog views in this module."""

    async def _get_org_id(self) -> str:
        """Best-effort org_id from the session; ``"default"`` when absent
        (Implementation Notes: "org_id for the shared namespace: derive
        from session; when absent use 'default'")."""
        try:
            session = await self._resolve_session()
        except Exception:  # pylint: disable=broad-except
            return DEFAULT_ORG_ID
        return org_id_from_session(session)

    async def _get_entry_by_id(self, skill_id: str) -> SkillCatalogEntry | None:
        db = self.request.app.get("database")
        if db is None:
            return None
        try:
            async with await db.acquire() as conn:
                SkillCatalogEntry.Meta.connection = conn
                try:
                    return await SkillCatalogEntry.get(skill_id=skill_id)
                except NoDataFound:
                    return None
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to query skill '%s': %s", skill_id, exc)
            return None

    async def _get_entry_by_name(self, name: str) -> SkillCatalogEntry | None:
        db = self.request.app.get("database")
        if db is None:
            return None
        try:
            async with await db.acquire() as conn:
                SkillCatalogEntry.Meta.connection = conn
                try:
                    return await SkillCatalogEntry.get(name=name)
                except NoDataFound:
                    return None
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to query skill by name '%s': %s", name, exc)
            return None

    async def _list_entries(self, **filters: Any) -> list[SkillCatalogEntry]:
        """Return catalog entries, optionally filtered by exact column match."""
        db = self.request.app.get("database")
        if db is None:
            raise RuntimeError("Database unavailable.")
        async with await db.acquire() as conn:
            SkillCatalogEntry.Meta.connection = conn
            entries = await SkillCatalogEntry.filter(**filters)
            return entries or []

    async def _insert_entry(self, entry: SkillCatalogEntry) -> None:
        db = self.request.app.get("database")
        if db is None:
            raise RuntimeError("Database unavailable.")
        async with await db.acquire() as conn:
            SkillCatalogEntry.Meta.connection = conn
            await entry.insert()

    async def _update_entry(self, entry: SkillCatalogEntry) -> None:
        db = self.request.app.get("database")
        if db is None:
            raise RuntimeError("Database unavailable.")
        async with await db.acquire() as conn:
            SkillCatalogEntry.Meta.connection = conn
            await entry.update()

    async def _delete_entry(self, entry: SkillCatalogEntry) -> None:
        db = self.request.app.get("database")
        if db is None:
            raise RuntimeError("Database unavailable.")
        async with await db.acquire() as conn:
            SkillCatalogEntry.Meta.connection = conn
            await entry.delete()

    @staticmethod
    def _entry_to_dict(entry: SkillCatalogEntry) -> dict:
        return {
            "skill_id": str(entry.skill_id),
            "name": entry.name,
            "description": entry.description,
            "category": entry.category,
            "owner": entry.owner,
            "triggers": list(entry.triggers or []),
            "body": entry.body,
            "version": entry.version,
            "status": entry.status,
            "search_index_stale": entry.search_index_stale,
        }

    def _error(self, message: str, *, status: int, code: str | None = None):
        return self.json_response(
            StudioError(message=message, code=code).model_dump(),
            status=status,
        )

    # -- database mode (StudioSkillCatalogService) -------------------------

    _dispatch = _StudioFilesMixin._dispatch

    async def _db_registry(self, part: Any):
        """The derived shared index of the partition (never under ``AGENTS_DIR``)."""
        return _sc._get_shared_skill_registry(self.request.app, await self._get_org_id(), part)

    async def _db_payload(self, *, lenient: bool = False):
        """The JSON body of a write (a dict), or the 400 response; ``expected_version`` is refused (§2.9).

        ``lenient`` treats an absent or invalid body as ``{}`` (the import route's optional body).
        """
        refused = self._refuse_expected_version(self.request.query)
        if refused is not None:
            return refused
        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            if lenient:
                return {}
            return self._error("Invalid JSON body.", status=400, code="invalid_json")
        payload = payload if isinstance(payload, dict) else {}
        refused = self._refuse_expected_version(payload)
        return payload if refused is None else refused

    async def _db_request(self):
        """The validated :class:`SkillPublishRequest` of a write, or an error response."""
        payload = await self._db_payload()
        if isinstance(payload, web.Response):
            return payload
        try:
            return SkillPublishRequest(**payload)
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

    async def _db_skill(self, storage: Any, part: Any, skill_id: str, *, manage: bool):
        """``(record, None)`` of a visible (manageable) skill, else ``(None, 404/403 response)``."""
        try:
            sid: UUID | None = UUID(str(skill_id))
        except ValueError:
            sid = None
        rec = await storage.services.skills.get(part, sid) if sid else None
        view = _store_record("skill", rec.skill_id, rec) if rec else None
        denied = await self._check_record_access(await self._access(), view, "skill", skill_id, manage=manage)
        return (None, denied) if denied is not None else (rec, None)

    async def _db_index(self, svc: Any, part: Any, rec: Any) -> Any:
        """Best-effort upload to the derived index; a failure flags ``search_index_stale`` and never raises."""
        return await index_published_skill(self.request.app, svc, part, rec, await self._get_org_id())
