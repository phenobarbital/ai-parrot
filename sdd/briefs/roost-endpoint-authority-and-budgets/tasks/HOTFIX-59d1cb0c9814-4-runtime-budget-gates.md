# HOTFIX-59d1cb0c9814-4: Wire the remaining runtime budget gates (hops, token charge, closed-dispatch resolution)

**Feature**: BRIEF-59d1cb0c9814 — Roost endpoint: caller authority, grant enforcement and runtime budget gates
**Spec**: `sdd/briefs/roost-endpoint-authority-and-budgets.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: HOTFIX-59d1cb0c9814-3
**Assigned-to**: unassigned

---

## Context

Closes `issue:5e3bcfe4ea4b` (folded into this brief by owner decision).

`ProtocolEngine` implements all three conversation budgets — hop limit
(`check_hops`, `protocols.py:280`), token budget (`charge`, `protocols.py:287`)
and deadline (`expire`, `protocols.py:297`) — and they are unit-tested. The
endpoint wiring is **partly** done.

**Already fixed by `8ffec9c10` — do not redo:**
- `expire()` runs: `_sweep_loop` → `sweep()` (`endpoint.py:101-125`). The
  issue's claim that "`ProtocolEngine.expire()` has no caller anywhere in
  `roost/`" is stale.
- `charge()`'s return value is acted on (`endpoint.py:158-161`).
- `RoostMessage.tokens` exists (`messages.py:78`) — the issue's claim that the
  field is missing is stale.
- Hop seeding on openers: `open()` takes `hops=opener.hops`
  (`protocols.py:248`) and `check_hops` runs at `gating.py:108`.

**Still broken — this task's scope:**

1. `RoostMessage.tokens` is never assigned anywhere in `roost/` (a grep for
   `tokens=` in the package returns nothing), so
   `self.engine.charge(msg.conversation_id, response.tokens)`
   (`endpoint.py:158`) always charges `0` and the token budget can never be
   exhausted.
2. `_on_message` calls `self.dispatcher.dispatch(msg)` (`endpoint.py:131`)
   without `hops`, so `GatingDispatcher.dispatch`'s `hops` defaults to `0`
   (`gating.py:92`) and `ProtocolEngine.accept(msg, hops=0)` (`gating.py:112`)
   never grows the hop count for continuation messages. Only openers are
   covered.
3. A `DispatchDecision.CLOSED` resolves the waiter with the **original** inbound
   message (`endpoint.py:140-142`). When that original is an `INFORM`,
   `_resolve_pending` takes the `INFORM` branch (`endpoint.py:210-213`) and
   calls `future.set_result(msg.content)` — so `request()` returns a *successful*
   result for a conversation the engine just closed with `HOP_LIMIT` or
   `TOKEN_BUDGET`.

---

## Scope

- Thread the message's own hop count into dispatch:
  `self.dispatcher.dispatch(msg, hops=msg.hops)` (or the equivalent that makes
  `accept()` grow `state.budget.hops`). Verify against `protocols.py:272-275`
  which already does `state.budget.hops += hops` — make sure the opener path
  (which seeds `hops=opener.hops` at `open()`) is not double-counted.
- Make the token charge carry a real count: document the `wake` callback
  contract (`WakeCallback`, `endpoint.py:27`) as "the returned `RoostMessage`
  must carry its LLM token usage in `tokens`", and keep `charge()` reading
  `response.tokens` (Assumption A1). If an existing usage object is reachable
  at that point, prefer it and note the deviation.
- Resolve a `CLOSED` dispatch from the transition's failure, not the original
  message: when `dispatch.transition` closed the conversation with a failure,
  the pending waiter must receive `RoostFailure(failure)`, never
  `set_result(msg.content)`.
- Add end-to-end tests for all three gates at the endpoint level (the engine
  level is already covered by `test_protocols.py`).

**NOT in scope**:
- Re-implementing `expire()`/`sweep()` (already wired).
- Changing `ProtocolEngine`'s budget semantics in `protocols.py` — unless a
  test proves the engine itself is wrong, in which case stop and record it.
- The audit-direction inversion at `endpoint.py:130` vs `endpoint.py:225`
  (tracked by `issue:d09c6c185547`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/endpoint.py` | MODIFY | hops into dispatch; CLOSED resolution; `WakeCallback` contract docs |
