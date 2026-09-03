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

import contextlib

import pytest

from parrot.tools.pythonrepl import PythonREPLTool
from parrot.tools.repl_worker.handle import WorkerHandle
from parrot.tools.repl_worker.pool import WorkerPool
from parrot.tools.repl_worker.protocol import WorkerConfig


async def _shutdown(tool: PythonREPLTool) -> None:
    if tool._worker_pool is not None:
        await tool._worker_pool.shutdown()


@pytest.fixture
async def tool(tmp_path):
    instance = PythonREPLTool(report_dir=str(tmp_path))
    yield instance
    await _shutdown(instance)


async def test_execute_error_dict_never_blank(tmp_path, monkeypatch):
    """FEAT-500 AC5: a message-less exception still yields a readable error.

    A bare `TimeoutError()` — exactly what `_send` used to raise on the
    5 s namespace budget — has `str() == ''`, which reached the LLM as
    "Error executing Python code: " with an empty `ToolResult.error`.
    """
    tool = PythonREPLTool(report_dir=str(tmp_path))
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

    async def test_session_isolation(self, tmp_path):
        """Two tool instances -> two workers; no cross-session visibility (AC7)."""
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
    async def test_e2e_runaway_loop_recovery(self, tmp_path):
        """Infinite loop -> timeout -> LLM gets a loss error with the variable
        list -> the session is still usable afterward.

        Since FEAT-500 `deadline_ms` no longer has to cover the freshly-spawned
        worker's own pandas/numpy bootstrap: readiness is a separate budget
        (`WorkerConfig.bootstrap_timeout_ms`), awaited by `_send()` BEFORE the
        deadline clock starts, so the first ("z = 5") call on a cold start can
        no longer be mistaken for the intended infinite loop. The 4 s deadline
        below therefore now only has to cover actual execution.
        """
        config = WorkerConfig(deadline_ms=4_000, max_workers=2, idle_ttl_seconds=30, prewarm_pool_size=0)
        tool = PythonREPLTool(report_dir=str(tmp_path), worker_config=config)
        try:
            ok = await tool._execute("z = 5")
            assert isinstance(ok, str)

            result = await tool._execute("while True:\n    pass")
            assert isinstance(result, dict)
            assert result["status"] == "error"
            assert "z" in result["result"]
            assert "recreate" in result["result"].lower()

            recovered = await tool._execute("w = 1\nresult = w")
            assert isinstance(recovered, str)
            assert "1" in recovered
        finally:
            await _shutdown(tool)
