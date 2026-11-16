# TASK-5679: Deterministic review export and replayable archives

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5678, TASK-5662
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes lazy command group and overlapping cli.py from TASK-5678; Consumes durable review/archive source from TASK-5662

## Context

Implement the bounded M6 slice of FEAT-892 revision 0.2. The owner's accepted
section 8 decisions govern defaults; earlier proposed wording is not permission to change them.
These are planning artifacts, not evidence that carried G1–G4 gates passed.

## Release Preconditions

No additional owner decision is required beyond completed dependency contracts. Do not bypass a blocked dependency.

Before releasing any blocked task, record the accepted amendment in the spec, expand its
Validation Contract with the released module test paths, regenerate the index test contract
using `parrot sdd tests contract`, and change status through the normal SDD workflow.
Do not infer gate acceptance from a completed spike or from the spec's approved body label.
The current scheduler treats every non-done status as pending: `blocked` is documentary,
not an automatic dispatch fence. Do not launch this feature unattended while gates remain;
the task executor must stop before code if its release preconditions are unmet.

## Scope

- Stable evidence export without training dependencies (`packages/ai-parrot/src/parrot/memory/dynamics/export.py`).
- Wire export command to deterministic exporter (`packages/ai-parrot/src/parrot/memory/dynamics/cli.py`).
- Stable mappings, round trip and export failure recovery (`packages/ai-parrot/tests/memory/dynamics/test_export.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/dynamics/export.py` | CREATE | Stable evidence export without training dependencies |
| `packages/ai-parrot/src/parrot/memory/dynamics/cli.py` | MODIFY | Wire export command to deterministic exporter |
| `packages/ai-parrot/tests/memory/dynamics/test_export.py` | CREATE | Stable mappings, round trip and export failure recovery |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from parrot.memory.episodic.models import MemoryNamespace
from pathlib import Path
from typing import Any
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/memory/dynamics/cli.py` is created by TASK-5678; anchor `def register_memory_commands(group: click.Group) -> None:` is planned, not an existing verified symbol.

### Does NOT Exist

- `packages/ai-parrot/src/parrot/memory/dynamics/export.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/dynamics/test_export.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/dynamics/export.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/dynamics/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_export.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

Use async I/O, strict hints, Pydantic v2 and Google docstrings; log through self.logger or
the module logger. Format Python with black (120) and run scoped ruff. Keep test logs under
artifacts/logs. All DB/process fixtures are isolated; no shared DDL or dependency mutation is
authorized. User explicitly confirmed that the new AgentMemoryToolkit remains in core at
parrot.memory.agent_memory; do not move it into parrot_tools.

## Implementation Blueprint

### Steps (in order)

1. Verify release preconditions and dependency contracts — unresolved evidence must not become invented implementation policy.
2. Recheck the exact anchors and imports below after dependencies land — overlapping writers deliberately run in sequence.
3. Apply each per-file block and complete its bounded FILL IN items — preserve public contracts outside this task's scope.
4. Implement the behavioral cases below with real temporary stores where persistence matters — mocks alone cannot prove durability.
5. Run the narrow validation commands and scoped style checks — do not mark missing backend evidence as a passing persistence test.

### `packages/ai-parrot/src/parrot/memory/dynamics/export.py` (CREATE)

```python
"""Deterministic export of durable review evidence and parameter provenance."""
from pathlib import Path
from typing import Any
from parrot.memory.episodic.models import MemoryNamespace

async def export_reviews(*, namespace: MemoryNamespace, destination: Path) -> dict[str, Any]:
    """Export replayable evidence with stable card mapping and immutable parameter provenance."""
    # FILL IN: resolve explicitly configured store, stable ordering/schema, atomic output — AC18/U4.
    # Retry failed post-commit export from durable evidence; no generic 90-day sweep of needed history.
    # No fitter, optimizer imports or invented historical per-memory grades.
    raise NotImplementedError
```

**Why:** Stable mappings and retained parameter provenance allow later fitting/replay without adding a serving-time optimizer.

### `packages/ai-parrot/src/parrot/memory/dynamics/cli.py` (MODIFY)

```python
# DEPENDENCY-CREATED MODIFY: packages/ai-parrot/src/parrot/memory/dynamics/cli.py from TASK-5678.
# Expected unique anchor: def register_memory_commands(group: click.Group) -> None:
# occurrences now: 0 (file does not exist on base); prerequisite blueprint declares 1.
# Re-read and verify exact count 1 after dependency lands; stop on mismatch.
# Wire export command to deterministic exporter.
# FILL IN: AC18/U4: identical source evidence produces stable mappings/order/provenance and an export suitable for the deferred fitting feature.
# FILL IN: AC12/AC18: post-commit export failure does not lose or reapply reviews; archives remain replayable after hot retention cleanup.
# FILL IN: AC18: no fit.py, fitting CLI or optimizer/dependency changes are introduced.
```

**Why:** Stable mappings and retained parameter provenance allow later fitting/replay without adding a serving-time optimizer.

### `packages/ai-parrot/tests/memory/dynamics/test_export.py` (CREATE)

```python
"""Behavioral acceptance tests for Deterministic review export and replayable archives."""
import pytest

def test_deterministic_round_trip() -> None:
    """Verify deterministic round trip."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_export_failure_replay_no_double_apply() -> None:
    """Verify export failure replay no double apply."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_archive_retains_required_provenance() -> None:
    """Verify archive retains required provenance."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Stable mappings and retained parameter provenance allow later fitting/replay without adding a serving-time optimizer.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/dynamics/export.py` — Stable evidence export without training dependencies; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/dynamics/cli.py` — Wire export command to deterministic exporter; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/dynamics/test_export.py` — Stable mappings, round trip and export failure recovery; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC18/U4: identical source evidence produces stable mappings/order/provenance and an export suitable for the deferred fitting feature.
- [ ] AC12/AC18: post-commit export failure does not lose or reapply reviews; archives remain replayable after hot retention cleanup.
- [ ] AC18: no fit.py, fitting CLI or optimizer/dependency changes are introduced.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_export.py -q`

## Test Specification

- `deterministic_round_trip`: AC18/U4: identical source evidence produces stable mappings/order/provenance and an export suitable for the deferred fitting feature.
- `export_failure_replay_no_double_apply`: AC12/AC18: post-commit export failure does not lose or reapply reviews; archives remain replayable after hot retention cleanup.
- `archive_retains_required_provenance`: AC18: no fit.py, fitting CLI or optimizer/dependency changes are introduced.

Use deterministic clocks, runtime-derived identities and isolated temporary stores. Preserve
CancelledError. Use subprocesses for crash/multiprocess checks, never shared production data.

## Agent Instructions

1. Use the FEAT-892 worktree provisioned by sdd-start; never implement on dev.
2. Check every Depends-on task is done and each Release Preconditions item is met; blocked is not runnable.
3. Read the full spec and reverify this task's Codebase Contract; refresh stale evidence before editing.
4. Implement only declared files plus normal SDD state; preserve concurrent/unrelated changes.
5. Run validation, commit scoped implementation, and finalize with `parrot sdd task finalize`
   using real TaskCompletionEvidence and the exact implementation HEAD. Let finalization own
   the completion note and active-to-completed move; do not fabricate completion evidence.
