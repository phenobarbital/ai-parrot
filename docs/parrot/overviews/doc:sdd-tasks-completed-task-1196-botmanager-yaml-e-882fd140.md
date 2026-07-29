---
type: Wiki Overview
title: 'TASK-1196: Add events: YAML block parsing to BotManager / AgentRegistry'
id: doc:sdd-tasks-completed-task-1196-botmanager-yaml-events-loader-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Module 16 of the spec. Lets users declare lifecycle subscribers directly
  in agent YAML definitions. Two forms supported: single-callback `handler:` (with
  `events:` filter list) and bundled `provider:` (with `config:` block). Optional
  `where:` clauses translate to predicate filter'
relates_to:
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.provider
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.yaml_loader
  rel: mentions
---

# TASK-1196: Add events: YAML block parsing to BotManager / AgentRegistry

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-1186, TASK-1188, TASK-1189, TASK-1193, TASK-1190, TASK-1191, TASK-1192
**Assigned-to**: unassigned

---

## Context

Module 16 of the spec. Lets users declare lifecycle subscribers directly in agent YAML definitions. Two forms supported: single-callback `handler:` (with `events:` filter list) and bundled `provider:` (with `config:` block). Optional `where:` clauses translate to predicate filters. Optional `forward_to_bus:` flag propagates per subscription.

Spec section: §2 YAML Declarative Syntax (lines 492–529), §3 Module 16.

---

## Scope

- Extend `AgentRegistry.load_agent_definitions()` / `BotMetadata.get_instance()` to parse the optional top-level `events:` block from each agent YAML.
- Support both forms:
  - **handler form**: `handler: dotted.path:func` + `events: [EventClass1, EventClass2]` + optional `where:` mapping (field → list of values to match) + optional `forward_to_bus: bool`.
  - **provider form**: `provider: dotted.path:Class` + optional `config: { ... }` constructor kwargs + optional `events:` (filter) + optional `forward_to_bus: bool`.
