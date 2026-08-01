# TASK-2048: CheckpointStore ABC + factory + FLOW_CHECKPOINT_* config

**Feature**: FEAT-399 — AgentsFlow State Checkpointing (Two-Tier Persistence)
**Spec**: `sdd/specs/agentsflow-state-checkpointing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2046
**Assigned-to**: unassigned

---

## Context

Spec §2 New Public Interfaces / §3 Module 3. The store contract every backend
implements (including the lease methods, resolved OQ3), the
`get_checkpoint_store()` factory (FEAT-147 `get_result_storage` pattern), and
the `FLOW_CHECKPOINT_*` env vars in `parrot/conf.py`.

---

## Scope

- Implement `store/base.py`: `CheckpointStore(ABC)` with the exact contract
  from spec §2: `put / latest / get / history / list_flows / delete_flow /
  acquire_lease / renew_lease / release_lease / close`.
- Implement `store/factory.py`: `get_checkpoint_store(arg)` — resolution
  order **instance > name arg > env `FLOW_CHECKPOINT_STORE` > default
  `"redis"`**; unknown name → `ValueError`. Backend names:
  `"redis" | "sqlite" | "postgres" | "mongodb"` (lazy imports so missing
  drivers only fail when selected).
- Add to `parrot/conf.py`: `FLOW_CHECKPOINT_STORE` (default `"redis"`),
  `FLOW_CHECKPOINT_DURABLE_STORE` (default unset), `FLOW_CHECKPOINT_REDIS_TTL`
  (default `86400`), `FLOW_CHECKPOINT_HISTORY` (default `10`),
  `FLOW_CHECKPOINT_SHUTDOWN_DEADLINE` (default `15`),
  `FLOW_CHECKPOINT_LEASE_TTL` (default `60`).
- Unit tests: factory resolution + env fallback + unknown-name error.

**NOT in scope**: concrete stores (TASK-2049/2050) — the factory may
reference their module paths but tests must not require Redis/DBs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/__init__.py` | CREATE | Sub-package, re-exports |
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/base.py` | CREATE | CheckpointStore ABC |
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/factory.py` | CREATE | get_checkpoint_store() |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | FLOW_CHECKPOINT_* env vars |
| `packages/ai-parrot/tests/flows/checkpoint/test_store_factory.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.core.checkpoint.model import FlowCheckpoint  # from TASK-2046
from parrot.conf import CREW_RESULT_STORAGE_REDIS_TTL  # verified: used at core/storage/backends/redis.py:16
```

### Existing Signatures to Use (pattern reference — COPY the pattern, do NOT couple)
```python
# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/factory.py
def get_result_storage(arg=None) -> ResultStorage: ...   # line 34 — arg > env > default resolution

# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/base.py
class ResultStorage(ABC):                                 # line 8
    async def save(self, collection: str, document: dict[str, Any]) -> None: ...  # line 18
    async def close(self) -> None: ...                    # line 27
```

Follow the existing `parrot/conf.py` style for the new env vars — read how
`CREW_RESULT_STORAGE_REDIS_TTL` is declared there and mirror it.

### Does NOT Exist
- ~~`CheckpointStore`, `get_checkpoint_store`~~ — introduced HERE.
- ~~`FLOW_CHECKPOINT_*` in parrot/conf.py today~~ — THIS task adds them.
- ~~A sqlite backend under `core/storage/backends/`~~ — FEAT-147 has none; checkpoint stores are a separate family (TASK-2050).
- ~~`RedisCheckpointStore` / `DurableCheckpointStore`~~ — TASK-2049/2050; factory imports them lazily inside the function body.

---

## Implementation Notes

### Key Constraints
- All ABC methods `async`; `close()` idempotent (FEAT-147 discipline).
- Lease methods return `bool` (acquired/renewed) — `release_lease` returns None
  and must be holder-checked (releasing someone else's lease is a no-op + warning).
- Factory lazy-imports concrete stores INSIDE the function to avoid hard
  Redis/DB import costs at package import time.

---

## Acceptance Criteria

- [ ] `test_factory_backend_selection_and_env_fallback` — arg > env > default; unknown raises ValueError.
- [ ] ABC unimplementable directly (`TypeError` on instantiation).
- [ ] `from parrot.conf import FLOW_CHECKPOINT_REDIS_TTL, FLOW_CHECKPOINT_HISTORY, FLOW_CHECKPOINT_SHUTDOWN_DEADLINE, FLOW_CHECKPOINT_LEASE_TTL` works with documented defaults.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/checkpoint/test_store_factory.py -v`
- [ ] `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/checkpoint/test_store_factory.py
def test_factory_instance_passthrough(fake_checkpoint_store):
    assert get_checkpoint_store(fake_checkpoint_store) is fake_checkpoint_store

def test_factory_env_fallback(monkeypatch):
    monkeypatch.setenv("FLOW_CHECKPOINT_STORE", "redis")
    ...  # resolves RedisCheckpointStore class (may mock the lazy import)

def test_factory_unknown_name_raises():
    with pytest.raises(ValueError, match="unknown"):
        get_checkpoint_store("etcd")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context
2. **Check dependencies** — TASK-2046 in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `factory.py:34` pattern and conf.py style before writing
4. **Update status** in `sdd/tasks/index/agentsflow-state-checkpointing.json` → `"in-progress"`
5. **Implement**, then **verify** all acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and update index → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
