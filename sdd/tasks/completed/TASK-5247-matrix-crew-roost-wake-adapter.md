# TASK-5247: Matrix crew — Roost wake adapter and opt-in endpoint factory seam

**Feature**: FEAT-827 fixgroup-742a9ada6cba
**Spec**: `sdd/specs/fixgroup-742a9ada6cba.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:2c7a156eb239`

## Context
Implements M2–M4 of the spec: the serving side of `ask_agent` over Roost has no wake adapter, so the
served agent's `ctx.current_hops` is never seeded from the inbound `RoostMessage.hops`, and
`MatrixCrewTransport` offers no way to hand an endpoint to `AgentSwarmToolkit`.

## Scope
- M2: `MatrixCrewAgentWrapper.handle_roost_wake(msg, dispatch) -> Optional[RoostMessage]` (a `WakeCallback`).
- M3: `MatrixCrewTransport(config, *, roost_endpoint_factory=None)` + `from_yaml(path, *, roost_endpoint_factory=None)`;
  per-agent endpoint build/start, `endpoint=` on `AgentSwarmToolkit`, stop on shutdown.
- M4: "Matrix crew wiring" section in `wiki/mcp/roost/carriers.md`.
- Tests for AC-2..AC-5.

**NOT in scope**: crew YAML config for Roost; serving `REQUEST`/`CFP`/`INFORM`; `expected_schema` on the
serving side; `ctx.current_session` on the Roost path; `MatrixCarrier` (TASK-5246); `swarm_toolkit.py`.

## Files to Create / Modify
- `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/crew_wrapper.py` (modify — add `handle_roost_wake` + its prompt/timeout helpers)
- `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/transport.py` (modify — constructor, `from_yaml`, toolkit attachment, `stop`)
- `packages/ai-parrot-integrations/tests/test_matrix_roost_wake.py` (new)
- `packages/ai-parrot-integrations/tests/test_matrix_transport_roost.py` (new)
- `wiki/mcp/roost/carriers.md` (modify — add a section)

## Codebase Contract (Anti-Hallucination)
Verified against `origin/dev` @ `927f9ab4b8`.

**Verified Imports**
- `from parrot.roost.endpoint import RoostEndpoint, RoostFailure, WakeCallback` (`WakeCallback = Callable[[RoostMessage, Dispatch], Awaitable[Optional[RoostMessage]]]`)
- `from parrot.roost.gating import Dispatch, GatingDispatcher, HandlerRegistry`
- `from parrot.roost.messages import AgentAddress, FailureInfo, RoostMessage`
- `from parrot.roost.performatives import CarrierKind, FailureCode, InteractionProtocol, Performative`
- `from parrot.roost.protocols import ProtocolEngine`; `from parrot.roost.grant import GrantPolicy`
- `from parrot.roost.carriers.inprocess import InProcessCarrier`
- `from parrot.roost.directory import InterAgentGrant, RoostAgentConfig`
- `from parrot.integrations.matrix.crew import context as ctx` (`ctx.current_hops: ContextVar[int]`, default 0)
- `from parrot.integrations.matrix.crew.config import MatrixCrewAgentEntry, MatrixCrewConfig`
- `from parrot.integrations.matrix.crew.crew_wrapper import MatrixCrewAgentWrapper`
- `from parrot.integrations.matrix.crew.transport import MatrixCrewTransport`
- `from parrot.integrations.matrix.crew.swarm_toolkit import AgentSwarmToolkit`
- `from parrot.manager import BotManager` (imported lazily inside methods; tests patch `parrot.manager.BotManager.get_bot`)

**Existing Signatures**
- `MatrixCrewAgentWrapper.handle_task(self, task: TaskEventContent, room_id: str) -> None` (crew_wrapper.py:169) — the model to mirror: `ctx.current_hops.set(...)`/`reset` in `finally`, `self._registry.update_status(self._agent_name, "busy", <preview>)` then `"ready"`, `BotManager.get_bot(self._config.chatbot_id)`, `asyncio.wait_for(agent.ask(prompt), timeout)`, text via `to_text` / `content` / `str()`.
- `RoostMessage.reply(self, performative, *, content=None, body=None, failure=None, tokens=0) -> RoostMessage`; allowed replies to `QUERY` are `INFORM` and `FAILURE` (performatives.py:80–84); raises `ValueError` otherwise.
- `RoostMessage` fields used: `performative`, `content`, `sender.name`, `hops`, `conversation_id`, `envelope` (may be `None`; `LocalEnvelope.budget_ms: Optional[int]`).
- `FailureInfo(code: FailureCode, detail: str = "", retryable: bool = False)`; `FailureCode.TIMEOUT`, `FailureCode.INTERNAL`.
- `AIMessage.usage: CompletionUsage` with `total_tokens: int = 0` (parrot/models/basic.py:82); a bot may also return a plain `str`.
- `MatrixCrewTransport.__init__(self, config: MatrixCrewConfig) -> None` (transport.py:43); `from_yaml(cls, path: str)` (transport.py:63); the toolkit is built at transport.py:235 inside `if self._tunnels is not None:` as `AgentSwarmToolkit(agent_name, self._tunnels, self._registry, self._channels, self._appservice)`; `stop()` stops tunnels at transport.py:261–262; `self._wrappers: Dict[str, MatrixCrewAgentWrapper]`.
- `AgentSwarmToolkit.__init__` pops the optional `endpoint` kwarg (swarm_toolkit.py:57) and exposes it as `self._endpoint`.
- `RoostEndpoint.start()` / `stop()` are `async`.
- Endpoint test wiring to copy: `_real_endpoint(name, carrier, *, config, wake=None)` in `packages/ai-parrot-integrations/tests/test_matrix_roost_ask_agent.py`.

