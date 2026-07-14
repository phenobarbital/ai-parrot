---
type: Wiki Entity
title: SOAPClient
id: class:parrot.interfaces.soap.SOAPClient
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: SOAPClient
---

# SOAPClient

Defined in [`parrot.interfaces.soap`](../summaries/mod:parrot.interfaces.soap.md).

```python
class SOAPClient(ABC)
```

SOAPClient

    Overview

        The SOAPClient class is a generic asynchronous base for SOAP integrations.
        It provides OAuth2 refresh_token grant, Redis caching of access_token, and
        customizable httpx.AsyncClient for Zeep. Designed for easy extension to
        specific SOAP APIs.

    .. table:: Properties
    :widths: auto

        +-------------------+----------+-----------+---------------------------------------------------------------+
        | Name              | Required | Summary                                                           |
        +-------------------+----------+-----------+---------------------------------------------------------------+
        | credentials       |   Yes    | Dict with client_id, client_secret, token_url, wsdl_path, refresh_token |
        | httpx_client      |   No     | Optionally inject a configured AsyncClient                        |
        | redis_url         |   No     | Redis DSN for token cache                                         |
        | redis_key         |   No     | Key under which to cache the access token                         |
        | timeout           |   No     | HTTP request timeout (seconds)                                    |
        +-------------------+----------+-----------+---------------------------------------------------------------+

    Returns

        This component provides an async interface to SOAP APIs, handling authentication,
        caching, and Zeep client/service setup. Subclasses should implement specific
        SOAP operations.

    Example:

    ```python
    class MyClient(SOAPClient):
        ...
    ```

## Methods

- `async def start(self) -> None` — 1) Connect to Redis
- `def get_transport(self) -> NoProxyAsyncTransport` — Wrap an AsyncClient in our NoProxyAsyncTransport.
- `def get_settings(self) -> Settings` — Zeep settings: non-strict, support huge XML trees.
- `def get_client(self) -> ZeepAsyncClient` — Instantiate the Zeep AsyncClient for our WSDL.
- `def bind_service(self) -> Any` — Return the bound service proxy from Zeep.
- `async def run(self, operation: str, **kwargs) -> Any` — Invoke a named SOAP operation with kwargs.
- `async def close(self) -> None` — Cleanup HTTP session and Redis connection.
