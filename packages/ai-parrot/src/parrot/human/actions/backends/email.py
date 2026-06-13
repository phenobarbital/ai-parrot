"""Email action backend — async-notify backed (back-compat shim).

Historically this backend talked to ``aiosmtplib`` directly. It now delegates
to :class:`~parrot.human.actions.backends.notify_provider.NotifyBackend`, which
sends through **async-notify**, so the delivery channel is a configuration
attribute (``provider``) rather than hard-wired SMTP.

The constructor keeps its original SMTP-flavoured signature so existing
callers (e.g. ``NotifyAction(email_cfg=...)``) keep working: the SMTP kwargs
are translated into async-notify email provider options.
"""
from __future__ import annotations

from typing import Optional

from .notify_provider import NotifyBackend


class EmailBackend(NotifyBackend):
    """Send an escalation email via async-notify's email provider.

    Backwards-compatible wrapper over :class:`NotifyBackend` with
    ``default_provider="email"``. The SMTP-style arguments are mapped onto the
    async-notify email provider's connection options.

    Args:
        host: SMTP server hostname (mapped to async-notify ``hostname``).
        port: SMTP server port.
        username: SMTP auth username (optional).
        password: SMTP auth password (optional).
        default_from: Default ``From`` address.
        use_tls: STARTTLS after connect (port 587 style).
        use_ssl: Implicit TLS on connect (port 465 style).
    """

    def __init__(
        self,
        *,
        host: str = "localhost",
        port: int = 25,
        username: Optional[str] = None,
        password: Optional[str] = None,
        default_from: str = "parrot-hitl@parrot.local",
        use_tls: bool = False,
        use_ssl: bool = False,
    ) -> None:
        provider_options = {
            "hostname": host,
            "port": port,
            "username": username,
            "password": password,
            "use_tls": use_tls,
            "use_ssl": use_ssl,
        }
        super().__init__(
            default_provider="email",
            default_from=default_from,
            provider_options=provider_options,
        )
