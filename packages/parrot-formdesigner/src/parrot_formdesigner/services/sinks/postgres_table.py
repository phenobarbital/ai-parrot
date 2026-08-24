"""`PostgresTableSink` — an arbitrary Postgres table owned by a single form.

The reference sink and the only v1 backend with the full capability set
(``WRITE``, ``READ``, ``LIST``, ``PROVISION``, ``EXTEND``). DDL is
templated on :class:`~parrot_formdesigner.services.submissions.
FormSubmissionStorage` (``_create_table_sql`` / ``_alter_table_sql``):
``CREATE TABLE IF NOT EXISTS``, additive ``ADD COLUMN IF NOT EXISTS``, and
**never** ``DROP`` or ``RENAME``.

Unlike :class:`~parrot_formdesigner.services.storage.PostgresFormStorage`
(which documents that its target schema is assumed to already exist),
this sink deliberately provisions its own target — a sanctioned departure
bounded by the alias allowlist (:mod:`~parrot_formdesigner.services.
sink_aliases`) and the additive-only rule.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from parrot_formdesigner.core.persistence import PostgresTableTarget, SinkCapability
from parrot_formdesigner.core.schema import FormSchema, FormSubsection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services._identifiers import (
    qualified_table,
    validate_identifier,
)
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry
from parrot_formdesigner.services.sinks.base import (
    AbstractSubmissionSink,
    SinkTargetMismatchError,
    SinkUnavailableError,
)
from parrot_formdesigner.services.sinks.mapper import column_names_for
from parrot_formdesigner.services.submissions import FormSubmission

# Reserved-column DDL, matching FormSubmissionStorage's own CREATE TABLE
# shape (services/submissions.py:173) for the columns this sink shares by
# name. Dict insertion order IS the column emission order (stable, unlike
# iterating a frozenset).
_RESERVED_COLUMN_DDL: dict[str, str] = {
    "submission_id": "VARCHAR(255) PRIMARY KEY",
    "form_uid": "UUID NOT NULL",
    "form_id": "VARCHAR(255) NOT NULL",
    "form_version": "VARCHAR(50) NOT NULL",
    "created_at": "TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    "tenant": "VARCHAR(63)",
    "user_id": "VARCHAR(255)",
    "username": "VARCHAR(255)",
    "org_id": "INTEGER",
    "submitted_at": "TIMESTAMPTZ",
    "ip": "INET",
    "user_agent": "TEXT",
    "locale": "VARCHAR(35)",
    "root_submission_id": "VARCHAR(255)",
    "revision": "INTEGER",
    "context": "JSONB",
}

# FieldType -> (DDL type for ADD COLUMN, compatible information_schema
# `data_type` strings for an existing column of that intent).
_FIELD_TYPE_PG: dict[FieldType, tuple[str, frozenset[str]]] = {
    FieldType.INTEGER: ("INTEGER", frozenset({"integer", "bigint", "smallint"})),
    FieldType.NUMBER: (
        "DOUBLE PRECISION",
        frozenset({"double precision", "numeric", "real"}),
    ),
    FieldType.BOOLEAN: ("BOOLEAN", frozenset({"boolean"})),
    FieldType.DATE: ("DATE", frozenset({"date"})),
    FieldType.DATETIME: (
        "TIMESTAMPTZ",
        frozenset({"timestamp with time zone", "timestamptz"}),
    ),
    FieldType.ARRAY: ("JSONB", frozenset({"jsonb", "json"})),
}
_DEFAULT_DDL_TYPE = "TEXT"
_DEFAULT_COMPATIBLE_TYPES = frozenset({"text", "character varying", "varchar"})


def _ddl_type_for(field_type: FieldType) -> str:
    """Return the ``ADD COLUMN`` SQL type fragment for ``field_type``."""
    return _FIELD_TYPE_PG.get(field_type, (_DEFAULT_DDL_TYPE, _DEFAULT_COMPATIBLE_TYPES))[0]


def _compatible_types_for(field_type: FieldType) -> frozenset[str]:
    """Return the set of compatible ``information_schema`` data types."""
    return _FIELD_TYPE_PG.get(field_type, (_DEFAULT_DDL_TYPE, _DEFAULT_COMPATIBLE_TYPES))[1]


def _walk_field_types(items: list[Any], prefix: str = "") -> Any:
    """Yield ``(column_name, field_type)`` for tabular flattening.

    Mirrors the traversal in ``services/sinks/mapper.py`` (GROUP ->
    ``parent__child``, ARRAY not expanded). Duplicated locally, rather than
    importing the mapper's private helper, to keep this sink's file
    self-contained.
    """
    for item in items:
        if isinstance(item, FormSubsection):
            yield from _walk_field_types(item.fields, prefix)
            continue
        name = f"{prefix}__{item.field_id}" if prefix else item.field_id
        if item.field_type == FieldType.GROUP and item.children:
            yield from _walk_field_types(item.children, name)
        else:
            yield name, item.field_type


def _field_types_for(form: FormSchema) -> dict[str, FieldType]:
    """Return a ``{column_name: field_type}`` map for every tabular column."""
    types: dict[str, FieldType] = {}
    for section in form.sections:
        for name, field_type in _walk_field_types(list(section.fields)):
            types[name] = field_type
    return types


class PostgresTableSink(AbstractSubmissionSink):
    """Arbitrary Postgres table owned by a single form.

    Args:
        target: The validated :class:`PostgresTableTarget` this sink writes
            to.
        alias_registry: Resolves ``target.connection`` to a DSN.
        tenant: Tenant scope used to resolve the connection alias.
        pool: An existing ``asyncpg``-compatible pool. When provided, this
            sink does NOT own it and will not close it. Primarily for
            tests (a fake pool) or externally managed pools.
        min_size: Minimum pool size when this sink creates its own pool.
        max_size: Maximum pool size when this sink creates its own pool.
        **pool_kwargs: Extra kwargs forwarded to ``asyncpg.create_pool()``.
    """

    def __init__(
        self,
        target: PostgresTableTarget,
        *,
        alias_registry: SinkAliasRegistry,
        tenant: str,
        pool: Any | None = None,
        min_size: int = 2,
        max_size: int = 10,
        **pool_kwargs: Any,
    ) -> None:
        self._target = target
        self._alias_registry = alias_registry
        self._tenant = tenant
        self._pool: Any | None = pool
        self._owns_pool: bool = pool is None
        self._min_size = min_size
        self._max_size = max_size
        self._pool_kwargs = pool_kwargs
        self._known_field_types: dict[str, FieldType] = {}
        self.logger = logging.getLogger(__name__)

    @property
    def capabilities(self) -> frozenset[SinkCapability]:
        """Full capability set — the reference sink implementation."""
        return frozenset(
            {
                SinkCapability.WRITE,
                SinkCapability.READ,
                SinkCapability.LIST,
                SinkCapability.PROVISION,
                SinkCapability.EXTEND,
            }
        )

    # ------------------------------------------------------------------
    # Identifier resolution / SQL builders
    # ------------------------------------------------------------------

    def _qualified(self) -> str:
        return qualified_table(self._target.schema_name, self._target.table)

    def _create_table_sql(self) -> str:
        """Idempotent ``CREATE TABLE`` DDL for the reserved column set."""
        qt = self._qualified()
        reserved_sql = ",\n            ".join(
            f'"{name}" {ddl}' for name, ddl in _RESERVED_COLUMN_DDL.items()
        )
        form_uid_idx = validate_identifier(
            f"idx_{self._target.table}_form_uid", kind="index"
        )
        root_idx = validate_identifier(
            f"idx_{self._target.table}_root_submission_id", kind="index"
        )
        return f"""
        CREATE TABLE IF NOT EXISTS {qt} (
            {reserved_sql}
        );
        CREATE INDEX IF NOT EXISTS "{form_uid_idx}" ON {qt}(form_uid);
        CREATE INDEX IF NOT EXISTS "{root_idx}" ON {qt}(root_submission_id);
        """

    def _add_column_sql(self, column: str, ddl_type: str) -> str:
        """Additive ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` statement."""
        qt = self._qualified()
        validate_identifier(column, kind="column")
        return f'ALTER TABLE {qt} ADD COLUMN IF NOT EXISTS "{column}" {ddl_type}'

    def _existing_columns_sql(self) -> str:
        return (
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = $1 AND table_name = $2"
        )

    def _insert_sql(
        self,
        columns: list[str] | None = None,
        *,
        jsonb_columns: frozenset[str] = frozenset({"context"}),
    ) -> str:
        """Build an ``INSERT`` statement for ``columns`` (default: reserved only).

        Any column named in ``jsonb_columns`` uses the ``$n::text::jsonb``
        parameter form — NEVER a bare ``$n::jsonb`` — because a
        host-provided pool may register a json/jsonb codec and double-encode
        the value (see ``services/storage.py:178``).
        """
        qt = self._qualified()
        cols = columns if columns is not None else list(_RESERVED_COLUMN_DDL.keys())
        quoted_cols = ", ".join(f'"{c}"' for c in cols)
        placeholders = [
            f"${i}::text::jsonb" if col in jsonb_columns else f"${i}"
            for i, col in enumerate(cols, start=1)
        ]
        return f'INSERT INTO {qt} ({quoted_cols}) VALUES ({", ".join(placeholders)})'

    def _all_sql_for_test(self) -> list[str]:
        """Return every SQL statement this sink can generate (test helper)."""
        return [
            self._create_table_sql(),
            self._add_column_sql("sample_column", "TEXT"),
            self._insert_sql(),
        ]

    # ------------------------------------------------------------------
    # Pool lifecycle
    # ------------------------------------------------------------------

    async def _ensure_pool(self) -> Any:
        if self._pool is None:
            try:
                dsn = self._alias_registry.resolve_dsn(
                    self._target.connection, tenant=self._tenant
                )
                import asyncpg  # lazy runtime import

                self._pool = await asyncpg.create_pool(
                    dsn=dsn,
                    min_size=self._min_size,
                    max_size=self._max_size,
                    **self._pool_kwargs,
                )
                self.logger.info(
                    "PostgresTableSink: created asyncpg pool for alias %r",
                    self._target.connection,
                )
            except Exception as exc:
                raise SinkUnavailableError(
                    f"Cannot connect to Postgres sink "
                    f"{self._target.connection!r}: {exc}"
                ) from exc
        return self._pool

    async def close(self) -> None:
        """Close the pool if this sink owns it. Idempotent."""
        if self._owns_pool and self._pool is not None:
            await self._pool.close()
            self.logger.info("PostgresTableSink: pool closed")
        self._pool = None
        self._owns_pool = False

    # ------------------------------------------------------------------
    # AbstractSubmissionSink implementation
    # ------------------------------------------------------------------

    async def ensure_target(self, form: FormSchema) -> None:
        """Create the table if absent, then additively extend it.

        Args:
            form: The form whose columns must all exist on the table.

        Raises:
            SinkTargetMismatchError: If an existing column's type is
                incompatible with what this form will send.
            SinkUnavailableError: If the connection cannot be established.
        """
        field_types = _field_types_for(form)
        self._known_field_types = field_types

        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                await conn.execute(self._create_table_sql())

                rows = await conn.fetch(
                    self._existing_columns_sql(),
                    self._target.schema_name,
                    self._target.table,
                )
                existing = {row["column_name"]: row["data_type"] for row in rows}

                for column in column_names_for(form):
                    if column in _RESERVED_COLUMN_DDL:
                        continue  # already covered by _create_table_sql
                    field_type = field_types.get(column)
                    compatible = (
                        _compatible_types_for(field_type)
                        if field_type is not None
                        else _DEFAULT_COMPATIBLE_TYPES
                    )
                    if column in existing:
                        if existing[column] not in compatible:
                            raise SinkTargetMismatchError(
                                f"Column {column!r} exists as "
                                f"{existing[column]!r}, incompatible with "
                                f"form field type {field_type!r}"
                            )
                        continue
                    ddl_type = (
                        _ddl_type_for(field_type)
                        if field_type is not None
                        else _DEFAULT_DDL_TYPE
                    )
                    await conn.execute(self._add_column_sql(column, ddl_type))
        except SinkTargetMismatchError:
            raise
        except SinkUnavailableError:
            raise
        except Exception as exc:
            raise SinkUnavailableError(
                f"Postgres sink {self._target.connection!r} unavailable "
                f"during ensure_target: {exc}"
            ) from exc

    async def write(self, submission: FormSubmission, payload: Any) -> str:
        """Insert one row from a flattened payload dict.

        Args:
            submission: The submission record being persisted (used only
                for its ``submission_id`` on success).
            payload: The flattened row produced by
                :func:`~parrot_formdesigner.services.sinks.mapper.
                flatten_submission`.

        Returns:
            The persisted ``submission_id``.

        Raises:
            SinkUnavailableError: If the write fails (connection or query).
        """
        if not isinstance(payload, dict):
            raise TypeError(
                "PostgresTableSink.write() expects a flattened dict payload"
            )

        jsonb_columns = {"context"} | {
            column
            for column, field_type in self._known_field_types.items()
            if field_type == FieldType.ARRAY
        }

        columns = list(payload.keys())
        values = []
        for column in columns:
            value = payload[column]
            if column in jsonb_columns and not isinstance(value, str):
                value = json.dumps(value) if value is not None else None
            values.append(value)

        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    self._insert_sql(columns, jsonb_columns=frozenset(jsonb_columns)),
                    *values,
                )
        except SinkUnavailableError:
            raise
        except Exception as exc:
            raise SinkUnavailableError(
                f"Postgres sink {self._target.connection!r} unavailable "
                f"during write: {exc}"
            ) from exc

        return submission.submission_id

    def _row_to_submission(self, row: Any) -> FormSubmission:
        """Map a row (reserved columns + form columns) onto a `FormSubmission`.

        Every non-reserved column is folded back into ``data``.
        """
        row_dict = dict(row)
        data = {k: v for k, v in row_dict.items() if k not in _RESERVED_COLUMN_DDL}
        context = row_dict.get("context")
        if isinstance(context, str):
            context = json.loads(context)
        return FormSubmission(
            submission_id=row_dict["submission_id"],
            form_uid=row_dict["form_uid"],
            form_id=row_dict["form_id"],
            form_version=row_dict["form_version"],
            data=data,
            is_valid=True,
            created_at=row_dict["created_at"],
            tenant=row_dict.get("tenant"),
            user_id=row_dict.get("user_id"),
            username=row_dict.get("username"),
            org_id=row_dict.get("org_id"),
            submitted_at=row_dict.get("submitted_at"),
            ip=str(row_dict["ip"]) if row_dict.get("ip") is not None else None,
            user_agent=row_dict.get("user_agent"),
            locale=row_dict.get("locale"),
            root_submission_id=row_dict.get("root_submission_id"),
            revision=row_dict.get("revision"),
            context=context,
        )

    async def read(self, submission_id: str) -> FormSubmission | None:
        """Fetch a single submission by ``submission_id``."""
        self.require(SinkCapability.READ)
        qt = self._qualified()
        sql = f"SELECT * FROM {qt} WHERE submission_id = $1"
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(sql, submission_id)
        except Exception as exc:
            raise SinkUnavailableError(
                f"Postgres sink {self._target.connection!r} unavailable "
                f"during read: {exc}"
            ) from exc
        return self._row_to_submission(row) if row is not None else None

    async def list_revisions(self, root_submission_id: str) -> list[FormSubmission]:
        """Return the full revision chain, oldest first."""
        self.require(SinkCapability.LIST)
        qt = self._qualified()
        sql = (
            f"SELECT * FROM {qt} WHERE root_submission_id = $1 "
            "ORDER BY revision ASC"
        )
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, root_submission_id)
        except Exception as exc:
            raise SinkUnavailableError(
                f"Postgres sink {self._target.connection!r} unavailable "
                f"during list_revisions: {exc}"
            ) from exc
        return [self._row_to_submission(row) for row in rows]
