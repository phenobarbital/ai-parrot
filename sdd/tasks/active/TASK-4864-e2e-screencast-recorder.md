# TASK-4864: In-connection screencast recorder (`parrot.e2e.screencast`)

**Feature**: FEAT-762 — Operational screencast logs for the E2E browser exploration flow
**Spec**: `sdd/specs/e2e-browser-screencast-logs.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-6h)
**Depends-on**: none (M0 / TASK-4842 evidence already frozen in the spec)
**Assigned-to**: unassigned

## Context

Spec §3 Module 1. M0 proved (on Obscura 0.2.2) that a page can only be
recorded through a `CDPSession` opened on the **same** Playwright connection
that owns the page; a separate connection sees no targets. This task turns the
spike's test-local prototype (`TestObscuraScreencastRecording` in
`packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py`)
into the production recorder: `ScreencastSession`, `start_screencast`,
`stop_screencast`, plus the typed `E2EScreencastError`.

## Scope

- Add `E2EScreencastError(E2EError)` to `parrot/e2e/errors.py`.
- Create `parrot/e2e/screencast.py` with `ScreencastSession`, `start_screencast`,
  `stop_screencast` and two module-level, picklable helpers `_encode_webm` /
  `_validate_webm` run in a `ProcessPoolExecutor`.
- Unit tests with fake Playwright objects (no browser, no real encoder unless
  `av` is importable — see Test Specification).

**NOT in scope**: `record_on_anomaly` / `AnomalyRecorder` (TASK-4865), the
agent prose (TASK-4866), any change to `cli.py`, `targets/`, `__init__.py`
re-exports, `pyproject.toml` (the `screencast` extra already exists).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/errors.py` | MODIFY | Append `E2EScreencastError`. |
| `packages/ai-parrot-server/src/parrot/e2e/screencast.py` | CREATE | Recorder session + start/stop + encoder helpers. |
| `packages/ai-parrot-server/tests/unit/e2e/test_screencast.py` | CREATE | M1 unit tests (spec §4 rows marked M1). |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.e2e.errors import E2EError, EXIT_FAILURE   # errors.py:42,51 (verified)
from playwright.async_api import Page, CDPSession       # TYPE_CHECKING only — playwright is NOT a dependency of ai-parrot-server
# lazily, inside the worker functions only (optional extra ai-parrot-server[screencast]):
import av                                               # PyAV 13.x (root override av>=13,<14; extra declared)
from PIL import Image                                   # pillow>=13
```

### Existing Signatures to Use

```python
# packages/ai-parrot-server/src/parrot/e2e/errors.py:51
class E2EError(Exception):
    exit_code: int = EXIT_FAILURE
    def __init__(self, message: str, *, reason_code: Optional[str] = None) -> None: ...

# packages/ai-parrot-server/src/parrot/e2e/errors.py:117 — last class in the file (126 lines)
class E2EEvidenceError(E2EError): ...

# Playwright (installed in the shared venv; verified by hasattr probe 2026-10-28)
BrowserContext.new_cdp_session(self, page: Page | Frame) -> CDPSession   # async
CDPSession.send(method: str, params: dict | None = None) -> dict          # async
CDPSession.on(event: str, handler) / CDPSession.detach()                  # detach is async
Page.is_closed() -> bool ; Page.context -> BrowserContext
```

CDP behaviour on Obscura 0.2.2 (spec §6 Backend Contract Gate, frozen by M0):
`Page.startScreencast {"format": "jpeg", "quality": int, "everyNthFrame": 1}`;
event `Page.screencastFrame` → `{"data": <base64 JPEG 1280x720>, "metadata": {"timestamp": <float seconds>, ...}, "sessionId": int}`;
each frame MUST be acked with `Page.screencastFrameAck {"sessionId": ...}`;
`Page.stopScreencast`; frames are activity-driven (only on change).

### Does NOT Exist

- `parrot.e2e.screencast` — this task creates it.
- `E2EScreencastError`, `E2EScreencastContextReusedError` — the latter is explicitly NOT part of the design.
- `record_on_anomaly` / `AnomalyRecorder` — TASK-4865.
- Any target-ID / cross-connection attach API (`Target.attachToTarget` from another connection fails on Obscura).
- `parrot.e2e.cli screencast` subcommands, daemons or tickets — dropped by the spec revision.
- `playwright` as a declared dependency of `ai-parrot-server` — never import it at module top level outside `TYPE_CHECKING`.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/e2e/errors.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/e2e/screencast.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/unit/e2e/test_screencast.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/e2e/errors.py#E2EError",
    "sym:packages/ai-parrot-server/src/parrot/e2e/errors.py#E2EEvidenceError"
  ]
}
```

## Implementation Notes

### Key Constraints

- Async-first; bounded waits (`asyncio.wait_for`) on every CDP call; CPU-bound encode/decode in a
  `ProcessPoolExecutor(max_workers=1)` — never in the event loop.
