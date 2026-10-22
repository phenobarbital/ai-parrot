# TASK-4553: Event fan-out wiring: attach_bus + forward_to_bus over durable Streams

**Feature**: FEAT-710 — Parrot telemetry event fan-out
**Spec**: `sdd/specs/parrot-telemetry-event-fanout.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-4546, TASK-4547
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. Native fan-out over navigator-eventbus FEAT-711 (`../navigator-eventbus/sdd/specs/durable-lifecycle-fanout.spec.md`): `EventRegistry.attach_bus()` + serializer hook, `EventBus(transport="streams", publish_only=True, outbox=...)`. Dedicated bus instance, never the autonomous orchestrator's (§8 Q2). **Do not start this task until the FEAT-711 release is on PyPI.**

---

## Scope

- Bump `navigator-eventbus` in `packages/ai-parrot/pyproject.toml` to the FEAT-711 release (0.4.0).
- Create `observability/fanout.py` with `FORWARD_DENYLIST`, `FORWARDED_EVENTS`, `redact_usage_event`, `setup_event_fanout`, `shutdown_event_fanout`.
- Wire it in `bootstrap.py` when `PARROT_EVENT_FANOUT_ENABLED=true`; call `shutdown_event_fanout()` from `shutdown_usage_recording()`.
- Fail at startup when `PARROT_EVENT_FANOUT_OUTBOX_DIR` is unset/not writable, or when an injected bus is not Streams + `publish_only`.
- Call `ensure_shared_cost_calculator()` so `cost_usd` is filled even with local observability off.
- Document the env vars in `observability/README.md`... `# FILL IN` if README is not in the file list, skip.
- Write tests.

**NOT in scope**: any change in navigator-eventbus (FEAT-711).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/fanout.py` | CREATE | Fan-out wiring |
| `packages/ai-parrot/src/parrot/observability/bootstrap.py` | MODIFY | Call setup/shutdown behind the flag |
| `packages/ai-parrot/pyproject.toml` | MODIFY | Bump navigator-eventbus pin |
| `packages/ai-parrot/tests/unit/observability/test_event_fanout.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

Verified against `origin/dev` @ `cf1888270` (2026-10-21). Re-run every `grep -c` before editing.

### Verified Imports
```python
from parrot.core.events.lifecycle import get_global_registry  # verified: observability/bootstrap.py:134-138
from parrot.core.events.lifecycle.events import (AfterInvokeEvent, InvokeFailedEvent, AfterClientCallEvent, ClientCallFailedEvent)  # verified: yaml_loader.py:33-47
from navigator_eventbus import EventBus  # verified: ai-parrot-server autonomous/orchestrator.py:31
from parrot.observability.cost import ensure_shared_cost_calculator  # created by TASK-4547
# FEAT-711 (navigator-eventbus >= 0.4.0, NOT in the installed 0.2.x/0.3.0): EventRegistry.attach_bus/detach_bus,
#   subscribe(..., forward_to_bus=True), EventBus(transport=, publish_only=, outbox=), BusSerializer
```

### Existing Signatures to Use
```python
# navigator_eventbus (FEAT-711 contract — verify against the released version before coding)
EventRegistry.attach_bus(bus, *, channel_prefix=None, serializer=None) -> None
EventRegistry.detach_bus() -> None
EventRegistry.subscribe(event_type, callback, *, where=None, forward_to_bus=False, bus_serializer=None) -> str
EventRegistry.unsubscribe(subscription_id) -> bool
EventBus(redis_url=None, use_redis=False, *, channel_prefix=None, backend=None, transport=None, publish_only=False, outbox=None, **bus_options)
# parrot: bootstrap.py ids = get_global_registry().add_provider(subscriber)  :138 ; shutdown_usage_recording() :186
# reference construction: ai-parrot-server autonomous/orchestrator.py:245-249
```

