"""End-to-end persistence, filter and mutation suite (FEAT-542, AC3/AC4/AC5)."""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("lancedb", reason="requires ai-parrot-embeddings[lancedb]")

sys.path.insert(0, str(Path(__file__).parent))
from lancedb_fixtures import DeterministicEmbedding, corpus  # noqa: E402

from parrot.stores.lancedb import LanceDBStore  # noqa: E402
from parrot.stores.models import Document  # noqa: E402


def _make_store(uri, **kwargs) -> LanceDBStore:
    kwargs.setdefault("dimension", 8)
    kwargs.setdefault("embedding_id", "lancedb-test-embedding-v1")
    kwargs.setdefault("collection_name", "t")
    store = LanceDBStore(uri=str(uri), **kwargs)
    store._embedding_callable_input = DeterministicEmbedding()
    return store


def _corpus_documents() -> list[Document]:
    return [
        Document(page_content=d["text"], metadata=dict(d["metadata"] | ({"id": d["id"]} if d["id"] else {})))
        for d in corpus()
    ]


async def _ingest_corpus(store: LanceDBStore, collection: str = "t") -> None:
    await store.create_collection(collection)
    await store.add_documents(_corpus_documents(), collection=collection)


class TestPersistence:
    async def test_reopen_in_a_fresh_subprocess_returns_identical_ids_and_metadata(self, tmp_path):
        uri = str(tmp_path / "col")
        store = _make_store(uri)
        await _ingest_corpus(store)
        rows_before = await store._default_table.query().limit(100).to_list()
        ids_before = sorted(r["record_id"] for r in rows_before)
        await store.disconnect()
        assert len(ids_before) == 24

        script = (
            "import asyncio, sys\n"
            f"sys.path.insert(0, {str(Path(__file__).parent)!r})\n"
            "from parrot.stores.lancedb import LanceDBStore\n"
            "async def main():\n"
            f"    store = LanceDBStore(uri={uri!r}, dimension=8, embedding_id='lancedb-test-embedding-v1', collection_name='t')\n"
            "    await store.connection()\n"
            "    table = store._default_table\n"
            "    rows = await table.query().limit(100).to_list()\n"
            "    ids = sorted(r['record_id'] for r in rows)\n"
            "    print('IDS:' + ','.join(ids))\n"
            "    print('METADATA_OK:' + str(all(r['metadata_json'] for r in rows)))\n"
            "    await store.disconnect()\n"
            "asyncio.run(main())\n"
        )
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        ids_line = next(line for line in result.stdout.splitlines() if line.startswith("IDS:"))
        ids_after = sorted(ids_line[len("IDS:") :].split(","))
        assert ids_after == ids_before
        assert "METADATA_OK:True" in result.stdout

    async def test_incompatible_reopen_leaves_original_data_readable(self, tmp_path):
        uri = str(tmp_path / "col")
        store = _make_store(uri)
        await store.create_collection("t")
        await store.add_documents([Document(page_content="hello", metadata={"id": "a"})], collection="t")
        await store.disconnect()

        conflicting = _make_store(uri, embedding_id="different-identity")
        with pytest.raises(ValueError):
            await conflicting.create_collection("t")
        await conflicting.disconnect()

        reopened = _make_store(uri)
        await reopened.create_collection("t")
        rows = await reopened._default_table.query().limit(10).to_list()
        assert [r["record_id"] for r in rows] == ["a"]
        await reopened.disconnect()

    async def test_same_local_ids_in_two_collections_stay_distinct(self, tmp_path):
        uri = str(tmp_path / "col")
        store_a = _make_store(uri, collection_name="collection_a")
        store_b = _make_store(uri, collection_name="collection_b")

        await store_a.create_collection("collection_a")
        await store_a.add_documents(
            [Document(page_content="content A", metadata={"id": "shared"})], collection="collection_a"
        )
        await store_b.create_collection("collection_b")
        await store_b.add_documents(
            [Document(page_content="content B", metadata={"id": "shared"})], collection="collection_b"
        )

        results_a = await store_a.similarity_search("content", limit=5)
        results_b = await store_b.similarity_search("content", limit=5)
        assert results_a[0].id != results_b[0].id  # namespaced ids differ across collections
        assert results_a[0].content == "content A"
        assert results_b[0].content == "content B"
        await store_a.disconnect()
        await store_b.disconnect()

    async def test_one_store_instance_touching_two_collections_keeps_ids_distinct(self, tmp_path):
        """Code review regression: a SINGLE store instance whose own default
        collection differs from a `collection=` override it is also asked to
        create/search must still resolve the CORRECT collection_uuid for
        each — not silently reuse whichever manifest was cached first."""
        uri = str(tmp_path / "col")
        # Store's own default is "t"; it also touches "other" via collection=.
        store = _make_store(uri, collection_name="t")

        await store.create_collection("t")
        await store.add_documents([Document(page_content="content T", metadata={"id": "shared"})], collection="t")

        await store.create_collection("other")
        await store.add_documents(
            [Document(page_content="content OTHER", metadata={"id": "shared"})], collection="other"
        )

        results_t = await store.similarity_search("content", limit=5, collection="t")
        results_other = await store.similarity_search("content", limit=5, collection="other")
        assert results_t[0].id != results_other[0].id  # distinct collection_uuid per collection
        assert results_t[0].content == "content T"
        assert results_other[0].content == "content OTHER"

        # The store's OWN default-collection attributes must still reflect
        # "t" (its configured collection_name), never "other".
        assert store._manifest is not None
        default_rows = await store._default_table.query().limit(10).to_list()
        assert [r["record_id"] for r in default_rows] == ["shared"]
        assert default_rows[0]["document"] == "content T"
        await store.disconnect()


