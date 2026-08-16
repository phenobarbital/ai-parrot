"""Regression tests for LLMWikiToolkit's ArangoDB backend wiring.

FEAT-400 code review caught that ``LLMWikiToolkit.__init__``'s sources
wiring had an ``else`` branch meant for ``"memory"`` that also silently
caught ``"arangodb"``, routing every agent-facing source-tracking tool
through a local ``.manifest.json`` instead of the ``wiki_sources``
ArangoDB collection. These tests pin the fix: the toolkit must wire
``SourceCollectionManager(backend="arangodb", arango_store=self._store)``.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit


@pytest.fixture
def mock_arango_driver():
    """Mocked ``asyncdb`` ArangoDB driver instance."""
    db = MagicMock()
    db.connection = AsyncMock(return_value=db)
    db.close = AsyncMock()
    db.collection_exists = AsyncMock(return_value=False)
    db.create_collection = AsyncMock()
    db.query = AsyncMock(return_value=([], None))
    db.execute = AsyncMock(return_value=([], None))
    db._connection = MagicMock()
    db._connection.views = AsyncMock(return_value=[])
    db._connection.create_view = AsyncMock()
    return db


@pytest.fixture
def arango_wiki_config(tmp_path: Path) -> WikiConfig:
    return WikiConfig(
        wiki_name="test-wiki", storage_dir=tmp_path, storage_backend="arangodb"
    )


class TestLLMWikiToolkitArangoWiring:
    """``LLMWikiToolkit`` correctly wires the arangodb sources backend."""

    def test_sources_backend_is_arangodb(
        self, arango_wiki_config, mock_arango_driver
    ):
        with patch(
            "parrot.knowledge.wiki.arango_store.AsyncDB",
            return_value=mock_arango_driver,
        ):
            toolkit = LLMWikiToolkit(
                MagicMock(), MagicMock(), MagicMock(), arango_wiki_config
            )
        assert isinstance(toolkit._store, ArangoDBWikiStore)
        assert isinstance(toolkit._sources, SourceCollectionManager)
        assert toolkit._sources.backend == "arangodb"

    def test_sources_lazily_shares_the_store_connection(
        self, arango_wiki_config, mock_arango_driver
    ):
        """No arango_db is connected yet at __init__ time (sync ctor) —
        the manager must hold a lazy `arango_store` reference, not an
        eagerly-required (and here, impossible-to-provide) connection.
        """
        with patch(
            "parrot.knowledge.wiki.arango_store.AsyncDB",
            return_value=mock_arango_driver,
        ):
            toolkit = LLMWikiToolkit(
                MagicMock(), MagicMock(), MagicMock(), arango_wiki_config
            )
        assert toolkit._sources._arango_store is toolkit._store
        assert toolkit._sources._arango_db is None

    @pytest.mark.asyncio
    async def test_sources_resolve_lazily_at_first_use(
        self, arango_wiki_config, mock_arango_driver
    ):
        with patch(
            "parrot.knowledge.wiki.arango_store.AsyncDB",
            return_value=mock_arango_driver,
        ):
            toolkit = LLMWikiToolkit(
                MagicMock(), MagicMock(), MagicMock(), arango_wiki_config
            )
            assert toolkit._store._initialized is False
            db = await toolkit._sources._resolve_arango_db()
            assert toolkit._store._initialized is True
            assert db is toolkit._store._db

    def test_sqlite_backend_unaffected(self, tmp_path: Path):
        config = WikiConfig(wiki_name="test-wiki", storage_dir=tmp_path)
        toolkit = LLMWikiToolkit(MagicMock(), MagicMock(), MagicMock(), config)
        assert toolkit._sources.backend == "sqlite"

    def test_memory_backend_unaffected(self, tmp_path: Path):
        config = WikiConfig(
            wiki_name="test-wiki", storage_dir=tmp_path, storage_backend="memory"
        )
        toolkit = LLMWikiToolkit(MagicMock(), MagicMock(), MagicMock(), config)
        assert toolkit._sources.backend == "json"
