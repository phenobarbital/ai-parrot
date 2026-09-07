"""Getting an issued coupon into the guest's hands.

Delivery is the one step of the coupon path that touches a person directly, so
two properties are load-bearing:

**The contact handle is resolved here, not carried here.** The flow's
``ContactCapture`` deliberately publishes only a *fingerprint* of the guest's
e-mail or phone, because flow results are persisted as execution rows and a
guest's address does not belong in an audit log. This service therefore reads
the handle from the guest repository at send time, uses it, and never puts it
back into flow state or a log line.

**A failed send is not a failed run.** By the time delivery runs the public
reply is out and the coupon exists in the database. Raising here would mark the
review failed and invite a retry that re-publishes the reply and re-issues the
coupon — far more damage than an undelivered e-mail. Every failure comes back
as a receipt with a reason, and the coupon stays ``issued`` with an event
explaining why, which is enough for someone to resend it.

Transport is `async-notify <https://github.com/phenobarbital/async-notify>`_,
reached through the same ``build_recipients`` helper the HITL notification
backend uses — that helper is exported at module level precisely so callers
outside the escalation machinery can address recipients the same way.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from navconfig.logging import logging

from .models import Coupon, CouponOffer, DiscountType

logger = logging.getLogger("parrot_saas.coupons.delivery")

#: Flow contact channel -> async-notify provider.
#:
#: WhatsApp is absent on purpose. async-notify has no WhatsApp provider in this
#: deployment, and the repository's three WhatsApp integrations are inbound
#: conversation bridges rather than outbound senders — see
#: ``sdd/proposals/saas-whatsapp-community-manager.brainstorm.md``. Mapping it
#: to SMS "because the field is a phone number" would send a message the guest
#: never agreed to receive over that channel.
CHANNEL_PROVIDERS: Mapping[str, str] = {
    "email": "email",
    "sms": "sms",
}

#: Rendered when a tenant has written no template of its own.
DEFAULT_SUBJECT = "A little something from {business}"
DEFAULT_BODY = """\
Hello{name},

Thank you again for your feedback. Here is {offer} from {business}:

    {code}

Valid until {expires}. {terms}