- Never close/navigate the page, context or browser. Cleanup order on stop AND on startup failure:
  `Page.stopScreencast` → `detach()` → await ack tasks → encode/flush → decode-validate → atomic publish.
- Buffer bounded by `max_frames`; overflow sets an overflow flag and the eventual `stop_screencast`
  raises `E2EScreencastError(reason_code="frame_overflow")` — never a truncated success.
- Publish atomically: encode to `<out_dir>/.screencast.<uuid>.webm.tmp`, validate, then `os.replace`
  to `screencast.webm`; refuse (raise) if `screencast.webm` already exists at start or publish.
- Missing `av`/`PIL` ⇒ `E2EScreencastError(reason_code="encoder_unavailable")` whose message names
  `ai-parrot-server[screencast]`; importing `parrot.e2e.screencast` must never import `av`.
- Logging via `logging.getLogger(__name__)`; no `print`.

### References in Codebase

- Prototype: `_encode_webm` / `_decode_webm` and the test body in
  `packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py` (TestObscuraScreencastRecording).

## Implementation Blueprint

### Steps (in order)

1. Append `E2EScreencastError` to `errors.py` — do it first because `screencast.py` imports it.
2. Write `screencast.py` from the block below; fill the marked gaps — the prototype shows working code.
3. Write unit tests with fake `Page`/`CDPSession` objects (Test Specification) — because CI has no Obscura.
4. `ruff check --fix` both source files; run Validation Commands.

### `packages/ai-parrot-server/src/parrot/e2e/errors.py` (MODIFY)

```python
# AFTER — append below the body of `class E2EEvidenceError(E2EError):` (end of file, verified: errors.py:117-126)
# occurrences: 1 (verified: grep -c 'class E2EEvidenceError(E2EError):' errors.py)


class E2EScreencastError(E2EError):
    """Operational screencast recording failed (FEAT-762).

    Maps to exit code 1. Never gate evidence: raised for a closed page, an
    unsupported/failed CDP capture, a missing encoder extra
    (``ai-parrot-server[screencast]``), a frame-buffer overflow, or an
    empty/invalid output file. ``reason_code`` carries a short slug such as
    ``page_closed``, ``capture_failed``, ``encoder_unavailable``,
    ``frame_overflow``, ``invalid_output`` or ``output_exists``.
    """

    exit_code = EXIT_FAILURE
```

**Why**: the spec requires a typed error in the existing hierarchy; `exit_code` mirrors `E2ETargetError`.

### `packages/ai-parrot-server/src/parrot/e2e/screencast.py` (CREATE)

```python
"""In-connection operational screencast recorder for E2E exploration (FEAT-762 M1).

Obscura isolates pages per CDP connection, so recording must use a CDPSession
opened on the SAME Playwright connection that owns the page (spike evidence:
sdd/state/FEAT-762/screencast-spike.md). Output is operational, never gate evidence.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import uuid
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from parrot.e2e.errors import E2EScreencastError

if TYPE_CHECKING:  # playwright is not a dependency of ai-parrot-server
    from playwright.async_api import CDPSession, Page

logger = logging.getLogger(__name__)

SCREENCAST_FILENAME = "screencast.webm"
_CDP_TIMEOUT_S = 10.0
_EXTRA_HINT = "install the optional extra: pip install 'ai-parrot-server[screencast]'"


def _encode_webm(frames: list[tuple[int, bytes]], out_path: str) -> int:
    """Encode (timestamp_ms, jpeg) frames to VP8 WebM; runs in a worker process.

    Args:
        frames: Frames ordered by timestamp, timestamps relative to the first frame.
        out_path: Destination file (temporary path).

    Returns:
        Number of frames encoded.
    """
    # FILL IN: lazy `import av` / `from PIL import Image`; libvpx stream, yuv420p, Fraction(1, 1000)
    # time base, strictly increasing pts, flush with stream.encode(None) — copy the M0 prototype.


def _validate_webm(path: str) -> int:
    """Decode ``path`` fully and return the number of decoded frames (worker process)."""
    # FILL IN: lazy `import av`; count decoded video frames — 0 frames means invalid output.


@dataclass
class ScreencastSession:
    """Runtime recorder handle; owns only the CDPSession, frames, ack tasks and output path."""

    page: Any
    cdp: Any
    out_dir: Path
    max_frames: int
    frames: list[tuple[int, bytes]] = field(default_factory=list)
    ack_tasks: list[asyncio.Task] = field(default_factory=list)
    overflow: bool = False
    result: Optional[Path] = None
    error: Optional[E2EScreencastError] = None
    stopped: bool = False

    @property
    def out_path(self) -> Path:
        """Final published WebM path."""
        return self.out_dir / SCREENCAST_FILENAME


async def start_screencast(page: "Page", out_dir: Path, *, max_frames: int = 600) -> ScreencastSession:
    """Begin capture of the caller's existing page; retain its context and state."""
    # FILL IN: page.is_closed() -> E2EScreencastError(reason_code="page_closed")
    # FILL IN: out_dir.mkdir(parents=True, exist_ok=True); existing screencast.webm -> reason_code="output_exists"
    # FILL IN: cdp = await page.context.new_cdp_session(page); register "Page.screencastFrame" handler that
    #   appends (int(ts*1000), base64-decoded bytes) while len < max_frames else sets overflow, and ALWAYS
    #   schedules an ack task; then send Page.startScreencast (wait_for _CDP_TIMEOUT_S).
    # FILL IN: on any exception after the CDPSession exists, detach it (suppress errors) and raise
    #   E2EScreencastError(reason_code="capture_failed") from the original.


async def stop_screencast(session: ScreencastSession) -> Path:
    """Stop, detach, encode, decode-validate and publish; return the validated WebM path."""
    # FILL IN: idempotent — if session.stopped: return session.result or raise session.error.
    # FILL IN: stopScreencast + detach + gather(ack_tasks, return_exceptions=True), each bounded.
    # FILL IN: overflow / no frames -> errors; encode + validate in ProcessPoolExecutor(max_workers=1)
    #   via loop.run_in_executor; ImportError (ModuleNotFoundError) -> reason_code="encoder_unavailable"
    #   with _EXTRA_HINT; 0 decoded frames -> "invalid_output"; publish with os.replace, never overwrite.
    # FILL IN: always remove the temp file on failure; store result/error on the session before returning/raising.
```

