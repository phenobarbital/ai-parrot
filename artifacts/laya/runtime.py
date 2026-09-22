"""Host-side owner of one isolated Laya inference subprocess (spec §3 Module 2)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from artifacts.laya.models import EvaluationConfig, PredictionRequest, PredictionResult, validate_answers

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GRACE_S = 5.0  # spec §3 M2: 5 s graceful, then terminate, then 5 s, then kill


class ReadyRecord(BaseModel):
    """Validated first line from the worker (spec §3 M2 'Ready record')."""

    model_config = ConfigDict(extra="allow")
    type: str
    worker_pid: int
    device: str
    checkpoint_path: str
    checkpoint_revision: str
    checkpoint_sha256: str | None = None
    packages: dict[str, str | None] = {}
    max_input_tokens: int | None = None
    torch_threads: int | None = None
    load_ms: float
    python: str
    platform: str


class WorkerStartupError(RuntimeError):
    """Raised by ``__aenter__``; carries a stable ``error_code`` from ``ERROR_CODES``."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class LayaWorker:
    """Own one isolated inference subprocess and its request/response stream."""

    def __init__(self, config: EvaluationConfig) -> None:
        """Store configuration without loading models or starting a process."""
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.ready: ReadyRecord | None = None
        self.failed = False
        self.peak_rss_kb: int | None = None
        self.stderr_tail: deque[str] = deque(maxlen=200)
        self._proc: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self.startup_ms: float | None = None

    def _argv(self) -> list[str]:
        c = self.config
        return [
            str(c.worker_python),
            "-m",
            c.worker_module,
            "--checkpoint",
            str(c.checkpoint_path),
            "--revision",
            c.checkpoint_revision,
        ]

    async def __aenter__(self) -> "LayaWorker":
        """Start the worker and await a validated ready record within the startup deadline."""
        t0 = time.perf_counter()
        self._proc = await asyncio.create_subprocess_exec(
            *self._argv(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(_REPO_ROOT),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        try:
            line = await asyncio.wait_for(self._proc.stdout.readline(), self.config.startup_timeout_s)
        except asyncio.TimeoutError:
            await self._shutdown()
            raise WorkerStartupError(
                "startup_timeout", f"no ready record within {self.config.startup_timeout_s}s"
            ) from None
        except asyncio.CancelledError:
            await self._shutdown()
            raise

        if not line:
            await self._shutdown()
            raise WorkerStartupError(
                "worker_failed", f"worker exited before ready; stderr tail: {list(self.stderr_tail)}"
            )

        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            await self._shutdown()
            raise WorkerStartupError("worker_protocol_error", f"invalid JSON in ready line: {exc}") from None

        if record.get("type") == "error":
            await self._shutdown()
            error_code = record.get("error_code", "worker_failed")
            error_message = record.get("error_message", "unknown worker error")
            raise WorkerStartupError(error_code, error_message)

        try:
            self.ready = ReadyRecord(**record)
        except ValidationError as exc:
            await self._shutdown()
            raise WorkerStartupError("worker_protocol_error", f"malformed ready record: {exc}") from None

        self.startup_ms = (time.perf_counter() - t0) * 1000.0
        return self

    async def predict(self, request: PredictionRequest) -> PredictionResult:
        """Serialize inference; return validated result or explicit operational error."""

        def _err(code: str, msg: str, roundtrip_ms: float | None = None) -> PredictionResult:
            return PredictionResult(
                request_id=request.request_id,
                status="error",
                roundtrip_ms=roundtrip_ms,
                error_code=code,
                error_message=msg,
            )

        if self.failed or self._proc is None or self._proc.stdin is None:
            return _err("worker_failed", "worker is not running (terminated after an earlier failure)")

        async with self._lock:  # spec §2: one outstanding request at a time
            t0 = time.perf_counter()
            try:
                self._proc.stdin.write((request.model_dump_json() + "\n").encode("utf-8"))
                await self._proc.stdin.drain()
                raw = await asyncio.wait_for(self._proc.stdout.readline(), self.config.prediction_timeout_s)
            except asyncio.TimeoutError:
                self.failed = True
                await self._shutdown()  # a hung prediction is terminated and reaped, never abandoned (spec §7)
                return _err(
                    "inference_timeout", f"no result within {self.config.prediction_timeout_s}s; worker terminated"
                )
            except asyncio.CancelledError:
                await self._shutdown()
                raise

            roundtrip_ms = (time.perf_counter() - t0) * 1000.0

            if not raw:
                self.failed = True
                await self._shutdown()
                return _err("worker_failed", f"worker exited during request; stderr tail: {list(self.stderr_tail)}")

            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                self.failed = True
                await self._shutdown()
                return _err("worker_protocol_error", f"invalid JSON in result: {exc}")

            if record.get("type") != "result":
                self.failed = True
                await self._shutdown()
                return _err("worker_protocol_error", f"unexpected result type: {record.get('type')}")

            if record.get("request_id") != request.request_id:
                self.failed = True
                await self._shutdown()
                return _err(
                    "worker_protocol_error",
                    f"request_id mismatch: {record.get('request_id')!r} != {request.request_id!r}",
                )

            self.peak_rss_kb = record.pop("peak_rss_kb", None)
            record.pop("type")

            try:
                result = PredictionResult(**record, roundtrip_ms=roundtrip_ms)
            except ValidationError as exc:
                self.failed = True
                await self._shutdown()
                return _err("worker_protocol_error", f"malformed result: {exc}")

            return validate_answers(request, result)

    async def _drain_stderr(self) -> None:
        """Retain the last 200 decoded stderr lines; log at DEBUG. Runs until EOF."""
        assert self._proc is not None and self._proc.stderr is not None
        async for chunk in self._proc.stderr:
            text = chunk.decode("utf-8", errors="replace").rstrip()
            self.stderr_tail.append(text)
            self.logger.debug("worker stderr: %s", text)

    async def _shutdown(self) -> None:
        """Close stdin, wait 5 s; terminate, wait 5 s; kill and await exit. Idempotent."""
        proc = self._proc
        if proc is None:
            return
        if proc.returncode is None:
            if proc.stdin is not None and not proc.stdin.is_closing():
                proc.stdin.close()
            for signal_step in (None, proc.terminate, proc.kill):
                if signal_step is not None:
                    signal_step()
                try:
                    await asyncio.wait_for(proc.wait(), _GRACE_S)
                    break
                except asyncio.TimeoutError:
                    continue
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            await asyncio.gather(self._stderr_task, return_exceptions=True)
        self._proc = None

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Close input, await exit, then terminate/kill with bounded waits if necessary."""
        await self._shutdown()
