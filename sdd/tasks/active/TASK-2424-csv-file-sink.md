# TASK-2424: `CsvFileSink` - lock-free single-line append

**Feature**: FEAT-457 — Autonomous FormSchema Persistence (Standalone Forms)
**Spec**: `sdd/specs/formbuilder-formschema-persistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2418, TASK-2419, TASK-2420
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 8

---

## Context

The Microsoft-Forms case that motivated the whole feature: a survey whose
responses land as one appended row in a local file.

Two decisions constrain this task tightly (spec section 8, resolved):
- **No lock.** One write emits exactly one `\n`-terminated line in a single call. Concurrent
  workers can still interleave a long row; that is a documented, accepted limitation.
- **`.xlsx` is out of scope.** A workbook cannot be appended - it must be rewritten - which
  is irreconcilable with the above. Do NOT add an xlsx path.

Implements spec section 3 Module 8.

---

## Scope

- Create `services/sinks/csv_file.py` with `CsvFileSink(AbstractSubmissionSink)`.
- Declare capabilities exactly `{WRITE, PROVISION}` - deliberately NOT `EXTEND`, NOT `READ`, NOT `LIST`.
- Resolve the file path via `SinkAliasRegistry.contain(...)` so it cannot escape the alias's base directory.
- `ensure_target(form)`: when the file is absent, create it and write the header row from `column_names_for(form)`. When present, leave the header untouched.
- `write(...)`: serialize one row with the stdlib `csv` module into a string, then append it to the file in a single write call, newline-terminated.
- When the existing header lacks a column the form now produces, log a warning and place the extra values in trailing columns - never rewrite the header.
- Offload blocking file I/O off the event loop (`asyncio.to_thread`).
- Map `OSError` / permission / missing-directory failures to `SinkUnavailableError`.
- Write unit tests in `tests/unit/test_csv_file_sink.py` using `tmp_path`.

**NOT in scope**: `.xlsx` in any form (explicit Non-Goal, spec section 1). Any locking or file-coordination mechanism. Read-back or listing. Registration in the dispatch table (TASK-2426).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/csv_file.py` | CREATE | CSV append sink |
| `packages/parrot-formdesigner/tests/unit/test_csv_file_sink.py` | CREATE | Unit tests using tmp_path |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.
>
> Verified against `dev` on 2026-08-24. All paths are relative to the repo root.
> Line numbers shift as soon as anything above them changes — **re-`grep` before editing**.

### Verified Imports

```python
# Verified to resolve today (all stdlib / earlier tasks):
import asyncio, csv, io, logging
from pathlib import Path
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services.submissions import FormSubmission
# Created by earlier tasks in this spec:
from parrot_formdesigner.core.persistence import SinkCapability, CsvFileTarget    # TASK-2417
from parrot_formdesigner.services.sinks.base import (                             # TASK-2419
    AbstractSubmissionSink, SinkUnavailableError,
)
from parrot_formdesigner.services.sinks.mapper import (                           # TASK-2420
    flatten_submission, column_names_for,
)
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry           # TASK-2418
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:50
class FormSubmission(BaseModel):
    submission_id: str          # default_factory=lambda: str(uuid.uuid4())
    form_uid: uuid.UUID         # REQUIRED (FEAT-389 / TASK-1979)
    form_id: str
    form_version: str
    data: dict[str, Any]
    is_valid: bool
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    created_at: datetime        # default_factory -> datetime.now(timezone.utc)
    tenant: str | None = None
    user_id: str | None = None
    username: str | None = None
    org_id: int | None = None
    submitted_at: datetime | None = None
    ip: str | None = None
    user_agent: str | None = None
    locale: str | None = None
    root_submission_id: str | None = None
    revision: int | None = None
    context: dict[str, Any] | None = None
```

### Does NOT Exist

- ~~`openpyxl` in `parrot-formdesigner`~~ - NOT a dependency. `.xlsx` is an explicit Non-Goal for v1 (spec section 1). Do not add an xlsx sink.
- ~~`AbstractSubmissionSink` / `FormSubmissionSink` / `SubmissionSink`~~ - no sink abstraction exists anywhere in `parrot-formdesigner` before TASK-2419. `FormSubmissionStorage` (`packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:118`) is a **plain class, NOT an ABC** - there is no existing interface to implement.
- ~~`aiofiles`~~ - NOT a dependency of `parrot-formdesigner` (check `packages/parrot-formdesigner/pyproject.toml:33-47`). Use `asyncio.to_thread` with stdlib file I/O instead of adding a dependency.
- ~~a `LocalBlobStorage`-style base for CSV~~ - `packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py:476` handles opaque blobs keyed by reference, not appendable tabular files. It is a shape reference only; do not subclass it.

