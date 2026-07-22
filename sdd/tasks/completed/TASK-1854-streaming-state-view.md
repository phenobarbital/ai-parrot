# TASK-1854: FlowStreamMultiplexer `view="state"` — snapshot + sequenced envelopes

**Feature**: FEAT-322 — AHP-style Session State, Host & HITL Approval Gates for dev-loop
**Spec**: `sdd/specs/agent-host-protocol-session-state.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1852
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (goal G5, read side). Clients opening a run mid-flight get
an instant `Snapshot` instead of replaying the whole event history, then a
sequenced envelope stream with gap-free reconnect (`server_seq > last_seen`)
— AHP's subscribe/reconnect semantics over the existing WS.

---

## Scope

- **`streaming.py`**:
  - Extend `ViewLiteral` (:43) with `"state"`.
  - `FlowStreamMultiplexer(view="state")`: reads ONLY the actions stream
    `flow:{run_id}:actions` (no dispatch discovery loop needed for this
    view).
  - Snapshot source on connect: fold the actions stream from seq 0 through
    `reduce()` (envelopes are `ActionEnvelope` JSON — parse with
    `ActionEnvelope.model_validate_json`). This works for live AND finished
    runs and needs no runner handle (crash-rebuild invariant, spec §7).
    Emit `{"source": "state", "node_id": None, "event_kind": "snapshot",
    "ts": <now>, "payload": Snapshot(...).model_dump()}` as the FIRST frame.
  - Then relay envelopes as
    `{"source": "state", "event_kind": "action", "ts": action.ts,
    "payload": envelope.model_dump()}` in `server_seq` order, starting
    strictly after the snapshot's `from_seq`.
  - `?last_seen=<int>` WS query param (in `flow_stream_ws`, :298): when
    present and view="state", skip the snapshot and replay envelopes with
    `server_seq > last_seen`, then continue tailing (AHP reconnect-replay).
  - Legacy views (`flow`/`dispatch`/`both`) byte-identical — zero changes to
    their code paths.
- Tests: snapshot-first ordering; replay gap/dup-free across
  disconnect/reconnect with `last_seen`; finished-run fold (stream exists,
  no live producer); legacy views untouched (existing tests green).

**NOT in scope**: REST commands (TASK-1855); WS client→server command
messages (non-goal — wire adapter spec); publisher/dispatcher changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py` | MODIFY | `view="state"` + `last_seen` replay |
| `packages/ai-parrot/tests/flows/dev_loop/test_streaming_state_view.py` | CREATE | state-view unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web                              # streaming.py:37 (existing)
from parrot.flows.dev_loop.session_state import (    # TASK-1848/1849
    ActionEnvelope, DevLoopSessionState, Snapshot, reduce, session_channel,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py
SourceLiteral = Literal["flow", "dispatch"]                     # :42 — extend or parallel a new literal
ViewLiteral = Literal["flow", "dispatch", "both"]               # :43 — add "state"
class FlowStreamMultiplexer:                                    # :51
    def __init__(self, redis, *, run_id, view: ViewLiteral = "both",
                 dispatch_refresh_seconds=2.0, block_ms=1000) -> None: ...  # :54
    # keys: self._flow_key = f"flow:{run_id}:flow" :80
    #        self._dispatch_prefix = f"flow:{run_id}:dispatch:" :81
    # cursors dict :83; closed Event :84
    async def _discover_dispatch_streams(self) -> List[str]: ...  # :90 (SCAN-based)
    async def replay(self) -> AsyncIterator[Dict[str, Any]]: ...  # :133
    async def tail(self) -> AsyncIterator[Dict[str, Any]]: ...    # :163
    async def close(self) -> None: ...                            # :209
    # envelope builder :232 (_fields_to_envelope) → {"source","node_id","event_kind","ts","payload"}
async def flow_stream_ws(request: web.Request) -> web.WebSocketResponse: ...  # :298
    # parses ?view= and ?replay= query params — add ?last_seen= here

# Actions-stream entry format (TASK-1851 sink): XADD flow:{run_id}:actions
#   with the envelope as model_dump_json() — confirm the exact field name
#   used by the sink (e.g. {"envelope": <json>}) by reading the TASK-1851
#   implementation before parsing.

# Test pattern to follow:
# packages/ai-parrot/tests/flows/dev_loop/test_streaming.py (TASK-879 unit style)
# packages/ai-parrot/tests/flows/dev_loop/integration/test_websocket_replay.py (reconnect pattern)
```

### Does NOT Exist
- ~~`FlowStreamMultiplexer.snapshot()` / any state mode~~ — THIS task adds it
- ~~`?last_seen` param~~ — new here
- ~~a live-host lookup from the multiplexer~~ — deliberately NOT used; state
  view folds from the stream only (works for finished runs and after crash);
  do not import DevLoopRunner
- ~~client→server messages on this WS~~ — non-goal (future wire adapter)

---

## Implementation Notes

### Key Constraints
- Fold-from-stream is the ONLY snapshot source here — keeps the multiplexer
  decoupled from the runner process (it may run in another worker).
- Preserve the existing envelope frame shape for the new source
  (`source="state"`) so nav-admin's WS plumbing needs no protocol change.
- `server_seq` ordering comes free from Redis stream order (single writer
  per run) — assert monotonicity in tests, don't re-sort.
- Unknown/newer action types inside envelopes must not crash the view —
  `ActionEnvelope` parse failures on a frame: log + skip frame (forward
  compat).

---

## Acceptance Criteria

- [ ] `view="state"`: first frame is the snapshot, then strictly increasing `server_seq` envelopes
- [ ] `?last_seen=N`: no snapshot, only envelopes `> N`, no gaps or duplicates across reconnect
- [ ] Finished run (stream present, no producer): snapshot reflects final state incl. gate audit
- [ ] Legacy views: existing `test_streaming.py` + `test_websocket_replay.py` pass unmodified
- [ ] Tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`; `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_streaming_state_view.py
async def test_state_view_snapshot_first(fake_redis_with_actions): ...
async def test_state_view_seq_monotonic(...): ...
async def test_last_seen_replay_no_gaps_no_dupes(...): ...
async def test_finished_run_fold(...): ...
async def test_bad_frame_skipped_not_crash(...): ...
```

---

## Agent Instructions

1. Read spec §3 M6 + §2 Overview (client surface). Verify TASK-1852 completed.
2. Read the TASK-1851 sink implementation for the exact XADD field format.
3. Implement; run full dev_loop suite; move to completed; update index.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-22
**Notes**: `ViewLiteral` extended with `"state"`. Added
`_read_action_envelopes` (XRANGE `flow:{run_id}:actions`, parses each
`{"envelope": <json>}` entry via `ActionEnvelope.model_validate_json`,
malformed entries logged+skipped — never crashes), `state_replay(last_seen)`
(folds via `reduce()` from a fresh `DevLoopSessionState`; `last_seen=None`
→ snapshot-only first frame; `last_seen=N` → only envelopes with
`server_seq > N`, no snapshot), and `state_tail()` (XREAD BLOCK live
continuation from the cursor `state_replay` leaves behind). All three are
NEW methods — the legacy `replay()`/`tail()`/`_fields_to_envelope()` code
paths are byte-identical, untouched. `flow_stream_ws` gained a
`view == "state"` branch (separate from the legacy branch) plus
`?last_seen=<int>` parsing; legacy `view`/`replay` handling unchanged.
Server_seq ordering trusted from the Redis stream (single writer,
TASK-1851's sink) — never re-sorted, per the task's own constraint. 8 new
tests (snapshot-first, seq monotonic, reconnect gap replay, finished-run
fold via a FRESH multiplexer proving crash-rebuild, malformed-entry
skip, live tail continuation, legacy-view sanity). Full dev_loop suite:
492 passed (same 4 pre-existing unrelated failures as prior tasks).

**Deviations from spec**: none of substance. One self-inflicted bug found
and fixed during validation: my first draft of `test_finished_run_fold`
imported `RunClosed` via a deferred in-function import, which — combined
with this repo's pre-existing `test_lazy_import.py` (purges
`parrot.flows.dev_loop` from `sys.modules` mid-session and re-imports it,
per spec §7 R1) running earlier in the same pytest session — resolved to
a DIFFERENT `RunClosed` class object than the one already baked into
`ActionEnvelope`'s pydantic discriminated-union schema, causing a
`ValidationError` ONLY when run as part of the full suite (passed in
isolation). Fixed by moving the import to the file's top-level import
block (collection-time), consistent with every other import in the file
and with how the rest of this feature's test files already do it.
