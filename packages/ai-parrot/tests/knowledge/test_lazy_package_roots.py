"""Lazy package roots (FEAT-540 M1)."""

import parrot.knowledge.graphindex as gi
import parrot.knowledge.ontology as ont
import parrot.stores as stores

from ._support.import_probe import run_import_probe


def test_roots_resolve_every_export() -> None:
    """Every declared ontology and GraphIndex public export remains available."""
    for module in (gi, ont):
        for name in module.__all__:
            assert getattr(module, name) is not None, (module.__name__, name)
    assert stores.AbstractStore is not None


def test_supported_stores_unchanged() -> None:
    """The eager store dispatch map remains compatible with the previous root."""
    assert stores.supported_stores == {
        "postgres": "PgVectorStore",
        "milvus": "MilvusStore",
        "kb": "KnowledgeBaseStore",
        "faiss_store": "FaissStore",
        "arango": "ArangoStore",
        "bigquery": "BigQueryStore",
        "lancedb": "LanceDBStore",
    }


def test_schema_import_skips_mixin_and_navconfig() -> None:
    """The schema path avoids ontology mixins and the stores abstract base."""
    result = run_import_probe("parrot.knowledge.ontology.schema")

    assert result.error is None
    assert not result.has("parrot.knowledge.ontology.mixin")
    assert not result.has("parrot.stores.abstract")


def test_graphindex_root_defers_expensive_exports() -> None:
    """The GraphIndex root leaves optional export modules unloaded."""
    result = run_import_probe("parrot.knowledge.graphindex")

    assert result.error is None
    for module in (
        "parrot.knowledge.graphindex.communities",
        "parrot.knowledge.graphindex.export_html",
        "parrot.knowledge.graphindex.persist_sqlite",
        "parrot.knowledge.graphindex.projection",
        "parrot.knowledge.graphindex.signals",
        "parrot.knowledge.graphindex.sqlite_reader",
        "parrot.knowledge.graphindex.extractors.odoo_code",
    ):
        assert not result.has(module)


def test_documents_defers_aiohttp() -> None:
    """The documents module imports aiohttp only while fetching remote content."""
    result = run_import_probe("parrot.knowledge.wiki.documents")

    assert result.error is None
    assert not result.has("aiohttp")
