# parrot/a2a/push_notifications.py
"""Push notification configuration store for the A2A v1.0 server (FEAT-272).

Implements the storage/CRUD side of the four A2A v1.0 push-notification config
operations (Create/Get/List/Delete). Actual webhook *delivery* (HTTP POST to
client URLs) is intentionally out of scope — this store only manages the
configuration objects. A basic SSRF guard rejects obviously private/loopback
webhook targets.
"""
from typing import Dict, List, Optional
import ipaddress
import uuid
from urllib.parse import urlparse

from navconfig.logging import logging

from parrot.a2a.models import TaskPushNotificationConfig


class PushNotificationStore:
    """In-memory store for :class:`TaskPushNotificationConfig` objects.

    The backend is a per-process ``dict`` keyed by ``task_id`` then ``config_id``.
    This mirrors the server's in-memory task store; a Redis-backed
    implementation with the same async interface is a follow-up.
    """

    def __init__(self) -> None:
        # task_id -> {config_id -> config}
        self._configs: Dict[str, Dict[str, TaskPushNotificationConfig]] = {}
        self.logger = logging.getLogger("A2A.PushNotificationStore")

    async def create(
        self, config: TaskPushNotificationConfig
    ) -> TaskPushNotificationConfig:
        """Store a push-notification config, assigning an id when absent."""
        try:
            self._validate_webhook_url(config.url)
        except ValueError as exc:
            self.logger.warning(
                "Rejected push-notification webhook for task %s: %s",
                config.task_id, exc,
            )
            raise
        if not config.id:
            config.id = str(uuid.uuid4())
        task_configs = self._configs.setdefault(config.task_id, {})
        task_configs[config.id] = config
        return config

    async def get(
        self, task_id: str, config_id: str
    ) -> Optional[TaskPushNotificationConfig]:
        """Return the config for ``(task_id, config_id)`` or ``None``."""
        return self._configs.get(task_id, {}).get(config_id)

    async def list_for_task(
        self, task_id: str
    ) -> List[TaskPushNotificationConfig]:
        """Return all configs registered for ``task_id``."""
        return list(self._configs.get(task_id, {}).values())

    async def delete(self, task_id: str, config_id: str) -> bool:
        """Remove a config; return ``True`` if one was removed."""
        task_configs = self._configs.get(task_id, {})
        return task_configs.pop(config_id, None) is not None

    def _validate_webhook_url(self, url: str) -> None:
        """Reject private/loopback IPs (basic SSRF protection).

        DNS-rebinding and other advanced attacks are out of scope; hostnames
        that are not literal IPs are allowed.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http"):
            raise ValueError(f"Invalid scheme: {parsed.scheme}")
        hostname = parsed.hostname
        if not hostname:
            raise ValueError("Webhook URL has no host")

        # Block the `localhost` name outright (it isn't an IP literal, so the
        # IP checks below would otherwise let it through).
        host_l = hostname.lower()
        if host_l == "localhost" or host_l.endswith(".localhost"):
            raise ValueError(f"Loopback host not allowed: {hostname}")

        ip = self._coerce_ip(hostname)
        if ip is None:
            return  # a real hostname — allowed (DNS rebinding is out of scope)

        # Reject every non-globally-routable class: loopback (127.0.0.0/8, ::1),
        # private (RFC1918, fc00::/7), link-local (169.254/16 incl. the cloud
        # metadata endpoint 169.254.169.254, fe80::/10), unspecified (0.0.0.0, ::),
        # reserved, and multicast.
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_unspecified
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise ValueError(f"Private/loopback IP not allowed: {hostname}")

    @staticmethod
    def _coerce_ip(hostname: str):
        """Return an ``ip_address`` for a literal or numeric-encoded host, else None.

        Covers the dotted/colon literals AND the integer forms many resolvers
        accept (decimal ``2130706433`` and hex ``0x7f000001`` both == 127.0.0.1),
        which would otherwise slip past a naive ``ip_address()`` parse.
        """
        try:
            return ipaddress.ip_address(hostname)
        except ValueError:
            pass
        try:
            if hostname.isdigit():
                return ipaddress.ip_address(int(hostname))
            if hostname.lower().startswith("0x"):
                return ipaddress.ip_address(int(hostname, 16))
        except ValueError:
            pass
        return None
