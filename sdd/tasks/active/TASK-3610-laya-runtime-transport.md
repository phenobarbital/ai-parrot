# TASK-3610: `LayaWorker` — async subprocess owner with deadlines, shutdown and stderr drain

**Feature**: FEAT-589 — Evaluate Laya for typed classification and agent model routing
**Spec**: `sdd/specs/laya-adoption.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3605, TASK-3606, TASK-3608
**Assigned-to**: unassigned

---

## Context

Implements the host half of spec §3 **Module 2**: `LayaWorker` owns exactly one persistent
`worker.py` child (spawned with the isolated `worker_python`), awaits a validated `ready`
record within `startup_timeout_s`, serializes one prediction at a time with a
`prediction_timeout_s` deadline, drains stderr concurrently with bounded retention, and shuts
the child down gracefully (5 s), then terminate (5 s), then kill. No inference ever runs on the
host event loop (spec §2). A timed-out prediction terminates and reaps the worker rather than
queuing behind a hung call (spec §3 M2); the runner marks the rest incomplete.

Tests use a **fake child script** written to `tmp_path` and pointed at via
`EvaluationConfig.worker_module` + `PYTHONPATH`, so no Laya is needed.

---

## Scope

- Create `artifacts/laya/runtime.py` with `LayaWorker` (`__init__`, `__aenter__`, `predict`,
  `__aexit__`), `ReadyRecord` (Pydantic, `extra="allow"` for forward-compatible package fields),
  and `WorkerStartupError`.
- Write `packages/ai-parrot/tests/unit/laya_eval/test_laya_runtime.py` with a fake protocol
  child covering ready/ok, startup timeout, inference timeout, stderr noise, mismatched
  request id, cancellation and reaping.

**NOT in scope**: scenario logic (TASK-3614); the CLI (TASK-3616); RSS *interpretation* in reports (TASK-3612).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/laya/runtime.py` | CREATE | `LayaWorker` async subprocess owner + `ReadyRecord` |
| `packages/ai-parrot/tests/unit/laya_eval/test_laya_runtime.py` | CREATE | Fake-child protocol/deadline/cancellation tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `1a7ccd5a1` on 2026-09-21. `models.py` (TASK-3605/3606) and `worker.py` (TASK-3608) are fixed by their blueprints.

### Verified Imports
```python
import asyncio, json, logging, os, sys, time
from collections import deque
from pydantic import BaseModel, ConfigDict, ValidationError
from artifacts.laya.models import ERROR_CODES, EvaluationConfig, PredictionRequest, PredictionResult, validate_answers  # TASK-3605/3606
```

### Existing Signatures to Use
```python
# artifacts/laya/models.py
class EvaluationConfig:   # worker_python: Path; checkpoint_path: Path; checkpoint_revision: str; startup_timeout_s: float;
                          # prediction_timeout_s: float; worker_module: str = "artifacts.laya.worker"
def validate_answers(request: PredictionRequest, result: PredictionResult) -> PredictionResult
# Child invocation this task fixes (worker.py argparse, TASK-3608):
#   [str(config.worker_python), "-m", config.worker_module, "--checkpoint", str(config.checkpoint_path), "--revision", config.checkpoint_revision]
#   cwd = repository root (so `-m artifacts.laya.worker` resolves); env = os.environ + {"PYTHONUNBUFFERED": "1"}
# First stdout line: {"type":"ready",...} or {"type":"error","error_code":...,"error_message":...}
# Per request: {"type":"result","request_id":...,"status":...,"answers":...,"inference_ms":...,"error_code":...,"error_message":...,"peak_rss_kb":...}
```

