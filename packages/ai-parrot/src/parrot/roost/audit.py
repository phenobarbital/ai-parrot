"""Roost audit ledger — one signed line per performative (FEAT-747 M10)."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from parrot.security.audit_ledger import AbstractKMSSigner, LocalHMACSigner

from .messages import RoostMessage
from .performatives import InteractionProtocol, Performative

logger = logging.getLogger(__name__)

_JSON_SCALARS = (bool, int, float)


def _canonical_json(value: Any) -> bytes:
    """Serialize *value* as canonical (sorted, compact) JSON bytes.

    Args:
        value: A JSON-compatible value.

    Returns:
        UTF-8 encoded canonical JSON.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _is_json_value(value: Any) -> bool:
    """Return True when *value* is a plain JSON value (dict/list/scalar tree).

    Args:
        value: Candidate value.

    Returns:
        Whether the value is JSON-serializable without coercion.
    """
    if value is None or isinstance(value, (str, *_JSON_SCALARS)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_json_value(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_json_value(v) for k, v in value.items())
    return False


def _result_digest(content: Any) -> Optional[str]:
    """Compute the sha256 hex digest of a message's content.

    Args:
        content: The message content.

    Returns:
        Digest of the handle string, of the canonical JSON of a model / JSON value, or ``None``
        when the content is absent or carried by reference (e.g. frames).
    """
    if content is None:
        return None
    if isinstance(content, str):
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
    if isinstance(content, BaseModel):
        return hashlib.sha256(_canonical_json(content.model_dump(mode="json"))).hexdigest()
    if _is_json_value(content):
        return hashlib.sha256(_canonical_json(content)).hexdigest()
    return None


class RoostAuditEntry(BaseModel):
    """One signed audit line for a single Roost performative."""

    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    direction: Literal["served", "received"]
    sender: str
    receiver: str
    performative: Performative
    protocol: InteractionProtocol
    conversation_id: str
    message_id: str
    trace_id: Optional[str] = None
    result_digest: Optional[str] = None
    body: Optional[str] = None
    signature: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def canonical_bytes(self) -> bytes:
        """Return the canonical bytes that are signed (everything except ``signature``).

        Returns:
            UTF-8 encoded canonical JSON of the entry.
        """
        return _canonical_json(self.model_dump(mode="json", exclude={"signature"}))


class RoostAuditLedger:
    """Sibling of ``AuditLedger`` that records one signed entry per performative."""

    def __init__(self, signer: Optional[AbstractKMSSigner] = None, storage: Optional[Any] = None) -> None:
        """Initialize the ledger.

        Args:
            signer: KMS signer; defaults to a ``LocalHMACSigner`` with a random secret.
            storage: Optional duck-typed backend exposing ``async store(entry)``.
        """
        self.logger = logging.getLogger(__name__)
        self._signer = signer or LocalHMACSigner()
        self._storage = storage
        self._entries: dict[str, RoostAuditEntry] = {}

    async def record(
        self, msg: RoostMessage, *, direction: Literal["served", "received"], self_name: str
    ) -> RoostAuditEntry:
        """Build, sign and persist the entry for *msg*.

        Args:
            msg: The Roost message being audited.
            direction: ``served`` on the serving agent, ``received`` on the caller.
            self_name: Name of the agent owning this ledger.

        Returns:
            The signed entry.

        Raises:
            Exception: Any storage error is logged and re-raised (fail-closed audit).
        """
        if direction == "served":
            receiver = self_name
        elif msg.receivers:
            receiver = msg.receivers[0].name
        else:
            receiver = msg.capability_filter or ""
        entry = RoostAuditEntry(
            direction=direction,
            sender=msg.sender.name,
            receiver=receiver,
            performative=msg.performative,
            protocol=msg.protocol,
            conversation_id=msg.conversation_id,
            message_id=msg.message_id,
            trace_id=msg.trace_id(),
            result_digest=_result_digest(msg.content),
            body=msg.body,
        )
        entry.signature = await self._signer.sign(entry.canonical_bytes())
        store = getattr(self._storage, "store", None) if self._storage is not None else None
        if store is not None:
            try:
                await store(entry)
            except Exception:
                self.logger.exception("Roost audit storage failed for entry %s", entry.entry_id)
                raise
        self._entries[entry.entry_id] = entry
        return entry

    async def verify(self, entry: RoostAuditEntry) -> bool:
        """Verify an entry's signature against its canonical bytes.

        Args:
            entry: Entry to verify.

        Returns:
            True when the signature matches.
        """
        return await self._signer.verify(entry.canonical_bytes(), entry.signature)

    def entries(
        self, *, conversation_id: Optional[str] = None, trace_id: Optional[str] = None
    ) -> list[RoostAuditEntry]:
        """Return entries filtered by conversation and/or trace id.

        Args:
            conversation_id: Optional conversation filter.
            trace_id: Optional trace filter.

        Returns:
            Matching entries in insertion order.
        """
        return [
            e
            for e in self._entries.values()
            if (conversation_id is None or e.conversation_id == conversation_id)
            and (trace_id is None or e.trace_id == trace_id)
        ]
