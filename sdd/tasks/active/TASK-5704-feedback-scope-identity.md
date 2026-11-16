# TASK-5704: Scope feedback imports while preserving existing episodes

**Feature**: FEAT-892 — Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Discovered-from**: `issue:fbc5627878da`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5675
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Depends on TASK-5675 because it creates feedback.py and test_feedback.py; this repair modifies both.

## Context

The global UUID5 import ID collides when the same feedback is imported into a
second namespace. Write-once storage ignores that insert, but the importer reports
success. The owner selected preservation of existing records after being offered
scope-aware IDs with compatibility versus visible rejection of a second scope.
Preserve every existing episode ID, timestamp, content, and provenance. New imports
use scoped IDs; existing imports are reused only in their exact namespace.
This is the accepted issue-specific amendment to D4, documented with this task.

## Scope

- Derive deterministic versioned IDs from the feedback ID and all seven namespace fields.
- Reuse the deployed legacy UUID5 form and the prefixed D4 form only in the exact scope.
- Retraction and restoration update only records belonging to the requested exact scope.
- Prove separate imports, replay, persistence, compatibility, and tombstone isolation with SQLite.

Out of scope: backend/schema changes, rewriting old IDs, other ledger issues, ranking and review fixes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/dynamics/feedback.py` | MODIFY | Scoped identity and exact-scope compatibility |
| `packages/ai-parrot/tests/memory/dynamics/test_feedback.py` | MODIFY | Cross-scope and legacy persistence regressions |
| `sdd/state/FEAT-892/feedback-scope-amendment.md` | CREATE | Accepted D4 compatibility amendment |

## Codebase Contract

Verified against the FEAT-892 worktree at e2314a8c06b4b84b91bdc7011e5f0c12c4b51b60;
these implementation files are not on dev yet. Recheck after dependencies land.

### Verified Imports

```python
import json
import uuid
from datetime import datetime
from pathlib import Path
import pytest
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedback, CoderFeedbackStore
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.memory.episodic.models import FEEDBACK_IMPORT_NAMESPACE, EpisodicMemory, MemoryNamespace
from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.dynamics.feedback import import_feedback
```

Standard-library json/uuid are available; pytest/Pydantic/aiosqlite are existing dependencies.

### Existing Signatures and Anchors

- `sym:packages/ai-parrot/src/parrot/memory/dynamics/feedback.py#import_feedback`: async `(root: Path, *, store: EpisodicMemoryStore, namespace: MemoryNamespace) -> dict[str, int]`.
- `sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace`: tenant_id, agent_id, model_id, user_id, session_id, room_id, crew_id; `build_filter()` omits None dimensions.
- `sym:packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py#SQLiteEpisodeBackend`: `store(episode)` is write-once; `update_metadata(episode_ids, patch)` addresses global IDs.
- Import anchor `import asyncio` occurs once; `episode_id = str(uuid.uuid5(FEEDBACK_IMPORT_NAMESPACE, feedback_id))` occurs twice, once in each import/retraction loop.
- Test anchor `async def test_stable_import_and_retraction_idempotency` occurs once.

### Does NOT Exist

- There is no importer-level scope-aware ID helper yet.
- `build_filter()` is not exact namespace equality; omitted optional fields are wildcards.
- Backend store return values do not prove a new row was inserted after an ID collision.

## Complexity Contract

```json
{"schema_version":1,"targets":[{"path":"packages/ai-parrot/src/parrot/memory/dynamics/feedback.py","action":"MODIFY"},{"path":"packages/ai-parrot/tests/memory/dynamics/test_feedback.py","action":"MODIFY"},{"path":"sdd/state/FEAT-892/feedback-scope-amendment.md","action":"CREATE"}],"contract_symbols":["sym:packages/ai-parrot/src/parrot/memory/dynamics/feedback.py#import_feedback","sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace","sym:packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py#SQLiteEpisodeBackend"]}
```

