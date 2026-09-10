# TASK-3082: BoundedSourceToolkit — streaming source_info / source_read with hashes and continuation

**Feature**: FEAT-543 — Claude Code and Codex Tool Optimizations
**Spec**: `sdd/specs/tool-optimizations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3079
**Assigned-to**: unassigned

---

## Context

Spec §2 "Bounded Reader Contract" (all 8 items), §3 Module M3, AC5, AC6.
Files above **350 lines or 64,000 bytes** (either threshold, both
configurable) require an explicit inclusive 1-based range. The reader
never holds a whole file in memory, never returns a partial line, and
lets the caller continue with `next_line` + `expected_sha256`.

`ReadOnlyRepoToolkit.read_file` (`repo/toolkit.py:200-256`) is the wrong
model: it `fh.read()`s the whole file and byte-slices the result. Its API
is preserved untouched; this toolkit is new.

The pure helpers in this module are reused by TASK-3083 (reference
slices) and TASK-3088 (hook threshold detection), so keep them free of
toolkit state.

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/reader.py`:
  - Pure, synchronous, stdlib-only helpers (run them via
    `asyncio.to_thread` from the toolkit):
    - `class FileIdentity(NamedTuple)`: `inode, size, mtime_ns` from `os.stat`.
    - `def stat_regular(path: Path) -> FileIdentity`: `os.lstat` → reject
      symlink (`SymlinkRejectedError`), require `S_ISREG` else
      `NotRegularFileError` (devices, FIFOs, directories).
    - `def sniff_binary(path: Path, probe: int = 8192) -> bool`: NUL byte
      in the first `probe` bytes.
    - `def count_lines_bounded(path: Path, stop_after: int) -> tuple[int, bool]`:
      count `\n` in 64 KiB chunks; return `(count, exceeded)` where
      `exceeded=True` as soon as `count > stop_after` (early exit; the
      exact count is then unknown — return `stop_after + 1`). A final line
      without `\n` counts as a line (track whether the last chunk ended in
      `\n`). Empty file → `(0, False)`.
    - `def sha256_stream(path: Path, *, deadline_seconds: float) -> str`:
      `hashlib.sha256` over 1 MiB chunks; abort with `HashTimeoutError`
      when `time.monotonic()` passes the deadline.
    - `def read_line_range(path: Path, start_line: int, end_line: int, *, max_line_bytes: int) -> RangeRead`:
      open in **binary** mode, iterate with `readline(max_line_bytes + 1)`
      — a returned chunk longer than `max_line_bytes` that does not end in
      `\n` means the line is too large → `LineTooLargeError(line_no, at_least_bytes)`
      (do not read the rest of it). Skip lines `< start_line` cheaply (same
      bounded `readline`, discard). Collect raw line bytes for
      `start_line..end_line`, preserving `\r\n` / `\n` / missing final
      newline verbatim. Decode each line with `bytes.decode("utf-8")`
      (STRICT) → `InvalidEncodingError(line_no)`. Return
      `RangeRead(lines: list[str], actual_end: int, eof: bool)` where
      `eof=True` when the file ended at or before `end_line`.
      `start_line > total lines` → `RangeOutOfBoundsError`.
    - `def check_identity_unchanged(before: FileIdentity, path: Path) -> None`
      → `ConcurrentModificationError` when `os.stat` differs.
  - `class BoundedSourceToolkit(OptimizationToolkitBase)`:
    `arg_models = {"source_info": SourceInfoArgs, "source_read": SourceReadArgs}`;
    no `confirming_tools` (read-only); `llm_dependent_tools` empty.
    - `_resolve(self, path) -> Path`: `resolve_operand(self.policy, path, must_exist=True)`
      (containment + `is_secret_path` when `policy.deny_secret_files` + no
      symlink components) then `stat_regular`.
    - `async source_info(self, path: str) -> SourceInfo | OperationResult`
      (`@tool_schema(SourceInfoArgs)`): identity → binary sniff →
      `count_lines_bounded(path, policy.max_lines)` → `is_large =
      exceeded or size > large_file_bytes` → sha256 (deadline =
      `policy.command_timeout_seconds`) → re-check identity. `line_count`
      is `None` when `exceeded` (only threshold detection ran).
      `range_required = is_large`. Never includes content.
    - `async source_read(self, path: str, start_line: int | None = None, end_line: int | None = None, expected_sha256: str | None = None) -> SourceResult | OperationResult`
      (`@tool_schema(SourceReadArgs)`):
      1. Validate `SourceReadArgs(...)` (both-or-neither; `1 <= start <= end`;
         `end - start + 1 <= policy.max_lines` → else `range_too_large`).
      2. Identity, binary, thresholds as in `source_info`.
      3. Large file without range → `range_required` error whose
         `details` carry `{"max_lines", "large_file_bytes", "size_bytes", "example": {"start_line": 1, "end_line": max_lines}}`
         and NO content.
      4. Hash (streaming, deadline). If `expected_sha256` given and
         differs → `stale_revision` (details: `current_sha256`).
      5. Small file without range → `start=1, end=policy.max_lines`
         (which covers the whole file by definition of "small").
      6. `read_line_range(...)` with `max_line_bytes = policy.max_result_bytes`.
      7. **Budget fit**: compute the envelope size once
         (`measure_json_bytes(SourceResult(..., content="").model_dump())`),
         then add lines while
         `envelope + escaped_len(accumulated) <= policy.max_result_bytes`,
         where `escaped_len(s) = len(json.dumps(s, ensure_ascii=False).encode()) - 2`.
         If the FIRST candidate line alone does not fit → `line_too_large`
         error with `{"line": n, "bytes": len}`. Otherwise return the
         complete lines that fit, `truncated = (returned_end < requested_end and not eof)`,
         `next_line = returned_end + 1` (or `None` when `eof` and every
         requested line was returned), `eof` accordingly.
      8. Re-check identity → `concurrent_modification`.
      9. Empty file → `content=""`, `start_line=1, end_line=0`, `eof=True`,
         `next_line=None`.
    - Every error is `OperationResult(status="error", operation="source_read"|"source_info", error=OperationError(code=...))`.
      Codes: `not_found`, `not_a_file`, `symlink_rejected`, `secret_file`,
      `path_outside_root`, `binary_file`, `invalid_encoding`,
      `range_required`, `range_too_large`, `range_out_of_bounds`,
      `line_too_large`, `stale_revision`, `concurrent_modification`,
      `hash_timeout`.
