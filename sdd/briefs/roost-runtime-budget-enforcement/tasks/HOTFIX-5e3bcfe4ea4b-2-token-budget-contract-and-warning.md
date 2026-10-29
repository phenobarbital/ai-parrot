# HOTFIX-5e3bcfe4ea4b-2: Document the wake token contract and warn on an unfed token budget

**Feature**: BRIEF-5e3bcfe4ea4b — roost-runtime-budget-enforcement
**Spec**: `sdd/briefs/roost-runtime-budget-enforcement.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: HOTFIX-5e3bcfe4ea4b-1
**Assigned-to**: unassigned

---

## Context

Ledger `issue:5e3bcfe4ea4b` limb (2). `RoostMessage.tokens` (`messages.py:78`) is declared
and charged (`endpoint.py:158`), but nothing in the repository ever sets it: `wake` is an
integration seam (`WakeCallback`, `endpoint.py:27`) with no in-repo implementation. Every
`charge()` therefore adds 0 and a conversation that declares a `token_budget` is served
unbudgeted, silently. Only the engine-level `test_token_budget_closes_with_failure`
(`test_protocols.py:101-110`) covers `charge`, which is why this survived.

Per the brief's Decision 2, the endpoint must **not** estimate tokens and must **not** fail
closed — a provider's real usage is only knowable to the host's wake callback. The fix is to
make the contract explicit and make a breach visible.

---

## Scope

- Document on `WakeCallback` that the returned `RoostMessage` must carry `tokens` for
  token-budget enforcement to work, and that leaving it 0 means the conversation is unbudgeted.
- Warn **once per conversation** via `self.logger.warning` when a conversation declares a
  `token_budget` and the wake response reports `tokens == 0`.
- Add two end-to-end tests: a wake response carrying `tokens` trips `TOKEN_BUDGET`; a wake
  response leaving `tokens` at 0 on a budgeted conversation emits the warning and still serves.

**NOT in scope**: changing `ProtocolEngine.charge` or any other part of `protocols.py`;
estimating or counting tokens inside the endpoint; failing the conversation closed when
`tokens` is 0; the routing fix in HOTFIX-5e3bcfe4ea4b-1; the hop-budget and expiry-sweep
limbs, already fixed on `dev` by `8ffec9c10`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/endpoint.py` | MODIFY | `WakeCallback` contract docs; once-per-conversation warning |
| `packages/ai-parrot/tests/roost/test_endpoint.py` | MODIFY | Two end-to-end token-budget tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

No new imports in either file. `Performative`, `FailureCode`, `ProtocolEngine`,
`AgentAddress`, `RoostFailure` are already imported in the test module
(`test_endpoint.py:7-15`).

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/roost/endpoint.py:27
WakeCallback = Callable[[RoostMessage, Dispatch], Awaitable[Optional[RoostMessage]]]

# packages/ai-parrot/src/parrot/roost/endpoint.py:158 — the single charge site
exhausted = self.engine.charge(msg.conversation_id, response.tokens)

# packages/ai-parrot/src/parrot/roost/protocols.py:287-295
def charge(self, conversation_id: str, tokens: int) -> Optional[Transition]:
    state = self._states.get(conversation_id)
    if state is None or state.terminal is not None:
        return None
    state.budget.tokens_used += tokens
    if state.budget.token_budget is not None and state.budget.tokens_used > state.budget.token_budget:
        return self._close_with_failure(state, FailureCode.TOKEN_BUDGET, "conversation token budget exceeded")
    return None

# packages/ai-parrot/src/parrot/roost/protocols.py — reading the budget
def state(self, conversation_id: str) -> Optional[ConversationState]
# ConversationState.budget -> ConversationBudget(hop_limit, hops, token_budget, tokens_used, deadline)

