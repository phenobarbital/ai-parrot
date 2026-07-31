# TASK-1830: Rewire imports in bots and clients

**Feature**: FEAT-317 — Parrot EventBus Migration
**Spec**: `sdd/specs/parrot-eventbus-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1828, TASK-1829
**Assigned-to**: unassigned

---

## Context

Module 5 of spec §3. With the machinery deleted (TASK-1828/1823), the bot and
client consumers must import lifecycle machinery (`EventEmitterMixin`,
`TraceContext`, `EventRegistry`) from `navigator_eventbus`, while keeping local
imports of parrot typed events. Purely mechanical import rewiring per the
Import Rewiring Table.

---

## Scope

Rewrite imports in the following files per the Import Rewiring Table:

- `bots/abstract.py` — `EventEmitterMixin`, `TraceContext` → package; typed
  events (`from ...lifecycle.events import ...`) STAY local; `_LegacyEventBridge`
  STAYS local. Update the deprecation-warning string at abstract.py:996 if it
  names a moved module.
- `bots/base.py` — `TraceContext` → package; typed events STAY local.
- `bots/flows/core/context.py` — `TraceContext` (TYPE_CHECKING) → package.
- `bots/flows/flow/telemetry.py` — `LifecycleEvent`, `EventRegistry`,
  `TraceContext`, `global_registry` → package; flow typed events STAY local.
- `bots/github_reviewer.py` — `GitHubWebhookHook` STAYS local
  (`parrot.core.hooks.github_webhook`); config models + `HookEvent` → package
  (or via `parrot.core.hooks` facade).
- `bots/jira_specialist.py` — `HookEvent`, `TransitionAction`,
  `TransitionActionType` → package (or via facade).
- `clients/base.py` — `EventEmitterMixin`, `TraceContext` → package; typed
  events STAY local.
- `clients/claude.py` — typed events STAY local; `TraceContext` → package.
- `clients/claude_agent.py` — `ClientStreamChunkEvent` STAYS local.
- `clients/google/client.py` — `ClientStreamChunkEvent` STAYS local.
- `clients/gpt.py` — typed events STAY local; `TraceContext` → package.
- `clients/grok.py` — `ClientStreamChunkEvent` STAYS local.
- `clients/groq.py` — `ClientStreamChunkEvent` STAYS local.

**NOT in scope**: observability/eval/registry/auth (TASK-1831); server &
integrations (TASK-1832); deleting/creating source in core/events|hooks
(TASK-1827–1829); tests (TASK-1833).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | mixin, trace → pkg; events/bridge local |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | trace → pkg; events local |
| `packages/ai-parrot/src/parrot/bots/flows/core/context.py` | MODIFY | trace (TYPE_CHECKING) → pkg |
| `packages/ai-parrot/src/parrot/bots/flows/flow/telemetry.py` | MODIFY | LifecycleEvent, EventRegistry, trace, global_registry → pkg; flow events local |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | hook local; models+HookEvent → pkg |
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | MODIFY | HookEvent, TransitionAction* → pkg |
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | mixin, trace → pkg; events local |
| `packages/ai-parrot/src/parrot/clients/claude.py` | MODIFY | trace → pkg; events local |
| `packages/ai-parrot/src/parrot/clients/claude_agent.py` | MODIFY | ClientStreamChunkEvent local |
| `packages/ai-parrot/src/parrot/clients/google/client.py` | MODIFY | ClientStreamChunkEvent local |
| `packages/ai-parrot/src/parrot/clients/gpt.py` | MODIFY | trace → pkg; events local |
| `packages/ai-parrot/src/parrot/clients/grok.py` | MODIFY | ClientStreamChunkEvent local |
| `packages/ai-parrot/src/parrot/clients/groq.py` | MODIFY | ClientStreamChunkEvent local |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# → navigator_eventbus (machinery moved out of parrot; PROJECTED for lifecycle,
#   verify via TASK-1828 delivery / import test):
from navigator_eventbus.lifecycle.mixin import EventEmitterMixin
from navigator_eventbus.lifecycle.trace import TraceContext
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.global_registry import get_global_registry
# — or, if TASK-1828 kept a working facade, EQUIVALENTLY:
from parrot.core.events.lifecycle import EventEmitterMixin, TraceContext, EventRegistry

# STAY local (parrot typed events) — DO NOT rewrite these:
from parrot.core.events.lifecycle.events import (
    BeforeInvokeEvent, AfterInvokeEvent, ClientStreamChunkEvent,
    BeforeClientCallEvent, AfterClientCallEvent, MessageAddedEvent,
    FlowStartedEvent, NodeStartedEvent,  # etc.
)
from parrot.core.events.lifecycle.legacy_bridge import _LegacyEventBridge  # abstract.py

# hooks (→ package facade or direct):
from parrot.core.hooks import HookEvent, TransitionAction, TransitionActionType
from parrot.core.hooks import GitHubWebhookConfig  # config model
from parrot.core.hooks.github_webhook import GitHubWebhookHook  # integration hook STAYS local
```

### Current import lines to change — VERIFIED 2026-07-18

