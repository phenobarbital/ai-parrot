---
type: Wiki Entity
title: LazyGroup
id: class:parrot.cli.LazyGroup
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Click group that imports subcommands on first invocation.
---

# LazyGroup

Defined in [`parrot.cli`](../summaries/mod:parrot.cli.md).

```python
class LazyGroup(click.Group)
```

Click group that imports subcommands on first invocation.

## Methods

- `def list_commands(self, ctx)` — Return sorted list of registered subcommand names.
- `def get_command(self, ctx, cmd_name)` — Lazily import and return a subcommand by name.
