---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: EventBus Lifecycle Extraction (`navigator-eventbus` phase 2)

**Feature ID**: FEAT-313
**Date**: 2026-07-17
**Author**: Jesus (phenobarbital) + Claude
**Status**: draft
**Target version**: navigator-eventbus 0.1.0

> **Brainstorm source**: `sdd/proposals/navigator-eventbus-extraction.brainstorm.md`
> (Option B — extracción por fases). This spec is **phase 2** of five.
> **Blocking dependency**: phase 1 (`eventbus-core-extraction`, **FEAT-312**,
> spec drafted 2026-07-17) must be implemented first — it creates the package
> scaffold and moves the bus core (including the `evb.py` facade) that
> lifecycle imports.
>
> **Target repo**: `/home/jesuslara/proyectos/navigator-eventbus` (work happens
> there, branch from its `main`). SDD artifacts (this spec, tasks) live in
> ai-parrot on `dev`. **ai-parrot code does NOT change in this phase** — import
> rewiring is phase 4 (`parrot-eventbus-migration`).

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-310 delivered the EventBus v2 inside ai-parrot, and phase 1 of the
extraction moves the bus core to the standalone `navigator-eventbus` package.
But the **typed lifecycle machinery** — `LifecycleEvent`, `TraceContext`,
`EventRegistry`, the global registry, `EventProvider`, `EventEmitterMixin`, and
the generic subscribers (logging, webhook) — still lives in
`packages/ai-parrot/src/parrot/core/events/lifecycle/` (~1.4k LOC of machinery).

Flowtask, QuerySource, and navigator-auth need typed lifecycle events with the
same guarantees (frozen dataclasses, error-isolation model B, dual-emit to the
bus) without depending on ai-parrot. Without this phase, the package offers
only the topic-based bus — consumers would have to re-invent the typed layer.

### Goals

- Move the lifecycle **machinery** (not the typed agent events) to
  `navigator_eventbus.lifecycle`, preserving API signatures exactly:
  `EventRegistry.subscribe/emit/emit_nowait`, `get_global_registry()`, `scope()`,
  `EventEmitterMixin._init_events`, `EventProvider.register`.
- Decouple the machinery from parrot: the observability auto-boot in
  `EventEmitterMixin` becomes an **injectable bootstrap hook**; the
  `yaml_loader` wiring engine takes an **injectable event-name table**.
- Move the generic subscribers `LoggingSubscriber` and `WebhookSubscriber`.
- Move the machinery test suite; leave typed-event tests in ai-parrot.
- Preserve the FEAT-177 performance budget (< 0.1% overhead on dual-emit) and
  error-isolation model B (emit never raises into the emitting flow).

### Non-Goals (explicitly out of scope)

- **Typed agent events stay in ai-parrot**: `events/` taxonomy
  (`BeforeInvokeEvent`, `ClientStreamChunkEvent`, etc.) remains at
  `parrot.core.events.lifecycle.events`, subclassing the package's
  `LifecycleEvent` (resolved in brainstorm — minimum diff).
- `legacy_bridge.py` and `subscribers/opentelemetry.py` stay in ai-parrot
  (both depend on typed agent events).
- No changes to ai-parrot imports or code — that is phase 4.
- No brokers work — that is phase 3 (`eventbus-brokers-port`).
- No compatibility shims (hard-migration decision from discovery Round 1;
  option C rejected — see brainstorm).

---

## 2. Architectural Design

### Overview

Fresh-copy move (no git history — resolved in brainstorm) of the lifecycle
machinery into the phase-1 scaffold at
`src/navigator_eventbus/lifecycle/`, with three decouples:

1. **Bootstrap hook injection** (`mixin.py`): the lazy, guarded import of
   `parrot.observability.bootstrap.ensure_observability_bootstrapped` at
   `mixin.py:68` is replaced by a module-level injectable hook:
   `set_bootstrap_hook(hook: Callable[[], None]) -> None`. `_init_events()`
   invokes the hook (if set) inside the same try/except guard. ai-parrot will
   inject its observability bootstrap in phase 4; the package default is no-op.
2. **Event-name table injection** (`yaml_loader.py`): the wiring engine
   (`wire_events`, `_wire_handler`, `_wire_provider`, `_resolve`, `_make_where`)
   moves to the package, but the hard import of the typed-event table at
   `yaml_loader.py:28` becomes a registry: `register_event_names(mapping:
   dict[str, type[LifecycleEvent]])`. Each app registers its taxonomy
   (ai-parrot its agent events in phase 4, Flowtask its own later).