---

## Implementation Notes

### Pattern to Follow

One write == one line, emitted in a single call. That single property is what
makes the lock-free choice defensible:

```python
def _render_line(self, row: dict[str, Any], header: list[str]) -> str:
    buf = io.StringIO()
    csv.writer(buf, delimiter=self._target.delimiter).writerow(
        [row.get(col, "") for col in header]
    )
    return buf.getvalue()            # already newline-terminated by csv.writer

async def write(self, submission, payload):
    line = self._render_line(payload, self._header)
    await asyncio.to_thread(self._append, line)      # ONE write() syscall
    return submission.submission_id

def _append(self, line: str) -> None:
    with open(self._path, "a", newline="", encoding="utf-8") as fh:
        fh.write(line)
```

### Key Constraints

- `EXTEND` must NOT be in `capabilities` - an existing header is never rewritten.
- Exactly one `fh.write()` per submission. Do not use `csv.writer` directly on the file handle (it may emit multiple writes).
- Path containment is mandatory - go through `SinkAliasRegistry.contain`, never `Path` joins.
- No blocking I/O on the event loop.
- Header order must match `column_names_for(form)` exactly, so the file stays readable.
- Log a warning (with the form_uid and the missing columns) on header drift - silence here would look like success.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py` - `column_names_for` gives the header (TASK-2420)
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/sink_aliases.py` - `contain()` for path safety (TASK-2418)
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py:476` - `LocalBlobStorage`, shape reference only

---

## Acceptance Criteria

- [ ] `capabilities == frozenset({WRITE, PROVISION})` - no READ, no LIST, no EXTEND
- [ ] A fresh file gets a header row matching `column_names_for(form)`
- [ ] Two submissions produce header + exactly 2 data lines
- [ ] An existing file's header is byte-identical after a write with a changed form
- [ ] Header drift logs a warning and does not rewrite the header
- [ ] `read()` and `list_revisions()` raise `SinkNotCapableError` (inherited default)
- [ ] A path escaping the base dir raises before any file is touched
- [ ] A permission error raises `SinkUnavailableError`
- [ ] One submission results in exactly one `write()` call (asserted with a patched handle)
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_csv_file_sink.py -v` passes
- [ ] `ruff` and `mypy` clean

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_csv_file_sink.py
import pytest

from parrot_formdesigner.core.persistence import SinkCapability
from parrot_formdesigner.services.sinks.base import (
    SinkNotCapableError, SinkUnavailableError,
)


class TestProvision:
    async def test_creates_header(self, csv_sink, csv_path, form):
        await csv_sink.ensure_target(form)
        assert csv_path.read_text().splitlines()[0].startswith("submission_id")

    async def test_existing_header_untouched(self, csv_sink, csv_path, form, form_with_extra_field):
        await csv_sink.ensure_target(form)
        header_before = csv_path.read_text().splitlines()[0]
        await csv_sink.ensure_target(form_with_extra_field)
        assert csv_path.read_text().splitlines()[0] == header_before


class TestWrite:
    async def test_two_submissions_two_lines(self, csv_sink, csv_path, form, submission_factory):
        await csv_sink.ensure_target(form)
        await csv_sink.write(submission_factory(), {})
        await csv_sink.write(submission_factory(), {})
        assert len(csv_path.read_text().strip().splitlines()) == 3

    async def test_single_write_call(self, csv_sink, form, submission, monkeypatch):
        calls = []
        monkeypatch.setattr(csv_sink, "_append", lambda line: calls.append(line))
        await csv_sink.write(submission, {})
        assert len(calls) == 1


class TestCapabilities:
    def test_write_only(self, csv_sink):
        assert csv_sink.capabilities == frozenset({
            SinkCapability.WRITE, SinkCapability.PROVISION
        })

    async def test_read_not_capable(self, csv_sink):
        with pytest.raises(SinkNotCapableError):
            await csv_sink.read("abc")


class TestSafety:
    async def test_permission_error_maps_unavailable(self, readonly_csv_sink, form):
        with pytest.raises(SinkUnavailableError):
            await readonly_csv_sink.ensure_target(form)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** - verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** - before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source).
   - Confirm every class/method in "Existing Signatures" still has the listed attributes.
   - If anything has changed, update the contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without
     verifying it exists.
4. **Update status** in `sdd/tasks/index/formbuilder-formschema-persistency.json` ->
   `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** -> `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