### Does NOT Exist
- ~~`LifecycleBusForwarder`~~ — dropped in spec rev 0.3; do not create
- ~~`EventRegistry.set_event_bus`~~ — the API is `attach_bus`
- ~~`TelemetryEvent` / BigQuery code~~ — lives in the external consumer

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/observability/fanout.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/observability/bootstrap.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/pyproject.toml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/observability/test_event_fanout.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/bootstrap.py#shutdown_usage_recording"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async-first; never block the event loop; `self.logger`, never `print`.
- Telemetry must never raise into the request path.
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Confirm the released navigator-eventbus exposes the FEAT-711 API (`python -c "from navigator_eventbus.lifecycle.registry import EventRegistry; EventRegistry.attach_bus"`) — *why*: this task is blocked on it; stop if absent.
2. Bump the pin — *why*: exclusive manifest edit.
3. Create `fanout.py`, wire `bootstrap.py`, write tests.

### `packages/ai-parrot/src/parrot/observability/fanout.py` (CREATE)
```python
"""FEAT-710 — fan-out of the four usage lifecycle events to a durable EventBus.

Native ``forward_to_bus`` on top of navigator-eventbus FEAT-711. ai-parrot only
publishes; the consumer (NVP-505) lives outside this package.
"""
from __future__ import annotations

import logging
import os
import socket
from typing import Any, Optional

from parrot.core.events.lifecycle import get_global_registry
from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent, AfterInvokeEvent, ClientCallFailedEvent, InvokeFailedEvent,
)

logger = logging.getLogger(__name__)

FORWARD_DENYLIST: frozenset[str] = frozenset({"error_message"})
FORWARDED_EVENTS: tuple[type, ...] = (AfterInvokeEvent, InvokeFailedEvent, AfterClientCallEvent, ClientCallFailedEvent)

_BUS: Any = None
_SUB_IDS: list[str] = []


def redact_usage_event(event: Any) -> Optional[dict[str, Any]]:
    """BusSerializer: ``to_dict()`` minus FORWARD_DENYLIST for FORWARDED_EVENTS; None for anything else."""
    if not isinstance(event, FORWARDED_EVENTS):
        return None
    return {k: v for k, v in event.to_dict().items() if k not in FORWARD_DENYLIST}


async def _noop(_event: Any) -> None:
    """Subscription callback; forwarding is done by the registry (forward_to_bus=True)."""


def setup_event_fanout(bus: Any = None) -> None:
    """Attach a dedicated Streams/publish-only bus to the global registry and add the four subscriptions. Idempotent."""
    global _BUS  # noqa: PLW0603
    if _BUS is not None:
        return
    # FILL IN: build the bus from PARROT_EVENT_FANOUT_REDIS_URL / _CHANNEL_PREFIX (default "parrot:events:") /
    #          _OUTBOX_DIR (required, writable → else raise RuntimeError) with transport="streams", publish_only=True,
    #          outbox=f"{dir}/{socket.gethostname()}-{os.getpid()}.db"; validate an injected bus is streams + publish_only — AC-2, AC-4
    # FILL IN: ensure_shared_cost_calculator() — AC-5
    registry = get_global_registry()
    registry.attach_bus(bus, serializer=redact_usage_event)
    for event_cls in FORWARDED_EVENTS:
        _SUB_IDS.append(registry.subscribe(event_cls, _noop, forward_to_bus=True))
    _BUS = bus
    logger.info("Event fan-out enabled (%d events)", len(FORWARDED_EVENTS))


async def shutdown_event_fanout() -> None:
    """Unsubscribe, detach the bus and close it (the outbox keeps undelivered rows on disk)."""
    # FILL IN: unsubscribe _SUB_IDS, registry.detach_bus(), await _BUS.close(), reset globals — AC-3
    raise NotImplementedError
```
**Why**: no forwarder class — the registry does the forwarding (spec rev 0.3); the serializer is the only redaction point.

