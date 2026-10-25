"""Signed semantic audit ledger (spec §3 Module 8, §8 Q3/Q5)."""

from __future__ import annotations

import json
import logging
import re
from collections import deque
from datetime import datetime
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel

from parrot.security import AbstractKMSSigner, LocalHMACSigner

from .errors import SemanticExecutionError

logger = logging.getLogger(__name__)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


class SemanticAuditEntry(BaseModel):
    """One signed audit record for a semantic tool call.

    ``engine`` is provenance only and is always ``"native"``. SQL text lives here,
    never in exception messages.
    """

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
    engine: Literal["native"] = "native"
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
        """Return sorted-key compact JSON of the entry, excluding ``signature``.

        Returns:
            Canonical UTF-8 bytes used for signing and verification.
        """
        data = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


class SemanticAuditLedger:
    """Bounded in-memory signed ledger with an optional async durable sink.

    Args:
        signer: Async KMS signer; defaults to a process-local HMAC signer.
        storage: Async callable receiving the entry JSON; makes the ledger durable.
        max_entries: Maximum number of entries kept in memory.
    """

    def __init__(
        self,
        signer: AbstractKMSSigner | None = None,
        storage: Callable[[str], Awaitable[None]] | None = None,
        max_entries: int = 10_000,
    ) -> None:
        self.signer: AbstractKMSSigner = signer or LocalHMACSigner()
        self.storage = storage
        self.entries: deque[SemanticAuditEntry] = deque(maxlen=max_entries)
        self.logger = logger

    @property
    def durable(self) -> bool:
        """True when a storage callable is configured (drives audit_required=None, §8 Q5)."""
        return self.storage is not None

    async def append(self, entry: SemanticAuditEntry, *, required: bool = False) -> SemanticAuditEntry:
        """Sign the entry, keep it in memory and forward it to storage.

        Args:
            entry: The audit entry to record.
            required: When True, a missing or failing sink raises instead of logging.

        Returns:
            The signed entry.

        Raises:
            SemanticExecutionError: ``audit_unavailable`` when required and the sink fails.
        """
        entry.signature = await self.signer.sign(entry.canonical_bytes())
        self.entries.append(entry)
        if self.storage is None:
            if required:
                raise SemanticExecutionError(
                    "audit_unavailable", "Audit storage is not configured", details={"audit_id": entry.entry_id}
                )
            return entry
        try:
            await self.storage(entry.model_dump_json())
        except Exception as exc:  # noqa: BLE001 - sink failures are policy-handled
            self.logger.error("Semantic audit sink failed for %s: %s", entry.entry_id, type(exc).__name__)
            if required:
                raise SemanticExecutionError(
                    "audit_unavailable", "Audit storage failed", details={"audit_id": entry.entry_id}
                ) from exc
        return entry

    async def verify(self, entry: SemanticAuditEntry) -> bool:
        """Verify the entry's signature with the configured async signer.

        Args:
            entry: Entry to verify.

        Returns:
            True when the signature matches the canonical content.
        """
        if not entry.signature:
            return False
        return await self.signer.verify(entry.canonical_bytes(), entry.signature)


def _quote_table(table: str) -> str:
    """Validate a bare or schema-qualified identifier and return it double-quoted.

    Args:
        table: ``name`` or ``schema.name``.

    Returns:
        The quoted identifier.

    Raises:
        ValueError: If any part is not a plain identifier.
    """
    parts = table.split(".")
    if not 1 <= len(parts) <= 2 or not all(_IDENTIFIER.match(p) for p in parts):
        raise ValueError("Invalid audit table identifier")
    return ".".join(f'"{p}"' for p in parts)


def postgres_audit_storage(
    dsn_or_pool: str | Any, *, table: str = "semantic_audit_events"
) -> Callable[[str], Awaitable[None]]:
    """Build an async storage callable that INSERTs entries into Postgres.

    An injected pool (anything with ``acquire()``) is never closed. A DSN string
    opens an owned asyncpg connection per write, always closed afterwards.

    Args:
        dsn_or_pool: asyncpg DSN or an existing pool.
        table: Target table (DDL: ``parrot/semantic/sql/semantic_audit_events.sql``).

    Returns:
        ``async storage(json_str)``.
    """
    quoted = _quote_table(table)
    sql = (
        f"INSERT INTO {quoted} (entry_id, created_at, user_id, tenant_id, model, outcome, payload, signature) "
        "VALUES ($1::uuid, $2, $3, $4, $5, $6, $7::jsonb, $8)"
    )

    def _params(payload: str) -> tuple[Any, ...]:
        data = json.loads(payload)
        return (
            data["entry_id"],
            datetime.fromisoformat(data["created_at"]),
            data["user_id"],
            data["tenant_id"],
            data["model"],
            data["outcome"],
            payload,
            data.get("signature", ""),
        )

    async def storage(payload: str) -> None:
        params = _params(payload)
        if isinstance(dsn_or_pool, str):
            import asyncpg  # lazy: optional dependency

            conn = await asyncpg.connect(dsn_or_pool)
            try:
                await conn.execute(sql, *params)
            finally:
                await conn.close()
            return
        async with dsn_or_pool.acquire() as conn:
            await conn.execute(sql, *params)

    return storage
