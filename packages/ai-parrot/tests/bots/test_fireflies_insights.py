"""Unit tests for the FEAT-715 FirefliesInsightsAgent data contracts."""

import pytest
from pydantic import ValidationError

from parrot.bots.fireflies_insights import (
    ActionItem,
    FirefliesMeeting,
    InsightRunReport,
    MeetingInsights,
    PendingApproval,
)


def test_meeting_requires_fingerprint() -> None:
    with pytest.raises(ValidationError):
        FirefliesMeeting(fireflies_id="m1", title="Sync", meeting_date="2026-10-22", transcript="hi")


def test_meeting_defaults_are_independent() -> None:
    a = FirefliesMeeting(fireflies_id="a", title="A", meeting_date="2026-10-22", transcript="x", fingerprint="f")
    b = FirefliesMeeting(fireflies_id="b", title="B", meeting_date="2026-10-22", transcript="y", fingerprint="g")
    a.participants.append("ana@example.test")
    assert b.participants == []
    assert a.summary == ""
    assert a.summary_fingerprint is None


def test_insights_round_trip() -> None:
    item = ActionItem(title="Ship it", owner="Ana", due_date="2026-11-01", evidence="Ana: I'll ship it")
    insights = MeetingInsights(
        meeting_id="m1",
        meeting_title="Sync",
        meeting_date="2026-10-22",
        decisions=["Go"],
        risks=["Late"],
        action_items=[item],
    )
    restored = MeetingInsights.model_validate_json(insights.model_dump_json())
    assert restored == insights


def test_action_item_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        ActionItem(title="No evidence")


def test_pending_approval_ticket_marker_defaults_empty() -> None:
    approval = PendingApproval(
        insight_id="i1", fireflies_id="m1", action_index=0, chat_id="-100", expires_at="2026-10-23T00:00:00+00:00"
    )
    assert approval.created_ticket is None
    assert approval.user_id is None


def test_run_report_starts_at_zero() -> None:
    report = InsightRunReport()
    assert (report.fetched, report.skipped, report.dropped_to_inbox, report.insights_sent) == (0, 0, 0, 0)
    assert report.errors == []
