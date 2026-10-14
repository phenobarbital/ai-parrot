# TASK-4339: Implement repository cache refresh recovery and eviction

**Feature**: FEAT-672 - GitHubReviewer local clone + wikitoolkit graph
**Spec**: `sdd/specs/github-reviewer-local-repo-wiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4336, TASK-4337, TASK-4338
**Assigned-to**: unassigned

## Context

Implement spec §3 M2 within the approved external-plane design. Implement repository cache refresh recovery and eviction.
This task changes only the files below. No provider SDK calls or new dependencies.

## Scope

- Append RepoWikiCache to the foundation module and import WikiBuildRunner locally during construction — repo_build imports BuildOutcome from this module.
- Validate a bare owner/name identity and resolve confined cache paths; validate persisted repository identity before reusing a hyphenated slug — distinct owner/name pairs can otherwise collide.
- Coalesce overlapping refreshes with the in-process lock and persisted successful generation checks under the process lock — serialization alone would run two builds.
- Validate origin and current/upstream branch before pulling; recover with exactly one re-clone on mismatch, corruption or pull failure — do not silently reuse another repository.
- Build under both locks, with prefer_gh=False and bounded git calls; require the complete marker and wiki.db before returning paths.
- Apply LRU eviction only to owned cache entries under safe locking; skip keep and busy entries, and warn without eviction for one oversized entry. Test all recovery and concurrency paths.

**NOT in scope**: PR-head checkout, programmatic build API extraction, shared sidecars,
and changes belonging to other tasks. This task does not alter the spec.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py` | MODIFY | Implement repository cache refresh recovery and eviction |
| `packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py` | MODIFY | Focused behavioral tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
import asyncio
import logging
from pathlib import Path
from typing import Any, Optional
from parrot.knowledge.wiki.repo_build import WikiBuildRunner
import pytest
```

Third-party dependencies click, pydantic and pytest are declared in packages/ai-parrot/pyproject.toml. Standard-library imports need no dependency additions. Imports of feature-created symbols are provided by the explicitly listed prerequisites, not claimed to exist at planning time. Verify any additional implementation imports before use.


### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1590
    async def clone_repo(
        self,
        repository: str,
        dest_dir: str,
        branch: Optional[str] = None,
        *,
        private: bool = False,
        depth: Optional[int] = None,
    ) -> Dict[str, Any]:
```

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1653
    async def pull_repo(
        self,
        repo_path: str,
        branch: Optional[str] = None,
    ) -> Dict[str, Any]:
```

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1576
    async def _run_subprocess(argv: List[str]) -> tuple[int, str, str]:
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:774
    def is_built(self, root: Path) -> bool:
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
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit.clone_repo",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit.pull_repo",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit._run_subprocess",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig.is_built"
  ]
}
```

## Implementation Notes

The WikiBuildRunner import belongs inside __init__, not at module scope. Cancellation must propagate after releasing resources; never swallow BaseException. clone_branch=None means remote HEAD, never GitToolkit.default_branch. Persist enough generation/last-use evidence to distinguish concurrent waiters from a later delivery. Preserve repository identity metadata against slug collisions. Keep fcntl lock inode ownership safe during eviction; do not unlink a lock while contenders can hold the old inode. Bound remaining implementation choices by AC-10/11, and report any unavoidable spec conflict before coding. Disk traversal/deletion must not run long blocking work on the event loop; use process-based offload where needed and retain the specified synchronous eviction interface. No arbitrary repository scripts or hooks may execute during local fixture setup.

**Parallelism**: Consumes timeout/prefer_gh from TASK-4336, RepoCachePaths/BuildOutcome/repo_lock from TASK-4337, and WikiBuildRunner from TASK-4338. Serializes repo_cache.py and test_repo_cache.py writers after TASK-4337.

## Implementation Blueprint

### Steps (in order)

