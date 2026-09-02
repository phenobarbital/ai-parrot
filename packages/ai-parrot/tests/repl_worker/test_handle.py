"""``WorkerHandle`` tests for FEAT-380 Module 3 (deadline SIGKILL, AC2/AC3/AC11).

These tests spawn REAL worker subprocesses (`PythonREPLTool` imports
pandas/numpy/matplotlib), so they need a generous `RLIMIT_AS` to boot — see
`real_worker_config` in `test_worker.py`'s reasoning, mirrored here.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import sys
import time

import pytest

from parrot.tools.repl_worker.handle import (
    NamespaceTimeoutError,
    WorkerBootstrapError,
    WorkerHandle,
)
from parrot.tools.repl_worker.protocol import ReadyResponse, WorkerConfig

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="rlimits are POSIX-only")

#: Delays the WORKER's own bootstrap deterministically (FEAT-500 tests):
#: `setup_code` is mirrored into the child via `repl_kwargs` and executed by
#: the worker's own `PythonREPLTool._bootstrap()`. No test hook in production
#: code is needed to reproduce a slow cold start.
SLOW_BOOTSTRAP = {"setup_code": "import time\ntime.sleep(3)"}


@pytest.fixture
def real_worker_config():
    """Generous AS (spec default ~4 GiB) so the real worker can actually boot."""
    return WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=5, prewarm_pool_size=0)


@pytest.fixture
def fast_deadline_config():
    """Same generous AS, but a short deadline so timeout tests stay quick."""
    return WorkerConfig(deadline_ms=1_500, max_workers=2, idle_ttl_seconds=5, prewarm_pool_size=0)


@pytest.fixture
def tiny_as_config():
    """AS too small for `PythonREPLTool` to even finish importing pandas/numpy.

    Verified empirically in this environment: importing `numpy.random`'s
    compiled extensions fails to `mmap` under a 512 MiB (and even 1 GiB)
    `RLIMIT_AS` — the worker process dies with an `ImportError: ... failed
    to map segment from shared object` traceback on stderr *before* it ever
    reads a frame. This reliably reproduces "memory pressure kills the
    worker, not the test runner" (AC3) without relying on a runtime
    allocation racing against CPython's own clean `MemoryError` handling
    (which frequently does NOT crash the process — see this task's
    Completion Note for the full reasoning).
    """
    return WorkerConfig(
        rlimit_as_bytes=512 * 1024**2, deadline_ms=5_000, max_workers=2, idle_ttl_seconds=5, prewarm_pool_size=0
    )


class TestDeadline:
    async def test_deadline_sigkill(self, fast_deadline_config, tmp_path):
        """Infinite loop -> killed at deadline; handle reports not alive (AC2)."""
        handle = WorkerHandle(fast_deadline_config, output_dir=str(tmp_path))
        await handle.start()
        try:
            result = await handle.execute("while True:\n    pass")
            assert isinstance(result, dict)
            assert result["status"] == "error"
            assert "timeout" in result["result"].lower()
            assert handle.is_alive is False
        finally:
            await handle.kill()

    async def test_namespace_loss_error_shape(self, real_worker_config, tmp_path):
        """After a kill: {status, result, error} dict, cause differentiated,
        previously-created variable names listed, instruction to recreate state (AC11)."""
        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        await handle.start()
        ok = await handle.execute("y = 42")
        assert isinstance(ok, str)

        await handle.kill()
        result = await handle.execute("z = 1")

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["result"] == result["error"]
        assert "y" in result["result"]
        assert "recreate" in result["result"].lower()
        # cause differentiated: killed deliberately (not via deadline timeout)
        assert "crash" in result["result"].lower() or "cause" not in result["result"].lower()

    @posix_only
    async def test_memory_limit_kills_worker(self, tiny_as_config, tmp_path):
        """A too-small RLIMIT_AS kills the worker only; cause != timeout (AC3).

        Reported cause is "memory" (stderr shows the mmap failure) — see
        `tiny_as_config` for why this uses an import-time crash rather than
        a runtime allocation.
        """
        handle = WorkerHandle(tiny_as_config, output_dir=str(tmp_path))
        await handle.start()
        result = await handle.execute("x = 1")

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert "timeout" not in result["result"].lower()
        assert "memory" in result["result"].lower()
        assert handle.is_alive is False
        # The test runner itself is unaffected — reaching this line proves it.


class TestPing:
    async def test_ping_true_when_alive(self, real_worker_config, tmp_path):
        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        await handle.start()
        try:
            assert await handle.ping() is True
        finally:
            await handle.kill()

    async def test_ping_false_after_kill(self, real_worker_config, tmp_path):
        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        await handle.start()
        await handle.kill()
        assert await handle.ping() is False


class TestNamespaceAPI:
    async def test_execute_contract_invariant(self, real_worker_config, tmp_path):
        """G5: str-shaped success / dict-shaped error, matching the in-process REPL."""
        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        await handle.start()
        try:
            ok = await handle.execute("x = 1 + 1")
            assert isinstance(ok, str)

            err = await handle.execute("raise ValueError('boom')")
            assert isinstance(err, dict)
            assert err["status"] in ("error", "done_with_errors")
        finally:
            await handle.kill()

    async def test_get_set_var_round_trip(self, real_worker_config, tmp_path):
        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        await handle.start()
        try:
            await handle.set_var("answer", 42)
            value = await handle.get_var("answer")
            assert value == 42
            assert "answer" in handle.known_vars
        finally:
            await handle.kill()

    async def test_list_vars_and_snapshot(self, real_worker_config, tmp_path):
        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        await handle.start()
        try:
            await handle.execute("greeting = 'hi'")
            names = await handle.list_vars()
            assert "greeting" in names
            assert "pd" in names

            data = await handle.snapshot()
            assert data.get("greeting") == "hi"
        finally:
            await handle.kill()

    async def test_reset_clears_known_vars(self, real_worker_config, tmp_path):
        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        await handle.start()
        try:
            await handle.execute("temp = 1")
            assert "temp" in handle.known_vars
            await handle.reset()
            assert handle.known_vars == []
        finally:
            await handle.kill()

    async def test_inject_dataframe(self, real_worker_config, tmp_path):
        """Arrow IPC/shm transport (TASK-1945) — see test_transport.py for
        full roundtrip/fallback/shm-leak coverage; this is a handle-level
        smoke test that the API works end-to-end."""
        import pandas as pd

        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        await handle.start()
        try:
            df = pd.DataFrame({"a": [1, 2, 3]})
            await handle.inject_dataframe("df", df)
            value = await handle.get_var("df")
            pd.testing.assert_frame_equal(value, df)
        finally:
            await handle.kill()


class TestReadiness:
    """FEAT-500 G1/AC1-AC2: the readiness handshake."""

    async def test_handle_wait_ready_success(self, real_worker_config, tmp_path):
        """After `start()`, the handle resolves the worker's ReadyResponse."""
        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        await handle.start()
        try:
            ready = await handle.wait_ready()
            assert isinstance(ready, ReadyResponse)
            assert ready.pid == handle._proc.pid
            assert handle.is_ready is True
            # Idempotent: a second waiter gets the same outcome.
            assert await handle.wait_ready() is ready
        finally:
            await handle.kill()

    async def test_handle_bootstrap_timeout_kills_and_reports(self, tmp_path):
        """AC2: budget expiry kills the worker and reports pid + budget."""
        config = WorkerConfig(
            deadline_ms=5_000,
            max_workers=2,
            idle_ttl_seconds=5,
            prewarm_pool_size=0,
            bootstrap_timeout_ms=500,
        )
        handle = WorkerHandle(config, output_dir=str(tmp_path), repl_kwargs=SLOW_BOOTSTRAP)
        await handle.start()
        pid = handle._proc.pid
        try:
            with pytest.raises(WorkerBootstrapError, match="500") as excinfo:
                await handle.wait_ready()
            assert str(pid) in str(excinfo.value)
            assert "stderr tail" in str(excinfo.value)
            assert handle.is_alive is False
            assert handle.is_ready is False
        finally:
            await handle.kill()

    async def test_handle_send_waits_for_ready(self, real_worker_config, tmp_path):
        """AC1/AC6: seeding a still-booting worker no longer times out at 5 s.

        This is the exact call that used to kill the worker: `set_var()` on a
        worker whose bootstrap outlasts the old hard-coded 5 s budget.
        """
        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path), repl_kwargs=SLOW_BOOTSTRAP)
        await handle.start()
        try:
            await handle.set_var("x", 1)
            assert await handle.get_var("x") == 1
            assert handle.is_alive is True
        finally:
            await handle.kill()

    async def test_fresh_spawn_bootstrap_failure_returns_loss_dict(self, tmp_path):
        """AC2/AC11: on the execute path a bootstrap failure is a G5 dict, never a raise."""
        config = WorkerConfig(
            deadline_ms=5_000,
            max_workers=2,
            idle_ttl_seconds=5,
            prewarm_pool_size=0,
            bootstrap_timeout_ms=500,
        )
        handle = WorkerHandle(config, output_dir=str(tmp_path), repl_kwargs=SLOW_BOOTSTRAP)
        await handle.start()
        try:
            result = await handle.execute("x = 1")
            assert isinstance(result, dict)
            assert result["status"] == "error"
            assert result["error"]  # AC5: never blank
            assert "ready" in result["result"].lower()
        finally:
            await handle.kill()


