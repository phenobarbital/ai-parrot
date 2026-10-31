"""FEAT-784 M4 — typed target resolver."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from parrot.knowledge.wiki.decisions.models import SCOPE_INCOMPLETE, TARGET_FOREIGN, TARGET_UNRESOLVED
from parrot.knowledge.wiki.decisions.scope import TargetResolver
from parrot.knowledge.wiki.store import WikiPageRecord


class _StubStructural:
    """Minimal lookup stub — suggestions only."""

    async def lookup(self, query, *, limit=20, **_):
        hits = [SimpleNamespace(symbol_id="sym:pkg/a.py#f")]
        return SimpleNamespace(hits=hits[:limit], total=len(hits))


@pytest.fixture
async def resolver(adr_store, tmp_path):
    """adr_store seeded with file:/sym:/dir: pages for a tiny tree under tmp_path."""
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    await adr_store.upsert_pages(
        [
            WikiPageRecord(concept_id="file:pkg/a.py", content_hash="h1"),
            WikiPageRecord(concept_id="sym:pkg/a.py#f", content_hash="h2"),
            WikiPageRecord(concept_id="dir:pkg"),
        ]
    )
    return TargetResolver(adr_store, root, _StubStructural())


async def test_resolver_exact_only(resolver):
    res, diags = await resolver.resolve("sym:pkg/a.py#g")
    assert res is not None and res.state == "missing" and res.page_id is None
    assert diags[0].code == TARGET_UNRESOLVED
    assert "sym:pkg/a.py#f" in diags[0].message
    ok, diags = await resolver.resolve("sym:pkg/a.py#f")
    assert ok.state == "resolved" and ok.page_id == "sym:pkg/a.py#f" and not diags


async def test_foreign_and_outside_root(resolver):
    for bad in ("file:../etc/passwd", "remote::file:x.py", "url:x.py", "dir:../.."):
        res, diags = await resolver.resolve(bad)
        assert res is None
        assert diags[0].code == TARGET_FOREIGN


async def test_ancestors_of_symbol(resolver):
    assert await resolver.ancestors_of("sym:pkg/a.py#f") == ["file:pkg/a.py", "dir:pkg", "dir:."]
    assert await resolver.ancestors_of("file:pkg/a.py") == ["dir:pkg", "dir:."]
    assert await resolver.ancestors_of("dir:pkg") == ["dir:."]


async def test_dir_expansion_completeness(resolver, adr_store):
    root = resolver._root
    assert await resolver.expand_dir("dir:pkg") == (["file:pkg/a.py"], True)
    (root / "pkg" / "b.py").write_text("x = 1\n", encoding="utf-8")
    ids, complete = await resolver.expand_dir("dir:pkg")
    assert ids == ["file:pkg/a.py", "file:pkg/b.py"] and complete is False
    res, diags = await resolver.resolve("dir:pkg")
    assert res.state == "incomplete" and diags[0].code == SCOPE_INCOMPLETE
    await adr_store.upsert_pages([WikiPageRecord(concept_id="file:pkg/b.py", content_hash="h3")])
    assert await resolver.expand_dir("dir:pkg") == (["file:pkg/a.py", "file:pkg/b.py"], True)
    ids, _ = await resolver.expand_dir("dir:pk")
    assert ids == []
