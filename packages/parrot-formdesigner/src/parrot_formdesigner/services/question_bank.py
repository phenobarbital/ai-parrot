"""QuestionBankService — tenant-scoped library of reusable field definitions.

Provides CRUD operations on ``ReusableField`` entries stored in a dedicated
``field_bank`` table (JSONB-backed), mirroring the ``form_schemas`` DDL
pattern from ``services/storage.py``.  Unit tests use the built-in in-memory
store; the ``db=`` constructor kwarg plugs in an asyncdb/asyncpg connection
for production use.

FEAT-300 — Module 3.
"""

from __future__ import annotations

import copy
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..core.schema import FormField
from ..core.types import FieldType  # noqa: F401 — re-exported for convenience
from ._identifiers import qualified_table, validate_identifier
from .registry import FormStorage


class ReusableField(BaseModel):
    """A single entry in the tenant's QuestionBank.

    Attributes:
        field_id: Unique identifier for this bank entry (UUID string).
        definition: The canonical ``FormField`` definition.
        tenant: Tenant slug that owns this entry.
        usage_forms: Number of forms that reference this entry.
        usage_responses: Cumulative response count across all referencing forms.
        created_at: UTC timestamp of creation.
    """

    model_config = ConfigDict(extra="forbid")

    field_id: str
    definition: FormField
    tenant: str
    usage_forms: int = 0
    usage_responses: int = 0
    created_at: datetime | None = None


class ReusableFieldRef(BaseModel):
    """A reference to a ``ReusableField`` with optional field-level overrides.

    When resolved via :meth:`QuestionBankService.resolve_ref`, the returned
    ``FormField`` is a deep copy of the bank definition with ``overrides``
    applied on top.

    Attributes:
        bank_field_id: The ``ReusableField.field_id`` to look up.
        overrides: Optional dict of ``FormField`` field-level attribute
            overrides (e.g. ``{"label": "New Label", "required": True}``).
    """

    model_config = ConfigDict(extra="forbid")

    bank_field_id: str
    overrides: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# DDL (for Postgres — used in production via db= constructor kwarg)
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table} (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    field_id VARCHAR(255) NOT NULL,
    definition_json JSONB NOT NULL,
    tenant VARCHAR(63) NOT NULL,
    usage_forms INTEGER NOT NULL DEFAULT 0,
    usage_responses INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(field_id, tenant)
);
"""

_INSERT_SQL = """
INSERT INTO {table} (field_id, definition_json, tenant)
VALUES ($1, $2::jsonb, $3)
ON CONFLICT (field_id, tenant) DO NOTHING
"""

_SELECT_SQL = "SELECT * FROM {table} WHERE field_id = $1 AND tenant = $2"

_SELECT_ALL_SQL = "SELECT * FROM {table} WHERE tenant = $1 ORDER BY field_id"

_INCREMENT_SQL = """
UPDATE {table}
SET usage_forms = usage_forms + $1,
    usage_responses = usage_responses + $2
