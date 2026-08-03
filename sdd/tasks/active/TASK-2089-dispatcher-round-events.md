# TASK-2089: Emit ClientRoundEvent from the LLMCodeDispatcher tool loop

**Feature**: FEAT-405 — Nova (AWS Bedrock) Dispatcher & Per-Agent Usage Report
**Spec**: `sdd/specs/novaclient-dev-loop.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** of the spec — and it is independent of every Nova task,
so it can be picked up first or in parallel.

FEAT-397 (`sdd/specs/tokens-observability.spec.md`) solved per-round token
accounting at the **client** layer: each client's `ask()` tool loop accumulates
`CompletionUsage`, emits a `ClientRoundEvent` per round, and exposes
`AIMessage.total_usage()` plus a round count at `usage.extra_usage["rounds"]`.

But `LLMCodeDispatcher` **never calls `ask()`**. It drives
`client._chat_completion(...)` in its own turn loop (`dispatchers/llm.py:190`),
so FEAT-397's in-`ask()` accumulation never runs for the dev-loop dispatch path —
for *any* backend. That is why nvidia, zai, moonshot and grok all report `None`
tokens today.

This task closes that gap by driving the same emitter trio the clients use.
Per [R8] it covers **all** backends from day one, not just Nova.

> **Investigated and confirmed (spec Q6): no extraction is needed.**
> `_emit_round_event` is an `AbstractClient` instance method whose only
> dependencies are `self.events` / `get_global_registry()` and a `TraceContext`
> from `_emit_before_call`. Nothing couples it to `ask()`, and `_dispatch_loop`
> already holds the client instance.

---

## Scope

- In `LLMCodeDispatcher._dispatch_loop` (`llm.py:172`):
  - before the turn loop, obtain `tc = client._emit_before_call(...)`;
  - after each turn, call `client._emit_round_event(tc, …, round_number=turn_index + 1, …)`;
  - after the loop, `await client._emit_after_call(tc, …)`.
- Extract each turn's `CompletionUsage` and provider-native `raw_usage` from the
  `_chat_completion` response, plus the tool names invoked and the turn's
  wall-clock `duration_ms`.
- **Add NO accumulation.** One event per round; summing is the consumer's job.
- Handle a client that lacks the emitter methods gracefully (no crash) — the
  dispatcher must keep working with test doubles and non-`AbstractClient` clients.
- Write unit tests, including a non-Nova backend path.

**NOT in scope**: summing/aggregating tokens anywhere in the dispatcher
(explicitly forbidden — see §1 Non-Goals); the `UsageReport` model and renderers
(TASK-2090/2091); per-round accumulation inside `BedrockConverseBase`
(**FEAT-404**, a separate spec).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` | MODIFY | Emitter trio around the turn loop; per-turn usage extraction |
| `packages/ai-parrot/tests/flows/dev_loop/test_dispatch_round_events.py` | CREATE | Unit tests |

> **Caution**: `dispatchers/llm.py` is described by its sibling `_shared.py`
> docstring as "hot, actively-churning". Keep the diff minimal and rebase often.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.core.events.lifecycle.events.client import ClientRoundEvent
# verified: packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py:177
```

`CompletionUsage` and `TraceContext` are already referenced by
`parrot/clients/base.py` — import them from the same source that module uses
(verify before writing the import line).

### Existing Signatures to Use — the FEAT-397 emitter trio

```python
# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):
    def _emit_before_call(self, *, client_name: str, model: str,
                          temperature: "Optional[float]" = None,
                          system_prompt: "Optional[str]" = None,
                          has_tools: bool = False,
                          parent_trace: "Optional[TraceContext]" = None,
                          ) -> "TraceContext": ...                     # line 431
        # "The returned TraceContext must be stored by the caller and passed to
        #  _emit_after_call or _emit_failed_call."

    def _emit_round_event(self, tc: "TraceContext", *, client_name: str,
                          model: str, round_number: int,
                          usage: "Optional[CompletionUsage]",
                          raw_usage: "Optional[dict]",
                          tool_calls: "Sequence[str]",
                          duration_ms: float) -> None: ...             # line 488
        # round_number is 1-INDEXED within the call (docstring line 518)
        # usage=None is legal — flat token fields become None (lines 519-524)
        # short-circuits when neither self.events nor the global registry
        # has ClientRoundEvent subscribers (lines 531-537) — zero hot-path cost
        # extracts: usage.prompt_tokens -> input_tokens,
        #           usage.completion_tokens -> output_tokens,
        #           usage.total_tokens -> total_tokens   (lines 544-546)

    async def _emit_after_call(self, tc: "TraceContext", *, client_name: str,
                               model: str, duration_ms: float,
                               input_tokens: "Optional[int]" = None,
                               output_tokens: "Optional[int]" = None,
                               finish_reason: "Optional[str]" = None,
                               ) -> None: ...                          # line 564
        # NOTE: this one is ASYNC; the other two are sync.
        # "Must NOT be called when _emit_failed_call was called."
