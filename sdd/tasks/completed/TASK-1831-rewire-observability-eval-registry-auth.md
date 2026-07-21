# TASK-1831: Rewire imports in observability, eval, registry, auth

**Feature**: FEAT-317 — Parrot EventBus Migration
**Spec**: `sdd/specs/parrot-eventbus-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1828, TASK-1829
**Assigned-to**: unassigned

---

## Context

Module 6 of spec §3. The observability subsystem, eval runner, registry
wiring, and auth permission module consume lifecycle machinery. Rewire their
machinery imports to the package while keeping local imports of parrot typed
events. Mechanical rewiring per the Import Rewiring Table.

---

## Scope

Rewrite imports per the Import Rewiring Table:

- `observability/attributes.py` — typed events STAY local.
- `observability/bootstrap.py` — `global_registry` → package (2 sites).
- `observability/provider.py` — `EventRegistry` (TYPE_CHECKING) → package.
- `observability/setup.py` — `global_registry` → package (2 sites).
- `observability/recorders/subscriber.py` — typed events local; `EventRegistry`
  (TYPE_CHECKING) → package.
- `observability/subscribers/metrics.py` — typed events local; `EventRegistry`
  (TYPE_CHECKING) → package.
- `observability/subscribers/trace.py` — `LifecycleEvent` + typed events;
  `LifecycleEvent` → package, typed events local; `EventRegistry` → package.
- `observability/traceloop_integration.py` — `global_registry` → package (2 sites).
- `eval/events.py` — `LifecycleEvent` → package.
- `eval/runner.py` — `EventBus` → package; `EventRegistry`, `TraceContext` → package.
- `auth/permission.py` — `TraceContext` (TYPE_CHECKING) → package.
- `registry/registry.py` — the lazy `from parrot.core.events.lifecycle.yaml_loader
  import wire_events` (registry.py:190) STAYS local (yaml_loader remains in
  parrot per TASK-1828) — verify no change needed; if TASK-1828 moved the
  engine and changed `wire_events`' location, follow whatever it exposed via
  the facade.
- Also update `observability/README.md:171` doc snippet if it references a
  moved import (doc-only; optional but preferred for accuracy).

**NOT in scope**: bots/clients (TASK-1830); server & integrations (TASK-1832);
core/events|hooks source (TASK-1827–1829); tests (TASK-1833).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../observability/attributes.py` | MODIFY | typed events local (verify) |
| `.../observability/bootstrap.py` | MODIFY | global_registry → pkg |
| `.../observability/provider.py` | MODIFY | EventRegistry → pkg |
| `.../observability/setup.py` | MODIFY | global_registry → pkg |
| `.../observability/recorders/subscriber.py` | MODIFY | events local; EventRegistry → pkg |
| `.../observability/subscribers/metrics.py` | MODIFY | events local; EventRegistry → pkg |
| `.../observability/subscribers/trace.py` | MODIFY | LifecycleEvent → pkg; events local |
| `.../observability/traceloop_integration.py` | MODIFY | global_registry → pkg |
| `.../eval/events.py` | MODIFY | LifecycleEvent → pkg |
| `.../eval/runner.py` | MODIFY | EventBus, EventRegistry, TraceContext → pkg |
| `.../auth/permission.py` | MODIFY | TraceContext (TYPE_CHECKING) → pkg |
| `.../registry/registry.py` | VERIFY | wire_events STAYS local (likely no change) |
| `.../observability/README.md` | MODIFY (optional) | doc import snippet |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# → navigator_eventbus (PROJECTED for lifecycle; verify via TASK-1828 / facade):
from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.global_registry import get_global_registry
from navigator_eventbus.lifecycle.trace import TraceContext
from navigator_eventbus import EventBus            # eval/runner.py
# — or via facade: from parrot.core.events.lifecycle import EventRegistry, TraceContext, get_global_registry, LifecycleEvent

