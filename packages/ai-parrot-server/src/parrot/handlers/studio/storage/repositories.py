"""Agent Studio repositories (spec §2.5/§2.5a). Raw parametrised SQL over the host asyncdb pool."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator, Sequence

from asyncpg.exceptions import UniqueViolationError

from .models import (
    StudioAgentDefinition,
    StudioAgentHead,
    StudioAgentRecord,
    StudioAgentSnapshot,
    StudioAssetRecord,
    StudioNameConflict,
    StudioNotFound,
    StudioPartition,
    StudioStaleAuthorization,
    StudioStorageError,
    StudioToolingRecord,
    StudioVersionConflict,
    StudioWriteGuard,
)

logger = logging.getLogger("Parrot.AgentStudio.Storage")
NAVIGATOR_SCHEMA = "navigator"


@asynccontextmanager
async def studio_transaction(pool: Any) -> AsyncIterator[Any]:
    """The ONLY way repositories open a transaction (asyncdb pg: transaction()/commit()/rollback())."""
    async with pool.acquire() as conn:
        await conn.transaction()
        try:
            yield conn
        except BaseException:
            await conn.rollback()
            raise
        await conn.commit()


async def _exec(conn: Any, sql: str, *args: Any) -> Any:
    """conn.execute wrapper: raise StudioStorageError when asyncdb returns an error tuple.

    Caveat (asyncdb 2.16.2): ``pg.execute`` swallows unique / foreign-key / not-null violations and returns the
    previous statement's result with no error. Use it for DDL and statements that cannot violate those
    constraints; row writes that can (inserts, updates, deletes) go through ``_fetch_one`` with ``RETURNING``.
    """
    outcome = await conn.execute(sql, *args)
    if isinstance(outcome, (list, tuple)) and len(outcome) == 2:
        result, error = outcome
        if error:
            logger.error("studio statement failed: %s", error)
            raise StudioStorageError(str(error))
        return result
    return outcome


async def _fetch_all(conn: Any, sql: str, *args: Any) -> list[Any]:
    """conn.fetch_all wrapper normalising asyncdb's ``None`` (zero rows) to ``[]``."""
    rows = await conn.fetch_all(sql, *args)
    return list(rows or [])


async def _fetch_one(conn: Any, sql: str, *args: Any, conflict: bool = False) -> Any:
    """``conn.fetch_one`` with errors mapped to Studio errors.

    Unlike ``execute``, ``fetch_one`` raises on every violation (``ProviderError`` chained to the asyncpg error).
    With ``conflict=True`` a unique violation becomes ``StudioNameConflict``; anything else ``StudioStorageError``.
    """
    try:
        return await conn.fetch_one(sql, *args)
    except StudioStorageError:
        raise
    except Exception as exc:  # noqa: BLE001 — asyncdb wraps asyncpg errors in ProviderError/StatementError
        cause = exc.__cause__ or exc
        if conflict and isinstance(cause, UniqueViolationError):
            raise StudioNameConflict(str(cause)) from exc
        logger.error("studio statement failed: %s", exc)
        raise StudioStorageError(str(exc)) from exc


def _json(value: Any) -> Any:
    """Decode a json/jsonb value that the driver may hand back as text."""
    return json.loads(value) if isinstance(value, (str, bytes)) else value


