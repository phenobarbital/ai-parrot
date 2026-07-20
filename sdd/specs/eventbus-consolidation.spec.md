---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: EventBus Consolidation — envelope schema_version, default-capable hooks routing, ai-parrot PyPI pin

**Feature ID**: FEAT-319
**Date**: 2026-07-20
**Author**: Jesus (phenobarbital) + Claude
**Status**: approved
**Target version**: navigator-eventbus 0.1.0 (final) / ai-parrot next minor

> **Cross-repo spec**: Modules 1–2 land in `navigator-eventbus`; Module 3 is the
> release gate (tag + PyPI publish of `0.1.0` final); Module 4 lands in `ai-parrot`.
> Module 4 MUST NOT start until Module 3 completes, so ai-parrot migrates once
> against the final published wire contract.
>
> **Supersedes** the draft proposal `sdd/proposals/eventbus-consolidation.spec.md`
> (provisional FEAT-320): its M3 (broker-port closure) and M4 (bus-copy deletion)
> were completed by FEAT-316/317/318 before this spec was cut. Brainstorm:
> `sdd/proposals/eventbus-consolidation.brainstorm.md` (Option B accepted).

---

## 1. Motivation & Business Requirements

### Problem Statement

The extraction of the bus core into `navigator-eventbus` succeeded — FEAT-316
(broker port), FEAT-317 (ai-parrot migration), and FEAT-318 (navigator cleanup)
are all complete on `dev`. The internal `parrot/core/events/bus/` copy is deleted,
all imports rewired, hooks deduplicated, migration guard tests in place.

Three consolidation items remain open:

1. **Envelope versioning**: the wire format (`EventEnvelope.to_dict()` /
   `from_dict()`) lacks a `schema_version` field. Redis Streams traffic will
   accumulate version-less messages; adding versioning NOW (before production
   traffic exists) avoids painful retroactive migration later.
2. **Default-capable hooks routing**: `HookManager(route_to_bus=False)` means
   hooks bypass the bus unless explicitly opted in, contradicting the "bus as
   app-wide fabric" goal. Audit finding: **zero `set_event_bus` or `route_to_bus`
   references exist in ai-parrot** (it uses `forward_to_global`/`forward_to_bus`
   per-subscriber instead), so the change is latent for ai-parrot but shapes the
   contract for future consumers.
3. **ai-parrot dependency pin**: `navigator-eventbus` is pinned to a git commit
   hash (`17b99c2…`), not a PyPI release — installs are not reproducible from
   the package index, and the FEAT-317 close-out TODO at `pyproject.toml:103`
   remains open.

### Goals

- G1: Every serialized envelope carries `schema_version`; deserialization is
  lenient backwards (missing key → 1) and strict forwards (unknown → raise
  `UnsupportedSchemaVersion`) — across **all six** envelope construction/
  deserialization paths, not just `from_dict()`.
- G2: `HookManager` routes hook events to the bus by default when a bus is
  attached (tri-state `route_to_bus: Optional[bool] = None`), preserving the
  callback path and explicit opt-in/opt-out.
- G3: navigator-eventbus `0.1.0` final tagged and published to PyPI
  (M1+M2 included), superseding `0.1.0rc2`.
- G4: ai-parrot depends on `navigator-eventbus>=0.1.0,<0.2` from PyPI (git pin
  removed) and gains the `test_no_internal_bus_copy` guard test.

### Non-Goals (explicitly out of scope)

- Broker-port closure / neutrality tightening — **already landed** (FEAT-316/318).
- Deleting `parrot/core/events/bus/` / import rewiring — **already landed** (FEAT-317).
- Deprecation warning on explicit `route_to_bus=False` — rejected in brainstorm
  (Option C): premature before auto-routing is production-validated.
- `MIGRATION.md` / version-compatibility matrix docs — rejected in brainstorm
  (Option C): speculative until envelope v2 is actually designed.
- New backends (NATS/Kafka) or envelope field additions beyond `schema_version`.
- Lifecycle extraction Phase 2, navigator-auth ledger/outbox, flowtask adoption
  (separate specs per the original decomposition).

---

## 2. Architectural Design

### Overview

Four small, strictly-ordered modules (M1 ∥ M2 → M3 → M4):

