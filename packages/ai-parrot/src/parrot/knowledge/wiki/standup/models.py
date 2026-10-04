"""Validated data passed between brief collection, rendering and persistence."""

from datetime import date as CalendarDate
from typing import Literal

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.entities import EntityType
from parrot.knowledge.wiki.standup.identity import StandupIdentity

Period = Literal["day", "week", "month"]


class PeriodWindow(BaseModel):
    """Inclusive period bounds plus meeting horizons and stable page identity."""

    period: Period
    anchor: CalendarDate
    start: CalendarDate
    end: CalendarDate
    recent_start: CalendarDate
    upcoming_end: CalendarDate
    brief_id: str


class BriefItem(BaseModel):
    """One qualified, attributable item from a native or attrs source."""

    id: str
    kind: EntityType
    title: str
    status: str | None = None
    status_raw: str | None = None
    project_hint: str | None = None
    date: CalendarDate | None = None
    due: CalendarDate | None = None
    owner: str | None = None
    urgent: bool = False
    namespace: str | None = None
    url: str | None = None
    source: str
    age_days: int | None = None


class BriefSection(BaseModel):
    """A named ordered collection of brief items."""

    key: str
    items: list[BriefItem]


class ProjectSlice(BaseModel):
    """Project grouping with deterministic activity ordering."""

    project: str
    status: str | None = None
    sections: list[BriefSection]
    activity: int


class HygieneReport(BaseModel):
    """Deterministic source health and optional synthesis outcome."""

    ledger_blockers: int = 0
    proposed_decisions_older_than: int = 0
    stale_tickets: int = 0
    unmapped_statuses: dict[str, int] = Field(default_factory=dict)
    jira_watermark: str | None = None
    attrs_indexed: int | None = None
    last_lint: str | None = None
    llm: str = "skipped: no model"


class BriefDocument(BaseModel):
    """Complete brief with safe write receipts and source diagnostics."""

    window: PeriodWindow
    identity: StandupIdentity
    team: bool
    language: str
    on_your_plate: list[str]
    projects: list[ProjectSlice]
    internal: list[BriefSection]
    delta_new: list[BriefItem]
    delta_closed: list[BriefItem]
    previous_brief_id: str | None = None
    sources: list[str]
    hygiene: HygieneReport
    item_ids: list[str]
    diagnostics: list[str] = Field(default_factory=list)
    written_page: bool = False
    written_file: str | None = None


class BriefProjection(BaseModel):
    """Only bounded, whitelisted scalar facts sent to a model."""

    period: Period
    language: str
    items: list[dict[str, str | int | bool | None]] = Field(max_length=40)

    def model_post_init(self, __context: object) -> None:
        """Reject projection fields that could expose unbounded source content."""
        del __context
        allowed_keys = {"kind", "title", "status", "project", "age_days", "urgent"}
        for item in self.items:
            if set(item) != allowed_keys:
                raise ValueError("Projection items must contain exactly the six allowed scalar fields")
            title = item["title"]
            if not isinstance(title, str) or len(title) > 120:
                raise ValueError("Projection item titles must be strings of at most 120 characters")
