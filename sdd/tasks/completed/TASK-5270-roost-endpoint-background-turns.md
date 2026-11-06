# TASK-5270: RoostEndpoint — run WAKE_LLM / RUN_TOOL turns in tracked background tasks

**Feature**: FEAT-828 fixgroup-51dc704c698c
**Spec**: `sdd/specs/fixgroup-51dc704c698c.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:a409d14b8130`

## Context
Every carrier awaits the endpoint's inbound callback inline, one message at a time per address, and
`RoostEndpoint._on_message` awaits the agent turn (`self.wake` / `_run_tool`) inline. An agent woken by a
query therefore cannot receive the reply to its own onward query: the onward call always ends in `TIMEOUT`
(repro in the issue). The fix keeps protocol processing on the consumer and moves only the agent turn into a
tracked background task (spec M1–M4).

## Scope
- M1: `_turns`, `_spawn_turn`, `_serve_wake` (the existing `WAKE_LLM` body moved verbatim); `_on_message`
  spawns the `WAKE_LLM` and `RUN_TOOL` turns instead of awaiting them.
- M2: `stop()` cancels and awaits outstanding turns before unsubscribing; `turns_started` metric and
  `turns_in_flight` property.
- M4: a "Delivery model" paragraph in `wiki/mcp/roost/carriers.md`.
- Tests for AC-1..AC-5 in one new module.

**NOT in scope**: any carrier file; `WakeCallback` / `Dispatch` / engine / dispatcher signatures; a
concurrency cap; `issue:c0063cc362a5`; the Matrix crew package.

## Files to Create / Modify
- `packages/ai-parrot/src/parrot/roost/endpoint.py` (modify — `__init__`, `stop`, `_on_message`, new `_spawn_turn`, `_serve_wake`, `turns_in_flight`, `metrics`)
- `packages/ai-parrot/tests/roost/test_endpoint_background_turns.py` (new)
- `wiki/mcp/roost/carriers.md` (modify — add a paragraph)

## Codebase Contract (Anti-Hallucination)
Verified against `origin/dev` @ `e1e225aa55`.

**Verified Imports**
- `from parrot.roost import AgentAddress, CarrierKind, GatingDispatcher, GrantPolicy, HandlerRegistry, InProcessCarrier, ProtocolEngine, RoostAgentConfig, RoostEndpoint` (as in `tests/roost/test_gate_ls1_wakes.py`)
- `from parrot.roost.endpoint import RoostFailure, WakeCallback`
- `from parrot.roost.directory import InterAgentGrant, RoostAgentConfig`
- `from parrot.roost.performatives import FailureCode, InteractionProtocol, Performative`
- `from parrot.roost.messages import RoostMessage`

**Existing Signatures**
- `RoostEndpoint._on_message(self, msg: RoostMessage) -> None` (endpoint.py:192–253): `WAKE_LLM` branch at :219–233 (`self._metrics["wakes"] += 1`, `response = await self.wake(msg, dispatch)`, `_send_reply`, `engine.charge(msg.conversation_id, response.tokens)`, `_warn_unfed_token_budget`, exhausted `_route_emitted`, `_forget_if_closed`, `_resolve_pending(msg)`); `RUN_TOOL` branch at :210–212 (`await self._run_tool(msg)`).
- `RoostEndpoint.stop(self) -> None` (endpoint.py:140–153): cancels the sweeper, unsubscribes, fails `_pending` with `RoostFailure(CANCELLED)`.
- `RoostEndpoint.__init__` sets `self._metrics = {"messages_in", "messages_out", "wakes", "not_understood", "stored"}` (endpoint.py:104); `metrics` property returns `dict(self._metrics)` (:790–793).
- `RoostEndpoint.query(self, question, *, receiver, timeout=None, expected_schema=None, hops=0, trace_id=None, conversation_id=None)` (:560–655) — on `CancelledError` calls `_finish_query_failure(..., code=CANCELLED)` and re-raises.
- `RoostEndpoint.request(self, cap_id, args, *, timeout=None, receiver=None, hops=0)` (:482–558); the served side runs `tool_manager.execute_tool(tool_name, content, permission_context=authority)` (:313) — the tool must be advertised in `config.capabilities` and the request must carry authority (`permission_context=object()` on the endpoint, as `test_matrix_roost_ask_agent._real_endpoint` does).
- `ProtocolEngine(default_hop_limit: int = 8)` (protocols.py:224); `GatingDispatcher.dispatch(msg)` refuses an opener past the limit via `engine.check_hops` (gating.py:108) by emitting `failure(HOP_LIMIT)` to the sender.
- `InProcessCarrier.pending(name) -> int` (carriers/inprocess.py:89); `InProcessCarrier.close()`.
- `RoostMessage.reply(performative, *, content=None, body=None, failure=None, tokens=0)`; `RoostMessage.hops: int`.
- `RoostFailure.failure: FailureInfo` with `.code: FailureCode` (endpoint.py:63–68).

