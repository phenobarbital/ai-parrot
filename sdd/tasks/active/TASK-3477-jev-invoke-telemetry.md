# TASK-3477: JevClient.invoke() lifecycle telemetry

**Feature**: FEAT-579 — Lifecycle Telemetry for `invoke()` (JevClient + OpenAIBaseClient)
**Spec**: `sdd/specs/invoke-telemetry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec. `AbstractClient` already exposes three
lifecycle hooks (`_emit_before_call` / `_emit_after_call` /
`_emit_failed_call_safe`) and `JevClient.ask()` already calls all three
(`jev/client.py:553-576`). `JevClient.invoke()` calls none of them, so every
`invoke()` call is invisible to `MetricsSubscriber`, the OTel subscribers and
the cost/token recorders — no tokens, no cost, no latency, no error count.

This task brings `invoke()` up to the same telemetry level as `ask()`, using
only hooks that already exist. `clients/base.py` is NOT touched.

---

## Scope

- Restructure the body of `JevClient.invoke()` into three segments so the
  events land on the right one:
  1. **input resolution** (`_resolve_questions`, `_coerce_state` /
     `_build_state`) — emits **nothing**, still wrapped into `InvokeError`;
  2. **provider dispatch** (`system_one`) — wrapped by
     `_emit_before_call` / `_emit_after_call` / `_emit_failed_call_safe`;
  3. **parse** (`answers_to_type`) — emits **nothing**, still wrapped into
     `InvokeError`.
- Reuse the single `CompletionUsage` from `self._usage_from(response)` for both
  `_emit_after_call` and `_build_invoke_result` (spec §7: compute once).
- Add the three M1 unit tests from spec §4 plus the M1 half of
  `test_invoke_exactly_one_terminal_event`.

**NOT in scope**: `JevClient.ask()` / `ask_stream()` (already instrumented);
`OpenAIBaseClient.invoke()` (TASK-3478); any change to `clients/base.py`,
`InvokeResult`, the event models, or the `invoke()` signature; telemetry for
any other client's `invoke()` (spec §1 Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py` | MODIFY | Add the three-hook telemetry to `invoke()` (lines 721-741) |
| `tests/clients/test_jev_client.py` | MODIFY | Add the M1 lifecycle-emission tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against the working tree on 2026-09-19 (branch `dev`).
> Use these exact names and signatures. Verify before adding anything not listed.

