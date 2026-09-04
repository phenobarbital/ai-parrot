"""Bootstrap-failure diagnostics on ``WorkerHandle`` / ``worker.py``.

A worker that never sends its ready frame used to fail with
``stderr tail: <empty>`` and nothing else. Now the error says (a) whether the
readiness read ever ran (thread starvation vs a stuck child), (b) the child's
``/proc`` state at the moment of the kill, and (c) the last bootstrap stage
the child reported on stderr.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import os
import subprocess
import sys
import threading
import time

import pytest

from parrot.tools.repl_worker.handle import WorkerBootstrapError, WorkerHandle, probe_process_state
from parrot.tools.repl_worker.observer import ProcessObserver
from parrot.tools.repl_worker.protocol import WorkerConfig
from parrot.tools.repl_worker import worker as worker_module


async def _noop_hard_breach(_verdict) -> None:
    """Default no-op `on_hard_breach` callback for observers under test."""


def test_probe_process_state_reports_self():
    probe = probe_process_state(os.getpid())
    if sys.platform != "linux":
        assert probe == ""
        return
    assert probe.startswith("state=R") or probe.startswith("state=S")
    for key in ("threads=", "vmpeak=", "wchan=", "cpu="):
        assert key in probe


def test_probe_process_state_never_raises():
    assert probe_process_state(None) == ""
    assert probe_process_state(2**22 + 12345) == ""  # almost certainly no such pid


async def _await_ready_against_silent_child(executor, budget_ms: int, *, config: WorkerConfig | None = None) -> str:
    """Drive `_await_ready` with a child that never writes a frame.

    FEAT-521: also wires up a real `ProcessObserver` against the silent
    child, mirroring what `WorkerHandle.start()` does — so `_await_ready()`'s
    timeout branch has ring data to build its observer-derived progress note
    from (`_describe_bootstrap_progress()`) instead of degrading silently
    (the one-shot `probe_process_state()` snapshot this helper used to rely
    on was removed from `_await_ready()` in TASK-2777).
    """
    resolved_config = config or WorkerConfig(bootstrap_timeout_ms=budget_ms, observer_poll_ms=50)
    handle = WorkerHandle(resolved_config, executor=executor)
    read_end, write_end = os.pipe()
    proc = subprocess.Popen(["sleep", "30"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    handle._proc = proc
    handle._from_worker = os.fdopen(read_end, "rb", buffering=0)
    handle._ready = asyncio.get_event_loop().create_future()
    handle.observer = ProcessObserver(proc.pid, resolved_config, on_hard_breach=_noop_hard_breach)
    observer_task = asyncio.get_event_loop().create_task(handle.observer.run())
    stall_task = None
    if resolved_config.bootstrap_stall_ms > 0:
        stall_task = asyncio.get_event_loop().create_task(handle._watch_bootstrap_stall())
        handle._bootstrap_stall_task = stall_task
    try:
        await handle._await_ready()
        with pytest.raises(WorkerBootstrapError) as excinfo:
            await handle.wait_ready()
        assert proc.poll() is not None, "the silent child must have been killed"
        return str(excinfo.value)
    finally:
        for task in (observer_task, stall_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        os.close(write_end)
        handle._from_worker.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        handle._stdio_executor.shutdown(wait=False)
        handle._lifecycle_executor.shutdown(wait=False)


@pytest.mark.skipif(sys.platform != "linux", reason="/proc probe is Linux-only")
async def test_silent_child_reports_observer_diagnostics():
    """FEAT-521: the bootstrap-timeout message names the observer's progress note.

    A `sleep 30` child never advances any CPU, so the observer's trailing
    window sees zero progress — `_describe_bootstrap_progress()` reports the
    "flat"/"stalled" branch, not "starved" (which needs at least one CPU
    tick to be measured as advancing).
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    try:
        message = await _await_ready_against_silent_child(executor, budget_ms=400)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    assert "no ready frame within the bootstrap budget" in message
    assert "booting, cpu flat since last sample" in message, message
    assert "state=sleeping" in message
    assert "wchan=" in message
    assert "stderr tail: <empty>" in message


