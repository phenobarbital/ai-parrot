from typing import get_args

import pytest
from pydantic import ValidationError
from parrot.knowledge.wiki.ledger.events import (
    LedgerEvent,
    LedgerEventKind,
    IssueOpenedPayload,
    IssueClaimedPayload,
    IssueUnclaimedPayload,
    IssueAcknowledgedPayload,
    IssueClosedPayload,
    InsightRecordedPayload,
    IssueSeverity,
    SEVERITY_ORDER,
    compute_event_id,
    compute_issue_id,
)


def test_compute_event_id_determinism():
    payload = {"title": "Test Issue", "severity": "critical"}
    id1 = compute_event_id("issue.opened", "issue:123", "agent:codex", "2026-09-14T12:00:00Z", payload)
    id2 = compute_event_id("issue.opened", "issue:123", "agent:codex", "2026-09-14T12:00:00Z", payload)
    assert id1 == id2
    assert len(id1) == 12

    # Different payload keys order should still produce the same ID
    payload_reordered = {"severity": "critical", "title": "Test Issue"}
    id3 = compute_event_id("issue.opened", "issue:123", "agent:codex", "2026-09-14T12:00:00Z", payload_reordered)
    assert id1 == id3


def test_compute_issue_id_determinism():
    id1 = compute_issue_id("bug", "Null pointer in parser", "task:TASK-3200")
    id2 = compute_issue_id("bug", "Null pointer in parser", "task:TASK-3200")
    assert id1 == id2
    assert id1.startswith("issue:")
    assert len(id1) == 18  # "issue:" (6) + 12 chars hash = 18


def test_ledger_event_auto_id():
    event = LedgerEvent(
        kind="issue.opened",
        subject="issue:123",
        actor="agent:codex",
        ts="2026-09-14T12:00:00Z",
        payload={"title": "Test"},
    )
    assert event.event_id != ""
    assert len(event.event_id) == 12


def test_invalid_event_kind():
    with pytest.raises(ValidationError):
        LedgerEvent(
            kind="invalid.kind",  # type: ignore
            subject="issue:123",
            actor="agent:codex",
            ts="2026-09-14T12:00:00Z",
            payload={},
        )


def test_payload_validation():
    # Valid IssueOpenedPayload
    opened = IssueOpenedPayload(
        title="A bug",
        body="Something is broken",
        kind="bug",
        severity="critical",
        discovered_from="task:TASK-3200",
        about=["sym:pkg/mod.py#Func"],
    )
    assert opened.kind == "bug"

    # Invalid IssueOpenedPayload severity
    with pytest.raises(ValidationError):
        IssueOpenedPayload(
            title="A bug",
            body="Something is broken",
            severity="extremely-high",  # type: ignore
            discovered_from="task:TASK-3200",
        )


def test_issue_claimed_payload():
    claimed = IssueClaimedPayload(claimed_by="task:TASK-3205")
    assert claimed.claimed_by == "task:TASK-3205"


def test_issue_acknowledged_payload():
    ack = IssueAcknowledgedPayload(acknowledged_by="human:jesus", reason="Will fix later")
    assert ack.acknowledged_by == "human:jesus"
    assert ack.reason == "Will fix later"


def test_issue_closed_payload():
    closed = IssueClosedPayload(reason="Fixed", closed_by="agent:codex", resolved_by="task:TASK-3205")
    assert closed.reason == "Fixed"
    assert closed.resolved_by == "task:TASK-3205"


def test_insight_recorded_payload():
    insight = InsightRecordedPayload(
        fact="This is a fact",
        title="Fact title",
        derived_from="task:TASK-3200",
        about=["sym:pkg/mod.py#Func"],
    )
    assert insight.category == "note"
    assert insight.fact == "This is a fact"


def test_issue_unclaimed_payload():
    payload = IssueUnclaimedPayload(unclaimed_by="agent:sdd-fix", reason="released: not fixed in this lane")
    assert payload.unclaimed_by == "agent:sdd-fix"
    assert payload.reason.startswith("released")


def test_ledger_event_kind_has_twelve_members_including_unclaimed():
    members = get_args(LedgerEventKind)
    assert len(members) == 12
    assert "issue.unclaimed" in members


def test_issue_unclaimed_event_validates():
    event = LedgerEvent(
        kind="issue.unclaimed",
        subject="issue:abc",
        actor="agent:sdd-fix",
        payload={"unclaimed_by": "agent:sdd-fix", "reason": "released"},
    )
    assert event.event_id  # computed by model_post_init


def test_severity_order_is_total_and_canonical():
    members = get_args(IssueSeverity)
    assert set(SEVERITY_ORDER) == set(members), "every IssueSeverity member must have a rank"
    assert sorted(SEVERITY_ORDER, key=SEVERITY_ORDER.__getitem__) == ["critical", "major", "minor", "low"]
    assert sorted(SEVERITY_ORDER.values()) == list(range(len(members)))
