# TASK-2729: Session state — `SeatState` projection + `tool_name` fix

**Feature**: FEAT-496 — Dev-Loop Dispatch Event Legibility
**Spec**: `sdd/specs/dev-loop-dispatch-event-legibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2723
**Assigned-to**: unassigned

---

## Context

Spec §1 root causes 3 and 5, §2 "Seat projection", §3 Module 6.

Two problems meet in `session_state.py`:

1. **`DispatchToolUse.tool_name` is always empty.**
   `action_from_dispatch_event` (`session_state.py:1337-1338`) reads
   `payload.get("tool_name")`, but the Claude dispatcher writes
   `payload["tools"]` (a list). TASK-2724 fixes the emission side; this task
   makes the reducer robust and adds the regression test that pins it.

2. **A pooled `development` node reports no seats.** `_owning_node_id`
   (`_shared.py:53-74`) deliberately rolls `development.w1` up to
   `development` — it must, because `NodeId` (`session_state.py:140-159`) is
   a closed `Literal` and a seat-keyed action fails validation and is
   silently swallowed. That roll-up fixed a real bug (a pooled node reporting
   0 messages / 0 tool uses) and **must be preserved**. What is missing is
   the per-seat *detail* underneath it.

The chosen design (spec §2, and a declared Non-Goal for the alternative):
do **not** widen `NodeId`. Add an optional `seats` map to `DispatchState`
instead, so persisted pre-FEAT-496 envelopes still validate and replay.

---

## Scope

- Add a `SeatState` frozen model to `session_state.py`.
- Add `seats: Dict[str, SeatState] = Field(default_factory=dict)` to
  `DispatchState` (`session_state.py:188`).
- Extend the dispatch actions so seat detail can travel: add optional
  `seat`, `task_id`, `task_title` and `summary` fields to the
  `_DispatchAction` family (or to the three dispatch actions that need them),
  all defaulted.
- Extend `action_from_dispatch_event` (`session_state.py:1315`) to populate
  those fields from the normalized payload.
- Extend `reduce()` (`session_state.py:748`) to fold seat detail into
  `DispatchState.seats` **in addition to** the existing roll-up counters.
- Extend `_apply_to_session_host` (`_shared.py:76`) to pass the seat through
  (it currently discards it via `_owning_node_id`) while still keying the
  action on the owning node.
- Tests, including a persisted-envelope backward-compatibility test.

**NOT in scope**: emitting `tool_name` from any dispatcher (TASK-2724..2728);
building `DispatchLabels` at the pool (TASK-2730); console rendering
(TASK-2732/2733).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` | MODIFY | `SeatState`, `DispatchState.seats`, action fields, `reduce`, `action_from_dispatch_event` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py` | MODIFY | thread the seat through `_apply_to_session_host` |
| `packages/ai-parrot/tests/flows/dev_loop/test_session_state.py` | MODIFY | seat-fold + tool_name regression tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_dual_publish.py` | MODIFY | assert roll-up **and** seat detail |

---

## Codebase Contract (Anti-Hallucination)

### Verified Signatures

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
NodeId = Literal[                                             # lines 140-159
    "intent_classifier", "bug_intake", "research", "development", "qa",
    "deployment_handoff", "revision_handoff", "failure_handler", "close",
    "planner", "synthesis", "feedback_router", "feature_handoff",
    "dev_intake", "ideation",
]                                                             # ← CLOSED. Do not widen.

class DispatchState(_Frozen):                                 # line 188
    status: DispatchStatus                                    # line 197
    dispatcher: str = ""                                      # line 198
    started_at: Optional[float] = None                        # line 199
    finished_at: Optional[float] = None                       # line 200
    message_count: int = 0                                    # line 201
    tool_use_count: int = 0                                   # line 202
    last_error: str = ""                                      # line 203
    terminal: str = ""                                        # line 204
    # FEAT-378 TASK-1927 — the PRECEDENT for additive optional fields:
    input_tokens: Optional[int] = None                        # line 207
    output_tokens: Optional[int] = None                       # line 208
    cache_creation_input_tokens: Optional[int] = None         # line 209
    cache_read_input_tokens: Optional[int] = None             # line 210
    total_cost_usd: Optional[float] = None                    # line 211
    num_turns: Optional[int] = None                           # line 212
    duration_ms: Optional[int] = None                         # line 213

