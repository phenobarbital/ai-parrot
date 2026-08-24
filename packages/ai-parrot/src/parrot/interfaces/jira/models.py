"""Pydantic v2 models for the shared Jira read interface (FEAT-454, M1).

These models are the network-free, jira-package-free projection surface
shared by :class:`parrot.interfaces.jira.client.JiraInterface`,
``JiraToolkit`` and the wiki sweep (``parrot.knowledge.wiki.jira_sync``).

Design notes:
- ``JiraPerson`` deliberately has **no** email field — G9. Raw Jira user
  objects always carry ``emailAddress``; it must never survive the
  ``_person()`` projection helper in :mod:`parrot.interfaces.jira.parse`.
- ``JiraAttachmentRef`` / ``JiraRemoteLink`` are references only — nothing
  is ever downloaded (non-goal).
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class JiraPerson(BaseModel):
    """A Jira user. NO email field — G9."""

    account_id: str
    display_name: str


class JiraIssueLinkKind(str, Enum):
    """Normalized issue-link relationship, direction-aware."""

    BLOCKS = "blocks"
    BLOCKED_BY = "blocked_by"
    RELATES = "relates"
    DUPLICATES = "duplicates"
    DUPLICATED_BY = "duplicated_by"
    CLONES = "clones"
    CLONED_BY = "cloned_by"


class JiraIssueLink(BaseModel):
    """A single normalized issue link."""

    kind: JiraIssueLinkKind
    target_key: str


class JiraChangeEvent(BaseModel):
    """A single changelog history event for one field."""

    at: datetime
    field: str
    from_value: str | None = None
    to_value: str | None = None
    author: JiraPerson | None = None


class JiraAttachmentRef(BaseModel):
    """Reference only — never downloaded (Non-Goal)."""

    filename: str
    size_bytes: int | None = None
    mime_type: str | None = None
    url: str


class JiraRemoteLink(BaseModel):
    """A Jira remote link (e.g. a wiki page or external URL)."""

    title: str
    url: str


class JiraIssue(BaseModel):
    """Validated projection of a raw Jira issue payload.

    Produced by :func:`parrot.interfaces.jira.parse.parse_issue`. Collections
    (``labels``, ``components``) are left in Jira's native order here — the
    renderer (``jira_render.py``) is responsible for sorting them; that is
    where the determinism contract lives (G2). Do not sort twice.
    """

    key: str
    issue_id: str
    project_key: str
    issue_type: str  # -> frontmatter `category`
    status: str
    resolution: str | None = None
    priority: str | None = None
    summary: str  # -> frontmatter `title`
    description_html: str | None = None  # from expand=renderedFields
    acceptance_criteria_html: str | None = None
    assignee: JiraPerson | None = None
    reporter: JiraPerson | None = None
    labels: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    epic_key: str | None = None
    parent_key: str | None = None
    subtask_keys: list[str] = Field(default_factory=list)
    links: list[JiraIssueLink] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    resolved_at: datetime | None = None
    history: list[JiraChangeEvent] = Field(default_factory=list)
    attachments: list[JiraAttachmentRef] = Field(default_factory=list)
    remote_links: list[JiraRemoteLink] = Field(default_factory=list)
    url: str  # browse URL
