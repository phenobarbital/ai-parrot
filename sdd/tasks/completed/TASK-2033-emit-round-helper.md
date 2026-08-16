# TASK-2033: AbstractClient._emit_round_event() helper

**Feature**: FEAT-397 — Per-Round Token Usage Observability
**Spec**: `sdd/specs/tokens-observability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2032
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. The shared emission helper all five client tasks
(TASK-2034…2038) call from inside their tool loops. Lives next to the
existing `_emit_before_call` / `_emit_after_call` / `_emit_failed_call`
helpers on `AbstractClient`.

---

## Scope

- Implement on `AbstractClient` (`clients/base.py`):
  ```
  def _emit_round_event(self, tc, *, client_name, model, round_number,
                        usage, raw_usage, tool_calls, duration_ms) -> None
  ```
  where `usage: Optional[CompletionUsage]` supplies the flat token ints
  (`usage.prompt_tokens` → `input_tokens`, `usage.completion_tokens` →
  `output_tokens`, `usage.total_tokens` → `total_tokens`; all None when
  `usage is None`), `raw_usage: Optional[dict]` passes through, and
  `tool_calls: Sequence[str]` is coerced to `tuple`.
- Short-circuit FIRST: `if not self.events.has_subscribers(ClientRoundEvent): return`
  — zero event construction when nobody listens.
- Emit fire-and-forget: `emit_nowait` + `forward_to_global`, mirroring
  `_emit_before_call`.
- Populate `agent_name` from the FEAT-228 ContextVar exactly like the
  sibling emitters do (defensive read; failure → None, never raises).
- Thread `trace_context=tc` (the TraceContext returned by
  `_emit_before_call`) plus `source_type="client"`, `source_name=client_name`.
- Unit tests (short-circuit, agent_name propagation, payload mapping).

**NOT in scope**: calling the helper from any client loop (TASK-2034…2038).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | Add `_emit_round_event()` |
| `packages/ai-parrot/tests/unit/clients/test_emit_round_event.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.core.events.lifecycle.events import ClientRoundEvent  # created by TASK-2032
from parrot.models.basic import CompletionUsage                   # models/basic.py:48
# TraceContext / EventEmitterMixin are already imported in clients/base.py — reuse.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):        # line ~242
    # ctor calls self._init_events(forward_to_global=False) — ISOLATED registry;
    # the client events are explicitly bridged via forward_to_global(event).
    def _emit_before_call(...) -> TraceContext:      # lines 423-478
        # pattern: emit_nowait(Event(..., source_type="client", source_name=client_name))
        # + agent_name read from FEAT-228 ContextVar at construction time
    async def _emit_after_call(self, tc, *, client_name, model, duration_ms,
        input_tokens=None, output_tokens=None, finish_reason=None) -> None:  # lines 480-523
        # pattern: await self.events.emit(event); self.events.forward_to_global(event)
    async def _emit_failed_call(...) -> None:        # lines 525-562

# EventRegistry (navigator_eventbus side, used by hot-path guard):
#   self.events.has_subscribers(EventType) -> bool
#   verified precedent: ask_stream uses it for ClientStreamChunkEvent
#   (see TASK-1194 completion; grep "has_subscribers" in clients/base.py)

# packages/ai-parrot/src/parrot/models/basic.py
class CompletionUsage(BaseModel):                    # line 48
    prompt_tokens: int      # line 70
    completion_tokens: int  # line 73
    total_tokens: int       # line 76
```

### Does NOT Exist
- ~~`AbstractClient._emit_round_event`~~ — created by THIS task
- ~~an awaited emit for round events~~ — round emission is `emit_nowait`
  (sync, fire-and-forget); do NOT make the helper async
- ~~`ClientRoundEvent.usage`~~ — the event has NO nested usage field; map
  to flat `input_tokens`/`output_tokens`/`total_tokens`

---

## Implementation Notes

### Pattern to Follow
```python
# Copy the structure of _emit_before_call (clients/base.py:423-478):
# build kwargs, read agent_name defensively, emit_nowait, forward_to_global.
# Copy the has_subscribers() short-circuit from the ClientStreamChunkEvent
# hot path in ask_stream implementations.
```

### Key Constraints
- Helper is SYNC (`def`, not `async def`) — it must be callable from inside
  loops without awaiting; `emit_nowait` is non-blocking.
- Short-circuit BEFORE constructing the event object.
- `tool_calls` coerced with `tuple(tool_calls)`; empty sequence → `()`.
- `raw_usage` must be passed through as-is (callers guarantee JSON-safety);
  do not deep-copy in the hot path.

---

## Acceptance Criteria

- [ ] Helper exists with the signature above; sync, fire-and-forget.
- [ ] Zero subscribers → zero event constructions (assert via mock on the registry).
- [ ] With a subscriber: event carries mapped token ints, tuple tool_calls, raw_usage, round_number, duration_ms, trace_context threading.
- [ ] `agent_name` populated from ContextVar when set (FEAT-228 parity).
- [ ] Tests pass: `pytest packages/ai-parrot/tests/unit/clients/test_emit_round_event.py -v`
- [ ] Existing client lifecycle tests pass: `pytest packages/ai-parrot/tests/unit/clients/test_client_lifecycle.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/clients/test_emit_round_event.py
# Reuse the fake-concrete-client fixture pattern from
# packages/ai-parrot/tests/unit/clients/test_client_lifecycle.py.

class TestEmitRoundEvent:
    def test_short_circuit_no_subscribers(self, fake_client): ...
    def test_event_payload_mapping(self, fake_client): ...
        # usage=CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        # → input_tokens=10, output_tokens=5, total_tokens=15
    def test_usage_none_maps_to_none_tokens(self, fake_client): ...
    def test_agent_name_from_contextvar(self, fake_client): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2032 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/tokens-observability.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill in the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-01
**Notes**: Added `AbstractClient._emit_round_event()` in `clients/base.py`
right after `_emit_before_call` (before `_emit_after_call`), following the
same fire-and-forget `emit_nowait` + `forward_to_global` pattern, with the
`has_subscribers(ClientRoundEvent)` short-circuit checked first (mirroring
the `ClientStreamChunkEvent` hot-path guards used in `claude.py`/`gpt.py`/
`groq.py`/`grok.py`). Added `ClientRoundEvent` to the `events/__init__`
import block and `Sequence` to the typing imports. Created
`tests/unit/clients/test_emit_round_event.py` (4 tests: short-circuit,
payload mapping, usage=None, agent_name from ContextVar) — all pass.
Ran `tests/unit/clients/` (23 passed) including the pre-existing
`test_client_lifecycle.py` suite.

**Deviations from spec**: none
