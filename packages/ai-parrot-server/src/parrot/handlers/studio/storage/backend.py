"""Studio storage backend selection (spec §2.2, §2.7a)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from aiohttp import web
from navconfig import config

from . import migrate
from .models import StudioPartition, StudioStorageUnavailable
from .repositories import StudioRepositories, build_studio_repositories

logger = logging.getLogger("Parrot.AgentStudio.Storage")
STUDIO_STORAGE_APP_KEY = "studio_storage"
_LOCK_KEY = "_astudio_storage_lock"
_SETTINGS = ("auto", "database", "filesystem")


@dataclass
class StudioStorage:
    """The resolved backend. ``reason`` is logged, never returned to clients."""

    backend: Literal["database", "filesystem", "unavailable"]
    reason: str | None = None
    repos: StudioRepositories | None = None
    app: Any = field(default=None, repr=False)
    _services: Any = field(default=None, repr=False)

    def require_for(self, part: StudioPartition) -> None:
        """Raise ``StudioStorageUnavailable`` when this partition cannot be served by the backend."""
        if self.backend == "unavailable" or (self.backend != "database" and part.tenant is not None):
            raise StudioStorageUnavailable(self.reason or self.backend)

    @property
    def services(self) -> Any:
        """Lazily built service container (database backend only)."""
        if self.backend != "database":
            return None
        if self._services is None:
            from .services import build_studio_services  # W2 (TASK-3933); lazy by design

            self._services = build_studio_services(self.app, self.repos)
        return self._services


def _read_setting() -> str:
    value = str(config.get("PARROT_STUDIO_STORAGE", fallback="auto") or "auto").strip().lower()
    if value not in _SETTINGS:
        logger.error("PARROT_STUDIO_STORAGE=%r is not one of %s; using 'auto'", value, _SETTINGS)
        return "auto"
    return value


async def _probe(pool: Any) -> migrate.LedgerState | Exception:
    """Read-only probe; a failure is returned (not raised) so the caller maps it to ``unavailable``."""
    try:
        async with pool.acquire() as conn:
            return await migrate.read_ledger(conn)
    except Exception as exc:  # noqa: BLE001 — any probe failure means the DB cannot be trusted
        return exc


_STORE_SWITCHES = ("VAULT_STORE", "TOOLKIT_OVERRIDES_STORE", "BYOK_STORE")
_PG_STORES_KEY = "_astudio_pg_stores"


class StudioStorageMisconfigured(RuntimeError):
    """A ``*_STORE=postgres`` switch is on but the Studio backend is not ``database`` (fail closed at startup)."""


def _postgres_switches() -> list[str]:
    """The phase-2 store switches currently set to ``postgres``."""
    return [
        key for key in _STORE_SWITCHES
        if str(config.get(key, fallback="documentdb") or "documentdb").strip().lower() == "postgres"
    ]


def _fail_closed(backend: str, reason: str | None) -> None:
    """Raise when a Postgres store switch is on and the backend cannot serve it (never fall back to DocumentDB)."""
    switches = _postgres_switches()
    if switches and backend != "database":
        raise StudioStorageMisconfigured(
            f"{', '.join(switches)}=postgres requires the Studio storage backend 'database', "
            f"but it resolved to {backend!r} ({reason})"
        )


def _register_postgres_stores(app: Any, pool: Any) -> None:
    """Hand every Postgres store whose switch is ``postgres`` to core, remembering them on ``app`` for cleanup."""
    switches = _postgres_switches()
    held: dict[str, Any] = {}
    if "VAULT_STORE" in switches:
        from .vault_store import get_vault_store  # lazy: pulls in the vault keyring machinery

        held["vault"] = get_vault_store(pool)
    if "TOOLKIT_OVERRIDES_STORE" in switches:
        from .overrides_store import get_override_store

        held["overrides"] = get_override_store(pool)
    if "BYOK_STORE" in switches:
        from .byok_store import install_byok_store

        held["byok"] = install_byok_store(app, pool)
    app[_PG_STORES_KEY] = held


async def release_studio_stores(app: web.Application) -> None:
    """``on_cleanup``: drop this app's process-global store registrations (only those still pointing at its stores)."""
    held = app.pop(_PG_STORES_KEY, None) or {}
    from .byok_store import release_byok_store
    from .overrides_store import release_override_store
    from .vault_store import release_vault_store

    release_vault_store(held.get("vault"))
    release_override_store(held.get("overrides"))
    release_byok_store(held.get("byok"))


def install_studio_storage_cleanup(app: web.Application) -> None:
    """Install :func:`release_studio_stores` once per app. Called by ``add_studio_runtime_hooks`` (BotManager
    ``setup()`` / ``setup_registry_only()``) and ``setup_studio_routes``, which is also what runs the startup resolve."""
    from .. import install_startup_hook_once

    install_startup_hook_once(app, release_studio_stores, signal="on_cleanup")


def _resolve(setting: str, pool: Any, state: migrate.LedgerState | Exception | None) -> tuple[str, str | None]:
    """Pure mapping of (setting, pool, probe result) to (backend, reason) — spec §2.2 matrix."""
    if setting == "filesystem":
        return "filesystem", "PARROT_STUDIO_STORAGE=filesystem"
    if pool is None:
        if setting == "auto":
            return "filesystem", "no database pool"
        return "unavailable", "PARROT_STUDIO_STORAGE=database but no database pool"
    if isinstance(state, Exception):
        return "unavailable", f"schema probe failed: {state!r}"
    if state.server_version_num < migrate.STUDIO_MIN_SERVER_VERSION_NUM:
        return "unavailable", f"PostgreSQL >= 14 required (server_version_num={state.server_version_num})"
    manifest = {m.version: m.checksum for m in migrate.list_migrations()}
    if not state.present:
        if setting == "auto":
            return "filesystem", "studio schema not migrated"
        return "unavailable", "PARROT_STUDIO_STORAGE=database but the studio schema is not migrated"
    problems = state.problems(migrate.STUDIO_SCHEMA_REQUIRED, manifest)
    if problems:
        return "unavailable", "studio schema incomplete or drifted: " + "; ".join(problems)
    return "database", None


async def ensure_studio_storage(app: web.Application) -> StudioStorage:
    """Idempotent, lock-guarded, memoised on ``app[STUDIO_STORAGE_APP_KEY]``; runs the §2.2 probe once."""
    lock = app.setdefault(_LOCK_KEY, asyncio.Lock())
    async with lock:
        existing = app.get(STUDIO_STORAGE_APP_KEY)
        if existing is not None:
            return existing
        setting = _read_setting()
        pool = app.get("database")
        state = await _probe(pool) if pool is not None and setting != "filesystem" else None
        backend, reason = _resolve(setting, pool, state)
        if backend == "unavailable":
            logger.error("Studio storage unavailable: %s", reason)
        elif backend == "filesystem" and setting == "auto":
            logger.warning("Studio storage: using the filesystem backend (%s)", reason)
        else:
            logger.info("Studio storage backend: %s", backend)
        _fail_closed(backend, reason)  # raises before anything is memoised: a retry fails the same way
        repos = build_studio_repositories(pool) if backend == "database" else None
        if backend == "database":
            _register_postgres_stores(app, pool)
        storage = StudioStorage(backend, reason, repos, app)  # type: ignore[arg-type]
        app[STUDIO_STORAGE_APP_KEY] = storage
        return storage


async def resolve_studio_storage(app: web.Application) -> None:
    """``on_startup`` wrapper."""
    await ensure_studio_storage(app)
