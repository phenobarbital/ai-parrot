# TASK-5609: Experience lifecycle integration in launch and closeout

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5598, TASK-5599, TASK-5605
**Assigned-to**: unassigned

## Context

Implement Module 11 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Wire best-effort sync into host sandbox preflight and namespace setup into installer initialization without making a missing plane fatal. At sdd-done Step 7 run sync/export inside feature worktree before staging; include only newly generated experience definition files in that closeout commit. Update all command/workflow/skill twins. Preserve host approval and push boundaries.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/tests/sdd/test_installer.py` | MODIFY | Task-specific regression coverage |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` | MODIFY | Task-specific regression coverage |
| `.claude/commands/sdd-done.md` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-done.md` | MODIFY | Scoped deliverable |
| `.agent/workflows/sdd-done.md` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-done.md` | MODIFY | Scoped deliverable |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-done/SKILL.md` | MODIFY | Scoped deliverable |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from parrot.flows.dev_loop.feature_launcher import _preflight_sandbox
from parrot.knowledge.wiki.experience.fastpath import resolve_plane_dir
from parrot.knowledge.wiki.experience.sync import register_namespace
from parrot.knowledge.wiki.experience.sync import sync_global
from pathlib import Path
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py#_preflight_sandbox` — `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:95`
```python
def _preflight_sandbox(worktree: Path, allowed_domains: Sequence[str]) -> None:
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

lifecycle: TASK-5598: consumes the sync contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/sync.py; TASK-5599: consumes the cli contract in packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py, packages/ai-parrot/src/parrot/sdd/cli.py; TASK-5605: serializes writes to packages/ai-parrot/src/parrot/sdd/installer.py, packages/ai-parrot/tests/sdd/test_installer.py

### Does NOT Exist

- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/installer.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_installer.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_sdd_launch.py",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-done.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-done.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-done.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-done.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-done/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-done/SKILL.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py#_preflight_sandbox",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#install_sdd_integration"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Wire best-effort sync into host sandbox preflight and namespace setup into installer initialization without making a missing plane fatal. At sdd-done Step 7 run sync/export inside feature worktree before staging; include only newly generated experience definition files in that closeout commit. Update all command/workflow/skill twins. Preserve host approval and push boundaries.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:98 at 0c5acf0915.
# Anchor: native_claude_sandbox.plan_native_launch(worktree, allowed_domains=allowed_domains)
from parrot.knowledge.wiki.experience.fastpath import resolve_plane_dir
from parrot.knowledge.wiki.experience.sync import sync_global
# In host _preflight_sandbox before plan_native_launch:
try:
    plane = resolve_plane_dir(worktree)
    if plane is not None:
        sync_global(plane)
except Exception:
    # FILL IN: use existing module logger; debug only, never block launch.
    pass
```

**Why**: This file owns the lifecycle behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/src/parrot/sdd/installer.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/installer.py:399 at 0c5acf0915.
# Anchor: def _install_dangerous_guard(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> list[str]:
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/installer.py:500 at 0c5acf0915.
# Anchor: AGY_HOOKS_PATH = Path(".agents/hooks.json")
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/installer.py:1515 at 0c5acf0915.
# Anchor: def install_sdd_integration(
from parrot.knowledge.wiki.experience.sync import register_namespace
# FILL IN: add idempotent host initialization through the installer plan/apply
# flow; call register_namespace(root) after shared config exists. Respect dry_run,
# receipts and caller host selection; preserve previous experience hook steps.
# Missing/unwritable plane is nonfatal; never grant global writes to workers.
```

**Why**: This file owns the lifecycle behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/sdd/test_installer.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/tests/sdd/test_installer.py:32 at 0c5acf0915.
# Anchor: def empty_repo(tmp_path: Path) -> Path:
# Add tests beside the existing cases; do not replace the quoted fixture/class.
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.flows.dev_loop.feature_launcher import _preflight_sandbox

@pytest.mark.asyncio
async def test_preflight_sync_failure_is_nonfatal(tmp_path: Path) -> None:
    """Verify preflight sync failure is nonfatal. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_closeout_exports_in_worktree(tmp_path: Path) -> None:
    """Verify closeout exports in worktree. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the lifecycle behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/sdd/test_sdd_launch.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/tests/sdd/test_sdd_launch.py:22 at 0c5acf0915.
# Anchor: def _restore_sandbox_mode(monkeypatch: pytest.MonkeyPatch) -> None:
# Add tests beside the existing cases; do not replace the quoted fixture/class.
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.flows.dev_loop.feature_launcher import _preflight_sandbox

@pytest.mark.asyncio
async def test_experience_namespace_install(tmp_path: Path) -> None:
    """Verify experience namespace install. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the lifecycle behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `.claude/commands/sdd-done.md` (MODIFY)

```text
# Anchor occurrences: 1; verified .claude/commands/sdd-done.md:502 at 0c5acf0915.
# Anchor: git -C "$WORKTREE_PATH" add "$INDEX" sdd/tasks/completed/
At Step 7 inside the feature worktree, immediately before scoped staging:
parrot sdd experience sync
parrot sdd experience export
Sync is best-effort. Inspect the exported paths, then stage only new files under
sdd/experience/lessons/ with the existing index/completed-task closeout commit.
FILL IN: adapt to each host syntax, preserve current approval gates and unrelated staging.
```

**Why**: This file owns the lifecycle behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-done.md` (MODIFY)

