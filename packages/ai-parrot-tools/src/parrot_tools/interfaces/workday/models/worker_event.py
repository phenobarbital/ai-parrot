"""Typed rows for Workday worker event history and job changes (FEAT-706)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, ClassVar, Literal, Optional

from pydantic import BaseModel, Field

JOB_CHANGE_EVENT_TYPES: tuple[str, ...] = (
    "Hire",
    "Change Job",
    "Change Organization Assignments for Worker",
    "Edit Position",
)
"""Event_Type_Name values treated as job-related (all four observed live 2026-10-19)."""

COMPENSATION_EVENT_TYPES: tuple[str, ...] = (
    "Propose Compensation Change",
    "Request Compensation Change",
)
"""Appended to the default filter only when include_compensation=True (both observed live 2026-10-19)."""


class ResolvedWorkerReference(BaseModel):
    """Identifiers of one worker as returned by Get_Workers Include_Reference."""

    wid: str
    employee_id: Optional[str] = None
    contingent_worker_id: Optional[str] = None
    formatted_name: Optional[str] = None

    @property
    def is_contingent(self) -> bool:
        """True when the worker has a Contingent_Worker_ID and no Employee_ID."""
        return bool(self.contingent_worker_id) and not self.employee_id


class WorkerEvent(BaseModel):
    """One Event_Data entry of Worker_Event_History."""

    worker_wid: str
    event_id: str
    event_type: Optional[str] = None
    description: Optional[str] = None
    effective_date: Optional[date] = None
    completed_at: Optional[datetime] = None


class JobSnapshot(BaseModel):
    """Worker job + organization data (and, opt-in, compensation) as of one effective date."""

    as_of: date
    position_id: Optional[str] = None
    position_title: Optional[str] = None
    business_title: Optional[str] = None
    position_effective_date: Optional[str] = None
    job_profile_id: Optional[str] = None
    job_profile_name: Optional[str] = None
    job_family: Optional[list[str]] = None
    management_level: Optional[str] = None
    job_category: Optional[str] = None
    worker_type: Optional[str] = None
    position_time_type: Optional[str] = None
    pay_rate_type: Optional[str] = None
    scheduled_weekly_hours: Optional[float] = None
    full_time_equivalent_percentage: Optional[float] = None
    location_name: Optional[str] = None
    location_id: Optional[str] = None
    supervisory_organization_id: Optional[str] = None
    supervisory_organization_name: Optional[str] = None
    cost_center_id: Optional[str] = None
    cost_center_name: Optional[str] = None
    cost_center_hierarchy_name: Optional[str] = None
    company_id: Optional[str] = None
    company_name: Optional[str] = None
    pay_group_id: Optional[str] = None
    pay_group_name: Optional[str] = None
    primary_organization_name: Optional[str] = None
    direct_manager_id: Optional[str] = None
    direct_manager_name: Optional[str] = None
    active: Optional[bool] = None
    hire_date: Optional[str] = None
    wage: Optional[float] = None
    pay_currency: Optional[str] = None
    pay_frequency: Optional[str] = None
    compensation_package: Optional[str] = None
    compensation_grade: Optional[str] = None
    compensation_grade_profile: Optional[str] = None
    compensation_effective_date: Optional[str] = None
    compensation_elements: Optional[list[dict[str, Any]]] = None

    DIFF_EXCLUDE: ClassVar[frozenset[str]] = frozenset({"as_of"})


class FieldChange(BaseModel):
    """One field whose value differs between two snapshots."""

    field: str
    before: Any = None
    after: Any = None


class JobChange(BaseModel):
    """One job-related change, keyed by effective date."""

    worker_wid: str
    effective_date: date
    kind: Literal["hire", "change", "no_change"]
    event_ids: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    descriptions: list[str] = Field(default_factory=list)
    before: Optional[JobSnapshot] = None
    after: JobSnapshot
    changes: list[FieldChange] = Field(default_factory=list)
    includes_compensation: bool = False