# STAY local (parrot typed events) — DO NOT rewrite:
from parrot.core.events.lifecycle.events import AfterClientCallEvent   # recorders/subscriber.py:18
from parrot.core.events.lifecycle.events import (...)                  # attributes.py:15, metrics.py:21, trace.py:24
from parrot.core.events.lifecycle.yaml_loader import wire_events        # registry/registry.py:190 (STAYS local)
```

### Current import lines to change — VERIFIED 2026-07-18

```python
# observability/bootstrap.py:147,220   ...lifecycle.global_registry import (...)  → pkg
# observability/provider.py:23         ...lifecycle.registry import EventRegistry (TYPE_CHECKING) → pkg
# observability/setup.py:254,322       ...lifecycle.global_registry import (...)  → pkg
# observability/recorders/subscriber.py:18  ...lifecycle.events import AfterClientCallEvent  ← local
# observability/recorders/subscriber.py:23  ...lifecycle.registry import EventRegistry (TYPE_CHECKING) → pkg
# observability/subscribers/metrics.py:21   ...lifecycle.events import (...)  ← local
# observability/subscribers/metrics.py:33   ...lifecycle.registry import EventRegistry (TYPE_CHECKING) → pkg
# observability/subscribers/trace.py:23     ...lifecycle.base import LifecycleEvent  → pkg
# observability/subscribers/trace.py:24     ...lifecycle.events import (...)  ← local
# observability/subscribers/trace.py:53     ...lifecycle.registry import EventRegistry (TYPE_CHECKING) → pkg
# observability/traceloop_integration.py:147,172  ...lifecycle.global_registry import (...) → pkg
# observability/attributes.py:15           ...lifecycle.events import (...)  ← local (verify: no change)
# eval/events.py:20                        ...lifecycle.base import LifecycleEvent → pkg
# eval/runner.py:32 (TYPE_CHECKING)        ...events.evb import EventBus → navigator_eventbus
# eval/runner.py:33 (TYPE_CHECKING)        ...lifecycle.registry import EventRegistry → pkg
# eval/runner.py:451,480                   ...lifecycle.trace import TraceContext → pkg
# auth/permission.py:17 (TYPE_CHECKING)    ...lifecycle.trace import TraceContext → pkg
```

### Does NOT Exist
- ~~parrot-local `global_registry`/`EventRegistry` modules after TASK-1828~~ — deleted; source from package/facade.
- ~~`wire_events` in the package's top level~~ — `yaml_loader` STAYS in parrot; the parrot import path is unchanged (only its internal machinery imports were rewired in TASK-1828).

---

## Implementation Notes

### Key Constraints
- **Mechanical only.** Preserve `if TYPE_CHECKING:` guards and `# noqa: PLC0415` comments on lazy imports.
- Prefer the `parrot.core.events.lifecycle` facade for machinery symbols it re-exports.
- Typed-event imports (`...lifecycle.events import ...`) are UNCHANGED — do not touch them.
- `registry/registry.py`: the `wire_events` import path should be unchanged; only verify.

### References in Codebase
- Spec §2 "Import Rewiring Table", §3 Module 6.

---

## Acceptance Criteria

- [ ] All listed machinery imports resolve from the package (or facade).
- [ ] Typed-event imports remain local and unchanged.
- [ ] `python -c "import parrot.observability.setup, parrot.eval.runner, parrot.auth.permission"` succeeds.
- [ ] `python -c "import parrot.registry.registry"` succeeds and `wire_events` still resolves.
- [ ] `ruff check` clean on all modified files.

---

## Test Specification

```bash
python - <<'PY'
import parrot.observability.bootstrap, parrot.observability.setup
import parrot.observability.subscribers.trace, parrot.observability.subscribers.metrics
import parrot.eval.events, parrot.eval.runner, parrot.auth.permission
import parrot.registry.registry
print("observability/eval/registry/auth import OK")
PY
```

---

## Agent Instructions

1. Verify TASK-1828 and TASK-1829 completed.
2. Verify the Codebase Contract.
3. Update index → `in-progress`.
4. Rewire imports mechanically; verify `registry.py` needs no change.
5. Verify acceptance criteria; move to completed; update index; fill note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-20
**Notes**:
- All import sites matched the Codebase Contract's verified current-state
  table exactly (line numbers included). Rewired all machinery imports to
  the `parrot.core.events.lifecycle` facade (preferred per Implementation
  Notes) rather than direct `navigator_eventbus.lifecycle.*` paths.
- `eval/runner.py` also needed its TYPE_CHECKING `EventBus` import fixed
  (`from parrot.core.events.evb import EventBus` → `from navigator_eventbus
  import EventBus`), consistent with the Contract's "eval/runner.py:32
  (TYPE_CHECKING) ...events.evb import EventBus → navigator_eventbus" line.
- `bootstrap.py`/`setup.py`/`traceloop_integration.py`'s multi-line
  `global_registry` import blocks (2 sites each, `# noqa: PLC0415` lazy
  imports) rewired via a scripted regex substitution to guarantee
  byte-identical formatting/indentation across all 6 occurrences.
- `registry/registry.py` verified unchanged, as specified — its
  `wire_events` import path (`parrot.core.events.lifecycle.yaml_loader`)
  was untouched by TASK-1828 (yaml_loader stayed in parrot).
- `observability/README.md:171` doc snippet updated (optional item) for
  accuracy.
- Typed-event imports (attributes.py, recorders/subscriber.py,
  subscribers/{metrics,trace}.py) verified unchanged/local, as required.
- Verified: this task's own Test Specification passes end-to-end
  (`observability/eval/registry/auth import OK`). Additionally re-ran
  TASK-1830's previously-deferred acceptance check (`import
  parrot.bots.abstract, parrot.clients.base` etc.) — now succeeds, since
  this task unblocked the eager `clients/base.py` →
  `observability/context` → `observability/subscribers/trace.py` import
  chain, confirming the strict-sequential Worktree Strategy assumption was
  correct.
- `ruff check` clean on every file this task modified; `registry/registry.py`
  has 2 pre-existing, unrelated lint findings (`F841`, `F811`) — confirmed
  via `git diff --stat` that the file was not touched by this task (0
  insertions/deletions), so these are out of scope.
**Deviations from spec**: none.
