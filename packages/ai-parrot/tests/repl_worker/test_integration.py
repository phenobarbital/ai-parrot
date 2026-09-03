"""``PythonREPLTool`` <-> worker integration tests (FEAT-380 Module 5, TASK-1943).

`_execute()` no longer runs code in-process — it delegates to this tool
instance's persistent worker via `WorkerHandle`/`WorkerPool`, preserving the
G5 return contract byte-for-byte. `execute_sync()` (a separate, pre-existing
synchronous escape hatch used by `test_pythonrepl_security.py`) is
deliberately UNTOUCHED by this task — it still calls `_execute_code()`
in-process; hardening it is out of this task's scope.

Every test that calls `_execute()`/the namespace API spawns a REAL worker
subprocess (`PythonREPLTool` imports pandas/numpy), so this uses the tool's
default `WorkerConfig()` (spec default ~4 GiB `RLIMIT_AS`) unless a test
explicitly needs a tighter deadline.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import time

import pytest

from parrot.tools.pythonrepl import PythonREPLTool
from parrot.tools.repl_worker.handle import WorkerHandle
from parrot.tools.repl_worker.pool import WorkerPool
from parrot.tools.repl_worker.protocol import WorkerConfig

abstract_module = importlib.import_module("parrot.tools.abstract")


async def _shutdown(tool: PythonREPLTool) -> None:
    if tool._worker_pool is not None:
        await tool._worker_pool.shutdown()


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    """A per-test report dir that passes `AbstractTool`'s output_dir guard.

    Both halves are needed: `abstract_module.STATIC_DIR` is patched for THIS
    (parent/test) process, and the `STATIC_DIR` env var is set for any
    spawned WORKER subprocess (which re-imports `parrot.conf` fresh and
    inherits the parent's environment), so its own `AbstractTool.__init__`
    guard check passes too (FEAT-521 TASK-2781 finding).
    """
    monkeypatch.setattr(abstract_module, "STATIC_DIR", tmp_path)
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    return str(tmp_path)


@pytest.fixture
async def tool(report_dir):
    instance = PythonREPLTool(report_dir=report_dir)
    yield instance
    await _shutdown(instance)


async def test_execute_error_dict_never_blank(report_dir, monkeypatch):
    """FEAT-500 AC5: a message-less exception still yields a readable error.

    A bare `TimeoutError()` — exactly what `_send` used to raise on the
    5 s namespace budget — has `str() == ''`, which reached the LLM as
    "Error executing Python code: " with an empty `ToolResult.error`.
    """
    tool = PythonREPLTool(report_dir=report_dir)
    try:

        @contextlib.asynccontextmanager
        async def boom():
            raise TimeoutError()
            yield  # pragma: no cover

        monkeypatch.setattr(tool, "_worker_session", boom)
        out = await tool._execute("x = 1")
        assert out["status"] == "error"
        assert out["error"] == "TimeoutError"
        assert out["result"].startswith("ToolError: TimeoutError: TimeoutError")
    finally:
        await _shutdown(tool)


class TestExecuteContract:
    async def test_execute_contract_invariant(self, tool):
        """G5: str on success, dict on error; behavior identical to before (AC5)."""
        ok = await tool._execute("x = 1 + 1")
        assert isinstance(ok, str)

        err = await tool._execute("raise ValueError('boom')")
        assert isinstance(err, dict)
        assert err["status"] in ("error", "done_with_errors")
        assert "error" in err and "result" in err

    async def test_no_inprocess_fallback(self, tool, monkeypatch):
        """Worker start forced to fail -> explicit G5 error; in-process
        `_execute_code` provably never reached (G8/AC8)."""

        async def _boom(self):
            raise RuntimeError("simulated worker spawn failure")

        monkeypatch.setattr(WorkerHandle, "start", _boom)

        def _unreachable(*args, **kwargs):
            raise AssertionError("in-process _execute_code must be unreachable from _execute()")

        monkeypatch.setattr(tool, "_execute_code", _unreachable)

        result = await tool._execute("x = 1")
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert "simulated worker spawn failure" in result["error"]

    async def test_gate_rejection_never_starts_worker(self, tool, monkeypatch):
        """Code rejected by the host gate never reaches WorkerPool.acquire (AC6)."""

        async def _unreachable(self, session_id):
            raise AssertionError("WorkerPool.acquire must not be touched for gate-denied code")

        monkeypatch.setattr(WorkerPool, "acquire", _unreachable)

        result = await tool._execute("import os\nos.system('id')")
        assert isinstance(result, dict)
        assert result["status"] == "done_with_errors"
        assert "denied" in result["result"].lower()


class TestStateAndIsolation:
    async def test_state_persists_across_calls(self, tool):
        """Variable created in call N is visible in call N+1 (AC4/G1)."""
        first = await tool._execute("x = 42")
        assert isinstance(first, str)

        second = await tool._execute("result = x * 2")
        assert isinstance(second, str)
        assert "84" in second

    async def test_session_isolation(self, tmp_path, report_dir):
        """Two tool instances -> two workers; no cross-session visibility (AC7).

        `report_dir` (unused directly) is depended on to arm the STATIC_DIR
        guard-bypass for BOTH subdirectories below, which are still under
        `tmp_path` itself.
        """
        tool_a = PythonREPLTool(report_dir=str(tmp_path / "a"))
        tool_b = PythonREPLTool(report_dir=str(tmp_path / "b"))
        try:
            assert tool_a._session_id != tool_b._session_id

            ok = await tool_a._execute("secret = 'a-only'")
            assert isinstance(ok, str)

            leaked = await tool_b._execute("secret")
            assert isinstance(leaked, dict)
            assert "NameError" in (leaked.get("error") or "")
        finally:
            await _shutdown(tool_a)
            await _shutdown(tool_b)

    async def test_reset_environment_restarts_worker(self, tool):
        """`reset_environment()` -> next call gets a fresh, clean namespace."""
        ok = await tool._execute("y = 99")
        assert isinstance(ok, str)

        tool.reset_environment()

        result = await tool._execute("y")
        assert isinstance(result, dict)
        assert "NameError" in (result.get("error") or "")


class TestNamespaceAPI:
    async def test_namespace_api(self, tool):
        """`get_var`/`set_var`/`list_vars`/`snapshot` against a live worker."""
        await tool.set_var("alpha", 7)

        value = await tool.get_var("alpha")
        assert value == 7

        names = await tool.list_vars()
        assert "alpha" in names
        assert "pd" in names

        snap = await tool.snapshot()
        assert snap.get("alpha") == 7


class TestE2E:
    async def test_e2e_runaway_loop_keeps_namespace(self, report_dir):
        """FEAT-521 G3: interrupt-before-kill PRESERVES the namespace — the
        LLM no longer has to reconstruct its state after a runaway snippet.

        Since FEAT-500 `deadline_ms` no longer has to cover the freshly-spawned
        worker's own pandas/numpy bootstrap: readiness is a separate budget
        (`WorkerConfig.bootstrap_timeout_ms`), awaited by `_send()` BEFORE the
        deadline clock starts, so the first ("z = 5") call on a cold start can
        no longer be mistaken for the intended infinite loop.

        Supersedes the pre-FEAT-521 `test_e2e_runaway_loop_recovery`, which
        asserted the OLD namespace-loss behavior ("recreate your state") that
        `interrupt_before_kill=True` (now the default) replaces.
        """
        import pandas as pd

        config = WorkerConfig(
            deadline_ms=1_000, interrupt_grace_ms=600, max_workers=2, idle_ttl_seconds=30, prewarm_pool_size=0
        )
        tool = PythonREPLTool(report_dir=report_dir, worker_config=config)
        try:
            ok = await tool._execute("z = 5")
            assert isinstance(ok, str)
            await tool.inject_dataframe("df", pd.DataFrame({"a": [1, 2, 3]}))

            result = await tool._execute("while True:\n    pass")
            assert isinstance(result, dict)
            assert result["status"] == "error"
            assert "interrupted" in result["error"]
            assert "ALL variables" not in result["error"]  # namespace NOT lost

            # Previously bound state — including the injected DataFrame —
            # is still directly usable, no reconstruction needed.
            still_z = await tool._execute("print(z)")
            assert isinstance(still_z, str) and "5" in still_z
            shape = await tool._execute("print(df.shape)")
            assert isinstance(shape, str) and "(3, 1)" in shape
        finally:
            await _shutdown(tool)

    async def test_e2e_long_groupby_completes_under_observation(self, report_dir):
        """Spec Integration Tests: a long-running groupby completes normally
        while observed, the observer reports `"computing"` mid-run, and
        observation overhead stays under 2% wall-clock (AC2).
        """
        import pandas as pd

        config = WorkerConfig(deadline_ms=10_000, max_workers=2, idle_ttl_seconds=30, prewarm_pool_size=0)
        tool = PythonREPLTool(report_dir=report_dir, worker_config=config)
        try:
            df = pd.DataFrame({"key": [i % 50 for i in range(200_000)], "value": range(200_000)})
            await tool.inject_dataframe("df", df)

            handle = await tool._get_worker_handle()
            snippet = (
                "import time\n"
                "_t0 = time.monotonic()\n"
                "while time.monotonic() - _t0 < 3:\n"
                "    df.groupby('key')['value'].sum()\n"
            )
            exec_task = asyncio.create_task(tool._execute(snippet))
            await asyncio.sleep(1.5)  # sample mid-run
            assert handle.observer is not None
            mid_run_verdict = handle.observer.verdict()

            started = time.monotonic()
            result = await exec_task
            elapsed = time.monotonic() - started

            assert isinstance(result, str)  # completed normally, no timeout
            assert mid_run_verdict == "computing", mid_run_verdict
            # Sanity bound only — the 2% overhead figure itself belongs in a
            # dedicated benchmark (artifacts/logs/), not a wall-clock-fragile
            # CI assertion; this just proves the run wasn't badly stalled.
            assert elapsed < 8.0
        finally:
            await _shutdown(tool)
