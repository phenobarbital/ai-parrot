# TASK-1828: Delete lifecycle machinery, rewire typed events + `lifecycle/__init__.py` facade

**Feature**: FEAT-317 — Parrot EventBus Migration
**Spec**: `sdd/specs/parrot-eventbus-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1827
**Assigned-to**: unassigned

---

## Context

Module 3 of spec §3 — the largest surface. The lifecycle **machinery**
(`base`, `trace`, `meta`, `registry`, `global_registry`, `provider`, `mixin`,
subscribers `logging`/`webhook`) was extracted to
`navigator_eventbus.lifecycle` in FEAT-313 (phase 2). This task deletes the
ai-parrot copies, rewires the **typed events** (which stay) to subclass the
package's `LifecycleEvent`, keeps `legacy_bridge.py`, `yaml_loader.py`, and
`OpenTelemetrySubscriber`, and rebuilds `lifecycle/__init__.py` as a
re-export facade preserving its full public surface.

---

## Preflight (BLOCKING)

`navigator_eventbus.lifecycle` did NOT exist as of 2026-07-18. Verify FEAT-313
delivered it and confirm the EXACT export paths before rewiring:

```bash
source .venv/bin/activate
python -c "from navigator_eventbus.lifecycle.base import LifecycleEvent"
python -c "from navigator_eventbus.lifecycle.trace import TraceContext"
python -c "from navigator_eventbus.lifecycle.registry import EventRegistry, AsyncSubscriber"
python -c "from navigator_eventbus.lifecycle.global_registry import get_global_registry, scope"
python -c "from navigator_eventbus.lifecycle.provider import EventProvider"
python -c "from navigator_eventbus.lifecycle.mixin import EventEmitterMixin"
python -c "from navigator_eventbus.lifecycle.meta import SubscriberErrorEvent"
python -c "from navigator_eventbus.lifecycle.subscribers.logging import LoggingSubscriber"
python -c "from navigator_eventbus.lifecycle.subscribers.webhook import WebhookSubscriber"
```
If any path differs from the above, update the Codebase Contract to the real
paths FIRST, then implement.

---

## Scope

- Delete from `parrot/core/events/lifecycle/`:
  `base.py`, `trace.py`, `meta.py`, `registry.py`, `global_registry.py`,
  `provider.py`, `mixin.py`, and `subscribers/logging.py`,
  `subscribers/webhook.py`.
- Rewire typed events (`events/{agent,client,flow,invoke,message,tool}.py` and
  `events/__init__.py`): change
  `from parrot.core.events.lifecycle.base import LifecycleEvent`
  → `from navigator_eventbus.lifecycle.base import LifecycleEvent`.
  Everything else in these files stays.
- Rewire `legacy_bridge.py`: `EventRegistry`/base imports → package; keep
  its dependency on local typed event `AgentStatusChangedEvent`.
- Rewire `yaml_loader.py`: `LifecycleEvent`/`EventRegistry` from package; keep
  the parrot-specific event-name table; delegate to the package's wiring
  engine (verify FEAT-313 exposed it — likely
  `navigator_eventbus.lifecycle.yaml_loader`; if the engine was NOT moved,
  keep the local engine but source `LifecycleEvent`/`EventRegistry` from the
  package).
- Rewire `subscribers/opentelemetry.py`: `LifecycleEvent` +`EventRegistry`
  from package; typed events from local `..events`.
- Rebuild `lifecycle/__init__.py` as a facade: re-export the machinery from
  `navigator_eventbus.lifecycle`, the typed events from local `.events`, and
  the three surviving subscriber names (`LoggingSubscriber`,
  `WebhookSubscriber` from the package; `OpenTelemetrySubscriber` local).
  **Preserve the full existing `__all__`** (see Contract).
- Rebuild `subscribers/__init__.py`: `OpenTelemetrySubscriber` local;
  `LoggingSubscriber`/`WebhookSubscriber` re-exported from package.

**NOT in scope**: bus core (TASK-1827); hooks (TASK-1829); external consumers
in bots/clients/observability/server (TASK-1830–1832); tests (TASK-1833).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../lifecycle/{base,trace,meta,registry,global_registry,provider,mixin}.py` | DELETE | moved to `navigator_eventbus.lifecycle` |
| `.../lifecycle/subscribers/{logging,webhook}.py` | DELETE | moved to package |
| `.../lifecycle/__init__.py` | MODIFY | re-export facade (machinery from pkg + local typed events + OTel) |
| `.../lifecycle/subscribers/__init__.py` | MODIFY | OTel local; logging/webhook from pkg |
| `.../lifecycle/events/{__init__,agent,client,flow,invoke,message,tool}.py` | MODIFY | `LifecycleEvent` import → package |
| `.../lifecycle/legacy_bridge.py` | MODIFY | registry/base import → package |
| `.../lifecycle/yaml_loader.py` | MODIFY | registry/base → package; keep name table; engine from pkg |
| `.../lifecycle/subscribers/opentelemetry.py` | MODIFY | base/registry → package; events local |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (target — PROJECTED, verify in Preflight)

