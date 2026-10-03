"""Regression cases for FEAT-627."""

from datetime import date
from pathlib import Path

import pytest

import parrot.knowledge.wiki.standup.collectors.entities as subject
from parrot.knowledge.wiki.project import StandupConfig
from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.collectors import jira
from parrot.knowledge.wiki.standup.identity import StandupIdentity
from parrot.knowledge.wiki.standup.models import PeriodWindow


class FakeStore:
    """Small async store fake exposing the collector read seam."""

    def __init__(self, rows: list[dict[str, object]], supports_attrs: bool = True) -> None:
        self.rows = rows
        self.supports_attrs = supports_attrs

    async def list_by_attrs(self, filters: object, **_kwargs: object) -> list[dict[str, object]]:
        del filters
        return self.rows

    async def list_pages(self, category: str | None = None, **_kwargs: object) -> list[dict[str, object]]:
        return [row for row in self.rows if row.get("category") == category]

    async def get_page(self, concept_id: str, **_kwargs: object) -> dict[str, object] | None:
        return next((row for row in self.rows if row["concept_id"] == concept_id), None)


class FakeFederation(FakeStore):
    """Issue namespace selector used by Jira collector tests."""

    def __init__(self, issues: FakeStore) -> None:
        super().__init__([])
        self.issues = issues

    def scoped(self, selector: str | None) -> FakeStore:
        if selector != "issues":
            raise KeyError(selector)
        return self.issues


class FakeMissingIssues(FakeStore):
    """Federation fake whose issues namespace is deliberately absent."""

    def scoped(self, selector: str | None) -> FakeStore:
        raise KeyError(selector)


def _context(store: object, *, period: str = "day", team: bool = False) -> CollectContext:
    """Build a deterministic collector context."""
    return CollectContext.model_construct(
        root=Path("."),
        store=store,
        cfg=StandupConfig(ticket_status_map={"To Do": "open", "Done": "closed", "Blocked": "blocked"}),
        window=PeriodWindow(
            period=period,
            anchor=date(2026, 10, 3),
            start=date(2026, 10, 1),
            end=date(2026, 10, 7),
            recent_start=date(2026, 9, 26),
            upcoming_end=date(2026, 10, 10),
            brief_id="brief:test",
        ),
        identity=StandupIdentity(wiki="human:me", jira_account_id="acct-1", jira_display_name="Me"),
        team=team,
        diagnostics=[],
        unmapped_statuses={},
    )


@pytest.mark.asyncio
async def test_entity_attrs_and_body_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify entity attrs and body fallback."""
    del tmp_path, monkeypatch
    attrs = {
        "type": "meeting",
        "status": "scheduled",
        "date": "2026-10-04",
        "owner": "human:me",
        "source": "vault",
    }
    attr_store = FakeStore([{"concept_id": "file:meeting.md", "title": "Planning", "attrs": attrs}])
    fallback_store = FakeStore(
        [
            {
                "concept_id": "file:meeting.md",
                "title": "Planning",
                "category": "document",
                "body": "# meeting.md\n\n## Content\n---\ntype: meeting\nstatus: scheduled\ndate: 2026-10-04\nowner: human:me\n---\n",
            }
        ],
        supports_attrs=False,
    )

    attr_items = await subject.collect(_context(attr_store))
    fallback_context = _context(fallback_store)
    fallback_items = await subject.collect(fallback_context)

    assert [item.id for item in attr_items] == [item.id for item in fallback_items] == ["file:meeting.md"]
    assert fallback_context.diagnostics == ["entities:local: attrs unsupported; using body frontmatter fallback"]


@pytest.mark.asyncio
async def test_jira_identity_statuses_and_periods(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify jira identity statuses and periods."""
    del tmp_path, monkeypatch
    rows = [
        {
            "concept_id": "file:NAV-1.md",
            "title": "Blocked work",
            "updated_at": "2026-10-01T12:00:00+00:00",
            "attrs": {"type": "ticket", "source": "jira", "status_raw": "Blocked", "x_assignee_id": "acct-1"},
        },
        {
            "concept_id": "file:NAV-2.md",
            "title": "Display fallback",
            "attrs": {"type": "ticket", "source": "markdown", "status_raw": "Custom", "x_assignee": "Me"},
        },
        {
            "concept_id": "file:NAV-3.md",
            "title": "Wrong ID wins",
            "attrs": {
                "type": "ticket",
                "source": "jira",
                "status_raw": "To Do",
                "x_assignee_id": "other",
                "x_assignee": "Me",
            },
        },
        {
            "concept_id": "file:NAV-4.md",
            "title": "Closed rollup",
            "attrs": {
                "type": "ticket",
                "source": "jira",
                "status_raw": "Done",
                "x_assignee_id": "acct-1",
                "date": "2026-10-02",
            },
        },
    ]
    context = _context(FakeFederation(FakeStore(rows)), period="week")

    items = await jira.collect(context)

    assert [item.id for item in items] == ["issues::file:NAV-1.md", "issues::file:NAV-4.md", "issues::file:NAV-2.md"]
    # Collector order: urgent first, then dated before undated, then id.
    assert [item.status for item in items] == ["blocked", "closed", "open"]
    assert context.unmapped_statuses == {"Custom": 1}
    missing_context = _context(FakeFederation(FakeStore(rows)), period="day")
    assert "issues::file:NAV-4.md" not in [item.id for item in await jira.collect(missing_context)]
    unavailable_context = _context(FakeMissingIssues([]))
    assert await jira.collect(unavailable_context) == []
    assert unavailable_context.diagnostics == ["jira:issues unavailable: 'issues'"]
