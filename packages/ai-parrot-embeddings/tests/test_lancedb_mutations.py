"""CRUD, contextual text and multi-process mutation tests (FEAT-542, AC4/AC8)."""
from __future__ import annotations

import math
import multiprocessing as mp
import sys
from pathlib import Path

import pytest

pytest.importorskip("lancedb", reason="requires ai-parrot-embeddings[lancedb]")

sys.path.insert(0, str(Path(__file__).parent))
from lancedb_fixtures import DeterministicEmbedding  # noqa: E402

from parrot.stores.lancedb import LanceDBStore  # noqa: E402
from parrot.stores.models import Document  # noqa: E402


def _make_store(uri, **kwargs) -> LanceDBStore:
    kwargs.setdefault("dimension", 8)
    kwargs.setdefault("embedding_id", "fixed-id")
    # Match every test's explicit `collection="t"` calls so self._default_table
    # (which only tracks the store's OWN configured default collection —
    # correct per get_vector()'s "default table" contract) stays in sync with
    # what these tests inspect directly.
    kwargs.setdefault("collection_name", "t")
    store = LanceDBStore(uri=str(uri), **kwargs)
    store._embedding_callable_input = DeterministicEmbedding()
    return store


class TestIdentity:
    async def test_explicit_ids_beat_metadata_id_beats_content_hash(self, tmp_path):
        store = _make_store(tmp_path / "col")

        # Explicit id alone is used as-is.
        docs_explicit = [Document(page_content="a", metadata={})]
        assert store._resolve_ids(docs_explicit, ["explicit-id"]) == ["explicit-id"]

        # Explicit id AGREEING with metadata['id'] is not a conflict.
        docs_agree = [Document(page_content="a", metadata={"id": "same-id"})]
        assert store._resolve_ids(docs_agree, ["same-id"]) == ["same-id"]

        # metadata['id'] alone (no explicit id) is used.
        docs2 = [Document(page_content="a", metadata={"id": "meta-id"})]
        ids2 = store._resolve_ids(docs2, None)
        assert ids2 == ["meta-id"]

        # Neither explicit nor metadata id: deterministic content-hash fallback.
        docs3 = [Document(page_content="a", metadata={})]
        ids3 = store._resolve_ids(docs3, None)
        assert ids3[0]  # content-hash fallback, deterministic
        docs3b = [Document(page_content="a", metadata={})]
        assert store._resolve_ids(docs3b, None) == ids3

    async def test_conflicting_or_duplicate_ids_raise_before_any_write(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await store.create_collection("t")

        conflicting = [Document(page_content="a", metadata={"id": "meta-id"})]
        with pytest.raises(ValueError):
            await store.add_documents(conflicting, collection="t", ids=["explicit-id"])

        duplicate = [
            Document(page_content="a", metadata={"id": "dup"}),
            Document(page_content="b", metadata={"id": "dup"}),
        ]
        with pytest.raises(ValueError):
            await store.add_documents(duplicate, collection="t")

        rows = await store._default_table.query().limit(10).to_list()
        assert rows == []
        await store.disconnect()

    async def test_fallback_id_uses_original_text_not_augmented(self, tmp_path):
        store = _make_store(tmp_path / "col", contextual_embedding=True)
        await store.create_collection("t")
        docs = [Document(page_content="hello world", metadata={"source": "a"})]
        await store.add_documents(docs, collection="t")
        rows = await store._default_table.query().limit(10).to_list()
        assert len(rows) == 1
        first_id = rows[0]["record_id"]

        # Reingest the SAME original document — the fallback ID must match
        # (computed from original text, not the contextual-augmented text),
        # so this is an upsert, not a duplicate row.
        await store.add_documents(
            [Document(page_content="hello world", metadata={"source": "a"})], collection="t"
        )
        rows2 = await store._default_table.query().limit(10).to_list()
        assert len(rows2) == 1
        assert rows2[0]["record_id"] == first_id
        await store.disconnect()


class TestIngestion:
    async def test_caller_documents_are_not_mutated(self, tmp_path):
        store = _make_store(tmp_path / "col", contextual_embedding=True)
        await store.create_collection("t")
        original_metadata = {"source": "a"}
        doc = Document(page_content="hello world", metadata=dict(original_metadata))
        await store.add_documents([doc], collection="t")
        assert doc.metadata == original_metadata  # unchanged — copies were augmented, not this
        assert "contextual_header" not in doc.metadata
        await store.disconnect()

    @pytest.mark.parametrize(
        "bad_vector",
        [
            [0.1, 0.2, 0.3],  # wrong dimension (3 instead of 8)
            [math.nan] * 8,  # non-finite
            [math.inf] * 8,  # non-finite
            [0.0] * 8,  # zero-norm
        ],
    )
    async def test_invalid_vectors_rejected(self, tmp_path, bad_vector):
        store = _make_store(tmp_path / "col")
        with pytest.raises(ValueError):
            store._validate_vector(bad_vector)

    async def test_partial_batch_failure_reports_count_and_retry_is_idempotent(self, tmp_path):
        store = _make_store(tmp_path / "col")
        store._config = store._config.model_copy(update={"batch_size": 1})
        await store.create_collection("t")

        docs = [
            Document(page_content="doc one", metadata={"id": "id-1"}),
            Document(page_content="doc two", metadata={"id": "id-2"}),
        ]

        call_count = {"n": 0}
        real_embed = store._embedding_callable_input.embed_documents

        async def flaky_embed(texts):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("simulated embedding failure on batch 2")
            return await real_embed(texts)

        store._embedding_callable_input.embed_documents = flaky_embed

        with pytest.raises(RuntimeError, match=r"failed after 1 of 2 batches committed"):
            await store.add_documents(docs, collection="t")

        rows = await store._default_table.query().limit(10).to_list()
        assert len(rows) == 1  # only the first (successful) batch is durable

        # Retry with the SAME stable IDs converges without duplication.
        store._embedding_callable_input.embed_documents = real_embed
        await store.add_documents(docs, collection="t")
        rows2 = await store._default_table.query().limit(10).to_list()
        assert {r["record_id"] for r in rows2} == {"id-1", "id-2"}
        await store.disconnect()

    async def test_missing_collection_raises_lookuperror(self, tmp_path):
        store = _make_store(tmp_path / "col")
        with pytest.raises(LookupError):
            await store.add_documents([Document(page_content="x", metadata={})], collection="never-created")

    async def test_empty_document_input_is_a_noop(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await store.create_collection("t")
        await store.add_documents([], collection="t")  # must not raise
        rows = await store._default_table.query().limit(10).to_list()
        assert rows == []
        await store.disconnect()


class TestDeletion:
    async def test_counts_are_exact_including_zero(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await store.create_collection("t")
        await store.add_documents(
            [Document(page_content="a", metadata={"id": "id-1", "source": "x"})], collection="t"
        )
        n = await store.delete_documents_by_filter({"source": "x"}, collection="t")
        assert n == 1
        n_zero = await store.delete_documents_by_filter({"source": "x"}, collection="t")
        assert n_zero == 0
        await store.disconnect()

    async def test_empty_or_conflicting_selectors_raise(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await store.create_collection("t")
        with pytest.raises(ValueError):
            await store.delete_documents(collection="t")  # no documents, no values
        with pytest.raises(ValueError):
            await store.delete_documents_by_filter({}, collection="t")
        with pytest.raises(ValueError):
            await store.delete_documents(table="a", collection="b")
        rows = await store._default_table.query().limit(10).to_list()
        assert rows == []
        await store.disconnect()

    async def test_deletion_reaches_parents_hidden_from_search(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await store.create_collection("t")
        await store.add_documents(
            [
                Document(
                    page_content="parent doc",
                    metadata={"id": "parent-1", "source": "x", "document_type": "parent", "is_full_document": True},
                )
            ],
            collection="t",
        )
        # delete_documents_by_filter does NOT apply the search-only parent
        # exclusion, so a parent row IS reachable by its own metadata filter.
        n = await store.delete_documents_by_filter({"source": "x"}, collection="t")
        assert n == 1
        await store.disconnect()

    async def test_delete_by_raw_id_pk(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await store.create_collection("t")
        await store.add_documents([Document(page_content="a", metadata={"id": "id-1"})], collection="t")
        n = await store.delete_documents(pk="id", values=["id-1"], collection="t")
        assert n == 1
        await store.disconnect()


def _upsert_worker(uri: str, prefix: str, ids: list[str], barrier) -> None:
    import asyncio
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).parent))
    from lancedb_fixtures import DeterministicEmbedding as _DeterministicEmbedding

    from parrot.stores.lancedb import LanceDBStore as _LanceDBStore
    from parrot.stores.models import Document as _Document

    async def run():
        store = _LanceDBStore(uri=uri, dimension=8, embedding_id="fixed-id", collection_name="t")
        store._embedding_callable_input = _DeterministicEmbedding()
        docs = [_Document(page_content=f"{prefix}-{i}", metadata={"id": rid}) for i, rid in enumerate(ids)]
        await store.add_documents(docs, collection="t")
        await store.disconnect()

    barrier.wait()
    asyncio.run(run())


class TestConcurrentMutations:
    def test_two_processes_upserting_the_same_ids_converge(self, tmp_path):
        uri = str(tmp_path / "col")

        async def setup():
            store = _make_store(uri)
            await store.create_collection("t")
            await store.disconnect()

        import asyncio

        asyncio.run(setup())

        shared_ids = ["shared-1", "shared-2", "shared-3"]
        ctx = mp.get_context("spawn")
        barrier = ctx.Barrier(2)
        p1 = ctx.Process(target=_upsert_worker, args=(uri, "p1", shared_ids, barrier))
        p2 = ctx.Process(target=_upsert_worker, args=(uri, "p2", shared_ids, barrier))
        p1.start()
        p2.start()
        p1.join(timeout=30)
        p2.join(timeout=30)
        assert not p1.is_alive() and not p2.is_alive()

        async def check():
            store = _make_store(uri)
            await store.connection()
            rows = await store._default_table.query().limit(100).to_list()
            record_ids = [r["record_id"] for r in rows]
            assert sorted(record_ids) == sorted(shared_ids)  # no duplicates, none lost
            await store.disconnect()

        asyncio.run(check())
