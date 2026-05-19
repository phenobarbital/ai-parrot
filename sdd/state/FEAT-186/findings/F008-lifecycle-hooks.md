---
id: F008
query: Q010
type: grep
pattern: on_startup|on_shutdown
---

## App Lifecycle Hooks

FormRegistry hooks into aiohttp lifecycle (registry.py:176-177):
```python
app.on_startup.append(self.on_startup)
app.on_shutdown.append(self.on_shutdown)
```

- on_startup: calls storage.initialize() + load_from_storage()
- on_shutdown: calls storage.close()

**Pattern for PartialSaveStore**: Should similarly hook into app
lifecycle. On startup: verify Redis connection. On shutdown: close
Redis connection (via the same `close()` pattern as FormCache).

No need for startup hydration (unlike FormRegistry) since partial
saves are ephemeral and Redis-native.