```python
from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.trace import TraceContext
from navigator_eventbus.lifecycle.meta import SubscriberErrorEvent
from navigator_eventbus.lifecycle.registry import EventRegistry, AsyncSubscriber
from navigator_eventbus.lifecycle.global_registry import get_global_registry, scope
from navigator_eventbus.lifecycle.provider import EventProvider
from navigator_eventbus.lifecycle.mixin import EventEmitterMixin
from navigator_eventbus.lifecycle.subscribers.logging import LoggingSubscriber
from navigator_eventbus.lifecycle.subscribers.webhook import WebhookSubscriber
```

### Full public surface to preserve — VERIFIED current `lifecycle/__init__.py` 2026-07-18

The facade MUST keep re-exporting ALL of these (machinery from package, events
local, OTel local). Current eager imports:

```python
# machinery (→ package):
TraceContext, LifecycleEvent, SubscriberErrorEvent, EventRegistry,
AsyncSubscriber, get_global_registry, scope, EventProvider, EventEmitterMixin
# concrete events (STAY local — from parrot.core.events.lifecycle.events):
AgentInitializedEvent, AgentConfiguredEvent, ToolManagerReadyEvent,
AgentStatusChangedEvent, BeforeInvokeEvent, AfterInvokeEvent, InvokeFailedEvent,
BeforeClientCallEvent, AfterClientCallEvent, ClientCallFailedEvent,
ClientStreamChunkEvent, BeforeToolCallEvent, AfterToolCallEvent,
ToolCallFailedEvent, MessageAddedEvent, FlowStartedEvent, FlowCompletedEvent,
NodeStartedEvent, NodeCompletedEvent, NodeFailedEvent, NodeSkippedEvent
# subscribers:
LoggingSubscriber (→ package), OpenTelemetrySubscriber (LOCAL),
WebhookSubscriber (→ package)
```

### Typed-event source files (STAY) — VERIFIED 2026-07-18

```python
# each currently starts with:  from parrot.core.events.lifecycle.base import LifecycleEvent
#   events/agent.py:11, events/client.py:14, events/flow.py:18,
#   events/invoke.py:10, events/message.py:8, events/tool.py:8
# events/__init__.py assembles the taxonomy (no base import to change there,
#   but verify the TYPE_CHECKING line at :7).
```

### Files that STAY untouched-in-logic

```python
# legacy_bridge.py:20   from parrot.core.events.lifecycle.events import AgentStatusChangedEvent  (KEEP local)
# legacy_bridge.py:23   TYPE_CHECKING import of EventRegistry  → package
# yaml_loader.py:26-28  LifecycleEvent, EventRegistry (→ package); events import (KEEP local table)
# subscribers/opentelemetry.py:22-23  LifecycleEvent (→ pkg), events (KEEP local); :36 EventRegistry (→ pkg)
```

### Does NOT Exist

- ~~`navigator_eventbus.lifecycle.events`~~ — typed events STAY in parrot; the
  package only ships the base `LifecycleEvent`, not parrot's taxonomy.
- ~~a parrot-local `EventRegistry`/`TraceContext`/`EventEmitterMixin` after this task~~ — deleted; sourced from package.
- ~~`OpenTelemetrySubscriber` in the package~~ — it depends on parrot typed events, so it STAYS local.

---

## Implementation Notes

### Key Constraints
- Delete with `git rm`.
- The facade `__init__.py` is the highest-risk file: a single missing symbol
  breaks ~15 downstream modules that use `from parrot.core.events.lifecycle import X`.
  Cross-check the new `__all__` against the current one — it must be a superset-or-equal.
- Preserve `if TYPE_CHECKING:` guards when changing import sources.
- `yaml_loader`: if FEAT-313 did NOT move the wiring engine, keep the engine
  local and only rewire the machinery imports; note the deviation.

### References in Codebase
- Spec §2 "Import Rewiring Table", §3 Module 3, §7 "Known Risks" (facade surface).

---

## Acceptance Criteria

