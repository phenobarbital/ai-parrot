"""Studio agent runtime (spec §2.6/§2.7/§2.7a). Instances live only in StudioRuntimeCache."""

from __future__ import annotations

import asyncio
import logging
import contextlib
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

from navconfig import config

from parrot.auth.agent_guard import enforce_agent_access
from parrot.registry import agent_registry

from ..handlers.studio.storage.backend import ensure_studio_storage, install_studio_storage_cleanup
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
_REFUSED_CAP = 1024


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
        max_sessions: int = 1000,
    ) -> None:
        self._manager, self._repos, self._builder = manager, repos, builder
        self._revalidate_ttl, self._session_ttl, self._idle_ttl = revalidate_ttl, session_ttl, idle_ttl
        self._grace, self._sweep_interval = retire_grace, sweep_interval
        self._cache = StudioRuntimeCache()
        self._locks: dict[str, asyncio.Lock] = {}
        self._validated: dict[str, float] = {}
        self._refused: dict[tuple[Any, int], None] = {}      # bounded log-once memory (insertion ordered)
        self._max_sessions = max_sessions
        self._dirs: set[Path] = set()                         # version directories THIS runtime created
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

    async def _head(self, key: StudioAgentKey) -> Any:
        """The revalidation row (§2.6 step 1), or None when the agent is missing or disabled."""
        head = await self._repos.agents.get_version(StudioPartition(key.tenant), key.name)
        return None if head is None or head.status == "disabled" else head

    @staticmethod
    def _current_for(entry: StudioCacheEntry | None, head: Any) -> bool:
        """The entry is exactly the row's ``(agent_id, version)``."""
        return entry is not None and (entry.agent_id, entry.version) == (head.agent_id, head.version)

    @staticmethod
    def _built_for(entry: StudioCacheEntry | None, head: Any) -> bool:
        """The entry belongs to the row's agent and is at least as new as the row (a concurrent build won)."""
        return entry is not None and entry.agent_id == head.agent_id and entry.version >= head.version

    def _within_ttl(self, entry: StudioCacheEntry | None, qualified: str, now: float) -> bool:
        if entry is None or self._revalidate_ttl <= 0:
            return False
        return now - self._validated.get(qualified, -1e18) < self._revalidate_ttl

    async def _base_entry(self, key: StudioAgentKey) -> StudioCacheEntry | None:
        qualified, now = key.qualified, time.monotonic()
        cached = self._cache.current(qualified)
        if self._within_ttl(cached, qualified, now):
            return self._touch(cached, now)
        head = await self._head(key)
        if head is None:
            self._retire_key(key)
            return None
        if self._current_for(cached, head):
            self._validated[qualified] = now
            return self._touch(cached, now)
        async with self._lock(qualified):
            again = self._cache.current(qualified)
            if self._built_for(again, head):
                return self._touch(again, time.monotonic())            # a concurrent caller built it (single flight)
            return await self._build_and_install(key, None)

    async def _session_entry(self, key: StudioAgentKey, session_id: str) -> StudioCacheEntry | None:
        qualified, now = key.qualified, time.monotonic()
        head = await self._head(key)
        existing = self._cache.session(qualified, session_id)
        if head is None:
            if existing:
                self._cache.retire(existing, now=now)
            return None
        if self._current_for(existing, head):
            existing.expires_at = now + self._session_ttl
            return self._touch(existing, now)
        async with self._lock(f"{qualified}\0{session_id}"):
            again = self._cache.session(qualified, session_id)
            if self._built_for(again, head):
                return self._touch(again, time.monotonic())
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
        rec = snapshot.record
        self._cache.acquire_dir(rec.agent_id, rec.version)
        self._dirs.add(directory)
        head = await self._head(key)                  # the agent may have been disabled/replaced while we built
        if head is None or head.agent_id != rec.agent_id:
            await self._discard_unserved(key, bot, rec, directory)
            return None
        now = time.monotonic()
        entry = StudioCacheEntry(
            qualified=key.qualified, session_id=session_id, agent_id=rec.agent_id, version=rec.version, bot=bot,
            asset_dir=directory, expires_at=None if session_id is None else now + self._session_ttl, last_used=now,
        )
        replaced = self._cache.install(entry)
        if session_id is None:
            self._validated[key.qualified] = now
        else:
            self._enforce_session_cap(entry, now)
        if replaced is not None:
            logger.debug("studio %s: v%s replaces v%s (retired)", key.qualified, rec.version, replaced.version)
        return entry

    async def _discard_unserved(self, key: StudioAgentKey, bot: "AbstractBot", rec: Any, directory: Path) -> None:
        """A finished build nobody may use (agent disabled/deleted meanwhile): clean it and release its directory."""
        self._retire_key(key)
        await cleanup_bot_instance(bot, label=f"{key.qualified}@v{rec.version}")
        if self._cache.release_dir(rec.agent_id, rec.version):
            await self._rmtree(directory)

    def _enforce_session_cap(self, new: StudioCacheEntry, now: float) -> None:
        """Retire the least recently used unleased sessions beyond ``max_sessions`` (cleaned by the sweep)."""
        sessions = self._cache.live_sessions()
        for old in sessions:
            if len(sessions) <= self._max_sessions:
                break
            if old is not new and old.leases == 0:
                self._cache.retire(old, now=now)
                sessions.remove(old)

    async def _build(self, snapshot: StudioAgentSnapshot, part: StudioPartition) -> tuple["AbstractBot", Any]:
        """Build; a policy refusal is logged ONCE per ``(agent_id, version)`` and re-raised."""
        rec = snapshot.record
        try:
            return await self._builder.build(snapshot, self._app(), part=part)
        except StudioToolingRefused as exc:
            if (rec.agent_id, rec.version) not in self._refused:
                self._refused[(rec.agent_id, rec.version)] = None
                while len(self._refused) > _REFUSED_CAP:
                    self._refused.pop(next(iter(self._refused)))
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

    def evict_session(self, key: StudioAgentKey, session_id: str) -> bool:
        """Retire ONE session entry (test chat teardown); the base entry and other sessions are untouched.

        Never cleans immediately (a lease may be held). Returns whether a live session entry was retired.
        """
        entry = self._cache.session(key.qualified, session_id)
        if entry is None:
            return False
        self._cache.retire(entry, now=time.monotonic())
        return True

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
        for entry in due:                       # synchronously, BEFORE the first await: no lookup can return them now
            self._cache.retire(entry, now=now)
        cleaned = 0
        for entry in due:
            cleaned += await self._clean(entry)
        live = {e.qualified for e in self._cache.all_entries()}
        self._locks = {k: v for k, v in self._locks.items() if v.locked() or k.split("\0")[0] in live}
        return cleaned

    async def _clean(self, entry: StudioCacheEntry, *, force: bool = False) -> int:
        """Clean one entry exactly once (identity guard: ``cleaned``); a leased entry is skipped unless ``force``
        (shutdown). Returns 1 when cleaned, else 0."""
        if entry.cleaned or (entry.leases > 0 and not force):
            return 0
        self._cache.mark_cleaned(entry)
        await cleanup_bot_instance(entry.bot, label=f"{entry.qualified}@v{entry.version}")
        if self._cache.release_dir(entry.agent_id, entry.version) and entry.asset_dir is not None:
            await self._rmtree(entry.asset_dir)
        return 1

    async def _rmtree(self, directory: Path) -> None:
        """Remove one version directory off the event loop, then its agent directory when that is now empty."""
        self._dirs.discard(directory)
        await asyncio.to_thread(_remove_dir, directory)

    async def shutdown(self) -> None:
        """Stop the sweep, clean EVERY entry not yet cleaned (leases ignored) and remove ONLY the directories this
        runtime created; the shared root goes away only when it is empty."""
        self._stopped = True
        task, self._sweep_task = self._sweep_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for entry in self._cache.all_entries():
            await self._clean(entry, force=True)
        leftovers, self._dirs = set(self._dirs), set()
        await asyncio.to_thread(_prune, leftovers, self._builder.runtime_dir)


