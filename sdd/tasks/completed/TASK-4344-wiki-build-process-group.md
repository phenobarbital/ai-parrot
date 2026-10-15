# TASK-4344: Run the wiki build in its own process group and kill the whole group

**Feature**: FEAT-672 — GitHubReviewer local clone + wikitoolkit graph
**Spec**: `sdd/specs/github-reviewer-local-repo-wiki.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4338 (done)
**Assigned-to**: unassigned
**discovered_from**: issue:93f2022d934a

---

## Context

Ledger issue `issue:93f2022d934a`: `WikiBuildRunner.run` spawns `wikitoolkit build`
without a process group. On timeout or cancellation `_stop_and_reap` signals
only the direct child, so any grandchild the build spawns (worker processes,
git, parsers) can outlive the timeout. It keeps writing into the plane after
the cache has released its lock (spec Module 3, "killable, bounded build").

---

## Scope

- Spawn the build with `start_new_session=True` so the child leads a new process group.
- In `_stop_and_reap`, send SIGTERM and then SIGKILL to the **process group**
  (`os.killpg(process.pid, sig)`). Fall back to `process.terminate()` /
  `process.kill()` when `os.killpg` is unavailable (non-POSIX), and treat
  `ProcessLookupError` / `PermissionError` as "already gone".
- Add a test proving a grandchild of the fake build is killed on timeout.

**NOT in scope**: `GitToolkit._run_subprocess` (git subprocesses, a separate path);
any change to marker or timeout semantics.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/repo_build.py` | MODIFY | New session for the build; group-wide terminate/kill |
| `packages/ai-parrot/tests/knowledge/wiki/test_repo_build.py` | MODIFY | Grandchild-killed-on-timeout test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio  # verified: repo_build.py:5
# os and signal are NOT imported in repo_build.py yet — add `import os` and `import signal`
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/repo_build.py
class WikiBuildRunner:  # line 22
    async def run(self, clone_dir: Path, plane_dir: Path, *, quiet: bool = True, force: bool = False) -> BuildOutcome:  # line 37
        #   process = await asyncio.create_subprocess_exec(   # line 65
    async def _stop_and_reap(self, process: asyncio.subprocess.Process,
                             communication: asyncio.Task[tuple[bytes, bytes]]) -> None:  # line 149
        #   process.terminate()   # line 157
        #   process.kill()        # line 165
_TERMINATE_GRACE_SECONDS = 5.0  # line 17
```

```python
# packages/ai-parrot/tests/knowledge/wiki/test_repo_build.py
def _fake_wikitoolkit(tmp_path: Path, body: str) -> Path:  # line 16 — writes an executable python script
async def test_build_runner_timeout_kills_child(tmp_path: Path) -> None:  # line 81 — pattern to copy
```

### Does NOT Exist
- ~~`WikiBuildRunner._signal_group`~~ — created by this task
- ~~`asyncio.subprocess.Process.killpg`~~ — not an API; use `os.killpg(process.pid, sig)`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/repo_build.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_repo_build.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_build.py#WikiBuildRunner.run",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_build.py#WikiBuildRunner._stop_and_reap"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `import os` and `import signal`, because the group signals need both.
2. Pass `start_new_session=True` to `create_subprocess_exec`, because then the child's pid is also its process-group id.
3. Add `_signal_group` and use it in `_stop_and_reap`, because terminate/kill must reach grandchildren.
4. Add the grandchild test, because the existing timeout test only checks the direct child.

### `repo_build.py` (MODIFY) — spawn
```python
# occurrences: 1 (verified: grep -c 'process = await asyncio.create_subprocess_exec(' repo_build.py → line 65)
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
```

### `repo_build.py` (MODIFY) — `_signal_group` (new, add above `_stop_and_reap`)
```python
    @staticmethod
    def _signal_group(process: asyncio.subprocess.Process, sig: int) -> None:
        """Signal the build's whole process group; fall back to the child alone."""
        if process.returncode is not None:
            return
        # FILL IN: if hasattr(os, "killpg"): os.killpg(process.pid, sig), else
        #          process.terminate() for SIGTERM / process.kill() otherwise;
        #          swallow ProcessLookupError and PermissionError — bounded by: never raise from cleanup
```
Then in `_stop_and_reap` replace the `process.terminate()` try-block (line 156-159) with
`self._signal_group(process, signal.SIGTERM)` and the `process.kill()` try-block (line 164-167) with
`self._signal_group(process, signal.SIGKILL)`. Keep the grace wait and the final `await communication` unchanged.

**Why**: the group leader's pid is the pgid only because of `start_new_session=True`. Keep both edits in this task.

### FILL IN checklist
- [ ] `_signal_group` — killpg, fallback, error swallowing
- [ ] test — the fake build spawns a `sleep` grandchild, writes its pid, and the test asserts it is dead after the timeout

---

## Acceptance Criteria

- [ ] A build timeout kills both the direct child and its grandchildren
- [ ] All existing `test_repo_build.py` tests still pass
- [ ] `ruff check` is clean on `repo_build.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_repo_build.py -q`

---

## Test Specification

```python
async def test_build_runner_timeout_kills_grandchildren(tmp_path: Path) -> None:
    """A grandchild spawned by the build dies with its process group."""
    # FILL IN: fake build runs subprocess.Popen(["sleep", "60"]), writes the grandchild pid,
    #          then sleeps; run with timeout=0.05; poll os.kill(pid, 0) until ProcessLookupError
    #          (reap via os.waitpid is not possible — it is not our child; poll up to ~5s)
```

Note: `test_repo_build.py` has one real-CLI test that needs an **absolute**
`PYTHONPATH` in a worktree; otherwise the subprocess imports the main checkout's
`wikitoolkit`.

---

## Agent Instructions

Standard SDD task flow (see `sdd/templates/task.md` → Agent Instructions).

---

## Completion Note

Implemented by sdd-worker (sequential, no coder seats). Implementing commit a6e4ada29. Tests: 7 passed, 0 failed (validation command). ruff: only 2 pre-existing ASYNC240 findings in gittoolkit.py (baseline identical). No contract drift.
