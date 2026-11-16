# TASK-5598: Global synchronization and immutable shared exports

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5593, TASK-5597
**Assigned-to**: unassigned

## Context

Implement Module 11 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Implement global_plane_dir, sync_global, shared_event_ids, export_shared and register_namespace. Resolve each evidence event tier through its lesson definition; copy global events with unchanged IDs. Export only definitions and derived lifecycle attestations to canonical content-digest O_EXCL files. Register absolute primary store paths without clobbering existing config. Never export hits/validations/refutations.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/sync.py` | CREATE | Scoped deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_sync.py` | CREATE | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from __future__ import annotations
from parrot.knowledge.wiki.experience import sync
from parrot.knowledge.wiki.experience.fastpath import append_event, safe_open
from parrot.knowledge.wiki.experience.graduation import graduate
from parrot.knowledge.wiki.experience.models import validate_event
from parrot.knowledge.wiki.project import find_shared_root
from parrot.launcher import parrot_home
from pathlib import Path
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/launcher.py#parrot_home` — `packages/ai-parrot/src/parrot/launcher.py:26`
```python
def parrot_home(env: Mapping[str, str] | None = None) -> Path:
```

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_shared_root` — `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1563`
```python
def find_shared_root(start: Path | None = None) -> Path | None:
```

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiNamespaceConfig` — `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:187`
```python
class WikiNamespaceConfig(BaseModel):
```

### Dependency Interfaces

sync: TASK-5593: consumes the service contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/service.py; TASK-5597: consumes the graduation contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/graduation.py

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/experience/sync.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `packages/ai-parrot/tests/knowledge/wiki/experience/test_sync.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/sync.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_sync.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiNamespaceConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_shared_root",
    "sym:packages/ai-parrot/src/parrot/launcher.py#parrot_home"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Implement global_plane_dir, sync_global, shared_event_ids, export_shared and register_namespace. Resolve each evidence event tier through its lesson definition; copy global events with unchanged IDs. Export only definitions and derived lifecycle attestations to canonical content-digest O_EXCL files. Register absolute primary store paths without clobbering existing config. Never export hits/validations/refutations.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/knowledge/wiki/experience/sync.py` (CREATE)

```python
"""sync experience component."""
from __future__ import annotations
from pathlib import Path
from parrot.launcher import parrot_home
from parrot.knowledge.wiki.project import find_shared_root
from parrot.knowledge.wiki.experience.fastpath import append_event, safe_open
from parrot.knowledge.wiki.experience.models import validate_event

SHARED_DIR = Path('sdd') / 'experience' / 'lessons'
DEFINITION_KINDS = frozenset({'lesson.recorded'})
ATTESTATION_KINDS = frozenset({'lesson.confirmed', 'lesson.quarantined', 'lesson.retired', 'lesson.graduated'})

def global_plane_dir() -> Path:
    """parrot_home() / 'experience' (parrot_home verified: launcher.py:26)."""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

def sync_global(repo_plane: Path) -> int:
    """Copy tier='global' events absent from the global log into it, same event_id; return the"""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

def shared_event_ids(checkout: Path) -> set[str]:
    """event_ids already present in any checkout/SHARED_DIR/*.jsonl file (safe_open, bounded)."""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

def export_shared(repo_plane: Path, checkout: Path) -> Path | None:
    """Collect DEFINITION_KINDS events not in shared_event_ids(), plus one attestation per lesson"""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

def register_namespace(root: Path) -> bool:
    """Add namespaces.experience = {store: '<absolute shared-root>/.parrot/experience'} to the"""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.
```

**Why**: This file owns the sync behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/knowledge/wiki/experience/test_sync.py` (CREATE)

```python
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.experience import sync
from parrot.knowledge.wiki.experience.graduation import graduate

def test_sync_global_moves_once(tmp_path: Path) -> None:
    """Verify sync global moves once. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_export_shared_redacted_definitions_only(tmp_path: Path) -> None:
    """Verify export shared redacted definitions only. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_export_carries_quarantine(tmp_path: Path) -> None:
    """Verify export carries quarantine. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_export_creates_new_file_only(tmp_path: Path) -> None:
    """Verify export creates new file only. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_export_filename_is_content_digest(tmp_path: Path) -> None:
    """Verify export filename is content digest. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_register_namespace_absolute(tmp_path: Path) -> None:
    """Verify register namespace absolute. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the sync behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/experience/sync.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/experience/test_sync.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: idempotent sync, event IDs preserved, global evidence routing, redaction, quarantine roundtrip, content-addressed immutable files, duplicate shared events, no data no file, absolute namespace from external worktree; graduation export carries the deterministic issue_id/owning ledger created by graduate.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_sync.py -q`

## Test Specification

Required behavioral cases: idempotent sync, event IDs preserved, global evidence routing, redaction, quarantine roundtrip, content-addressed immutable files, duplicate shared events, no data no file, absolute namespace from external worktree; graduation export carries the deterministic issue_id/owning ledger created by graduate.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5598` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
