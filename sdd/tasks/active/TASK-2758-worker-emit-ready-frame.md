# TASK-2758: Worker — emit the `ReadyResponse` frame after bootstrap

**Feature**: FEAT-500 — REPL Worker Readiness Handshake & Non-Lethal Namespace Timeouts
**Spec**: `sdd/specs/bug-workerpool-repl.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2757
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. Today `worker.serve()` builds `WorkerNamespace` (the
heavy `parrot` + pandas import and REPL bootstrap), logs
`repl_worker: ready` and silently enters the read loop
(`worker.py:274-278`). The host has no way to know when that point is
reached — the root of the cold-start spiral (spec §1). This task makes the
worker *say* it is ready by writing one `ReadyResponse` frame on the
control pipe before reading its first request.

---

## Scope

- In `main()`, record `t0 = time.monotonic()` as the first statement and
  pass it into `serve()` (new keyword `started_at: float | None = None`).
- In `serve()`, immediately after `namespace = WorkerNamespace(...)` and
  **before** the `while True` loop, `write_frame(out_stream,
  ReadyResponse(pid=os.getpid(), bootstrap_ms=int((time.monotonic() - started_at) * 1000)))`
  (use `0` if `started_at` is `None`, e.g. tests calling `serve()` directly).
- Extend the existing `logger.info("repl_worker: ready ...")` line with
  `bootstrap_ms`.
- If `WorkerNamespace(...)` raises, let the exception propagate as today
  (the process exits non-zero; the host's bootstrap path in TASK-2759
  reports it via EOF). Do **not** swallow it.
- Tests in `tests/repl_worker/test_worker.py` using the existing
  `SpawnedWorker` harness: the first frame read from a freshly spawned
  worker is a `ReadyResponse` with `pid == proc.pid`, `bootstrap_ms >= 0`;
  a following `PingRequest` still gets a `PongResponse` (loop unaffected).

**NOT in scope**: host-side reading of the frame (TASK-2759), pool
changes (TASK-2760).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py` | MODIFY | `serve()` writes `ReadyResponse`; `main()` measures bootstrap |
| `packages/ai-parrot/tests/repl_worker/test_worker.py` | MODIFY | first-frame-is-ready test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# worker.py:32-53 already imports from .protocol — add ReadyResponse to that block (created by TASK-2757)
from .protocol import ReadyResponse, write_frame, read_frame, WorkerConfig, PingRequest, PongResponse
import os, sys, time, logging                     # os/sys/logging already imported (worker.py:25-30); add `time`
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/repl_worker/worker.py
class WorkerNamespace:                                                 # :121
    def __init__(self, output_dir=None, sanitize_input_enabled=True, repl_kwargs=None)   # :138-157  (imports PythonREPLTool, builds it → the bootstrap)
def _dispatch(namespace, message) -> Any                               # :205-247
def serve(config, in_stream, out_stream, output_dir=None, repl_kwargs=None) -> None   # :250-287
    namespace = WorkerNamespace(output_dir=output_dir, repl_kwargs=repl_kwargs)        # :274
    logger.info("repl_worker: ready (max_workers config=%s), entering service loop", config.max_workers)   # :275
    while True: message = read_frame(in_stream) ... write_frame(out_stream, response)  # :276-287
def main(argv=None) -> None                                            # :290-337
    logging.basicConfig(level=logging.INFO)                            # :317
    config = WorkerConfig.model_validate_json(argv[0]); read_fd = int(argv[1]); write_fd = int(argv[2])   # :326-328
    set_parent_death_signal(); apply_rlimits(config)                   # :332-333
    in_stream = os.fdopen(read_fd, "rb", buffering=0); out_stream = os.fdopen(write_fd, "wb", buffering=0)   # :335-336
    serve(config, in_stream, out_stream, output_dir=output_dir, repl_kwargs=repl_kwargs)   # :337

# packages/ai-parrot/tests/repl_worker/test_worker.py
class SpawnedWorker            # :81   real subprocess + dedicated pipes (read_frame/write_frame over os.pipe())
def _spawn_worker(config: WorkerConfig, output_dir: str) -> SpawnedWorker   # :129
class TestWorkerSubprocess     # :224  — add the new test here; look at how existing tests send a request and read the reply
fixture real_worker_config     # :59-79 (uses the default ~12 GiB RLIMIT_AS so numpy imports)
```

### Does NOT Exist
- ~~a `ready` log/frame today~~ — only the `logger.info` at `worker.py:275`; no frame is written before the loop.
- ~~`serve(..., started_at=...)`~~ — you are adding this keyword.
- ~~`WorkerNamespace.ready()`~~ — no such method; readiness is simply "constructor returned".
- ~~stdin/stdout framing~~ — the control channel is the dedicated fd pair (`worker.py:299-308`); never write the frame to `sys.stdout`.

---

## Implementation Notes

### Pattern to Follow
```python
# worker.py:274-287 (current) — insert the ready frame between namespace construction and the loop
namespace = WorkerNamespace(output_dir=output_dir, repl_kwargs=repl_kwargs)
bootstrap_ms = int((time.monotonic() - started_at) * 1000) if started_at is not None else 0
write_frame(out_stream, ReadyResponse(pid=os.getpid(), bootstrap_ms=bootstrap_ms))
logger.info("repl_worker: ready in %d ms (max_workers config=%s), entering service loop", bootstrap_ms, config.max_workers)
while True:
    ...
```

### Key Constraints
- The ready frame MUST be the very first frame the worker writes — TASK-2759's host reader treats any other first frame as a bootstrap failure.
- `write_frame` flushes (`protocol.py:391-405`); `out_stream` is unbuffered (`buffering=0`) — no extra flush needed.
- Existing tests that call `serve()` directly with in-memory streams (if any in `test_worker.py`) must keep passing: they will now see a `ReadyResponse` first — update them to consume it.

### References in Codebase
- `worker.py:250-337` — serve/main
- `test_worker.py:81-135` — `SpawnedWorker` harness

---

## Acceptance Criteria

- [ ] First frame read from a spawned worker is `ReadyResponse` with `pid == worker pid` and `bootstrap_ms >= 0`
- [ ] A `PingRequest` sent after consuming the ready frame yields `PongResponse` (loop unchanged)
- [ ] `pytest packages/ai-parrot/tests/repl_worker/test_worker.py -v` passes; `ruff check` clean
- [ ] Spec AC1 worker half: readiness is signalled only after `WorkerNamespace` is fully constructed

---

## Test Specification

```python
# packages/ai-parrot/tests/repl_worker/test_worker.py (addition inside TestWorkerSubprocess)
from parrot.tools.repl_worker.protocol import PingRequest, PongResponse, ReadyResponse

def test_worker_first_frame_is_ready(self, real_worker_config, tmp_path):
    worker = _spawn_worker(real_worker_config, str(tmp_path))
    try:
        first = worker.read()            # whatever SpawnedWorker's read helper is named — check :81-128
        assert isinstance(first, ReadyResponse)
        assert first.pid == worker.proc.pid
        assert first.bootstrap_ms >= 0
        worker.send(PingRequest())
        assert isinstance(worker.read(), PongResponse)
    finally:
        worker.close()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2757 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm line numbers and the `SpawnedWorker` helper's method names before editing
4. **Update status** in `sdd/tasks/index/bug-workerpool-repl.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2758-worker-emit-ready-frame.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