async def test_bootstrap_error_reports_cpu_progress():
    """FEAT-521: `_describe_bootstrap_progress()` names the verdict window explicitly.

    Cross-platform (unlike the Linux-only `/proc` wchan check above) since
    it only asserts on the `cpu advanced .. s in .. s` / `cpu flat` shape,
    which comes from `psutil`, not `/proc`.
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    try:
        message = await _await_ready_against_silent_child(executor, budget_ms=400)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    assert "booting" in message
    assert ("cpu advanced" in message) or ("cpu flat" in message)


async def test_bootstrap_stall_ms_fails_early():
    """FEAT-521 spec §2: `bootstrap_stall_ms > 0` fails the bootstrap BEFORE
    the full `bootstrap_timeout_ms` budget once the observer sees a
    sustained CPU-flat stall.

    Unlike `_await_ready_against_silent_child` (which sequentially awaits
    `_await_ready()` to completion — always ~`bootstrap_timeout_ms`,
    regardless of what `_watch_bootstrap_stall()` does concurrently), this
    races `wait_ready()` directly: the stall watcher resolves
    `handle._ready` EARLIER via the idempotent `_fail_ready()`, while
    `_await_ready()`'s own internal read keeps blocking harmlessly in the
    background.
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    config = WorkerConfig(
        bootstrap_timeout_ms=30_000,  # generous — the stall path must win first
        bootstrap_stall_ms=300,
        observer_poll_ms=50,
    )
    handle = WorkerHandle(config, executor=executor)
    read_end, write_end = os.pipe()
    proc = subprocess.Popen(["sleep", "30"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    handle._proc = proc
    handle._from_worker = os.fdopen(read_end, "rb", buffering=0)
    handle._ready = asyncio.get_event_loop().create_future()
    handle.observer = ProcessObserver(proc.pid, config, on_hard_breach=_noop_hard_breach)
    observer_task = asyncio.get_event_loop().create_task(handle.observer.run())
    ready_task = asyncio.get_event_loop().create_task(handle._await_ready())
    stall_task = asyncio.get_event_loop().create_task(handle._watch_bootstrap_stall())
    handle._bootstrap_stall_task = stall_task

    started = time.monotonic()
    try:
        with pytest.raises(WorkerBootstrapError) as excinfo:
            await asyncio.wait_for(handle.wait_ready(), timeout=5.0)
        elapsed = time.monotonic() - started
        assert elapsed < 5.0, "must fail early via bootstrap_stall_ms, not wait the full 30s budget"
        message = str(excinfo.value)
        assert "bootstrap stalled" in message
        assert "bootstrap_stall_ms exceeded" in message
        assert proc.poll() is not None, "the stalled child must have been killed"
    finally:
        for task in (observer_task, ready_task, stall_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        os.close(write_end)
        handle._from_worker.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        handle._stdio_executor.shutdown(wait=False)
        handle._lifecycle_executor.shutdown(wait=False)
        executor.shutdown(wait=False, cancel_futures=True)


async def test_starved_executor_is_named_not_blamed_on_the_worker():
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    release = threading.Event()
    executor.submit(release.wait)  # the only thread is now busy for the whole budget
    try:
        message = await _await_ready_against_silent_child(executor, budget_ms=400)
    finally:
        release.set()
        executor.shutdown(wait=False, cancel_futures=True)
    assert "never got an executor thread" in message
    assert "all 1 thread(s)" in message
    assert "no ready frame within the bootstrap budget" not in message


def test_worker_stage_markers_go_to_stderr(capsys):
    worker_module._stage("hello stage")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"repl_worker[pid={os.getpid()}] hello stage" in captured.err


def test_real_worker_reports_stages_in_stderr_tail():
    """End to end: a real worker's stderr tail ends with the ready stage."""

    async def run():
        handle = WorkerHandle(WorkerConfig())
        await handle.start()
        try:
            ready = await handle.wait_ready()
            assert ready.pid == handle._proc.pid
            # Give the drain task a moment to pump the last stderr line.
            for _ in range(50):
                if any("sending ready frame" in line for line in handle._stderr_tail):
                    break
                await asyncio.sleep(0.1)
            stages = [line for line in handle._stderr_tail if line.startswith(f"repl_worker[pid={ready.pid}]")]
            assert any("rlimits applied" in s for s in stages), stages
            assert any("building namespace" in s for s in stages), stages
            assert any("sending ready frame" in s for s in stages), stages
        finally:
            await handle.kill()

    asyncio.run(run())