1. **Envelope schema_version (M1, navigator-eventbus)**: add
   `schema_version: int = 1` as the LAST field of `EventEnvelope`
   (frozen/slots preserved, positional compat kept); constant
   `ENVELOPE_SCHEMA_VERSION = 1` and exception `UnsupportedSchemaVersion`
   in `envelope.py`, both exported from the package root. The version rule
   propagates to ALL envelope-producing paths: `from_dict()` (legacy→1,
   unknown→raise), DLQ `_row_to_envelope()` (same legacy→1 rule),
   `IngressEnvelope` (new Pydantic field, passed through `to_envelope()`),
   and the three converters (`from_legacy_event`, `from_lifecycle_dict`,
   `from_hook_event` — always emit 1).
2. **HookManager tri-state routing (M2, navigator-eventbus)**:
   `route_to_bus: Optional[bool] = None`; `None` → auto (route iff a bus is
   attached), `True`/`False` → explicit. One-time INFO log on first
   auto-activation; the flag resets when the bus is detached, so the log fires
   again on re-attachment. Callback dual-emit path unchanged — bus routing is
   additive, never replaces the callback.
3. **Release gate (M3, navigator-eventbus)**: tag `0.1.0` final containing
   M1+M2, publish to PyPI.
4. **ai-parrot follow-up (M4, ai-parrot)**: swap the git-hash dependency to
   `navigator-eventbus>=0.1.0,<0.2`; add guard test `test_no_internal_bus_copy`
   to `tests/core/events/test_migration_guard.py`.

No user-visible behavior change: `schema_version` is internal to the wire
format, and the auto-routing default is latent in ai-parrot (zero call sites
use `route_to_bus`/`set_event_bus` today).

### Component Diagram

```
navigator-eventbus (M1–M3)                          ai-parrot (M4)
  EventEnvelope(schema_version=1) ──to_dict()──→ Redis Streams / PubSub
        ▲            ▲                                │
  from_dict()   converters ×3                        │ pyproject:
  (legacy→1,    IngressEnvelope.to_envelope()        │   git pin ✂ →
   >1→raise)    DLQ._row_to_envelope() (legacy→1)    │   navigator-eventbus>=0.1.0,<0.2
                                                     │
  HookManager(route_to_bus=None ⇒ auto) ──emit──→ bus│ tests: + test_no_internal_bus_copy
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator_eventbus/envelope.py` `EventEnvelope` | extends | trailing `schema_version: int = 1`; frozen/slots preserved |
| `envelope.py` `to_dict()` / `from_dict()` | modifies | emit version; legacy→1, unknown→`UnsupportedSchemaVersion` |
| `navigator_eventbus/dlq.py` `_row_to_envelope()` | modifies | legacy→1 rule for Postgres DLQ rows (manual construction, not `from_dict`) |
| `navigator_eventbus/ingress_models.py` `IngressEnvelope` | extends | `schema_version: int = 1` field; `to_envelope()` passes through |
| `navigator_eventbus/converters.py` (×3 converters) | modifies | always emit `schema_version=1` |
| `navigator_eventbus/hooks/manager.py` `HookManager` | modifies | tri-state `route_to_bus`, `_effective_route_to_bus()`, one-time log |
| `navigator_eventbus/__init__.py` | extends | export `ENVELOPE_SCHEMA_VERSION`, `UnsupportedSchemaVersion` |
| `backends/redis_streams.py`, `backends/redis_pubsub.py` | none (verify only) | the only 2 wire-data `from_dict` call sites; serialize via `to_dict()` — no code change expected |
| ai-parrot `packages/ai-parrot/pyproject.toml` | modifies | line 103–104: git pin → `navigator-eventbus>=0.1.0,<0.2` |
| ai-parrot `tests/core/events/test_migration_guard.py` | extends | add `test_no_internal_bus_copy` |

### Data Models

```python
# navigator_eventbus/envelope.py — final field layout (frozen=True, slots=True preserved)
ENVELOPE_SCHEMA_VERSION: int = 1

@dataclass(frozen=True, slots=True)
class EventEnvelope:
    ...existing 10 fields unchanged...
    schema_version: int = ENVELOPE_SCHEMA_VERSION   # MUST be last (positional compat)

class UnsupportedSchemaVersion(ValueError):
    """Raised by from_dict() when data['schema_version'] > ENVELOPE_SCHEMA_VERSION.
    Message MUST include topic and event_id for operator triage."""

# navigator_eventbus/ingress_models.py
class IngressEnvelope(BaseModel):
    ...existing fields unchanged...
    schema_version: int = 1   # shape validation only; semantic (unknown-version)
                              # rejection stays in EventEnvelope.from_dict
```

