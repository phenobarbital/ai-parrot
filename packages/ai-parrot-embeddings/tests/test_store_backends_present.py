"""Smoke tests for TASK-1335: vector-store backends moved to satellite."""
import importlib
from pathlib import Path

import pytest

STORE_BACKENDS = ["postgres", "milvus", "arango", "bigquery", "faiss_store"]


@pytest.mark.parametrize("backend", STORE_BACKENDS)
def test_backend_resolves_to_satellite(backend):
    """Moved backend modules resolve inside the satellite distribution."""
    importlib.invalidate_caches()
    mod = importlib.import_module(f"parrot.stores.{backend}")
    assert "ai-parrot-embeddings" in mod.__file__, (
        f"Expected {backend} to resolve inside ai-parrot-embeddings, "
        f"but got: {mod.__file__}"
    )


def test_pgvector_shim_reexports_pgvectorstore():
    """The 3-line pgvector.py shim still aliases postgres.PgVectorStore."""
    from parrot.stores import pgvector, postgres
    assert pgvector.PgVectorStore is postgres.PgVectorStore


def test_supported_stores_unchanged():
    """Dispatch table in core remains exactly as before (mismatches preserved)."""
    from parrot.stores import supported_stores
    assert supported_stores == {
        'postgres': 'PgVectorStore',
        'milvus': 'MilvusStore',
        'kb': 'KnowledgeBaseStore',
        'faiss_store': 'FaissStore',
        'arango': 'ArangoStore',
        'bigquery': 'BigQueryStore',
    }


def test_kb_parents_utils_stay_in_core():
    """U2: higher-level sub-packages remain in the host."""
    for subpkg in ("kb", "parents", "utils"):
        mod = importlib.import_module(f"parrot.stores.{subpkg}")
        assert "ai-parrot/src/parrot/stores" in mod.__file__, (
            f"{subpkg} should stay in core, got {mod.__file__}"
        )


def test_satellite_did_not_create_stores_init():
    """Satellite did not accidentally create __init__.py at the stores level."""
    init = (
        Path(__file__).parent.parent
        / "src" / "parrot" / "stores" / "__init__.py"
    )
    assert not init.exists(), f"forbidden file: {init}"