3. **Facade reference** (`registry.py:40`): the TYPE_CHECKING-only import of
   `EventBus` switches from `parrot.core.events.evb` to the package facade
   moved in phase 1 (`navigator_eventbus.evb`). Runtime behavior unchanged —
   the registry only calls `bus.emit(channel, dict)` duck-typed.

Everything else moves verbatim: `base.py`, `trace.py` (zero-dep W3C
traceparent), `meta.py`, `registry.py`, `global_registry.py`, `provider.py`,
`subscribers/logging.py`, `subscribers/webhook.py`.

### Component Diagram

```
navigator_eventbus/                    (phase 1 scaffold — PREREQUISITE)
├── evb.py, envelope.py, core.py, ...  (phase 1 — bus core)
└── lifecycle/                          (THIS SPEC)
    ├── __init__.py        curated public API (machinery only, no typed events)
    ├── base.py            LifecycleEvent (frozen dataclass ABC)
    ├── trace.py           TraceContext (W3C traceparent, zero deps)
    ├── meta.py            SubscriberErrorEvent
    ├── registry.py        EventRegistry, AsyncSubscriber  ──→ evb.EventBus (TYPE_CHECKING)
    ├── global_registry.py get_global_registry(), scope()
    ├── provider.py        EventProvider protocol
    ├── mixin.py           EventEmitterMixin ──→ bootstrap hook (injected, no parrot import)
    ├── yaml_loader.py     wire_events engine ──→ event-name registry (injected table)
    └── subscribers/
        ├── logging.py     LoggingSubscriber
        └── webhook.py     WebhookSubscriber (aiohttp)

ai-parrot (UNCHANGED this phase; phase-4 wiring shown for context)
└── parrot/core/events/lifecycle/
    ├── events/            typed taxonomy — subclasses package LifecycleEvent (phase 4)
    ├── legacy_bridge.py   stays (depends on typed events)
    └── subscribers/opentelemetry.py  stays (depends on typed events)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator_eventbus.evb.EventBus` (phase 1) | TYPE_CHECKING ref + duck-typed `emit()` | `registry.py` dual-emit path; no runtime import |
| `navigator_eventbus` package scaffold (phase 1) | contains | `lifecycle/` subpackage, exported from top-level `__init__.py` |
| `navconfig.logging` | uses | already a direct dep of the package (discovery decision) |
| `aiohttp` | uses | `WebhookSubscriber` delivery; direct dep of the package (phase 1 decision) |
| `parrot.core.events.lifecycle.*` (ai-parrot) | frozen source | copy origin; frozen during extraction window — fixes land in the package first |

### Data Models

No new data models. Moved as-is (signatures preserved):

```python
@dataclass(frozen=True)
class LifecycleEvent(ABC):          # base.py — frozen, to_dict() with strict json validation
    trace_context: TraceContext
    event_id: str
    timestamp: datetime             # tz-aware
    source_type: str
    source_name: str

@dataclass(frozen=True)
class TraceContext: ...             # trace.py — W3C traceparent fields
```

### New Public Interfaces

The only genuinely new surface (the two decouples):

```python
# navigator_eventbus/lifecycle/mixin.py
def set_bootstrap_hook(hook: Callable[[], None] | None) -> None:
    """Install a process-wide hook invoked once per EventEmitterMixin init.

    Replaces the hard-coded parrot.observability auto-boot. Idempotency is
    the hook's responsibility. Failures are swallowed (guarded), matching
    current behavior at parrot mixin.py:67-74.
    """

# navigator_eventbus/lifecycle/yaml_loader.py
def register_event_names(mapping: dict[str, type[LifecycleEvent]]) -> None:
    """Register app-specific event-name → class mappings for wire_events().

    Additive across calls; later registrations override same-name keys.
    """
```

---

## 3. Module Breakdown

### Module 1: Core machinery move (`base`, `trace`, `meta`)
- **Path**: `src/navigator_eventbus/lifecycle/{base,trace,meta}.py` (navigator-eventbus repo)
- **Responsibility**: verbatim move of `LifecycleEvent`, `TraceContext`,
  `SubscriberErrorEvent`; only intra-package import paths change.
- **Depends on**: phase 1 scaffold.

