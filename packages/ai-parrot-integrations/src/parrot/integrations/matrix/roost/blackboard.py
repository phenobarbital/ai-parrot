"""Room-state blackboard over ``m.parrot.blackboard`` state events (FEAT-747 M12)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from parrot.roost.blackboard import (
    Blackboard,
    BlackboardEntry,
    KeyACL,
    ReadDeniedError,
    StaleWriteError,
    WriterDeniedError,
    WriterPolicy,
    _can_read,
)

from ..events import BlackboardStateContent, ParrotEventType

if TYPE_CHECKING:
    from ..client import MatrixClientWrapper

logger = logging.getLogger(__name__)


class MatrixBlackboard(Blackboard):
    """Blackboard whose keys are room state events (``state_key`` = key), replaced and never appended.

    Writes are read-compare-set: the stored ``version`` is compared to ``expected_version`` and then the state
    event is replaced. A per-key asyncio lock serialises local writers; writers in *other processes* can still race
    inside the read-compare-set window (Matrix state has no server-side CAS), so that window bounds the guarantee.

    Args:
        client: Connected Matrix client wrapper.
        room_id: Room whose state holds the blackboard.
        scope: Blackboard scope (conversation or channel id).
        policy: Writer policy deciding the owner of each key.
    """

    def __init__(self, client: "MatrixClientWrapper", *, room_id: str, scope: str, policy: WriterPolicy) -> None:
        super().__init__(scope=scope, policy=policy)
        self._client = client
        self._room_id = room_id
        self._locks: Dict[str, asyncio.Lock] = {}
        self._known_keys: set[str] = set()

    @staticmethod
    def _to_entry(raw: Dict[str, Any]) -> BlackboardEntry:
        state = BlackboardStateContent.model_validate(raw)
        acl = KeyACL(**state.acl) if state.acl else KeyACL(writer=state.writer)
        return BlackboardEntry(
            key=state.key,
            value=state.value,
            version=state.version,
            writer=state.writer,
            acl=acl,
            updated_at=state.updated_at,
            provenance=state.provenance,
        )

    async def _read(self, key: str) -> Optional[BlackboardEntry]:
        raw = await self._client.get_room_state_event(self._room_id, ParrotEventType.BLACKBOARD, key)
        if not raw:
            return None
        self._known_keys.add(key)
        return self._to_entry(raw)

    async def get(self, key: str, *, reader: str) -> Optional[BlackboardEntry]:
        """Read a key from room state (``ReadDeniedError`` if the ACL forbids it)."""
        entry = await self._read(key)
        if entry is None:
            return None
        if not _can_read(entry.acl, reader):
            raise ReadDeniedError(f"{reader!r} may not read {key!r}")
        self._cache[key] = entry
        return entry

    async def put(
        self,
        key: str,
        value: Any,
        *,
        writer: str,
        expected_version: Optional[int],
        acl: Optional[KeyACL] = None,
        provenance: Optional[Dict[str, Any]] = None,
        producer: Optional[str] = None,
    ) -> BlackboardEntry:
        """Compare-and-set write replacing the key's state event.

        Raises:
            WriterDeniedError: *writer* does not own the key.
            StaleWriteError: ``expected_version`` does not match the stored version.
        """
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            current = await self._read(key)
            owner = self.policy.owner_of(key, producer=producer)
            if not owner and current is not None:
                owner = current.writer
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
                updated_at=datetime.now(timezone.utc),
            )
            content = BlackboardStateContent(
                key=key,
                value=value,
                version=version,
                writer=writer,
                acl=entry.acl.model_dump(mode="json"),
                updated_at=entry.updated_at,
                provenance=entry.provenance,
            ).model_dump(mode="json")
            await self._client.set_room_state(self._room_id, ParrotEventType.BLACKBOARD, content, state_key=key)
            self._known_keys.add(key)
            self._cache[key] = entry
        await self._notify(entry)
        return entry

    async def keys(self, *, reader: str) -> List[str]:
        """List readable keys this blackboard instance has read or written (the client has no state listing)."""
        result: List[str] = []
        for key in sorted(self._known_keys):
            entry = self._cache.get(key) or await self._read(key)
            if entry is not None and _can_read(entry.acl, reader):
                result.append(key)
        return result
