---
type: Wiki Overview
title: 'TASK-1192: Implement WebhookSubscriber'
id: doc:sdd-tasks-completed-task-1192-webhook-subscriber-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Module 11 of the spec. `WebhookSubscriber` POSTs serialized lifecycle events
  to a configured HTTPS endpoint, optionally signed with HMAC-SHA256. Use case: feeding
  events to SIEM, alerting, audit-trail, or third-party observability dashboards.
  Each subscriber instance reuses a sin'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.base
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.subscribers.webhook
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
---

# TASK-1192: Implement WebhookSubscriber

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-1184
**Assigned-to**: unassigned

---

## Context

Module 11 of the spec. `WebhookSubscriber` POSTs serialized lifecycle events to a configured HTTPS endpoint, optionally signed with HMAC-SHA256. Use case: feeding events to SIEM, alerting, audit-trail, or third-party observability dashboards. Each subscriber instance reuses a single `aiohttp.ClientSession` for efficiency.

Spec section: §3 Module 11.

**Parallel-safe** with TASK-1190 / 1191 / 1186 / 1187 / 1188 / 1189 (different file).

---

## Scope

- Implement `WebhookSubscriber` as an `EventProvider` accepting `url`, `secret` (optional, enables HMAC), and `events` (optional list of event class names — default: subscribe to all).
- POST serialized event (`event.to_dict()`) as JSON body.
- If `secret` is configured, include `X-Parrot-Signature: sha256=<hex>` header with HMAC-SHA256 of the request body.
- Implement bounded retry on transient HTTP failures (5xx, connection errors): up to 3 attempts with exponential backoff (e.g., 0.5s, 1s, 2s). Permanent failures (4xx) are logged and dropped.
- Reuse a single `aiohttp.ClientSession` per subscriber instance; expose `aclose()` for clean shutdown.
- Add unit tests using `aresponses` or a stub server to verify: HMAC signature, retry on 5xx, give-up on 4xx, JSON body matches `event.to_dict()`.

**NOT in scope**: YAML integration (TASK-1196), OTel mapping (TASK-1191).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/webhook.py` | CREATE | `WebhookSubscriber` provider. |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/__init__.py` | MODIFY | Re-export `WebhookSubscriber` alongside `LoggingSubscriber`. |
| `packages/ai-parrot/tests/unit/events/lifecycle/test_webhook_subscriber.py` | CREATE | HMAC + retry tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
import hashlib
import hmac
import json
import logging
from typing import TYPE_CHECKING, Optional, Sequence

import aiohttp   # already a core project dependency

from parrot.core.events.lifecycle.base import LifecycleEvent     # TASK-1183

if TYPE_CHECKING:
    from parrot.core.events.lifecycle.registry import EventRegistry
```

### Existing Signatures to Use

```python
# aiohttp.ClientSession — third-party, well-known.
# We instantiate one per subscriber and reuse it; close in aclose().
```

### Does NOT Exist

- ~~`httpx`~~ — NOT a project dependency; use `aiohttp` per CONTEXT.md ("Never use requests or httpx — use aiohttp").
- ~~Synchronous urllib3~~ — must be async throughout.
- ~~Global session~~ — each subscriber owns its session; that's the only way `aclose()` is meaningful.

---

## Implementation Notes

### Class skeleton

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/webhook.py
import asyncio
import hashlib
import hmac
import json
import logging
from typing import TYPE_CHECKING, Optional, Sequence

import aiohttp

from parrot.core.events.lifecycle.base import LifecycleEvent

if TYPE_CHECKING:
    from parrot.core.events.lifecycle.registry import EventRegistry


class WebhookSubscriber:
    """EventProvider that POSTs serialized lifecycle events to an HTTPS endpoint."""

    def __init__(
        self,
        *,
        url: str,
        secret: Optional[str] = None,
        event_classes: Optional[Sequence[type[LifecycleEvent]]] = None,
        max_attempts: int = 3,
        timeout_seconds: float = 5.0,
        forward_to_bus: bool = False,
    ) -> None:
        self._url = url
        self._secret = secret.encode() if secret else None
        self._event_classes = tuple(event_classes) if event_classes else (LifecycleEvent,)
        self._max_attempts = max_attempts
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._forward_to_bus = forward_to_bus
        self._session: Optional[aiohttp.ClientSession] = None
        self._logger = logging.getLogger("parrot.lifecycle.webhook")

    def register(self, registry: "EventRegistry") -> None:
        for ec in self._event_classes:
            registry.subscribe(ec, self._on_event, forward_to_bus=self._forward_to_bus)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def _on_event(self, event: LifecycleEvent) -> None:
        body = json.dumps(event.to_dict()).encode()
        headers = {"Content-Type": "application/json"}
        if self._secret:
            sig = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
            headers["X-Parrot-Signature"] = f"sha256={sig}"
        await self._post_with_retry(body, headers)

    async def _post_with_retry(self, body, headers) -> None:
        session = await self._ensure_session()
        delay = 0.5
        for attempt in range(1, self._max_attempts + 1):
            try:
                async with session.post(self._url, data=body, headers=headers) as resp:
                    if 200 <= resp.status < 300:
                        return
                    if 400 <= resp.status < 500:
                        self._logger.warning(
                            "Webhook %s returned %d — not retrying", self._url, resp.status,
                        )
                        return
                    self._logger.warning(
                        "Webhook %s returned %d — retrying", self._url, resp.status,
                    )
            except aiohttp.ClientError as exc:
                self._logger.warning("Webhook %s error: %s", self._url, exc)
            if attempt < self._max_attempts:
                await asyncio.sleep(delay)
                delay *= 2
        self._logger.error("Webhook %s exhausted retries", self._url)

    async def aclose(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
```