- [ ] The 9 machinery files listed are deleted.
- [ ] `from parrot.core.events.lifecycle import EventRegistry, LifecycleEvent, TraceContext, EventEmitterMixin, scope` resolves.
- [ ] `from parrot.core.events.lifecycle import BeforeInvokeEvent, ClientStreamChunkEvent, NodeSkippedEvent` resolves.
- [ ] `from parrot.core.events.lifecycle import LoggingSubscriber, WebhookSubscriber, OpenTelemetrySubscriber` resolves.
- [ ] `issubclass(BeforeInvokeEvent, navigator_eventbus.lifecycle.base.LifecycleEvent)` is `True`.
- [ ] New `__all__` ⊇ old `__all__` (no dropped public names).
- [ ] `ruff check` clean on all modified files.

---

## Test Specification

```bash
python - <<'PY'
from parrot.core.events.lifecycle import (
    EventRegistry, LifecycleEvent, TraceContext, EventEmitterMixin, scope,
    BeforeInvokeEvent, ClientStreamChunkEvent, NodeSkippedEvent,
    LoggingSubscriber, WebhookSubscriber, OpenTelemetrySubscriber,
)
from navigator_eventbus.lifecycle.base import LifecycleEvent as PkgLE
assert issubclass(BeforeInvokeEvent, PkgLE)
assert LifecycleEvent is PkgLE
print("lifecycle facade OK")
PY
```

---

## Agent Instructions

1. Run **Preflight**; if lifecycle paths differ, fix the Contract first.
2. Verify TASK-1827 completed.
3. Update index → `in-progress`.
4. Delete machinery; rewire events/bridge/loader/otel; rebuild both `__init__.py`.
5. Verify acceptance criteria; move to completed; update index; fill note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-20
**Notes**:
- Preflight: all 9 projected `navigator_eventbus.lifecycle.*` import paths
  verified to resolve exactly as specified in the Contract; also confirmed
  `navigator_eventbus.lifecycle.yaml_loader` exposes the generic engine
  (`wire_events`, `register_event_names`, injectable `EVENT_CLASSES`) —
  FEAT-313 did move the wiring engine, so `yaml_loader.py` delegates fully
  rather than keeping a local engine.
- Deleted the 9 machinery files (`base`, `trace`, `meta`, `registry`,
  `global_registry`, `provider`, `mixin`, `subscribers/{logging,webhook}.py`)
  via `git rm`.
- Rewired the 6 typed-event files (`events/{agent,client,flow,invoke,
  message,tool}.py`) — single-line `LifecycleEvent` import change each,
  nothing else touched. `events/__init__.py` needed no change (no direct
  `LifecycleEvent`/machinery import there — it only re-exports from its
  own local submodules).
- Rewired `legacy_bridge.py` (TYPE_CHECKING `EventRegistry` import) and
  `subscribers/opentelemetry.py` (`LifecycleEvent` + TYPE_CHECKING
  `EventRegistry` imports) — typed-event imports stayed local in both, as
  specified.
- Rewrote `yaml_loader.py`: kept the parrot event-name table (`EVENT_CLASSES`,
  same 15 classes as before) but now registers it via the package's
  `register_event_names()` and re-exports the package's `wire_events`
  directly — dropped the local `_resolve`/`_wire_handler`/`_wire_provider`/
  `_make_where` implementations entirely (now live only in the package).
  `registry/registry.py`'s `from parrot.core.events.lifecycle.yaml_loader
  import wire_events` call site needed no change, per spec.
- Rebuilt `lifecycle/__init__.py` as a re-export facade: machinery from
  `navigator_eventbus.lifecycle`, typed events + `OpenTelemetrySubscriber`
  local, `LoggingSubscriber`/`WebhookSubscriber` from the package. New
  `__all__` is identical to the previous one (same 30 names) — no dropped
  symbols.
- Rebuilt `subscribers/__init__.py` analogously (OTel local; logging/webhook
  from package).
- Verified: all Test Specification assertions pass (`lifecycle facade OK`,
  `issubclass(BeforeInvokeEvent, PkgLE)` True, `LifecycleEvent is PkgLE`
  True); `ruff check` clean on every modified file (one pre-existing,
  out-of-scope `F401 Optional unused` in `events/agent.py` predates this
  migration — left untouched per "mechanical rewiring only, no unrelated
  fixes").
- Heads-up for TASK-1833 (test migration): `tests/unit/registry/
  test_events_yaml.py` imports `_resolve`/`_make_where` directly from
  `parrot.core.events.lifecycle.yaml_loader` — those private helpers no
  longer exist there (moved to the package); that test file will need to
  import them from `navigator_eventbus.lifecycle.yaml_loader` instead.
**Deviations from spec**: none — the yaml_loader wiring-engine delegation
happened via full re-export (not a hybrid local/package split) because
FEAT-313 did deliver the engine as specified.
