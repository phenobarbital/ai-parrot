# TASK-2727: GoogleCoding (`agy`) dispatcher — extractor **and** wire-format fix

**Feature**: FEAT-496 — Dev-Loop Dispatch Event Legibility
**Spec**: `sdd/specs/dev-loop-dispatch-event-legibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2723
**Assigned-to**: unassigned

---

## Context

Spec §1 root causes 4 **and 7**, §2 "Layer 3", §3 Module 4, §5 AC9 + AC9b.

This backend has two defects, and the second is worse than the one this
feature was opened for.

**(a) Thin payload.** `_publish_agy_event` (`google_coding.py:393-415`)
publishes the whole raw CLI event under one nested key: `{"agy_event": {...}}`.

**(b) Wrong wire format — the events never arrive.** Unlike the other four
dispatchers, `GoogleCodingDispatcher._publish_event`
(`google_coding.py:77-99`) does **not** construct a `DispatchEvent` and does
**not** XADD a single `"event"` field. It writes five flat fields
(`kind`, `run_id`, `node_id`, `timestamp`, `payload`-as-JSON-string).
`FlowStreamMultiplexer._envelope` (`streaming.py:497-506`) looks for
`fields["event"]`, does not find it, and falls into the "plain fields" branch
— so **every `agy` dispatch event reaches the console as
`event_kind="flow.unknown"`** with the raw field dict as its payload. The same
method also never calls `_apply_to_session_host`, so an `agy`-backed dispatch
contributes *nothing* to session state: no status, no `message_count`, no
`tool_use_count`.

Fixing (b) is the priority; (a) is the same treatment as its two siblings.

---

## Scope

- **Rewrite `GoogleCodingDispatcher._publish_event` (`google_coding.py:77`)
  to match the other four dispatchers**: build a `DispatchEvent`, call
  `_apply_to_session_host(event)`, and XADD `{"event": event.model_dump_json()}`.
  Preserve the existing `expire(stream_key, self.stream_ttl_seconds)` TTL
  behaviour and the swallow-and-warn error handling.
- Route that `_publish_event` through `normalize_payload`.
- Add `_extract_agy_display(event)` and publish its keys alongside the
  preserved raw `agy_event` in `_publish_agy_event` (`google_coding.py:393`).
- Accept `labels: Optional[DispatchLabels] = None` on
  `GoogleCodingDispatcher.dispatch` (`google_coding.py:100`), and bind/reset
  both it and the session host.
- Add tests, including a multiplexer round-trip proving `event_kind` is no
  longer `flow.unknown`.

**NOT in scope**: any other dispatcher; `streaming.py` (the multiplexer is
correct — this backend was the one out of line); console HTML.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` | MODIFY | `_publish_event` wire format + session-host fold, extractor, `labels` kwarg |
| `packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py` | CREATE or MODIFY | wire-format + extraction tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# The CORRECT pattern to copy — verified: dispatchers/claude.py:50 and _shared.py:19
from parrot.flows.dev_loop.models import DispatchEvent
from parrot.flows.dev_loop.dispatchers._shared import (
    _SESSION_HOST_CTX, _apply_to_session_host,
    bind_labels, normalize_payload, summarize_tool_input,
)
from parrot.flows.dev_loop.models import DispatchLabels
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py
class GoogleCodingDispatcher:                                 # line 41

    async def _publish_event(self, stream_key: str, *, kind: str,
                             run_id: str, node_id: str,
                             payload: Dict[str, Any]) -> None:# line 77
        try:                                                  # line 86
            r = await self._get_redis()                       # line 87
            data = {                                          # lines 88-94
                "kind": kind, "run_id": run_id, "node_id": node_id,
                "timestamp": str(time.time()),
                "payload": json.dumps(payload),
            }
            await r.xadd(stream_key, data)                    # line 95  ← NO "event" field
            await r.expire(stream_key, self.stream_ttl_seconds)  # line 96
        except Exception as exc:                              # line 97
            self.logger.warning(
                "Failed to publish dispatch event to Redis: %s", exc)  # 98-99

    async def dispatch(self, *, brief, profile: Any, output_model,
                       run_id, node_id, cwd,
                       session_host=None) -> T:               # line 100
        stream_key = f"flow:{run_id}:dispatch:{node_id}"      # line 112

    async def _publish_agy_event(self, stream_key, event: Dict[str, Any],
                                 run_id, node_id) -> None:    # line 393
        event_type = event.get("type") or event.get("event")  # line 399
        kind = "dispatch.message"                             # line 401
        if event_type == "init":     kind = "dispatch.started"    # 402-403
        elif event_type == "result": kind = "dispatch.completed"  # 404-405
        elif event_type == "step_update":                     # line 406
            su = event.get("step_update", {})                 # line 407
            st = su.get("step_type") if isinstance(su, dict) else None  # 408
            if st == "tool_call":     kind = "dispatch.tool_use"      # 409-410
            elif st == "tool_response": kind = "dispatch.tool_result" # 411-412
        await self._publish_event(..., payload={"agy_event": event})  # 414

