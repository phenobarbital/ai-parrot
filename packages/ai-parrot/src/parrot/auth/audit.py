"""DEPRECATED: Use ``parrot.security.audit_ledger`` instead.

This module is superseded by the canonical
:class:`parrot.security.audit_ledger.AuditLedger` (FEAT-264 / TASK-1675),
which provides KMS-signed entries and a unified single-ledger design.

Migration
---------
Old (deprecated)::

    from parrot.auth.audit import AuditLedger, AuditEntry
    ledger = AuditLedger()
    ledger.record(AuditEntry(timestamp=..., user_id=..., ...))

New (canonical)::

    from parrot.security.audit_ledger import AuditLedger
    ledger = AuditLedger()
    await ledger.append(user_id=..., channel=..., tool=...,
                        provider=..., credential_material=token)

This file is kept for backward-compatibility; both ``AuditLedger`` and
``AuditEntry`` will emit :class:`DeprecationWarning` on use in a future
release and will be removed in the version after that.
"""
from __future__ import annotations

import json
import logging
import warnings
from collections import deque
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class AuditEntry:
    """Single credential invocation record.

    .. deprecated::
        Use :class:`parrot.security.audit_ledger.AuditLedgerEntry` instead.
        This class will be removed in a future release.

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
    """DEPRECATED log-based audit ledger.

    .. deprecated::
        Use :class:`parrot.security.audit_ledger.AuditLedger` instead.
        This class will be removed in a future release.

    Records per-invocation credential usage for compliance.
    Initially log-based (structured JSON lines).

    Attributes:
        logger: Logger instance used for structured JSON output.
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        """Initialise the ledger.

        Args:
            logger: Logger to write audit records to. Defaults to a logger
                named ``parrot.auth.audit``.
        """
        warnings.warn(
            "parrot.auth.audit.AuditLedger is deprecated. "
            "Use parrot.security.audit_ledger.AuditLedger instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.logger = logger or logging.getLogger(__name__)
        self._entries: deque[AuditEntry] = deque(maxlen=1000)

    def record(self, entry: AuditEntry) -> None:
        """Record a credential invocation entry.

        .. deprecated::
            Prefer :meth:`parrot.security.audit_ledger.AuditLedger.append`.

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
        """Flush any buffered entries to the backing store (no-op)."""

    def entries(self) -> list[AuditEntry]:
        """Return a copy of all recorded entries (primarily for testing).

        Returns:
            A list of all recorded entries (converted from the internal deque).
        """
        return list(self._entries)
