"""FEAT-750 (ledger issue:e19ac9b4ba42): `_infer_data_variable_from_tools`
must skip a candidate whose `get_var()` raises instead of failing the turn.
"""
import pickle
import types

import pandas as pd
import pytest

try:
    from parrot.bots.data import PandasAgent
except Exception:  # pragma: no cover - env-dependent
    PandasAgent = None


pytestmark = pytest.mark.skipif(PandasAgent is None, reason="parrot.bots.data not importable in this environment")


class _FakeTool:
    """Stands in for the worker-backed PythonPandasTool namespace API."""

    def __init__(self, values: dict):
        self._values = values

    async def get_var(self, name: str):
        value = self._values[name]
        if isinstance(value, Exception):
            raise value
        return value


def _agent(tool: _FakeTool, candidates: set) -> types.SimpleNamespace:
    ns = types.SimpleNamespace()
    ns.logger = __import__("logging").getLogger("test_infer_tolerant")
    ns._get_python_pandas_tool = lambda: tool
    ns._current_turn_variable_names = lambda tool_calls: set(candidates)
    ns._current_response_data_columns = None
    ns._infer = types.MethodType(PandasAgent._infer_data_variable_from_tools, ns)
    return ns


async def test_infer_skips_candidate_whose_get_var_raises(caplog):
    tool = _FakeTool(
        {
            "broken": pickle.UnpicklingError("repl_worker: refusing to unpickle pyarrow.lib._restore_array"),
            "result": pd.DataFrame({"a": [1, 2]}),
        }
    )
    agent = _agent(tool, {"broken", "result"})
    with caplog.at_level("WARNING", logger="test_infer_tolerant"):
        assert await agent._infer([object()]) == "result"
    assert "broken" in caplog.text


async def test_infer_returns_none_when_only_candidate_fails():
    tool = _FakeTool({"broken": RuntimeError("worker died")})
    agent = _agent(tool, {"broken"})
    assert await agent._infer([object()]) is None
