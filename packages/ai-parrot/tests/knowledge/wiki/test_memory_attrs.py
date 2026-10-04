"""Regression cases for FEAT-627 memory-store page attributes."""

from pathlib import Path

import pytest

import parrot.knowledge.wiki.file_store as subject
from parrot.knowledge.wiki.store import WikiPageRecord


def _page(concept_id: str, attrs: dict[str, str] | None = None, **kwargs: str) -> WikiPageRecord:
    """Create a minimal page record with entity attrs."""
    return WikiPageRecord(concept_id=concept_id, title=concept_id, attrs=attrs or {}, **kwargs)


@pytest.mark.asyncio
async def test_memory_attrs_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify filtering, defensive copies, and attrs replacement semantics."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    store = subject.InMemoryWikiStore(tmp_path / "pages")
    await store.upsert_pages(
        [
            _page("t1", {"type": "ticket", "status": "open", "date": "2026-10-01"}),
            _page("t2", {"type": "ticket", "status": "done", "date": "2026-10-03"}),
            _page("n1", {"type": "note", "status": "open", "date": "2026-10-05"}),
            _page("plain"),
        ]
    )

    assert store.supports_attrs is True
    assert sorted(row["concept_id"] for row in await store.list_by_attrs({"type": "ticket"})) == ["t1", "t2"]
    assert sorted(row["concept_id"] for row in await store.list_by_attrs({"status": ["open", "done"]})) == [
        "n1",
        "t1",
        "t2",
    ]
    assert sorted(
        row["concept_id"]
        for row in await store.list_by_attrs({}, date_key="date", since="2026-10-03", until="2026-10-05")
    ) == ["n1", "t2"]
    assert await store.list_by_attrs({"status": []}) == []
    with pytest.raises(ValueError, match="date_key"):
        await store.list_by_attrs({}, since="2026-10-01")

    fetched = await store.get_page("t1")
    assert fetched is not None
    fetched["attrs"]["status"] = "mutated"
    attrs = await store.get_attrs("t1")
    attrs["status"] = "changed"
    stub = (await store.list_by_attrs({"type": "ticket"}))[0]
    stub["attrs"]["status"] = "changed-again"
    assert await store.get_attrs("t1") == {"type": "ticket", "status": "open", "date": "2026-10-01"}

    assert await store.upsert_attrs("t1", {"owner": "me"}, replace=False) == 1
    assert (await store.get_attrs("t1"))["owner"] == "me"
    assert await store.upsert_attrs("t1", {"owner": "you"}) == 1
    assert await store.get_attrs("t1") == {"owner": "you"}
    assert await store.upsert_attrs("t1", {}) == 0
    assert await store.get_attrs("t1") == {}
    assert await store.upsert_attrs("missing", {"owner": "you"}) == 0
    replacement_attrs = {"type": "ticket"}
    await store.upsert_pages([_page("t2", replacement_attrs)])
    replacement_attrs["type"] = "mutated"
    assert await store.get_attrs("t2") == {"type": "ticket"}
    assert (await store.stats())["attrs_pages"] == 2


@pytest.mark.asyncio
async def test_attrs_survive_bundle_reload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify attrs persist across CAS and source-slice bundle writes."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    bundle = tmp_path / "pages"
    first = subject.InMemoryWikiStore(bundle)
    assert await first.compare_and_swap_page(_page("cas", {"status": "open"}, content_hash="h1"), None) is True
    assert await first.compare_and_swap_page(_page("cas", {"status": "done"}, content_hash="h2"), "h1") is True
    assert await first.compare_and_swap_page(_page("cas", {"status": "stale"}, content_hash="h3"), "bad") is False
    await first.replace_source_slice(
        "source",
        [_page("s1", {"project": "one"}, source_id="source"), _page("s2", {"project": "two"}, source_id="source")],
    )
    await first.replace_source_slice("source", [_page("s1", {"project": "new"}, source_id="source")])

    second = subject.InMemoryWikiStore(bundle)
    assert await second.get_attrs("cas") == {"status": "done"}
    assert await second.get_attrs("s1") == {"project": "new"}
    assert await second.get_attrs("s2") == {}
    page = await second.get_page("cas", include_body=False)
    assert page is not None and page["attrs"] == {"status": "done"}
