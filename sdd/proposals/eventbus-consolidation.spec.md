---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: EventBus Consolidation — schema_version, default-capable hooks routing, broker-port closure, ai-parrot migration

**Feature ID**: FEAT-320 <!-- provisional; reconcile with tracker — broker port is FEAT-316 in docstrings but FEAT-318 per author -->
**Date**: 2026-07-20
**Author**: Jesus (phenobarbital) + Claude
**Status**: draft
**Target version**: navigator-eventbus 0.2.0 / ai-parrot next minor

> **Cross-repo spec**: Modules 1–3 land in `navigator-eventbus`; Module 4 lands in
> `ai-parrot`. Module 4 MUST NOT start until Modules 1–2 are released (tagged),
> so ai-parrot migrates once against the final envelope contract.

---

## 1. Motivation & Business Requirements

### Problem Statement

The extraction of the bus core into `navigator-eventbus` succeeded (envelope, BusCore,
DLQ, Streams backend, neutrality tests), but four consolidation items remain open,
and one of them is actively dangerous: **two divergent copies of the bus core exist**
(`navigator_eventbus/*` and `ai-parrot:parrot/core/events/bus/*`) — any fix applied
to one silently rots in the other. Additionally, the wire format lacks versioning
before persistent Redis Streams traffic accumulates, `HookManager.route_to_bus`
remains opt-in (hooks bypass the bus by default, contradicting the brainstorm's
"bus as app-wide fabric" goal), and the FEAT-316/318 broker port needs formal
verification closure (tightened neutrality guard, exports, extras).

### Goals

- G1: Every serialized envelope carries `schema_version`; deserialization tolerates known versions and fails loudly on unknown ones — BEFORE production Streams traffic exists.
- G2: `HookManager` routes hook events to the bus by default when a bus is attached (default-capable), preserving the orchestrator-callback path.
- G3: Broker port (FEAT-316/318) formally closed: zero `navigator.*` references anywhere, neutrality test tightened, public exports and extras verified.
- G4: `ai-parrot` depends on `navigator-eventbus` (pinned release), `parrot/core/events/bus/` is **deleted**, and all imports/tests pass against the external package. Single source of truth restored.

### Non-Goals (explicitly out of scope)

- Lifecycle extraction to navigator-eventbus (`lifecycle.*` namespace — reserved Phase 2, separate spec).
- navigator-auth ledger/outbox integration (spec 6 of the brainstorm decomposition).
- Flowtask adoption (spec 7).
- New backends (NATS/Kafka) or envelope field additions beyond `schema_version`.
- Removing navconfig/asyncdb from core dependencies — **resolved: accepted as-is.** navconfig is a lightweight config lib (dotenv + Redis + HashiCorp Vault readers, configurable conf.py); the earlier "dependency weight" concern was mistaken.

---

## 2. Architectural Design

### Overview

Four independent, small-surface changes ordered by risk:

1. **Envelope versioning** (M1): add `schema_version: int = 1` as the last field of
   `EventEnvelope`; `to_dict()` emits it; `from_dict()` accepts absent (→ 1, legacy),
   known versions, and raises `UnsupportedSchemaVersion` on higher-than-supported.
   Constant `ENVELOPE_SCHEMA_VERSION = 1` in `envelope.py`.
2. **Default-capable hooks routing** (M2): `HookManager(route_to_bus=None)` — `None`
   means "auto": route to bus iff a bus is attached. Explicit `False` preserves
   today's opt-out; explicit `True` today's opt-in. Deprecation note in docstring for
   relying on implicit OFF.
3. **Broker-port closure** (M3): verification + tightening, minimal code.
4. **ai-parrot migration** (M4): dependency swap, shim imports, delete internal copy.

### Component Diagram

```
ai-parrot (M4)                      navigator-eventbus (M1–M3)
  parrot/core/events/evb.py  ──→  navigator_eventbus.evb.EventBus (facade)
  parrot/core/events/bus/ ✂ DELETED     │
  lifecycle registry (stays) ──emit──→  BusCore ──→ backends (Memory / Streams / PubSub)
  hooks (stays, thin) ───────────────→  HookManager(route_to_bus: auto) ──→ bus
                                        EventEnvelope(schema_version=1)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `EventEnvelope` | extends | new trailing field, default `1` — frozen/slots preserved |
| `serialization.py` | modifies | version-aware `from_dict` path |
| `RedisStreamsBackend` | none (transitive) | serializes via `to_dict()`; no code change expected — verify only |
| `HookManager` | modifies | tri-state `route_to_bus` |
| `tests/test_neutrality.py` | modifies | drop the `navigator.brokers` allowance clause |
| ai-parrot `parrot/core/events/__init__.py` | rewrites | re-export from `navigator_eventbus` |
| ai-parrot `pyproject.toml` | extends | `navigator-eventbus>=0.2.0,<0.3` |

### Data Models

```python
# envelope.py — final field layout (frozen=True, slots=True preserved)
ENVELOPE_SCHEMA_VERSION: int = 1