### Verified Imports
```python
# packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py — ALREADY imported, reuse as is
import time                                             # verified: jev/client.py:37

# tests/clients/test_jev_client.py — ALREADY imported, reuse as is
from parrot.clients.jev import JevClient, JevConfigurationError, JevSchemaError, SystemOneResponse, Noul
from parrot.exceptions import InvokeError               # verified: test_jev_client.py:44
from parrot.models.responses import InvokeResult        # verified: test_jev_client.py:47

# tests/clients/test_jev_client.py — NEW imports this task must add
import asyncio
from parrot.core.events.lifecycle.events import (       # verified: clients/base.py:50-56 (same import)
    AfterClientCallEvent,
    BeforeClientCallEvent,
    ClientCallFailedEvent,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):                                   # line 235
    def _emit_before_call(self, *, client_name: str, model: str,                # line 559 — KEYWORD-ONLY
        temperature: Optional[float] = None, system_prompt: Optional[str] = None,
        has_tools: bool = False, parent_trace: Optional[TraceContext] = None) -> TraceContext: ...
    async def _emit_after_call(self, tc: TraceContext, *, client_name: str,     # line 696 — tc POSITIONAL, rest KEYWORD-ONLY
        model: str, duration_ms: float, input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None, finish_reason: Optional[str] = None) -> None: ...
    async def _emit_failed_call_safe(self, tc: TraceContext, client_name: str,  # line 790 — ALL POSITIONAL
        model: str, t0: float, exc: Exception) -> None: ...
    def _build_invoke_result(self, output, output_type, model, usage, raw_response=None) -> InvokeResult:  # line 2158
    def _handle_invoke_error(self, exception: Exception) -> InvokeError:        # line 2186

# packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py
class JevClient(AbstractClient):                                                # line 119
    client_name: str = "jev"                                                    # line 157
    def _resolve_questions(self, questions, output_type) -> Dict[str, QuestionInput]:  # line 389 — raises JevConfigurationError
    @staticmethod
    def _usage_from(response: SystemOneResponse) -> CompletionUsage:            # line 411
    async def system_one(self, state, questions, *, model=None, extra_body=None, timeout=None)  # line 425
    # ask() telemetry reference — COPY THIS SHAPE VERBATIM:      lines 553-576
    #   tc = self._emit_before_call(client_name=..., model=resolved_model,
    #        temperature=None, system_prompt=system_prompt, has_tools=False)   553-559
    #   started = time.perf_counter()                                           560
    #   try: response = await self.system_one(...)                              561-562
    #   except Exception as exc:                                                563
    #       await self._emit_failed_call_safe(tc, self.client_name, resolved_model, started, exc); raise   564-565
    #   elapsed = time.perf_counter() - started                                 566
    #   usage = self._usage_from(response)                                      567
    #   await self._emit_after_call(tc, client_name=..., model=response.model,
    #        duration_ms=elapsed * 1000, input_tokens=usage.prompt_tokens,
    #        output_tokens=usage.completion_tokens, finish_reason="completed")  568-576
    async def invoke(...) -> InvokeResult:                                      # line 677 — SIGNATURE UNCHANGED
    #   config_ = self._build_invoke_structured_config(output_type, structured_output)  721
    #   resolved_type = config_.output_type if config_ else None                722
    #   resolved_model = self._resolve_model(model)                             723
    #   try:                                                                    724
    #       resolved_questions = self._resolve_questions(questions, resolved_type)   725
    #       request_state = self._coerce_state(state) if state is not None else self._build_state(prompt, system_prompt)  726
    #       response = await self.system_one(request_state, resolved_questions, model=resolved_model)  727
    #       output: Any = answers_to_type(...) if resolved_type is not None else response  728-732
    #   except Exception as exc: raise self._handle_invoke_error(exc) from exc  733-734
    #   return self._build_invoke_result(output, resolved_type, response.model,
    #       self._usage_from(response), raw_response=response.model_dump(mode="json"))  735-741

# tests/clients/test_jev_client.py — existing helpers to reuse
SAMPLE_ANSWERS                                                                  # line 55
def _sample_response(**overrides): ...  # {"model": "jev-latest", "usage": {"input_tokens": 42, "output_tokens": None}, "answers": SAMPLE_ANSWERS}  # line 72
class Triage(BaseModel): ...            # category / urgent / severity          # line 82
@pytest.fixture
def stub_api(aiohttp_server): ...       # returns `_make(handler=None, *, models_handler=None) -> (server, calls)`  # line 93
def _client(server, **kwargs) -> JevClient: ...  # api_key="test-key", max_retries=0  # line 125
async def test_invoke_derives_questions_and_parses_output_type(stub_api)        # line 615 — MUST STILL PASS
async def test_invoke_without_output_type_returns_response_and_wraps_errors(stub_api)  # line 631 — MUST STILL PASS
```

### Does NOT Exist
- ~~`AbstractClient._emit_invoke_before` / `_emit_invoke_after`~~ — there is no
  invoke-specific hook. Use the three generic hooks above.
- ~~an instrumented-invoke decorator / mixin on `AbstractClient`~~ — spec §1
  Non-Goals explicitly rules this out; `clients/base.py` must not be modified.
- ~~`InvokeResult.finish_reason`~~ — `InvokeResult` has no finish-reason field.
- ~~`ClientCallFailedEvent.input_tokens` / `.output_tokens`~~ — the failed event
  carries no token fields (`_emit_failed_call`, `base.py:750`).
- ~~`self._usage_from(response)` being an instance method~~ — it is a
  `@staticmethod` (line 411); calling it via `self.` is fine, do not add `self`
  as an argument.
- ~~`JevClient.invoke` accepting `history=`~~ — only `ask()` takes `history`;
  `_build_state` is called with `(prompt, system_prompt)` in `invoke`, with
  `(prompt, system_prompt, history)` in `ask`. Do NOT copy the 3-arg form.