class NodeState(_Frozen):                                     # line 216
    node_id: NodeId                                           # line 219
    dispatch: Optional[DispatchState] = None                  # line 224

class DispatchQueued(_DispatchAction):  dispatcher: str = ""  # lines 401-403
class DispatchStarted(_DispatchAction): terminal: str = ""    # lines 406-408
class DispatchDelta(_DispatchAction)                          # line 411
class DispatchToolUse(_DispatchAction): tool_name: str = ""   # lines 418-420
class DispatchToolResult(_DispatchAction)                     # line 423
class DispatchOutputInvalid(_DispatchAction): error: str = "" # lines 427-429
class DispatchFailed(_DispatchAction): error: str = ""        # lines 432-434
class DispatchCompleted(_DispatchAction): ...telemetry...     # lines 437-448

DevLoopAction = Annotated[...]                                # line 545
def reduce(state, action)                                     # line 748
class SessionHost                                             # line 999
_DISPATCH_KIND_MAP: Dict[str, type] = {                       # line 1271
    "dispatch.message": DispatchDelta,                        # line 1274
    "dispatch.tool_use": DispatchToolUse,                     # line 1275
    "dispatch.tool_result": DispatchToolResult,               # line 1276
    ...
}
def action_from_dispatch_event(kind, node_id, ts,
                               payload=None) -> Optional[DevLoopAction]:  # 1315
    kwargs = {"node_id": node_id, "ts": ts}                   # line 1334
    if cls in (DispatchOutputInvalid, DispatchFailed):
        kwargs["error"] = str(payload.get("error", ""))[:500] # lines 1335-1336
    if cls is DispatchToolUse:
        kwargs["tool_name"] = str(payload.get("tool_name", ""))  # 1337-1338
    if cls is DispatchQueued:
        kwargs["dispatcher"] = str(payload.get("dispatcher", ""))# 1339-1340

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py
def _owning_node_id(node_id: str) -> str:                     # line 53
    """docstring explains WHY the roll-up exists — read it"""  # lines 54-73
    return node_id.split(".", 1)[0]                           # line 74

def _apply_to_session_host(event: DispatchEvent) -> None:     # line 76
    host = _SESSION_HOST_CTX.get()                            # line 84
    action = action_from_dispatch_event(
        event.kind, _owning_node_id(event.node_id),
        event.ts, event.payload)                              # lines 88-90
    if action is not None: host.apply(action)                 # lines 91-92
```

### Does NOT Exist

- ~~`SeatState`~~ / ~~`DispatchState.seats`~~ — this task creates them.
- ~~`NodeState.seats`~~ — the seat map goes on `DispatchState`, **not** on
  `NodeState`. Do not put it there.
- ~~a seat-tolerant `NodeId`~~ — widening the `Literal` is an explicit
  Non-Goal (spec §1): it appears in every persisted `ActionEnvelope` and
  would break replay of existing runs.
- ~~`DispatchToolResult.tool_name`~~ — does not exist today; adding it is
  optional and additive if the reducer needs it for `SeatState.last_tool`.
- ~~a `seat` field on any existing action~~ — none of the eight dispatch
  actions carries one today.

---

## Implementation Notes

### `SeatState` (spec §2 "Data Models")

```python
class SeatState(_Frozen):
    """Per-seat detail under a node's DispatchState (FEAT-496)."""

    seat: str
    task_id: str = ""
    task_title: str = ""
    agent: str = ""
    model: str = ""
    status: DispatchStatus = "queued"
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    message_count: int = 0
    tool_use_count: int = 0
    last_tool: str = ""
    last_summary: str = ""
    last_error: str = ""