@dataclass(frozen=True, slots=True)
class EventEnvelope:
    ...existing fields unchanged...
    schema_version: int = ENVELOPE_SCHEMA_VERSION   # MUST be last (positional compat)

class UnsupportedSchemaVersion(ValueError):
    """Raised by from_dict() when data['schema_version'] > supported."""
```

### New Public Interfaces

```python
# hooks/manager.py
class HookManager:
    def __init__(self, *, route_to_bus: Optional[bool] = None) -> None: ...
    # None → auto (route iff bus attached); True/False → explicit

# envelope.py
ENVELOPE_SCHEMA_VERSION  # exported in __init__.py
UnsupportedSchemaVersion  # exported in __init__.py
```

---

## 3. Module Breakdown

### Module 1: Envelope schema_version
- **Path**: `src/navigator_eventbus/envelope.py`, `src/navigator_eventbus/serialization.py`, `src/navigator_eventbus/__init__.py`
- **Responsibility**:
  - Add `ENVELOPE_SCHEMA_VERSION = 1`, `schema_version` field (last position, default 1), `UnsupportedSchemaVersion`.
  - `to_dict()` emits `"schema_version"`.
  - `from_dict()`: missing key → 1 (legacy envelopes already in Streams); `1` → parse; `> 1` → raise `UnsupportedSchemaVersion` with topic + event_id in message.
  - Export both new names; verify converters (`converters.py`) pass version through untouched.
- **Depends on**: nothing.

### Module 2: HookManager default-capable routing
- **Path**: `src/navigator_eventbus/hooks/manager.py`
- **Responsibility**:
  - `route_to_bus: Optional[bool] = None`; internal `_effective_route_to_bus()` → `self._route_to_bus if self._route_to_bus is not None else (self._event_bus is not None)`.
  - Callback path (`set_event_callback`) unchanged and still fires alongside bus routing (dual-emit stays; bus is additive, never replaces the callback in this spec).
  - Log at INFO once on first auto-activation ("route_to_bus auto-enabled: bus attached").
- **Depends on**: nothing.

### Module 3: FEAT-316/318 broker-port closure (verify + tighten)
- **Path**: `tests/test_neutrality.py`, `src/navigator_eventbus/brokers/__init__.py`, `pyproject.toml`, tracker
- **Responsibility** (checklist — most already verified true on `main@f523357`, re-assert in CI):
  - [x] Zero `from/import navigator.` in `src/` (verified 2026-07-20; keep as regression test).
  - [ ] **Tighten** `test_navigator_brokers_lazy_imports_are_confined_to_hooks_brokers` → replace with `test_no_navigator_imports_anywhere` (the phase-1 allowance is obsolete now the port landed).
  - [ ] `brokers/__init__.py` exports `BaseConnection`, `BrokerProducer`, `BrokerConsumer`, `BaseWrapper`, `DataSerializer` + per-broker classes; verify against actual `__init__` contents.
  - [ ] Extras audit: `rabbitmq` extra installs `aiormq>=6.7`; `sqs` extra exists or SQS deps documented; `brokers` meta-extra pulls the union. Fix pyproject if any gap.
  - [ ] Broker tests (`tests/brokers/`) run in CI without `navigator` installed (add a CI job or tox env with bare deps to prove it).
  - [ ] Reconcile FEAT numbering: docstrings say FEAT-316 (TASK-1813..1817), tracker says FEAT-318 — align docstrings or tracker, one PR.
- **Depends on**: nothing.

### Module 4: ai-parrot migration to navigator-eventbus (repo: ai-parrot)
- **Path**: `packages/ai-parrot/pyproject.toml`, `packages/ai-parrot/src/parrot/core/events/`, `packages/ai-parrot/src/parrot/core/hooks/`
- **Responsibility**:
  - Add dependency `navigator-eventbus>=0.2.0,<0.3` (release containing M1+M2 first — hard ordering constraint).
  - **Delete** `parrot/core/events/bus/` entirely (backends, core.py, dlq.py, envelope.py, converters.py, ingress/, ingress_models.py, subscribers/).
  - Rewrite `parrot/core/events/evb.py` as a thin shim: `from navigator_eventbus.evb import EventBus, Event, EventPriority, EventSubscription` (+ deprecation docstring pointing to the package). Alternatively delete evb.py and re-export from `events/__init__.py` — decide in task, shim preferred for grep-ability.
  - Rewrite internal imports: `parrot.core.events.bus.envelope` → `navigator_eventbus.envelope`, etc. (`grep -rn "core.events.bus" packages/ai-parrot/src` must return zero after).
  - `parrot/core/hooks/`: keep parrot-specific hooks (jira/github/imap/sharepoint/messaging/whatsapp/matrix/postgres/file_upload — domain integrations); base classes (`BaseHook`, `HookManager`, broker hooks, scheduler, watchdog, models) now import from `navigator_eventbus.hooks.*`. Delete parrot copies that are pure duplicates; keep only subclasses adding parrot behavior.
  - Lifecycle registry `forward_to_bus` and `HookManager.set_event_bus` call sites: regression-test unchanged behavior (existing tests `test_dual_emit_integration`, hooks tests must pass without edits beyond imports).
  - TOML `[bus]` config keys (`BUS_WORKERS`, `BUS_QUEUE_SIZE`, ...) verified to flow through the external facade identically.
  - Guard test in ai-parrot: `test_no_internal_bus_copy` — asserts `parrot/core/events/bus/` does not exist and no module defines a class named `BusCore`/`EventEnvelope` under `parrot.*`.
- **Depends on**: Modules 1–2 released.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_envelope_schema_version_default` | M1 | New envelope has `schema_version == 1`; present in `to_dict()` |
| `test_from_dict_missing_version_is_legacy_v1` | M1 | Dict without key parses, version = 1 |
| `test_from_dict_unknown_version_raises` | M1 | `schema_version: 2` → `UnsupportedSchemaVersion` incl. topic/event_id in message |
| `test_frozen_slots_preserved_after_field_add` | M1 | dataclass still frozen+slots; positional construction with old arity unaffected |
| `test_converters_preserve_schema_version` | M1 | legacy Event/HookEvent → envelope carries version 1 |
| `test_route_to_bus_auto_with_bus` | M2 | `route_to_bus=None` + bus attached → events reach bus topic `hooks.*` |
| `test_route_to_bus_auto_without_bus` | M2 | `route_to_bus=None`, no bus → callback-only, no error |
| `test_route_to_bus_explicit_false_overrides_bus` | M2 | `False` + bus attached → NOT routed |
| `test_callback_still_fires_when_routed` | M2 | dual-emit: callback and bus both receive |
| `test_no_navigator_imports_anywhere` | M3 | tightened neutrality: zero `navigator.` refs in all of `src/` |
| `test_brokers_public_exports` | M3 | `brokers/__init__.py` exposes the documented names |
| `test_no_internal_bus_copy` | M4 (ai-parrot) | `parrot/core/events/bus/` absent; no `parrot.*` BusCore/EventEnvelope |
| `test_evb_shim_reexports` | M4 (ai-parrot) | `from parrot.core.events.evb import EventBus` is `navigator_eventbus.evb.EventBus` |

