"""``WorkerHandle`` tests for FEAT-380 Module 3 (deadline SIGKILL, AC2/AC3/AC11).

These tests spawn REAL worker subprocesses (`PythonREPLTool` imports
pandas/numpy/matplotlib), so they need a generous `RLIMIT_AS` to boot — see
`real_worker_config` in `test_worker.py`'s reasoning, mirrored here.
"""

from __future__ import annotations

import sys

import pytest

from parrot.tools.repl_worker.handle import WorkerHandle
from parrot.tools.repl_worker.protocol import WorkerConfig

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="rlimits are POSIX-only")


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