class TestNonLethalTimeouts:
    """FEAT-500 G2/U2/AC3: only the execute deadline kills."""

    async def test_namespace_timeout_is_non_lethal(self, tmp_path, monkeypatch):
        """A namespace-request timeout is messaged, keeps the worker, and drains."""
        config = WorkerConfig(
            deadline_ms=5_000,
            max_workers=2,
            idle_ttl_seconds=5,
            prewarm_pool_size=0,
            namespace_timeout_ms=200,
        )
        handle = WorkerHandle(config, output_dir=str(tmp_path))
        await handle.start()
        await handle.wait_ready()
        real_roundtrip = handle._roundtrip

        def slow_roundtrip(request):
            time.sleep(1.0)
            return real_roundtrip(request)

        monkeypatch.setattr(handle, "_roundtrip", slow_roundtrip)
        try:
            with pytest.raises(NamespaceTimeoutError) as excinfo:
                await handle.list_vars()
            # AC5: the old bare TimeoutError had str() == ""
            assert str(excinfo.value)
            assert "still alive" in str(excinfo.value)
            # AC3: the worker — and its namespace — survived.
            assert handle.is_alive is True

            monkeypatch.setattr(handle, "_roundtrip", real_roundtrip)
            await asyncio.sleep(1.2)  # let the parked reply land
            names = await handle.list_vars()
            assert isinstance(names, list)
            assert "pd" in names  # the drained frame was not mis-attributed
        finally:
            await handle.kill()

    async def test_namespace_api_after_soft_timeout_keeps_state(self, tmp_path, monkeypatch):
        """AC3: state set before a non-lethal timeout is still there afterwards."""
        config = WorkerConfig(
            deadline_ms=5_000,
            max_workers=2,
            idle_ttl_seconds=5,
            prewarm_pool_size=0,
            namespace_timeout_ms=200,
        )
        handle = WorkerHandle(config, output_dir=str(tmp_path))
        await handle.start()
        await handle.wait_ready()
        try:
            await handle.execute("x = 1")
            real_roundtrip = handle._roundtrip

            def slow_roundtrip(request):
                time.sleep(1.0)
                return real_roundtrip(request)

            monkeypatch.setattr(handle, "_roundtrip", slow_roundtrip)
            with pytest.raises(NamespaceTimeoutError):
                await handle.list_vars()
            monkeypatch.setattr(handle, "_roundtrip", real_roundtrip)
            await asyncio.sleep(1.2)

            assert await handle.get_var("x") == 1
        finally:
            await handle.kill()

    async def test_execute_deadline_is_still_lethal(self, fast_deadline_config, tmp_path):
        """AC4: the execute deadline remains the one lethal budget."""
        handle = WorkerHandle(fast_deadline_config, output_dir=str(tmp_path))
        await handle.start()
        try:
            result = await handle.execute("while True:\n    pass")
            assert isinstance(result, dict)
            assert result["status"] == "error"
            assert "timeout" in result["result"].lower()
            assert handle.is_alive is False
        finally:
            await handle.kill()

    async def test_kill_leaves_no_ready_task_or_pending_reply(self, real_worker_config, tmp_path):
        """AC12: `kill()` tears down the readiness task and any parked reply."""
        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        await handle.start()
        await handle.wait_ready()
        await handle.kill()
        assert handle._ready_task is None
        assert handle._pending_reply is None
        assert handle.is_alive is False

    async def test_wait_ready_after_kill_reports_a_message(self, real_worker_config, tmp_path):
        """AC5: a handle killed before readiness never leaves `wait_ready()` hanging."""
        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        await handle.start()
        await handle.kill()
        with pytest.raises(WorkerBootstrapError) as excinfo:
            await asyncio.wait_for(handle.wait_ready(), timeout=5)
        assert str(excinfo.value)