1. Append RepoWikiCache to the foundation module and import WikiBuildRunner locally during construction — repo_build imports BuildOutcome from this module.
2. Validate a bare owner/name identity and resolve confined cache paths; validate persisted repository identity before reusing a hyphenated slug — distinct owner/name pairs can otherwise collide.
3. Coalesce overlapping refreshes with the in-process lock and persisted successful generation checks under the process lock — serialization alone would run two builds.
4. Validate origin and current/upstream branch before pulling; recover with exactly one re-clone on mismatch, corruption or pull failure — do not silently reuse another repository.
5. Build under both locks, with prefer_gh=False and bounded git calls; require the complete marker and wiki.db before returning paths.
6. Apply LRU eviction only to owned cache entries under safe locking; skip keep and busy entries, and warn without eviction for one oversized entry. Test all recovery and concurrency paths.

### `packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py` (MODIFY)

Prerequisite-created anchors (not present on base at planning time): `class BuildOutcome(BaseModel):` and `async def repo_lock(lock_path: Path, *, timeout: float) -> AsyncIterator[bool]:`. Re-read and count once the foundation lands; append RepoWikiCache after the complete lock function.

```python
class RepoWikiCache:
    """Maintain a local clone + wiki plane per remote repository."""

    def __init__(
        self,
        git_toolkit: Any,                     # GitToolkit; verified: gittoolkit.py:961
        cache_dir: Path,
        *,
        max_bytes: int = 5 * 1024**3,
        clone_branch: Optional[str] = None,   # None → the remote's default HEAD
        clone_depth: Optional[int] = None,    # None → full history
        build_timeout: float = 900.0,
        lock_timeout: float = 600.0,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """..."""

    def paths_for(self, repository: str) -> RepoCachePaths:
        """Canonicalize ``owner/name`` → slug and resolve the three paths."""

    async def ensure_fresh(self, repository: str) -> Optional[RepoCachePaths]:
        """Refresh clone + plane under both locks. Never raises."""

    async def _ensure_clone(self, paths: RepoCachePaths) -> None:
        """Clone, or validate-and-fast-forward an existing clone."""

    def _evict_if_needed(self, *, keep: Optional[str] = None) -> list[str]:
        """Drop least-recently-used (clone, plane, lock) triples until the"""
# FILL IN: complete method bodies and wiring using the ordered steps and acceptance criteria.
```

**Why**: Preserve the spec signatures and small edit surface; the implementation details are bounded by the task acceptance criteria.

### `packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py` (MODIFY)

Prerequisite-created anchor: `async def test_repo_lock_is_exclusive_across_processes(tmp_path: Path) -> None:`
from TASK-4337. Expected occurrence count: 1; verify after that task lands.
Append cache lifecycle tests without replacing the existing lock tests.

```python
def test_paths_for_canonicalizes_slug(tmp_path: Path) -> None:
    """`Owner/Name` → `owner-name`; URL or alias raises `ValueError`."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

async def test_ensure_clone_validates_origin_and_branch(tmp_path: Path) -> None:
    """A cache dir pointing at another remote is detected."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

async def test_ensure_clone_reclones_once_on_corruption(tmp_path: Path) -> None:
    """Not-a-clone and failed `pull --ff-only` both re-clone exactly once, then give up."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

def test_evict_lru_respects_size_cap(tmp_path: Path) -> None:
    """Oldest-used entries dropped until under cap; locked entries skipped."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

def test_evict_never_drops_entry_being_refreshed(tmp_path: Path) -> None:
    """`keep=` slug survives even when the cache is over cap."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

def test_single_oversized_entry_warns_without_evicting(tmp_path: Path) -> None:
    """One entry larger than the cap logs a warning and evicts nothing (no thrash)."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

async def test_ensure_fresh_returns_none_on_any_failure(tmp_path: Path) -> None:
    """Clone error, build error and timeout all return `None` without raising."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

```

**Why**: These tests cover the spec failure modes without network, provider calls or shared conftest changes. Implement fixtures in this file.

### FILL IN checklist

