"""Result envelopes returned by :class:`~parrot_tools.odoo.helpdesk.OdooHelpdeskToolkit` tools."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .entities import Many2one
from .envelopes import FieldSelectionMetadata
from .helpdesk_entities import (
    HelpdeskMessage,
    HelpdeskSla,
    HelpdeskSlaStatus,
    HelpdeskStageInfo,
    HelpdeskTicket,
    HelpdeskTicketAlarm,
)


class HelpdeskReferenceItem(BaseModel):
    """A named helpdesk reference record."""

    id: int
    name: str
    extra: dict[str, Any] = Field(default_factory=dict)


class HelpdeskReferenceResult(BaseModel):
    """Result of the ``list_helpdesk_*`` reference-data tools."""

    kind: str = Field(..., description="Odoo model technical name")
    items: list[HelpdeskReferenceItem] = Field(default_factory=list)
    total: int = 0


class TicketResult(BaseModel):
    """A helpdesk ticket with its Odoo URL."""

    ticket: HelpdeskTicket
    url: str
    model: str = "sh.helpdesk.ticket"
    history: list[HelpdeskStageInfo] = Field(default_factory=list, description="Stage history when requested")
    model_config = ConfigDict(protected_namespaces=())


class TicketListResult(BaseModel):
    """A paginated collection of helpdesk tickets."""

    tickets: list[HelpdeskTicket] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
    fields: list[str] = Field(default_factory=list)
    metadata: Optional[FieldSelectionMetadata] = None


class TicketHistoryResult(BaseModel):
    """Stage-history lines for a helpdesk ticket."""

    ticket_id: int
    lines: list[HelpdeskStageInfo] = Field(default_factory=list)
    total: int = 0


class TicketMessagesResult(BaseModel):
    """Messages posted to a helpdesk ticket."""

    ticket_id: int
    messages: list[HelpdeskMessage] = Field(default_factory=list)
    total: int = 0


class TicketExtraFieldsResult(BaseModel):
    """Custom extra-field values and labels for a ticket."""

    ticket_id: int
    fields: dict[str, str] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    count: int = 0


class TicketTransitionResult(BaseModel):
    """Outcome of a transition verified through a post-condition read."""

    ticket_id: int
    action: str
    applied: bool
    method_used: Literal["action", "stage_write", "none"]
    from_stage: Optional[str] = None
    to_stage: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    ticket: HelpdeskTicket


class TicketCommentResult(BaseModel):
    """Outcome of posting a ticket comment."""

    ticket_id: int
    message_id: int
    internal: bool
    reopened: bool
    stage_after: Optional[str] = None


class TicketAssignmentResult(BaseModel):
    """Outcome of assigning a helpdesk ticket."""

    ticket_id: int
    assignee: Optional[Many2one] = None
    additional_assignees: list[int] = Field(default_factory=list)
    method_used: str
    ticket: HelpdeskTicket


class SlaPolicyResult(BaseModel):
    """A helpdesk SLA policy with its Odoo URL."""

    policy: HelpdeskSla
    url: str


class SlaPolicyListResult(BaseModel):
    """A collection of helpdesk SLA policies."""

    policies: list[HelpdeskSla] = Field(default_factory=list)
    total: int = 0


class SlaStatusResult(BaseModel):
    """The SLA status summary for a helpdesk ticket."""

    ticket_id: int
    overall_status: Optional[str] = None
    deadline: Optional[str] = None
    statuses: list[HelpdeskSlaStatus] = Field(default_factory=list)


class TicketAlarmListResult(BaseModel):
    """A collection of ticket alarms."""

    alarms: list[HelpdeskTicketAlarm] = Field(default_factory=list)
    total: int = 0


class StatsGroup(BaseModel):
    """One group returned by ticket statistics."""

    key: Optional[int | str] = None
    label: str
    count: int


class TicketStatsResult(BaseModel):
    """Aggregated helpdesk ticket statistics."""

    group_by: str
    groups: list[StatsGroup] = Field(default_factory=list)
    total: int = 0
    source_method: str


class WizardResult(BaseModel):
    """Outcome of a transient Odoo helpdesk wizard."""

    wizard_model: str
    wizard_id: int
    ticket_ids: list[int] = Field(default_factory=list)
    applied: bool
    result_ticket_id: Optional[int] = None
    message: str


class TicketTimerResult(BaseModel):
    """The current state of a ticket timesheet timer."""

    ticket_id: int
    running: bool
    started_at: Optional[str] = None
    duration_hours: Optional[float] = None
    warnings: list[str] = Field(default_factory=list)
