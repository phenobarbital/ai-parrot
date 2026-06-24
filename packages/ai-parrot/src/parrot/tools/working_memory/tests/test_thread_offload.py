"""Tests for the CPU-bound thread-offload optimisation in WorkingMemoryToolkit.

Large DataFrame copy/summary work (``copy(deep=True)``, ``describe``,
``memory_usage(deep=True)``) is offloaded to a worker thread via
``asyncio.to_thread`` so it does not block the event loop, while small frames
stay inline to avoid the thread-dispatch overhead.

Covers:
- ``_is_large_df`` / ``_has_large_entry`` cell-count gating.
- store / get_stored / import_from_tool / compute_and_store / merge_stored /
  summarize_stored / list_stored / search_stored route large frames through
  ``asyncio.to_thread`` but produce identical results to the inline path.
- Small frames never hit ``asyncio.to_thread``.
"""
import asyncio
import threading

import numpy as np
import pandas as pd
import pytest

from parrot.tools.working_memory import WorkingMemoryToolkit
from parrot.tools.working_memory.internals import CatalogEntry


def _wide_df(rows: int, cols: int) -> pd.DataFrame:
    """Build a deterministic numeric DataFrame of the requested shape."""
    data = {f"c{c}": np.arange(rows, dtype="int64") + c for c in range(cols)}
    return pd.DataFrame(data)


class _ToThreadSpy:
    """Context-manager-free spy that wraps ``asyncio.to_thread`` and records
    whether it was invoked while still delegating to the real implementation."""

    def __init__(self) -> None:
        self.called = False
        self.thread_names: list[str] = []
        self._real = asyncio.to_thread

    async def __call__(self, func, /, *args, **kwargs):
        self.called = True

        def _wrapped(*a, **kw):
            self.thread_names.append(threading.current_thread().name)
            return func(*a, **kw)

        return await self._real(_wrapped, *args, **kwargs)


@pytest.fixture
def spy(monkeypatch) -> _ToThreadSpy:
    """Patch ``asyncio.to_thread`` as seen by the toolkit module with a spy."""
    s = _ToThreadSpy()
    monkeypatch.setattr(
        "parrot.tools.working_memory.tool.asyncio.to_thread", s
    )
    return s


# ── gating ──────────────────────────────────────────────────────────────────

class TestGating:
    def test_is_large_df_threshold(self):
        tk = WorkingMemoryToolkit(thread_offload_cells=1_000)
        assert tk._is_large_df(_wide_df(100, 10)) is True   # 1000 cells == threshold
        assert tk._is_large_df(_wide_df(99, 10)) is False   # 990 cells < threshold

    def test_zero_column_frame_is_not_large(self):
        tk = WorkingMemoryToolkit(thread_offload_cells=1)
        # A frame with rows but no columns must not divide-by-zero or over-count.
        empty_cols = pd.DataFrame(index=range(10))
        assert tk._is_large_df(empty_cols) is False

    def test_has_large_entry_ignores_generic_entries(self):
        tk = WorkingMemoryToolkit(thread_offload_cells=1_000)
        tk._catalog.put("small", _wide_df(10, 2))
        tk._catalog.put_generic("blob", "x" * 10_000)  # huge string, not a frame
        assert tk._has_large_entry() is False
        tk._catalog.put("big", _wide_df(200, 10))  # 2000 cells
        assert tk._has_large_entry() is True

    def test_default_threshold_applied(self):
        tk = WorkingMemoryToolkit()
        assert tk._thread_offload_cells == WorkingMemoryToolkit.DEFAULT_THREAD_OFFLOAD_CELLS


# ── offload routing + correctness ────────────────────────────────────────────

