---
kind: brief
slug: roost-runtime-budget-enforcement
key: 5e3bcfe4ea4b
base_branch: dev
source:
  type: ledger
  ref: issue:5e3bcfe4ea4b
  url: null
jira_issue_key: null
ledger_issue: issue:5e3bcfe4ea4b
created: "2026-10-29"
---

# Brief: Roost — deliver engine-emitted failures to the local waiter, and make the token budget observable

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/<slug>/tasks/. -->

## Problem

Ledger `issue:5e3bcfe4ea4b` (critical, from the FEAT-747 code review) reports that the
Roost endpoint "never enforces hop limit, token budget or deadline at runtime (AC-5)",
listing four defects. Two of the four were since fixed on `dev` by commit `8ffec9c10`
("review fixes — hop budget on the wire, expiry sweep"):

| # | Original claim | State on `dev` today |
|---|---|---|
| 1 | `dispatch(msg)` passes no hops, so `accept` never exceeds `hop_limit` | **Fixed.** The hop budget rides the wire: `RoostMessage.hops` (`messages.py:77`) seeds `budget.hops` in `ProtocolEngine.open` (`protocols.py:248`), `GatingDispatcher.dispatch` calls `check_hops` (`gating.py:108`), and `request`/`query` send `hops=hops + 1` (`endpoint.py:357`, `endpoint.py:410`). Covered by `test_hop_limit_is_enforced_on_the_wire`. |
| 2 | `charge(...)` discarded; `RoostMessage` has no `tokens` field | **Partly fixed.** `tokens` exists (`messages.py:78`) and the returned transition is acted on (`endpoint.py:158`). But nothing in the repo ever *sets* `tokens`, so every charge is 0 — see "Root cause" (b). |
| 3 | `ProtocolEngine.expire()` has no caller | **Fixed.** `RoostEndpoint.sweep` (`endpoint.py:118`) and `_sweep_loop` (`endpoint.py:100`) call it. Covered by `test_expired_conversation_emits_failure_timeout_to_the_requester`. |
| 4 | A hop-failure `Transition(kind='closed')` reaches `_resolve_pending(msg)` with the ORIGINAL msg | **Live.** Reproduced both ways — see "Root cause" (a). |

This brief fixes the live residue: (a) and (b). It does not re-litigate (1) and (3).

## Root cause

### (a) Engine-emitted failures are always sent outbound, never to the local waiter

`RoostEndpoint._on_message` sends every message the dispatcher emits over a carrier:

```python
# packages/ai-parrot/src/parrot/roost/endpoint.py:131-133
dispatch = self.dispatcher.dispatch(msg)
for emitted in dispatch.emit:
    await self._send_reply(emitted)
```

`ProtocolEngine._close_with_failure` addresses its typed failure to
`receivers=[state.initiator]` (`protocols.py`, in `_close_with_failure`). When *this*
agent is the initiator — i.e. the budget tripped on the requester's own side — that
failure is the one thing the pending `request()`/`query()` future is waiting for, yet it
is pushed out over a carrier back at ourselves instead of resolving the future. The
`CLOSED` branch then calls `_resolve_pending` with the **inbound** message rather than
the failure:

```python
# packages/ai-parrot/src/parrot/roost/endpoint.py:140-142
if dispatch.decision is DispatchDecision.CLOSED:
    await self._resolve_pending(msg)
    return
```

`_resolve_pending` (`endpoint.py:205-219`) only completes the future for `INFORM`
(result) or `REFUSE`/`FAILURE` (exception). So the original message produces one of two
wrong outcomes, both reproduced on `dev` with a probe script:

- **False success** — `QUERY` has no agreement phase, so the `INFORM` reply is itself the
  message that trips `accept`'s hop check (`protocols.py:272-273`). The conversation is
  closed `TerminalState.FAILED` with `HOP_LIMIT`, and `_resolve_pending(INFORM)` then
  calls `future.set_result(...)`. Probe output on `dev`:
  `LIVE BUG (false success): query returned {'answer': 42} on a conversation the caller closed with HOP_LIMIT / caller terminal=TerminalState.FAILED hops=5/4`
- **Hang until timeout** — on the `REQUEST` path the `AGREE` trips the limit first; it is
  neither `INFORM` nor a failure, so the future is never completed. The emitted failure is
  delivered to ourselves over the carrier, arrives on an already-terminal conversation and
  is logged as `Roost protocol did not understand message …`. The caller observes
  `FailureCode.TIMEOUT` instead of `HOP_LIMIT` — and hangs forever when `timeout is None`.

`sweep()` already has the correct routing and is the model for the fix:

```python
# packages/ai-parrot/src/parrot/roost/endpoint.py:118-124
transitions = self.engine.expire()
for transition in transitions:
    for emitted in transition.emit:
        if emitted.is_addressed_to(self.agent_name):
            await self._resolve_pending(emitted)
        else:
            await self._send_reply(emitted)
```

