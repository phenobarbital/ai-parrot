# TASK-5610: Experience integration scenarios and wheel smoke

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5596, TASK-5599, TASK-5600, TASK-5602, TASK-5603, TASK-5604, TASK-5605, TASK-5607, TASK-5608, TASK-5609
**Assigned-to**: unassigned

## Context

Implement Module 12 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Add the motivating authored gh pr edit to gh api scenario across A/B/C/D sessions, external linked worktree plane resolution and fresh clone with deduplicated shared definitions. Add experience_cli and experience_hook wheel-only foreign-repo smoke scenarios. Use deterministic temporary repos, fake streams and temporary PARROT_HOME; never real global storage or paid host calls.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_end_to_end.py` | CREATE | Task-specific regression coverage |
| `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` | MODIFY | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from parrot.flows.dev_loop.experience import ExperienceInterceptor
from parrot.knowledge.wiki.experience.service import ExperienceService
from pathlib import Path
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py#Scenario` — `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py:341`
```python
class Scenario:
```

- `sym:packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py#_seed_feature` — `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py:126`
```python
def _seed_feature(clone: Path) -> None:
```

### Dependency Interfaces

integration: TASK-5596: consumes the hooks contract in packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py, packages/ai-parrot/src/parrot/launcher.py; TASK-5599: consumes the cli contract in packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py, packages/ai-parrot/src/parrot/sdd/cli.py; TASK-5600: consumes the claude-install contract in packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py, packages/ai-parrot/src/parrot/sdd/installer.py; TASK-5602: consumes the codex-replay contract in packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py; TASK-5603: consumes the agy-replay contract in packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py; TASK-5604: consumes the gemini-replay contract in packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py; TASK-5605: consumes the host-install contract in packages/ai-parrot/src/parrot/sdd/installer.py, .codex/hooks.json; TASK-5607: consumes the engine contract in packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py; TASK-5608: consumes the authoring-assets contract in .claude/commands/sdd-start.md, .agent/workflows/sdd-start.md; TASK-5609: consumes the lifecycle contract in packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py, packages/ai-parrot/src/parrot/sdd/installer.py

### Does NOT Exist

- `packages/ai-parrot/tests/knowledge/wiki/experience/test_end_to_end.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_end_to_end.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py#Scenario",
    "sym:packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py#_seed_feature"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Add the motivating authored gh pr edit to gh api scenario across A/B/C/D sessions, external linked worktree plane resolution and fresh clone with deduplicated shared definitions. Add experience_cli and experience_hook wheel-only foreign-repo smoke scenarios. Use deterministic temporary repos, fake streams and temporary PARROT_HOME; never real global storage or paid host calls.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/tests/knowledge/wiki/experience/test_end_to_end.py` (CREATE)

```python
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.experience.service import ExperienceService
from parrot.flows.dev_loop.experience import ExperienceInterceptor

@pytest.mark.asyncio
async def test_gh_pr_edit_end_to_end(tmp_path: Path) -> None:
    """Verify gh pr edit end to end. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_shared_log_feeds_fresh_clone(tmp_path: Path) -> None:
    """Verify shared log feeds fresh clone. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the integration behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py:461 at 0c5acf0915.
# Anchor: "migrate_index": Scenario(prepare=_seed_feature, expect_exit=_ANY_CLEAN),
# Add tests beside the existing cases; do not replace the quoted fixture/class.
# Add entries to SCENARIOS next to the verified migrate_index entry.
# FILL IN: define typed prepare functions matching Scenario's verified signature.
# experience_cli: run brief --task-file <seeded task> with no plane; expect 0, silent.
# experience_hook: supply a bounded Claude successful post payload; expect 0.
# Both run using installed wheel helpers in a foreign repository with no monorepo.
# Use Scenario(prepare=..., expect_exit=_ANY_CLEAN) only after replacing planning gaps.
```

**Why**: This file owns the integration behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/tests/knowledge/wiki/experience/test_end_to_end.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: candidate after A, fix-family validation in B/C, confirmed D briefing, terminal retirement, shared quarantine, primary plane external worktree, wheel import and missing-plane success.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_end_to_end.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py -q`

## Test Specification

Required behavioral cases: candidate after A, fix-family validation in B/C, confirmed D briefing, terminal retirement, shared quarantine, primary plane external worktree, wheel import and missing-plane success.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5610` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
