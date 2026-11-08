# TASK-5245: Roost ask_agent — carry the conversation id, lock hop / schema carriage

**Feature**: FEAT-825 fixgroup-e6ea121738c9
**Spec**: `sdd/specs/fixgroup-e6ea121738c9.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:0f5ee739eca8`

## Context
Implements M1–M3 of the spec: the one limb of `issue:0f5ee739eca8` still open on `dev`
(`conversation_id` carriage on the Roost `ask_agent` path) plus toolkit-level regression tests for
the two limbs that already shipped (hop budget, `expected_schema`).

## Scope
- M1: `RoostEndpoint.query()` accepts a keyword-only `conversation_id: Optional[str] = None`; validated like
  `trace_id`; used instead of the minted `uuid4().hex` when given; return value unchanged.
- M2: `AgentSwarmToolkit._ask_via_roost` mints the id, passes it to `query()`, and reports it in the success
  `metadata` and in the `RoostFailure` status dict.
- M3: toolkit tests that `hops` / `expected_schema` reach `query()`, and an in-process two-endpoint test that
  `ask_agent` returns `hop_limit` at the hop limit.

**NOT in scope**: `request()` / `cfp()` / `inform()`; the return type of `query()`; a Matrix `WakeCallback`
adapter (receiving-side `ctx.current_hops` seeding); `issue:c0063cc362a5`.

## Files to Create / Modify
- `packages/ai-parrot/src/parrot/roost/endpoint.py` (modify — `query()` only)
- `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py` (modify — `_ask_via_roost` only)
- `packages/ai-parrot/tests/roost/test_query_conversation_id.py` (new)
- `packages/ai-parrot-integrations/tests/test_matrix_roost_ask_agent.py` (modify — add tests, keep existing ones)

## Codebase Contract (Anti-Hallucination)
Verified against `origin/dev` @ `0a87e83e3d`.

**Verified Imports**
- `from parrot.roost.endpoint import RoostEndpoint, RoostFailure`
- `from parrot.roost.protocols import ProtocolEngine, ConversationExistsError`
- `from parrot.roost.carriers.inprocess import InProcessCarrier`
- `from parrot.roost.directory import InterAgentGrant, RoostAgentConfig`
- `from parrot.roost.gating import GatingDispatcher, HandlerRegistry`
- `from parrot.roost.grant import GrantPolicy`
- `from parrot.roost.messages import AgentAddress, FailureInfo`
- `from parrot.roost.performatives import CarrierKind, FailureCode, Performative`
- `from parrot.integrations.matrix.crew import context as ctx` (`ctx.current_hops: ContextVar[int]`, default 0)
- `from parrot.integrations.matrix.events import AgentAnswer`

**Existing Signatures**
- `RoostEndpoint.query(self, question, *, receiver: AgentAddress, timeout=None, expected_schema=None, hops: int = 0, trace_id: str | None = None) -> Any` (endpoint.py:544); it validates `trace_id` (endpoint.py:568–573), checks the grant, then mints `conversation_id = uuid.uuid4().hex` (endpoint.py:576) and calls `self.engine.open(opener)` (endpoint.py:597) **before** `self._pending[conversation_id] = future`.
- `ProtocolEngine.open(opener, *, budget=None)` raises `ConversationExistsError` (a `ValueError`, protocols.py:39) when the id is already in `self._states` (protocols.py:242).
- `ProtocolEngine(default_hop_limit: int = 8, ...)` (protocols.py:221).
- `AgentSwarmToolkit._ask_via_roost(self, agent, question, *, expected_schema=None, timeout=None) -> dict` (swarm_toolkit.py:118); calls `self._endpoint.query(question, receiver=AgentAddress(name=agent), timeout=timeout, expected_schema=expected_schema, hops=ctx.current_hops.get())` (swarm_toolkit.py:156) and returns `AgentAnswer(answer=result, metadata={"via": "roost", "status": "ok"}).model_dump()` (swarm_toolkit.py:173).
- `AgentSwarmToolkit.__init__` pops `endpoint` from kwargs (swarm_toolkit.py:56).
- Test helper to copy (do not import across packages): `make_endpoint(...)` in `packages/ai-parrot/tests/roost/test_endpoint.py:24`.
- `uuid` is already imported in endpoint.py (line 9); swarm_toolkit.py does **not** import `uuid`.