### Does NOT Exist
- ~~`asyncio.create_subprocess_exec(..., text=True)`~~ — asyncio subprocess streams are bytes; decode UTF-8 yourself.
- ~~a request queue / concurrent predictions~~ — spec §2: one outstanding request; guard with an `asyncio.Lock`.
- ~~`PredictionResult.peak_rss_kb`~~ — RSS is kept on the worker object (`self.peak_rss_kb`, last seen) and `self.ready`; the result model has no such field.
- ~~automatic restart after a timeout~~ — the worker is terminated and the caller marks remaining inference incomplete (spec §3 M2).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "artifacts/laya/runtime.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/laya_eval/test_laya_runtime.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- `__init__` stores config only — no process, no I/O (spec §3 M2 skeleton docstring).
- `predict()` returns `PredictionResult` **always**: operational failures become
  `status="error"` with `inference_timeout` / `worker_protocol_error` / `worker_failed`;
  `roundtrip_ms` is measured on the host around write→read.
- After `inference_timeout`, `self.failed = True`; further `predict()` calls return
  `worker_failed` immediately ("worker terminated after timeout") without touching the process.
- Cancellation (`asyncio.CancelledError`) during startup or predict: shut the child down (same
  5 s / 5 s ladder) **then re-raise** (spec §2 "Propagate cancellation after shutting down the child").
- Stderr drain: background task appending decoded lines to `deque(maxlen=200)`; exposed as
  `self.stderr_tail`. Never awaited inline with a prediction.
- Logging via `self.logger = logging.getLogger(__name__)`; no `print`.

---

## Implementation Blueprint

### Steps (in order)
1. Write `ReadyRecord` and `WorkerStartupError` — *why*: the ready line is validated before anything else is trusted.
2. Write `LayaWorker` lifecycle (`__aenter__`/`_shutdown`/`__aexit__`) — *why*: the ladder must exist before `predict` can rely on it after a timeout.
3. Write `predict()` — *why*: it is the only hot path; keep it small and wrap every await in the deadline.
4. Write the fake child script in the test module and the seven scenarios — *why*: spec §4 "Worker protocol/deadlines" enumerates them.
5. `git add -f` both files.

### `artifacts/laya/runtime.py` (CREATE — models and lifecycle)
```python
"""Host-side owner of one isolated Laya inference subprocess (spec §3 Module 2)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
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
        return [str(c.worker_python), "-m", c.worker_module, "--checkpoint", str(c.checkpoint_path), "--revision", c.checkpoint_revision]

    async def __aenter__(self) -> "LayaWorker":
        """Start the worker and await a validated ready record within the startup deadline."""
        t0 = time.perf_counter()
        self._proc = await asyncio.create_subprocess_exec(
            *self._argv(), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(_REPO_ROOT), env={**os.environ, "PYTHONUNBUFFERED": "1"})
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        try:
            line = await asyncio.wait_for(self._proc.stdout.readline(), self.config.startup_timeout_s)
        except asyncio.TimeoutError:
            await self._shutdown()
            raise WorkerStartupError("startup_timeout", f"no ready record within {self.config.startup_timeout_s}s") from None
        except asyncio.CancelledError:
            await self._shutdown()
            raise
        # FILL IN: empty line -> worker exited: WorkerStartupError("worker_failed", stderr tail); parse JSON;
        #          {"type":"error"} -> WorkerStartupError(record["error_code"], record["error_message"]) (shutdown first);
        #          ReadyRecord(**record) (ValidationError -> "worker_protocol_error") — bounded by spec §3 M2 "Reject malformed/mismatched records"
        self.startup_ms = (time.perf_counter() - t0) * 1000.0
        return self
```
**Why this shape**: the child is spawned with `cwd=_REPO_ROOT` so `-m artifacts.laya.worker`
resolves without installing anything, and `worker_module` stays swappable for the mocked e2e test.

