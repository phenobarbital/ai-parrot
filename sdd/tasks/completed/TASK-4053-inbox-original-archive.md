# TASK-4053: Archive originals and preserve source provenance

**Feature**: FEAT-626 — wikitoolkit inbox autonomous ingestion
**Spec**: `sdd/specs/wikitoolkit-new-ingestion.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4047
**Assigned-to**: unassigned

## Context

Implements spec §3 M6 archive for FEAT-626. Source contracts reverified at `18c22a3fd1af1ccf6692be6f795388189e295a76`.
This is a planning artifact; implementation occurs through `$sdd-start` in the feature worktree.

## Scope

- AC9: Implement deterministic date-stamped destinations and -N collision suffixes without overwriting. Reject unsafe computed date path components. Use os.replace with EXDEV-only shutil.move fallback, then verify destination before git operations.
- Stage only tracked originals with git -C root rm --cached --quiet -- <relative path>. Use list argv, never shell=True or git commit. Git absence/failure returns staged_git=False without undoing an otherwise successful move.
- AC21: repoint_source calls update_source_uri after the destination exists, preserving source/external identity; log FileNotFoundError/ValueError without attempting to unarchive. The processor owns archived_to/archived_at metadata and assigns ArchiveResult.rejected from its known routing decision (the fixed archive_original signature has no rejected argument).

**NOT in scope**: unrelated refactors, dependency changes, provider SDK calls, MCP implementation, or changes outside the declared files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/archive.py` | CREATE | Scoped M6 archive deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/inbox/test_archive.py` | CREATE | Focused tests/fixtures |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from datetime import date
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
from parrot.knowledge.wiki.inbox.archive import archive_destination, archive_original, repoint_source
```
Verified: planned in TASK-4053: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/archive.py#archive_destination; planned in TASK-4053: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/archive.py#archive_original; planned in TASK-4053: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/archive.py#repoint_source.

```python
from parrot.knowledge.wiki.inbox.models import ArchiveResult
```
Verified: planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#ArchiveResult.

```python
from parrot.knowledge.wiki.sources import SourceCollectionManager
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:108.

```python
from pathlib import Path
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import errno
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import logging
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import os
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import pytest
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import shutil
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import subprocess
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).


### Existing Signatures to Use

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:108
class SourceCollectionManager:
    _MANIFEST_FILENAME: str = '.manifest.json'
    def __init__(
        self,
        sources_dir: Path,
        db_path: Path | None = None,
        backend: Literal["sqlite", "json", "arangodb"] = "sqlite",
        arango_db: Any | None = None,
        arango_store: Any | None = None,
        *,
        busy_timeout: float = 15.0,
    ) -> None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager.get_source`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:514
    def get_source(self, source_id: str) -> SourceManifestEntry | None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager.update_source_uri`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:948
    def update_source_uri(self, source_id: str, new_uri: Path | str) -> SourceManifestEntry | None:
```


### Does NOT Exist

- SourceCollectionManager.move_source/rename_source do not exist; use update_source_uri.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/inbox/archive.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/test_archive.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager.get_source",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager.update_source_uri"
  ]
}
```

## Implementation Notes

Consumes ArchiveResult from TASK-4047.

Follow Python 120-column black formatting, strict annotations and Google-style docstrings. Keep I/O off the event loop. Merge imports into the existing import groups; do not duplicate them. All FILL IN markers are planning-only and must be removed from completed implementation.

## Implementation Blueprint

### Steps (in order)

1. Reverify the quoted contracts and dependency outputs before editing — because concurrently landing features may move anchors.
2. Apply the declared per-file blocks and complete only the bounded gaps in Scope — because public signatures and ownership are fixed.
3. Implement the named failure-path tests using temporary resources and fake model responses — because success-only coverage misses the lifecycle guarantees.
4. Run the exact Validation Commands and lint touched Python files — because unchanged defaults and failure behavior are the acceptance evidence.

### `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/archive.py` (CREATE)