```

### The loop to instrument

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
async def _dispatch_loop(self, *, brief, profile, output_model, run_id,
                         node_id, stream_key, cwd) -> T:               # line 172
    client = self._create_client(profile)
    await self._ensure_client_ready(client)
    model = self._resolve_model(profile, client)
    messages = self._initial_messages(profile, brief, output_model)
    tools = self._tool_schemas(output_model)
    args = self._completion_args(profile, tools)

    for turn_index in range(profile.max_turns):                        # line 190
        response = await self._chat_completion(client=client, model=model,
                                               messages=messages, args=args)
        message = self._response_message(response)
        content = self._message_content(message)
        tool_calls = self._message_tool_calls(message)
        ...
        if not tool_calls:
            result = self._validate_text_output(content, output_model)
            ... # publishes dispatch.completed
            return result
        ...
        for call in tool_calls:
            tool_name = self._tool_call_name(call)   # ← the names for the event
            ...
```

Existing helpers available on the class: `_response_message`,
`_message_content`, `_message_tool_calls`, `_tool_call_name`,
`_tool_call_id`, `_tool_call_arguments`, `_resolve_model`.

### Does NOT Exist

- ~~Usage extraction anywhere in `LLMCodeDispatcher`~~ — the loop reads no token counts today
- ~~`_emit_round_event` being called outside a client's `ask()`~~ — this is the first such caller; it is supported (verified above) but new
- ~~Round accumulation in `BedrockConverseBase` / `NovaClient`~~ — FEAT-404, out of scope
- ~~A `usage` attribute on the `_chat_completion` response guaranteed to exist~~ — providers differ; extract defensively and pass `usage=None` when absent (legal per the docstring)
- ~~`AIMessage` in this path~~ — the dispatcher works with raw provider responses, not `AIMessage`; `total_usage()` is not available here
- ~~A summing helper in the dispatcher~~ — **do not add one**; [R4] forbids it

---

## Implementation Notes

### Pattern to Follow

`clients/claude.py` is the reference caller of the trio
(`clients/claude.py:566` accumulate, `:641` emit round, `:715` final usage) —
**follow its call shape, but NOT its accumulation**, which is the client's job.

```python
tc = client._emit_before_call(client_name=..., model=model, has_tools=True)
try:
    for turn_index in range(profile.max_turns):
        started = time.perf_counter()
        response = await self._chat_completion(...)
        duration_ms = (time.perf_counter() - started) * 1000
        usage, raw_usage = self._extract_usage(response)      # new tiny helper
        client._emit_round_event(
            tc, client_name=..., model=model,
            round_number=turn_index + 1,      # 1-INDEXED
            usage=usage, raw_usage=raw_usage,
            tool_calls=[...], duration_ms=duration_ms,
        )
        ...
finally:
    await client._emit_after_call(tc, client_name=..., model=model,
                                  duration_ms=total_ms, ...)
```

### Key Constraints

- **No accumulation.** If you find yourself writing `total += usage...`, stop —
  that belongs to FEAT-397's client layer, not here.
