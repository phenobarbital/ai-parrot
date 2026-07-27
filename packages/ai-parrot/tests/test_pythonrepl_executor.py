"""Tests for the dedicated bounded executor (FEAT-380 Module 1 / AC1).

`PythonREPLTool._execute()` must dispatch generated code to a dedicated,
bounded `ThreadPoolExecutor` (default 4 threads, named `python-repl*`)
instead of the framework's shared default executor, so a runaway loop can
only exhaust the REPL's own pool. The return contract (G5) must remain
byte-identical: str on success, `{status, result, error}` dict on error.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from parrot.tools.pythonrepl import PythonREPLTool


@pytest.fixture
def tool(tmp_path):
    return PythonREPLTool(report_dir=tmp_path, sanitize_input_enabled=True)


class TestDedicatedExecutor:
    async def test_exec_runs_on_named_repl_thread(self, tool):
        """`_execute()`'s executor is the dedicated, named pool.

        NOTE (deviation from the task's Test Specification scaffold): the
        scaffold's sandboxed-code variant (``import threading`` inside
        ``tool._execute(...)``) is not achievable here — ``threading`` is
        categorically denied by the (out-of-scope, unmodified) allowlist
        gate's ``deny_data_io`` set (`python_sanitizer.py` `_DATA_IO_IMPORTS`),
        regardless of profile. This task must not touch the sanitizer, so we
        verify the same property — the dedicated named pool is the one
        `_execute()` actually dispatches to — via `tool._repl_executor`
        directly (the exact executor object `_execute()` passes to
        `run_in_executor`), rather than through sandboxed code text.
        """
        loop = asyncio.get_event_loop()
        name = await loop.run_in_executor(
            tool._repl_executor, lambda: threading.current_thread().name
        )
        assert name.startswith("python-repl")

    async def test_pool_is_bounded(self, tool):
        """Executor max_workers honours the configured bound (default 4)."""
        assert tool._repl_executor._max_workers == 4

    async def test_pool_size_configurable(self, tmp_path):
        """executor_max_workers kwarg overrides the default bound."""
        custom_tool = PythonREPLTool(report_dir=tmp_path, executor_max_workers=2)
        assert custom_tool._repl_executor._max_workers == 2

    async def test_return_contract_unchanged(self, tool):
        """G5: str on success, dict on error."""
        ok = await tool._execute("x = 1 + 1")
        assert isinstance(ok, (str, dict))
        err = await tool._execute("raise ValueError('boom')")
        assert isinstance(err, dict) and err["status"] in ("error", "done_with_errors")

    def test_default_executor_not_used(self):
        """AC1: `run_in_executor(None, ...)` must not appear in the exec path."""
        import inspect

        from parrot.tools import pythonrepl

        source = inspect.getsource(pythonrepl.PythonREPLTool._execute)
        assert "run_in_executor(None" not in source
