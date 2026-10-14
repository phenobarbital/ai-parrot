# TASK-4336: Harden GitToolkit clone and pull subprocess lifecycle

**Feature**: FEAT-672 - GitHubReviewer local clone + wikitoolkit graph
**Spec**: `sdd/specs/github-reviewer-local-repo-wiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement spec §3 M4 within the approved external-plane design. Harden GitToolkit clone and pull subprocess lifecycle.
This task changes only the files below. No provider SDK calls or new dependencies.

## Scope

- Add timeout=None and prefer_gh=True exactly as in M4 — old callers retain their current behavior.
- Propagate timeout through fresh clone, idempotent clone-to-pull, and pull subprocess paths; prefer_gh=False must choose authenticated git even when gh exists.
- On timeout or cancellation terminate, allow a bounded grace period, kill if necessary, and await reaping — cancelling communicate alone leaks a child.
- Extend the recorder to accept timeout while retaining argv assertions; test secret scrubbing, timeout propagation, cancellation and private authentication.

**NOT in scope**: PR-head checkout, programmatic build API extraction, shared sidecars,
and changes belonging to other tasks. This task does not alter the spec.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | Harden GitToolkit clone and pull subprocess lifecycle |
| `packages/ai-parrot-tools/tests/test_gittoolkit_clone.py` | MODIFY | Focused behavioral tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import patch
import pytest
from parrot_tools.gittoolkit import GitToolkit, GitToolkitError
from pathlib import Path
```

Third-party dependencies click, pydantic and pytest are declared in packages/ai-parrot/pyproject.toml. Standard-library imports need no dependency additions. Imports of feature-created symbols are provided by the explicitly listed prerequisites, not claimed to exist at planning time. Verify any additional implementation imports before use.


### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1576
    async def _run_subprocess(argv: List[str]) -> tuple[int, str, str]:
```

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
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1556
    def _scrub(self, text: str, token: Optional[str] = None) -> str:
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
      "path": "packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/test_gittoolkit_clone.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit._run_subprocess",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit.clone_repo",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit.pull_repo",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit._scrub"
  ]
}
```

## Implementation Notes

Timeout returns (-9, "", a timeout diagnostic) at the runner boundary; clone/pull preserve GitToolkitError and scrubbed messages. Re-raise CancelledError after cleanup. Default timeout=None must remain compatible with existing subprocess mocks. Do not alter provider auth or unrelated GitToolkit tools.

**Parallelism**: Independent GitToolkit writer: gittoolkit.py and test_gittoolkit_clone.py only; no dependency on the build runner because it consumes no runner symbol.

## Implementation Blueprint

### Steps (in order)

1. Add timeout=None and prefer_gh=True exactly as in M4 — old callers retain their current behavior.
2. Propagate timeout through fresh clone, idempotent clone-to-pull, and pull subprocess paths; prefer_gh=False must choose authenticated git even when gh exists.
3. On timeout or cancellation terminate, allow a bounded grace period, kill if necessary, and await reaping — cancelling communicate alone leaks a child.
4. Extend the recorder to accept timeout while retaining argv assertions; test secret scrubbing, timeout propagation, cancellation and private authentication.

### `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` (MODIFY)

```python
# Anchor:     async def _run_subprocess(argv: List[str]) -> tuple[int, str, str]:
# occurrences: 1 (verified with grep -Fxc; packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1576)
# Anchor:     async def clone_repo(
# occurrences: 1 (verified with grep -Fxc; packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1590)
# Anchor:     async def pull_repo(
# occurrences: 1 (verified with grep -Fxc; packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1653)
```

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
#   (modifies gittoolkit.py:1576, :1590, :1653)
@staticmethod
async def _run_subprocess(argv: List[str], timeout: Optional[float] = None) -> tuple[int, str, str]:
    """Run ``argv``; return ``(returncode, stdout, stderr)``.

    With ``timeout``, terminate → kill → reap the child and return
    ``(-9, "", "<timed out after Ns>")``. Default None keeps today's
    unbounded behaviour for every existing caller.
    """

