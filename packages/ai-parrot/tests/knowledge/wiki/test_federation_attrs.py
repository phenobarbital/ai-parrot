"""Regression cases for FEAT-627 — federated attrs reads and local-only writes."""

from __future__ import annotations

from pathlib import Path

import pytest

import parrot.knowledge.wiki.federation as subject
from parrot.knowledge.wiki.project import WikiNamespaceConfig
from parrot.knowledge.wiki.store import AttrsUnsupportedError, SQLiteWikiStore, WikiPageRecord


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep any convention-path lookups inside tmp_path."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdgc"))


def _page(cid: str, attrs: dict[str, str]) -> WikiPageRecord:
    return WikiPageRecord(concept_id=cid, title=cid, attrs=attrs)


def _handle(name: str, store: SQLiteWikiStore, tmp_path: Path) -> subject.NamespaceHandle:
    return subject.NamespaceHandle(name=name, store=store, config=WikiNamespaceConfig(path=str(tmp_path / name)))


async def _fed(tmp_path: Path) -> tuple[subject.FederatedWikiStore, SQLiteWikiStore, SQLiteWikiStore]:
    local = SQLiteWikiStore(tmp_path / "local.db")
    other = SQLiteWikiStore(tmp_path / "other.db")
    await local.upsert_pages([_page("L1", {"type": "ticket", "status": "open"})])
    await other.upsert_pages([_page("F1", {"type": "ticket", "status": "open"}), _page("F2", {"type": "note"})])
    fed = subject.FederatedWikiStore(local, handles=[_handle("other", other, tmp_path)])
    return fed, local, other


async def test_qualified_attrs_routing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Foreign rows are ns-qualified, local stay bare, get_attrs routes by id."""
    fed, local, _other = await _fed(tmp_path)
    assert fed.supports_attrs is True
    rows = await fed.list_by_attrs({"type": "ticket"})
    assert sorted(r["concept_id"] for r in rows) == ["L1", "other::F1"]
    assert {r["namespace"] for r in rows} == {None, "other"}
    assert [r["concept_id"] for r in await fed.list_by_attrs({"type": "ticket"}, limit=1)] in (["L1"], ["other::F1"])
    assert len(await fed.list_by_attrs({"type": "ticket"}, limit=1)) == 1

    assert await fed.get_attrs("L1") == {"type": "ticket", "status": "open"}
    assert await fed.get_attrs("other::F2") == {"type": "note"}
    assert await fed.get_attrs("nope::F2") == {}

    # Scoped to one foreign namespace: rows keep the ns:: prefix.
    scoped = fed.scoped("other")
    assert [r["concept_id"] for r in await scoped.list_by_attrs({"type": "note"})] == ["other::F2"]
    # Date bounds without a key are rejected before any fan-out.
    with pytest.raises(ValueError):
        await fed.list_by_attrs({}, since="2026-01-01")


async def test_unsupported_and_foreign_write_guards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unsupported/failed planes are skipped with evidence; foreign writes are refused."""
    fed, local, other = await _fed(tmp_path)
    third = SQLiteWikiStore(tmp_path / "third.db")
    fourth = SQLiteWikiStore(tmp_path / "fourth.db")
    monkeypatch.setattr(third, "supports_attrs", False, raising=False)

    async def boom(*args, **kwargs):
        raise RuntimeError("plane down")

    monkeypatch.setattr(fourth, "list_by_attrs", boom)
    fed = subject.FederatedWikiStore(
        local,
        handles=[
            _handle("other", other, tmp_path),
            _handle("third", third, tmp_path),
            _handle("fourth", fourth, tmp_path),
        ],
    )
    rows = await fed.list_by_attrs({"type": "ticket"})
    assert sorted(r["concept_id"] for r in rows) == ["L1", "other::F1"]
    skips = {s.name: s for s in fed.last_skipped}
    assert set(skips) == {"third", "fourth"}
    assert "not supported" in skips["third"].detail
    assert "plane down" in skips["fourth"].detail

    # Local write works; foreign and scoped-facade writes do not.
    assert await fed.upsert_attrs("L1", {"owner": "me"}, replace=False) >= 1
    assert (await local.get_attrs("L1"))["owner"] == "me"
    with pytest.raises(ValueError):
        await fed.upsert_attrs("other::F1", {"owner": "me"})
    assert "owner" not in await other.get_attrs("F1")
    with pytest.raises(AttrsUnsupportedError):
        await fed.scoped("other").upsert_attrs("F1", {"owner": "me"})
    assert "owner" not in await other.get_attrs("F1")


async def test_empty_local_store_is_silent_and_read_only(tmp_path: Path) -> None:
    """A namespace-subset facade with no local plane yields empty reads and no local skip."""
    fed, _local, _other = await _fed(tmp_path)
    sub = fed.scoped("other,other")
    assert isinstance(sub, subject.FederatedWikiStore)
    empty = subject._EmptyStore()
    assert await empty.get_attrs("x") == {}
    assert await empty.list_by_attrs({}) == []
    with pytest.raises(AttrsUnsupportedError):
        await empty.upsert_attrs("x", {"a": "b"})
    rows = await sub.list_by_attrs({"type": "note"})
    assert [r["concept_id"] for r in rows] == ["other::F2"]
    assert sub.last_skipped == []
