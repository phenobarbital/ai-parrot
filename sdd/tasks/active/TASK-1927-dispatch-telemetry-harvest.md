# TASK-1927: Dispatch telemetry harvest — usage/cost/turns from the terminal ResultMessage

**Feature**: FEAT-378 — DevLoop Enhancement — Feature-Mode Topology
**Spec**: `sdd/specs/devloop-enhancement.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1919
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (v0.2 amendment), step 1-2. The dispatcher buffers the
Claude Agent SDK's terminal `ResultMessage` but only mines it for error
diagnosis (`_extract_result_error`, dispatcher.py:716) — on the success
path it discards `usage` (tokens), `total_cost_usd`, `num_turns` and
`duration_ms`. The run bundle (TASK-1928/1929) needs that per-agent
telemetry, folded into session state the event-sourced way (FEAT-322).

---

## Scope

- **Dispatcher** (`dispatcher.py`):
  - New static helper `_extract_result_usage(messages) -> Optional[dict]` —
    duck-typed on the terminal `ResultMessage` (same reverse-scan +
    `getattr` pattern as `_extract_result_error`, dispatcher.py:737).
    Extracted keys (all optional): `input_tokens`, `output_tokens`,
    `cache_creation_input_tokens`, `cache_read_input_tokens` (from the
    `usage` attribute, which may be a dict or an object),
    `total_cost_usd`, `num_turns`, `duration_ms`.
  - Attach the extracted dict (when non-empty) to the
    `dispatch.completed` event payload under key `"usage"` on the Claude
    Code success path (dispatcher.py:433). Other dispatcher families
    (codex/gemini/llm/zai — `dispatch.completed` emits at :1104, :1633,
    :2077, :2123) attach whatever subset they have, or nothing; do NOT
    invent values.
- **Session state** (`session_state.py`):
  - `DispatchCompleted` action (:365) gains optional fields:
    `input_tokens: Optional[int]`, `output_tokens: Optional[int]`,
    `cache_creation_input_tokens: Optional[int]`,
    `cache_read_input_tokens: Optional[int]`,
    `total_cost_usd: Optional[float]`, `num_turns: Optional[int]`,
    `duration_ms: Optional[int]` — all default `None`.
  - `DispatchState` (:177) gains the same optional fields; the
    `dispatch/completed` reducer branch folds them.
  - `action_from_dispatch_event` (:1010) extracts the `"usage"` payload
    dict into the `DispatchCompleted` kwargs (int/float coercion,
    ignore unknown keys — lazy-loading rule stays: no heavy content).
- Unit tests: usage extraction (dict-shaped and object-shaped `usage`,
  absent usage), payload → action mapping, reducer fold, and a
  regression test that a payload-less `dispatch.completed` behaves
  exactly as before.

**NOT in scope**: the `RunBundle` model/renderer (TASK-1928), runner
export wiring (TASK-1929), any streaming/UI change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py` | MODIFY | `_extract_result_usage` + payload on `dispatch.completed` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` | MODIFY | `DispatchCompleted`/`DispatchState` usage fields + reducer + shim |
| `packages/ai-parrot/tests/flows/dev_loop/test_dispatch_telemetry.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Anchors (2026-07-27)
```python
# dispatcher.py
def _extract_result_error(messages) -> Optional[Dict]: ...   # :716-752 — pattern to copy
# dispatch.completed emissions: :433 (claude success), :1104, :1633, :2077, :2123
# _publish_event(stream_key, kind=..., run_id=..., node_id=..., payload={...})

# session_state.py
class DispatchState(_Frozen): ...        # :177 — status/started_at/finished_at/counters
class DispatchCompleted(_DispatchAction): ...   # :365 — currently NO payload fields
def action_from_dispatch_event(kind, node_id, ts, payload=None): ...  # :1010
def reduce(...): ...                     # :560 — dispatch/completed branch folds DispatchState
```

### Does NOT Exist
- ~~Usage capture on the success path~~ — only error diagnosis is mined today.
- ~~A `DispatchUsage` action~~ — do NOT add a new action type; extend
  `DispatchCompleted` (optional fields keep old envelopes deserializable).
- Note: TASK-1919 also edits session_state.py (NodeId +4, three new
  actions). Re-grep all line anchors at task start; place the new fields
  alongside whatever landed.

---

## Implementation Notes

- Duck-type everything from the SDK message (`getattr(msg, "usage", None)`
  etc.) — no eager SDK import, matching the module's existing style.
- `usage` may arrive as a dict or as an object with attributes; support
  both (helper: read via `getattr` falling back to `dict.get`).
- All new model fields optional with `None` defaults → old persisted
  envelopes (`flow:{run_id}:actions`) still validate.
- Never let telemetry extraction raise on the success path — wrap the
  helper body defensively; a malformed usage payload must not fail a
  dispatch that succeeded.

---

## Acceptance Criteria

- [ ] Successful Claude Code dispatch → `dispatch.completed` payload
      carries `usage` with tokens/cost/turns/duration when the SDK
      provides them
- [ ] `DispatchState` exposes the folded telemetry after reduction
- [ ] Payload-less `dispatch.completed` (other dispatchers, old streams)
      behaves exactly as before (regression test)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_dispatch_telemetry.py -v` AND the existing dispatcher + session-state suites stay green
- [ ] `ruff check` clean on both modified modules

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_dispatch_telemetry.py
def test_extract_result_usage_dict_shaped(): ...
def test_extract_result_usage_object_shaped(): ...
def test_extract_result_usage_absent_returns_none(): ...
def test_action_from_dispatch_event_maps_usage_payload(): ...
def test_reducer_folds_usage_into_dispatch_state(): ...
def test_payloadless_completed_unchanged(): ...
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 8, §6, §7 Patterns)
2. **Check dependencies** — TASK-1919 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-grep every line anchor
   (session_state.py and dispatcher.py are both under active edit by
   FEAT-377/FEAT-378 tasks)
4. **Update status** in `sdd/tasks/index/devloop-enhancement.json` → `"in-progress"`
5. **Implement**, **verify criteria**, move file to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
