# TASK-5207: Implement guarded host sync and advisory API

**Feature**: FEAT-806 — Worktree Sync Base
**Spec**: `sdd/specs/worktree-sync-base.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5206
**Assigned-to**: unassigned

## Context

M1 host foundation implements target safety, base metadata, process guards, transactional merge/cherry-pick, dry-run and the advisory API consumed by M5.

## Scope

Implement the §3 signatures and §2 host behavior. Until TASK-5208 adds patches, sandbox sync must refuse with exit 5 and host guidance, with no mutation. Implement complete operational refusal, not a TODO/stub. NOT in scope: gh patch transport, CLI registry or launcher wiring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` | CREATE | Sync models, resolver, host integration and CLI entry |
| `tests/sdd_scripts/test_worktree_sync.py` | CREATE | Host and guard tests |

## Codebase Contract (Anti-Hallucination)

Verified at `cd57902e64`. Dependency-created symbols are explicitly identified below; verify them after dependencies land.

### Verified Imports
```python
from __future__ import annotations
import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal, Sequence
from pydantic import BaseModel, Field
from parrot.sdd.scripts.remove_worktree import discover, _match, live_processes_in
from parrot.sdd.scripts.worktree_status import _read_worktree_index
from parrot.sdd.scripts.native_claude_sandbox import BACKEND_ENV
from parrot.sdd.scripts.sdd_meta import parse
import pytest
from parrot.sdd.scripts import worktree_sync  # Created by this task; used by its tests.
```
Stdlib imports need no new dependency. Pydantic is declared in packages/ai-parrot/pyproject.toml:54; pytest in root pyproject.toml:64.

### Existing Signatures to Use
- `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py:191`: `discover() -> list[Worktree]`; returns registered worktrees AND orphan directories. Worktree has path, branch, registered, primary fields.
- `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py:269`: `_match(worktrees: list[Worktree], target: str) -> list[Worktree]`.
- TASK-5206 extends `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py:163` with `exclude_pids: Collection[int] = ()`.
- `packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py:135`: `_read_worktree_index(wt_path: Path, slug: str) -> tuple[list[WorktreeTaskStatus], str]`; failure returns `([], "dev")`, which cannot distinguish absent index from an explicit dev base. Check the selected index's existence before choosing the brief fallback.
- `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:31`: `BACKEND_ENV = "PARROT_SDD_SANDBOX_BACKEND"`.
- sdd_meta.py reexports `parse(doc_path: Path, *, config: SddConfig | None = None) -> FlowMeta` from knowledge/wiki/ledger/sdd_meta.py:169; use `.base_branch`.

### Does NOT Exist
- worktree_sync module, SyncError, SyncResult and stale_base_summary are new here.
- No automatic ancestry exclusion and no safe orphan-target sync helper exist.
- No gh object transport exists; TASK-5208 adds patch transport to this module.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py",
      "action": "CREATE"
    },
    {
      "path": "tests/sdd_scripts/test_worktree_sync.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#discover",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#_match",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#live_processes_in",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py#_read_worktree_index",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#parse"
  ]
}
```

## Implementation Notes

Consumes TASK-5206 live_processes_in(exclude_pids) in remove_worktree.py. TASK-5208 later extends the same core and tests; no dependency on future CLI registration is needed for direct module tests.

Use repository tools from the activated environment; preserve shared environments. Keep changes within declared files, use typed functions and Google-style docstrings, black (120 columns), and ruff. Tests must import this worktree's source, not another editable checkout. No new dependency is authorized. CLI subprocess I/O is synchronous by design; do not introduce blocking I/O into async entry points. Run no network or destructive operations against the real repository in tests.

## Implementation Blueprint

Blueprint gaps below are planning instructions only; finished code must have no placeholders.

### Steps (in order)

1. Implement the typed API and safe resolver — an orphan directory must never redirect Git into primary.
2. Resolve metadata and ancestry; validate refs/SHAs as data — explicit argv does not alone prevent Git option injection.
3. Implement host fetch and single integration transaction; snapshot HEAD/index/tree, collect conflicts before abort, and verify restoration — rollback failures must not be called restored.
4. Implement dry-run and stale_base_summary — approved v0.3 skips dirty/live guards for dry-run but still validates target; never integrate.
5. Exercise the specification host tests in disposable repositories — no real remotes, no rebase/reset/push.

### `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` (CREATE)

```python
"""Safely integrate base commits into a registered SDD linked worktree."""
from __future__ import annotations
import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal, Sequence
from pydantic import BaseModel, Field
from parrot.sdd.scripts.remove_worktree import discover, _match, live_processes_in
from parrot.sdd.scripts.worktree_status import _read_worktree_index
from parrot.sdd.scripts.native_claude_sandbox import BACKEND_ENV
from parrot.sdd.scripts.sdd_meta import parse

