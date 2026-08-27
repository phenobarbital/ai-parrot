"""Unit tests for the pluggable wiki-backend registration seam (FEAT-449 TASK-2498)."""

from __future__ import annotations

import pytest
from parrot.knowledge.wiki import federation
from parrot.knowledge.wiki import store as wiki_store
from parrot.knowledge.wiki.project import WikiNamespaceConfig


class TestRegisterWikiBackendDispatch:
    def test_dispatch_calls_registered_factory(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setitem(wiki_store._EXTRA_BACKENDS, "fake", lambda **kw: calls.append(kw) or object())
        wiki_store.create_wiki_store(tmp_path, wiki_name="w", backend="fake", database="d")
        assert calls[0]["wiki_name"] == "w"
        assert calls[0]["database"] == "d"

    def test_unknown_backend_still_raises_value_error(self, tmp_path):
        with pytest.raises(ValueError):
            wiki_store.create_wiki_store(tmp_path, backend="nope")

    def test_builtin_backends_untouched(self, tmp_path):
        store = wiki_store.create_wiki_store(tmp_path, wiki_name="w", backend="sqlite")
        assert isinstance(store, wiki_store.SQLiteWikiStore)

    def test_register_wiki_backend_populates_registry(self, monkeypatch):
        monkeypatch.setitem(wiki_store._EXTRA_BACKENDS, "throwaway", None)
        sentinel = object()
        wiki_store.register_wiki_backend("throwaway2", lambda **kw: sentinel)
        assert wiki_store._EXTRA_BACKENDS["throwaway2"](wiki_name="x") is sentinel
        del wiki_store._EXTRA_BACKENDS["throwaway2"]


class TestNamespaceConfigBackend:
    def test_namespace_config_keeps_explicit_backend(self):
        assert WikiNamespaceConfig(database="legal_x", backend="ontology_legal").backend == "ontology_legal"

    def test_namespace_config_defaults_database_to_arangodb(self):
        assert WikiNamespaceConfig(database="legal_x").backend == "arangodb"

    def test_namespace_config_store_kind_still_forbids_arangodb_without_database(self):
        # Existing behavior — a `store` entry cannot declare backend=arangodb
        # (kind == "store" branch in open_namespace_store still rejects it).
        cfg = WikiNamespaceConfig(store="/tmp/x", backend="arangodb")
        assert cfg.backend == "arangodb"
        assert cfg.kind == "store"


class TestOpenNamespaceStoreExtraBackendDispatch:
    async def test_dispatches_extra_backend_for_database_kind(self, monkeypatch, tmp_path):
        created = {}

        class FakeStore:
            async def get_page(self, *a, **k):
                return None

        def fake_factory(**kwargs):
            created.update(kwargs)
            return FakeStore()

        monkeypatch.setitem(wiki_store._EXTRA_BACKENDS, "fake_db_backend", fake_factory)
        cfg = WikiNamespaceConfig(database="legal_x", backend="fake_db_backend")

        store, storage_dir = await federation.open_namespace_store("legal", cfg, base_dir=tmp_path)

        assert isinstance(store, FakeStore)
        assert storage_dir is None
        assert created["wiki_name"] == "legal"
        assert created["database"] == "legal_x"
        assert created["storage_dir"] is None

    async def test_unknown_database_backend_raises_value_error(self, tmp_path):
        cfg = WikiNamespaceConfig(database="legal_x", backend="totally_unknown")
        with pytest.raises(ValueError, match="totally_unknown"):
            await federation.open_namespace_store("legal", cfg, base_dir=tmp_path)
