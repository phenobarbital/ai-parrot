# HOTFIX-5e3bcfe4ea4b-1: Route engine-emitted failures to the local waiter

**Feature**: BRIEF-5e3bcfe4ea4b — roost-runtime-budget-enforcement
**Spec**: `sdd/briefs/roost-runtime-budget-enforcement.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Ledger `issue:5e3bcfe4ea4b` limb (4). When a conversation's budget trips on the side that
*initiated* it, `ProtocolEngine._close_with_failure` emits a typed failure addressed to
`state.initiator` — this agent. `_on_message` pushes every emitted message out over a
carrier, so that failure never reaches the `asyncio.Future` the caller's
`request()`/`query()` is awaiting. The `CLOSED` branch then resolves the waiter with the
*inbound* message instead, which either completes it with a bogus result or leaves it
hanging. See the brief's "Root cause (a)" for both reproductions.

`sweep()` (`endpoint.py:118-124`) already routes correctly; this task lifts that rule into
a helper and applies it at the two sites that lack it.

---

## Scope

- Add `RoostEndpoint._route_emitted`, holding the address check `sweep()` already performs.
- Use it for the dispatcher's emitted messages in `_on_message`.
- Use it for the `charge()` exhausted-transition emits in `_on_message`.
- Rewrite `sweep()`'s inner loop to call it, so the rule exists once.
- Add two end-to-end regression tests: the `query` false-success variant and the `request`
  hang-until-timeout variant.

**NOT in scope**: the token-budget feed (HOTFIX-5e3bcfe4ea4b-2); any change to
`protocols.py`, `gating.py` or `messages.py`; the hop-budget-on-the-wire and expiry-sweep
limbs of the ledger issue, which are already fixed on `dev` by `8ffec9c10`; the neighbouring
ledger issues listed in the brief.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/endpoint.py` | MODIFY | Add `_route_emitted`; use it at the three emit sites |
| `packages/ai-parrot/tests/roost/test_endpoint.py` | MODIFY | Add the two end-to-end regression tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase. Use them verbatim.

### Verified Imports

The test module already imports everything the new tests need — add no new imports:

```python
# packages/ai-parrot/tests/roost/test_endpoint.py:7-15 (verified)
from parrot.roost.carriers.inprocess import InProcessCarrier
from parrot.roost.directory import InterAgentGrant, RoostAgentConfig
from parrot.roost.endpoint import RoostEndpoint, RoostFailure
from parrot.roost.gating import GatingDispatcher, HandlerRegistry
from parrot.roost.grant import GrantPolicy
from parrot.roost.messages import AgentAddress, FailureInfo
from parrot.roost.performatives import CarrierKind, FailureCode, InteractionProtocol, Performative
from parrot.roost.protocols import ProtocolEngine
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/roost/endpoint.py
class RoostEndpoint:
    async def sweep(self) -> int:  # line 109
    async def _on_message(self, msg: RoostMessage) -> None:  # line 127
    async def _resolve_pending(self, msg: RoostMessage) -> None:  # line 205
    async def _send_reply(self, msg: RoostMessage) -> RoostMessage:  # line 219
    agent_name: str  # constructor parameter, line ~46

# packages/ai-parrot/src/parrot/roost/messages.py
class RoostMessage(BaseModel):
    hops: int = 0     # line 77
    tokens: int = 0   # line 78
    def is_addressed_to(self, name: str) -> bool:  # used at endpoint.py:121

# packages/ai-parrot/src/parrot/roost/protocols.py
class ProtocolEngine:
    def __init__(self, ..., default_hop_limit: int = ...)  # accepts default_hop_limit
    def accept(self, msg: RoostMessage, *, hops: int = 0) -> Transition:  # line 267
    def charge(self, conversation_id: str, tokens: int) -> Optional[Transition]:  # line 287
    def state(self, conversation_id: str)  # used in tests/roost/test_endpoint.py:248

# packages/ai-parrot/tests/roost/test_endpoint.py:20
def make_endpoint(name, carrier, *, config=None, tool_result=None,
                  working_memory=None, wake=None, registry=None) -> RoostEndpoint:
```

### Does NOT Exist

- ~~`RoostEndpoint._route_emitted`~~ — this task creates it.
- ~~`make_endpoint(..., engine=...)`~~ — the helper builds its own `ProtocolEngine()` and
  takes **no** `engine` parameter. The tests below need endpoints with different
  `default_hop_limit`s, so add an optional `engine` keyword to `make_endpoint` (defaulting
  to `ProtocolEngine()`) rather than inventing a call signature.
