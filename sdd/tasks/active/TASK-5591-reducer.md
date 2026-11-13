# TASK-5591: Deterministic lesson reduction and failure matching

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5590
**Assigned-to**: unassigned

## Context

Implement Module 2 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Reduce deduplicated event sets independently of order. Partition evidence by solution revision, exclude recording sessions, apply retired/quarantined/confirmed/candidate precedence and deterministic revision ties. Only trusted shared-source attestations participate; local self-attestation cannot confirm or quarantine. Implement exact-family/Jaccard matching. Read only the loader-owned _shared_attestation private flag for shared attestations; never infer trust from payload fields.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/reducer.py` | CREATE | Scoped deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_reducer.py` | CREATE | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from __future__ import annotations
from collections.abc import Iterable
from parrot.knowledge.wiki.experience.fastpath import normalize_error
from parrot.knowledge.wiki.experience.models import ExperienceConfig, ExperienceEvent, Lesson
from parrot.knowledge.wiki.experience.reducer import reduce_events, match_score
from pathlib import Path
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

No existing class/function is consumed beyond the standard library and declared dependencies. Existing edit anchors are quoted per file below.

### Dependency Interfaces

reducer: TASK-5590: consumes the event-schemas contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/experience/reducer.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `packages/ai-parrot/tests/knowledge/wiki/experience/test_reducer.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/reducer.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_reducer.py",
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
2. Apply the per-file starting points and complete the scoped behavior — Reduce deduplicated event sets independently of order. Partition evidence by solution revision, exclude recording sessions, apply retired/quarantined/confirmed/candidate precedence and deterministic revision ties. Only trusted shared-source attestations participate; local self-attestation cannot confirm or quarantine. Implement exact-family/Jaccard matching. Read only the loader-owned _shared_attestation private flag for shared attestations; never infer trust from payload fields.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/knowledge/wiki/experience/reducer.py` (CREATE)

```python
"""reducer experience component."""
from __future__ import annotations
from collections.abc import Iterable
from parrot.knowledge.wiki.experience.models import ExperienceConfig, ExperienceEvent, Lesson
from parrot.knowledge.wiki.experience.fastpath import normalize_error

def reduce_events(events: Iterable[ExperienceEvent], config: ExperienceConfig) -> dict[str, Lesson]:
    """Derive lessons from a SET of events (§2 state table): de-duplicate by event_id, group by"""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

def match_score(lesson: Lesson, executable: str, subcommand: str, error: str) -> float:
    """0.0 unless executable and subcommand equal the trigger family; else 1.0 for an exact"""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.
```

**Why**: This file owns the reducer behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/knowledge/wiki/experience/test_reducer.py` (CREATE)

```python
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.experience.reducer import reduce_events, match_score

def test_reduce_candidate_to_confirmed(tmp_path: Path) -> None:
    """Verify reduce candidate to confirmed. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_reduce_refutations_quarantine(tmp_path: Path) -> None:
    """Verify reduce refutations quarantine. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_reduce_permutation_invariant(tmp_path: Path) -> None:
    """Verify reduce permutation invariant. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_reduce_ignores_forged_local_attestation(tmp_path: Path) -> None:
    """Verify reduce ignores forged local attestation. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_reduce_retired_is_terminal(tmp_path: Path) -> None:
    """Verify reduce retired is terminal. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_solution_revision_owns_evidence(tmp_path: Path) -> None:
    """Verify solution revision owns evidence. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_match_requires_family_and_jaccard(tmp_path: Path) -> None:
    """Verify match requires family and jaccard. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the reducer behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/experience/reducer.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/experience/test_reducer.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: 50 shuffled permutations with duplicates, revision evidence isolation, rediscovery, recorder exclusion, sticky quarantine, terminal retirement, local forgery, shared attestation and Jaccard near misses.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_reducer.py -q`

## Test Specification

Required behavioral cases: 50 shuffled permutations with duplicates, revision evidence isolation, rediscovery, recorder exclusion, sticky quarantine, terminal retirement, local forgery, shared attestation and Jaccard near misses.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5591` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
