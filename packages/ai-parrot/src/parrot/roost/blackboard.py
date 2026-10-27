"""Roost blackboard — versioned single-writer keys with ACLs and subscriptions (FEAT-747 M6)."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from .messages import AgentAddress, RoostMessage
from .performatives import InteractionProtocol, Performative

logger = logging.getLogger(__name__)


class BlackboardKey(str, Enum):
    """Well-known blackboard keys."""

    ROSTER = "roster"
    DEFINITIONS = "definitions"
    TASKS = "tasks"
    DIGEST = "digest"
    ARTIFACTS = "artifacts"


class KeyACL(BaseModel):
    """Access control for one key: a single writer and a reader list (``*`` = everyone)."""

    readers: list[str] = Field(default_factory=lambda: ["*"])
    writer: str


class BlackboardEntry(BaseModel):
    """A versioned blackboard value."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    key: str
    value: Any
    version: int
    writer: str
    acl: KeyACL
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provenance: dict[str, Any] = Field(default_factory=dict)


class StaleWriteError(Exception):
    """A write carried an ``expected_version`` that no longer matches; it is refused, never merged."""


class WriterDeniedError(Exception):
    """The writer is not the owner of the key."""


class ReadDeniedError(Exception):
    """The reader is not allowed to read the key."""


Subscriber = Callable[[RoostMessage], Awaitable[None]]


class WriterPolicy:
    """Decides the single owner (writer) of each blackboard key.

    Args:
        harness: Owner of ``roster`` and ``definitions``.
        engine: Owner of ``tasks``.
        coordinator: Owner of ``digest`` when set.
    """

    def __init__(self, *, harness: str = "harness", engine: str = "engine", coordinator: Optional[str] = None) -> None:
        self.harness, self.engine, self.coordinator = harness, engine, coordinator
        self._last_request_closer: Optional[str] = None

    def owner_of(self, key: str, *, last_request_closer: Optional[str] = None, producer: Optional[str] = None) -> str:
        """Return the owner of ``key``, or ``""`` when no owner can be determined yet.

        Args:
            key: Blackboard key.
            last_request_closer: Overrides the recorded last Request closer.
            producer: Producer of an artifact (owner of ``artifacts``).

        Returns:
            The owning agent name; empty string when undetermined (unknown keys: first writer wins).
        """
        if key in (BlackboardKey.ROSTER.value, BlackboardKey.DEFINITIONS.value):
            return self.harness
        if key == BlackboardKey.TASKS.value:
            return self.engine
        if key == BlackboardKey.DIGEST.value:
            if self.coordinator:
                return self.coordinator
            return last_request_closer or self._last_request_closer or ""
        if key == BlackboardKey.ARTIFACTS.value:
            return producer or ""
        return ""

    def record_request_closed(self, agent_name: str) -> None:
        """Record the agent that last closed a Request (``digest`` owner without a coordinator)."""
        self._last_request_closer = agent_name


def _can_read(acl: KeyACL, reader: str) -> bool:
    return "*" in acl.readers or reader in acl.readers or reader == acl.writer


