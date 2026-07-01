"""Pydantic v2 models for GigSmart timesheets and disputes API surfaces.

Important: there is NO ``TimesheetState`` enum in the GigSmart schema.
Timesheet lifecycle is tracked via ``EngagementStateName``
(``PENDING_TIMESHEET_APPROVAL``, ``DISBURSED``) plus the ``is_approved``
boolean on :class:`EngagementTimesheet`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict


class EngagementTimesheet(BaseModel):
    """A GigSmart engagement timesheet record.

    Variants: ADMIN, FINAL, LATEST, REQUESTER, SYSTEM, WORKER.
    Payment styles: CALCULATED, FIXED_AMOUNT, FIXED_HOURS.

    Args:
        id: Opaque prefixed timesheet ID (e.g. ``"engts_9fesLHHFy0By8MC6FvbYiv"``).
        engagement_id: Parent engagement ID.
        is_approved: True when the requester has approved this timesheet.
        variant: Which timesheet variant this record represents.
        payment_style: How payment is calculated.
    """

    model_config = ConfigDict(populate_by_name=True)
    id: str
    engagement_id: str | None = Field(default=None, alias="engagementId")
    is_approved: bool = Field(default=False, alias="isApproved")
    variant: str | None = None
    payment_style: str | None = Field(default=None, alias="paymentStyle")


class ApproveEngagementTimesheetInput(BaseModel, frozen=True):
    """Input for the ``approveEngagementTimesheet`` mutation.

    Args:
        timesheet_id: Opaque ID of the timesheet to approve.
        mutation_lock: Optional optimistic-concurrency lock token.
    """

    model_config = ConfigDict(populate_by_name=True)
    timesheet_id: str = Field(alias="timesheetId")
    mutation_lock: str | None = Field(default=None, alias="mutationLock")


class RemoveEngagementTimesheetInput(BaseModel, frozen=True):
    """Input for the ``removeEngagementTimesheet`` mutation.

    This rejects the timesheet and allows the worker to resubmit.
    It does NOT delete the timesheet record.

    Args:
        timesheet_id: Opaque ID of the timesheet to reject/send back.
    """

    model_config = ConfigDict(populate_by_name=True)
    timesheet_id: str = Field(alias="timesheetId")


class AddEngagementDisputeInput(BaseModel, frozen=True):
    """Input for the ``addEngagementDispute`` mutation.

    Args:
        engagement_id: The engagement on which to file a dispute.
    """

    model_config = ConfigDict(populate_by_name=True)
    engagement_id: str = Field(alias="engagementId")


class SetEngagementDisputeApprovalInput(BaseModel, frozen=True):
    """Input for the ``setEngagementDisputeApproval`` mutation.

    Allows the requester to accept or reject a worker's dispute.

    Args:
        dispute_id: Opaque ID of the dispute to resolve.
        accept: ``True`` to accept the dispute; ``False`` to reject it.
        response_note: Optional explanation of the resolution decision.
    """

    model_config = ConfigDict(populate_by_name=True)
    dispute_id: str = Field(alias="disputeId")
    accept: bool
    response_note: str | None = Field(default=None, alias="responseNote")