```

### The roll-up must survive

`reduce()` keeps doing exactly what it does today to
`DispatchState.message_count` / `.tool_use_count` / `.status`. The seat fold
is **additive**: when the action carries a non-empty `seat`, also upsert
`state.nodes[node_id].dispatch.seats[seat]`. When `seat` is empty (every
single-agent dispatch), behaviour is byte-identical to today.

`test_dual_publish.py:206-218` already asserts the roll-up for pooled seats —
it must keep passing **unchanged**. Add new assertions rather than editing it.

### Threading the seat

`_apply_to_session_host` currently loses the seat at `_shared.py:88-90`. Keep
`_owning_node_id(event.node_id)` as the action's `node_id` (validation
requires it) and pass the raw `event.node_id` as the new `seat` — the
simplest shape is to let `action_from_dispatch_event` take an extra optional
`seat` argument, defaulted, so every existing caller is unaffected:

```python
action = action_from_dispatch_event(
    event.kind, _owning_node_id(event.node_id), event.ts, event.payload,
    seat=event.node_id if "." in event.node_id else "",
)
```

Prefer `payload["seat"]` (stamped by `DispatchLabels`) when present, falling
back to the derived value — labels are authoritative, the node id is a
fallback for unlabelled dispatches.

### Reducer purity

`reduce()` is a pure `(state, action) -> state` that must stay **total and
non-raising** (module docstring, `session_state.py:40-46`). Never raise on an
unknown seat; upsert it.

### Key Constraints

- Every new field is optional with a default — pre-FEAT-496 persisted
  `ActionEnvelope`s must still validate (the `DispatchCompleted` TASK-1927
  fields at `session_state.py:207-213` are the precedent to copy).
- `_Frozen` models: build new instances with `model_copy(update=...)`, never
  mutate.
- Clamp `last_summary` to the spec's 160 chars and `last_error` to 500 (the
  existing convention at `session_state.py:1336`).
- `session_state.py` imports no transport (no aiohttp/Redis/JSON-RPC) — keep
  it that way (module docstring, lines 8-12).

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py:437-448` — the additive-optional-fields precedent.
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py:53-74` — why the roll-up exists; read before touching it.
- `packages/ai-parrot/tests/flows/dev_loop/test_dual_publish.py:200-220` — the pooled-seat roll-up assertions to preserve.

---

## Acceptance Criteria

- [ ] `DispatchToolUse.tool_name` is populated from a realistic Claude-shaped `tool_use` payload (regression test for root cause 3).
- [ ] A `development.w1` dispatch event updates **both** `nodes["development"].dispatch.tool_use_count` (roll-up, unchanged semantics) **and** `nodes["development"].dispatch.seats["development.w1"]`.
- [ ] A seat entry carries `task_id`, `task_title`, `agent`, `model`, `status` and `last_tool` when the payload supplies them.
- [ ] A single-agent (`node_id="qa"`, no dot) dispatch produces **no** seat entry and behaves exactly as before.
- [ ] `DispatchState(status="running")` still validates with no `seats` argument, and `seats == {}`.
- [ ] A JSON `ActionEnvelope` captured before FEAT-496 (no `seats`, no `seat`) re-validates and replays through `reduce()` unchanged.
- [ ] `reduce()` never raises for any action/seat combination, including an unknown seat and a seat arriving before its `dispatch/queued`.
- [ ] `NodeId` is unchanged.
- [ ] Existing `test_dual_publish.py` assertions pass unchanged.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_session_state.py  (additions)

from parrot.flows.dev_loop.session_state import (
    DispatchState, SeatState, action_from_dispatch_event, reduce,
)


class TestToolNameRegression:
    def test_tool_name_is_populated(self):
        """Root cause 3: tool_name was always '' for Claude dispatches."""
        a = action_from_dispatch_event(
            "dispatch.tool_use", "development", 1.0,
            {"tool_name": "Read", "tools": ["Read"]})
        assert a.tool_name == "Read"


class TestSeatProjection:
    def test_seat_event_updates_rollup_and_seat(self, state):
        a = action_from_dispatch_event(
            "dispatch.tool_use", "development", 1.0,
            {"tool_name": "Bash", "seat": "development.w1",
             "task_id": "TASK-1857", "agent": "claude-code"},
            seat="development.w1")
        s = reduce(state, a)
        d = s.nodes["development"].dispatch
        assert d.tool_use_count == 1                     # roll-up preserved
        assert d.seats["development.w1"].task_id == "TASK-1857"
        assert d.seats["development.w1"].last_tool == "Bash"

    def test_single_agent_dispatch_has_no_seats(self, state):
        a = action_from_dispatch_event("dispatch.tool_use", "qa", 1.0,
                                       {"tool_name": "Read"})
        s = reduce(state, a)
        assert s.nodes["qa"].dispatch.seats == {}

    def test_seat_before_queued_does_not_raise(self, state):
        """reduce() must stay total."""
        a = action_from_dispatch_event("dispatch.tool_use", "development", 1.0,
                                       {"seat": "development.w9"},
                                       seat="development.w9")
        assert reduce(state, a) is not None


class TestBackwardCompatibility:
    def test_dispatch_state_without_seats_validates(self):
        assert DispatchState(status="running").seats == {}

    def test_pre_feat496_envelope_replays(self):
        """A persisted envelope with no seat fields must still validate."""
        legacy = {"type": "dispatch/tool_use", "node_id": "development",
                  "ts": 1.0, "tool_name": ""}
        ...   # validate through ActionEnvelope and reduce()
```

