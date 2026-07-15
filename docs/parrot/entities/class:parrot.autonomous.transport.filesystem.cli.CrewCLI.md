---
type: Wiki Entity
title: CrewCLI
id: class:parrot.autonomous.transport.filesystem.cli.CrewCLI
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Read-only CLI view into the FilesystemTransport state.
---

# CrewCLI

Defined in [`parrot.autonomous.transport.filesystem.cli`](../summaries/mod:parrot.autonomous.transport.filesystem.cli.md).

```python
class CrewCLI
```

Read-only CLI view into the FilesystemTransport state.

Reads directly from the filesystem — no running transport process
is required.

Args:
    root_dir: Root directory of the FilesystemTransport data.

## Methods

- `async def get_state(self) -> Dict[str, Any]` — Read current system state from the filesystem.
- `def render_text(self, state: Dict[str, Any]) -> str` — Render state as plain text.
- `def render_rich(self, state: Dict[str, Any]) -> None` — Render state using ``rich`` for formatted terminal output.