### `artifacts/laya/runtime.py` (CREATE — continued: predict, drain, shutdown)
```python
    async def predict(self, request: PredictionRequest) -> PredictionResult:
        """Serialize inference; return validated result or explicit operational error."""
        def _err(code: str, msg: str, roundtrip_ms: float | None = None) -> PredictionResult:
            return PredictionResult(request_id=request.request_id, status="error", roundtrip_ms=roundtrip_ms,
                                    error_code=code, error_message=msg)
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
                return _err("inference_timeout", f"no result within {self.config.prediction_timeout_s}s; worker terminated")
            except asyncio.CancelledError:
                await self._shutdown()
                raise
            roundtrip_ms = (time.perf_counter() - t0) * 1000.0
            # FILL IN: empty raw -> failed=True + worker_failed(stderr tail); json.loads (JSONDecodeError -> worker_protocol_error);
            #          record.get("type") != "result" or record["request_id"] != request.request_id -> worker_protocol_error;
            #          self.peak_rss_kb = record.pop("peak_rss_kb", None); record.pop("type");
            #          result = PredictionResult(**record, roundtrip_ms=roundtrip_ms) (ValidationError -> worker_protocol_error);
            #          return validate_answers(request, result) — bounded by spec §3 M2 "Each response echoes the request ID"
            raise NotImplementedError

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
```
**Why**: the ladder is exactly spec §3 M2's "five-second graceful shutdown then terminate and, after a
further five seconds, kill and await exit". `_shutdown` is idempotent so timeout, cancellation and
`__aexit__` can all call it.

### `packages/ai-parrot/tests/unit/laya_eval/test_laya_runtime.py` (CREATE)
```python
"""FEAT-589 M2 — LayaWorker against a fake protocol child (spec §4 'Worker protocol/deadlines')."""
from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from pathlib import Path

import pytest

from artifacts.laya.models import EvaluationConfig, PredictionRequest
from artifacts.laya.runtime import LayaWorker, WorkerStartupError

# Fake child: behaviour is selected by --revision (startup-delay / hang / noisy / bad-id / ok).
FAKE_CHILD = textwrap.dedent('''
    import json, sys, time, os
    args = sys.argv; rev = args[args.index("--revision") + 1]
    if rev == "startup-delay": time.sleep(30)
    print("loading noise on stdout", file=sys.stderr)
    sys.stdout.write(json.dumps({"type": "ready", "worker_pid": os.getpid(), "device": "cpu", "checkpoint_path": "x",
        "checkpoint_revision": rev, "packages": {}, "load_ms": 1.0, "python": "3", "platform": "fake"}) + "\\n"); sys.stdout.flush()
    for line in sys.stdin:
        req = json.loads(line)
        if rev == "hang": time.sleep(30)
        rid = "WRONG" if rev == "bad-id" else req["request_id"]
        if rev == "noisy": print("garbage on stderr", file=sys.stderr)
        answers = {q: {"type": "noul", "noul": 0.1, "confidence": 0.9} for q in req["questions"]}
        sys.stdout.write(json.dumps({"type": "result", "request_id": rid, "status": "ok", "answers": answers,
            "inference_ms": 2.0, "error_code": None, "error_message": None, "peak_rss_kb": 1234}) + "\\n"); sys.stdout.flush()
''')


@pytest.fixture
def fake_module(tmp_path, monkeypatch) -> str:
    (tmp_path / "fake_laya_child.py").write_text(FAKE_CHILD, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    return "fake_laya_child"


def _cfg(module: str, revision: str, tmp_path: Path, **kw) -> EvaluationConfig:
    return EvaluationConfig(worker_python=Path(sys.executable), checkpoint_path=tmp_path, checkpoint_revision=revision,
                            output_dir=tmp_path / "out", worker_module=module, startup_timeout_s=kw.pop("startup", 20.0),
                            prediction_timeout_s=kw.pop("predict", 5.0), **kw)


def _req(rid: str = "r1") -> PredictionRequest:
    return PredictionRequest(request_id=rid, state="hello", questions={"injection": {"type": "noul", "text": "q"}})


async def test_ready_ok_roundtrip_and_rss(fake_module, tmp_path):
    async with LayaWorker(_cfg(fake_module, "ok", tmp_path)) as w:
        assert w.ready is not None and w.ready.device == "cpu" and w.startup_ms is not None
        res = await w.predict(_req())
        assert res.status == "ok" and res.roundtrip_ms is not None and res.inference_ms == 2.0 and w.peak_rss_kb == 1234


async def test_startup_timeout_terminates_child(fake_module, tmp_path):
    with pytest.raises(WorkerStartupError) as ei:
        async with LayaWorker(_cfg(fake_module, "startup-delay", tmp_path, startup=1.0)):
            pass
    assert ei.value.error_code == "startup_timeout"


async def test_inference_timeout_marks_failed_and_reaps(fake_module, tmp_path):
    async with LayaWorker(_cfg(fake_module, "hang", tmp_path, predict=1.0)) as w:
        res = await w.predict(_req())
        assert res.status == "error" and res.error_code == "inference_timeout" and w.failed
        again = await w.predict(_req("r2"))
        assert again.error_code == "worker_failed"
        assert w._proc is None  # reaped, not abandoned


async def test_stderr_noise_is_retained_not_mixed_into_protocol(fake_module, tmp_path):
    async with LayaWorker(_cfg(fake_module, "noisy", tmp_path)) as w:
        assert (await w.predict(_req())).status == "ok"
        await asyncio.sleep(0.2)
        assert any("garbage" in line for line in w.stderr_tail)


async def test_mismatched_request_id_is_protocol_error(fake_module, tmp_path):
    async with LayaWorker(_cfg(fake_module, "bad-id", tmp_path)) as w:
        assert (await w.predict(_req())).error_code == "worker_protocol_error"


async def test_cancellation_shuts_child_down_then_propagates(fake_module, tmp_path):
    # FILL IN: start worker with revision "hang", create_task(predict), cancel after 0.2s; assert CancelledError propagates
    #          and w._proc is None afterwards — bounded by spec §2 "Propagate cancellation after shutting down the child"
    raise NotImplementedError


async def test_missing_worker_module_is_worker_failed_startup(tmp_path):
    # FILL IN: worker_module="no_such_module_xyz" -> WorkerStartupError with error_code "worker_failed" (child exits before ready)
    raise NotImplementedError
```
**Why**: this is spec §4 "Worker protocol/deadlines" verbatim: "Fake child exercises startup/inference
timeout, stderr noise, malformed IDs, cancellation and reaping".