### Module 2: Registry + global registry + provider
- **Path**: `src/navigator_eventbus/lifecycle/{registry,global_registry,provider}.py`
- **Responsibility**: move `EventRegistry` (subscribe/emit/emit_nowait, model B,
  recursion guard, dual-emit), `get_global_registry()`/`scope()`, `EventProvider`.
  Switch TYPE_CHECKING `EventBus` ref to `navigator_eventbus.evb`.
- **Depends on**: Module 1.

### Module 3: EventEmitterMixin with injectable bootstrap
- **Path**: `src/navigator_eventbus/lifecycle/mixin.py`
- **Responsibility**: move mixin; replace parrot.observability import
  (parrot `mixin.py:68`) with `set_bootstrap_hook()` mechanism (no-op default).
- **Depends on**: Module 2.

### Module 4: yaml_loader engine with injectable event table
- **Path**: `src/navigator_eventbus/lifecycle/yaml_loader.py`
- **Responsibility**: move `wire_events` engine; replace the typed-events
  import (parrot `yaml_loader.py:28`) with `register_event_names()` registry.
  `_resolve`/`_make_where` move unchanged.
- **Depends on**: Module 2.

### Module 5: Generic subscribers
- **Path**: `src/navigator_eventbus/lifecycle/subscribers/{logging,webhook}.py`
- **Responsibility**: verbatim move of `LoggingSubscriber` and
  `WebhookSubscriber` (HMAC signing, aiohttp delivery).
- **Depends on**: Module 1.

### Module 6: Public API + test suite migration
- **Path**: `src/navigator_eventbus/lifecycle/__init__.py` + `tests/lifecycle/`
- **Responsibility**: curated `__init__.py` exporting machinery only (NO typed
  events — those stay parrot-side); move machinery tests from ai-parrot
  (`test_base`, `test_trace_context`, `test_registry`,
  `test_registry_fire_and_forget`, `test_global_registry`, `test_mixin`,
  `test_provider`, `test_logging_subscriber`, `test_webhook_subscriber`),
  adapting imports; add tests for the two new injection points.
- **Depends on**: Modules 1–5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_lifecycle_event_frozen` | 1 | moved: mutation raises FrozenInstanceError |
| `test_trace_context_traceparent` | 1 | moved: W3C parse/format round-trip |
| `test_registry_emit_never_raises` | 2 | moved: model B — failing subscriber isolated |
| `test_registry_dual_emit_fire_and_forget` | 2 | moved: bus emit via create_task, non-blocking |
| `test_global_registry_scope` | 2 | moved: contextvar isolation |
| `test_mixin_bootstrap_hook_invoked` | 3 | NEW: injected hook called once on `_init_events` |
| `test_mixin_bootstrap_hook_failure_swallowed` | 3 | NEW: raising hook never breaks construction |
| `test_mixin_no_hook_noop` | 3 | NEW: default (no hook) constructs cleanly |
| `test_yaml_loader_registered_names` | 4 | NEW: `register_event_names` + `wire_events` resolves registered class |
| `test_yaml_loader_unknown_name` | 4 | NEW: unregistered event name → clear error, not ImportError |
| `test_webhook_subscriber_hmac` | 5 | moved: signature header correctness |
| `test_public_api_exports` | 6 | NEW: `__init__` exports machinery, absent typed events |

### Integration Tests

| Test | Description |
|---|---|
| `test_registry_dual_emit_to_bus` | EventRegistry → phase-1 `EventBus` facade end-to-end (envelope arrives on topic `lifecycle.<Class>`) |
| `test_emit_overhead_budget` | re-run FEAT-177 overhead benchmark against the moved machinery: < 0.1% |

### Test Data / Fixtures

```python
@pytest.fixture
def fresh_global_registry():
    """Isolate the global registry per test via scope()."""
    from navigator_eventbus.lifecycle import scope
    with scope() as reg:
        yield reg
