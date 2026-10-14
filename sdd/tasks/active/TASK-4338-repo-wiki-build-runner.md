# TASK-4338: Run cancellable wiki builds with completion markers

**Feature**: FEAT-672 - GitHubReviewer local clone + wikitoolkit graph
**Spec**: `sdd/specs/github-reviewer-local-repo-wiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4335, TASK-4337
**Assigned-to**: unassigned

## Context

Implement spec §3 M3 within the approved external-plane design. Run cancellable wiki builds with completion markers.
This task changes only the files below. No provider SDK calls or new dependencies.

## Scope

- Import BuildOutcome from the completed models task and implement the fixed build argv — the CLI task supplies --storage-dir.
- Read needs_force before marking started; atomically persist started before spawning and complete only after exit zero — failed incremental state must force a rebuild.
- Bound communicate, terminate/kill/reap on timeout and cancellation, and scrub bounded stderr; never interpret stdout as structured output.
- Exercise fake executable and actual local CLI builds; assert no exported OKF bundle or graph files and no surviving child.

**NOT in scope**: PR-head checkout, programmatic build API extraction, shared sidecars,
and changes belonging to other tasks. This task does not alter the spec.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/repo_build.py` | CREATE | Run cancellable wiki builds with completion markers |
| `packages/ai-parrot/tests/knowledge/wiki/test_repo_build.py` | CREATE | Focused behavioral tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from parrot.knowledge.wiki.repo_cache import BuildOutcome
import pytest
```

Third-party dependencies click, pydantic and pytest are declared in packages/ai-parrot/pyproject.toml. Standard-library imports need no dependency additions. Imports of feature-created symbols are provided by the explicitly listed prerequisites, not claimed to exist at planning time. Verify any additional implementation imports before use.


### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1560
def build(
    path_: str | None,
    name: str | None,
    backend: str | None,
    force: bool,
    no_git: bool,
    quiet: bool,
    no_export: bool,
    no_graph: bool,
    graph_kinds: str,
    vault_mode: bool | None,
    no_push: bool,
) -> None:
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
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/repo_build.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_repo_build.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#build"
  ]
}
```

## Implementation Notes

Use atomic marker replacement and UTC timestamps. Absent, malformed or started markers are unusable; incomplete or corrupt state requires force. Propagate cancellation after child cleanup. Keep stderr bounded and redact credential-bearing URLs before logging. Models remain in repo_cache.py; do not import RepoWikiCache here.

**Parallelism**: Consumes --storage-dir added by TASK-4335 in cli.py and BuildOutcome created by TASK-4337 in repo_cache.py.

## Implementation Blueprint

### Steps (in order)

1. Import BuildOutcome from the completed models task and implement the fixed build argv — the CLI task supplies --storage-dir.
2. Read needs_force before marking started; atomically persist started before spawning and complete only after exit zero — failed incremental state must force a rebuild.
3. Bound communicate, terminate/kill/reap on timeout and cancellation, and scrub bounded stderr; never interpret stdout as structured output.
4. Exercise fake executable and actual local CLI builds; assert no exported OKF bundle or graph files and no surviving child.

### `packages/ai-parrot/src/parrot/knowledge/wiki/repo_build.py` (CREATE)

```python
"""Killable repository wiki builds and completion markers."""
from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from parrot.knowledge.wiki.repo_cache import BuildOutcome

# packages/ai-parrot/src/parrot/knowledge/wiki/repo_build.py  (new)
LAST_GOOD_FILENAME = ".last_good_build.json"

class WikiBuildRunner:
    """Run `wikitoolkit build` over a clone, into an external plane."""

    def __init__(self, *, executable: str = "wikitoolkit", timeout: float = 900.0,
                 logger: Optional[logging.Logger] = None) -> None:
        """Configure the executable and bounded subprocess lifetime."""
        self.executable = executable
        self.timeout = timeout
        self.logger = logger or logging.getLogger(__name__)

    async def run(self, clone_dir: Path, plane_dir: Path, *, quiet: bool = True,
                  force: bool = False) -> BuildOutcome:
        """Spawn the build subprocess."""

    def mark_build_started(self, plane_dir: Path) -> None:
        """Record that a build is in flight, BEFORE spawning it."""

    def mark_last_good(self, plane_dir: Path, outcome: BuildOutcome) -> None:
        """Flip LAST_GOOD_FILENAME to ``complete`` (utc timestamp + duration)"""

    def last_good(self, plane_dir: Path) -> Optional[datetime]:
        """Completion time of the last COMPLETE build, else None."""

    def needs_force(self, plane_dir: Path) -> bool:
        """True when the previous build for this plane never completed, so"""
# FILL IN: complete method bodies and wiring using the ordered steps and acceptance criteria.
```

