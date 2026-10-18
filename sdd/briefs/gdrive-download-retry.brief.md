---
kind: brief
slug: gdrive-download-retry
key: 57bfa5240cab
base_branch: dev
source:
  type: ledger
  ref: issue:57bfa5240cab
  url: null
jira_issue_key: null
ledger_issue: issue:57bfa5240cab
created: 2026-10-18T09:00:00+00:00
---

# Brief: gdrive download retry can duplicate bytes; resumable chunk 429 ignores Retry-After

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/gdrive-download-retry/tasks/. -->

## Problem

Two bugs in `GoogleDriveFileManager` (gdrive.py), discovered in FEAT-608 code review:

1. **Download retry duplicates bytes**: `download_file()` wraps
   `files_download(pipe_to=_AsyncSink(destination))` inside `_retrying()`. If a
   retryable error occurs mid-stream, the retry re-downloads from byte 0 but the
   `BinaryIO` stream position is not reset → the same bytes are appended again.
   The `Path` variant (`download_file=str(...)`) overwrites the file on each
   attempt and is safe.

2. **Resumable upload chunk 429 ignores Retry-After**: The `_put()` closure
   inside `_upload_resumable()` raises `GoogleDriveFileManagerError(status_code=code)`
   on a 429 response. This error has no `.res` attribute, so
   `_retry_after_seconds()` (which reads `error.res.headers`) returns `None` and
   falls back to exponential backoff instead of honoring the server's
   `Retry-After` header.

## Root cause

**Bug 1** — `gdrive.py:641-644`: `_retrying` re-invokes the download lambda.
`_AsyncSink.write()` at L78-79 delegates to `target.write(chunk)` which appends
at the current stream position. There is no seek-back logic. The `Path` code
path at L636-639 is safe because `download_file=` overwrites the file.

**Bug 2** — `gdrive.py:785-790`: `_put()` creates a
`GoogleDriveFileManagerError(status_code=code)` from the `res` object returned
by `send_raw(full_res=True)`, but does NOT attach `res` to the exception.
`_retry_after_seconds()` at L400 reads `getattr(error, "res", None)` → `None`.
The response object carrying the `Retry-After` header is discarded.

## Research findings

- `_retrying` (L443-460) is the single retry loop for all Drive operations.
- `_retry_after_seconds` (L398-417) reads `error.res.headers["Retry-After"]`.
- `FakeHTTPError` in tests (L23-37 of `_gdrive_fakes.py`) already sets `.res`
  on the exception, confirming the expected interface.
- `_is_rate_limited_403` (L420-427) also reads `error.res.json` — same pattern.
- `GoogleDriveFileManagerError` (L64-69) has only `status_code`, no `res`.
- Blast radius of `_retrying`: 15+ callers including `download_file`,
  `_upload_resumable`, `_upload_small`, `list_files`, `copy_file`, etc.
- Related open issue: `issue:25a6ca04919c` (ruff residuals, minor).

## Assumptions

- The fix for Bug 1 should seek back to the initial stream position on retry
  when the stream is seekable, and mark the operation as `idempotent=False`
  (no retry) when the stream is not seekable, to avoid silent corruption.
- The fix for Bug 2 should attach the response object to the raised error so
  `_retry_after_seconds` can read `Retry-After` from it.

## Fix plan

1. **HOTFIX-57bfa5240cab-1**: Fix both bugs in `gdrive.py` and add regression
   tests to `test_gdrive_filemanager.py`.

## Validation commands

- `pytest packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py -q`