- Run `python scripts/generate_tool_registry.py --check` (update
  `parrot_tools/__init__.py` only if it demands it).
- Tests: `packages/ai-parrot-tools/tests/tool_optimizations/test_reader.py`.
  Generate size fixtures in the test (never commit large files, spec §4).

**NOT in scope**: chunk concatenation helpers (explicitly excluded by
Contract 5), offset/limit aliases (excluded from v1), hooks (TASK-3088).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/reader.py` | CREATE | Pure helpers + `BoundedSourceToolkit` |
| `packages/ai-parrot-tools/tests/tool_optimizations/test_reader.py` | CREATE | Boundary/encoding/allocation tests |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY (only if registry check demands) | `TOOL_REGISTRY` entry |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.tool_optimizations.base import OptimizationToolkitBase                     # TASK-3079
from parrot_tools.tool_optimizations.models import SourceResult, SourceInfo, OperationResult, OperationError, SourceInfoArgs, SourceReadArgs
from parrot_tools.tool_optimizations.policy import OptimizationPolicy, resolve_operand, SymlinkRejectedError, measure_json_bytes
from parrot.tools.repo.confinement import PathOutsideRootError, SecretFileError, is_secret_path   # confinement.py:55, :59, :93
from parrot.tools.decorators import tool_schema                                              # decorators.py:39
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/repo/confinement.py
def is_secret_path(rel_path: str) -> bool               # :93  (.env, *.pem, *.key, id_rsa*, credentials, ... ; *.example etc. allowed)
def resolve_readable_path(root: Path, candidate: str) -> Path   # :115 — containment then deny-list; raises the two errors above

# packages/ai-parrot/src/parrot/tools/repo/toolkit.py — the ANTI-pattern (for reference only)
async def read_file(self, path: str, start: int = 1, end: int = 0)   # :200 — :227-230 reads whole file with errors="replace"; :241-243 slices AFTER reading
```

### Does NOT Exist
- ~~`SourceReadArgs.offset` / `.limit`~~ — excluded from v1 (Contract 2).
- ~~`source_read_all` / `source_read_chunks`~~ — no concatenating call exists (Contract 5).
- ~~`ReadOnlyRepoToolkit.read_file` as a base~~ — API preserved, not reused.
- ~~`Path.read_text()` / `fh.read()` / `fh.readlines()` anywhere in reader.py~~ — tests grep the source for `read_text(`, `.read()` and `readlines(` and fail if present.
- ~~`errors="replace"` decoding~~ — strict UTF-8 only (Contract 8).
- ~~`aiofiles`~~ — not a dependency; use `asyncio.to_thread`.