**Why**: Preserve the spec signatures and small edit surface; the implementation details are bounded by the task acceptance criteria.

### `packages/ai-parrot/tests/knowledge/wiki/test_repo_build.py` (CREATE)

```python
"""Hermetic behavioral tests for FEAT-672."""
from pathlib import Path
import pytest

async def test_build_runner_argv(tmp_path: Path) -> None:
    """Exact argv incl. `--path`, `--storage-dir`, `--no-export`, `--no-graph`, `-q`."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

async def test_build_runner_omits_export_and_graph(tmp_path: Path) -> None:
    """No OKF bundle and no `graph.html` land in the plane after a run."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

def test_needs_force_after_incomplete_build(tmp_path: Path) -> None:
    """A marker left in `started` ⇒ `needs_force()` is True and the next argv carries `--force`."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

async def test_build_runner_never_parses_stdout(tmp_path: Path) -> None:
    """A navconfig banner on stdout does not affect the outcome."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

async def test_build_runner_timeout_kills_child(tmp_path: Path) -> None:
    """Hung child is terminated, killed and reaped; `timed_out=True`."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

def test_last_good_marker_roundtrip(tmp_path: Path) -> None:
    """Marker written only after success; absent marker ⇒ plane unusable."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

```

**Why**: These tests cover the spec failure modes without network, provider calls or shared conftest changes. Implement fixtures in this file.

### FILL IN checklist

- [ ] Import BuildOutcome from the completed models task and implement the fixed build argv — the CLI task supplies --storage-dir.
- [ ] Read needs_force before marking started; atomically persist started before spawning and complete only after exit zero — failed incremental state must force a rebuild.
- [ ] Bound communicate, terminate/kill/reap on timeout and cancellation, and scrub bounded stderr; never interpret stdout as structured output.
- [ ] Exercise fake executable and actual local CLI builds; assert no exported OKF bundle or graph files and no surviving child.
- [ ] Replace all blueprint placeholders with complete typed, documented implementation and assertions; no unfinished placeholders in delivered source.

## Acceptance Criteria

The feature criteria below apply to this task’s declared scope; cross-module portions are completed by their owning tasks.

- [ ] AC-5: The warm-up task is stored on the agent, logs its own exceptions, and is cancelled and awaited on shutdown; no orphaned `git`/`wikitoolkit` child survives a reload.
- [ ] AC-6: A build exceeding `GITHUB_REVIEW_BUILD_TIMEOUT` is terminated, killed and reaped, and reported as `timed_out` distinctly from an ordinary non-zero exit.
- [ ] AC-9: Clone failure, build failure, build timeout, missing `wikitoolkit` binary, and a plane without a last-good marker each degrade to the diff-only review, with one log line and no exception escaping.
- [ ] AC-15: The build subprocess always passes `--no-export --no-graph`; no OKF bundle or `graph.html` is produced for a reviewed repository.
- [ ] AC-16: A build that does not complete leaves its marker in the `started` state, the plane is not attached, and the next build for that plane runs with `--force`.
- [ ] All task-local tests pass; black formatting and ruff check are clean on changed Python files. No unrelated source changes.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_repo_build.py -q`

## Test Specification

- `test_build_runner_argv`: Exact argv incl. `--path`, `--storage-dir`, `--no-export`, `--no-graph`, `-q`.
- `test_build_runner_omits_export_and_graph`: No OKF bundle and no `graph.html` land in the plane after a run.
- `test_needs_force_after_incomplete_build`: A marker left in `started` ⇒ `needs_force()` is True and the next argv carries `--force`.
- `test_build_runner_never_parses_stdout`: A navconfig banner on stdout does not affect the outcome.
- `test_build_runner_timeout_kills_child`: Hung child is terminated, killed and reaped; `timed_out=True`.
- `test_last_good_marker_roundtrip`: Marker written only after success; absent marker ⇒ plane unusable.

## Agent Instructions

1. Use `$sdd-start TASK-4338` to provision the feature worktree; do not implement on dev.
2. Read the spec and ensure dependencies are done in `sdd/tasks/index/github-reviewer-local-repo-wiki.json`.
3. Reverify contracts and anchors, including prerequisite-created anchors; update stale task evidence before implementing.
4. Implement only declared files, run Validation Commands, and retain logs under artifacts/logs/.
5. Commit scoped code, then close with `scripts.sdd.finalize_task` and real TaskCompletionEvidence.
   Let the finalizer own the completion note and active-to-completed move; commit its SDD state separately.

## Completion Note

Pending implementation; the finalizer records evidence after validation.
