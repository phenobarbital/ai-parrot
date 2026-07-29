---
type: Wiki Entity
title: ChannelDeepLinkResume
id: class:parrot.integrations.a2ui_resume.ChannelDeepLinkResume
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Shared per-channel deep-link resume flow for Telegram / MS Teams.
---

# ChannelDeepLinkResume

Defined in [`parrot.integrations.a2ui_resume`](../summaries/mod:parrot.integrations.a2ui_resume.md).

```python
class ChannelDeepLinkResume
```

Shared per-channel deep-link resume flow for Telegram / MS Teams.

## Methods

- `async def resume(self, token: str, *, inject: Injector) -> dict[str, Any]` — Consume ``token`` and inject the action into the original session.