**Does NOT Exist**
- Any `_turns`, `_spawn_turn`, `_serve_wake`, `turns_in_flight` or `turns_started` on `RoostEndpoint`.
- A test that calls `RoostEndpoint._on_message` directly (none under `packages/*/tests`).
- A "Delivery model" section in `wiki/mcp/roost/carriers.md`.

## Implementation Notes
- `_spawn_turn(coro, *, msg)`: `task = asyncio.get_running_loop().create_task(coro)`; add to `_turns`;
  `self._metrics["turns_started"] += 1`; `add_done_callback` that discards the task and, when
  `not task.cancelled() and task.exception() is not None`, logs
  `self.logger.error("Roost turn for %s on conversation %s failed", self.agent_name, msg.conversation_id, exc_info=exc)`.
- Keep `_on_message` ordering: audit → dispatch → route `dispatch.emit` → decision branches. The `wakes`
  metric still increments inline before spawning (gate L-S1 counts it right after `_drain`).
- `stop()`: snapshot `list(self._turns)`, cancel each, `await asyncio.gather(*turns, return_exceptions=True)`,
  then the existing sweeper / unsubscribe / pending logic. Idempotent on an endpoint with no turns.
- Do not add a lock or a semaphore; do not touch the carriers.
- Tests build real endpoints on one `InProcessCarrier` exactly like `test_gate_ls1_wakes._endpoint`, plus
  `RoostAgentConfig(grant=InterAgentGrant(scopes=["*"]))` on callers and `permission_context=object()` where a
  `request` is served. Always `stop()` endpoints and `close()` the carrier in `finally`.

## Acceptance Criteria
Spec AC-1..AC-6.

## Validation Commands

- `pytest packages/ai-parrot/tests/roost/test_endpoint_background_turns.py -q`
- `pytest packages/ai-parrot/tests/roost/test_endpoint.py packages/ai-parrot/tests/roost/test_gate_ls1_wakes.py packages/ai-parrot/tests/roost/test_query_trace.py packages/ai-parrot/tests/roost/test_query_conversation_id.py packages/ai-parrot/tests/roost/test_agent_tool_roost.py -q`
- `pytest packages/ai-parrot-integrations/tests/test_matrix_roost_ask_agent.py packages/ai-parrot-integrations/tests/test_matrix_roost_wake.py -q`

Run from the worktree root with
`PYTHONPATH=$PWD/packages/ai-parrot/src:$PWD/packages/ai-parrot-integrations/src`.

## Test Specification
- `test_endpoint_background_turns.py`: nested A→B→C query returns the composed answer under 1 s (AC-1);
  mutual forwarding A↔B ends in `RoostFailure` with `HOP_LIMIT` under 1 s, wakes ≤ `hop_limit + 1` (AC-2);
  raising wake is logged (`caplog`) and the next message is served, `turns_in_flight == 0` (AC-3);
  `stop()` during a wake blocked on `query(timeout=5)` returns quickly, the wake saw `CancelledError`,
  `turns_in_flight == 0` (AC-4); served `request` whose tool awaits `endpoint.query()` on a third agent
  returns the third agent's answer to the requester (AC-5); `turns_started` counts spawned turns.

## Agent Instructions
Lint the changed files with `ruff check` and `black --check -l 120` before committing. Stage only the three
files listed above.

## Completion Note

**Completed by**: Claude Code `/sdd-fix` session (`agent:sdd-fix:b73eac7f`)
**Date**: 2026-11-07
**Notes**: Implemented M1, M2 and M4 in `eda917b658`.
- `RoostEndpoint._spawn_turn` (tracked task, `turns_started` metric, failure log with `exc_info`),
  `_serve_wake` (the former `WAKE_LLM` body, moved verbatim), `turns_in_flight` property; `_on_message`
  spawns the `WAKE_LLM` and `RUN_TOOL` turns and keeps every other branch inline. `stop()` cancels and
  awaits in-flight turns before the sweeper / unsubscribe / pending steps.
- No carrier file changed. `WakeCallback`, `Dispatch`, engine and dispatcher untouched.
- `wiki/mcp/roost/carriers.md`: "Delivery model (FEAT-828)" section.

Validation (worktree on `PYTHONPATH`): the new module 5 passed (AC-1..AC-5, each with a 1 s bound — the
nested A→B→C query and the A↔B hop-limit chain finish in well under 100 ms); `packages/ai-parrot/tests/roost/`
158 passed (gate L-S1 included); `test_matrix_roost_ask_agent` + `test_matrix_roost_wake` 31 passed.
`ruff check` and `black --check -l 120` clean. Mutation check: putting both turns back inline
(`await self._serve_wake(...)` / `await self._run_tool(...)`) fails all five new tests.

**Deviations from spec**: none. The AC-5 test marks the served agent `backing="deterministic"` — the
dispatcher only yields `RUN_TOOL` for that backing (gating.py:125-127), which the contract did not state.
