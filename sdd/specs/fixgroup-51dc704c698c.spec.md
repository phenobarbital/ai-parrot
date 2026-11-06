---
type: feature
base_branch: dev
feature_id: FEAT-828
projects: [ai-parrot]
tags: [roost, bugfix, ledger]
discovered_from: issue:a409d14b8130
---
# FEAT-828 — Roost: serve agent turns off the carrier consumer so a woken agent can make onward calls

**Status**: approved · **Parent**: FEAT-747 (Roost) / FEAT-827 (merged, PR #2008) · **Issue**: `issue:a409d14b8130`

## Problem
Every Roost carrier delivers inbound messages by awaiting the endpoint's `inbound` callback inline, one message
at a time per address: `InProcessCarrier._consume` (`carriers/inprocess.py:63-71`), the `SharedMemoryCarrier`
wrapper that rides on it (`carriers/shm.py:70-79`), the `EventBusCarrier` bus handler (`carriers/bus.py:76-89`)
and `MatrixCarrier._on_event` (`integrations/matrix/roost/carrier.py:121-150`). `RoostEndpoint._on_message`
in turn awaits the agent turn inline: `response = await self.wake(msg, dispatch)` for `WAKE_LLM`
(`endpoint.py:222`) and `await self._run_tool(msg)` for `RUN_TOOL` (`endpoint.py:211`).

While endpoint B is inside a wake it therefore cannot process any other inbound message — including the
reply to a query that B's own woken agent sends. Verified on `origin/dev` @ `1db7daea9f` with three endpoints
on one `InProcessCarrier`: A queries B; B's wake does `await B.query(C, timeout=2, hops=msg.hops)`; C's wake
answers immediately. B's onward query raises `RoostFailure(TIMEOUT)` after exactly 2.00 s and A receives the
failure text. Consequences:

1. any nested `ask_agent` from a Roost-woken agent ends in `status == "timeout"`;
2. a `failure(HOP_LIMIT)` emitted by the peer is never seen either, so the A→B→A chain that FEAT-825 /
   FEAT-827 budget is ended by timeouts, not by the hop limit;
3. each stuck level holds its consumer for the full timeout, stalling every other message addressed to that
   agent (a serving tool call, an inform, a Contract Net accept).

## Design
The fix is in the endpoint, not the carriers: the carriers' serial, inline delivery is what keeps protocol
processing ordered per address and must stay. What must not run on the consumer is the *agent turn* — the
LLM wake or the serving tool call — because a turn may itself open a Roost conversation and wait for its reply.

- **M1 turns run in tracked background tasks.** `RoostEndpoint` gains `_turns: set[asyncio.Task[None]]`
  and a private `_spawn_turn(coro, *, msg)` that creates the task with `asyncio.get_running_loop().create_task`,
  tracks it, and on completion drops it from the set and logs (`self.logger.exception`) any exception other
  than `CancelledError` — the carrier's consumer used to log turn failures; that duty moves to the task.
  `_on_message` keeps everything that is protocol work inline and ordered: audit, `dispatcher.dispatch`,
  routing of `dispatch.emit` (the hop-limit / policy failures), `IGNORE` / `NOT_UNDERSTOOD` / `CLOSED` /
  `STORE` / `BID_FROM_CONTRACT` / `REPLAN` handling, the `wakes` metric increment. Only the two execution
  branches change:
  - `WAKE_LLM` → `self._spawn_turn(self._serve_wake(msg, dispatch), msg=msg)`, where `_serve_wake` is the
    body that exists today (call `self.wake`, send the reply, `engine.charge`, the unfed-budget warning,
    route the exhausted transition, `_forget_if_closed`, then `_resolve_pending(msg)`), moved verbatim.
  - `RUN_TOOL` → `self._spawn_turn(self._run_tool(msg), msg=msg)`.
  Because `create_task` copies the current context, each turn sees its own `ContextVar` values (the
  `ctx.current_hops` seeding FEAT-827 does in the wake stays per turn).
- **M2 lifecycle.** `stop()` cancels every task still in `_turns`, awaits them with
  `asyncio.gather(..., return_exceptions=True)` *before* unsubscribing from the carriers (a cancelled turn that
  was inside `query()` still sends its `CANCELLED` close over a live carrier), then fails the pending waiters
  as today. `metrics` gains `turns_started` (incremented in `_spawn_turn`) and a read-only
  `turns_in_flight` property (`len(self._turns)`) so tests and the L-S1 metric can observe the change.
- **M3 behavioural note (documented, not guarded).** An agent may now serve two turns concurrently — two
  wakes, or a wake while a tool call runs. That is the same concurrency `AbstractBot.ask` already sees from
  the HTTP handlers and from the Matrix tunnel path (`handle_task` runs per inbound event). No per-endpoint
  concurrency cap is introduced; one is a follow-up if a deployment needs it.
- **M4 docs.** `wiki/mcp/roost/carriers.md` gets a short "Delivery model" paragraph: carriers deliver
  serially per address; the endpoint runs agent turns off the consumer; what that means for nested calls.

No carrier file changes. No change to `WakeCallback`, `Dispatch`, the engine or the dispatcher.

## Acceptance Criteria
- [ ] AC-1 Three real endpoints on one `InProcessCarrier`, A → B → C, where B's wake awaits `B.query(C, timeout=2.0, hops=msg.hops)` and C's wake answers at once: `A.query(B, timeout=2.0)` returns the composed answer in well under the timeout (bound: 1.0 s), and no `RoostFailure` is raised anywhere in the chain.
- [ ] AC-2 Two real endpoints whose wakes each forward the question back to the other (`hops=msg.hops`, `timeout=2.0`): the originator's `query()` ends in `RoostFailure` with `code == HOP_LIMIT` (not `TIMEOUT`) within 1.0 s, and the total wake count across both endpoints is at most `hop_limit + 1`.
- [ ] AC-3 A wake that raises is logged by the endpoint and does not kill the consumer: a second message to the same endpoint is still served; `turns_in_flight` returns to 0.
- [ ] AC-4 `stop()` with a wake in flight cancels that turn (the wake observes `CancelledError`), returns without waiting for the wake's own timeout, and leaves `turns_in_flight == 0`; the in-flight `query()` the wake was awaiting is closed as `CANCELLED`.
- [ ] AC-5 A `RUN_TOOL` turn whose tool awaits `endpoint.query()` on a third agent completes with that agent's answer (the serving endpoint keeps draining while the tool runs) and the requester receives `INFORM` with the tool result.
- [ ] AC-6 Gate L-S1 (`test_gate_ls1_wakes.py`) and the rest of `packages/ai-parrot/tests/roost/` stay green; `packages/ai-parrot-integrations/tests/test_matrix_roost_ask_agent.py` and `test_matrix_roost_wake.py` stay green; `ruff check` clean on the changed files.

## Out of scope
- A per-endpoint concurrency cap or a per-conversation ordering guarantee between turns (M3).
- Changing carrier delivery to spawn per message (it would reorder protocol replies against openers).
- `issue:c0063cc362a5` (terminal audit during `CancelledError` in `query()`), a separate minor issue on the
  same file.
- The Matrix crew wiring (FEAT-827) — unchanged; its AC-4 chain halves can be rejoined in a later feature.

## Worktree Strategy
- **Isolation**: one feature worktree, `feat-FEAT-828-fixgroup-51dc704c698c`, off `origin/dev`.
- **Module dependency graph**: M2 depends on M1 (same file, same task); M4 documents M1–M3. One task.
- **Shared files**: `packages/ai-parrot/src/parrot/roost/endpoint.py` only.
- **Exclusive resources**: none.

## Governing Decisions

<!-- decision-audit: input_digest=sha256:4f99f73743a1077363003f18a04f9296b48b971d1d955754c1fa4518a9bc9257 evaluation_digest=sha256:17da9067b7a9189d38b3a8d888fb76bbd3ba0e553a8e7241165b636d17ab8e76 rules_version=1 status=pass -->

## Consequences

<!-- decision-audit: input_digest=sha256:4f99f73743a1077363003f18a04f9296b48b971d1d955754c1fa4518a9bc9257 evaluation_digest=sha256:17da9067b7a9189d38b3a8d888fb76bbd3ba0e553a8e7241165b636d17ab8e76 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/06287cc5-6f01-421d-93f4-d0cfabd1030e/scratchpad/dev-clone/sdd/specs/fixgroup-51dc704c698c.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: bugfix, ledger, roost
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "bugfix",
      "ledger",
      "roost"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/06287cc5-6f01-421d-93f4-d0cfabd1030e/scratchpad/dev-clone/sdd/specs/fixgroup-51dc704c698c.spec.md"
    }
  ],
  "evaluation_digest": "sha256:17da9067b7a9189d38b3a8d888fb76bbd3ba0e553a8e7241165b636d17ab8e76",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:4f99f73743a1077363003f18a04f9296b48b971d1d955754c1fa4518a9bc9257",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "9887c26aa37a5daa626531f2ef465c9f7ef63adf1a9d890eb248ea33c0053dbd"
  },
  "status": "pass"
}
```