- ~~behavioural Jev tests under `packages/ai-parrot-client-jev/tests/`~~ — that
  directory only holds `test_entry_points.py`. The tests live in the repo-root
  `tests/clients/test_jev_client.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/clients/test_jev_client.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._emit_before_call",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._emit_after_call",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._emit_failed_call_safe",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._build_invoke_result",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._handle_invoke_error"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Async throughout.** `_emit_after_call` and `_emit_failed_call_safe` are
  coroutines and MUST be awaited; `_emit_before_call` is sync and returns the
  `TraceContext`.
- **`_emit_failed_call_safe` takes positional args** in the order
  `(tc, client_name, model, t0, exc)` — do not pass them as keywords.
- **Argument order matters for `_emit_after_call`**: `tc` is positional,
  everything else is keyword-only.
- The after-event uses `model=response.model` (what the provider actually ran),
  while the before- and failed-events use `model=resolved_model` (what we asked
  for). This is exactly what `ask()` does — keep the asymmetry.
- Do not change the `invoke()` signature or its docstring `Args:` block; only
  extend the docstring with the emission contract (see blueprint).

### References in Codebase
- `packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py:553-576` —
  the `ask()` telemetry block this task mirrors.
- `packages/ai-parrot/tests/unit/clients/test_client_failed_call_emission.py:80-88`
  — the `_capture()` helper + `await asyncio.sleep(0.05)` drain pattern.

### Environment gotchas (verified 2026-09-19)
- `ai-parrot-client-jev` is **not installed** in the shared `.venv`. Run its
  tests with `PYTHONPATH=packages/ai-parrot-client-jev/src` prefixed, from the
  repo root, or collection fails with
  `ModuleNotFoundError: No module named 'parrot.clients.jev'`.
- **Pre-existing baseline failure — do NOT chase it**: with that `PYTHONPATH`,
  `tests/clients/test_jev_client.py` is `1 failed, 47 passed`. The failure is
  `test_factory_registration` (`KeyError: 'jev'`), caused by the distribution's
  entry point not being registered in this venv. It is unrelated to this task
  and must be left exactly as it is.
- Do **not** combine `tests/` and `packages/ai-parrot/tests/` in one pytest
  invocation — it aborts with
  `_pytest.pathlib.ImportPathMismatchError: ('tests.conftest', ...)`. Run the
  two roots separately.

---

## Implementation Blueprint

### Steps (in order)
1. Split the single `try:` at `client.py:724` into three segments — *why*: the
   spec requires input-resolution errors to emit **nothing** and parse errors to
   emit **no failed event**, which one flat `try` cannot express.
2. Keep a `raise self._handle_invoke_error(exc) from exc` in the first and third
   segments — *why*: the exception type callers see today must not change
   (AC: "the exception it raises is unchanged"); `test_invoke_without_output_type_returns_response_and_wraps_errors`
   asserts `InvokeError.original is JevSchemaError` on the parse path.
3. In the dispatch segment call `_emit_failed_call_safe` **before** the re-raise
   — *why*: the helper swallows its own errors so the original exception still
   propagates untouched (`base.py:790`).
4. Bind `usage = self._usage_from(response)` once and pass that same object to
   both `_emit_after_call` and `_build_invoke_result` — *why*: spec §7 forbids
   computing it twice, and reuse guarantees the event and the result agree.
5. Add the tests last, subscribing **before** the call and draining with
   `await asyncio.sleep(0.05)` — *why*: `BeforeClientCallEvent` is dispatched
   fire-and-forget via `emit_nowait()` (`base.py:559` docstring), so without the
   drain the assertion races the event loop.

### `packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'config_ = self._build_invoke_structured_config(output_type, structured_output)' packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py)
# REPLACE the whole method body from `config_ = ...` (verified: jev/client.py:721)
# through the closing `)` of the `return self._build_invoke_result(...)` (verified: jev/client.py:741)
# with the block below. The `async def invoke(...)` signature and the existing
# docstring `Args:`/`Returns:` sections stay EXACTLY as they are.
        config_ = self._build_invoke_structured_config(output_type, structured_output)
        resolved_type = config_.output_type if config_ else None
        resolved_model = self._resolve_model(model)

        # Input resolution: may fail without ever contacting System One, so it
        # emits no lifecycle events at all (spec §2 "Where the before-event goes").
        try:
            resolved_questions = self._resolve_questions(questions, resolved_type)
            request_state = self._coerce_state(state) if state is not None else self._build_state(prompt, system_prompt)
        except Exception as exc:
            raise self._handle_invoke_error(exc) from exc

        tc = self._emit_before_call(
            client_name=self.client_name,
            model=resolved_model,
            temperature=None,
            system_prompt=system_prompt,
            has_tools=False,
        )
        started = time.perf_counter()
        try:
            response = await self.system_one(request_state, resolved_questions, model=resolved_model)
        except Exception as exc:
            await self._emit_failed_call_safe(tc, self.client_name, resolved_model, started, exc)
            raise self._handle_invoke_error(exc) from exc
        elapsed = time.perf_counter() - started
        usage = self._usage_from(response)
        await self._emit_after_call(
            tc,
            client_name=self.client_name,
            model=response.model,
            duration_ms=elapsed * 1000,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            finish_reason="completed",
        )

        # Parsing happens after the terminal event: the tokens were consumed and
        # billed, so a parse failure must not retract them (spec §2, decision 1).
        try:
            output: Any = (
                answers_to_type(response, resolved_type, noul_threshold=self.noul_threshold)
                if resolved_type is not None
                else response
            )
        except Exception as exc:
            raise self._handle_invoke_error(exc) from exc
        return self._build_invoke_result(
            output,
            resolved_type,
            response.model,
            usage,
            raw_response=response.model_dump(mode="json"),
        )
