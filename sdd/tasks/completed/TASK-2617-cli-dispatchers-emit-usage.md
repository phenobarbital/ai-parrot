# TASK-2617: CLI dispatchers emit AfterClientCallEvent after harvest

**Feature**: FEAT-479 — Dev-Flow / Dev-Loop Telemetry Accounting on the Lifecycle Bus
**Spec**: `sdd/specs/devflow-telemetry-accounting.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2612, TASK-2616
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 6. This is what makes **pool-worker** usage and
**model identity** reach the ledger (spec Findings 3 and 4's model gap).

`claude-code`, `codex` and `agy`/`google_coding` run **out of process**. There
is no `AbstractClient`, so none of `clients/base.py`'s lifecycle emission
happens. Their usage exists only in the harvested terminal `ResultMessage`,
published as a `dispatch.completed` payload — which the session-state shim then
**drops entirely** for pool workers, because `development.w1` cannot validate
against the closed `NodeId` `Literal` (`_shared.py:53-74` swallows the
`ValidationError` at DEBUG).

Emitting an `AfterClientCallEvent` from these dispatchers routes their usage
through the same accounting path as in-process clients, keyed by a free-string
seat that needs no `NodeId` at all.

---

## Scope

- In the `claude-code` dispatcher, after the existing
  `_extract_result_usage(messages)` harvest, emit an `AfterClientCallEvent`
  on the per-run registry, wrapped in
  `usage_attribution(run_id, seat=node_id)`.
- Map the harvested payload onto the event's fields (`model` from
  `profile.model`; tokens from the harvested `usage`).
- Apply the same treatment to `codex` / `google_coding` **only where a usage
  harvest exists**. Where none does, emit nothing rather than fabricating —
  and record which backends lack one in the Completion Note, answering spec
  §8's fourth open question.
- Write the unit tests below.

**NOT in scope**: building a new usage harvest for `codex`/`gemini`/
`google_coding` (that is a follow-up feature — see the note below); changing
`_publish_event` or the `dispatch.completed` payload; changing
`_apply_to_session_host` or `NodeId`; the report (TASK-2618/2619).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py` | MODIFY | Emit after harvest |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py` | MODIFY | Same, **only if** a usage harvest exists |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` | MODIFY | Same, **only if** a usage harvest exists |
| `packages/ai-parrot/tests/flows/dev_loop/test_cli_dispatcher_usage_events.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py:45
from parrot.core.events.lifecycle.events.client import AfterClientCallEvent
# verified: packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py (facade)
from parrot.core.events.lifecycle import TraceContext
# from TASK-2612:
from parrot.observability.context import usage_attribution
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py
# THE HARVEST + EMIT POINT — lines 315-325:
                completed_payload: Dict[str, Any] = {
                    "output_model": output_model.__name__,
                }
                usage_detail = self._extract_result_usage(messages)   # line 318
                if usage_detail:
                    completed_payload["usage"] = usage_detail         # line 320-321
                await self._publish_event(                            # line 322
                    stream_key,
                    kind="dispatch.completed",
                    run_id=run_id,
                    ...
                )
                # <-- EMIT THE AfterClientCallEvent HERE, after the harvest

    @staticmethod
    def _extract_result_usage(messages: List[Any]) -> Optional[Dict[str, Any]]:  # line 637
        """Usage/cost/turns from the terminal ResultMessage, if any.
        Surfaces ``usage`` (tokens), ``total_cost_usd``, ``num_turns``.
        ``usage`` may arrive as a dict OR as an object with attributes —
        both supported. NEVER raises; returns None when absent/malformed."""

# Model identity IS available on this path — verified:
#   claude.py:414  "model": profile.model
#   claude.py:423  model=profile.model
#   claude.py:450  model=profile.model

# packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py
@dataclass(frozen=True)
class AfterClientCallEvent(LifecycleEvent):                # line 45
    client_name: str          # the provider id — NOT `provider`
    model: str = ""                                        # line 69
    input_tokens: Optional[int] = None                     # line 71
    output_tokens: Optional[int] = None                    # line 72
    # plus trace_context / source_type / source_name / duration_ms /
    # finish_reason / agent_name / user_id / session_id.
    # VERIFY required args with dataclasses.fields() before constructing.

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py
_SESSION_HOST_CTX: contextvars.ContextVar                  # line ~48
def _apply_to_session_host(event: DispatchEvent) -> None: ...  # line 53
    # lines 70-74: swallows every exception at DEBUG. This is WHY pool-worker
    # telemetry vanishes today. Do NOT change this function — route around it.
```

