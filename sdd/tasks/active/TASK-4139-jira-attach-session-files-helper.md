# TASK-4139: `_attach_session_files` — resolve, pre-flight and upload handles, best-effort

**Feature**: FEAT-639 — Session file store and Jira attachments for binary documents
**Spec**: `sdd/specs/jiratoolkit-docx-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4138, TASK-4128
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, the core of it. This is the single shared helper both attachment
tools route through — the fix for the two divergent paths described in spec §1
(`jira_add_attachment` lets exceptions escape; the loop inside `jira_add_comment`
swallows them into `{"file", "error"}`).

It is also where pre-flight lives, so the model gets `empty_file` or `too_large`
instead of an opaque `JIRAError` raised only after the round trip
(`jira/client.py:1198-1202`).

---

## Scope

- Implement `JiraToolkit._attach_session_files(issue, file_ids) -> List[AttachmentResult]`.
- Resolve each handle through `SessionFileStore.resolve()`, mapping its exceptions to
  the matching `AttachmentErrorCode` by their `code` attribute.
- Pre-flight in order: unresolvable → empty → oversize against
  `await self._max_attachment_bytes()`. A rejected file is never uploaded.
- Upload survivors off the event loop; map Jira failures to `forbidden` (401/403),
  `rejected` (other 4xx) or `transport_error`, with `_bounded_detail`.
- Return exactly one `AttachmentResult` per input, order preserved. Never raise.
- Write tests for every error code and for ordering.

**NOT in scope**: the two tools' signatures (TASK-4140 / TASK-4141) · the models
(TASK-4138) · the store (TASK-4128).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | Add the shared helper |
| `packages/ai-parrot-tools/tests/unit/test_jira_attach_session_files.py` | CREATE | Per-code and ordering tests |

---

## Codebase Contract (Anti-Hallucination)

> Line numbers verified against `1f74e23c7` on 2026-10-08, **after FEAT-637 merged**.
> Every one of them drifted from the spec's original §6 values — re-verify before editing.

### Verified Imports
```python
from parrot.interfaces.file.session import (        # created by TASK-4128
    SessionFileStore, SessionFileError, UnknownHandle, OutsideSandbox, MissingBlob,
)
# from TASK-4138, in this same file:
#   AttachmentResult, AttachmentErrorCode, _bounded_detail, DEFAULT_MAX_ATTACHMENT_BYTES
from parrot.utils.helpers import current_context    # verified: packages/ai-parrot/src/parrot/utils/helpers.py:58
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/file/session.py  (TASK-4128 / TASK-4129)
class SessionFileError(Exception):
    code: str                      # "unknown_handle" | "outside_sandbox" | "missing_file"
class SessionFileStore:
    async def resolve(self, session_id: str, file_id: str) -> tuple[SessionFileRecord, Path]

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py  (TASK-4138)
    async def _max_attachment_bytes(self) -> int
class AttachmentResult(BaseModel):
    file_id: str; ok: bool; filename: Optional[str]; attachment_id: Optional[str]
    size: Optional[int]; error_code: Optional[AttachmentErrorCode]; detail: Optional[str]

# the existing upload call this helper replaces (verified 1f74e23c7):
    async def jira_add_attachment(self, issue: str, attachment: str) -> Dict[str, Any]:  # line 2169
        def _run(): return self.jira.add_attachment(issue=issue, attachment=attachment)  # line 2176

# .venv/lib/python3.12/site-packages/jira/client.py (jira==3.10.5)
def add_attachment(self, issue, attachment: str | BufferedReader,
                   filename: str | None = None) -> Attachment:          # line 1119
    #  Content-Type is HARD-CODED to application/octet-stream           # line 1160
    if jira_attachment.size == 0: raise JIRAError(...)                  # lines 1198-1202
