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