### Does NOT Exist

- ~~`_extract_result_usage` on `codex.py` / `gemini.py` / `google_coding.py`~~ —
  **verified: only `claude.py` defines it.** The other backends have no usage
  harvest at all. Do not call a method that isn't there; do not invent one.
- ~~A `model` field on `DispatchState`~~ — none (`session_state.py:188-213`).
  The model reaches accounting through the event, not session state.
- ~~`AfterClientCallEvent.provider`~~ — the field is `client_name`.
- ~~`AfterClientCallEvent(**usage_detail)`~~ — the harvested dict's keys
  (`usage`, `total_cost_usd`, `num_turns`) do **not** match the event's fields.
  Map explicitly.
- ~~`self.events` on a dispatcher~~ — verify before use. Dispatchers are not
  necessarily `EventEmitterMixin` subclasses; the per-run registry comes from
  TASK-2616's injection. Confirm how it is threaded.

---

## Implementation Notes

### Shape

```python
usage_detail = self._extract_result_usage(messages)
if usage_detail:
    completed_payload["usage"] = usage_detail
await self._publish_event(...)   # unchanged

# FEAT-479: route out-of-process usage through the same accounting path as
# in-process clients. seat=node_id, which is "development.w1" for a pool
# worker — a free string, so no NodeId widening is needed.
if usage_detail and registry is not None:
    tokens = self._usage_tokens(usage_detail)     # small local helper
    with usage_attribution(run_id, seat=node_id):
        await registry.emit(
            AfterClientCallEvent(
                trace_context=..., client_name=<backend id>,
                model=profile.model,
                input_tokens=tokens.get("input_tokens"),
                output_tokens=tokens.get("output_tokens"),
                duration_ms=...,
                source_type="client", source_name=<backend id>,
            )
        )
```

### Token extraction — defensive, like the harvest itself

`_extract_result_usage`'s docstring notes `usage` may be a **dict** or an
**object with attributes**. Handle both, and return `None` (never `0`) for
anything absent. If neither token count is present, TASK-2614 sets
`usage_reported=False` and the report shows `—`.

### `await registry.emit(...)`, never `emit_nowait`

This is the whole point (spec §2 Exactness). `emit()` awaits the subscriber, so
the ledger holds the record before the dispatch returns. `emit_nowait` would
reintroduce the race.

### Backends with no harvest

Where `_extract_result_usage` (or an equivalent) does not exist, **emit
nothing**. A seat with no reported usage renders `—`, which is honest. Do not
fabricate zeros, and do not build a new harvest here — record the gap in the
Completion Note as the answer to spec §8's fourth question, and let it become
a follow-up feature.

### Key Constraints

- Never let telemetry break a dispatch. Wrap the emission so a failure is
  logged, not raised — matching `_apply_to_session_host`'s posture
  (`_shared.py:70`), though prefer a narrower `except Exception` with a
  warning over a silent DEBUG swallow.
- Do not modify `_apply_to_session_host` or widen `NodeId` — explicit Non-Goals.
  This task routes *around* that drop, leaving session state as the live-UI view.
- `usage_attribution` must wrap the `emit` call itself: the subscriber reads
  the ContextVars when building the record.
