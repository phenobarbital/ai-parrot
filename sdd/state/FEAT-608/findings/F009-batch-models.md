---
id: F009
query_id: Q012
type: read
intent: batch.py — BatchItemResult/BatchSummary shared models the Drive manager should reuse
executed_at: 2026-09-25T22:53:40Z
duration_ms: 300
parent_id: null
depth: 0
---

# F009 — `batch.py` is backend-neutral by design; Drive can import it unchanged

## Summary

`parrot/interfaces/file/batch.py` (FEAT-603) declares `BatchState`,
`BatchErrorCode` (`not_found | throttled | timeout | auth | conflict |
invalid_path | io | unknown`), `BatchItemResult` and `BatchSummary.from_items`.
Its module docstring states it "deliberately has no Microsoft Graph
dependency so generic file-manager batch operations can use it with every
supported storage backend". The toolkit's `batch_upload` / `batch_download`
already consume these models (F011).

## Citations

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/interfaces/file/batch.py`
  lines: 1-18
  symbol: module docstring / `BatchErrorCode`
  excerpt: |
    """Batch result models shared by Graph managers and FileManagerToolkit (FEAT-603).
    This module deliberately has no Microsoft Graph dependency ..."""
    BatchErrorCode = Literal["not_found", "throttled", "timeout", "auth", "conflict", "invalid_path", "io", "unknown"]

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/interfaces/file/batch.py`
  lines: 21-38
  symbol: `BatchItemResult`
  excerpt: |
    index: int; source: str; destination: str; state: BatchState; ok: bool
    metadata: Optional[FileMetadata]; error: Optional[str]; error_code: Optional[BatchErrorCode]; status_code: Optional[int]; attempts: int

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/interfaces/file/batch.py`
  lines: 41-71
  symbol: `BatchSummary.from_items`
  excerpt: |
    @classmethod
    def from_items(cls, items: List[BatchItemResult], *, aborted: bool = False) -> "BatchSummary": ...
