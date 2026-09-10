# TASK-3134: `BudgetScope`, `BudgetRegistry`, Suspension Nonces and Snapshot Transfer

**Feature**: FEAT-550 — Cumulative Question Token Budgets for Bedrock and Mantle
**Spec**: `sdd/specs/token-budget-bedrock.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3133
**Assigned-to**: unassigned

---

## Context

Module 2 (spec §3 "Module 2: Question Scope and Resume Ownership"), first half. A
process-local `BudgetRegistry` owns active/suspended/closed ledgers keyed by an
opaque UUID `budget_operation_id`; a ContextVar carries only the **live** scope.
`BudgetScope` is the async context manager that binds the ContextVar, validates the
owning event loop, and on exit closes/suspends/retains state (spec §2.6).

TASK-3135 adds the coroutine/async-generator **entry adapters** on top of this module.

---

## Scope

- Create `packages/ai-parrot/src/parrot/clients/budget_scope.py` with:
  - module ContextVar `_CURRENT_SCOPE: ContextVar[Optional[BudgetScope]]` and
    helper `current_budget_scope() -> Optional[BudgetScope]`;
  - `BudgetScope` (spec skeleton: `__aenter__`/`__aexit__`), carrying `ledger`,
    `operation_id`, `policy`, `owner_call_id`, `is_root`, `loop_id`;
  - `BudgetRegistry` (spec skeleton: `create`, `resume`, `export_settled`, `release`)
    with bounded retention (`max_retained=1024`, `retention_seconds=3600`), never
    evicting active work; `BudgetRegistryFull` on a full registry;
  - suspension envelope helpers: `build_suspension_envelope(scope) -> dict` (keys
    `operation_id`, `policy`, `revision`, `consumed_floor`, `resume_nonce`,
    `owner_call_id`) and `TOKEN_BUDGET_STATE_KEY = "token_budget"`;
  - nonce consumption in `resume()` — second use raises `BudgetResumeConflict`;
    missing live state raises `BudgetStateMissing` unless an admissible snapshot
    is supplied; snapshot import validates identity/policy/nonce/floors
    (`BudgetSnapshotInvalid`), is idempotent for identical import, refuses to
    lower a known floor or reopen a closed operation;
  - `export_settled()` refuses in-flight/uncertain ledgers and **detaches** the
    suspended owner (transfer semantics);
  - a module-level default registry accessor `get_default_registry()`.
- Cross-loop guard: mutating a ledger from a different running loop raises
  `BudgetScopeConflict`.
- Write `packages/ai-parrot/tests/unit/clients/test_token_budget_scope.py` groups
  "Resume and snapshots" and "Registry lifecycle" (spec §4).

**NOT in scope**: kwargs parsing / method wrapping (TASK-3135); any client/bot
edit; distributed coordination (non-goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/budget_scope.py` | CREATE | Scope, registry, nonces, snapshot transfer |
| `packages/ai-parrot/tests/unit/clients/test_token_budget_scope.py` | CREATE | Resume/snapshot + registry lifecycle tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev `755c61347` on 2026-09-11 plus TASK-3132/3133 declared outputs.

### Verified Imports
```python
from parrot.clients.budget import QuestionBudget                         # TASK-3133
from parrot.models.token_budget import TokenBudgetPolicy, BudgetSnapshot, BudgetReport   # TASK-3132
from parrot.core.exceptions import (                                     # TASK-3132
    BudgetRegistryFull, BudgetResumeConflict, BudgetScopeConflict, BudgetSnapshotInvalid, BudgetStateMissing,
)
import asyncio, contextvars, copy, secrets, time, uuid, logging          # stdlib
from typing import Any, Optional
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/budget.py (TASK-3133)
class QuestionBudget:
    def __init__(self, policy: TokenBudgetPolicy, operation_id: str) -> None
    operation_id: str; policy: TokenBudgetPolicy; state: OperationState; revision: int   # properties
    async def report(self) -> BudgetReport
    async def close(self, *, terminal_reason: Optional[str] = None) -> None

# packages/ai-parrot/src/parrot/models/token_budget.py (TASK-3132)
class BudgetSnapshot(BaseModel):
    schema_version: Literal[1]; operation_id: str; policy: TokenBudgetPolicy
    settled_input_tokens: int; settled_output_tokens: int; revision: int; consumed_floor: int
    resume_nonce: str; attempt_count: int; round_count: int; owner_call_id: Optional[str]; suspended_metadata: dict
class BudgetReport(BaseModel):
    in_flight_tokens: int; uncertain_tokens: int; input_tokens: int; output_tokens: int; revision: int; state: OperationState
```

