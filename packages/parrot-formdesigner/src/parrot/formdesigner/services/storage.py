"""PostgreSQL Form Storage for the forms abstraction layer.

Implements the FormStorage ABC using asyncpg for PostgreSQL persistence.
Forms are stored as JSONB, supporting versioning and UPSERT operations.

Table: form_schemas
- id: UUID primary key
- form_id: VARCHAR UNIQUE per version
- version: VARCHAR
- schema_json: JSONB (serialized FormSchema)
- style_json: JSONB (serialized StyleSchema, optional)
- created_at, updated_at: TIMESTAMPTZ
- created_by: VARCHAR (optional metadata)

Usage:
    pool = await asyncpg.create_pool(dsn="postgresql://...")
    storage = PostgresFormStorage(pool=pool)
    await storage.initialize()
    await storage.save(form_schema)
    form = await storage.load("my-form")
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from .registry import FormStorage
from ..core.schema import FormSchema
from ..core.style import StyleSchema

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)


class PostgresFormStorage(FormStorage):
    """Persist FormSchema objects in a PostgreSQL table using asyncpg.

    Requires `asyncpg` to be installed. The database pool is passed in
    at construction time (no internal connection management).

    Table name: form_schemas (created via initialize()).

    Example:
        pool = await asyncpg.create_pool(dsn="postgresql://user:pw@host/db")
        storage = PostgresFormStorage(pool=pool)
        await storage.initialize()

        await storage.save(form)
        form = await storage.load("my-form")
        forms = await storage.list_forms()
        await storage.delete("my-form")
    """

    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS form_schemas (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        form_id VARCHAR(255) NOT NULL,
        version VARCHAR(50) NOT NULL DEFAULT '1.0',
        schema_json JSONB NOT NULL,
        style_json JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_by VARCHAR(255),
        UNIQUE(form_id, version)
    );
    """

    UPSERT_SQL = """
    INSERT INTO form_schemas (form_id, version, schema_json, style_json, created_by)
    VALUES ($1, $2, $3::jsonb, $4::jsonb, $5)
    ON CONFLICT (form_id, version)
    DO UPDATE SET
        schema_json = EXCLUDED.schema_json,
        style_json = EXCLUDED.style_json,
        updated_at = NOW()
    """

    LOAD_SQL = """
    SELECT schema_json FROM form_schemas
    WHERE form_id = $1
    ORDER BY updated_at DESC
    LIMIT 1
    """

    LOAD_VERSION_SQL = """
    SELECT schema_json FROM form_schemas
    WHERE form_id = $1 AND version = $2
    ORDER BY updated_at DESC
    LIMIT 1
    """

    DELETE_SQL = """
    DELETE FROM form_schemas WHERE form_id = $1
    """

    LIST_SQL = """
    SELECT DISTINCT ON (form_id) form_id, version, schema_json, updated_at
    FROM form_schemas
    ORDER BY form_id, updated_at DESC
    """

    def __init__(self, pool: Any) -> None:
        """Initialize PostgresFormStorage.

        Args:
            pool: asyncpg connection pool (asyncpg.Pool).
        """
        self._pool = pool
        self.logger = logging.getLogger(__name__)

    async def initialize(self) -> None:
        """Create the form_schemas table if it does not exist.

        This method is idempotent — safe to call on every startup.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(self.CREATE_TABLE_SQL)
        self.logger.info("form_schemas table ensured")

    async def save(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        created_by: str | None = None,
    ) -> str:
        """Persist a FormSchema (UPSERT by form_id + version).

        Args:
            form: FormSchema to persist.
            style: Optional associated StyleSchema.
            created_by: Optional creator identifier for audit trail.

        Returns:
            The form_id of the saved form.
        """
        version = getattr(form, "version", "1.0") or "1.0"
        schema_json = json.dumps(form.model_dump())
        style_json = json.dumps(style.model_dump()) if style else None

        async with self._pool.acquire() as conn:
            await conn.execute(
                self.UPSERT_SQL,
                form.form_id,
                version,
                schema_json,
                style_json,
                created_by,
            )

        self.logger.debug("Saved form %s version %s", form.form_id, version)
        return form.form_id

    async def load(
        self,
        form_id: str,
        version: str | None = None,
    ) -> FormSchema | None:
        """Load a FormSchema from PostgreSQL.

        Args:
            form_id: Identifier of the form.
            version: Specific version to load. If None, loads the latest.

        Returns:
            FormSchema if found, None otherwise.
        """
        async with self._pool.acquire() as conn:
            if version is not None:
                row = await conn.fetchrow(self.LOAD_VERSION_SQL, form_id, version)
            else:
                row = await conn.fetchrow(self.LOAD_SQL, form_id)

        if row is None:
            return None

        try:
            raw = row["schema_json"]
            if isinstance(raw, str):
                data = json.loads(raw)
            else:
                data = raw
            return FormSchema.model_validate(data)
        except Exception as exc:
            self.logger.error(
                "Failed to deserialize form %s: %s", form_id, exc
            )
            return None

    async def delete(self, form_id: str) -> bool:
        """Delete all versions of a form from PostgreSQL.

        Args:
            form_id: Identifier of the form to delete.

        Returns:
            True if at least one row was deleted, False if not found.
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(self.DELETE_SQL, form_id)

        # asyncpg returns "DELETE N" where N is count
        try:
            count = int(result.split()[-1])
            return count > 0
        except (ValueError, IndexError):
            return False

    async def list_forms(self) -> list[dict[str, str]]:
        """List all persisted forms (latest version of each).

        Returns:
            List of dicts with form_id, version, and title (if available).
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(self.LIST_SQL)

        result: list[dict[str, str]] = []
        for row in rows:
            entry: dict[str, str] = {
                "form_id": row["form_id"],
                "version": row["version"],
            }
            # Extract title from schema_json if possible
            try:
                raw = row["schema_json"]
                if isinstance(raw, str):
                    data = json.loads(raw)
                else:
                    data = raw
                title = data.get("title", "")
                if isinstance(title, dict):
                    title = next(iter(title.values()), "")
                entry["title"] = str(title)
            except Exception:
                entry["title"] = ""
            result.append(entry)

        return result