---

## Implementation Notes

### Pattern to Follow
```python
def read_line_range(path: Path, start_line: int, end_line: int, *, max_line_bytes: int) -> RangeRead:
    lines: list[str] = []; line_no = 0; eof = False
    with open(path, "rb", buffering=1 << 16) as fh:
        while True:
            raw = fh.readline(max_line_bytes + 1)
            if not raw:
                eof = True; break
            line_no += 1
            if len(raw) > max_line_bytes and not raw.endswith(b"\n"):
                raise LineTooLargeError(line_no, len(raw))
            if line_no < start_line:
                continue
            try:
                lines.append(raw.decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise InvalidEncodingError(line_no) from exc
            if line_no >= end_line:
                eof = fh.peek(1) == b"" if hasattr(fh, "peek") else False
                break
    if line_no < start_line:
        raise RangeOutOfBoundsError(start_line, line_no)
    return RangeRead(lines=lines, actual_end=min(end_line, line_no), eof=eof)
```

```python
# budget fit inside source_read
envelope = measure_json_bytes(SourceResult(path=rel, sha256=digest, size_bytes=size, start_line=start,
                                           end_line=start, content="", truncated=False, next_line=None, eof=False).model_dump(mode="json"))
budget = self.policy.max_result_bytes - envelope - 32          # slack for the wider numbers
used = 0; kept: list[str] = []
for i, line in enumerate(rr.lines):
    cost = len(json.dumps(line, ensure_ascii=False).encode("utf-8")) - 2
    if used + cost > budget:
        if i == 0:
            return self._error("source_read", "line_too_large", ..., details={"line": start + i, "bytes": len(line.encode())})
        break
    kept.append(line); used += cost
```

### Key Constraints
- Blocking I/O only inside `asyncio.to_thread` (Contract 7).
- Memory is bounded by `max_line_bytes + chunk size`, never by file
  length: a 200 MB single-line fixture must fail with `line_too_large`
  using < 8 MB RSS growth (measure with `resource.getrusage` in the test
  or `tracemalloc` peak).
- Identity check before AND after every scan (Contract 6).
- Thresholds are strict `>` (351 lines is large, 350 is not; 64,001
  bytes is large, 64,000 is not).
