"""FEAT-694 M1 — shared ledger event log core."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from parrot.knowledge.wiki.ledger import shared_log as sl
from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.log import LedgerLog


def _event(kind: str, subject: str, actor: str = "agent:a", **payload: object) -> LedgerEvent:
    return LedgerEvent(kind=kind, subject=subject, actor=actor, payload=payload)


def _write_events(path: Path, *events: LedgerEvent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(event.model_dump_json() + "\n" for event in events), encoding="utf-8")


def test_append_line_verbatim_and_fsync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = LedgerLog(str(tmp_path / "local.jsonl"))
    fsync_calls: list[int] = []
    monkeypatch.setattr("parrot.knowledge.wiki.ledger.log.os.fsync", fsync_calls.append)

    assert log.append_line('{"raw": true}') == 0
    assert (tmp_path / "local.jsonl").read_bytes() == b'{"raw": true}\n'
    assert len(fsync_calls) == 1
    with pytest.raises(ValueError):
        log.append_line("x" * 4097)


def test_is_shareable_filters_suspension_only() -> None:
    assert not sl.is_shareable(_event("insight.recorded", "insight:a", category="coder_suspension"))
    assert sl.is_shareable(_event("insight.recorded", "insight:a", category="other"))
    assert sl.is_shareable(_event("issue.opened", "issue:a", category="coder_suspension"))


def test_export_creates_then_appends_only(tmp_path: Path) -> None:
    first = _event("issue.opened", "issue:first")
    second = _event("issue.closed", "issue:first")
    local = LedgerLog(str(tmp_path / "local.jsonl"))
    _write_events(Path(local.path), first, second)

    report = sl.export_events(local, tmp_path / "repo")
    assert report.created and report.added == 2 and report.total_committed == 2
    assert sl.export_events(local, tmp_path / "repo").added == 0


def test_export_never_rewrites_dest(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    dest = repo / sl.SHARED_LOG_REL_PATH
    existing = _event("issue.opened", "issue:existing")
    new = _event("issue.opened", "issue:new")
    _write_events(dest, existing)
    local = LedgerLog(str(tmp_path / "local.jsonl"))
    _write_events(Path(local.path), new)

    sl.export_events(local, repo)
    assert dest.read_text(encoding="utf-8") == existing.model_dump_json() + "\n" + new.model_dump_json() + "\n"


def test_export_ensures_trailing_newline(tmp_path: Path) -> None:
    """Export prepends a newline when the committed file does not end with one."""
    repo = tmp_path / "repo"
    dest = repo / sl.SHARED_LOG_REL_PATH
    dest.parent.mkdir(parents=True)
    dest.write_text('{"existing": true}', encoding="utf-8")
    event = _event("issue.opened", "issue:new")
    local = LedgerLog(str(tmp_path / "local.jsonl"))
    _write_events(Path(local.path), event)

    sl.export_events(local, repo)

    assert dest.read_bytes() == b'{"existing": true}\n' + (event.model_dump_json() + "\n").encode()


def test_digest_stable_across_repo_paths(tmp_path: Path) -> None:
    """digest_files produces the same digest regardless of the repository parent path."""
    first_root = tmp_path / "first" / "repo"
    second_root = tmp_path / "sdd" / "second" / "repo"
    first = first_root / sl.SHARED_LOG_REL_PATH
    second = second_root / sl.SHARED_LOG_REL_PATH
    event = _event("issue.opened", "issue:stable")
    _write_events(first, event)
    _write_events(second, event)

    assert sl.digest_files([first], first_root) == sl.digest_files([second], second_root)


def test_import_appends_unknown_in_src_order(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    first = _event("issue.opened", "issue:first")
    second = _event("issue.claimed", "issue:first")
    _write_events(repo / sl.SHARED_LOG_REL_PATH, first, second)
    local = LedgerLog(str(tmp_path / "local.jsonl"))

    report, claims = sl.import_events(local, repo, tmp_path / "marker")
    assert report.added == 2
    assert [event.event_id for event, _ in local.iter_events()] == [first.event_id, second.event_id]
    assert claims == [second]


def test_import_marker_fast_path_and_force(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    event = _event("issue.opened", "issue:first")
    _write_events(repo / sl.SHARED_LOG_REL_PATH, event)
    local = LedgerLog(str(tmp_path / "local.jsonl"))
    marker = tmp_path / "marker"
    sl.import_events(local, repo, marker)
    with monkeypatch.context() as context:
        context.setattr(local, "iter_events", lambda: (_ for _ in ()).throw(AssertionError("read local")))
        assert sl.import_events(local, repo, marker)[0].fast_path
    assert not sl.import_events(local, repo, marker, force=True)[0].fast_path


def test_import_skips_unparseable_line(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    repo = tmp_path / "repo"
    event = _event("issue.opened", "issue:first")
    dest = repo / sl.SHARED_LOG_REL_PATH
    dest.parent.mkdir(parents=True)
    dest.write_text("not json\n" + event.model_dump_json() + "\n", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger=sl.__name__):
        report, _ = sl.import_events(LedgerLog(str(tmp_path / "local.jsonl")), repo, tmp_path / "marker")
    assert report.skipped_unparseable == 1
    assert "unparseable ledger line skipped" in caplog.text


def test_export_skips_ids_present_in_archive(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    event = _event("issue.opened", "issue:first")
    _write_events(repo / sl.ARCHIVE_REL_DIR / "events-2026-09.jsonl", event)
    local = LedgerLog(str(tmp_path / "local.jsonl"))
    _write_events(Path(local.path), event)

    assert sl.export_events(local, repo).added == 0
    assert (repo / sl.SHARED_LOG_REL_PATH).read_text(encoding="utf-8") == ""


def test_import_reads_archives_then_current(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    archived = _event("issue.opened", "issue:archived")
    current = _event("issue.opened", "issue:current")
    _write_events(repo / sl.ARCHIVE_REL_DIR / "events-2026-09.jsonl", archived)
    _write_events(repo / sl.SHARED_LOG_REL_PATH, current)
    local = LedgerLog(str(tmp_path / "local.jsonl"))

    sl.import_events(local, repo, tmp_path / "marker")
    assert [event.subject for event, _ in local.iter_events()] == ["issue:archived", "issue:current"]


def test_live_claims_drops_superseded_claim() -> None:
    """A claim revoked and then re-made by another actor leaves only the later claim (issue:fe3480881432)."""
    events = [
        _event("issue.claimed", "issue:1", claimed_by="task:a"),
        _event("issue.unclaimed", "issue:1", unclaimed_by="task:a", reason="done looking"),
        _event("issue.claimed", "issue:1", claimed_by="task:b"),
    ]

    assert [event.payload["claimed_by"] for event in sl.live_claims(events)] == ["task:b"]


@pytest.mark.parametrize("terminal_kind", ["issue.closed", "issue.superseded"])
def test_live_claims_drops_closed_subject(terminal_kind: str) -> None:
    """A claim revoked by a terminal event for the same subject does not survive."""
    events = [
        _event("issue.claimed", "issue:1", claimed_by="task:a"),
        _event(terminal_kind, "issue:1", reason="resolved elsewhere"),
    ]

    assert sl.live_claims(events) == []


def test_live_claims_keeps_last_claim_per_subject() -> None:
    """Two claims with no revocation between them collapse to the later one."""
    events = [
        _event("issue.claimed", "issue:1", claimed_by="task:a"),
        _event("issue.claimed", "issue:1", claimed_by="task:b"),
    ]

    survivors = sl.live_claims(events)

    assert [event.payload["claimed_by"] for event in survivors] == ["task:b"]


def test_live_claims_is_pure_and_ignores_other_kinds() -> None:
    """Non-claim kinds are ignored, subjects are independent, and the input is untouched."""
    events = [
        _event("issue.opened", "issue:1", title="first"),
        _event("issue.claimed", "issue:1", claimed_by="task:a"),
        _event("issue.opened", "issue:2", title="second"),
        _event("issue.acknowledged", "issue:1", actor="human:jesus"),
        _event("issue.claimed", "issue:2", claimed_by="task:b"),
        _event("issue.linked", "issue:2", rel="about"),
    ]
    unchanged = list(events)

    survivors = sl.live_claims(events)

    # claim order, one per subject, and nothing but claims comes back
    assert [(event.subject, event.payload["claimed_by"]) for event in survivors] == [
        ("issue:1", "task:a"),
        ("issue:2", "task:b"),
    ]
    assert events == unchanged


def test_live_claims_unclaim_without_claim_is_noop() -> None:
    """An unclaim for a subject that was never claimed in this batch is harmless."""
    events = [
        _event("issue.unclaimed", "issue:1", unclaimed_by="task:a", reason="stale"),
        _event("issue.claimed", "issue:2", claimed_by="task:b"),
    ]

    assert [event.subject for event in sl.live_claims(events)] == ["issue:2"]