### Does NOT Exist
- ~~`parrot.clients.budget_scope`~~ — this task creates it.
- ~~`QuestionBudget.from_snapshot()`~~ — the ledger has no snapshot constructor; the
  registry rebuilds a ledger from a snapshot by constructing `QuestionBudget(policy,
  operation_id)` and calling a NEW ledger method you must add in this task:
  `QuestionBudget.restore_settled(*, input_tokens, output_tokens, revision, attempt_count, round_count) -> None`
  (append it to `budget.py`; only valid on a fresh, empty ledger — else `BudgetAccountingError`).
- ~~`HumanInteractionInterrupt.state["token_budget"]`~~ — nothing writes it yet; this task only defines the envelope shape. Providers merge it in TASK-3140 / TASK-3143.
- ~~Redis/distributed registry~~ — non-goal (spec §1).
- ~~`asyncio.get_event_loop()`~~ — use `asyncio.get_running_loop()` and compare `id(loop)`.

---

## Implementation Notes

### Pattern to Follow
```python
# ContextVar binding restored on EVERY exit path (spec §2.6 "Scope exit restores ContextVars in all paths")
async def __aenter__(self):
    self._token = _CURRENT_SCOPE.set(self)
    return self
async def __aexit__(self, exc_type, exc, tb):
    try:
        ...  # close / suspend / retain
    finally:
        _CURRENT_SCOPE.reset(self._token)
```

### Key Constraints
- Registry records: `_Record(ledger, status: Literal["active","suspended","closed"], nonce: Optional[str], high_water: int, updated_at: float, detached: bool)`.
  `high_water` = highest `consumed` seen; snapshots may never lower it.
- `create()` → new UUID4 `operation_id` **every time**, even with reused client/user/session.
  Before allocating, prune expired `suspended`/`closed` records older than
  `retention_seconds`; if `len(records) >= max_retained` after pruning and the
  overflow is entirely active work, raise `BudgetRegistryFull` (never evict active).
- `resume(state, snapshot=None)`: read `state[TOKEN_BUDGET_STATE_KEY]`; if missing →
  `BudgetStateMissing`. Live record present → check policy equality, `revision >=`
  envelope revision, nonce equality, then **atomically** consume nonce (set to `None`),
  mark `active`, return a scope with `is_root=True`, `owner_call_id` from envelope.
  Nonce already `None` → `BudgetResumeConflict`. No live record: if `snapshot` is `None`
  → `BudgetStateMissing`; else validate snapshot against envelope (same identity,
  policy, nonce; `consumed_floor >= envelope.consumed_floor`; not a known-closed id;
  not lower than any recorded high-water) → rebuild ledger via `restore_settled` →
  consume nonce → return scope. Identical re-import of an already-live record: no-op
  (idempotent) then normal resume path.
- `suspend(scope)` (new method): mint `secrets.token_urlsafe(16)` nonce, status
  `suspended`, return the envelope. A new suspension → new nonce.
- `export_settled(operation_id)`: record must be `suspended`, report must have
  `in_flight_tokens == 0 and uncertain_tokens == 0`, no `finalization_attempted`;
  build `BudgetSnapshot`, set `detached=True` (further `resume` on it raises
  `BudgetResumeConflict`), return snapshot.
- `release(operation_id)`: only `suspended`/`closed` records; active → `BudgetScopeConflict`.
- `BudgetScope.__aenter__`: if `self.loop_id != id(asyncio.get_running_loop())` →
  `BudgetScopeConflict` (covered child on another loop is rejected, spec §2.1).
  `__aexit__`: root scope with no exception → `ledger.close()`; with a
  `HumanInteractionInterrupt` propagating → leave as is (the provider called
  `suspend()` already); any other exception → close with `terminal_reason=type name`;
  child scope → never closes the ledger.
