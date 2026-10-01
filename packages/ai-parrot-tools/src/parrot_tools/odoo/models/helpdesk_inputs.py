"""Pydantic input schemas for :class:`~parrot_tools.odoo.helpdesk.OdooHelpdeskToolkit` tools."""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import Field, model_validator

from .inputs import OdooDomain, _OdooBaseInput


#: An Odoo id, or the record's name (resolved server-side; ambiguous names are rejected).
Ref = Union[int, str]
_REF_DESC = "Odoo id, or the record's name (exact match first, then unique partial match)"


class TicketIdInput(_OdooBaseInput):
    """Input with a required helpdesk ticket identifier."""

    ticket_id: int = Field(..., ge=1, description="sh.helpdesk.ticket id")


class GetTicketInput(TicketIdInput):
    """Input for retrieving a ticket."""

    include_extra_fields: bool = Field(default=True, description="Fold ticket extra fields into extra_fields")
    include_history: bool = Field(default=False, description="Also load the stage history lines")


class SearchTicketsInput(_OdooBaseInput):
    """Input for searching helpdesk tickets."""

    query: Optional[str] = Field(default=None, description="Substring matched against name, email subject and email")
    stage: Optional[Ref] = Field(default=None, description=f"Stage — {_REF_DESC}")
    team: Optional[Ref] = Field(default=None, description=f"Team — {_REF_DESC}")
    assignee: Optional[Ref] = Field(default=None, description="Assignee user — id, login or name")
    category: Optional[Ref] = Field(default=None, description=f"Category — {_REF_DESC}")
    priority: Optional[Ref] = Field(default=None, description=f"Priority — {_REF_DESC}")
    ticket_type: Optional[Ref] = Field(default=None, description=f"Ticket type — {_REF_DESC}")
    partner_id: Optional[int] = Field(default=None, ge=1, description="Customer partner id")
    created_after: Optional[str] = Field(default=None, description="ISO datetime lower bound on create_date")
    created_before: Optional[str] = Field(default=None, description="ISO datetime upper bound on create_date")
    only_open: bool = Field(default=False, description="Exclude the company's close and cancel stages")
    domain: Optional[OdooDomain] = Field(default=None, description="Extra Odoo domain clauses, AND-ed")
    fields: Optional[list[str]] = Field(default=None, description="Fields to return; default is a compact list")
    limit: int = Field(default=50, ge=1, le=500, description="Maximum tickets to return")
    offset: int = Field(default=0, ge=0, description="Tickets to skip for pagination")
    order: str = Field(default="id desc", description="Odoo sort expression")


class ListMyTicketsInput(_OdooBaseInput):
    """Input for listing the current user's tickets."""

    only_open: bool = Field(default=True, description="Exclude the company's close and cancel stages")
    limit: int = Field(default=50, ge=1, description="Maximum tickets to return")


class GetTicketHistoryInput(TicketIdInput):
    """Input for retrieving ticket stage history."""


class GetTicketMessagesInput(TicketIdInput):
    """Input for retrieving ticket messages."""

    limit: int = Field(default=20, ge=1, description="Maximum messages to return")
    include_notifications: bool = Field(default=False, description="Include notification-only messages")


class GetTicketExtraFieldsInput(TicketIdInput):
    """Input for retrieving custom ticket fields."""


class CreateTicketInput(_OdooBaseInput):
    """Input for creating a helpdesk ticket."""

    subject: str = Field(..., description="Ticket subject (email_subject)")
    partner_id: Optional[int] = Field(default=None, ge=1, description="Existing customer partner id")
    partner_email: Optional[str] = Field(default=None, description="Find or create the customer by email")
    partner_name: Optional[str] = Field(default=None, description="Find or create the customer by exact name")
    description: Optional[str] = Field(default=None, description="Ticket description")
    category: Optional[Ref] = Field(default=None, description=f"Category — {_REF_DESC}")
    sub_category: Optional[Ref] = Field(default=None, description=f"Sub-category — {_REF_DESC}")
    priority: Optional[Ref] = Field(default=None, description=f"Priority — {_REF_DESC}")
    team: Optional[Ref] = Field(default=None, description=f"Team — {_REF_DESC}")
    ticket_type: Optional[Ref] = Field(default=None, description=f"Ticket type — {_REF_DESC}")
    tags: Optional[list[Ref]] = Field(default=None, description="Ticket tag ids or names")
    assignee: Optional[Ref] = Field(default=None, description="Initial assignee user — id, login or name")
    email: Optional[str] = Field(default=None, description="Customer email address")
    mobile_no: Optional[str] = Field(default=None, description="Customer mobile number")
    person_name: Optional[str] = Field(default=None, description="Contact person name")
    due_date: Optional[str] = Field(default=None, description="ISO due date")
    replied_status: Literal["customer_replied", "staff_replied"] = Field(
        default="customer_replied", description="Initial reply direction"
    )

    @model_validator(mode="after")
    def _require_partner_ref(self) -> "CreateTicketInput":
        """Require an existing or discoverable customer reference."""
        if self.partner_id is None and not self.partner_email and not self.partner_name:
            raise ValueError("one of partner_id, partner_email or partner_name is required")
        return self


