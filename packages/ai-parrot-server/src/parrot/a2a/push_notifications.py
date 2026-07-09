# parrot/a2a/push_notifications.py
"""A2A Protocol v1.0.0 — Push Notification Configuration Store (FEAT-272 / TASK-1716).

Implements the in-memory `PushNotificationStore` used by `A2AServer` to back
the four push-notification management operations (Create/Get/List/Delete).

Scope (per spec §3 Module 4):
    - CRUD for `TaskPushNotificationConfig`, keyed by `(task_id, config_id)`.
    - Basic SSRF validation: reject private/loopback IP webhook URLs.

Explicitly out of scope (deferred to a follow-up feature):
    - Actual webhook delivery (HTTP POST to the registered URL on task events).
    - A Redis-backed persistent store (the in-memory dict here is per-process,
      consistent with `A2AServer._tasks` also being in-memory).
    - Advanced SSRF protections (DNS rebinding, redirect-following, etc.) —
      only obviously-private/loopback IP literals are rejected.
"""
from __future__ import annotations

import ipaddress
import uuid
from typing import Dict, List, Optional
from urllib.parse import urlparse

from parrot.a2a.models import TaskPushNotificationConfig


class PushNotificationStore:
    """In-memory store for push notification configurations.

    Pluggable: a Redis-backed (or other) store can implement the same
    `create`/`get`/`list_for_task`/`delete` async interface and be passed to
    `A2AServer(..., push_store=...)` as a drop-in replacement.
    """

    def __init__(self) -> None:
        # task_id -> {config_id -> config}
        self._configs: Dict[str, Dict[str, TaskPushNotificationConfig]] = {}

    async def create(
        self, config: TaskPushNotificationConfig
    ) -> TaskPushNotificationConfig:
        """Store a new push notification config, validating its webhook URL.

        Args:
            config: The config to store. If `config.id` is empty, a UUID is
                assigned.

        Returns:
            The stored config (with `id` populated).

        Raises:
            ValueError: If `config.url` fails SSRF validation.
        """
        self._validate_webhook_url(config.url)
        if not config.id:
            config.id = str(uuid.uuid4())
        task_configs = self._configs.setdefault(config.task_id, {})
        task_configs[config.id] = config
        return config

    async def get(
        self, task_id: str, config_id: str
    ) -> Optional[TaskPushNotificationConfig]:
        """Return the config for `(task_id, config_id)`, or `None`."""
        return self._configs.get(task_id, {}).get(config_id)

    async def list_for_task(
        self, task_id: str
    ) -> List[TaskPushNotificationConfig]:
        """Return all push notification configs registered for `task_id`."""
        return list(self._configs.get(task_id, {}).values())

    async def delete(self, task_id: str, config_id: str) -> bool:
        """Delete the config for `(task_id, config_id)`.

        Returns:
            `True` if a config was deleted, `False` if it did not exist.
        """
        task_configs = self._configs.get(task_id, {})
        return task_configs.pop(config_id, None) is not None

    def _validate_webhook_url(self, url: str) -> None:
        """Reject private/loopback IPs (basic SSRF protection).

        Args:
            url: The webhook URL to validate.

        Raises:
            ValueError: If the scheme is not http/https, or the hostname
                resolves to a literal private/loopback IP address.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http"):
            raise ValueError(f"Invalid scheme: {parsed.scheme}")
        hostname = parsed.hostname
        if hostname:
            try:
                ip = ipaddress.ip_address(hostname)
            except ValueError:
                # Not an IP literal (i.e. a DNS hostname) — allow. DNS-based
                # SSRF (rebinding, resolving to a private IP at request time)
                # is explicitly out of scope for this basic stub.
                ip = None
            if ip is not None and (ip.is_private or ip.is_loopback):
                raise ValueError(f"Private/loopback IP not allowed: {hostname}")