### Integration Tests

| Test | Description |
|---|---|
| `test_streams_roundtrip_with_version` | XADD → XREADGROUP → `from_dict` preserves `schema_version`; mixed legacy (no key) + v1 messages in one stream both consumable |
| `test_hooks_to_bus_default_e2e` | Real hook fires → HookManager (auto) → BusCore → subscriber receives envelope on `hooks.<type>.<event>` |
| `test_parrot_lifecycle_dual_emit_external_pkg` | (ai-parrot) lifecycle `forward_to_bus=True` → external-package bus receives — existing test green post-migration |
| `test_brokers_ci_without_navigator` | CI env without `navigator` installed: brokers test suite passes |

### Test Data / Fixtures

```python
@pytest.fixture
def legacy_envelope_dict():
    """Wire dict as produced BEFORE this spec (no schema_version key)."""
    return {
        "topic": "order.created", "payload": {"id": 1},
        "event_id": "…uuid…", "timestamp": "2026-07-01T10:00:00+00:00",
        "source": "test", "severity": 20, "priority": 5,
        "correlation_id": None, "trace_context": None, "metadata": {},
    }

@pytest.fixture
def future_envelope_dict(legacy_envelope_dict):
    return {**legacy_envelope_dict, "schema_version": 99}
```

---

## 5. Acceptance Criteria

