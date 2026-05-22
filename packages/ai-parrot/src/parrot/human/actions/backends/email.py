"""Email action backend using aiosmtplib.

FEAT-194 — TASK-1275
"""
from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import aiosmtplib

from .base import ActionBackend, EmailBackendError

if TYPE_CHECKING:
    from parrot.human.models import HumanInteraction, EscalationTier


class EmailBackend(ActionBackend):
    """Sends an escalation notification via SMTP using aiosmtplib.

    Configuration is provided at construction time to avoid module-level
    globals or environment reads inside ``execute``.

    Args:
        host: SMTP server hostname.
        port: SMTP server port (e.g. 25, 465, 587).
        username: SMTP auth username (may be ``None`` for open relays).
        password: SMTP auth password (may be ``None`` for open relays).
        default_from: The ``From:`` address used when ``action_metadata`` does
            not provide one.
        use_tls: Whether to use implicit TLS / SSL on connect (default ``False``).
            Passed as ``use_tls`` to aiosmtplib; typically used on port 465.
        use_ssl: Whether to use STARTTLS after connect (default ``False``).
            Mapped to ``start_tls`` in aiosmtplib; typically used on port 587.

    Example ``action_metadata`` consumed by this backend::

        {
            "kind": "email",
            "to": ["ops@example.com", "manager@example.com"],
            "subject_template": "HITL Escalation: {interaction.question[:60]}",
        }
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
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._default_from = default_from
        self._use_tls = use_tls
        self._use_ssl = use_ssl
        self.logger = logging.getLogger("parrot.human.actions.backends.email")

    async def execute(
        self,
        interaction: "HumanInteraction",
        tier: "EscalationTier",
    ) -> Dict[str, Any]:
        """Send an escalation email and return a confirmation dict.

        Args:
            interaction: The human interaction being escalated.
            tier: The escalation tier (reads ``action_metadata`` for ``to``,
                ``subject_template``).

        Returns:
            Dict with ``message`` (sent to LLM), ``to``, and ``status``.

        Raises:
            EmailBackendError: On SMTP failure or empty recipient list.
        """
        meta = tier.action_metadata
        to: List[str] = meta.get("to") or []
        if not to:
            raise EmailBackendError(
                "EmailBackend: 'to' list is empty in action_metadata. "
                "Provide at least one recipient email address."
            )

        # Validate recipient format (basic check)
        for addr in to:
            if "@" not in addr:
                raise EmailBackendError(
                    f"EmailBackend: invalid email address {addr!r} in 'to' list."
                )

        subject_template = meta.get(
            "subject_template",
            "HITL Escalation: {question}",
        )
        question_snippet = (interaction.question or "")[:80]
        try:
            subject = subject_template.format(
                interaction=interaction,
                tier=tier,
                question=question_snippet,
            )
        except (KeyError, AttributeError):
            subject = f"HITL Escalation: {question_snippet}"

        body_lines = [
            f"Interaction ID: {interaction.interaction_id}",
            f"Question: {interaction.question}",
        ]
        if interaction.context:
            body_lines.append(f"Context: {interaction.context}")
        severity = getattr(interaction, "severity", None)
        if severity is not None:
            body_lines.append(f"Severity: {severity}")
        body = "\n".join(body_lines)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._default_from
        msg["To"] = ", ".join(to)
        msg.attach(MIMEText(body, "plain"))

        try:
            kwargs: Dict[str, Any] = {
                "hostname": self._host,
                "port": self._port,
                "use_tls": self._use_ssl,
                "start_tls": self._use_tls,
            }
            if self._username and self._password:
                kwargs["username"] = self._username
                kwargs["password"] = self._password

            await aiosmtplib.send(msg, **kwargs)

        except aiosmtplib.SMTPException as exc:
            # Do NOT log the password — only the exception message
            self.logger.warning(
                "EmailBackend SMTP send failed for interaction %s: %s",
                interaction.interaction_id,
                str(exc),
            )
            raise EmailBackendError(
                f"EmailBackend: SMTP send failed: {exc}"
            ) from exc
        except OSError as exc:
            raise EmailBackendError(
                f"EmailBackend: network error connecting to {self._host}:{self._port}: {exc}"
            ) from exc

        self.logger.info(
            "EmailBackend: sent escalation email for interaction %s to %s",
            interaction.interaction_id,
            to,
        )
        return {
            "message": (
                f"[escalated:email] Notified {', '.join(to)}."
            ),
            "to": to,
            "status": "sent",
        }
