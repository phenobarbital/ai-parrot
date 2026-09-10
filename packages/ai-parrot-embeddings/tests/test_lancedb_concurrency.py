"""Real process coordination, failure and cancellation tests (FEAT-542, AC8)."""
from __future__ import annotations

import asyncio
import contextlib
import multiprocessing as mp
import os
import signal
import time

import pytest

from parrot.stores.lancedb_concurrency import (
    CommitConflict,
    CoordinationConfig,
    MutationCoordinator,
)

class TestKeying:
    def test_two_spellings_of_one_directory_share_a_key(self, tmp_path):
        target = tmp_path / "col"
        target.mkdir()
        absolute = MutationCoordinator.for_directory(target, "agent_knowledge")
        relative = MutationCoordinator.for_directory(
            os.path.relpath(target, os.getcwd()), "agent_knowledge"
        )
        assert absolute.dataset_key == relative.dataset_key

    def test_distinct_collections_retain_isolation(self, tmp_path):
        target = tmp_path / "col"
        a = MutationCoordinator.for_directory(target, "collection_a")
        b = MutationCoordinator.for_directory(target, "collection_b")
        assert a.dataset_key != b.dataset_key
        assert a._lock_file_path() != b._lock_file_path()

    def test_same_dataset_key_shares_local_lock_instance(self, tmp_path):
        target = tmp_path / "col"
        a = MutationCoordinator.for_directory(target, "agent_knowledge")
        b = MutationCoordinator.for_directory(target, "agent_knowledge")
        assert a._local_lock is b._local_lock


class TestRetry:
    async def test_conflict_retried_within_bound_then_succeeds(self):
        coordinator = MutationCoordinator.for_directory(
            "/tmp/does-not-need-to-exist-for-retry-test", "c",
            config=CoordinationConfig(max_attempts=5, base_backoff_seconds=0.001, max_backoff_seconds=0.01),
        )
        calls = {"n": 0}

        def flaky_operation():
            calls["n"] += 1
            if calls["n"] < 3:
                raise CommitConflict("simulated conflict")
            return "ok"

        result = await coordinator.run_mutation(flaky_operation, description="test")
        assert result == "ok"
        assert calls["n"] == 3

    async def test_conflict_raised_after_exhausting_bound(self):
        coordinator = MutationCoordinator.for_directory(
            "/tmp/does-not-need-to-exist-for-retry-test-2", "c",
            config=CoordinationConfig(max_attempts=3, base_backoff_seconds=0.001, max_backoff_seconds=0.01),
        )

        def always_conflicts():
            raise CommitConflict("always fails")

        with pytest.raises(CommitConflict):
            await coordinator.run_mutation(always_conflicts, description="test")

    async def test_backoff_does_not_block_the_event_loop(self):
        coordinator = MutationCoordinator.for_directory(
            "/tmp/does-not-need-to-exist-for-retry-test-3", "c",
            config=CoordinationConfig(max_attempts=4, base_backoff_seconds=0.05, max_backoff_seconds=0.05),
        )
        calls = {"n": 0}

        def flaky_operation():
            calls["n"] += 1
            if calls["n"] < 4:
                raise CommitConflict("simulated conflict")
            return "ok"

        heartbeats = {"n": 0}

        async def heartbeat():
            while True:
                await asyncio.sleep(0.01)
                heartbeats["n"] += 1

        hb_task = asyncio.create_task(heartbeat())
        try:
            await coordinator.run_mutation(flaky_operation, description="test")
        finally:
            hb_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await hb_task
        assert heartbeats["n"] >= 3


def _hold_exclusive_lock(uri: str, collection: str, hold_seconds: float, start_evt, out_q) -> None:
    async def run():
        coordinator = MutationCoordinator.for_directory(uri, collection)
        async with coordinator.exclusive(description="hold"):
            out_q.put(("acquired", time.monotonic()))
            start_evt.set()
            time.sleep(hold_seconds)
        out_q.put(("released", time.monotonic()))

    asyncio.run(run())


def _acquire_and_record(uri: str, collection: str, out_q) -> None:
    async def run():
        coordinator = MutationCoordinator.for_directory(uri, collection)
        async with coordinator.exclusive(description="acquire"):
            out_q.put(("acquired", time.monotonic()))

    asyncio.run(run())


def _hold_forever_then_die(uri: str, collection: str, ready_evt) -> None:
    async def run():
        coordinator = MutationCoordinator.for_directory(uri, collection)
        async with coordinator.exclusive(description="hold-forever"):
            ready_evt.set()
            time.sleep(3600)  # simulate a hung process; test kills us instead

    asyncio.run(run())


class TestCrossProcess:
    def test_two_real_processes_serialize_the_exclusive_section(self, tmp_path):
        ctx = mp.get_context("spawn")
        start_evt = ctx.Event()
        out_q = ctx.Queue()

        holder = ctx.Process(
            target=_hold_exclusive_lock, args=(str(tmp_path), "c", 0.3, start_evt, out_q)
        )
        holder.start()
        assert start_evt.wait(timeout=10)

        waiter = ctx.Process(target=_acquire_and_record, args=(str(tmp_path), "c", out_q))
        waiter.start()

        holder.join(timeout=10)
        waiter.join(timeout=10)
        assert not holder.is_alive() and not waiter.is_alive()

        events = [out_q.get(timeout=5) for _ in range(3)]
        by_label = {}
        for label, ts in events:
            by_label.setdefault(label, []).append(ts)

        # The waiter's acquisition must happen strictly after the holder released.
        assert by_label["acquired"][-1] >= by_label["released"][0]

    def test_process_death_releases_ownership(self, tmp_path):
        ctx = mp.get_context("spawn")
        ready_evt = ctx.Event()

        holder = ctx.Process(target=_hold_forever_then_die, args=(str(tmp_path), "c", ready_evt))
        holder.start()
        assert ready_evt.wait(timeout=10)

        # Kill the holder without giving it a chance to release cleanly —
        # the OS must release the flock anyway.
        os.kill(holder.pid, signal.SIGKILL)
        holder.join(timeout=10)
        assert not holder.is_alive()

        async def acquire_next():
            coordinator = MutationCoordinator.for_directory(
                tmp_path, "c", config=CoordinationConfig(acquire_timeout_seconds=5.0)
            )
            async with coordinator.exclusive(description="successor"):
                return True

        assert asyncio.run(acquire_next()) is True


class TestCancellation:
    async def test_cancellation_releases_ownership_without_claiming_rollback(self, tmp_path):
        coordinator = MutationCoordinator.for_directory(tmp_path, "c")
        entered = asyncio.Event()

        async def hold_until_cancelled():
            async with coordinator.exclusive(description="cancel-me"):
                entered.set()
                await asyncio.sleep(10)

        task = asyncio.create_task(hold_until_cancelled())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # A fresh acquisition must succeed promptly — ownership was released.
        second = MutationCoordinator.for_directory(
            tmp_path, "c", config=CoordinationConfig(acquire_timeout_seconds=5.0)
        )
        async with second.exclusive(description="after-cancel"):
            pass
