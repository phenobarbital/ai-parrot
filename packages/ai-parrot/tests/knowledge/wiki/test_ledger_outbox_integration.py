"""FEAT-758 M2 — strict merge, transition conflicts, scratch replay."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from parrot.knowledge.wiki.ledger.events import LedgerEvent, canonical_json_dumps
from parrot.knowledge.wiki.ledger.integration import (
    LedgerIntegrator,
    build_scratch_snapshot,
    drop_redundant_closes,
    find_transition_conflicts,
    merge_batch,
    read_logical_log,
)
from parrot.knowledge.wiki.ledger.outbox import LedgerOutbox, StrictLedgerReadError

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
    third = _ev(
        "insight.recorded", "spec:three", {"fact": "three", "title": "three", "derived_from": "spec:FEAT-758"}, 3
    )

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
    close = _ev(
        "issue.closed", close_subject, {"closed_by": "agent:one", "reason": "done", "resolved_by": "task:TASK-1"}, 4
    )
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

    rows = {
        row["issue_id"]: row for row in (json.loads(line) for line in dest.read_text(encoding="utf-8").splitlines())
    }
    assert rows[subject]["status"] == "closed"
    assert rows["issue:legacy"] == legacy


def _run_git(cwd: Path, *args: str) -> str:
    """Run one test-only git command and return its standard output."""
    result = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


@pytest.fixture
def two_clones(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a bare dev origin and two independently configured clone checkouts."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "--initial-branch=dev", str(origin)], check=True, capture_output=True)
    seed = tmp_path / "seed"
    _run_git(tmp_path, "clone", str(origin), str(seed))
    for clone in (seed,):
        _run_git(clone, "config", "user.name", "Ledger Test")
        _run_git(clone, "config", "user.email", "ledger@example.test")
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _run_git(seed, "add", "README.md")
    _run_git(seed, "commit", "-m", "seed")
    _run_git(seed, "push", "origin", "dev")
    first = tmp_path / "a"
    second = tmp_path / "b"
    _run_git(tmp_path, "clone", str(origin), str(first))
    _run_git(tmp_path, "clone", str(origin), str(second))
    for clone in (first, second):
        _run_git(clone, "config", "user.name", "Ledger Test")
        _run_git(clone, "config", "user.email", "ledger@example.test")
    return origin, first, second


async def _batch_for(repo: Path, event: LedgerEvent):
    """Write one isolated local journal event and seal it into a delivery batch."""
    ledger_dir = repo / ".parrot" / "ledger"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "events.jsonl").write_bytes(_line(event) + b"\n")
    outbox = LedgerOutbox(ledger_dir)
    batch = await outbox.prepare(repo_root=repo, source_ref="HEAD", source_head=_run_git(repo, "rev-parse", "HEAD"))
    assert batch is not None
    return outbox, batch


async def test_delivers_batch_and_writes_receipt(two_clones: tuple[Path, Path, Path]) -> None:
    """A sealed event is pushed and acknowledged only after remote verification."""
    _, first, _ = two_clones
    event = _ev("insight.recorded", "spec:delivery", {"fact": "x", "title": "x", "derived_from": "spec:FEAT-758"}, 10)
    outbox, batch = await _batch_for(first, event)

    report = await LedgerIntegrator(first, outbox).integrate(batch)

    assert report.status == "delivered"
    assert report.added == 1
    assert await outbox.receipt_for(batch.batch_id) is not None
    assert event.event_id in await LedgerIntegrator(first, outbox).remote_event_ids()


async def test_two_clone_race_loser_retries_both_present_once(two_clones: tuple[Path, Path, Path]) -> None:
    """A stale clone refreshes and delivers its independent event without duplication."""
    _, first, second = two_clones
    first_event = _ev(
        "insight.recorded", "spec:first", {"fact": "one", "title": "one", "derived_from": "spec:FEAT-758"}, 11
    )
    second_event = _ev(
        "insight.recorded", "spec:second", {"fact": "two", "title": "two", "derived_from": "spec:FEAT-758"}, 12
    )
    first_outbox, first_batch = await _batch_for(first, first_event)
    second_outbox, second_batch = await _batch_for(second, second_event)

    assert (await LedgerIntegrator(first, first_outbox).integrate(first_batch)).status == "delivered"
    report = await LedgerIntegrator(second, second_outbox).integrate(second_batch)

    assert report.status == "delivered"
    ids = await LedgerIntegrator(second, second_outbox).remote_event_ids()
    assert {first_event.event_id, second_event.event_id} <= ids


async def test_lost_receipt_retry_is_already_delivered_no_duplicate_commit(two_clones: tuple[Path, Path, Path]) -> None:
    """A retry after deleting a local receipt verifies remote content without another commit."""
    _, first, _ = two_clones
    event = _ev(
        "insight.recorded", "spec:retry", {"fact": "retry", "title": "retry", "derived_from": "spec:FEAT-758"}, 13
    )
    outbox, batch = await _batch_for(first, event)
    integrator = LedgerIntegrator(first, outbox)
    assert (await integrator.integrate(batch)).status == "delivered"
    outbox._receipt_path(batch.batch_id).unlink()
    before = _run_git(first, "rev-parse", "origin/dev")

    report = await integrator.integrate(batch)

    assert report.status == "already_delivered"
    assert _run_git(first, "rev-parse", "origin/dev") == before
    assert await outbox.receipt_for(batch.batch_id) is not None


async def test_conflict_blocks_push_and_receipt(two_clones: tuple[Path, Path, Path]) -> None:
    """An invalid transition is reported before a commit or receipt is created."""
    _, first, _ = two_clones
    event = _ev("issue.claimed", "issue:missing", {"claimed_by": "agent:test"}, 14)
    outbox, batch = await _batch_for(first, event)

    report = await LedgerIntegrator(first, outbox).integrate(batch)

    assert report.status == "conflict"
    assert report.conflicts[0].reason == "missing-predecessor"
    assert await outbox.receipt_for(batch.batch_id) is None


async def test_hook_mutating_commit_blocks_push(two_clones: tuple[Path, Path, Path]) -> None:
    """A commit hook that stages an unrelated file is retained for recovery and never pushed."""
    _, first, _ = two_clones
    hooks = first / "hooks"
    hooks.mkdir()
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\necho changed > hook-output\ngit add hook-output\n", encoding="utf-8")
    hook.chmod(0o755)
    _run_git(first, "config", "core.hooksPath", str(hooks))
    event = _ev("insight.recorded", "spec:hook", {"fact": "hook", "title": "hook", "derived_from": "spec:FEAT-758"}, 15)
    outbox, batch = await _batch_for(first, event)

    report = await LedgerIntegrator(first, outbox).integrate(batch)

    assert report.status == "pending"
    assert report.error_code == "hook-mutated-commit"
    assert report.recovery_path is not None
    assert await outbox.receipt_for(batch.batch_id) is None


async def test_push_failure_is_pending_and_retains_batch(two_clones: tuple[Path, Path, Path]) -> None:
    """A missing remote produces a typed pending result and leaves the batch unacknowledged."""
    _, first, _ = two_clones
    event = _ev(
        "insight.recorded", "spec:missing", {"fact": "missing", "title": "missing", "derived_from": "spec:FEAT-758"}, 16
    )
    outbox, batch = await _batch_for(first, event)
    _run_git(first, "remote", "set-url", "origin", str(first / "missing-origin.git"))

    report = await LedgerIntegrator(first, outbox).integrate(batch)

    assert report.status == "pending"
    assert report.error_code == "push-failed"
    assert await outbox.receipt_for(batch.batch_id) is None


async def test_active_checkouts_untouched(two_clones: tuple[Path, Path, Path]) -> None:
    """Delivery through an owned detached worktree leaves both active clone indexes unchanged."""
    _, first, second = two_clones
    event = _ev(
        "insight.recorded", "spec:clean", {"fact": "clean", "title": "clean", "derived_from": "spec:FEAT-758"}, 17
    )
    outbox, batch = await _batch_for(first, event)
    before = [
        (_run_git(clone, "rev-parse", "HEAD"), _run_git(clone, "status", "--porcelain")) for clone in (first, second)
    ]

    assert (await LedgerIntegrator(first, outbox).integrate(batch)).status == "delivered"

    assert [
        (_run_git(clone, "rev-parse", "HEAD"), _run_git(clone, "status", "--porcelain")) for clone in (first, second)
    ] == before


async def test_check_feature_diff_reports_contamination(two_clones: tuple[Path, Path, Path]) -> None:
    """The read-only contamination report identifies ledger paths changed on a feature ref."""
    _, first, _ = two_clones
    _run_git(first, "checkout", "-b", "feature-ledger")
    path = first / "sdd" / "ledger" / "events.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("{}\n", encoding="utf-8")
    _run_git(first, "add", "sdd/ledger/events.jsonl")
    _run_git(first, "commit", "-m", "contaminate ledger")
    outbox = LedgerOutbox(first / ".parrot" / "ledger")

    assert await LedgerIntegrator(first, outbox).check_feature_diff("feature-ledger") == ["sdd/ledger/events.jsonl"]


# FEAT-771 / TASK-4895 — redundant closes never block delivery.


def test_drop_redundant_closes_moves_close_of_closed_issue() -> None:
    """A close of an issue already closed on the destination is set aside, not conflicted."""
    subject = "issue:one"
    remote = [_opened(subject, 1), _ev("issue.closed", subject, {"closed_by": "agent:one", "reason": "done"}, 2)]
    close = _ev("issue.closed", subject, {"closed_by": "agent:two", "reason": "different"}, 3)

    plan = drop_redundant_closes(remote, merge_batch([], [(_line(close), close)]))

    assert plan.redundant_closes == [close.event_id]
    assert plan.new_events == []
    assert plan.new_lines == []
    assert find_transition_conflicts(remote, plan.new_events) == []


def test_drop_redundant_closes_keeps_first_close_and_drops_in_batch_repeat() -> None:
    """The first close of an open issue lands; a second close in the same batch is redundant."""
    subject = "issue:two"
    first = _ev("issue.closed", subject, {"closed_by": "agent:one", "reason": "done"}, 2)
    second = _ev("issue.closed", subject, {"closed_by": "agent:two", "reason": "again"}, 3)

    plan = drop_redundant_closes([_opened(subject, 1)], merge_batch([], [(_line(e), e) for e in (first, second)]))

    assert plan.new_events == [first]
    assert plan.new_lines == [_line(first)]
    assert plan.redundant_closes == [second.event_id]


def test_drop_redundant_closes_keeps_non_close_events() -> None:
    """Claims, opens and non-issue events are kept in order; duplicates are carried over."""
    closed_subject = "issue:closed"
    opened = _opened(closed_subject, 1)
    remote = [opened, _ev("issue.closed", closed_subject, {"closed_by": "agent:one", "reason": "done"}, 2)]
    claim = _ev("issue.claimed", closed_subject, {"claimed_by": "agent:two"}, 3)
    fresh = _opened("issue:fresh", 4)
    insight = _ev("insight.recorded", "spec:x", {"fact": "x", "title": "x", "derived_from": "spec:FEAT-771"}, 5)
    batch = [(_line(e), e) for e in (opened, claim, fresh, insight)]

    plan = drop_redundant_closes(remote, merge_batch([(_line(e), e) for e in remote], batch))

    assert plan.new_events == [claim, fresh, insight]
    assert plan.redundant_closes == []
    assert plan.duplicates == 1


async def _batch_of(repo: Path, *events: LedgerEvent):
    """Write several local journal events and seal them into one delivery batch."""
    ledger_dir = repo / ".parrot" / "ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / "events.jsonl").write_bytes(b"".join(_line(event) + b"\n" for event in events))
    outbox = LedgerOutbox(ledger_dir)
    batch = await outbox.prepare(repo_root=repo, source_ref="HEAD", source_head=_run_git(repo, "rev-parse", "HEAD"))
    assert batch is not None
    return outbox, batch


async def _close_on_dev(clone: Path, subject: str) -> None:
    """Deliver an opened + closed pair for ``subject`` from ``clone``."""
    closed = _ev("issue.closed", subject, {"closed_by": "agent:one", "reason": "fixed", "resolved_by": "task:T-1"}, 21)
    outbox, batch = await _batch_of(clone, _opened(subject, 20), closed)
    assert (await LedgerIntegrator(clone, outbox).integrate(batch)).status == "delivered"


async def test_redundant_close_delivers_rest_and_records_skipped(two_clones: tuple[Path, Path, Path]) -> None:
    """The batch's other events land; the redundant close is skipped, receipted and never re-sealed."""
    _, first, second = two_clones
    await _close_on_dev(second, "issue:dup")
    redundant = _ev("issue.closed", "issue:dup", {"closed_by": "agent:two", "reason": "fixed by PR"}, 22)
    fresh = _opened("issue:fresh", 23)
    outbox, batch = await _batch_of(first, _opened("issue:dup", 20), redundant, fresh)
    integrator = LedgerIntegrator(first, outbox)

    report = await integrator.integrate(batch)

    assert report.status == "delivered", report
    assert report.added == 1
    assert report.skipped == [redundant.event_id]
    receipt = await outbox.receipt_for(batch.batch_id)
    assert receipt is not None
    assert receipt.skipped_event_ids == [redundant.event_id]
    remote_ids = await integrator.remote_event_ids()
    assert fresh.event_id in remote_ids
    assert redundant.event_id not in remote_ids
    head = _run_git(first, "rev-parse", "HEAD")
    assert await outbox.prepare(repo_root=first, source_ref="HEAD", source_head=head, known_ids=remote_ids) is None
    assert (await outbox.status(known_ids=remote_ids))["unsealed_events"] == 0


async def test_all_redundant_is_already_delivered_without_commit(two_clones: tuple[Path, Path, Path]) -> None:
    """A batch holding only a redundant close creates no commit but is acknowledged."""
    _, first, second = two_clones
    await _close_on_dev(second, "issue:only")
    redundant = _ev("issue.closed", "issue:only", {"closed_by": "agent:two", "reason": "dup"}, 22)
    outbox, batch = await _batch_of(first, redundant)
    _run_git(first, "fetch", "origin", "dev")
    before = _run_git(first, "rev-parse", "origin/dev")

    report = await LedgerIntegrator(first, outbox).integrate(batch)

    assert report.status == "already_delivered", report
    assert report.skipped == [redundant.event_id]
    _run_git(first, "fetch", "origin", "dev")
    assert _run_git(first, "rev-parse", "origin/dev") == before
    receipt = await outbox.receipt_for(batch.batch_id)
    assert receipt is not None
    assert receipt.skipped_event_ids == [redundant.event_id]