- `profile.model` is the model identity; do not re-derive it.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py:637` — the harvest
- `packages/ai-parrot/src/parrot/clients/claude.py:733-742` — reference emission call site
- `packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py:149` — the `development.w{i}` seat scheme

---

## Acceptance Criteria

- [ ] A `claude-code` dispatch with harvested usage emits exactly one
      `AfterClientCallEvent` carrying `profile.model` and the harvested tokens.
- [ ] The event is emitted with `await registry.emit(...)`, not `emit_nowait`.
- [ ] The event is attributed via `usage_attribution(run_id, seat=node_id)`.
- [ ] A **pool-worker** dispatch (`node_id="development.w1"`) produces a ledger
      record for that seat — the case that is silently dropped today.
- [ ] A dispatch with no harvested usage emits no event (no fabricated zeros).
- [ ] Usage arriving as an object-with-attributes works as well as a dict.
- [ ] A telemetry failure does not fail the dispatch.
- [ ] `dispatch.completed` payload and `_publish_event` behaviour are unchanged.
- [ ] The Completion Note records which backends lack a usage harvest (spec §8 Q4).
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` passes.
- [ ] `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_cli_dispatcher_usage_events.py
import pytest

from parrot.observability.recorders.run_ledger import RunLedgerRecorder


async def test_claude_dispatch_emits_after_call_with_model(claude_dispatcher, run_registry, ledger):
    """Out-of-process usage must reach the ledger with its real model."""
    await claude_dispatcher.dispatch(..., node_id="development", run_id="run-1")
    (rec,) = ledger.records
    assert rec.model == "claude-opus-5"
    assert rec.input_tokens > 0
    assert rec.seat == "development"


async def test_pool_worker_seat_reaches_ledger(claude_dispatcher, ledger):
    """Regression guard for FEAT-479 Finding 3: 'development.w1' cannot
    validate against the closed NodeId Literal, so _apply_to_session_host
    swallowed it at DEBUG and all fan-out usage was lost."""
    await claude_dispatcher.dispatch(..., node_id="development.w1", run_id="run-1")
    (rec,) = ledger.records
    assert rec.seat == "development.w1"
    assert rec.node_id == "development"


async def test_no_usage_no_event(claude_dispatcher, ledger):
    """No harvest -> no event. '—' is honest; 0 is a lie."""
    # make _extract_result_usage return None
    await claude_dispatcher.dispatch(..., node_id="qa", run_id="run-1")
    assert ledger.records == []


async def test_usage_as_object_and_as_dict(claude_dispatcher, ledger):
    """The harvest docstring promises both shapes are supported."""
    ...


async def test_telemetry_failure_does_not_break_dispatch(claude_dispatcher, broken_registry):
    """A raising registry must not fail the dispatch."""
    result = await claude_dispatcher.dispatch(..., node_id="qa", run_id="run-1")
    assert result is not None
```

**Harness note**: reuse the existing `claude` dispatcher fixtures under
`packages/ai-parrot/tests/flows/dev_loop/` (see `test_dispatch_telemetry.py`,
which already exercises the TASK-1927 harvest) rather than building a new
subprocess double.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §3 Module 6, and §2 Exactness for why `emit` not `emit_nowait`
2. **Check dependencies** — TASK-2612 and TASK-2616 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — in particular, confirm which dispatchers
   have a usage harvest before touching them