class TestConcurrencyRegressions:
    """Code-review findings (FEAT-500): cancellation and drain edge cases."""

    async def test_cancelled_send_parks_the_reply(self, real_worker_config, tmp_path, monkeypatch):
        """A cancelled caller must not leave the pipe owned by an untracked thread.

        `_send()` shields its executor round-trip, so cancelling the awaiting
        task does NOT stop the thread that is mid-`read_frame()`. If that
        future were not parked, the next `_send()` would write while the old
        thread is still reading — two readers on one pipe, and every later
        reply shifted by a frame.
        """
        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        await handle.start()
        await handle.wait_ready()
        real_roundtrip = handle._roundtrip

        def slow_roundtrip(request):
            time.sleep(1.0)
            return real_roundtrip(request)

        monkeypatch.setattr(handle, "_roundtrip", slow_roundtrip)
        try:
            task = asyncio.create_task(handle.list_vars())
            await asyncio.sleep(0.2)  # let it write the request and block
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            # The straggler is tracked, and the worker was NOT killed.
            assert handle._pending_reply is not None
            assert handle.is_alive is True

            monkeypatch.setattr(handle, "_roundtrip", real_roundtrip)
            await asyncio.sleep(1.2)  # let the parked reply land
            names = await handle.list_vars()
            # Correct frame, not the parked one mis-attributed.
            assert isinstance(names, list)
            assert "pd" in names
            assert handle._pending_reply is None
        finally:
            await handle.kill()

    async def test_execute_after_undrained_timeout_is_not_reported_as_loss(self, tmp_path, monkeypatch):
        """A drain timeout inside `execute()` must not claim the namespace was lost.

        `NamespaceTimeoutError` subclasses `TimeoutError` (== `asyncio.
        TimeoutError` on 3.11+), so without an explicit branch `execute()`
        would report "execution exceeded deadline_ms" and "ALL variables were
        lost" for a worker that is alive with its namespace intact.
        """
        # `execute()` drains with ITS OWN budget (deadline_ms + 250 ms grace),
        # so the deadline must be SHORTER than the straggler, or execute()
        # simply waits it out and succeeds (itself correct behaviour — this
        # test needs the drain to actually expire).
        config = WorkerConfig(
            deadline_ms=1_000,
            max_workers=2,
            idle_ttl_seconds=5,
            prewarm_pool_size=0,
            namespace_timeout_ms=200,
        )
        handle = WorkerHandle(config, output_dir=str(tmp_path))
        await handle.start()
        await handle.wait_ready()
        try:
            await handle.execute("x = 1")
            real_roundtrip = handle._roundtrip

            def slow_roundtrip(request):
                time.sleep(3.0)
                return real_roundtrip(request)

            monkeypatch.setattr(handle, "_roundtrip", slow_roundtrip)
            with pytest.raises(NamespaceTimeoutError):
                await handle.list_vars()

            # Straggler still in flight -> execute()'s drain step times out.
            result = await handle.execute("y = 2")
            assert isinstance(result, dict)
            assert result["status"] == "error"
            assert result["error"]
            assert "lost" not in result["result"].lower()
            assert handle.is_alive is True

            # And the namespace really did survive.
            monkeypatch.setattr(handle, "_roundtrip", real_roundtrip)
            await asyncio.sleep(3.2)
            assert await handle.get_var("x") == 1
        finally:
            await handle.kill()

    async def test_deadline_kill_survives_a_saturated_executor(self, tmp_path):
        """AC4/AC12: the SIGKILL path must not queue behind the reads it interrupts.

        `_kill_process()` runs on a dedicated `_lifecycle_executor`. If it
        shared `self._executor` with `_roundtrip()`/`_await_ready()`, then once
        every thread there is parked on a blocking `read_frame()` the timed-out
        `execute()` could never get a thread to run the kill — while freeing a
        thread required that kill. Reproduced as a hard hang (execute() never
        returning and `kill()` hanging too) with the one-thread executor below.
        """
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="saturated")
        config = WorkerConfig(deadline_ms=1_000, max_workers=2, idle_ttl_seconds=5, prewarm_pool_size=0)
        handle = WorkerHandle(config, output_dir=str(tmp_path), executor=executor)
        await handle.start()
        await handle.wait_ready()
        try:
            # Generous ceiling: the point is that it returns AT ALL.
            result = await asyncio.wait_for(handle.execute("while True:\n    pass"), timeout=20.0)
            assert isinstance(result, dict)
            assert result["status"] == "error"
            assert "timeout" in result["result"].lower()
            assert handle.is_alive is False
        finally:
            await asyncio.wait_for(handle.kill(), timeout=10.0)
            executor.shutdown(wait=False, cancel_futures=True)

    async def test_death_summary_reports_exit_code_and_stderr(self, real_worker_config, tmp_path):
        """The public accessor the pool uses instead of reading private attrs."""
        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        exit_code, stderr_tail = handle.death_summary()
        assert exit_code is None  # never spawned
        assert stderr_tail == ""

        await handle.start()
        await handle.wait_ready()
        await handle.kill()

        exit_code, stderr_tail = handle.death_summary()
        assert exit_code is not None  # reaped by kill()
        assert isinstance(stderr_tail, str)

    async def test_concurrent_kills_are_serialized(self, real_worker_config, tmp_path):
        """`_kill_process()`'s poll() guard is not atomic — a lock serializes it.

        Several independent paths can race to tear the process down (a lethal
        deadline, the bootstrap-timeout branch, `_classify_death()`, an explicit
        `kill()`), and `Popen.kill()`/`.wait()` are not documented as safe to
        call concurrently from multiple threads.
        """
        handle = WorkerHandle(real_worker_config, output_dir=str(tmp_path))
        await handle.start()
        await handle.wait_ready()
        try:
            results = await asyncio.gather(*(handle._kill_process() for _ in range(5)), return_exceptions=True)
            assert all(not isinstance(r, BaseException) for r in results), results
            assert handle.is_alive is False
        finally:
            await handle.kill()