EXIT_OK, EXIT_TARGET, EXIT_DIRTY, EXIT_LIVE, EXIT_TRANSPORT, EXIT_CONFLICT = 0, 2, 3, 4, 5, 6
logger = logging.getLogger(__name__)

class SyncError(Exception):
    """Operator-facing refusal with a stable exit code."""
    def __init__(self, exit_code: int, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code

class SyncResult(BaseModel):
    """Machine-readable synchronization outcome."""
    worktree: str
    branch: str | None
    base_branch: str
    transport: Literal["host-git", "sandbox-gh"]
    mode: Literal["merge", "ff-only", "cherry-pick"]
    dry_run: bool
    before: str
    after: str
    commits: list[str]
    status: Literal["synced", "up-to-date", "refused", "conflict", "error"]
    exit_code: int
    message: str
    conflicts: list[str] = Field(default_factory=list)

def in_sandbox() -> bool:
    """Return whether BACKEND_ENV selects a sandbox."""
    # FILL IN: spec env detection.
def own_ancestry() -> set[int]:
    """Return self and ancestor PIDs by walking /proc stat parent fields."""
    # FILL IN: handle parenthesized command names, vanished PIDs and cycles.
def resolve_target(target: str) -> Path:
    """Require one registered non-primary linked worktree with matching Git top-level."""
    # FILL IN: spec target validation before mutation; EXIT_TARGET on failure.
def resolve_base_branch(wt: Path, override: str | None) -> str:
    """Resolve override, selected per-spec index, brief frontmatter, then dev."""
    # FILL IN: derive the matching slug; never select an arbitrary index in the checkout.
def check_guards(wt: Path) -> None:
    """Reject dirty trees and foreign live processes using stable refusal codes."""
    # FILL IN: preserve diagnostics and exclude only own ancestry.
def owner_repo(wt: Path) -> str:
    """Parse owner/repo from SSH or HTTPS origin URLs."""
    # FILL IN: reject invalid origins without shell interpolation.
def sync(wt: Path, base: str, *, cherry_picks: Sequence[str] = (), ff_only: bool = False,
         dry_run: bool = False) -> SyncResult:
    """Integrate safely; only report conflict after verified rollback."""
    # FILL IN: host transaction and results; sandbox returns safe EXIT_TRANSPORT until TASK-5208.
def stale_base_summary(wt: Path, base: str | None = None) -> str:
    """Return an advisory host dry-run summary or a skipped reason; never raise."""
    # FILL IN: no integration, sandbox fetch or propagation of operational exceptions.
def main(argv: Sequence[str] | None = None) -> int:
    """Parse target and sync flags, emit human/JSON output and return the result code."""
    # FILL IN: argparse, diagnostics, JSON refusal handling; no --force-live.
if __name__ == "__main__":
    raise SystemExit(main())
```

**Why**: The spec fixes the public API; private helpers can separate subprocess, guards and rollback without changing signatures.

### `tests/sdd_scripts/test_worktree_sync.py` (CREATE)

```python
"""Real temporary Git integration tests for worktree sync."""
from pathlib import Path
import subprocess
import pytest
from parrot.sdd.scripts import worktree_sync


def test_host_merge_from_outside(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A new base commit is integrated into a registered feature worktree."""
    # FILL IN: local bare origin, primary and linked feature fixture; verify all refs and files.


def test_conflict_aborts_and_restores_head(tmp_path: Path) -> None:
    """Conflicting merge restores HEAD, index and tree and reports paths."""
    # FILL IN: conflicting branches and exact before/after snapshots.


def test_stale_base_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Advisory covers ahead, current, sandbox and unavailable targets without raising."""
    # FILL IN: spec outputs, no sandbox fetch, and unchanged HEAD/index/worktree.
```

**Why**: Real local Git repositories validate state transitions that subprocess mocks would miss.


### FILL IN checklist

- [ ] Primary, orphan, unregistered, ambiguous and mismatched Git-root targets return 2 without mutation.
- [ ] Base precedence is override > selected index > selected brief > dev; malformed/missing metadata is handled deliberately.
- [ ] Dirty/live checks return 3/4 and list diagnostics; own ancestry alone is excluded; recheck guards immediately before integration.
- [ ] Host merge, ff-only and cherry-pick -x work; cherry-picks are reachable from freshly fetched base; conflicts restore the entire operation.
- [ ] Dry-run reports commits without changing HEAD/index/tree, even when dirty or live; no mode pushes or rebases.
- [ ] stale_base_summary emits the specified ahead/up-to-date/skipped lines and never raises on operational errors.
- [ ] CLI entry accepts repeatable --cherry-pick, --base, --ff-only, --dry-run and --json with stable exit codes; no live override.

## Acceptance Criteria

- [ ] Primary, orphan, unregistered, ambiguous and mismatched Git-root targets return 2 without mutation.
- [ ] Base precedence is override > selected index > selected brief > dev; malformed/missing metadata is handled deliberately.
- [ ] Dirty/live checks return 3/4 and list diagnostics; own ancestry alone is excluded; recheck guards immediately before integration.
- [ ] Host merge, ff-only and cherry-pick -x work; cherry-picks are reachable from freshly fetched base; conflicts restore the entire operation.
- [ ] Dry-run reports commits without changing HEAD/index/tree, even when dirty or live; no mode pushes or rebases.
- [ ] stale_base_summary emits the specified ahead/up-to-date/skipped lines and never raises on operational errors.
- [ ] CLI entry accepts repeatable --cherry-pick, --base, --ff-only, --dry-run and --json with stable exit codes; no live override.
- [ ] All task validation commands pass and touched Python files pass `ruff check`; apply `black --line-length 120` to touched Python files.

## Validation Commands

- `pytest tests/sdd_scripts/test_worktree_sync.py -q`

## Test Specification

Cover every host/guard/metadata/owner_repo test in spec §4, ff-only divergence, multi-commit cherry-pick rollback, malformed Git output, failed abort, stale/invalid refs and dry-run with dirty/live tree. Use argument-list subprocess calls and pin child imports to the feature source.

## Agent Instructions

1. Use `$sdd-start TASK-5207` in the FEAT-806 feature worktree; never implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/worktree-sync-base.json` and revalidate contracts before editing.
3. Implement only declared files, finish every blueprint gap, and run the listed validation commands. Store logs under `artifacts/logs/`.
4. Commit implementation files, then finalize through `scripts.sdd.finalize_task` using real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move tasks or write completion evidence.
5. Commit only the resulting task/index state. Do not push from the worker.

## Completion Note

Implemented by seat gpt-5.6-terra (codex, attempt 1, 375s). Created `parrot/sdd/scripts/worktree_sync.py`
(SyncError, SyncResult, in_sandbox, own_ancestry, resolve_target, resolve_base_branch, check_guards, owner_repo,
sync, stale_base_summary, main) and `tests/sdd_scripts/test_worktree_sync.py`. Engine lint commit b24570e069.
Merge-tier validation green (3 passed; cached targets unchanged). Orchestrator verified every blueprint symbol is
present. Closed via `parrot sdd task close` because `coder_record_review` fails server-side, so no review
EvidenceRef was available for `parrot sdd task finalize`.