```
**Why this shape**: the three segments map one-to-one onto the spec's §2
overview diagram — resolution (silent) → dispatch (instrumented) → parse
(silent). Exactly one terminal event is structurally guaranteed: the failed
branch always re-raises, so `_emit_after_call` is unreachable once
`_emit_failed_call_safe` has run, and neither can execute twice. `usage` is
bound once and reused, replacing the old second `self._usage_from(response)`
call in the return. **Must NOT change**: the method signature, the
`_handle_invoke_error(exc) from exc` wrapping in every segment, and
`raw_response=response.model_dump(mode="json")`.

Also extend the existing docstring — insert immediately below the summary line
`"""Stateless typed evaluation of ``prompt``.` (verified: jev/client.py:692,
occurrences: 1):
```
        Emits ``BeforeClientCallEvent`` before the System One request and exactly
        one terminal event: ``AfterClientCallEvent`` (tokens, duration,
        ``response.model``, ``finish_reason="completed"``) when the request
        returns, or ``ClientCallFailedEvent`` when ``system_one`` raises. Errors
        while resolving questions or state (before the request) and parse errors
        (after it) emit no failed event.
```

### `tests/clients/test_jev_client.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def test_ask_stream_yields_text_then_message(stub_api):' tests/clients/test_jev_client.py)
# BEFORE — insert above `async def test_ask_stream_yields_text_then_message(stub_api):` (verified: tests/clients/test_jev_client.py:648)
# Add `import asyncio` and the lifecycle-event import to the module header first
# (see Verified Imports) — do not re-import anything already at the top.


def _capture():
    """Return ``(captured, async_callback)`` for one event class."""
    captured: list = []

    async def cb(event):
        captured.append(event)

    return captured, cb


async def test_invoke_emits_before_and_after_with_usage(stub_api):
    """invoke() success → one Before + one After carrying the response usage."""
    server, _ = await stub_api()
    client = _client(server)
    before, before_cb = _capture()
    after, after_cb = _capture()
    client.events.subscribe(BeforeClientCallEvent, before_cb)
    client.events.subscribe(AfterClientCallEvent, after_cb)
    try:
        await client.invoke("I was charged twice", output_type=Triage)
    finally:
        await client.close()
    await asyncio.sleep(0.05)
    assert len(before) == 1
    assert len(after) == 1
    # FILL IN: assert input_tokens == 42, output_tokens matches _sample_response()'s
    # `"output_tokens": None` as _usage_from maps it, model == "jev-latest",
    # finish_reason == "completed", duration_ms > 0, client_name == "jev"
    # — bounded by AC-1. Read JevClient._usage_from (jev/client.py:411) to
    # confirm how a null output_tokens is mapped before asserting on it.


async def test_invoke_api_error_emits_failed_and_raises_invokeerror(stub_api):
    """system_one raises → one Failed, no After, InvokeError still raised."""
    # FILL IN: build a stub_api handler returning an HTTP error (e.g.
    # `web.json_response({"error": "boom"}, status=500)`) — mirror the error
    # mapping already exercised elsewhere in this file; subscribe to
    # ClientCallFailedEvent and AfterClientCallEvent; assert len(failed) == 1,
    # len(after) == 0, and pytest.raises(InvokeError) — bounded by AC-2.


async def test_invoke_missing_questions_emits_nothing(stub_api):
    """JevConfigurationError before the request → no events at all."""
    # FILL IN: build a client with no questions and no output_type so
    # _resolve_questions (jev/client.py:389) raises JevConfigurationError;
    # subscribe to all three event classes; assert every list is empty and
    # InvokeError is raised — bounded by AC-6.


@pytest.mark.parametrize("scenario", ["success", "api_error", "parse_error"])
async def test_invoke_exactly_one_terminal_event(stub_api, scenario):
    """Every invoke() that reaches dispatch emits exactly one terminal event."""
    # FILL IN: drive each scenario (parse_error = output_type whose fields the
    # stub answers cannot satisfy, as in
    # test_invoke_without_output_type_returns_response_and_wraps_errors:631);
    # assert len(after) + len(failed) == 1 in all three — bounded by AC-6.
```
**Why**: these are the spec §4 M1 rows. Subscription must happen before the
call and the `asyncio.sleep(0.05)` drain is mandatory because
`BeforeClientCallEvent` is emitted fire-and-forget. `parse_error` is the case
that proves the after-event is not retracted by a later failure.

### FILL IN checklist
- [ ] `test_invoke_emits_before_and_after_with_usage` — the exact token/model/
      finish_reason/duration assertions; bounded by AC-1 and `_usage_from`'s
      real mapping of a null `output_tokens`.
- [ ] `test_invoke_api_error_emits_failed_and_raises_invokeerror` — the failing
      `stub_api` handler and its assertions; bounded by AC-2.
- [ ] `test_invoke_missing_questions_emits_nothing` — the client construction
      that reaches `JevConfigurationError`; bounded by AC-6.
- [ ] `test_invoke_exactly_one_terminal_event` — the three scenario drivers;
      bounded by AC-6.
- [ ] docstring insertion point in `invoke()` — confirm the summary line is
      still at `jev/client.py:692` before inserting.

---

## Acceptance Criteria

- [ ] AC-1: `JevClient.invoke()` emits `BeforeClientCallEvent` + `AfterClientCallEvent`
      on success, with `input_tokens`, `output_tokens`, `duration_ms`,
      `model == response.model` and `finish_reason == "completed"`.
- [ ] AC-2: `JevClient.invoke()` emits `ClientCallFailedEvent` and **no** After event
      when `system_one` raises, and still raises `InvokeError`.
- [ ] AC-3: A parse failure (`answers_to_type`) emits the After event and **no**
      Failed event, and still raises `InvokeError` wrapping the original.
- [ ] AC-4: `self._usage_from(response)` is called exactly once per `invoke()`;
      the same object reaches `_emit_after_call` and `_build_invoke_result`.
- [ ] AC-5: The `invoke()` signature is unchanged and
      `packages/ai-parrot/src/parrot/clients/base.py` is not modified
      (`git diff --name-only` must not list it).
- [ ] AC-6: Every `invoke()` that reaches dispatch produces exactly one terminal
      event; input-resolution errors produce no events.
- [ ] AC-7: The two pre-existing invoke tests (`test_jev_client.py:615` and `:631`)
      still pass unchanged.
- [ ] AC-8: Baseline preserved — `tests/clients/test_jev_client.py` ends at
      `1 failed` (`test_factory_registration`, pre-existing, `KeyError: 'jev'`)
      and every other test passes.
- [ ] AC-9: `ruff check` clean on both modified files.

---

## Validation Commands

> **Run both with `PYTHONPATH=packages/ai-parrot-client-jev/src` exported first**
> — `ai-parrot-client-jev` is not installed in the shared `.venv`, so without it
> collection fails with `ModuleNotFoundError: No module named 'parrot.clients.jev'`.
> Expected result: `1 failed, 47 passed` + the new tests, where the single
> failure is the pre-existing `test_factory_registration` (see AC-8).

- `pytest tests/clients/test_jev_client.py -q`
- `pytest tests/clients/test_jev_client.py::test_invoke_derives_questions_and_parses_output_type tests/clients/test_jev_client.py::test_invoke_without_output_type_returns_response_and_wraps_errors -q`

---

## Test Specification

See the blueprint's test block. The four new tests are:
`test_invoke_emits_before_and_after_with_usage`,
`test_invoke_api_error_emits_failed_and_raises_invokeerror`,
`test_invoke_missing_questions_emits_nothing`,
`test_invoke_exactly_one_terminal_event` (parametrized).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/invoke-telemetry.spec.md` (§2 "JevClient.invoke()", §4, §7).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** before writing any code: re-`grep` each
   anchor line and each signature above; if a line number moved, update this
   contract first, then implement.
4. **Update status** in `sdd/tasks/index/invoke-telemetry.json` → `"in-progress"`.
5. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`.
6. **Verify** all acceptance criteria, including the AC-8 baseline.
7. **Move this file** to `sdd/tasks/completed/TASK-3477-jev-invoke-telemetry.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
