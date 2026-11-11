"""User store backend selection and Redis client primitives."""

from __future__ import annotations

import asyncio
import logging
import weakref
from dataclasses import dataclass
from typing import Literal, cast

import redis.asyncio as aioredis
from navconfig import config

logger = logging.getLogger("parrot.userstore")

StoreBackend = Literal["redis", "documentdb", "postgres"]
GLOBAL_SWITCH: str = "PARROT_USER_STORE"
DEFAULT_BACKEND: StoreBackend = "redis"
CREW_RESULT_SWITCH: str = "CREW_RESULT_STORAGE"
_GLOBAL_ALLOWED = frozenset({"redis", "documentdb"})
_WITH_POSTGRES = frozenset({"redis", "documentdb", "postgres"})


class UserStoreMisconfigured(RuntimeError):
    """A user-store backend setting is invalid or would silently switch DocumentDB to Redis."""


@dataclass(frozen=True)
class StoreSwitch:
    """One per-store switch, its collections, and its allowed backend values."""

    name: str
    collections: tuple[str, ...]
    allowed: frozenset[str]


SWITCHES: dict[str, StoreSwitch] = {
    switch.name: switch
    for switch in (
        StoreSwitch("VAULT_STORE", ("user_credentials",), _WITH_POSTGRES),
        StoreSwitch("BYOK_STORE", ("user_llm_keys",), _WITH_POSTGRES),
        StoreSwitch("TOOLKIT_OVERRIDES_STORE", ("user_toolkit_configs",), _WITH_POSTGRES),
        StoreSwitch("MCP_CONFIGS_STORE", ("user_mcp_configs",), _GLOBAL_ALLOWED),
        StoreSwitch("TELEGRAM_MCP_STORE", ("telegram_user_mcp_configs",), _GLOBAL_ALLOWED),
        StoreSwitch("INTEGRATIONS_STORE", ("users_integrations",), _GLOBAL_ALLOWED),
        StoreSwitch("DASHBOARDS_STORE", ("dashboards", "dashboard_tabs"), _GLOBAL_ALLOWED),
    )
}


def _read(key: str) -> str:
    """Return the normalized call-time value of ``key``, or an empty string."""
    return str(config.get(key, fallback="") or "").strip().lower()


def _invalid_value(switch: str, allowed: frozenset[str]) -> UserStoreMisconfigured:
    """Build an error without exposing the configured value."""
    return UserStoreMisconfigured(f"{switch} must be one of: {', '.join(sorted(allowed))}")


def resolve_store_backend(switch: str) -> StoreBackend:
    """Resolve a store's backend from its switch, the global switch, then the Redis default.

    Args:
        switch: Name of a switch in :data:`SWITCHES`.

    Raises:
        KeyError: If ``switch`` is unknown.
        UserStoreMisconfigured: If a configured value is not allowed.
    """
    spec = SWITCHES[switch]
    configured = _read(switch)
    if configured:
        if configured not in spec.allowed:
            raise _invalid_value(switch, spec.allowed)
        return cast(StoreBackend, configured)

    configured = _read(GLOBAL_SWITCH)
    if configured:
        if configured not in _GLOBAL_ALLOWED:
            raise _invalid_value(GLOBAL_SWITCH, _GLOBAL_ALLOWED)
        return cast(StoreBackend, configured)
    return DEFAULT_BACKEND


def store_backend_source(switch: str) -> Literal["switch", "global", "default"]:
    """Return which configuration level decides ``resolve_store_backend(switch)``."""
    SWITCHES[switch]
    if _read(switch):
        return "switch"
    if _read(GLOBAL_SWITCH):
        return "global"
    return "default"


def documentdb_configured() -> bool:
    """Return whether either DocumentDB configuration value is set."""
    return bool(config.get("DOCUMENTDB_HOSTNAME") or config.get("DOCUMENTDB_DBNAME"))


def implicit_redis_stores() -> list[str]:
    """Return stores which resolve to Redis solely because their settings are unset."""
    stores = [
        name
        for name in SWITCHES
        if store_backend_source(name) == "default" and resolve_store_backend(name) == DEFAULT_BACKEND
    ]
    if not _read(CREW_RESULT_SWITCH) and not _read(GLOBAL_SWITCH):
        stores.append(CREW_RESULT_SWITCH)
    return stores


def validate_user_store_settings() -> dict[str, StoreBackend]:
    """Resolve all switches and reject implicit Redis defaults on a DocumentDB installation."""
    resolved = {name: resolve_store_backend(name) for name in SWITCHES}
    implicit_stores = implicit_redis_stores()
    if documentdb_configured() and implicit_stores:
        stores = ", ".join(implicit_stores)
        raise UserStoreMisconfigured(
            f"DocumentDB is configured but these stores default to Redis: {stores}. "
            "Set PARROT_USER_STORE=documentdb to keep MongoDB, or set PARROT_USER_STORE=redis "
            "to move; run `python -m parrot.userstore.copy` first."
        )
    return resolved


def default_result_storage() -> Literal["redis", "documentdb"]:
    """Return the global result backend, or Redis when no global backend is configured."""
    configured = _read(GLOBAL_SWITCH)
    if configured:
        if configured not in _GLOBAL_ALLOWED:
            raise _invalid_value(GLOBAL_SWITCH, _GLOBAL_ALLOWED)
        return cast(Literal["redis", "documentdb"], configured)
    return DEFAULT_BACKEND


def redis_url() -> str:
    """Return the explicit Redis URL or the user-store database-six URL."""
    explicit = str(config.get("PARROT_USER_STORE_REDIS_URL", fallback="") or "").strip()
    if explicit:
        return explicit
    host = config.get("REDIS_HOST", fallback="localhost")
    port = config.get("REDIS_PORT", fallback=6379)
    db = config.get("PARROT_USER_STORE_REDIS_DB", fallback=6)
    return f"redis://{host}:{port}/{db}"


def key_prefix() -> str:
    """Return the user-store key prefix without a trailing colon."""
    return str(config.get("PARROT_USER_STORE_REDIS_PREFIX", fallback="parrot:us") or "parrot:us").rstrip(":")


_CLIENTS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, aioredis.Redis] = weakref.WeakKeyDictionary()


def get_user_store_redis() -> aioredis.Redis:
    """Return the lazy, response-decoding Redis client for the current event loop."""
    loop = asyncio.get_running_loop()
    client = _CLIENTS.get(loop)
    if client is None:
        client = aioredis.from_url(redis_url(), decode_responses=True)
        _CLIENTS[loop] = client
    return client


async def close_user_store_redis() -> None:
    """Close and forget the Redis client associated with the current event loop."""
    client = _CLIENTS.pop(asyncio.get_running_loop(), None)
    if client is not None:
        await client.aclose()