WHERE field_id = $3 AND tenant = $4
"""


class QuestionBankService:
    """Tenant-scoped service for managing reusable field definitions.

    Backs a ``field_bank`` table (one per tenant schema) that stores
    ``FormField`` definitions as JSONB, with usage counters.  In tests
    the in-memory fallback (internal dict) is used automatically when no
    ``db=`` connection is provided.

    Example::

        svc = QuestionBankService(storage, tenant="navigator")
        created = await svc.create_field(my_field)
        await svc.increment_usage(created.field_id, forms=1)
        ref = ReusableFieldRef(bank_field_id=created.field_id,
                               overrides={"label": "Custom"})
        field = await svc.resolve_ref(ref)

    Args:
        storage: ``FormStorage`` instance (used for tenant-schema resolution
            in production).  The service uses ``storage`` for context but
            manages the ``field_bank`` table itself.
        tenant: Tenant slug scoping all operations.
        db: Optional asyncdb/asyncpg DB connection.  When ``None``, the
            service operates in-memory (suitable for tests and development).
        table: Table name inside the tenant schema. Defaults to
            ``"field_bank"``.
    """

    def __init__(
        self,
        storage: FormStorage,
        *,
        tenant: str,
        db: Any | None = None,
        table: str = "field_bank",
    ) -> None:
        self._storage = storage
        # Guard against SQL injection: tenant comes from the auth session and
        # both names are interpolated into DDL/DML — same pattern as
        # PostgresFormStorage (storage.py).
        self._tenant = validate_identifier(tenant, kind="tenant")
        self._db = db
        self._table = validate_identifier(table, kind="table")
        self._qualified = qualified_table(self._tenant, self._table)
        self.logger = logging.getLogger(__name__)

        # In-memory fallback store: field_id → ReusableField
        self._mem: dict[str, ReusableField] = {}

    # ------------------------------------------------------------------
    # DDL helper (production use)
    # ------------------------------------------------------------------

    async def _ensure_table(self) -> None:
        """Run ``CREATE TABLE IF NOT EXISTS`` for the field_bank table.

        No-op when operating in-memory (no ``db`` connection).
        """
        if self._db is None:
            return
        qualified = self._qualified
        sql = _CREATE_TABLE_SQL.format(table=qualified)
        await self._db.execute(sql)

    # ------------------------------------------------------------------
    # Public API (all async)
    # ------------------------------------------------------------------

    async def create_field(self, field: FormField) -> ReusableField:
        """Add a field definition to the bank.

        A new ``field_id`` (UUID4) is minted for the bank entry regardless
        of the source field's ``field_id``.

        Args:
            field: ``FormField`` definition to store.

        Returns:
            ``ReusableField`` with the minted ``field_id``.
        """
        bank_id = str(uuid.uuid4())
        entry = ReusableField(
            field_id=bank_id,
            definition=field,
            tenant=self._tenant,
            created_at=datetime.now(timezone.utc),
        )

        if self._db is not None:
            await self._ensure_table()
            qualified = self._qualified
            sql = _INSERT_SQL.format(table=qualified)
            await self._db.execute(
                sql,
                bank_id,
                json.dumps(field.model_dump(mode="json")),
                self._tenant,
            )
        else:
            self._mem[bank_id] = entry

        self.logger.debug("QuestionBank: created field %s for tenant %s", bank_id, self._tenant)
        return entry

    async def get_field(self, field_id: str) -> ReusableField | None:
        """Retrieve a ``ReusableField`` by its bank ID.

        Args:
            field_id: Bank entry ID (the UUID minted by :meth:`create_field`).

        Returns:
            ``ReusableField`` if found, ``None`` otherwise.
        """
        if self._db is not None:
            await self._ensure_table()
            qualified = self._qualified
            sql = _SELECT_SQL.format(table=qualified)
            row = await self._db.fetchrow(sql, field_id, self._tenant)
            if row is None:
                return None
            return self._row_to_entry(row)
        return self._mem.get(field_id)

    async def list_fields(self) -> list[ReusableField]:
        """List all bank entries for the current tenant.

        Returns:
            List of ``ReusableField`` sorted by ``field_id``.
        """
        if self._db is not None:
            await self._ensure_table()
            qualified = self._qualified
            sql = _SELECT_ALL_SQL.format(table=qualified)
            rows = await self._db.fetch(sql, self._tenant)
            return [self._row_to_entry(r) for r in rows]
        return sorted(self._mem.values(), key=lambda e: e.field_id)

    async def increment_usage(
        self,
        field_id: str,
        *,
        forms: int = 0,
        responses: int = 0,
    ) -> None:
        """Atomically increment usage counters.

        Uses a single UPDATE (no read-modify-write) to avoid race conditions.

        Args:
            field_id: Bank entry ID.
            forms: Number of form references to add.
            responses: Number of response references to add.
        """
        if self._db is not None:
            await self._ensure_table()
            qualified = self._qualified
            sql = _INCREMENT_SQL.format(table=qualified)
            await self._db.execute(sql, forms, responses, field_id, self._tenant)
        else:
            entry = self._mem.get(field_id)
            if entry is not None:
                self._mem[field_id] = entry.model_copy(update={
                    "usage_forms": entry.usage_forms + forms,
                    "usage_responses": entry.usage_responses + responses,
                })

    async def resolve_ref(self, ref: ReusableFieldRef) -> FormField:
        """Resolve a ``ReusableFieldRef`` to a ``FormField``.

        Returns a deep copy of the bank entry's definition, with any
        ``overrides`` merged on top.  The bank entry is never mutated.

        Args:
            ref: ``ReusableFieldRef`` with ``bank_field_id`` and optional
                 ``overrides``.

        Returns:
            ``FormField`` instance.

        Raises:
            KeyError: If ``ref.bank_field_id`` is not found in the bank.
        """
        entry = await self.get_field(ref.bank_field_id)
        if entry is None:
            raise KeyError(f"QuestionBank: field '{ref.bank_field_id}' not found in tenant '{self._tenant}'")

        # Deep copy to avoid mutating the bank entry
        definition_dict = copy.deepcopy(entry.definition.model_dump())

        if ref.overrides:
            definition_dict.update(ref.overrides)

        return FormField.model_validate(definition_dict)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _row_to_entry(self, row: Any) -> ReusableField:
        """Convert a DB row to a ``ReusableField`` instance.

        Args:
            row: asyncpg Record or dict-like object.

        Returns:
            ``ReusableField`` instance.
        """
        definition_data = row["definition_json"]
        if isinstance(definition_data, str):
            definition_data = json.loads(definition_data)
        return ReusableField(
            field_id=row["field_id"],
            definition=FormField.model_validate(definition_data),
            tenant=row["tenant"],
            usage_forms=row.get("usage_forms", 0),
            usage_responses=row.get("usage_responses", 0),
            created_at=row.get("created_at"),
        )
