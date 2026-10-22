# TASK-4610: Sync native artifacts into every sdd-coder pool sub-worktree

**Feature**: FEAT-722 — Worktree Native Artifact Sync
**Spec**: `sdd/specs/worktree-native-artifact-sync.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4608
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (pool half). `SubWorktreeManager.create()` is the second
worktree-creation path in this repo: the `sdd-coder` engine calls it once per
task attempt, producing `<base>/<feature-branch>--pool/<worker-id>` trees
(`engine.py:2187`). Those trees are plain `git worktree add` results, so they
carry no native artifacts either — which is exactly where a coder seat then
fails to import `parrot.utils`.

Two differences from TASK-4609 matter:
- `create()` is `async`, and `sync_native_artifacts` is blocking I/O (globs,
  `copy2`, possibly a subprocess build) ⇒ wrap it in `asyncio.to_thread`.
- A native-sync problem must **never** fail a coder attempt. `create()`'s only
  failure mode stays `git worktree add` failing; sync warnings are logged.

---

## Scope

- In `create()`, after the `self._created[worker_id] = (path, branch)`
  bookkeeping, resolve the main checkout from `self.base_worktree` and run
  `sync_native_artifacts` via `asyncio.to_thread`.
- Log each `report.warnings` entry with `self.logger.warning`; swallow any
  exception from the sync itself (log it, keep going) and still return `path`.
- Extend `test_worktree_manager.py` using its `git_sandbox` fixture.

**NOT in scope**: `ensure_worktree.py` (TASK-4609); `baseline.py` (TASK-4611);
changing merge/cleanup behaviour; syncing on `refresh_all`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py` | MODIFY | Sync after `git worktree add` |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_manager.py` | MODIFY | Sub-worktree sync tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already in worktree_manager.py
import asyncio                                      # verified: worktree_manager.py:27
import logging                                      # verified: worktree_manager.py:28
from pathlib import Path                             # verified: worktree_manager.py:29
from parrot.flows.dev_loop.procs import git_env, run_bounded  # verified: worktree_manager.py:34

# added by THIS task
from parrot.flows.dev_loop.native_artifacts import main_checkout_root, sync_native_artifacts
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py
class SubWorktreeManager:                                            # line 80
    def __init__(self, *, base_worktree: str, feature_branch: str,
                 worktree_base_path: str) -> None:                   # line 81
        self.base_worktree = str(Path(base_worktree).resolve())      # line 98
        self.logger = logging.getLogger(__name__)                    # line 105
    async def _git(self, *args: str, cwd: str) -> Tuple[int, str, str]:   # line 117
    async def create(self, worker_id: str, *, base: Optional[str] = None) -> str:  # line 145
        rc, _out, err = await self._git("worktree", "add", "-b", branch, path, base or self.feature_branch, cwd=self.base_worktree)  # lines 159-161
        if rc != 0: raise SubWorktreeMergeError(...)                 # lines 162-168
        self._created[worker_id] = (path, branch)                    # line 173 (occurrences: 1)
        return path                                                  # line 174
```

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py (TASK-4606..4608)
def main_checkout_root(worktree: Path) -> Path | None
def sync_native_artifacts(*, main_root: Path, target: Path,
                          manifest: NativeManifest | None = None,
                          autobuild: bool = True) -> NativeSyncReport
```

```python
# packages/ai-parrot/tests/flows/dev_loop/test_worktree_manager.py
@pytest.fixture                       # line 34
def git_sandbox(...)                  # the fixture every test in this file uses
async def test_create_with_base_forks_from_that_branch(git_sandbox) -> None:   # line 265
```

### Does NOT Exist
- ~~a synchronous `SubWorktreeManager.create`~~ — it is `async def`; never call
  the blocking sync directly in the coroutine, use `asyncio.to_thread`.
- ~~`self.main_root` / `self.repo_root`~~ — the manager stores
  `base_worktree`, `feature_branch`, `worktree_base_path` and `_created` only.
  Resolve the main checkout with `main_checkout_root(Path(self.base_worktree))`.
- ~~`SubWorktreeManager.refresh_all` as a second sync point~~ — it exists
  (`test_worktree_manager.py:105` exercises it) but is out of scope here.
- ~~raising `SubWorktreeMergeError` for a sync failure~~ — that exception means
  a git/merge failure; a native-sync problem is logged, never raised.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_manager.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py#SubWorktreeManager.create",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py#sync_native_artifacts"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Keep the sync **after** the `_created` bookkeeping: if the sync somehow blows
  up, the worktree is still registered for cleanup.
- `main_checkout_root` returning `None` (not a git tree) ⇒ skip silently with a
  `logger.debug`; this happens in synthetic tests, not in production.
- Do not pass `autobuild=False`: a pool sub-worktree is created while the
  orchestrator is in the main checkout, and the per-group lock in
  `build_missing` already collapses N concurrent attempts into one build.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:2187` —
  where sub-worktree paths are composed, for context on how many are created.

---