from jira.exceptions import JIRAError   # carries .status_code and .text
```

### Does NOT Exist
- ~~a MIME-aware or custom multipart upload~~ — spec §1 Non-Goals and AC15: this feature
  posts through `jira.JIRA.add_attachment` only. Do NOT write an `aiohttp` upload here
- ~~`SessionFileStore.resolve` returning `None` for a bad handle~~ — it RAISES; map the
  exception's `.code`, never check for None
- ~~a `quota_exceeded` code~~ — not in `AttachmentErrorCode` (spec AC16)
- ~~`JIRAError.status`~~ — the attribute is `.status_code`
- ~~an existing shared attachment helper~~ — today the logic is duplicated between
  `jira_add_attachment` (:2169) and the loop inside `jira_add_comment` (:2578-2600)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/unit/test_jira_attach_session_files.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit",
    "sym:packages/ai-parrot/src/parrot/interfaces/file/session.py#SessionFileStore",
    "sym:packages/ai-parrot/src/parrot/utils/helpers.py#current_context"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Never raise. Every failure becomes an `AttachmentResult` with `ok=False`.
- Resolve the session once per call from `current_context()`; with none bound, every
  input gets `no_session` (spec AC13).
- The size limit is awaited **once** per call, not per file.
- `self.logger` for diagnostics; never log a resolved path (spec §7).

---

## Implementation Blueprint

### Steps (in order)
1. Resolve the session id once and short-circuit to `no_session` — *why*: AC13, and it
   avoids N identical failures doing N resolutions.
2. Await the size limit once — *why*: `attachment_meta()` is an HTTP call.
3. Loop: resolve → pre-flight → upload, appending exactly one result per input — *why*:
   AC4 requires one entry per handle, in order.
4. Map Jira exceptions last — *why*: the status-code mapping is the part most likely to
   be written loosely, and AC10 constrains what reaches the model.

### `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def jira_add_attachment(self, issue: str, attachment: str) -> Dict\[str, Any\]:' packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py)
# BEFORE — insert above `async def jira_add_attachment(` (verified: jiratoolkit.py:2169),
#          above its @requires_permission / @tool_schema decorator lines
    async def _attach_session_files(
        self, issue: str, file_ids: Sequence[str]
    ) -> List[AttachmentResult]:
        """Resolve, pre-flight and upload each handle. Best-effort, never raises.

        Per handle, in order: resolve via SessionFileStore (unknown_handle /
        outside_sandbox / missing_file), then size checks (empty_file, too_large
        against await self._max_attachment_bytes()), then upload off the event loop.
        Jira failures map to forbidden / rejected / transport_error with a bounded,
        sanitized detail. Returns exactly one AttachmentResult per input, order preserved.
        """
        ctx = current_context()
        session_id = getattr(ctx, "session_id", None) if ctx else None
        if not session_id:
            return [
                AttachmentResult(file_id=fid, ok=False, error_code="no_session",
                                 detail="No session is bound to this request.")
                for fid in file_ids
            ]
        limit = await self._max_attachment_bytes()
        store = self._session_store()
        results: List[AttachmentResult] = []
        for fid in file_ids:
            # FILL IN: try store.resolve(session_id, fid) -> (record, path);
            # except SessionFileError as exc -> append ok=False with
            # error_code=exc.code and detail=_bounded_detail(exc); continue.
            # Then: record.size == 0 -> "empty_file"; record.size > limit ->
            # "too_large" with the limit named in detail. Neither uploads.
            # Then upload: await asyncio.to_thread(
            #     self.jira.add_attachment, issue=issue, attachment=str(path))
            # and append ok=True with filename/attachment_id/size from the returned
            # Attachment (getattr with the record as fallback).
            # Map JIRAError: .status_code in (401, 403) -> "forbidden";
            # other 4xx -> "rejected"; anything else -> "transport_error".
            # detail is ALWAYS _bounded_detail(...).
            # bounded by AC4 (one entry per input, order preserved), AC8 (rejected
            # files never reach the client) and AC10 (<= 500 chars, never a raw body)
            raise NotImplementedError
        return results

    def _session_store(self) -> SessionFileStore:
        """Lazily build the session store shared by this toolkit instance."""
        # FILL IN: cache on self; the store is stateless per session so one instance
        # is safe — bounded by "never cache a session id on the toolkit"
        raise NotImplementedError