- ~~`RoostMessage.reply_inform`~~ — not a method; build replies with
  `msg.reply(Performative.INFORM, content=...)`.
- ~~`ProtocolEngine.expire_one`~~ / ~~`RoostEndpoint._route`~~ — do not exist.

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
    "sym:packages/ai-parrot/src/parrot/roost/endpoint.py#RoostEndpoint.sweep",
    "sym:packages/ai-parrot/src/parrot/roost/endpoint.py#RoostEndpoint._resolve_pending",
    "sym:packages/ai-parrot/src/parrot/roost/endpoint.py#RoostEndpoint._send_reply",
    "sym:packages/ai-parrot/src/parrot/roost/protocols.py#ProtocolEngine.charge",
    "sym:packages/ai-parrot/src/parrot/roost/protocols.py#ProtocolEngine.accept"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- Async throughout; `self.logger` for any logging; no new imports in `endpoint.py`.
- Do **not** change `protocols.py`. The engine already produces the right message; only its
  delivery is wrong.
- Preserve the serving-side behaviour: when the closed conversation's initiator is a
  *remote* agent, the failure must still go out over the carrier. The existing
  `test_hop_limit_is_enforced_on_the_wire` covers that and must keep passing.
- Order matters in `_on_message`: emitted messages are routed *before* the decision branch
  runs, so by the time the `CLOSED` branch calls `_resolve_pending(msg)` the future is
  already done and `_resolve_pending`'s `future.done()` guard (`endpoint.py:208-209`) makes
  it a no-op. Leave that call in place — removing it changes the `STORE`/`REPLAN` paths.

### References in Codebase

- `packages/ai-parrot/src/parrot/roost/endpoint.py:118-124` — the correct routing rule to lift.
- `packages/ai-parrot/tests/roost/test_endpoint.py:217-233` — the serving-side hop-limit test
  to model the new tests on.

---

## Implementation Blueprint

> This patch was applied and verified against `dev` while the brief was written: both probe
> variants reported `OK: raised FailureCode.HOP_LIMIT`, and
> `pytest packages/ai-parrot/tests/roost/ -q` gave `112 passed`. Apply it as written.

### Steps (in order)

1. Add `_route_emitted` and rewrite `sweep()`'s inner loop to use it — *why*: the rule must
   exist in exactly one place.
2. Route the dispatcher's emits through it in `_on_message` — *why*: this is the fix for the
   false-success and hang variants.
3. Route the `charge()` exhausted emits through it — *why*: a `TOKEN_BUDGET` failure on the
   initiator's own side has the identical defect; HOTFIX-5e3bcfe4ea4b-2's end-to-end test
   depends on this.
4. Add an optional `engine` keyword to the `make_endpoint` test helper — *why*: the
   regression tests need two endpoints with different hop limits.
5. Add the two regression tests.

### `packages/ai-parrot/src/parrot/roost/endpoint.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'transitions = self.engine.expire()' endpoint.py)
# REPLACE the body of sweep()'s loop (endpoint.py:118-124) and append the helper:
        transitions = self.engine.expire()
        for transition in transitions:
            for emitted in transition.emit:
                await self._route_emitted(emitted)
        return len(transitions)

    async def _route_emitted(self, emitted: RoostMessage) -> None:
        """Deliver an engine-emitted message: locally when it names this agent, else over a carrier.

        A budget that trips on the side which opened the conversation produces a failure
        addressed to this agent; that message is what the pending ``request``/``query``
        future is waiting for, so it must resolve the waiter instead of going out over a
        carrier and arriving back on an already-terminal conversation.
        """
        if emitted.is_addressed_to(self.agent_name):
            await self._resolve_pending(emitted)
        else:
            await self._send_reply(emitted)
```

```python
# occurrences: 1 (verified: grep -c 'dispatch = self.dispatcher.dispatch(msg)' endpoint.py)
# REPLACE at endpoint.py:131-133
        dispatch = self.dispatcher.dispatch(msg)
        for emitted in dispatch.emit:
            await self._route_emitted(emitted)
```

```python
# occurrences: 1 (verified: grep -c 'exhausted = self.engine.charge' endpoint.py)
# REPLACE the emit loop at endpoint.py:159-161
                    if exhausted is not None:
                        for emitted in exhausted.emit:
                            await self._route_emitted(emitted)
