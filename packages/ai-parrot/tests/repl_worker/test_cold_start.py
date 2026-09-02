"""Cold-start regression tests for FEAT-500 (spec G6/AC7, Module 6).

This module is the permanent home of the proposal's **Probe B** — the
deterministic reproduction of the cold-start death spiral
(`sdd/state/FEAT-518/findings/F016-probe-death-spiral-under-load.md`):

1. `WorkerHandle.start()` returned right after `Popen`, so the pool counted a
   still-booting worker as a ready spare;
2. `PythonPandasTool` seeded `df_locals` into that cold worker with
   `set_var()`, which had a hard-coded 5 s budget;
3. a `set_var` timeout SIGKILLed the worker and raised a bare `TimeoutError`
   (`str()` == `''`);
4. the next call bound an equally-cold spare and killed it too — forever, on a
   5 s grid, with `worker is dead, restarting` in the logs and
   `Error executing Python code: ` reaching the LLM.

The worker's bootstrap is delayed deterministically with `setup_code`, which
`PythonREPLTool` mirrors into the child via `_worker_repl_kwargs` and the
child runs in its own `__init__` -> `_bootstrap()`. No test hook exists (or is
wanted) in production code for this.

These tests spawn REAL worker subprocesses and deliberately sleep 8 s inside
the bootstrap, so they are slow by construction (~20 s each: the host-side
`PythonREPLTool.__init__` runs the same `setup_code` once per process too).
No `@pytest.mark.slow` is applied — no such marker is registered in
`pytest.ini` / `pyproject.toml`, and `--strict-markers` is enabled.
"""

from __future__ import annotations

import asyncio
import logging
import time

import pandas as pd
import pytest

from parrot.tools.pythonpandas import PythonPandasTool
from parrot.tools.pythonrepl import PythonREPLTool
from parrot.tools.repl_worker import NamespaceTimeoutError, WorkerConfig

#: Pushes the worker's own bootstrap well past the old hard-coded 5 s
#: `set_var`/`get_var`/`list_vars` budget — the precondition of the spiral.
SLOW_BOOT = "import time\ntime.sleep(8)"

#: Long deadline, no prewarmed spares. `prewarm_pool_size=0` is what makes the
#: `spawned worker pid=` count exact: only the session worker is ever spawned.
COLD_START_CONFIG = WorkerConfig(
    deadline_ms=60_000,
    max_workers=2,
    idle_ttl_seconds=60,
    prewarm_pool_size=0,
)


async def _shutdown(tool: PythonREPLTool) -> None:
    """Tear down the tool's lazily-created worker pool (mirrors test_integration)."""
    if tool._worker_pool is not None:
        await tool._worker_pool.shutdown()


async def test_cold_worker_seeding_survives_slow_bootstrap(tmp_path, caplog):
    """THE Probe B regression (AC7): an 8 s bootstrap no longer kills anything.

    Three consecutive calls on a tool whose worker takes 8 s to boot must all
    succeed, with zero worker restarts and exactly one worker ever spawned.
    Before FEAT-500 this produced three killed workers and three blank errors.
    """
    caplog.set_level(logging.DEBUG, logger="parrot.tools.repl_worker")
    tool = PythonPandasTool(
        dataframes=None,
        report_dir=str(tmp_path),
        setup_code=SLOW_BOOT,
        worker_config=COLD_START_CONFIG,
    )
    # The scalar the probe seeded — pushed via `set_var()` on a cold worker,
    # which is precisely the call that used to time out at 5 s and SIGKILL.
    tool.df_locals["n_rows"] = 3
    try:
        for _ in range(3):
            out = await tool._execute("print(n_rows)")
            assert isinstance(out, str), f"expected success, got {out!r}"
            assert "3" in out

        # The log signature of the spiral, asserted absent.
        assert "worker is dead, restarting" not in caplog.text
        assert caplog.text.count("spawned worker pid=") == 1
    finally:
        await _shutdown(tool)


async def test_pandas_seeding_order_independent(tmp_path, caplog):
    """A DataFrame plus its scalar metadata seed fine in ANY order (F009/F016 C6).

    `_get_worker_handle()` iterates `set(self.df_locals) - self._seeded_df_names`,
    so seeding order follows set iteration (hash) order. Reordering `df_locals`
    must therefore change nothing: success must not depend on the DataFrame
    happening to be seeded before the scalars ("buying time" was explicitly
    rejected as a fix).
    """
    caplog.set_level(logging.DEBUG, logger="parrot.tools.repl_worker")
    frame = pd.DataFrame({"amount": [1, 2, 3], "region": ["a", "b", "c"]})

    tool = PythonPandasTool(
        dataframes={"sales": frame},
        report_dir=str(tmp_path),
        setup_code=SLOW_BOOT,
        worker_config=COLD_START_CONFIG,
    )
    try:
        # The constructor's `_process_dataframes()` registers the DataFrame,
        # its alias and the *_row_count/_col_count/_shape/_columns scalars.
        assert len(tool.df_locals) > 1
        out = await tool._execute("print(sales.shape)")
        assert isinstance(out, str), f"expected success, got {out!r}"
        assert "(3, 2)" in out

        # Now seed the very same payload in the opposite insertion order into a
        # fresh worker: force a full reseed by dropping the seeded bookkeeping.
        tool.df_locals = dict(reversed(list(tool.df_locals.items())))
        tool._seeded_df_names = set()
        tool._seeded_worker_handle_id = None

        out = await tool._execute("print(sales.shape)")
        assert isinstance(out, str), f"expected success, got {out!r}"
        assert "(3, 2)" in out

        assert "worker is dead, restarting" not in caplog.text
    finally:
        await _shutdown(tool)


async def test_namespace_api_after_soft_timeout_keeps_state(tmp_path, monkeypatch):
    """AC3 end-to-end: a non-lethal namespace timeout preserves the namespace.

    Set `x = 1`, force one `list_vars()` timeout on a tight
    `namespace_timeout_ms`, then read `x` back — the worker (and its state)
    must have survived. Before FEAT-500 that timeout SIGKILLed the worker and
    `x` was gone.
    """
    config = WorkerConfig(
        deadline_ms=60_000,
        max_workers=2,
        idle_ttl_seconds=60,
        prewarm_pool_size=0,
        namespace_timeout_ms=200,
    )
    tool = PythonREPLTool(report_dir=str(tmp_path), worker_config=config)
    try:
        out = await tool._execute("x = 1")
        assert isinstance(out, str), f"expected success, got {out!r}"

        handle = await tool._get_worker_handle()
        real_roundtrip = handle._roundtrip

        def slow_roundtrip(request):
            time.sleep(1.0)
            return real_roundtrip(request)

        monkeypatch.setattr(handle, "_roundtrip", slow_roundtrip)
        with pytest.raises(NamespaceTimeoutError) as excinfo:
            await tool.list_vars()
        assert str(excinfo.value)  # never blank (AC5)
        assert handle.is_alive is True

        monkeypatch.setattr(handle, "_roundtrip", real_roundtrip)
        await asyncio.sleep(1.2)  # let the parked reply land, then be drained

        assert await tool.get_var("x") == 1
    finally:
        await _shutdown(tool)