```
**Why this shape**: the `no_session` short-circuit returns one result per input rather
than a single error, so callers never have to special-case it. Awaiting the limit once
and resolving the session once keeps an N-file call to one extra HTTP probe. Mapping
`exc.code` straight through is only correct because TASK-4128 chose those exact strings
— if a code is missing from `AttachmentErrorCode`, fix the literal, do not invent a
translation.

### FILL IN checklist
- [ ] per-handle loop body — resolve, pre-flight, upload, map; bounded by AC4, AC8, AC10
- [ ] `_session_store` caching; bounded by "never cache a session id on the toolkit"
- [ ] test bodies; bounded by the Test Specification

---

## Acceptance Criteria

- [ ] N handles in produce N results out, in input order (spec AC4)
- [ ] An empty file yields `empty_file` and `self.jira.add_attachment` is **not** called (spec AC8)
- [ ] An oversize file yields `too_large` against the configured/discovered limit, not uploaded (spec AC8)
- [ ] An unknown handle yields `unknown_handle`; a traversal handle yields `outside_sandbox` (spec AC6)
- [ ] With no bound session every input yields `no_session` (spec AC13)
- [ ] A Jira 403 yields `forbidden`; `detail` is <= 500 chars and is not a raw body (spec AC10)
- [ ] Good and bad handles together: successes stand, failures are named — nothing raises
- [ ] No `aiohttp` call to Jira and no custom endpoint appear in the diff (spec AC15)
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/unit/test_jira_attach_session_files.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/unit/test_jira_attach_session_files.py
import pytest


class TestAttachSessionFiles:
    async def test_one_result_per_handle_in_order(self, toolkit, bound_session):
        """Spec AC4."""
        # FILL IN

    async def test_empty_file_not_uploaded(self, toolkit, bound_session):
        """Spec AC8 — the Jira client must not be called at all."""
        # FILL IN: assert the fake client recorded zero add_attachment calls

    async def test_oversize_not_uploaded(self, toolkit, bound_session):
        # FILL IN: limit patched low; assert error_code == "too_large"

    async def test_unknown_and_traversal_handles(self, toolkit, bound_session):
        # FILL IN: assert "unknown_handle" and "outside_sandbox"

    async def test_no_session_marks_every_input(self, toolkit):
        """Spec AC13."""
        # FILL IN

    async def test_jira_403_maps_to_forbidden_with_bounded_detail(self, toolkit, bound_session):
        """Spec AC10."""
        # FILL IN: raise JIRAError(status_code=403, text="<html>"+"x"*50000)

    async def test_mixed_handles_are_best_effort(self, toolkit, bound_session):
        # FILL IN: one good + one bad; nothing raises
```

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug jiratoolkit-docx-support --feature-id FEAT-639`)
2. Read spec §2 Data Models, §3 Module 3 and §6 before writing code.
3. **Verify the Codebase Contract** — `jiratoolkit.py` moves often (FEAT-637 shifted every
   anchor once already). Re-run each `grep -c` and correct the line numbers in this file
   FIRST, then implement.
4. Check every `Depends-on` task is `done` in `sdd/tasks/index/jiratoolkit-docx-support.json`,
   then set this task `in-progress` and commit only that index file.
5. Implement from the blueprint; complete every `# FILL IN:`; never change a fixed signature.
6. Run the Validation Commands.
7. Commit only the files this task lists (never `git add .` / `-A`).
8. `scripts/sdd/close_task.sh TASK-4139 jiratoolkit-docx-support verified`

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any
