"""Studio agent runtime (spec §2.6/§2.7/§2.7a). Instances live only in StudioRuntimeCache."""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

from navconfig import config

from parrot.auth.agent_guard import enforce_agent_access
from parrot.registry import agent_registry

from ..handlers.studio.storage.backend import ensure_studio_storage
from ..handlers.studio.storage.models import (
    StudioAgentKey,
    StudioAgentSnapshot,
    StudioNotFound,
    StudioPartition,
    StudioToolingRefused,
)
from ..handlers.studio.storage.repositories import StudioRepositories
from ..handlers.studio.storage.services._common import StudioToolingGate, studio_runtime_dir
from .manager import AgentNotFoundError, ReloadResult, cleanup_bot_instance
from .studio_builder import StudioAgentBuilder
from .studio_cache import StudioCacheEntry, StudioRuntimeCache

if TYPE_CHECKING:
    from aiohttp import web

    from parrot.bots.abstract import AbstractBot

    from .manager import BotManager

__all__ = [
    "StudioAgentBuilder",
    "StudioAgentRuntime",
    "StudioCacheEntry",
    "StudioRuntimeCache",
    "add_studio_runtime_hooks",
    "install_studio_runtime",
    "shutdown_studio_runtime",
]

logger = logging.getLogger("Parrot.AgentStudio.Storage")


def _float_setting(name: str, default: float) -> float:
    """A float setting from the environment/config; an unparsable value falls back to ``default`` (logged)."""
    raw = config.get(name)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.error("%s=%r is not a number; using %s", name, raw, default)
        return default


_HOOKS_KEY = "_astudio_runtime_hooks_installed"


