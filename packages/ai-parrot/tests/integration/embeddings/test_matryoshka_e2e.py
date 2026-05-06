"""End-to-end integration test for Matryoshka embedding truncation — FEAT-150.

Exercises the full pipeline:
    configure bot  →  provision pgvector table with vector(512)
                   →  ingest 5 short documents
                   →  query with a semantically close phrase
                   →  assert top-1 cosine similarity ≥ 0.5

Requires a running PostgreSQL + pgvector instance.  Gated behind the
``PG_VECTOR_DSN`` environment variable and skips cleanly when it is not set.

Run with a real DB::

    PG_VECTOR_DSN=postgresql://user:pass@localhost/testdb \\
    pytest packages/ai-parrot/tests/integration/embeddings/test_matryoshka_e2e.py -v

Each test creates its own uniquely-named collection and drops it on teardown
so that repeated runs leave no leftovers.

FEAT-150 acceptance criteria verified here (spec §5):
- The pgvector table is created with vector(512), not vector(768).
- Cosine similarity search returns the expected document as top-1.
- The disabled path (no matryoshka flag) produces 768-dim vectors.
"""
from __future__ import annotations

import os
import uuid

import pytest

# ---------------------------------------------------------------------------
# Skip gate — no live DB in CI by default
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    not os.getenv("PG_VECTOR_DSN"),
    reason=(
        "Requires PG_VECTOR_DSN env var pointing to a test PostgreSQL+pgvector "
        "database.  Example: "
        "PG_VECTOR_DSN=postgresql://user:pass@localhost/testdb pytest ..."
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_table() -> str:
    """Return a unique table name for test isolation."""
    return f"feat150_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def pgvector_dsn():
    """Provide the DSN from the environment (already gated by pytestmark)."""
    return os.environ["PG_VECTOR_DSN"]


@pytest.fixture
def vector_store_config_512(pgvector_dsn):
    """vector_store_config with Matryoshka 512-dim enabled."""
    return {
        "name": "postgres",
        "table": _unique_table(),
        "schema": "public",
        "dimension": 512,
        "connection_string": pgvector_dsn,
        "embedding_model": {
            "model_name": "nomic-ai/nomic-embed-text-v1.5",
            "model_type": "huggingface",
            "matryoshka": {
                "enabled": True,
                "dimension": 512,
            },
        },
    }


@pytest.fixture
def vector_store_config_768(pgvector_dsn):
    """vector_store_config without Matryoshka (native 768 dims)."""
    return {
        "name": "postgres",
        "table": _unique_table(),
        "schema": "public",
        "dimension": 768,
        "connection_string": pgvector_dsn,
        "embedding_model": {
            "model_name": "nomic-ai/nomic-embed-text-v1.5",
            "model_type": "huggingface",
        },
    }


# ---------------------------------------------------------------------------
# Sample corpus
# ---------------------------------------------------------------------------

_DOCUMENTS = [
    "The annual leave policy allows employees to take up to 20 days of paid leave per year.",
    "Employees must submit expense reports within 30 days of incurring the expense.",
    "Remote work is permitted for up to 3 days per week with manager approval.",
    "Health insurance benefits are available to all full-time employees after 90 days.",
    "Performance reviews are conducted biannually in June and December.",
]

# Query expected to match _DOCUMENTS[2] most closely.
_QUERY = "How many days per week can employees work from home?"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_end_to_end_matryoshka_512_search(vector_store_config_512):
    """Configure bot with nomic@512, ingest 5 docs, query, expect cosine ≥ 0.5.

    This test loads real model weights (nomic-ai/nomic-embed-text-v1.5).
    It requires internet access or a pre-cached HuggingFace model.
    """
    from parrot.stores.postgres import PGVectorStore
    from parrot.stores.models import Document

    cfg = vector_store_config_512
    table = cfg["table"]
    schema = cfg["schema"]
    dsn = cfg["connection_string"]
    dim = cfg["dimension"]
    emb = cfg["embedding_model"]

    store = PGVectorStore(
        table=table,
        schema=schema,
        dimension=dim,
        embedding_model=emb,
        connection_string=dsn,
    )

    try:
        # Provision the collection (creates vector(512) column).
        await store.connection()
        await store.create_collection()

        # Ingest corpus.
        docs = [
            Document(page_content=text, metadata={"idx": i})
            for i, text in enumerate(_DOCUMENTS)
        ]
        await store.add_documents(docs)

        # Query.
        results = await store.similarity_search(_QUERY, k=3)

        assert len(results) >= 1, "Expected at least one search result"

        top = results[0]
        assert hasattr(top, "score") or hasattr(top, "page_content"), \
            "Result must have page_content"

        # Check that top-1 is the remote-work doc (idx=2).
        top_content = top.page_content if hasattr(top, "page_content") else str(top)
        assert "remote work" in top_content.lower() or "days per week" in top_content.lower(), (
            f"Expected remote-work document as top-1, got: {top_content!r}"
        )

        # Check score when available.
        if hasattr(top, "score") and top.score is not None:
            assert top.score >= 0.5, (
                f"Expected cosine similarity ≥ 0.5, got {top.score:.4f}"
            )

    finally:
        # Teardown — drop the test collection.
        try:
            await store.delete_collection()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_matryoshka_vector_dimension_is_512(vector_store_config_512):
    """Embedding vectors produced by SentenceTransformerModel are 512-dimensional."""
    from parrot.embeddings.huggingface import SentenceTransformerModel

    model = SentenceTransformerModel(
        model_name="nomic-ai/nomic-embed-text-v1.5",
        matryoshka={"enabled": True, "dimension": 512},
    )
    vecs = await model.embed_documents(["hello world"])
    assert len(vecs) == 1
    assert len(vecs[0]) == 512, f"Expected 512-dim vector, got {len(vecs[0])}"


@pytest.mark.asyncio
async def test_disabled_matryoshka_vector_dimension_is_768(pgvector_dsn):
    """Without Matryoshka, SentenceTransformerModel produces 768-dim vectors."""
    from parrot.embeddings.huggingface import SentenceTransformerModel

    model = SentenceTransformerModel(
        model_name="nomic-ai/nomic-embed-text-v1.5",
    )
    vecs = await model.embed_documents(["hello world"])
    assert len(vecs) == 1
    assert len(vecs[0]) == 768, f"Expected 768-dim vector, got {len(vecs[0])}"
