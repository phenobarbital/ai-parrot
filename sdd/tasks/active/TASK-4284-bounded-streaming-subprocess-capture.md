# TASK-4284: Bound `_run_subprocess` output in bytes during capture

**Feature**: FEAT-663 — Bounded streaming capture in complexity collectors' `_run_subprocess`
**Spec**: `sdd/specs/sdd-coder-complexity-collectors-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: issue:cf3c4a0db0ca, issue:0306504b9917

---

## Context

Ledger fix lane (`/sdd-fix`, fixgroup:b05e3ddf1de4). `_run_subprocess` in
`complexity_collectors.py` uses `await proc.communicate()`, so a chatty
subprocess's **entire** output is buffered in memory before the
`max_output_bytes` bound is applied — and the bound is applied as a
character slice after decoding, not as a byte bound. Implements spec §2/§3
Module 1: bounded streaming capture.

---

## Scope

- Add module constant `_SUBPROCESS_READ_CHUNK = 65536`.
- Add private helper `_read_bounded(stream, max_bytes) -> bytes` that
  drains a stream to EOF in chunks, retaining at most `max_bytes` bytes
  and discarding (but still draining) the rest.
- Rewrite `_run_subprocess` to gather both stream drains and `proc.wait()`
  under one `asyncio.wait_for(timeout_seconds)`, decoding AFTER the byte
  bound, keeping the existing timeout/cancellation kill-and-reap branch.
- Add two unit tests (AC1–AC3 coverage) to `test_complexity_collectors.py`.

**NOT in scope**: any change to `SubprocessResult`'s shape, to callers,
to `ComplexityPolicy`, or any truncation flag.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py` | MODIFY | bounded streaming `_run_subprocess` + `_read_bounded` helper |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py` | MODIFY | 2 new tests for byte-bounded capture |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio  # verified: complexity_collectors.py:10 (already imported)
from parrot.flows.dev_loop.sdd_coder.complexity_collectors import _run_subprocess  # verified: test_complexity_collectors.py:20
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py
class SubprocessResult:  # line 1048
    def __init__(self, returncode: int, stdout: str, stderr: str):  # line 1051

async def _run_subprocess(cmd: List[str], cwd: Path, timeout_seconds: int, max_output_bytes: int) -> SubprocessResult:  # line 1057
```

### Does NOT Exist
- ~~`SubprocessResult.truncated`~~ — no truncation flag; do not add one.
- ~~`ComplexityPolicy.chunk_size`~~ — chunk size is a module constant.
- ~~`proc.communicate()` in the new implementation~~ — must be removed.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py#_run_subprocess",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py#SubprocessResult"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Must keep draining past the bound** — stopping reads deadlocks the
  child on a full pipe. Discard bytes beyond `max_bytes`, never stop reading.
- Child runs to completion; `SubprocessResult.returncode` is its real exit code.
- Decode with `errors="replace"` AFTER the byte bound (a truncated multibyte
  sequence must not raise).
- Keep the `except (asyncio.TimeoutError, asyncio.CancelledError)` kill-and-reap
  branch and its explanatory comment (FEAT-561 §7).
