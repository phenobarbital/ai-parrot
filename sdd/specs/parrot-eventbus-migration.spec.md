---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Parrot EventBus Migration — rewire ai-parrot to `navigator-eventbus`

**Feature ID**: FEAT-317
**Date**: 2026-07-18
**Author**: Jesus (phenobarbital) + Claude
**Status**: approved
**Target version**: ai-parrot 0.26.0

> **Phase 4 of 5** of the extraction plan defined in
> `sdd/proposals/navigator-eventbus-extraction.brainstorm.md` (Option B —
> phased extraction). Prior phases:
>
> - Phase 1: `eventbus-core-extraction` (**FEAT-312**, status: done) — bus
>   core, facade, hooks generic, subscribers, ingress extracted to
>   `navigator-eventbus`.
> - Phase 2: `eventbus-lifecycle-extraction` (**FEAT-313**, status: draft) —
>   lifecycle machinery (LifecycleEvent, TraceContext, EventRegistry, mixin,
>   subscribers logging/webhook, yaml_loader wiring engine) extracted.
> - Phase 3: `eventbus-brokers-port` (**FEAT-316**, status: draft) — port
>   of `navigator.brokers` to `navigator-eventbus.brokers` with PR#393
>   fixes.
>
> **Blocking dependencies**: phases 1, 2, and 3 must be complete before
> this spec can execute. The `navigator-eventbus` package must export the
> full public surface (bus core + lifecycle + brokers) as an editable
> install.
>
> **Next phase**: `navigator-brokers-removal` (phase 5) — deletes
> `navigator/brokers/` from the navigator framework.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-310 delivered the EventBus v2 inside ai-parrot. Phases 1–3 of the
extraction plan copied that code into the standalone `navigator-eventbus`
package (`/home/jesuslara/proyectos/navigator-eventbus`). During those
phases, **ai-parrot was frozen** — it still uses its own copy of the bus
core, lifecycle machinery, and hooks.

This phase completes the extraction: ai-parrot adds `navigator-eventbus`
as a dependency, **deletes the duplicated code** (~6.5k LOC), and
rewrites every import site to use the package. After this phase, the
event fabric lives in one place and ai-parrot is a consumer, not an
owner.

Affected: ~54 production files, ~65 test files, and 2 example files
across three distribution packages (`ai-parrot`, `ai-parrot-server`,
`ai-parrot-integrations`).

### Goals

- Add `navigator-eventbus` as a dependency of `ai-parrot` in
  `pyproject.toml`. Configure legacy Redis prefixes (`parrot:events:`,
  `parrot:stream:`, `parrot:events:dedup:`, consumer-group `parrot-bus`)
  to maintain compatibility with deployed streams.
- Delete all code that was migrated to `navigator-eventbus` in phases 1–3:
  - `parrot/core/events/bus/` (entire directory)
  - `parrot/core/events/evb.py`
  - `parrot/core/events/lifecycle/{base,trace,meta,registry,global_registry,provider,mixin}.py`
  - `parrot/core/events/lifecycle/subscribers/{logging,webhook}.py`
  - `parrot/core/hooks/{base,manager,models,mixins,scheduler,file_watchdog}.py`
  - `parrot/core/hooks/brokers/` (entire directory)
- Rewrite all import sites to use `navigator_eventbus.*` (hard migration,
  no shims — brainstorm decision).
- Preserve and rewire parrot-specific code that stays:
  - **Typed lifecycle events** (`parrot.core.events.lifecycle.events/*`) —
    subclass `navigator_eventbus.lifecycle.LifecycleEvent`.
  - **`legacy_bridge.py`** — stays, imports registry from package.
  - **`yaml_loader.py`** — the parrot-specific event name table stays;
    it delegates to the wiring engine in `navigator_eventbus.lifecycle`
    (delivered by phase 2).
  - **`OpenTelemetrySubscriber`** — stays (depends on typed events).
  - **Integration hooks** (jira, github, sharepoint, whatsapp_redis,
    matrix, imap, messaging, postgres, file_upload) — stay, import
    BaseHook/HookRegistry/models from the package.
  - **`parrot.notifications`** — unchanged (unrelated to migration).
- Inject parrot's observability bootstrap into `EventEmitterMixin` at
  bot/client initialization (the mixin no longer imports
  `parrot.observability` — phase 2 made it hook-injectable).
- Full regression: complete test suite green + FEAT-177 emit-overhead
  benchmark (< 0.1% LLM-latency) without degradation.

### Non-Goals (explicitly out of scope)

- Changes to `navigator-eventbus` code — phases 1–3 already delivered it.
- Elimination of `navigator/brokers/` from the navigator framework —
  **phase 5**.
- Consolidation of Redis Streams consumers (bus vs brokers) — future spec
  `eventbus-streams-consolidation`.
- Shims, re-export facades, or backward-compatibility bridges from
  `parrot.core.events`/`parrot.core.hooks` to `navigator_eventbus` —
  rejected in brainstorm (Option C). All call-sites change.
- PyPI publication of `navigator-eventbus` — happens after this phase
  passes regression, but the publication itself is out of scope.
- Migration of Flowtask/FieldSync/navigator-auth to `navigator-eventbus`
  — each has its own spec in its own repo.

---

## 2. Architectural Design

### Overview

This is a **migration spec, not a design spec** — no new architecture,
algorithms, or data models are introduced. The work is mechanical: delete
duplicated source files and rewrite `from parrot.core.events.*` /
`from parrot.core.hooks.*` imports to `from navigator_eventbus.*`.

All resolved brainstorm decisions carry forward verbatim:
1. **Import name**: `navigator_eventbus` (flat, not PEP 420).
2. **Hard migration**: no `parrot-events-compat` shim, no
   `sys.modules` aliasing.
3. **Redis prefixes**: ai-parrot configures legacy values
   (`parrot:events:`, `parrot:stream:`, `parrot:events:dedup:`,
   `parrot-bus`) via `EventBus` constructor kwargs or navconfig
   overrides — the package defaults are neutral (`evb:*`).
