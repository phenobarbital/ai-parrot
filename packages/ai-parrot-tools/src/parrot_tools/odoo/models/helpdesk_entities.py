"""Pydantic entities for the Softhealer helpdesk models (``sh.helpdesk.*`` / ``helpdesk.*``).

All Odoo-backed classes subclass :class:`_OdooEntity` (``extra="allow"``) so tenant-specific
fields round-trip. ``HelpdeskTicket.extra_fields`` and ``.lifecycle`` are derived by
``parrot_tools.odoo.helpdesk_normalize``; Odoo never sends them.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .entities import Many2one, _OdooEntity


class HelpdeskLifecycle(BaseModel):
    """Lifecycle derived from ticket stages, booleans, and company stage roles."""

    stage_id: Optional[int] = None
    stage_name: Optional[str] = None
    is_closed: bool = False
    is_cancelled: bool = False
    is_done: bool = False
    can_reopen: bool = False
    next_stage_id: Optional[int] = None
    next_stage_name: Optional[str] = None
    role: Optional[Literal["new", "reopen", "done", "cancel", "close"]] = None


class HelpdeskTicket(_OdooEntity):
    """``sh.helpdesk.ticket`` wire fields plus derived lifecycle data."""

    name: Optional[str] = None
    description: Optional[str] = None
    comment: Optional[str] = None
    customer_comment: Optional[str] = None
    email: Optional[str] = None
    email_cc: Optional[str] = None
    email_subject: Optional[str] = None
    mobile_no: Optional[str] = None
    person_name: Optional[str] = None
    partner_id: Optional[Many2one] = None
    stage_id: Optional[Many2one] = None
    team_id: Optional[Many2one] = None
    team_head: Optional[Many2one] = None
    user_id: Optional[Many2one] = None
    category_id: Optional[Many2one] = None
    sub_category_id: Optional[Many2one] = None
    ticket_type: Optional[Many2one] = None
    subject_id: Optional[Many2one] = None
    priority: Optional[Many2one] = None
    company_id: Optional[Many2one] = None
    sh_user_ids: Optional[list[int]] = None
    tag_ids: Optional[list[int]] = None
    sh_sla_policy_ids: Optional[list[int]] = None
    sh_sla_status_ids: Optional[list[int]] = None
    sh_ticket_alarm_ids: Optional[list[int]] = None
    attachment_ids: Optional[list[int]] = None
    timehseet_ids: Optional[list[int]] = None
    priority_new: Optional[str] = None
    replied_status: Optional[str] = Field(
        default=None,
        alias="state",
        description="'customer_replied' | 'staff_replied' — not the lifecycle",
    )
    open_boolean: Optional[bool] = None
    done_stage_boolean: Optional[bool] = None
    closed_stage_boolean: Optional[bool] = None
    cancel_stage_boolean: Optional[bool] = None
    reopen_stage_boolean: Optional[bool] = None
    done_button_boolean: Optional[bool] = None
    cancel_button_boolean: Optional[bool] = None
    close_date: Optional[str | bool] = None
    close_by: Optional[Many2one] = None
    cancel_date: Optional[str] = None
    cancel_by: Optional[Many2one] = None
    cancel_reason: Optional[str | bool] = None
    replied_date: Optional[str] = None
    sh_due_date: Optional[str] = None
    sh_sla_deadline: Optional[str | bool] = None
    sh_status: Optional[str | bool] = None
    create_date: Optional[str] = None
    write_date: Optional[str] = None
    ticket_from_portal: Optional[bool] = None
    ticket_from_website: Optional[bool] = None
    ticket_running: Optional[bool] = None
    dynamic_form_submission_id: Optional[Many2one] = None
    extra_fields: dict[str, str] = Field(
        default_factory=dict,
        description="TROC extra fields (field_name → value), derived",
    )
    lifecycle: Optional[HelpdeskLifecycle] = Field(default=None, description="Derived lifecycle block")


class HelpdeskStage(_OdooEntity):
    """``helpdesk.stages``."""

    name: Optional[str] = None
    sequence: Optional[int] = None
    is_done_button_visible: Optional[bool] = None
    is_cancel_button_visible: Optional[bool] = None
    sh_next_stage: Optional[Many2one] = None
    sh_group_ids: Optional[list[int]] = None
    mail_template_ids: Optional[list[int]] = None
    company_id: Optional[Many2one] = None


class HelpdeskTeam(_OdooEntity):
    """``sh.helpdesk.team``."""

    name: Optional[str] = None
    team_head: Optional[Many2one] = None
    team_members: Optional[list[int]] = None
    category_ids: Optional[list[int]] = None
    sh_resource_calendar_id: Optional[Many2one] = None
    alias_name: Optional[str] = None


class HelpdeskCategory(_OdooEntity):
    """``helpdesk.category``."""

    name: Optional[str] = None
    sequence: Optional[int] = None
    team_id: Optional[Many2one] = None
    company_id: Optional[Many2one] = None
    is_helpdesk_manager: Optional[bool] = None


class HelpdeskSubcategory(_OdooEntity):
    """``helpdesk.subcategory``."""

    name: Optional[str] = None
    parent_category_id: Optional[Many2one] = None


class HelpdeskPriority(_OdooEntity):
    """``helpdesk.priority``."""

    name: Optional[str] = None
    sequence: Optional[int] = None
    color: Optional[str] = None


class HelpdeskTicketType(_OdooEntity):
    """``sh.helpdesk.ticket.type``."""

    name: Optional[str] = None
    sla_count: Optional[int] = None


class HelpdeskTag(_OdooEntity):
    """``helpdesk.tags``."""

    name: Optional[str] = None
    color: Optional[int] = None


class HelpdeskStageInfo(_OdooEntity):
    """``sh.helpdesk.ticket.stage.info`` history row."""

    stage_task_id: Optional[Many2one] = None
    stage_name: Optional[str] = None
    date_in: Optional[str] = None
    date_out: Optional[str] = None
    date_in_by: Optional[Many2one] = None
    date_out_by: Optional[Many2one] = None
    day_diff: Optional[int] = None
    time_diff: Optional[float] = None
    total_time_diff: Optional[float] = None


class HelpdeskSla(_OdooEntity):
    """``sh.helpdesk.sla`` policy."""

    name: Optional[str] = None
    sh_team_id: Optional[Many2one] = None
    sh_days: Optional[int] = None
    sh_hours: Optional[int] = None
    sh_minutes: Optional[int] = None
    sh_sla_target_type: Optional[str] = None
    sh_stage_id: Optional[Many2one] = None
    sh_ticket_type_id: Optional[Many2one] = None
    company_id: Optional[Many2one] = None
    sla_ticket_count: Optional[int] = None


class HelpdeskSlaStatus(_OdooEntity):
    """``sh.helpdesk.sla.status`` record for one ticket policy."""

    sh_ticket_id: Optional[Many2one] = None
    sh_sla_id: Optional[Many2one] = None
    sh_sla_stage_id: Optional[Many2one] = None
    sh_deadline: Optional[str] = None
    sh_done_sla_date: Optional[str] = None
    sh_exceeded_hours: Optional[float] = None
    sh_status: Optional[str] = None
    sh_create_date: Optional[str] = None


class HelpdeskTicketAlarm(_OdooEntity):
    """``sh.ticket.alarm`` reminder configuration."""

    name: Optional[str] = None
    type: Optional[Literal["email", "popup"]] = None
    sh_remind_before: Optional[int] = None
    sh_reminder_unit: Optional[str] = None


class HelpdeskMessage(BaseModel):
    """One ``mail.message`` row on a ticket shaped by the toolkit."""

    model_config = ConfigDict(extra="ignore")

    id: int
    date: Optional[str] = None
    author_id: Optional[Many2one] = None
    message_type: Optional[str] = None
    subtype: Optional[str] = None
    body: str = ""
    is_internal: bool = False