4. **Update status** in `sdd/tasks/index/devflow-telemetry-accounting.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2617-cli-dispatchers-emit-usage.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** — including the §8 Q4 answer

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-08-31
**Notes**: Added `set_event_registry_resolver(resolver)` +
`self._event_registry_resolver` to `ClaudeCodeDispatcher` (same shape as
`LLMCodeDispatcher`'s TASK-2616 resolver, so `DevLoopRunner.__init__`'s
existing `hasattr`-guarded wiring — unchanged, no `runner.py` edit needed —
picks it up automatically; verified empirically: constructing a
`ClaudeCodeDispatcher` and a `DevLoopRunner(dispatcher=...)` shows
`disp._event_registry_resolver is runner._run_registries.get`). Added a new
`_emit_usage_event(usage_detail, run_id, node_id, profile)` method, called
right after the existing `_publish_event(kind="dispatch.completed", ...)`
call (unchanged): no-ops when `usage_detail` is falsy (no harvest -> no
event, never a fabricated `0`/`—`-is-honest) or no resolver/registry is
available, otherwise constructs an `AfterClientCallEvent` (`client_name=
"claude-code"`, `model=profile.model`, tokens from the harvested
`usage_detail` dict) inside `usage_attribution(run_id, seat=node_id)` and
`await registry.emit(...)` (never `emit_nowait` — the whole point per spec
§2 Exactness). Wrapped in `try/except Exception` logging a warning so a
telemetry failure never breaks the dispatch. `codex.py` and
`google_coding.py` were **intentionally left untouched** — see §8 Q4 below.

Wrote `test_cli_dispatcher_usage_events.py` (6 tests, all from the task's
Test Specification, reusing `test_dispatch_telemetry.py`'s `_ResultMessage`/
`_UsageObj` fakes and `test_dispatcher.py`'s dispatch harness pattern):
model+tokens reach the ledger; a pool-worker seat (`"development.w1"`)
reaches the ledger with `node_id` rolled up to `"development"` (Finding 3
regression guard); no harvest -> no event; both dict-shaped and
object-shaped `usage` work; a raising registry doesn't break the dispatch;
and a dispatcher with no resolver ever wired (not owned by a
`DevLoopRunner`) still dispatches successfully. Full
`packages/ai-parrot/tests/flows/dev_loop/` suite (1123 tests, excluding the
3 pre-existing unrelated failures) passes. `ruff check` clean on both files
(fixed the import-order/quoted-annotation findings my own new code
introduced; the `Dict`/`Optional`-style debt already present in the
unmodified file is left as-is, per the established TASK-2612–2616
precedent of matching each file's own surrounding convention).

**§8 Q4 — which backends expose model identity / a usage harvest?**
- **`claude-code`** (`dispatchers/claude.py`): **has both.** Model identity
  is `profile.model` (verified: `claude.py:414`/`423`/`450`, unchanged by
  this task). A usage harvest exists:
  `_extract_result_usage(messages)` (`claude.py:637-691`, pre-existing,
  TASK-1927) mines the terminal `ResultMessage` for `input_tokens`/
  `output_tokens`/`cache_creation_input_tokens`/`cache_read_input_tokens`/
  `total_cost_usd`/`num_turns`/`duration_ms`. This is the only backend
  wired by this task.
- **`codex`** (`dispatchers/codex.py`): **neither.** Verified by grep:
  zero occurrences of `token`, `cost_usd`, `num_turns`, `ResultMessage`, or
  any `_extract_*_usage`-shaped method anywhere in the file. `dispatch()`
  publishes no `usage` key in its completed payload at all. Left
  completely untouched — there is nothing to route. Building a Codex CLI
  usage harvest (parsing whatever the `codex` CLI's own terminal/JSONL
  output exposes, if anything) is a follow-up feature, not a mechanical
  extension of this task.
- **`google_coding`** (`dispatchers/google_coding.py`, backs `agy`/
  `google_coding_dispatcher`): **neither**, same verification (zero
  `token`/`cost_usd`/`num_turns`/`ResultMessage` occurrences). Also left
  untouched. Same follow-up-feature conclusion as `codex`.
- `gemini.py` (`GeminiCodeDispatcher`) was not in this task's declared file
  list and was not investigated — out of scope.

**Deviations from spec**: `codex.py` and `google_coding.py` are listed in
the task's Files-to-Modify table as "MODIFY... Same, only if a usage
harvest exists" — since neither has one (verified above), the correct
action per that conditional instruction was to make NO changes to either
file, not to add speculative infrastructure (e.g. a `set_event_registry_
resolver` with nothing to call it) ahead of a harvest that doesn't exist
yet. No other deviations.
