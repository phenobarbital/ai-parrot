"""FirefliesInsightsAgent — Fireflies meetings to wiki inbox, insights, Telegram and Jira (FEAT-715).

This module starts with the data contracts shared by the ingestion path and the
insight path. The agent class is added by later tasks of the same feature.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

#: Telegram chat identifier. GitHubReviewer defines the same alias locally
#: (bots/github_reviewer.py:88); it is not importable from a shared module.
ChatId = int | str


class FirefliesMeeting(BaseModel):
    """One meeting's raw inputs, carried by both the ingestion and the insight paths.

    ``sync_fireflies_transcripts`` returns a report dict rather than these fields,
    so the agent owns its own fetch and builds this model from it.
    """

    fireflies_id: str
    title: str
    meeting_date: str
    transcript: str
    summary: str = ""
    participants: list[str] = Field(default_factory=list)
    duration_minutes: float = 0.0
    fingerprint: str
    summary_fingerprint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionItem(BaseModel):
    """One actionable commitment extracted from a meeting."""

    title: str
    owner: str | None = None
    due_date: str | None = None
    evidence: str


class MeetingInsights(BaseModel):
    """Structured insight set for one meeting; the LLM ``output_type``."""

    meeting_id: str
    meeting_title: str
    meeting_date: str
    decisions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)


class PendingApproval(BaseModel):
    """One outstanding Telegram confirmation for turning an action item into a ticket.

    ``telegram_command`` only attaches slash-command metadata and carries no
    approval state, so this feature owns the protocol explicitly.
    """

    insight_id: str
    fireflies_id: str
    action_index: int
    chat_id: str
    user_id: str | None = None
    expires_at: str
    created_ticket: str | None = None


class InsightRunReport(BaseModel):
    """Outcome of one agent run; never raised into a scheduler."""

    fetched: int = 0
    skipped: int = 0
    dropped_to_inbox: int = 0
    insights_sent: int = 0
    errors: list[str] = Field(default_factory=list)
