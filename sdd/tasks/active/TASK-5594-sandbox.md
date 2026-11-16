# TASK-5594: Experience writable directory and protected hook files

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement Module 5 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Mirror coder_evidence_dirs for .parrot/experience and bind it in Bubblewrap, native allowWrite and prefix roots. Protect experience_hook.py, fastpath.py and launcher.py using installed/monorepo/shim resolution. Preserve every existing denial and return () on primary checkout, missing git metadata or OSError.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | Task-specific regression coverage |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` | MODIFY | Task-specific regression coverage |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` | MODIFY | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from parrot.sdd.scripts import worktree_environment, native_claude_sandbox
from pathlib import Path
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#coder_evidence_dirs` — `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:243`
```python
def coder_evidence_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]:
```

- `sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#protected_argv` — `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:299`
```python
def protected_argv(cwd: Path, argv: Sequence[str], *, derive_pythonpath: bool = False) -> list[str]:
```

- `sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#_control_files` — `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:209`
```python
def _control_files(root: Path) -> list[Path]:
```

- `sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#native_sandbox_settings` — `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:410`
```python
def native_sandbox_settings(
    cwd: Path, *, allowed_domains: Sequence[str] = (), include_sandbox: bool = True
) -> dict[str, Any]:
```

- `sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#_prefix_writable_roots` — `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:922`
```python
def _prefix_writable_roots(cwd: Path) -> tuple[Path, ...]:
```

### Dependency Interfaces

Independent sandbox files; no shared state outside declared targets.

### Does NOT Exist

- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_sdd_launch.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#_control_files",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#_prefix_writable_roots",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#native_sandbox_settings",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#coder_evidence_dirs",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#protected_argv"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Mirror coder_evidence_dirs for .parrot/experience and bind it in Bubblewrap, native allowWrite and prefix roots. Protect experience_hook.py, fastpath.py and launcher.py using installed/monorepo/shim resolution. Preserve every existing denial and return () on primary checkout, missing git metadata or OSError.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:151 at 0c5acf0915.
# Anchor: CODER_EVIDENCE_DIR = Path("artifacts") / "logs" / "sdd-coder-usage"
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:243 at 0c5acf0915.
# Anchor: def coder_evidence_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]:
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:360 at 0c5acf0915.
# Anchor: for evidence_dir in coder_evidence_dirs(root, git_dir):
from pathlib import Path
EXPERIENCE_PLANE_DIR = Path(".parrot") / "experience"

def experience_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]:
    """Return/create the primary experience directory for linked worktrees."""
    # FILL IN: mirror coder_evidence_dirs primary/OSError behavior; AC1-AC3.
# Extend protected_argv's writable bind list using experience_dirs(root, git_dir).
```

**Why**: This file owns the sandbox behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:218 at 0c5acf0915.
# Anchor: names = ("native_claude_sandbox.py", "worktree_environment.py")
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:426 at 0c5acf0915.
# Anchor: allow_paths.extend(_we.coder_evidence_dirs(root, git_dir))
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:442 at 0c5acf0915.
# Anchor: "hooks": [{"type": "command", "command": hook_command, "timeout": 10}],
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:930 at 0c5acf0915.
# Anchor: _canonical(primary / "artifacts" / "logs" / "sdd-coder-usage"),
# In native_sandbox_settings after coder_evidence_dirs:
allow_paths.extend(_we.experience_dirs(root, git_dir))
# In _prefix_writable_roots include:
# _canonical(primary / ".parrot" / "experience")
# FILL IN: extend _control_files names with experience_hook.py and add
# fastpath.py and launcher.py for installed + monorepo copies; preserve shims.
# Keep wiki, HOME, shared environments and every existing denial read-only.
```

**Why**: This file owns the sandbox behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py:26 at 0c5acf0915.
# Anchor: def scratch_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
# Add tests beside the existing cases; do not replace the quoted fixture/class.
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.sdd.scripts import worktree_environment, native_claude_sandbox

def test_experience_dirs_contract(tmp_path: Path) -> None:
    """Verify experience dirs contract. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_control_files_include_experience_hook(tmp_path: Path) -> None:
    """Verify control files include experience hook. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the sandbox behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py:20 at 0c5acf0915.
# Anchor: def scratch_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
# Add tests beside the existing cases; do not replace the quoted fixture/class.
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.sdd.scripts import worktree_environment, native_claude_sandbox

def test_protected_argv_binds_experience(tmp_path: Path) -> None:
    """Verify protected argv binds experience. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the sandbox behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/sdd/test_sdd_launch.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/tests/sdd/test_sdd_launch.py:22 at 0c5acf0915.
# Anchor: def _restore_sandbox_mode(monkeypatch: pytest.MonkeyPatch) -> None:
# Add tests beside the existing cases; do not replace the quoted fixture/class.
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.sdd.scripts import worktree_environment, native_claude_sandbox

def test_native_allow_write_includes_experience(tmp_path: Path) -> None:
    """Verify native allow write includes experience. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the sandbox behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/sdd/test_sdd_launch.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: exact path lists in both backends, primary versus external linked worktree, mkdir failure, control file denial, no wiki or HOME grant.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_launch.py -q`

## Test Specification

Required behavioral cases: exact path lists in both backends, primary versus external linked worktree, mkdir failure, control file denial, no wiki or HOME grant.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5594` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
