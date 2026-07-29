---
type: Wiki Entity
title: FileWatchdogHook
id: class:parrot.core.hooks.file_watchdog.FileWatchdogHook
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Monitors a directory for file changes and emits HookEvents.
relates_to:
- concept: class:parrot.core.hooks.base.BaseHook
  rel: extends
---

# FileWatchdogHook

Defined in [`parrot.core.hooks.file_watchdog`](../summaries/mod:parrot.core.hooks.file_watchdog.md).

```python
class FileWatchdogHook(BaseHook)
```

Monitors a directory for file changes and emits HookEvents.

## Methods

- `async def start(self) -> None`
- `async def stop(self) -> None`
- `def dispatch_event(self, event_type: str, filename: str, raw_event: Any) -> None` — Called from the watchdog thread — schedules async callback.
