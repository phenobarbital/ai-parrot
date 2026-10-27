"""FEAT-758 M2 — strict merge, transition conflicts, scratch replay."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.knowledge.wiki.ledger.events import LedgerEvent, canonical_json_dumps
from parrot.knowledge.wiki.ledger.integration import (
    build_scratch_snapshot,
    find_transition_conflicts,
    merge_batch,
    read_logical_log,
)
from parrot.knowledge.wiki.ledger.outbox import StrictLedgerReadError


def _ev(kind: str, subject: str, payload: dict[str, object], n: int) -> LedgerEvent:
    """Build a deterministic event with a unique timestamp-derived identity."""
    return LedgerEvent(
        kind=kind,
        subject=subject,
        actor="agent:test",
        ts=f"2026-10-27T00:00:{n:02d}+00:00",
        payload=payload,
    )


def _opened(subject: str, n: int) -> LedgerEvent:
    """Build a valid issue-opened event for replay tests."""
    return _ev(
        "issue.opened",
        subject,
        {
            "title": subject,
            "body": "body",
            "kind": "bug",
            "severity": "minor",
            "discovered_from": "spec:FEAT-758",
        },
        n,
    )


def _line(event: LedgerEvent) -> bytes:
    """Serialize an event as the raw JSONL content without its newline."""
    return canonical_json_dumps(event.model_dump()).encode("utf-8")


def test_merge_skips_exact_duplicates_and_keeps_order() -> None:
    """Exact remote duplicates are skipped and captured batch ordering is retained."""
    first = _ev("insight.recorded", "spec:one", {"fact": "one", "title": "one", "derived_from": "spec:FEAT-758"}, 1)
    second = _ev("insight.recorded", "spec:two", {"fact": "two", "title": "two", "derived_from": "spec:FEAT-758"}, 2)
    third = _ev("insight.recorded", "spec:three", {"fact": "three", "title": "three", "derived_from": "spec:FEAT-758"}, 3)

    plan = merge_batch([(_line(first), first)], [(_line(first), first), (_line(third), third), (_line(second), second)])

    assert plan.duplicates == 1
    assert plan.new_events == [third, second]
    assert plan.new_lines == [_line(third), _line(second)]


def test_merge_rejects_equal_id_different_content() -> None:
    """A duplicate event identity cannot be used for a different payload."""
    original = _ev("insight.recorded", "spec:one", {"fact": "one", "title": "one", "derived_from": "spec:FEAT-758"}, 1)
    forged = original.model_copy(update={"payload": {"fact": "two", "title": "two", "derived_from": "spec:FEAT-758"}})

    with pytest.raises(StrictLedgerReadError):
        merge_batch([(_line(original), original)], [(_line(forged), forged)])


def test_logical_log_dedups_archive_and_current(tmp_path: Path) -> None:
    """An archive/current duplicate appears once in the logical log."""
    event = _ev("insight.recorded", "spec:one", {"fact": "one", "title": "one", "derived_from": "spec:FEAT-758"}, 1)
    line = _line(event) + b"\n"
    archive = tmp_path / "sdd" / "ledger" / "archive"
    archive.mkdir(parents=True)
    (archive / "events-2026_09.jsonl").write_bytes(line)
    current = tmp_path / "sdd" / "ledger" / "events.jsonl"
    current.write_bytes(line)

    assert read_logical_log(tmp_path) == [(_line(event), event)]


@pytest.mark.parametrize("reason", ["competing-claim", "conflicting-close", "unclaim-terminal", "missing-predecessor"])
def test_transition_conflicts(reason: str) -> None:
    """Each incompatible transition reports its event, subject, and policy reason."""
    subject = "issue:one"
    opened = _opened(subject, 1)
    if reason == "competing-claim":
        remote = [opened, _ev("issue.claimed", subject, {"claimed_by": "agent:one"}, 2)]
        new = [_ev("issue.claimed", subject, {"claimed_by": "agent:two"}, 3)]
    elif reason == "conflicting-close":
        remote = [opened, _ev("issue.closed", subject, {"closed_by": "agent:one", "reason": "done"}, 2)]
        new = [_ev("issue.closed", subject, {"closed_by": "agent:two", "reason": "different"}, 3)]
    elif reason == "unclaim-terminal":
        remote = [opened, _ev("issue.closed", subject, {"closed_by": "agent:one", "reason": "done"}, 2)]
        new = [_ev("issue.unclaimed", subject, {"unclaimed_by": "agent:two", "reason": "retry"}, 3)]
    else:
        remote = []
        new = [_ev("issue.claimed", subject, {"claimed_by": "agent:one"}, 1)]

    conflict = find_transition_conflicts(remote, new)

    assert [(item.event_id, item.subject, item.reason) for item in conflict] == [(new[0].event_id, subject, reason)]


def test_same_owner_claim_and_identical_close_are_not_conflicts() -> None:
    """Idempotent repeated claims and closes remain valid delivery events."""
    claim_subject = "issue:claim"
    close_subject = "issue:close"
    claim = _ev("issue.claimed", claim_subject, {"claimed_by": "agent:one"}, 2)
    close = _ev("issue.closed", close_subject, {"closed_by": "agent:one", "reason": "done", "resolved_by": "task:TASK-1"}, 4)
    remote = [_opened(claim_subject, 1), claim, _opened(close_subject, 3), close]

    assert find_transition_conflicts(remote, [claim, close]) == []


async def test_scratch_replay_remote_closed_wins_and_legacy_rows_survive(tmp_path: Path) -> None:
    """Scratch replay derives remote state and reconciles unknown legacy snapshot rows."""
    subject = "issue:closed"
    opened = _opened(subject, 1)
    closed = _ev("issue.closed", subject, {"closed_by": "agent:remote", "reason": "done"}, 2)
    stale_claim = _ev("issue.claimed", subject, {"claimed_by": "agent:local"}, 3)
    dest = tmp_path / "dest" / "issues.jsonl"
    legacy = {"issue_id": "issue:legacy", "status": "open", "title": "legacy"}
    dest.parent.mkdir(parents=True)
    dest.write_text(json.dumps(legacy, sort_keys=True) + "\n", encoding="utf-8")

    assert await build_scratch_snapshot(
        [_line(opened), _line(closed), _line(stale_claim)], scratch_dir=tmp_path / "scratch", dest=dest
    )

    rows = {row["issue_id"]: row for row in (json.loads(line) for line in dest.read_text(encoding="utf-8").splitlines())}
    assert rows[subject]["status"] == "closed"
    assert rows["issue:legacy"] == legacy
