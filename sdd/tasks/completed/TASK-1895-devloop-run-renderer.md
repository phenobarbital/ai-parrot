# TASK-1895: Run Renderer — Rich Live Envelope Painter (`renderer.py`)

**Feature**: FEAT-374 — `parrot devloop`: Interactive CLI Console for Dev-Loop Flows
**Spec**: `sdd/specs/devloop-cli-console.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1894
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 / Goal G4. The console's live view: a `RunView` that turns a
run's `ActionEnvelope` stream into Claude-Code-like scrolling Rich output.
Key spec decision (§2 Overview): `SessionHost` has NO public subscribe API —
the renderer **polls** the public read side `replay_since(last_seq)` on a
~100–200 ms ticker. This is the G7 contract that avoids any core change.

---

## Scope

- Implement `packages/ai-parrot/src/parrot/cli/devloop/renderer.py`:
  - `class RunView` — constructed with a `SessionHost` (+ Rich `Console`).
    - `poll_once() -> list[ActionEnvelope]` — `host.replay_since(self._last_seq)`,
      advance cursor, return new envelopes (never re-render a seen seq).
    - `render(envelope)` — dispatch-table mapping action type → renderable:
      - `NodeStarted/NodeCompleted/NodeFailed/NodeSkipped` → node progress
        lines (name, status glyph, duration if available).
      - `DispatchQueued/DispatchStarted/DispatchCompleted/DispatchFailed/`
        `DispatchOutputInvalid` → dispatch lifecycle lines.
      - `DispatchDelta` → streaming assistant text appended to the tail
        region; `DispatchToolUse`/`DispatchToolResult` → dimmed tool lines.
      - `JiraLinked`/`PullRequestLinked` → highlighted link lines.
      - `GateOpened/GateResolved/GateExpired` → gate notices.
      - `RunCreated/RunCancelled/RunClosed` → run banner/footer.
      - Unknown/future action types → tolerated (dim one-liner, no crash).
    - `async def run_live(stop: asyncio.Event)` — Rich `Live` loop: tick,
      poll, paint; suspend/resume API (`pause()`/`resume()` context manager)
      so the console can take the terminal for modal prompts.
    - `pending_gates() -> dict[str, ApprovalGate]` — from
      `host.state.gates`, filtered `status == "pending"`.
- Unit tests `packages/ai-parrot/tests/cli/devloop/test_renderer.py` with a
  real `SessionHost` fed scripted actions via `host.apply(...)` (no mocks of
  dev-loop internals needed — `SessionHost` is pure in-memory).

**NOT in scope**: gate prompting/resolution and slash commands (TASK-1896);
runtime construction (TASK-1894); wizard (TASK-1893).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/devloop/renderer.py` | CREATE | RunView (poll + paint + pause/resume) |
| `packages/ai-parrot/tests/cli/devloop/test_renderer.py` | CREATE | scripted-host unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.session_state import (   # session_state.py
    SessionHost,            # line 723
    ApprovalGate,           # line 209
    ActionEnvelope,         # line 432
    DevLoopSessionState,    # line 238
)
from rich.live import Live
from rich.console import Console
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
class SessionHost:                                            # line 723
    def __init__(self, run_id: str, *,
                 on_envelope: Optional[Callable[[ActionEnvelope], None]] = None)  # line 738
    @property
    def state(self) -> DevLoopSessionState                    # line 765
    def snapshot(self) -> Snapshot                            # line 769
    def replay_since(self, last_seen_server_seq: int) -> List[ActionEnvelope]  # line 774
    def apply(self, action, origin=None) -> ActionEnvelope    # trusted-producer fold (tests use this)

class DevLoopSessionState(_Frozen):                           # line 238
    gates: Dict[str, ApprovalGate]                            # line 257
class ActionEnvelope(_Frozen): ...                            # line 432 — .channel, .server_seq, .action, .origin

# Action classes (dispatch table keys), all in session_state.py:
# RunCreated:276  RunCancelled:284  RunClosed:289
# NodeStarted:299 NodeCompleted:304 NodeFailed:310 NodeSkipped:316
# DispatchQueued:328 DispatchStarted:333 DispatchDelta:338
# DispatchToolUse:345 DispatchToolResult:350 DispatchOutputInvalid:354
# DispatchFailed:359 DispatchCompleted:364
# GateOpened:371 GateResolved:376 GateExpired:386
# JiraLinked:394 PullRequestLinked:399
# ApprovalGate:209 — has .status ("pending" | resolved states), .gate_id, kind, TTL fields
#   (read the class body at implementation time for exact field names)
```

### Does NOT Exist
- ~~`SessionHost.subscribe()` / `add_listener()` / `on(...)`~~ — NO public
  multi-subscriber API. Poll `replay_since`. Do NOT wrap or replace the
  host's constructor `on_envelope` sink (owned by `DevLoopRunner`).
- ~~`ActionEnvelope.type` / `.kind` string field~~ — discriminate by the
  **class** of `envelope.action` (isinstance / type-keyed dict).
- ~~`host.pending_gates()`~~ — no such method on SessionHost; derive from
  `host.state.gates` in THIS module's `RunView.pending_gates()`.
- ~~`rich.live.Live` nesting~~ — one Live at a time; pause/resume for modals.

---

## Implementation Notes

### Pattern to Follow
- Dispatch-table rendering (type → handler), like
  `parrot/cli/renderer.py::ResponseRenderer` (line 21) organizes rendering.
- Ticker: `while not stop.is_set(): await asyncio.sleep(0.15); paint(poll_once())`.

### Key Constraints
- Read-only relationship with the host (G7): never call `apply`/`resolve_gate`
  from the renderer (tests may use `apply` to script the host).
- Unknown action classes must render harmlessly (forward-compat — dev-loop
  is a hot subsystem, FEAT-322/323).
- `DispatchDelta` text accumulates per (node_id, dispatch) into a bounded
  tail (keep last N lines) so long runs don't grow unbounded.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/renderer.py:21` — Rich renderer shape.
- `sdd/specs/devloop-cli-console.spec.md` §2 "Key design decision".

---

## Acceptance Criteria

- [ ] Every action class listed in the contract maps to a distinct renderable;
  an unknown action type renders a dim line without raising.
- [ ] `poll_once()` cursor never re-yields a seen `server_seq`; works after
  re-attach (cursor reset to 0 → full replay).
- [ ] `pending_gates()` returns only `status == "pending"` gates.
- [ ] `pause()`/`resume()` stop and restart Live painting cleanly.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/cli/devloop/test_renderer.py -v`
- [ ] `ruff check` clean; no imports from `parrot.flows.dev_loop.dispatcher`.

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/devloop/test_renderer.py
import pytest
from parrot.flows.dev_loop.session_state import SessionHost
from parrot.cli.devloop.renderer import RunView

@pytest.fixture
def scripted_host():
    """SessionHost with a scripted NodeStarted…GateOpened…RunClosed sequence via apply()."""

def test_renderer_maps_all_action_types(scripted_host): ...
def test_renderer_unknown_action_tolerated(scripted_host): ...
def test_replay_cursor_no_duplicates(scripted_host): ...
def test_pending_gates_filters_status(scripted_host): ...
```

---

## Agent Instructions

1. **Read the spec** (§2 Overview, §3 M3, §6, §7).
2. **Check dependencies** — TASK-1894 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — esp. read `ApprovalGate` body
   (session_state.py:209) for exact field names before rendering TTLs.
4. **Update index** → `"in-progress"`.
5. **Implement** (TDD).  6. **Verify** criteria.
7. **Move to completed/**; index → `"done"`.  8. **Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
