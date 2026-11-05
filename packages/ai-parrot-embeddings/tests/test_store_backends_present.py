"""Smoke tests for TASK-1335: vector-store backends moved to satellite."""

import importlib
from pathlib import Path

import pytest

STORE_BACKENDS = ["postgres", "milvus", "arango", "bigquery", "faiss_store", "lancedb"]


@pytest.mark.parametrize("backend", STORE_BACKENDS)
def test_backend_resolves_to_satellite(backend):
    """Moved backend modules resolve inside the satellite distribution."""
    importlib.invalidate_caches()
    mod = importlib.import_module(f"parrot.stores.{backend}")
    assert "ai-parrot-embeddings" in mod.__file__, (
        f"Expected {backend} to resolve inside ai-parrot-embeddings, " f"but got: {mod.__file__}"
    )


def test_pgvector_shim_reexports_pgvectorstore():
    """The 3-line pgvector.py shim still aliases postgres.PgVectorStore."""
    from parrot.stores import pgvector, postgres

    assert pgvector.PgVectorStore is postgres.PgVectorStore


def test_supported_stores_unchanged():
    """Dispatch table in core remains exactly as before (mismatches preserved)."""
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


def test_kb_parents_utils_stay_in_core():
    """U2: higher-level sub-packages remain in the host."""
    for subpkg in ("kb", "parents", "utils"):
        mod = importlib.import_module(f"parrot.stores.{subpkg}")
        assert "ai-parrot/src/parrot/stores" in mod.__file__, f"{subpkg} should stay in core, got {mod.__file__}"


def test_satellite_did_not_create_stores_init():
    """Satellite did not accidentally create __init__.py at the stores level."""
    init = Path(__file__).parent.parent / "src" / "parrot" / "stores" / "__init__.py"
    assert not init.exists(), f"forbidden file: {init}"


def test_every_supported_store_name_resolves_to_a_class():
    """Each ``supported_stores`` value is defined (class or alias) in its dispatch module.

    The handler does ``getattr(import_module(f"parrot.stores.{slug}"), supported_stores[slug])``; the map itself is
    frozen (see ``test_supported_stores_unchanged``), so a name that is not defined in its module is a runtime error.
    The check is static (AST) so it needs none of the optional backend dependencies.
    """
    import ast

    import parrot.stores as stores_pkg
    from parrot.stores import supported_stores

    roots = [Path(p) for p in stores_pkg.__path__]
    # ``kb`` resolves lazily from its package ``__getattr__``; its class lives in kb/store.py.
    sources = {"kb": ["kb/store.py"]}
    missing = []
    for slug, cls_name in supported_stores.items():
        candidates = [r / rel for r in roots for rel in sources.get(slug, [f"{slug}.py", f"{slug}/__init__.py"])]
        defined: set[str] = set()
        for path in candidates:
            if path.exists():
                tree = ast.parse(path.read_text(encoding="utf-8"))
                defined |= {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
                defined |= {
                    t.id for n in ast.walk(tree) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)
                }
                defined |= {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        if cls_name not in defined:
            missing.append((slug, cls_name))
    assert not missing, f"supported_stores names not defined in their module: {missing}"
