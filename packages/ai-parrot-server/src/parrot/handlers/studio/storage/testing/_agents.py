"""In-memory agent, asset and tooling repositories."""

from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import replace
from typing import Any, Sequence
from uuid import UUID, uuid4

from ..models import (
    StudioAgentDefinition,
    StudioAgentHead,
    StudioAgentRecord,
    StudioAgentSnapshot,
    StudioAssetInput,
    StudioAssetRecord,
    StudioNameConflict,
    StudioNotFound,
    StudioPartition,
    StudioStorageError,
    StudioToolingRecord,
    StudioWriteGuard,
)
from ._common import (
    _ASSET_HARD_CAP,
    _now,
    _check_shared,
    _Repo,
    _guard,
)


class _Agents(_Repo):
    def _put(self, rec: StudioAgentRecord, **changes: Any) -> StudioAgentRecord:
        return self._bump("agents", rec, **changes)

    def touch(self, agent_id: UUID) -> None:
        """A child row write bumps the parent version (the DB touch trigger)."""
        rec = self._s["agents"].get(agent_id)
        if rec is not None:
            self._put(rec)

    async def get(self, part: StudioPartition, name: str, *, conn: Any | None = None) -> StudioAgentRecord | None:
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

    async def get(
        self, part: StudioPartition, agent_name: str, kind: str, name: str, *, conn: Any | None = None
    ) -> StudioAssetRecord | None:
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