**Why**: the dataclass is an internal runtime handle (spec: not persisted), so no Pydantic model is needed;
module-level helpers are required because `ProcessPoolExecutor` pickles functions by qualified name.

### `packages/ai-parrot-server/tests/unit/e2e/test_screencast.py` (CREATE)

```python
"""Unit tests for parrot.e2e.screencast (FEAT-762 M1) — fake Playwright objects, no browser."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.e2e.errors import E2EScreencastError
from parrot.e2e import screencast


class FakeCDPSession:
    """Records sent CDP commands; ``emit`` delivers a Page.screencastFrame event."""
    # FILL IN: send(), on(), detach(), emit(); configurable failure for a given method.


class FakePage:
    """Minimal Page: is_closed(), context.new_cdp_session(page), close-tracking flags."""
    # FILL IN


# FILL IN: one test per spec §4 M1 row (names below are fixed by the spec):
# test_start_screencast_existing_page_succeeds, test_start_screencast_closed_page_raises,
# test_start_screencast_failure_releases_resources, test_stop_screencast_finalizes_and_preserves_page,
# test_stop_screencast_invalid_output_raises, test_stop_screencast_refuses_overwrite_and_is_idempotent,
# test_frame_buffer_overflow_is_explicit_failure, test_missing_encoder_extra_is_typed_error
```

**Why**: the fakes keep the tests hermetic; encoder success paths monkeypatch `_encode_webm`/`_validate_webm`
(or use `pytest.importorskip("av")` with tiny generated JPEGs) so CI without `av` still runs the logic.

### FILL IN checklist

- [ ] `_encode_webm` / `_validate_webm` ported from the M0 prototype.
- [ ] `start_screencast` validation, handler, ack scheduling, failure cleanup.
- [ ] `stop_screencast` ordering, idempotence, overflow/empty/invalid/encoder errors, atomic publish.
- [ ] Fakes and the 8 named unit tests.

## Acceptance Criteria

- [ ] AC-1: `start_screencast` opens a CDPSession on the given page only; never creates/selects/closes pages or contexts.
- [ ] AC-2: closed page, CDP failure, missing encoder, overflow, empty and invalid output each raise `E2EScreencastError` with the documented `reason_code`; no published file on failure.
- [ ] AC-3: stop order is stopScreencast → detach → acks → encode → validate → publish; repeated stop returns the prior result/error.
- [ ] AC-4: existing `screencast.webm` is never overwritten.
- [ ] AC-5: `import parrot.e2e.screencast` works without `av`/`PIL`/`playwright` installed.
- [ ] AC-6: all 8 unit tests pass; `ruff check` clean on the three files.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_screencast.py -q`

## Test Specification

Fake `CDPSession` records the ordered list of `send` calls and `detach`; assert the exact order in
`test_stop_screencast_finalizes_and_preserves_page`. Simulate the missing extra by patching
`screencast._encode_webm` to raise `ModuleNotFoundError("av")`. Route the executor through one small
module-level factory (e.g. `_run_in_worker(fn, *args)`) so unit tests can patch it to run inline —
patched functions are not picklable into a real worker process. Real encoding is covered by the
existing M0 integration test and TASK-4865's real-Obscura test.

## Agent Instructions

1. Verify this Codebase Contract before coding (`errors.py` anchor, Playwright attributes).
2. Modify only the three listed files. Do not add re-exports to `parrot/e2e/__init__.py`.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src`.
4. Commit code only; SDD state is updated by the orchestrator.

## Completion Note

Owned by the finalization tool after verified acceptance.
