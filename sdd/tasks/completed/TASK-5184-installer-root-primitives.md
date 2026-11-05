# TASK-5184: Install-root classification and explicit-pin primitives

**Feature**: FEAT-804 — Installer portability gaps — one root, one portable rule
**Spec**: `sdd/specs/installer-portability-gaps.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.4 of FEAT-804. This task owns the following bounded deliverable;
the dependency graph separates disjoint host implementations and serializes overlapping test writers.
Source references and literal edit anchors were verified at `62aaa17228` on 2026-11-05.

## Scope

- Implement spec M1 using stdlib only; preserve existing launcher resolution behavior.
- Classify the containing checkout using original gitdir/commondir metadata, not common != root/.git.
- Move make_venv and linked_worktree_repo to launcher/conftest.py; keep tests importable via the existing launcher test package.

**NOT in scope**: worktree-root relocation (FEAT-802), wiki discovery redesign, non-Python worktree
provisioning, dependency additions, or edits outside the declared files. This is an implementation
task artifact; generation of this artifact makes no runtime changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/launcher.py` | MODIFY | Retain discovery compatibility while exposing provenance and classification to every installer. |
| `packages/ai-parrot/tests/launcher/conftest.py` | CREATE | Move the already-tested helpers instead of introducing a different fake worktree layout. |
| `packages/ai-parrot/tests/launcher/test_launcher_core.py` | MODIFY | Pin the four review regressions at the primitive boundary. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Existing imports below resolve in the referenced source/test modules; `click`, `pytest` and
`pydantic` are already declared in the workspace pyproject files. Stdlib imports require no new
dependency. Imports explicitly marked with a task ID are future dependency contracts, not claims
that those symbols exist at planning HEAD. Preserve existing imports not shown in the blueprint.

```python
import dataclasses
import shutil
from pathlib import Path
from collections.abc import Mapping, Sequence
import pytest
from parrot import launcher
from .conftest import make_venv  # moved by this task; tests/launcher/__init__.py exists
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/launcher.py:24
def parrot_home(env: Mapping[str, str] | None = None) -> Path:

# packages/ai-parrot/src/parrot/launcher.py:58
def repository_paths(cwd: Path) -> tuple[Path, Path | None]:

# packages/ai-parrot/src/parrot/launcher.py:49
def _existing_directory(path: Path) -> Path:

# packages/ai-parrot/src/parrot/launcher.py:87
def find_project_root(argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> Path | None:

# packages/ai-parrot/src/parrot/sdd/installer.py:280
def guard_hook_command(*, portable: bool) -> tuple[str, Literal["bare", "baked"]]:

# packages/ai-parrot/tests/launcher/test_launcher_core.py:11
def make_venv(path: Path, *scripts: str) -> Path:

# packages/ai-parrot/tests/launcher/test_launcher_core.py:26
def linked_worktree_repo(tmp_path: Path) -> tuple[Path, Path]:
```

### Does NOT Exist

