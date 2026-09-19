# TASK-3478: OpenAIBaseClient.invoke() lifecycle telemetry

**Feature**: FEAT-579 — Lifecycle Telemetry for `invoke()` (JevClient + OpenAIBaseClient)
**Spec**: `sdd/specs/invoke-telemetry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of the spec. `OpenAIBaseClient.ask()` already calls the
three `AbstractClient` lifecycle hooks (`openai_base.py:797-805` and
`1034-1043`), but `invoke()` calls none of them. Because OpenAIClient,
OpenRouter, Moonshot, Nvidia, Meta, BedrockMantle and GeminiOpenAICompat all
inherit `invoke()` unchanged, one fix covers all seven providers.

`invoke()` is harder than `ask()` because its dispatch block has **three** exit
paths (spec §2): normal, budget-finalize, and budget-partial — and the partial
path `return`s from inside an `except`. Exactly one terminal event must be
emitted on each.

---

## Scope

- Instrument the dispatch block of `OpenAIBaseClient.invoke()`
  (`openai_base.py:1600-1671`) with `_emit_before_call` /
  `_emit_after_call` / `_emit_failed_call_safe`:
  - **before**: right after the `_BUDGET_CALL_CTX.set(...)` line, once.
  - **after**: on the normal path (`finish_reason` from
    `_extract_finish_reason(response)`), on the finalize path
    (`finish_reason="budget_exhausted"`), and on the partial path
    (`input_tokens=None`, `output_tokens=None`,
    `finish_reason="budget_exhausted"`).
  - **failed**: on any exception escaping the dispatch block before the after
    event, including `BudgetError` subclasses and a non-`BudgetExhausted`
    failure inside the finalize handler.
- Guard with a local `_lc_terminal` flag so no call can emit two terminal
  events (spec §7 Known Risks).
- Reuse the `CompletionUsage` computed for the after event as the `usage` passed
  to `_build_invoke_result` instead of computing it twice.
- Create `packages/ai-parrot/tests/unit/clients/test_invoke_telemetry.py` with
  the five M2 tests from spec §4 plus the M2 half of
  `test_invoke_exactly_one_terminal_event`.

**NOT in scope**: `ask()` / `ask_stream()` (already instrumented); `JevClient`
(TASK-3477); `GroqClient`, `LocalLLMClient`, `ZaiClient` — they **override**
`invoke()` and deliberately stay uninstrumented (spec §1 Non-Goals); any change
to `clients/base.py`, `InvokeResult`, the event models, or the `invoke()`
signature; per-round `ClientRoundEvent`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/openai_base.py` | MODIFY | Instrument the dispatch block of `invoke()` |
| `packages/ai-parrot/tests/unit/clients/test_invoke_telemetry.py` | CREATE | M2 lifecycle-emission unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against the working tree on 2026-09-19 (branch `dev`).
> Use these exact names and signatures. Verify before adding anything not listed.