- [ ] Append RepoWikiCache to the foundation module and import WikiBuildRunner locally during construction — repo_build imports BuildOutcome from this module.
- [ ] Validate a bare owner/name identity and resolve confined cache paths; validate persisted repository identity before reusing a hyphenated slug — distinct owner/name pairs can otherwise collide.
- [ ] Coalesce overlapping refreshes with the in-process lock and persisted successful generation checks under the process lock — serialization alone would run two builds.
- [ ] Validate origin and current/upstream branch before pulling; recover with exactly one re-clone on mismatch, corruption or pull failure — do not silently reuse another repository.
- [ ] Build under both locks, with prefer_gh=False and bounded git calls; require the complete marker and wiki.db before returning paths.
- [ ] Apply LRU eviction only to owned cache entries under safe locking; skip keep and busy entries, and warn without eviction for one oversized entry. Test all recovery and concurrency paths.
- [ ] Replace all blueprint placeholders with complete typed, documented implementation and assertions; no unfinished placeholders in delivered source.

## Acceptance Criteria

The feature criteria below apply to this task’s declared scope; cross-module portions are completed by their owning tasks.

- [ ] AC-3: The clone tracks the reviewed repository's own default branch (or `GITHUB_REVIEW_CLONE_BRANCH` when set) — never the `GIT_DEFAULT_BRANCH` fallback of `"main"` — and the branch is reported in the injected context header.
- [ ] AC-4: A cache entry whose origin URL or checked-out branch does not match is detected and re-cloned exactly once; a second failure degrades instead of looping.
- [ ] AC-9: Clone failure, build failure, build timeout, missing `wikitoolkit` binary, and a plane without a last-good marker each degrade to the diff-only review, with one log line and no exception escaping.
- [ ] AC-10: Cache total stays within `GITHUB_REVIEW_CACHE_MAX_BYTES` via LRU eviction; neither a locked entry nor the entry being refreshed is ever evicted, and a single over-cap entry is warned about rather than thrashed.
- [ ] AC-11: Two concurrent deliveries for one repository, in one process and across two processes, produce one build and no lock error.
- [ ] AC-16: A build that does not complete leaves its marker in the `started` state, the plane is not attached, and the next build for that plane runs with `--force`.
- [ ] All task-local tests pass; black formatting and ruff check are clean on changed Python files. No unrelated source changes.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py -q`

## Test Specification

- `test_paths_for_canonicalizes_slug`: `Owner/Name` → `owner-name`; URL or alias raises `ValueError`.
- `test_ensure_clone_validates_origin_and_branch`: A cache dir pointing at another remote is detected.
- `test_ensure_clone_reclones_once_on_corruption`: Not-a-clone and failed `pull --ff-only` both re-clone exactly once, then give up.
- `test_evict_lru_respects_size_cap`: Oldest-used entries dropped until under cap; locked entries skipped.
- `test_evict_never_drops_entry_being_refreshed`: `keep=` slug survives even when the cache is over cap.
- `test_single_oversized_entry_warns_without_evicting`: One entry larger than the cap logs a warning and evicts nothing (no thrash).
- `test_ensure_fresh_returns_none_on_any_failure`: Clone error, build error and timeout all return `None` without raising.

## Agent Instructions

1. Use `$sdd-start TASK-4339` to provision the feature worktree; do not implement on dev.
2. Read the spec and ensure dependencies are done in `sdd/tasks/index/github-reviewer-local-repo-wiki.json`.
3. Reverify contracts and anchors, including prerequisite-created anchors; update stale task evidence before implementing.
4. Implement only declared files, run Validation Commands, and retain logs under artifacts/logs/.
5. Commit scoped code, then close with `scripts.sdd.finalize_task` and real TaskCompletionEvidence.
   Let the finalizer own the completion note and active-to-completed move; commit its SDD state separately.

## Completion Note

Implemented by gpt-5.6-terra (codex). test_repo_cache.py + test_repo_build.py: 20 passed. Residual lint: 2 (ASYNC230 blocking open in lock helpers, intentional).