class UpdateTicketInput(TicketIdInput):
    """Explicit ticket patch without lifecycle, assignment, or SLA fields."""

    subject: Optional[str] = Field(default=None, description="Ticket subject (email_subject)")
    description: Optional[str] = Field(default=None, description="Ticket description")
    comment: Optional[str] = Field(default=None, description="Internal ticket comment")
    customer_comment: Optional[str] = Field(default=None, description="Customer-visible ticket comment")
    email: Optional[str] = Field(default=None, description="Customer email address")
    email_cc: Optional[str] = Field(default=None, description="Carbon-copy email recipients")
    mobile_no: Optional[str] = Field(default=None, description="Customer mobile number")
    person_name: Optional[str] = Field(default=None, description="Contact person name")
    due_date: Optional[str] = Field(default=None, description="ISO due date")
    category: Optional[Ref] = Field(default=None, description=f"Category — {_REF_DESC}")
    sub_category: Optional[Ref] = Field(default=None, description=f"Sub-category — {_REF_DESC}")
    priority: Optional[Ref] = Field(default=None, description=f"Priority — {_REF_DESC}")
    team: Optional[Ref] = Field(default=None, description=f"Team — {_REF_DESC}")
    ticket_type: Optional[Ref] = Field(default=None, description=f"Ticket type — {_REF_DESC}")
    tags: Optional[list[Ref]] = Field(default=None, description="Ticket tag ids or names")


class AddTicketCommentInput(TicketIdInput):
    """Input for posting a ticket message."""

    body: str = Field(..., description="Message body; HTML is allowed")
    internal: bool = Field(default=True, description="True for an internal note; false for a public comment")
    attachment_ids: Optional[list[int]] = Field(default=None, description="Existing attachment ids to include")


class AttachToTicketInput(TicketIdInput):
    """Input for attaching a document to a ticket."""

    name: str = Field(..., description="Attachment file name")
    source: str = Field(..., description="HTTP(S) URL or base64-encoded attachment content")
    mimetype: Optional[str] = Field(default=None, description="Attachment MIME type")
    description: Optional[str] = Field(default=None, description="Attachment description")


class AssignTicketInput(TicketIdInput):
    """Input for assigning a ticket."""

    assignee: Ref = Field(..., description="Primary assignee user — id, login or name")
    additional_assignees: Optional[list[Ref]] = Field(default=None, description="Additional assignee ids, logins or names")


class TakeTicketInput(TicketIdInput):
    """Input for assigning the current user to a ticket."""


class ReassignTicketInput(TicketIdInput):
    """Input for reassigning a ticket."""

    new_assignee: Ref = Field(..., description="New assignee user — id, login or name")


class MoveTicketToStageInput(TicketIdInput):
    """Input for moving a ticket to a stage."""

    stage: Ref = Field(..., description=f"Target stage — {_REF_DESC}")
    expected_current_stage: Optional[Ref] = Field(default=None, description="Abort unless the ticket is in this stage")


class CloseTicketInput(TicketIdInput):
    """Input for closing a ticket."""

    comment: Optional[str] = Field(default=None, description="Internal note posted before closing")


class ReopenTicketInput(TicketIdInput):
    """Input for reopening a ticket."""

    to_stage: Optional[Ref] = Field(default=None, description="Reopen stage; default is the company reopen stage or Open")


class ResolveTicketInput(TicketIdInput):
    """Input for resolving a ticket."""


class ApproveTicketInput(TicketIdInput):
    """Input for approving a ticket."""


class CancelTicketInput(TicketIdInput):
    """Input for cancelling a ticket."""

    reason: str = Field(..., min_length=1, description="Stored in cancel_reason before cancellation")


class ListSlaPoliciesInput(_OdooBaseInput):
    """Input for listing SLA policies."""

    team: Optional[Ref] = Field(default=None, description=f"Team — {_REF_DESC}")
    ticket_type: Optional[Ref] = Field(default=None, description=f"Ticket type — {_REF_DESC}")
    limit: int = Field(default=50, ge=1, description="Maximum policies to return")


