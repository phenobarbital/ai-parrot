# TASK-1823: Move yaml_loader engine with injectable event-name table

**Feature**: FEAT-313 — EventBus Lifecycle Extraction (navigator-eventbus phase 2)
**Spec**: `sdd/specs/eventbus-lifecycle-extraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1821
**Assigned-to**: unassigned

---

## Context

This is Module 4 — the second decoupling module. The yaml_loader engine
(`wire_events`, `_wire_handler`, `_wire_provider`, `_resolve`, `_make_where`)
wires YAML-declared event subscriptions onto an agent's `EventRegistry`. Today
it hard-imports the typed event taxonomy at yaml_loader.py:28 and builds a
static `EVENT_CLASSES` dict. This task replaces that with an injectable
registry: `register_event_names(mapping)`.

This is the second of only TWO genuinely new public interfaces in the spec.

---

## Scope

- Copy `yaml_loader.py` (248 LOC) from ai-parrot, applying these changes:
  1. Remove the hard import of typed events (yaml_loader.py:28-44).
  2. Replace the static `EVENT_CLASSES` dict (yaml_loader.py:53-79) with a mutable module-level dict and `register_event_names()` public function.
  3. Change `from parrot.core.events.lifecycle.base import LifecycleEvent` → `from navigator_eventbus.lifecycle.base import LifecycleEvent`
  4. Change `from parrot.core.events.lifecycle.registry import EventRegistry` → `from navigator_eventbus.lifecycle.registry import EventRegistry`
  5. Update logger name to `navigator_eventbus.lifecycle.yaml_loader`
  6. Ensure `LifecycleEvent` is always pre-registered (base/wildcard subscription).
- Error mode change: unknown event name must raise a clear `KeyError`/`ValueError` naming the missing registration (not an `ImportError`).
- Write tests for `register_event_names` and the error mode.

**NOT in scope**: mixin, subscribers, typed events, __init__.py curation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/lifecycle/yaml_loader.py` | CREATE | wire_events engine + register_event_names() |
| `tests/lifecycle/test_yaml_loader.py` | CREATE | Tests for injectable event table + error mode |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# yaml_loader.py current imports (packages/ai-parrot/src/parrot/core/events/lifecycle/yaml_loader.py)
from __future__ import annotations           # :19
import importlib                             # :21
from typing import Any, Callable, Optional   # :22
from navconfig.logging import logging        # :24 — stays (navconfig is a package dep)
from parrot.core.events.lifecycle.base import LifecycleEvent       # :26 → CHANGE
from parrot.core.events.lifecycle.registry import EventRegistry     # :27 → CHANGE

# THE COUPLING TO REPLACE (yaml_loader.py:28-44):
from parrot.core.events.lifecycle.events import (
    AgentInitializedEvent, AgentConfiguredEvent, ToolManagerReadyEvent,
    AgentStatusChangedEvent, BeforeInvokeEvent, AfterInvokeEvent,
    InvokeFailedEvent, BeforeClientCallEvent, AfterClientCallEvent,
    ClientCallFailedEvent, ClientStreamChunkEvent, BeforeToolCallEvent,
    AfterToolCallEvent, ToolCallFailedEvent, MessageAddedEvent,
)
# ^^^ This entire block is REMOVED. The static EVENT_CLASSES dict (:53-79) becomes injectable.
```

### Existing Signatures to Use

```python
# yaml_loader.py functions (signatures preserved exactly):
def _resolve(dotted: str) -> Any: ...                              # :86
def _make_where(where_dict: dict) -> Callable[[Any], bool]: ...    # :113
def wire_events(bot: Any, events_block: Optional[dict]) -> None: ... # :148
def _wire_handler(registry: EventRegistry, sub: dict) -> None: ... # :189
def _wire_provider(registry: EventRegistry, sub: dict) -> None: ... # :233

# New interface (defined by this task — spec §2):
def register_event_names(mapping: dict[str, type[LifecycleEvent]]) -> None:
    """Register app-specific event-name → class mappings for wire_events().
    Additive across calls; later registrations override same-name keys."""
```

### Does NOT Exist

- ~~`navigator_eventbus.lifecycle.yaml_loader` today~~ — does not exist; this task creates it.
- ~~`register_event_names` anywhere in the codebase~~ — this is a new function created by this task.
- ~~`test_yaml_loader.py` in ai-parrot tests~~ — no dedicated test file exists (verified 2026-07-17); the tests here are net-new.
- ~~Typed event classes in the package~~ — they stay in ai-parrot; the engine must NOT import them.

---

## Implementation Notes

### Pattern to Follow

```python
# navigator_eventbus/lifecycle/yaml_loader.py
from __future__ import annotations

import importlib
from typing import Any, Callable, Optional

from navconfig.logging import logging

from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.registry import EventRegistry

logger = logging.getLogger("navigator_eventbus.lifecycle.yaml_loader")

