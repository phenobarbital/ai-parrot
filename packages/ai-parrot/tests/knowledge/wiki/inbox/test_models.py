"""Focused FEAT-626 regression and failure-path tests."""

from pathlib import Path

import pytest

from parrot.knowledge.wiki.inbox.models import (
    RELATIONS,
    ArchiveResult,
    InboxClassification,
    InboxDocResult,
    InboxRunReport,
    LinkChoice,
    LinkSelection,
)


def test_relation_and_status_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject unknown relations/statuses while allowing every declared value."""
    source_uri = tmp_path.as_uri()
    monkeypatch.setenv("PARROT_INBOX_TEST_SOURCE", source_uri)

    for relation in RELATIONS:
        assert LinkChoice(page_id="page:1", rel=relation, why="relevant").rel == relation

    for status in ("admitted", "archived_category", "rejected", "skipped", "failed", "dry_run"):
        assert InboxDocResult(source_uri=source_uri, status=status).status == status

    with pytest.raises(ValueError):
        LinkChoice(page_id="page:1", rel="invalid", why="invalid relation")

    with pytest.raises(ValueError):
        InboxDocResult(source_uri=source_uri, status="invalid")


def test_report_failed_and_json_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover all statuses, failed aggregation and Path JSON serialization."""
    source = tmp_path / "source.md"
    destination = tmp_path / "archive" / "source.md"
    monkeypatch.setenv("PARROT_INBOX_TEST_ARCHIVE", str(destination))
    archive = ArchiveResult(source=source, destination=destination, rejected=False, staged_git=True)
    assert ArchiveResult.model_validate_json(archive.model_dump_json()) == archive

    report = InboxRunReport(
        inbox_dir=str(tmp_path),
        charter_version="1",
        charter_fingerprint="fingerprint",
        models={"lightweight": "test-model"},
        dry_run=False,
        counts={"failed": 1, "skipped": 1},
        documents=[
            InboxDocResult(source_uri=source.as_uri(), status="skipped"),
            InboxDocResult(source_uri=destination.as_uri(), status="failed", error="unreadable"),
        ],
    )

    restored = InboxRunReport.model_validate_json(report.model_dump_json())
    assert restored.counts == report.counts
    assert restored.failed is True
    assert InboxRunReport(
        **report.model_dump(exclude={"documents"}),
        documents=[InboxDocResult(source_uri=source.as_uri(), status="skipped")],
    ).failed is False


def test_mutable_defaults_are_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure rows and selections never share mutable defaults."""
    monkeypatch.setenv("PARROT_INBOX_TEST_DIR", str(tmp_path))
    first_row = InboxDocResult(source_uri=tmp_path.as_uri(), status="skipped")
    second_row = InboxDocResult(source_uri=tmp_path.as_uri(), status="skipped")
    first_classification = InboxClassification(kind="note", title="First", summary="Summary")
    second_classification = InboxClassification(kind="note", title="Second", summary="Summary")
    first_selection = LinkSelection()
    second_selection = LinkSelection()

    first_row.tags.append("tag")
    first_classification.entities.append("entity")
    first_selection.links.append(LinkChoice(page_id="page:1", rel="mentions", why="related"))

    assert second_row.tags == []
    assert second_classification.entities == []
    assert second_selection.links == []