### FILL IN checklist
- [ ] `runtime.py::__aenter__` ready-line parsing → `ReadyRecord` / `WorkerStartupError` variants
- [ ] `runtime.py::predict` result parsing → id echo check, RSS capture, `validate_answers`
- [ ] `test_laya_runtime.py` cancellation + missing-module tests

---

## Acceptance Criteria

- [ ] AC-1 — All five protocol/deadline behaviours above pass against the fake child within the test timeouts.
- [ ] AC-2 — After an inference timeout the child is gone (`_proc is None`) and later calls return `worker_failed` without hanging.
- [ ] AC-3 — Cancellation during a pending prediction shuts the child down and re-raises `CancelledError`.
- [ ] AC-4 — `predict()` never raises for worker misbehaviour; every returned `error_code` ∈ `ERROR_CODES`.
- [ ] `ruff check artifacts/laya/runtime.py` clean (ASYNC rules included — no blocking calls).

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_runtime.py -q`

---

## Test Specification

See the CREATE block above. Wrap the whole file in a 60 s per-test budget
(`pytestmark = pytest.mark.timeout(60)` only if `pytest-timeout` is installed — check with
`python -c "import pytest_timeout"`; otherwise rely on the config deadlines).

---

## Agent Instructions

1. Read spec §2 "Overview" and §3 Module 2 (lifecycle paragraph), §7 "A process timeout must terminate inference".
2. Confirm TASK-3605, TASK-3606 and TASK-3608 are completed.
3. Implement from the Blueprint; run the Validation Command; watch for leaked child processes (`ps` after the run).
4. `git add -f` both files, commit, move this file, update the index, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