4. **HookType open registry**: integration hooks in parrot register
   their types at import time via `HOOK_TYPES.register(...)` — the 18
   legacy types + `webhook` are already pre-registered by the package
   (FEAT-312 amendment v0.2).
5. **Observability bootstrap**: `EventEmitterMixin` in the package
   accepts an injectable bootstrap hook; parrot injects
   `ensure_observability_bootstrapped` at bot/client init.
6. **yaml_loader**: the wiring engine lives in the package (phase 2);
   parrot's `yaml_loader.py` retains only the event-name table and
   delegates to the engine.

### Component Diagram

```
navigator-eventbus (standalone package, already delivered)
├── EventBus, Event, EventPriority, EventSubscription, EventEnvelope, Severity
├── BusCore, backends/*, converters, DLQ, subscribers/*, ingress/*
├── lifecycle/ (LifecycleEvent, TraceContext, EventRegistry, mixin, ...)
├── hooks/ (BaseHook, HookRegistry, HookManager, HookEvent, models, ...)
└── brokers/ (connection, consumer, producer, redis/rabbitmq/sqs)

ai-parrot (THIS SPEC — consumer after migration)
├── parrot/core/events/
│   ├── __init__.py              ← minimal, no re-exports of bus
│   └── lifecycle/
│       ├── __init__.py          ← re-exports typed events + OpenTelemetry sub
│       ├── events/              ← STAYS: typed events (agent/client/flow/invoke/
│       │                           message/tool), subclass navigator_eventbus.
│       │                           lifecycle.LifecycleEvent
│       ├── legacy_bridge.py     ← STAYS: imports registry from package
│       ├── yaml_loader.py       ← STAYS: event-name table; engine from package
│       └── subscribers/
│           └── opentelemetry.py ← STAYS: depends on typed events
├── parrot/core/hooks/
│   ├── __init__.py              ← re-exports integration hooks + package symbols
│   ├── github_webhook.py        ← STAYS: BaseHook/models from package
│   ├── jira_webhook.py          ← STAYS
│   ├── sharepoint.py            ← STAYS
│   ├── whatsapp_redis.py        ← STAYS
│   ├── matrix.py                ← STAYS
│   ├── imap.py                  ← STAYS
│   ├── messaging.py             ← STAYS
│   ├── postgres.py              ← STAYS
│   └── file_upload.py           ← STAYS
├── parrot/bots/* clients/* observability/* eval/* registry/* auth/*
│   └── (imports rewritten to navigator_eventbus)
└── (ai-parrot-server, ai-parrot-integrations — imports rewritten)
```

### Import Rewiring Table

The canonical mapping for all import sites. Agents implementing tasks
MUST use this table — do not invent import paths.

| Old import (parrot) | New import (navigator_eventbus) |
|---|---|
| `parrot.core.events.EventBus` | `navigator_eventbus.EventBus` |
| `parrot.core.events.Event` | `navigator_eventbus.Event` |
| `parrot.core.events.EventPriority` | `navigator_eventbus.EventPriority` |
| `parrot.core.events.EventSubscription` | `navigator_eventbus.EventSubscription` |
| `parrot.core.events.evb.EventBus` | `navigator_eventbus.evb.EventBus` (or top-level) |
| `parrot.core.events.evb.Event` | `navigator_eventbus.evb.Event` |
| `parrot.core.events.evb.EventPriority` | `navigator_eventbus.evb.EventPriority` |
| `parrot.core.events.bus.envelope.EventEnvelope` | `navigator_eventbus.envelope.EventEnvelope` (or top-level) |
| `parrot.core.events.bus.envelope.Severity` | `navigator_eventbus.envelope.Severity` (or top-level) |
| `parrot.core.events.bus.core.BusCore` | `navigator_eventbus.core.BusCore` (or top-level) |
| `parrot.core.events.bus.core.BusClosedError` | `navigator_eventbus.core.BusClosedError` (or top-level) |
| `parrot.core.events.bus.backends.*` | `navigator_eventbus.backends.*` |
| `parrot.core.events.bus.converters.*` | `navigator_eventbus.converters.*` |
| `parrot.core.events.bus.dlq.*` | `navigator_eventbus.dlq.*` |
| `parrot.core.events.bus.ingress_models.*` | `navigator_eventbus.ingress_models.*` |
| `parrot.core.events.bus.ingress.*` | `navigator_eventbus.ingress.*` |
| `parrot.core.events.bus.subscribers.*` | `navigator_eventbus.subscribers.*` |
| `parrot.core.events.lifecycle.base.LifecycleEvent` | `navigator_eventbus.lifecycle.base.LifecycleEvent` |
| `parrot.core.events.lifecycle.trace.TraceContext` | `navigator_eventbus.lifecycle.trace.TraceContext` |
| `parrot.core.events.lifecycle.meta.SubscriberErrorEvent` | `navigator_eventbus.lifecycle.meta.SubscriberErrorEvent` |
| `parrot.core.events.lifecycle.registry.EventRegistry` | `navigator_eventbus.lifecycle.registry.EventRegistry` |
| `parrot.core.events.lifecycle.registry.AsyncSubscriber` | `navigator_eventbus.lifecycle.registry.AsyncSubscriber` |
| `parrot.core.events.lifecycle.global_registry.*` | `navigator_eventbus.lifecycle.global_registry.*` |
| `parrot.core.events.lifecycle.provider.EventProvider` | `navigator_eventbus.lifecycle.provider.EventProvider` |
| `parrot.core.events.lifecycle.mixin.EventEmitterMixin` | `navigator_eventbus.lifecycle.mixin.EventEmitterMixin` |
| `parrot.core.events.lifecycle.subscribers.logging.LoggingSubscriber` | `navigator_eventbus.lifecycle.subscribers.logging.LoggingSubscriber` |
| `parrot.core.events.lifecycle.subscribers.webhook.WebhookSubscriber` | `navigator_eventbus.lifecycle.subscribers.webhook.WebhookSubscriber` |
| `parrot.core.hooks.BaseHook` | `navigator_eventbus.hooks.BaseHook` |
| `parrot.core.hooks.HookRegistry` | `navigator_eventbus.hooks.HookRegistry` |
| `parrot.core.hooks.base.BaseHook` | `navigator_eventbus.hooks.base.BaseHook` |
| `parrot.core.hooks.base.HookRegistry` | `navigator_eventbus.hooks.base.HookRegistry` |
| `parrot.core.hooks.base.MessagingHook` | `navigator_eventbus.hooks.base.MessagingHook` |
| `parrot.core.hooks.HookManager` | `navigator_eventbus.hooks.HookManager` |
| `parrot.core.hooks.manager.HookManager` | `navigator_eventbus.hooks.manager.HookManager` |
| `parrot.core.hooks.HookEvent` | `navigator_eventbus.hooks.HookEvent` |
| `parrot.core.hooks.models.HookEvent` | `navigator_eventbus.hooks.models.HookEvent` |
| `parrot.core.hooks.models.HookType` | `navigator_eventbus.hooks.models.HookType` |
| `parrot.core.hooks.models.*Config` | `navigator_eventbus.hooks.models.*Config` |
| `parrot.core.hooks.models.TransitionAction` | `navigator_eventbus.hooks.models.TransitionAction` |
| `parrot.core.hooks.models.TransitionActionType` | `navigator_eventbus.hooks.models.TransitionActionType` |
| `parrot.core.hooks.HookableAgent` | `navigator_eventbus.hooks.HookableAgent` |
| `parrot.core.hooks.mixins.HookableAgent` | `navigator_eventbus.hooks.mixins.HookableAgent` |

