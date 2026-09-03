"""``execution_mode="inprocess"`` escape hatch (``repl_worker/inprocess.py``).

The in-process handle must present ``WorkerHandle``'s surface over the host
tool's own namespace, never touch ``WorkerPool``, keep the allowlist/AST gate,
and be selectable per instance (constructor) or per deployment
(``PYTHON_REPL_EXECUTION_MODE``) — while the default stays ``worker``.
"""

from __future__ import annotations

import asyncio
import importlib
import time

import pandas as pd
import pytest

from parrot.tools.pythonpandas import PythonPandasTool
from parrot.tools.pythonrepl import PythonREPLTool, resolve_execution_mode
from parrot.tools.repl_worker.inprocess import InProcessHandle
from parrot.tools.repl_worker.protocol import WorkerConfig

# `from parrot.tools import pythonrepl` goes through the package's meta_path
# redirector and does not hand back the module object — import it directly.
pythonrepl_module = importlib.import_module("parrot.tools.pythonrepl")
abstract_module = importlib.import_module("parrot.tools.abstract")


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    """A per-test report dir that passes ``AbstractTool``'s output_dir guard."""
    monkeypatch.setattr(abstract_module, "STATIC_DIR", tmp_path)
    return str(tmp_path)


@pytest.fixture
def inprocess_tool(report_dir):
    return PythonREPLTool(report_dir=report_dir, execution_mode="inprocess")


def test_default_mode_is_worker(report_dir, monkeypatch):
    monkeypatch.delenv("PYTHON_REPL_EXECUTION_MODE", raising=False)
    monkeypatch.setattr(pythonrepl_module.config, "get", lambda key, fallback=None: fallback)
    tool = PythonREPLTool(report_dir=report_dir)
    assert tool.execution_mode == "worker"
    assert tool._inprocess_handle is None


def test_env_var_selects_inprocess(report_dir, monkeypatch):
    monkeypatch.setattr(
        pythonrepl_module.config,
        "get",
        lambda key, fallback=None: "InProcess" if key == "PYTHON_REPL_EXECUTION_MODE" else fallback,
    )
    tool = PythonREPLTool(report_dir=report_dir)
    assert tool.execution_mode == "inprocess"


def test_explicit_argument_beats_env(report_dir, monkeypatch):
    monkeypatch.setattr(pythonrepl_module.config, "get", lambda key, fallback=None: "inprocess")
    tool = PythonREPLTool(report_dir=report_dir, execution_mode="worker")
    assert tool.execution_mode == "worker"


def test_invalid_mode_rejected(report_dir):
    with pytest.raises(ValueError, match="execution_mode"):
        PythonREPLTool(report_dir=report_dir, execution_mode="yolo")
    with pytest.raises(ValueError):
        resolve_execution_mode("fork")


def test_inprocess_logs_warning(report_dir, caplog):
    with caplog.at_level("WARNING"):
        PythonREPLTool(report_dir=report_dir, execution_mode="inprocess")
    assert any("execution_mode='inprocess'" in rec.getMessage() for rec in caplog.records)


async def test_inprocess_executes_without_a_pool(inprocess_tool):
    out = await inprocess_tool._execute("x = 40 + 2\nprint(x)")
    assert out == "42\n"
    assert inprocess_tool._worker_pool is None, "inprocess mode must never build a WorkerPool"
    assert isinstance(inprocess_tool._inprocess_handle, InProcessHandle)
    # Namespace API reads the HOST namespace directly.
    assert "x" in await inprocess_tool.list_vars()
    assert await inprocess_tool.get_var("x") == 42
    await inprocess_tool.set_var("y", 7)
    assert inprocess_tool.locals["y"] == 7 and inprocess_tool.globals["y"] == 7
    assert (await inprocess_tool.snapshot())["y"] == 7
    # State persists across calls (same handle, same namespace).
    assert await inprocess_tool._execute("print(x + y)") == "49\n"


async def test_inprocess_error_contract_matches_worker(inprocess_tool):
    out = await inprocess_tool._execute("1/0")
    assert out["status"] == "done_with_errors"
    assert "ZeroDivisionError" in out["result"]
    assert out["error"] == out["result"]


