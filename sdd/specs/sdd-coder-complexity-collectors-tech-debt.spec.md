---
type: feature
base_branch: dev
projects: [ai-parrot, dev-loop]
tags: [sdd-coder, complexity, subprocess, tech-debt, ledger-fix]
---

# Feature Specification: Bounded streaming capture in complexity collectors' `_run_subprocess`

**Feature ID**: FEAT-663
**Date**: 2026-10-14
**Author**: Claude (agent:sdd-fix)
**Status**: approved
**Target version**: 0.30.x

---

## 1. Motivation & Business Requirements

> Ledger-driven fix (`/sdd-fix`, fixgroup:b05e3ddf1de4). Resolves:
> - `issue:cf3c4a0db0ca` (major, tech_debt) — `_run_subprocess` buffers full
>   output in memory before bounding it.
> - `issue:0306504b9917` (minor, tech_debt) — `_run_subprocess` enforces
>   `max_output_bytes` only after full buffering, not during capture.

### Problem Statement

`parrot/flows/dev_loop/sdd_coder/complexity_collectors.py::_run_subprocess`
runs bounded collectors (Ruff, wikitoolkit blast) with
`await proc.communicate()`: the child's **entire** stdout/stderr is
accumulated in memory first, and only then sliced. A misbehaving or
very chatty subprocess (e.g. Ruff JSON over a large target set, a wiki
CLI stack trace loop) can therefore allocate unbounded memory inside the
orchestrator process before the "bound" is applied. Additionally the slice
`decoded[:max_output_bytes]` truncates by **characters after decode**, not
by bytes, so the policy knob `max_output_bytes` is not actually a byte
bound.

### Goals
- Enforce `max_output_bytes` **during capture**: at no point does
  `_run_subprocess` hold more than `max_output_bytes` (+ one read chunk)
  of a stream's data in memory.
- Bound is applied **in bytes, before decoding**.
- Preserve existing semantics: the child always runs to completion (or
  timeout), its real `returncode` is reported, timeout/cancellation still
  kills and reaps the process, and the returned `stdout`/`stderr` remain
  `str` (decoded UTF-8, `errors="replace"`).

### Non-Goals (explicitly out of scope)
- No change to `SubprocessResult`'s shape or any caller in this file.
- No change to `ComplexityPolicy` (`max_output_bytes` keeps its meaning —
  it simply becomes true).
- No truncation *flag* surfaced to callers (callers already treat bounded
  output defensively; adding a flag is a separate enhancement).

---

## 2. Architectural Design

### Overview

Replace `proc.communicate()` with concurrent bounded drains of
`proc.stdout` and `proc.stderr` plus `proc.wait()`, all under the same
`asyncio.wait_for` timeout. A private helper `_read_bounded(stream,
max_bytes)` reads fixed-size chunks, keeps at most `max_bytes` bytes, and
**keeps draining** (discarding) the remainder so the child never blocks on
a full pipe and its exit code stays meaningful.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `_collect_ruff_cyclomatic` / `_collect_ruff_syntax` / `_collect_wiki_blast` | callers (unchanged) | keep calling `_run_subprocess(cmd, cwd, timeout, max_output_bytes)` |
| `ComplexityPolicy.max_output_bytes` | consumed | now a real byte bound during capture |

### New Public Interfaces

None — `_read_bounded` is module-private.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: bounded capture | yes | helper signature, drain-and-discard semantics, kill/reap branch all fixed below | — |

