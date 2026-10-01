"""Agent Studio repositories (spec §2.5/§2.5a). Raw parametrised SQL over the host asyncdb pool."""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncIterator, Sequence
from uuid import UUID

from asyncpg.exceptions import UniqueViolationError

from .models import (
    StudioAgentDefinition,
    StudioAgentHead,
    StudioAgentRecord,
    StudioAgentSnapshot,
    StudioAssetInput,
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


async def _write(conn: Any, sql: str, *args: Any, conflict: bool = False) -> int:
    """Run an INSERT/UPDATE/DELETE (no RETURNING) through ``fetch_one`` so violations raise; returns row count."""
    row = await _fetch_one(conn, f"WITH w AS ({sql} RETURNING 1) SELECT count(*) AS n FROM w", *args, conflict=conflict)
    return int(row["n"])


_ASSET_COLS = "kind, name, content, content_type, size, sha256, storage_uri, updated_at"
_ASSET_COLS_NO_CONTENT = "kind, name, NULL::text AS content, content_type, size, sha256, storage_uri, updated_at"
_ASSET_COLS_J = ", ".join(
    f"c.{c}" for c in ("kind", "name", "content", "content_type", "size", "sha256", "storage_uri", "updated_at")
)
_ASSET_COLS_J_NO_CONTENT = _ASSET_COLS_J.replace("c.content,", "NULL::text AS content,")
_AS = f"{NAVIGATOR_SCHEMA}.ai_agent_assets"
_TOOLING_COLS = "kind, slug, position, config, secret_refs, vault_owner, updated_at"
_TOOLING_COLS_J = ", ".join(
    f"c.{c}" for c in ("kind", "slug", "position", "config", "secret_refs", "vault_owner", "updated_at")
)
_TS = f"{NAVIGATOR_SCHEMA}.ai_agent_tooling"


def _asset_row(agent_id: UUID, row: Any) -> StudioAssetRecord:
    return StudioAssetRecord(
        agent_id=agent_id,
        kind=row["kind"],
        name=row["name"],
        content=row["content"],
        content_type=row["content_type"],
        size=row["size"],
        sha256=row["sha256"],
        storage_uri=row["storage_uri"],
        updated_at=row["updated_at"],
    )


def _tooling_row(agent_id: UUID, row: Any) -> StudioToolingRecord:
    return StudioToolingRecord(
        agent_id=agent_id,
        kind=row["kind"],
        slug=row["slug"],
        position=row["position"],
        config=_json(row["config"]),
        secret_refs=_json(row["secret_refs"]),
        vault_owner=row["vault_owner"],
        updated_at=row["updated_at"],
    )


class StudioAssetRepository:
    """Assets of an agent. Partitioned reads join ``ai_agents``; writes take an ``agent_id`` from ``lock()``."""

    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def list(self, part: StudioPartition, agent_name: str, kind: str | None = None) -> list[StudioAssetRecord]:
        """Assets of the agent (content omitted: ``content=None``), ordered by (kind, name)."""
        sql = (
            f"SELECT a.agent_id, {_ASSET_COLS_J_NO_CONTENT} FROM {_AS} c "
            f"JOIN {_A} a ON a.agent_id = c.agent_id WHERE a.tenant IS NOT DISTINCT FROM $1 AND a.name = $2"
        )
        args: list[Any] = [part.tenant, agent_name]
        if kind is not None:
            sql += " AND c.kind = $3"
            args.append(kind)
        async with self.pool.acquire() as conn:
            rows = await _fetch_all(conn, sql + " ORDER BY c.kind, c.name", *args)
        return [_asset_row(r["agent_id"], r) for r in rows]

    async def get(self, part: StudioPartition, agent_name: str, kind: str, name: str) -> StudioAssetRecord | None:
        """One asset including its content, or None."""
        sql = (
            f"SELECT a.agent_id, {_ASSET_COLS_J} FROM {_AS} c JOIN {_A} a ON a.agent_id = c.agent_id "
            "WHERE a.tenant IS NOT DISTINCT FROM $1 AND a.name = $2 AND c.kind = $3 AND c.name = $4"
        )
        async with self.pool.acquire() as conn:
            row = await _fetch_one(conn, sql, part.tenant, agent_name, kind, name)
        return _asset_row(row["agent_id"], row) if row else None

    async def total_size(self, conn: Any, agent_id: UUID) -> int:
        """Sum of the agent's asset sizes (call under the agent lock: quota)."""
        row = await _fetch_one(
            conn, f"SELECT COALESCE(SUM(size), 0)::bigint AS n FROM {_AS} WHERE agent_id = $1", agent_id
        )
        return int(row["n"])

    async def put(self, conn: Any, agent_id: UUID, asset: StudioAssetInput, *, sha256: str) -> StudioAssetRecord:
        """Upsert one asset; ``size`` is computed in SQL so it always matches the CHECK."""
        sql = (
            f"INSERT INTO {_AS} (agent_id, kind, name, content, content_type, size, sha256) "
            "VALUES ($1, $2, $3, $4, $5, octet_length($4), $6) "
            "ON CONFLICT (agent_id, kind, name) DO UPDATE SET content = EXCLUDED.content, "
            "content_type = EXCLUDED.content_type, size = EXCLUDED.size, sha256 = EXCLUDED.sha256, "
            f"updated_at = now() RETURNING {_ASSET_COLS}"
        )
        row = await _fetch_one(conn, sql, agent_id, asset.kind, asset.name, asset.content, asset.content_type, sha256)
        return _asset_row(agent_id, row)

    async def delete(self, conn: Any, agent_id: UUID, kind: str, name: str) -> bool:
        """Delete one asset; True when it existed."""
        sql = f"DELETE FROM {_AS} WHERE agent_id = $1 AND kind = $2 AND name = $3"
        return await _write(conn, sql, agent_id, kind, name) > 0

    async def replace_all(self, conn: Any, agent_id: UUID, assets: Sequence[StudioAssetInput]) -> None:
        """Replace every asset of the agent with exactly ``assets`` (atomic within the caller's transaction)."""
        await _write(conn, f"DELETE FROM {_AS} WHERE agent_id = $1", agent_id)
        for asset in assets:
            digest = hashlib.sha256(asset.content.encode("utf-8")).hexdigest()
            await self.put(conn, agent_id, asset, sha256=digest)


class StudioToolingRepository:
    """Tooling (toolkits and MCP servers) of an agent."""

    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def list(self, part: StudioPartition, agent_name: str) -> list[StudioToolingRecord]:
        """Tooling rows of the agent ordered by (kind, position)."""
        sql = (
            f"SELECT a.agent_id, {_TOOLING_COLS_J} FROM {_TS} c JOIN {_A} a ON a.agent_id = c.agent_id "
            "WHERE a.tenant IS NOT DISTINCT FROM $1 AND a.name = $2 ORDER BY c.kind, c.position, c.slug"
        )
        async with self.pool.acquire() as conn:
            rows = await _fetch_all(conn, sql, part.tenant, agent_name)
        return [_tooling_row(r["agent_id"], r) for r in rows]

    async def list_locked(self, conn: Any, agent_id: UUID) -> list[StudioToolingRecord]:
        """Tooling rows read inside the caller's transaction, locked in (kind, slug) order."""
        sql = f"SELECT {_TOOLING_COLS} FROM {_TS} WHERE agent_id = $1 ORDER BY kind, slug FOR UPDATE"
        rows = await _fetch_all(conn, sql, agent_id)
        found = [_tooling_row(agent_id, r) for r in rows]
        return sorted(found, key=lambda r: (r.kind, r.position, r.slug))

    async def replace(
        self,
        conn: Any,
        agent_id: UUID,
        *,
        toolkits: Sequence[StudioToolingRecord],
        mcp_servers: Sequence[StudioToolingRecord],
    ) -> None:
        """Replace every tooling row with exactly the given ones; ``position`` is the list index."""
        await _write(conn, f"DELETE FROM {_TS} WHERE agent_id = $1", agent_id)
        sql = (
            f"INSERT INTO {_TS} (agent_id, kind, slug, position, config, secret_refs, vault_owner) "
            "VALUES ($1, $2, $3, $4, $5::text::jsonb, $6::text::jsonb, $7)"
        )
        for kind, records in (("toolkit", toolkits), ("mcp", mcp_servers)):
            for position, rec in enumerate(records):
                await _write(
                    conn,
                    sql,
                    agent_id,
                    kind,
                    rec.slug,
                    position,
                    json.dumps(rec.config),
                    json.dumps(rec.secret_refs),
                    rec.vault_owner,
                    conflict=True,
                )


@dataclass(frozen=True)
class StudioRepositories:
    """The five repositories sharing one pool."""

    pool: Any
    agents: StudioAgentRepository
    assets: StudioAssetRepository
    tooling: StudioToolingRepository
    drafts: "StudioDraftRepository"
    skills: "StudioSkillCatalogRepository"


def build_studio_repositories(pool: Any) -> StudioRepositories:
    """Build every repository over ``pool`` (the host's ``app["database"]``)."""
    from .catalog_repository import StudioSkillCatalogRepository
    from .draft_repository import StudioDraftRepository

    return StudioRepositories(
        pool,
        StudioAgentRepository(pool),
        StudioAssetRepository(pool),
        StudioToolingRepository(pool),
        StudioDraftRepository(pool),
        StudioSkillCatalogRepository(pool),
    )


def __getattr__(name: str) -> Any:
    """Lazy re-export (``draft_repository`` / ``catalog_repository`` import this module's helpers, so it cannot be imported eagerly)."""
    if name == "StudioSkillCatalogRepository":
        from .catalog_repository import StudioSkillCatalogRepository

        return StudioSkillCatalogRepository
    if name == "StudioDraftRepository":
        from .draft_repository import StudioDraftRepository

        return StudioDraftRepository
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