**Does NOT Exist**
- A `conversation_id` parameter on `RoostEndpoint.query()` / `request()`.
- A conversation id on `RoostFailure` / `FailureInfo`.
- Any `WakeCallback` implementation under `packages/ai-parrot-integrations/src/parrot/integrations/matrix/`.

## Implementation Notes
- Validate `conversation_id` with the same predicate as `trace_id` (non-empty `str`, no whitespace, no Unicode
  `Cc`/`Cf`). Share one private module-level helper for both rather than duplicating the expression; keep the two
  existing `trace_id` error messages byte-identical (tests assert on behaviour, the message is user-facing).
- Do not catch `ConversationExistsError`; let `engine.open` raise it. Nothing may be added to `_pending` or sent
  before it.
- In `_ask_via_roost` the id is minted locally (`uuid.uuid4().hex`), never read from tool arguments.
- `GrantDenied` result stays exactly `{"status": "refused", "detail": "grant denied: <agent>"}`.

## Acceptance Criteria
Spec AC-1..AC-6.

## Validation Commands

- `pytest packages/ai-parrot/tests/roost/test_query_conversation_id.py packages/ai-parrot/tests/roost/test_endpoint.py packages/ai-parrot/tests/roost/test_query_trace.py -q`
- `pytest packages/ai-parrot-integrations/tests/test_matrix_roost_ask_agent.py packages/ai-parrot-integrations/tests/test_matrix_swarm_toolkit.py -q`

Run from the worktree root with
`PYTHONPATH=$PWD/packages/ai-parrot/src:$PWD/packages/ai-parrot-integrations/src` (the shared venv is
editable-installed against the main checkout).

## Test Specification
- `test_query_conversation_id.py`: supplied id reaches the receiver's wake as `msg.conversation_id` and the answer
  resolves (AC-1); default still mints a 32-hex id (AC-1); parametrized invalid ids raise `ValueError` with nothing
  sent (AC-2); an id already open in the engine raises `ConversationExistsError`, `_pending` unchanged and the
  first conversation still resolves (AC-2).
- `test_matrix_roost_ask_agent.py`: success metadata carries the id passed to `query()` (AC-3); failure dict carries
  it, `GrantDenied` dict unchanged (AC-4); `hops` / `expected_schema` forwarded (AC-5); real two-endpoint
  `hop_limit` (AC-5).

## Agent Instructions
Lint the changed files with `ruff check` before committing. Stage only the four files listed above.

## Completion Note

**Completed by**: Claude Code `/sdd-fix` session (`agent:sdd-fix:b73eac7f`)
**Date**: 2026-11-06
**Notes**: Implemented M1–M3 in `9d92c40a61`.
- M1: `RoostEndpoint.query(conversation_id=...)`; the `trace_id` predicate moved into the module-level
  `_is_wire_identifier()` helper and is shared by both identifiers (the `trace_id` error message is unchanged).
- M2: `_ask_via_roost` mints the id and reports it in the success `metadata` and in `RoostFailure` status dicts.
- M3: toolkit tests for `hops` / `expected_schema` forwarding plus a two-real-endpoint test (`ok` at 0 hops with
  `msg.hops == 1` on the wire and a matching conversation id; `hop_limit` at 8 hops, nothing served).

Validation: `packages/ai-parrot/tests/roost` 153 passed; the task's two validation commands 65 passed;
`ruff check` and `black --check -l 120` clean on the four files. Mutation-checked: dropping `hops=` from the
toolkit call (2 failures), dropping `conversation_id=` from it (4), ignoring the supplied id in `query()` (4) and
skipping its validation (9) each fail the new tests.

**Deviations from spec**: none. The hop-budget and `expected_schema` limbs of `issue:0f5ee739eca8` were already on
`dev` (`8ffec9c103`, FEAT-788); this task only adds the regression tests for them.