class StudioAgentRuntime:
    """Revalidating, single-flight lookup of Studio agents over ``StudioRuntimeCache`` (spec §2.6/§2.7a)."""

    def __init__(
        self,
        manager: "BotManager",
        repos: StudioRepositories,
        builder: StudioAgentBuilder,
        *,
        revalidate_ttl: float = 0.0,
        session_ttl: float = 3600.0,
        idle_ttl: float = 3600.0,
        retire_grace: float = 300.0,
        sweep_interval: float = 60.0,
    ) -> None:
        self._manager, self._repos, self._builder = manager, repos, builder
        self._revalidate_ttl, self._session_ttl, self._idle_ttl = revalidate_ttl, session_ttl, idle_ttl
        self._grace, self._sweep_interval = retire_grace, sweep_interval
        self._cache = StudioRuntimeCache()
        self._locks: dict[str, asyncio.Lock] = {}
        self._validated: dict[str, float] = {}
        self._refused: set[tuple[Any, int]] = set()
        self._sweep_task: asyncio.Task | None = None
        self._stopped = False
        self.app: Any = None          # set by ``install_studio_runtime``; the builder's gate/policy source

    # ---- lookup -----------------------------------------------------------------------------------------------
    async def get(self, key: StudioAgentKey) -> "AbstractBot | None":
        """§2.6 steps 1–4: ``get_version`` → retire on missing/disabled → reuse on same ``(agent_id, version)`` →
        single-flight rebuild. A policy-refused build raises ``StudioToolingRefused`` (the agent is not served)."""
        entry = await self._base_entry(key)
        return entry.bot if entry else None

    async def get_session(self, key: StudioAgentKey, session_id: str) -> "AbstractBot | None":
        """The session instance (test chat): reused while ``(agent_id, version)`` is current, else built fresh."""
        entry = await self._session_entry(key, session_id)
        return entry.bot if entry else None

    @asynccontextmanager
    async def use(
        self, key: StudioAgentKey, *, session_id: str | None = None, request: "Optional[web.Request]" = None
    ) -> "AsyncIterator[AbstractBot]":
        """Same lookup, holding a lease for the block so the instance cannot be cleaned under the caller.

        PBAC runs before any build (the FEAT-153 ordering). Raises ``StudioNotFound`` for a missing/disabled agent.
        """
        await enforce_agent_access(self._manager.registry.evaluator, key.qualified, request)
        entry = await (self._session_entry(key, session_id) if session_id else self._base_entry(key))
        if entry is None:
            raise StudioNotFound(key.qualified)
        entry.leases += 1                     # no await since the lookup returned: the sweep cannot interleave
        try:
            yield entry.bot
        finally:
            entry.leases -= 1
            entry.last_used = time.monotonic()

    async def _base_entry(self, key: StudioAgentKey) -> StudioCacheEntry | None:
        qualified, now = key.qualified, time.monotonic()
        cached = self._cache.current(qualified)
        if cached and self._revalidate_ttl > 0 and now - self._validated.get(qualified, -1e18) < self._revalidate_ttl:
            return self._touch(cached, now)
        head = await self._repos.agents.get_version(StudioPartition(key.tenant), key.name)
        if head is None or head.status == "disabled":
            self._retire_key(key)
            return None
        if cached and (cached.agent_id, cached.version) == (head.agent_id, head.version):
            self._validated[qualified] = now
            return self._touch(cached, now)
        async with self._lock(qualified):
            cached = self._cache.current(qualified)
            if cached and cached.agent_id == head.agent_id and cached.version >= head.version:
                return self._touch(cached, time.monotonic())            # a concurrent caller built it (single flight)
            return await self._build_and_install(key, None)

    async def _session_entry(self, key: StudioAgentKey, session_id: str) -> StudioCacheEntry | None:
        qualified, now = key.qualified, time.monotonic()
        head = await self._repos.agents.get_version(StudioPartition(key.tenant), key.name)
        existing = self._cache.session(qualified, session_id)
        if head is None or head.status == "disabled":
            if existing:
                self._cache.retire(existing, now=now)
            return None
        if existing and (existing.agent_id, existing.version) == (head.agent_id, head.version):
            existing.expires_at = now + self._session_ttl
            return self._touch(existing, now)
        async with self._lock(f"{qualified}\0{session_id}"):
            existing = self._cache.session(qualified, session_id)
            if existing and existing.agent_id == head.agent_id and existing.version >= head.version:
                return self._touch(existing, time.monotonic())
            return await self._build_and_install(key, session_id)

    # ---- build / retire ---------------------------------------------------------------------------------------
    async def _build_and_install(self, key: StudioAgentKey, session_id: str | None) -> StudioCacheEntry | None:
        """Load ONE snapshot, build from it and install; the replaced entry is retired, never cleaned here."""
        part = StudioPartition(key.tenant)
        snapshot = await self._repos.agents.load_snapshot(part, key.name)
        if snapshot is None:
            self._retire_key(key)
            return None
        bot, directory = await self._build(snapshot, part)
        rec, now = snapshot.record, time.monotonic()
        entry = StudioCacheEntry(
            qualified=key.qualified, session_id=session_id, agent_id=rec.agent_id, version=rec.version, bot=bot,
            asset_dir=directory, expires_at=None if session_id is None else now + self._session_ttl, last_used=now,
        )
        self._cache.acquire_dir(rec.agent_id, rec.version)
        replaced = self._cache.install(entry)
        if session_id is None:
            self._validated[key.qualified] = now
        if replaced is not None:
            logger.debug("studio %s: v%s replaces v%s (retired)", key.qualified, rec.version, replaced.version)
        return entry

    async def _build(self, snapshot: StudioAgentSnapshot, part: StudioPartition) -> tuple["AbstractBot", Any]:
        """Build; a policy refusal is logged ONCE per ``(agent_id, version)`` and re-raised."""
        rec = snapshot.record
        try:
            return await self._builder.build(snapshot, self._app(), part=part)
        except StudioToolingRefused as exc:
            if (rec.agent_id, rec.version) not in self._refused:
                self._refused.add((rec.agent_id, rec.version))
                logger.warning("studio %s v%s refused at build: %s", rec.name, rec.version, exc)
            raise

    def _app(self) -> Any:
        return self.app or getattr(self._manager, "app", None) or {}

    def _retire_key(self, key: StudioAgentKey) -> None:
        """Retire the base entry and every session entry of ``key`` (row missing, disabled or replaced)."""
        now = time.monotonic()
        for entry in self._cache.all_entries():
            if entry.qualified == key.qualified and entry.retired_at is None:
                self._cache.retire(entry, now=now)
        self._validated.pop(key.qualified, None)

    def _touch(self, entry: StudioCacheEntry, now: float) -> StudioCacheEntry:
        entry.last_used = now
        return entry

    def _lock(self, name: str) -> asyncio.Lock:
        return self._locks.setdefault(name, asyncio.Lock())

    # ---- admin ------------------------------------------------------------------------------------------------
    async def reload(self, key: StudioAgentKey) -> ReloadResult:
        """Forced rebuild from the current row; the previous instance is retired (cleaned after the grace)."""
        if await self._repos.agents.get_version(StudioPartition(key.tenant), key.name) is None:
            raise AgentNotFoundError(key.name)
        async with self._lock(key.qualified):
            had_previous = self._cache.current(key.qualified) is not None
            entry = await self._build_and_install(key, None)
        if entry is None:
            raise AgentNotFoundError(key.name)
        warnings = ["previous instance retired; it is cleaned after the grace period"] if had_previous else []
        return ReloadResult(name=key.name, reloaded=True, previous_instance_closed=False, warnings=warnings)

    def evict(self, key: StudioAgentKey) -> None:
        """Retire the agent's entries (base and sessions). Never cleans immediately: leases may be held."""
        self._retire_key(key)

    # ---- lifecycle --------------------------------------------------------------------------------------------
    async def start(self) -> None:
        """Create the runtime root directory and the sweep task."""
        self._builder.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._stopped = False
        if self._sweep_task is None or self._sweep_task.done():
            self._sweep_task = asyncio.create_task(self._sweep_loop(), name="studio-runtime-sweep")

    async def _sweep_loop(self) -> None:
        while not self._stopped:
            await asyncio.sleep(self._sweep_interval)
            try:
                await self.sweep()
            except Exception:  # noqa: BLE001 — the sweep must never die
                logger.exception("studio runtime sweep failed")

    async def sweep(self, now: float | None = None) -> int:
        """One pass: clean sessions past TTL, retire idle base entries, clean retired entries past the grace
        with no lease. Returns the number of entries cleaned."""
        now = time.monotonic() if now is None else now
        due = self._cache.reclaimable(now=now, grace=self._grace, session_ttl=self._session_ttl, idle_ttl=self._idle_ttl)
        for entry in due:
            await self._clean(entry)
        live = {e.qualified for e in self._cache.all_entries()}
        self._locks = {k: v for k, v in self._locks.items() if v.locked() or k.split("\0")[0] in live}
        return len(due)

    async def _clean(self, entry: StudioCacheEntry) -> None:
        """Clean one entry exactly once (identity guard: ``cleaned``), then drop its asset directory if last user."""
        if entry.cleaned:
            return
        self._cache.mark_cleaned(entry)
        await cleanup_bot_instance(entry.bot, label=f"{entry.qualified}@v{entry.version}")
        if self._cache.release_dir(entry.agent_id, entry.version) and entry.asset_dir is not None:
            shutil.rmtree(entry.asset_dir, ignore_errors=True)

    async def shutdown(self) -> None:
        """Stop the sweep, clean EVERY entry not yet cleaned (leases ignored), remove the runtime root."""
        self._stopped = True
        task, self._sweep_task = self._sweep_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for entry in self._cache.all_entries():
            await self._clean(entry)
        shutil.rmtree(self._builder.runtime_dir, ignore_errors=True)


