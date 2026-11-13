# TASK-5605: Codex and agy experience hook registration

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5600, TASK-5603
**Assigned-to**: unassigned

## Context

Implement Module 8 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Add portable Codex PostToolUse Bash entry and named agy parrot-sdd-experience group. Agy PostToolUse is grouped with run_command matcher; PostInvocation is a flat list of command hooks. Use fixed installer template and maintain existing permissions group byte-for-byte semantically. Integrate agy installer plan/apply without adding a Codex installer that does not exist.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | Scoped deliverable |
| `.codex/hooks.json` | MODIFY | Scoped deliverable |
| `.agents/hooks.json` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/tests/sdd/test_installer.py` | MODIFY | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from parrot.sdd import installer
from pathlib import Path
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/sdd/installer.py#_install_agy_hook` — `packages/ai-parrot/src/parrot/sdd/installer.py:640`
```python
def _install_agy_hook(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> tuple[bool, list[str]]:
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

host-install: TASK-5600: serializes writes to packages/ai-parrot/src/parrot/sdd/installer.py, packages/ai-parrot/tests/sdd/test_installer.py; TASK-5603: consumes the agy-replay contract in packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py

### Does NOT Exist

- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/installer.py",
      "action": "MODIFY"
    },
    {
      "path": ".codex/hooks.json",
      "action": "MODIFY"
    },
    {
      "path": ".agents/hooks.json",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_installer.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#_install_agy_hook",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#install_sdd_integration"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Add portable Codex PostToolUse Bash entry and named agy parrot-sdd-experience group. Agy PostToolUse is grouped with run_command matcher; PostInvocation is a flat list of command hooks. Use fixed installer template and maintain existing permissions group byte-for-byte semantically. Integrate agy installer plan/apply without adding a Codex installer that does not exist.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/sdd/installer.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/installer.py:399 at 0c5acf0915.
# Anchor: def _install_dangerous_guard(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> list[str]:
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/installer.py:500 at 0c5acf0915.
# Anchor: AGY_HOOKS_PATH = Path(".agents/hooks.json")
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/installer.py:1515 at 0c5acf0915.
# Anchor: def install_sdd_integration(
# Add a fixed experience group to the existing agy hook installer template:
# parrot-sdd-experience.PostToolUse -> matcher run_command + command hook list.
# parrot-sdd-experience.PostInvocation -> FLAT command hook list.
# Commands use parrot sdd experience hook --host agy --event post|post-invocation.
# FILL IN: idempotent merge through _install_agy_hook; preserve permissions group,
# receipts, dry-run, portable command selection and upgrade behavior; AC1-AC3.
```

**Why**: This file owns the host-install behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `.codex/hooks.json` (MODIFY)

```text
# Anchor occurrences: 1; verified .codex/hooks.json:9 at 0c5acf0915.
# Anchor: "command": "sh scripts/sdd/codex_hook.sh",
{
  "PostToolUse": [{
    "matcher": "Bash",
    "hooks": [{
      "type": "command",
      "command": "parrot sdd experience hook --host codex --event post",
      "timeout": 5
    }]
  }]
}
```

**Why**: This file owns the host-install behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `.agents/hooks.json` (MODIFY)

```text
# Anchor occurrences: 1; verified .agents/hooks.json:9 at 0c5acf0915.
# Anchor: "command": "sh ../scripts/sdd/agy_hook.sh",
{
  "parrot-sdd-experience": {
    "PostToolUse": [{
      "matcher": "run_command",
      "hooks": [{"type": "command", "command": "parrot sdd experience hook --host agy --event post", "timeout": 5}]
    }],
    "PostInvocation": [
      {"type": "command", "command": "parrot sdd experience hook --host agy --event post-invocation", "timeout": 5}
    ]
  }
}
```

**Why**: This file owns the host-install behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/sdd/test_installer.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/tests/sdd/test_installer.py:32 at 0c5acf0915.
# Anchor: def empty_repo(tmp_path: Path) -> Path:
# Add tests beside the existing cases; do not replace the quoted fixture/class.
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.sdd import installer

def test_agy_hooks_json_shape(tmp_path: Path) -> None:
    """Verify agy hooks json shape. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_agy_permissions_preserved(tmp_path: Path) -> None:
    """Verify agy permissions preserved. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_codex_experience_hook_shape(tmp_path: Path) -> None:
    """Verify codex experience hook shape. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the host-install behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/sdd/installer.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `.codex/hooks.json` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `.agents/hooks.json` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/sdd/test_installer.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: exact JSON shapes, idempotent upgrade, unchanged permission group, no pre experience hook, review profiles remain replay-only.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_installer.py -q`

## Test Specification

Required behavioral cases: exact JSON shapes, idempotent upgrade, unchanged permission group, no pre experience hook, review profiles remain replay-only.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5605` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