- Keep every helper synchronous & stdlib-only so TASK-3088's hook can
  import `count_lines_bounded` without pulling pydantic (put helpers ABOVE
  the toolkit class and keep the toolkit's pydantic imports at module top
  — the hook will import the helper module via
  `importlib` after checking cost; if that turns out too heavy, TASK-3088
  copies the 20-line helper; do not pre-optimise here).

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/repo/toolkit.py:154-198` — `_error`/`_rel`/`_resolve_for_read` conventions to mirror.
- `packages/ai-parrot/src/parrot/tools/repo/schemas.py:15-24` — how argument schemas describe line ranges (`ge=1`).

---

## Acceptance Criteria

- [ ] Line boundaries: 349/350/351-line files → `is_large` False/False/True; byte boundaries 63,999/64,000/64,001 → False/False/True (with `max_lines` and `large_file_bytes` tested independently by setting the other very high).
- [ ] Large file + no range → `range_required`, `content` absent, details include an example range.
- [ ] `source_read(path, 1, 351)` on a 1,000-line file → `range_too_large`; `(1, 350)` → 350 complete lines, `next_line == 351`, `truncated False`, `eof False`.
- [ ] `end_line` beyond EOF clamps and reports the actual end with `eof True`, `next_line None`; `start_line` beyond EOF → `range_out_of_bounds`.
- [ ] Budget: `max_result_bytes=4096` on 100 lines of 100 chars returns fewer than 100 complete lines, `truncated True`, `next_line` = first omitted line; the result's compact JSON is ≤ 4096 bytes.
- [ ] A single 5,000-byte line with a 4,096 budget → `line_too_large` with its line number and size; never a partial line.
- [ ] CRLF and missing-final-newline content round-trips byte-exact (`content.encode() == original slice`).
- [ ] Empty file → `content ""`, `eof True`, `end_line 0`.
- [ ] Stale hash → `stale_revision`; file modified between hash and read (monkeypatched helper) → `concurrent_modification`.
- [ ] Binary (NUL) → `binary_file`; invalid UTF-8 → `invalid_encoding` with line number.
- [ ] Symlink / FIFO (`os.mkfifo`) / directory / `.env` / `../x` → correct codes; `.env.example` readable.
- [ ] 200 MB single-line fixture (created sparse via `truncate` + a few bytes, or written in chunks to tmp) → `line_too_large` with bounded peak memory.
- [ ] Module source has no `read_text(`, `.read()`, `readlines(`.
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_reader.py -v`; lint clean; log in `artifacts/logs/TASK-3082-pytest.log`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/tool_optimizations/test_reader.py
import json, os, tracemalloc
from pathlib import Path
import pytest
from parrot_tools.tool_optimizations.reader import BoundedSourceToolkit, count_lines_bounded, read_line_range, LineTooLargeError
from parrot_tools.tool_optimizations.policy import measure_json_bytes

def _lines(tmp_path: Path, n: int, width: int = 10, name="f.py", eol="\n") -> Path:
    p = tmp_path / name; p.write_bytes(eol.join(f"l{i:0{width}d}" for i in range(1, n + 1)).encode() + eol.encode()); return p

@pytest.mark.parametrize("n,large", [(349, False), (350, False), (351, True)])
async def test_line_threshold(tmp_path, n, large):
    _lines(tmp_path, n)
    info = await BoundedSourceToolkit(repo_root=tmp_path, large_file_bytes=10**9).source_info("f.py")
    assert info.is_large is large and info.range_required is large

@pytest.mark.parametrize("size,large", [(63_999, False), (64_000, False), (64_001, True)])
async def test_byte_threshold(tmp_path, size, large):
    (tmp_path / "f.py").write_bytes(b"x" * size)
    info = await BoundedSourceToolkit(repo_root=tmp_path, max_lines=10**9).source_info("f.py")
    assert info.is_large is large

async def test_large_requires_range_without_content(tmp_path):
    _lines(tmp_path, 1000)
    res = await BoundedSourceToolkit(repo_root=tmp_path).source_read("f.py")
    assert res.status == "error" and res.error.code == "range_required" and "content" not in res.data
    ok = await BoundedSourceToolkit(repo_root=tmp_path).source_read("f.py", 1, 350)
    assert ok.next_line == 351 and ok.content.count("\n") == 350 and ok.eof is False

async def test_budget_returns_complete_lines_only(tmp_path):
    _lines(tmp_path, 100, width=100)
    res = await BoundedSourceToolkit(repo_root=tmp_path, max_result_bytes=4096).source_read("f.py", 1, 100)
    assert res.truncated and res.next_line == res.end_line + 1 and res.content.endswith("\n")
    assert measure_json_bytes(res.model_dump(mode="json")) <= 4096

async def test_single_long_line_is_reported_not_cut(tmp_path):
    (tmp_path / "f.py").write_bytes(b"y" * 5000 + b"\n")
    res = await BoundedSourceToolkit(repo_root=tmp_path, max_result_bytes=4096).source_read("f.py")
    assert res.error.code == "line_too_large" and res.error.details["line"] == 1

async def test_crlf_and_no_final_newline_roundtrip(tmp_path):
    raw = b"a\r\nb\r\nc"; (tmp_path / "f.py").write_bytes(raw)
    res = await BoundedSourceToolkit(repo_root=tmp_path).source_read("f.py")
    assert res.content.encode() == raw and res.eof is True and res.next_line is None

async def test_stale_hash_rejected(tmp_path):
    _lines(tmp_path, 10)
    res = await BoundedSourceToolkit(repo_root=tmp_path).source_read("f.py", 1, 5, expected_sha256="0" * 64)
    assert res.error.code == "stale_revision"

def test_bounded_allocation_on_huge_single_line(tmp_path):
    p = tmp_path / "huge.py"
    with open(p, "wb") as fh:
        for _ in range(200): fh.write(b"z" * (1 << 20))
    tracemalloc.start()
    with pytest.raises(LineTooLargeError):
        read_line_range(p, 1, 1, max_line_bytes=64_000)
    _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    assert peak < 8 * (1 << 20)

def test_no_whole_file_reads_in_source():
    import inspect, parrot_tools.tool_optimizations.reader as m
    src = inspect.getsource(m)
    assert "read_text(" not in src and ".read()" not in src and "readlines(" not in src
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-3079 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/tool-optimizations.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3082-bounded-source-reader.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