```

**Why this shape**: `_route_emitted` is the single delivery rule for everything the engine
emits. `sweep()` keeps working unchanged in behaviour; `_on_message` gains the local-delivery
case it never had. Nothing about the serving side changes, because a remote initiator fails
`is_addressed_to(self.agent_name)`.

### `packages/ai-parrot/tests/roost/test_endpoint.py` (MODIFY)

```python
# Add the `engine` keyword to make_endpoint (test_endpoint.py:20-49), then append:

@pytest.mark.asyncio
async def test_hop_limit_on_the_caller_side_fails_the_query_instead_of_returning_a_result() -> None:
    """A reply that trips the caller's own hop limit raises HOP_LIMIT, never a result."""
    # FILL IN: build `srv` (capabilities=["s.x"], wake returning
    #   msg.reply(Performative.INFORM, content={"answer": 42}),
    #   engine=ProtocolEngine(default_hop_limit=99)) and `caller`
    #   (config=GRANTED, engine=ProtocolEngine(default_hop_limit=4)) on one InProcessCarrier.
    # Then assert caller.query(..., receiver=AgentAddress(name="srv"), timeout=2, hops=5)
    #   raises RoostFailure with FailureCode.HOP_LIMIT — bounded by brief "Root cause (a)".
    raise NotImplementedError


@pytest.mark.asyncio
async def test_hop_limit_on_the_caller_side_fails_the_request_instead_of_timing_out() -> None:
    """The REQUEST path surfaces HOP_LIMIT, not the TIMEOUT it used to degrade into."""
    # FILL IN: same shape with a deterministic server
    #   (backing="deterministic", tool_result={"salary": 100}, default_hop_limit=99)
    #   and caller.request("hr.x", {}, receiver=..., timeout=2, hops=5).
    # Assert FailureCode.HOP_LIMIT — the pre-fix behaviour was FailureCode.TIMEOUT, so
    #   asserting "a RoostFailure was raised" is NOT sufficient; assert the code.
    raise NotImplementedError
```

**Why**: these two are the exact reproductions from the brief; without asserting the
specific `FailureCode`, the `request` test would have passed before the fix as well.

### FILL IN checklist

- [ ] `make_endpoint` — optional `engine: ProtocolEngine | None = None` keyword.
- [ ] `test_..._query_instead_of_returning_a_result` — body per the comment.
- [ ] `test_..._request_instead_of_timing_out` — body per the comment; assert the code.

---

## Acceptance Criteria

- [ ] `RoostEndpoint._route_emitted` exists and is the only place the address check appears.
- [ ] `_on_message` routes both the dispatcher emits and the `charge()` exhausted emits through it.
- [ ] A `query` whose reply trips the caller's hop limit raises `RoostFailure(HOP_LIMIT)`, not a result.
- [ ] A `request` whose reply trips the caller's hop limit raises `RoostFailure(HOP_LIMIT)`, not `TIMEOUT`.
- [ ] `test_hop_limit_is_enforced_on_the_wire` and `test_expired_conversation_emits_failure_timeout_to_the_requester` still pass.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/roost/endpoint.py packages/ai-parrot/tests/roost/test_endpoint.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/roost/test_endpoint.py -q`
- `pytest packages/ai-parrot/tests/roost/test_protocols.py -q`

---

## Test Specification

Both tests are end-to-end over `InProcessCarrier` with two real endpoints — the gap the
ledger issue calls out is precisely that only engine-level behaviour was tested. Give the
server a high `default_hop_limit` and the caller a low one so the server answers normally
and the budget trips on the caller's side; that asymmetry is what the existing
serving-side test does not cover. Always `await caller.stop()` / `await srv.stop()` in a
`finally`.

---

## Agent Instructions

1. **Work in this brief's worktree** —
   `.claude/worktrees/fix-5e3bcfe4ea4b-roost-runtime-budget-enforcement` — never on `dev`.
2. **Read the brief** at `sdd/briefs/roost-runtime-budget-enforcement.brief.md` first.
3. **Verify the Codebase Contract** before writing code; if an anchor moved, fix the
   contract in this file first.
4. Run tests with `PYTHONPATH=packages/ai-parrot/src` — a bare `pytest` inside a worktree
   imports the main checkout's `parrot`.
5. **Implement** from the Implementation Blueprint; do not change `protocols.py`.
6. **Commit only** the two files this task lists — never `git add .` / `-A`.
7. Fill in the Completion Note below, then commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