class TestRetrievalMatrix:
    async def test_vector_fts_and_hybrid_on_one_corpus(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await _ingest_corpus(store)

        fts_results = await store.fulltext_search("ZXQ731", limit=5)
        assert any(r.metadata["_lancedb"]["record_id"] == "lexical-zxq731" for r in fts_results)

        vector_results = await store.similarity_search("escalation case reference", limit=10)
        assert len(vector_results) > 0

        hybrid_results = await store.hybrid_search("ZXQ731 escalation case reference", limit=10)
        hybrid_ids = {r.metadata["_lancedb"]["record_id"] for r in hybrid_results}
        assert "lexical-zxq731" in hybrid_ids or "semantic-neighbor" in hybrid_ids
        await store.disconnect()

    async def test_excluded_rows_never_consume_the_candidate_budget(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await _ingest_corpus(store)

        # Two explicit parent rows exist in the corpus (parent-a, parent-b).
        # With a small limit, excluded parents must not starve child results.
        results = await store.similarity_search("billing shipping", limit=3, include_parents=False)
        ids = {r.metadata["_lancedb"]["record_id"] for r in results}
        assert "parent-a" not in ids
        assert "parent-b" not in ids
        assert len(results) == 3
        await store.disconnect()


class TestMutationVisibility:
    async def test_upsert_and_delete_visible_in_all_modes_before_and_after_reopen(self, tmp_path):
        uri = str(tmp_path / "col")
        store = _make_store(uri)
        await store.create_collection("t")  # FTS index created with zero rows

        # Row added AFTER index creation.
        await store.add_documents([Document(page_content="alpha document", metadata={"id": "a"})], collection="t")
        assert len(await store.fulltext_search("alpha", limit=5)) == 1
        assert len(await store.similarity_search("alpha document", limit=5)) == 1
        assert len(await store.hybrid_search("alpha document", limit=5)) == 1

        # Upsert.
        await store.add_documents(
            [Document(page_content="alpha document updated", metadata={"id": "a"})], collection="t"
        )
        assert len(await store.fulltext_search("updated", limit=5)) == 1

        # Delete.
        n = await store.delete_documents(pk="id", values=["a"], collection="t")
        assert n == 1
        assert await store.fulltext_search("alpha", limit=5) == []
        await store.disconnect()

        # Fresh reopen sees the same post-delete state.
        reopened = _make_store(uri)
        await reopened.connection()
        rows = await reopened._default_table.query().limit(10).to_list()
        assert rows == []
        await reopened.disconnect()


class TestNoNetwork:
    async def test_storage_operations_with_sockets_denied(self, tmp_path):
        """Storage half of AC6 (I8) — TASK-3068 owns the whole-agent half."""
        real_socket = socket.socket

        class _NoNetSocket(real_socket):
            def connect(self, address):
                raise OSError("network denied by test")

            def connect_ex(self, address):
                raise OSError("network denied by test")

        socket.socket = _NoNetSocket
        try:
            store = _make_store(tmp_path / "col")
            await store.create_collection("t")
            await store.add_documents([Document(page_content="offline doc", metadata={"id": "a"})], collection="t")
            assert len(await store.similarity_search("offline doc", limit=5)) == 1
            assert len(await store.fulltext_search("offline", limit=5)) == 1
            assert len(await store.hybrid_search("offline doc", limit=5)) == 1
            n = await store.delete_documents(pk="id", values=["a"], collection="t")
            assert n == 1
            await store.disconnect()
        finally:
            socket.socket = real_socket
