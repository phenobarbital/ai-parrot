# TASK-1820: Add navigator-eventbus dependency + configure legacy Redis prefixes

**Feature**: FEAT-317 — Parrot EventBus Migration
**Spec**: `sdd/specs/parrot-eventbus-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none *(but externally BLOCKED: FEAT-313 lifecycle extraction and FEAT-316 brokers port must be delivered in `navigator-eventbus` first — see Preflight)*
**Assigned-to**: unassigned

---

## Context

Phase 4 (Module 1) of the `navigator-eventbus` extraction. Before any code
can be deleted or rewired, ai-parrot must declare `navigator-eventbus` as a
dependency and the singleton `EventBus` construction site must pass the
legacy Redis prefixes so deployed streams (`parrot:stream:*`, group
`parrot-bus`) remain consumable. Implements spec §3 Module 1.

---

## Preflight (BLOCKING — verify before starting)

The package's `lifecycle/` and `brokers/` subpackages did **not** exist as of
2026-07-18 (only `backends/`, `hooks/`, `ingress/`, `subscribers/` and the
top-level modules were present). This task's later siblings (TASK-1822,
TASK-1823) depend on them. Verify all three subsystems resolve before the
feature proceeds:

```bash
source .venv/bin/activate
uv pip install -e /home/jesuslara/proyectos/navigator-eventbus
python -c "from navigator_eventbus import EventBus, EventEnvelope, Severity"
python -c "from navigator_eventbus.lifecycle.base import LifecycleEvent"   # phase 2
python -c "from navigator_eventbus.hooks import BaseHook, HookManager, HookEvent"
```

If the `lifecycle` import fails, STOP — FEAT-313 is not done; do not proceed
with the feature.

---

## Scope

- Add `navigator-eventbus` to `[project.dependencies]` in
  `packages/ai-parrot/pyproject.toml`. During development use an editable /
  path dependency (the package is not yet on PyPI); document the temporary
  form and the intended `>=0.1.0` PyPI form.
- Update ai-parrot's `grpc` optional-dependency extra to pull
  `navigator-eventbus[grpc]` (gRPC ingress now lives in the package).
- Ensure the singleton `EventBus` construction site
  (`AutonomousOrchestrator`, orchestrator.py:231) passes the **legacy**
  Redis prefixes so existing deployments keep working. This is the one
  place a running system instantiates the bus. (The actual import rewrite
  of orchestrator.py happens in TASK-1826; here only add/prepare the prefix
  kwargs plumbing — coordinate so the two edits do not conflict, or defer
  the orchestrator edit to TASK-1826 and only add the pyproject dependency +
  document the required kwargs here.)
- Verify the editable install resolves in a clean venv.

**NOT in scope**: deleting any source files (TASK-1821+); rewriting import
statements across consumers (TASK-1824–1826); test changes (TASK-1827).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | add `navigator-eventbus` dep; point `grpc` extra at `navigator-eventbus[grpc]` |
| `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py` | MODIFY (optional) | pass `channel_prefix="parrot:events:"` etc. to `EventBus(...)` — may be deferred to TASK-1826 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# navigator-eventbus top-level — VERIFIED present 2026-07-18:
from navigator_eventbus import EventBus, Event, EventPriority, EventSubscription
from navigator_eventbus import EventEnvelope, Severity, BusCore, DLQHandler

# PROJECTED — depends on FEAT-313 (phase 2) delivery; VERIFY in Preflight:
from navigator_eventbus.lifecycle.base import LifecycleEvent
```

### Existing Signatures to Use

```python
# navigator-eventbus src/navigator_eventbus/evb.py — VERIFIED 2026-07-18
DEFAULT_CHANNEL_PREFIX = "evb:events:"            # line 48
class EventBus:                                    # line ~132
    CHANNEL_PREFIX = DEFAULT_CHANNEL_PREFIX         # line 162
    def __init__(self, redis_url=None, use_redis=False, *,
                 channel_prefix: Optional[str] = None, **bus_options)  # line 164-169
    #  channel_prefix falls back to navconfig BUS_CHANNEL_PREFIX (line 183-184)

# navigator-eventbus src/navigator_eventbus/backends/redis_streams.py — VERIFIED 2026-07-18
DEFAULT_STREAM_PREFIX = "evb:stream:"             # line 57
DEFAULT_DEDUP_PREFIX  = "evb:events:dedup:"       # line 58
class RedisStreamsBackend:
    def __init__(self, ..., *, group: Optional[str] = None,
                 stream_prefix: Optional[str] = None,
                 dedup_prefix: Optional[str] = None, ...)  # line 104-112
    #  navconfig keys: BUS_GROUP, BUS_STREAM_PREFIX, BUS_DEDUP_PREFIX

# ai-parrot-server autonomous/orchestrator.py:231 — the ONLY production EventBus() site
#   current: from parrot.core.events import EventBus, Event, EventPriority  (orchestrator.py:27)
```

### Legacy prefix values to configure (compatibility with deployed streams)

```
channel_prefix = "parrot:events:"
stream_prefix  = "parrot:stream:"
dedup_prefix   = "parrot:events:dedup:"
group          = "parrot-bus"
```

These may be passed as constructor kwargs OR set as navconfig env keys
`BUS_CHANNEL_PREFIX`, `BUS_STREAM_PREFIX`, `BUS_DEDUP_PREFIX`, `BUS_GROUP`.

### Does NOT Exist

- ~~`navigator-eventbus` in `packages/ai-parrot/pyproject.toml`~~ — not present yet; this task adds it.
- ~~an `events` or `redis` extra in ai-parrot's current pyproject~~ — redis arrives transitively; the package declares `[redis]` itself.
- ~~`navigator_eventbus.lifecycle` / `navigator_eventbus.brokers`~~ — NOT present as of 2026-07-18 (FEAT-313 / FEAT-316 pending). Verify in Preflight.

---

## Implementation Notes

### Key Constraints
- Use `uv` for dependency management; ALWAYS `source .venv/bin/activate` first.
- Do not touch other dependency lines in pyproject.toml.
- The package is pre-PyPI: prefer an editable/path dependency for now and add a
  `# TODO: switch to navigator-eventbus>=0.1.0 after PyPI publish (FEAT-317 close)`
  comment.

### References in Codebase
- `packages/ai-parrot/pyproject.toml` — existing `grpc` extra at ~line 416.
- Spec §7 "External Dependencies" and §2 decision #3 (prefix compatibility).

---

## Acceptance Criteria

- [ ] `navigator-eventbus` declared in `packages/ai-parrot/pyproject.toml`.
- [ ] `grpc` extra references `navigator-eventbus[grpc]`.
- [ ] `source .venv/bin/activate && uv pip install -e packages/ai-parrot` succeeds.
- [ ] `python -c "from navigator_eventbus import EventBus"` works.
- [ ] Legacy prefix plumbing documented/prepared for the orchestrator (kwargs or navconfig keys).
- [ ] `ruff check` clean on modified files.

---

## Test Specification

```bash
# Smoke — run in activated venv
python -c "from navigator_eventbus import EventBus, EventEnvelope, Severity; print('OK')"
python -c "from navigator_eventbus import EventBus; b=EventBus(channel_prefix='parrot:events:'); assert b.channel_prefix=='parrot:events:'; print('prefix OK')"
```

---

## Agent Instructions

1. Run the **Preflight** block first. If lifecycle import fails, STOP.
2. Verify the Codebase Contract against the installed package.
3. Update index → `in-progress`.
4. Implement per scope.
5. Verify acceptance criteria.
6. Move to `sdd/tasks/completed/`, update index → `done`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
