"""Full-session and concurrent-session end-to-end tests (FEAT-380 Module 7, TASK-1945).

Exercises the whole stack together: `WorkerPool` acquisition, `inject_df`
(Arrow transport), multi-turn `exec`, plots, and `snapshot` — plus the
concurrency ceiling under `WorkerPool` (TASK-1942) with real workers.
"""

from __future__ import annotations

import pandas as pd
import pytest

from parrot.tools.repl_worker.pool import WorkerPool, WorkerPoolExhaustedError
from parrot.tools.repl_worker.protocol import WorkerConfig


@pytest.fixture
def sample_df():
    return pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})


@pytest.fixture
def real_worker_config():
    """Generous AS (spec default ~4 GiB) so real workers can actually boot."""
    return WorkerConfig(deadline_ms=10_000, max_workers=4, idle_ttl_seconds=30, prewarm_pool_size=0)


async def test_e2e_data_analysis_session(real_worker_config, sample_df, tmp_path):
    """inject_df -> multi-turn exec -> plot -> snapshot; state persists throughout."""
    pool = WorkerPool(real_worker_config, output_dir=str(tmp_path))
    try:
        handle = await pool.acquire("session-a")

        # 1. inject_df (Arrow transport, TASK-1945)
        await handle.inject_dataframe("sales", sample_df)

        # 2. multi-turn exec — state persists across calls (G1)
        r1 = await handle.execute("total_a = sales['a'].sum()")
        assert isinstance(r1, str)
        # int(...) forces a plain Python int — numpy int64 doesn't hit the
        # scalar-preview branch of `_describe_new_var`, only showing the type.
        r2 = await handle.execute("result = int(total_a) * 2")
        assert isinstance(r2, str)
        assert "12" in r2  # sum([1,2,3]) * 2 == 12

        # 3. plot
        r3 = await handle.execute("plt.plot(sales['a'])\nresult = save_current_plot()")
        assert isinstance(r3, str)
        assert "Plot saved" in r3
        assert list(tmp_path.glob("*.png"))

        # 4. snapshot — sees the injected DataFrame and the computed scalar
        snap = await handle.snapshot()
        assert "total_a" in snap
        assert "sales" in snap
    finally:
        await pool.shutdown()


async def test_e2e_concurrent_sessions(real_worker_config, tmp_path):
    """N sessions under the ceiling all work independently; ceiling+1 is rejected."""
    config = WorkerConfig(
        deadline_ms=10_000, max_workers=2, idle_ttl_seconds=30, prewarm_pool_size=0
    )
    pool = WorkerPool(config, output_dir=str(tmp_path))
    try:
        handle_a = await pool.acquire("session-a")
        handle_b = await pool.acquire("session-b")
        assert handle_a is not handle_b

        await handle_a.execute("secret = 'a-only'")
        await handle_b.execute("secret = 'b-only'")

        result_a = await handle_a.execute("result = secret")
        result_b = await handle_b.execute("result = secret")
        assert "a-only" in result_a
        assert "b-only" in result_b

        # Ceiling reached (2 sessions, max_workers=2) — 3rd rejected immediately.
        with pytest.raises(WorkerPoolExhaustedError):
            await pool.acquire("session-c")
    finally:
        await pool.shutdown()


async def test_share_dataframe_delivers_into_worker_namespace(sample_df, tmp_path):
    """`ToolManager.share_dataframe()` -> `PythonPandasTool` -> worker (Arrow transport).

    Regression coverage for the `add_dataframe(..., regenerate_guide=True)`
    kwarg mismatch fixed in this task (TASK-1945): before the fix,
    `share_dataframe()`'s auto-push into `python_pandas` always raised
    `TypeError`, silently swallowed, so the DataFrame never reached the tool
    (or its worker) at all.
    """
    from parrot.tools.manager import ToolManager
    from parrot.tools.pythonpandas import PythonPandasTool

    tool = PythonPandasTool(report_dir=str(tmp_path))
    tm = ToolManager()
    tm.pandas_tool_name = tool.name  # "python_repl_pandas" — see manager.py default mismatch
    tm.register_tool(tool)
    try:
        tm.share_dataframe("sales", sample_df)

        # The push landed in the tool's own df_locals (host-side bookkeeping,
        # updated synchronously by add_dataframe() -> _process_dataframes()).
        assert "sales" in tool.df_locals

        # And it's actually delivered into the WORKER's namespace, visible to
        # executed code, the next time the tool's worker is used (lazy
        # diff-based seeding, TASK-1944, upgraded to Arrow by TASK-1945).
        result = await tool._execute("result = len(sales)")
        assert isinstance(result, str)
        assert "3" in result
    finally:
        if tool._worker_pool is not None:
            await tool._worker_pool.shutdown()
