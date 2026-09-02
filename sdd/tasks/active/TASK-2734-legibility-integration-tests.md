# TASK-2734: End-to-end legibility integration tests + acceptance sweep

**Feature**: FEAT-496 — Dev-Loop Dispatch Event Legibility
**Spec**: `sdd/specs/dev-loop-dispatch-event-legibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2722, TASK-2723, TASK-2724, TASK-2725, TASK-2726, TASK-2727, TASK-2728, TASK-2729, TASK-2730, TASK-2731, TASK-2732, TASK-2733
**Assigned-to**: unassigned

---

## Context

Spec §4 "Integration Tests", §5 (the whole acceptance list).

Every prior task tests its own layer. This task tests the **seam**, and it is
the one that would actually have caught the reported bug: each individual
piece was internally consistent, and the defect lived in the mismatch between
them (`payload["tools"]` written, `payload["tool_name"]` read, `keys[0]`
rendered).

It also performs the AC sweep: walk spec §5 criterion by criterion and record
the evidence for each.

---

## Scope

- Write `test_dispatch_legibility_integration.py` covering the three
  integration tests named in spec §4.
- Add a cross-backend parametrized test asserting the normalized payload
  contract holds for **every** dispatcher, so a future backend cannot regress
  it silently.
- Add a regression test that pins the exact reported symptom: no
  `dispatch.*` payload may be uninformative.
- Perform the spec §5 acceptance sweep and record evidence per criterion in
  `artifacts/logs/feat-496/acceptance-sweep.md`.
- Run the full dev-loop suite plus `ruff` over every file the feature touched.

**NOT in scope**: fixing defects found during the sweep in files owned by
other tasks — file them in the Completion Note and (if small) fix them, but
never silently rewrite another task's design decision.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/test_dispatch_legibility_integration.py` | CREATE | the three §4 integration tests + cross-backend contract |
| `artifacts/logs/feat-496/acceptance-sweep.md` | CREATE | evidence per acceptance criterion |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.flows.dev_loop.dispatchers.claude import ClaudeCodeDispatcher       # claude.py:94
from parrot.flows.dev_loop.dispatchers.codex import CodexCodeDispatcher         # codex.py:38
from parrot.flows.dev_loop.dispatchers.gemini import GeminiCodeDispatcher       # gemini.py:38
from parrot.flows.dev_loop.dispatchers.google_coding import GoogleCodingDispatcher  # google_coding.py:41
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher             # llm.py:48
from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer               # streaming.py
from parrot.flows.dev_loop.session_state import SessionHost, reduce             # session_state.py:999, :748
from parrot.flows.dev_loop.models import DispatchEvent, DispatchLabels          # models/base.py:735 + TASK-2722
from parrot.flows.dev_loop.agent_pool import DevAgentPool                       # agent_pool.py:107
from parrot.flows.dev_loop.task_scheduler import TaskRef                        # task_scheduler.py:25
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py
#   envelope shape: {"source", "node_id", "event_kind", "ts", "payload"}  # lines 16-17
    def _envelope(self, stream_key: str, fields: Dict[str, Any],
                  ts: float) -> Optional[Dict[str, Any]]:     # line ~487
        raw_event = fields.get("event")                       # line 497
        # falls back to event_kind="flow.unknown" when absent # lines 499-506
        return {... "event_kind": decoded.get("kind", "stream.unknown") ...}  # 517-523

# The eight kinds the contract must hold for — models/base.py:745-754
KINDS = ["dispatch.queued", "dispatch.started", "dispatch.message",
         "dispatch.tool_use", "dispatch.tool_result",
         "dispatch.output_invalid", "dispatch.failed", "dispatch.completed"]

# Existing fixture sources to reuse (do not rebuild fake SDKs from scratch):
#   packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py:163-164
#   packages/ai-parrot/tests/flows/dev_loop/test_gemini_dispatcher.py:168-169
#   packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py:176-178
#   packages/ai-parrot/tests/flows/dev_loop/test_dual_publish.py:179-218
```

### Does NOT Exist

- ~~a live Redis in CI~~ — every dispatcher test in this suite uses a fake or
  monkeypatched publish path. Follow `test_dual_publish.py`'s approach; do
  not require a real server.
- ~~a JS test harness for `dev.html` / `index.html`~~ — console verification
  is manual (TASK-2732/2733). This task asserts the **data** the console
  reads, not the DOM.
- ~~an end-to-end fixture that runs a real dev-loop flow~~ — there is none;
  build the wave from `DevAgentPool` + fake dispatchers, as
  `test_agent_pool.py` does.

---

## Implementation Notes

### The three §4 integration tests

1. **`test_claude_dispatch_stream_is_legible`** — drive a realistic Claude SDK
   message sequence (SystemMessage → TextBlock → ToolUseBlock →
   ToolResultBlock → ResultMessage) and assert that **no** published payload
   is uninformative and every one has a `summary`. This is the direct
   regression test for the reported bug.

2. **`test_pool_wave_events_carry_task_identity`** — run a 2-seat, 2-task fake
   wave through `DevAgentPool.run_wave` and assert every published event
   carries the `task_id` belonging to *its own* seat (no cross-talk).

3. **`test_multiplexer_passes_enriched_payload_through`** — publish an
   enriched event, read it back through `FlowStreamMultiplexer._envelope`, and
   assert every key survives and `event_kind` is the real kind. Guards both
   against a future multiplexer regression and against the `agy` wire-format
   defect (spec root cause 7) reappearing.

### Cross-backend contract test

Parametrize over all five dispatcher classes and assert the invariant that
defines this feature:

```python
@pytest.mark.parametrize("dispatcher_cls", ALL_DISPATCHERS)
@pytest.mark.parametrize("kind", KINDS)
async def test_normalized_contract_holds(dispatcher_cls, kind, captured):
    """Every backend, every kind: a summary, and never a bare class name."""
