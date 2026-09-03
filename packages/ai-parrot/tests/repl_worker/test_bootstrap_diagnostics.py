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
import os
import subprocess
import sys
import threading

import pytest

from parrot.tools.repl_worker.handle import WorkerBootstrapError, WorkerHandle, probe_process_state
from parrot.tools.repl_worker.protocol import WorkerConfig
from parrot.tools.repl_worker import worker as worker_module


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


async def _await_ready_against_silent_child(executor, budget_ms: int) -> str:
    """Drive `_await_ready` with a child that never writes a frame."""
    handle = WorkerHandle(WorkerConfig(bootstrap_timeout_ms=budget_ms), executor=executor)
    read_end, write_end = os.pipe()
    proc = subprocess.Popen(["sleep", "30"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    handle._proc = proc
    handle._from_worker = os.fdopen(read_end, "rb", buffering=0)
    handle._ready = asyncio.get_event_loop().create_future()
    try:
        await handle._await_ready()
        with pytest.raises(WorkerBootstrapError) as excinfo:
            await handle.wait_ready()
        assert proc.poll() is not None, "the silent child must have been killed"
        return str(excinfo.value)
    finally:
        os.close(write_end)
        handle._from_worker.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        handle._stdio_executor.shutdown(wait=False)
        handle._lifecycle_executor.shutdown(wait=False)


@pytest.mark.skipif(sys.platform != "linux", reason="/proc probe is Linux-only")
async def test_silent_child_reports_proc_state():
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    try:
        message = await _await_ready_against_silent_child(executor, budget_ms=400)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    assert "no ready frame within the bootstrap budget" in message
    assert "process: state=S" in message, message  # `sleep` is sleeping, not stopped
    assert "wchan=" in message
    assert "stderr tail: <empty>" in message


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