**Imports that do NOT change** (typed events stay in parrot):
- `parrot.core.events.lifecycle.events.*` — all typed events remain local
- `parrot.core.events.lifecycle.legacy_bridge.*` — stays local
- `parrot.core.events.lifecycle.yaml_loader.*` — stays local (table only)
- `parrot.core.events.lifecycle.subscribers.opentelemetry.*` — stays local
- `parrot.core.hooks.{github_webhook,jira_webhook,...}` — integration
  hooks stay local (but their internal imports of `base`/`models` change
  to navigator_eventbus)

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator-eventbus` (package) | new dependency | editable install during dev; PyPI after regression passes |
| `packages/ai-parrot/pyproject.toml` | modifies | adds `navigator-eventbus` to `[project.dependencies]` |
| `packages/ai-parrot-server/pyproject.toml` | unchanged | inherits transitively via `ai-parrot` |
| `packages/ai-parrot-integrations/pyproject.toml` | unchanged | inherits transitively via `ai-parrot` |
| `parrot/core/events/` | modifies (partial delete) | bus core + lifecycle machinery + evb.py deleted; typed events stay |
| `parrot/core/hooks/` | modifies (partial delete) | generic hooks deleted; integration hooks stay |
| `parrot/bots/{abstract,base}.py` | modifies (imports) | EventEmitterMixin, TraceContext, typed events |
| `parrot/clients/*.py` | modifies (imports) | EventEmitterMixin, TraceContext, typed events, stream chunk events |
| `parrot/observability/*.py` | modifies (imports) | EventRegistry, global_registry, typed events |
| `parrot/eval/{events,runner}.py` | modifies (imports) | LifecycleEvent, EventBus, EventRegistry |
| `parrot/registry/registry.py` | modifies (import) | yaml_loader.wire_events |
| `parrot/auth/permission.py` | modifies (import) | TraceContext |
| `autonomous/{evb,ledger,orchestrator,webhooks}.py` | modifies (imports) | EventBus, LifecycleEvent, hooks |
| `autonomous/transport/filesystem/hook.py` | modifies (imports) | BaseHook, models |
| `integrations/matrix/hook.py` | modifies (imports) | BaseHook, HookRegistry, models |

---

## 3. Module Breakdown

### Module 1: Add dependency and configure prefix overrides
- **Path**: `packages/ai-parrot/pyproject.toml`, configuration bootstrap
- **Responsibility**: Add `navigator-eventbus` as a core dependency.
  Migrate ai-parrot's `grpc` extra to depend on
  `navigator-eventbus[grpc]`. Ensure the `EventBus` instantiation site
  (`AutonomousOrchestrator`) passes legacy Redis prefix kwargs
  (`channel_prefix="parrot:events:"`, etc.) to maintain compatibility
  with deployed streams. Verify editable install works:
  `source .venv/bin/activate && uv pip install -e /home/jesuslara/proyectos/navigator-eventbus && python -c "from navigator_eventbus import EventBus"`.
- **Depends on**: phases 1–3 complete

### Module 2: Rewire and delete `parrot/core/events/` bus core
- **Path**: `packages/ai-parrot/src/parrot/core/events/`
- **Responsibility**:
  - Delete `evb.py` and `bus/` (entire directory).
  - Rewrite `events/__init__.py` to a minimal stub (no re-exports of
    EventBus etc. — hard migration; the package only hosts typed events
    now).
  - Any file that imported from `parrot.core.events.evb` or
    `parrot.core.events.bus.*` must be updated in this or a later module.
- **Depends on**: Module 1

### Module 3: Rewire and delete `parrot/core/events/lifecycle/` machinery
- **Path**: `packages/ai-parrot/src/parrot/core/events/lifecycle/`
- **Responsibility**:
  - Delete `base.py`, `trace.py`, `meta.py`, `registry.py`,
    `global_registry.py`, `provider.py`, `mixin.py`.
  - Delete `subscribers/logging.py`, `subscribers/webhook.py`.
  - Rewrite `lifecycle/__init__.py`: re-export typed events from
    `.events` and OpenTelemetrySubscriber from `.subscribers.opentelemetry`;
    re-export lifecycle machinery (LifecycleEvent, TraceContext,
    EventRegistry, EventEmitterMixin, etc.) from `navigator_eventbus.lifecycle`.
  - Rewrite `lifecycle/subscribers/__init__.py`: only OpenTelemetrySubscriber
    stays; LoggingSubscriber and WebhookSubscriber re-exported from
    `navigator_eventbus.lifecycle.subscribers`.
  - Rewire typed events (`events/{agent,client,flow,invoke,message,tool}.py`):
    change `from parrot.core.events.lifecycle.base import LifecycleEvent`
    to `from navigator_eventbus.lifecycle.base import LifecycleEvent`.
  - Rewire `legacy_bridge.py`: registry import from package.
  - Rewire `yaml_loader.py`: registry and base imports from package;
    keep the parrot-specific event-name table; delegate to the package's
    wiring engine (phase 2 delivery).
  - Rewire `subscribers/opentelemetry.py`: LifecycleEvent and EventRegistry
    from package; typed events from local `.events`.
- **Depends on**: Module 2

### Module 4: Rewire and delete `parrot/core/hooks/` generic code
- **Path**: `packages/ai-parrot/src/parrot/core/hooks/`
- **Responsibility**:
  - Delete `base.py`, `manager.py`, `models.py`, `mixins.py`,
    `scheduler.py`, `file_watchdog.py`.
  - Delete `brokers/` (entire directory).
  - Rewrite `hooks/__init__.py`: import BaseHook, HookRegistry,
    MessagingHook, HookManager, HookableAgent, HookEvent, HookType, all
    config models, TransitionAction/Type, and factory helpers from
    `navigator_eventbus.hooks`; lazy-import integration hooks from local
    submodules (github_webhook, jira_webhook, sharepoint, etc.); lazy-import
    generic hooks (SchedulerHook, FileWatchdogHook, broker hooks) from
    `navigator_eventbus.hooks`.
  - Rewire each integration hook file to import BaseHook, HookType, and
    config models from `navigator_eventbus.hooks` (currently relative
    imports `.base`, `.models` — must change to absolute since the source
    files are deleted).
- **Depends on**: Module 2

### Module 5: Rewire bots and clients
- **Path**: `packages/ai-parrot/src/parrot/{bots,clients}/`
- **Responsibility**: Rewrite imports per the Import Rewiring Table in
  the following files:
  - `bots/abstract.py` — EventEmitterMixin, TraceContext from package;
    typed events stay local; _LegacyEventBridge stays local. Inject
    observability bootstrap into EventEmitterMixin if needed.
  - `bots/base.py` — TraceContext from package; typed events stay local.
  - `bots/flows/core/context.py` — TraceContext from package.
  - `bots/flows/flow/telemetry.py` — LifecycleEvent, EventRegistry,
    TraceContext, global_registry from package; flow typed events stay
    local.
  - `bots/github_reviewer.py` — GitHubWebhookHook stays local; config
    models and HookEvent from package.
  - `bots/jira_specialist.py` — HookEvent, TransitionAction models from
    package.
  - `clients/base.py` — EventEmitterMixin, TraceContext from package;
    typed events stay local.
  - `clients/claude.py` — typed events stay local; TraceContext from
    package.
  - `clients/claude_agent.py` — ClientStreamChunkEvent stays local.
  - `clients/google/client.py` — ClientStreamChunkEvent stays local.
  - `clients/gpt.py` — typed events stay local; TraceContext from package.
  - `clients/grok.py` — ClientStreamChunkEvent stays local.
  - `clients/groq.py` — ClientStreamChunkEvent stays local.
- **Depends on**: Modules 3, 4

### Module 6: Rewire observability, eval, registry, and auth
- **Path**: `packages/ai-parrot/src/parrot/{observability,eval,registry,auth}/`
- **Responsibility**: Rewrite imports per the Import Rewiring Table:
  - `observability/attributes.py` — typed events stay local.
  - `observability/bootstrap.py` — global_registry from package.
  - `observability/provider.py` — EventRegistry from package.
  - `observability/setup.py` — global_registry from package.
  - `observability/recorders/subscriber.py` — typed events stay local;
    EventRegistry from package.
  - `observability/subscribers/metrics.py` — typed events stay local;
    EventRegistry from package.
  - `observability/subscribers/trace.py` — LifecycleEvent and
    EventRegistry from package; typed events stay local.
  - `observability/traceloop_integration.py` — global_registry from
    package.
  - `eval/events.py` — LifecycleEvent from package.
  - `eval/runner.py` — EventBus from package; EventRegistry and
    TraceContext from package.
  - `registry/registry.py` — `yaml_loader.wire_events` stays local
    (no change needed — the import is already
    `parrot.core.events.lifecycle.yaml_loader`).
  - `auth/permission.py` — TraceContext from package.
- **Depends on**: Modules 3, 4

### Module 7: Rewire ai-parrot-server and ai-parrot-integrations
- **Path**: `packages/ai-parrot-server/src/`, `packages/ai-parrot-integrations/src/`
- **Responsibility**: Rewrite imports:
  - `autonomous/evb.py` — change re-export from
    `parrot.core.events.evb` to `navigator_eventbus.evb` (or delete the
    shim and rewire its consumers to import from
    `navigator_eventbus` directly — evaluate which is less churn).
  - `autonomous/ledger.py` — LifecycleEvent, global_registry from
    package.
  - `autonomous/orchestrator.py` — EventBus, Event, EventPriority from
    package; BaseHook, HookManager, HookEvent from package. Pass legacy
    Redis prefix kwargs when constructing EventBus.
  - `autonomous/webhooks.py` — EventBus from package.
  - `autonomous/transport/filesystem/hook.py` — BaseHook and models
    from package.
  - `integrations/matrix/hook.py` — BaseHook, HookRegistry, models
    from package.
- **Depends on**: Modules 3, 4

### Module 8: Test suite migration
- **Path**: `packages/ai-parrot/tests/`, `packages/ai-parrot-server/tests/`
- **Responsibility**:
  - **Delete** tests that were already migrated to navigator-eventbus
    (bus core tests): `tests/core/events/bus/` (entire directory — these
    tests now live in navigator-eventbus's own test suite).
  - **Delete** `tests/core/events/test_eventbus_imports.py` (tests the
    old `__all__` of `parrot.core.events` which changes shape).
  - **Rewire** all remaining 65 test files that import from
    `parrot.core.events` or `parrot.core.hooks` per the Import Rewiring
    Table. Key areas:
    - `tests/core/hooks/` — hook tests stay (test integration hooks);
      rewire base/models/manager imports from package.
    - `tests/unit/events/lifecycle/` — tests for typed events stay;
      tests for lifecycle machinery (registry, mixin, provider, etc.)
      stay but import from package.
    - `tests/unit/observability/` — typed events stay local; lifecycle
      machinery from package.
    - `tests/benchmarks/test_lifecycle_perf.py` — rewire lifecycle
      imports from package.
    - Server tests: `test_ledger_*`, `test_orchestrator_hooks_via_bus`
      — rewire imports.
  - **Add** migration guard test: `test_no_bus_core_in_parrot` — asserts
    that `parrot.core.events.bus` is not importable (code was deleted),
    and that `parrot.core.events.evb` is not importable.
  - **Add** `test_navigator_eventbus_integration` — smoke test that
    `from navigator_eventbus import EventBus, EventEnvelope, Severity`
    resolves and basic emit works.
  - **Update** `tests/conftest.py` if any stubs reference deleted modules.
  - **Update** example files: `examples/dev_loop/e2e_demo.py`.
- **Depends on**: Modules 2–7

### Module 9: Regression and benchmark
- **Path**: project-wide
- **Responsibility**:
  - Run full test suite: `pytest tests/ -v` across all three packages.
  - Run FEAT-177 emit-overhead benchmark:
    `python scripts/bench/feat310_emit_overhead.py` — confirm < 0.1%
    LLM-latency overhead, no regression vs FEAT-310 baseline.
  - Run linting: `ruff check .` and `mypy` on changed files.
  - Verify editable install in clean venv:
    `uv venv /tmp/test-migration && source /tmp/test-migration/bin/activate && uv pip install -e /home/jesuslara/proyectos/navigator-eventbus && uv pip install -e packages/ai-parrot && python -c "from navigator_eventbus import EventBus; from parrot.core.events.lifecycle.events import BeforeInvokeEvent; print('OK')"`.
- **Depends on**: Module 8

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_no_bus_core_in_parrot` | 8 | `import parrot.core.events.bus` raises ImportError; `import parrot.core.events.evb` raises ImportError |
| `test_no_old_hooks_in_parrot` | 8 | `import parrot.core.hooks.base` raises ImportError (base.py deleted); `import parrot.core.hooks.models` raises ImportError |
| `test_navigator_eventbus_smoke` | 8 | `from navigator_eventbus import EventBus, EventEnvelope, Severity` resolves; basic emit→subscribe round-trip works |
| `test_typed_events_subclass` | 8 | `BeforeInvokeEvent` is still a subclass of `LifecycleEvent` (via `navigator_eventbus.lifecycle.base`) |
| `test_hooks_init_reexports` | 8 | `from parrot.core.hooks import BaseHook, HookManager, HookEvent` resolves (re-exported from package) |
| `test_lifecycle_init_reexports` | 8 | `from parrot.core.events.lifecycle import EventRegistry, LifecycleEvent, TraceContext, BeforeInvokeEvent` resolves |
| `test_no_parrot_imports_in_navigator_eventbus` | (in navigator-eventbus) | Already exists from phase 1 — `grep -r "from parrot" src/` → empty |
| existing lifecycle/hooks/observability test suite | 8 | All pre-existing tests pass with rewired imports |

### Integration Tests

| Test | Description |
|---|---|
| `test_orchestrator_eventbus_prefixes` | `AutonomousOrchestrator` creates `EventBus` with `parrot:events:` prefix; verify via `bus.CHANNEL_PREFIX` |
| `test_end_to_end_emit_subscribe` | emit via `navigator_eventbus.EventBus` → subscriber receives `EventEnvelope` with correct topic/payload |
| `test_hookmanager_via_package` | `HookManager` from package + integration hook from parrot → hook event published to bus |
| `test_lifecycle_perf_no_regression` | FEAT-177 benchmark: dual-emit overhead < 0.1% LLM-latency |

### Test Data / Fixtures

```python
@pytest.fixture
def eventbus_with_parrot_prefixes():
    """EventBus configured with legacy parrot:* prefixes."""
    from navigator_eventbus import EventBus
    bus = EventBus(
        channel_prefix="parrot:events:",
        use_redis=False,
    )
    return bus
```

---

## 5. Acceptance Criteria

- [ ] `navigator-eventbus` is a declared dependency in
      `packages/ai-parrot/pyproject.toml`.
- [ ] `uv pip install -e packages/ai-parrot` resolves and
      `from navigator_eventbus import EventBus` works in the venv.
- [ ] **Zero** `from parrot.core.events.bus` or
      `from parrot.core.events.evb` imports remain anywhere in the repo
      (verified by grep).
- [ ] **Zero** `from parrot.core.hooks.base` or
      `from parrot.core.hooks.models` or `from parrot.core.hooks.manager`
      imports remain anywhere except in `parrot/core/hooks/__init__.py`
      (which re-exports from the package).
- [ ] `parrot/core/events/bus/` directory does not exist.
- [ ] `parrot/core/events/evb.py` does not exist.
- [ ] `parrot/core/events/lifecycle/{base,trace,meta,registry,global_registry,provider,mixin}.py`
      do not exist.
- [ ] `parrot/core/events/lifecycle/subscribers/{logging,webhook}.py` do
      not exist.
- [ ] `parrot/core/hooks/{base,manager,models,mixins,scheduler,file_watchdog}.py`
      do not exist.
- [ ] `parrot/core/hooks/brokers/` directory does not exist.
- [ ] Typed events (`parrot.core.events.lifecycle.events.*`) still importable
      and subclass `navigator_eventbus.lifecycle.LifecycleEvent`.
- [ ] Integration hooks (`parrot.core.hooks.{github_webhook,jira_webhook,...}`)
      still importable and subclass `navigator_eventbus.hooks.BaseHook`.
- [ ] `parrot.core.hooks.__init__` re-exports BaseHook, HookManager, HookEvent,
      all config models, and lazy-loads integration hooks — preserving the
      public surface of `from parrot.core.hooks import X`.
- [ ] `parrot.core.events.lifecycle.__init__` re-exports typed events,
      OpenTelemetrySubscriber, AND lifecycle machinery from
      `navigator_eventbus.lifecycle` — preserving the public surface of
      `from parrot.core.events.lifecycle import X`.
- [ ] `AutonomousOrchestrator` constructs `EventBus` with legacy Redis
      prefixes (`parrot:events:`, `parrot:stream:`, `parrot-bus`).
- [ ] Full test suite green: `pytest` across ai-parrot, ai-parrot-server,
      ai-parrot-integrations.
- [ ] FEAT-177 emit-overhead benchmark: < 0.1% LLM-latency, no regression.
- [ ] `ruff check .` clean on changed files.
- [ ] Migration guard tests added and passing.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section anchors the migration to verified code locations.
> Implementation agents MUST consult this before writing any import.

### Verified Imports — navigator_eventbus (target)

```python
# Top-level re-exports (verified in navigator-eventbus __init__.py):
from navigator_eventbus import (
    EventBus, Event, EventPriority, EventSubscription,  # facade
    EventEnvelope, Severity,                              # envelope
    BusCore, BackpressureError, BusClosedError,           # core
    DLQHandler,                                           # dlq
    IngressEnvelope,                                      # ingress models
)

# Hooks (verified in navigator-eventbus hooks/__init__.py):
from navigator_eventbus.hooks import (
    BaseHook, HookRegistry, MessagingHook,                # base
    HookManager,                                          # manager
    HookableAgent,                                        # mixins
    HookEvent, HookType, HookTypeRegistry, HOOK_TYPES,   # models
    # All config models:
    BrokerHookConfig, FilesystemHookConfig, FileUploadHookConfig,
    FileWatchdogHookConfig, GitHubWebhookConfig, IMAPHookConfig,
    JiraWebhookConfig, MatrixHookConfig, MessagingHookConfig,
    PostgresHookConfig, SchedulerHookConfig, SharePointHookConfig,
    WhatsAppRedisHookConfig,
    TransitionAction, TransitionActionType,
    create_simple_whatsapp_hook, create_multi_agent_whatsapp_hook,
    create_crew_whatsapp_hook,
)

# Lifecycle (will be verified after phase 2 delivers — paths based on
# brainstorm spec and phase 1 naming convention):
from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.trace import TraceContext
from navigator_eventbus.lifecycle.meta import SubscriberErrorEvent
from navigator_eventbus.lifecycle.registry import EventRegistry, AsyncSubscriber
from navigator_eventbus.lifecycle.global_registry import get_global_registry, scope
from navigator_eventbus.lifecycle.provider import EventProvider
from navigator_eventbus.lifecycle.mixin import EventEmitterMixin
from navigator_eventbus.lifecycle.subscribers.logging import LoggingSubscriber
from navigator_eventbus.lifecycle.subscribers.webhook import WebhookSubscriber

# Backends:
from navigator_eventbus.backends import (
    MemoryBackend, RedisStreamsBackend, RedisPubSubBackend, TransportBackend,
)

# Subscribers:
from navigator_eventbus.subscribers import (
    NotificationSubscriber, AuditSubscriber, MetricsSubscriber,
)
```

### Verified Imports — parrot (what stays, source)

```python
# Typed lifecycle events (STAY in parrot — do NOT delete):
from parrot.core.events.lifecycle.events import (
    BeforeInvokeEvent, AfterInvokeEvent,
    BeforeClientCallEvent, AfterClientCallEvent,
    ClientStreamChunkEvent,
    BeforeToolCallEvent, AfterToolCallEvent,
    AgentStatusChangedEvent,
    MessageAddedEvent,
    # Flow events:
    FlowStartedEvent, FlowCompletedEvent, FlowFailedEvent,
    NodeStartedEvent, NodeCompletedEvent, NodeFailedEvent,
    NodeSkippedEvent,
)
# verified: packages/ai-parrot/src/parrot/core/events/lifecycle/events/__init__.py

# Legacy bridge (STAYS):
from parrot.core.events.lifecycle.legacy_bridge import _LegacyEventBridge
# verified: packages/ai-parrot/src/parrot/core/events/lifecycle/legacy_bridge.py:20

# yaml_loader (STAYS — event-name table):
from parrot.core.events.lifecycle.yaml_loader import wire_events
# verified: packages/ai-parrot/src/parrot/core/events/lifecycle/yaml_loader.py:26

# OpenTelemetry subscriber (STAYS):
from parrot.core.events.lifecycle.subscribers.opentelemetry import OpenTelemetrySubscriber
# verified: packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/opentelemetry.py:22

# Integration hooks (STAY — these import BaseHook/models via relative imports
# that must be changed to navigator_eventbus absolute imports):
#   github_webhook.py: from .base import BaseHook; from .models import GitHubWebhookConfig, HookType
#   jira_webhook.py: from .base import BaseHook; from .models import HookType, JiraWebhookConfig
#   sharepoint.py: from .base import BaseHook; from .models import HookType, SharePointHookConfig
#   whatsapp_redis.py: from .base import BaseHook; from .models import HookType, WhatsAppRedisHookConfig
#   imap.py: from .base import BaseHook; from .models import HookType, IMAPHookConfig
#   messaging.py: from .base import BaseHook; from .models import HookType, MessagingHookConfig
#   postgres.py: from .base import BaseHook; from .models import HookType, PostgresHookConfig
#   file_upload.py: from .base import BaseHook; from .models import FileUploadHookConfig, HookType
#   matrix.py (core): from .base import BaseHook, HookRegistry; from .models import HookType, MatrixHookConfig
```

### Existing Class Signatures — Key Consumer Sites

```python
# AutonomousOrchestrator — THE singleton EventBus constructor
# packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py:231
#   Currently: from parrot.core.events import EventBus, Event, EventPriority
#   Change to: from navigator_eventbus import EventBus, Event, EventPriority
#   Add prefix kwargs: EventBus(channel_prefix="parrot:events:", ...)

# autonomous/evb.py — re-export shim
# packages/ai-parrot-server/src/parrot/autonomous/evb.py:7
#   Currently: from parrot.core.events.evb import (Event, EventBus, EventPriority, EventSubscription)
#   Change to: from navigator_eventbus.evb import (Event, EventBus, EventPriority, EventSubscription)

# parrot/core/hooks/__init__.py — lazy-import map
# packages/ai-parrot/src/parrot/core/hooks/__init__.py
#   Currently: from .base import BaseHook, HookRegistry, MessagingHook
#   Change to: from navigator_eventbus.hooks.base import BaseHook, HookRegistry, MessagingHook
#   And so on for all eager imports from .manager, .models, .mixins
#   Lazy-imports for generic hooks (SchedulerHook, etc.) change from
#   ".scheduler" to "navigator_eventbus.hooks.scheduler"
#   Lazy-imports for integration hooks (JiraWebhookHook, etc.) stay
#   pointing to local ".jira_webhook" etc.
```

### Census of Production Files to Modify

**ai-parrot** (25 external consumers + 13 internal rewires):
- `bots/abstract.py` — EventEmitterMixin, TraceContext, typed events, _LegacyEventBridge
- `bots/base.py` — TraceContext, typed events
- `bots/flows/core/context.py` — TraceContext (TYPE_CHECKING)
- `bots/flows/flow/telemetry.py` — LifecycleEvent, flow events, EventRegistry, TraceContext, global_registry
- `bots/github_reviewer.py` — GitHubWebhookHook (local), config models + HookEvent (package)
- `bots/jira_specialist.py` — HookEvent, TransitionAction models (package)
- `clients/base.py` — EventEmitterMixin, TraceContext, typed events
- `clients/claude.py` — typed events, TraceContext
- `clients/claude_agent.py` — ClientStreamChunkEvent (local)
- `clients/google/client.py` — ClientStreamChunkEvent (local)
- `clients/gpt.py` — typed events, TraceContext
- `clients/grok.py` — ClientStreamChunkEvent (local)
- `clients/groq.py` — ClientStreamChunkEvent (local)
- `auth/permission.py` — TraceContext (TYPE_CHECKING)
- `eval/events.py` — LifecycleEvent
- `eval/runner.py` — EventBus, EventRegistry, TraceContext
- `observability/attributes.py` — typed events
- `observability/bootstrap.py` — global_registry
- `observability/provider.py` — EventRegistry
- `observability/setup.py` — global_registry
- `observability/recorders/subscriber.py` — typed events, EventRegistry
- `observability/subscribers/metrics.py` — typed events, EventRegistry
- `observability/subscribers/trace.py` — LifecycleEvent, typed events, EventRegistry
- `observability/traceloop_integration.py` — global_registry
- `registry/registry.py` — yaml_loader (stays local, no change)

**ai-parrot-server** (5 files):
- `autonomous/evb.py`, `autonomous/ledger.py`, `autonomous/orchestrator.py`,
  `autonomous/webhooks.py`, `autonomous/transport/filesystem/hook.py`

**ai-parrot-integrations** (1 file):
- `integrations/matrix/hook.py`

**Internal (core/events + core/hooks — files that stay but need rewiring):**
- `core/events/__init__.py`, `core/events/lifecycle/__init__.py`,
  `core/events/lifecycle/subscribers/__init__.py`
- `core/events/lifecycle/events/{__init__,agent,client,flow,invoke,message,tool}.py`
- `core/events/lifecycle/{legacy_bridge,yaml_loader}.py`,
  `core/events/lifecycle/subscribers/opentelemetry.py`
- `core/hooks/__init__.py`
- `core/hooks/{github_webhook,jira_webhook,sharepoint,whatsapp_redis,imap,messaging,postgres,file_upload,matrix}.py`

### Does NOT Exist (Anti-Hallucination)

- ~~`navigator_eventbus.lifecycle.*`~~ — does NOT exist yet as of
  2026-07-18; phase 2 (FEAT-313) will create it. The import paths in
  this spec are **projected** based on the brainstorm and phase 1
  naming conventions. Implementation MUST verify the actual paths
  exported by the package before rewiring.
- ~~`navigator-eventbus` in `ai-parrot/pyproject.toml`~~ — not present
  yet; Module 1 adds it.
- ~~`parrot.core.events.lifecycle.yaml_loader` wiring engine~~ — after
  phase 2, the engine moves to `navigator_eventbus.lifecycle.yaml_loader`;
  parrot's file retains only the event-name table. Implementation must
  verify what phase 2 actually delivered before rewiring.
- ~~Shim/compat layer in `parrot.core.events.__init__`~~ — the hard
  migration decision means no re-exports of EventBus etc. from parrot.
  All consumers import directly from `navigator_eventbus`.
- ~~`parrot.core.hooks.base.py` after migration~~ — this file is deleted.
  Integration hooks that used relative `from .base import BaseHook` must
  switch to absolute `from navigator_eventbus.hooks.base import BaseHook`.
- ~~`FilesystemHookConfig` in old `parrot.core.hooks.models`~~ — this
  model was added by phase 1 in the package; it may not exist in parrot's
  current `models.py`. The package is canonical.
- ~~`parrot.core.hooks.matrix` as a standalone module~~ — `matrix.py`
  exists in `parrot/core/hooks/` BUT it's just a re-export/stub; the
  real matrix hook lives in `ai-parrot-integrations`
  (`integrations/matrix/hook.py`).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Mechanical rewiring only** — do not refactor, redesign, or improve
  any code touched by this spec. The only change to each file is
  updating import statements. If a function body mentions a removed
  module path in a string (docstring, error message, deprecation
  warning), update the string too.
- **Delete before rewiring is fine** within a single commit — the
  `__init__.py` files that remain will re-export from the package, so
  backward-compatible symbols resolve. But verify: run
  `python -c "from parrot.core.events.lifecycle import EventRegistry"`
  after each module's commit.
- **Prefer `navigator_eventbus.X` top-level imports** (e.g.
  `from navigator_eventbus import EventBus`) when the symbol is
  re-exported at the package root. Use submodule paths
  (`from navigator_eventbus.lifecycle.registry import EventRegistry`)
  only when the symbol is not at the top level.
- **Preserve TYPE_CHECKING guards** — imports inside
  `if TYPE_CHECKING:` blocks that change source must still be inside
  the guard.
- **Commit per module** — one logical commit per Module in §3, so
  bisection is possible.

### Known Risks / Gotchas

- **Phase 2/3 not yet delivered**: this spec cannot execute until
  FEAT-313 (lifecycle extraction) and FEAT-316 (brokers port) are
  complete. The lifecycle import paths in §6 are projected — verify
  against the actual package before implementing.
- **`lifecycle/__init__.py` re-export surface**: the current
  `parrot.core.events.lifecycle.__init__` re-exports ~30 symbols.
  After migration, it must re-export the same symbols (sourced from
  the package + local typed events) to avoid breaking internal
  consumers that use the shortcut import. Missing any symbol will cause
  ImportError in downstream modules.
- **Relative imports in integration hooks**: all 9 integration hook
  files use `from .base import BaseHook` / `from .models import ...`.
  Since `base.py` and `models.py` are deleted, these relative imports
  MUST change to absolute imports from `navigator_eventbus.hooks`.
  Forgetting even one file will cause ImportError at hook registration
  time.
- **`hooks/__init__.py` lazy-import map**: the lazy-import `__getattr__`
  currently points to local submodules (`.scheduler`, `.brokers.redis`,
  etc.). After migration, generic hooks (SchedulerHook, FileWatchdogHook,
  all broker hooks) must lazy-import from `navigator_eventbus.hooks`
  submodules. Integration hooks (JiraWebhookHook, etc.) stay local.
  The map must be carefully split.
- **Streams compatibility**: deployed Redis instances may have data in
  `parrot:stream:*` streams with consumer-group `parrot-bus`. The
  `EventBus` constructor must explicitly pass these legacy prefixes —
  the package defaults are `evb:*`.
- **`autonomous/evb.py` shim**: this file re-exports EventBus from
  `parrot.core.events.evb` for backward compatibility. After `evb.py`
  is deleted, the shim must point to `navigator_eventbus.evb` (or be
  deleted if no external consumer depends on it — check git blame).
- **Test conftest stubs**: `tests/conftest.py` stubs out `navconfig`
  and `navigator.utils` modules. After migration, navigator-eventbus
  imports navconfig at import time — verify the stubs don't conflict
  with the real navconfig the package needs.
- **Examples**: `examples/dev_loop/e2e_demo.py` imports from
  `parrot.core.events` — update it.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navigator-eventbus` | `>=0.1.0` | provides EventBus, lifecycle, hooks, brokers — the entire event fabric |

(All other dependencies — `navconfig`, `asyncdb`, `redis`, `grpcio`,
`async-notify` — are now transitive via `navigator-eventbus` and its
extras. ai-parrot may keep its own declarations if needed for other
features.)

---

## 8. Open Questions

> All design questions for this phase were resolved in the brainstorm.
> Listed as audit trail — do NOT re-open.

- [x] Import migration strategy: hard or shim? — *Resolved in brainstorm*:
  hard migration, no shims. All call-sites in ai-parrot change to
  `from navigator_eventbus import ...`.
- [x] Should `parrot.core.events.__init__` re-export EventBus from the
  package for convenience? — *Resolved in brainstorm*: no — hard migration
  means consumers import from `navigator_eventbus` directly.
- [x] Redis prefix configuration: how does ai-parrot pass legacy values?
  — *Resolved in brainstorm*: `EventBus` constructor kwargs +
  navconfig overrides; defaults are neutral in the package.
- [x] HookType: will ai-parrot integration hooks need to register their
  hook types? — *Resolved in brainstorm (amended FEAT-312 v0.2)*: no —
  all 18 legacy types are pre-registered in the package at import time;
  integration hooks work without registration.
- [x] What about `parrot.notifications`? — *Resolved in brainstorm*:
  unchanged, stays in parrot. NotificationSubscriber in the package
  accepts any duck-typed sender.
- [x] Observability bootstrap injection? — *Resolved in brainstorm*:
  `EventEmitterMixin` in the package accepts an injectable bootstrap
  hook; parrot injects `ensure_observability_bootstrapped` at
  bot/client init.
- [x] Should `parrot.core.events.lifecycle.__init__` re-export lifecycle
  machinery from the package? — *Implied by brainstorm "mínimo diff"
  decision*: yes, to preserve the `from parrot.core.events.lifecycle
  import EventRegistry` shortcut that ~15 files use. The `__init__`
  becomes a re-export facade over `navigator_eventbus.lifecycle` +
  local typed events.
- [x] Who owns the migration? — *Resolved in brainstorm*: Jesus owns
  all package migrations personally.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — one worktree in ai-parrot, all
  modules sequential.
- **Worktree location**: `.claude/worktrees/feat-317-parrot-eventbus-migration`
  branched from `dev`.
- **Sequence**: Module 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9, strictly
  sequential. Each module commits atomically. The order ensures that
  dependency additions (M1) precede deletions (M2–4), which precede
  consumer rewiring (M5–7), which precedes test rewiring (M8), which
  precedes regression (M9).
- **Cross-feature dependencies**: FEAT-313 (lifecycle extraction) and
  FEAT-316 (brokers port) MUST be complete before starting. Verify
  `from navigator_eventbus.lifecycle import LifecycleEvent` resolves
  in the venv before creating the worktree.
- **Freeze**: `parrot/core/events/` and `parrot/core/hooks/` are
  already frozen (declared since phase 1). No other specs should touch
  these directories until this phase completes.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-18 | Jesus + Claude | Initial draft from brainstorm navigator-eventbus-extraction (phase 4) |
