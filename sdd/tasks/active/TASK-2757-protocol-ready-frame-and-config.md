# TASK-2757: Protocol — `ReadyResponse` frame + `WorkerConfig` timeout fields

**Feature**: FEAT-500 — REPL Worker Readiness Handshake & Non-Lethal Namespace Timeouts
**Spec**: `sdd/specs/bug-workerpool-repl.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. The worker ↔ host control protocol has no readiness
frame and `WorkerConfig` has no timeout field besides `deadline_ms`
(spec §6 "Does NOT Exist"). This task adds the frozen-protocol pieces the
rest of the feature builds on: a `ReadyResponse` message the worker will
emit once bootstrapped (TASK-2758), and two config knobs the handle will
honour (TASK-2759). Nothing behavioural changes yet.

---

## Scope

- Add `class ReadyResponse(BaseModel)` to `protocol.py` with
  `op: Literal["ready"] = "ready"`, `pid: int`, `bootstrap_ms: int` (`ge=0`).
- Register it in `_MESSAGE_TYPES` under the key `"ready"`.
- Add to `WorkerConfig`: `bootstrap_timeout_ms: int = 30_000` and
  `namespace_timeout_ms: int = 30_000`, both validated `> 0` (Pydantic
  `Field(gt=0)`); document each field in the class docstring.
- Export `ReadyResponse` from `parrot/tools/repl_worker/__init__.py`
  (import + `__all__`). Also add the names `NamespaceTimeoutError` and
  `WorkerBootstrapError` to `__all__` **only if** you also define them
  here — otherwise leave that export to TASK-2759 (which defines them in
  `handle.py`). Preferred: leave to TASK-2759.
- Tests in `tests/repl_worker/test_protocol.py`.

**NOT in scope**: emitting the frame (TASK-2758), reading it (TASK-2759),
any change to `handle.py`/`pool.py`/`worker.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py` | MODIFY | `ReadyResponse`, `_MESSAGE_TYPES["ready"]`, two `WorkerConfig` fields |
| `packages/ai-parrot/src/parrot/tools/repl_worker/__init__.py` | MODIFY | export `ReadyResponse` |
| `packages/ai-parrot/tests/repl_worker/test_protocol.py` | MODIFY | round-trip + config validation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.repl_worker.protocol import (   # protocol.py; re-exported by repl_worker/__init__.py:16-38, __all__ :40-65
    PingRequest, PongResponse, ErrorResponse, WorkerConfig, read_frame, write_frame,
)
from pydantic import BaseModel, Field            # already imported in protocol.py (NamespaceLossError uses Field :313-323)
from typing import Literal                       # already imported in protocol.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py
_LENGTH_STRUCT = struct.Struct(">I")                                  # :32
class PingRequest(BaseModel):  op: Literal["ping"] = "ping"          # :250-253   ← copy this shape
class PongResponse(BaseModel): op: Literal["pong"] = "pong"          # :300-303
class ErrorResponse(BaseModel): op: Literal["error"] = "error"; message: str   # :306-309
class WorkerConfig(BaseModel):                                        # :326-341
    rlimit_as_bytes: int = 12 * 1024**3; rlimit_cpu_seconds: int = 300; rlimit_nofile: int = 256
    deadline_ms: int = 60_000; max_workers: int = 0; idle_ttl_seconds: int = 1800; prewarm_pool_size: int = 2
_MESSAGE_TYPES: dict[str, type[BaseModel]] = {"exec": ExecRequest, ..., "pong": PongResponse, "error": ErrorResponse}   # :346-362
def write_frame(stream: BinaryIO, message: BaseModel) -> None         # :391-405  (model_dump_json + 4-byte BE length)
def read_frame(stream: BinaryIO) -> BaseModel                         # :408-429  dispatches on raw["op"] via _MESSAGE_TYPES; ValueError on unknown op

# packages/ai-parrot/tests/repl_worker/test_protocol.py
def test_protocol_roundtrip(message)                                  # :57  parametrized over message instances — add ReadyResponse(pid=1, bootstrap_ms=10)
```

### Does NOT Exist
- ~~`ReadyRequest`~~ — there is no request side; readiness is worker → host only.
- ~~`WorkerConfig.bootstrap_timeout_ms` / `namespace_timeout_ms`~~ — you are creating them; nothing reads them yet.
- ~~`NamespaceTimeoutError` / `WorkerBootstrapError`~~ — created in TASK-2759 (`handle.py`), not here.
- ~~`tests/repl_worker/conftest.py`~~ — no conftest; fixtures live in each test module.

---

## Implementation Notes

### Pattern to Follow
```python
# protocol.py:250-253 — every message is a Pydantic model with a Literal `op` discriminator
class PingRequest(BaseModel):
    """Health check (host -> worker)."""
    op: Literal["ping"] = "ping"
```

### Key Constraints
- Keep the frame format untouched (4-byte BE length + JSON); only add a model + registry entry.
- `WorkerConfig.model_dump_json()` is passed on the worker's argv (`handle.py:164`) and re-parsed with
  `WorkerConfig.model_validate_json` (`worker.py:326`) — new fields with defaults are automatically compatible.
- Google-style docstrings; the field docstrings must state the lethal/non-lethal semantics (bootstrap expiry kills, namespace expiry does not).

### References in Codebase
- `protocol.py:189-309` — all message models (shape to copy)
- `test_protocol.py:57-95` — round-trip / framing tests

---

## Acceptance Criteria

- [ ] `ReadyResponse(pid=…, bootstrap_ms=…)` round-trips through `write_frame`/`read_frame` and `read_frame` returns an instance of `ReadyResponse`
- [ ] `WorkerConfig()` defaults: `bootstrap_timeout_ms == 30_000`, `namespace_timeout_ms == 30_000`; `WorkerConfig(bootstrap_timeout_ms=0)` and `namespace_timeout_ms=-1` raise `ValidationError`
- [ ] `from parrot.tools.repl_worker import ReadyResponse` works
- [ ] `pytest packages/ai-parrot/tests/repl_worker/test_protocol.py -v` passes; `ruff check` clean on changed files
- [ ] Spec AC6 (config fields exist, defaults, validation) satisfied for the config half

---

## Test Specification

```python
# packages/ai-parrot/tests/repl_worker/test_protocol.py (additions)
import io
import pytest
from pydantic import ValidationError
from parrot.tools.repl_worker.protocol import ReadyResponse, WorkerConfig, read_frame, write_frame

def test_ready_response_roundtrip():
    buf = io.BytesIO()
    write_frame(buf, ReadyResponse(pid=4242, bootstrap_ms=1234))
    buf.seek(0)
    msg = read_frame(buf)
    assert isinstance(msg, ReadyResponse)
    assert (msg.pid, msg.bootstrap_ms) == (4242, 1234)

def test_worker_config_new_fields_defaults_and_validation():
    cfg = WorkerConfig()
    assert cfg.bootstrap_timeout_ms == 30_000 and cfg.namespace_timeout_ms == 30_000
    with pytest.raises(ValidationError):
        WorkerConfig(bootstrap_timeout_ms=0)
    with pytest.raises(ValidationError):
        WorkerConfig(namespace_timeout_ms=-1)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm the line numbers above still match before editing
4. **Update status** in `sdd/tasks/index/bug-workerpool-repl.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2757-protocol-ready-frame-and-config.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