- `round_number` is **1-indexed** (`turn_index + 1`).
- `usage=None` is legal and must not crash.
- Guard the emitter calls so a client without them (a test double, a
  non-`AbstractClient`) does not break dispatch — use `getattr`/`callable`
  checks in the same spirit as `_chat_completion` does at `llm.py:376-379`.
- These are underscore-private methods. That is a deliberate, documented choice
  — the dispatcher already couples to `client._chat_completion` at the same
  level of intimacy. Add a comment saying so.
- Keep the diff small; this file is hot.

### References in Codebase

- `packages/ai-parrot/src/parrot/clients/claude.py:535,566,640-641,715` — the reference caller
- `packages/ai-parrot/src/parrot/clients/grok.py:342`, `gpt.py:1028` — two more callers
- `packages/ai-parrot/src/parrot/clients/base.py:431,488,564` — the trio itself
- `sdd/specs/tokens-observability.spec.md` — FEAT-397, the contract being extended

---

## Acceptance Criteria

- [ ] A 3-turn dispatch emits exactly 3 `ClientRoundEvent`s with `round_number` 1, 2, 3
- [ ] Each event carries only **that round's** usage — no running totals
- [ ] The dispatcher contains **no** token-summing logic (grep the diff)
- [ ] Events are emitted for a non-Nova backend too (nvidia/zai path) — [R8]
- [ ] A response with no usage yields an event with `usage=None`, no crash
- [ ] A client lacking the emitter methods does not break dispatch
- [ ] No events and no measurable overhead when nothing subscribes
      (`has_subscribers` short-circuit)
- [ ] `_emit_after_call` is awaited exactly once per dispatch
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_dispatch_round_events.py -v` passes
- [ ] Existing dispatcher tests still pass (`test_dispatcher.py`, `test_dispatch_telemetry.py`)
- [ ] `ruff check` + `mypy` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_dispatch_round_events.py
import pytest
from parrot.core.events.lifecycle.events.client import ClientRoundEvent


@pytest.fixture
def collector():
    """Subscribe to ClientRoundEvent on the GLOBAL registry and record events."""
    events = []
    # register on get_global_registry(); yield events; unregister
    yield events


class TestRoundEvents:
    async def test_one_event_per_turn(self, collector, three_turn_dispatch):
        await three_turn_dispatch()
        assert [e.round_number for e in collector] == [1, 2, 3]

    async def test_events_carry_per_round_usage_not_totals(self, collector,
                                                           three_turn_dispatch):
        """Each event is one round — the dispatcher must not accumulate."""
        await three_turn_dispatch()
        assert all(e.input_tokens == 10 for e in collector)   # not 10, 20, 30

    async def test_missing_usage_is_tolerated(self, collector, dispatch_without_usage):
        await dispatch_without_usage()
        assert collector and collector[0].input_tokens is None

    async def test_client_without_emitters_does_not_break(self, dispatch_plain_client):
        """A test double lacking _emit_* must still dispatch successfully."""
        assert await dispatch_plain_client() is not None

    async def test_no_events_when_no_subscribers(self, three_turn_dispatch):
        """has_subscribers short-circuit — zero cost on the hot path."""

    async def test_non_nova_backend_also_emits(self, collector, nvidia_dispatch):
        """[R8]: coverage is backend-independent."""
        await nvidia_dispatch()
        assert collector


class TestNoAccumulation:
    def test_source_contains_no_summing(self):
        """Guard rail: the dispatcher must not re-implement FEAT-397."""
        from pathlib import Path
        src = Path("packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py").read_text()
        assert "total_usage" not in src
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (Module 6, §1 Non-Goals, §7 "Private-method coupling")
2. **Also read** `sdd/specs/tokens-observability.spec.md` (FEAT-397) — this task extends its contract
3. **Check dependencies** — none; this task is independent of the Nova work
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm the three emitter signatures at `clients/base.py:431,488,564`
   - Confirm `_dispatch_loop`'s structure and the turn loop at `llm.py:172,190`
   - Read `clients/claude.py:640-641` to see a real call site
   - If anything has changed, update the contract FIRST, then implement
5. **Update status** in `sdd/tasks/index/novaclient-dev-loop.json` → `"in-progress"`
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2089-dispatcher-round-events.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
