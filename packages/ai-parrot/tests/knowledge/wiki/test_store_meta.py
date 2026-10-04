"""FEAT-609 Q2: per-backend plane metadata (get_meta / set_meta)."""

from __future__ import annotations

import pytest
from parrot.knowledge.wiki.project import WikiNamespaceConfig
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle, _EmptyStore
from parrot.knowledge.wiki.file_store import InMemoryWikiStore
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore


async def test_meta_roundtrip_sqlite(tmp_path) -> None:
    store = SQLiteWikiStore(tmp_path / "wiki.db", "t")
    assert await store.get_meta("k") is None
    await store.set_meta("k", "v1")
    await store.set_meta("k", "v2")
    assert await store.get_meta("k") == "v2"
    assert await store.get_meta("other") is None


async def test_meta_read_only_refuses(tmp_path) -> None:
    db = tmp_path / "wiki.db"
    writable = SQLiteWikiStore(db, "t")
    await writable.set_meta("k", "v")
    ro = SQLiteWikiStore(db, "t", read_only=True)
    assert await ro.get_meta("k") == "v"
    with pytest.raises(PermissionError):
        await ro.set_meta("k", "x")
    assert await ro.get_meta("k") == "v"


async def test_meta_roundtrip_memory_survives_reopen(tmp_path) -> None:
    store = InMemoryWikiStore(tmp_path / "bundle", "t")
    assert await store.get_meta("k") is None
    await store.set_meta("k", "v")
    reopened = InMemoryWikiStore(tmp_path / "bundle", "t")
    assert await reopened.get_meta("k") == "v"
    assert await reopened.get_meta("nope") is None


async def test_meta_memory_corrupt_file_is_empty(tmp_path) -> None:
    bundle = tmp_path / "bundle"
    store = InMemoryWikiStore(bundle, "t")
    (bundle / ".meta.json").write_text("{not json", encoding="utf-8")
    assert await store.get_meta("k") is None
    await store.set_meta("k", "v")
    assert await InMemoryWikiStore(bundle, "t").get_meta("k") == "v"


async def test_meta_roundtrip_federated_local_only(tmp_path) -> None:
    local = SQLiteWikiStore(tmp_path / "local.db", "l")
    fed = FederatedWikiStore(local)
    assert await fed.get_meta("k") is None
    await fed.set_meta("k", "v")
    assert await local.get_meta("k") == "v"
    assert await fed.get_meta("k") == "v"


async def test_federated_meta_never_writes_foreign(tmp_path) -> None:
    foreign_db = tmp_path / "foreign.db"
    foreign = SQLiteWikiStore(foreign_db, "f")
    await foreign.set_meta("k", "foreign-value")
    local = SQLiteWikiStore(tmp_path / "local.db", "l")
    handle = NamespaceHandle(
        name="f", store=foreign, config=WikiNamespaceConfig(store=str(tmp_path)), storage_dir=tmp_path
    )
    fed = FederatedWikiStore(local, handles=[handle])
    await fed.set_meta("k", "local-value")
    assert await foreign.get_meta("k") == "foreign-value"
    assert await local.get_meta("k") == "local-value"


async def test_empty_store_meta() -> None:
    empty = _EmptyStore()
    assert await empty.get_meta("k") is None
    with pytest.raises(PermissionError):
        await empty.set_meta("k", "v")


async def test_base_default_raises_not_implemented() -> None:
    """Backends that do not override the pair keep working, and say so."""
    stub = object()  # the defaults never touch ``self`` beyond its type name
    with pytest.raises(NotImplementedError):
        await BaseWikiStore.get_meta(stub, "k")  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError):
        await BaseWikiStore.set_meta(stub, "k", "v")  # type: ignore[arg-type]