class TestOffloadRouting:
    @pytest.mark.asyncio
    async def test_store_large_frame_offloads(self, spy):
        tk = WorkingMemoryToolkit(thread_offload_cells=1_000, max_rows=3, max_cols=5)
        res = await tk.store("big", _wide_df(500, 5))  # 2500 cells
        assert res["status"] == "stored"
        assert res["summary"]["shape"] == {"rows": 500, "cols": 5}
        assert spy.called is True
        # Summary really ran on a worker thread, not the event-loop thread.
        assert spy.thread_names and all(
            name != threading.main_thread().name for name in spy.thread_names
        )

    @pytest.mark.asyncio
    async def test_store_small_frame_runs_inline(self, spy):
        tk = WorkingMemoryToolkit(thread_offload_cells=1_000_000)
        res = await tk.store("small", _wide_df(10, 3))
        assert res["status"] == "stored"
        assert spy.called is False

    @pytest.mark.asyncio
    async def test_offload_summary_matches_inline_summary(self):
        """The offloaded summary must be byte-for-byte the same as the inline one."""
        df = _wide_df(400, 6)

        inline_tk = WorkingMemoryToolkit(thread_offload_cells=10_000_000, max_rows=4, max_cols=6)
        offload_tk = WorkingMemoryToolkit(thread_offload_cells=1, max_rows=4, max_cols=6)

        inline_res = await inline_tk.store("k", df.copy())
        offload_res = await offload_tk.store("k", df.copy())
        assert inline_res["summary"] == offload_res["summary"]

    @pytest.mark.asyncio
    async def test_get_stored_large_offloads(self, spy):
        tk = WorkingMemoryToolkit(thread_offload_cells=1_000)
        tk._catalog.put("big", _wide_df(500, 5))
        spy.called = False
        out = await tk.get_stored("big")
        assert out["shape"]["rows"] == 500
        assert spy.called is True

    @pytest.mark.asyncio
    async def test_import_from_tool_large_offloads_copy_and_summary(self, spy):
        df = _wide_df(500, 5)
        tk = WorkingMemoryToolkit(
            thread_offload_cells=1_000,
            tool_locals_registry={"PandasTool": {"df": df}},
        )
        res = await tk.import_from_tool("PandasTool", "df", "imported")
        assert res["status"] == "imported"
        # Deep copy decoupled the stored frame from the source namespace.
        stored = tk._catalog.get("imported")
        assert isinstance(stored, CatalogEntry)
        assert stored.df is not df
        # Both the copy and the summary were offloaded → to_thread used twice.
        assert spy.called is True
        assert len(spy.thread_names) >= 2

    @pytest.mark.asyncio
    async def test_compute_and_store_large_offloads(self, spy):
        tk = WorkingMemoryToolkit(thread_offload_cells=1_000)
        tk._catalog.put("src", _wide_df(500, 5))
        spy.called = False
        res = await tk.compute_and_store(
            {"op": "select", "source": "src", "store_as": "sel", "select_columns": ["c0", "c1"]}
        )
        assert res["status"] == "computed_and_stored"
        assert spy.called is True

    @pytest.mark.asyncio
    async def test_merge_stored_large_offloads(self, spy):
        tk = WorkingMemoryToolkit(thread_offload_cells=1_000)
        tk._catalog.put("a", _wide_df(500, 5))
        tk._catalog.put("b", _wide_df(500, 5))
        spy.called = False
        res = await tk.merge_stored(keys=["a", "b"], store_as="m")
        assert res["status"] == "merged"
        assert spy.called is True

    @pytest.mark.asyncio
    async def test_list_stored_offloads_when_any_entry_large(self, spy):
        tk = WorkingMemoryToolkit(thread_offload_cells=1_000)
        tk._catalog.put("small", _wide_df(5, 2))
        tk._catalog.put("big", _wide_df(500, 5))
        spy.called = False
        out = await tk.list_stored()
        assert out["count"] == 2
        assert spy.called is True

    @pytest.mark.asyncio
    async def test_list_stored_inline_when_all_small(self, spy):
        tk = WorkingMemoryToolkit(thread_offload_cells=1_000_000)
        tk._catalog.put("s1", _wide_df(5, 2))
        tk._catalog.put("s2", _wide_df(5, 2))
        out = await tk.list_stored()
        assert out["count"] == 2
        assert spy.called is False

    @pytest.mark.asyncio
    async def test_search_stored_large_offloads_and_matches(self, spy):
        tk = WorkingMemoryToolkit(thread_offload_cells=1_000)
        tk._catalog.put("revenue_big", _wide_df(500, 5), description="quarterly revenue")
        tk._catalog.put("other", _wide_df(500, 5), description="misc")
        spy.called = False
        out = await tk.search_stored("revenue")
        assert out["count"] == 1
        assert out["matches"][0]["key"] == "revenue_big"
        assert spy.called is True
