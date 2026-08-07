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
# ruff: noqa: UP045 -- `datamodel`/`asyncdb.models.Model` field validation does
# not understand PEP 604 `X | None` unions (raises `TypeError: Expected type,
# got types.UnionType` at construction time); `typing.Optional[X]` is required
# here, verified live against this repo's installed `datamodel` package.
import uuid
from datetime import datetime
from typing import Optional

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
    row_number: Optional[int] = Field(required=False, default=None)
    provider: str = Field(required=True)
    recipient_name: Optional[str] = Field(required=False, default=None)
    recipient_address: Optional[str] = Field(required=False, default=None)
    status: str = Field(required=True)
    reason: Optional[str] = Field(required=False, default=None)
    message_id: Optional[str] = Field(required=False, default=None)
    published_at: Optional[datetime] = Field(required=False, default=None)
    attempts: int = Field(required=False, default=0)
    template_ref: Optional[str] = Field(required=False, default=None)
    subject: Optional[str] = Field(required=False, default=None)
    created_at: datetime = Field(required=False, default=datetime.now)
    created_by: Optional[int] = Field(required=False, default=None)
    updated_at: datetime = Field(required=False, default=datetime.now)

    class Meta:
        """Meta NotificationBatchRecipient."""

        driver = "pg"
        name = "notification_batch_recipients"
        schema = PARROT_SCHEMA
        strict = True
        frozen = False
