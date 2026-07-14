---
type: Wiki Entity
title: IMAPWatchdogHook
id: class:parrot.core.hooks.imap.IMAPWatchdogHook
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Monitors an IMAP mailbox for new emails using aioimaplib.
relates_to:
- concept: class:parrot.core.hooks.base.BaseHook
  rel: extends
---

# IMAPWatchdogHook

Defined in [`parrot.core.hooks.imap`](../summaries/mod:parrot.core.hooks.imap.md).

```python
class IMAPWatchdogHook(BaseHook)
```

Monitors an IMAP mailbox for new emails using aioimaplib.

Supports basic auth and XOAUTH2.  Optional tagged-email filtering
(plus-addressing) when ``config.tag`` is set.

## Methods

- `async def start(self) -> None`
- `async def stop(self) -> None`