- [ ] M1: all envelope/serialization unit tests pass; `ENVELOPE_SCHEMA_VERSION` and `UnsupportedSchemaVersion` exported from package root.
- [ ] M1: Streams round-trip test proves legacy (version-less) and v1 messages coexist in one stream.
- [ ] M2: hooks route to bus by default when a bus is attached; explicit `False` opts out; callback path untouched (all pre-existing HookManager tests pass unmodified except constructor kwargs).
- [ ] M3: tightened neutrality test in CI; extras audit closed (pyproject diff or "no gap" finding recorded); FEAT-316/318 numbering reconciled.
- [ ] M4: `grep -rn "core.events.bus" packages/ai-parrot/src` → empty; `parrot/core/events/bus/` deleted; ai-parrot full test suite green with `navigator-eventbus` from PyPI (not a path/git dep).
- [ ] M4: guard test `test_no_internal_bus_copy` in ai-parrot CI prevents regression.
- [ ] No breaking changes: `EventBus.emit/subscribe/on/publish` signatures identical in both repos; `EventEnvelope` positional construction with pre-spec arity still valid.
- [ ] navigator-eventbus `0.2.0` tagged and published before the ai-parrot PR merges.

---

## 6. Codebase Contract

> Verified on `navigator-eventbus@f523357` (main, 2026-07-20) and
> `ai-parrot@47a8ade` (main, 2026-07-20).

### Verified Imports

```python
from navigator_eventbus.envelope import EventEnvelope, Severity        # src/navigator_eventbus/__init__.py:19
from navigator_eventbus.evb import Event, EventBus, EventPriority, EventSubscription  # __init__.py:20
from navigator_eventbus.core import BackpressureError, BusClosedError, BusCore        # __init__.py:17
from navigator_eventbus.dlq import DLQHandler                           # __init__.py:18
from navigator_eventbus.ingress_models import IngressEnvelope           # __init__.py:21
from navigator_eventbus.hooks.manager import HookManager
from navigator_eventbus.hooks.base import BaseHook
from navigator_eventbus.brokers.rabbitmq import RabbitMQConnection      # lazy-imported at hooks/brokers/rabbitmq.py:31
```

### Existing Class Signatures