### Why subscribe directly to the configured event classes (not always `LifecycleEvent`)

The webhook is the kind of subscriber where users typically want to filter — they don't want their SIEM flooded by every `ClientStreamChunkEvent`. Defaulting to `LifecycleEvent` (everything) but letting them narrow via `event_classes=[AfterInvokeEvent, InvokeFailedEvent]` is the right ergonomic.

### Key Constraints

- async only.
- Reuse a single `ClientSession` per instance.
- HMAC is computed over the EXACT bytes sent on the wire (the json-encoded body).
- Retries are bounded; no infinite loops.
- Never raise inside the callback — the registry already isolates, but be defensive.

---

## Acceptance Criteria

- [ ] `WebhookSubscriber` defined; conforms to `EventProvider` Protocol.
- [ ] POST body equals `json.dumps(event.to_dict())` byte-for-byte.
- [ ] When `secret` is set, the `X-Parrot-Signature` header equals `sha256=<hmac>` of the body.
- [ ] On 5xx, retries up to `max_attempts` with exponential backoff.
- [ ] On 4xx, does NOT retry; logs a warning.
- [ ] `aclose()` closes the underlying `aiohttp.ClientSession`.
- [ ] Unit tests pass: `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_webhook_subscriber.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/webhook.py` is clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/events/lifecycle/test_webhook_subscriber.py
import asyncio
import hashlib
import hmac
import json
import pytest
from aiohttp import web

from parrot.core.events.lifecycle.registry import EventRegistry
from parrot.core.events.lifecycle.events import AfterInvokeEvent
from parrot.core.events.lifecycle.trace import TraceContext
from parrot.core.events.lifecycle.subscribers.webhook import WebhookSubscriber


@pytest.fixture
async def stub_server(aiohttp_server):
    """In-process aiohttp server that records every POST."""
    received: list[dict] = []

    async def handler(request):
        body = await request.read()
        received.append({
            "body": body,
            "signature": request.headers.get("X-Parrot-Signature"),
        })
        return web.Response(status=200)

    app = web.Application()
    app.router.add_post("/hook", handler)
    server = await aiohttp_server(app)
    yield server, received


class TestWebhookSubscriber:
    @pytest.mark.asyncio
    async def test_posts_event_body(self, stub_server):
        server, received = stub_server
        sub = WebhookSubscriber(url=str(server.make_url("/hook")))
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(sub)
        await reg.emit(AfterInvokeEvent(trace_context=TraceContext.new_root()))
        await sub.aclose()
        assert len(received) == 1
        payload = json.loads(received[0]["body"])
        assert payload["event_class"] == "AfterInvokeEvent"

    @pytest.mark.asyncio
    async def test_hmac_signature(self, stub_server):
        server, received = stub_server
        secret = "topsecret"
        sub = WebhookSubscriber(url=str(server.make_url("/hook")), secret=secret)
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(sub)
        await reg.emit(AfterInvokeEvent(trace_context=TraceContext.new_root()))
        await sub.aclose()
        body = received[0]["body"]
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert received[0]["signature"] == expected
```

(Retry/4xx tests can use `aresponses` or extend the stub server to return 500 then 200.)

---

## Agent Instructions

1. Read spec §3 Module 11.
2. Confirm TASK-1184 is in `sdd/tasks/completed/`.
3. Implement, run tests, update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-15
**Notes**: WebhookSubscriber implemented with HMAC, retry, aclose(). 8/8 tests pass using pytest-aiohttp stub server. Ruff clean.

**Deviations from spec**: none