| `packages/ai-parrot/tests/roost/test_endpoint.py` | MODIFY | end-to-end hop-limit, token-budget and deadline tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .gating import Dispatch, DispatchDecision, GatingDispatcher, Handler  # verified: endpoint.py:15
from .protocols import ConversationBudget, ProtocolEngine, TerminalState   # verified: endpoint.py:19
from .performatives import FailureCode                                     # verified: endpoint.py:18
from .messages import FailureInfo                                          # verified: endpoint.py:17
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/roost/gating.py:92
    def dispatch(self, msg: RoostMessage, *, hops: int = 0) -> Dispatch: ...

# packages/ai-parrot/src/parrot/roost/gating.py:54
class Dispatch(BaseModel):
    decision: DispatchDecision
    transition: Optional[Transition] = None
    emit: list[RoostMessage] = Field(default_factory=list)
    handler: Any = None

# packages/ai-parrot/src/parrot/roost/protocols.py:267
    def accept(self, msg: RoostMessage, *, hops: int = 0) -> Transition:
        state.budget.hops += hops                                     # line 272
        if state.budget.hops > state.budget.hop_limit:                # line 273
            return self._close_with_failure(state, FailureCode.HOP_LIMIT, "conversation hop limit exceeded", msg)

# packages/ai-parrot/src/parrot/roost/protocols.py:235
    def open(self, opener: RoostMessage, *, budget: Optional[ConversationBudget] = None) -> ConversationState:
            budget = ConversationBudget(hop_limit=self._default_hop_limit,   # line 247
                                        hops=opener.hops,                    # line 248
                                        token_budget=getattr(opener.envelope, "token_budget", None),
                                        deadline=now + timedelta(milliseconds=budget_ms) if budget_ms is not None else None)

# packages/ai-parrot/src/parrot/roost/protocols.py:287
    def charge(self, conversation_id: str, tokens: int) -> Optional[Transition]: ...

# packages/ai-parrot/src/parrot/roost/protocols.py:43 (ConversationBudget)
    hop_limit: int = 8        # line 46
    token_budget: Optional[int] = None  # line 48
    tokens_used: int = 0      # line 49
    deadline: Optional[datetime] = None # line 50

# packages/ai-parrot/src/parrot/roost/endpoint.py:205
    async def _resolve_pending(self, msg: RoostMessage) -> None:
        if msg.performative is Performative.INFORM:      # line 210
            future.set_result(msg.content)               # line 211
        elif msg.performative in (Performative.REFUSE, Performative.FAILURE):  # line 214
            failure = msg.failure or FailureInfo(code=FailureCode.POLICY, detail="request refused")
            future.set_exception(RoostFailure(failure))  # line 216

# packages/ai-parrot/src/parrot/roost/endpoint.py:27
WakeCallback = Callable[[RoostMessage, Dispatch], Awaitable[Optional[RoostMessage]]]

# packages/ai-parrot/src/parrot/roost/messages.py:77-78
    hops: int = 0
    tokens: int = 0
