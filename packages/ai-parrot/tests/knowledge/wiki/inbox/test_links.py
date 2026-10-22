"""Focused FEAT-626 regression and failure-path tests for the link proposer."""

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from parrot.knowledge.wiki.inbox.links import LinkProposer
from parrot.knowledge.wiki.inbox.models import (
    LinkChoice,
    LinkSelection,
    ResolvedClassification,
)


class FakeStore:
    """Mutable in-memory store exposing get_page/search_fts."""

    def __init__(self, pages: dict[str, dict[str, Any]], fts: dict[str, list[str]] | None = None) -> None:
        self.pages = pages
        self.fts = fts or {}

    async def get_page(self, concept_id: str, include_body: bool = True) -> dict[str, Any] | None:
        return self.pages.get(concept_id)

    async def search_fts(self, query: str, category: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        return [{"concept_id": pid} for pid in self.fts.get(query, [])][:limit]


class FakeSearch:
    def __init__(self, ids: list[str]) -> None:
        self.ids = ids

    async def search(self, query: str, **kwargs: Any) -> list[Any]:
        assert kwargs.get("include_archived") is False
        return [SimpleNamespace(node_id=i) for i in self.ids]


class FakeAdapter:
    def __init__(self, result: Any = None, exc: Exception | None = None) -> None:
        self.result = result
        self.exc = exc

    async def ask_structured(self, prompt: str, output_type: type, **kwargs: Any) -> Any:
        if self.exc:
            raise self.exc
        return self.result


def _page(pid: str, category: str = "note") -> dict[str, Any]:
    return {"concept_id": pid, "title": f"T {pid}", "category": category, "summary": f"S {pid}"}


def _cls(tags: list[str] | None = None) -> ResolvedClassification:
    return ResolvedClassification(
        kind="note",
        category="note",
        title="Doc",
        summary="sum",
        tags=tags or [],
        entities=[],
        event_date=None,
        classification_source="model",
    )


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "parrot"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))


def _proposer(store: FakeStore, search_ids: list[str], adapter: Any = None, **kw: Any) -> LinkProposer:
    return LinkProposer(store, FakeSearch(search_ids), adapter, **kw)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_candidates_cap_and_exclusion() -> None:
    """Dedupe more than 30 hits, exclude own pages and honor the cap."""
    ids = [f"p{i}" for i in range(32)]
    store = FakeStore({i: _page(i) for i in ids}, fts={"alpha": ids[:10]})
    proposer = _proposer(store, ids)
    result = await proposer.candidates("text", _cls(["alpha"]), [], {"p0", "p1"})
    got = [c.page_id for c in result]
    assert len(got) == 20
    assert len(set(got)) == 20
    assert "p0" not in got and "p1" not in got
    assert all(c.origin == "search" for c in result)


@pytest.mark.asyncio
async def test_code_pages_only_on_verbatim_mention() -> None:
    """Search cannot introduce unmentioned code pages."""
    store = FakeStore(
        {
            "sym:a.py#A": _page("sym:a.py#A", "code"),
            "file:b/c.py": _page("file:b/c.py", "code"),
            "file:z.py": _page("file:z.py", "code"),
            "n1": _page("n1"),
        },
        fts={"t": ["file:z.py", "n1"]},
    )
    proposer = _proposer(store, ["sym:a.py#A", "file:z.py", "n1"])
    text = "See sym:a.py#A, and `b/c.py`."
    result = await proposer.candidates(text, _cls(["t"]), [], set())
    by_id = {c.page_id: c.origin for c in result}
    assert by_id == {"sym:a.py#A": "verbatim", "file:b/c.py": "verbatim", "n1": "search"}
    links = proposer.deterministic_links(result)
    assert [(link.page_id, link.rel, link.why) for link in links] == [
        ("sym:a.py#A", "references", "verbatim mention"),
        ("file:b/c.py", "references", "verbatim mention"),
    ]


@pytest.mark.asyncio
async def test_select_verifies_ids_and_relations(caplog: pytest.LogCaptureFixture) -> None:
    """Drop invented, deleted and invalid-relation targets."""
    store = FakeStore({"a": _page("a"), "b": _page("b"), "c": _page("c")})
    proposer = _proposer(store, ["a", "b", "c"])
    cands = await proposer.candidates("x", _cls(), [], set())
    bad_rel = LinkChoice.model_construct(page_id="b", rel="bogus", why="w")
    selection = LinkSelection.model_construct(
        links=[
            LinkChoice(page_id="a", rel="relates_to", why="ok"),
            LinkChoice(page_id="ghost", rel="references", why="invented"),
            bad_rel,
            LinkChoice(page_id="c", rel="mentions", why="gone later"),
        ]
    )
    proposer.adapter = FakeAdapter(selection)  # type: ignore[assignment]
    del store.pages["c"]
    with caplog.at_level(logging.WARNING):
        links = await proposer.select("x", _cls(), cands)
    assert [(link.page_id, link.rel) for link in links] == [("a", "relates_to")]
    assert caplog.text.count("LINK_DROPPED") == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["none", "raises", "malformed"])
async def test_select_degrades_without_adapter(mode: str) -> None:
    """Missing, raising and malformed adapters return only verified verbatim links."""
    store = FakeStore({"file:x.py": _page("file:x.py", "code"), "n": _page("n"), "sym:gone": _page("sym:gone")})
    adapter: Any = {
        "none": None,
        "raises": FakeAdapter(exc=RuntimeError("boom")),
        "malformed": FakeAdapter(result={"links": []}),
    }[mode]
    proposer = _proposer(store, ["n"], adapter)
    cands = await proposer.candidates("see `x.py` and sym:gone", _cls(), [], set())
    del store.pages["sym:gone"]
    links = await proposer.select("t", _cls(), cands)
    assert [(link.page_id, link.rel) for link in links] == [("file:x.py", "references")]


@pytest.mark.asyncio
async def test_select_drops_duplicates_and_self_links() -> None:
    """Exercise own-id exclusion through candidates then select and keep first duplicates."""
    store = FakeStore({"self": _page("self"), "a": _page("a")})
    proposer = _proposer(store, ["self", "a"])
    cands = await proposer.candidates("x", _cls(), [], {"self"})
    assert [c.page_id for c in cands] == ["a"]
    selection = LinkSelection(
        links=[
            LinkChoice(page_id="a", rel="follows_up", why="first"),
            LinkChoice(page_id="a", rel="supersedes", why="second"),
            LinkChoice(page_id="self", rel="references", why="self"),
        ]
    )
    proposer.adapter = FakeAdapter(selection)  # type: ignore[assignment]
    links = await proposer.select("x", _cls(), cands)
    assert [(link.page_id, link.rel, link.why) for link in links] == [("a", "follows_up", "first")]