```

---

## 5. Acceptance Criteria

- [ ] `from navigator_eventbus.lifecycle import EventRegistry, LifecycleEvent, TraceContext, EventEmitterMixin, EventProvider, get_global_registry, scope, LoggingSubscriber, WebhookSubscriber` works in the target repo.
- [ ] No `parrot.*` import anywhere under `src/navigator_eventbus/lifecycle/` (`grep -r "from parrot\|import parrot" src/navigator_eventbus/lifecycle/` → 0 hits).
- [ ] API signatures unchanged vs. ai-parrot source: `EventRegistry.__init__(*, event_bus=None, bus_channel_prefix="lifecycle", forward_to_global=True)`, `subscribe(event_type, callback, *, where=None, forward_to_bus=False)`, `async emit(event)`, `emit_nowait(event)`, `EventEmitterMixin._init_events(*, event_bus=None, forward_to_global=True)`.
- [ ] `set_bootstrap_hook` replaces the parrot.observability import; a raising hook never breaks construction (guarded, model B).
- [ ] `wire_events` resolves event classes exclusively through `register_event_names`; no typed-event imports in the engine.
- [ ] Error isolation model B preserved: `emit()` never propagates subscriber exceptions; `SubscriberErrorEvent` emitted with recursion guard.
- [ ] Typed events (`BeforeInvokeEvent`, etc.), `legacy_bridge`, `OpenTelemetrySubscriber` are NOT in the package.
- [ ] ai-parrot working tree untouched (this phase writes only to the navigator-eventbus repo + SDD artifacts here).
- [ ] All moved + new tests pass in navigator-eventbus CI (pytest + ruff + mypy — CI exists from phase 1).
- [ ] Dual-emit overhead benchmark < 0.1% (FEAT-177 budget) re-verified.

---

## 6. Codebase Contract

> Source tree: `packages/ai-parrot/src/parrot/core/events/lifecycle/` (branch
> `dev`, post-FEAT-310). All references re-verified 2026-07-17.

### Verified Imports

```python
# ai-parrot source (copy origin — these are the modules being moved):
from parrot.core.events.lifecycle.trace import TraceContext            # __init__.py:15
from parrot.core.events.lifecycle.base import LifecycleEvent           # __init__.py:16
from parrot.core.events.lifecycle.meta import SubscriberErrorEvent     # __init__.py:17
from parrot.core.events.lifecycle.registry import EventRegistry, AsyncSubscriber  # __init__.py:18
from parrot.core.events.lifecycle.global_registry import get_global_registry, scope  # __init__.py:19
from parrot.core.events.lifecycle.provider import EventProvider        # __init__.py:20
from parrot.core.events.lifecycle.mixin import EventEmitterMixin       # __init__.py:21

# Couplings to decouple (exhaustive census — ONLY these two hard points):
from parrot.observability.bootstrap import ensure_observability_bootstrapped
    # mixin.py:68 — lazy + guarded (try/except at :67-74) → becomes set_bootstrap_hook()
from parrot.core.events.lifecycle.events import (...)
    # yaml_loader.py:28 — hard import of typed taxonomy → becomes register_event_names()

# TYPE_CHECKING-only (no runtime coupling):
from parrot.core.events.evb import EventBus                            # registry.py:40

# Third-party used by moved modules (already package deps per phase-1 decisions):
from navconfig.logging import logging                                  # yaml_loader.py:24
import aiohttp                                                         # subscribers/webhook.py:28
```

### Existing Class Signatures

```python
# lifecycle/base.py
@dataclass(frozen=True)
class LifecycleEvent(ABC):                                # base.py:21
    def to_dict(self) -> dict[str, Any]: ...              # base.py:52 — strict json validation

# lifecycle/trace.py
@dataclass(frozen=True)
class TraceContext: ...                                   # trace.py:15 — zero deps, 219 LOC

# lifecycle/meta.py
class SubscriberErrorEvent(LifecycleEvent): ...           # meta.py:15

# lifecycle/registry.py (447 LOC)
class _Subscription: ...                                  # registry.py:64
class EventRegistry:                                      # registry.py:90
    def __init__(self, *, event_bus: "Optional[EventBus]" = None,
                 bus_channel_prefix: str = "lifecycle",
                 forward_to_global: bool = True) -> None  # registry.py:104
    def subscribe(self, event_type, callback, *, where=None,
                  forward_to_bus=False) -> str            # registry.py:121
    def unsubscribe(self, subscription_id: str) -> bool   # registry.py:159
    async def emit(self, event: LifecycleEvent) -> None   # registry.py:235 — never raises
    def emit_nowait(self, event: LifecycleEvent) -> None  # registry.py:366
    # lazy imports inside methods: provider (:218), global_registry (:354, :432)

# lifecycle/global_registry.py (91 LOC)
def get_global_registry() -> EventRegistry                # global_registry.py:37
def scope() -> Iterator[EventRegistry]                    # global_registry.py:59 — contextmanager

