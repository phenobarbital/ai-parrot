# TASK-5595: Shared pairing and evidence transition engine

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5588, TASK-5590, TASK-5593
**Assigned-to**: unassigned

## Context

Implement Module 4 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Implement on_outcome as the single stdlib transition engine for hooks and interceptors. Use TYPE_CHECKING for CommandOutcome so runtime never imports Pydantic. Unknown outcomes are strict no-ops; pair only eligible same-family retries, track trigger/fix-family injection evidence, cooldown and per-observation dedup under session lock. Render escaped labelled advice within 700 characters. Persist enough normalized command-occurrence aliases to reconcile codex hook IDs with replay IDs without suppressing repeated commands. Consume trigger stubs with lesson_id, state, solution_rev, executable, subcommand, error_tokens, fix_executable, fix_subcommand, advice and recording_session. A callback matcher is synchronous and consults the published map; do not call an async service from it.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py` | CREATE | Scoped deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_transitions.py` | CREATE | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from __future__ import annotations
from collections.abc import Callable, Mapping
from parrot.knowledge.wiki.experience.fastpath import append_event, leading_command, update_session
from parrot.knowledge.wiki.experience.models import CommandOutcome
from parrot.knowledge.wiki.experience.service import ExperienceService
from parrot.knowledge.wiki.experience.transitions import on_outcome
from pathlib import Path
from typing import TYPE_CHECKING, Any
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

No existing class/function is consumed beyond the standard library and declared dependencies. Existing edit anchors are quoted per file below.

### Dependency Interfaces

transitions: TASK-5588: consumes the fastpath contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/__init__.py, packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py; TASK-5590: consumes the event-schemas contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py; TASK-5593: consumes the service contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/service.py

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `packages/ai-parrot/tests/knowledge/wiki/experience/test_transitions.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_transitions.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Implement on_outcome as the single stdlib transition engine for hooks and interceptors. Use TYPE_CHECKING for CommandOutcome so runtime never imports Pydantic. Unknown outcomes are strict no-ops; pair only eligible same-family retries, track trigger/fix-family injection evidence, cooldown and per-observation dedup under session lock. Render escaped labelled advice within 700 characters. Persist enough normalized command-occurrence aliases to reconcile codex hook IDs with replay IDs without suppressing repeated commands. Consume trigger stubs with lesson_id, state, solution_rev, executable, subcommand, error_tokens, fix_executable, fix_subcommand, advice and recording_session. A callback matcher is synchronous and consults the published map; do not call an async service from it.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py` (CREATE)

```python
"""Shared stdlib-only pairing, evidence and advice transitions."""
from __future__ import annotations
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any
from parrot.knowledge.wiki.experience.fastpath import append_event, leading_command, update_session
if TYPE_CHECKING:
    from parrot.knowledge.wiki.experience.models import CommandOutcome

def on_outcome(plane_dir: Path, *, session: str, command: str, outcome: CommandOutcome,
               seat: str, matcher: Callable[[str, str, str], Mapping[str, Any] | None]) -> str | None:
    """Apply one observation atomically and return bounded advisory data."""
    # FILL IN: unknown -> no change; eligibility, evidence, revision and dedup rules from §2.
    # FILL IN: use duck-typed outcome attributes; never import models at runtime.
    # FILL IN: preserve pending state, bounded locks and fixed escaped template; AC1-AC3.
```

**Why**: This file owns the transitions behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/knowledge/wiki/experience/test_transitions.py` (CREATE)

```python
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.experience.transitions import on_outcome
from parrot.knowledge.wiki.experience.service import ExperienceService

def test_hook_pairing_drafts_lesson(tmp_path: Path) -> None:
    """Verify hook pairing drafts lesson. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_hook_validation_by_fix_family(tmp_path: Path) -> None:
    """Verify hook validation by fix family. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_hook_validation_and_refutation(tmp_path: Path) -> None:
    """Verify hook validation and refutation. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_hook_excluded_executables(tmp_path: Path) -> None:
    """Verify hook excluded executables. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_hook_duplicate_callback_idempotent(tmp_path: Path) -> None:
    """Verify hook duplicate callback idempotent. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_advice_escapes_lesson_text(tmp_path: Path) -> None:
    """Verify advice escapes lesson text. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_codex_occurrence_aliases(tmp_path: Path) -> None:
    """Verify codex occurrence aliases. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the transitions behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/experience/test_transitions.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: retry pairing, cross-family non-pairing, fix-family validation, trigger refutation, unrelated failures leave injection pending, exclusions, unknown outcomes, duplicate callbacks, cooldown, adversarial lesson text and codex occurrence alias matching.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_transitions.py -q`

## Test Specification

Required behavioral cases: retry pairing, cross-family non-pairing, fix-family validation, trigger refutation, unrelated failures leave injection pending, exclusions, unknown outcomes, duplicate callbacks, cooldown, adversarial lesson text and codex occurrence alias matching.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5595` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