def _when(value: Any) -> datetime:
    """Timestamps inside ``json_agg`` payloads arrive as ISO-8601 strings."""
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _agent_record(row: Any) -> StudioAgentRecord:
    """Map an ``ai_agents`` row (``_AGENT_COLS``) to a record."""
    return StudioAgentRecord(
        agent_id=row["agent_id"],
        tenant=row["tenant"],
        name=row["name"],
        owner=row["owner"],
        visibility=row["visibility"],
        allowed_groups=tuple(row["allowed_groups"] or ()),
        definition=StudioAgentDefinition.model_validate(_json(row["definition"])),
        status=row["status"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _snapshot(row: Any) -> StudioAgentSnapshot:
    """Map the one-statement snapshot row (agent columns + ``assets`` + ``tooling`` json arrays)."""
    agent_id = row["agent_id"]
    assets = tuple(
        StudioAssetRecord(agent_id=agent_id, **{**a, "updated_at": _when(a["updated_at"])})
        for a in _json(row["assets"])
    )
    tooling = tuple(
        StudioToolingRecord(agent_id=agent_id, **{**t, "updated_at": _when(t["updated_at"])})
        for t in _json(row["tooling"])
    )
    return StudioAgentSnapshot(record=_agent_record(row), assets=assets, tooling=tooling)


_AGENT_COLS = (
    "agent_id, tenant, name, owner, visibility, allowed_groups, definition, status, version, created_at, updated_at"
)
_A = f"{NAVIGATOR_SCHEMA}.ai_agents"
_SNAPSHOT_SQL = f"""
SELECT a.agent_id, a.tenant, a.name, a.owner, a.visibility, a.allowed_groups, a.definition, a.status,
       a.version, a.created_at, a.updated_at,
       COALESCE((SELECT json_agg(json_build_object(
                    'kind', s.kind, 'name', s.name, 'content', s.content, 'content_type', s.content_type,
                    'size', s.size, 'sha256', s.sha256, 'storage_uri', s.storage_uri, 'updated_at', s.updated_at)
                    ORDER BY s.kind, s.name)
                   FROM {NAVIGATOR_SCHEMA}.ai_agent_assets s WHERE s.agent_id = a.agent_id), '[]'::json) AS assets,
       COALESCE((SELECT json_agg(json_build_object(
                    'kind', t.kind, 'slug', t.slug, 'position', t.position, 'config', t.config,
                    'secret_refs', t.secret_refs, 'vault_owner', t.vault_owner, 'updated_at', t.updated_at)
                    ORDER BY t.kind, t.position, t.slug)
                   FROM {NAVIGATOR_SCHEMA}.ai_agent_tooling t WHERE t.agent_id = a.agent_id), '[]'::json) AS tooling
  FROM {_A} a
"""


class StudioAgentRepository:
    """Partitioned access to navigator.ai_agents (spec §2.5). Never encodes access policy."""

    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def get(self, part: StudioPartition, name: str) -> StudioAgentRecord | None:
        """The agent ``name`` of the partition, or None."""
        sql = f"SELECT {_AGENT_COLS} FROM {_A} WHERE tenant IS NOT DISTINCT FROM $1 AND name = $2"
        async with self.pool.acquire() as conn:
            row = await _fetch_one(conn, sql, part.tenant, name)
        return _agent_record(row) if row else None

    async def get_version(self, part: StudioPartition, name: str) -> StudioAgentHead | None:
        """Revalidation query (§2.6): id, version and status, no row lock."""
        sql = f"SELECT agent_id, version, status FROM {_A} WHERE tenant IS NOT DISTINCT FROM $1 AND name = $2"
        async with self.pool.acquire() as conn:
            row = await _fetch_one(conn, sql, part.tenant, name)
        return StudioAgentHead(row["agent_id"], row["version"], row["status"]) if row else None

    async def load_snapshot(self, part: StudioPartition, name: str) -> StudioAgentSnapshot | None:
        """ONE statement: row + json_agg(assets incl. content) + json_agg(tooling ORDER BY kind, position)."""
        sql = _SNAPSHOT_SQL + " WHERE a.tenant IS NOT DISTINCT FROM $1 AND a.name = $2"
        async with self.pool.acquire() as conn:
            row = await _fetch_one(conn, sql, part.tenant, name)
        return _snapshot(row) if row else None

    async def list(self, part: StudioPartition, *, owner: str | None = None) -> list[StudioAgentRecord]:
        """Every agent of the partition (optionally one owner's), ordered by name."""
        sql = f"SELECT {_AGENT_COLS} FROM {_A} WHERE tenant IS NOT DISTINCT FROM $1"
        args: list[Any] = [part.tenant]
        if owner is not None:
            sql += " AND owner = $2"
            args.append(owner)
        async with self.pool.acquire() as conn:
            rows = await _fetch_all(conn, sql + " ORDER BY name", *args)
        return [_agent_record(r) for r in rows]

    async def _lock_row(self, conn: Any, part: StudioPartition, name: str) -> StudioAgentHead | None:
        sql = (
            f"SELECT agent_id, version, status FROM {_A} "
            "WHERE tenant IS NOT DISTINCT FROM $1 AND name = $2 FOR UPDATE"
        )
        row = await _fetch_one(conn, sql, part.tenant, name)
        return StudioAgentHead(row["agent_id"], row["version"], row["status"]) if row else None

    async def lock(self, conn: Any, part: StudioPartition, name: str, guard: StudioWriteGuard) -> StudioAgentHead:
        """SELECT … FOR UPDATE, then NotFound → VersionConflict → StaleAuthorization (§2.5a order)."""
        head = await self._lock_row(conn, part, name)
        if head is None:
            raise StudioNotFound(name)
        if guard.expected_version is not None and guard.expected_version != head.version:
            raise StudioVersionConflict(f"{name}: expected {guard.expected_version}, found {head.version}")
        if guard.authorized_version is not None and guard.authorized_version != head.version:
            raise StudioStaleAuthorization(f"{name}: authorized {guard.authorized_version}, found {head.version}")
        return head

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
        """Insert an agent; ``StudioNameConflict`` on either unique index."""
        sql = (
            f"INSERT INTO {_A} (tenant, name, owner, visibility, allowed_groups, definition) "
            f"VALUES ($1, $2, $3, $4, $5, $6::text::jsonb) RETURNING {_AGENT_COLS}"
        )
        row = await _fetch_one(
            conn,
            sql,
            part.tenant,
            name,
            owner,
            visibility,
            list(allowed_groups),
            definition.model_dump_json(),
            conflict=True,
        )
        return _agent_record(row)

    async def _update(
        self, conn: Any, part: StudioPartition, name: str, assignments: str, *args: Any
    ) -> StudioAgentRecord:
        """Lock the row (no preconditions: services applied the guard), then UPDATE it by ``agent_id``."""
        head = await self.lock(conn, part, name, StudioWriteGuard())
        sql = f"UPDATE {_A} SET {assignments} WHERE agent_id = $1 RETURNING {_AGENT_COLS}"
        return _agent_record(await _fetch_one(conn, sql, head.agent_id, *args))

    async def update_definition(
        self, conn: Any, part: StudioPartition, name: str, definition: StudioAgentDefinition
    ) -> StudioAgentRecord:
        """Replace the stored definition."""
        return await self._update(conn, part, name, "definition = $2::text::jsonb", definition.model_dump_json())

    async def update_visibility(
        self, conn: Any, part: StudioPartition, name: str, *, visibility: str, allowed_groups: Sequence[str]
    ) -> StudioAgentRecord:
        """Replace visibility and allowed groups."""
        return await self._update(
            conn, part, name, "visibility = $2, allowed_groups = $3", visibility, list(allowed_groups)
        )

    async def set_status(self, conn: Any, part: StudioPartition, name: str, status: str) -> StudioAgentRecord:
        """Set ``active`` / ``disabled``."""
        return await self._update(conn, part, name, "status = $2", status)

    async def delete(self, conn: Any, part: StudioPartition, name: str) -> StudioAgentSnapshot | None:
        """Delete (cascading) and return what was deleted, or None when there was no such agent."""
        head = await self._lock_row(conn, part, name)
        if head is None:
            return None
        row = await _fetch_one(conn, _SNAPSHOT_SQL + " WHERE a.agent_id = $1", head.agent_id)
        await _fetch_one(conn, f"DELETE FROM {_A} WHERE agent_id = $1 RETURNING agent_id", head.agent_id)
        return _snapshot(row)