```

Include `GoogleCodingDispatcher` explicitly — it is the one that was silently
absent from the UI entirely (spec root cause 7 / AC9b).

### The acceptance sweep

Write `artifacts/logs/feat-496/acceptance-sweep.md` as a table: one row per
criterion in spec §5 (AC1..AC13, including AC7b and AC9b), each with the
test name or the manual step that proves it, and its result. A criterion with
no evidence is a failure, not an omission — report it.

### Key Constraints

- Reuse the existing fake-SDK / fake-subprocess doubles; do not invent a
  parallel fixture stack.
- No live Redis, no live network, no real CLI subprocess.
- Tests must be fast — this file runs on every CI pass.
- If the sweep uncovers a defect owned by another task, record it in the
  Completion Note with the task id. Fix only what is unambiguously a bug;
  never quietly change another task's design decision.

### References in Codebase

- `packages/ai-parrot/tests/flows/dev_loop/test_dual_publish.py` — the closest existing seam test (dispatcher → session host).
- `packages/ai-parrot/tests/flows/dev_loop/test_session_state.py:595-605` — existing `action_from_dispatch_event` assertions.

---

## Acceptance Criteria

- [ ] `test_claude_dispatch_stream_is_legible` passes: over a realistic message sequence, no payload's only informative key is a class name, and every payload has a non-empty `summary` (spec AC1, AC2).
- [ ] `test_pool_wave_events_carry_task_identity` passes: a 2-seat/2-task wave attributes every event to the correct `task_id` and `seat` (spec AC5).
- [ ] `test_multiplexer_passes_enriched_payload_through` passes: no key is lost and `event_kind` is never `"flow.unknown"` (spec AC9b).
- [ ] The cross-backend contract test passes for all five dispatchers across all eight kinds (spec AC2, AC7, AC9).
- [ ] `artifacts/logs/feat-496/acceptance-sweep.md` exists and records evidence for every criterion in spec §5, including the two manual console criteria (AC7, AC7b).
- [ ] Full suite green: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` (spec AC12).
- [ ] `ruff check` clean on every file this feature touched (spec AC13).
- [ ] Backward compatibility confirmed: a pre-FEAT-496 persisted `ActionEnvelope` still validates and replays (spec AC11).
- [ ] No new dependency was added to `pyproject.toml` (spec §7 External Dependencies: none).

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_dispatch_legibility_integration.py
import pytest

from parrot.flows.dev_loop.models import DispatchLabels
from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer

KINDS = ["dispatch.queued", "dispatch.started", "dispatch.message",
         "dispatch.tool_use", "dispatch.tool_result",
         "dispatch.output_invalid", "dispatch.failed", "dispatch.completed"]


class TestClaudeStreamLegibility:
    async def test_no_payload_is_uninformative(self, claude_message_sequence, captured):
        """FEAT-496 regression: the reported console output was literally
        `message_class=SystemMessage` and `tools: [toolu_01DJ...]`."""
        for _kind, payload in captured:
            assert payload["summary"], f"no summary: {payload}"
            assert set(payload) - {"message_class"}, f"uninformative: {payload}"
            for value in payload.values():
                assert not (isinstance(value, str) and value.startswith("toolu_")
                            and "tool_use_id" not in payload), \
                    "an opaque tool id leaked into a display field"


class TestPoolTaskIdentity:
    async def test_two_seats_two_tasks_no_crosstalk(self, fake_pool, captured):
        by_seat = {}
        for _kind, p in captured:
            if p.get("seat"):
                by_seat.setdefault(p["seat"], set()).add(p.get("task_id"))
        assert all(len(v) == 1 for v in by_seat.values()), by_seat
        assert len(by_seat) == 2


class TestMultiplexerPassthrough:
    def test_enriched_payload_survives(self, published_fields):
        mux = FlowStreamMultiplexer(object(), run_id="r1")
        env = mux._envelope("flow:r1:dispatch:development.w1", published_fields, ts=1.0)
        assert env["event_kind"] != "flow.unknown"
        assert env["payload"]["summary"]
        assert env["payload"]["task_id"] == "TASK-1857"


ALL_DISPATCHERS = [...]  # the five classes


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("dispatcher_cls", ALL_DISPATCHERS,
                         ids=lambda c: c.__name__)
async def test_normalized_contract_holds(dispatcher_cls, kind, captured):
    """Every backend, every kind, the same display contract."""
    ...
    assert payload["summary"] and len(payload["summary"]) <= 160
```

---

## Agent Instructions

1. **Read the spec** — §4 "Integration Tests" and the whole of §5.
2. **Check dependencies** — every other FEAT-496 task must be in `sdd/tasks/completed/`. This task runs last.
3. **Verify the Codebase Contract** — confirm the fixture sources still exist before reusing them.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** the tests, then run the acceptance sweep.
6. **Verify** — full suite + ruff + the written sweep document.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`, and set the per-spec index's `completed_at`.
9. **Fill in the Completion Note**, listing any defect the sweep found and which task owns it.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Acceptance sweep result**: <N>/<M> criteria evidenced — link to `artifacts/logs/feat-496/acceptance-sweep.md`

**Defects found during the sweep**: none | `<task-id>`: description

**Deviations from spec**: none | describe if any