class Blackboard(ABC):
    """Abstract blackboard scoped to a conversation or channel."""

    def __init__(self, *, scope: str, policy: WriterPolicy) -> None:
        self.logger = logging.getLogger(__name__)
        self.scope = scope
        self.policy = policy
        self._subs: dict[str, tuple[str, Subscriber, str]] = {}  # sub_id -> (key, callback, subscriber_name)
        self._cache: dict[str, BlackboardEntry] = {}

    @abstractmethod
    async def get(self, key: str, *, reader: str) -> Optional[BlackboardEntry]:
        """Read a key (``ReadDeniedError`` if the ACL forbids it)."""

    @abstractmethod
    async def put(
        self,
        key: str,
        value: Any,
        *,
        writer: str,
        expected_version: Optional[int],
        acl: Optional[KeyACL] = None,
        provenance: Optional[dict[str, Any]] = None,
        producer: Optional[str] = None,
    ) -> BlackboardEntry:
        """Compare-and-set write of a key."""

    async def subscribe(self, key: str, subscriber: Subscriber, *, subscriber_name: str) -> str:
        """Subscribe to changes of ``key``; returns the subscription id."""
        sub_id = uuid.uuid4().hex
        self._subs[sub_id] = (key, subscriber, subscriber_name)
        return sub_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription; True if it existed."""
        return self._subs.pop(subscription_id, None) is not None

    async def _notify(self, entry: BlackboardEntry) -> None:
        """Exactly one ``inform`` per subscriber of ``entry.key``."""
        for sub_id, (key, callback, name) in list(self._subs.items()):
            if key != entry.key:
                continue
            msg = RoostMessage(
                performative=Performative.INFORM,
                protocol=InteractionProtocol.SUBSCRIBE,
                conversation_id=sub_id,
                sender=AgentAddress(name=entry.writer),
                receivers=[AgentAddress(name=name)],
                content=entry,
            )
            try:
                await callback(msg)
            except Exception:  # noqa: BLE001 - a failing subscriber never blocks the others
                self.logger.exception("Blackboard subscriber %s failed for key %s", name, entry.key)

    @abstractmethod
    async def keys(self, *, reader: str) -> list[str]:
        """List readable keys."""

    def render_prefix(self, *, reader: str, keys: Sequence[str] = ("roster", "definitions", "tasks", "digest")) -> str:
        """Deterministic text rendering for prompt-cache-friendly prefixes."""
        lines: list[str] = []
        for key in keys:
            entry = self._cache.get(key)
            if entry is None or not _can_read(entry.acl, reader):
                continue
            lines.append(f"## {key} (v{entry.version})")
            lines.append(json.dumps(entry.value, sort_keys=True, default=str))
        return "\n".join(lines)


class InMemoryBlackboard(Blackboard):
    """Process-local blackboard."""

    def __init__(self, *, scope: str, policy: WriterPolicy) -> None:
        super().__init__(scope=scope, policy=policy)
        self._entries: dict[str, BlackboardEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get(self, key: str, *, reader: str) -> Optional[BlackboardEntry]:
        """Read a key."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        if not _can_read(entry.acl, reader):
            raise ReadDeniedError(f"{reader!r} may not read {key!r}")
        return entry

    async def put(
        self,
        key: str,
        value: Any,
        *,
        writer: str,
        expected_version: Optional[int],
        acl: Optional[KeyACL] = None,
        provenance: Optional[dict[str, Any]] = None,
        producer: Optional[str] = None,
    ) -> BlackboardEntry:
        """Compare-and-set write; stale writes are refused with ``StaleWriteError``."""
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            current = self._entries.get(key)
            owner = self.policy.owner_of(key, producer=producer)
            if not owner and current is not None:
                owner = current.writer  # unknown keys: the first writer owns them
            if owner and writer != owner:
                raise WriterDeniedError(f"{writer!r} is not the writer of {key!r} (owner {owner!r})")
            if expected_version is None:
                if current is not None:
                    raise StaleWriteError(f"{key!r} already exists at version {current.version}")
                version = 1
            else:
                if current is None or current.version != expected_version:
                    found = None if current is None else current.version
                    raise StaleWriteError(f"{key!r}: expected version {expected_version}, found {found}")
                version = current.version + 1
            entry = BlackboardEntry(
                key=key,
                value=value,
                version=version,
                writer=writer,
                acl=acl or (current.acl if current else KeyACL(writer=writer)),
                provenance=provenance or {},
            )
            self._entries[key] = entry
            self._cache[key] = entry
        await self._notify(entry)
        return entry

    async def keys(self, *, reader: str) -> list[str]:
        """List keys the reader may read."""
        return [k for k, e in self._entries.items() if _can_read(e.acl, reader)]
