"""Credential invocation audit ledger.

Records per-invocation credential usage for compliance. Each credentialed
tool invocation produces an :class:`AuditEntry` that captures a
``key_fingerprint`` (SHA-256 of the first 8 bytes of the token) rather than
the raw token itself.

The :class:`AuditLedger` ships a log-based backend that writes structured JSON
lines via the standard :mod:`logging` module. It is designed to be extended to
a persistent store (database, event stream) without changing the calling code.
"""
from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class AuditEntry:
    """Single credential invocation record.

    Attributes:
        timestamp: ISO-8601 UTC timestamp of the invocation.
        user_id: Canonical user identity (``aad_object_id`` or channel id).
        channel: Integration channel (e.g. ``"msagentsdk"``).
        tool: Tool name that requested credentials (e.g. ``"o365"``).
        connection: OAuth connection name used (e.g. ``"graph_sso"``).
        key_fingerprint: SHA-256 hex of the first 8 bytes of the resolved
            token. Never the raw token itself.
        action: Either ``"resolve"`` (token fetched from token service) or
            ``"obo_exchange"`` (on-behalf-of exchange performed).
    """

    timestamp: str
    user_id: str
    channel: str
    tool: str
    connection: str
    key_fingerprint: str
    action: str


class AuditLedger:
    """Records per-invocation credential usage for compliance.

    Initially log-based (structured JSON lines). Can be extended to persist
    to a database or external audit service by overriding :meth:`record`.

    Attributes:
        logger: Logger instance used for structured JSON output.
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        """Initialise the ledger.

        Args:
            logger: Logger to write audit records to. Defaults to a logger
                named ``parrot.auth.audit``.
        """
        self.logger = logger or logging.getLogger(__name__)
        self._entries: deque[AuditEntry] = deque(maxlen=1000)

    def record(self, entry: AuditEntry) -> None:
        """Record a credential invocation entry.

        Appends the entry to the in-memory list and emits it as a structured
        JSON INFO log line prefixed with ``AUDIT``.

        Args:
            entry: The :class:`AuditEntry` to record.
        """
        self._entries.append(entry)
        self.logger.info(
            "AUDIT %s",
            json.dumps(asdict(entry), separators=(",", ":")),
        )

    async def flush(self) -> None:
        """Flush any buffered entries to the backing store.

        For the log-based implementation this is a no-op — entries are
        written synchronously in :meth:`record`. Persistent backends should
        override this method.
        """

    def entries(self) -> list[AuditEntry]:
        """Return a copy of all recorded entries (primarily for testing).

        Returns:
            A list of all recorded entries (converted from the internal deque).
        """
        return list(self._entries)
