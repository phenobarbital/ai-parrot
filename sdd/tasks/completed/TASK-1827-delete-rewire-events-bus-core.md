# TASK-1827: Delete bus core (`evb.py` + `bus/`) and minimize `events/__init__.py`

**Feature**: FEAT-317 — Parrot EventBus Migration
**Spec**: `sdd/specs/parrot-eventbus-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1826
**Assigned-to**: unassigned

---

## Context

Module 2 of spec §3. The bus core (facade `evb.py` + entire `bus/` package)
was copied to `navigator-eventbus` in FEAT-312. This task **deletes** the
ai-parrot copy and reduces `parrot/core/events/__init__.py` to a minimal stub
(hard migration — no re-export of `EventBus` etc. from parrot). Consumers of
these symbols are rewired in TASK-1830–1833.

---

## Scope

- Delete `packages/ai-parrot/src/parrot/core/events/evb.py`.
- Delete `packages/ai-parrot/src/parrot/core/events/bus/` (entire directory:
  `core.py`, `envelope.py`, `converters.py`, `dlq.py`, `ingress_models.py`,
  `backends/`, `subscribers/`, `ingress/`, all `__init__.py`).
- Rewrite `parrot/core/events/__init__.py` to a minimal module that no longer
  re-exports `EventBus/Event/EventPriority/EventSubscription` from a local
  `evb`. It should keep a docstring pointing consumers to
  `navigator_eventbus`, and expose nothing bus-related (typed events remain
  reachable via `parrot.core.events.lifecycle`, untouched here).
- Confirm nothing INSIDE the surviving `parrot/core/events/` tree still
  imports the deleted modules at import time (lifecycle machinery imports are
  handled in TASK-1828; if `lifecycle/__init__.py` transitively fails, that is
  expected and fixed there — but verify the events package top-level import
  itself does not hard-fail on deleted `evb`).

**NOT in scope**: lifecycle machinery deletion (TASK-1828); hooks (TASK-1829);
rewiring external consumers in bots/clients/observability/server (TASK-1830+);
tests (TASK-1833).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/evb.py` | DELETE | facade moved to `navigator_eventbus.evb` |
| `packages/ai-parrot/src/parrot/core/events/bus/` | DELETE | entire dir moved to `navigator_eventbus` |
| `packages/ai-parrot/src/parrot/core/events/__init__.py` | MODIFY | minimal stub; drop bus re-exports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (target — where these symbols now live)

```python
# navigator-eventbus — VERIFIED present 2026-07-18:
from navigator_eventbus import (
    EventBus, Event, EventPriority, EventSubscription,
    EventEnvelope, Severity, BusCore, BusClosedError, BackpressureError,
    DLQHandler, IngressEnvelope,
)
from navigator_eventbus.backends import (
    MemoryBackend, RedisStreamsBackend, RedisPubSubBackend, TransportBackend,
)
from navigator_eventbus.subscribers import (
    NotificationSubscriber, AuditSubscriber, MetricsSubscriber,
)
```

### Current parrot source being deleted — VERIFIED 2026-07-18

```python
# packages/ai-parrot/src/parrot/core/events/__init__.py  (current)
from .evb import Event, EventBus, EventPriority, EventSubscription
__all__ = ["EventBus", "Event", "EventPriority", "EventSubscription"]

# bus/ package modules that import each other (all deleted together):
#   bus/core.py, bus/envelope.py, bus/converters.py, bus/dlq.py,
#   bus/ingress_models.py, bus/backends/{base,memory,redis_pubsub,redis_streams}.py,
#   bus/subscribers/{audit,metrics,notification}.py,
#   bus/ingress/{websocket,grpc}.py + bus/ingress/proto/
```

### Import sites that will break until later tasks rewire them (informational)

These are handled in TASK-1830–1833 — do NOT edit them here, just be aware:
- `autonomous/{evb,orchestrator,webhooks}.py`, `eval/runner.py`
  (import `parrot.core.events.EventBus` / `.evb`)
- `core/events/lifecycle/registry.py` (`TYPE_CHECKING` import of
  `parrot.core.events.evb.EventBus`) — fixed in TASK-1828 when registry is deleted.
- `core/hooks/manager.py` (`TYPE_CHECKING` import of `evb.EventBus`; lazy
  `bus.envelope.Severity`) — fixed in TASK-1829 when manager is deleted.

### Does NOT Exist

- ~~a compat shim re-exporting `EventBus` from `parrot.core.events`~~ — hard
  migration; this task removes such re-exports.
- ~~`parrot.core.events.bus` after this task~~ — deleted.

---

## Implementation Notes

### Key Constraints
- Use `git rm` for deletions so the removals are staged cleanly.
- Do NOT add a backward-compat re-export — spec §2 decision #2 (hard migration).
- Keep `parrot/core/events/lifecycle/` untouched in this task.

### References in Codebase
- Spec §2 "Import Rewiring Table" and §6 "Does NOT Exist".

---

## Acceptance Criteria

- [ ] `parrot/core/events/evb.py` does not exist.
- [ ] `parrot/core/events/bus/` does not exist.
- [ ] `parrot/core/events/__init__.py` no longer imports from `.evb` or `.bus`.
- [ ] `grep -rn "parrot.core.events.bus\|parrot.core.events.evb" packages/ai-parrot/src/parrot/core/events/__init__.py` → empty.
- [ ] `ruff check` clean on modified `__init__.py`.

---

## Test Specification

```bash
# After deletion (import of lifecycle may still fail until TASK-1828 — that is expected):
python -c "import parrot.core.events" 2>&1 | grep -qi "evb\|bus" && echo "FAIL: still references deleted bus" || echo "events top-level OK w.r.t. bus"
test ! -e packages/ai-parrot/src/parrot/core/events/evb.py && echo "evb.py deleted"
test ! -d packages/ai-parrot/src/parrot/core/events/bus && echo "bus/ deleted"
```

---

## Agent Instructions

1. Verify TASK-1826 is completed (dependency installed).
2. Verify the Codebase Contract.
3. Update index → `in-progress`.
4. Delete with `git rm`; minimize `__init__.py`.
5. Verify acceptance criteria; move to completed; update index; fill note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-20
**Notes**:
- Deleted `evb.py` and the entire `bus/` directory (23 files, ~4066 LOC)
  via `git rm`, matching the Codebase Contract's file list exactly
  (core, envelope, converters, dlq, ingress_models, backends/*,
  subscribers/*, ingress/{websocket,grpc,proto/*}).
- Rewrote `events/__init__.py` to a minimal docstring-only stub (no
  `EventBus`/`Event`/`EventPriority`/`EventSubscription` re-exports, no
  `__all__`) pointing consumers at `navigator_eventbus` — hard migration,
  no compat shim, per spec §2 decision #2.
- Verified: `evb.py` and `bus/` gone; `__init__.py` has zero references to
  `.evb`/`.bus`; `ruff check` clean; `import parrot.core.events` succeeds
  cleanly (the stub does not eagerly import `lifecycle`, so it does not
  hard-fail even though lifecycle/hooks rewiring — TASK-1828/1829 — hasn't
  happened yet).
- Left `parrot/core/events/lifecycle/` completely untouched, as scoped.
**Deviations from spec**: none.
