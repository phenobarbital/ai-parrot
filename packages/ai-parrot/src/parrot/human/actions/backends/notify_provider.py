"""async-notify-backed escalation notification backend.

This backend replaces the legacy ``aiosmtplib``-only :class:`EmailBackend`
with a provider-agnostic sender built on **async-notify**. The delivery
channel becomes a single ``provider`` attribute on the tier's
``action_metadata`` — switching email → SES → Twilio SMS → Telegram → Teams
is a configuration change, not new code.

Selected by :class:`~parrot.human.actions.notify.NotifyAction` for
``action_metadata["kind"] in {"notify", "email"}``.

``action_metadata`` consumed by this backend::

    {
        "kind": "notify",                # or legacy "email"
        "provider": "email",             # email | ses | telegram | teams | sms/twilio | slack
        "to": ["ops@example.com", "manager@example.com"],
        "cc": ["audit@example.com"],     # optional
        "cc_originator": true,            # append interaction.originator to CC
        "subject_template": "HITL Escalation: {question}",
        "body_template": "...{question}...",   # optional; a sensible default is built
        "provider_options": {"hostname": "smtp...", "port": 587},  # per-call creds
    }
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .base import ActionBackend, NotifyBackendError

if TYPE_CHECKING:
    from parrot.human.models import HumanInteraction, EscalationTier


# Providers that address recipients by chat id rather than email address.
_CHAT_PROVIDERS = {"telegram"}
_CHANNEL_PROVIDERS = {"slack"}
# Providers where a recipient list is required to deliver anything.
_RECIPIENT_REQUIRED = {"email", "ses", "smtp", "teams", "telegram", "slack", "sms", "twilio"}
# Providers that use email-format addresses (require "@") — others use phone numbers or IDs.
_EMAIL_PROVIDERS = {"email", "ses", "smtp"}


class NotifyBackend(ActionBackend):
    """Sends an escalation notification through any async-notify provider.

    The provider is chosen at call time from ``action_metadata["provider"]``
    (falling back to ``default_provider``), so a single backend instance can
    deliver email, SES, SMS, Telegram, Teams, etc.

    Args:
        default_provider: Provider used when the tier does not set one
            (default ``"email"`` — preserves legacy ``kind:"email"`` behaviour).
        default_from: Default ``From``/sender used by providers that support it.
        provider_options: Connection-level kwargs forwarded to the async-notify
            provider constructor (e.g. SMTP ``hostname``/``port``/``username``/
            ``password`` for email, ``bot_token`` for Telegram). Merged with —
            and overridden by — the per-tier ``action_metadata["provider_options"]``.
    """

    def __init__(
        self,
        *,
        default_provider: str = "email",
        default_from: Optional[str] = None,
        provider_options: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._default_provider = (default_provider or "email").lower()
        self._default_from = default_from
        self._provider_options: Dict[str, Any] = provider_options or {}
        self.logger = logging.getLogger("parrot.human.actions.backends.notify")

    # ── recipient building ────────────────────────────────────────────────

    @staticmethod
    def build_recipients(provider: str, addresses: List[str]) -> List[Any]:
        """Wrap raw address strings into async-notify recipient models."""
        from notify.models import Actor, Chat, Channel

        recipients: List[Any] = []
        for addr in addresses:
            if provider in _CHAT_PROVIDERS:
                recipients.append(Chat(chat_id=str(addr)))
            elif provider in _CHANNEL_PROVIDERS:
                recipients.append(Channel(channel_id=str(addr)))
            else:
                # email / ses / teams / sms — address by Actor account.
                name = addr.split("@")[0] if "@" in str(addr) else str(addr)
                recipients.append(Actor(name=name, account={"address": addr}))
        return recipients

    @staticmethod
    def _render_subject(
        meta: Dict[str, Any], interaction: "HumanInteraction", tier: "EscalationTier"
    ) -> str:
        question_snippet = (interaction.question or "")[:80]
        template = meta.get("subject_template", "HITL Escalation: {question}")
        try:
            return template.format(
                interaction=interaction, tier=tier, question=question_snippet
            )
        except (KeyError, AttributeError, IndexError):
            return f"HITL Escalation: {question_snippet}"

    @staticmethod
    def _render_body(
        meta: Dict[str, Any], interaction: "HumanInteraction", tier: "EscalationTier"
    ) -> str:
        template = meta.get("body_template")
        if template:
            try:
                return template.format(
                    interaction=interaction, tier=tier, question=interaction.question
                )
            except (KeyError, AttributeError, IndexError) as exc:
                logger = logging.getLogger("parrot.human.actions.backends.notify")
                logger.warning(
                    "NotifyBackend: body_template rendering failed: %s; using default body.",
                    exc,
                )
        body_lines = [
            f"Interaction ID: {interaction.interaction_id}",
            f"Question: {interaction.question}",
        ]
        if interaction.context:
            body_lines.append(f"Context: {interaction.context}")
        severity = getattr(interaction, "severity", None)
        if severity is not None:
            body_lines.append(f"Severity: {severity}")
        return "\n".join(body_lines)

    # ── recipient resolution ──────────────────────────────────────────────

    def _resolve_recipients(
        self, meta: Dict[str, Any], interaction: "HumanInteraction", provider: str
    ) -> tuple[List[str], List[str]]:
        """Return ``(to, cc)`` address lists, applying ``cc_originator``."""
        to: List[str] = list(meta.get("to") or [])
        cc: List[str] = list(meta.get("cc") or [])

        if meta.get("cc_originator") and interaction.originator:
            origin = interaction.originator
            if origin not in to and origin not in cc:
                # For email-based providers, only append the originator if it
                # looks like an email address. Non-email identifiers (session IDs,
                # Telegram chat IDs) are silently skipped to avoid '@' validation
                # failures when the NOTIFY tier uses an email provider.
                if provider not in _EMAIL_PROVIDERS or "@" in str(origin):
                    cc.append(origin)

        if provider in _RECIPIENT_REQUIRED and not to:
            raise NotifyBackendError(
                f"NotifyBackend: 'to' list is empty for provider {provider!r}. "
                "Provide at least one recipient in action_metadata['to']."
            )

        # For email-based providers, validate that all addresses contain "@".
        # SMS/Twilio use phone numbers; Telegram/Slack use IDs — no "@" needed.
        if provider in _EMAIL_PROVIDERS:
            for addr in to + cc:
                if "@" not in str(addr):
                    raise NotifyBackendError(
                        f"NotifyBackend: invalid address {addr!r} for provider "
                        f"{provider!r} (expected an email address)."
                    )
        return to, cc

    async def execute(
        self,
        interaction: "HumanInteraction",
        tier: "EscalationTier",
    ) -> Dict[str, Any]:
        """Deliver the escalation notification via the configured provider.

        Args:
            interaction: The human interaction being escalated.
            tier: The escalation tier providing ``action_metadata``.

        Returns:
            Dict with ``message`` (surfaced to the LLM), ``provider``, ``to``,
            ``cc`` and ``status``.

        Raises:
            NotifyBackendError: On delivery failure or invalid configuration,
                so ``_escalate_to_next_tier`` can advance the chain.
        """
        meta = tier.action_metadata or {}
        # "provider" wins; fall back to legacy "channel"; then the instance default.
        provider = str(
            meta.get("provider") or meta.get("channel") or self._default_provider
        ).lower()

        to, cc = self._resolve_recipients(meta, interaction, provider)

        subject = self._render_subject(meta, interaction, tier)
        body = self._render_body(meta, interaction, tier)

        opts: Dict[str, Any] = {**self._provider_options, **(meta.get("provider_options") or {})}

        try:
            from notify import Notify
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise NotifyBackendError(
                "NotifyBackend requires async-notify. Install it with "
                "'pip install async-notify[all]'."
            ) from exc

        recipients = self.build_recipients(provider, to)
        cc_recipients = self.build_recipients(provider, cc) if cc else None

        send_kwargs: Dict[str, Any] = {"message": body}
        if subject:
            send_kwargs["subject"] = subject
        if cc_recipients:
            # Forwarded to the provider; honoured by providers that support CC
            # (e.g. email/ses). Harmless for providers that ignore it.
            send_kwargs["cc"] = cc_recipients
        if self._default_from:
            send_kwargs.setdefault("sender", self._default_from)

        try:
            sender = Notify(provider, **opts)
            async with sender as conn:
                await conn.send(recipient=recipients, **send_kwargs)
        except NotifyBackendError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise provider errors
            # Do NOT log credentials — only the exception message.
            self.logger.warning(
                "NotifyBackend send failed for interaction %s via %s: %s",
                interaction.interaction_id,
                provider,
                str(exc),
            )
            raise NotifyBackendError(
                f"NotifyBackend: send via {provider!r} failed: {exc}"
            ) from exc

        all_targets = to + cc
        self.logger.info(
            "NotifyBackend: sent escalation via %s for interaction %s to %s",
            provider,
            interaction.interaction_id,
            all_targets,
        )
        cc_note = f" (cc: {', '.join(cc)})" if cc else ""
        return {
            "message": f"[escalated:{provider}] Notified {', '.join(to) or '—'}.{cc_note}",
            "provider": provider,
            "to": to,
            "cc": cc,
            "status": "sent",
        }


# Module-level alias so callers outside the class (e.g. manager._send_async_notify)
# can import a stable public name without depending on a private static method.
build_recipients = NotifyBackend.build_recipients