See you soon,
{business}\
"""


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """What happened when the coupon was sent.

    Attributes:
        delivered: Whether the message actually left.
        provider: The async-notify provider used, empty when none was.
        reason: Why it did not go, empty on success. Machine-readable enough
            to route on and specific enough to act on.
    """

    delivered: bool = False
    provider: str = ""
    reason: str = ""


class CouponDelivery:
    """Sends an issued coupon over the guest's consented channel.

    Args:
        guest_repository: Where the contact handle is read from at send time.
        coupon_repository: Used to look the coupon up by code, mark it
            delivered and append to its trail. Optional: without it the
            message still goes out, it is simply not recorded.
        provider_options: Connection-level kwargs for async-notify (SMTP host
            and credentials, Twilio tokens). Never logged.
        sender_factory: Override for ``notify.Notify``, so a test can drive
            this without a provider. Called as
            ``sender_factory(provider, **options)`` and used as an async
            context manager whose ``send`` is awaited.
        default_from: Sender address for providers that support one.
    """

    def __init__(
        self,
        *,
        guest_repository: Any,
        coupon_repository: Optional[Any] = None,
        provider_options: Optional[dict] = None,
        sender_factory: Optional[Any] = None,
        default_from: str = "",
    ) -> None:
        self._guests = guest_repository
        self._coupons = coupon_repository
        self._options = provider_options or {}
        self._sender_factory = sender_factory
        self._default_from = default_from

    async def send(
        self, tenant_id: str, contact: Any, issued: Any, *, business: str = ""
    ) -> DeliveryReceipt:
        """Deliver one coupon.

        Args:
            tenant_id: Owning tenant.
            contact: The flow's ``ContactCapture`` — consulted for the channel
                and the guest id, never for a handle.
            issued: The flow's ``CouponIssued``, carrying the coupon code.
            business: Display name used in the message.

        Returns:
            A receipt. Never raises: see the module docstring for why a failed
            send must not fail the run.
        """
        code = getattr(issued, "coupon_code", "") or ""
        if not code:
            return DeliveryReceipt(reason="no_coupon")

        channel = str(
            getattr(getattr(contact, "channel", ""), "value", None)
            or getattr(contact, "channel", "")
        )
        provider = CHANNEL_PROVIDERS.get(channel, "")
        if not provider:
            logger.info(
                "tenant %s cannot deliver over channel %r; the coupon stays "
                "issued and can be sent by hand",
                tenant_id,
                channel or "none",
            )
            return DeliveryReceipt(reason=f"unsupported_channel:{channel or 'none'}")

        guest_id = getattr(contact, "guest_id", "") or ""
        handle = await self._handle(tenant_id, guest_id, channel)
        if not handle:
            return DeliveryReceipt(reason="no_contact_handle")

        coupon, offer = await self._coupon_and_offer(tenant_id, code)
        subject, body = self._render(
            business or tenant_id, coupon, offer, code, handle_name=""
        )

        try:
            await self._dispatch(provider, handle, subject, body)
        except Exception as exc:  # noqa: BLE001 - reported, never raised on
            # The message, not the exception object: a provider's repr can
            # carry the connection options, and those are credentials.
            logger.warning(
                "delivering coupon %s for tenant %s over %s failed: %s",
                code,
                tenant_id,
                provider,
                exc,
            )
            await self._record(tenant_id, coupon, "delivery_failed", str(exc))
            return DeliveryReceipt(
                provider=provider, reason=f"send_failed:{type(exc).__name__}"
            )

        await self._mark_delivered(tenant_id, coupon, provider)
        logger.info(
            "tenant %s delivered coupon %s over %s", tenant_id, code, provider
        )
        return DeliveryReceipt(delivered=True, provider=provider)

    async def _handle(
        self, tenant_id: str, guest_id: str, channel: str
    ) -> str:
        """Read the guest's address for one channel.

        Consent is re-checked here even though the flow already checked it.
        The two reads are seconds apart, but a guest who withdrew consent in
        between must not receive the message, and this is the last point at
        which that is still true.
        """
        if self._guests is None or not guest_id:
            return ""
        try:
            guest = await self._guests.get(tenant_id, guest_id)
        except Exception as exc:  # noqa: BLE001 - no handle is a clean refusal
            logger.warning(
                "could not resolve guest %s for delivery: %s", guest_id, exc
            )
            return ""
        if guest is None or not guest.consent_marketing:
            return ""
        return (guest.email if channel == "email" else guest.phone) or ""

    async def _coupon_and_offer(
        self, tenant_id: str, code: str
    ) -> tuple[Optional[Coupon], Optional[CouponOffer]]:
        """Load the coupon and the offer behind it, tolerating neither."""
        if self._coupons is None:
            return None, None
        try:
            coupon = await self._coupons.get_coupon_by_code(tenant_id, code)
            offer = (
                await self._coupons.get_offer(tenant_id, coupon.offer_id)
                if coupon is not None
                else None
            )
            return coupon, offer
        except Exception as exc:  # noqa: BLE001 - the code alone still sends
            logger.warning("could not load coupon %s: %s", code, exc)
            return None, None

    def _render(
        self,
        business: str,
        coupon: Optional[Coupon],
        offer: Optional[CouponOffer],
        code: str,
        *,
        handle_name: str,
    ) -> tuple[str, str]:
        """Build the subject and body of the message.

        Args:
            business: Tenant display name.
            coupon: The stored coupon, when it could be read.
            offer: The offer behind it, when it could be read.
            code: The redeemable code — the one thing that is always known.
            handle_name: How to address the guest, blank for "no name".

        Returns:
            ``(subject, body)``.
        """
        expires = getattr(coupon, "expires_at", None)
        return (
            DEFAULT_SUBJECT.format(business=business),
            DEFAULT_BODY.format(
                name=f" {handle_name}" if handle_name else "",
                business=business,
                offer=_describe(offer),
                code=code,
                expires=expires.date().isoformat() if expires else "further notice",
                terms=getattr(offer, "terms", "") or "",
            ).strip(),
        )

    async def _dispatch(
        self, provider: str, handle: str, subject: str, body: str
    ) -> None:
        """Hand the message to async-notify."""
        from parrot.human.actions.backends.notify_provider import build_recipients

        factory = self._sender_factory
        if factory is None:
            from notify import Notify

            factory = Notify

        kwargs: dict[str, Any] = {"message": body, "subject": subject}
        if self._default_from:
            kwargs["sender"] = self._default_from

        sender = factory(provider, **self._options)
        async with sender as conn:
            await conn.send(
                recipient=build_recipients(provider, [handle]), **kwargs
            )

    async def _mark_delivered(
        self, tenant_id: str, coupon: Optional[Coupon], provider: str
    ) -> None:
        """Move the coupon to ``delivered`` and note how it went out."""
        if self._coupons is None or coupon is None:
            return
        try:
            await self._coupons.mark_delivered(tenant_id, coupon.coupon_id)
        except Exception as exc:  # noqa: BLE001 - the guest already has it
            logger.warning(
                "coupon %s was delivered but could not be marked so: %s",
                coupon.code,
                exc,
            )
        await self._record(tenant_id, coupon, "delivered", "", provider=provider)

    async def _record(
        self,
        tenant_id: str,
        coupon: Optional[Coupon],
        event: str,
        reason: str,
        *,
        provider: str = "",
    ) -> None:
        """Append to the coupon's trail, never raising.

        The detail carries the provider and the reason — **never the handle**.
        A guest's address in an event row would put it back in the database
        the fingerprinting was meant to keep it out of.
        """
        if self._coupons is None or coupon is None:
            return
        detail = {"provider": provider} if provider else {}
        if reason:
            detail["reason"] = reason
        try:
            await self._coupons.record_event(
                tenant_id, coupon.coupon_id, event, detail=detail, actor="flow"
            )
        except Exception as exc:  # noqa: BLE001 - bookkeeping, not the outcome
            logger.debug("could not record %s for %s: %s", event, coupon.code, exc)


def _describe(offer: Optional[CouponOffer]) -> str:
    """Render an offer in words a guest reads, not a database's terms."""
    if offer is None:
        return "your coupon"
    if offer.name:
        return offer.name
    discount_type = getattr(offer.discount_type, "value", offer.discount_type)
    value = offer.discount_value
    if discount_type == DiscountType.PERCENT.value:
        return f"{value:g}% off your next visit"
    if discount_type == DiscountType.AMOUNT.value:
        return f"{value:g} {offer.currency} off your next visit"
    return "your coupon"


__all__ = ("CHANNEL_PROVIDERS", "CouponDelivery", "DeliveryReceipt")