### Module 1: Bounded streaming capture
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py`
- **Responsibility**: bound subprocess output in bytes during capture.
- **Depends on**: nothing new (stdlib `asyncio` only).
- **Interface Skeleton**:
  ```python
  # modifies complexity_collectors.py:1057 (_run_subprocess)
  async def _read_bounded(stream: asyncio.StreamReader, max_bytes: int) -> bytes:
      """Drain `stream` to EOF, retaining at most `max_bytes` bytes.

      Reads in fixed chunks (64 KiB); once `max_bytes` is reached, later
      chunks are discarded but the stream keeps being drained so the child
      process never blocks on a full pipe.
      """

  async def _run_subprocess(cmd: List[str], cwd: Path, timeout_seconds: int, max_output_bytes: int) -> SubprocessResult:
      """Run a subprocess with output bounded IN BYTES DURING CAPTURE.

      stdout/stderr drains and proc.wait() run concurrently under one
      asyncio.wait_for(timeout_seconds). Timeout/cancellation still kills
      and reaps the process (spec FEAT-561 §7). Returned text is decoded
      UTF-8 with errors="replace" AFTER the byte bound is applied.
      """
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_run_subprocess_bounds_stdout_during_capture` | M1 | child emits ≫ `max_output_bytes`; captured `stdout` is ≤ `max_output_bytes` bytes, `returncode` is the child's real exit code (0) |
| `test_run_subprocess_bound_is_bytes_not_chars` | M1 | multibyte output: bound applied to the byte stream pre-decode; decode with `errors="replace"` never raises on a split code point |
| `test_run_subprocess` (existing) | M1 | unchanged behavior for small outputs |
| `test_run_subprocess_timeout` (existing) | M1 | timeout still kills + reaps and re-raises |

### Integration Tests
Existing `test_complexity_collectors.py` suite passes unchanged (callers
mock `_run_subprocess`; no caller-visible contract change).

---

## 5. Acceptance Criteria

- [ ] AC1: `_run_subprocess` never buffers more than `max_output_bytes` +
      one chunk per stream — `proc.communicate()` is no longer called.
- [ ] AC2: the bound is applied in **bytes before decoding**, and decoding
      a truncated multibyte sequence does not raise (`errors="replace"`).
- [ ] AC3: the child runs to completion and `SubprocessResult.returncode`
      is its real exit code even when output exceeds the bound.
- [ ] AC4: timeout and cancellation still kill and reap the process
      (existing `test_run_subprocess_timeout` passes).
- [ ] AC5: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py` passes.

---

## 6. Codebase Contract

### Verified Imports
```python
import asyncio  # already imported, complexity_collectors.py:10
from parrot.flows.dev_loop.sdd_coder.complexity_collectors import _run_subprocess, SubprocessResult  # tests, verified test_complexity_collectors.py:20
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py
class SubprocessResult:  # line 1048
    def __init__(self, returncode: int, stdout: str, stderr: str): ...  # line 1051
async def _run_subprocess(cmd: List[str], cwd: Path, timeout_seconds: int, max_output_bytes: int) -> SubprocessResult:  # line 1057
```

### Does NOT Exist (Anti-Hallucination)
- ~~`SubprocessResult.truncated`~~ — no truncation flag exists or is added.
- ~~`policy.chunk_size`~~ — chunk size is a module constant, not policy.

### Edit Sites (Blueprint Anchors)

Verified against: fc010335c

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py` | MODIFY | `async def _run_subprocess(cmd: List[str], cwd: Path, timeout_seconds: int, max_output_bytes: int) -> SubprocessResult:` | `complexity_collectors.py:1057` | 1 |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py` | MODIFY | `async def test_run_subprocess_timeout():` | `test_complexity_collectors.py:545` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- `asyncio.gather(_read_bounded(proc.stdout, N), _read_bounded(proc.stderr, N), proc.wait())`
  wrapped in `asyncio.wait_for(..., timeout=timeout_seconds)`.
- Keep the existing `except (asyncio.TimeoutError, asyncio.CancelledError)`
  kill-and-reap branch verbatim (FEAT-561 §7 requirement).
- Chunk size: 65536 bytes, module-level constant `_SUBPROCESS_READ_CHUNK`.

### Known Risks / Gotchas
- **Must keep draining past the bound** — stopping reads deadlocks the
  child on a full pipe and corrupts the returncode semantics.
- `create_subprocess_exec` is called with `stdout=PIPE, stderr=PIPE`, so
  `proc.stdout` / `proc.stderr` are never `None`; no guard needed.

### External Dependencies
None.

---

## 8. Open Questions

None — scope fixed by the two ledger issues.

---

## 9. Design Research Cross-Check

Status: skipped (ledger-driven tech-debt fix with fully-determined design;
no exploration doc exists for this group).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-14 | Claude (agent:sdd-fix) | Initial spec from fixgroup:b05e3ddf1de4 |