- `stdout=PIPE, stderr=PIPE` are always set, so `proc.stdout`/`proc.stderr`
  are never `None` — no guards.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_SUBPROCESS_READ_CHUNK` and `_read_bounded` above `_run_subprocess` —
   *why*: module-private helper, keeps the bound logic testable in one place.
2. Replace the `proc.communicate()` body of `_run_subprocess` with the gathered
   bounded drains — *why*: this is the fix; communicate() is the unbounded buffer.
3. Add the two new tests after `test_run_subprocess_timeout` — *why*: pins AC1–AC3.
4. Run validation commands; `ruff check --fix` the two files.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def _run_subprocess' <path>)
# REPLACE — the whole body of `async def _run_subprocess` (verified: complexity_collectors.py:1057),
# inserting the constant and helper immediately above it:

_SUBPROCESS_READ_CHUNK = 65536


async def _read_bounded(stream: asyncio.StreamReader, max_bytes: int) -> bytes:
    """Drain `stream` to EOF, retaining at most `max_bytes` bytes.

    Reads fixed chunks; once `max_bytes` is reached, later chunks are
    discarded but the stream keeps being drained so the child process
    never blocks on a full pipe (spec FEAT-663 §7).
    """
    buf = bytearray()
    while True:
        chunk = await stream.read(_SUBPROCESS_READ_CHUNK)
        if not chunk:
            return bytes(buf)
        if len(buf) < max_bytes:
            buf.extend(chunk[: max_bytes - len(buf)])


async def _run_subprocess(cmd: List[str], cwd: Path, timeout_seconds: int, max_output_bytes: int) -> SubprocessResult:
    """Run a subprocess with output bounded in bytes during capture.

    stdout/stderr drains and the process wait run concurrently under one
    timeout. The byte bound is applied while reading (never buffering the
    full output), and decoding happens after the bound with
    errors="replace" so a split multibyte sequence cannot raise.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_b, stderr_b, _ = await asyncio.wait_for(
            asyncio.gather(
                _read_bounded(proc.stdout, max_output_bytes),
                _read_bounded(proc.stderr, max_output_bytes),
                proc.wait(),
            ),
            timeout=timeout_seconds,
        )
        return SubprocessResult(
            proc.returncode,
            stdout_b.decode("utf-8", errors="replace"),
            stderr_b.decode("utf-8", errors="replace"),
        )
    except (asyncio.TimeoutError, asyncio.CancelledError):
        # Kill and reap on EITHER a timeout OR the awaiting task being
        # cancelled (spec §7: "cancellation must terminate and reap their
        # processes") -- only handling TimeoutError left a cancelled
        # collection's subprocess un-reaped.
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass  # Process already finished
        raise
```
**Why this shape**: `gather` of the two drains plus `wait()` replaces
`communicate()` 1:1 — same ordering guarantees, but each drain caps memory at
`max_bytes` + one chunk. Keep the kill/reap branch verbatim.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def test_run_subprocess_timeout' <path>)
# AFTER — insert below the whole `test_run_subprocess_timeout` function
# (verified: test_complexity_collectors.py:545)

@pytest.mark.asyncio
async def test_run_subprocess_bounds_stdout_during_capture():
    """Output beyond max_output_bytes is discarded during capture (AC1, AC3)."""
    cmd = ["python", "-c", "import sys; sys.stdout.write('x' * 1_000_000)"]
    result = await _run_subprocess(cmd, Path("."), 30, 1024)
    assert result.returncode == 0  # child ran to completion
    assert len(result.stdout.encode("utf-8")) <= 1024


@pytest.mark.asyncio
async def test_run_subprocess_bound_is_bytes_not_chars():
    """The bound applies to bytes pre-decode; a split code point must not raise (AC2)."""
    # 'é' is 2 bytes in UTF-8; an odd byte bound splits the final code point.
    cmd = ["python", "-c", "import sys; sys.stdout.buffer.write('é'.encode() * 100)"]
    result = await _run_subprocess(cmd, Path("."), 30, 33)
    assert result.returncode == 0
    # FILL IN: assert decoded length/replacement-char behavior — bounded by AC2
```
**Why**: pins the byte-bound and completion semantics the spec's AC1–AC3 require.

### FILL IN checklist
- [ ] `test_run_subprocess_bound_is_bytes_not_chars` final assertion — bounded by AC2 (decode never raises; captured bytes ≤ bound).

---

## Acceptance Criteria

- [ ] AC1: `proc.communicate()` no longer appears in `_run_subprocess`; per-stream memory ≤ `max_output_bytes` + one chunk
- [ ] AC2: bound applied in bytes before decoding; `errors="replace"` decode never raises
- [ ] AC3: child runs to completion; real `returncode` reported even when output exceeds the bound
- [ ] AC4: existing `test_run_subprocess_timeout` still passes (kill + reap preserved)
- [ ] AC5: full module test file passes
- [ ] No linting errors: `ruff check` on both files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py -q`

---

## Test Specification

See blueprint blocks above — two new tests, plus the existing
`test_run_subprocess` / `test_run_subprocess_timeout` must keep passing.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-coder-complexity-collectors-tech-debt --feature-id FEAT-663`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in `sdd/tasks/index/sdd-coder-complexity-collectors-tech-debt.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the two listed files
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4284 sdd-coder-complexity-collectors-tech-debt verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
