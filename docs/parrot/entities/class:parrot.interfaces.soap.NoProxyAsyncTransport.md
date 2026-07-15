---
type: Wiki Entity
title: NoProxyAsyncTransport
id: class:parrot.interfaces.soap.NoProxyAsyncTransport
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Zeep AsyncTransport subclass that:'
---

# NoProxyAsyncTransport

Defined in [`parrot.interfaces.soap`](../summaries/mod:parrot.interfaces.soap.md).

```python
class NoProxyAsyncTransport(ZeepAsyncTransport)
```

Zeep AsyncTransport subclass that:
- Omits 'proxies=' when building the sync httpx.Client (avoids httpx>=0.28 errors).
- Provides the attributes Zeep expects (client, logger, _close_session).
- Disables automatic session close in destructor to avoid AsyncClient.close errors.
