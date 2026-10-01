"""In-memory Studio repositories with the same invariants and signals as Postgres (spec §2.5). Tests only.

Enforces UNIQUE(tenant, name) (tenant NULL included), the CHECKs, version bumps (child writes included) and the write
guards; absent rows give None/False/[]. Concurrency is only tested on Postgres.
"""

from __future__ import annotations

import copy
import hashlib
import re
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID, uuid4

from .models import (
    StudioAgentBundle,
    StudioAgentDefinition,
    StudioAgentHead,
    StudioAgentRecord,
    StudioAgentSnapshot,
    StudioAssetInput,
    StudioAssetRecord,
    StudioDraftRecord,
    StudioNameConflict,
    StudioNotFound,
    StudioPartition,
    StudioSkillRecord,
    StudioStaleAuthorization,
    StudioStorageError,
    StudioToolingRecord,
    StudioVersionConflict,
    StudioWriteGuard,
)

_NAME_RE = re.compile(r"^[a-z0-9_-]{1,64}$")
_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
_VISIBILITY = ("private", "tenant", "groups")
_ASSET_HARD_CAP = 1048576


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _check_shared(tenant: str | None, name: str | None, visibility: str, *, slug_name: bool = True) -> None:
    """The CHECK constraints every Studio table shares."""
    if visibility not in _VISIBILITY:
        raise StudioStorageError(f"visibility {visibility!r} violates check constraint")
    if tenant is not None and not _TENANT_RE.match(tenant):
        raise StudioStorageError(f"tenant {tenant!r} violates check constraint")
    if tenant is None and visibility != "private":
        raise StudioStorageError("shared visibility needs a tenant (check constraint)")
    if slug_name and name is not None and not _NAME_RE.match(name):
        raise StudioStorageError(f"name {name!r} violates check constraint")


class _MemoryConn:
    """Satisfies ``studio_transaction``: ``transaction()`` snapshots the state, ``rollback()`` restores it."""

    def __init__(self, store: "InMemoryStudioRepositories") -> None:
        self._store = store
        self._saved: Any = None

    async def transaction(self) -> "_MemoryConn":
        self._saved = copy.deepcopy(self._store._state)
        return self

    async def commit(self) -> None:
        self._saved = None

    async def rollback(self) -> None:
        if self._saved is not None:
            self._store._state = self._saved
            self._saved = None


class _MemoryPool:
    """Pool double: ``acquire()`` yields a connection bound to the store."""

    def __init__(self, store: "InMemoryStudioRepositories") -> None:
        self._store = store

    @asynccontextmanager
    async def acquire(self):
        yield _MemoryConn(self._store)


class _Repo:
    def __init__(self, store: "InMemoryStudioRepositories") -> None:
        self._store = store

    @property
    def _s(self) -> dict[str, Any]:
        return self._store._state

    def _find(self, table: str, tenant: str | None, name: str) -> Any:
        return next((r for r in self._s[table].values() if r.tenant == tenant and r.name == name), None)

    def _bump(self, table: str, rec: Any, **changes: Any) -> Any:
        new = replace(rec, version=rec.version + 1, updated_at=_now(), **changes)
        self._s[table][getattr(rec, _ID[table])] = new
        return new

    def _unique(self, table: str, tenant: str | None, name: str, *, skip: Any = None) -> None:
        other = self._find(table, tenant, name)
        if other is not None and getattr(other, _ID[table]) != skip:
            raise StudioNameConflict(f"{table}: {name!r} already exists in partition {tenant!r}")


_ID = {"agents": "agent_id", "drafts": "draft_id", "skills": "skill_id"}


def _guard(head: StudioAgentHead, name: str, guard: StudioWriteGuard) -> StudioAgentHead:
    if guard.expected_version is not None and guard.expected_version != head.version:
        raise StudioVersionConflict(f"{name}: expected {guard.expected_version}, found {head.version}")
    if guard.authorized_version is not None and guard.authorized_version != head.version:
        raise StudioStaleAuthorization(f"{name}: authorized {guard.authorized_version}, found {head.version}")
    return head