### Verified Imports
```python
# packages/ai-parrot/src/parrot/clients/openai_base.py — ALREADY imported, reuse as is
import time                                                                     # verified: openai_base.py:26
import uuid                                                                     # already used at openai_base.py:1606
from ..core.exceptions import BudgetAccountingError, BudgetError, BudgetExhausted  # verified: openai_base.py:41
# CompletionUsage, InvokeResult, current_budget_scope, _BUDGET_CALL_CTX — all already in scope

# packages/ai-parrot/tests/unit/clients/test_invoke_telemetry.py — NEW file
import asyncio
from unittest.mock import MagicMock
import pytest
from parrot.core.events.lifecycle.events import (                               # verified: clients/base.py:50-56 (same import)
    AfterClientCallEvent,
    BeforeClientCallEvent,
    ClientCallFailedEvent,
)
from parrot.clients.openai_base import OpenAIBaseClient                         # verified: openai_base.py:73
from parrot.exceptions import InvokeError
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):                                   # line 235
    client_name: str = "generic"                                                # line 243
    def _emit_before_call(self, *, client_name: str, model: str,                # line 559 — KEYWORD-ONLY
        temperature: Optional[float] = None, system_prompt: Optional[str] = None,
        has_tools: bool = False, parent_trace: Optional[TraceContext] = None) -> TraceContext: ...
    async def _emit_after_call(self, tc: TraceContext, *, client_name: str,     # line 696 — tc POSITIONAL, rest KEYWORD-ONLY
        model: str, duration_ms: float, input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None, finish_reason: Optional[str] = None) -> None: ...
    async def _emit_failed_call(self, tc, *, client_name, model, duration_ms, exc) -> None:  # line 750 — NO token fields
    async def _emit_failed_call_safe(self, tc: TraceContext, client_name: str,  # line 790 — ALL POSITIONAL
        model: str, t0: float, exc: Exception) -> None: ...
    @staticmethod
    def _extract_finish_reason(response: Any) -> Any:                           # line 2245 — DEFINED IN base.py, not openai_base.py
    def _build_invoke_result(self, output, output_type, model, usage, raw_response=None) -> InvokeResult:  # line 2158
    def _handle_invoke_error(self, exception: Exception) -> InvokeError:        # line 2186

# packages/ai-parrot/src/parrot/clients/openai_base.py
class OpenAIBaseClient(AbstractClient):                                         # line 73
    async def _finalize_budgeted_chat(self, messages, *, model_str, args,       # line 286
        all_tool_calls, pending_tool_calls, partial_text, stream) -> Any: ...
    async def invoke(...) -> InvokeResult:                                      # line 1526 — SIGNATURE UNCHANGED
    #   """Lightweight stateless invocation ..."""                              1539
    #   outer `try:`                                                            1571
    #   resolved_prompt / config / resolved_model / max_tokens                  1572-1575
    #   messages = [...]                                                        1577-1580
    #   kwargs: dict[str, Any] = {"max_tokens": ..., "temperature": ...}        1582-1585
    #   kwargs["response_format"] / kwargs["tools"] (only when use_tools)       1587-1594
    #   if not self.client: raise RuntimeError("... not initialised ...")       1597-1598
    #   _budget_forced = False                                                  1600
    #   _budget_call_id = str(uuid.uuid4())                                     1606
    #   _BUDGET_CALL_CTX.set({"call_id": ..., "round_number": 1, "phase": "work"})  1607
    #   try: response = await self._chat_completion(model=resolved_model,
    #        messages=messages, use_tools=True, **kwargs)                       1608-1611
    #   except BudgetExhausted: -> _finalize_budgeted_chat(...) ; _budget_forced = True  1612-1625
    #       except BudgetExhausted as bx2: -> partial InvokeResult(usage=CompletionUsage())  1626-1637
    #       return invoke_result   (PARTIAL PATH — returns from inside an except) 1638
    #   raw_text = response.choices[0].message.content or ""                    1640
    #   _raise_if_truncated / custom_parser / _parse_structured_output          1643-1653
    #   usage = CompletionUsage.from_openai(response.usage)                     1660
    #   invoke_result = self._build_invoke_result(...)                          1661-1667
    #   return invoke_result                                                    1671
    #   except BudgetError: raise / except InvokeError: raise
    #       / except Exception as exc: raise self._handle_invoke_error(exc)     1672-1677
    # ask() telemetry reference — COPY THIS SHAPE:
    #   _lc_tc = self._emit_before_call(client_name=self.client_name, model=model_str,
    #       temperature=..., system_prompt=system_prompt, has_tools=bool(_use_tools),
    #       parent_trace=None)                                                  797-805
    #   _lc_t0 = time.perf_counter()                                            806
    #   await self._emit_after_call(_lc_tc, client_name=self.client_name, model=model_str,
    #       duration_ms=(time.perf_counter() - _lc_t0) * 1000, input_tokens=...,
    #       output_tokens=..., finish_reason=...)                               1034-1042
    #   ask() sets ai_message.stop_reason = "budget_exhausted" on forced termination  1030

# packages/ai-parrot/tests/unit/clients/test_client_failed_call_emission.py — pattern to COPY, not import
def _make_openai_stub(*, raise_on_completion: Exception | None = None):         # line 30
class _Stub(OpenAIBaseClient):                                                  # line 33
    client_name = "stub-openai"; client_type = "stub"; model = "stub-model"     # 34-36
    async def get_client(self): return MagicMock()                              # 41-42
    async def _ensure_client(self): pass                                        # 44-45
    async def invoke(self, *args, **kwargs): raise NotImplementedError("stub")  # 47-48 <-- MUST NOT BE COPIED
    async def resume(self, *args, **kwargs): raise NotImplementedError("stub")  # 50-51
    async def _chat_completion(self, **kwargs): ...                             # 53-70
def _capture():  # -> (captured: list, async cb)                                # line 80
```