- Deep-copy `state["messages"]` in resume? **No** — the registry does not own messages;
  document that providers deep-copy (spec §2.6 "Resume deep-copies request state") and
  assert it in TASK-3140/3143.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/abstract.py` — `_A2UI_SURFACE_STATE_VAR` ContextVar set/reset idiom (grep `_A2UI_SURFACE_STATE_VAR`).
- `packages/ai-parrot/src/parrot/clients/base.py:903-935` — loop-id + weakref guard for loop identity.

---

## Implementation Blueprint

### Steps (in order)
1. Add `QuestionBudget.restore_settled(...)` to `budget.py` — *why*: the registry must rebuild a ledger from a trusted snapshot without a second constructor.
2. Create `budget_scope.py` with ContextVar, `BudgetScope`, `_Record`, `BudgetRegistry` — *why*: spec §3 Module 2 skeleton fixes the public method set.
3. Implement `suspend` / `resume` / `export_settled` / `release` with the checks listed above — *why*: AC "Resume identity/nonce/floors … duplicate resume refused … snapshot cannot lower a known floor".
4. Write the tests with explicit `asyncio.Event` barriers.

### `packages/ai-parrot/src/parrot/clients/budget.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3133: grep -c '    def _require(self, reservation_id: str) -> _Attempt:' packages/ai-parrot/src/parrot/clients/budget.py)
# BEFORE — insert above `    def _require(self, reservation_id: str) -> _Attempt:`
    def restore_settled(
        self, *, input_tokens: int, output_tokens: int, revision: int, attempt_count: int, round_count: int,
    ) -> None:
        """Seed a fresh ledger from a trusted snapshot (registry-only; spec §2.6)."""
        if self._attempts or self._consumed() or self._revision:
            raise BudgetAccountingError("restore_settled requires an empty ledger", operation_id=self._operation_id)
        self._settled_input, self._settled_output = input_tokens, output_tokens
        self._revision = revision
        self._restored_attempts, self._restored_rounds = attempt_count, round_count
```
**Why**: keeps snapshot authority inside the registry while the ledger stays the only counter owner. Initialise `self._restored_attempts = self._restored_rounds = 0` in `__init__` so `_report_locked` can add them.

### `packages/ai-parrot/src/parrot/clients/budget_scope.py` (CREATE)
```python
"""Question budget scopes, process-local registry and suspension/snapshot transfer (FEAT-550, spec §2.6 / §3 M2)."""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from parrot.clients.budget import QuestionBudget  # TASK-3133
from parrot.core.exceptions import (  # TASK-3132
    BudgetRegistryFull, BudgetResumeConflict, BudgetScopeConflict, BudgetSnapshotInvalid, BudgetStateMissing,
)
from parrot.models.token_budget import BudgetSnapshot, TokenBudgetPolicy  # TASK-3132

TOKEN_BUDGET_STATE_KEY = "token_budget"
_CURRENT_SCOPE: ContextVar[Optional["BudgetScope"]] = ContextVar("parrot_budget_scope", default=None)
logger = logging.getLogger(__name__)


def current_budget_scope() -> Optional["BudgetScope"]:
    """Return the live inherited scope, or None when no question budget is active."""
    return _CURRENT_SCOPE.get()