### New Public Interfaces

```python
# navigator_eventbus/hooks/manager.py
class HookManager:
    def __init__(self, *, route_to_bus: Optional[bool] = None) -> None: ...
    # None → auto (route iff bus attached); True/False → explicit
    def _effective_route_to_bus(self) -> bool: ...
    # returns self._route_to_bus if not None else (self._event_bus is not None)

# navigator_eventbus/__init__.py — new exports
ENVELOPE_SCHEMA_VERSION
UnsupportedSchemaVersion
```

---

## 3. Module Breakdown

### Module 1: Envelope schema_version — all paths (repo: navigator-eventbus)
- **Path**: `navigator_eventbus/envelope.py`, `navigator_eventbus/dlq.py`,
  `navigator_eventbus/ingress_models.py`, `navigator_eventbus/converters.py`,
  `navigator_eventbus/__init__.py`
- **Responsibility**:
  - `ENVELOPE_SCHEMA_VERSION = 1` constant + `UnsupportedSchemaVersion(ValueError)`
    in `envelope.py` (keep the exception in `envelope.py`, NOT `serialization.py`,
    to avoid new import cycles — `envelope.py` already imports `EventPriority`
    from `evb.py`).
  - `schema_version: int = ENVELOPE_SCHEMA_VERSION` as the LAST dataclass field.
  - `to_dict()` emits `"schema_version"`.
  - `from_dict()`: missing key → 1 (legacy); `<= ENVELOPE_SCHEMA_VERSION` → parse;
    `> ENVELOPE_SCHEMA_VERSION` → raise `UnsupportedSchemaVersion` with topic +
    event_id in the message.
  - `dlq.py:_row_to_envelope()` (line 310–334): apply the same legacy→1 rule when
    reconstructing from Postgres rows (row dicts predating M1 have no version).
  - `ingress_models.py`: add `schema_version: int = 1` to `IngressEnvelope`;
    `to_envelope()` passes it through. Pydantic validates shape only (any int);
    semantic rejection of unknown versions stays in `from_dict` — intentional.
  - `converters.py`: `from_legacy_event`, `from_lifecycle_dict`, `from_hook_event`
    all emit `schema_version=1` (they construct `EventEnvelope` directly).
  - Export `ENVELOPE_SCHEMA_VERSION` and `UnsupportedSchemaVersion` from
    `navigator_eventbus/__init__.py` (`__all__` updated).
  - Verify (no change expected): `backends/redis_streams.py:350` and
    `backends/redis_pubsub.py:188` round-trip the new field via
    `json.loads` + `from_dict`.
- **Depends on**: nothing.

### Module 2: HookManager default-capable routing (repo: navigator-eventbus)
- **Path**: `navigator_eventbus/hooks/manager.py`
- **Responsibility**:
  - Signature change: `def __init__(self, *, route_to_bus: Optional[bool] = None)`.
  - New `_effective_route_to_bus() -> bool`:
    `self._route_to_bus if self._route_to_bus is not None else (self._event_bus is not None)`.
  - `_build_dispatch()` (line 92–130) and `_publish_hook_event()` (line 132–177)
    consult `_effective_route_to_bus()` instead of reading `self._route_to_bus`.
  - `route_to_bus` property returns the *effective* value; setter keeps accepting
    `Optional[bool]` and re-injects callbacks (existing behavior at line 57–63).
  - One-time INFO log on first auto-activation
    ("route_to_bus auto-enabled: bus attached"); the once-flag resets in
    `set_event_bus` when the bus is detached/replaced, so re-attachment logs again.
  - Callback path (`_dual_emit`) unchanged — callback and bus both receive.
- **Depends on**: nothing (parallel with Module 1).

### Module 3: Release gate — navigator-eventbus 0.1.0 final (repo: navigator-eventbus)
- **Path**: `pyproject.toml` (version), git tag, PyPI publish
- **Responsibility**:
  - Bump version `0.1.0rc2` → `0.1.0`; changelog entry covering M1+M2
    (envelope versioning + tri-state routing, flagged as a latent behavior
    change for consumers that call `set_event_bus`).
  - Tag and publish to PyPI. Full test suite green at the tag.
- **Depends on**: Modules 1–2 merged.

