# TASK-3679: ExecutionPool public API; engine stops reaching into pool internals

**Feature**: FEAT-599 — sdd-coder engine fixes 2 (suspension attribution + pool encapsulation + settlement hygiene)
**Spec**: `sdd/specs/sdd-coder-engine-fixes-2.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3678
**Assigned-to**: unassigned
**discovered_from**: issue:700660c7f663

---

## Context

Spec §1 item 3 / §2 M3. `engine.py` reads or writes eleven private
`ExecutionPool` attributes from 35 sites and locally imports `_effective_key`
five times. The pool's docstring promises an admit/release/suspend/view/
assigner API; the erosion let a `str`-for-`RosterSeat` bug through
(commit `84ede6b60`). This task gives the pool the narrow accessors the engine
needs and converts every site, then locks it with a source-level test.

## Scope

- `pool.py`: `effective_key` (public; `_effective_key` alias kept), `status`,
  `seats`, `persistence_degraded` properties; `resolve_admission`,
  `restore_local_exclusions`, `require_fallback`, `set_persistence_degraded`,
  `mark_exhausted`, `select_free_seat`.
- `engine.py`: convert all sites per the spec §2 mapping table; module-level
  `effective_key` import; delete the `noqa: SLF001` comment at :2046.
- Tests: pool API tests + `test_engine_has_no_private_pool_access`.

**NOT in scope**: rewriting tests that inspect `pool._…` themselves; any
selection-policy change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py` | MODIFY | public API |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | call-site conversion |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_pool.py` | MODIFY | API tests |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_pool_encapsulation.py` | CREATE | source-level guard |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.pool import ExecutionPool, roster_fingerprint, SeatBusyError  # engine.py:114 (add `effective_key`)
from parrot.flows.dev_loop.sdd_coder.models import ExecutionStatus, RosterSeat, SeatKind  # models.py
```

### Existing Signatures to Use
```python
# pool.py
def _effective_key(seat: RosterSeat) -> Optional[ModelKey]   # :53
self._condition: Condition; self._status: ExecutionStatus; self._seats: List[RosterSeat]
self._admitted: Dict[str, Tuple[str, ModelKey]]; self._busy_seats: Set[ModelKey]
self._initial_exclusions / self._local_exclusions: Set[ModelKey]; self._seat_views: Dict[ModelKey, PoolSeatView]
self._fallback_required: bool; self._fallback_reason: str; self._persistence_degraded: bool
async def close(self) -> None            # :394 sets "closed" + notify_all
async def mark_recovery_required(self)   # :399
# engine.py sites — see spec §6 Edit Sites table (re-verify counts; TASK-3677/3678 shift lines)
async def _select_native_retry_seat(self, pool, tried_seats, *, eligible_labels=None) -> Optional[RosterSeat]  # ~:3371
async def _select_retry_seat(self, pool, failed_label, tried_seats, *, eligible_labels=None) -> Optional[RosterSeat]  # ~:3421
```

### Does NOT Exist
- ~~`ExecutionPool.status` setter~~ — status transitions only via `close()` / `mark_recovery_required()` / `mark_exhausted()` / `suspend()`.
- ~~`ExecutionPool.condition` property~~ — the condition stays private; waiting is done inside `select_free_seat`.
- ~~`ChunkAssigner.retry_seat` accepting a pool~~ — legacy path unchanged.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_pool.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_pool_encapsulation.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py#ExecutionPool",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py#_effective_key",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Rename `_effective_key` → `effective_key`, keep `_effective_key = effective_key` — *why*: tests import the old name.
2. Add the accessors/mutators and `select_free_seat` to `ExecutionPool` — *why*: one owner of the condition and the seat sets.
3. Convert every engine site per the spec §2 table; `_select_native_retry_seat` / `_select_retry_seat` pool bodies become one `select_free_seat` call each (keep their docstrings and the legacy `pool is None` branches) — *why*: AC4.
4. Add tests; the guard test reads `engine.py` source and asserts `re.search(r"\bpool\._[a-z]", src) is None` and `"_effective_key" not in src`.

### `pool.py` (MODIFY) — public API (sketch; full docstrings required)
```python
    @property
    def status(self) -> ExecutionStatus: return self._status
    @property
    def seats(self) -> List[RosterSeat]: return list(self._seats)
    @property
    def persistence_degraded(self) -> bool: return self._persistence_degraded
    def resolve_admission(self, attempt_uid: str) -> Optional[Tuple[str, ModelKey]]: return self._admitted.get(attempt_uid)
    def restore_local_exclusions(self, keys: Iterable[ModelKey]) -> None: self._local_exclusions = set(keys)
    def require_fallback(self, reason: str) -> None: self._fallback_required = True; self._fallback_reason = reason
    def set_persistence_degraded(self, degraded: bool) -> None: self._persistence_degraded = degraded
    async def mark_exhausted(self) -> None:  # under condition: self._status = "exhausted"; notify_all
    async def select_free_seat(self, *, kind: SeatKind, tried_seats: Set[str], eligible_labels: Optional[Set[str]] = None, wait: bool = False) -> Optional[RosterSeat]:
        # FILL IN: port _select_retry_seat's loop (engine.py ~:3457-3516) generalised over `kind`;
        #   wait=False returns None instead of awaiting the condition — bounded by spec §2 M3 + §7 native never-wait rule
```

### `engine.py` (MODIFY)
Apply the spec §2 mapping table row by row. `end_execution`'s `pool._status = "closed"` becomes `await pool.close()` (also wakes waiters — acceptable, documented).

### `test_pool_encapsulation.py` (CREATE)
```python
"""FEAT-599 / issue:700660c7f663: engine.py must use ExecutionPool's public API only."""
import re
from pathlib import Path
import parrot.flows.dev_loop.sdd_coder.engine as engine_module

def test_engine_has_no_private_pool_access() -> None:
    src = Path(engine_module.__file__).read_text(encoding="utf-8")
    assert re.search(r"\bpool\._[a-z]", src) is None
    assert "_effective_key" not in src
```

### FILL IN checklist
- [ ] `select_free_seat` body — behavior-preserving port
- [ ] all 35 engine sites converted — AC4
- [ ] API tests — spec §4 M3 rows

---

## Acceptance Criteria

- [ ] AC4: guard test passes; `grep -c 'pool\._' engine.py` counts only comments (or 0).
- [ ] all existing `sdd_coder` tests pass (`test_engine_dispatch.py`, `test_execution_pool_integration.py`, `test_native_observations.py`, `test_background_mcp.py` inspect pool internals and must be unaffected).
- [ ] `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_pool.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_pool_encapsulation.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_native_observations.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_mcp.py -q`

---

## Completion Note

(Agent fills this in when done)