# packages/ai-parrot/src/parrot/roost/squawk_bridge.py — the envelope carrying the budget
def new_envelope(*, correlation_id: str, caller: str, budget_ms: Optional[int] = None)
```

### Does NOT Exist

- ~~`RoostEndpoint._token_counter`~~ / ~~`parrot.roost.tokens`~~ — no token counting in roost.
- ~~`ConversationBudget.token_budget_exhausted`~~ — not an attribute; compare
  `tokens_used` against `token_budget` yourself.
- ~~`new_envelope(..., token_budget=...)`~~ — **verify before use.** `ProtocolEngine.open`
  reads `getattr(opener.envelope, "token_budget", None)` (`protocols.py:247`), and
  `LocalEnvelope` accepts `token_budget` in `test_protocols.py:12-14`, but
  `squawk_bridge.new_envelope` may not forward it. If it does not, build the envelope the
  way `test_protocols.py` does, or open the conversation with an explicit
  `ConversationBudget` — do not add a parameter to `new_envelope` for this task.

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
    "sym:packages/ai-parrot/src/parrot/roost/protocols.py#ProtocolEngine.charge"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- `self.logger.warning`, never `print`; Google-style docstrings; 120-column lines.
- **Once per conversation**, not once per turn: a long conversation must not flood the log.
  Track the conversation ids already warned about in an instance-level `set[str]`
  initialized in `__init__` alongside `self._pending` / `self._metrics`
  (`endpoint.py:62-68`), and discard the id when the conversation ends so the set cannot
  grow without bound on a long-lived endpoint.
- Only warn when the conversation actually declares a budget: read
  `self.engine.state(msg.conversation_id)` and check `budget.token_budget is not None`.
  A conversation with no budget is legitimately unbudgeted and must stay silent.
- The warning must not change control flow — the response is still sent and the turn still
  completes.

### References in Codebase

- `packages/ai-parrot/src/parrot/roost/endpoint.py:153-163` — the `WAKE_LLM` branch to amend.
- `packages/ai-parrot/tests/roost/test_protocols.py:101-110` — the engine-level budget test
  these end-to-end tests complement (leave it unchanged).

---

## Implementation Blueprint

### Steps (in order)

1. Extend the `WakeCallback` docstring/comment with the token-reporting contract — *why*:
   the seam is the only place a host integrator will look.
2. Initialize the warned-conversations set in `__init__` — *why*: once-per-conversation.
3. Warn in the `WAKE_LLM` branch when a budgeted conversation reports 0 tokens — *why*:
   makes a misintegration visible instead of silent.
4. Add the two end-to-end tests.

### `packages/ai-parrot/src/parrot/roost/endpoint.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'WakeCallback = Callable' endpoint.py)
# AFTER the WakeCallback alias (endpoint.py:27), document the contract:
#: Wakes the host agent for one turn.
#:
#: The returned :class:`RoostMessage` MUST carry ``tokens`` — the tokens the host actually
#: spent on this turn. Roost cannot know a provider's usage, so a response left at the
#: default ``tokens=0`` leaves the conversation effectively unbudgeted: ``token_budget``
#: is never reached and ``FailureCode.TOKEN_BUDGET`` never fires. The endpoint logs a
#: warning once per conversation when a budgeted conversation reports 0 tokens.
```

```python
# occurrences: 1 (verified: grep -c 'exhausted = self.engine.charge' endpoint.py)
# REPLACE the charge block in the WAKE_LLM branch (endpoint.py:158-161):
                    exhausted = self.engine.charge(msg.conversation_id, response.tokens)
                    if response.tokens == 0:
                        self._warn_unfed_token_budget(msg.conversation_id)
                    if exhausted is not None:
                        for emitted in exhausted.emit:
                            await self._route_emitted(emitted)
```

```python
# ADD the helper next to _resolve_pending (endpoint.py:205):
    def _warn_unfed_token_budget(self, conversation_id: str) -> None:
        """Warn once per conversation that a declared token budget is receiving no usage.

        A wake callback that leaves ``RoostMessage.tokens`` at 0 makes the budget
        unenforceable; this surfaces the misintegration without changing the turn.
        """
        # FILL IN: return early unless self.engine.state(conversation_id) exists and its
        #   budget.token_budget is not None; return early if the id is already in the
        #   warned set; otherwise add it and self.logger.warning(...) naming the
        #   conversation and the WakeCallback contract.
        raise NotImplementedError
