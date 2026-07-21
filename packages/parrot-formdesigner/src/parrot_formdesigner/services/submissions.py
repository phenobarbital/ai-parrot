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


# Reserved keys that, when produced by metadata enrichment, are promoted
# from the JSONB ``data`` blob to dedicated columns on ``form_data``.
# Order is meaningful — it matches the INSERT column order in
# :meth:`FormSubmissionStorage._insert_sql`.
CORE_METADATA_COLUMNS: tuple[str, ...] = (
    "user_id",
    "username",
    "org_id",
    "submitted_at",
    "ip",
    "user_agent",
    "locale",
)


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
        user_id: Promoted metadata column — authenticated user identifier.
        username: Promoted metadata column — authenticated username.
        org_id: Promoted metadata column — authenticated organization ID.
        submitted_at: Promoted metadata column — wall-clock moment the
            form left the client. Distinct from ``created_at`` (which is
            the DB-insert moment).
        ip: Promoted metadata column — submitter IP address.
        user_agent: Promoted metadata column — submitter User-Agent header.
        locale: Promoted metadata column — BCP-47 locale (e.g. ``en-US``).
        root_submission_id: Revision-chain anchor — the ``submission_id`` of
            the first revision in the chain. Equals this record's own
            ``submission_id`` on revision 1. ``None`` on legacy rows, which
            readers treat as a single-revision chain.
        revision: 1-based position within the revision chain. ``None`` on
            legacy rows.
        context: Optional per-revision audit context (free-form JSONB), e.g.
            geofence status, GPS coordinates, and a post-visit flag.
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
    user_id: str | None = None
    username: str | None = None
    org_id: int | None = None
    submitted_at: datetime | None = None
    ip: str | None = None
    user_agent: str | None = None
    locale: str | None = None
    root_submission_id: str | None = None
    revision: int | None = None
    context: dict[str, Any] | None = None


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
        root_idx_name = f"idx_{self._table}_root_submission_id"
        validate_identifier(root_idx_name, kind="index")
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
            user_id VARCHAR(255),
            username VARCHAR(255),
            org_id INTEGER,
            submitted_at TIMESTAMPTZ,
            ip INET,
            user_agent TEXT,
            locale VARCHAR(35),
            root_submission_id VARCHAR(255),
            revision INTEGER,
            context JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS "{idx_name}"
            ON "{schema}"."{self._table}"(form_id);
        CREATE INDEX IF NOT EXISTS "{root_idx_name}"
            ON "{schema}"."{self._table}"(root_submission_id);
        """

    def _alter_table_sql(self, tenant: str | None) -> str:
        """Idempotent ``ADD COLUMN IF NOT EXISTS`` block for legacy tables.

        Postgres >= 11 makes ``ADD COLUMN IF NOT EXISTS`` a metadata-only
        operation when the column is nullable with no default, so this
        is cheap on existing rows.
        """
        qt = self._qualified(tenant)
        root_idx_name = f"idx_{self._table}_root_submission_id"
        validate_identifier(root_idx_name, kind="index")
        schema = self._resolve_schema(tenant)
        return f"""
        ALTER TABLE {qt}
            ADD COLUMN IF NOT EXISTS user_id VARCHAR(255),
            ADD COLUMN IF NOT EXISTS username VARCHAR(255),
            ADD COLUMN IF NOT EXISTS org_id INTEGER,
            ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS ip INET,
            ADD COLUMN IF NOT EXISTS user_agent TEXT,
            ADD COLUMN IF NOT EXISTS locale VARCHAR(35),
            ADD COLUMN IF NOT EXISTS root_submission_id VARCHAR(255),
            ADD COLUMN IF NOT EXISTS revision INTEGER,
            ADD COLUMN IF NOT EXISTS context JSONB;
        CREATE INDEX IF NOT EXISTS "{root_idx_name}"
            ON "{schema}"."{self._table}"(root_submission_id);
        """

    def _insert_sql(self, tenant: str | None) -> str:
        qt = self._qualified(tenant)
        return f"""
        INSERT INTO {qt} (
            submission_id, form_id, form_version, data,
            is_valid, forwarded, forward_status, forward_error,
            tenant, created_at,
            user_id, username, org_id, submitted_at, ip, user_agent, locale,
            root_submission_id, revision, context
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15, $16, $17,
            $18, $19, $20
        )
        """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def initialize(self, *, tenant: str | None = None) -> None:
        """Create the configured submission table if it does not exist.

        Idempotent. Targets the default schema unless a ``tenant`` is
        provided (or the instance has a default tenant configured). The
        schema itself MUST already exist.

        Runs the metadata-column ``ALTER TABLE ... ADD COLUMN IF NOT
        EXISTS`` block immediately after the ``CREATE TABLE`` so legacy
        ``form_data`` tables pick up the new columns on startup.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(self._create_table_sql(tenant))
            await conn.execute(self._alter_table_sql(tenant))
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
        context_json = (
            json.dumps(submission.context)
            if submission.context is not None
            else None
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
                submission.user_id,
                submission.username,
                submission.org_id,
                submission.submitted_at,
                submission.ip,
                submission.user_agent,
                submission.locale,
                submission.root_submission_id,
                submission.revision,
                context_json,
            )
        self.logger.debug(
            "Stored submission %s for form %s in %s",
            submission.submission_id,
            submission.form_id,
            self._qualified(effective_tenant),
        )
        return submission.submission_id

    # ------------------------------------------------------------------
    # Read API (revision chain)
    # ------------------------------------------------------------------

    # Column list for reads — order is not significant (rows are accessed by
    # name), but it enumerates every column mapped back onto ``FormSubmission``.
    _SELECT_COLUMNS: str = (
        "submission_id, form_id, form_version, data, is_valid, "
        "forwarded, forward_status, forward_error, tenant, created_at, "
        "user_id, username, org_id, submitted_at, ip, user_agent, locale, "
        "root_submission_id, revision, context"
    )

    @staticmethod
    def _row_to_submission(row: Any) -> FormSubmission:
        """Map an ``asyncpg.Record`` back onto a :class:`FormSubmission`.

        Handles the type gaps between the DB and the model: JSONB columns
        (``data``, ``context``) come back as ``str`` unless a codec is set,
        and ``INET`` (``ip``) comes back as an ``ipaddress`` object.
        """

        def _load_json(value: Any) -> Any:
            if value is None or isinstance(value, (dict, list)):
                return value
            return json.loads(value)

        ip = row["ip"]
        return FormSubmission(
            submission_id=row["submission_id"],
            form_id=row["form_id"],
            form_version=row["form_version"],
            data=_load_json(row["data"]) or {},
            is_valid=row["is_valid"],
            forwarded=row["forwarded"],
            forward_status=row["forward_status"],
            forward_error=row["forward_error"],
            tenant=row["tenant"],
            created_at=row["created_at"],
            user_id=row["user_id"],
            username=row["username"],
            org_id=row["org_id"],
            submitted_at=row["submitted_at"],
            ip=str(ip) if ip is not None else None,
            user_agent=row["user_agent"],
            locale=row["locale"],
            root_submission_id=row["root_submission_id"],
            revision=row["revision"],
            context=_load_json(row["context"]),
        )

    async def get_submission(
        self,
        submission_id: str,
        *,
        tenant: str | None = None,
    ) -> FormSubmission | None:
        """Fetch a single submission by ``submission_id``.

        Args:
            submission_id: The unique submission identifier to look up.
            tenant: Optional per-call tenant override (schema resolution).

        Returns:
            The matching :class:`FormSubmission`, or ``None`` if no row
            exists.
        """
        qt = self._qualified(tenant)
        sql = f"SELECT {self._SELECT_COLUMNS} FROM {qt} WHERE submission_id = $1"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, submission_id)
        return self._row_to_submission(row) if row is not None else None

    async def list_revisions(
        self,
        root_submission_id: str,
        *,
        tenant: str | None = None,
    ) -> list[FormSubmission]:
        """Return the full revision chain for a submission, oldest first.

        The chain is every row sharing ``root_submission_id``, ordered by
        ``revision ASC``. Legacy rows written before the revision-chain
        columns existed have ``NULL`` ``root_submission_id``/``revision``
        and are therefore single-revision chains reachable only via their
        own ``submission_id`` (use :meth:`get_submission` for those).

        Args:
            root_submission_id: The chain anchor (revision 1's
                ``submission_id``).
            tenant: Optional per-call tenant override (schema resolution).

        Returns:
            The chain ordered by ``revision`` ascending (empty if none).
        """
        qt = self._qualified(tenant)
        sql = (
            f"SELECT {self._SELECT_COLUMNS} FROM {qt} "
            "WHERE root_submission_id = $1 ORDER BY revision ASC"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, root_submission_id)
        return [self._row_to_submission(row) for row in rows]
