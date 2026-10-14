"""Structural conformance of concrete providers/backends (FEAT-540 M2/M7)."""
import subprocess
import sys

import pytest

from parrot.knowledge.graphindex.protocols import (
    CapabilityUnavailable,
    Embedder,
    GraphPersistence,
    HybridRetrievalPersistence,
    IncrementalPersistence,
    LLMCaller,
    PageIndexer,
    ProviderNotAvailable,
    TemporalGraphPersistence,
    edge_key,
)


def _has_all(cls: type, names: list[str]) -> bool:
    return all(hasattr(cls, n) for n in names)


def test_hashing_embedder_is_embedder() -> None:
    from parrot.knowledge.graphindex.factory import HashingGraphEmbedder

    assert isinstance(HashingGraphEmbedder(), Embedder)


def test_double_missing_search_is_not_embedder() -> None:
    class _D:
        async def embed_nodes(self, nodes, batch_size=64):
            return nodes

        def get_embedding(self, node_id):
            return None

    assert not isinstance(_D(), Embedder)


def test_provider_not_available_message() -> None:
    err = ProviderNotAvailable("llm", "ai-parrot", "clients")
    assert "llm" in str(err) and "ai-parrot[clients]" in str(err)
    assert "pip install ai-parrot)" in str(ProviderNotAvailable("llm", "ai-parrot"))


def test_capability_unavailable_message() -> None:
    err = CapabilityUnavailable("sqlite", "temporal")
    assert "sqlite" in str(err) and "temporal" in str(err)


def test_edge_key_matches_sqlite_helper() -> None:
    from parrot.knowledge.graphindex.persist_sqlite import _edge_key

    assert edge_key("a", "b", "calls") == _edge_key("a", "b", "calls") == "a|b|calls"


def test_llm_adapter_is_llm_caller() -> None:
    from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter

    assert _has_all(PageIndexLLMAdapter, ["ask", "ask_structured", "ask_json"])


def test_toolkit_is_page_indexer() -> None:
    pytest.importorskip("parrot.knowledge.pageindex.toolkit")
    from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

    assert _has_all(
        PageIndexToolkit,
        ["list_trees", "create_tree", "delete_tree", "get_tree", "insert_markdown", "insert_ebook"],
    )


def test_llm_double_missing_method_is_not_caller() -> None:
    class _D:
        async def ask(self, prompt):
            return None

    assert not isinstance(_D(), LLMCaller)
    assert not isinstance(_D(), PageIndexer)


def test_sqlite_persistence_satisfies_base_minus_close() -> None:
    from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence

    names = [n for n in dir(GraphPersistence) if not n.startswith("_") and n != "close"]
    assert "apply_update" in names
    assert _has_all(SQLitePersistence, names)
    assert hasattr(SQLitePersistence, "is_stale")
    assert not hasattr(SQLitePersistence, "as_of")


def test_postgres_temporal_and_hybrid() -> None:
    pytest.importorskip("asyncpg")
    from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence

    assert _has_all(PostgresPersistence, ["as_of", "history", "diff"])
    assert _has_all(PostgresPersistence, ["hybrid_retrieve", "upsert_embeddings", "is_stale"])


def test_runtime_protocols_are_exported() -> None:
    for proto in (IncrementalPersistence, TemporalGraphPersistence, HybridRetrievalPersistence):
        assert getattr(proto, "_is_runtime_protocol", False)


def test_import_loads_no_framework_modules() -> None:
    code = (
        "import sys\n"
        "import importlib.util as u\n"
        "spec = u.spec_from_file_location('p', sys.argv[1])\n"
        "m = u.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "bad = [k for k in sys.modules if k.startswith(('parrot.tools','parrot.clients','parrot.embeddings'))]\n"
        "assert not bad, bad\n"
    )
    import parrot.knowledge.graphindex.protocols as mod

    res = subprocess.run([sys.executable, "-c", code, mod.__file__], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
