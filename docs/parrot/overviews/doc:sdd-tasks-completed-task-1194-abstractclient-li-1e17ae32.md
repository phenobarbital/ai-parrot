---
type: Wiki Overview
title: 'TASK-1194: Integrate EventEmitterMixin into AbstractClient'
id: doc:sdd-tasks-completed-task-1194-abstractclient-lifecycle-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Module 13 of the spec. `AbstractClient` gains `self.events: EventRegistry`
  and emits `BeforeClientCallEvent` / `AfterClientCallEvent` / `ClientCallFailedEvent`
  around its `ask` and `ask_stream` methods, plus `ClientStreamChunkEvent` per streamed
  chunk. Because `ask` / `ask_stream'
relates_to:
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.mixin
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
---

# TASK-1194: Integrate EventEmitterMixin into AbstractClient

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-1184, TASK-1189
**Assigned-to**: unassigned
**Parallel**: yes (touches only `parrot/clients/` — no overlap with TASK-1193 or TASK-1195)

---

## Context

Module 13 of the spec. `AbstractClient` gains `self.events: EventRegistry` and emits `BeforeClientCallEvent` / `AfterClientCallEvent` / `ClientCallFailedEvent` around its `ask` and `ask_stream` methods, plus `ClientStreamChunkEvent` per streamed chunk. Because `ask` / `ask_stream` are `@abstractmethod` and implemented in concrete subclasses (`ClaudeClient`, `OpenAIClient`, `GoogleClient`, etc.), the spec gives the implementer a choice of two patterns — see Implementation Notes.

Spec section: §3 Module 13.

---

## Scope

- Add `EventEmitterMixin` to `AbstractClient` and call `_init_events()` in `__init__`.
- Add helper methods on the base for use by concrete subclasses:
  - `_emit_before_call(client_name, model, ..., trace_context=None) -> TraceContext` (returns the child trace_context to thread through the call).
  - `_emit_after_call(trace_context, duration_ms, input_tokens, output_tokens, finish_reason)`.
  - `_emit_failed_call(trace_context, duration_ms, error)`.
  - `_emit_stream_chunk(trace_context, chunk_index, chunk_size_bytes)`.
- Update every concrete subclass under `packages/ai-parrot/src/parrot/clients/` to call these helpers around `ask` and `ask_stream`.
- Performance: short-circuit `_emit_stream_chunk` when there are zero subscribers (use `registry.has_subscribers(ClientStreamChunkEvent)` — add the helper to `EventRegistry` if not already present).
- Add unit tests covering the success path (Before + After), the failure path (Before + Failed, NO After), and the stream-chunk path (1000 chunks → 0 bus calls when no opt-in).

**NOT in scope**: `AbstractBot` integration (TASK-1193), `AbstractTool` integration (TASK-1195), YAML loader (TASK-1196).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | Mixin + emission helpers. |
| `packages/ai-parrot/src/parrot/clients/<concrete>.py` (each one) | MODIFY | Wrap `ask` / `ask_stream` with the helpers. Implementer enumerates the concrete files via `grep -l "class.*AbstractClient" packages/ai-parrot/src/parrot/clients/`. |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py` | MODIFY | Add `has_subscribers(event_type)` short-circuit helper. |
| `packages/ai-parrot/tests/unit/clients/test_client_lifecycle.py` | CREATE | Before/After/Failed + stream-chunk tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# In packages/ai-parrot/src/parrot/clients/base.py
import hashlib
import time
from typing import Optional