### Does NOT Exist
- ~~`AbstractClient._emit_invoke_*` / an instrumented-invoke decorator~~ — there
  is no invoke-specific hook, and spec §1 Non-Goals forbids adding one.
  `packages/ai-parrot/src/parrot/clients/base.py` must NOT be modified.
- ~~`_chat_completion` emitting lifecycle events~~ — it emits none; emission
  lives in the calling method.
- ~~`OpenAIBaseClient._extract_finish_reason`~~ — it is **not** defined in
  `openai_base.py`; it is a `@staticmethod` inherited from `base.py:2245`. Call
  it as `self._extract_finish_reason(response)` (as `invoke` already does at
  line 1645), do not redefine it.
- ~~`InvokeResult.finish_reason`~~ — no such field. Take the finish reason from
  the response.
- ~~`ClientCallFailedEvent.input_tokens` / `.output_tokens`~~ — the failed event
  carries no token fields, which is exactly why the partial path emits an
  **After** event (with `None` tokens) rather than a Failed one.
- ~~reusing `_Stub` from `test_client_failed_call_emission.py`~~ — that stub
  overrides `invoke()` with `raise NotImplementedError`, so it would not
  exercise the real method at all. The new file needs its own stub that does
  **not** override `invoke()`.
- ~~`GroqClient` / `LocalLLMClient` / `ZaiClient` inheriting this fix~~ — all
  three override `invoke()`; do not write a test that asserts every
  `OpenAIBaseClient` subclass is instrumented.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/clients/openai_base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/clients/test_invoke_telemetry.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/openai_base.py#OpenAIBaseClient",
    "sym:packages/ai-parrot/src/parrot/clients/openai_base.py#OpenAIBaseClient.invoke",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._emit_before_call",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._emit_after_call",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._emit_failed_call_safe",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._extract_finish_reason",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._build_invoke_result"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **The existing except-chain at 1672-1677 must be byte-identical afterwards.**
  All emission happens strictly inside the outer `try`; nothing is added to
  `except BudgetError: / except InvokeError: / except Exception:`.
- **`_emit_failed_call_safe` takes positional args** `(tc, client_name, model,
  t0, exc)`. `_emit_after_call` takes `tc` positionally and the rest
  keyword-only.
- **An exception raised inside an `except` block is NOT caught by a sibling
  handler of the same `try`.** That is why a failure inside the
  `except BudgetExhausted:` handler (e.g. `_finalize_budgeted_chat` raising
  something that is not `BudgetExhausted`) needs the *outer* lifecycle wrapper
  in the blueprint, not another sibling `except`.
- Set `_lc_terminal = True` **before** each `await self._emit_after_call(...)`,
  not after — so that even a failure inside the emission itself cannot produce a
  second terminal event.
