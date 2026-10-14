# TASK-4337: Define repository cache models and async advisory lock

**Feature**: FEAT-672 - GitHubReviewer local clone + wikitoolkit graph
**Spec**: `sdd/specs/github-reviewer-local-repo-wiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement spec §3 M2 within the approved external-plane design. Define repository cache models and async advisory lock.
This task changes only the files below. No provider SDK calls or new dependencies.

## Scope

- Define RepoCachePaths and BuildOutcome in repo_cache.py as specified — placing shared models first breaks the cache/runner task cycle.
- Implement repo_lock with nonblocking flock and asyncio.sleep polling — contended acquisition must not block the event loop.
- Test separate-process exclusion, timeout, exception/cancellation release, and the fcntl-unavailable no-op with tmp_path fixtures.

**NOT in scope**: PR-head checkout, programmatic build API extraction, shared sidecars,
and changes belonging to other tasks. This task does not alter the spec.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py` | CREATE | Define repository cache models and async advisory lock |
| `packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py` | CREATE | Focused behavioral tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from pydantic import BaseModel
import pytest
```

Third-party dependencies click, pydantic and pytest are declared in packages/ai-parrot/pyproject.toml. Standard-library imports need no dependency additions. Imports of feature-created symbols are provided by the explicitly listed prerequisites, not claimed to exist at planning time. Verify any additional implementation imports before use.


### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:76
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]:
```

### Does NOT Exist

- `build_wiki()` or `run_build()` repository-scan API: use the CLI subprocess.
- `GitToolkit.checkout_ref()` and clone `sha=`/`ref=`: PR heads are out of scope.
- `WIKI_ROOT` or `PARROT_WIKI_ROOT`: pass explicit paths/config/store.
- `CodeStructuralToolkit(repository=...)`: constructor takes root/store/config.
- New repo_cache/repo_build symbols and seven GITHUB_REVIEW wiki settings are absent at planning time; rely on prerequisites before importing them.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#wiki_write_lock"
  ]
}
```

## Implementation Notes

Use a guarded stdlib fcntl import as in project.py. A lock is owned through its open descriptor and released in finally. Keep the cache-entry lock distinct from plane/wiki.lock. Do not add RepoWikiCache yet; the lifecycle task extends this module. Use multiprocessing for the cross-process test, with bounded joins and cleanup.

**Parallelism**: Independent foundation: creates repo_cache.py models and repo_lock plus test_repo_cache.py; imports no WikiBuildRunner or RepoWikiCache.

## Implementation Blueprint

### Steps (in order)

1. Define RepoCachePaths and BuildOutcome in repo_cache.py as specified — placing shared models first breaks the cache/runner task cycle.
2. Implement repo_lock with nonblocking flock and asyncio.sleep polling — contended acquisition must not block the event loop.
3. Test separate-process exclusion, timeout, exception/cancellation release, and the fcntl-unavailable no-op with tmp_path fixtures.

### `packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py` (CREATE)

```python
"""Repository cache data contracts and asynchronous process locking."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from pydantic import BaseModel

class RepoCachePaths(BaseModel):
    """Resolved layout for one canonical repository."""
    slug: str
    repository: str
    clone_dir: Path
    plane_dir: Path
    lock_path: Path

class BuildOutcome(BaseModel):
    """Outcome of one bounded wiki build subprocess."""
    ok: bool
    returncode: int
    timed_out: bool
    duration_s: float
    stderr_tail: str

@asynccontextmanager
async def repo_lock(lock_path: Path, *, timeout: float) -> AsyncIterator[bool]:
    """Acquire an advisory process lock without blocking the event loop."""
    # FILL IN: guarded fcntl import and nonblocking retries, bounded by AC-11.
    # FILL IN: yield acquisition result and release descriptor in finally.
```

**Why**: Both new modules consume the same Pydantic contracts; the foundation imports neither consumer.

### `packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py` (CREATE)

```python
"""Hermetic behavioral tests for FEAT-672."""
from pathlib import Path
import pytest

async def test_repo_lock_is_exclusive_across_processes(tmp_path: Path) -> None:
    """Second acquirer gets `False` while the first holds it."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

async def test_repo_lock_does_not_block_event_loop(tmp_path: Path) -> None:
    """A contended acquire with timeout still lets other coroutines run."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

```

**Why**: These tests cover the spec failure modes without network, provider calls or shared conftest changes. Implement fixtures in this file.

Test scaffold imports `RepoCachePaths`, `BuildOutcome`, and `repo_lock` from
`parrot.knowledge.wiki.repo_cache` after creating that module in this task.
These are newly declared symbols, not existing base-branch imports.

### FILL IN checklist

- [ ] Define RepoCachePaths and BuildOutcome in repo_cache.py as specified — placing shared models first breaks the cache/runner task cycle.
- [ ] Implement repo_lock with nonblocking flock and asyncio.sleep polling — contended acquisition must not block the event loop.
- [ ] Test separate-process exclusion, timeout, exception/cancellation release, and the fcntl-unavailable no-op with tmp_path fixtures.
- [ ] Replace all blueprint placeholders with complete typed, documented implementation and assertions; no unfinished placeholders in delivered source.

## Acceptance Criteria

The feature criteria below apply to this task’s declared scope; cross-module portions are completed by their owning tasks.

- [ ] AC-11: Two concurrent deliveries for one repository, in one process and across two processes, produce one build and no lock error.
- [ ] All task-local tests pass; black formatting and ruff check are clean on changed Python files. No unrelated source changes.
- [ ] This foundation proves lock exclusion and event-loop responsiveness; coalesced build behavior in AC-11 is completed by the cache lifecycle task.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py -q`

## Test Specification

- `test_repo_lock_is_exclusive_across_processes`: Second acquirer gets `False` while the first holds it.
- `test_repo_lock_does_not_block_event_loop`: A contended acquire with timeout still lets other coroutines run.

## Agent Instructions

1. Use `$sdd-start TASK-4337` to provision the feature worktree; do not implement on dev.
2. Read the spec and ensure dependencies are done in `sdd/tasks/index/github-reviewer-local-repo-wiki.json`.
3. Reverify contracts and anchors, including prerequisite-created anchors; update stale task evidence before implementing.
4. Implement only declared files, run Validation Commands, and retain logs under artifacts/logs/.
5. Commit scoped code, then close with `scripts.sdd.finalize_task` and real TaskCompletionEvidence.
   Let the finalizer own the completion note and active-to-completed move; commit its SDD state separately.

## Completion Note

Pending implementation; the finalizer records evidence after validation.
