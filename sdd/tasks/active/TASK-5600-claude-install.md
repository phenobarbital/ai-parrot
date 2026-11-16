# TASK-5600: Claude experience hooks for workers and installs

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5594, TASK-5596, TASK-5599
**Assigned-to**: unassigned

## Context

Implement Module 6 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Generate exactly PostToolUse and PostToolUseFailure Bash hooks with timeout 5; worker commands use absolute shared-venv Python -I -m, interactive installs use portable parrot command. Merge existing hook groups idempotently, preserve receipt/dry-run behavior and all guards. Register through installer plan/apply paths. No agent-frontmatter hooks.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` | MODIFY | Task-specific regression coverage |
| `packages/ai-parrot/tests/sdd/test_installer.py` | MODIFY | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from parrot.sdd import installer
from pathlib import Path
from typing import Any
import pytest
import shlex
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#native_sandbox_settings` — `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:410`
```python
def native_sandbox_settings(
    cwd: Path, *, allowed_domains: Sequence[str] = (), include_sandbox: bool = True
) -> dict[str, Any]:
```

- `sym:packages/ai-parrot/src/parrot/sdd/installer.py#_install_dangerous_guard` — `packages/ai-parrot/src/parrot/sdd/installer.py:399`
```python
def _install_dangerous_guard(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> list[str]:
```

- `sym:packages/ai-parrot/src/parrot/sdd/installer.py#install_sdd_integration` — `packages/ai-parrot/src/parrot/sdd/installer.py:1515`
```python
def install_sdd_integration(
    root: Path,
    hosts: Sequence[str] = ("claude",),
    *,
    keep_edits: bool = False,
    dry_run: bool = False,
    portable: bool | None = None,
    base_branch: str | None = None,
    push_base: bool = False,
    hotfix_base: str | None = None,
    dangerous_guard: bool = True,
    sdd_coder: bool = True,
    agy_permissions: bool = True,
) -> list[str]:
```

### Dependency Interfaces

claude-install: TASK-5594: serializes writes to packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py, packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py; TASK-5596: consumes the hooks contract in packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py, packages/ai-parrot/src/parrot/launcher.py; TASK-5599: consumes the cli contract in packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py, packages/ai-parrot/src/parrot/sdd/cli.py

### Does NOT Exist

- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/installer.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_installer.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#_install_dangerous_guard",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#install_sdd_integration",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#native_sandbox_settings"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Generate exactly PostToolUse and PostToolUseFailure Bash hooks with timeout 5; worker commands use absolute shared-venv Python -I -m, interactive installs use portable parrot command. Merge existing hook groups idempotently, preserve receipt/dry-run behavior and all guards. Register through installer plan/apply paths. No agent-frontmatter hooks.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

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
import shlex
from pathlib import Path
from typing import Any
def _experience_hook_entries(python: Path) -> dict[str, list[dict[str, Any]]]:
    """Build the two advisory Bash hooks using the absolute shared interpreter."""
    return {
        event_name: [{
            "matcher": "Bash",
            "hooks": [{
                "type": "command",
                "command": shlex.join([str(python), "-I", "-m",
                    "parrot.sdd.scripts.experience_hook", "--host", "claude", "--event", event]),
                "timeout": 5,
            }],
        }]
        for event_name, event in (("PostToolUse", "post"), ("PostToolUseFailure", "post-failure"))
    }
# FILL IN: resolve primary shared venv interpreter (not worktree Python),
# merge into settings["hooks"], preserve PreToolUse guard; AC1-AC3.
```

**Why**: This file owns the claude-install behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/src/parrot/sdd/installer.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/installer.py:399 at 0c5acf0915.
# Anchor: def _install_dangerous_guard(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> list[str]:
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/installer.py:500 at 0c5acf0915.
# Anchor: AGY_HOOKS_PATH = Path(".agents/hooks.json")
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/installer.py:1515 at 0c5acf0915.
# Anchor: def install_sdd_integration(
from pathlib import Path
from typing import Any
def _install_experience_hooks(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> list[str]:
    """Idempotently install portable Claude PostToolUse/PostToolUseFailure hooks."""
    # FILL IN: follow existing receipt/managed settings helpers; preserve other hooks.
    # Commands: parrot sdd experience hook --host claude --event post|post-failure.
# FILL IN: wire through install_sdd_integration plan/apply/dry-run for Claude hosts.
```

**Why**: This file owns the claude-install behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py:20 at 0c5acf0915.
# Anchor: def scratch_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
# Add tests beside the existing cases; do not replace the quoted fixture/class.
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.sdd import installer

def test_native_settings_experience_hooks(tmp_path: Path) -> None:
    """Verify native settings experience hooks. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_agent_frontmatter_has_no_experience_hooks(tmp_path: Path) -> None:
    """Verify agent frontmatter has no experience hooks. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the claude-install behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/sdd/test_installer.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/tests/sdd/test_installer.py:32 at 0c5acf0915.
# Anchor: def empty_repo(tmp_path: Path) -> Path:
# Add tests beside the existing cases; do not replace the quoted fixture/class.
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.sdd import installer

def test_worker_hook_ignores_worktree_pythonpath(tmp_path: Path) -> None:
    """Verify worker hook ignores worktree pythonpath. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_experience_install_idempotent(tmp_path: Path) -> None:
    """Verify experience install idempotent. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the claude-install behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/sdd/installer.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/sdd/test_installer.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: exact entry shapes, hostile worktree PYTHONPATH ignored, primary runtime selected, install/upgrade idempotency, foreign wheel paths, no experience PreToolUse or exit 2 suffix.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_installer.py -q`

## Test Specification

Required behavioral cases: exact entry shapes, hostile worktree PYTHONPATH ignored, primary runtime selected, install/upgrade idempotency, foreign wheel paths, no experience PreToolUse or exit 2 suffix.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5600` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
