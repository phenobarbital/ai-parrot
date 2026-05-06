"""Form submission persistence service.

Provides the ``FormSubmission`` Pydantic model and ``FormSubmissionStorage``
class for persisting form submission records to a PostgreSQL ``form_submissions``
table. Storage is local-first — data is always saved before optional forwarding
to external endpoints.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    import asyncpg


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


class FormSubmissionStorage:
    """Persist form submissions in a PostgreSQL ``form_submissions`` table.

    Follows the same pattern as ``PostgresFormStorage``: class-level SQL
    constants, ``asyncpg`` pool management, and an explicit ``initialize()``
    step to create the table when the application starts.

    Args:
        pool: An active ``asyncpg`` connection pool.
    """

    CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS form_submissions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            submission_id VARCHAR(255) NOT NULL UNIQUE,
            form_id VARCHAR(255) NOT NULL,
            form_version VARCHAR(50) NOT NULL,
            data JSONB NOT NULL,
            is_valid BOOLEAN NOT NULL DEFAULT TRUE,
            forwarded BOOLEAN NOT NULL DEFAULT FALSE,
            forward_status INTEGER,
            forward_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_form_submissions_form_id
            ON form_submissions(form_id);
    """

    INSERT_SQL = """
        INSERT INTO form_submissions (
            submission_id, form_id, form_version, data,
            is_valid, forwarded, forward_status, forward_error, created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
    """

    def __init__(self, pool: Any) -> None:
        """Initialise with an asyncpg connection pool.

        Args:
            pool: Active asyncpg Pool — the same pool used by other storage
                components in the application.
        """
        self._pool = pool
        self.logger = logging.getLogger(__name__)

    async def initialize(self) -> None:
        """Create the ``form_submissions`` table if it does not exist.

        Should be called once during application startup before any
        ``store()`` calls.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(self.CREATE_TABLE_SQL)
        self.logger.info("FormSubmissionStorage: table initialised")

    async def store(self, submission: FormSubmission) -> str:
        """Persist a ``FormSubmission`` record and return its ``submission_id``.

        Args:
            submission: The submission record to insert.

        Returns:
            The ``submission_id`` of the persisted record.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                self.INSERT_SQL,
                submission.submission_id,
                submission.form_id,
                submission.form_version,
                json.dumps(submission.data),
                submission.is_valid,
                submission.forwarded,
                submission.forward_status,
                submission.forward_error,
                submission.created_at,
            )
        self.logger.debug(
            "Stored submission %s for form %s",
            submission.submission_id,
            submission.form_id,
        )
        return submission.submission_id
