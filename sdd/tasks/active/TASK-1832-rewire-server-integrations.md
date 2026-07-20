# TASK-1832: Rewire ai-parrot-server and ai-parrot-integrations

**Feature**: FEAT-317 — Parrot EventBus Migration
**Spec**: `sdd/specs/parrot-eventbus-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1828, TASK-1829
**Assigned-to**: unassigned

---

## Context

Module 7 of spec §3. The `ai-parrot-server` (autonomous orchestrator, ledger,
webhooks, filesystem hook, evb shim) and `ai-parrot-integrations` (matrix hook)
packages consume the bus/lifecycle/hooks machinery. Rewire their imports to
`navigator_eventbus`, and configure the **legacy Redis prefixes** at the one
production `EventBus()` construction site (orchestrator).

---

## Scope

- `autonomous/evb.py` — the backward-compat re-export shim: change source from
  `parrot.core.events.evb` to `navigator_eventbus.evb`. (Check consumers via
  `grep -rn "autonomous.evb import\|autonomous\.evb" packages/`; if none remain,
  consider deleting the shim and note it — but default to keeping it repointed.)
- `autonomous/ledger.py` — `LifecycleEvent`, `global_registry` → package.
- `autonomous/orchestrator.py` — `EventBus`, `Event`, `EventPriority` → package;
  `BaseHook`, `HookManager`, `HookEvent` → package. **Construct `EventBus` with
  legacy prefixes** (`channel_prefix="parrot:events:"`, and — if it builds a
  `RedisStreamsBackend` — `stream_prefix="parrot:stream:"`,
  `dedup_prefix="parrot:events:dedup:"`, `group="parrot-bus"`), or ensure the
  `BUS_*` navconfig keys are set. Coordinate with TASK-1826 if the prefix
  plumbing was staged there.
- `autonomous/webhooks.py` — `EventBus` (TYPE_CHECKING) → package.
- `autonomous/transport/filesystem/hook.py` — `BaseHook`,
  `FilesystemHookConfig`, `HookType` → package.
- `integrations/matrix/hook.py` — `BaseHook`, `HookRegistry`, `HookType`,
  `MatrixHookConfig` → package.

**NOT in scope**: bots/clients (TASK-1830); observability/eval/registry/auth
(TASK-1831); core source deletions (TASK-1827–1829); tests (TASK-1833).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `ai-parrot-server/.../autonomous/evb.py` | MODIFY | re-export from `navigator_eventbus.evb` |
| `ai-parrot-server/.../autonomous/ledger.py` | MODIFY | LifecycleEvent, global_registry → pkg |
| `ai-parrot-server/.../autonomous/orchestrator.py` | MODIFY | EventBus/Event/EventPriority, hooks → pkg; legacy prefixes |
| `ai-parrot-server/.../autonomous/webhooks.py` | MODIFY | EventBus (TYPE_CHECKING) → pkg |
| `ai-parrot-server/.../autonomous/transport/filesystem/hook.py` | MODIFY | BaseHook, models → pkg |
| `ai-parrot-integrations/.../integrations/matrix/hook.py` | MODIFY | BaseHook, HookRegistry, models → pkg |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (target)

```python
from navigator_eventbus import EventBus, Event, EventPriority, EventSubscription   # VERIFIED present
from navigator_eventbus.evb import Event, EventBus, EventPriority, EventSubscription
from navigator_eventbus.hooks import BaseHook, HookRegistry, HookManager, HookEvent
from navigator_eventbus.hooks.base import BaseHook, HookRegistry
from navigator_eventbus.hooks.models import HookType, MatrixHookConfig, FilesystemHookConfig
# lifecycle (PROJECTED — verify via TASK-1828):
from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.global_registry import get_global_registry
```

### Current import lines to change — VERIFIED 2026-07-18

```python
# autonomous/evb.py:7       from parrot.core.events.evb import (Event, EventBus, EventPriority, EventSubscription)  → navigator_eventbus.evb
# autonomous/ledger.py:40   from parrot.core.events.lifecycle.base import LifecycleEvent  → pkg
# autonomous/ledger.py:41   from parrot.core.events.lifecycle.global_registry import get_global_registry  → pkg
# autonomous/orchestrator.py:27  from parrot.core.events import EventBus, Event, EventPriority  → navigator_eventbus
# autonomous/orchestrator.py:28  from parrot.core.hooks import BaseHook, HookManager, HookEvent  → navigator_eventbus.hooks
# autonomous/orchestrator.py:231 EventBus(...)  ← add legacy prefix kwargs / ensure BUS_* env
# autonomous/webhooks.py:14 (TYPE_CHECKING)  from parrot.core.events import EventBus  → navigator_eventbus
# autonomous/transport/filesystem/hook.py:8  from parrot.core.hooks.base import BaseHook  → navigator_eventbus.hooks.base
# autonomous/transport/filesystem/hook.py:9  from parrot.core.hooks.models import FilesystemHookConfig, HookType  → navigator_eventbus.hooks.models
# integrations/matrix/hook.py:23  from parrot.core.hooks.base import BaseHook, HookRegistry  → navigator_eventbus.hooks.base
# integrations/matrix/hook.py:24  from parrot.core.hooks.models import HookType, MatrixHookConfig  → navigator_eventbus.hooks.models
```

### Legacy prefix values (compatibility)
```
channel_prefix="parrot:events:"  stream_prefix="parrot:stream:"
dedup_prefix="parrot:events:dedup:"  group="parrot-bus"
```

### Does NOT Exist
- ~~`parrot.core.events.evb` after TASK-1827~~ — deleted; the shim now re-exports from `navigator_eventbus.evb`.
- ~~`parrot.core.hooks.base`/`.models` modules after TASK-1829~~ — deleted; import from the package (or the `parrot.core.hooks` facade).
- ~~`FilesystemHookConfig` in parrot's old models~~ — it is a package model (FEAT-312).

---

## Implementation Notes

### Key Constraints
- **Mechanical import rewiring**, plus the single behavioral addition of legacy
  Redis prefixes at the orchestrator's `EventBus()` call.
- Preserve `if TYPE_CHECKING:` guards (webhooks.py, orchestrator hints).
- `integrations/matrix/hook.py` may import via the package directly; the
  `core/hooks/matrix.py` stub (fixed in TASK-1829) still resolves it via
  `HookRegistry`.

### References in Codebase
- Spec §2 "Import Rewiring Table", §3 Module 7, §7 "Known Risks" (streams compat, evb shim).

---

## Acceptance Criteria

- [ ] All 6 files import from `navigator_eventbus` (no `parrot.core.events.evb`/`bus`, no `parrot.core.hooks.base`/`.models`).
- [ ] Orchestrator constructs `EventBus` with legacy `parrot:*` prefixes (verified by reading the constructed instance's `channel_prefix`).
- [ ] `python -c "import parrot.autonomous.orchestrator, parrot.autonomous.ledger, parrot.autonomous.evb"` succeeds (in the server package's env).
- [ ] `python -c "import parrot.integrations.matrix.hook"` succeeds (in the integrations env).
- [ ] `ruff check` clean on all modified files.

---

## Test Specification

```bash
# server package env
python -c "import parrot.autonomous.evb as e; assert hasattr(e,'EventBus'); print('evb shim OK')"
python -c "from parrot.autonomous.orchestrator import AutonomousOrchestrator; print('orchestrator import OK')"
# integrations env
python -c "import parrot.integrations.matrix.hook; print('matrix hook import OK')"
```

---

## Agent Instructions

1. Verify TASK-1828 and TASK-1829 completed.
2. Verify the Codebase Contract.
3. Update index → `in-progress`.
4. Rewire imports; add legacy prefixes at the orchestrator's `EventBus()`.
5. Verify acceptance criteria; move to completed; update index; fill note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