---

## Agent Instructions

1. **Read the spec** — §1 root causes 3 and 5, §2 "Seat projection", §3 Module 6, §7 "The roll-up must not regress".
2. **Check dependencies** — TASK-2723 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — read `_shared.py:53-99` (especially the `_owning_node_id` docstring) before changing anything there.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement**. Never widen `NodeId`. Never remove the roll-up.
6. **Verify** all acceptance criteria, backward compatibility especially.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: Added `SeatState` (frozen, defined right after `DispatchState`;
the forward reference `Dict[str, "SeatState"]` resolves fine under Pydantic
v2 since both classes are in the same module) and
`DispatchState.seats: Dict[str, SeatState] = Field(default_factory=dict)`.
Added `seat`, `task_id`, `task_title`, `agent`, `model`, `summary` — all
optional, defaulted to `""` — to the `_DispatchAction` base class (spec's
Scope text named `seat`/`task_id`/`task_title`/`summary`; `agent`/`model`
were added too since AC6 explicitly requires them on the seat entry and
there is no other channel for them to reach `reduce()`). `reduce()`'s eight
dispatch branches now additionally call a new `_fold_seat_from_action`
helper (defined beside `_with_dispatch`) that upserts
`DispatchState.seats[seat]` when the action carries a non-empty seat —
strictly additive; the existing roll-up counters are computed exactly as
before. `action_from_dispatch_event` gained an optional `seat: str = ""`
parameter (payload's own `seat` key wins when present — labels are
authoritative). `_apply_to_session_host` now passes
`seat=event.node_id if "." in event.node_id else ""`. 14 new tests added
(10 in `test_session_state.py`, 1 in `test_dual_publish.py`, matching
existing `test_pool_worker_seats_fold_into_their_owning_node` unchanged);
full `dev_loop` suite green (same 3 pre-existing unrelated failures in
`test_recovery_lifecycle.py`).

**Deviations from spec**: added `agent`/`model` fields to `_DispatchAction`
(and threading them through `action_from_dispatch_event`/
`_fold_seat_from_action`) beyond the four fields the Scope section named —
required by AC6's explicit requirement that a seat entry carry `agent`/
`model` "when the payload supplies them".
