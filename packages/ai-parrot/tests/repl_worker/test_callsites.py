"""Grep-guard + regression tests for FEAT-380 Module 6 (TASK-1944).

The namespace now lives in each ``PythonREPLTool``/``PythonPandasTool``
instance's worker process (TASK-1943) — ``.locals``/``.globals`` on the host
instance are no longer the source of truth. This asserts no host module
outside ``pythonrepl.py``/``repl_worker/`` reads them directly (AC13), with
ONE explicit, documented exception (see ``_KNOWN_EXCEPTIONS`` below).
"""

from __future__ import annotations

import logging
import pathlib
import re

import pandas as pd

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "parrot"

_PATTERN = re.compile(r"\b(pandas_tool|python_repl|tool)\.(locals|globals)\b")

#: (relative path, substring of the line) pairs that are KNOWN, DOCUMENTED
#: exceptions to the "no direct .locals/.globals" rule — see TASK-1944's
#: Completion Note for the full reasoning on each.
_KNOWN_EXCEPTIONS = {
    # `execute_code()`'s `pandas_tool` branch reads `.locals` right after
    # `execute_sync()` — a separate, pre-existing SYNCHRONOUS escape hatch
    # (TASK-1943) that still runs `_execute_code()` in-process. The worker
    # is never started on this path, so `snapshot()`/`get_var()` (which
    # always read the WORKER's namespace) would silently return an
    # unrelated, empty namespace instead of this method's own just-executed
    # result. Porting this branch correctly would require ALSO routing
    # `execute_sync()` through the worker, which TASK-1943 explicitly keeps
    # out of scope.
    ("outputs/formats/base.py", "return tool.locals, None"),
}


def test_callsites_use_namespace_api():
    """Grep guard (AC13): no direct REPL .locals/.globals from host modules."""
    offenders = []
    for py in SRC.rglob("*.py"):
        if "repl_worker" in py.parts or py.name == "pythonrepl.py":
            continue
        relative = py.relative_to(SRC).as_posix()
        for i, line in enumerate(py.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # comments/docstring prose aren't code access
            if not _PATTERN.search(line):
                continue
            if any(relative == path and needle in line for path, needle in _KNOWN_EXCEPTIONS):
                continue
            offenders.append(f"{relative}:{i}: {stripped}")
    assert not offenders, "\n".join(offenders)


class TestPythonPandasToolWorkerSeeding:
    """`PythonPandasTool`'s `df_locals` -> worker-seeding port (TASK-1944)."""

    async def test_dataframes_seeded_into_worker(self, tmp_path):
        from parrot.tools.pythonpandas import PythonPandasTool

        df = pd.DataFrame({"a": [1, 2, 3]})
        tool = PythonPandasTool(dataframes={"my_df": df}, report_dir=str(tmp_path))
        try:
            names = await tool.list_vars()
            assert "my_df" in names
            assert "df1" in names  # sequential alias

            value = await tool.get_var("my_df")
            pd.testing.assert_frame_equal(value, df)
        finally:
            if tool._worker_pool is not None:
                await tool._worker_pool.shutdown()

    async def test_reset_environment_reseeds_dataframes(self, tmp_path):
        from parrot.tools.pythonpandas import PythonPandasTool

        df = pd.DataFrame({"a": [1, 2, 3]})
        tool = PythonPandasTool(dataframes={"my_df": df}, report_dir=str(tmp_path))
        try:
            await tool.list_vars()  # trigger first seed
            tool.reset_environment()

            value = await tool.get_var("my_df")
            pd.testing.assert_frame_equal(value, df)
        finally:
            if tool._worker_pool is not None:
                await tool._worker_pool.shutdown()

    async def test_session_clone_gets_isolated_worker(self, tmp_path):
        from parrot.tools.pythonpandas import PythonPandasTool

        df = pd.DataFrame({"a": [1, 2, 3]})
        source = PythonPandasTool(dataframes={"my_df": df}, report_dir=str(tmp_path))
        clone = source.create_session_clone()
        try:
            assert clone._session_id != source._session_id
            value = await clone.get_var("my_df")
            pd.testing.assert_frame_equal(value, df)
        finally:
            if source._worker_pool is not None:
                await source._worker_pool.shutdown()
            if clone._worker_pool is not None:
                await clone._worker_pool.shutdown()


class _FakePandasAgentHost:
    """Minimal stand-in exposing just what the ported `PandasAgent` methods
    need off `self` (`_get_python_pandas_tool()`, `.logger`). Binding the
    REAL, unbound `PandasAgent` methods to this fake host exercises the
    actual ported production code against a real `PythonPandasTool` +
    worker, without constructing a full `PandasAgent`/`BasicAgent` (LLM
    client, tool_manager wiring, …) — out of proportion for this task.
    """

    def __init__(self, pandas_tool):
        self._pandas_tool = pandas_tool
        self.logger = logging.getLogger("test_callsites")
        self._current_response_data_columns = None

    def _get_python_pandas_tool(self):
        return self._pandas_tool


class TestE2EPandasAgent:
    """PandasAgent's ported methods (data.py) operate end-to-end over the
    namespace API against a real PythonPandasTool + worker (AC13)."""

    async def test_get_repl_locals_snapshot(self, tmp_path):
        from parrot.bots.data import PandasAgent
        from parrot.tools.pythonpandas import PythonPandasTool

        df = pd.DataFrame({"a": [1, 2, 3]})
        tool = PythonPandasTool(dataframes={"my_df": df}, report_dir=str(tmp_path))
        host = _FakePandasAgentHost(tool)
        try:
            repl_locals = await PandasAgent._get_repl_locals(host)
            assert "my_df" in repl_locals
            pd.testing.assert_frame_equal(repl_locals["my_df"], df)
        finally:
            if tool._worker_pool is not None:
                await tool._worker_pool.shutdown()

    async def test_inject_data_from_variable(self, tmp_path):
        from parrot.bots.data import PandasAgent
        from parrot.models.basic import CompletionUsage
        from parrot.models.responses import AIMessage
        from parrot.tools.pythonpandas import PythonPandasTool

        df = pd.DataFrame({"a": [1, 2, 3]})
        tool = PythonPandasTool(dataframes={"my_df": df}, report_dir=str(tmp_path))
        host = _FakePandasAgentHost(tool)
        response = AIMessage(
            input="q", output="a", model="test-model", provider="test", usage=CompletionUsage()
        )
        try:
            await PandasAgent._inject_data_from_variable(host, response, "my_df")
            assert isinstance(response.data, pd.DataFrame)
            assert list(response.data["a"]) == [1, 2, 3]
        finally:
            if tool._worker_pool is not None:
                await tool._worker_pool.shutdown()