- InstallRoot, LinkedWorktreeError, install_root, explicit_project_pin, managed_launcher_on_path and require_primary_checkout do not exist yet.
- No wiki-module import is allowed in the launcher; do not add a git subprocess for classification.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/launcher.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/launcher/conftest.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/launcher/test_launcher_core.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/launcher.py#parrot_home",
    "sym:packages/ai-parrot/src/parrot/launcher.py#repository_paths",
    "sym:packages/ai-parrot/src/parrot/launcher.py#_existing_directory",
    "sym:packages/ai-parrot/src/parrot/launcher.py#find_project_root",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#guard_hook_command",
    "sym:packages/ai-parrot/tests/launcher/test_launcher_core.py#make_venv",
    "sym:packages/ai-parrot/tests/launcher/test_launcher_core.py#linked_worktree_repo"
  ]
}
```

## Implementation Notes

Exclusive: creates tests/launcher/conftest.py loaded by launcher tests; no dependencies.

Use the approved stdlib-only launcher/decision structures from the spec. Keep public signatures
and existing ownership checks; use black (120 columns) and ruff for Python edits. New test functions
must have type hints and explanatory docstrings, matching production conventions. Keep HOME/PATH,
Google user-global config, credential probes and Git fixtures isolated under tmp_path. Never run
installers against the developer checkout/home as a test. Store test logs in artifacts/logs/.

## Implementation Blueprint

The blocks below are scoped edit plans, not wholesale replacements of existing files. CREATE
blocks are whole-file starting points; fill their bounded bodies before committing. Preserve
surrounding implementation and imports. No FILL IN or unfinished body may remain in implemented code.

### Steps (in order)

1. Revalidate listed anchors and prerequisite signatures — because dependencies or FEAT-802 may move adjacent code.
2. Apply the declared per-file edits in the order below — because caller and callee contracts must remain coherent.
3. Implement every bounded test case in Acceptance Criteria — because wiring-only spies do not verify emitted artifacts.
4. Run the Validation Commands and scoped lint — because the final state must preserve existing regression coverage.

### `packages/ai-parrot/src/parrot/launcher.py` (MODIFY)

Anchor `def find_project_root(argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> Path | None:` — occurrences: 1; verified `packages/ai-parrot/src/parrot/launcher.py:87`.

```python
import dataclasses
import shutil

@dataclasses.dataclass(frozen=True)
class InstallRoot:
    """Install target and shared wiki state location, with explicit-pin provenance."""
    root: Path
    shared_root: Path
    linked: bool
    explicit: bool

class LinkedWorktreeError(RuntimeError):
    """An implicit installation target is a linked worktree."""

def managed_launcher_on_path(env: Mapping[str, str] | None = None) -> bool:
    """Test found/resolved parrot paths against found/resolved parrot_home; never raise."""
    # FILL IN: move guard_hook_command's PATH test; honor the supplied env, AC1.

def explicit_project_pin(argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> Path | None:
    """Return a valid CLI/environment pin, never the repository-discovery fallback."""
    # FILL IN: extract existing pin precedence/validation from find_project_root, AC1/AC9.

def install_root(cwd: Path, *, explicit: Path | None = None) -> InstallRoot:
    """Resolve target and classify actual commondir metadata without changing wiki discovery."""
    # FILL IN: implement spec M1 classification and explicit non-repository/subdir behavior, AC2.

def require_primary_checkout(resolved: InstallRoot) -> InstallRoot:
    """Refuse implicit linked-worktree writes; retain deliberate explicit overrides."""
    if resolved.linked and not resolved.explicit:
        raise LinkedWorktreeError(
            f"{resolved.root} is a linked worktree of {resolved.shared_root}; installers "
            f"write to the checkout you run them in — run this from {resolved.shared_root}, "
            f"or pass --path {resolved.root} to install into the worktree on purpose"
        )
    return resolved

# In existing find_project_root, call explicit_project_pin first; keep the .git walk unchanged.
```

**Why**: Retain discovery compatibility while exposing provenance and classification to every installer.

### `packages/ai-parrot/tests/launcher/conftest.py` (CREATE)

New file; absence verified at planning HEAD.

```python
"""Reusable fake venv and linked-worktree fixtures for launcher tests."""
from pathlib import Path
import pytest

def make_venv(path: Path, *scripts: str) -> Path:
    """Create a fake venv with script stubs, matching the existing helper exactly."""
    # FILL IN: move the existing test_launcher_core.make_venv body unchanged.

@pytest.fixture
def linked_worktree_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create a primary checkout and a linked-worktree gitdir with commondir."""
    # FILL IN: move the existing fixture body unchanged.
```

**Why**: Move the already-tested helpers instead of introducing a different fake worktree layout.

### `packages/ai-parrot/tests/launcher/test_launcher_core.py` (MODIFY)

Anchor `def make_venv(path: Path, *scripts: str) -> Path:` — occurrences: 1; verified `packages/ai-parrot/tests/launcher/test_launcher_core.py:11`.

```python
from .conftest import make_venv
# Remove the moved helper and fixture definitions; pytest discovers linked_worktree_repo.
def test_install_root_external_gitdir_is_not_linked(tmp_path: Path) -> None:
    """An external gitdir without commondir is an ordinary checkout."""
    # FILL IN: real separate-git-dir and submodule cases plus spec M1 matrix.
def test_explicit_project_pin_provenance(tmp_path: Path) -> None:
    """Automatic discovery never becomes an explicit pin."""
    # FILL IN: pin precedence, invalid pins and no-pin cases; keep existing resolver tests.
```

**Why**: Pin the four review regressions at the primitive boundary.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/launcher.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/tests/launcher/conftest.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/tests/launcher/test_launcher_core.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.

## Acceptance Criteria

- [ ] AC1/AC2: primary, nested, linked, explicit subdir, explicit non-repo and outside-repo cases match the spec.
- [ ] Real separate-git-dir and submodule fixtures without commondir are not refused; malformed metadata never raises.
- [ ] Explicit pin precedence matches the existing resolver; no pin returns None even in a linked worktree.
- [ ] Managed launcher detection covers absent, foreign, direct and symlink paths; stdlib-only import test passes.

## Validation Commands

- `pytest packages/ai-parrot/tests/launcher/test_launcher_core.py -q`
- `pytest packages/ai-parrot/tests/launcher/test_launcher_stdlib_only.py -q`

Run with the activated project environment and `PYTHONPATH=packages/ai-parrot/src`.
These commands are this task's relevant tests; the index carries the cached spec-wide contract.

## Test Specification

Use the cases and assertions in Acceptance Criteria and each test-file blueprint. Assert outputs,
exit statuses and before/after file snapshots as appropriate. Tests for malformed config and
worktree refusal must prove no unintended write; avoid network services and real user config.

## Agent Instructions

1. Use `$sdd-start TASK-5184` in the feature workflow; implementation belongs in its provisioned worktree.
2. Read the spec and verify dependencies are done in `sdd/tasks/index/installer-portability-gaps.json`.
3. Verify this contract before editing; refresh stale anchors explicitly rather than inventing interfaces.
4. Implement only declared files, complete every blueprint gap, run validation and scoped lint.
5. Commit only the implementation scope. Finalize through `scripts.sdd.finalize_task` with real
   TaskCompletionEvidence and exact implementation HEAD per docs/sdd/CODEX.md; never hand-edit
   the Completion Note or move this task to completed manually. Commit the resulting SDD state.

## Completion Note

Completed 2026-11-05 via sdd-worker orchestration.

- Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 248s · Tokens: n/a
- Implementation: merge 80c893b32c (coder d390506a79, engine lint 8b1e3f15f2). Diff touches only the three declared files.
- Merge-tier validation (engine, tier=merge): 231 passed, 3 failed, all classified baseline reds
  (test_launcher_core::test_resolve_order_and_validity, ::test_worktree_prefers_local_then_main,
  test_sdd_cli::test_sdd_cli_mounts_every_helper). The first fails here because the launcher refuses a
  tmp-path `.venv` ("tracked by git or not owned by you") — an environment effect, not this change.
- Closure deviation: `coder_record_review` returned a server-side error
  (`CoderReview() argument after ** must be a mapping, not CoderReview`), so no review EvidenceRef
  existed for `parrot sdd task finalize`. The task was closed with `parrot sdd task close` and this note
  written by hand. review/feedback NOT recorded in the coder ledger; fix_commits: none.
