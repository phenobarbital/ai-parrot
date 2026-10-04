"""Regression cases for FEAT-627."""

from datetime import date
from pathlib import Path

import pytest

import parrot.knowledge.wiki.standup.models as subject
from parrot.knowledge.wiki.project import StandupConfig
from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.config import StandupConfig as ExportedStandupConfig
from parrot.knowledge.wiki.standup.identity import StandupIdentity


def test_model_serialization_and_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify model serialization and defaults."""
    del tmp_path, monkeypatch
    window = subject.PeriodWindow(
        period="day",
        anchor=date(2026, 10, 3),
        start=date(2026, 10, 3),
        end=date(2026, 10, 3),
        recent_start=date(2026, 9, 26),
        upcoming_end=date(2026, 10, 10),
        brief_id="brief:daily:2026-10-03",
    )
    item = subject.BriefItem(
        id="file:NAV-10016.md",
        kind="ticket",
        title="Complete the standup models",
        date=date(2026, 10, 3),
        source="jira",
    )
    section = subject.BriefSection(key="tickets", items=[item])
    project = subject.ProjectSlice(project="parrot", sections=[section], activity=1)
    hygiene = subject.HygieneReport()
    document = subject.BriefDocument(
        window=window,
        identity=StandupIdentity(wiki="human:jesus"),
        team=False,
        language="en",
        on_your_plate=["Complete the standup models"],
        projects=[project],
        internal=[section],
        delta_new=[item],
        delta_closed=[],
        sources=["jira"],
        hygiene=hygiene,
        item_ids=[item.id],
    )

    serialized = document.model_dump(mode="json")

    assert serialized["window"]["anchor"] == "2026-10-03"
    assert serialized["delta_new"][0]["date"] == "2026-10-03"
    assert document.diagnostics == []
    assert document.written_page is False
    assert document.written_file is None
    hygiene.unmapped_statuses["Custom"] = 1
    document.diagnostics.append("offline")
    assert subject.HygieneReport().unmapped_statuses == {}
    assert (
        subject.BriefDocument(
            window=window,
            identity=StandupIdentity(wiki="human:jesus"),
            team=False,
            language="en",
            on_your_plate=[],
            projects=[],
            internal=[],
            delta_new=[],
            delta_closed=[],
            sources=[],
            hygiene=subject.HygieneReport(),
            item_ids=[],
        ).diagnostics
        == []
    )
    assert ExportedStandupConfig is StandupConfig
    assert CollectContext.model_config["arbitrary_types_allowed"] is True
    assert set(CollectContext.model_fields) == {
        "root",
        "store",
        "cfg",
        "window",
        "identity",
        "team",
        "diagnostics",
        "unmapped_statuses",
    }


def test_projection_rejects_unbounded_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify projection rejects unbounded fields."""
    del tmp_path, monkeypatch
    item = {
        "kind": "ticket",
        "title": "Bounded title",
        "status": "open",
        "project": "parrot",
        "age_days": 1,
        "urgent": False,
    }
    projection = subject.BriefProjection(period="day", language="en", items=[item])

    assert projection.items == [item]
    with pytest.raises(ValueError):
        subject.BriefProjection(period="day", language="en", items=[item] * 41)
    with pytest.raises(ValueError):
        subject.BriefProjection(period="day", language="en", items=[{**item, "body": "private"}])
    with pytest.raises(ValueError):
        subject.BriefProjection(period="day", language="en", items=[{**item, "title": "x" * 121}])
