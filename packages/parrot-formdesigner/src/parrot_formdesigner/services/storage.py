"""PostgreSQL Form Storage for the forms abstraction layer.

Implements the FormStorage ABC using asyncpg for PostgreSQL persistence.
Forms are stored as JSONB, supporting versioning and UPSERT operations.

Schema, table name, and tenant are configurable. The default schema is
``navigator`` (NOT ``public``) and the default table is ``form_schemas``.
A tenant slug — when provided — overrides the schema at the SQL level so
the same storage instance can serve many tenants
(``epson.form_schemas``, ``pokemon.form_schemas``, …).

Table columns:
- id: UUID primary key
- form_id: VARCHAR
- version: VARCHAR
- schema_json: JSONB (serialized FormSchema)
- style_json: JSONB (serialized StyleSchema, optional)
- tenant: VARCHAR (nullable; physical-schema indicator captured for audit)
- created_at, updated_at: TIMESTAMPTZ
- created_by: VARCHAR (optional metadata)
- UNIQUE(form_id, version)

Usage:
    pool = await asyncpg.create_pool(dsn="postgresql://...")
    storage = PostgresFormStorage(
        pool=pool,
        schema="navigator",          # default
        table_name="form_schemas",   # default
        tenant=None,                 # default; set for single-tenant deploy
    )
    await storage.initialize()
    await storage.save(form_schema)
    await storage.save(form_schema, tenant="epson")  # → epson.form_schemas
    form = await storage.load("my-form", tenant="epson")
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ._identifiers import qualified_table, validate_identifier
from .registry import FormStorage
from ..core.schema import FormSchema
from ..core.style import StyleSchema

logger = logging.getLogger(__name__)


DEFAULT_SCHEMA = "navigator"
DEFAULT_TABLE = "form_schemas"


class PostgresFormStorage(FormStorage):
    """Persist FormSchema objects in a PostgreSQL table using asyncpg.

    Requires ``asyncpg`` to be installed. The database pool is passed in
    at construction time (no internal connection management). The target
    schema is assumed to exist — it is NOT auto-created. Configure
    per-tenant schemas at the DBA level before using a tenant override.

    Args:
        pool: An active ``asyncpg`` connection pool.
        schema: Postgres schema where the table lives. Default
            ``"navigator"``. Used when no per-call tenant overrides it.
        table_name: Table name within ``schema``. Default
            ``"form_schemas"``.
        tenant: Optional default tenant slug. When set, every operation
            without an explicit ``tenant=`` kwarg targets
            ``<tenant>.<table_name>`` instead of ``<schema>.<table_name>``.
    """

    def __init__(
        self,
        pool: Any,
        *,
        schema: str = DEFAULT_SCHEMA,
        table_name: str = DEFAULT_TABLE,
        tenant: str | None = None,
    ) -> None:
        validate_identifier(schema, kind="schema")
        validate_identifier(table_name, kind="table")
        if tenant is not None:
            validate_identifier(tenant, kind="tenant")

        self._pool = pool
        self._schema = schema
        self._table = table_name
        self._tenant = tenant
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Identifier resolution
    # ------------------------------------------------------------------

    def _resolve_schema(self, tenant: str | None) -> str:
        """Pick the effective schema for an operation.

        Precedence: explicit ``tenant`` arg > instance default tenant >
        configured ``schema``.
        """
        if tenant is not None:
            return validate_identifier(tenant, kind="tenant")
        if self._tenant is not None:
            return self._tenant
        return self._schema

    def _qualified(self, tenant: str | None) -> str:
        return qualified_table(self._resolve_schema(tenant), self._table)

    # ------------------------------------------------------------------
    # SQL builders (identifiers are validated, values are parameterised)
    # ------------------------------------------------------------------

    def _create_table_sql(self, tenant: str | None) -> str:
        qt = self._qualified(tenant)
        return f"""
        CREATE TABLE IF NOT EXISTS {qt} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            form_id VARCHAR(255) NOT NULL,
            version VARCHAR(50) NOT NULL DEFAULT '1.0',
            schema_json JSONB NOT NULL,
            style_json JSONB,
            tenant VARCHAR(63),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by VARCHAR(255),
            UNIQUE(form_id, version)
        );
        """

    def _upsert_sql(self, tenant: str | None) -> str:
        qt = self._qualified(tenant)
        return f"""
        INSERT INTO {qt} (form_id, version, schema_json, style_json, tenant, created_by)
        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6)
        ON CONFLICT (form_id, version)
        DO UPDATE SET
            schema_json = EXCLUDED.schema_json,
            style_json = EXCLUDED.style_json,
            tenant = EXCLUDED.tenant,
            updated_at = NOW()
        """

    def _load_sql(self, tenant: str | None) -> str:
        qt = self._qualified(tenant)
        return f"""
        SELECT schema_json, created_at FROM {qt}
        WHERE form_id = $1
        ORDER BY updated_at DESC
        LIMIT 1
        """

    def _load_version_sql(self, tenant: str | None) -> str:
        qt = self._qualified(tenant)
        return f"""
        SELECT schema_json, created_at FROM {qt}
        WHERE form_id = $1 AND version = $2
        ORDER BY updated_at DESC
        LIMIT 1
        """

    def _delete_sql(self, tenant: str | None) -> str:
        return f"DELETE FROM {self._qualified(tenant)} WHERE form_id = $1"

    def _list_sql(self, tenant: str | None) -> str:
        qt = self._qualified(tenant)
        return f"""
        SELECT DISTINCT ON (form_id)
            form_id,
            version,
            schema_json,
            tenant,
            created_at,
            updated_at
        FROM {qt}
        ORDER BY form_id, updated_at DESC
        """

    # ------------------------------------------------------------------
    # FormStorage implementation
    # ------------------------------------------------------------------

    async def initialize(self, *, tenant: str | None = None) -> None:
        """Create the configured table if it does not exist.

        Idempotent. Targets the default schema unless a ``tenant`` is
        provided (or the instance has a default tenant configured). The
        schema itself MUST already exist — initialize() will not create
        it.

        Args:
            tenant: Optional tenant override; resolves the schema for
                this single call.
        """
        sql = self._create_table_sql(tenant)
        async with self._pool.acquire() as conn:
            await conn.execute(sql)
        self.logger.info(
            "%s ensured", self._qualified(tenant)
        )

    async def save(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        created_by: str | None = None,
        tenant: str | None = None,
    ) -> str:
        """Persist a FormSchema (UPSERT by form_id + version).

        Args:
            form: FormSchema to persist.
            style: Optional associated StyleSchema.
            created_by: Optional creator identifier for audit trail.
            tenant: Optional per-call tenant override. If omitted, falls
                back to ``form.tenant``, then the storage's default
                tenant, then ``schema``.

        Returns:
            The form_id of the saved form.
        """
        effective_tenant = tenant if tenant is not None else form.tenant
        version = getattr(form, "version", "1.0") or "1.0"
        schema_json = form.model_dump_json()
        style_json = style.model_dump_json() if style else None

        async with self._pool.acquire() as conn:
            await conn.execute(
                self._upsert_sql(effective_tenant),
                form.form_id,
                version,
                schema_json,
                style_json,
                effective_tenant,
                created_by,
            )

        self.logger.debug(
            "Saved form %s version %s in %s",
            form.form_id,
            version,
            self._qualified(effective_tenant),
        )
        return form.form_id

    async def load(
        self,
        form_id: str,
        version: str | None = None,
        *,
        tenant: str | None = None,
    ) -> FormSchema | None:
        """Load a FormSchema from PostgreSQL.

        Args:
            form_id: Identifier of the form.
            version: Specific version to load. If None, loads the latest.
            tenant: Optional tenant override; resolves the schema for
                this single call.

        Returns:
            FormSchema if found, None otherwise.
        """
        async with self._pool.acquire() as conn:
            if version is not None:
                row = await conn.fetchrow(
                    self._load_version_sql(tenant), form_id, version
                )
            else:
                row = await conn.fetchrow(self._load_sql(tenant), form_id)

        if row is None:
            return None

        try:
            raw = row["schema_json"]
            if isinstance(raw, str):
                data = json.loads(raw)
            else:
                data = raw
            form = FormSchema.model_validate(data)

            row_created_at = row.get("created_at")
            updates: dict[str, Any] = {}
            if row_created_at is not None and form.created_at is None:
                updates["created_at"] = row_created_at
            # Stamp the resolved tenant if the schema didn't carry one
            resolved = tenant if tenant is not None else self._tenant
            if form.tenant is None and resolved is not None:
                updates["tenant"] = resolved
            if updates:
                form = form.model_copy(update=updates)

            return form
        except Exception as exc:
            self.logger.error(
                "Failed to deserialize form %s: %s", form_id, exc
            )
            return None

    async def delete(
        self,
        form_id: str,
        *,
        tenant: str | None = None,
    ) -> bool:
        """Delete all versions of a form from PostgreSQL.

        Args:
            form_id: Identifier of the form to delete.
            tenant: Optional tenant override; resolves the schema for
                this single call.

        Returns:
            True if at least one row was deleted, False if not found.
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(self._delete_sql(tenant), form_id)

        try:
            count = int(result.split()[-1])
            return count > 0
        except (ValueError, IndexError):
            return False

    async def list_forms(
        self,
        *,
        tenant: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all persisted forms (latest version of each).

        Args:
            tenant: Optional tenant override; resolves the schema for
                this single call.

        Returns:
            List of dicts with keys ``form_id``, ``version``, ``title``,
            ``description``, ``tenant``, and ``created_at``.
            ``description`` may be ``None`` when the form has no
            description; ``created_at`` is an ISO-8601 string or
            ``None``.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(self._list_sql(tenant))

        result: list[dict[str, Any]] = []
        for row in rows:
            entry: dict[str, Any] = {
                "form_id": row["form_id"],
                "version": row["version"],
                "tenant": row["tenant"],
            }
            ts = row["created_at"]
            entry["created_at"] = ts.isoformat() if ts is not None else None

            try:
                raw = row["schema_json"]
                if isinstance(raw, str):
                    data = json.loads(raw)
                else:
                    data = raw

                title = data.get("title", "")
                if isinstance(title, dict):
                    title = next(iter(title.values()), "")
                entry["title"] = str(title) if title else ""

                desc = data.get("description")
                if isinstance(desc, dict):
                    desc = next(iter(desc.values()), None)
                entry["description"] = str(desc) if desc else None
            except Exception as exc:
                self.logger.debug(
                    "Malformed schema_json for form %s: %s",
                    row["form_id"],
                    exc,
                )
                entry["title"] = ""
                entry["description"] = None
            result.append(entry)

        return result