## Implementation Blueprint

1. Add canonical JSON encoding of a version tag, feedback ID and all namespace fields, including nulls — avoid delimiter collisions and omitted-field ambiguity.
2. Filter candidate episodes to exact field equality before resolving legacy IDs — broad queries must not authorize cross-scope updates.
3. Share ID resolution between record/retraction loops — preservation and tombstone replay must agree.
4. Add durable regression cases before the implementation — establish the failing cross-scope behavior.
5. Document compatibility — keep old rows and the permanent UUID namespace unchanged.

### `packages/ai-parrot/src/parrot/memory/dynamics/feedback.py` (MODIFY)

```python
# AFTER import asyncio (occurrences: 1), add json.
# BEFORE async def import_feedback( (occurrences: 1), define:
def _scoped_feedback_id(feedback_id: str, namespace: MemoryNamespace) -> str:
    """Build a deterministic ID from the complete import namespace."""
    # FILL IN: encode version, feedback ID and seven fields, including null, using json.dumps.
# Replace the two UUID5 assignments, disambiguated by their containing loops:
# for recorded_at, feedback in records:
# for feedback_id in retracted_ids:
# FILL IN: reuse exact-scope legacy/prefixed IDs, otherwise scoped ID; AC1–AC4.
```

Why: keeping stored IDs preserves references while new scope-aware IDs avoid global write-once collisions.

### `packages/ai-parrot/tests/memory/dynamics/test_feedback.py` (MODIFY)

```python
# Existing test anchor (occurrences: 1):
# async def test_stable_import_and_retraction_idempotency
# FILL IN: retain provenance/replay assertions and check new stable IDs behaviorally.
# Append parametrized async tests using real temporary SQLite stores:
# FILL IN: tenant/agent/model/user/session/room/crew separation; broad null scopes;
# old UUID5 forms preserved after close/reopen; isolated tombstones; AC1–AC4.
```

Why: persisted rows and counters expose the original silent loss; mocks cannot prove preservation.

### `sdd/state/FEAT-892/feedback-scope-amendment.md` (CREATE)

```markdown
# Feedback import identity amendment

Issue: issue:fbc5627878da. Owner direction: preserve existing records.
Supersedes D4 only for assigning new import IDs. Existing IDs remain unchanged.

New IDs include every namespace dimension with an explicit null representation.
Legacy unprefixed and D4-prefixed UUID5 IDs are reused only in their exact scope.
Retractions never update a different scope. No schema migration or row rewrite occurs.
```

### FILL IN checklist

- [ ] Implement canonical scope encoding and exact-scope legacy resolution.
- [ ] Prove distinct namespace persistence, replay, old-row preservation and tombstone isolation.
- [ ] Record exact encoding and compatibility rules in the amendment.

## Acceptance Criteria

- [ ] AC1: Identical feedback imports independently into each namespace; counters match persisted rows.
- [ ] AC2: Re-import is idempotent after reopening SQLite; IDs and provenance remain stable.
- [ ] AC3: Both historic ID forms are reused unchanged only in their exact original namespace, including null fields.
- [ ] AC4: Retractions/restorations affect only the requested exact namespace; existing rows are never rewritten to new IDs.
- [ ] Scoped pytest, black (120), ruff and diff checks pass; no dependency/schema changes.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_feedback.py -q`

## Test Specification

Use the existing CoderFeedbackStore/LedgerLog fixture and actual temporary SQLite files.
Check all seven dimensions separately, reverse broad/narrow import order, reopen the DB,
seed both legacy ID variants, compare stored timestamps/content/metadata, and interleave
imports and retractions across scopes. No shared services or paid providers.

## Agent Instructions

Work in the FEAT-892 worktree. Preserve concurrent edits. TASK-5675 must be done.
Commit only scoped files, retain logs in artifacts/logs, review semantics, and finalize
using parrot sdd task finalize with real validation/review evidence and the exact commit SHA.
