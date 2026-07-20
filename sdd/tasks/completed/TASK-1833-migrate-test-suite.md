# TASK-1833: Migrate test suite + examples + migration guard tests

**Feature**: FEAT-317 — Parrot EventBus Migration
**Spec**: `sdd/specs/parrot-eventbus-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1827, TASK-1828, TASK-1829, TASK-1830, TASK-1831, TASK-1832
**Assigned-to**: unassigned

---

## Context

Module 8 of spec §3. With production code fully rewired, the test suite must be
brought in line: delete tests already migrated to `navigator-eventbus`, rewire
the remaining ~65 test files' imports, add migration-guard tests, and update
the affected example. Also update any conftest stubs referencing deleted
modules.

---

## Scope

- **Delete** bus-core tests now owned by `navigator-eventbus`:
  `packages/ai-parrot/tests/core/events/bus/` (entire directory —
  `test_core.py`, `test_envelope.py`, `test_backends.py`, `test_dlq.py`,
  `test_facade.py`, `test_ingress.py`, `test_integration.py`,
  `test_audit_metrics.py`, `test_notification_subscriber.py`,
  `test_redis_streams.py`).
- **Delete** `packages/ai-parrot/tests/core/events/test_eventbus_imports.py`
  (asserts the old `parrot.core.events.__all__` shape, which no longer exists).
- **Rewire** the remaining test files that import `parrot.core.events.*` /
  `parrot.core.hooks.*` per the Import Rewiring Table. Priority clusters:
  - `tests/core/hooks/*` (hook tests stay; rewire base/models/manager → package).
  - `tests/unit/events/lifecycle/*` (machinery tests stay but import from
    package/facade; typed-event tests stay local).
  - `tests/unit/observability/*` (typed events local; machinery from package).
  - `tests/benchmarks/test_lifecycle_perf.py`.
  - `tests/bots/flows/test_flow_telemetry.py`, `tests/eval/test_eval_events.py`,
    `tests/integration/events/*`, `tests/transport/filesystem/*`,
    `tests/test_hooks.py`, `tests/test_jira_*`, `tests/test_google_client.py`,
    `tests/test_prompt_cache_events.py`, `tests/unit/{auth,bots,clients,tools}/*`.
  - Server tests: `packages/ai-parrot-server/tests/{test_ledger_*,test_orchestrator_hooks_via_bus}.py`.
- **Add** migration-guard tests:
  - `test_no_bus_core_in_parrot`: `import parrot.core.events.bus` and
    `import parrot.core.events.evb` both raise `ModuleNotFoundError`.
  - `test_no_old_hooks_modules`: `import parrot.core.hooks.base` and
    `import parrot.core.hooks.models` both raise `ModuleNotFoundError`.
  - `test_navigator_eventbus_smoke`: top-level package imports + emit round-trip.
  - `test_typed_events_subclass`: parrot typed events subclass the package `LifecycleEvent`.
  - `test_facade_reexports`: `from parrot.core.events.lifecycle import EventRegistry`
    and `from parrot.core.hooks import BaseHook, HookEvent` resolve.
- **Update** `packages/ai-parrot/tests/conftest.py` if any `sys.modules` stub
  references a deleted module (`parrot.core.events.*`, `parrot.core.hooks.*`).
  Note: the current conftest stubs `navconfig`/`navigator.utils`/
  `parrot.interfaces.file` — verify these do not conflict with the real
  `navconfig` that `navigator_eventbus` imports at import time.
- **Update** `examples/dev_loop/e2e_demo.py` imports.

**NOT in scope**: production source (TASK-1827–1832); running the full
regression/benchmark (TASK-1834).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/core/events/bus/` | DELETE | migrated to navigator-eventbus |
| `packages/ai-parrot/tests/core/events/test_eventbus_imports.py` | DELETE | old `__all__` shape gone |
| `packages/ai-parrot/tests/**` (remaining eventbus/hooks importers) | MODIFY | rewire imports |
| `packages/ai-parrot-server/tests/{test_ledger_*,test_orchestrator_hooks_via_bus}.py` | MODIFY | rewire imports |
| `packages/ai-parrot/tests/core/events/test_migration_guard.py` | CREATE | guard + smoke + facade tests |
| `packages/ai-parrot/tests/conftest.py` | MODIFY (if needed) | drop stubs for deleted modules |
| `examples/dev_loop/e2e_demo.py` | MODIFY | rewire imports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (test-side targets)

```python
from navigator_eventbus import EventBus, EventEnvelope, Severity          # VERIFIED
from navigator_eventbus.hooks import BaseHook, HookManager, HookEvent     # VERIFIED
# lifecycle machinery via facade (preferred) or package (PROJECTED):
from parrot.core.events.lifecycle import EventRegistry, LifecycleEvent, TraceContext
from parrot.core.events.lifecycle.events import BeforeInvokeEvent          # STAYS local
```

### Test files importing eventbus/hooks — VERIFIED census 2026-07-18 (65 files)

```
# Delete (bus core — migrated):
tests/core/events/bus/{test_audit_metrics,test_backends,test_core,test_dlq,
  test_envelope,test_facade,test_ingress,test_integration,
  test_notification_subscriber,test_redis_streams}.py
tests/core/events/test_eventbus_imports.py
# Rewire (representative — full list via grep, see command below):
tests/core/hooks/{test_github_webhook,test_github_webhook_comments,
  test_hookable_agent,test_hookable_cleanup,test_hookmanager_eventbus,
  test_hookmanager_route_to_bus,test_imports,test_jira_webhook_classify}.py
tests/unit/events/lifecycle/*.py  (test_base,test_registry,test_mixin,test_provider,
  test_global_registry,test_logging_subscriber,test_webhook_subscriber,
  test_opentelemetry_subscriber,test_trace_context,test_concrete_events,
  test_public_api,test_registry_fire_and_forget,test_client_events_agent_name)
tests/unit/observability/*.py  tests/benchmarks/test_lifecycle_perf.py
tests/bots/flows/test_flow_telemetry.py  tests/eval/test_eval_events.py
tests/integration/events/test_a2a_trace_propagation.py
tests/integration/observability/{test_perf,test_poc}.py
tests/transport/filesystem/{test_hook,test_imports,test_integration}.py
tests/{test_hooks,test_jira_assignment,test_jira_ticket_created,
  test_jira_transition_dispatch,test_google_client,test_prompt_cache_events}.py
tests/unit/{auth/test_permission_context_trace,bots/test_abstract_lifecycle,
  clients/test_client_emits_agent_name,clients/test_client_lifecycle,
  tools/test_tool_lifecycle,registry/test_events_yaml}.py
# server:
../ai-parrot-server/tests/{test_ledger_integration,test_ledger_models,
  test_ledger_recorder,test_orchestrator_hooks_via_bus}.py
```

Regenerate the exact live list before starting:
```bash
grep -rln "from parrot\.core\.events\|from parrot\.core\.hooks" \
  packages/ai-parrot/tests packages/ai-parrot-server/tests | grep -v __pycache__
```

### Does NOT Exist
- ~~`parrot.core.events.bus` / `parrot.core.events.evb` importable~~ — deleted; the guard tests assert this.
- ~~`parrot.core.hooks.base` / `.models` importable~~ — deleted; only the `parrot.core.hooks` facade re-exports them.
- ~~a `parrot.notifications` real module the conftest must stub~~ — check current conftest; only stub what genuinely fails to import.

---

## Implementation Notes

### Key Constraints
- Delete with `git rm`. Rewire mechanically — do not change test logic/assertions
  except where they assert an import path or `__all__` that legitimately changed.
- Tests for lifecycle machinery (registry, mixin, provider, subscribers) STAY in
  ai-parrot but should import from the facade/package. Tests for parrot typed
  events STAY and keep local imports.
- Run each cluster's tests as you rewire it to catch mistakes early.

### References in Codebase
- Spec §3 Module 8, §4 "Test Specification", §7 "Known Risks" (conftest stubs).

---

## Acceptance Criteria

- [ ] `tests/core/events/bus/` and `tests/core/events/test_eventbus_imports.py` deleted.
- [ ] `grep -rln "from parrot.core.events.bus\|from parrot.core.events.evb" packages/*/tests` → empty.
- [ ] `grep -rln "from parrot.core.hooks.base\|from parrot.core.hooks.models\|from parrot.core.hooks.manager" packages/*/tests` → empty (facade or package used).
- [ ] Migration-guard test file created; guard/smoke/facade tests pass.
- [ ] `examples/dev_loop/e2e_demo.py` imports updated.
- [ ] Per-cluster `pytest` runs green (full-suite regression is TASK-1834).
- [ ] `ruff check` clean on modified test files.

---

## Test Specification

```python
# tests/core/events/test_migration_guard.py
import importlib, pytest

@pytest.mark.parametrize("mod", [
    "parrot.core.events.bus", "parrot.core.events.evb",
    "parrot.core.hooks.base", "parrot.core.hooks.models",
])
def test_deleted_modules_not_importable(mod):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(mod)

def test_navigator_eventbus_smoke():
    from navigator_eventbus import EventBus, EventEnvelope, Severity
    assert EventBus and EventEnvelope and Severity

def test_facade_reexports():
    from parrot.core.events.lifecycle import EventRegistry, LifecycleEvent
    from parrot.core.hooks import BaseHook, HookEvent
    from parrot.core.events.lifecycle.events import BeforeInvokeEvent
    from navigator_eventbus.lifecycle.base import LifecycleEvent as PkgLE
    assert issubclass(BeforeInvokeEvent, PkgLE)
```

---

## Agent Instructions

1. Verify TASK-1827–1832 completed.
2. Regenerate the live importer list; verify the Codebase Contract.
3. Update index → `in-progress`.
4. Delete migrated tests; rewire remaining; add guard tests; fix conftest/example.
5. Run per-cluster pytest; verify acceptance criteria; move to completed; update index; fill note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-20
**Notes**:
- Regenerated the live importer list per the task's own command; found 64
  files (vs. the spec's ~65 estimate) plus one extra companion
  (`ai-parrot-integrations/tests/test_matrix_hook.py`, found by widening the
  grep to that package — same category as TASK-1830's spec-gap deviation,
  since TASK-1832 rewired its production counterpart).
- Deleted `tests/core/events/bus/` (11 files) and
  `tests/core/events/test_eventbus_imports.py` via `git rm`.
- Rewired the remaining ~50 test files mechanically per the Import
  Rewiring Table — machinery imports (`base`/`trace`/`meta`/`registry`/
  `global_registry`/`provider`/`mixin`/subscribers `logging`/`webhook`) →
  `navigator_eventbus.lifecycle.*`; hooks (`base`/`manager`/`models`/
  `mixins`/`scheduler`/`file_watchdog`) → `navigator_eventbus.hooks.*`;
  typed events and integration-hook submodule imports left untouched
  (stay local).
- Created `tests/core/events/test_migration_guard.py` with the 4 guard/
  smoke/facade tests from the Test Specification (parametrized guard test
  covers both `test_no_bus_core_in_parrot` and `test_no_old_hooks_modules`
  from the Scope bullets in one test, matching the task's own Test
  Specification code block verbatim).
- `conftest.py`: verified no stub references any deleted `parrot.core.
  events.*`/`parrot.core.hooks.*` path (only `navconfig`/`navigator.*`
  stubs, unrelated) — no changes needed, confirmed by the full test run
  exercising `navigator_eventbus` (which imports navconfig at its own
  import time) without conflict.
- `examples/dev_loop/e2e_demo.py`: `LifecycleEvent`/`get_global_registry`
  now imported from the `parrot.core.events.lifecycle` facade.
- **Test-logic fixes beyond pure import rewiring** (each is a "legitimately
  changed" case per the Implementation Notes exception, not scope creep):
  - `test_webhook_subscriber.py` / `test_registry.py`: two tests use
    `unittest.mock.patch(...)` / `sys.modules` injection targeting the
    OLD dotted module path (`parrot.core.events.lifecycle.subscribers.
    webhook.asyncio.sleep`, `parrot.core.events.lifecycle.global_registry`)
    to intercept a lazy import — these targets had to be repointed to the
    new `navigator_eventbus.lifecycle.*` paths, since patching/injecting
    under the old (now-nonexistent) module name silently no-ops instead of
    raising, which is why these failures only surfaced at runtime, not at
    collection.
  - `test_registry.py::TestDualEmit` (4 tests): inline `from parrot.core.
    events.evb import EventBus` → `from navigator_eventbus.evb import
    EventBus`.
  - `test_events_yaml.py`: `_resolve`/`_make_where` (private helpers) no
    longer exist in `parrot.core.events.lifecycle.yaml_loader` — the
    engine fully moved to the package per TASK-1828. Split the import:
    `EVENT_CLASSES`/`wire_events` stay from the parrot module (re-exported
    unchanged); `_resolve`/`_make_where` now from
    `navigator_eventbus.lifecycle.yaml_loader`. Exactly the heads-up TASK-
    1828's completion note flagged for this task.
  - `test_matrix_hook.py::test_matrix_hook_type_exists`: removed a
    `HookType.MATRIX.value == "matrix"` assertion — `navigator_eventbus.
    hooks.models.HookType` is a plain open-registry class of str
    constants (FEAT-312 decision), not an `Enum`, so `.value` no longer
    exists; the `HookType.MATRIX == "matrix"` assertion above it already
    covers the real invariant.
- **Pre-existing, unrelated failures confirmed and left untouched** (root-
  caused by diffing against unmodified `dev`, not introduced by this
  migration):
  - `test_matrix_hook.py::TestMatrixHook` (6 tests): `_make_hook()` always
    imported the `parrot.core.hooks.matrix.MatrixHook` *compatibility shim*
    (not the concrete `parrot.integrations.matrix.hook.MatrixHook`), which
    lacks `_on_room_message` — reproduced identically on `dev` before any
    migration changes; out of scope (NO SCOPE CREEP).
  - `test_botmanager_flags.py` (2 tests, `IntegrationBotManager` missing
    attribute) and `tests/manager/test_bot_cleanup_lifecycle.py` /
    `tests/interfaces/test_file_shim.py` (collection errors: missing
    `parrot.tools.pythonrepl` / `parrot.interfaces`) and 19 other
    collection errors (missing optional-extra packages like coingecko/
    cryptoquant toolkits) — reproduced byte-identically on unmodified
    `dev` (22 collection errors, same file set).
- Verified: all explicitly-listed test clusters green (`tests/unit/events/
  lifecycle/` + `tests/core/hooks/`: 283 passed; `tests/unit/
  observability/`: 111 passed; the scattered cluster — benchmarks, flows,
  eval, integration, transport, root jira/google/prompt-cache tests,
  unit/{auth,bots,clients,tools,registry}: 328 passed, 3 pre-existing
  skips; `test_google_client.py`: 61 passed; server ledger/orchestrator
  tests: 47 passed; migration guard: 7 passed; matrix hook: 14 passed / 6
  pre-existing failures). Acceptance-criteria greps (bus/evb, hooks base/
  models/manager) → empty across all three packages' test trees. `ruff
  check`: confirmed byte-identical error counts before/after on every
  modified file (diffed against `HEAD~30`); the one new file
  (`test_migration_guard.py`) is ruff-clean.
- **Test-environment note**: had to temporarily editable-reinstall
  `ai-parrot-server`/`ai-parrot-integrations` from the worktree (not just
  `ai-parrot`) to exercise these packages' own tests against this
  feature's changes, then restored them after cross-checking pre-existing
  failures against unmodified `dev`.
**Deviations from spec**: added `ai-parrot-integrations/tests/
test_matrix_hook.py` (not in the spec's file census, found via widened
live-grep) and the test-logic fixes enumerated above (all within the
"legitimately changed" exception, not scope creep).
