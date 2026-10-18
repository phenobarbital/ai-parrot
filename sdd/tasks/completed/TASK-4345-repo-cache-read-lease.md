# TASK-4345: Shared read lease, lock-held eviction and orphan-aware eviction for RepoWikiCache

**Feature**: FEAT-672 — GitHubReviewer local clone + wikitoolkit graph
**Spec**: `sdd/specs/github-reviewer-local-repo-wiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4343, TASK-4339 (done)
**Assigned-to**: unassigned
**discovered_from**: issue:93f2022d934a

---

## Context

Ledger issue `issue:93f2022d934a` (review of FEAT-672). Its headline:
`RepoWikiCache.ensure_fresh` releases the per-repository `flock` before the
reviewer reads the plane. Meanwhile another delivery or process can pull,
rebuild or evict (`rmtree`) the clone and plane. Spec AC-10 ("a locked entry is
never evicted") therefore holds only during the refresh window. The same issue
also reports:

- a TOCTOU between `_lock_is_busy` (probe, then unlock) and `_remove_entry` in eviction;
- eviction runs only after a *successful* refresh;
- eviction enumerates only `repos/`, so plane-only orphans (a plane whose clone is gone) are never reclaimed;
- private clones keep the token in `.git/config`. Fixed in GitToolkit by
  TASK-4343; this task only passes `private=True` to `pull_repo`.

**Verified, not a defect**: the SQLite wiki store opens a new connection per
operation from the plane path (`store.py:1301` `_connect_immutable`,
`store.py:1321` `_connect_readonly`), so there is no long-lived handle to go
stale after a reclone. The fix is mutual exclusion between readers and writers,
not re-attaching the store.

---

## Scope

- Add `shared: bool = False` to `repo_lock`: `LOCK_SH` when `True`, else `LOCK_EX`
  (same polling and release semantics).
- Add `RepoWikiCache.read_lease(repository, *, timeout=0.0)`, an async context
  manager yielding `Optional[RepoCachePaths]`. It holds a **shared** `flock` on
  the entry's lock file for the whole `async with` body, and yields the paths
  only when the lock was acquired and the entry `_usable`, else `None`. It never
  raises for an invalid slug or a lock timeout (yields `None`). Cancellation
  propagates.
- Replace the probe-then-remove eviction with removal **while holding** a
  non-blocking exclusive lock on the entry (`_remove_if_unlocked`). A held shared
  lease therefore blocks eviction, and there is no window between the check and
  the `rmtree`.
- Enumerate eviction candidates from the **union** of `repos/` and `planes/`
  directory names, so plane-only orphans are sized and evictable.
- Run eviction after every refresh attempt that reached the build step,
  successful or not (still `keep=paths.slug`, still via `asyncio.to_thread`).
- Pass `private=True` to `self.git_toolkit.pull_repo(...)` in `_ensure_clone`
  (needs TASK-4343).

**NOT in scope**: reviewer wiring (TASK-4346); process groups (TASK-4344); changing
`ensure_fresh`'s return contract or the reclone-once rule of spec M2.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py` | MODIFY | `repo_lock(shared=)`, `read_lease`, lock-held + orphan-aware eviction, eviction after failure, `pull_repo(private=True)` |
| `packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py` | MODIFY | Lease and eviction tests; adapt `test_evict_skips_locked_entries` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from contextlib import asynccontextmanager  # verified: repo_cache.py:9
from typing import Any, AsyncIterator, Optional  # verified: repo_cache.py:12
# fcntl is imported under try/except at repo_cache.py:16-19 (None on non-POSIX)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py
_LOCK_POLL_SECONDS = 0.05  # line 22
class RepoCachePaths(BaseModel): slug, repository, clone_dir, plane_dir, lock_path  # line 27
@asynccontextmanager
async def repo_lock(lock_path: Path, *, timeout: float) -> AsyncIterator[bool]:  # line 48
    #   fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)   # the line to parametrize
