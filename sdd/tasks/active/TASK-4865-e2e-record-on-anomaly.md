# TASK-4865: Anomaly-triggered recorder (`record_on_anomaly`)

**Feature**: FEAT-762 — Operational screencast logs for the E2E browser exploration flow
**Spec**: `sdd/specs/e2e-browser-screencast-logs.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4864
**Assigned-to**: unassigned

## Context

Spec §3 Module 2. Exploration scripts wrap their investigation in
`async with record_on_anomaly(page, out_dir, run_id=...) as rec:`. The context
manager watches the page for the first console `error` message or HTTP ≥ 500
response, starts the TASK-4864 recorder exactly once, and stops it on every exit
path. A clean run produces nothing. Recorder failures are recorded, never raised.

## Scope

- Append `AnomalyRecorder` and `record_on_anomaly` to `parrot/e2e/screencast.py`.
- Append M2 unit tests to `tests/unit/e2e/test_screencast.py`.
- Create the real-Obscura integration test `test_record_on_anomaly_real_obscura`.

**NOT in scope**: changing `start_screencast`/`stop_screencast` semantics (TASK-4864),
agent prose (TASK-4866), CLI/daemon code.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/screencast.py` | MODIFY | Add `AnomalyRecorder`, `record_on_anomaly`. |
| `packages/ai-parrot-server/tests/unit/e2e/test_screencast.py` | MODIFY | Add the three M2 unit tests. |
| `packages/ai-parrot-server/tests/integration/e2e/test_screencast_integration.py` | CREATE | Real Obscura round trip. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# created by TASK-4864 (verify after it merges):
from parrot.e2e.screencast import ScreencastSession, start_screencast, stop_screencast, SCREENCAST_FILENAME
from parrot.e2e.errors import E2EScreencastError
# integration test only:
from parrot.mcp.obscura import ObscuraProcessConfig, ObscuraProcessManager   # packages/ai-parrot-server/src/parrot/mcp/obscura.py:32,66
from playwright.async_api import async_playwright                             # installed in the shared venv; not a server dependency
```

### Existing Signatures to Use

```python
# TASK-4864 (spec §2 Public contract)
async def start_screencast(page: "Page", out_dir: Path, *, max_frames: int = 600) -> ScreencastSession: ...
async def stop_screencast(session: ScreencastSession) -> Path: ...

# Playwright (verified hasattr 2026-10-28)
Page.on(event: str, handler) ; Page.remove_listener(event: str, handler)
ConsoleMessage.type  # "error" for console errors ; Response.status -> int

# packages/ai-parrot-server/src/parrot/mcp/obscura.py
class ObscuraProcessConfig:  # binary_path: str, port: int = 9222, allow_private_network: bool = False, ...
class ObscuraProcessManager:
    async def start(self) -> str: ...   # returns CDP endpoint, raises on failure
    async def stop(self) -> None: ...
```

Obscura 0.2.2 quirk (M0): only the most recently created page can evaluate JS — the
integration test must create the recorded page last.

### Does NOT Exist

- `AnomalyRecorder`, `record_on_anomaly` — this task creates them.
- `real_obscura_driver` reuse — do NOT use it (it turns connection errors into skips).
- `packages/ai-parrot-server/tests/integration/e2e/` — new directory; `tests/unit/e2e/` has no
  `__init__.py`, so do not add one here either.
- Any retrospective capture of events before the anomaly.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/e2e/screencast.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/e2e/test_screencast.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/integration/e2e/test_screencast_integration.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/mcp/obscura.py#ObscuraProcessConfig",
    "sym:packages/ai-parrot-server/src/parrot/mcp/obscura.py#ObscuraProcessManager"
  ]
}
```

## Implementation Notes

- Playwright event handlers are sync callbacks: schedule `start_screencast` as a task guarded by an
  `asyncio.Lock`/flag so concurrent console+response events start capture exactly once.
- `__aexit__`: remove both listeners first, await a pending start task, then `stop_screencast` if a
  session exists. Catch `E2EScreencastError` (and log unexpected exceptions, wrapping them) into
  `.error`; return `False` so the body's exception propagates unchanged; handle
  `asyncio.CancelledError` in the body the same way (stop, then let it propagate).
- `run_id` is used only for logging/labelling; the caller passes `out_dir`.

## Implementation Blueprint

### Steps (in order)

1. Append the class/function below to `screencast.py` — after `stop_screencast` because it uses it.
2. Add the M2 unit tests reusing TASK-4864's fakes (`FakePage` gains `on`/`remove_listener`/`emit`).
3. Write the integration test from the M0 prototype bootstrap.
4. `ruff check --fix`; run Validation Commands (integration with a real `obscura` on PATH).

### `packages/ai-parrot-server/src/parrot/e2e/screencast.py` (MODIFY)