class CreateSlaPolicyInput(_OdooBaseInput):
    """Input for creating an SLA policy."""

    name: str = Field(..., description="SLA policy name")
    team: Ref = Field(..., description=f"Team the policy applies to — {_REF_DESC}")
    days: int = Field(default=0, ge=0, description="SLA duration days")
    hours: int = Field(default=0, ge=0, description="SLA duration hours")
    minutes: int = Field(default=0, ge=0, description="SLA duration minutes")
    target_type: Literal["reaching_stage", "assign_to"] = Field(
        default="reaching_stage", description="SLA target type"
    )
    stage: Optional[Ref] = Field(default=None, description="Required target stage for reaching_stage policies")
    ticket_type: Optional[Ref] = Field(default=None, description=f"Ticket type — {_REF_DESC}")

    @model_validator(mode="after")
    def _check_duration_and_stage(self) -> "CreateSlaPolicyInput":
        """Validate the required SLA duration and stage target."""
        if self.days + self.hours + self.minutes == 0:
            raise ValueError("at least one of days, hours or minutes must be greater than zero")
        if self.target_type == "reaching_stage" and self.stage is None:
            raise ValueError("stage is required when target_type is reaching_stage")
        return self


class UpdateSlaPolicyInput(_OdooBaseInput):
    """Input for updating an SLA policy."""

    sla_id: int = Field(..., ge=1, description="sh.helpdesk.sla id")
    name: Optional[str] = Field(default=None, description="SLA policy name")
    days: Optional[int] = Field(default=None, ge=0, description="SLA duration days")
    hours: Optional[int] = Field(default=None, ge=0, description="SLA duration hours")
    minutes: Optional[int] = Field(default=None, ge=0, description="SLA duration minutes")
    target_type: Optional[Literal["reaching_stage", "assign_to"]] = Field(default=None, description="SLA target type")
    stage: Optional[Ref] = Field(default=None, description=f"Target stage — {_REF_DESC}")
    ticket_type: Optional[Ref] = Field(default=None, description=f"Ticket type — {_REF_DESC}")


class GetTicketSlaStatusInput(TicketIdInput):
    """Input for retrieving a ticket's SLA status."""


class ListTicketAlarmsInput(_OdooBaseInput):
    """Input for listing ticket alarms."""

    limit: int = Field(default=50, ge=1, description="Maximum alarms to return")


class ListReferenceInput(_OdooBaseInput):
    """Input shared by helpdesk reference-data list tools."""

    limit: int = Field(default=100, ge=1, description="Maximum reference records to return")


class TicketStatsInput(_OdooBaseInput):
    """Input for aggregating ticket statistics."""

    group_by: Literal["stage_id", "team_id", "user_id", "category_id", "priority", "ticket_type"] = Field(
        default="stage_id", description="Ticket field used to group counts"
    )
    only_open: bool = Field(default=False, description="Exclude the company's close and cancel stages")
    domain: Optional[OdooDomain] = Field(default=None, description="Extra Odoo domain clauses, AND-ed")
    created_after: Optional[str] = Field(default=None, description="ISO datetime lower bound on create_date")
    created_before: Optional[str] = Field(default=None, description="ISO datetime upper bound on create_date")


class MergeTicketsInput(_OdooBaseInput):
    """Input for merging two or more tickets."""

    ticket_ids: list[int] = Field(..., min_length=2, description="Ticket ids to merge")
    into_ticket_id: Optional[int] = Field(default=None, ge=1, description="Target ticket id; omit to create a new ticket")
    merged_action: Literal["close", "cancel", "done", "remove", "do_nothing"] = Field(
        default="close", description="Action applied to merged source tickets"
    )
    merge_history: bool = Field(default=True, description="Copy source ticket history into the target")


class MassUpdateTicketsInput(_OdooBaseInput):
    """Input for applying one or more changes to tickets."""

    ticket_ids: list[int] = Field(..., min_length=1, description="Ticket ids to update")
    stage: Optional[Ref] = Field(default=None, description=f"Target stage — {_REF_DESC}")
    assignee: Optional[Ref] = Field(default=None, description="Primary assignee user — id, login or name")
    team: Optional[Ref] = Field(default=None, description=f"Target team — {_REF_DESC}")
    add_followers: Optional[list[int]] = Field(default=None, description="Partner ids to add as followers")
    remove_followers: Optional[list[int]] = Field(default=None, description="Partner ids to remove as followers")

    @model_validator(mode="after")
    def _require_change(self) -> "MassUpdateTicketsInput":
        """Require at least one effective update operation."""
        if (
            self.stage is None
            and self.assignee is None
            and self.team is None
            and not self.add_followers
            and not self.remove_followers
        ):
            raise ValueError("at least one change is required")
        return self


class StartTicketTimerInput(TicketIdInput):
    """Input for starting a ticket timer."""


class StopTicketTimerInput(TicketIdInput):
    """Input for stopping a ticket timer."""

    description: Optional[str] = Field(default=None, description="Description for the recorded time entry")