- The before/failed events use `model=resolved_model`; the after event also uses
  `resolved_model` here (spec §2 field table) — unlike Jev, which uses
  `response.model`.

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/openai_base.py:797-806, 1034-1043` —
  the `ask()` telemetry block this task mirrors.
- `packages/ai-parrot/tests/unit/clients/test_client_failed_call_emission.py` —
  stub shape, `_capture()`, and the `await asyncio.sleep(0.05)` drain.

### Environment gotchas (verified 2026-09-19)
- Do **not** combine `tests/` and `packages/ai-parrot/tests/` in one pytest
  invocation — it aborts with
  `_pytest.pathlib.ImportPathMismatchError: ('tests.conftest', ...)`. The spec's
  §5 criterion that lists both roots in a single command cannot be run as
  written; use the two separate commands in **Validation Commands** below.
- Baseline on `dev`: `packages/ai-parrot/tests/unit/clients/test_client_failed_call_emission.py`
  is `4 passed`.

---

## Implementation Blueprint

### Steps (in order)
1. Emit the before-event immediately after `_BUDGET_CALL_CTX.set(...)` — *why*:
   everything earlier (model/prompt/max_tokens resolution, the "not initialised"
   check) can fail without contacting the provider and must emit nothing, which
   is how `ask()` behaves too.
2. Wrap the whole existing dispatch block in an outer `try: ... except Exception`
   that emits the failed event and re-raises bare — *why*: a bare `raise` leaves
   the exception untouched so the pre-existing
   `except BudgetError/InvokeError/Exception` chain at 1672-1677 still produces
   exactly the same type and message it does today.
3. Emit the after-event on the partial path **before** its `return
   invoke_result` — *why*: that path returns from inside an `except`, so there is
   no later point at which it could be emitted.
4. Emit the after-event for the normal and finalize paths right after the
   wrapper closes and **before** `raw_text = ...` — *why*: spec §2 decides the
   terminal event describes the provider call, not the parse; tokens were billed
   and must reach the cost recorders even if parsing then fails.
5. Replace the `CompletionUsage.from_openai(response.usage)` at line 1660 with
   the object bound in step 4 — *why*: spec §7 requires it be computed once so
   the event and the `InvokeResult` cannot disagree.
6. Write the tests last, with a stub that does **not** override `invoke()` —
   *why*: the existing `_Stub` overrides it with `NotImplementedError` and would
   silently test nothing.

### `packages/ai-parrot/src/parrot/clients/openai_base.py` (MODIFY — block A of 3)
```python
# occurrences: 1 (verified: grep -c 'except BudgetExhausted as bx2:' packages/ai-parrot/src/parrot/clients/openai_base.py)
# REPLACE lines 1600-1638 — from `            _budget_forced = False` (verified:
# openai_base.py:1600) through `                    return invoke_result`
# (verified: openai_base.py:1638) — with the block below. The FEAT-550 comment
# at 1601-1605 and the `_finalize_budgeted_chat(...)` argument list at 1617-1624
# are reproduced unchanged; re-read them before writing and copy verbatim.
            _budget_forced = False
            # FEAT-550: a stable call_id across the sole dispatch and any
            # follow-on finalization attempt — without this, `reserve()`'s
            # phase="final" owner check mints a fresh random call_id on each
            # `_BUDGET_CALL_CTX.get()` (empty default) and unconditionally
            # rejects the finalize dispatch as a foreign owner.
            _budget_call_id = str(uuid.uuid4())
            _BUDGET_CALL_CTX.set({"call_id": _budget_call_id, "round_number": 1, "phase": "work"})
            _lc_tc = self._emit_before_call(
                client_name=self.client_name,
                model=resolved_model,
                temperature=temperature,
                system_prompt=resolved_prompt,
                has_tools="tools" in kwargs,
                parent_trace=None,
            )
            _lc_t0 = time.perf_counter()
            _lc_terminal = False
            try:
                try:
                    response = await self._chat_completion(
                        model=resolved_model, messages=messages, use_tools=True, **kwargs
                    )
                except BudgetExhausted:
                    # invoke() is a single-shot call: the frame is the payload
                    # without tools; owner finalization still applies (spec §2.3).
                    try:
                        # FILL IN: copy the `response = await self._finalize_budgeted_chat(...)`
                        # call verbatim from openai_base.py:1617-1624, then
                        # `_budget_forced = True` — bounded by "the existing
                        # behaviour is unchanged"; do not re-derive its arguments.
                        raise NotImplementedError
                    except BudgetExhausted as bx2:
                        # FILL IN: copy lines 1627-1637 verbatim (_scope, partial,
                        # InvokeResult(...), budget_report) — bounded by AC-4.
                        raise NotImplementedError
                        _lc_terminal = True
                        await self._emit_after_call(
                            _lc_tc,
                            client_name=self.client_name,
                            model=resolved_model,
                            duration_ms=(time.perf_counter() - _lc_t0) * 1000,
                            input_tokens=None,
                            output_tokens=None,
                            finish_reason="budget_exhausted",
                        )
                        return invoke_result
            except Exception as exc:  # noqa: BLE001 — re-raised untouched below
                if not _lc_terminal:
                    _lc_terminal = True
                    await self._emit_failed_call_safe(_lc_tc, self.client_name, resolved_model, _lc_t0, exc)
                raise
