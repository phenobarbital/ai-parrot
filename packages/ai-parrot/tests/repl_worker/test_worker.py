"""Worker entrypoint tests for FEAT-380 Module 2 (`repl_worker.worker`).

Exercises the actual spawned subprocess (``python -m
parrot.tools.repl_worker.worker``) wherever the acceptance criteria demand
process isolation (rlimits, per-worker bootstrap); uses the in-process
``WorkerNamespace`` directly for gate-revalidation and dispatch behaviour
that doesn't need a real child process.

Spawned workers talk over a **dedicated pipe** (spec §2: "pipe dedicado"),
never stdin/stdout — this framework's logging setup (`navconfig`) attaches a
colorized `StreamHandler` to stdout for every logger, which would otherwise
corrupt the binary framing the moment `PythonREPLTool.__init__` logs
anything during bootstrap.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from parrot.tools.repl_worker.protocol import (
    ExecRequest,
    ExecResult,
    ListNsRequest,
    ListNsResponse,
    PingRequest,
    PongResponse,
    ReadyResponse,
    WorkerConfig,
    read_frame,
    write_frame,
)
from parrot.tools.repl_worker.worker import WorkerNamespace, apply_rlimits

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="rlimits are POSIX-only")


@pytest.fixture
def worker_config():
    """Low limits for fast tests (mirrors the spec's fixture).

    Only used where no real pandas/numpy/matplotlib import happens inside
    the limited process (e.g. ``test_worker_rlimits_applied`` calls
    `apply_rlimits` directly in a bare helper script) — see
    ``real_worker_config`` below for anything that spawns the actual
    `repl_worker.worker` entrypoint.

    FEAT-521: `memory_soft/hard_limit_bytes=0` — this fixture is
    specifically about the pre-existing `RLIMIT_AS` mechanism at a
    deliberately tiny value; the new host-side RSS guardrails' default
    `memory_hard_limit_bytes` (8 GiB) would otherwise exceed this tiny
    `rlimit_as_bytes` and fail `WorkerConfig`'s own `hard <=
    rlimit_as_bytes` validator (same fix as `test_handle.py`'s
    `tiny_as_config`).
    """
    return WorkerConfig(
        rlimit_as_bytes=512 * 1024**2,
        memory_soft_limit_bytes=0,
        memory_hard_limit_bytes=0,
        deadline_ms=2_000,
        interrupt_grace_ms=500,
        max_workers=2,
        idle_ttl_seconds=5,
        prewarm_pool_size=0,
    )


@pytest.fixture
def real_worker_config():
    """Config for tests that spawn the real worker entrypoint.

    `PythonREPLTool.__init__` imports pandas/numpy/matplotlib, which need
    more virtual address space than the spec's illustrative 512 MiB
    "fast tests" fixture allows for — importing `numpy.random` alone fails
    to mmap its compiled extensions under a 512 MiB (and even 1 GiB)
    `RLIMIT_AS`. This is exactly the calibration risk the spec flags
    ("RLIMIT_AS mal calibrado: pandas reserva más de lo que toca") and the
    reason Module 8 exists as a dedicated empirical-calibration task; this
    fixture uses the spec's own *default* (~4 GiB) rather than re-guessing
    a smaller number here.
    """
    return WorkerConfig(
        deadline_ms=5_000,
        max_workers=2,
        idle_ttl_seconds=5,
        prewarm_pool_size=0,
    )


class SpawnedWorker:
    """A real `repl_worker.worker` subprocess plus its dedicated control pipes.

    Mirrors the spec's Component Diagram ("control (pipe)") — the
    protocol never touches stdin/stdout, which this framework's logging
    setup writes to directly (see module docstring).
    """

    def __init__(self, config: WorkerConfig, output_dir: str):
        to_worker_r, to_worker_w = os.pipe()
        from_worker_r, from_worker_w = os.pipe()

        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "parrot.tools.repl_worker.worker",
                config.model_dump_json(),
                str(to_worker_r),
                str(from_worker_w),
                output_dir,
            ],
            pass_fds=(to_worker_r, from_worker_w),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Parent doesn't need the child's ends of either pipe.
        os.close(to_worker_r)
        os.close(from_worker_w)
        self._to_worker = os.fdopen(to_worker_w, "wb", buffering=0)
        self._from_worker = os.fdopen(from_worker_r, "rb", buffering=0)

    def send(self, message) -> None:
        write_frame(self._to_worker, message)

    def recv(self):
        return read_frame(self._from_worker)

    def recv_ready(self) -> ReadyResponse:
        """Consume the worker's FEAT-500 readiness frame (always the first one)."""
        frame = self.recv()
        assert isinstance(frame, ReadyResponse), f"expected ReadyResponse first, got {frame!r}"
        return frame

    def close(self) -> None:
        self._to_worker.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)
        self._from_worker.close()


def _spawn_worker(config: WorkerConfig, output_dir: str) -> SpawnedWorker:
    """Spawn a real worker subprocess speaking the framed protocol over a dedicated pipe."""
    return SpawnedWorker(config, output_dir)


def test_rlimit_as_default_is_calibrated():
    """Guard (TASK-1946/AC15): the shipped default matches the calibrated,
    documented value. See artifacts/logs/feat-380-rlimit-as-calibration.md
    before changing — this is not "set by eye", it's measured.
    """
    assert WorkerConfig().rlimit_as_bytes == 12 * 1024**3


class TestApplyRlimits:
    @posix_only
    def test_worker_rlimits_applied(self, worker_config):
        """`apply_rlimits` sets AS/CPU/NOFILE per config and RLIMIT_CORE == 0.

        Verified via a helper subprocess that calls `apply_rlimits` directly
        and reports back `resource.getrlimit(...)` — independent of the
        sandbox gate (which categorically denies importing `resource` from
        REPL code, out of scope for this task to change).
        """
        script = (
            "import json, resource, sys\n"
            "from parrot.tools.repl_worker.worker import apply_rlimits\n"
            "from parrot.tools.repl_worker.protocol import WorkerConfig\n"
            "config = WorkerConfig.model_validate_json(sys.argv[1])\n"
            "apply_rlimits(config)\n"
            "print(json.dumps({\n"
            "    'as': resource.getrlimit(resource.RLIMIT_AS),\n"
            "    'cpu': resource.getrlimit(resource.RLIMIT_CPU),\n"
            "    'nofile': resource.getrlimit(resource.RLIMIT_NOFILE),\n"
            "    'core': resource.getrlimit(resource.RLIMIT_CORE),\n"
            "}))\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script, worker_config.model_dump_json()],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0, proc.stderr
        import json as _json

        reported = _json.loads(proc.stdout.strip().splitlines()[-1])
        assert reported["as"][0] == worker_config.rlimit_as_bytes
        assert reported["cpu"][0] == worker_config.rlimit_cpu_seconds
        assert reported["nofile"][0] == worker_config.rlimit_nofile
        assert reported["core"][0] == 0

    def test_non_posix_skips_with_visible_log(self, worker_config, monkeypatch, caplog):
        """When `resource` is unavailable, apply_rlimits skips with a warning (AC16)."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "resource":
                raise ImportError("simulated non-POSIX platform")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with caplog.at_level("WARNING"):
            apply_rlimits(worker_config)
        assert any("POSIX-only" in record.message for record in caplog.records)


class TestWorkerNamespaceGate:
    def test_worker_revalidates_gate(self, tmp_path):
        """Blocked code sent directly to the worker namespace is rejected before exec."""
        namespace = WorkerNamespace(output_dir=str(tmp_path))
        result = namespace.exec(ExecRequest(code="import os\nos.system('id')", deadline_ms=1000))
        assert result.status in ("error", "done_with_errors")
        assert "denied" in (result.error or "").lower() or "SecurityError" in (result.result or "")

    def test_execute_contract_invariant(self, tmp_path):
        """G5: str-shaped success / dict-shaped error, same as the in-process REPL."""
        namespace = WorkerNamespace(output_dir=str(tmp_path))
        ok = namespace.exec(ExecRequest(code="x = 1 + 1", deadline_ms=1000))
        assert isinstance(ok, ExecResult)
        assert ok.status is None
        assert ok.output is not None

        err = namespace.exec(ExecRequest(code="raise ValueError('boom')", deadline_ms=1000))
        assert err.status in ("error", "done_with_errors")
        assert err.error is not None

    def test_list_ns_reports_preloaded_libraries(self, tmp_path):
        namespace = WorkerNamespace(output_dir=str(tmp_path))
        names = namespace.list_ns()
        assert "pd" in names
        assert "np" in names


class TestWorkerSubprocess:
    def test_worker_first_frame_is_ready(self, real_worker_config, tmp_path):
        """FEAT-500 AC1 (worker half): readiness is announced as the first frame.

        The frame is only written after ``WorkerNamespace`` is fully
        constructed, and writing it does not disturb the service loop.
        """
        worker = _spawn_worker(real_worker_config, str(tmp_path))
        try:
            first = worker.recv()
            assert isinstance(first, ReadyResponse)
            assert first.pid == worker.proc.pid
            assert first.bootstrap_ms >= 0
            worker.send(PingRequest())
            assert isinstance(worker.recv(), PongResponse)
        finally:
            worker.close()

    def test_bootstrap_per_worker(self, real_worker_config, tmp_path):
        """Two independently-spawned workers each bootstrap their own environment.

        Process isolation (a fresh interpreter per worker) is what fixes the
        `_bootstrapped` class-variable bug (AC14) — this proves both workers
        report the preloaded libraries independently, not that the SECOND
        one skipped setup because the FIRST already flipped a shared flag.
        """
        workers = []
        try:
            for i in range(2):
                out_dir = tmp_path / f"worker_{i}"
                out_dir.mkdir()
                workers.append(_spawn_worker(real_worker_config, str(out_dir)))

            for worker in workers:
                worker.recv_ready()  # FEAT-500: readiness frame precedes any reply
                worker.send(ListNsRequest())
                response = worker.recv()
                assert isinstance(response, ListNsResponse)
                assert "pd" in response.names
                assert "np" in response.names
        finally:
            for worker in workers:
                worker.close()

    def test_ping_pong_over_real_subprocess(self, real_worker_config, tmp_path):
        worker = _spawn_worker(real_worker_config, str(tmp_path))
        try:
            worker.recv_ready()  # FEAT-500: readiness frame precedes any reply
            worker.send(PingRequest())
            response = worker.recv()
            assert isinstance(response, PongResponse)
        finally:
            worker.close()

    def test_exec_over_real_subprocess(self, real_worker_config, tmp_path):
        worker = _spawn_worker(real_worker_config, str(tmp_path))
        try:
            worker.recv_ready()  # FEAT-500: readiness frame precedes any reply
            worker.send(ExecRequest(code="x = 21 * 2\nresult = x", deadline_ms=2000))
            response = worker.recv()
            assert isinstance(response, ExecResult)
            assert response.status is None
            assert "42" in (response.output or "")
        finally:
            worker.close()
