"""WebhookSubscriber — HTTP POST lifecycle events to an external endpoint.

FEAT-176 — Lifecycle Events System.

``WebhookSubscriber`` is an ``EventProvider`` that serialises each lifecycle
event to JSON and POSTs it to a configured HTTPS endpoint.  Key features:

- **Optional HMAC-SHA256 signing**: include ``X-Parrot-Signature: sha256=<hex>``
  for endpoint verification.
- **Bounded retry**: up to ``max_attempts`` retries on 5xx / connection errors,
  with exponential backoff.  Permanent 4xx responses are logged and dropped.
- **Efficient session reuse**: one ``aiohttp.ClientSession`` per subscriber;
  call ``aclose()`` to release it at shutdown.
- **Selective subscription**: pass ``event_classes`` to restrict which event
  types trigger a POST (default: all ``LifecycleEvent`` subclasses).
"""

from __future__ import annotations

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

logger = logging.getLogger("parrot.lifecycle.webhook")


class WebhookSubscriber:
    """EventProvider that POSTs serialized lifecycle events to an HTTPS endpoint.

    Args:
        url: Destination endpoint URL.
        secret: Optional secret for HMAC-SHA256 signing.  When set, the
            ``X-Parrot-Signature: sha256=<hex>`` header is included.
        event_classes: Optional sequence of ``LifecycleEvent`` subclasses to
            subscribe to.  Defaults to ``[LifecycleEvent]`` (all events).
        max_attempts: Maximum number of POST attempts per event (default 3).
        timeout_seconds: Per-request timeout in seconds (default 5.0).
        forward_to_bus: Whether to forward to ``EventBus`` (default False).
    """

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

    # ------------------------------------------------------------------
    # EventProvider
    # ------------------------------------------------------------------

    def register(self, registry: "EventRegistry") -> None:
        """Register subscribers for each configured event class.

        Args:
            registry: The ``EventRegistry`` to subscribe to.
        """
        for ec in self._event_classes:
            registry.subscribe(ec, self._on_event, forward_to_bus=self._forward_to_bus)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the underlying ``aiohttp.ClientSession``.

        Call this at application shutdown to release the session's resources.
        Safe to call multiple times.
        """
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Lazily create or reuse the ``ClientSession``.

        Returns:
            An open ``aiohttp.ClientSession``.
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def _on_event(self, event: LifecycleEvent) -> None:
        """Async callback invoked for each dispatched lifecycle event.

        Serialises the event and delegates to ``_post_with_retry``.

        Args:
            event: The lifecycle event to POST.
        """
        body = json.dumps(event.to_dict()).encode()
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._secret:
            sig = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
            headers["X-Parrot-Signature"] = f"sha256={sig}"
        await self._post_with_retry(body, headers)

    async def _post_with_retry(self, body: bytes, headers: dict[str, str]) -> None:
        """POST *body* to the configured URL with exponential-backoff retry.

        Retries on 5xx responses and transient ``aiohttp.ClientError``.
        Gives up immediately on 4xx responses.

        Args:
            body: JSON-encoded event body.
            headers: HTTP headers to include in the request.
        """
        session = await self._ensure_session()
        delay = 0.5
        for attempt in range(1, self._max_attempts + 1):
            try:
                async with session.post(self._url, data=body, headers=headers) as resp:
                    if 200 <= resp.status < 300:
                        return
                    if 400 <= resp.status < 500:
                        logger.warning(
                            "Webhook %s returned %d — not retrying",
                            self._url,
                            resp.status,
                        )
                        return
                    logger.warning(
                        "Webhook %s returned %d (attempt %d/%d) — retrying",
                        self._url,
                        resp.status,
                        attempt,
                        self._max_attempts,
                    )
            except aiohttp.ClientError as exc:
                logger.warning(
                    "Webhook %s connection error (attempt %d/%d): %s",
                    self._url,
                    attempt,
                    self._max_attempts,
                    exc,
                )
            if attempt < self._max_attempts:
                await asyncio.sleep(delay)
                delay *= 2

        logger.error("Webhook %s exhausted %d retries", self._url, self._max_attempts)
