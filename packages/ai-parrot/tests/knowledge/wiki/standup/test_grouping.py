"""Regression cases for FEAT-627."""

import random
from datetime import date
from pathlib import Path

import pytest

import parrot.knowledge.wiki.standup.grouping as subject
from parrot.knowledge.wiki.project import StandupConfig
from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.identity import StandupIdentity
from parrot.knowledge.wiki.standup.models import BriefItem, PeriodWindow


class FakeStore:
    """Async store fake with project pages."""

    supports_attrs = True

    def __init__(self, pages: list[dict[str, object]]) -> None:
        self.pages = pages

    async def list_by_attrs(self, filters: object, **_kwargs: object) -> list[dict[str, object]]:
        del filters
        return self.pages

    async def get_page(self, concept_id: str, **_kwargs: object) -> dict[str, object] | None:
        return next((p for p in self.pages if p["concept_id"] == concept_id), None)


def _ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_map: dict[str, str] | None = None) -> CollectContext:
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    pages = [
        {"concept_id": "project:atlas", "title": "Atlas Platform", "attrs": {"type": "project", "status": "active"}},
        {"concept_id": "project:zeta", "title": "Zeta", "attrs": {"type": "project"}},
    ]
    window = PeriodWindow(
        period="day",
        anchor=date(2026, 10, 3),
        start=date(2026, 10, 3),
        end=date(2026, 10, 3),
        recent_start=date(2026, 9, 26),
        upcoming_end=date(2026, 10, 10),
        brief_id="brief:daily:2026-10-03",
    )
    return CollectContext.model_construct(
        root=tmp_path,
        store=FakeStore(pages),
        cfg=StandupConfig(project_map=project_map or {}),
        window=window,
        identity=StandupIdentity.model_construct(),
        team=False,
        diagnostics=[],
        unmapped_statuses={},
    )


def _item(id_: str, kind: str = "ticket", hint: str | None = None, **kw: object) -> BriefItem:
    kw.setdefault("source", "jira")
    return BriefItem(id=id_, kind=kind, title=id_, project_hint=hint, **kw)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_project_resolution_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify project resolution chain."""
    ctx = _ctx(tmp_path, monkeypatch, {"NAV": "project:zeta", "OPS": "Operations"})
    assert await subject.resolve_project(_item("a", hint="project:atlas"), ctx) == "Atlas Platform"
    assert await subject.resolve_project(_item("b", hint="Atlas Platform"), ctx) == "Atlas Platform"
    assert await subject.resolve_project(_item("c", hint="NAV"), ctx) == "Zeta"
    assert await subject.resolve_project(_item("d", hint="OPS"), ctx) == "Operations"
    assert await subject.resolve_project(_item("e", hint="XYZ"), ctx) == "XYZ"
    sdd = _item("f", kind="task", hint="my-feature", source="sdd")
    assert await subject.resolve_project(sdd, ctx) == "my-feature"
    assert await subject.resolve_project(_item("g"), ctx) == "Internal"
    other = _item("h", kind="meeting", hint="unknown", source="meeting")
    assert await subject.resolve_project(other, ctx) == "Internal"


@pytest.mark.asyncio
async def test_stable_urgent_first_grouping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify stable urgent first grouping."""
    ctx = _ctx(tmp_path, monkeypatch)
    items = [
        _item("t1", hint="project:atlas", status="open", date=date(2026, 10, 1)),
        _item("t2", hint="project:atlas", status="open", date=date(2026, 9, 1)),
        _item("t3", hint="project:atlas", status="blocked", urgent=True),
        _item("t4", hint="project:atlas", status="open", urgent=True, date=date(2026, 10, 2)),
        _item("z1", hint="project:zeta", status="open"),
        _item("m1", kind="meeting", status=None, hint="project:zeta", source="meeting", date=date(2026, 10, 5)),
        _item("m2", kind="meeting", status=None, hint="project:zeta", source="meeting", date=date(2026, 9, 30)),
        _item("d1", kind="decision", source="decisions"),
        _item("i1", kind="task", source="sdd", status="open"),
    ]
    expected = await subject.group_items(items, ctx)
    for seed in range(5):
        shuffled = list(items)
        random.Random(seed).shuffle(shuffled)
        assert await subject.group_items(shuffled, ctx) == expected
    projects, internal = expected
    assert [p.project for p in projects] == ["Atlas Platform", "Zeta"]
    atlas = projects[0]
    assert atlas.status == "active" and atlas.activity == 4
    assert [s.key for s in atlas.sections] == ["blocked", "tickets"]
    assert [i.id for i in atlas.sections[1].items] == ["t4", "t2", "t1"]
    zeta = projects[1]
    assert [s.key for s in zeta.sections] == ["tickets", "recent", "upcoming"]
    assert [s.key for s in internal] == ["decisions", "tasks"]
    all_ids = sorted(i.id for p in projects for s in p.sections for i in s.items) + [
        i.id for s in internal for i in s.items
    ]
    assert sorted(all_ids) == sorted(i.id for i in items)