def _remove_dir(directory: Path) -> None:
    shutil.rmtree(directory, ignore_errors=True)
    with contextlib.suppress(OSError):
        directory.parent.rmdir()        # the agent directory, only when no other version is left in it


def _prune(directories: set[Path], root: Path) -> None:
    for directory in directories:
        _remove_dir(directory)
    with contextlib.suppress(OSError):
        root.rmdir()                    # never recursive: other processes may share the root


def add_studio_runtime_hooks(app: "web.Application") -> None:
    """Append the runtime start/stop hooks once per app (guard ``_astudio_runtime_hooks_installed``)."""
    if app.get(_HOOKS_KEY):
        return
    app[_HOOKS_KEY] = True
    app.on_startup.append(install_studio_runtime)  # resolves storage first, which registers the Postgres stores
    app.on_cleanup.append(shutdown_studio_runtime)
    install_studio_storage_cleanup(app)


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
        max_sessions=int(_float_setting("STUDIO_MAX_SESSIONS", 1000)),
    )
    runtime.app = app
    manager.studio = runtime
    await runtime.start()


async def shutdown_studio_runtime(app: "web.Application") -> None:
    """``on_cleanup``: stop and clean the runtime when one was installed. Needs no database."""
    runtime = getattr(app.get("bot_manager"), "studio", None)
    if runtime is not None:
        await runtime.shutdown()