### `packages/ai-parrot/src/parrot/observability/bootstrap.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'ids = get_global_registry().add_provider(subscriber)' bootstrap.py)
# FILL IN: call setup_event_fanout() when navconfig PARROT_EVENT_FANOUT_ENABLED is true, from a point reached on BOTH
#          the lightweight and the OTel path (the OTel path returns before :111) — AC-1; and await/schedule
#          shutdown_event_fanout() from shutdown_usage_recording() (:186) like the existing aclose pattern — AC-3
```

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '"navigator-eventbus>=0.2.1",' packages/ai-parrot/pyproject.toml)
# REPLACE :187 with the FEAT-711 release, e.g.:
    "navigator-eventbus>=0.4.0",
```

### `packages/ai-parrot/tests/unit/observability/test_event_fanout.py` (CREATE)
```python
"""FEAT-710 TASK-4553 — event fan-out wiring."""
from parrot.core.events.lifecycle.events import AfterClientCallEvent, BeforeInvokeEvent, ClientCallFailedEvent
from parrot.observability.fanout import redact_usage_event


def test_redaction_drops_error_message() -> None:
    payload = redact_usage_event(ClientCallFailedEvent(error_message="secret prompt", tenant="t1"))
    assert payload is not None and "error_message" not in payload and payload["tenant"] == "t1"


def test_other_events_are_skipped() -> None:
    assert redact_usage_event(BeforeInvokeEvent()) is None
    assert redact_usage_event(AfterClientCallEvent()) is not None


def test_setup_idempotent_and_flag_off() -> None:
    # FILL IN: fake bus (streams+publish_only); two setups → 4 subscriptions; one publish per event;
    #          flag off → no attach — AC-1, AC-3
    raise NotImplementedError


def test_bad_bus_or_outbox_dir_fails_fast() -> None:
    # FILL IN — AC-2, AC-4
    raise NotImplementedError
```

### FILL IN checklist
- [ ] Bus construction + validation — AC-2, AC-4
- [ ] Shared calculator — AC-5
- [ ] shutdown — AC-3
- [ ] bootstrap hook on both paths — AC-1
- [ ] Test bodies

---

## Acceptance Criteria

- [ ] Flag off (default): no bus attached, no subscriptions; behavior identical to today.
- [ ] Flag on: the four events reach the bus on `<prefix>.<EventClass>` without `error_message`; other events never forwarded.
- [ ] Setup is idempotent (one publish per event); shutdown unsubscribes, detaches and closes.
- [ ] Missing/unwritable `PARROT_EVENT_FANOUT_OUTBOX_DIR`, or an injected bus that is not Streams + `publish_only`, fails at startup.
- [ ] `cost_usd` is populated with observability off (shared calculator ensured).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/observability/test_event_fanout.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_bootstrap.py -q`

---

## Test Specification

See the test-file block in the Implementation Blueprint; every `FILL IN` test must pass.

---

## Agent Instructions

1. Work in the feature worktree, never on `dev`:
   `python -m scripts.sdd.ensure_worktree --slug parrot-telemetry-event-fanout --feature-id FEAT-710`
2. Read the spec `sdd/specs/parrot-telemetry-event-fanout.spec.md` (rev 0.4) for context.
3. Check that every `Depends-on` task is `done` in `sdd/tasks/index/parrot-telemetry-event-fanout.json`.
4. Verify the Codebase Contract before writing code (re-run `grep -c` on every anchor); fix the contract first if it drifted.
5. Set this task `in-progress` in the index and commit only that file.
6. Implement from the Blueprint, completing every `# FILL IN:`; never change a fixed signature or path.
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
8. Commit only the files listed in this task.
9. Close with `scripts/sdd/close_task.sh TASK-4553 parrot-telemetry-event-fanout verified`.
10. Fill in the Completion Note and commit the staged SDD state.

---

## Completion Note



**Completed by**: sdd-worker orchestrator (coder: codex/gpt-5.6-sol, attempt 2; attempt 1 terra empty_delivery while navigator-eventbus 0.3.0 was installed)
**Date**: 2026-10-22
**Notes**: Merged, 8 unit tests + merge-tier green.

**Deviations from spec**: none