class _Agents(_Repo):
    def _put(self, rec: StudioAgentRecord, **changes: Any) -> StudioAgentRecord:
        return self._bump("agents", rec, **changes)

    def touch(self, agent_id: UUID) -> None:
        """A child row write bumps the parent version (the DB touch trigger)."""
        rec = self._s["agents"].get(agent_id)
        if rec is not None:
            self._put(rec)

    async def get(self, part: StudioPartition, name: str) -> StudioAgentRecord | None:
        return self._find("agents", part.tenant, name)

    async def get_version(self, part: StudioPartition, name: str) -> StudioAgentHead | None:
        rec = self._find("agents", part.tenant, name)
        return StudioAgentHead(rec.agent_id, rec.version, rec.status) if rec else None

    def _snapshot(self, rec: StudioAgentRecord) -> StudioAgentSnapshot:
        assets = [a for k, a in self._s["assets"].items() if k[0] == rec.agent_id]
        tooling = [t for k, t in self._s["tooling"].items() if k[0] == rec.agent_id]
        return StudioAgentSnapshot(
            record=rec,
            assets=tuple(sorted(assets, key=lambda a: (a.kind, a.name))),
            tooling=tuple(sorted(tooling, key=lambda t: (t.kind, t.position, t.slug))),
        )

    async def load_snapshot(self, part: StudioPartition, name: str) -> StudioAgentSnapshot | None:
        rec = self._find("agents", part.tenant, name)
        return self._snapshot(copy.deepcopy(rec)) if rec else None

    async def list(self, part: StudioPartition, *, owner: str | None = None) -> list[StudioAgentRecord]:
        rows = [
            r for r in self._s["agents"].values() if r.tenant == part.tenant and (owner is None or r.owner == owner)
        ]
        return sorted(rows, key=lambda r: r.name)

    async def lock(self, conn: Any, part: StudioPartition, name: str, guard: StudioWriteGuard) -> StudioAgentHead:
        rec = self._find("agents", part.tenant, name)
        if rec is None:
            raise StudioNotFound(name)
        return _guard(StudioAgentHead(rec.agent_id, rec.version, rec.status), name, guard)

    async def insert(
        self,
        conn: Any,
        part: StudioPartition,
        *,
        name: str,
        owner: str,
        definition: StudioAgentDefinition,
        visibility: str,
        allowed_groups: Sequence[str],
    ) -> StudioAgentRecord:
        _check_shared(part.tenant, name, visibility)
        self._unique("agents", part.tenant, name)
        now = _now()
        rec = StudioAgentRecord(
            uuid4(), part.tenant, name, owner, visibility, tuple(allowed_groups), definition, "active", 1, now, now
        )
        self._s["agents"][rec.agent_id] = rec
        return rec

    async def _update(self, part: StudioPartition, name: str, **changes: Any) -> StudioAgentRecord:
        rec = self._find("agents", part.tenant, name)
        if rec is None:
            raise StudioNotFound(name)
        return self._put(rec, **changes)

    async def update_definition(
        self, conn: Any, part: StudioPartition, name: str, definition: StudioAgentDefinition
    ) -> StudioAgentRecord:
        return await self._update(part, name, definition=definition)

    async def update_visibility(
        self, conn: Any, part: StudioPartition, name: str, *, visibility: str, allowed_groups: Sequence[str]
    ) -> StudioAgentRecord:
        _check_shared(part.tenant, None, visibility)
        return await self._update(part, name, visibility=visibility, allowed_groups=tuple(allowed_groups))

    async def set_status(self, conn: Any, part: StudioPartition, name: str, status: str) -> StudioAgentRecord:
        if status not in ("active", "disabled"):
            raise StudioStorageError(f"status {status!r} violates check constraint")
        return await self._update(part, name, status=status)

    async def delete(self, conn: Any, part: StudioPartition, name: str) -> StudioAgentSnapshot | None:
        rec = self._find("agents", part.tenant, name)
        if rec is None:
            return None
        snap = self._snapshot(rec)
        del self._s["agents"][rec.agent_id]
        for table in ("assets", "tooling"):
            for key in [k for k in self._s[table] if k[0] == rec.agent_id]:
                del self._s[table][key]
        for key, draft in list(self._s["drafts"].items()):
            if draft.activated_agent_id == rec.agent_id:
                self._s["drafts"][key] = replace(draft, activated_agent_id=None)
        return copy.deepcopy(snap)