```python
"""Date-stamped original archiving and git index bookkeeping."""
from datetime import date
import errno
import logging
import os
from pathlib import Path
import shutil
import subprocess
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.inbox.models import ArchiveResult
logger = logging.getLogger(__name__)

def archive_destination(archive_dir: Path, source: Path, *, rejected: bool, rejected_subdir: str,
                        date_format: str, today: date) -> Path:
    """Choose a free date-stamped filename, adding -N before the extension."""
    # FILL IN: AC9 collision handling, path-component safety and rejection subdirectory.
    raise NotImplementedError

def is_git_tracked(root: Path, path: Path) -> bool:
    """Check git ls-files --error-unmatch; return False if git cannot run."""
    # FILL IN: list argv, relative path, OSError/nonzero handling (AC9).
    raise NotImplementedError

def stage_git_removal(root: Path, path: Path) -> bool:
    """Stage only an index deletion after the move; never raise or commit."""
    # FILL IN: exact git rm --cached --quiet -- path command (AC9).
    raise NotImplementedError

def archive_original(root: Path, source: Path, destination: Path, *, stage_git: bool) -> ArchiveResult:
    """Move without overwrite, verify destination, then optionally stage removal."""
    # FILL IN: AC9 same/cross-filesystem move and verified git ordering.
    # Return rejected=False here; caller sets it using its known triage decision.
    raise NotImplementedError

def repoint_source(sources: SourceCollectionManager, source_id: str, destination: Path) -> None:
    """Repoint the manifest, logging recoverable source errors without undoing the move."""
    # FILL IN: update_source_uri; catch FileNotFoundError/ValueError only (AC21).
    raise NotImplementedError
```

**Why**: Move and verification precede git staging; neither git failures nor source repoint failures should delete the archived copy.

### `packages/ai-parrot/tests/knowledge/wiki/inbox/test_archive.py` (CREATE)

```python
"""Focused FEAT-626 regression and failure-path tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.inbox.archive import archive_destination, archive_original, repoint_source


def test_archive_destination_collision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Produce base, -1 and -2 paths; reject date-based directory traversal."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_archive_original_git_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tracked files stage deletion; untracked and missing git do not."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_archive_cross_filesystem_and_no_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover EXDEV fallback and destination collisions without data loss."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_archive_repoints_source_uri(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep source_id/external_id stable and make is_stale false for archived bytes."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_archive_never_commits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert exact git argv and unchanged git HEAD after a tracked move."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError
```

**Why**: Use temporary files and stub adapters; assert observable state and side effects, never call providers.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/archive.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/inbox/test_archive.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.

## Acceptance Criteria

- [ ] AC9: Implement deterministic date-stamped destinations and -N collision suffixes without overwriting. Reject unsafe computed date path components. Use os.replace with EXDEV-only shutil.move fallback, then verify destination before git operations.
- [ ] Stage only tracked originals with git -C root rm --cached --quiet -- <relative path>. Use list argv, never shell=True or git commit. Git absence/failure returns staged_git=False without undoing an otherwise successful move.
- [ ] AC21: repoint_source calls update_source_uri after the destination exists, preserving source/external identity; log FileNotFoundError/ValueError without attempting to unarchive. The processor owns archived_to/archived_at metadata and assigns ArchiveResult.rejected from its known routing decision (the fixed archive_original signature has no rejected argument).
- [ ] All declared tests pass; no unfinished implementation placeholders remain; touched Python files pass ruff check.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_archive.py -q`

Run in the activated repository environment; in a feature worktree set `PYTHONPATH=packages/ai-parrot/src`. Store test logs under `artifacts/logs/`.

## Test Specification

- Initialize only a tmp git repo; use per-command local identity for its initial fixture commit and never touch the working repository index.
- Check destination exists before any git call with spies. Exercise staging disabled, missing executable and nonzero exit.
- Archive helpers are synchronous and will be offloaded by the processor; use fixed date(2026,10,3).

## Agent Instructions

1. Use `$sdd-start TASK-4053`; let it provision the feature worktree. Do not implement on dev.
2. Read the spec and this task; verify dependencies are done in `sdd/tasks/index/wikitoolkit-new-ingestion.json`.
3. Reverify source contracts before writing. Record discovered drift and refresh this task before relying on a changed API.
4. Implement only declared files. Run the focused validation commands and the normal lint gate.
5. Commit scoped implementation and finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move task files or use legacy close_task.sh.

## Completion Note

Pending. Populated by the finalizer from implementation and validation evidence.


### Completion Note (orchestrator)
Seat: sonnet (native). Merged cleanly; merge-tier green (70 passed). No defects confirmed.