```python
# src/navigator_eventbus/envelope.py
class Severity(IntEnum): DEBUG=10; INFO=20; WARNING=30; ERROR=40; CRITICAL=50
@dataclass(frozen=True, slots=True)
class EventEnvelope:
    topic: str; payload: dict; event_id: str; timestamp: datetime  # tz-aware enforced in __post_init__
    source: Optional[str]; severity: Severity; priority: EventPriority
    correlation_id: Optional[str]; trace_context: Optional[dict]; metadata: dict
    def to_dict(self) -> dict[str, Any]
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventEnvelope"
    # NOTE: EventPriority is imported FROM navigator_eventbus.evb (envelope.py:22)

# src/navigator_eventbus/core.py
class BusCore:                                   # line 92
    async def publish(self, envelope: EventEnvelope) -> None   # line 287 — O(1) enqueue
    def subscribe(...)                                          # line 397
    # ctor kwargs: workers, queue_size, handler_timeout, retry_attempts,
    #   retry_base_delay, backpressure, default_backpressure  (lines 134–137)
# Meta-topics: bus.subscriber_error, bus.backpressure, bus.shutdown_incomplete,
#   bus.dlq, bus.dlq_error  (TOPICS.md)

# src/navigator_eventbus/hooks/manager.py
class HookManager:
    def __init__(self, *, route_to_bus: bool = False) -> None   # line 45 — M2 changes to Optional[bool]=None
    # attrs: self._route_to_bus (line 49), self._event_bus, self._callback

# ai-parrot@47a8ade — packages/ai-parrot/src/parrot/core/events/
#   evb.py           → facade over INTERNAL parrot.core.events.bus (to be shimmed, M4)
#   bus/             → full internal copy: backends/, core.py, dlq.py, envelope.py,
#                      converters.py, ingress/, ingress_models.py, subscribers/  (to be DELETED, M4)
#   pyproject.toml   → does NOT declare navigator-eventbus (verified absent)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `schema_version` field | `RedisStreamsBackend` XADD payload | `EventEnvelope.to_dict()` | backends/redis_streams.py:163–174 |
| auto `route_to_bus` | attached bus | `HookManager._event_bus` emit | hooks/manager.py |
| ai-parrot shim | external package | re-export in `parrot/core/events/evb.py` | M4 |

### Does NOT Exist (Anti-Hallucination)

- ~~`schema_version` / `ENVELOPE_SCHEMA_VERSION` / `UnsupportedSchemaVersion`~~ — do not exist yet anywhere (M1 creates them).
- ~~`HookManager.route_to_bus = None` tri-state~~ — currently strict `bool = False` (M2 creates it).
- ~~`navigator-eventbus` in ai-parrot's pyproject~~ — not declared (M4 adds it).
- ~~`test_no_navigator_imports_anywhere`~~ — current neutrality test still contains the phase-1 `navigator.brokers` allowance clause (M3 tightens it).
- ~~`navigator.brokers` runtime imports in src/~~ — already zero (only historical mentions in docstrings); do not "fix" imports that aren't there.
- ~~`lifecycle` package in navigator-eventbus wired to BusCore~~ — copied but `lifecycle.*` topics reserved/not implemented (out of scope).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `EventEnvelope` stays `@dataclass(frozen=True, slots=True)` — no Pydantic in the hot path (FEAT-176 rationale). New field LAST to keep positional-arg compatibility.
- Version tolerance direction: **readers are lenient backwards (missing → 1), strict forwards (unknown → raise)**. Never silently downgrade.
- M4 is a delete-heavy PR: prefer one atomic PR (dep add + shim + delete + import rewrite) over incremental, so no commit ever has both copies importable.
- Pin `navigator-eventbus>=0.2.0,<0.3` (tagged release, not git URL) per the brainstorm's parallelism agreement.

### Known Risks / Gotchas

- **Streams with pre-spec traffic**: any existing stream entries lack `schema_version`; the legacy→1 rule in `from_dict` is what makes M1 deployable without draining streams. Do not add a required key.
- **`slots=True` + new default field**: safe, but any pickle of old envelopes (if it exists anywhere) breaks — grep both repos for `pickle` usage of envelopes before merge (brokers/serializers.py uses a DataSerializer port — verify it round-trips via `to_dict`, not pickle-of-dataclass).
- **route_to_bus auto**: components attaching a bus for OTHER reasons (e.g. only for lifecycle dual-emit) will suddenly get hooks traffic on the bus. Audit ai-parrot call sites of `set_event_bus` during M4 and set explicit `False` where auto-routing is undesired.
- **Circular import**: envelope.py imports `EventPriority` from evb.py (envelope.py:22) while evb.py imports envelope — currently works via ordering; when adding `UnsupportedSchemaVersion`, keep it in envelope.py, not serialization.py, to avoid new cycles.
- ai-parrot hooks dedup (M4): parrot-only hooks (jira, github, imap, sharepoint, messaging, whatsapp, matrix, postgres, file_upload) must keep working subclassing `navigator_eventbus.hooks.base.BaseHook` — verify `setup_routes(app)` contract identical before deleting parrot's base.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navigator-eventbus` | `>=0.2.0,<0.3` | ai-parrot dependency (M4) — release gate |

No new dependencies in navigator-eventbus.

---

## 8. Open Questions

- [ ] M4 shim strategy: keep `parrot/core/events/evb.py` as re-export shim permanently, or deprecate with warning and remove in a later major? — *Owner: Jesus*
- [ ] Which parrot hooks are pure duplicates of the navigator-eventbus copies vs. divergent? Requires a file-level diff (`hooks/base.py`, `hooks/manager.py`, `hooks/models.py`, `hooks/brokers/*`, `scheduler.py`, `file_watchdog.py`, `mixins.py`) before deletion — *Owner: Claude Code (M4 research task)*
- [ ] FEAT numbering: rename docstrings FEAT-316 → FEAT-318, or record 316 as the implementation feature under the 318 umbrella? — *Owner: Jesus*
- [ ] Does anything already persist envelopes outside Streams (DLQ table rows)? If DLQ rows predate M1, `replay()`/`_row_to_envelope` needs the same legacy→1 rule — verify `dlq.py:311` — *Owner: Claude Code (M1 task)*
- [ ] Should `route_to_bus` auto-activation be announced in ai-parrot's changelog as behavior change (it is one, for any deployment calling `set_event_bus`)? — *Owner: Jesus*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-20 | Jesus + Claude | Initial draft; codebase contract verified against both mains |