```python
# AFTER — append at end of file, below `async def stop_screencast(` (created by TASK-4864)
# occurrences: 1 (verify: grep -c 'async def stop_screencast(' screencast.py)


class AnomalyRecorder:
    """Async context manager starting capture at the first console error / HTTP 5xx."""

    def __init__(self, page: "Page", out_dir: Path, *, run_id: str, max_frames: int = 600) -> None:
        """Bind to the caller's page; nothing is recorded until an anomaly occurs."""
        self.page = page
        self.out_dir = out_dir
        self.run_id = run_id
        self.max_frames = max_frames
        self.triggered: bool = False
        self.path: Optional[Path] = None
        self.error: Optional[E2EScreencastError] = None
        self._session: Optional[ScreencastSession] = None
        self._start_task: Optional[asyncio.Task] = None

    def _on_console(self, message: Any) -> None:
        """Trigger on console messages of type ``error``."""
        # FILL IN: if message.type == "error": self._trigger("console error")

    def _on_response(self, response: Any) -> None:
        """Trigger on HTTP responses with status >= 500."""
        # FILL IN

    def _trigger(self, reason: str) -> None:
        """Schedule start_screencast exactly once."""
        # FILL IN: guard with self.triggered; create task; store failure in self.error (never raise)

    async def __aenter__(self) -> "AnomalyRecorder":
        """Register page listeners."""
        # FILL IN

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        """Remove listeners, stop capture on every exit path, never mask the body's exception."""
        # FILL IN: see Implementation Notes; return False


def record_on_anomaly(page: "Page", out_dir: Path, *, run_id: str, max_frames: int = 600) -> AnomalyRecorder:
    """Return an :class:`AnomalyRecorder` for ``async with`` use (spec §2 Public contract)."""
    return AnomalyRecorder(page, out_dir, run_id=run_id, max_frames=max_frames)
```

**Why**: signatures are fixed by spec §2; a plain class (not `@asynccontextmanager`) exposes
`triggered`/`path`/`error` after exit, which the agent protocol (TASK-4866) reads.

### `packages/ai-parrot-server/tests/integration/e2e/test_screencast_integration.py` (CREATE)

```python
"""Real-Obscura integration test for record_on_anomaly (FEAT-762 M2)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from parrot.e2e.screencast import record_on_anomaly


async def test_record_on_anomaly_real_obscura(unused_tcp_port: int, tmp_path: Path) -> None:
    """Anomaly page yields a playable WebM showing the post-trigger change; clean page yields none."""
    binary = os.environ.get("OBSCURA_BINARY") or shutil.which("obscura")
    if not binary:
        pytest.skip("No Obscura binary configured (set OBSCURA_BINARY or install 'obscura').")
    pytest.importorskip("playwright.async_api")
    pytest.importorskip("av")
    # FILL IN: ObscuraProcessManager(allow_private_network=False is fine for data:/about pages) start in try/finally stop
    # FILL IN: clean page inside record_on_anomaly -> rec.triggered is False and rec.path is None
    # FILL IN: anomaly page (created last): console.error(...) then change background white->red;
    #   assert rec.path exists, decode with av: last sample red; page still open and connected after exit
```

**Why**: skips only on a missing binary or missing optional packages (environment prerequisites);
connection/capture/encode failures must fail.

### FILL IN checklist

- [ ] Listener handlers, once-only trigger, `__aenter__`/`__aexit__`.
- [ ] Unit tests: `test_record_on_anomaly_clean_run_creates_nothing`,
      `test_record_on_anomaly_starts_once_on_first_anomaly`,
      `test_record_on_anomaly_stops_on_exception_and_cancel`.
- [ ] Real integration test body.

## Acceptance Criteria

- [ ] AC-1: zero anomalies ⇒ no CDPSession, no file, `path is None`.
- [ ] AC-2: first console error or 5xx starts capture exactly once, even with concurrent events.
- [ ] AC-3: capture is stopped on normal exit, exception and cancellation; the body's exception propagates unchanged; recorder errors land in `.error`.
- [ ] AC-4: real Obscura run produces a decodable WebM showing the post-trigger change; page/browser intact.
- [ ] AC-5: `ruff check` clean on the three files.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_screencast.py -q`
- `pytest packages/ai-parrot-server/tests/integration/e2e/test_screencast_integration.py::test_record_on_anomaly_real_obscura -q -rs`

## Test Specification

Unit: extend `FakePage` with `on`/`remove_listener` and helpers to emit console/response events;
patch `screencast.start_screencast`/`stop_screencast` to fakes counting calls. Integration: run with
the real `obscura` on PATH; a skip is not acceptance evidence.

## Agent Instructions

1. Wait for TASK-4864 to be merged; verify its symbols before coding.
2. Modify only the three listed files.
3. Run with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src`.
4. Commit code only.

## Completion Note

Owned by the finalization tool after verified acceptance.