# ---------------------------------------------------------------------------
# Injectable event-name → class registry (replaces hard-coded taxonomy import)
# ---------------------------------------------------------------------------
EVENT_CLASSES: dict[str, type] = {
    LifecycleEvent.__name__: LifecycleEvent,  # always available as wildcard
}


def register_event_names(mapping: dict[str, type[LifecycleEvent]]) -> None:
    """Register app-specific event-name → class mappings for wire_events().

    Additive across calls; later registrations override same-name keys.
    Each app registers its taxonomy:
      - ai-parrot registers BeforeInvokeEvent, AfterInvokeEvent, etc.
      - Flowtask registers its own events.
    """
    EVENT_CLASSES.update(mapping)

# ... rest of the functions copied verbatim (no changes to _resolve, _make_where,
# wire_events, _wire_handler, _wire_provider — only import paths change)
```

### Key Constraints
- `LifecycleEvent` MUST be pre-registered in `EVENT_CLASSES` (base/wildcard subscription).
- `_wire_handler` at the point where it resolves event names from `EVENT_CLASSES` (original :204-209) must raise a clear `ValueError` (not `KeyError` from dict lookup) naming the missing registration — the error message should guide the user to call `register_event_names()`.
- `register_event_names()` is additive — multiple calls accumulate; later calls override same-name keys.
- `_resolve()`, `_make_where()` move unchanged.
- `navconfig.logging` is already a direct dep of the package (phase-1 decision).

### References in Codebase
- `packages/ai-parrot/src/parrot/core/events/lifecycle/yaml_loader.py` — copy source (248 LOC)

---

## Acceptance Criteria

- [ ] `from navigator_eventbus.lifecycle.yaml_loader import wire_events, register_event_names` works
- [ ] No `parrot.*` imports: `grep -r "from parrot\|import parrot" src/navigator_eventbus/lifecycle/yaml_loader.py` → 0 hits
- [ ] No typed event imports (BeforeInvokeEvent, etc.) in the file
- [ ] `register_event_names({"MyEvent": MyEventClass})` makes `MyEvent` resolvable by `wire_events`
- [ ] `LifecycleEvent` is pre-registered (wildcard subscription works without registration)
- [ ] Unregistered event name raises `ValueError` with clear message mentioning `register_event_names`
- [ ] `wire_events`, `_wire_handler`, `_wire_provider`, `_resolve`, `_make_where` signatures preserved
- [ ] All tests pass: `pytest tests/lifecycle/test_yaml_loader.py -v`
- [ ] No linting errors: `ruff check src/navigator_eventbus/lifecycle/yaml_loader.py`

---

## Test Specification

```python
# tests/lifecycle/test_yaml_loader.py
import pytest
from dataclasses import dataclass
from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.yaml_loader import (
    register_event_names, wire_events, EVENT_CLASSES,
)

@dataclass(frozen=True)
class _CustomEvent(LifecycleEvent):
    detail: str = ""

class TestRegisterEventNames:
    def setup_method(self):
        # Reset to baseline — only LifecycleEvent pre-registered
        EVENT_CLASSES.clear()
        EVENT_CLASSES[LifecycleEvent.__name__] = LifecycleEvent

    def test_register_adds_event(self):
        register_event_names({"_CustomEvent": _CustomEvent})
        assert "_CustomEvent" in EVENT_CLASSES

    def test_register_is_additive(self):
        register_event_names({"A": _CustomEvent})
        register_event_names({"B": _CustomEvent})
        assert "A" in EVENT_CLASSES
        assert "B" in EVENT_CLASSES

    def test_register_overrides_same_key(self):
        @dataclass(frozen=True)
        class _Other(LifecycleEvent):
            pass
        register_event_names({"X": _CustomEvent})
        register_event_names({"X": _Other})
        assert EVENT_CLASSES["X"] is _Other

    def test_lifecycle_event_always_preregistered(self):
        assert "LifecycleEvent" in EVENT_CLASSES

class TestUnknownEventName:
    def test_unknown_name_raises_value_error(self):
        """Unregistered event name → clear error, not ImportError."""
        from navigator_eventbus.lifecycle.yaml_loader import _wire_handler
        from navigator_eventbus.lifecycle.registry import EventRegistry

        registry = EventRegistry(forward_to_global=False)
        with pytest.raises(ValueError, match="register_event_names"):
            _wire_handler(registry, {
                "events": ["NonExistentEventName"],
                "handler": "some.module.handler",
            })
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/eventbus-lifecycle-extraction.spec.md` §2 Module 4
2. **Check dependencies** — verify TASK-1821 is done (registry exists in the package)
3. **Verify the Codebase Contract** — confirm yaml_loader.py source still matches
4. **Work in the navigator-eventbus repo** at `/home/jesuslara/proyectos/navigator-eventbus`
5. **Remove** the typed event import block and static dict — replace with injectable registry
6. **Update error messages** to reference `register_event_names()`
7. **Run tests**: `pytest tests/lifecycle/test_yaml_loader.py -v`
8. **Commit**: `feat: yaml_loader engine + injectable event-name table (FEAT-313 TASK-1823)`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