### Module 4: ai-parrot follow-up — PyPI pin + guard test (repo: ai-parrot)
- **Path**: `packages/ai-parrot/pyproject.toml`,
  `packages/ai-parrot/tests/core/events/test_migration_guard.py`
- **Responsibility**:
  - Replace line 103–104 git-hash dependency with
    `"navigator-eventbus>=0.1.0,<0.2"`; delete the FEAT-317 TODO comment.
  - Verify the `grpc` extra (`navigator-eventbus[grpc]`, line ~419) still
    resolves against the PyPI release.
  - Add an ai-parrot changelog entry noting the `route_to_bus` auto-routing
    behavior change inherited from navigator-eventbus 0.1.0 (latent today —
    zero call sites — but relevant for any future `set_event_bus` consumer).
  - Add `test_no_internal_bus_copy` to the existing migration-guard tests:
    asserts `packages/ai-parrot/src/parrot/core/events/bus/` does not exist on
    disk AND no importable `parrot.*` module defines a class named `BusCore` or
    `EventEnvelope`.
  - Full ai-parrot test suite green with the PyPI package (not the git pin).
- **Depends on**: Module 3 (published release) — hard gate.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_envelope_schema_version_default` | M1 | New envelope has `schema_version == 1`; present in `to_dict()` output |
| `test_from_dict_missing_version_is_legacy_v1` | M1 | Dict without the key parses; resulting envelope has version 1 |
| `test_from_dict_unknown_version_raises` | M1 | `schema_version: 99` → `UnsupportedSchemaVersion`; message contains topic and event_id |
| `test_frozen_slots_preserved_after_field_add` | M1 | dataclass still frozen+slots; positional construction with pre-spec arity (10 args) unaffected |
| `test_converters_emit_schema_version` | M1 | `from_legacy_event` / `from_lifecycle_dict` / `from_hook_event` → envelope carries version 1 |
| `test_dlq_row_to_envelope_legacy_v1` | M1 | Pre-M1 DLQ row (no version) → replayed envelope has version 1 |
| `test_ingress_envelope_schema_version` | M1 | `IngressEnvelope` accepts/defaults the field; `to_envelope()` passes it through |
| `test_route_to_bus_auto_with_bus` | M2 | `route_to_bus=None` + bus attached → events reach bus topic `hooks.*` |
| `test_route_to_bus_auto_without_bus` | M2 | `route_to_bus=None`, no bus → callback-only, no error |
| `test_route_to_bus_explicit_false_overrides_bus` | M2 | `False` + bus attached → NOT routed |
| `test_route_to_bus_explicit_true_preserved` | M2 | `True` behaves exactly as pre-spec opt-in |
| `test_callback_still_fires_when_routed` | M2 | dual-emit: callback and bus both receive |
| `test_auto_activation_logs_once` | M2 | INFO log fires once per attachment; resets on detach/re-attach |
| `test_no_internal_bus_copy` | M4 (ai-parrot) | `parrot/core/events/bus/` absent on disk; no `parrot.*` BusCore/EventEnvelope class |

### Integration Tests

| Test | Description |
|---|---|
| `test_streams_roundtrip_with_version` | XADD → XREADGROUP → `from_dict` preserves `schema_version`; mixed legacy (no key) + v1 messages in one stream both consumable |
| `test_pubsub_roundtrip_with_version` | Same guarantee over the Redis Pub/Sub backend (`redis_pubsub.py:188` path) |
| `test_hooks_to_bus_default_e2e` | Real hook fires → HookManager (auto) → bus → subscriber receives envelope on `hooks.<type>.<event>` |
| `test_dlq_replay_mixed_rows` | DLQ replay over a table containing pre-M1 and post-M1 rows publishes valid envelopes for both |
| `test_parrot_suite_on_pypi_package` | (ai-parrot, M4) full test suite green with `navigator-eventbus` installed from PyPI |

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

@pytest.fixture
def legacy_dlq_row():
    """Postgres evb_dlq row persisted BEFORE this spec (no schema_version)."""
    return {
        "topic": "order.created", "payload": '{"id": 1}',
        "event_id": "…uuid…", "failed_at": "2026-07-01T10:00:00",
        "source": "test", "severity": 20, "priority": 5,
        "correlation_id": None, "trace_context": None, "metadata": "{}",
        "attempts": 3, "error": "boom", "subscriber_id": "sub-1",
    }
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] M1: all envelope unit tests pass; `ENVELOPE_SCHEMA_VERSION` and
  `UnsupportedSchemaVersion` importable from `navigator_eventbus` package root.
- [ ] M1: `EventEnvelope` remains `@dataclass(frozen=True, slots=True)`;
  positional construction with pre-spec arity (10 args) still valid;
  `schema_version` is the last field.
- [ ] M1: readers lenient backwards, strict forwards — verified on ALL paths:
  `from_dict` (Streams + Pub/Sub), DLQ `_row_to_envelope`, `IngressEnvelope`,
  three converters. No path silently downgrades or drops the version.
- [ ] M1: Streams round-trip test proves legacy (version-less) and v1 messages
  coexist in one stream; DLQ replay test proves the same for mixed rows.
- [ ] M2: hooks route to bus by default when a bus is attached; explicit `False`
  opts out; explicit `True` unchanged; callback path untouched (all pre-existing
  HookManager tests pass unmodified except constructor kwargs).
- [ ] M2: auto-activation logs INFO exactly once per attachment.
- [ ] M3: navigator-eventbus `0.1.0` final tagged and published to PyPI before
  the ai-parrot PR merges; changelog notes the latent routing behavior change.
- [ ] M4: ai-parrot `pyproject.toml` contains `navigator-eventbus>=0.1.0,<0.2`
  and no git URL for it; FEAT-317 TODO comment removed.
- [ ] M4: `test_no_internal_bus_copy` in ai-parrot CI; full ai-parrot suite
  green against the PyPI package.
- [ ] M4: ai-parrot changelog entry documents the auto-routing behavior change.
- [ ] No breaking changes: `EventBus.emit/subscribe/on/publish` signatures
  unchanged; no new required dependencies in navigator-eventbus.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified 2026-07-20 against `navigator-eventbus` 0.1.0rc1 as installed in
> `.venv/lib/python3.11/site-packages/navigator_eventbus/` (rc2 is the current
> package version; installed line numbers below — re-verify in the
> navigator-eventbus repo checkout before editing) and `ai-parrot@dev`
> (post-FEAT-317/318).

### Verified Imports

```python
from navigator_eventbus import (          # __init__.py __all__, lines 25–39
    BackpressureError, BusClosedError, BusCore, DLQHandler,
    Event, EventBus, EventEnvelope, EventPriority, EventSubscription,
    IngressEnvelope, Severity, lifecycle,
)
from navigator_eventbus.hooks.manager import HookManager
from navigator_eventbus.converters import (
    from_legacy_event, from_lifecycle_dict, from_hook_event,
)
```

### Existing Class Signatures

```python
# navigator_eventbus/envelope.py
@dataclass(frozen=True, slots=True)                    # line 40–41
class EventEnvelope:
    topic: str                                         # line 62
    payload: dict[str, Any]                            # line 63
    event_id: str                                      # line 64, default uuid4()
    timestamp: datetime                                # line 65, tz-aware enforced in __post_init__ (75–93)
    source: Optional[str] = None                       # line 66
    severity: Severity = Severity.INFO                 # line 67
    priority: EventPriority = EventPriority.NORMAL     # line 68
    correlation_id: Optional[str] = None               # line 69
    trace_context: Optional[dict] = None               # line 70
    metadata: dict[str, Any] = field(default_factory=dict)  # line 71–73
    def to_dict(self) -> dict[str, Any]                # line 95 — enums as .value, ts as ISO 8601
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventEnvelope"  # line 117 — requires topic+timestamp
    # NOTE: EventPriority is imported FROM navigator_eventbus.evb — import-cycle
    # constraint: new names (constant + exception) go in envelope.py, not serialization.py