class BudgetScope:
    """Live ledger reference, owner identity and immutable inherited policy."""

    def __init__(self, ledger: QuestionBudget, *, registry: "BudgetRegistry", is_root: bool, owner_call_id: Optional[str] = None) -> None:
        self.ledger = ledger
        self.registry = registry
        self.is_root = is_root
        self.owner_call_id = owner_call_id or (str(uuid.uuid4()) if is_root else None)
        self.loop_id = id(asyncio.get_running_loop())
        self._token: Optional[Token] = None

    @property
    def operation_id(self) -> str:
        return self.ledger.operation_id

    @property
    def policy(self) -> TokenBudgetPolicy:
        return self.ledger.policy

    def child(self) -> "BudgetScope":
        """Derive a descendant scope: spending rights only, never finalization ownership (spec §2.1)."""
        return BudgetScope(self.ledger, registry=self.registry, is_root=False, owner_call_id=None)

    async def __aenter__(self) -> "BudgetScope":
        """Bind in-process context and validate the owning event loop."""
        if self.loop_id != id(asyncio.get_running_loop()):
            raise BudgetScopeConflict("budget scope entered on a different event loop", operation_id=self.operation_id)
        self._token = _CURRENT_SCOPE.set(self)
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Restore context; close, suspend or retain uncertain state as appropriate."""
        try:
            # FILL IN: root + no exception -> await self.ledger.close(); root + HumanInteractionInterrupt -> leave (provider suspended);
            #          root + other exception -> close(terminal_reason=exc_type.__name__); child -> nothing.
            #          Bounded by spec §2.6 "Scope exit restores ContextVars in all paths" and §2.3 owner rules.
            raise NotImplementedError
        finally:
            if self._token is not None:
                _CURRENT_SCOPE.reset(self._token)


@dataclass
class _Record:
    ledger: QuestionBudget
    status: Literal["active", "suspended", "closed"] = "active"
    nonce: Optional[str] = None
    high_water: int = 0
    updated_at: float = field(default_factory=time.monotonic)
    detached: bool = False
```
**Why this shape**: `child()` is how TASK-3135 grants descendants spending rights without finalization ownership (spec §2.1 "Descendants inherit only spending rights"). The loop check is in `__aenter__` so a covered child on another loop is *rejected*, never treated as a fresh question.

### `packages/ai-parrot/src/parrot/clients/budget_scope.py` (CREATE, continued — registry)
```python
class BudgetRegistry:
    """Bounded process-local registry; each operation stays on its owning loop."""

    def __init__(self, *, max_retained: int = 1024, retention_seconds: int = 3600) -> None:
        """Configure finite suspended/closed retention without evicting active work."""
        self._max_retained = max_retained
        self._retention_seconds = retention_seconds
        self._records: dict[str, _Record] = {}
        self._closed_ids: set[str] = set()
        self._lock = asyncio.Lock()

    async def create(self, policy: TokenBudgetPolicy) -> BudgetScope:
        """Allocate one root identity or fail if retained capacity is exhausted."""
        async with self._lock:
            self._prune_locked()
            if len(self._records) >= self._max_retained:
                raise BudgetRegistryFull(f"registry holds {len(self._records)} records")
            operation_id = str(uuid.uuid4())
            ledger = QuestionBudget(policy, operation_id)
            self._records[operation_id] = _Record(ledger)
            logger.debug("budget registry: created %s", operation_id)
            return BudgetScope(ledger, registry=self, is_root=True)

    async def suspend(self, scope: BudgetScope) -> dict[str, Any]:
        """Mint a fresh resume nonce and return the namespaced state envelope (spec §2.6)."""
        async with self._lock:
            rec = self._records[scope.operation_id]
            rec.nonce, rec.status, rec.updated_at = secrets.token_urlsafe(16), "suspended", time.monotonic()
            report = await scope.ledger.report()
            rec.high_water = max(rec.high_water, report.total_tokens)
            return {
                "operation_id": scope.operation_id, "policy": scope.policy.model_dump(), "revision": report.revision,
                "consumed_floor": report.total_tokens, "resume_nonce": rec.nonce, "owner_call_id": scope.owner_call_id,
            }

    async def resume(self, state: dict[str, Any], *, snapshot: BudgetSnapshot | None = None) -> BudgetScope:
        """Consume the suspension nonce after policy, identity and floor checks."""
        envelope = state.get(TOKEN_BUDGET_STATE_KEY)
        if not isinstance(envelope, dict):
            raise BudgetStateMissing("resume state carries no token_budget envelope")
        async with self._lock:
            rec = self._records.get(envelope.get("operation_id", ""))
            if rec is None:
                # FILL IN: no live record -> snapshot None => BudgetStateMissing; else _import_snapshot_locked(envelope, snapshot)
                #          (identity/policy/nonce/floor/high-water/closed checks -> BudgetSnapshotInvalid). Bounded by spec §2.6 import rules.
                raise NotImplementedError
            # FILL IN: detached -> BudgetResumeConflict; policy mismatch/revision below floor -> BudgetSnapshotInvalid;
            #          nonce None or != envelope -> BudgetResumeConflict; then consume nonce, status active, return root scope
            #          with owner_call_id=envelope["owner_call_id"]. Bounded by spec §2.6 "atomically consumes the suspension's nonce".
            raise NotImplementedError

    async def export_settled(self, operation_id: str) -> BudgetSnapshot:
        """Transfer a quiescent suspension; refuse in-flight/uncertain ownership."""
        async with self._lock:
            rec = self._records.get(operation_id)
            # FILL IN: require suspended, report.in_flight_tokens==0 and uncertain_tokens==0 and not finalization_attempted;
            #          build BudgetSnapshot; rec.detached=True. Else BudgetSnapshotInvalid. Bounded by spec §2.6 export rules.
            raise NotImplementedError

    async def release(self, operation_id: str) -> None:
        """Release retained terminal state; never discard an active reservation."""
        async with self._lock:
            # FILL IN: active -> BudgetScopeConflict; suspended/closed -> pop and remember id in _closed_ids. Bounded by spec §2.6.
            raise NotImplementedError

    async def mark_closed(self, operation_id: str) -> None:
        """Record terminal state so a snapshot can never reopen it (called by BudgetScope.__aexit__)."""
        async with self._lock:
            rec = self._records.get(operation_id)
            if rec is not None:
                rec.status, rec.updated_at = "closed", time.monotonic()
            self._closed_ids.add(operation_id)

    def _prune_locked(self) -> None:
        """Drop suspended/closed records past retention; never touch active ones."""
        cutoff = time.monotonic() - self._retention_seconds
        for op_id in [k for k, r in self._records.items() if r.status != "active" and r.updated_at < cutoff]:
            self._records.pop(op_id)
            self._closed_ids.add(op_id)


_DEFAULT_REGISTRY: Optional[BudgetRegistry] = None


def get_default_registry() -> BudgetRegistry:
    """Process-wide default registry used when a client/bot is not handed one explicitly."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = BudgetRegistry()
    return _DEFAULT_REGISTRY


