"""In-memory draft and skill-catalogue repositories."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence
from uuid import UUID, uuid4

from ..models import (
    StudioAgentBundle,
    StudioAgentHead,
    StudioDraftRecord,
    StudioNotFound,
    StudioPartition,
    StudioSkillRecord,
    StudioStorageError,
    StudioWriteGuard,
)
from ._common import (
    _now,
    _check_shared,
    _Repo,
    _guard,
)


class _Drafts(_Repo):
    def _bump(self, rec: StudioDraftRecord, **changes: Any) -> StudioDraftRecord:
        return super()._bump("drafts", rec, **changes)

    def _need(self, part: StudioPartition, name: str) -> StudioDraftRecord:
        rec = self._find("drafts", part.tenant, name)
        if rec is None:
            raise StudioNotFound(name)
        return rec

    async def get(self, part: StudioPartition, name: str) -> StudioDraftRecord | None:
        return self._find("drafts", part.tenant, name)

    async def list(self, part: StudioPartition, *, owner: str | None = None) -> list[StudioDraftRecord]:
        rows = [
            r for r in self._s["drafts"].values() if r.tenant == part.tenant and (owner is None or r.owner == owner)
        ]
        return sorted(rows, key=lambda r: r.name)

    async def lock(self, conn: Any, part: StudioPartition, name: str, guard: StudioWriteGuard) -> StudioAgentHead:
        rec = self._need(part, name)
        return _guard(StudioAgentHead(rec.draft_id, rec.version, rec.status), name, guard)

    async def insert(
        self,
        conn: Any,
        part: StudioPartition,
        *,
        name: str,
        owner: str,
        bundle: StudioAgentBundle,
        visibility: str,
        allowed_groups: Sequence[str],
        validation: dict | None = None,
    ) -> StudioDraftRecord:
        _check_shared(part.tenant, name, visibility)
        self._unique("drafts", part.tenant, name)
        now = _now()
        rec = StudioDraftRecord(
            uuid4(),
            part.tenant,
            owner,
            name,
            visibility,
            tuple(allowed_groups),
            bundle,
            dict(validation or {}),
            "draft",
            1,
            None,
            now,
            now,
        )
        self._s["drafts"][rec.draft_id] = rec
        return rec

    async def update_bundle(
        self, conn: Any, part: StudioPartition, name: str, bundle: StudioAgentBundle, *, validation: dict | None = None
    ) -> StudioDraftRecord:
        rec = self._need(part, name)
        return self._bump(rec, bundle=bundle, validation=rec.validation if validation is None else dict(validation))

    async def set_status(
        self, conn: Any, part: StudioPartition, name: str, status: str, *, activated_agent_id: UUID | None = None
    ) -> StudioDraftRecord:
        rec = self._need(part, name)
        if status not in ("draft", "validated", "failed", "activated"):
            raise StudioStorageError(f"status {status!r} violates check constraint")
        if activated_agent_id is not None and activated_agent_id not in self._s["agents"]:
            raise StudioStorageError("foreign key violation: unknown agent")
        return self._bump(rec, status=status, activated_agent_id=activated_agent_id or rec.activated_agent_id)

    async def update_visibility(
        self, conn: Any, part: StudioPartition, name: str, *, visibility: str, allowed_groups: Sequence[str]
    ) -> StudioDraftRecord:
        rec = self._need(part, name)
        _check_shared(part.tenant, None, visibility)
        return self._bump(rec, visibility=visibility, allowed_groups=tuple(allowed_groups))

    async def delete(self, conn: Any, part: StudioPartition, name: str) -> bool:
        rec = self._find("drafts", part.tenant, name)
        if rec is None:
            return False
        del self._s["drafts"][rec.draft_id]
        return True


class _Skills(_Repo):
    def _by_id(self, part: StudioPartition, skill_id: UUID) -> StudioSkillRecord | None:
        rec = self._s["skills"].get(skill_id)
        return rec if rec is not None and rec.tenant == part.tenant else None

    def _bump(self, rec: StudioSkillRecord, **changes: Any) -> StudioSkillRecord:
        return super()._bump("skills", rec, **changes)

    async def get(self, part: StudioPartition, skill_id: UUID) -> StudioSkillRecord | None:
        return self._by_id(part, skill_id)

    async def get_by_name(self, part: StudioPartition, name: str) -> StudioSkillRecord | None:
        return self._find("skills", part.tenant, name)

    async def list(
        self, part: StudioPartition, *, category: str | None = None, owner: str | None = None
    ) -> list[StudioSkillRecord]:
        rows = [
            r
            for r in self._s["skills"].values()
            if r.tenant == part.tenant and category in (None, r.category) and owner in (None, r.owner)
        ]
        return sorted(rows, key=lambda r: r.name)

    async def insert(
        self,
        conn: Any,
        part: StudioPartition,
        *,
        owner: str,
        name: str,
        description: str,
        body: str,
        category: str = "general",
        triggers: Sequence[Any] = (),
        visibility: str = "private",
        allowed_groups: Sequence[str] = (),
        skill_id: UUID | None = None,
    ) -> StudioSkillRecord:
        _check_shared(part.tenant, name, visibility, slug_name=False)
        self._unique("skills", part.tenant, name)
        now = _now()
        rec = StudioSkillRecord(
            skill_id or uuid4(),
            part.tenant,
            owner,
            visibility,
            tuple(allowed_groups),
            name,
            description,
            category,
            list(triggers),
            body,
            1,
            "active",
            False,
            now,
            now,
        )
        self._s["skills"][rec.skill_id] = rec
        return rec

    async def update(
        self,
        conn: Any,
        part: StudioPartition,
        skill_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        category: str | None = None,
        triggers: Sequence[Any] | None = None,
        body: str | None = None,
        status: str | None = None,
    ) -> StudioSkillRecord | None:
        rec = self._by_id(part, skill_id)
        if rec is None:
            return None
        if name is not None:
            self._unique("skills", part.tenant, name, skip=skill_id)
        given = {
            "name": name,
            "description": description,
            "category": category,
            "body": body,
            "status": status,
            "triggers": None if triggers is None else list(triggers),
        }
        return self._bump(rec, **{k: v for k, v in given.items() if v is not None})

    async def update_visibility(
        self, conn: Any, part: StudioPartition, skill_id: UUID, *, visibility: str, allowed_groups: Sequence[str]
    ) -> StudioSkillRecord | None:
        rec = self._by_id(part, skill_id)
        if rec is None:
            return None
        _check_shared(part.tenant, None, visibility)
        return self._bump(rec, visibility=visibility, allowed_groups=tuple(allowed_groups))

    async def delete(self, conn: Any, part: StudioPartition, skill_id: UUID) -> bool:
        if self._by_id(part, skill_id) is None:
            return False
        del self._s["skills"][skill_id]
        return True

    async def mark_stale(self, conn: Any, part: StudioPartition, skill_id: UUID, stale: bool = True) -> bool:
        rec = self._by_id(part, skill_id)
        if rec is None:
            return False
        self._s["skills"][skill_id] = replace(rec, search_index_stale=stale)
        return True

    async def list_stale(self, part: StudioPartition) -> list[StudioSkillRecord]:
        return [r for r in await self.list(part) if r.search_index_stale]