# navigator_eventbus/hooks/manager.py
class HookManager:
    def __init__(self, *, route_to_bus: bool = False) -> None   # line 45–50
        # sets: self._hooks, self._callback, self._event_bus=None, self._route_to_bus
    # route_to_bus property (52–54) / setter (57–63, re-injects callbacks)
    def set_event_bus(self, bus) -> None                        # line 75–90, rebuilds dispatch
    def _build_dispatch(self) -> Callable                       # line 92–130, callback read at call-time
    def _publish_hook_event(self, event) -> None                # line 132–177
        # route_to_bus=False → legacy bus.emit(topic, event.model_dump())  (line 132)
        # route_to_bus=True  → first-class envelope kwargs emit            (lines 149–177)

# navigator_eventbus/dlq.py
class DLQHandler:
    def __init__(self, bus, *, dsn=None, driver="pg")           # line 125–147, unwraps EventBus facade
    @staticmethod
    def _row_to_envelope(row: dict) -> EventEnvelope            # line 310–334
        # manual construction (NOT from_dict); json.loads for str JSONB fields (313–314);
        # failed_at → timestamp, naive coerced to UTC (317–320)
    async def replay(...)                                       # line 268–308, publishes reconstructed envelopes

# navigator_eventbus/ingress_models.py
class IngressEnvelope(BaseModel):                               # line 21–89
    model_config = ConfigDict(extra="forbid", frozen=True)
    # mirrors EventEnvelope fields; _coerce_naive_to_utc validator (57–70)
    def to_envelope(self) -> EventEnvelope                      # line 72–89, direct construction