```
**Why this shape**: the outer `try` is the only construct that catches a failure
raised *inside* the `except BudgetExhausted:` handler (Python does not route
that to a sibling handler), which is the "finalize path itself blows up" case
the spec's failed-event row calls out. `raise` with no argument re-raises the
identical exception object, so the untouched chain at 1672-1677 still decides
the final type — AC-5. `_lc_terminal` is set before every emission so no path
can produce two terminal events. **Must NOT change**: the `_budget_call_id` /
`_BUDGET_CALL_CTX` lines, the `_chat_completion` arguments, the
`_finalize_budgeted_chat` arguments, or the partial `InvokeResult` construction.

### `packages/ai-parrot/src/parrot/clients/openai_base.py` (MODIFY — block B of 3)
```python
# occurrences: 1 (verified: grep -c 'raw_text = response.choices\[0\].message.content or ""' packages/ai-parrot/src/parrot/clients/openai_base.py)
# BEFORE — insert above `            raw_text = response.choices[0].message.content or ""` (verified: openai_base.py:1640)
            _lc_usage = CompletionUsage.from_openai(response.usage)
            _lc_terminal = True
            await self._emit_after_call(
                _lc_tc,
                client_name=self.client_name,
                model=resolved_model,
                duration_ms=(time.perf_counter() - _lc_t0) * 1000,
                input_tokens=_lc_usage.prompt_tokens,
                output_tokens=_lc_usage.completion_tokens,
                finish_reason="budget_exhausted" if _budget_forced else self._extract_finish_reason(response),
            )
```
**Why**: this is the single after-emission covering both the normal and the
finalize path, placed before any parsing so a `TruncatedResponseError` from
`_raise_if_truncated` (1645) cannot retract already-billed tokens. The
`_budget_forced` ternary reproduces the literal `ask()` uses for its
`stop_reason` (openai_base.py:1030).

### `packages/ai-parrot/src/parrot/clients/openai_base.py` (MODIFY — block C of 3)
```python
# occurrences: 1 (verified: grep -c 'usage = CompletionUsage.from_openai(response.usage)' packages/ai-parrot/src/parrot/clients/openai_base.py)
# REPLACE `            usage = CompletionUsage.from_openai(response.usage)` (verified: openai_base.py:1660)
            usage = _lc_usage
