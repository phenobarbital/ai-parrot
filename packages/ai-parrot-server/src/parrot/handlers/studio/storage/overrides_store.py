"""Per-user toolkit overrides in Postgres (spec §2.10, M12): ``TOOLKIT_OVERRIDES_STORE=postgres``."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ...toolkit_persistence import UserToolkitOverride, set_toolkit_override_store
from .repositories import _fetch_all, _fetch_one, _json

logger = logging.getLogger("Parrot.AgentStudio.Storage")

_COLUMNS = "user_id, agent_ref, slug, params, secret_refs, updated_at"
_PUT_SQL = (
    "INSERT INTO navigator.ai_user_toolkit_overrides (user_id, agent_ref, slug, params, secret_refs, updated_at) "
    "VALUES ($1, $2, $3, $4::text::jsonb, $5::text::jsonb, $6) "
    "ON CONFLICT (user_id, agent_ref, slug) DO UPDATE SET params = EXCLUDED.params, "
    "secret_refs = EXCLUDED.secret_refs, updated_at = EXCLUDED.updated_at RETURNING slug"
)
_LOAD_SQL = f"SELECT {_COLUMNS} FROM navigator.ai_user_toolkit_overrides WHERE user_id = $1 AND agent_ref = $2"
_DELETE_SQL = (
    "DELETE FROM navigator.ai_user_toolkit_overrides WHERE user_id = $1 AND agent_ref = $2 AND slug = $3 "
    "RETURNING slug"
)
_PURGE_SQL = f"DELETE FROM navigator.ai_user_toolkit_overrides WHERE agent_ref = $1 RETURNING {_COLUMNS}"
_REVISION_SQL = (
    "SELECT max(updated_at) AS revision FROM navigator.ai_user_toolkit_overrides WHERE user_id = $1 AND agent_ref = $2"
)


def _timestamp(value: str) -> datetime:
    """The override's ISO ``updated_at`` as an aware datetime (now when it does not parse)."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _override(row: Any) -> UserToolkitOverride:
    return UserToolkitOverride(
        user_id=row["user_id"],
        agent_id=row["agent_ref"],
        slug=row["slug"],
        params=_json(row["params"]) or {},
        secret_refs=_json(row["secret_refs"]) or {},
        updated_at=row["updated_at"].isoformat(),
    )


class PgToolkitOverrideStore:
    """``ToolkitConfigService`` methods over the host pool; ``agent_id`` is the ``agent_ref`` column (X3/X17)."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def save(self, override: UserToolkitOverride) -> None:
        """Upsert one override keyed ``(user_id, agent_ref, slug)``."""
        dumped = override.model_dump(mode="json")
        async with self._pool.acquire() as conn:
            await _fetch_one(
                conn, _PUT_SQL, override.user_id, override.agent_id, override.slug,
                json.dumps(dumped["params"]), json.dumps(dumped["secret_refs"]), _timestamp(override.updated_at),
            )

    async def load(self, user_id: str, agent_id: str) -> list[UserToolkitOverride]:
        """Every override of one user on one agent reference."""
        async with self._pool.acquire() as conn:
            rows = await _fetch_all(conn, _LOAD_SQL, user_id, agent_id)
        return [_override(row) for row in rows]

    async def remove(self, user_id: str, agent_id: str, slug: str) -> bool:
        """Delete an override; ``True`` when it existed."""
        async with self._pool.acquire() as conn:
            return await _fetch_one(conn, _DELETE_SQL, user_id, agent_id, slug) is not None

    async def purge_agent(self, agent_ref: str) -> list[UserToolkitOverride]:
        """Delete every user's override for ``agent_ref`` in one statement and return them (spec §2.5c clean-up)."""
        async with self._pool.acquire() as conn:
            rows = await _fetch_all(conn, _PURGE_SQL, agent_ref)
        return [_override(row) for row in rows]

    async def revision(self, user_id: str, agent_id: str) -> str:
        """Latest override timestamp, or an empty string when none exist."""
        async with self._pool.acquire() as conn:
            row = await _fetch_one(conn, _REVISION_SQL, user_id, agent_id)
        latest = row["revision"] if row is not None else None
        return latest.isoformat() if latest is not None else ""


def register_override_store(store: "PgToolkitOverrideStore | None") -> None:
    """Called by the server at startup when TOOLKIT_OVERRIDES_STORE=postgres; read by ``ToolkitConfigService``."""
    set_toolkit_override_store(store)


_REGISTERED: "PgToolkitOverrideStore | None" = None


def get_override_store(pool: Any) -> PgToolkitOverrideStore:
    """The store over ``pool``, registered with ``ToolkitConfigService`` (reused while the pool is unchanged)."""
    global _REGISTERED
    store = _REGISTERED
    if store is None or store._pool is not pool:
        store = _REGISTERED = PgToolkitOverrideStore(pool)
    register_override_store(store)
    return store
