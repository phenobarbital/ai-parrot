# TASK-5614: RedisGateStore

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-5612
**Assigned-to**: unassigned

---

## Context

Spec §2.1 / Module 2. Redis-backed store for deployments that have Redis (dev-loop already persists its gate actions in Redis streams, `streaming.py:106`).

---

## Scope

- Implement `RedisGateStore` in `core/gates/stores/redis.py`: one hash per gate (`gate:{gate_id}` → JSON) + a set of pending ids per owner and a global pending set.
- Constructor takes an async redis client (`redis.asyncio.Redis`) and a key prefix.
- Unit tests with an in-process fake async client.

**NOT in scope**: SQLite store and the resolver (TASK-5615). Moving dev-loop's action stream (TASK-5618) — the action stream remains dev-loop's event log; this store keeps gate *state*.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/gates/stores/redis.py` | CREATE | RedisGateStore |
| `packages/ai-parrot/tests/flows/gates/test_store_redis.py` | CREATE | unit tests |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
from parrot.bots.flows.core.gates.models import GateRecord, GateError, GateErrorCode  # TASK-5612
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py:106  self._actions_key = f"flow:{run_id}:actions"  (reference only)
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop` imports inside `parrot/bots/flows/core/gates/` or `parrot/experts/`~~ — forbidden (spec Decisions `gate-core-independent-of-dev-loop`).
- ~~HelixDB client / `HelixGateStore`~~ — no client in the repo; spec §8 Q1 open — do NOT implement.
- ~~`ExpertManifest.stage`~~, ~~`RosterSeat.tier`~~, ~~`WikiSource.remember`~~, ~~`DecisionService.propose`/`.record`~~ — do not exist.
- ~~`stores/__init__.py`~~ — created by TASK-5615; do not create it here (avoid file overlap). Tests import `parrot.bots.flows.core.gates.stores.redis` directly — namespace import works once TASK-5615 adds `__init__`; until then the test must import via the module path after creating no `__init__` (PEP 420 implicit namespace is acceptable inside the package tree).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/core/gates/stores/redis.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/gates/test_store_redis.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Conventions: `.claude/rules/codebase-conventions.md` (Pydantic v2, Google docstrings, `self.logger`, async I/O, no print).
- Worktree tests need `PYTHONPATH=packages/ai-parrot/src` (plus `packages/ai-parrot-integrations/src` / `packages/ai-parrot-tools/src` when touched).

---

## Implementation Blueprint

### Steps (in order)
1. Create the file.
2. Fill the three methods.
3. Tests with a small fake implementing set/get/sadd/srem/smembers.

### Blocks

```python
# packages/ai-parrot/src/parrot/bots/flows/core/gates/stores/redis.py  (CREATE)
"""Redis gate store (FEAT-890 M2)."""
from __future__ import annotations
import logging
from typing import Any
from ..models import GateRecord

class RedisGateStore:
    """GateStore over an async Redis client."""
    def __init__(self, client: Any, *, prefix: str = "parrot:gates") -> None:
        self.client = client
        self.prefix = prefix
        self.logger = logging.getLogger(__name__)

    def _key(self, gate_id: str) -> str:
        return f"{self.prefix}:{gate_id}"

    async def put(self, record: GateRecord) -> None:
        """Write the record and maintain pending sets (global + per owner)."""
        # FILL IN: set JSON (record.model_dump_json()); sadd/srem pending sets by record.status

    async def get(self, gate_id: str) -> GateRecord | None:
        """Return the record or None."""
        # FILL IN: get + GateRecord.model_validate_json

    async def pending(self, owner: str | None = None) -> list[GateRecord]:
        """Pending records, optionally for one owner, ordered by opened_at."""
        # FILL IN
```
**Why**: the client is injected so tests use a fake and production reuses the app's Redis pool.

### FILL IN checklist
- [ ] put/get/pending bodies
- [ ] fake client in tests

---

## Acceptance Criteria

- [ ] RedisGateStore satisfies `isinstance(store, GateStore)`.
- [ ] Tests pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/gates/test_store_redis.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5614 expert-stages-and-delegation verified`.

---

## Completion Note

*(Agent fills this in when done)*