# THE REFERENCE IMPLEMENTATION to copy for _publish_event —
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py:1077-1114
        event = DispatchEvent(kind=kind, ts=time.time(), run_id=run_id,
                              node_id=node_id, payload=payload)
        _apply_to_session_host(event)                         # ~line 1097
        maxlen = max(1, self.stream_ttl_seconds // 60)        # line 1109
        fields = {"event": event.model_dump_json()}           # line 1110
        await redis_client.xadd(stream_key, fields, maxlen=maxlen,
                                approximate=True)             # line 1112

# THE CONSUMER that requires it — streaming.py:497-506
        raw_event = fields.get("event") if isinstance(fields, dict) else None
        if raw_event is None:
            return {..., "event_kind": fields.get("event_kind", "flow.unknown"), ...}
```

### Does NOT Exist

- ~~a bug in `FlowStreamMultiplexer`~~ — `streaming.py` is correct and is a
  declared Non-Goal of this spec. Do **not** "fix" the multiplexer to accept
  the flat-field shape; fix the dispatcher to emit the standard shape.
- ~~`_apply_to_session_host` being called anywhere in `google_coding.py`~~ —
  it is not imported or called in this file today. That is defect (b).
- ~~`DispatchEvent` being imported in `google_coding.py`~~ — it is not.
- ~~an `agy_event` consumer that depends on the flat field layout~~ — nothing
  reads these streams except `FlowStreamMultiplexer`, which wants
  `{"event": ...}`.
- ~~`maxlen` on the current xadd~~ — this dispatcher caps by `expire()` TTL
  instead. Keep the `expire()` call; adding `maxlen` is optional and must not
  replace it.

---

## Implementation Notes

### Order of work

Do the wire-format fix (b) **first** and prove it with the multiplexer
round-trip test, then layer the extractor (a) on top. That way a failure in
the harder half is isolated.

### `_publish_event` rewrite

Copy `claude.py:1077-1114`'s body shape, keeping this file's own Redis getter
and TTL policy:

```python
async def _publish_event(self, stream_key, *, kind, run_id, node_id, payload):
    event = DispatchEvent(
        kind=kind, ts=time.time(), run_id=run_id, node_id=node_id,
        payload=normalize_payload(kind, payload),
    )
    _apply_to_session_host(event)          # independent failure domain
    try:
        r = await self._get_redis()
        await r.xadd(stream_key, {"event": event.model_dump_json()})
        await r.expire(stream_key, self.stream_ttl_seconds)
    except Exception as exc:
        self.logger.warning("Failed to publish dispatch event to Redis: %s", exc)
```

Note the ordering from `claude.py`: the session-host fold happens **before**
the Redis round-trip, and a Redis failure must not skip it.

### Extractor sketch

```python
@staticmethod
def _extract_agy_display(event: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort display projection of one agy CLI stream event."""
```

| Shape | Extract |
|---|---|
| `type == "init"` | `model`, `cwd`, `session_id` if present |
| `step_update.step_type == "tool_call"` | `tool_name` from `step_update["tool_call"]["name"]` (probe alternatives); `tool_input` via `summarize_tool_input` |
| `step_update.step_type == "tool_response"` | `tool_name` when echoed; `is_error`; clamped `result_snippet` |
| `step_update.text_delta` | `text`, clamped |
| `type == "result"` | turns/duration/status from `event["result"]` (note `google_coding.py:374-381` already tolerates `result` arriving as a JSON **string**) |

`payload = {"agy_event": event}` then `payload.update(...)` — additive only.

### Key Constraints

- **`agy_event` must survive verbatim** (spec AC9).
- The extractor is total: `try/except Exception` → `{}`.
- `event["result"]` may be a JSON string, not a dict — the existing code at
  `google_coding.py:374-381` handles that; do the same, do not assume a dict.
- Bind labels **and** the session host in `dispatch()`, resetting both on
  every exit path.
- Telemetry never breaks a dispatch.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py:1077-1114` — the reference `_publish_event`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py:488-524` — the consumer that defines the required wire format.
- `packages/ai-parrot/tests/flows/dev_loop/test_dual_publish.py` — how session-host folding is asserted for the other backends.

---

## Acceptance Criteria

- [ ] **AC9b** — a published `agy` event, read back through
      `FlowStreamMultiplexer._envelope`, has its real `event_kind`
      (e.g. `"dispatch.tool_use"`), never `"flow.unknown"`.
- [ ] The XADD writes a single `"event"` field containing the JSON-encoded `DispatchEvent`.
- [ ] `_apply_to_session_host` is called for every published event, before the Redis round-trip, and a Redis failure does not skip it.
- [ ] The `expire(stream_key, self.stream_ttl_seconds)` TTL behaviour is preserved.
- [ ] A `step_update` / `tool_call` event yields `tool_name` and `tool_input`.
- [ ] `payload["agy_event"]` is the verbatim parsed event on every kind.
- [ ] Every published payload carries a non-empty `summary`.
- [ ] `event["result"]` arriving as a JSON string does not raise.
- [ ] `GoogleCodingDispatcher.dispatch` accepts `labels=` and binds/resets it on every exit path.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py

import json
import pytest

from parrot.flows.dev_loop.dispatchers.google_coding import GoogleCodingDispatcher
from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer


class TestAgyWireFormat:
    async def test_xadd_writes_a_single_event_field(self, fake_redis):
        """Defect (b): the flat-field layout the multiplexer cannot read."""
        d = GoogleCodingDispatcher(...)
        await d._publish_event("flow:r1:dispatch:development",
                               kind="dispatch.tool_use", run_id="r1",
                               node_id="development", payload={"agy_event": {}})
        fields = fake_redis.last_xadd_fields
        assert set(fields) == {"event"}
        assert json.loads(fields["event"])["kind"] == "dispatch.tool_use"

    def test_multiplexer_reads_the_real_event_kind(self, fake_redis):
        """AC9b — the end-to-end symptom: flow.unknown in the console."""
        mux = FlowStreamMultiplexer(fake_redis, run_id="r1")
        env = mux._envelope("flow:r1:dispatch:development",
                            fake_redis.last_xadd_fields, ts=1.0)
        assert env["event_kind"] == "dispatch.tool_use"
        assert env["event_kind"] != "flow.unknown"

    async def test_session_host_is_folded(self, session_host):
        """Defect (b), second half: agy contributed nothing to session state."""
        ...
        assert session_host.state.nodes["development"].dispatch.tool_use_count == 1

    async def test_redis_failure_still_folds_session_host(self, broken_redis, session_host):
        ...


class TestAgyEventExtraction:
    def test_tool_call_yields_name_and_input(self):
        d = GoogleCodingDispatcher(...)
        out = d._extract_agy_display({
            "type": "step_update",
            "step_update": {"step_type": "tool_call",
                            "tool_call": {"name": "read_file",
                                          "args": {"path": "src/a.py"}}}})
        assert out["tool_name"] == "read_file"
        assert "a.py" in out["tool_input"]

    def test_text_delta_yields_text(self):
        d = GoogleCodingDispatcher(...)
        out = d._extract_agy_display({
            "type": "step_update", "step_update": {"text_delta": "hi"}})
        assert out["text"] == "hi"

    def test_result_as_json_string_does_not_raise(self):
        d = GoogleCodingDispatcher(...)
        assert isinstance(
            d._extract_agy_display({"type": "result", "result": '{"turns": 3}'}),
            dict)

    def test_raw_event_preserved(self, captured_events):
        ...
```

---

## Agent Instructions

1. **Read the spec** — §1 root causes 4 **and 7**, §2 "Layer 3", §3 Module 4, §5 AC9/AC9b, §1 Non-Goals (the multiplexer is off-limits).
2. **Check dependencies** — TASK-2723 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — read `google_coding.py:77-99`, `claude.py:1077-1114` and `streaming.py:488-524` side by side before editing. The whole task is making the first match the second so the third works.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** — wire format first, extractor second.
6. **Verify** all acceptance criteria, AC9b especially.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: Fixed the priority defect (b) first: `_publish_event` now builds a
`DispatchEvent`, calls `_apply_to_session_host(event)` BEFORE the Redis
round-trip (independent failure domain, mirroring `claude.py:1077-1114`
exactly), and XADDs a single `{"event": event.model_dump_json()}` field
instead of the five flat fields — proven by a multiplexer round-trip test
using the real `FlowStreamMultiplexer._fields_to_envelope` (the task's
Codebase Contract named this method `_envelope`; it is `_fields_to_envelope`
in the current codebase — corrected here, no behavior difference). Kept the
`expire(stream_key, self.stream_ttl_seconds)` TTL call. Then layered
defect (a): `_extract_agy_display(event)` handles `init`
(`model`/`cwd`/`session_id`), `step_update.tool_call`/`tool_response`
(`tool_name`/`tool_input`/`is_error`/`result_snippet`), `text_delta`, and a
terminal `result` (tolerating `result` as a JSON string, matching the
existing tolerance at `google_coding.py:~375`). `dispatch()` accepts
`labels: Optional[DispatchLabels] = None`, bound/reset alongside
`_SESSION_HOST_CTX`. 9 new tests added (including the AC9b multiplexer
round-trip and a session-host-survives-Redis-failure test); all 13 tests in
`test_google_coding_dispatcher.py` pass; full `dev_loop` suite green (same 3
pre-existing unrelated failures in `test_recovery_lifecycle.py`).

**Deviations from spec**: `FlowStreamMultiplexer`'s field-decoding method is
`_fields_to_envelope`, not `_envelope` as the Codebase Contract stated —
verified stale, corrected in the test.
