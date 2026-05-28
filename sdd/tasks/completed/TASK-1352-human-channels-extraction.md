# TASK-1352: Human Channels Extraction + ChannelRegistry

**Feature**: FEAT-202 — ai-parrot-integrations
**Spec**: `sdd/specs/ai-parrot-integrations.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1344
**Assigned-to**: unassigned

---

## Context

Move channel-specific implementations from `parrot/human/channels/` to
the satellite package while keeping the base interface and a new
`ChannelRegistry` in core. The `TelegramHumanChannel` (41 KB) is
inherently channel-specific; `base.py` (HumanChannel ABC) and `cli.py`
stay in core. `web.py` stays in core (not channel-specific).

The `ChannelRegistry` enables satellite packages to register channel
implementations that core can discover at runtime.

Implements **Spec Module 9**.

---

## Scope

- Move `packages/ai-parrot/src/parrot/human/channels/telegram.py` →
  `packages/ai-parrot-integrations/src/parrot/human/channels/telegram.py`
- Keep in core: `base.py`, `cli.py`, `web.py`, `__init__.py`
- Create `ChannelRegistry` in `parrot/human/channels/__init__.py` (core):
  ```python
  class ChannelRegistry:
      def register(self, name: str, channel_cls: type) -> None: ...
      def get(self, name: str) -> type: ...
      def available(self) -> list[str]: ...
  ```
- Update `parrot/human/__init__.py` to lazy-load `TelegramHumanChannel`
  via PEP 420 (it currently imports it directly at lines 30-32).
- `TelegramHumanChannel` in satellite auto-registers with `ChannelRegistry`.

**NOT in scope**: Moving `parrot/human/` top-level (HITL is core concept).
Moving `cli.py` or `web.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/human/channels/telegram.py` | CREATE (move) | TelegramHumanChannel |
| `packages/ai-parrot/src/parrot/human/channels/__init__.py` | MODIFY | Add ChannelRegistry |
| `packages/ai-parrot/src/parrot/human/__init__.py` | MODIFY | Update lazy TelegramHumanChannel import |
| `packages/ai-parrot/src/parrot/human/channels/telegram.py` | DELETE | Moved to satellite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# parrot/human/__init__.py:30-32 — lazy export (PEP 562)
# TelegramHumanChannel loaded lazily

# parrot/integrations/manager.py:18-22 — runtime import
from ..human import (
    HumanInteractionManager,
    TelegramHumanChannel,       # this will resolve via PEP 420
    set_default_human_manager,
)

# parrot/human/channels/__init__.py — current exports
# (need to read to see what's there now)

# parrot/human/channels/base.py — HumanChannel ABC (~7.4KB)
# parrot/human/channels/cli.py — CLIHumanChannel (~21KB)
# parrot/human/channels/web.py — WebHumanChannel
# parrot/human/channels/telegram.py — TelegramHumanChannel (~41KB)
```

### Does NOT Exist

- ~~`parrot.human.channels.ChannelRegistry`~~ — does NOT exist; this task creates it
- ~~`parrot.human.channels.SlackHumanChannel`~~ — only telegram exists today

---

## Implementation Notes

### Pattern to Follow — ChannelRegistry

```python
# parrot/human/channels/__init__.py (core)
class ChannelRegistry:
    _channels: dict[str, type] = {}

    @classmethod
    def register(cls, name: str, channel_cls: type) -> None:
        cls._channels[name] = channel_cls

    @classmethod
    def get(cls, name: str) -> type | None:
        return cls._channels.get(name)

    @classmethod
    def available(cls) -> list[str]:
        return list(cls._channels.keys())
```

```python
# packages/ai-parrot-integrations/src/parrot/human/channels/telegram.py
# At module level, after class definition:
from parrot.human.channels import ChannelRegistry
ChannelRegistry.register("telegram", TelegramHumanChannel)
```

### Key Constraints

- `base.py` and `cli.py` MUST stay in core — they are used by non-channel
  code (HITL manager, CLI companion).
- `web.py` stays in core — it's a generic web channel.
- `parrot/human/__init__.py` currently has `TelegramHumanChannel` in
  `__all__` (line ~80) and as a lazy export — update to use PEP 420.
- `IntegrationBotManager` (now in satellite) imports
  `TelegramHumanChannel` — this resolves via PEP 420 within satellite.

---

## Acceptance Criteria

- [ ] `TelegramHumanChannel` in satellite at `parrot/human/channels/telegram.py`
- [ ] `ChannelRegistry` in core with `register()`, `get()`, `available()`
- [ ] `TelegramHumanChannel` auto-registers with `ChannelRegistry` on import
- [ ] `base.py`, `cli.py`, `web.py` remain in core untouched
- [ ] `from parrot.human import TelegramHumanChannel` works via PEP 420
- [ ] No linting errors

---

## Completion Note

*(Agent fills this in when done)*
