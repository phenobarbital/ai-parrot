"""Tests for the ``create_wiki_store(backend="arangodb")`` factory branch
and package export (FEAT-400, TASK-2059).

No real ArangoDB server is touched — ``ArangoDBWikiStore.__init__`` is
synchronous (it only stores params; the connection happens lazily in
``initialize()``), so these tests exercise the factory dispatch and the
package's lazy export without any mocking.
"""

from pathlib import Path

import pytest
from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore
from parrot.knowledge.wiki.store import (
    BaseWikiStore,
    SQLiteWikiStore,
    create_wiki_store,
)


class TestCreateWikiStoreArangoBranch:
    """``create_wiki_store()`` dispatches to ``ArangoDBWikiStore``."""

    def test_arangodb_backend_returns_arango_store(self, tmp_path: Path):
        store = create_wiki_store(tmp_path, wiki_name="test-wiki", backend="arangodb")
        assert isinstance(store, ArangoDBWikiStore)
        assert isinstance(store, BaseWikiStore)

    def test_arangodb_backend_passes_wiki_name(self, tmp_path: Path):
        store = create_wiki_store(tmp_path, wiki_name="test-wiki", backend="arangodb")
        assert store._wiki_name == "test-wiki"
        assert store._database == "wiki_test-wiki"

    def test_arangodb_backend_accepts_arango_params_kwarg(self, tmp_path: Path):
        params = {"host": "arango.internal", "port": 8530}
        store = create_wiki_store(
            tmp_path, wiki_name="test-wiki", backend="arangodb", arango_params=params
        )
        assert store._params == params

    def test_arangodb_backend_accepts_database_kwarg(self, tmp_path: Path):
        store = create_wiki_store(
            tmp_path, wiki_name="test-wiki", backend="arangodb", database="custom_db"
        )
        assert store._database == "custom_db"

    def test_arangodb_backend_accepts_text_analyzer_kwarg(self, tmp_path: Path):
        store = create_wiki_store(
            tmp_path,
            wiki_name="test-wiki",
            backend="arangodb",
            text_analyzer="text_es",
        )
        assert store._text_analyzer == "text_es"

    def test_arangodb_backend_default_text_analyzer(self, tmp_path: Path):
        store = create_wiki_store(tmp_path, wiki_name="test-wiki", backend="arangodb")
        assert store._text_analyzer == "text_en"

    def test_sqlite_backend_unchanged(self, tmp_path: Path):
        store = create_wiki_store(tmp_path, wiki_name="test-wiki", backend="sqlite")
        assert isinstance(store, SQLiteWikiStore)

    def test_memory_backend_unchanged(self, tmp_path: Path):
        from parrot.knowledge.wiki.file_store import InMemoryWikiStore

        store = create_wiki_store(tmp_path, wiki_name="test-wiki", backend="memory")
        assert isinstance(store, InMemoryWikiStore)

    def test_unknown_backend_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Unknown wiki storage backend"):
            create_wiki_store(tmp_path, wiki_name="test-wiki", backend="postgres")


class TestPackageExport:
    """``ArangoDBWikiStore`` is importable from ``parrot.knowledge.wiki``."""

    def test_arango_db_wiki_store_importable_from_package(self):
        import parrot.knowledge.wiki as wiki_pkg

        assert wiki_pkg.ArangoDBWikiStore is ArangoDBWikiStore

    def test_arango_db_wiki_store_in_all(self):
        import parrot.knowledge.wiki as wiki_pkg

        assert "ArangoDBWikiStore" in wiki_pkg.__all__