# lifecycle/provider.py (51 LOC)
@runtime_checkable
class EventProvider(Protocol):                            # provider.py:20
    def register(self, registry: "EventRegistry") -> None # provider.py:45

# lifecycle/mixin.py (94 LOC)
class EventEmitterMixin:                                  # mixin.py:24
    def _init_events(self, *, event_bus: Optional[object] = None,
                     forward_to_global: bool = True) -> None  # mixin.py:45
    # observability auto-boot: mixin.py:67-74 (try/except around import + call)
    @property
    def events(self) -> EventRegistry                     # mixin.py:77

# lifecycle/yaml_loader.py (248 LOC)
def _resolve(dotted: str) -> Any                          # yaml_loader.py:86
def _make_where(where_dict: dict) -> Callable[[Any], bool]  # yaml_loader.py:113
def wire_events(bot: Any, events_block: Optional[dict]) -> None  # yaml_loader.py:148
def _wire_handler(registry: EventRegistry, sub: dict) -> None    # yaml_loader.py:189
def _wire_provider(registry: EventRegistry, sub: dict) -> None   # yaml_loader.py:233

# lifecycle/subscribers/logging.py (85 LOC)
class LoggingSubscriber: ...                              # logging.py:21

# lifecycle/subscribers/webhook.py (174 LOC)
class WebhookSubscriber:                                  # webhook.py:38
    def __init__(...)                                     # webhook.py:52 — hmac/hashlib/aiohttp
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `lifecycle/registry.py` (moved) | `navigator_eventbus.evb.EventBus` | duck-typed `bus.emit(channel, dict)` in dual-emit path | parrot registry.py:40 (TYPE_CHECKING) + brainstorm-eventbus-v2 registry.py:280-300 |
| `set_bootstrap_hook()` (new) | app bootstrap (parrot phase 4) | module-level callable, invoked in `_init_events` guarded block | replaces parrot mixin.py:67-74 |
| `register_event_names()` (new) | app taxonomies (parrot phase 4, Flowtask later) | dict registry consulted by `wire_events`/`_wire_handler` | replaces parrot yaml_loader.py:28 |
| Machinery tests (moved) | `tests/unit/events/lifecycle/` split | 9 machinery test files move; 4 typed-event files stay | tests dir listing verified 2026-07-17 |

### Does NOT Exist (Anti-Hallucination)

- ~~`navigator_eventbus.lifecycle` today~~ — the target repo contains only
  README + LICENSE (verified 2026-07-17). **Phase 1 must create the scaffold
  first**; this spec cannot start until `src/navigator_eventbus/` exists with
  `evb.py`/`envelope.py`/`core.py`.
- ~~Implemented phase-1 code~~ — the phase-1 spec exists
  (`sdd/specs/eventbus-core-extraction.spec.md`, FEAT-312, status draft) but is
  NOT implemented; the target repo has no code yet. Blocking dependency.
- ~~`navigator.eventbus` (dotted namespace import)~~ — unviable; `navigator` is
  a regular package. Import name is `navigator_eventbus` (flat).
- ~~Runtime import of `EventBus` in `registry.py`~~ — TYPE_CHECKING only
  (registry.py:40); the dual-emit path is duck-typed.
- ~~`parrot.notifications` import in any moved module~~ — does not exist in
  lifecycle machinery.
- ~~`SynthesisMixin`, `EventLedger`, or any ledger class in lifecycle/~~ — the
  ledger machinery lives in `ai-parrot-server` (`parrot.autonomous.ledger`) and
  is NOT part of this phase.
- ~~`aiohttp` usage in registry/mixin/base~~ — only `subscribers/webhook.py`
  uses aiohttp.
- ~~`test_yaml_loader.py` in tests/unit/events/lifecycle/~~ — no dedicated
  yaml_loader test file exists today (verified dir listing); the new injection
  tests in Module 6 are net-new coverage.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Fresh copy, no git history** (resolved in brainstorm): initial commit in
  navigator-eventbus references the ai-parrot origin SHA.
- Preserve module docstrings and FEAT-176/177 references — they document the
  frozen-dataclass performance rationale and model B.
- Frozen dataclasses stay dataclasses (NOT Pydantic) — hot-path instantiation,
  ~5x faster (FEAT-176 rationale; brainstorm-eventbus-v2 resolved the
  dataclass-core/Pydantic-ingress split).
- Lazy in-method imports in `registry.py` (:218, :354, :432) must remain lazy —
  they break import cycles between registry/provider/global_registry.
