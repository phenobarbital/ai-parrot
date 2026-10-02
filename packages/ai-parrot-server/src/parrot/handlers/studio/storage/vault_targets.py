"""``navigator_session.vault_targets`` for the phase-2 Postgres secret tables (spec §2.10, M12).

Mirrors core ``parrot.vault_targets`` (DocumentDB): ``navigator.ai_user_credentials`` and
``navigator.ai_user_llm_keys`` hold the same base64 envelopes under the same AAD contexts, so ``navigator-vault``
rotation / migration covers them. The tables have no lifecycle column (DDL fixed by the spec), so a quarantined row
is *renamed* (``<name>#quarantined:<run_id>``): its blob is untouched, runtime reads (keyed by the original name)
no longer find it, iteration skips it, and ``restore_raw`` puts the original key back.

Security Note:
    Row refs and logs carry identities only, never credential values.
"""
from __future__ import annotations

import base64
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Mapping, Optional

from navigator_session.vault.registry import BackupSink, BackupSource, VaultRow
from navigator_session.vault.targets.postgres import acquire_connection, fetch_rows

from parrot.security.credentials_utils import (
    CREDENTIAL_PURPOSE,
    LLM_KEY_PURPOSE,
    credential_context,
    llm_key_context,
)

QUARANTINE_MARK = "#quarantined:"


class _PgSealedTarget:
    """One sealed base64 text column per row, composite identity ``(user_id, <name column>)``."""

    name: str
    table: str
    purpose: str
    identity_columns: tuple[str, str]
    field: str
    key_column: Optional[str] = None
    state_columns: tuple[str, ...] = ("created_at",)

    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self._conn: ContextVar[Any] = ContextVar(f"studio_vault_conn_{self.name}", default=None)
        a, b = self.identity_columns
        self._cols = [a, b, self.field, *([self.key_column] if self.key_column else []), *self.state_columns]
        select = f"SELECT {', '.join(self._cols)} FROM {self.table} WHERE position($1 in {b}) = 0"
        self._first_sql = f"{select} ORDER BY {a}, {b} LIMIT $2"
        self._next_sql = f"{select} AND ({a}, {b}) > ($2, $3) ORDER BY {a}, {b} LIMIT $4"

    @property
    def encrypted_fields(self) -> tuple[str, ...]:
        return (self.field,)

    def _context(self, *identity: Any):
        raise NotImplementedError

    def context_for(self, row: Any, field: str):
        """Context binding ``field`` of ``row`` (same AAD as the DocumentDB documents)."""
        if field != self.field:
            raise ValueError(f"{field!r} is not an encrypted field of {self.name}")
        return self._context(*(row.identity[c] for c in self.identity_columns))

    def ref_for(self, identity: Mapping[str, Any]) -> str:
        return f"{self.name}:" + ",".join(f"{c}={identity.get(c)}" for c in self.identity_columns)

    def _row(self, record: Any) -> VaultRow:
        identity = {c: record[c] for c in self.identity_columns}
        stored = record[self.field]
        return VaultRow(
            ref=self.ref_for(identity),
            pk=identity,
            identity=identity,
            values={self.field: base64.b64decode(stored) if stored else None},
            key_version=record[self.key_column] if self.key_column else None,
            state={c: _jsonable(record[c]) for c in self.state_columns},
        )

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[Any]:
        current = self._conn.get()
        if current is not None:
            yield current
            return
        async with acquire_connection(self._pool) as conn:
            yield conn

    async def iter_batches(self, batch_size: int) -> AsyncIterator[list[VaultRow]]:
        """Keyset pagination over ``(user_id, <name>)``; the connection is released before each yield."""
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        last: Optional[Mapping[str, Any]] = None
        while True:
            async with self._connection() as conn:
                if last is None:
                    records = await fetch_rows(conn, self._first_sql, QUARANTINE_MARK, batch_size)
                else:
                    a, b = self.identity_columns
                    records = await fetch_rows(conn, self._next_sql, QUARANTINE_MARK, last[a], last[b], batch_size)
            rows = [self._row(r) for r in records]
            if rows:
                yield rows
            if len(rows) < batch_size:
                return
            last = rows[-1].identity

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        """One connection / transaction for a group of writes (nested calls reuse the outer one)."""
        current = self._conn.get()
        if current is not None:
            yield current
            return
        async with acquire_connection(self._pool) as conn:
            await conn.transaction()
            token = self._conn.set(conn)
            try:
                yield conn
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise
            finally:
                self._conn.reset(token)

    async def _returning(self, sql: str, *args: Any) -> Any:
        async with self._connection() as conn:
            return await conn.fetch_one(sql, *args)

    async def write(self, row: Any, blobs: Mapping[str, Optional[bytes]], key_version: int) -> None:
        """Replace the sealed value (and key id) of ``row``. Raises ``LookupError`` when the row is gone."""
        unknown = set(blobs) - {self.field}
        blob = blobs.get(self.field)
        if unknown or blob is None:
            raise ValueError(f"{self.name} requires a value for {self.field} and no other field")
        a, b = self.identity_columns
        encoded = base64.b64encode(bytes(blob)).decode()
        sets, args = [f"{self.field} = $3"], [row.identity[a], row.identity[b], encoded]
        if self.key_column:
            args.append(key_version)
            sets.append(f"{self.key_column} = ${len(args)}")
        sql = (f"UPDATE {self.table} SET {', '.join(sets)}, updated_at = now() "
               f"WHERE {a} = $1 AND {b} = $2 RETURNING {a}")
        if await self._returning(sql, *args) is None:
            raise LookupError(f"{row.ref} not found")

    async def quarantine(self, row: Any, reason: str, run_id: str) -> None:
        """Rename the row's name column (blob untouched) so runtime reads and iteration no longer see it."""
        a, b = self.identity_columns
        sql = f"UPDATE {self.table} SET {b} = {b} || $3 WHERE {a} = $1 AND {b} = $2 RETURNING {a}"
        if await self._returning(sql, row.identity[a], row.identity[b], QUARANTINE_MARK + run_id) is None:
            raise LookupError(f"{row.ref} not found")

    def to_backup_record(self, row: VaultRow) -> dict[str, Any]:
        """JSON-safe snapshot of a row (sealed value stays sealed)."""
        blob = row.values[self.field]
        return {
            "ref": row.ref,
            "pk": dict(row.identity),
            "identity": dict(row.identity),
            "values": {self.field: None if blob is None else base64.b64encode(blob).decode("ascii")},
            "key_version": row.key_version,
            "state": dict(row.state),
        }

    async def export_raw(self, sink: BackupSink) -> int:
        """Export every live row as stored."""
        count = 0
        async for batch in self.iter_batches(200):
            for row in batch:
                await sink.write(self.name, self.to_backup_record(row))
                count += 1
        return count

    async def restore_raw(self, source: BackupSource) -> int:
        """Upsert rows from a backup and drop their quarantined renames, in one transaction."""
        a, b = self.identity_columns
        cols = [a, b, self.field, *([self.key_column] if self.key_column else []), *self.state_columns]
        marks = ", ".join(f"${i + 1}" for i in range(len(cols)))
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols[2:])
        upsert = (f"INSERT INTO {self.table} ({', '.join(cols)}) VALUES ({marks}) "
                  f"ON CONFLICT ({a}, {b}) DO UPDATE SET {updates}, updated_at = now() RETURNING {a}")
        purge = f"DELETE FROM {self.table} WHERE {a} = $1 AND starts_with({b}, $2) RETURNING {a}"
        count = 0
        async with self.transaction() as conn:
            async for rec in source.read(self.name):
                ident, state = rec["identity"], rec.get("state", {})
                args = [ident[a], ident[b], rec["values"][self.field]]
                args += [rec.get("key_version")] if self.key_column else []
                args += [_from_state(c, state.get(c)) for c in self.state_columns]
                await conn.fetch_one(upsert, *args)
                await conn.fetch_one(purge, ident[a], ident[b] + QUARANTINE_MARK)
                count += 1
        return count


