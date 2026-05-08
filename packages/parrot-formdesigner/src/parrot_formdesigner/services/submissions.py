"""Form submission persistence service.

Provides the ``FormSubmission`` Pydantic model and ``FormSubmissionStorage``
class for persisting form submission records to a PostgreSQL table.
Storage is local-first — data is always saved before optional forwarding
to external endpoints.

Schema, table name, and tenant are configurable. The default schema is
``navigator`` (NOT ``public``) and the default table is ``form_data``
(renamed from the original ``form_submissions``). Pass ``tenant`` at
construction or per-call to target a per-tenant schema such as
``epson.form_data``.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ._identifiers import qualified_table, validate_identifier

if TYPE_CHECKING:
    pass


DEFAULT_SCHEMA = "navigator"
DEFAULT_TABLE = "form_data"


class FormSubmission(BaseModel):
    """Record of a single form data submission.

    Attributes:
        submission_id: Unique identifier for this submission.
        form_id: ID of the form that was submitted.
        form_version: Version of the form at the time of submission.
        data: The validated (sanitized) submission data.
        is_valid: Whether the submission passed form validation.
        forwarded: Whether the submission was forwarded to an external endpoint.
        forward_status: HTTP status code from the forwarding request (if any).
        forward_error: Error message from failed forwarding (if any).
        created_at: UTC timestamp when the submission was created.
        tenant: Optional tenant slug. When set, ``FormSubmissionStorage``
            uses it to resolve the Postgres schema where the submission
            is stored. ``None`` falls back to the storage's default
            schema.
    """

    submission_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique submission identifier",
    )
    form_id: str
    form_version: str
    data: dict[str, Any]
    is_valid: bool
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    tenant: str | None = None


class FormSubmissionStorage:
    """Persist form submissions in a PostgreSQL table.

    Follows the same pattern as ``PostgresFormStorage``: identifier-validated
    SQL, ``asyncpg`` pool management, and an explicit ``initialize()`` step
    that creates the table when the application starts. The target schema
    must already exist.

    Args:
        pool: An active ``asyncpg`` connection pool.
        schema: Postgres schema where the table lives. Default
            ``"navigator"``. Used when no per-call tenant overrides it.
        table_name: Table name within ``schema``. Default ``"form_data"``.
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
        if tenant is not None:
            return validate_identifier(tenant, kind="tenant")
        if self._tenant is not None:
            return self._tenant
        return self._schema

    def _qualified(self, tenant: str | None) -> str:
        return qualified_table(self._resolve_schema(tenant), self._table)

    # ------------------------------------------------------------------
    # SQL builders
    # ------------------------------------------------------------------

    def _create_table_sql(self, tenant: str | None) -> str:
        qt = self._qualified(tenant)
        # Index name must be unique per schema; tie it to the table.
        idx_name = f"idx_{self._table}_form_id"
        validate_identifier(idx_name, kind="index")
        schema = self._resolve_schema(tenant)
        return f"""
        CREATE TABLE IF NOT EXISTS {qt} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            submission_id VARCHAR(255) NOT NULL UNIQUE,
            form_id VARCHAR(255) NOT NULL,
            form_version VARCHAR(50) NOT NULL,
            data JSONB NOT NULL,
            is_valid BOOLEAN NOT NULL DEFAULT TRUE,
            forwarded BOOLEAN NOT NULL DEFAULT FALSE,
            forward_status INTEGER,
            forward_error TEXT,
            tenant VARCHAR(63),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS "{idx_name}"
            ON "{schema}"."{self._table}"(form_id);
        """

    def _insert_sql(self, tenant: str | None) -> str:
        qt = self._qualified(tenant)
        return f"""
        INSERT INTO {qt} (
            submission_id, form_id, form_version, data,
            is_valid, forwarded, forward_status, forward_error,
            tenant, created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def initialize(self, *, tenant: str | None = None) -> None:
        """Create the configured submission table if it does not exist.

        Idempotent. Targets the default schema unless a ``tenant`` is
        provided (or the instance has a default tenant configured). The
        schema itself MUST already exist.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(self._create_table_sql(tenant))
        self.logger.info(
            "FormSubmissionStorage: %s ensured", self._qualified(tenant)
        )

    async def store(
        self,
        submission: FormSubmission,
        *,
        tenant: str | None = None,
    ) -> str:
        """Persist a ``FormSubmission`` record and return its ``submission_id``.

        Args:
            submission: The submission record to insert.
            tenant: Optional per-call tenant override. If omitted, falls
                back to ``submission.tenant``, then the storage's default
                tenant, then ``schema``.

        Returns:
            The ``submission_id`` of the persisted record.
        """
        effective_tenant = (
            tenant if tenant is not None else submission.tenant
        )
        async with self._pool.acquire() as conn:
            await conn.execute(
                self._insert_sql(effective_tenant),
                submission.submission_id,
                submission.form_id,
                submission.form_version,
                json.dumps(submission.data),
                submission.is_valid,
                submission.forwarded,
                submission.forward_status,
                submission.forward_error,
                effective_tenant,
                submission.created_at,
            )
        self.logger.debug(
            "Stored submission %s for form %s in %s",
            submission.submission_id,
            submission.form_id,
            self._qualified(effective_tenant),
        )
        return submission.submission_id
