"""Regression cases for FEAT-627 rendering."""

from datetime import date
from pathlib import Path

import pytest

import parrot.knowledge.wiki.standup.render as subject
from parrot.knowledge.wiki.standup.identity import StandupIdentity
from parrot.knowledge.wiki.standup.models import (
    BriefDocument,
    BriefItem,
    BriefSection,
    HygieneReport,
    PeriodWindow,
    ProjectSlice,
)


def _item(identifier: str, title: str, *, section: str = "tickets", **values: object) -> BriefItem:
    """Build a compact item fixture with safe renderer defaults."""
    return BriefItem(id=identifier, kind="ticket", title=title, source="jira", **values)


def _document(*, period: str = "day", **values: object) -> BriefDocument:
    """Build a document fixture with a deterministic period window."""
    window = PeriodWindow(
        period=period,
        anchor=date(2026, 10, 3),
        start=date(2026, 10, 1),
        end=date(2026, 10, 7),
        recent_start=date(2026, 10, 1),
        upcoming_end=date(2026, 10, 7),
        brief_id="brief:daily:2026-10-03",
    )
    return BriefDocument(
        window=window,
        identity=StandupIdentity(wiki="human:test"),
        team=False,
        language="en",
        on_your_plate=[],
        projects=[],
        internal=[],
        delta_new=[],
        delta_closed=[],
        sources=[],
        hygiene=HygieneReport(),
        item_ids=[],
        **values,
    )


def test_daily_en_es_golden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Render daily headings while retaining titles and qualified references."""
    blocked = _item("issues::OPS-7", "Deploy *now*", status="blocked", age_days=2, urgent=True)
    document = _document(
        on_your_plate=["Deploy *now*", "Review plan", "Third", "Not rendered"],
        projects=[
            ProjectSlice(
                project="Roadshows",
                status="active",
                sections=[BriefSection(key="blocked", items=[blocked])],
                activity=1,
            )
        ],
        internal=[BriefSection(key="tasks", items=[_item("TASK-1", "Write docs", source="tasks")])],
        hygiene=HygieneReport(ledger_blockers=1, stale_tickets=2, llm="skipped: no model"),
        diagnostics=["ledger unavailable"],
    )

    assert subject.render_markdown(document, "en") == """# Daily brief — 2026-10-03

## On your plate today

- Deploy \\*now\\*
- Review plan
- Third

## By project

### [[Roadshows]] — active
- **Blocked:** [[issues::OPS-7|Deploy \\*now\\*]] (blocked — 2 days old)

## Internal

- **Tasks:** [[TASK-1|Write docs]] (unknown)

## Hygiene

- Ledger blockers: 1
- Proposed decisions older than threshold: 0
- Stale tickets: 2
- LLM: skipped: no model

### Diagnostics

- ledger unavailable
"""
    spanish = subject.render_markdown(document, "es")
    assert "# Resumen diario — 2026-10-03" in spanish
    assert "## Tus pendientes de hoy" in spanish
    assert "**Bloqueado:** [[issues::OPS-7|Deploy \\*now\\*]]" in spanish
    assert "Deploy *now*" not in spanish


@pytest.mark.parametrize("period,title", [("week", "Weekly brief"), ("month", "Monthly brief")])
def test_weekly_monthly_golden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, period: str, title: str) -> None:
    """Render period roll-ups with their source identifiers and required sections."""
    open_ticket = _item("issues::OPS-8", "Keep open", status="open")
    decision = BriefItem(id="adr::3", kind="decision", title="Choose path", source="adr", status="proposed")
    closed = _item("issues::OPS-1", "Finished", status="closed")
    document = _document(
        period=period,
        projects=[
            ProjectSlice(
                project="Roadshows",
                sections=[
                    BriefSection(key="tickets", items=[open_ticket]),
                    BriefSection(key="decisions", items=[decision]),
                ],
                activity=2,
            )
        ],
        delta_closed=[closed],
        sources=["brief:daily:2026-10-02", "brief:daily:2026-10-01"],
    )

    rendered = subject.render_markdown(document, "en")
    assert f"# {title} — 2026-10-01 to 2026-10-07" in rendered
    assert "## Closed this period" in rendered
    assert "## Still open" in rendered
    assert "## Decisions taken" in rendered
    assert "## Daily brief sources" in rendered
    assert rendered.index("brief:daily:2026-10-01") < rendered.index("brief:daily:2026-10-02")
    assert "On your plate today" not in rendered
    assert "[[issues::OPS-8|Keep open]]" in rendered


def test_empty_and_first_run_sections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Omit empty projects and delta headings on the first run."""
    document = _document(projects=[ProjectSlice(project="Empty", sections=[], activity=0)])

    rendered = subject.render_markdown(document, "en")

    assert "## By project" not in rendered
    assert "## Internal" not in rendered
    assert "## Since last brief" not in rendered
    assert "## Hygiene" in rendered
    with pytest.raises(ValueError, match="Unsupported standup language"):
        subject.render_markdown(document, "fr")
