"""Studio runtime cache (spec §2.7/§2.7a). Private to StudioAgentRuntime; never BotManager._bots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from parrot.bots.abstract import AbstractBot


@dataclass
class StudioCacheEntry:
    """One built Studio instance. ``session_id`` is None for the base entry of an agent."""

    qualified: str
    session_id: str | None
    agent_id: UUID
    version: int
    bot: "AbstractBot"
    asset_dir: Path | None
    leases: int = 0
    expires_at: float | None = None
    last_used: float = 0.0
    retired_at: float | None = None
    cleaned: bool = False


class StudioRuntimeCache:
    """Pure, synchronous bookkeeping: it decides what is reclaimable, the runtime does the cleaning.

    Rules (§2.7a): a session past its TTL with no lease is reclaimable; a base entry idle past ``idle_ttl`` with no
    lease is retired; a retired entry is reclaimable once it has no lease AND ``grace`` seconds passed since it was
    retired. ``cleaned`` is the identity guard: an entry marked cleaned is never returned again.
    """

    def __init__(self) -> None:
        self._base: dict[str, StudioCacheEntry] = {}
        self._sessions: dict[tuple[str, str], StudioCacheEntry] = {}
        self._retired: list[StudioCacheEntry] = []
        self._dir_refs: dict[tuple[UUID, int], int] = {}

    # ---- lookup -----------------------------------------------------------------------------------------------
    def current(self, qualified: str) -> StudioCacheEntry | None:
        """The live base entry of an agent, or None."""
        return self._base.get(qualified)

    def session(self, qualified: str, session_id: str) -> StudioCacheEntry | None:
        """The live session entry, or None."""
        return self._sessions.get((qualified, session_id))

    def all_entries(self) -> list[StudioCacheEntry]:
        """Every entry not yet cleaned (base, session and retired) — what shutdown must clean."""
        entries = [*self._base.values(), *self._sessions.values(), *self._retired]
        return [e for e in entries if not e.cleaned]

    # ---- transitions ------------------------------------------------------------------------------------------
    def install(self, entry: StudioCacheEntry) -> StudioCacheEntry | None:
        """Install as the base (or session) entry; return the replaced entry, now retired at ``entry.last_used``."""
        if entry.session_id is None:
            previous = self._base.get(entry.qualified)
            self._base[entry.qualified] = entry
        else:
            previous = self._sessions.get((entry.qualified, entry.session_id))
            self._sessions[(entry.qualified, entry.session_id)] = entry
        if previous is None or previous is entry:
            return None
        self.retire(previous, now=entry.last_used)
        return previous

    def retire(self, entry: StudioCacheEntry, *, now: float) -> None:
        """Take ``entry`` out of the live maps and keep it until it is reclaimable. Idempotent."""
        if entry.cleaned:
            return
        self._unlink(entry)
        if entry.retired_at is None:
            entry.retired_at = now
        self._retired.append(entry)

    def mark_cleaned(self, entry: StudioCacheEntry) -> None:
        """Record that ``entry`` was cleaned: it leaves every structure and is never returned again."""
        entry.cleaned = True
        self._unlink(entry)

    def _unlink(self, entry: StudioCacheEntry) -> None:
        """Remove ``entry`` (by identity) from the live maps and the retired list."""
        if entry.session_id is None:
            if self._base.get(entry.qualified) is entry:
                del self._base[entry.qualified]
        elif self._sessions.get((entry.qualified, entry.session_id)) is entry:
            del self._sessions[(entry.qualified, entry.session_id)]
        self._retired = [e for e in self._retired if e is not entry]

    def reclaimable(self, *, now: float, grace: float, session_ttl: float, idle_ttl: float) -> list[StudioCacheEntry]:
        """Retire idle base entries, then list what may be cleaned now (sessions past TTL, retired past grace)."""
        self._retire_idle(now, idle_ttl)
        return [*self._due_sessions(now, session_ttl), *self._due_retired(now, grace)]

    def _retire_idle(self, now: float, idle_ttl: float) -> None:
        for entry in [e for e in self._base.values() if self._idle(e, now, idle_ttl)]:
            self.retire(entry, now=now)

    @staticmethod
    def _idle(entry: StudioCacheEntry, now: float, idle_ttl: float) -> bool:
        return entry.leases == 0 and now - entry.last_used >= idle_ttl

    def _due_sessions(self, now: float, session_ttl: float) -> list[StudioCacheEntry]:
        return [
            e for e in self._sessions.values() if e.leases == 0 and self._session_expired(e, now, session_ttl)
        ]

    def _due_retired(self, now: float, grace: float) -> list[StudioCacheEntry]:
        return [e for e in self._retired if self._retired_due(e, now, grace)]

    @staticmethod
    def _retired_due(entry: StudioCacheEntry, now: float, grace: float) -> bool:
        if entry.cleaned or entry.leases != 0 or entry.retired_at is None:
            return False
        return now - entry.retired_at >= grace

    @staticmethod
    def _session_expired(entry: StudioCacheEntry, now: float, session_ttl: float) -> bool:
        if entry.expires_at is not None and now >= entry.expires_at:
            return True
        return now - entry.last_used >= session_ttl

    def live_sessions(self) -> list[StudioCacheEntry]:
        """Session entries still installed (not retired), oldest ``last_used`` first."""
        return sorted(self._sessions.values(), key=lambda e: e.last_used)

    # ---- asset directories ------------------------------------------------------------------------------------
    def acquire_dir(self, agent_id: UUID, version: int) -> int:
        """Add a user of the ``(agent_id, version)`` asset directory; returns the new count."""
        key = (agent_id, version)
        self._dir_refs[key] = self._dir_refs.get(key, 0) + 1
        return self._dir_refs[key]

    def release_dir(self, agent_id: UUID, version: int) -> bool:
        """Drop one user; True when it was the last one (the directory may be removed). Unknown keys → False."""
        key = (agent_id, version)
        count = self._dir_refs.get(key, 0)
        if count <= 0:
            return False
        if count == 1:
            del self._dir_refs[key]
            return True
        self._dir_refs[key] = count - 1
        return False
