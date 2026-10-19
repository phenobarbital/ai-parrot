"""Signed semantic audit ledger (spec §3 Module 8, §8 Q3/Q5)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel

from parrot.security import AbstractKMSSigner

from .errors import SemanticExecutionError

logger = logging.getLogger(__name__)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


class SemanticAuditEntry(BaseModel):
    """One signed record of a semantic-layer query attempt (AC9)."""

    schema_version: int = 1
    entry_id: str
    created_at: datetime
    user_id: str
    tenant_id: str
    channel: str
    agent_id: str | None
    subject_digest: str
    roles: list[str]
    static_subject: bool
    model: str
    model_digest: str
    policy_digest: str
    engine: str
    tool: str
    structured_query: dict | None
    raw_sql: bool
    compiled_sql: str | None
    governed_sql: str | None
    dialect: str
    driver: str
    rls_applied: list[str]
    masked_columns: list[str]
    pbac: Literal["allow", "deny", "unavailable", "not_governed"]
    outcome: Literal["ok", "denied", "validation_error", "execution_error"]
    error_code: str | None
    row_count: int | None
    duration_ms: int | None
    signature: str = ""

    def canonical_bytes(self) -> bytes:
        """Return sorted-key JSON without ``signature`` (same approach as AuditLedgerEntry.canonical_bytes).

        Returns:
            Canonical UTF-8 bytes used for signing and verification.
        """
        data = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


class SemanticAuditLedger:
    """Bounded in-memory, optionally signed and durable, semantic audit ledger.

    Args:
        signer: Optional core signer used to sign entries.
        storage: Optional async ``storage(json_str)`` sink.
        max_entries: Maximum entries kept in memory.
    """

    def __init__(
        self,
        signer: AbstractKMSSigner | None = None,
        storage: Callable[[str], Awaitable[None]] | None = None,
        max_entries: int = 10_000,
    ) -> None:
        """Initialize the ledger."""
        self.signer = signer
        self.storage = storage
        self.entries: deque[SemanticAuditEntry] = deque(maxlen=max_entries)
        self.logger = logger

    @property
    def durable(self) -> bool:
        """True when a storage callable is configured — drives audit_required=None resolution (§8 Q5)."""
        return self.storage is not None

    async def append(self, entry: SemanticAuditEntry, *, required: bool = False) -> SemanticAuditEntry:
        """Sign, keep in memory, forward JSON to storage; storage failure raises only when required.

        Args:
            entry: The entry to record.
            required: When True, a storage failure raises instead of only logging.

        Returns:
            The (signed) entry.

        Raises:
            SemanticExecutionError: ``audit_unavailable`` when storage fails and ``required`` is True.
        """
        if self.signer is not None:
            entry.signature = await self.signer.sign(entry.canonical_bytes())
        self.entries.append(entry)
        if self.storage is not None:
            try:
                await self.storage(entry.model_dump_json())
            except Exception as exc:  # noqa: BLE001 - any sink failure is an audit failure
                self.logger.error("Semantic audit storage failed for %s: %s", entry.entry_id, type(exc).__name__)
                if required:
                    raise SemanticExecutionError(
                        "audit_unavailable", details={"audit_id": entry.entry_id}
                    ) from exc
        elif required:
            raise SemanticExecutionError("audit_unavailable", details={"audit_id": entry.entry_id})
        return entry

    async def verify(self, entry: SemanticAuditEntry) -> bool:
        """Verify an entry's signature (async because core signers are async).

        Args:
            entry: The entry to verify.

        Returns:
            True iff a signer is configured and the signature matches.
        """
        if self.signer is None or not entry.signature:
            return False
        return await self.signer.verify(entry.canonical_bytes(), entry.signature)


def postgres_audit_storage(
    dsn_or_pool: str | Any, *, table: str = "semantic_audit_events"
) -> Callable[[str], Awaitable[None]]:
    """Async storage(json_str) that INSERTs into ``table`` (DDL: parrot/semantic/sql/semantic_audit_events.sql).

    Args:
        dsn_or_pool: A Postgres DSN (pool created lazily on first call) or an object exposing async ``execute``.
        table: Target table name (bare or schema-qualified identifier).

    Returns:
        An async callable accepting the entry JSON string.

    Raises:
        ValueError: If ``table`` is not a safe identifier.
    """
    if not _IDENTIFIER.match(table):
        raise ValueError(f"invalid audit table identifier: {table!r}")
    sql = (
        f"INSERT INTO {table} (entry_id, created_at, user_id, tenant_id, model, outcome, payload, signature) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)"
    )
    state: dict[str, Any] = {"pool": None if isinstance(dsn_or_pool, str) else dsn_or_pool}
    lock = asyncio.Lock()

    async def _get_pool() -> Any:
        if state["pool"] is None:
            async with lock:
                if state["pool"] is None:
                    import asyncpg

                    state["pool"] = await asyncpg.create_pool(dsn_or_pool)
        return state["pool"]

    async def storage(json_str: str) -> None:
        data = json.loads(json_str)
        created = data.get("created_at")
        created_at = datetime.fromisoformat(created.replace("Z", "+00:00")) if isinstance(created, str) else created
        pool = await _get_pool()
        await pool.execute(
            sql,
            uuid.UUID(str(data["entry_id"])),
            created_at,
            data["user_id"],
            data["tenant_id"],
            data["model"],
            data["outcome"],
            json_str,
            data.get("signature", ""),
        )

    return storage
