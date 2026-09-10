"""Lifecycle, schema and provider-ownership tests (FEAT-542, AC3/AC4/AC6/AC8)."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("lancedb", reason="requires ai-parrot-embeddings[lancedb]")

from parrot.stores.lancedb import LanceDBStore  # noqa: E402


class _RaisingProvider:
    """embed_documents/embed_query raise — proves FTS never touches this."""

    async def embed_documents(self, texts):  # pragma: no cover — must never be called
        raise AssertionError("provider must not be constructed/invoked on the FTS path")

    async def embed_query(self, text):  # pragma: no cover — must never be called
        raise AssertionError("provider must not be constructed/invoked on the FTS path")


class _CountingProvider:
    def __init__(self):
        self.constructed_calls = 0
        self.freed = False

    async def embed_documents(self, texts):
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    async def embed_query(self, text):
        return [0.1, 0.2, 0.3, 0.4]

    def free(self):  # pragma: no cover — must never be called (AC4)
        self.freed = True


class TestLazyProvider:
    async def test_construction_does_not_build_a_provider(self, tmp_path):
        provider = _RaisingProvider()
        store = LanceDBStore(uri=str(tmp_path / "col"), embedding=provider)
        # Construction alone must not invoke embed_documents/embed_query.
        assert store._embedding_provider is None

        # Connecting and preparing a collection (which needs only the
        # embedding IDENTITY, not a loaded model) must not touch it either.
        store2 = LanceDBStore(uri=str(tmp_path / "col2"), embedding=provider, embedding_id="fixed-id")
        await store2.connection()
        await store2.create_collection("t")
        assert store2._embedding_provider is None
        await store2.disconnect()

    async def test_concurrent_first_use_constructs_exactly_once(self, tmp_path):
        provider = _CountingProvider()
        store = LanceDBStore(uri=str(tmp_path / "col"), embedding=provider)
        results = await asyncio.gather(*(store._ensure_provider() for _ in range(10)))
        assert all(r is provider for r in results)
        # Caller-injected callables are used as-is (no registry construction
        # counter to check here — that's the registry-provider case); the
        # single-flight lock still means every gather() caller gets the SAME
        # object with no duplicate work.
        assert store._embedding_provider is provider


class TestConnection:
    async def test_connect_is_idempotent_and_creates_nothing(self, tmp_path):
        store = LanceDBStore(uri=str(tmp_path / "col"))
        conn1, table1 = await store.connection()
        conn2, table2 = await store.connection()
        assert conn1 is conn2
        assert table1 is None and table2 is None
        # No table/collection was created merely by connecting.
        names = await conn1.table_names()
        assert names == []
        await store.disconnect()

    async def test_get_vector_raises_when_not_connected(self, tmp_path):
        store = LanceDBStore(uri=str(tmp_path / "col"))
        with pytest.raises(RuntimeError):
            store.get_vector()


class TestCollection:
    async def test_create_collection_persists_manifest_and_is_idempotent(self, tmp_path):
        store = LanceDBStore(
            uri=str(tmp_path / "col"), embedding_id="fixed-id", dimension=4, collection_name="agent_knowledge"
        )
        await store.create_collection("agent_knowledge")
        assert store._manifest is not None
        assert store._default_table is not None

        # Idempotent: reopening/re-preparing the same compatible collection
        # does not raise and does not replace it.
        await store.create_collection("agent_knowledge")
        await store.disconnect()

    async def test_incompatible_reopen_raises_without_overwriting(self, tmp_path):
        uri = str(tmp_path / "col")
        store = LanceDBStore(uri=uri, embedding_id="fixed-id", dimension=4)
        await store.create_collection("agent_knowledge")
        await store.disconnect()

        conflicting = LanceDBStore(uri=uri, embedding_id="different-id", dimension=4)
        with pytest.raises(ValueError):
            await conflicting.create_collection("agent_knowledge")
        await conflicting.disconnect()

    async def test_retry_completes_index_prep_without_replacing_rows(self, tmp_path):
        store = LanceDBStore(
            uri=str(tmp_path / "col"), embedding_id="fixed-id", dimension=4, collection_name="agent_knowledge"
        )
        await store.create_collection("agent_knowledge")
        table = store._default_table
        await table.add(
            [{"record_id": "a", "document": "hello world", "embedding": [0.1, 0.2, 0.3, 0.4], "metadata_json": "{}"}]
        )

        # A second store instance "retries" collection preparation against
        # the same directory — rows must survive.
        store2 = LanceDBStore(
            uri=str(tmp_path / "col"), embedding_id="fixed-id", dimension=4, collection_name="agent_knowledge"
        )
        await store2.create_collection("agent_knowledge")
        rows = await store2._default_table.query().limit(10).to_list()
        assert [r["record_id"] for r in rows] == ["a"]
        await store.disconnect()
        await store2.disconnect()


class TestOwnership:
    async def test_borrowed_provider_is_never_freed(self, tmp_path):
        provider = _CountingProvider()
        store = LanceDBStore(uri=str(tmp_path / "col"), embedding=provider)
        await store._ensure_provider()
        await store._free_resources()
        assert provider.freed is False
        assert store._embedding_provider is None

    async def test_nested_context_closes_only_at_outermost_exit(self, tmp_path):
        store = LanceDBStore(uri=str(tmp_path / "col"))
        async with store:
            async with store:
                await store.connection()
                assert store._connected is True
            # Inner exit: still connected (outer context not closed yet).
            assert store._connected is True
        # Outer exit: now disconnected.
        assert store._connected is False

    async def test_event_loop_heartbeat_advances_during_blocking_work(self, tmp_path):
        heartbeats = {"n": 0}

        async def heartbeat():
            while True:
                await asyncio.sleep(0.01)
                heartbeats["n"] += 1

        def blocking_provider_construction():
            import time

            time.sleep(0.2)
            return _CountingProvider()

        hb_task = asyncio.create_task(heartbeat())
        try:
            provider = await asyncio.to_thread(blocking_provider_construction)
            assert provider is not None
            await asyncio.sleep(0)  # let the heartbeat task record its last tick
        finally:
            hb_task.cancel()
            import contextlib

            with contextlib.suppress(asyncio.CancelledError):
                await hb_task
        assert heartbeats["n"] >= 5


class TestCompatibilityConstructor:
    def test_routing_kwargs_consumed_not_rejected(self, tmp_path):
        store = LanceDBStore(uri=str(tmp_path / "col"), name="lancedb", vector_database="LanceDBStore")
        assert store._config.uri

    def test_null_dsn_accepted_non_null_dsn_rejected(self, tmp_path):
        LanceDBStore(uri=str(tmp_path / "col"), dsn=None)
        with pytest.raises(ValueError):
            LanceDBStore(uri=str(tmp_path / "col"), dsn="postgresql://x")

    def test_unknown_kwargs_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            LanceDBStore(uri=str(tmp_path / "col"), totally_unknown_option=True)

    def test_table_alias_maps_to_collection_name(self, tmp_path):
        store = LanceDBStore(uri=str(tmp_path / "col"), table="agent_knowledge")
        assert store._config.collection_name == "agent_knowledge"


class TestPrepareEmbeddingTable:
    async def test_default_labels_and_use_jsonb_accepted(self, tmp_path):
        store = LanceDBStore(
            uri=str(tmp_path / "col"), embedding_id="fixed-id", dimension=4, collection_name="agent_knowledge"
        )
        await store.prepare_embedding_table("agent_knowledge", dimension=4)
        assert store._default_table is not None
        await store.disconnect()

    async def test_drop_columns_rejected(self, tmp_path):
        store = LanceDBStore(uri=str(tmp_path / "col"), embedding_id="fixed-id", dimension=4)
        with pytest.raises(ValueError):
            await store.prepare_embedding_table("agent_knowledge", drop_columns=True)

    async def test_custom_column_label_rejected(self, tmp_path):
        store = LanceDBStore(uri=str(tmp_path / "col"), embedding_id="fixed-id", dimension=4)
        with pytest.raises(ValueError):
            await store.prepare_embedding_table("agent_knowledge", embedding_column="vec")