```text
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-done.md:502 at 0c5acf0915.
# Anchor: git -C "$WORKTREE_PATH" add "$INDEX" sdd/tasks/completed/
At Step 7 inside the feature worktree, immediately before scoped staging:
parrot sdd experience sync
parrot sdd experience export
Sync is best-effort. Inspect the exported paths, then stage only new files under
sdd/experience/lessons/ with the existing index/completed-task closeout commit.
FILL IN: adapt to each host syntax, preserve current approval gates and unrelated staging.
```

**Why**: This file owns the lifecycle behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `.agent/workflows/sdd-done.md` (MODIFY)

```text
# Anchor occurrences: 1; verified .agent/workflows/sdd-done.md:391 at 0c5acf0915.
# Anchor: git -C "$WORKTREE_PATH" add "$INDEX" sdd/tasks/completed/
At Step 7 inside the feature worktree, immediately before scoped staging:
parrot sdd experience sync
parrot sdd experience export
Sync is best-effort. Inspect the exported paths, then stage only new files under
sdd/experience/lessons/ with the existing index/completed-task closeout commit.
FILL IN: adapt to each host syntax, preserve current approval gates and unrelated staging.
```

**Why**: This file owns the lifecycle behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-done.md` (MODIFY)

```text
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-done.md:391 at 0c5acf0915.
# Anchor: git -C "$WORKTREE_PATH" add "$INDEX" sdd/tasks/completed/
At Step 7 inside the feature worktree, immediately before scoped staging:
parrot sdd experience sync
parrot sdd experience export
Sync is best-effort. Inspect the exported paths, then stage only new files under
sdd/experience/lessons/ with the existing index/completed-task closeout commit.
FILL IN: adapt to each host syntax, preserve current approval gates and unrelated staging.
```

**Why**: This file owns the lifecycle behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `.agents/skills/sdd-done/SKILL.md` (MODIFY)

```text
# Anchor occurrences: 1; verified .agents/skills/sdd-done/SKILL.md:194 at 0c5acf0915.
# Anchor: - stage only the index and this feature's task files, verify cached names
At Step 7 inside the feature worktree, immediately before scoped staging:
parrot sdd experience sync
parrot sdd experience export
Sync is best-effort. Inspect the exported paths, then stage only new files under
sdd/experience/lessons/ with the existing index/completed-task closeout commit.
FILL IN: adapt to each host syntax, preserve current approval gates and unrelated staging.
```

**Why**: This file owns the lifecycle behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-done/SKILL.md` (MODIFY)

```text
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-done/SKILL.md:194 at 0c5acf0915.
# Anchor: - stage only the index and this feature's task files, verify cached names
At Step 7 inside the feature worktree, immediately before scoped staging:
parrot sdd experience sync
parrot sdd experience export
Sync is best-effort. Inspect the exported paths, then stage only new files under
sdd/experience/lessons/ with the existing index/completed-task closeout commit.
FILL IN: adapt to each host syntax, preserve current approval gates and unrelated staging.
```

**Why**: This file owns the lifecycle behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/sdd/installer.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/sdd/test_installer.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/sdd/test_sdd_launch.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `.claude/commands/sdd-done.md` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-done.md` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `.agent/workflows/sdd-done.md` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-done.md` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `.agents/skills/sdd-done/SKILL.md` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-done/SKILL.md` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: preflight failure isolation, installer namespace idempotency, worktree export location, scoped closeout staging instructions and all asset twins.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_installer.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_launch.py -q`
- `pytest tests/sdd_scripts/test_check_asset_sync.py -q`

## Test Specification

Required behavioral cases: preflight failure isolation, installer namespace idempotency, worktree export location, scoped closeout staging instructions and all asset twins.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5609` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