async def clone_repo(
    self,
    repository: str,
    dest_dir: str,
    branch: Optional[str] = None,
    *,
    private: bool = False,
    depth: Optional[int] = None,
    timeout: Optional[float] = None,      # NEW
    prefer_gh: bool = True,               # NEW — False forces the token-in-URL path
) -> Dict[str, Any]:
    """...

    ``prefer_gh=False`` skips the ``gh repo clone`` branch even when the
    binary exists: ``gh`` never sees the PAT / App token this toolkit holds
    (verified: gittoolkit.py:1627), so an installed-but-unauthenticated
    ``gh`` would otherwise fail a private clone that the token could serve.
    """

async def pull_repo(
    self,
    repo_path: str,
    branch: Optional[str] = None,
    *,
    timeout: Optional[float] = None,      # NEW
) -> Dict[str, Any]:
    """..."""
# FILL IN: complete method bodies and wiring using the ordered steps and acceptance criteria.
```

**Why**: Preserve the spec signatures and small edit surface; the implementation details are bounded by the task acceptance criteria.

### `packages/ai-parrot-tools/tests/test_gittoolkit_clone.py` (MODIFY)

```python
# Anchor: async def test_clone_repo_idempotent_pulls(tmp_path):
# occurrences: 1 (verified with grep -Fxc; packages/ai-parrot-tools/tests/test_gittoolkit_clone.py:99)
# Extend this test module; preserve existing fixtures and regression assertions.
```

```python
async def test_run_subprocess_timeout_reaps_child(tmp_path: Path) -> None:
    """`_run_subprocess(timeout=…)` leaves no orphan."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

async def test_clone_repo_prefer_gh_false_uses_token_url(tmp_path: Path) -> None:
    """With `gh` present and `prefer_gh=False`, argv is the token-in-URL `git clone`."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

async def test_clone_repo_timeout_propagates(tmp_path: Path) -> None:
    """Timeout reaches `_run_subprocess`."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

```

**Why**: These tests cover the spec failure modes without network, provider calls or shared conftest changes. Implement fixtures in this file.

### FILL IN checklist

- [ ] Add timeout=None and prefer_gh=True exactly as in M4 — old callers retain their current behavior.
- [ ] Propagate timeout through fresh clone, idempotent clone-to-pull, and pull subprocess paths; prefer_gh=False must choose authenticated git even when gh exists.
- [ ] On timeout or cancellation terminate, allow a bounded grace period, kill if necessary, and await reaping — cancelling communicate alone leaks a child.
- [ ] Extend the recorder to accept timeout while retaining argv assertions; test secret scrubbing, timeout propagation, cancellation and private authentication.
- [ ] Replace all blueprint placeholders with complete typed, documented implementation and assertions; no unfinished placeholders in delivered source.

## Acceptance Criteria

The feature criteria below apply to this task’s declared scope; cross-module portions are completed by their owning tasks.

- [ ] AC-5: The warm-up task is stored on the agent, logs its own exceptions, and is cancelled and awaited on shutdown; no orphaned `git`/`wikitoolkit` child survives a reload.
- [ ] AC-6: A build exceeding `GITHUB_REVIEW_BUILD_TIMEOUT` is terminated, killed and reaped, and reported as `timed_out` distinctly from an ordinary non-zero exit.
- [ ] All task-local tests pass; black formatting and ruff check are clean on changed Python files. No unrelated source changes.
- [ ] AC-5/6 coverage here is the Git subprocess lifecycle; the build runner and reviewer tasks complete the feature-level lifecycle.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/test_gittoolkit_clone.py -q`

## Test Specification

- `test_run_subprocess_timeout_reaps_child`: `_run_subprocess(timeout=…)` leaves no orphan.
- `test_clone_repo_prefer_gh_false_uses_token_url`: With `gh` present and `prefer_gh=False`, argv is the token-in-URL `git clone`.
- `test_clone_repo_timeout_propagates`: Timeout reaches `_run_subprocess`.

## Agent Instructions

1. Use `$sdd-start TASK-4336` to provision the feature worktree; do not implement on dev.
2. Read the spec and ensure dependencies are done in `sdd/tasks/index/github-reviewer-local-repo-wiki.json`.
3. Reverify contracts and anchors, including prerequisite-created anchors; update stale task evidence before implementing.
4. Implement only declared files, run Validation Commands, and retain logs under artifacts/logs/.
5. Commit scoped code, then close with `scripts.sdd.finalize_task` and real TaskCompletionEvidence.
   Let the finalizer own the completion note and active-to-completed move; commit its SDD state separately.

## Completion Note

Pending implementation; the finalizer records evidence after validation.
