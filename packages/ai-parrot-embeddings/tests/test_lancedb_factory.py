"""Factory, tool and origin integration plus absence errors (FEAT-542, AC2)."""
from __future__ import annotations

import importlib  # verified: packages/ai-parrot-embeddings/tests/test_store_backends_present.py:2
import subprocess
import sys

import pytest
from pydantic import ValidationError

pytest.importorskip("lancedb", reason="requires ai-parrot-embeddings[lancedb]")


class TestDispatch:
    def test_supported_stores_resolves_lancedb_to_the_satellite(self):
        importlib.invalidate_caches()
        mod = importlib.import_module("parrot.stores.lancedb")
        assert "ai-parrot-embeddings" in mod.__file__
        from parrot.stores import supported_stores

        assert supported_stores["lancedb"] == "LanceDBStore"
        assert hasattr(mod, "LanceDBStore")

    def test_no_other_mapping_changed(self):
        from parrot.stores import supported_stores

        assert supported_stores == {
            "postgres": "PgVectorStore",
            "milvus": "MilvusStore",
            "kb": "KnowledgeBaseStore",
            "faiss_store": "FaissStore",
            "arango": "ArangoStore",
            "bigquery": "BigQueryStore",
            "lancedb": "LanceDBStore",
        }


class TestFactoryConfig:
    def test_get_database_store_routes_name_and_embedding_fields(self, tmp_path):
        """Exercise the exact VectorInterface._get_database_store forwarding path."""
        from parrot.stores import supported_stores

        store_dict = {
            "name": "lancedb",
            "uri": str(tmp_path / "col"),
            "dimension": 8,
            "embedding_id": "fixed-id",
        }
        name = store_dict.get("name")
        store_cls_name = supported_stores.get(name)
        module = importlib.import_module(f"parrot.stores.{name}", package=name)
        store_cls = getattr(module, store_cls_name)
        store_dict.setdefault("embedding_model", None)
        store_dict.setdefault("embedding", None)
        store = store_cls(**store_dict)
        assert store._config.uri

    def test_storeconfig_requires_explicit_flat_index_type(self, tmp_path):
        """StoreConfig.index_type defaults to 'IVF_FLAT' (models/stores.py:162);
        a factory user must override it for LanceDB, which supports FLAT only."""
        from parrot.stores.lancedb import LanceDBStore

        with pytest.raises(ValidationError, match="FLAT"):
            LanceDBStore(uri=str(tmp_path / "col"), index_type="IVF_FLAT")

        # Explicit FLAT (the documented override) works.
        store = LanceDBStore(uri=str(tmp_path / "col"), index_type="FLAT")
        assert store._config.index_type == "FLAT"

    async def test_default_tool_column_aliases_accepted(self, tmp_path):
        """The tool always sends table/schema/content_column/embedding_column/
        metadata_column/id_column (vectorstoresearch.py:211) with their defaults —
        LanceDBStore must accept the full default set, not just an empty kwargs dict."""
        from parrot.stores.lancedb import LanceDBStore

        store = LanceDBStore(uri=str(tmp_path / "col"), embedding_id="fixed-id", dimension=4)
        results = await store.similarity_search(
            "",  # blank query is the cheapest path that still exercises kwarg validation
            table=None,
            schema="public",
            content_column="document",
            embedding_column="embedding",
            metadata_column="cmetadata",
            id_column="id",
        )
        assert results == []

    def test_non_null_dsn_rejected_in_favour_of_uri(self, tmp_path):
        from parrot.stores.lancedb import LanceDBStore

        LanceDBStore(uri=str(tmp_path / "col"), dsn=None)  # accepted
        with pytest.raises(ValueError):
            LanceDBStore(uri=str(tmp_path / "col"), dsn="postgresql://example")


class TestOriginIntegration:
    async def test_vector_store_origin_and_lancedb_origin_against_concrete_store(self, tmp_path):
        """Both the existing VectorStoreOrigin (duck-typed) and the new
        LanceDBOrigin work against a real, concrete LanceDBStore."""
        import sys as _sys
        from pathlib import Path as _Path

        _sys.path.insert(0, str(_Path(__file__).parent))
        from lancedb_fixtures import DeterministicEmbedding

        from parrot.stores.lancedb import LanceDBStore
        from parrot.stores.models import Document
        from parrot_tools.multistoresearch.origins import LanceDBOrigin, VectorStoreOrigin

        store = LanceDBStore(uri=str(tmp_path / "col"), embedding_id="fixed-id", dimension=8)
        store._embedding_callable_input = DeterministicEmbedding()
        await store.from_documents([Document(page_content="cats are great", metadata={"id": "a"})])

        vector_origin = VectorStoreOrigin(store, name="lancedb-vector")
        vector_hits = await vector_origin.search("cats", k=5)
        assert len(vector_hits) == 1
        assert vector_origin.supports_fts is True  # duck-typed: fulltext_search is callable
        fts_hits = await vector_origin.fts_search("cats", k=5)
        assert len(fts_hits) == 1

        lancedb_origin = LanceDBOrigin(store, mode="hybrid")
        hybrid_hits = await lancedb_origin.search("cats", k=5)
        assert len(hybrid_hits) == 1
        await store.disconnect()


class TestMissingExtra:
    def test_selecting_lancedb_without_the_sdk_names_the_install_extra(self, tmp_path):
        script = (
            "import sys\n"
            "sys.modules['lancedb'] = None\n"  # blocks any subsequent `import lancedb`
            "import asyncio\n"
            "from parrot.stores.lancedb import LanceDBStore\n"
            f"store = LanceDBStore(uri={str(tmp_path / 'col')!r}, dimension=4)\n"
            "try:\n"
            "    asyncio.run(store.connection())\n"
            "    print('NO ERROR RAISED')\n"
            "except ImportError as e:\n"
            "    print('CAUGHT:' + str(e))\n"
        )
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
        assert "CAUGHT:" in result.stdout, result.stdout + result.stderr
        assert "ai-parrot-embeddings[lancedb]" in result.stdout

    def test_unrelated_core_and_origin_imports_work_without_lancedb(self):
        """Absence of the SDK must not break unrelated origins/stores imports."""
        script = (
            "import sys\n"
            "sys.modules['lancedb'] = None\n"
            "import parrot.stores\n"
            "from parrot_tools.multistoresearch.origins import VectorStoreOrigin, LanceDBOrigin\n"
            "from parrot.stores.lancedb import LanceDBStore\n"  # importable, just can't connect()
            "print('OK')\n"
        )
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout
