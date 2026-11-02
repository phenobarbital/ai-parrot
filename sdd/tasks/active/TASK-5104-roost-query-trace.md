# TASK-5104: Trace-carrying Roost queries and terminal audit coverage

**Feature**: FEAT-790 — Expert model overrides and trace-carrying Roost queries
**Spec**: `sdd/specs/expert-model-override-and-roost-trace.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement spec M2/M3 and Roost's M4 documentation together. Merely adding query(trace_id=...)
would leave generated timeout and cancellation messages untraced and locally routed failures
unaudited. This task owns the complete trace path and its tests. It consumes no new registry symbols.
Decision-audit advisory remains SNAPSHOT_UNSTABLE; do not repair unrelated inventory code here
or treat task completion as evidence that the feature's consequence audit has passed.

## Scope

- Add keyword-only trace_id: str | None = None to query. Reject non-string, empty, Unicode whitespace,
  Cc and Cf values with ValueError before state/waiter/envelope/send side effects. Preserve the exact
  value; t1 is valid. None does not inherit an ambient trace. Generate a fresh 16-hex span_id.
- Construct the existing TraceContext and pass trace= into new_envelope; preserve grants, caller
  authority, hop accounting, expected_schema and result/error semantics.
- Add ConversationState.envelope: Any = None, set it from the opener, and preserve it on every
  ProtocolEngine-generated timeout, hop/token budget and cancellation message. Keep engine I/O-free.
- Audit locally addressed output in _route_emitted before resolving the waiter. Remote output still
  uses _send_reply, with no duplicate record on that route.
- Add _finish_query_failure(conversation_id, *, code, detail) for local timeout/task cancellation.
  Claim an open state synchronously before audit I/O; close as TIMED_OUT or CANCELLED and audit one
  local FAILURE with the retained envelope, addressed to the initiator. Never send this synthetic
  failure remotely or route the engine's cancellation REJECT from this helper. If already terminal,
  do not synthesize another event. Do not suppress real received-message auditing.
- In query, await cleanup on asyncio.CancelledError then re-raise it. Timeout still raises
  RoostFailure(TIMEOUT); always remove the pending waiter. Leave request's _close_timed_out unchanged.
- Endpoint.cancel remains RoostFailure(CANCELLED) with existing REJECT/failure payload semantics;
  make it idempotent for already-terminal states. Retain envelopes. Audit storage errors fail closed.
- Document qualified LocalEnvelope behavior and unqualified satellite parity, including terminal
  audit additions for untraced failures and unchanged successful untraced exchanges.

**NOT in scope**: new trace keywords on other openers, Squawk wire/schema/import changes, W3C-only
validation, provider calls, grants/policy redesign, audit entry schema, registry overrides or dependencies.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/protocols.py` | MODIFY | Retain opener envelope on generated terminal messages |
| `packages/ai-parrot/src/parrot/roost/endpoint.py` | MODIFY | Query trace input, terminal cleanup and local audit routing |
| `packages/ai-parrot/tests/roost/test_query_trace.py` | CREATE | Complete LocalEnvelope trace and failure-path coverage |
| `docs/roost/README.md` | MODIFY | Query tracing contract, example and satellite limitation |

## Codebase Contract (Anti-Hallucination)

Verified at `408bd66808a46803df16e165a44b727b53aa6c82`. Source paths abbreviated below as
R = `packages/ai-parrot/src/parrot/roost/`.

### Verified Imports

```python
import asyncio  # standard library; existing endpoint.py:5
import secrets  # standard library, token_hex(8) for span_id
import unicodedata  # standard library, category for Cc/Cf validation
from typing import Any, Optional  # standard library
from pydantic import BaseModel  # existing protocols.py:11
import pytest  # existing tests/roost/test_endpoint.py:8
from parrot.core.events.lifecycle import TraceContext  # packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py:18
from parrot.roost import squawk_bridge  # endpoint.py:12 imports the same sibling module
from parrot.roost.endpoint import RoostEndpoint, RoostFailure  # R/endpoint.py:51,43
from parrot.roost.messages import AgentAddress, FailureInfo, RoostMessage  # R/messages.py:42,50,58
from parrot.roost.protocols import ConversationBudget, ConversationState, ProtocolEngine, TerminalState, Transition
# verified: R/protocols.py:43,54,217,25,68
from parrot.roost.performatives import FailureCode, Performative  # R/performatives.py:38,11
```

Relative imports inside source modules stay relative. The test uses absolute parrot imports.
Preserve existing source imports not shown. Verify added test-helper imports against source before use.

### Existing Signatures to Use

- query(self, question: Any, *, receiver: AgentAddress, timeout: Optional[float] = None,
  expected_schema: Optional[dict] = None, hops: int = 0) -> Any at R/endpoint.py:539.
- _route_emitted(self, emitted: RoostMessage) -> None (async) at :158 currently skips local auditing;
  _resolve_pending at :342 recognizes INFORM/REFUSE/FAILURE; _audit_direction at :356 reports initiator
  role `received` and serving role `served`; _deliver_outbound at :384 records remote output.
- cancel(self, conversation_id: str, *, reason: str = "") -> None (async) at :699 emits REJECT and
  sets RoostFailure(CANCELLED). _close_timed_out at :610 remains request-compatible and synchronous.
- ConversationState at R/protocols.py:54 has conversation_id, protocol, initiator, state, terminal,
  budget, last_message_id, proposals and opened_at, but no envelope yet.
- ProtocolEngine.open(opener, *, budget=None) -> ConversationState at :235; state(id) at :339;
  close(id, terminal, *, reason="") -> Transition at :343; expire(*, now=None) at :297;
  _close_with_failure(state, code, detail, source=None) -> Transition at :374 omits envelope today.
- new_envelope(*, correlation_id: str, caller: str, trace: Optional[TraceContext] = None,
  budget_ms: Optional[int] = None, token_budget: Optional[int] = None,
  idempotency_key: Optional[str] = None) -> Any at R/squawk_bridge.py:83.
- RoostMessage.reply retains envelope at R/messages.py:121; trace_id() at :132 reads nested trace.
- RoostAuditLedger.record(msg, *, direction, self_name) -> RoostAuditEntry (async) at R/audit.py:116;
  verify(entry) -> bool (async) at :162; entries(*, conversation_id=None, trace_id=None) at :173.
- TraceContext re-export is verified above; installed navigator_eventbus/lifecycle/trace.py:38 requires
  trace_id and span_id. Direct construction accepts application ids; do not use from_traceparent_header.
- Existing isolated endpoint setup: packages/ai-parrot/tests/roost/test_endpoint.py:24 make_endpoint;
  use its carrier/dispatcher/grant/mock patterns in the new test file, without editing shared fixtures.

### Does NOT Exist

- query trace_id keyword, ConversationState.envelope, _finish_query_failure and test_query_trace.py are new.
- RoostAuditEntry has no failure-code field; inspect FailureInfo on captured emitted messages instead.
- Satellite CallMessage source at packages/ai-parrot-squawk/src/parrot/squawk/schema/messages.py is absent;
  mocked satellite tests cannot establish parity. Qualify LocalEnvelope explicitly.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/protocols.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/roost/endpoint.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_query_trace.py",
      "action": "CREATE"
    },
    {
      "path": "docs/roost/README.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/roost/endpoint.py#RoostEndpoint",
    "sym:packages/ai-parrot/src/parrot/roost/endpoint.py#RoostFailure",
    "sym:packages/ai-parrot/src/parrot/roost/protocols.py#ConversationState",
    "sym:packages/ai-parrot/src/parrot/roost/protocols.py#ProtocolEngine",
    "sym:packages/ai-parrot/src/parrot/roost/protocols.py#TerminalState",
    "sym:packages/ai-parrot/src/parrot/roost/protocols.py#Transition",
    "sym:packages/ai-parrot/src/parrot/roost/protocols.py#ConversationBudget",
    "sym:packages/ai-parrot/src/parrot/roost/messages.py#RoostMessage",
    "sym:packages/ai-parrot/src/parrot/roost/messages.py#AgentAddress",
    "sym:packages/ai-parrot/src/parrot/roost/messages.py#FailureInfo",
    "sym:packages/ai-parrot/src/parrot/roost/audit.py#RoostAuditLedger",
    "sym:packages/ai-parrot/src/parrot/roost/squawk_bridge.py#new_envelope",
    "sym:packages/ai-parrot/src/parrot/roost/performatives.py#FailureCode",
    "sym:packages/ai-parrot/src/parrot/roost/performatives.py#Performative"
  ]
}
```

## Implementation Notes

No-trace success behavior is unchanged; missing terminal audit records are intentionally repaired
even without a trace. Claim terminal state before an await to avoid two local completions winning.
Do not rely on wall-clock sleeps in race tests. Always clean pending waiters on send/audit failures.
Cancellation cleanup must not convert task cancellation into a successful answer. Preserve endpoint
grant/authority and query schema validation. Retain only envelopes, not entire payloads or a second
unbounded trace dictionary. Local routing records exactly once; remote routing already audits.

## Implementation Blueprint

### Steps (in order)

1. Retain the opener envelope in state and generated messages — sweeps have no source message.
2. Add validation and TraceContext construction to query — fail invalid input before side effects.
3. Complete terminal cleanup and local audit routing — preserve trace through every failure path.
4. Add deterministic success/failure/concurrency tests and documentation — qualify the supported mode.

### `packages/ai-parrot/src/parrot/roost/protocols.py` (MODIFY)

Anchor: `class ConversationState(BaseModel):` at :54; literal occurrence count: **1**.
Keep existing fields and engine methods; extend the typing import with Any.

```python
class ConversationState(BaseModel):
    """Existing conversation state plus the opener envelope used for generated output."""
    envelope: Any = None
    # FILL IN: retain every existing field, unchanged (AC2).