```python
# bots/abstract.py:154  from parrot.core.events.lifecycle.mixin import EventEmitterMixin
# bots/abstract.py:155  from parrot.core.events.lifecycle.trace import TraceContext
# bots/abstract.py:156  from parrot.core.events.lifecycle.events import (...)      ← STAYS local
# bots/abstract.py:163  from parrot.core.events.lifecycle.legacy_bridge import _LegacyEventBridge  ← STAYS local
# bots/base.py:49       from parrot.core.events.lifecycle.trace import TraceContext
# bots/flows/flow/telemetry.py:32  ...lifecycle.base import LifecycleEvent
# bots/flows/flow/telemetry.py:41  ...lifecycle.registry import EventRegistry
# bots/flows/flow/telemetry.py:42  ...lifecycle.trace import TraceContext
# bots/flows/flow/telemetry.py:33  ...lifecycle.events.flow import (...)           ← STAYS local
# clients/base.py:64-66  mixin, trace (→pkg), events (local)
# clients/{claude,gpt}.py  trace → pkg; events local
# clients/{claude_agent,grok,groq}.py + google/client.py  ClientStreamChunkEvent  ← STAYS local
# bots/github_reviewer.py:48 from parrot.core.hooks.github_webhook import GitHubWebhookHook  ← STAYS
# bots/github_reviewer.py:49 from parrot.core.hooks.models import GitHubWebhookConfig, HookEvent → facade/pkg
# bots/jira_specialist.py:49 from parrot.core.hooks.models import HookEvent, TransitionAction, TransitionActionType → facade/pkg
```

### Does NOT Exist
- ~~parrot-local `EventEmitterMixin`/`TraceContext`/`EventRegistry` modules~~ — deleted in TASK-1828; import from package or the surviving lifecycle facade.
- ~~`ClientStreamChunkEvent` in the package~~ — parrot typed event, STAYS local.

---

## Implementation Notes

### Key Constraints
- **Mechanical only** — change import sources, nothing else. Do not refactor.
- Prefer importing machinery via the `parrot.core.events.lifecycle` facade
  (TASK-1828) when it re-exports the symbol — fewer long paths, and it keeps a
  single choke point. Use the direct `navigator_eventbus.lifecycle.*` path only
  when the facade does not expose the symbol.
- Preserve `if TYPE_CHECKING:` guards and local `as _Alias` aliases.
- Update any docstring/deprecation strings that reference the old module path
  (e.g. abstract.py:996).

### References in Codebase
- Spec §2 "Import Rewiring Table", §3 Module 5.

---

## Acceptance Criteria

- [ ] All 13 files import lifecycle machinery from the package (or facade), not from deleted parrot modules.
- [ ] Typed events still imported from `parrot.core.events.lifecycle.events` (local).
- [ ] `python -c "import parrot.bots.abstract, parrot.clients.base"` succeeds.
- [ ] `grep -rn "from parrot.core.events.lifecycle.mixin\|.registry import EventRegistry\|.trace import TraceContext" packages/ai-parrot/src/parrot/{bots,clients}` → empty (all moved to package/facade).
- [ ] `ruff check` clean on all modified files.

---

## Test Specification

```bash
python - <<'PY'
import parrot.bots.abstract, parrot.bots.base, parrot.clients.base
import parrot.clients.claude, parrot.clients.gpt
import parrot.bots.flows.flow.telemetry
print("bots/clients import OK")
PY
```

---

## Agent Instructions

1. Verify TASK-1828 and TASK-1829 completed.
2. Verify the Codebase Contract (facade vs direct paths).
3. Update index → `in-progress`.
4. Rewire imports mechanically.
5. Verify acceptance criteria; move to completed; update index; fill note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-20
**Notes**:
- Rewired all 13 listed files exactly per the Import Rewiring Table,
  preferring the `parrot.core.events.lifecycle` facade (TASK-1828) over
  direct `navigator_eventbus.lifecycle.*` paths wherever the facade
  re-exports the symbol, per Implementation Notes. Typed events and
  `_LegacyEventBridge`/`GitHubWebhookHook` stayed local everywhere, as
  specified. `clients/{claude_agent,grok,groq}.py` and
  `clients/google/client.py` needed zero changes (their
  `ClientStreamChunkEvent` imports were already correctly local).
- `bots/abstract.py:996` deprecation string references
  `parrot.core.events.lifecycle` (the facade, not a deleted module) — left
  unchanged, it's still accurate.
- **Deviation (spec census gap, fixed to unblock this task's own acceptance
  criteria)**: `packages/ai-parrot/src/parrot/tools/abstract.py` imports
  `..core.events.lifecycle.mixin.EventEmitterMixin` and
  `..core.events.lifecycle.trace.TraceContext` — the exact same pattern as
  `bots/abstract.py` — but is **not listed anywhere** in the spec's Module 5
  census, nor in TASK-1831/1832/1833's file lists (verified by grep). Since
  `AbstractTool` is imported transitively by `parrot.clients.base` (via
  `memory.episodic.tools`), leaving it unrewired breaks `import
  parrot.bots.abstract` / `import parrot.clients.base` outright — this
  task's own acceptance criteria. Rewired it identically (facade import),
  flagging the deviation here rather than silently expanding scope.
- **Acceptance criterion partially deferred**: the `python -c "import
  parrot.bots.abstract, parrot.clients.base"` test still fails at this
  point in the sequence — NOT due to any defect in this task's changes, but
  because `clients/base.py` eagerly imports `parrot.observability.context`
  at module level, which pulls in `observability/subscribers/trace.py`
  (`from parrot.core.events.lifecycle.base import LifecycleEvent` — a
  Module 6 / TASK-1831 rewrite). The spec's Worktree Strategy mandates
  strictly sequential Module 5 → 6 execution in one worktree specifically
  because of this import entanglement. Verified via `grep`: zero remaining
  references to deleted modules in `bots/`/`clients/`
  (`from parrot.core.events.lifecycle.mixin|.registry import
  EventRegistry|.trace import TraceContext` → empty). The full end-to-end
  import will be (and was) re-verified immediately after TASK-1831 lands.
- `ruff check`: confirmed byte-for-byte identical error counts
  before/after on every modified file (all pre-existing E402/F841 issues,
  none introduced by this migration) — clean with respect to this task's
  changes.
**Deviations from spec**: added `parrot/tools/abstract.py` to the modified
set (not in the spec's file census) — required to keep the import graph
consistent; see Notes above.