- Resolve dotted paths via `importlib.import_module` + `getattr`. Format: `"module.path:ObjectName"` (colon separator, matching the spec's example syntax).
- Wire the constructed subscribers/providers to the bot's `self.events` registry AT bot construction time, before `AgentInitializedEvent` would emit (i.e., before `_init_events` finishes, OR immediately after — see Notes).
- Support optional top-level `events.forward_to_global` (bool, default `True`) and `events.event_bus` (navconfig-resolved reference, default `None`).
- Add unit tests covering: handler form + filter, provider form + config, where clause translates to predicate, forward_to_bus honored, dotted-path resolution errors yield a clear error message.

**NOT in scope**: changes to existing YAML fields, hot-reload of subscribers (re-loading after the bot is running).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | Parse `events:` block inside `BotMetadata.get_instance()` (lines 78–149) — wire subscribers after `_init_events`. |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/yaml_loader.py` | CREATE | Helper module: `parse_events_block(events_dict) -> EventsConfig` + `wire_events(bot, cfg)`. |
| `packages/ai-parrot/tests/unit/registry/test_events_yaml.py` | CREATE | YAML parsing + wiring tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import importlib
from typing import Any, Optional

from parrot.core.events.lifecycle.registry import EventRegistry            # TASK-1186
from parrot.core.events.lifecycle.provider import EventProvider            # TASK-1188
from parrot.core.events.lifecycle.events import (                          # TASK-1184
    # Map event-class names to actual classes for YAML resolution
    BeforeInvokeEvent, AfterInvokeEvent, InvokeFailedEvent,
    BeforeClientCallEvent, AfterClientCallEvent,
    ClientCallFailedEvent, ClientStreamChunkEvent,
    BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent,
    AgentInitializedEvent, AgentConfiguredEvent,
    ToolManagerReadyEvent, AgentStatusChangedEvent,
    MessageAddedEvent,
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/registry/registry.py — VERIFIED
class BotMetadata:
    def get_instance(self, ...) -> AbstractBot:   # lines 78-149
        # Field-merging logic. Add `events:` parsing alongside `tools` / `model` / etc.
        ...

class AgentRegistry:
    def load_agent_definitions(self): ...   # iterates AGENTS_DIR for YAML files
```

```python
# packages/ai-parrot/src/parrot/manager/manager.py — VERIFIED
class BotManager:
    def load_bots(self): ...                # line 89, entry point
    def _load_database_bots(self): ...
```

### Does NOT Exist

- ~~`yaml.safe_load` per-line~~ — YAML files are loaded as a whole via `yaml.load` (or `safe_load`). Use the existing pattern in `registry.py`.
- ~~`EventClassRegistry`~~ — no central event-class registry exists. Use a dict mapping `str → type[LifecycleEvent]` inside `yaml_loader.py`.

---

## Implementation Notes

### EVENT_CLASSES name registry

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/yaml_loader.py
EVENT_CLASSES: dict[str, type] = {
    cls.__name__: cls
    for cls in [
        BeforeInvokeEvent, AfterInvokeEvent, InvokeFailedEvent,
        BeforeClientCallEvent, AfterClientCallEvent,
        ClientCallFailedEvent, ClientStreamChunkEvent,
        BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent,
        AgentInitializedEvent, AgentConfiguredEvent,
        ToolManagerReadyEvent, AgentStatusChangedEvent,
        MessageAddedEvent,
    ]
}
```

### Dotted-path resolver

```python
def _resolve(dotted: str):
    """`module.path:ObjectName` → resolved object."""
    if ":" not in dotted:
        raise ValueError(
            f"Bad dotted path {dotted!r}: expected 'module.path:Object'"
        )
    mod_path, name = dotted.split(":", 1)
    mod = importlib.import_module(mod_path)
    try:
        return getattr(mod, name)
    except AttributeError as exc:
        raise ImportError(f"{mod_path} has no attribute {name!r}") from exc
```

### where-clause translator

YAML:
```yaml
where:
  tool_name: [jira_create_issue, jira_update_issue]
```

becomes:
```python
def _make_where(where_dict: dict) -> Callable:
    def predicate(event) -> bool:
        for field, allowed in where_dict.items():
            value = getattr(event, field, None)
            if isinstance(allowed, list):
                if value not in allowed:
                    return False
            else:
                if value != allowed:
                    return False
        return True
    return predicate
```

### Wiring entry point

```python
def wire_events(bot, events_block: dict) -> None:
    """Apply a parsed YAML `events:` block to the bot's registry."""
    if not events_block:
        return
    registry: EventRegistry = bot.events
    for sub in events_block.get("subscribers", []):
        if "handler" in sub:
            cb = _resolve(sub["handler"])
            evt_classes = [EVENT_CLASSES[n] for n in sub.get("events", [])] or [LifecycleEvent]
            where = _make_where(sub["where"]) if sub.get("where") else None
            for ec in evt_classes:
                registry.subscribe(ec, cb, where=where, forward_to_bus=sub.get("forward_to_bus", False))
        elif "provider" in sub:
            ProviderCls = _resolve(sub["provider"])
            provider = ProviderCls(**sub.get("config", {}))
            registry.add_provider(provider)
        else:
            raise ValueError(f"Subscriber needs 'handler' or 'provider': {sub!r}")
```

### Top-level options

```yaml
events:
  forward_to_global: false        # applied to registry at construction
  event_bus: ${EVENT_BUS_REF}     # navconfig reference; resolve before passing
```

The implementer parses these from the YAML and passes them to `_init_events`. Since `_init_events` is called inside `AbstractBot.__init__` (TASK-1193), `BotMetadata.get_instance` must pass them via the AbstractBot constructor kwargs (the bot's `__init__` accepts `**kwargs` per the verified signature).

### Integration point in registry.py

Inside `BotMetadata.get_instance(...)`, after the bot is constructed but before any user code emits, call:

```python
from parrot.core.events.lifecycle.yaml_loader import wire_events
wire_events(bot, self.events_block)
```

(Where `self.events_block` is parsed from the YAML earlier in the same method.)

### Key Constraints

- Keep ordering deterministic: subscribers are wired in the order they appear in YAML.
- If the YAML is malformed (missing `handler`/`provider`, unknown event class), raise a `ValueError` with a clear message naming the offending entry — never silently skip.
- Pass `event_bus` through `_init_events` only if the YAML explicitly declares it. Default behavior unchanged.

---

## Acceptance Criteria

- [ ] An agent YAML with a `handler:` subscriber wires up correctly; `bot.events` has the expected subscription.
- [ ] An agent YAML with a `provider:` + `config:` subscriber instantiates the provider with kwargs and registers it.
- [ ] `where:` clause filters events as declared.
- [ ] `forward_to_bus: true` per subscriber is honored.
- [ ] Top-level `forward_to_global: false` propagates to `_init_events`.
- [ ] Malformed YAML (missing fields, unknown event class) raises `ValueError` with a clear message.
- [ ] Unit tests pass: `pytest packages/ai-parrot/tests/unit/registry/test_events_yaml.py -v`.
- [ ] Existing registry/manager tests continue to pass.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/registry/test_events_yaml.py
import pytest

from parrot.core.events.lifecycle.yaml_loader import (
    wire_events, _resolve, _make_where, EVENT_CLASSES,
)
from parrot.core.events.lifecycle.events import BeforeToolCallEvent
from parrot.core.events.lifecycle.registry import EventRegistry


class TestYamlLoader:
    def test_resolve_dotted(self):
        cls = _resolve("parrot.core.events.lifecycle.events:BeforeToolCallEvent")
        assert cls is BeforeToolCallEvent

    def test_resolve_bad_path(self):
        with pytest.raises(ValueError):
            _resolve("noseparator")

    def test_where_predicate(self):
        pred = _make_where({"tool_name": ["a", "b"]})
        from parrot.core.events.lifecycle.trace import TraceContext
        e1 = BeforeToolCallEvent(trace_context=TraceContext.new_root(), tool_name="a")
        e2 = BeforeToolCallEvent(trace_context=TraceContext.new_root(), tool_name="c")
        assert pred(e1) is True
        assert pred(e2) is False

    def test_handler_form(self):
        captured = []
        async def cb(e): captured.append(e)
        # Stub module so _resolve finds the callback
        import sys, types
        mod = types.ModuleType("test_stub_handler")
        mod.cb = cb
        sys.modules["test_stub_handler"] = mod

        from types import SimpleNamespace
        bot = SimpleNamespace(events=EventRegistry(forward_to_global=False))
        block = {
            "subscribers": [
                {
                    "handler": "test_stub_handler:cb",
                    "events": ["BeforeToolCallEvent"],
                }
            ]
        }
        wire_events(bot, block)
        assert len(bot.events._subscriptions) == 1
```

---

## Agent Instructions

1. Read spec §2 lines 492–529 (YAML syntax) and §3 Module 16.
2. Confirm dependencies (TASK-1186, 1188, 1189, 1193, 1190, 1191, 1192) are completed.
3. Read `parrot/registry/registry.py` line 78–149 to understand `BotMetadata.get_instance` field-merging flow.
4. Implement `yaml_loader.py` and wire it into `get_instance`.
5. Run registry/manager tests, verify zero regressions.
6. Update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-15
**Notes**:
- Created parrot/core/events/lifecycle/yaml_loader.py with EVENT_CLASSES dict (16 classes including LifecycleEvent), _resolve() dotted-path resolver, _make_where() predicate builder, wire_events() entry point, _wire_handler() and _wire_provider() helpers
- Added events_block: Optional[Dict[str, Any]] = None field to BotMetadata dataclass (slots=True)
- Modified BotMetadata.get_instance(): after configure(), calls wire_events(instance, self.events_block) with error logging on failure (not fatal)
- Modified AgentRegistry.load_agent_definitions(): parses top-level 'events:' key and stores in BotMetadata.events_block
- 19 unit tests covering resolve, where predicates, handler/provider forms, where clause, forward_to_bus, bad inputs, empty block, EVENT_CLASSES population
- All 110 registry tests pass (no regressions)

**Deviations from spec**: none