class RepoWikiCache:  # line 90
    def paths_for(self, repository: str) -> RepoCachePaths:  # raises ValueError
    async def ensure_fresh(self, repository: str) -> Optional[RepoCachePaths]:
        #   await asyncio.to_thread(self._evict_if_needed, keep=paths.slug)   # line 198 (success branch only)
    async def _ensure_clone(self, paths: RepoCachePaths) -> None:
        #   await self.git_toolkit.pull_repo(   # line 221
        #       str(paths.clone_dir), self.clone_branch, timeout=self.build_runner.timeout
        #   )
    def _usable(self, paths: RepoCachePaths) -> bool:
    def _remove_entry(self, paths: RepoCachePaths) -> None:  # rmtree clone_dir + plane_dir
    def _evict_if_needed(self, *, keep: Optional[str] = None) -> list[str]:  # line 332
    @staticmethod
    def _tree_size(root: Path) -> int:
    @staticmethod
    def _lock_is_busy(path: Path) -> bool:  # line 382 — probe-then-unlock (the TOCTOU)
```

```python
# GitToolkit.pull_repo(repo_path, branch=None, *, timeout=None, private=False)
#   — `private` is ADDED by TASK-4343 (dependency). Tests use FakeGit.pull_repo(self, repo_path, branch, **kwargs)
#   (test_repo_cache.py:42), which already accepts it.
```

```python
# packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py
def test_evict_skips_locked_entries(...)  # line 249 — monkeypatches cache._lock_is_busy; must be rewritten
                                          # to hold a real lock/lease, since eviction no longer calls _lock_is_busy
```

### Does NOT Exist
- ~~`RepoWikiCache.read_lease`~~, ~~`RepoWikiCache._remove_if_unlocked`~~ — created by this task
- ~~`repo_lock(shared=...)`~~ — created by this task
- ~~`WikiStore.reopen()` / store re-attach API~~ — not needed (per-operation connections)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py#repo_lock",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py#RepoWikiCache.ensure_fresh",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py#RepoWikiCache._ensure_clone",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py#RepoWikiCache._evict_if_needed",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py#RepoWikiCache._lock_is_busy",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py#RepoWikiCache._remove_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py#RepoWikiCache._usable"
  ]
}
```

---

## Implementation Notes

- `flock` locks belong to the open file description. Two separate `open()` calls
  in the same process conflict like separate processes do, so a lease held by
  delivery A blocks a refresh by delivery B in the same reviewer. This is
  intended: the refresh waits (bounded by `lock_timeout`) instead of rebuilding
  under a reader.
- Do not unlink lock files (existing invariant, `_evict_if_needed` docstring).
- Keep `_lock_is_busy` (public-ish helper; may still be used for diagnostics),
  but eviction must not depend on it.

---

## Implementation Blueprint

### Steps (in order)
1. Parametrize `repo_lock` with `shared`, because the lease and the writers must share one lock file.
2. Add `read_lease`, because the reviewer (TASK-4346) holds it across a whole review.
3. Add `_remove_if_unlocked` and use it in `_evict_if_needed`, because removing while holding the lock closes the TOCTOU, and a held lease keeps an entry from being evicted.
4. Enumerate `repos/ ∪ planes/`, because plane-only orphans are otherwise never reclaimed.
5. Move eviction so it also runs after a failed build, and pass `private=True` to `pull_repo`.
6. Tests.

### `repo_cache.py` (MODIFY) — `repo_lock`
```python
# occurrences: 1 (verified: grep -c 'async def repo_lock(lock_path: Path, \*, timeout: float)' repo_cache.py → line 48)
async def repo_lock(lock_path: Path, *, timeout: float, shared: bool = False) -> AsyncIterator[bool]:
    # docstring: add "shared: take LOCK_SH (concurrent readers) instead of LOCK_EX."
    ...
    mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX   # compute only when fcntl is not None
    #   fcntl.flock(handle.fileno(), mode | fcntl.LOCK_NB)
```

### `repo_cache.py` (MODIFY) — `read_lease` (new method, insert after `ensure_fresh`)
```python
    @asynccontextmanager
    async def read_lease(self, repository: str, *, timeout: float = 0.0) -> AsyncIterator[Optional[RepoCachePaths]]:
        """Hold a shared lock on a usable entry for the duration of a read.

        Yields the entry's paths while refresh and eviction are excluded, or
        ``None`` when the slug is invalid, the lock is unavailable within
        ``timeout``, or the plane is not usable. Never raises for those cases.
        """
        try:
            paths = self.paths_for(repository)
        except ValueError:
            yield None
            return
        async with repo_lock(paths.lock_path, timeout=timeout, shared=True) as acquired:
            # FILL IN: yield paths if acquired and self._usable(paths) else None — bounded by:
            #          exactly one yield on every path (asynccontextmanager contract)
```