from parrot.core.events.lifecycle.mixin import EventEmitterMixin               # TASK-1189
from parrot.core.events.lifecycle.trace import TraceContext                    # TASK-1182
from parrot.core.events.lifecycle.events import (                              # TASK-1184
    BeforeClientCallEvent, AfterClientCallEvent,
    ClientCallFailedEvent, ClientStreamChunkEvent,
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/base.py — VERIFIED
class AbstractClient(ABC):
    def __init__(
        self,
        conversation_memory: Optional[ConversationMemory] = None,
        preset: Optional[str] = None,
        tools: Optional[List[Union[str, AbstractTool]]] = None,
        use_tools: bool = False,
        debug: bool = True,
        tool_manager: Optional[ToolManager] = None,
        **kwargs,
    ): ...                                                # line 263

    @abstractmethod
    async def ask(
        self, prompt: str, model: str, max_tokens: int = 4096,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        ...,
    ) -> MessageResponse: ...                             # line 1286

    @abstractmethod
    async def ask_stream(
        self, prompt: str, model: str = None, max_tokens: int = 4096,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        ...,
    ) -> AsyncIterator[Union[str, AIMessage]]: ...        # line 1324
```

### Concrete client subclasses to update (enumerate via grep first)

```bash
grep -l "class .*(AbstractClient)" packages/ai-parrot/src/parrot/clients/*.py
# Likely candidates: claude.py, gpt.py (OpenAI), google.py, groq.py, etc.
```

The implementer must enumerate the exact list at the start of the task and apply emission helpers uniformly.

### Does NOT Exist

- ~~`AbstractClient.events` before this task~~ — being added.
- ~~`MessageResponse.tokens.input` / `output`~~ — token-usage location varies per provider; the implementer reads each provider's response shape to pull tokens for `AfterClientCallEvent`.

---

## Implementation Notes

### Pattern: thin helpers on the base

```python
# In AbstractClient
def _system_prompt_hash(self, system_prompt: Optional[str]) -> str:
    return hashlib.sha256((system_prompt or "").encode()).hexdigest() if system_prompt else ""

def _emit_before_call(
    self,
    *,
    client_name: str,
    model: str,
    temperature: Optional[float],
    system_prompt: Optional[str],
    has_tools: bool,
    parent_trace: Optional[TraceContext] = None,
) -> TraceContext:
    tc = parent_trace.child() if parent_trace else TraceContext.new_root()
    self.events.emit_nowait(BeforeClientCallEvent(
        trace_context=tc,
        client_name=client_name,
        model=model,
        temperature=temperature,
        system_prompt_hash=self._system_prompt_hash(system_prompt),
        has_tools=has_tools,
        source_type="client", source_name=client_name,
    ))
    return tc

async def _emit_after_call(self, tc, *, client_name, model, duration_ms,
                            input_tokens, output_tokens, finish_reason) -> None:
    await self.events.emit(AfterClientCallEvent(
        trace_context=tc, client_name=client_name, model=model,
        duration_ms=duration_ms, input_tokens=input_tokens,
        output_tokens=output_tokens, finish_reason=finish_reason,
        source_type="client", source_name=client_name,
    ))

async def _emit_failed_call(self, tc, *, client_name, model, duration_ms, exc) -> None:
    await self.events.emit(ClientCallFailedEvent(
        trace_context=tc, client_name=client_name, model=model,
        duration_ms=duration_ms,
        error_type=type(exc).__name__, error_message=str(exc),
        source_type="client", source_name=client_name,
    ))
```

### Concrete `ask` wrapper pattern

```python
async def ask(self, prompt: str, model: str, **kw) -> MessageResponse:
    tc = self._emit_before_call(
        client_name="claude", model=model,
        temperature=kw.get("temperature"), system_prompt=kw.get("system_prompt"),
        has_tools=bool(kw.get("tools")),
        parent_trace=kw.pop("_trace_context", None),
    )
    t0 = time.perf_counter()
    try:
        resp = await self._do_ask_implementation(prompt, model, **kw)
    except Exception as exc:
        dur = (time.perf_counter() - t0) * 1000
        await self._emit_failed_call(tc, client_name="claude", model=model, duration_ms=dur, exc=exc)
        raise
    dur = (time.perf_counter() - t0) * 1000
    await self._emit_after_call(
        tc, client_name="claude", model=model, duration_ms=dur,
        input_tokens=resp.usage.input_tokens if resp.usage else None,
        output_tokens=resp.usage.output_tokens if resp.usage else None,
        finish_reason=resp.stop_reason if hasattr(resp, "stop_reason") else None,
    )
    return resp
```

The hidden `_trace_context` kwarg is the channel for `AbstractBot` (TASK-1193) to pass its current invocation's trace down to the client without changing the public `ask` signature in incompatible ways.

### Stream-chunk hot path

```python
async def ask_stream(self, prompt: str, **kw):
    tc = self._emit_before_call(...)
    has_chunk_subs = self.events.has_subscribers(ClientStreamChunkEvent)
    t0 = time.perf_counter()
    chunk_idx = 0
    try:
        async for chunk in self._do_ask_stream_implementation(prompt, **kw):
            if has_chunk_subs:
                await self.events.emit(ClientStreamChunkEvent(
                    trace_context=tc, client_name=..., model=...,
                    chunk_index=chunk_idx,
                    chunk_size_bytes=len(chunk.encode("utf-8")) if isinstance(chunk, str) else 0,
                    source_type="client", source_name=...,
                ))
                chunk_idx += 1
            yield chunk
    except Exception as exc:
        ...
        raise
    # After successful stream
    await self._emit_after_call(...)
```

### `has_subscribers` helper on EventRegistry

```python
def has_subscribers(self, event_type: Type[E]) -> bool:
    return any(
        issubclass(event_type, s.event_type) or issubclass(s.event_type, event_type)
        for s in self._subscriptions
    )
```

The bidirectional `issubclass` check is needed because a subscriber to `LifecycleEvent` covers `ClientStreamChunkEvent`, and a subscriber to `ClientStreamChunkEvent` itself also counts.

### Key Constraints

- Do NOT introduce a public `trace_context` kwarg on `ask` / `ask_stream` (that's the `AbstractBot` public API in TASK-1193). Use the private `_trace_context` channel.
- Use `time.perf_counter()` for duration measurements.
- Never call `event.to_dict()` in the chunk hot path — the registry does it only if `forward_to_bus=True`.
- Short-circuit chunk emission when there are no subscribers — keeps the streaming hot path lean.

---

## Acceptance Criteria

- [ ] `AbstractClient` exposes `self.events: EventRegistry`.
- [ ] Every concrete client emits `BeforeClientCallEvent` then either `AfterClientCallEvent` (success) or `ClientCallFailedEvent` (exception) — never both.
- [ ] `system_prompt_hash` is the SHA-256 hex of the system prompt; never the prompt itself.
- [ ] `ask_stream` emits one `ClientStreamChunkEvent` per chunk when there are subscribers, zero otherwise.
- [ ] `_trace_context` kwarg, if provided, becomes the parent of the client's child trace.
- [ ] 1000-chunk streaming + no `forward_to_bus` → zero `EventBus.emit` calls (existing test in TASK-1186 must still pass; the new client tests add the concrete-client coverage).
- [ ] Existing client test suite continues to pass (`pytest packages/ai-parrot/tests/unit/clients/`).
- [ ] New tests pass: `pytest packages/ai-parrot/tests/unit/clients/test_client_lifecycle.py -v`.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/clients/test_client_lifecycle.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.core.events.lifecycle.global_registry import scope
from parrot.core.events.lifecycle.events import (
    BeforeClientCallEvent, AfterClientCallEvent,
    ClientCallFailedEvent, ClientStreamChunkEvent,
)
from parrot.core.events.lifecycle.trace import TraceContext


class TestClientLifecycle:
    """The implementer should adapt to whichever client subclass is simplest
    to mock — e.g., a test-only subclass that overrides _do_ask_implementation."""

    @pytest.mark.asyncio
    async def test_success_emits_before_and_after(self):
        # Build a fake concrete client subclass; emit subscriber captures events.
        ...

    @pytest.mark.asyncio
    async def test_failure_emits_failed_not_after(self):
        ...

    @pytest.mark.asyncio
    async def test_trace_context_threaded(self):
        parent = TraceContext.new_root()
        # call client.ask(..., _trace_context=parent)
        # assert: emitted Before event has tc.parent_span_id == parent.span_id
        ...

    @pytest.mark.asyncio
    async def test_stream_chunk_per_chunk(self):
        ...
```

---

## Agent Instructions

1. Read spec §3 Module 13 and the Module 13 caveat in §3.
2. Confirm TASK-1184, TASK-1189 are in `sdd/tasks/completed/`.
3. `grep -l "class .*(AbstractClient)" packages/ai-parrot/src/parrot/clients/*.py` — list every concrete client.
4. Implement the base helpers + `has_subscribers`, then wrap each concrete client's `ask` / `ask_stream`.
5. Run client test suite, fix any regressions.
6. Update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-15
**Notes**:
- EventEmitterMixin added to AbstractClient MRO; _init_events(forward_to_global=False) called in __init__
- Emission helpers added to base: _system_prompt_hash (SHA-256 privacy), _emit_before_call (returns child TraceContext), _emit_after_call, _emit_failed_call
- has_subscribers(event_type) bidirectional-issubclass helper added to EventRegistry for hot-path short-circuit
- Concrete clients instrumented: AnthropicClient, OpenAIClient, GroqClient, GrokClient, GoogleGenAIClient, TransformersClient, Gemma4Client, ClaudeAgentClient, GeminiLiveClient
- hf.py and gemma4.py ask_stream delegate to self.ask() so no separate stream instrumentation needed
- Per-chunk ClientStreamChunkEvent emission with has_subscribers() short-circuit
- 12 unit tests all pass

**Deviations from spec**: none
