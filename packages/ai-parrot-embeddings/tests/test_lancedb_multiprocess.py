"""Real concurrent-writer, crash and cancellation tests (FEAT-542, AC8, spec §4 I9)."""

from __future__ import annotations

import multiprocessing as mp
import os
import signal
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("lancedb", reason="requires ai-parrot-embeddings[lancedb]")

_TESTS_DIR = str(Path(__file__).parent)


def _store(uri: str, **kwargs):
    sys.path.insert(0, _TESTS_DIR)
    from lancedb_fixtures import DeterministicEmbedding
    from parrot.stores.lancedb import LanceDBStore

    kwargs.setdefault("dimension", 8)
    kwargs.setdefault("embedding_id", "lancedb-test-embedding-v1")
    kwargs.setdefault("collection_name", "t")
    store = LanceDBStore(uri=uri, **kwargs)
    store._embedding_callable_input = DeterministicEmbedding()
    return store


def _writer(uri: str, prefix: str, n: int, colliding: bool, barrier, out_q) -> None:
    import asyncio

    sys.path.insert(0, _TESTS_DIR)
    from parrot.stores.models import Document

    async def run():
        store = _store(uri)
        errors = []
        for i in range(n):
            rid = "shared" if colliding else f"{prefix}-{i}"
            try:
                await store.add_documents(
                    [Document(page_content=f"{prefix} doc {i}", metadata={"id": rid})], collection="t"
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")
        await store.disconnect()
        out_q.put((prefix, errors))

    barrier.wait()
    asyncio.run(run())


def _create_collection_worker(uri: str, barrier, out_q) -> None:
    import asyncio

    async def run():
        store = _store(uri)
        try:
            await store.create_collection("t")
            out_q.put("ok")
        except Exception as exc:  # noqa: BLE001
            out_q.put(f"error: {exc}")
        await store.disconnect()

    barrier.wait()
    asyncio.run(run())


def _reader_loop(uri: str, stop_evt, out_q) -> None:
    import asyncio

    sys.path.insert(0, _TESTS_DIR)

    async def run():
        store = _store(uri)
        errors = []
        partial_or_erroring = 0
        reads = 0
        while not stop_evt.is_set():
            try:
                await store.connection()
                table = store._default_table
                if table is not None:
                    await table.query().limit(1000).to_list()
                    reads += 1
            except Exception as exc:  # noqa: BLE001
                partial_or_erroring += 1
                errors.append(str(exc))
            time.sleep(0.01)
        await store.disconnect()
        out_q.put((reads, partial_or_erroring, errors))

    asyncio.run(run())


def _index_rebuilder(uri: str, ready_evt, out_q) -> None:
    import asyncio

    async def run():
        store = _store(uri)
        await store.create_collection("t")  # idempotent FTS re-check/creation
        ready_evt.set()
        out_q.put("done")
        await store.disconnect()

    asyncio.run(run())


def _hold_then_die(uri: str, ready_evt) -> None:
    import asyncio

    async def run():
        store = _store(uri)
        coordinator = store._coordinator
        async with coordinator.exclusive(description="hold-forever"):
            ready_evt.set()
            time.sleep(3600)

    asyncio.run(run())


class TestConcurrentWriters:
    def test_disjoint_ids_from_two_processes_all_land(self, tmp_path):
        uri = str(tmp_path / "col")
        import asyncio

        asyncio.run(_setup(uri))

        ctx = mp.get_context("spawn")
        barrier = ctx.Barrier(2)
        out_q = ctx.Queue()
        p1 = ctx.Process(target=_writer, args=(uri, "p1", 8, False, barrier, out_q))
        p2 = ctx.Process(target=_writer, args=(uri, "p2", 8, False, barrier, out_q))
        p1.start()
        p2.start()
        p1.join(timeout=60)
        p2.join(timeout=60)
        assert not p1.is_alive() and not p2.is_alive()
        results = dict(out_q.get() for _ in range(2))
        assert results["p1"] == [] and results["p2"] == []

        rows = asyncio.run(_read_all(uri))
        assert len(rows) == 16
        assert len(set(rows)) == 16

    def test_colliding_ids_converge_without_duplicates(self, tmp_path):
        uri = str(tmp_path / "col")
        import asyncio

        asyncio.run(_setup(uri))

        ctx = mp.get_context("spawn")
        barrier = ctx.Barrier(2)
        out_q = ctx.Queue()
        p1 = ctx.Process(target=_writer, args=(uri, "p1", 5, True, barrier, out_q))
        p2 = ctx.Process(target=_writer, args=(uri, "p2", 5, True, barrier, out_q))
        p1.start()
        p2.start()
        p1.join(timeout=60)
        p2.join(timeout=60)
        results = dict(out_q.get() for _ in range(2))
        assert results["p1"] == [] and results["p2"] == []

        rows = asyncio.run(_read_all(uri))
        assert rows.count("shared") == 1

    def test_simultaneous_collection_and_index_creation(self, tmp_path):
        uri = str(tmp_path / "col")
        ctx = mp.get_context("spawn")
        barrier = ctx.Barrier(2)
        out_q = ctx.Queue()
        p1 = ctx.Process(target=_create_collection_worker, args=(uri, barrier, out_q))
        p2 = ctx.Process(target=_create_collection_worker, args=(uri, barrier, out_q))
        p1.start()
        p2.start()
        p1.join(timeout=60)
        p2.join(timeout=60)
        results = [out_q.get(), out_q.get()]
        assert results == ["ok", "ok"]  # idempotent creation, neither process errors

    def test_reader_never_observes_a_partial_or_erroring_table(self, tmp_path):
        uri = str(tmp_path / "col")
        import asyncio

        asyncio.run(_setup(uri))

        ctx = mp.get_context("spawn")
        stop_evt = ctx.Event()
        out_q = ctx.Queue()
        reader = ctx.Process(target=_reader_loop, args=(uri, stop_evt, out_q))
        reader.start()

        ready_evt = ctx.Event()
        rebuild_q = ctx.Queue()
        rebuilder = ctx.Process(target=_index_rebuilder, args=(uri, ready_evt, rebuild_q))
        rebuilder.start()
        rebuilder.join(timeout=60)
        assert rebuild_q.get() == "done"

        time.sleep(0.2)  # let the reader observe a few more cycles
        stop_evt.set()
        reader.join(timeout=60)
        reads, partial_or_erroring, errors = out_q.get()
        assert reads > 0
        assert partial_or_erroring == 0, errors

    def test_conflicts_retry_within_bound_or_raise_the_documented_error(self, tmp_path):
        """Per TASK-3057's gate: the coordinator's file-lock + reopen pattern is the
        proven mechanism — no distinguishable SDK conflict exception was observed.
        This test asserts the OUTCOME (no duplicate/lost rows under real contention),
        which is what AC8 actually requires, rather than asserting a specific
        exception type the gate found the SDK does not raise for this race."""
        uri = str(tmp_path / "col")
        import asyncio

        asyncio.run(_setup(uri))

        ctx = mp.get_context("spawn")
        barrier = ctx.Barrier(3)
        out_q = ctx.Queue()
        procs = [ctx.Process(target=_writer, args=(uri, f"p{i}", 10, True, barrier, out_q)) for i in range(3)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=90)
        assert all(not p.is_alive() for p in procs)
        results = dict(out_q.get() for _ in range(3))
        for prefix, errors in results.items():
            assert errors == [], f"{prefix}: {errors}"

        rows = asyncio.run(_read_all(uri))
        assert rows.count("shared") == 1


class TestFailureModes:
    def test_writer_termination_then_successful_subsequent_mutation(self, tmp_path):
        uri = str(tmp_path / "col")
        import asyncio

        asyncio.run(_setup(uri))

        ctx = mp.get_context("spawn")
        ready_evt = ctx.Event()
        holder = ctx.Process(target=_hold_then_die, args=(uri, ready_evt))
        holder.start()
        assert ready_evt.wait(timeout=10)
        os.kill(holder.pid, signal.SIGKILL)
        holder.join(timeout=10)
        assert not holder.is_alive()

        async def subsequent_mutation():
            from parrot.stores.models import Document

            store = _store(uri)
            await store.add_documents(
                [Document(page_content="after crash", metadata={"id": "post-crash"})], collection="t"
            )
            await store.disconnect()

        asyncio.run(subsequent_mutation())  # must not deadlock
        rows = asyncio.run(_read_all(uri))
        assert "post-crash" in rows

    async def test_cancellation_does_not_imply_rollback(self, tmp_path):
        import asyncio

        uri = str(tmp_path / "col")
        store = _store(uri)
        await store.create_collection("t")

        from parrot.stores.models import Document

        entered = asyncio.Event()

        async def slow_write():
            async def _op():
                entered.set()
                await asyncio.sleep(5)

            await store._coordinator.run_mutation(_op, description="slow")

        task = asyncio.create_task(slow_write())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Cancellation must not claim the write was rolled back — it wasn't
        # even committed here (the op never wrote), but ownership must be
        # released so a subsequent mutation proceeds without deadlock.
        await store.add_documents(
            [Document(page_content="after cancel", metadata={"id": "after-cancel"})], collection="t"
        )
        rows = await store._default_table.query().limit(10).to_list()
        assert any(r["record_id"] == "after-cancel" for r in rows)
        await store.disconnect()


async def _setup(uri: str) -> None:
    store = _store(uri)
    await store.create_collection("t")
    await store.disconnect()


async def _read_all(uri: str) -> list[str]:
    store = _store(uri)
    await store.connection()
    rows = await store._default_table.query().limit(1000).to_list()
    ids = [r["record_id"] for r in rows]
    await store.disconnect()
    return ids