The deadline path works end to end *only* because `sweep()` routes locally; the dispatch
and `charge()` paths do not. This is one missing routing rule, not three separate bugs.

### (b) `RoostMessage.tokens` is declared and charged but never produced

`tokens: int = 0` (`messages.py:78`) is read once, at `endpoint.py:158`:

```python
exhausted = self.engine.charge(msg.conversation_id, response.tokens)
```

`response` comes from the `wake` callback — an integration seam typed at
`endpoint.py:27` (`WakeCallback`) with **no implementation anywhere in the repo**
(`grep -rn "WakeCallback\|wake=" --include=*.py packages/` returns only the declaration
and the constructor parameter; `grep -rn "tokens=" packages/ai-parrot/src/parrot/roost/`
returns nothing). So `response.tokens` is always the default `0`, `charge` always adds 0,
and a conversation that declares a `token_budget` is served unbudgeted and silently.
Probe output on `dev`: `result={'answer': 'hi'} tokens_used=0 token_budget=None`.

`wiki_blast_radius ProtocolEngine.charge` confirms the only callers are
`RoostEndpoint._on_message` and the engine-level unit test
`test_token_budget_closes_with_failure` (`test_protocols.py:101-110`) — there is no
end-to-end coverage, which is why the gap survived.

## Research findings

- **Symbols**: `RoostEndpoint._on_message` (`endpoint.py:127-170`), `RoostEndpoint.sweep`
  (`endpoint.py:109-124`), `RoostEndpoint._resolve_pending` (`endpoint.py:205-219`),
  `ProtocolEngine.charge` (`protocols.py:287-295`), `ProtocolEngine.accept`
  (`protocols.py:267-278`), `ProtocolEngine._close_with_failure`.
- **Blast radius** (`wiki_blast_radius ProtocolEngine.charge`, depth 2): only
  `RoostEndpoint._on_message` and `tests/roost/test_protocols.py`. The change is contained
  to `roost/endpoint.py`; `protocols.py` needs no change.
- **Candidate fix verified before hand-off.** The `sweep()` routing rule was factored into
  a `_route_emitted` helper and applied at the three emit sites
  (`_on_message` dispatch emits, the `charge()` exhausted emits, and `sweep` itself). Both
  probes then reported `OK: raised FailureCode.HOP_LIMIT`, and
  `pytest packages/ai-parrot/tests/roost/ -q` gave **112 passed**. The patch was reverted;
  it is reproduced in HOTFIX-5e3bcfe4ea4b-1's Implementation Blueprint.
- **Related ledger issues on the same files** (`ledger context`): `issue:0f5ee739eca8`
  (major, open — `ask_agent` does not carry hop budget / conversation_id),
  `issue:59d1cb0c9814` (critical, **claimed** — PermissionContext / grant on explicit-receiver
  paths), `issue:d09c6c185547` (major, open — cfp scorer / grant attenuation).
  `issue:59d1cb0c9814` touches `endpoint.py` too; it is claimed by another lane, so expect a
  merge conflict window on that file and rebase rather than reorder commits.
- No worktree or remote branch is in flight for this issue (`git worktree list`,
  `git branch -r`), and FEAT-747's roost work is already merged to `dev`.

## Decisions

Answers from the Q&A round:

1. **Scope — fix the live residue only.** The brief covers (a) the pending-future
   resolution bug and (b) the token-budget feed, plus the missing end-to-end regression
   tests. Limbs (1) and (3) of the ledger body are recorded as already fixed by `8ffec9c10`
   and get no new tests. When closing the issue, say so in the close note.
2. **Token feed — document the contract and warn.** `tokens` stays the `wake` callback's
   responsibility: the endpoint cannot know a provider's real usage. Document it on
   `WakeCallback`, and log a warning **once per conversation** when that conversation
   declares a `token_budget` but the wake response reports 0 tokens, so a misintegrated
   host is visible instead of silently unbudgeted. Do **not** estimate tokens in the
   endpoint, and do **not** fail closed.

## Fix plan

- **HOTFIX-5e3bcfe4ea4b-1** — Route engine-emitted messages addressed to this agent to the
  local waiter instead of a carrier. Add `_route_emitted` and use it at all three emit
  sites. Add end-to-end regression tests for the false-success (`query`) and
  hang-until-timeout (`request`) variants.
- **HOTFIX-5e3bcfe4ea4b-2** — Document the `WakeCallback` token-reporting contract and warn
  once per conversation when a budgeted conversation charges 0 tokens. Add an end-to-end
  test that a wake response carrying `tokens` trips `TOKEN_BUDGET`, and one that the
  warning fires when it does not.

Sequential: both tasks modify `packages/ai-parrot/src/parrot/roost/endpoint.py`, and task 2's
end-to-end `TOKEN_BUDGET` test only passes once task 1 routes the failure locally.

## Validation commands

- `pytest packages/ai-parrot/tests/roost/test_endpoint.py -q`
- `pytest packages/ai-parrot/tests/roost/test_protocols.py -q`
