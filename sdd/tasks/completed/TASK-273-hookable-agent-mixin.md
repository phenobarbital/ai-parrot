# TASK-273: HookableAgent Mixin

**Feature**: Shared Hooks Infrastructure (FEAT-040)
**Spec**: `sdd/specs/integrations-hooks.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-269
**Assigned-to**: null

---

## Context

> Create a `HookableAgent` mixin in `parrot/core/hooks/mixins.py` that integration handlers
> can inherit to gain hook support without depending on `parrot/autonomous`.

---

## Scope

### Files to Create

| File | Action | Description |
|---|---|---|
| `parrot/core/hooks/mixins.py` | CREATE | `HookableAgent` mixin class |

### Files to Modify

| File | Action | Description |
|---|---|---|
| `parrot/core/hooks/__init__.py` | MODIFY | Add `HookableAgent` to exports |

### HookableAgent API

```python
class HookableAgent:
    """Mixin that adds hook support to any agent or integration handler.

    Provides a HookManager instance and convenience methods for
    attaching, starting, stopping hooks and handling hook events.
    """

    def _init_hooks(self) -> None:
        """Initialize the hook manager. Call in __init__."""

    def attach_hook(self, hook: BaseHook) -> str:
        """Register a hook and return its hook_id."""

    async def start_hooks(self) -> None:
        """Start all registered hooks."""

    async def stop_hooks(self) -> None:
        """Stop all registered hooks."""

    async def handle_hook_event(self, event: HookEvent) -> None:
        """Default event handler. Override in subclass for custom routing."""

    @property
    def hook_manager(self) -> HookManager:
        """Access the underlying HookManager."""
```

### Implementation Notes

- The mixin should call `_init_hooks()` lazily — create `HookManager` on first use.
- `handle_hook_event()` should log the event and be designed to be overridden.
- The mixin must NOT assume anything about the host class (no `self.agent`, `self.bot`, etc.).
- Use `logging.getLogger(__name__)` for logging.
- Add `HookableAgent` to `__init__.py` exports (eager, not lazy — it's lightweight).

---

## Acceptance Criteria

- [ ] `parrot/core/hooks/mixins.py` exists with `HookableAgent` class
- [ ] `from parrot.core.hooks import HookableAgent` works
- [ ] Mixin can be attached to a plain class and hooks can be registered
- [ ] `start_hooks()` / `stop_hooks()` lifecycle works with mock hooks
- [ ] `handle_hook_event()` receives events from registered hooks
- [ ] `ruff check parrot/core/hooks/mixins.py` passes
- [ ] Unit tests cover full mixin lifecycle

---

## Agent Instructions

1. Read the spec for mixin requirements
2. Create `parrot/core/hooks/mixins.py` with `HookableAgent`
3. Update `parrot/core/hooks/__init__.py` to export `HookableAgent`
4. Write unit tests in `tests/core/hooks/test_hookable_agent.py`
5. Run `ruff check` and `pytest`
6. Update status → `done`, move to `sdd/tasks/completed/`