__all__ = ["BudgetScope", "BudgetRegistry", "current_budget_scope", "get_default_registry", "TOKEN_BUDGET_STATE_KEY"]
```
**Why this shape**: method names and signatures are the spec §3 Module 2 skeleton; `suspend`/`mark_closed` are the two non-skeleton helpers the providers and scope exit need, kept minimal. Expired suspended state is pruned into `_closed_ids` so a later resume fails `BudgetStateMissing`/`BudgetSnapshotInvalid` rather than starting at zero (spec §2.6).

### `packages/ai-parrot/tests/unit/clients/test_token_budget_scope.py` (CREATE)
```python
"""FEAT-550 M2 — resume/snapshot and registry lifecycle (spec §4 rows 'Resume and snapshots', 'Registry lifecycle')."""
from __future__ import annotations

import asyncio

import pytest

from parrot.clients.budget_scope import TOKEN_BUDGET_STATE_KEY, BudgetRegistry, BudgetScope, current_budget_scope
from parrot.core.exceptions import BudgetRegistryFull, BudgetResumeConflict, BudgetScopeConflict, BudgetSnapshotInvalid, BudgetStateMissing
from parrot.models.token_budget import TokenBudgetPolicy

POLICY = TokenBudgetPolicy(token_budget=10_000)