class ProtocolEngine:
    def open(self, opener: RoostMessage, *, budget: Optional[ConversationBudget] = None) -> ConversationState:
        """Initialize the existing state and retain opener.envelope."""
        # FILL IN: add envelope=opener.envelope to existing construction (AC2).
        raise NotImplementedError

    def close(self, conversation_id: str, terminal: TerminalState, *, reason: str = "") -> Transition:
        """Preserve the envelope on existing cancellation output."""
        # FILL IN: keep REJECT/CANCELLED semantics; add envelope=state.envelope (AC2, AC5).
        raise NotImplementedError

    def _close_with_failure(self, state: ConversationState, code: FailureCode, detail: str,
                            source: Optional[RoostMessage] = None) -> Transition:
        """Carry the retained envelope through timeout, hop and token-budget failure output."""
        # FILL IN: preserve current protocol fields and add state envelope (AC2).
        raise NotImplementedError
```

Why: existing protocol messages need no new wire fields; the state keeps the envelope available
when a timer or cancellation has no message argument. Keep protocol state transitions synchronous.

### `packages/ai-parrot/src/parrot/roost/endpoint.py` (MODIFY)

Anchor: `    async def query(` at :539; literal occurrence count: **1**.
Add standard-library secrets/unicodedata and the existing TraceContext import. Extend the existing
class at the verified methods; do not replace unrelated endpoint behavior.

```python
class RoostEndpoint:
    async def query(self, question: Any, *, receiver: AgentAddress,
                    timeout: Optional[float] = None, expected_schema: Optional[dict] = None,
                    hops: int = 0, trace_id: str | None = None) -> Any:
        """Query with optional exact application trace; reject invalid ids before side effects."""
        # FILL IN: validation, TraceContext(trace_id=..., span_id=secrets.token_hex(8)),
        # envelope trace=, existing grant/send/wait logic and terminal cleanup (AC1, AC3-AC6).
        raise NotImplementedError

    async def _finish_query_failure(self, conversation_id: str, *, code: FailureCode, detail: str) -> None:
        """Close an open query and audit one local TIMEOUT or CANCELLED failure."""
        # FILL IN: synchronous terminal claim, retained-envelope FAILURE, local ledger only (AC4).
        raise NotImplementedError

    async def _route_emitted(self, emitted: RoostMessage) -> None:
        """Audit local generated messages before resolving; retain existing remote delivery."""
        # FILL IN: one record on the local branch; no added record on remote branch (AC3, AC4).
        raise NotImplementedError

    async def cancel(self, conversation_id: str, *, reason: str = "") -> None:
        """Cancel an open conversation once, keeping the existing CANCELLED error contract."""
        # FILL IN: already-terminal guard plus existing emission and waiter handling (AC5).
        raise NotImplementedError
```

Why: a local timeout is an audit event, not a remote cancellation protocol. Retain query's finally
cleanup and typed failures; re-raise asyncio.CancelledError after its local cleanup completes.

### `packages/ai-parrot/tests/roost/test_query_trace.py` (CREATE)

```python
"""LocalEnvelope query traces, generated failures and audit-race regressions for FEAT-790."""
from __future__ import annotations
import pytest
from parrot.roost import squawk_bridge
from parrot.roost.endpoint import RoostEndpoint, RoostFailure
from parrot.roost.messages import AgentAddress, RoostMessage
from parrot.roost.protocols import ProtocolEngine

@pytest.mark.asyncio
async def test_query_trace_exchange(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both ledgers retain the exact trace and valid signatures on opener and reply."""
    # FILL IN: two deterministic endpoints; force LocalEnvelope; assert both roles (AC3).
    raise NotImplementedError

@pytest.mark.asyncio
async def test_invalid_trace_has_no_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """All invalid values raise before state, envelope creation, waiter creation or send."""
    # FILL IN: non-string/empty/Unicode whitespace/Cc/Cf cases, plus t1 and None (AC1).
    raise NotImplementedError

@pytest.mark.asyncio
async def test_engine_terminal_retains_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expire, hop/token budget and cancel output retain the opener envelope."""
    # FILL IN: clock-driven engine transitions and actual FailureInfo assertions (AC2).
    raise NotImplementedError

@pytest.mark.asyncio
async def test_query_local_and_swept_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local wait and both sweep routes produce traced terminal audit records."""
    # FILL IN: deterministic deadline control, waiter removal, TIMEOUT and signatures (AC4).
    raise NotImplementedError

@pytest.mark.asyncio
async def test_query_cancellation_and_terminal_races(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit cancel and task cancel preserve semantics without duplicate local outcomes."""
    # FILL IN: event-controlled races, late replies and repeated cancellation (AC5).
    raise NotImplementedError

@pytest.mark.asyncio
async def test_query_trace_isolation_and_audit_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent traces stay isolated; storage failure never becomes success."""
    # FILL IN: untraced baseline, fresh spans, concurrent queries and storage failure (AC6).
    raise NotImplementedError
```

Expand cases into separate tests as needed. Build helpers locally using test_endpoint.py's pattern
after verifying its imports. Use fake wake responses, mocked tools, event barriers and injected clocks;
no external LLM/network or shared-conftest changes. Capture messages to inspect failure codes.

### `docs/roost/README.md` (MODIFY)

Anchor: `## Quick start` at :30; literal occurrence count: **1**. Add the following section after
the existing quick-start content; retain current examples.

```markdown
## Query trace identifiers

<!-- FILL IN: a configured caller.query(question, receiver=AgentAddress(name="analyst"),
trace_id="run-123") example; required grant/config context; exact validation and None behavior;
trace lookup on both ledgers; timeout/cancellation audit semantics; LocalEnvelope-only qualification.
Explain arbitrary audit ids are not necessarily W3C traceparent ids; satellite parity is unqualified. -->
```

### FILL IN checklist

- [ ] Preserve envelope in engine state and each generated failure/cancellation message.
- [ ] Query input validation, fresh spans and original grant/authority/schema behavior.
- [ ] Terminal claim, audit routing, idempotence and waiter cleanup under races/storage errors.
- [ ] Complete every success/failure/isolation test and documentation section; no implementation stubs remain.

## Acceptance Criteria

- [ ] AC1: query exposes trace_id; invalid inputs raise before side effects; t1 accepted; None stays absent.
- [ ] AC2: All generated terminal messages retain opener envelope, including no-source expiry and cancellation.
- [ ] AC3: Both endpoints' query/reply audit entries retain exact trace with valid signatures and correct role.
- [ ] AC4: Local and swept timeouts record traced terminal failure, raise TIMEOUT and remove pending waiters.
- [ ] AC5: Explicit cancellation raises CANCELLED, task cancellation re-raises CancelledError; repeated/racing
      completion does not duplicate locally synthesized terminal events or overwrite a winning terminal state.
- [ ] AC6: Concurrent traces/spans are isolated; untraced success, grants, authority, hops and schema checks
      remain correct; audit errors fail closed and waiters are cleaned up.
- [ ] AC7: Focused tests, black and ruff pass; docs explain support boundaries; no wire/dependency changes.

## Validation Commands

- `pytest packages/ai-parrot/tests/roost/test_query_trace.py -q`

## Test Specification

Cover spec §4's full Roost matrix: success on both ledgers; no-trace baseline; invalid types and Unicode;
fresh spans with exact application ids; engine expire/hop/token failures; local and remote sweep routes;
local timeout; endpoint cancel and asyncio task cancel; deterministic timeout/sweep/cancel/late-reply
ordering; concurrent trace isolation; schema/grant/authority preservation; fail-closed audit storage.
The feature's cached contract adds existing endpoint/protocol/audit/bridge regressions at later gates.

## Agent Instructions

1. Use `$sdd-start TASK-5104` to provision the feature worktree; never implement on dev.
2. Reverify the spec/contracts and modify only these four files. Other agents may work on the registry.
3. Complete blueprint branches/tests, run Validation Commands and repository format/lint checks.
4. Commit the scoped implementation; finalize using `scripts.sdd.finalize_task` and real
   TaskCompletionEvidence for the implementation HEAD, following docs/sdd/CODEX.md.
5. Commit generated completion state. Do not manually move this task or claim satellite parity,
   downstream rollout, or the separate consequence audit passed.

## Completion Note

Pending implementation; populated by the finalization workflow with actual evidence.
