"""Database model for CommCenter batch/recipient tracking.

``navigator.notification_batch_recipients`` is a FLAT tracking table — one
row per recipient, with ``batch_id`` repeated across every row in a batch.
There is **no separate batches table**: totals are computed by aggregation
(see ``CommCenterService`` fan-out/aggregation logic, spec §3 Module 6).

The ``status`` column encodes the duplicate-delivery containment state
machine (spec §2): ``pending`` -> ``publishing`` (written immediately
before the ``xadd`` call) -> ``queued`` (terminal) or ``publish_failed``
(retryable), with ``skipped`` (terminal) for rows that fail validation.
"""
import uuid
from datetime import datetime

from asyncdb.models import Model
from datamodel import Field
from parrot.conf import PARROT_SCHEMA


class NotificationBatchRecipient(Model):
    """One tracked recipient row within a CommCenter send batch.

    ``batch_id`` is repeated across every row belonging to the same batch;
    batch-level totals are obtained by aggregating over this flat table
    rather than joining against a separate header row.
    """

    id: uuid.UUID = Field(
        primary_key=True,
        required=False,
        default_factory=uuid.uuid4,
    )
    batch_id: uuid.UUID = Field(required=True)
    row_number: int = Field(required=False, default=None)
    provider: str = Field(required=True)
    recipient_name: str | None = Field(required=False, default=None)
    recipient_address: str | None = Field(required=False, default=None)
    status: str = Field(required=True)
    reason: str | None = Field(required=False, default=None)
    message_id: str | None = Field(required=False, default=None)
    published_at: datetime | None = Field(required=False, default=None)
    attempts: int = Field(required=False, default=0)
    template_ref: str | None = Field(required=False, default=None)
    subject: str | None = Field(required=False, default=None)
    created_at: datetime = Field(required=False, default=datetime.now)
    created_by: int | None = Field(required=False, default=None)
    updated_at: datetime = Field(required=False, default=datetime.now)

    class Meta:
        """Meta NotificationBatchRecipient."""

        driver = "pg"
        name = "notification_batch_recipients"
        schema = PARROT_SCHEMA
        strict = True
        frozen = False