def _jsonable(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _from_state(column: str, value: Any) -> Any:
    return datetime.fromisoformat(value) if column.endswith("_at") and isinstance(value, str) else value


class PgUserCredentialsTarget(_PgSealedTarget):
    """``navigator.ai_user_credentials.credential`` sealed under ``credential_context(user_id, name)``."""

    name = "pg:ai_user_credentials"
    table = "navigator.ai_user_credentials"
    purpose = CREDENTIAL_PURPOSE
    identity_columns = ("user_id", "name")
    field = "credential"

    def _context(self, user_id: Any, name: str):
        return credential_context(user_id, name)


class PgUserLlmKeysTarget(_PgSealedTarget):
    """``navigator.ai_user_llm_keys.api_key_enc`` sealed under ``llm_key_context(user_id, provider)``."""

    name = "pg:ai_user_llm_keys"
    table = "navigator.ai_user_llm_keys"
    purpose = LLM_KEY_PURPOSE
    identity_columns = ("user_id", "provider")
    field = "api_key_enc"
    key_column = "key_id"
    state_columns = ("masked", "created_at")

    def _context(self, user_id: Any, provider: str):
        return llm_key_context(user_id, provider)


def _factory(resources: Mapping[str, Any], cls: Callable[[Any], Any]) -> Any:
    pool = resources.get("parrot_db_pool") or resources.get("db_pool")
    return None if pool is None else cls(pool)


def user_credentials_factory(resources: Mapping[str, Any]) -> Optional[PgUserCredentialsTarget]:
    """Entry-point factory (needs the PostgreSQL pool)."""
    return _factory(resources, PgUserCredentialsTarget)


def user_llm_keys_factory(resources: Mapping[str, Any]) -> Optional[PgUserLlmKeysTarget]:
    """Entry-point factory (needs the PostgreSQL pool)."""
    return _factory(resources, PgUserLlmKeysTarget)
