# TASK-5599: Experience CLI noun and lifecycle commands

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5593, TASK-5597, TASK-5598, TASK-5596
**Assigned-to**: unassigned

## Context

Implement Module 3 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Register init, brief, record, list, show, retire, sync, export, rebuild and hook. Use existing main(argv)->int script pattern. init creates/configures plane; ordinary reads on absent plane are silent success. export refreshes, graduates, then exports. Use stdout.write for CLI output and logging for diagnostics; no print. Host-side sync/export are never called from hook.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py` | CREATE | Scoped deliverable |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/tests/sdd/test_experience_cli.py` | CREATE | Task-specific regression coverage |
| `packages/ai-parrot/tests/sdd/test_sdd_cli.py` | MODIFY | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from __future__ import annotations
from collections.abc import Sequence
from parrot.knowledge.wiki.experience.graduation import graduate
from parrot.knowledge.wiki.experience.service import ExperienceService
from parrot.knowledge.wiki.experience.sync import export_shared, register_namespace, sync_global
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.sdd.scripts.experience_cli import main
from pathlib import Path
import asyncio
import pytest
import sys
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService` — `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:149`
```python
class LedgerService:
```

- `sym:packages/ai-parrot/src/parrot/sdd/cli.py#_mount` — `packages/ai-parrot/src/parrot/sdd/cli.py:349`
```python
def _mount(noun: click.Group, verb: str, module: str, prefix: tuple[str, ...], help_: str) -> None:
```

### Dependency Interfaces

cli: TASK-5593: consumes the service contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/service.py; TASK-5597: consumes the graduation contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/graduation.py; TASK-5598: consumes the sync contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/sync.py; TASK-5596: consumes the hooks contract in packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py, packages/ai-parrot/src/parrot/launcher.py

### Does NOT Exist

- `packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `packages/ai-parrot/tests/sdd/test_experience_cli.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_experience_cli.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_sdd_cli.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#_mount"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Register init, brief, record, list, show, retire, sync, export, rebuild and hook. Use existing main(argv)->int script pattern. init creates/configures plane; ordinary reads on absent plane are silent success. export refreshes, graduates, then exports. Use stdout.write for CLI output and logging for diagnostics; no print. Host-side sync/export are never called from hook.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py` (CREATE)

```python
"""CLI lifecycle operations for the experience plane."""
from __future__ import annotations
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from parrot.knowledge.wiki.experience.service import ExperienceService
from parrot.knowledge.wiki.experience.graduation import graduate
from parrot.knowledge.wiki.experience.sync import export_shared, register_namespace, sync_global
from parrot.knowledge.wiki.ledger.service import LedgerService

def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch lifecycle verbs; 0 on success/absent plane, 2 on invalid usage."""
    # FILL IN: argparse shapes in §2 New Public Interfaces; stdout.write for output.
    # FILL IN: async service calls via one asyncio.run boundary; export ordering.
    # FILL IN: init is explicit creation; normal missing-plane operations stay silent.

if __name__ == "__main__":
    sys.exit(main())
```

**Why**: This file owns the cli behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/src/parrot/sdd/cli.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/cli.py:281 at 0c5acf0915.
# Anchor: "review": ("review_checkpoint", (), "Review: prepare | validate | record."),
# Add a sibling noun to VERBS (outside the task noun containing review):
"experience": {
    "init": ("experience_cli", ("init",), "Initialize the experience plane."),
    "brief": ("experience_cli", ("brief",), "Show known pitfalls."),
    "record": ("experience_cli", ("record",), "Record a candidate lesson."),
    "list": ("experience_cli", ("list",), "List experience lessons."),
    "show": ("experience_cli", ("show",), "Show one lesson."),
    "retire": ("experience_cli", ("retire",), "Retire one lesson."),
    "sync": ("experience_cli", ("sync",), "Sync global experience events."),
    "export": ("experience_cli", ("export",), "Export shared lesson definitions."),
    "rebuild": ("experience_cli", ("rebuild",), "Rebuild experience indexes."),
    "hook": ("experience_hook", (), "Handle a host hook event."),
},
```

**Why**: This file owns the cli behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/sdd/test_experience_cli.py` (CREATE)

```python
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.sdd.scripts.experience_cli import main

def test_cli_missing_plane_is_silent(tmp_path: Path) -> None:
    """Verify cli missing plane is silent. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_cli_export_order(tmp_path: Path) -> None:
    """Verify cli export order. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the cli behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/sdd/test_sdd_cli.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/tests/sdd/test_sdd_cli.py:16 at 0c5acf0915.
# Anchor: def test_lazy_registration() -> None:
# Add tests beside the existing cases; do not replace the quoted fixture/class.
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.sdd.scripts.experience_cli import main

def test_cli_usage_errors(tmp_path: Path) -> None:
    """Verify cli usage errors. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_cli_init_namespace(tmp_path: Path) -> None:
    """Verify cli init namespace. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the cli behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/sdd/cli.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/sdd/test_experience_cli.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/sdd/test_sdd_cli.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: argument errors exit 2, missing plane silent 0, disabled no-op, JSON/text output, init namespace, task-title/files briefing extraction, export ordering and full verb registration.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_experience_cli.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`

## Test Specification

Required behavioral cases: argument errors exit 2, missing plane silent 0, disabled no-op, JSON/text output, init namespace, task-title/files briefing extraction, export ordering and full verb registration.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5599` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
