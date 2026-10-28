---
type: feature
base_branch: dev
projects: [ai-parrot-server]
tags: [e2e, screencast, tech-debt, testing]
---

# Feature Specification: Screencast recorder hardening (FEAT-762 review follow-up)

**Feature ID**: FEAT-765
**Date**: 2026-10-28
**Author**: Jesus Lara
**Status**: approved
**Target version**: next patch
**Discovered-from**: `issue:c3e0c9065cce` (FEAT-762 deferred review findings)

---

## 1. Motivation & Business Requirements

### Problem Statement

The FEAT-762 review deferred five gaps in `parrot.e2e.screencast`:

1. Unit tests fake the whole encoder via `_run_in_worker`, so only the
   Obscura-gated integration test exercises real PyAV/libvpx encoding.
2. `stop_screencast` is not single-flight: a second concurrent call sees
   `stopped=True` with neither `result` nor `error` and raises a misleading
   `invalid_output` "stopped without a result".
3. No test cancels during `AnomalyRecorder.__aexit__`; a cancelled stop leaves
   `recorder.error` unset even though the session holds a typed error.
4. `test_screencast_integration` reads the private `recorder._session` and
   polls with sleeps to detect capture start.
5. `start_screencast` / `stop_screencast` docstrings lack Google-style
   Args/Returns/Raises, and `uv.lock` was not refreshed for the
   `ai-parrot-server[screencast]` extra.

### Goals
- Concurrent `stop_screencast` callers all observe the first call's outcome.
- A cancelled `AnomalyRecorder.__aexit__` leaves a typed `recorder.error` and re-raises the cancellation.
- Public `AnomalyRecorder.recording` property and `wait_started(timeout)` coroutine replace private polling.
- A unit test encodes and decodes real frames in-process when `av`/`PIL` are installed.
- Google-style docstrings; `uv.lock` includes the screencast extra.

### Non-Goals (explicitly out of scope)
- Changing capture, encoding parameters or the worker-process design.
- Cancellation handling inside `start_screencast`.

---

## 2. Architectural Design

### Overview
`ScreencastSession` gains a `finished: asyncio.Event` set in `stop_screencast`'s
`finally`. A caller that finds `stopped=True` awaits `finished` before reading
`result`/`error`. `AnomalyRecorder` gains a `_started` event set when `_start`
completes (success or failure), `recording` (`_session is not None`) and
`wait_started(timeout) -> bool`. `__aexit__` maps `asyncio.CancelledError` from
the stop into `self.error` (session's typed error, else a `capture_failed` one)
and re-raises.

### New Public Interfaces
```python
class AnomalyRecorder:
    @property
    def recording(self) -> bool: ...
    async def wait_started(self, timeout: float) -> bool: ...
```

---

## 3. Module Breakdown

### Module 1: Recorder hardening + tests (TASK-4872)
- `packages/ai-parrot-server/src/parrot/e2e/screencast.py` (MODIFY)
- `packages/ai-parrot-server/tests/unit/e2e/test_screencast.py` (MODIFY)
- `packages/ai-parrot-server/tests/integration/e2e/test_screencast_integration.py` (MODIFY)
- `uv.lock` (MODIFY — `uv lock`, no sync)

---

## 4. Test Specification

### Unit Tests
- `test_concurrent_stop_screencast_is_single_flight` — two concurrent stops encode once and return the same path.
- `test_concurrent_stop_screencast_shares_failure` — the waiting caller re-raises the first call's typed error.
- `test_record_on_anomaly_cancel_during_aexit_records_typed_error` — cancelling while the real stop is encoding re-raises `CancelledError`, sets `recorder.error`, removes listeners and leaves no temp file.
- `test_wait_started_reports_recording` — `wait_started` returns `True` after a trigger, `False` with no trigger before timeout.
- `test_real_encoder_roundtrip_in_process` — `_encode_webm` + `_validate_webm` on real JPEG frames (skips without `av`/`PIL`).

### Integration Tests
- `test_record_on_anomaly_real_obscura` uses `wait_started` / `recording` (still Obscura-gated).

### Validation Contract
`pytest packages/ai-parrot-server/tests/unit/e2e/test_screencast.py` with `PYTHONPATH=packages/ai-parrot-server/src`.