```
**Why**: spec §7 — compute the usage once and pass the same object to both the
event and `_build_invoke_result`, so a dashboard and an `InvokeResult` can never
disagree. Nothing else in the 1661-1671 return block changes.

### `packages/ai-parrot/tests/unit/clients/test_invoke_telemetry.py` (CREATE)
```python
"""Unit tests for lifecycle-event emission from OpenAIBaseClient.invoke() (FEAT-579).

``ask()`` has emitted BeforeClientCallEvent / AfterClientCallEvent /
ClientCallFailedEvent for some time; ``invoke()`` emitted nothing, so every
invoke call was missing from token, cost and latency telemetry.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from parrot.clients.openai_base import OpenAIBaseClient
from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    BeforeClientCallEvent,
    ClientCallFailedEvent,
)


def _capture():
    """Return ``(captured, async_callback)`` for one event class."""
    captured: list = []

    async def cb(event):
        captured.append(event)

    return captured, cb


def _make_stub(*, raise_on_completion: Exception | None = None, finish_reason: str = "stop"):
    """An OpenAIBaseClient subclass that fakes _chat_completion and does NOT override invoke()."""

    class _InvokeStub(OpenAIBaseClient):
        client_name = "stub-openai"
        client_type = "stub"
        model = "stub-model"

        def __init__(self):
            super().__init__(debug=False)
            self._raise_on_completion = raise_on_completion

        async def get_client(self):
            return MagicMock()

        async def _ensure_client(self):
            pass

        async def resume(self, *args, **kwargs):
            raise NotImplementedError("stub")

        async def _chat_completion(self, **kwargs):
            if self._raise_on_completion:
                raise self._raise_on_completion
            # FILL IN: build the MagicMock response shape — copy
            # test_client_failed_call_emission.py:56-69 (choices[0].message.content,
            # choices[0].finish_reason, usage.prompt_tokens=10/completion_tokens=5)
            # and honour the `finish_reason` closure argument — bounded by AC-1.
            raise NotImplementedError

    stub = _InvokeStub()
    # FILL IN: `self.client` must be truthy or invoke() raises at openai_base.py:1597
    # before any event is emitted — bounded by AC-6.
    return stub


@pytest.mark.asyncio
async def test_invoke_emits_before_and_after() -> None:
    """Normal path → one Before + one After with the provider's tokens and finish_reason."""
    client = _make_stub()
    before, before_cb = _capture()
    after, after_cb = _capture()
    client.events.subscribe(BeforeClientCallEvent, before_cb)
    client.events.subscribe(AfterClientCallEvent, after_cb)

    await client.invoke("hello", model="stub-model")

    await asyncio.sleep(0.05)  # drain emit_nowait tasks
    assert len(before) == 1
    assert len(after) == 1
    assert after[0].input_tokens == 10
    assert after[0].output_tokens == 5
    assert after[0].finish_reason == "stop"
    # FILL IN: assert after[0].model == the resolved model and duration_ms > 0
    # — bounded by AC-1; resolve the expected model via _resolve_invoke_model.


@pytest.mark.asyncio
async def test_invoke_error_emits_failed_not_after() -> None:
    """_chat_completion raises → one Failed (error_type "RuntimeError"), no After, InvokeError."""
    # FILL IN: _make_stub(raise_on_completion=RuntimeError("model on fire")),
    # subscribe to both, pytest.raises(InvokeError), assert len(failed) == 1 and
    # failed[0].error_type == "RuntimeError" and len(after) == 0 — bounded by AC-5.


@pytest.mark.asyncio
async def test_invoke_budget_finalize_emits_after_budget_exhausted() -> None:
    """_chat_completion raises BudgetExhausted, _finalize_budgeted_chat returns → After."""
    # FILL IN: stub whose _chat_completion raises BudgetExhausted and whose
    # _finalize_budgeted_chat returns a response; assert one After with
    # finish_reason == "budget_exhausted" and the finalize response's tokens,
    # and zero Failed — bounded by AC-3. Read openai_base.py:286 for the
    # _finalize_budgeted_chat signature you must match when overriding it.


@pytest.mark.asyncio
async def test_invoke_budget_partial_emits_after_without_tokens() -> None:
    """Both raise BudgetExhausted → After with None tokens; InvokeResult still returned."""
    # FILL IN: assert input_tokens is None, output_tokens is None,
    # finish_reason == "budget_exhausted", zero Failed, and that the returned
    # value is an InvokeResult carrying the partial text — bounded by AC-4.


@pytest.mark.asyncio
async def test_invoke_parse_failure_emits_after_only() -> None:
    """Truncated response + output_type → After emitted, then raises, no Failed."""
    # FILL IN: finish_reason="length" plus an output_type so _raise_if_truncated
    # (openai_base.py:1645) fires; assert len(after) == 1, len(failed) == 0, and
    # that the exception still propagates — bounded by AC-2 and AC-6.


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["normal", "error", "finalize", "partial", "parse_error"])
async def test_invoke_exactly_one_terminal_event(scenario: str) -> None:
    """Every invoke() that reaches dispatch emits exactly one terminal event."""
    # FILL IN: drive each scenario through the stubs above and assert
    # len(after) + len(failed) == 1 — bounded by AC-6.