# navigator_eventbus/converters.py — all construct EventEnvelope directly
def from_legacy_event(event, *, severity) -> EventEnvelope      # line 43–71
def from_lifecycle_dict(data, *, severity) -> EventEnvelope     # line 74–122, topic lifecycle.<class>
def from_hook_event(event, *, severity) -> EventEnvelope        # line 125–162, topic hooks.<type>.<event>
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `schema_version` field | Redis Streams XADD payload | `EventEnvelope.to_dict()` | `backends/redis_streams.py:350` (from_dict side) |
| `schema_version` field | Redis Pub/Sub | `json.loads` + `from_dict` | `backends/redis_pubsub.py:188` |
| legacy→1 rule (DLQ) | Postgres `evb_dlq` rows | `DLQHandler._row_to_envelope()` | `dlq.py:310–334` |
| `schema_version` on ingress | WebSocket/gRPC input | `IngressEnvelope` validation | `ingress_models.py:21–89` |
| `_effective_route_to_bus()` | dispatch wrapper | `_build_dispatch` / `_publish_hook_event` | `hooks/manager.py:92–177` |
| PyPI pin (M4) | ai-parrot deps | `pyproject.toml` line 103–104 | verified: git+…@17b99c2 with FEAT-317 TODO at line 103 |
| guard test (M4) | existing migration guard | `tests/core/events/test_migration_guard.py` | 4 existing tests verified |

### Does NOT Exist (Anti-Hallucination)

- ~~`schema_version` / `ENVELOPE_SCHEMA_VERSION` / `UnsupportedSchemaVersion`~~ — M1 creates them.
- ~~`HookManager` tri-state / `_effective_route_to_bus()`~~ — currently strict `bool = False`; M2 creates them.
- ~~`serialization.py` involvement in envelope versioning~~ — `serialization.py` holds generic `dumps/loads` (+ opt-in cloudpickle helpers); `from_dict` lives in `envelope.py`. Do not touch `serialization.py`.
- ~~`set_event_bus` / `route_to_bus` call sites in ai-parrot~~ — zero; ai-parrot uses `forward_to_global`/`forward_to_bus` (e.g. `parrot/bots/abstract.py:452`).
- ~~`parrot/core/events/bus/`, `parrot/core/events/evb.py`, `parrot.core.hooks.base`, `parrot.core.hooks.models`~~ — deleted by FEAT-317; migration guard asserts `ModuleNotFoundError`.
- ~~pickle in the envelope transport path~~ — none; `cloudpickle`/`jsonpickle` exist only in `brokers/` (generic broker layer), never in `backends/`.
- ~~`navigator.*` imports in navigator-eventbus src/~~ — zero; neutrality test already tightened (FEAT-318).
- ~~`test_no_internal_bus_copy`~~ — M4 creates it; the existing guard file has 4 other tests.
- ~~`navigator-eventbus` `0.1.0` final on PyPI~~ — current is `0.1.0rc2`; M3 publishes final.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `EventEnvelope` stays `@dataclass(frozen=True, slots=True)` — no Pydantic in
  the hot path (FEAT-176 rationale). New field LAST for positional compat.
- Version tolerance direction: **lenient backwards (missing → 1), strict
  forwards (unknown → raise)**. Never silently downgrade. Apply the identical
  rule in `from_dict` AND `_row_to_envelope`.
- Keep `UnsupportedSchemaVersion` in `envelope.py` (import-cycle constraint:
  `envelope.py` ⇄ `evb.py` ordering currently works; adding names to
  `serialization.py` risks new cycles).