```

### Does NOT Exist
- ~~`Transition.failure`~~ — not verified; read `Transition`'s real fields in `protocols.py` before using any attribute of it
- ~~`ConversationState.budget.exhausted`~~ — not a field
- ~~`RoostMessage.usage`~~ — the field is `tokens`
- ~~`ProtocolEngine.charge_message(...)`~~ — the method is `charge(conversation_id, tokens)`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/endpoint.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_endpoint.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/roost/endpoint.py#RoostEndpoint._on_message",
    "sym:packages/ai-parrot/src/parrot/roost/endpoint.py#RoostEndpoint._resolve_pending",
    "sym:packages/ai-parrot/src/parrot/roost/endpoint.py#RoostEndpoint.sweep",
    "sym:packages/ai-parrot/src/parrot/roost/gating.py#GatingDispatcher.dispatch",
    "sym:packages/ai-parrot/src/parrot/roost/protocols.py#ProtocolEngine.accept",
    "sym:packages/ai-parrot/src/parrot/roost/protocols.py#ProtocolEngine.charge",
    "sym:packages/ai-parrot/src/parrot/roost/protocols.py#ProtocolEngine.open",
    "sym:packages/ai-parrot/src/parrot/roost/messages.py#RoostMessage"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Double-counting is the trap.** `open()` already seeds `budget.hops` from
  `opener.hops`, and `accept()` adds its `hops` argument on top. Passing
  `hops=msg.hops` for a message whose conversation was just opened from that
  same message would count it twice. Note that `gating.py:106-110` takes the
  *opener* branch (which never calls `accept`) only when
  `engine.state(conversation_id) is None`, so the two paths are mutually
  exclusive per message — confirm this with a test rather than by reading.
- A failure transition emitted by `accept()` is already sent to the peer by
  `_on_message`'s `for emitted in dispatch.emit` loop (`endpoint.py:132-133`).
  This task changes only how the **local** waiter is resolved.
- Read `Transition`'s actual definition in `protocols.py` before touching the
  CLOSED branch — its fields are not in this contract on purpose.
- Keep `sweep()` and `_sweep_loop` as they are.

### References in Codebase
- `packages/ai-parrot/tests/roost/test_protocols.py` — existing engine-level budget tests to mirror end-to-end
- `packages/ai-parrot/src/parrot/roost/endpoint.py:110-125` — `sweep()`, which already resolves failures correctly (`_resolve_pending` vs `_send_reply` by address) — the CLOSED branch should behave consistently with it

---

## Implementation Blueprint

### Steps (in order)
1. Pass the inbound hop count into `dispatch` — *why*: continuation messages must grow the budget.
2. Resolve a CLOSED dispatch from the closing failure — *why*: a hop/token kill must not look like success.
3. Document the `wake` token-reporting contract — *why*: the charge is otherwise always 0.
4. Add the three end-to-end tests — *why*: the issue says engine-level is tested, end-to-end is not.

### `packages/ai-parrot/src/parrot/roost/endpoint.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'dispatch = self.dispatcher.dispatch(msg)' packages/ai-parrot/src/parrot/roost/endpoint.py)
# REPLACE `        dispatch = self.dispatcher.dispatch(msg)` (verified: endpoint.py:131) with:
        dispatch = self.dispatcher.dispatch(msg, hops=msg.hops)
```
```python
# occurrences: 1 (verified: grep -c 'if dispatch.decision is DispatchDecision.CLOSED:' packages/ai-parrot/src/parrot/roost/endpoint.py)
# REPLACE the CLOSED branch (verified: endpoint.py:140-142) with a version that
# prefers the transition's own failure message over the original inbound msg:
        if dispatch.decision is DispatchDecision.CLOSED:
            # FILL IN: find the failure message among dispatch.emit / dispatch.transition
            # that is addressed to this agent and resolve the waiter from IT;
            # fall back to `await self._resolve_pending(msg)` only when there is none.
            raise NotImplementedError