```
**Why**: spec §4's M2 rows. The stub deliberately omits an `invoke()` override —
copying `_Stub` from `test_client_failed_call_emission.py` would test nothing.
The `await asyncio.sleep(0.05)` drain is mandatory because
`BeforeClientCallEvent` is emitted fire-and-forget via `emit_nowait()`.

### FILL IN checklist
- [ ] block A — the verbatim `_finalize_budgeted_chat(...)` call (1617-1624) and
      `_budget_forced = True`; bounded by "existing behaviour unchanged".
- [ ] block A — the verbatim partial-path body (1627-1637); bounded by AC-4.
- [ ] `_make_stub` — the MagicMock response shape and a truthy `self.client`;
      bounded by AC-1/AC-6.
- [ ] `test_invoke_emits_before_and_after` — model + duration assertions; AC-1.
- [ ] `test_invoke_error_emits_failed_not_after` — whole body; AC-5.
- [ ] `test_invoke_budget_finalize_emits_after_budget_exhausted` — whole body; AC-3.
- [ ] `test_invoke_budget_partial_emits_after_without_tokens` — whole body; AC-4.
- [ ] `test_invoke_parse_failure_emits_after_only` — whole body; AC-2/AC-6.
- [ ] `test_invoke_exactly_one_terminal_event` — the five scenario drivers; AC-6.

---

## Acceptance Criteria

- [ ] AC-1: Normal path emits Before + After with `input_tokens`/`output_tokens`
      from `CompletionUsage.from_openai(response.usage)`, `model == resolved_model`,
      `finish_reason == self._extract_finish_reason(response)` and `duration_ms > 0`.
- [ ] AC-2: The after-event is emitted **before** parsing; a parse/truncation
      failure emits no Failed event and still raises.
- [ ] AC-3: Finalize path emits After with `finish_reason == "budget_exhausted"`
      and the finalize response's tokens.
- [ ] AC-4: Partial path emits After with `input_tokens is None`,
      `output_tokens is None`, `finish_reason == "budget_exhausted"`, and still
      returns its `InvokeResult`.
- [ ] AC-5: A dispatch error emits exactly one Failed and no After, and the
      exception that escapes `invoke()` is unchanged in type and message.
- [ ] AC-6: Every `invoke()` that reaches dispatch produces exactly one terminal
      event; errors before dispatch (model resolution, "not initialised")
      produce no events.
- [ ] AC-7: `CompletionUsage.from_openai(response.usage)` is evaluated exactly
      once per `invoke()`.
- [ ] AC-8: The `invoke()` signature is unchanged, the except-chain at
      1672-1677 is unchanged, and
      `packages/ai-parrot/src/parrot/clients/base.py` is not modified
      (`git diff --name-only` must not list it).
- [ ] AC-9: `packages/ai-parrot/tests/unit/clients/test_client_failed_call_emission.py`
      still reports `4 passed`.
- [ ] AC-10: `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/clients/test_invoke_telemetry.py -q`
- `pytest packages/ai-parrot/tests/unit/clients/test_client_failed_call_emission.py -q`
- `pytest packages/ai-parrot/tests/unit/clients/test_token_budget_boundaries.py -q`
- `pytest tests/clients/test_openai_base.py tests/clients/test_invoke_max_tokens.py -q`

---

## Test Specification

See the blueprint's test block — six tests in
`packages/ai-parrot/tests/unit/clients/test_invoke_telemetry.py`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/invoke-telemetry.spec.md` (§2 "OpenAIBaseClient.invoke()", §4, §7).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** before writing any code: re-`grep` every
   anchor and line number above; if one moved, update this contract first.
4. **Update status** in `sdd/tasks/index/invoke-telemetry.json` → `"in-progress"`.
5. **Implement** blocks A, B, C in order, then the tests; complete every `# FILL IN:`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3478-openai-base-invoke-telemetry.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