- M2: read effective routing at call-time (matching the existing
  `_build_dispatch` pattern where `self._callback` is read at call-time to
  avoid stale closures).
- M4 is a two-file PR (pyproject + guard test) — single commit, no worktree
  ceremony needed.

### Known Risks / Gotchas

- **Pre-spec Streams/DLQ data**: existing stream entries and DLQ rows lack
  `schema_version`; the legacy→1 rule is what makes M1 deployable without
  draining streams or migrating tables. Do NOT make the key required anywhere.
- **`slots=True` + new default field**: safe for our JSON paths; pickle of old
  envelope instances would break, but pickle is verified absent from the
  envelope transport path (see contract) — no action needed.
- **`IngressEnvelope(extra="forbid")`**: without adding the field, post-M1
  clients sending `schema_version` would be REJECTED by ingress validation —
  this is why M1 must touch `ingress_models.py`, not just `envelope.py`.
- **Auto-routing blast radius**: any consumer that attaches a bus via
  `set_event_bus` for other reasons will start receiving hooks traffic on the
  bus. ai-parrot audit: zero call sites → latent. Changelog note in M3 covers
  future consumers.
- **Installed-package line numbers**: contract line numbers were verified
  against the installed 0.1.0rc1 wheel; the navigator-eventbus repo checkout
  may drift slightly — re-verify with grep before editing (cheap, mandatory).
- **M3→M4 gate**: publishing to PyPI is irreversible per-version; if a defect
  is found post-publish, M3 re-releases as `0.1.1` and M4 pins `>=0.1.1,<0.2`.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navigator-eventbus` | `>=0.1.0,<0.2` | ai-parrot dependency (M4) — release gate on M3 |

No new dependencies in navigator-eventbus.

---

## 8. Open Questions

> Decision trail from the brainstorm (`sdd/proposals/eventbus-consolidation.brainstorm.md`):

- [x] Which parrot hooks are pure duplicates vs. divergent? — *Resolved in brainstorm*: FEAT-317 already deduplicated; generic hooks import from `navigator_eventbus.hooks.*`, domain hooks (jira/github/imap/sharepoint/messaging/whatsapp/matrix/postgres/file_upload) stay local. No duplicates remain.
- [x] Does anything persist envelopes outside Streams? — *Resolved in brainstorm*: yes — DLQ Postgres rows via `dlq.py:_row_to_envelope()` (line 310–334, manual construction). The legacy→1 rule is applied there (M1 scope).
- [x] FEAT numbering 316 vs 318 reconciliation — *Resolved in brainstorm*: FEAT-318 is canonical per completed task indexes; no docstring work remains.
- [x] `set_event_bus` call sites in ai-parrot needing explicit `False`? — *Resolved in brainstorm*: zero call sites; auto-routing is latent in ai-parrot, no opt-outs needed.
- [x] Release version target — *Resolved in brainstorm discovery*: M1+M2 land in `0.1.0` final (from `0.1.0rc2`), NOT `0.2.0`; ai-parrot pins `>=0.1.0,<0.2`.
- [x] Auto-activation logging — *Resolved in brainstorm discovery*: one-time INFO log per attachment; flag resets on detach.
- [x] `evb.py` shim strategy (keep permanently vs. deprecate)? — *Resolved (moot)*: FEAT-317 deleted `evb.py` entirely; consumers import from `navigator_eventbus` directly. Closed.
- [x] Should `route_to_bus` auto-activation be announced in ai-parrot's changelog too (beyond the navigator-eventbus 0.1.0 changelog)? — *Resolved by Jesus (2026-07-20)*: yes — M4 adds an ai-parrot changelog entry noting the auto-routing behavior change.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`.
- **Sequencing**: M1 ∥ M2 (independent files, may proceed in parallel) → M3
  (release gate) → M4. M1–M3 live in the `navigator-eventbus` repo (outside
  this checkout); M4 is a two-file ai-parrot change.
- **Worktree**: NOT recommended for M4 — single-commit change per the
  "When NOT to Use Worktrees" policy. M1–M3 happen in the navigator-eventbus
  repo and are outside ai-parrot worktree scope entirely.
- **Cross-feature dependencies**: none in-flight; FEAT-316/317/318 all merged.
  Only shared touchpoint is the navigator-eventbus package version.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-20 | Jesus + Claude | Initial draft from brainstorm Option B; supersedes proposal draft (FEAT-320 provisional) after FEAT-316/317/318 closed its M3/M4 |