- `subscribers/__init__.py` in the package exports only `LoggingSubscriber` and
  `WebhookSubscriber` (OpenTelemetrySubscriber stays parrot-side).
- Follow phase-1 scaffold conventions (src-layout, ruff/mypy config, CI matrix).

### Known Risks / Gotchas

- **Phase-1 drift**: this spec assumes phase 1 moved `evb.py` and established
  the scaffold. Re-verify the facade's module path (`navigator_eventbus.evb`)
  when phase 1's spec lands — adjust the TYPE_CHECKING ref if it differs.
- **Divergence window**: `parrot/core/events/lifecycle/` is frozen in ai-parrot
  dev during extraction; any fix lands in the package first (brainstorm
  mitigation). Check for commits touching the source tree since 2026-07-17
  before copying.
- **Global registry is process-global state**: moved tests must keep using
  `scope()` for isolation; running moved + parrot suites in one process (phase
  4) will exercise two distinct global registries until parrot migrates —
  acceptable because phases don't co-import.
- **Bootstrap hook semantics**: the current auto-boot runs on *every* mixin
  init (idempotency inside the bootstrap). Keep hook invocation per-init and
  document that idempotency is the hook's job — do NOT add call-once logic in
  the mixin (would change parrot's semantics on injection).
- **`wire_events` error mode changes**: today an unknown event name fails at
  import of the parrot taxonomy; with the registry it must raise a clear
  `KeyError`/`ValueError` naming the missing registration — tests cover this.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navconfig[default]` | `>=2.2.2` | logging in yaml_loader; package-wide config (phase-1 direct dep) |
| `aiohttp` | (phase-1 pin) | WebhookSubscriber delivery (already direct dep for WS ingress) |
| — | — | No NEW dependencies introduced by this phase |

---

## 8. Open Questions

> All brainstorm questions relevant to this phase were resolved; echoed here
> for the audit trail. No unresolved blockers.

- [x] Typed events destination post-migration — *Resolved in brainstorm*:
  mantener `parrot.core.events.lifecycle` (mínimo diff); typed events
  subclasean `navigator_eventbus.lifecycle.LifecycleEvent`.
- [x] `yaml_loader`: ¿mudar el motor al paquete? — *Resolved in brainstorm*:
  sí — motor de wiring al paquete, tabla de nombres de eventos inyectable
  per-app (ai-parrot registra sus typed events, Flowtask los suyos).
- [x] Mixin observability auto-boot — *Resolved in brainstorm (Constraints)*:
  se reemplaza por hook inyectable; parrot inyecta su bootstrap al
  inicializar bots/clients (fase 4).
- [x] Historia git de archivos mudados — *Resolved in brainstorm*: copia
  fresca; el commit inicial referencia el SHA de origen en ai-parrot.
- [x] Import name — *Resolved in brainstorm*: `navigator_eventbus` (plano).
- [x] CI del repo destino — *Resolved in brainstorm*: GitHub Actions
  (pytest + ruff + mypy) desde la fase 1 — prerequisito, no parte de este spec.
- [x] Exact module path of the facade in the package — *Resolved by phase-1
  spec (FEAT-312)*: `src/navigator_eventbus/evb.py` → `navigator_eventbus.evb`
  (facade moves verbatim, EventBus/Event/EventPriority/EventSubscription).

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — one worktree **in the navigator-eventbus
  repo** (branch from its `main`), NOT in ai-parrot. ai-parrot receives only
  SDD-state commits on `dev`.
- **Task ordering**: sequential within the worktree — Modules 1 → 2 → (3 ∥ 4 ∥ 5)
  → 6. Modules 3, 4, 5 are independent of each other after Module 2 lands, but
  the volume (~1.4k LOC total) does not justify parallel worktrees.
- **Cross-feature dependencies**:
  - **BLOCKING**: `eventbus-core-extraction` (FEAT-312, spec drafted) must be
    implemented first: scaffold, `evb.py` facade, CI.
  - Phase 3 (`eventbus-brokers-port`) is parallelizable with this spec (only
    needs the phase-1 scaffold).
  - Phase 4 (`parrot-eventbus-migration`) consumes this spec's output.
  - Freeze declared on `parrot/core/events/` in ai-parrot dev for the duration.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-17 | Jesus + Claude | Initial draft from navigator-eventbus-extraction brainstorm (phase 2) |
