# TASK-5615: SQLiteGateStore, resolve_gate_store and the shared store contract suite

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-5614
**Assigned-to**: unassigned

---

## Context

Spec §2.1 / Module 2, AC3: SQLite is the default when Redis is not configured; Redis and SQLite pass one parametrized contract suite. HelixDB is NOT implemented (spec §8 Q1 open): `resolve_gate_store` raises a clear error for `backend='helix'`.

---

## Scope

- Implement `SQLiteGateStore` (aiosqlite, single table `gates(gate_id PK, owner, status, opened_at, body JSON)`, created lazily).
- Create `stores/__init__.py` with `resolve_gate_store(*, backend: str | None = None, redis_client=None, sqlite_path=None) -> GateStore`: explicit backend wins; else Redis when a client is given; else SQLite at `sqlite_path` or a default under the user's parrot data dir.
- Write a parametrized contract suite (redis-fake, sqlite tmp_path) + resolver tests.

**NOT in scope**: HelixDB store.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/gates/stores/__init__.py` | CREATE | resolver + exports |
| `packages/ai-parrot/src/parrot/bots/flows/core/gates/stores/sqlite.py` | CREATE | SQLiteGateStore |
| `packages/ai-parrot/tests/flows/gates/test_store_contract.py` | CREATE | contract suite + resolver tests |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
import aiosqlite  # core dep: packages/ai-parrot/pyproject.toml:209 "aiosqlite>=0.17"
from parrot.bots.flows.core.gates.models import GateRecord, GateStore, GateError, GateErrorCode  # TASK-5612
from parrot.bots.flows.core.gates.stores.redis import RedisGateStore  # TASK-5614
```

### Existing Signatures to Use
```python
# none — this task only creates new modules
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop` imports inside `parrot/bots/flows/core/gates/` or `parrot/experts/`~~ — forbidden (spec Decisions `gate-core-independent-of-dev-loop`).
- ~~HelixDB client / `HelixGateStore`~~ — no client in the repo; spec §8 Q1 open — do NOT implement.
- ~~`ExpertManifest.stage`~~, ~~`RosterSeat.tier`~~, ~~`WikiSource.remember`~~, ~~`DecisionService.propose`/`.record`~~ — do not exist.


---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/core/gates/stores/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/core/gates/stores/sqlite.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/gates/test_store_contract.py",
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
1. Create sqlite.py and fill it (mkdir parents of path).
2. Create `__init__.py`.
3. Contract suite parametrized over both stores.

### Blocks

```python
# packages/ai-parrot/src/parrot/bots/flows/core/gates/stores/__init__.py  (CREATE)
"""Gate store backends and resolver."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from ..models import GateError, GateErrorCode, GateStore
from .redis import RedisGateStore
from .sqlite import SQLiteGateStore

def resolve_gate_store(*, backend: str | None = None, redis_client: Any = None, sqlite_path: Path | None = None) -> GateStore:
    """Pick a store: explicit backend → Redis if a client is given → SQLite default (AC3)."""
    # FILL IN: 'helix' → GateError(STORE_UNAVAILABLE, "HelixDB store not implemented (FEAT-890 §8 Q1)")
    # FILL IN: default sqlite path — reuse an existing parrot data-dir helper if one exists (grep before inventing); else Path.home()/".parrot"/"gates.sqlite"

__all__ = ["RedisGateStore", "SQLiteGateStore", "resolve_gate_store"]
```
```python
# packages/ai-parrot/src/parrot/bots/flows/core/gates/stores/sqlite.py  (CREATE)
"""SQLite gate store — default local backend (FEAT-890 M2)."""
from __future__ import annotations
import logging
from pathlib import Path
import aiosqlite
from ..models import GateRecord

class SQLiteGateStore:
    """GateStore on one SQLite file; schema created on first use."""
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.logger = logging.getLogger(__name__)
    async def put(self, record: GateRecord) -> None: ...   # FILL IN: upsert
    async def get(self, gate_id: str) -> GateRecord | None: ...  # FILL IN
    async def pending(self, owner: str | None = None) -> list[GateRecord]: ...  # FILL IN
```
**Why**: one connection per call keeps it safe across event loops; the file is the durable record for CLI runs without Redis.

### FILL IN checklist
- [ ] SQLite methods
- [ ] resolver branches + default path
- [ ] contract tests

---

## Acceptance Criteria

- [ ] AC3: SQLite chosen with no Redis; both stores pass the same suite; helix raises STORE_UNAVAILABLE.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/gates/test_store_contract.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5615 expert-stages-and-delegation verified`.

---

## Completion Note

*(Agent fills this in when done)*