class _Assets(_Repo):
    def _agent(self, part: StudioPartition, agent_name: str) -> StudioAgentRecord | None:
        return self._find("agents", part.tenant, agent_name)

    async def list(self, part: StudioPartition, agent_name: str, kind: str | None = None) -> list[StudioAssetRecord]:
        agent = self._agent(part, agent_name)
        if agent is None:
            return []
        rows = [a for k, a in self._s["assets"].items() if k[0] == agent.agent_id and kind in (None, a.kind)]
        return [replace(a, content=None) for a in sorted(rows, key=lambda a: (a.kind, a.name))]

    async def get(self, part: StudioPartition, agent_name: str, kind: str, name: str) -> StudioAssetRecord | None:
        agent = self._agent(part, agent_name)
        return self._s["assets"].get((agent.agent_id, kind, name)) if agent else None

    async def total_size(self, conn: Any, agent_id: UUID) -> int:
        return sum(a.size for k, a in self._s["assets"].items() if k[0] == agent_id)

    async def put(self, conn: Any, agent_id: UUID, asset: StudioAssetInput, *, sha256: str) -> StudioAssetRecord:
        size = len(asset.content.encode("utf-8"))
        if asset.kind not in ("identity", "kb", "skills") or asset.name.startswith("/") or ".." in asset.name:
            raise StudioStorageError(f"asset {asset.kind}/{asset.name} violates check constraint")
        if size > _ASSET_HARD_CAP or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise StudioStorageError("asset violates check constraint")
        if agent_id not in self._s["agents"]:
            raise StudioStorageError("foreign key violation: unknown agent")
        rec = StudioAssetRecord(
            agent_id, asset.kind, asset.name, asset.content, asset.content_type, size, sha256, None, _now()
        )
        self._s["assets"][(agent_id, asset.kind, asset.name)] = rec
        self._store.agents.touch(agent_id)
        return rec

    async def delete(self, conn: Any, agent_id: UUID, kind: str, name: str) -> bool:
        if self._s["assets"].pop((agent_id, kind, name), None) is None:
            return False
        self._store.agents.touch(agent_id)
        return True

    async def replace_all(self, conn: Any, agent_id: UUID, assets: Sequence[StudioAssetInput]) -> None:
        for key in [k for k in self._s["assets"] if k[0] == agent_id]:
            del self._s["assets"][key]
            self._store.agents.touch(agent_id)
        for asset in assets:
            digest = hashlib.sha256(asset.content.encode("utf-8")).hexdigest()
            await self.put(conn, agent_id, asset, sha256=digest)


class _Tooling(_Repo):
    def _rows(self, agent_id: UUID) -> list[StudioToolingRecord]:
        rows = [t for k, t in self._s["tooling"].items() if k[0] == agent_id]
        return sorted(rows, key=lambda t: (t.kind, t.position, t.slug))

    async def list(self, part: StudioPartition, agent_name: str) -> list[StudioToolingRecord]:
        agent = self._find("agents", part.tenant, agent_name)
        return self._rows(agent.agent_id) if agent else []

    async def list_locked(self, conn: Any, agent_id: UUID) -> list[StudioToolingRecord]:
        return self._rows(agent_id)

    async def replace(
        self,
        conn: Any,
        agent_id: UUID,
        *,
        toolkits: Sequence[StudioToolingRecord],
        mcp_servers: Sequence[StudioToolingRecord],
    ) -> None:
        for key in [k for k in self._s["tooling"] if k[0] == agent_id]:
            del self._s["tooling"][key]
            self._store.agents.touch(agent_id)
        for kind, records in (("toolkit", toolkits), ("mcp", mcp_servers)):
            for position, rec in enumerate(records):
                if (agent_id, kind, rec.slug) in self._s["tooling"]:
                    raise StudioNameConflict(f"duplicate tooling {kind}/{rec.slug}")
                self._s["tooling"][(agent_id, kind, rec.slug)] = replace(
                    rec, agent_id=agent_id, kind=kind, position=position, updated_at=_now()
                )
                self._store.agents.touch(agent_id)


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


class InMemoryStudioRepositories:
    """Same method set as the five repositories; usable wherever a ``StudioRepositories`` is."""

    def __init__(self) -> None:
        self._state: dict[str, Any] = {"agents": {}, "assets": {}, "tooling": {}, "drafts": {}, "skills": {}}
        self.pool = _MemoryPool(self)
        self.agents = _Agents(self)
        self.assets = _Assets(self)
        self.tooling = _Tooling(self)
        self.drafts = _Drafts(self)
        self.skills = _Skills(self)