**Does NOT Exist**
- Any `WakeCallback` implementation or `RoostEndpoint` construction under `packages/*/src` (outside `parrot/roost/endpoint.py` itself).
- A Roost section in `MatrixCrewConfig` / the crew YAML.
- An originating-session field on `RoostMessage`.

## Implementation Notes
- `handle_roost_wake` must never raise: catch `asyncio.TimeoutError` → `FAILURE`/`TIMEOUT`; any other `Exception`
  → `FAILURE`/`INTERNAL` with `detail=type(exc).__name__` (no exception text crosses agents); log the full error locally.
- Only `Performative.QUERY` is served; anything else returns `None` without touching the bot or the registry.
- Reset `ctx.current_hops` and set the registry back to `"ready"` in `finally`.
- Roost imports in `crew_wrapper.py` / `transport.py` stay lazy (inside the method) or under `TYPE_CHECKING`,
  matching `swarm_toolkit.py` — the Matrix crew must import without touching `parrot.roost` at module load.
- Transport: keep endpoint creation in one small private coroutine so it is unit-testable without `start()`;
  a factory / `start()` error must propagate; `stop()` stops every endpoint, logging (not raising) per-endpoint errors.

## Acceptance Criteria
Spec AC-2..AC-6.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/test_matrix_roost_wake.py packages/ai-parrot-integrations/tests/test_matrix_transport_roost.py -q`
- `pytest packages/ai-parrot-integrations/tests/test_matrix_handle_task.py packages/ai-parrot-integrations/tests/test_matrix_transport_swarm.py packages/ai-parrot-integrations/tests/test_matrix_roost_ask_agent.py -q`

Run from the worktree root with
`PYTHONPATH=$PWD/packages/ai-parrot/src:$PWD/packages/ai-parrot-integrations/src`.

## Test Specification
- `test_matrix_roost_wake.py`: hop depth visible inside `bot.ask` and restored after (AC-2); INFORM reply with
  text + tokens, str response → tokens 0 (AC-3); bot error / timeout / missing bot → FAILURE codes, no raise (AC-3);
  non-QUERY → `None`, bot not called (AC-3); two real in-process endpoints + wrappers + toolkits, bots that
  re-ask the peer: chain ends in `hop_limit` with a bounded wake count (AC-4).
- `test_matrix_transport_roost.py`: factory called with `(agent_name, wrapper.handle_roost_wake)`, `start()` awaited,
  endpoint retained and stopped by `stop()`; factory error propagates; no factory → `None` (AC-5).

## Agent Instructions
Lint the changed files with `ruff check` before committing. Stage only the five files listed above.

## Completion Note

**Completed by**: Claude Code `/sdd-fix` session (`agent:sdd-fix:b73eac7f`)
**Date**: 2026-11-06
**Notes**: Implemented M2–M4 in `903985339e`.
- `MatrixCrewAgentWrapper.handle_roost_wake` (+ `_response_text`, `_response_tokens`, `_ROOST_WAKE_TIMEOUT`).
- `MatrixCrewTransport(roost_endpoint_factory=...)`, `from_yaml(..., roost_endpoint_factory=...)`,
  `_start_roost_endpoint`, `_stop_roost_endpoints`. The toolkit attachment loop moved verbatim from `start()` into
  `_attach_swarm_toolkits()` so the endpoint hand-off is unit-testable; its only behavioural change is `endpoint=`.
- `wiki/mcp/roost/carriers.md`: "Matrix crew wiring (FEAT-827)".

Validation: the two new modules 23 passed; `test_matrix_handle_task`, `test_matrix_transport_swarm`,
`test_matrix_roost_ask_agent` green; all `-k matrix` integration tests 299 passed, 2 skipped, 6 failed — the six
are `test_matrix_hook.py` (`'MatrixHook' object has no attribute '_on_room_message'`), a module this task does
not touch and that imports `navigator_eventbus`. `ruff check` / `black --check -l 120` clean on the four Python
files. Mutation-checked (no hop seeding, leaked exception text, serving non-queries, toolkit without endpoint,
`stop()` skipping endpoints, swallowed factory error): each fails the new tests.

**Deviations from spec**: AC-4 was revised on this branch (spec § Revision). The original AC required a full
A→B→A chain over real endpoints to end in `hop_limit`; a probe showed that an agent woken by a query cannot
receive the reply to its own onward query (always `TIMEOUT`) — a core Roost defect filed as
`issue:a409d14b8130`, outside this task. The chain is pinned as: onward `query()` carries the inbound depth
(toolkit seam) + one real hop serves at depth `d + 1` and refuses at the hop limit.