```
```python
# occurrences: 1 (verified: grep -c '^WakeCallback = ' packages/ai-parrot/src/parrot/roost/endpoint.py)
# AFTER — insert below `WakeCallback = Callable[[RoostMessage, Dispatch], Awaitable[Optional[RoostMessage]]]` (verified: endpoint.py:27)
"""Contract: a wake callback that returns a message MUST set ``RoostMessage.tokens``
to the LLM token usage of that reply. The endpoint charges it against the
conversation's token budget (``ProtocolEngine.charge``); a reply left at the
default ``tokens=0`` makes the budget unenforceable (``issue:5e3bcfe4ea4b``)."""
```
**Why this shape**: the emitted failure is already on the wire for the peer; the
local future is the only thing still being resolved from the wrong object.
Resolving from `dispatch.emit` keeps one source of truth for what the engine
decided, instead of re-deriving a `FailureInfo` at the endpoint.

### FILL IN checklist
- [ ] `_on_message` CLOSED branch — select the failure message and resolve from it; bounded by `issue:5e3bcfe4ea4b` sub-claim (4)

---

## Acceptance Criteria

- [ ] An end-to-end conversation exceeding `hop_limit` fails the caller's `request()` with `RoostFailure(code=HOP_LIMIT)` — not a successful result
- [ ] A continuation message grows `state.budget.hops` (the opener is not double-counted — assert the exact count)
- [ ] A wake reply carrying `tokens` over the envelope's `token_budget` closes the conversation with `TOKEN_BUDGET` and fails the waiter
- [ ] A conversation past its deadline is closed by `sweep()` and fails the waiter with `TIMEOUT` (regression guard for the already-fixed sweep)
- [ ] `WakeCallback`'s token contract is documented at `endpoint.py`
- [ ] `ruff check packages/ai-parrot/src/parrot/roost/endpoint.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/roost/test_endpoint.py -q`
- `pytest packages/ai-parrot/tests/roost/test_protocols.py -q`
- `pytest packages/ai-parrot/tests/roost/test_gating.py -q`
- `pytest packages/ai-parrot/tests/roost/test_salary_flow_end_to_end.py -q`
- `pytest packages/ai-parrot/tests/roost/test_gate_ls1_wakes.py -q`
- `pytest packages/ai-parrot/tests/roost/test_gate_ls2_inform_no_reply.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/roost/test_endpoint.py (extend)

@pytest.mark.asyncio
async def test_hop_limit_fails_the_caller_end_to_end() -> None:
    """A conversation beyond its hop limit raises HOP_LIMIT, never returns a result."""
    # FILL IN: build the endpoint pair, send with hops above ConversationBudget.hop_limit (default 8),
    # assert pytest.raises(RoostFailure) and exc.value.failure.code is FailureCode.HOP_LIMIT


@pytest.mark.asyncio
async def test_opener_hops_are_not_double_counted() -> None:
    """Opening from a message and dispatching it must not add its hops twice."""
    # FILL IN: assert engine.state(cid).budget.hops == <exact expected>


@pytest.mark.asyncio
async def test_token_budget_exhaustion_closes_the_conversation() -> None:
    """A wake reply reporting tokens over the envelope budget closes with TOKEN_BUDGET."""
    # FILL IN: wake AsyncMock returning a RoostMessage with tokens > envelope.token_budget


@pytest.mark.asyncio
async def test_deadline_sweep_fails_the_waiter() -> None:
    """A conversation past its deadline is closed by sweep() with TIMEOUT."""
    # FILL IN: short budget_ms, await endpoint.sweep(), assert the waiter raised TIMEOUT
```

---

## Agent Instructions

1. **Work in the brief worktree** `.claude/worktrees/fix-59d1cb0c9814-roost-endpoint-authority-and-budgets`.
2. **Check the dependency**: HOTFIX-59d1cb0c9814-3 must be `done` in the per-brief index.
3. **Read the brief's "Already fixed on dev — do not re-fix" section first** — this task's ledger issue is partly stale.
4. **Verify the Codebase Contract** — tasks 1–3 have edited this file; re-anchor on literals.
5. **Update status** to `"in-progress"`; commit only the index file.
6. **Implement**, complete the `# FILL IN:`, run the Validation Commands, `ruff check --fix`.
7. **Commit only this task's files**: `fix(roost): HOTFIX-59d1cb0c9814-4 — wire hop, token and closed-dispatch budget gates`.
8. **Mark `done`**, fill in the Completion Note, commit the SDD state.
9. **After this task**, both ledger issues can be closed:
   `wikitoolkit ledger close issue:59d1cb0c9814 --resolved-by commit:<sha> --reason "…"` and the same for `issue:5e3bcfe4ea4b`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