def add_studio_runtime_hooks(app: "web.Application") -> None:
    """Append the runtime start/stop hooks once per app (guard ``_astudio_runtime_hooks_installed``)."""
    if app.get(_HOOKS_KEY):
        return
    app[_HOOKS_KEY] = True
    app.on_startup.append(install_studio_runtime)
    app.on_cleanup.append(shutdown_studio_runtime)


async def install_studio_runtime(app: "web.Application") -> None:
    """``on_startup``: resolve storage FIRST (X8); when it is ``database`` build and start the runtime."""
    storage = await ensure_studio_storage(app)
    if storage.backend != "database" or storage.repos is None:
        return
    manager = app["bot_manager"]
    builder = StudioAgentBuilder(
        getattr(manager, "registry", None) or agent_registry, studio_runtime_dir(), StudioToolingGate(app)
    )
    runtime = StudioAgentRuntime(
        manager,
        storage.repos,
        builder,
        revalidate_ttl=_float_setting("STUDIO_REVALIDATE_TTL_SECONDS", 0.0),
        session_ttl=_float_setting("STUDIO_SESSION_TTL_SECONDS", 3600.0),
        idle_ttl=_float_setting("STUDIO_IDLE_TTL_SECONDS", 3600.0),
        retire_grace=_float_setting("STUDIO_RETIRE_GRACE_SECONDS", 300.0),
        sweep_interval=_float_setting("STUDIO_SWEEP_INTERVAL_SECONDS", 60.0),
    )
    runtime.app = app
    manager.studio = runtime
    await runtime.start()


async def shutdown_studio_runtime(app: "web.Application") -> None:
    """``on_cleanup``: stop and clean the runtime when one was installed. Needs no database."""
    runtime = getattr(app.get("bot_manager"), "studio", None)
    if runtime is not None:
        await runtime.shutdown()
