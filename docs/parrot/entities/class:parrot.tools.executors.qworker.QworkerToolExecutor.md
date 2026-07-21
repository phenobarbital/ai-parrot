---
type: Wiki Entity
title: QworkerToolExecutor
id: class:parrot.tools.executors.qworker.QworkerToolExecutor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Dispatch tool execution to the Qworker service.
relates_to:
- concept: class:parrot.tools.executors.abstract.AbstractToolExecutor
  rel: extends
---

# QworkerToolExecutor

Defined in [`parrot.tools.executors.qworker`](../summaries/mod:parrot.tools.executors.qworker.md).

```python
class QworkerToolExecutor(AbstractToolExecutor)
```

Dispatch tool execution to the Qworker service.

Args:
    transport: ``"http"`` for the Qclient HTTP API, ``"redis"`` for
        Redis Streams. Defaults to ``"http"``.
    endpoint: HTTP base URL for Qworker (e.g. ``http://qworker:9000``).
        Required when ``transport="http"`` unless
        :data:`parrot.conf.QWORKER_URL` is set.
    api_token: Optional bearer token. Falls back to
        :data:`parrot.conf.QWORKER_API_TOKEN`.
    redis_url: Redis DSN for the streams transport. Falls back to
        :data:`parrot.conf.REDIS_SERVICES_URL`.
    request_stream: Redis stream name jobs are posted to.
        Defaults to ``parrot:tool_tasks``.
    result_stream: Redis stream name results are read from.
        Defaults to ``parrot:tool_results``.
    qclient: Pre-built Qclient instance — useful for tests and for
        sharing a connection pool. When ``None``, an instance is
        created lazily from ``endpoint`` + ``api_token``.
    verify_ssl: Whether aiohttp should verify TLS certificates.
        Honours the ``NAVIGATOR_SSL_VERIFY`` env var by default.

## Methods

- `async def execute(self, envelope: ToolExecutionEnvelope) -> 'ToolResult'`
- `async def close(self) -> None`