### `repo_cache.py` (MODIFY) — `_remove_if_unlocked` (new) and `_evict_if_needed`
```python
    def _remove_if_unlocked(self, paths: RepoCachePaths) -> bool:
        """Remove an entry only while holding its exclusive lock; ``False`` if busy."""
        if fcntl is None:  # pragma: no cover - non-POSIX platform
            self._remove_entry(paths)
            return True
        paths.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(paths.lock_path, "a+")  # noqa: SIM115 - closed in finally
        try:
            # FILL IN: try LOCK_EX|LOCK_NB → on OSError return False; else _remove_entry(paths)
            #          then LOCK_UN, return True — bounded by: rmtree only while the lock is held
        finally:
            handle.close()
```
In `_evict_if_needed` (line 332):
- build the slug set as the union of directory names under `repos_root` and
  `planes_root` (skip non-dirs and symlinks); size = `_tree_size(repos/slug) + _tree_size(planes/slug)`;
- replace `if slug == keep or self._lock_is_busy(...): continue` + `self._remove_entry(paths)` with
  `if slug == keep: continue` and `if not self._remove_if_unlocked(paths): continue`.

### `repo_cache.py` (MODIFY) — `ensure_fresh` and `_ensure_clone`
```python
# ensure_fresh: occurrences: 1 (verified: grep -c 'await asyncio.to_thread(self._evict_if_needed, keep=paths.slug)' → line 198)
# FILL IN: run `await asyncio.to_thread(self._evict_if_needed, keep=paths.slug)` after the build
#          on BOTH the failure branch and the success branch (before each return) — bounded by:
#          cancellation still propagates; eviction exceptions are caught by the existing outer except
# _ensure_clone: occurrences: 1 (verified: grep -c 'await self.git_toolkit.pull_repo(' → line 221)
                    await self.git_toolkit.pull_repo(
                        str(paths.clone_dir), self.clone_branch, timeout=self.build_runner.timeout, private=True
                    )
```

### FILL IN checklist
- [ ] `read_lease` — one yield per path; shared lock
- [ ] `_remove_if_unlocked` — remove only under LOCK_EX
- [ ] `_evict_if_needed` — union enumeration; lock-held removal
- [ ] `ensure_fresh` — eviction on the failure branch too
- [ ] tests (below)

---

## Acceptance Criteria

- [ ] While a `read_lease` is held, `repo_lock(..., timeout=0)` (exclusive) yields `False`, and eviction does not remove that entry
- [ ] `read_lease` yields `None` for an unusable plane, an invalid slug, or an exclusive holder (timeout 0)
- [ ] Two `read_lease`s on the same entry can be held at once
- [ ] A plane-only orphan above the cap is evicted
- [ ] Eviction runs after a failed build
- [ ] `_ensure_clone` calls `pull_repo(..., private=True)`
- [ ] Existing `test_repo_cache.py` tests pass (`test_evict_skips_locked_entries` adapted to a real held lock)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py -q`

---

## Test Specification

```python
async def test_read_lease_blocks_writer_and_eviction(tmp_path: Path) -> None:
    # FILL IN: make the entry usable (FakeBuildRunner path), hold read_lease, assert an exclusive
    #          repo_lock(timeout=0) yields False and _evict_if_needed(keep=None) with a tiny cap
    #          does not remove it

async def test_read_lease_yields_none_when_unusable_or_locked(tmp_path: Path) -> None:
    # FILL IN

async def test_read_leases_are_shared(tmp_path: Path) -> None:
    # FILL IN

def test_evict_reclaims_plane_only_orphan(tmp_path: Path) -> None:
    # FILL IN

async def test_eviction_runs_after_failed_build(tmp_path: Path) -> None:
    # FILL IN: FakeBuildRunner returning ok=False; monkeypatch _evict_if_needed to record a call

async def test_pull_is_authenticated_for_private_repositories(tmp_path: Path) -> None:
    # FILL IN: FakeGit records pull_repo kwargs; assert private=True
```

---

## Agent Instructions

Standard SDD task flow (see `sdd/templates/task.md` → Agent Instructions).

---

## Completion Note

Implemented by sdd-worker. Implementing commit 5da5757ff17541fd1914c1b490313927275147d0. test_repo_cache.py: 22 passed, 0 failed. Adapted test_evict_skips_locked_entries to a real held lock. Remaining ruff ASYNC110 is pre-existing. No contract drift.