class TestResumeAndSnapshots:
    async def test_suspend_then_resume_reuses_same_identity(self):
        reg = BudgetRegistry()
        scope = await reg.create(POLICY)
        env = await reg.suspend(scope)
        resumed = await reg.resume({TOKEN_BUDGET_STATE_KEY: env})
        assert resumed.operation_id == scope.operation_id and resumed.is_root

    async def test_duplicate_nonce_rejected(self):
        # FILL IN: second resume with same envelope -> BudgetResumeConflict. Bounded by spec §2.6.
        raise NotImplementedError

    async def test_missing_live_state_typed(self):
        with pytest.raises(BudgetStateMissing):
            await BudgetRegistry().resume({"messages": []})

    async def test_snapshot_cannot_lower_floor_and_transfer_detaches(self):
        # FILL IN: suspend -> export_settled -> resume on original registry raises BudgetResumeConflict (detached);
        #          import into a NEW registry with tampered lower consumed_floor -> BudgetSnapshotInvalid;
        #          untampered import succeeds once and is idempotent. Bounded by spec §2.6 import rules.
        raise NotImplementedError


class TestRegistryLifecycle:
    async def test_active_never_evicted_and_full_registry_refuses(self):
        reg = BudgetRegistry(max_retained=1, retention_seconds=0)
        await reg.create(POLICY)
        with pytest.raises(BudgetRegistryFull):
            await reg.create(POLICY)

    async def test_release_only_terminal(self):
        # FILL IN: release active -> BudgetScopeConflict; after suspend -> ok. Bounded by spec §2.6.
        raise NotImplementedError

    async def test_contextvar_restored_on_every_exit(self):
        reg = BudgetRegistry()
        scope = await reg.create(POLICY)
        assert current_budget_scope() is None
        with pytest.raises(RuntimeError):
            async with scope:
                assert current_budget_scope() is scope
                raise RuntimeError("boom")
        assert current_budget_scope() is None

    async def test_cross_loop_scope_rejected(self):
        # FILL IN: create scope on loop A (asyncio.run in a thread), enter it on the test loop -> BudgetScopeConflict. Bounded by spec §2.1.
        raise NotImplementedError
```
**Why**: exact spec §4 rows; `retention_seconds=0` makes pruning deterministic without sleeps.

### FILL IN checklist
- [ ] `budget_scope.py::BudgetScope.__aexit__` — close/suspend/retain decision; bounded by spec §2.6 + §2.3 owner rules
- [ ] `budget_scope.py::BudgetRegistry.resume` — live path + snapshot import path; bounded by spec §2.6 import rules
- [ ] `budget_scope.py::BudgetRegistry.export_settled` / `release` — quiescence + terminal-only; bounded by spec §2.6
- [ ] `budget.py::QuestionBudget._report_locked` — add `_restored_attempts/_restored_rounds` to counts (follow-up to TASK-3133)
- [ ] all `test_token_budget_scope.py` FILL IN bodies

---

## Acceptance Criteria

- [ ] `from parrot.clients.budget_scope import BudgetScope, BudgetRegistry, current_budget_scope, get_default_registry, TOKEN_BUDGET_STATE_KEY` works
- [ ] Suspend → resume reuses identity; second resume with the same nonce raises `BudgetResumeConflict`
- [ ] Resume without envelope or without live state (and no snapshot) raises `BudgetStateMissing`
- [ ] Exported snapshot detaches the original; tampered lower floor raises `BudgetSnapshotInvalid`; identical import idempotent
- [ ] Full registry raises `BudgetRegistryFull`; active records are never pruned; `release` on active raises `BudgetScopeConflict`
- [ ] ContextVar restored on normal and exceptional exit; cross-loop entry raises `BudgetScopeConflict`
- [ ] `pytest packages/ai-parrot/tests/unit/clients/test_token_budget_scope.py packages/ai-parrot/tests/unit/clients/test_token_budget.py -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/budget_scope.py` clean

---

## Test Specification

Scaffold above. Add `test_new_question_gets_new_uuid_even_with_same_policy` (two `create()` calls → different ids) and `test_expired_suspended_state_fails_state_missing` (`retention_seconds=0`, suspend, create another to trigger prune, resume → `BudgetStateMissing`).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2.1 (child/loop rules), §2.6, §3 Module 2
2. **Check dependencies** — TASK-3133 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `QuestionBudget.report()`/`close()` exist as declared
4. **Update status** in `sdd/tasks/index/token-budget-bedrock.json` → `"in-progress"`
5. **Implement** from the Blueprint; never change a skeleton signature
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3134-budget-scope-registry.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