async def test_inprocess_keeps_the_security_gate(inprocess_tool):
    out = await inprocess_tool._execute("import os\nos.system('true')")
    assert out["status"] == "done_with_errors"
    assert "SecurityError" in out["result"]
    assert "os" not in inprocess_tool.locals


async def test_inprocess_deadline_returns_bounded_error(report_dir):
    tool = PythonREPLTool(
        report_dir=report_dir,
        execution_mode="inprocess",
        worker_config=WorkerConfig(deadline_ms=300),
    )
    started = time.monotonic()
    out = await tool._execute("import time\ntime.sleep(1.5)\nz = 1")
    assert time.monotonic() - started < 1.4, "the caller must get its answer at the deadline"
    assert out["status"] == "error"
    assert "deadline_ms=300" in out["error"] and "inprocess" in out["error"]
    # The namespace is NOT reported lost — nothing died.
    assert "ALL variables" not in out["error"]
    # The handle stays busy until the runaway snippet finishes (code-review
    # fix): a second call must not mutate `locals` concurrently with it.
    out2 = await tool._execute("w = 2")
    assert out2["status"] == "error" and "still running" in out2["error"]
    assert "w" not in tool.locals
    # Once it lands, the namespace is usable again and the late assignment
    # is visible.
    await asyncio.sleep(1.5)
    assert tool.locals.get("z") == 1
    assert await tool._execute("w = 2\nprint(w)") == "2\n"


async def test_inprocess_reset_clears_flag_and_namespace(inprocess_tool):
    await inprocess_tool._execute("x = 1")
    handle = await inprocess_tool._get_worker_handle()
    inprocess_tool.reset_environment()
    assert inprocess_tool._pending_worker_reset is True
    # The next acquisition consumes the flag without touching a pool: the
    # namespace is rebuilt (bootstrap bindings only) and, like a worker
    # restart, a NEW handle is handed out so pandas seeding re-runs.
    fresh = await inprocess_tool._get_worker_handle()
    assert fresh is not handle
    assert inprocess_tool._pending_worker_reset is False
    assert inprocess_tool._worker_pool is None
    assert "x" not in inprocess_tool.locals
    assert "pd" in inprocess_tool.locals  # bootstrap bindings are back
    assert await inprocess_tool._execute("print(pd.__name__)") == "pandas\n"
    # `handle.reset()` retires the handle the same way.
    await fresh.reset()
    assert not fresh.is_alive
    assert (await inprocess_tool._get_worker_handle()) is not fresh


async def test_killed_handle_is_replaced(inprocess_tool):
    handle = await inprocess_tool._get_worker_handle()
    await handle.kill()
    assert not handle.is_alive
    assert (await handle.execute("print(1)"))["status"] == "error"
    fresh = await inprocess_tool._get_worker_handle()
    assert fresh is not handle and fresh.is_alive


async def test_pandas_clone_inherits_mode_and_seeds_dataframes(report_dir):
    df = pd.DataFrame({"a": [1, 2, 3]})
    source = PythonPandasTool(dataframes={"sales": df}, report_dir=report_dir, execution_mode="inprocess")
    clone = source.create_session_clone()
    assert clone.execution_mode == "inprocess"
    assert clone._inprocess_handle is None, "the clone must build its own handle over its own namespace"
    out = await clone._execute("print(sales['a'].sum(), sales_col_count)")
    assert isinstance(out, str) and out.startswith("6 1")
    assert clone._worker_pool is None and source._worker_pool is None
    # The clone's handle is bound to the clone, not the source.
    assert clone._inprocess_handle._tool is clone
    clone.locals["only_here"] = True
    assert "only_here" not in source.locals


async def test_pandas_clone_helpers_are_rebound_to_the_clone(report_dir):
    """Code-review fix: `store_result`/`list_variables` must not reach the source."""
    source = PythonPandasTool(
        dataframes={"sales": pd.DataFrame({"a": [1]})}, report_dir=report_dir, execution_mode="inprocess"
    )
    clone = source.create_session_clone()
    out = await clone._execute("store_result('k', 123)")
    assert not (isinstance(out, dict) and out.get("status") == "error"), out
    assert clone.locals["execution_results"]["k"] == 123
    assert clone.locals["k"] == 123
    assert "k" not in source.locals
    assert "k" not in source.locals["execution_results"]