## Implementation Blueprint

### Steps (in order)
1. Add the `native_artifacts` import — *why*: `worktree_manager` already imports
   from `parrot.flows.dev_loop`, so this introduces no new dependency edge and
   no cycle (`native_artifacts` imports nothing from `parrot`).
2. Insert the sync after the bookkeeping line — *why*: that is the single point
   every successful sub-worktree creation passes through.
3. Extend the tests — *why*: a coder seat that cannot import `parrot.utils` is
   exactly the failure this feature exists to remove.

### `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py` (MODIFY — 1 of 2)
```python
# occurrences: 1 (verified: grep -c 'from parrot.flows.dev_loop.procs import git_env, run_bounded' packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py)
# AFTER — insert below `from parrot.flows.dev_loop.procs import git_env, run_bounded` (verified: worktree_manager.py:34)
from parrot.flows.dev_loop.native_artifacts import main_checkout_root, sync_native_artifacts
```
**Why**: keeps the module's single `parrot` import block together.

### `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py` (MODIFY — 2 of 2)
```python
# occurrences: 1 (verified: grep -c '        self._created[worker_id] = (path, branch)' packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py)
# AFTER — insert between `self._created[worker_id] = (path, branch)` and
#   `return path` (verified: worktree_manager.py:173-174)
        await self._sync_native_artifacts(path)
        return path

    async def _sync_native_artifacts(self, path: str) -> None:
        """Copy the declared native build artifacts into a fresh sub-worktree.

        A `git worktree add` tree carries no compiled extension (they are all
        gitignored), so a coder seat in it cannot even `import parrot.utils`
        (FEAT-722). Blocking I/O, so it runs in a thread. Never raises: a
        native-sync problem must not fail a coder attempt.
        """
        main_root = main_checkout_root(Path(self.base_worktree))
        if main_root is None:
            self.logger.debug("native sync skipped: no main checkout for %s", self.base_worktree)
            return
        try:
            report = await asyncio.to_thread(
                sync_native_artifacts, main_root=main_root, target=Path(path)
            )
        except Exception:  # noqa: BLE001 — a sync problem must never fail the attempt
            self.logger.warning("native artifact sync failed for %s", path, exc_info=True)
            return
        for warning in report.warnings:
            self.logger.warning("native artifacts: %s", warning)
        self.logger.debug(
            "native artifacts for %s: %d copied, %d skipped, built=%s",
            path,
            len(report.copied),
            len(report.skipped),
            report.built,
        )
```
**Why this shape**: a private helper keeps `create()` readable and gives the
tests something to monkeypatch. `asyncio.to_thread` is required because the
sync globs the tree, copies files and may spawn a build — all of which would
block the event loop the engine runs several attempts on. The bare `except`
is deliberate and narrated: the alternative (an exception escaping) turns a
missing `.so` into a failed task attempt.

### FILL IN checklist
- [ ] none for the two blocks above — complete as written. Judgement remains
      only in the tests.

---

## Acceptance Criteria

- [ ] `await SubWorktreeManager.create(worker_id)` leaves the declared artifact
      inside the returned sub-worktree path
- [ ] `create()` still returns the path and raises `SubWorktreeMergeError` only
      for a `git worktree add` failure
- [ ] A sync that raises is caught: `create()` returns the path, and a warning
      is logged (assert with `caplog`)
- [ ] `report.warnings` entries are logged at WARNING level
- [ ] `main_checkout_root` returning `None` does not raise and logs at DEBUG
- [ ] The sync runs off the event loop (`asyncio.to_thread`), verified by the
      call being awaited and the helper not being a plain function call
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_manager.py -q`
      passes, including every pre-existing test
- [ ] `ruff check` clean on both files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_manager.py -q`

---

## Test Specification

Extend `packages/ai-parrot/tests/flows/dev_loop/test_worktree_manager.py`,
reusing its `git_sandbox` fixture (line 34):

```python
async def test_subworktree_create_syncs_artifacts(git_sandbox):
    """A declared artifact from the sandbox main checkout lands in the sub-worktree."""


async def test_subworktree_sync_failure_does_not_raise(git_sandbox, monkeypatch, caplog):
    """A sync that raises is logged and `create()` still returns the path."""


async def test_subworktree_sync_warnings_are_logged(git_sandbox, monkeypatch, caplog):
    """Each report warning reaches the logger at WARNING level."""
```

Declare a stub group in the sandbox repo (or monkeypatch
`worktree_manager.sync_native_artifacts`) so no test compiles the real
extensions. Write real bodies — the docstrings state what each must assert.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-4608 must be `"done"`
4. **Verify the Codebase Contract** — re-run the two `grep -c` commands in the
   blueprint; both anchors were verified at `a99dd4fe9`
5. **Update status** in the per-spec index → `"in-progress"`, commit only it
6. **Implement** — write both blocks as given, then the tests
7. **Verify** the acceptance criteria — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the two files this task lists
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4610 worktree-native-artifact-sync verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
