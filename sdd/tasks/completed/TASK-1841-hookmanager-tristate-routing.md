# TASK-1841: HookManager tri-state route_to_bus — auto-routing when bus attached

**Feature**: FEAT-319 — EventBus Consolidation
**Spec**: `sdd/specs/eventbus-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

> **REPO**: `navigator-eventbus` — work in `/home/jesuslara/proyectos/navigator-eventbus`.
> SDD state stays in ai-parrot. Independent of TASK-1839/1840 (different files) —
> may run in parallel on the same branch.

---

## Context

Spec §3 Module 2. `HookManager(route_to_bus=False)` makes bus routing opt-in,
contradicting the "bus as app-wide fabric" goal. This task makes routing
default-capable: `None` (new default) → auto-route iff a bus is attached;
explicit `True`/`False` keep today's semantics. Audit fact: ai-parrot has ZERO
`route_to_bus`/`set_event_bus` call sites, so this change is latent downstream —
but it must be flagged in the 0.1.0 changelog (TASK-1842).

---

## Scope

- Change signature: `def __init__(self, *, route_to_bus: Optional[bool] = None)`.
- Add `_effective_route_to_bus() -> bool`:
  `self._route_to_bus if self._route_to_bus is not None else (self._event_bus is not None)`.
- `_build_dispatch()` and `_publish_hook_event()` consult
  `_effective_route_to_bus()` instead of `self._route_to_bus` directly
  (note: `_publish_hook_event` line 145 currently reads `if not self._route_to_bus:`).
- `route_to_bus` property returns the **effective** value; setter accepts
  `Optional[bool]` — remove the `bool(enabled)` coercion at line 60 (it would
  turn `None` into `False`), keep the callback re-injection behavior.
- One-time INFO log on first auto-activation
  (`"route_to_bus auto-enabled: bus attached"`); the once-flag resets in
  `set_event_bus` when the bus is detached/replaced so re-attachment logs again.
- Unit tests (see Test Specification). Pre-existing HookManager tests must pass
  unmodified except constructor kwargs.

**NOT in scope**: envelope/schema_version (TASK-1839/1840); release (TASK-1842);
any ai-parrot change (TASK-1843).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/hooks/manager.py` | MODIFY | tri-state + effective resolver + one-time log |
| `tests/hooks/test_route_to_bus_tristate.py` | CREATE | unit tests below (place beside existing hook tests) |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-20 against `navigator-eventbus@main` local checkout.

### Verified Imports
```python
from navigator_eventbus.hooks.manager import HookManager
```

### Existing Signatures to Use
```python
# src/navigator_eventbus/hooks/manager.py
class HookManager:
    def __init__(self, *, route_to_bus: bool = False) -> None:   # line 45
        self._hooks: Dict[str, BaseHook] = {}
        self._callback: Optional[Callable] = None
        self._event_bus: Optional["EventBus"] = None
        self._route_to_bus = route_to_bus                        # line 49
    @property  # route_to_bus                                    # line 52–55 (returns self._route_to_bus)
    # setter                                                     # line 57–63: self._route_to_bus = bool(enabled)  ← REMOVE coercion
    def set_event_bus(self, bus: "EventBus") -> None             # line 75 — rebuilds dispatch, re-injects hook callbacks
    def _build_dispatch(self) -> Optional[Callable]              # line 92 — callback read at CALL-time (anti-stale-closure)
    async def _publish_hook_event(self, bus: "EventBus", event) -> None  # line 132
        # line 145: `if not self._route_to_bus:` → legacy bus.emit(topic, event.model_dump())
        # else (149–177): first-class envelope kwargs emit (source/metadata/severity)
```

### Does NOT Exist
- ~~`_effective_route_to_bus()`~~ — this task creates it.
- ~~an auto-activation log / once-flag~~ — this task creates them.
- ~~`route_to_bus` consumers in ai-parrot~~ — zero call sites (audit 2026-07-20);
  do not add compatibility shims for callers that don't exist.

---

## Implementation Notes

### Pattern to Follow
```python
# Match the call-time-read pattern already used in _build_dispatch (line 92–130):
# the dispatch wrapper reads self._callback at call time, not capture time.
# Read the effective routing the same way — at call time inside the wrapper.
def _effective_route_to_bus(self) -> bool:
    if self._route_to_bus is not None:
        return self._route_to_bus
    return self._event_bus is not None
```

### Key Constraints
- Dual-emit stays: bus routing is ADDITIVE — the callback path must keep firing
  when routing is active (`test_callback_still_fires_when_routed`).
- Explicit `False` beats an attached bus; explicit `True` behaves exactly as today.
- One-time log: `logging.Logger.info` once per attachment; reset the flag when
  `set_event_bus` swaps/removes the bus.
- Property now returns the effective value — check existing tests/docstrings that
  read `manager.route_to_bus` and adjust ONLY if they asserted the raw flag.

---

## Acceptance Criteria