```

**Why this shape**: the charge call is untouched (an explicit 0 charge still keeps
`tokens_used` honest), the warning is advisory only, and `_route_emitted` from
HOTFIX-5e3bcfe4ea4b-1 is what makes an initiator-side `TOKEN_BUDGET` failure reach the
waiter at all.

### `packages/ai-parrot/tests/roost/test_endpoint.py` (MODIFY)

```python
@pytest.mark.asyncio
async def test_wake_reported_tokens_trip_the_conversation_token_budget() -> None:
    """A wake response carrying `tokens` beyond the budget closes with TOKEN_BUDGET."""
    # FILL IN: open the served conversation with a token_budget (see the "Does NOT Exist"
    #   note on new_envelope — verify how the budget reaches ProtocolEngine.open first).
    #   wake returns msg.reply(Performative.INFORM, content=..., tokens=<over budget>).
    #   Assert the server-side conversation terminal is FAILED and the emitted failure
    #   carries FailureCode.TOKEN_BUDGET — bounded by brief "Root cause (b)".
    raise NotImplementedError


@pytest.mark.asyncio
async def test_budgeted_conversation_warns_once_when_wake_reports_no_tokens(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A budgeted conversation whose wake reports 0 tokens warns once and still serves."""
    # FILL IN: same setup with a wake that leaves tokens at 0; drive two turns on the same
    #   conversation; assert the result is still returned and exactly ONE warning record
    #   mentions the conversation id. Also assert an UNBUDGETED conversation logs none.
    raise NotImplementedError
```

**Why**: the first test is the end-to-end coverage the ledger issue says is missing; the
second pins "once per conversation" and "silent when unbudgeted", the two ways a naive
warning goes wrong.

### FILL IN checklist

- [ ] `_warn_unfed_token_budget` — guard on budget presence, dedupe, warn.
- [ ] warned-conversation set initialized in `__init__` and discarded when a conversation ends.
- [ ] `test_wake_reported_tokens_trip_the_conversation_token_budget`.
- [ ] `test_budgeted_conversation_warns_once_when_wake_reports_no_tokens`.

---

## Acceptance Criteria

- [ ] `WakeCallback` documents that the wake response must carry `tokens`.
- [ ] A budgeted conversation whose wake reports 0 tokens logs exactly one warning, however many turns it runs.
- [ ] An unbudgeted conversation logs no such warning.
- [ ] A wake response carrying `tokens` over the budget closes the conversation with `FailureCode.TOKEN_BUDGET`.
- [ ] The turn still completes when the warning fires — the warning changes no control flow.
- [ ] `ProtocolEngine.charge` and the rest of `protocols.py` are unchanged.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/roost/endpoint.py packages/ai-parrot/tests/roost/test_endpoint.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/roost/test_endpoint.py -q`
- `pytest packages/ai-parrot/tests/roost/test_protocols.py -q`

---

## Test Specification

Use `caplog` at `WARNING` level for the dedupe test and drive two turns on one conversation
— a per-turn warning would produce two records and must fail the test. For the
`TOKEN_BUDGET` test, verify first how `token_budget` actually reaches
`ProtocolEngine.open` (`protocols.py:247` reads it off the envelope); if
`squawk_bridge.new_envelope` does not forward it, open the conversation with an explicit
`ConversationBudget` rather than widening `new_envelope`'s signature in this task.

---

## Agent Instructions

1. **Work in this brief's worktree** —
   `.claude/worktrees/fix-5e3bcfe4ea4b-roost-runtime-budget-enforcement` — never on `dev`.
2. **Check the dependency**: HOTFIX-5e3bcfe4ea4b-1 must be `done` in
   `sdd/briefs/roost-runtime-budget-enforcement.index.json`; the `TOKEN_BUDGET` end-to-end
   test relies on its `_route_emitted`.
3. **Verify the Codebase Contract** before writing code — especially the
   `new_envelope` / `token_budget` question flagged under "Does NOT Exist".
4. Run tests with `PYTHONPATH=packages/ai-parrot/src`.
5. **Implement** from the Implementation Blueprint; do not touch `protocols.py`.
6. **Commit only** the two files this task lists — never `git add .` / `-A`.
7. Fill in the Completion Note below, then commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
