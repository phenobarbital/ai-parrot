# TASK-1852: Dual-publish shims — FlowEventPublisher + dispatcher XADD sites

**Feature**: FEAT-322 — AHP-style Session State, Host & HITL Approval Gates for dev-loop
**Spec**: `sdd/specs/agent-host-protocol-session-state.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1851
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. Today's producers keep emitting legacy envelopes
unchanged; this task additionally folds each event into the run's
`SessionHost` via the 1:1 shims (TASK-1849), so the session state becomes
authoritative while nav-admin keeps working (spec §1 G4 zero-regression,
dual-publish window).

---

## Scope

- **`flow.py` — `FlowEventPublisher.__call__` (:94)**: after the legacy
  XADD block, resolve the host and apply:
  - Reuse the SAME `run_id` already computed per-event (:97-101).
  - Host resolution: the publisher cannot import the runner (layering).
    Resolve via `info["context"].shared_data.get("session_host")` — seeded
    by TASK-1851 — mirroring how run_id itself travels. NO new constructor
    params (holder untouched).
  - `error` for node_failed comes from the same `info` payload the legacy
    envelope carries.
  - Wrap in its own try/except — new-path failure never affects legacy
    publish, and vice versa (two independent swallow blocks).
- **`dispatcher.py` — the four XADD sites** (:816 Claude, :1281 Codex,
  :1721 Gemini, :2565 LLM family): each site builds a `DispatchEvent` and
  XADDs it. Add ONE module-level helper
  `_apply_to_session_host(host, event: DispatchEvent) -> None` (swallow-all,
  calls `action_from_dispatch_event(event.kind, event.node_id, event.ts,
  event.payload)` and `host.apply(...)` when both are non-None) and invoke
  it at each site. Host reaches the dispatcher the same way `run_id` does:
  dispatch calls receive explicit `run_id`/`node_id` kwargs
  (dispatcher.py:132) — pass the host alongside via the brief/shared
  plumbing ONLY if it already flows there; otherwise resolve via an
  optional `session_host` attribute settable on the dispatcher per-dispatch
  is NOT acceptable (shared instance!). **Correct approach**: nodes invoke
  dispatchers; the node has `shared["session_host"]` — add an optional
  keyword `session_host: Optional[SessionHost] = None` to the internal
  event-publish helper path each dispatcher already threads per-dispatch
  (verify the exact per-dispatch plumbing at implementation time; the
  invariant is: per-dispatch value, never dispatcher-instance state).
- Tests: legacy envelope bytes unchanged (existing tests must pass
  untouched); with a host present, flow events + dispatch events fold into
  state (counters bump, node statuses transition); redis-down on the
  actions stream doesn't affect legacy publish and vice versa.

**NOT in scope**: gate opening (TASK-1853); streaming (TASK-1854); any
change to legacy envelope shape or stream keys.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py` | MODIFY | dual-publish in `FlowEventPublisher.__call__` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py` | MODIFY | shared shim helper + 4 call sites |
| `packages/ai-parrot/tests/flows/dev_loop/test_dual_publish.py` | CREATE | dual-publish unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.session_state import (   # TASK-1848/1849
    SessionHost, action_from_dispatch_event, action_from_flow_event,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/flow.py
class FlowEventPublisher:                                       # :71
    def __init__(self, redis_url: str, run_id_holder: Dict[str, str]) -> None: ...  # :89
    async def __call__(self, event: str, node_id: str, info: Dict[str, Any]) -> None:  # :94
        # run_id resolution :97-101:
        #   run_ctx = info.get("context")
        #   run_id = getattr(run_ctx, "shared_data", {}).get("run_id", "")
        #   fallback: self._holder.get("run_id", "")
        # legacy XADD :113-118: f"flow:{run_id}:flow", maxlen=10_000, approximate=True
        # swallow-all :119-120
# events arriving here: node_started, node_completed, node_failed, node_skipped

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py
class DevLoopCodeDispatcher(Protocol):                          # :129
    async def dispatch(self, *, brief, profile, output_model, run_id: str,
                       node_id: str, cwd: str) -> T: ...        # :132
# XADD sites (all: xadd(stream_key, fields, maxlen=maxlen, approximate=True)):
#   :816 (Claude) · :1281 (Codex) · :1721 (Gemini) · :2565 (LLM/Grok/Zai)
#   stream_key = flow:{run_id}:dispatch:{node_id}
# DispatchEvent (models.py:698): kind/ts/run_id/node_id/payload

# Shim contracts (TASK-1849):
def action_from_flow_event(event: str, node_id: str, ts: float, error: str = "") -> Optional[DevLoopAction]: ...
def action_from_dispatch_event(kind: str, node_id: str, ts: float, payload: Optional[dict] = None) -> Optional[DevLoopAction]: ...
```

### Does NOT Exist
- ~~`FlowEventPublisher.session_host` attribute / new constructor param~~ —
  host travels via `info["context"].shared_data["session_host"]` per event
- ~~a single shared XADD helper in dispatcher.py today~~ — the four sites are
  separate; THIS task adds the one shared shim helper (verify the four line
  anchors first — file is very active)
- ~~importing DevLoopRunner from flow.py or dispatcher.py~~ — layering
  violation; host arrives via shared state / per-dispatch plumbing

---

## Implementation Notes

### Key Constraints
- The two publish paths are independent failure domains: two try/except
  blocks, both swallow, both log at debug/warning.
- `NodeId` typing: shims accept plain `str` node_id (sketch behavior) —
  do not add validation that could raise on unexpected node ids.
- Do NOT reorder or modify the legacy envelope construction — the
  zero-regression criterion is "existing tests pass unmodified".
- dispatcher.py is 2856 lines and hot (FEAT-270/Moonshot churn):
  RE-VERIFY the four XADD anchors by grep before editing; if a fifth
  dispatcher family has appeared, wire it too and note it in the
  Completion Note.

---

## Acceptance Criteria

- [ ] Legacy streams/envelopes byte-identical (existing streaming + dispatcher tests pass unmodified)
- [ ] With a host in shared state: node lifecycle events fold (idle→running→completed/failed/skipped) and dispatch events bump counters/status
- [ ] No host in shared state (legacy callers): both paths behave exactly as today
- [ ] Redis failure on either path leaves the other unaffected; run never breaks
- [ ] All dispatcher families wired through the ONE shared helper (no copy-paste per site)
- [ ] Tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`; `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_dual_publish.py
async def test_flow_event_folds_into_host(): ...
async def test_flow_event_without_host_is_legacy_only(): ...
async def test_dispatch_event_bumps_counters(): ...
async def test_legacy_envelope_unchanged_with_shim_active(): ...
async def test_actions_xadd_failure_does_not_break_legacy(): ...
```

---

## Agent Instructions

1. Read spec §3 M4 + §7 Patterns. Verify TASK-1851 completed.
2. RE-VERIFY flow.py:94-120 and the four dispatcher XADD anchors by grep.
3. Implement; run full dev_loop suite; move to completed; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