- [ ] `route_to_bus=None` + bus attached → events reach bus topic `hooks.*` (auto).
- [ ] `route_to_bus=None`, no bus → callback-only, no error.
- [ ] Explicit `False` + bus attached → NOT routed; explicit `True` unchanged.
- [ ] Callback and bus both receive when routed (dual-emit).
- [ ] INFO log fires exactly once per attachment; detach/re-attach logs again.
- [ ] Pre-existing HookManager tests pass unmodified except constructor kwargs.
- [ ] Full suite green: `pytest tests/ -v`; `ruff check src/` clean.

---

## Test Specification

```python
# tests/hooks/test_route_to_bus_tristate.py
import pytest
from navigator_eventbus.hooks.manager import HookManager


class FakeBus:
    def __init__(self):
        self.emitted = []
    async def emit(self, topic, payload=None, **kw):
        self.emitted.append((topic, payload, kw))


@pytest.mark.asyncio
async def test_route_to_bus_auto_with_bus():
    mgr = HookManager()                      # route_to_bus omitted → None → auto
    bus = FakeBus()
    mgr.set_event_bus(bus)
    assert mgr.route_to_bus is True          # effective value
    # fire a hook event through the dispatch and assert bus.emitted non-empty


@pytest.mark.asyncio
async def test_route_to_bus_auto_without_bus():
    mgr = HookManager()
    assert mgr.route_to_bus is False         # no bus → auto-off, no error


@pytest.mark.asyncio
async def test_route_to_bus_explicit_false_overrides_bus():
    mgr = HookManager(route_to_bus=False)
    mgr.set_event_bus(FakeBus())
    assert mgr.route_to_bus is False


def test_auto_activation_logs_once(caplog):
    mgr = HookManager()
    with caplog.at_level("INFO", logger="navigator_eventbus.hooks.manager"):
        mgr.set_event_bus(FakeBus())
        mgr.set_event_bus(FakeBus())         # replace → flag reset → logs again
    assert sum("auto-enabled" in r.message for r in caplog.records) == 2
```

> Wire the "fire a hook event" step to the repo's existing hook-test fixtures
> (see current HookManager tests) rather than inventing new fakes for BaseHook.

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/eventbus-consolidation.spec.md` (ai-parrot).
2. **cd to `/home/jesuslara/proyectos/navigator-eventbus`** — all code work there.
3. **Verify the Codebase Contract** (grep the listed lines) before writing code.
4. **Update status** in `sdd/tasks/index/eventbus-consolidation.json` → `"in-progress"`.
5. **Implement**, run the FULL test suite (existing hook tests must stay green).
6. **Move this file** to `sdd/tasks/completed/`, set index status `"done"`, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-21
**Notes**: Implemented in the same `navigator-eventbus` worktree/branch as
TASK-1839/1840 (`feat-FEAT-319-eventbus-consolidation`). Signature changed
to `route_to_bus: Optional[bool] = None`; added `_effective_route_to_bus()`;
`_publish_hook_event`'s wire-format branch now reads the effective value
(`_build_dispatch` itself never gated on the flag — only the wire-format
branch in `_publish_hook_event` did, verified by grep before editing);
`route_to_bus` property returns the effective value, setter drops the
`bool()` coercion; one-time INFO log + once-flag reset in `set_event_bus`.
Discovered during implementation: with the new `None` default, several
PRE-EXISTING tests that manually attach a bus via `mgr._event_bus = bus`
(bypassing `set_event_bus`) would silently flip from legacy to first-class
wire format under auto-routing. Per the task's own allowance ("pre-existing
tests pass unmodified except constructor kwargs"), pinned
`route_to_bus=False` explicitly in 3 tests in `tests/test_hooks_manager.py`
(`test_route_to_bus_default_off_legacy_dual_emit`,
`test_dual_emit_calls_callback_and_bus`,
`test_dual_emit_channel_uses_hook_type_and_event_type`) to preserve their
original legacy-shape intent — no assertions changed, only constructor
kwargs. Added `tests/hooks/test_route_to_bus_tristate.py` (7 tests) per
spec. Full suite green: 324 passed, 1 skipped (all pre-existing HookManager
tests pass). Ruff clean on touched files. Commit: `44d88d2`.

**Deviations from spec**: none (constructor-kwarg-only test edits explicitly
permitted by this task's own acceptance criteria).

---

## Addendum (2026-07-21) — code review confirmation + doc wording fix

Independent code review (via `code-reviewer` agent) independently
re-verified (not just trusted this note) that `_build_dispatch()` never
read `self._route_to_bus` in either the pre- or post-diff code — only
`_publish_hook_event()`'s wire-format branch did — confirming the
observation already recorded above. The parent spec
(`sdd/specs/eventbus-consolidation.spec.md` §3 Module 2) has been
corrected accordingly (revision 0.2) since it had claimed both methods
needed the swap. Also tightened `set_event_bus`'s docstring/comment
wording: "resets when the bus is detached/replaced" → clarified that
there is no separate detach method — the flag resets on every
`set_event_bus` call (a replace is the only way attachment changes
today). No behavior change, no new tests needed (pure wording). Commit:
`a50c1f8` (same worktree/branch).
