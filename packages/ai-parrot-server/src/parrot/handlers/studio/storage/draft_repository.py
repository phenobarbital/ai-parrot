"""Agent Studio draft repository (spec §2.5): partitioned, guarded access to ``navigator.ai_agent_drafts``."""

from __future__ import annotations

import json
from typing import Any, Sequence
from uuid import UUID

from .models import (
    StudioAgentBundle,
    StudioAgentHead,
    StudioDraftRecord,
    StudioNotFound,
    StudioPartition,
    StudioWriteGuard,
)
from .repositories import NAVIGATOR_SCHEMA, _conn_or_acquire, _fetch_all, _fetch_one, _json, _write

_DRAFT_COLS = (
    "draft_id, tenant, owner, name, visibility, allowed_groups, definition, validation, status, version, "
    "activated_agent_id, created_at, updated_at"
)
_D = f"{NAVIGATOR_SCHEMA}.ai_agent_drafts"


def _draft_record(row: Any) -> StudioDraftRecord:
    return StudioDraftRecord(
        draft_id=row["draft_id"],
        tenant=row["tenant"],
        owner=row["owner"],
        name=row["name"],
        visibility=row["visibility"],
        allowed_groups=tuple(row["allowed_groups"] or ()),
        bundle=StudioAgentBundle.model_validate(_json(row["definition"])),
        validation=_json(row["validation"]) or {},
        status=row["status"],
        version=row["version"],
        activated_agent_id=row["activated_agent_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class StudioDraftRepository:
    """Partitioned access to navigator.ai_agent_drafts; ``definition`` holds a ``StudioAgentBundle`` dump."""

    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def get(self, part: StudioPartition, name: str, *, conn: Any | None = None) -> StudioDraftRecord | None:
        """The draft ``name`` of the partition, or None. Pass ``conn`` to read inside an open transaction."""
        sql = f"SELECT {_DRAFT_COLS} FROM {_D} WHERE tenant IS NOT DISTINCT FROM $1 AND name = $2"
        async with _conn_or_acquire(self.pool, conn) as c:
            row = await _fetch_one(c, sql, part.tenant, name)
        return _draft_record(row) if row else None

    async def list(self, part: StudioPartition, *, owner: str | None = None) -> list[StudioDraftRecord]:
        """Every draft of the partition (optionally one owner's), ordered by name."""
        sql = f"SELECT {_DRAFT_COLS} FROM {_D} WHERE tenant IS NOT DISTINCT FROM $1"
        args: list[Any] = [part.tenant]
        if owner is not None:
            sql += " AND owner = $2"
            args.append(owner)
        async with self.pool.acquire() as conn:
            rows = await _fetch_all(conn, sql + " ORDER BY name", *args)
        return [_draft_record(r) for r in rows]

    async def _lock_row(self, conn: Any, part: StudioPartition, name: str) -> StudioAgentHead | None:
        sql = (
            f"SELECT draft_id, version, status FROM {_D} "
            "WHERE tenant IS NOT DISTINCT FROM $1 AND name = $2 FOR UPDATE"
        )
        row = await _fetch_one(conn, sql, part.tenant, name)
        return StudioAgentHead(row["draft_id"], row["version"], row["status"]) if row else None

    async def lock(self, conn: Any, part: StudioPartition, name: str, guard: StudioWriteGuard) -> StudioAgentHead:
        """FOR UPDATE + guard (NotFound → VersionConflict → StaleAuthorization). ``agent_id`` carries the draft id."""
        head = await self._lock_row(conn, part, name)
        if head is None:
            raise StudioNotFound(name)
        return guard.check(head, name)

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
        """Insert a draft; ``StudioNameConflict`` on either unique index."""
        sql = (
            f"INSERT INTO {_D} (tenant, name, owner, visibility, allowed_groups, definition, validation) "
            f"VALUES ($1, $2, $3, $4, $5, $6::text::jsonb, $7::text::jsonb) RETURNING {_DRAFT_COLS}"
        )
        row = await _fetch_one(
            conn,
            sql,
            part.tenant,
            name,
            owner,
            visibility,
            list(allowed_groups),
            json.dumps(bundle.model_dump(mode="json")),
            json.dumps(validation or {}),
            conflict=True,
        )
        return _draft_record(row)

    async def _update(
        self, conn: Any, part: StudioPartition, name: str, assignments: str, *args: Any
    ) -> StudioDraftRecord:
        head = await self.lock(conn, part, name, StudioWriteGuard())
        sql = f"UPDATE {_D} SET {assignments} WHERE draft_id = $1 RETURNING {_DRAFT_COLS}"
        return _draft_record(await _fetch_one(conn, sql, head.agent_id, *args))

    async def update_bundle(
        self, conn: Any, part: StudioPartition, name: str, bundle: StudioAgentBundle, *, validation: dict | None = None
    ) -> StudioDraftRecord:
        """Replace the bundle (and the validation report when given)."""
        return await self._update(
            conn,
            part,
            name,
            "definition = $2::text::jsonb, validation = COALESCE($3::text::jsonb, validation)",
            json.dumps(bundle.model_dump(mode="json")),
            None if validation is None else json.dumps(validation),
        )

    async def set_status(
        self, conn: Any, part: StudioPartition, name: str, status: str, *, activated_agent_id: UUID | None = None
    ) -> StudioDraftRecord:
        """Set the status; ``activated_agent_id`` is stamped when given and otherwise left unchanged."""
        return await self._update(
            conn,
            part,
            name,
            "status = $2, activated_agent_id = COALESCE($3, activated_agent_id)",
            status,
            activated_agent_id,
        )

    async def update_visibility(
        self, conn: Any, part: StudioPartition, name: str, *, visibility: str, allowed_groups: Sequence[str]
    ) -> StudioDraftRecord:
        """Replace visibility and allowed groups."""
        return await self._update(
            conn, part, name, "visibility = $2, allowed_groups = $3", visibility, list(allowed_groups)
        )

    async def delete(self, conn: Any, part: StudioPartition, name: str) -> bool:
        """Delete the draft; True when it existed."""
        head = await self._lock_row(conn, part, name)
        if head is None:
            return False
        return await _write(conn, f"DELETE FROM {_D} WHERE draft_id = $1", head.agent_id) > 0
