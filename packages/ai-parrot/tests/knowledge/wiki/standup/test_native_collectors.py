"""Regression cases for FEAT-627 native collectors."""

from datetime import date
from pathlib import Path

import pytest

import parrot.knowledge.wiki.standup.collectors.decisions as decisions
import parrot.knowledge.wiki.standup.collectors.ledger as ledger
import parrot.knowledge.wiki.standup.collectors.memories as memories
import parrot.knowledge.wiki.standup.collectors.tasks as subject
from parrot.knowledge.wiki.project import StandupConfig
from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.identity import StandupIdentity
from parrot.knowledge.wiki.standup.models import PeriodWindow


class FakeStore:
    """Small async store fake exposing the collectors' read seams."""

    def __init__(self, pages: list[dict[str, object]]) -> None:
        self.pages = pages

    async def list_pages(self, **_kwargs: object) -> list[dict[str, object]]:
        return self.pages


def _context(root: Path, store: object, *, period: str = "day") -> CollectContext:
    """Build a deterministic collector context."""
    return CollectContext.model_construct(
        root=root,
        store=store,
        cfg=StandupConfig(),
        window=PeriodWindow(
            period=period,
            anchor=date(2026, 10, 3),
            start=date(2026, 10, 1),
            end=date(2026, 10, 7),
            recent_start=date(2026, 9, 26),
            upcoming_end=date(2026, 10, 10),
            brief_id="brief:test",
        ),
        identity=StandupIdentity(wiki="human:me", aliases=["agent:me"]),
        team=False,
        diagnostics=[],
        unmapped_statuses={},
    )


@pytest.mark.asyncio
async def test_ledger_and_task_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ledger ownership, blockers, task readiness and malformed indexes."""
    index = tmp_path / "sdd" / "tasks" / "index"
    index.mkdir(parents=True)
    (index / "feature.json").write_text(
        '{"feature_id":"FEAT-1","tasks":[{"id":"TASK-1","title":"Done","status":"done"},'
        '{"id":"TASK-2","title":"Ready","status":"pending","depends_on":["TASK-1"],'
        '"assigned_to":"human:me"},{"id":"TASK-3","title":"Blocked","status":"pending",'
        '"depends_on":["TASK-X"]},{"id":"TASK-4","title":"Active","status":"in-progress",'
        '"assigned_to":"agent:me"}]}',
        encoding="utf-8",
    )
    (index / "bad.json").write_text("{", encoding="utf-8")
    context = _context(tmp_path, FakeStore([]))

    task_items = await subject.collect(context)

    assert [(item.id, item.status_raw) for item in task_items] == [("TASK-2", "ready"), ("TASK-4", None)]
    assert any(line.startswith("tasks:bad.json:") for line in context.diagnostics)

    class FakeLedger:
        async def list_issues(self, statuses: tuple[str, ...]) -> list[dict[str, object]]:
            assert statuses == ("open", "claimed")
            return [
                {"issue_id": "issue:1", "title": "Critical", "status": "open", "claimed_by": "human:me"},
                {"issue_id": "issue:2", "title": "Elsewhere", "status": "claimed", "claimed_by": "other"},
            ]

        async def merge_blockers(self, feature_id: str) -> list[dict[str, object]]:
            assert feature_id == "FEAT-1"
            return [{"issue_id": "issue:1"}]

    monkeypatch.setattr(ledger, "find_shared_root", lambda root: root)
    monkeypatch.setattr(ledger.LedgerService, "from_root", lambda root: FakeLedger())
    ledger_items = await ledger.collect(context)

    assert [(item.id, item.status, item.urgent, item.owner) for item in ledger_items] == [
        ("issue:1", "blocked", True, "human:me")
    ]


@pytest.mark.asyncio
async def test_decision_and_memory_ownership(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ADR metadata ownership and memory filtering."""
    class Record:
        decision_id = "adr:one"
        title = "Proposed"
        source_status = "proposed"
        origin = "documented"
        review_status = "unreviewed"

    class FakeRepository:
        def __init__(self, _store: object) -> None:
            pass

        async def inventory(self) -> list[Record]:
            return [Record()]

    monkeypatch.setattr(decisions, "DecisionRepository", FakeRepository)
    store = FakeStore(
        [
            {"concept_id": "adr:one", "updated_at": "2026-10-02T10:00:00+00:00", "asserted_by": "human:me"},
            {"concept_id": "memory:mine", "title": "Note", "category": "note", "updated_at": "2026-10-03T10:00:00+00:00", "asserted_by": "human:me"},
            {"concept_id": "brief:daily", "category": "brief", "updated_at": "2026-10-03T10:00:00+00:00", "asserted_by": "human:me"},
            {"concept_id": "memory:other", "category": "lesson", "updated_at": "2026-10-03T10:00:00+00:00", "asserted_by": "other"},
        ]
    )
    context = _context(tmp_path, store)

    decision_items = await decisions.collect(context)
    memory_items = await memories.collect(context)

    assert [(item.id, item.owner, item.age_days) for item in decision_items] == [("adr:one", "human:me", 1)]
    assert [(item.id, item.kind) for item in memory_items] == [("memory:mine", "deliverable")]


@pytest.mark.asyncio
async def test_missing_native_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify each failing native source reports a diagnostic and remains non-fatal."""
    context = _context(tmp_path, FakeStore([]))
    monkeypatch.setattr(ledger, "find_shared_root", lambda root: None)

    assert await ledger.collect(context) == []
    assert context.diagnostics == ["ledger: shared root unavailable"]
