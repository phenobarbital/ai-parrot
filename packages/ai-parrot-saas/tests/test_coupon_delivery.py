"""The coupon delivery service, with a fake async-notify sender.

Three things are being protected here, in order of how much damage getting
them wrong does:

1. **A guest's contact handle stays out of everything that persists it.** The
   flow deliberately carries only a fingerprint; the service reads the real
   address, uses it, and must not put it into a log line, an event row or its
   own return value.
2. **Consent is re-checked at send time.** The flow checked it seconds earlier,
   but this is the last moment at which a withdrawal can still stop the
   message.
3. **A failed send never raises.** By this point the reply is published and the
   coupon is minted; an exception here would fail an answered review.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from parrot_saas.coupons.delivery import CHANNEL_PROVIDERS, CouponDelivery
from parrot_saas.coupons.models import Coupon, CouponOffer, DiscountType
from parrot_saas.flows.community_manager.models import (
    ContactCapture,
    ContactChannel,
    CouponIssued,
)

EMAIL = "guest@example.com"
PHONE = "+34600111222"


class _Guest:
    def __init__(self, **kw):
        self.email = kw.get("email", "")
        self.phone = kw.get("phone", "")
        self.consent_marketing = kw.get("consent_marketing", True)
        self.display_name = kw.get("display_name", "")


class _Guests:
    def __init__(self, guest=None, *, fail=None):
        self.guest = guest
        self.fail = fail

    async def get(self, tenant_id, guest_id):
        if self.fail is not None:
            raise self.fail
        return self.guest


class _Coupons:
    """Stand-in for the parts of ``CouponRepository`` delivery touches."""

    def __init__(self, coupon=None, offer=None, *, fail_mark=None):
        self.coupon = coupon
        self.offer = offer
        self.fail_mark = fail_mark
        self.delivered: list = []
        self.events: list = []

    async def get_coupon_by_code(self, tenant_id, code):
        return self.coupon

    async def get_offer(self, tenant_id, offer_id):
        return self.offer

    async def mark_delivered(self, tenant_id, coupon_id):
        if self.fail_mark is not None:
            raise self.fail_mark
        self.delivered.append(coupon_id)
        return self.coupon

    async def record_event(self, tenant_id, coupon_id, event, *, detail=None, actor=""):
        self.events.append((event, detail or {}, actor))


class _Sender:
    """Fake ``notify.Notify``: an async context manager with ``send``."""

    def __init__(self, provider, **options):
        self.provider = provider
        self.options = options
        _Sender.last = self
        self.sent: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, recipient=None, **kwargs):
        self.sent.append({"recipient": recipient, **kwargs})


class _FailingSender(_Sender):
    async def send(self, recipient=None, **kwargs):
        raise ConnectionRefusedError("smtp unreachable")


def _coupon(**kw) -> Coupon:
    payload = {
        "coupon_id": "33333333-3333-3333-3333-333333333333",
        "tenant_id": "bar-pepe",
        "offer_id": "44444444-4444-4444-4444-444444444444",
        "code": "RECOVER20-7KQF9M",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
    }
    payload.update(kw)
    return Coupon(**payload)


def _offer(**kw) -> CouponOffer:
    payload = {
        "offer_id": "44444444-4444-4444-4444-444444444444",
        "tenant_id": "bar-pepe",
        "code": "RECOVER20",
        "name": "20% off your next visit",
        "terms": "One per guest.",
    }
    payload.update(kw)
    return CouponOffer(**payload)


def _contact(channel=ContactChannel.EMAIL) -> ContactCapture:
    return ContactCapture(
        contact_available=True,
        channel=channel,
        guest_id="22222222-2222-2222-2222-222222222222",
        handle_fingerprint="fp",
    )


def _issued() -> CouponIssued:
    return CouponIssued(
        issued=True, coupon_code="RECOVER20-7KQF9M", offer_code="RECOVER20"
    )


def _service(**kw) -> CouponDelivery:
    kw.setdefault("guest_repository", _Guests(_Guest(email=EMAIL)))
    kw.setdefault("coupon_repository", _Coupons(_coupon(), _offer()))
    kw.setdefault("sender_factory", _Sender)
    return CouponDelivery(**kw)


@pytest.mark.asyncio
async def test_a_coupon_reaches_the_guest_and_is_recorded():
    """The happy path, all the way to the trail."""
    coupons = _Coupons(_coupon(), _offer())
    service = _service(coupon_repository=coupons)

    receipt = await service.send(
        "bar-pepe", _contact(), _issued(), business="Bar Pepe"
    )

    assert receipt.delivered is True
    assert receipt.provider == "email"
    sent = _Sender.last.sent[0]
    assert "RECOVER20-7KQF9M" in sent["message"]
    assert "20% off your next visit" in sent["message"]
    assert "Bar Pepe" in sent["subject"]
    assert coupons.delivered == ["33333333-3333-3333-3333-333333333333"]
    assert coupons.events[0][0] == "delivered"
    assert coupons.events[0][1]["provider"] == "email"


@pytest.mark.asyncio
async def test_the_message_goes_to_the_address_read_at_send_time():
    """The handle comes from the repository, never from the flow."""
    service = _service()

    await service.send("bar-pepe", _contact(), _issued())

    recipients = _Sender.last.sent[0]["recipient"]
    assert [r.account.address for r in recipients] == [EMAIL]


@pytest.mark.asyncio
async def test_sms_addresses_the_phone_number():
    """The channel picks both the provider and which handle is used."""
    service = _service(guest_repository=_Guests(_Guest(phone=PHONE)))

    receipt = await service.send(
        "bar-pepe", _contact(ContactChannel.SMS), _issued()
    )

    assert receipt.provider == "sms"
    recipients = _Sender.last.sent[0]["recipient"]
    assert [r.account.address for r in recipients] == [PHONE]


@pytest.mark.asyncio
async def test_consent_withdrawn_between_the_flow_and_the_send_stops_it():
    """This is the last point at which a withdrawal can still be honoured."""
    service = _service(
        guest_repository=_Guests(_Guest(email=EMAIL, consent_marketing=False))
    )

    receipt = await service.send("bar-pepe", _contact(), _issued())

    assert receipt.delivered is False
    assert receipt.reason == "no_contact_handle"


@pytest.mark.asyncio
async def test_whatsapp_is_refused_rather_than_downgraded_to_sms():
    """A guest who consented to one channel did not consent to another.

    There is no async-notify WhatsApp provider here, and quietly sending the
    coupon by SMS "because the handle is a phone number" would deliver over a
    channel the guest never agreed to.
    """
    assert "whatsapp" not in CHANNEL_PROVIDERS
    service = _service()

    receipt = await service.send(
        "bar-pepe", _contact(ContactChannel.WHATSAPP), _issued()
    )

    assert receipt.delivered is False
    assert receipt.reason == "unsupported_channel:whatsapp"


@pytest.mark.asyncio
async def test_a_failed_send_is_reported_and_recorded_not_raised():
    """The coupon stays issued, with an event saying why it did not go."""
    coupons = _Coupons(_coupon(), _offer())
    service = _service(coupon_repository=coupons, sender_factory=_FailingSender)

    receipt = await service.send("bar-pepe", _contact(), _issued())

    assert receipt.delivered is False
    assert receipt.reason == "send_failed:ConnectionRefusedError"
    assert coupons.delivered == []
    assert coupons.events[0][0] == "delivery_failed"


@pytest.mark.asyncio
async def test_a_delivered_coupon_that_cannot_be_marked_is_still_delivered():
    """The guest has it; a bookkeeping failure must not say otherwise."""
    coupons = _Coupons(_coupon(), _offer(), fail_mark=RuntimeError("db down"))
    service = _service(coupon_repository=coupons)

    receipt = await service.send("bar-pepe", _contact(), _issued())

    assert receipt.delivered is True


@pytest.mark.asyncio
async def test_nothing_to_send_without_a_coupon_code():
    """Guards the case where issuance declined but the edge fired anyway."""
    receipt = await _service().send(
        "bar-pepe", _contact(), CouponIssued(issued=False)
    )

    assert receipt.delivered is False
    assert receipt.reason == "no_coupon"


@pytest.mark.asyncio
async def test_an_unreadable_coupon_row_still_sends_the_code():
    """The code is the one thing always known; the rest is decoration."""
    class _Broken(_Coupons):
        async def get_coupon_by_code(self, tenant_id, code):
            raise RuntimeError("db down")

    receipt = await _service(coupon_repository=_Broken()).send(
        "bar-pepe", _contact(), _issued()
    )

    assert receipt.delivered is True
    assert "RECOVER20-7KQF9M" in _Sender.last.sent[0]["message"]


@pytest.mark.asyncio
async def test_the_handle_never_appears_in_the_logs_or_the_receipt(caplog):
    """Delivery reads personal data; it must not scatter it."""
    coupons = _Coupons(_coupon(), _offer())
    service = _service(coupon_repository=coupons, sender_factory=_FailingSender)

    with caplog.at_level(logging.DEBUG):
        receipt = await service.send("bar-pepe", _contact(), _issued())

    assert EMAIL not in caplog.text
    assert EMAIL not in str(receipt)
    assert EMAIL not in str(coupons.events)


@pytest.mark.asyncio
async def test_an_offer_without_a_name_is_still_described_in_words():
    """A guest reads the message, so it cannot say 'percent 20.0'."""
    service = _service(
        coupon_repository=_Coupons(
            _coupon(),
            _offer(name="", discount_type=DiscountType.PERCENT, discount_value=20),
        )
    )

    await service.send("bar-pepe", _contact(), _issued())

    assert "20% off your next visit" in _Sender.last.sent[0]["message"]
