"""Wiki backend registry (FEAT-540 M7)."""

from __future__ import annotations

import pytest
from parrot.knowledge.wiki import federation
from parrot.knowledge.wiki import store as wiki_store
from parrot.knowledge.wiki.project import WikiNamespaceConfig
from parrot.knowledge.wiki.store import (
    is_server_backend,
    resolve_wiki_backend,
    wiki_backend_names,
    wiki_backend_spec,
)


@pytest.fixture(autouse=True)
def _isolate_registry(monkeypatch):
    monkeypatch.setattr(wiki_store, "_EXTRA_BACKENDS", dict(wiki_store._EXTRA_BACKENDS))
    monkeypatch.setattr(wiki_store, "_EXTRA_SPECS", dict(wiki_store._EXTRA_SPECS))


class _Fake:
    async def get_page(self, *a, **k):
        return None


def test_builtins() -> None:
    assert {"sqlite", "memory", "arangodb", "postgres"} <= set(wiki_backend_names())
    assert is_server_backend("arangodb") and is_server_backend("postgres")
    assert not is_server_backend("sqlite") and not is_server_backend("memory")


def test_unknown_backend_lists_known() -> None:
    with pytest.raises(ValueError, match="sqlite"):
        wiki_backend_spec("nope")
    with pytest.raises(ValueError):
        resolve_wiki_backend("nope")


def test_create_wiki_store_sqlite_and_memory(tmp_path) -> None:
    assert isinstance(wiki_store.create_wiki_store(tmp_path, "w", "sqlite"), wiki_store.SQLiteWikiStore)
    mem = wiki_store.create_wiki_store(tmp_path, "w", "memory")
    assert type(mem).__name__ == "InMemoryWikiStore"


def test_register_with_kind_and_options() -> None:
    wiki_store.register_wiki_backend("kinded", lambda **kw: _Fake(), kind="local", resolve_options=lambda cfg: {})
    assert not is_server_backend("kinded")
    assert "kinded" in wiki_backend_names()


def test_legacy_two_arg_register_defaults_to_server() -> None:
    wiki_store.register_wiki_backend("legacy", lambda **kw: _Fake())
    spec = wiki_backend_spec("legacy")
    assert spec.kind == "server" and spec.resolve_options is None


async def test_namespace_dispatch_uses_resolve_options(tmp_path) -> None:
    created: dict = {}

    def factory(**kw):
        created.update(kw)
        return _Fake()

    wiki_store.register_wiki_backend("opt_backend", factory, resolve_options=lambda cfg: {"custom": cfg.database})
    cfg = WikiNamespaceConfig(database="db1", backend="opt_backend")
    store, storage_dir = await federation.open_namespace_store("ns", cfg, base_dir=tmp_path)
    assert isinstance(store, _Fake) and storage_dir is None
    assert created["custom"] == "db1"
    assert "arango_params" not in created


async def test_namespace_dispatch_legacy_gets_arango_params(tmp_path) -> None:
    created: dict = {}

    def factory(**kw):
        created.update(kw)
        return _Fake()

    wiki_store.register_wiki_backend("legacy_db", factory)
    cfg = WikiNamespaceConfig(database="db1", backend="legacy_db")
    await federation.open_namespace_store("ns", cfg, base_dir=tmp_path)
    assert created["database"] == "db1" and "arango_params" in created
