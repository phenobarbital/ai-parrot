"""Regression cases for FEAT-627."""

from pathlib import Path

import pytest

import parrot.knowledge.wiki.entities as subject


def test_normalize_aliases_dates_and_statuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify normalize aliases dates and statuses."""
    monkeypatch.chdir(tmp_path)
    attrs = subject.normalize_frontmatter(
        {
            "type": "meeting-source",
            "meeting_date": "2026-10-03T09:30:00+00:00",
            "primary_project": "Parrot",
            "projects": ["Parrot", "Wiki"],
            "status": "HELD",
            "assignee_id": "jira-user-1",
            "assignee": "Ada",
            "custom_flag": True,
        },
        source="vault",
    )

    assert attrs.type == "meeting"
    assert attrs.status == "held"
    assert attrs.status_raw == "HELD"
    assert attrs.date == "2026-10-03"
    assert attrs.project == "Parrot"
    assert attrs.source == "vault"
    assert attrs.to_rows() == {
        "type": "meeting",
        "status": "held",
        "status_raw": "HELD",
        "project": "Parrot",
        "date": "2026-10-03",
        "source": "vault",
        "x_projects": "Parrot,Wiki",
        "x_assignee_id": "jira-user-1",
        "x_assignee": "Ada",
        "x_custom_flag": "True",
    }

    listed_project = subject.normalize_frontmatter(
        {"type": "issue", "projects": ["Parrot", "Wiki"], "status": "not-mapped"}, source="jira"
    )
    assert listed_project.type == "ticket"
    assert listed_project.project == "Parrot"
    assert listed_project.status is None
    assert listed_project.status_raw == "not-mapped"
    assert listed_project.extra["projects"] == "Parrot,Wiki"

    assert subject.STATUS_BY_TYPE == {
        "project": ("active", "paused", "done", "archived"),
        "engagement": ("active", "paused", "done", "archived"),
        "meeting": ("scheduled", "held", "cancelled"),
        "ticket": ("open", "in-progress", "blocked", "in-review", "closed"),
        "task": ("pending", "in-progress", "done", "done-with-issues"),
        "decision": ("proposed", "accepted", "rejected", "superseded", "deprecated"),
        "deliverable": ("draft", "sent", "approved", "rejected"),
        "person": (),
    }
    assert subject.OPEN_STATUSES["ticket"] == {"open", "in-progress", "blocked", "in-review"}
    assert subject.OPEN_STATUSES["task"] == {"pending", "in-progress"}
    assert subject.URGENT_STATUSES == {"blocked"}


def test_strict_errors_and_malformed_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify strict errors and malformed yaml."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(subject.EntityValidationError, match="Unknown entity type") as error:
        subject.normalize_frontmatter({"type": "unknown"}, source="entity-cli", strict=True)
    assert error.value.code == "E_ENTITY_TYPE"

    with pytest.raises(subject.EntityValidationError, match="Invalid status") as error:
        subject.normalize_frontmatter({"type": "ticket", "status": "waiting"}, source="entity-cli", strict=True)
    assert error.value.code == "E_ENTITY_STATUS"

    with pytest.raises(subject.EntityValidationError, match="Invalid due") as error:
        subject.normalize_frontmatter({"type": "task", "due_date": "tomorrow"}, source="entity-cli", strict=True)
    assert error.value.code == "E_ENTITY_DATE"

    assert subject.parse_leading_yaml("title: no opening delimiter") is None
    assert subject.parse_leading_yaml("---\nnot a mapping block\n---\n# Title") is None
    assert subject.parse_leading_yaml("---\ntitle: [unclosed\n---\n# Title") is None
    assert subject.parse_leading_yaml("---\n- a list\n---\n# Title") is None
    assert subject.parse_leading_yaml("---\ntitle: valid\n---\n# Title") == {"title": "valid"}


def test_canonical_ticket_status_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify canonical ticket status map."""
    monkeypatch.chdir(tmp_path)
    status_map = {"To Do": "open", "In Progress": "in-progress", "Done": "closed"}

    assert subject.canonical_ticket_status("to do", status_map) == "open"
    assert subject.canonical_ticket_status("IN PROGRESS", status_map) == "in-progress"
    assert subject.canonical_ticket_status("Unknown", status_map) is None
    assert subject.canonical_ticket_status(None, status_map) is None
