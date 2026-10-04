"""Agent Studio skills-catalogue repository (spec §2.5): partitioned access to ``navigator.ai_skills_catalog``.

Catalogue writes never take a client ``expected_version`` (spec §2.9). The table has no version trigger, so every
write bumps ``version`` and ``updated_at`` here.
"""

from __future__ import annotations

import json
from typing import Any, Sequence
from uuid import UUID

from .models import StudioPartition, StudioSkillRecord
from .repositories import NAVIGATOR_SCHEMA, _fetch_all, _fetch_one, _json

_SKILL_COLS = (
    "skill_id, tenant, owner, visibility, allowed_groups, name, description, category, triggers, body, version, "
    "status, search_index_stale, created_at, updated_at"
)
_C = f"{NAVIGATOR_SCHEMA}.ai_skills_catalog"
_PART = "tenant IS NOT DISTINCT FROM $1"


def _skill_record(row: Any) -> StudioSkillRecord:
    return StudioSkillRecord(
        skill_id=row["skill_id"],
        tenant=row["tenant"],
        owner=row["owner"],
        visibility=row["visibility"],
        allowed_groups=tuple(row["allowed_groups"] or ()),
        name=row["name"],
        description=row["description"],
        category=row["category"],
        triggers=list(_json(row["triggers"]) or []),
        body=row["body"],
        version=row["version"],
        status=row["status"],
        search_index_stale=bool(row["search_index_stale"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class StudioSkillCatalogRepository:
    """Partitioned CRUD over the skills catalogue (no ``StudioWriteGuard``)."""

    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def get(self, part: StudioPartition, skill_id: UUID) -> StudioSkillRecord | None:
        """The skill ``skill_id`` of the partition, or None."""
        sql = f"SELECT {_SKILL_COLS} FROM {_C} WHERE {_PART} AND skill_id = $2"
        async with self.pool.acquire() as conn:
            row = await _fetch_one(conn, sql, part.tenant, skill_id)
        return _skill_record(row) if row else None

    async def get_by_name(self, part: StudioPartition, name: str) -> StudioSkillRecord | None:
        """The skill called ``name`` in the partition, or None."""
        sql = f"SELECT {_SKILL_COLS} FROM {_C} WHERE {_PART} AND name = $2"
        async with self.pool.acquire() as conn:
            row = await _fetch_one(conn, sql, part.tenant, name)
        return _skill_record(row) if row else None

    async def list(
        self, part: StudioPartition, *, category: str | None = None, owner: str | None = None
    ) -> list[StudioSkillRecord]:
        """Skills of the partition, optionally filtered, ordered by name."""
        sql = f"SELECT {_SKILL_COLS} FROM {_C} WHERE {_PART}"
        args: list[Any] = [part.tenant]
        for column, value in (("category", category), ("owner", owner)):
            if value is not None:
                args.append(value)
                sql += f" AND {column} = ${len(args)}"
        async with self.pool.acquire() as conn:
            rows = await _fetch_all(conn, sql + " ORDER BY name", *args)
        return [_skill_record(r) for r in rows]

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
        """Insert a skill; ``StudioNameConflict`` on either unique index. ``skill_id`` defaults to a new UUID."""
        sql = (
            f"INSERT INTO {_C} (skill_id, tenant, owner, visibility, allowed_groups, name, description, category, "
            "triggers, body) VALUES (COALESCE($1, gen_random_uuid()), $2, $3, $4, $5, $6, $7, $8, "
            f"$9::text::jsonb, $10) RETURNING {_SKILL_COLS}"
        )
        row = await _fetch_one(
            conn,
            sql,
            skill_id,
            part.tenant,
            owner,
            visibility,
            list(allowed_groups),
            name,
            description,
            category,
            json.dumps(list(triggers)),
            body,
            conflict=True,
        )
        return _skill_record(row)

    async def _update(
        self, conn: Any, part: StudioPartition, skill_id: UUID, assignments: str, *args: Any, conflict: bool = False
    ) -> StudioSkillRecord | None:
        sql = (
            f"UPDATE {_C} SET {assignments}, version = version + 1, updated_at = now() "
            f"WHERE {_PART} AND skill_id = $2 RETURNING {_SKILL_COLS}"
        )
        row = await _fetch_one(conn, sql, part.tenant, skill_id, *args, conflict=conflict)
        return _skill_record(row) if row else None

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
        """Update the given fields (None = unchanged); returns the new record, or None when absent."""
        return await self._update(
            conn,
            part,
            skill_id,
            "name = COALESCE($3, name), description = COALESCE($4, description), category = COALESCE($5, category), "
            "triggers = COALESCE($6::text::jsonb, triggers), body = COALESCE($7, body), status = COALESCE($8, status)",
            name,
            description,
            category,
            None if triggers is None else json.dumps(list(triggers)),
            body,
            status,
            conflict=True,
        )

    async def update_visibility(
        self, conn: Any, part: StudioPartition, skill_id: UUID, *, visibility: str, allowed_groups: Sequence[str]
    ) -> StudioSkillRecord | None:
        """Replace visibility and allowed groups; None when absent."""
        return await self._update(
            conn, part, skill_id, "visibility = $3, allowed_groups = $4", visibility, list(allowed_groups)
        )

    async def delete(self, conn: Any, part: StudioPartition, skill_id: UUID) -> bool:
        """Delete the skill; True when it existed."""
        sql = f"DELETE FROM {_C} WHERE {_PART} AND skill_id = $2 RETURNING skill_id"
        return await _fetch_one(conn, sql, part.tenant, skill_id) is not None

    async def mark_stale(self, conn: Any, part: StudioPartition, skill_id: UUID, stale: bool = True) -> bool:
        """Set ``search_index_stale``; True when the skill exists. Does not bump ``version``."""
        sql = f"UPDATE {_C} SET search_index_stale = $3 WHERE {_PART} AND skill_id = $2 RETURNING skill_id"
        return await _fetch_one(conn, sql, part.tenant, skill_id, stale) is not None

    async def list_stale(self, part: StudioPartition) -> list[StudioSkillRecord]:
        """Skills of the partition whose search index needs a refresh."""
        sql = f"SELECT {_SKILL_COLS} FROM {_C} WHERE {_PART} AND search_index_stale ORDER BY name"
        async with self.pool.acquire() as conn:
            rows = await _fetch_all(conn, sql, part.tenant)
        return [_skill_record(r) for r in rows]
