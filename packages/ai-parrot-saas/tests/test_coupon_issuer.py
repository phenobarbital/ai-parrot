"""Coupon issuance, including the races that cost real money.

The budget test is the reason this module exists: two reviews arriving at the
same instant against one remaining coupon must produce one coupon and one
refusal, not two coupons and a tenant giving away more than they agreed to.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
from asyncdb import AsyncDB

from parrot_saas.coupons.issuer import CouponIssuer, period_start
from parrot_saas.coupons.models import CouponOfferCreate
from parrot_saas.coupons.repository import CouponRepository, as_uuid
from parrot_saas.db.schema import ensure_schema

pytestmark = pytest.mark.integration


@pytest.fixture
async def coupons(
    test_dsn: str, unique_schema: str
) -> AsyncIterator[CouponRepository]:
    """A coupon repository on a throwaway schema with two tenants and a guest."""
    conn = AsyncDB("pg", dsn=test_dsn)
    async with await conn.connection():
        await ensure_schema(conn, schema=unique_schema)
        for tenant_id in ("bar-pepe", "hotel-x"):
            await conn.execute(
                f"INSERT INTO {unique_schema}.tenants (tenant_id, name) "
                "VALUES ($1, $2)",
                tenant_id,
                tenant_id.title(),
            )
        await conn.execute(
            f"INSERT INTO {unique_schema}.guests "
            "(guest_id, tenant_id, email) VALUES "
            "('11111111-1111-1111-1111-111111111111', 'bar-pepe', 'a@example.com'),"
            "('22222222-2222-2222-2222-222222222222', 'bar-pepe', 'b@example.com')"
        )

    # A wide, pre-warmed pool on purpose. With ``min_size=1`` the issuers
    # queue for a connection and serialise themselves, so the race tests below
    # would pass with no locking at all — verified by removing the FOR UPDATE
    # and watching them still go green.
    repository = CouponRepository(
        test_dsn, schema=unique_schema, min_size=8, max_size=16
    )
    try:
        yield repository
    finally:
        await repository.aclose()
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


GUEST_A = "11111111-1111-1111-1111-111111111111"
GUEST_B = "22222222-2222-2222-2222-222222222222"


async def _offer(coupons, **overrides):
    """Create an offer with sensible defaults."""
    payload = {"code": "RECOVER20", "name": "20% back", "discount_value": 20}
    payload.update(overrides)
    return await coupons.create_offer("bar-pepe", CouponOfferCreate(**payload))


@pytest.fixture
def issuer(coupons) -> CouponIssuer:
    """An issuer over the fixture repository."""
    return CouponIssuer(coupons)


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


async def test_issuing_produces_a_redeemable_coupon(coupons, issuer) -> None:
    """A coupon with a readable code and a real expiry."""
    await _offer(coupons, valid_days=30)

    result = await issuer.issue(
        "bar-pepe", offer_code="RECOVER20", guest_id=GUEST_A
    )

    assert result.issued is True
    assert result.coupon_code.startswith("RECOVER20-")
    assert result.offer_code == "RECOVER20"
    stored = await coupons.get_coupon_by_code("bar-pepe", result.coupon_code)
    assert stored.status == "issued"
    assert stored.guest_id == GUEST_A


async def test_expiry_comes_from_the_offer(coupons, issuer) -> None:
    """``valid_days`` is the tenant's lever on how long an offer lives."""
    await _offer(coupons, valid_days=7)

    result = await issuer.issue("bar-pepe", offer_code="RECOVER20")

    delta = result.expires_at - datetime.now(timezone.utc)
    assert timedelta(days=6) < delta <= timedelta(days=7)


async def test_issuance_is_recorded_in_the_trail(coupons, issuer) -> None:
    """Money is involved; the trail outlives any status column."""
    await _offer(coupons)

    result = await issuer.issue("bar-pepe", offer_code="RECOVER20")

    coupon = await coupons.get_coupon_by_code("bar-pepe", result.coupon_code)
    events = await coupons.list_events("bar-pepe", coupon.coupon_id)
    assert [e.event for e in events] == ["issued"]


async def test_an_anonymous_review_can_still_earn_a_coupon(coupons, issuer) -> None:
    """No guest on file is not a reason to refuse — delivery decides that."""
    await _offer(coupons)

    result = await issuer.issue("bar-pepe", offer_code="RECOVER20")

    assert result.issued is True


# ---------------------------------------------------------------------------
# Refusals — every one a decision, none an exception
# ---------------------------------------------------------------------------


async def test_an_unknown_offer_is_refused_not_raised(coupons, issuer) -> None:
    """A rule naming a deleted offer must not crash every review."""
    result = await issuer.issue("bar-pepe", offer_code="NOPE")

    assert result.issued is False
    assert result.reason == "unknown_offer"


async def test_an_inactive_offer_is_refused(coupons, issuer) -> None:
    """Retiring an offer stops issuance without touching coupons in the wild."""
    offer = await _offer(coupons)
    await coupons.deactivate_offer("bar-pepe", offer.offer_id)

    result = await issuer.issue("bar-pepe", offer_code="RECOVER20")

    assert result.issued is False
    assert result.reason == "offer_inactive"


async def test_an_exhausted_budget_is_a_decision(coupons, issuer) -> None:
    """A sold-out offer closes the run normally; it is not an incident."""
    await _offer(coupons, max_coupons=1)
    await issuer.issue("bar-pepe", offer_code="RECOVER20")

    second = await issuer.issue("bar-pepe", offer_code="RECOVER20")

    assert second.issued is False
    assert second.reason == "budget_exhausted"


async def test_zero_means_unlimited(coupons, issuer) -> None:
    """``max_coupons = 0`` is arithmetic, not a null branch."""
    await _offer(coupons, max_coupons=0)

    results = [
        await issuer.issue("bar-pepe", offer_code="RECOVER20")
        for _ in range(5)
    ]

    assert all(r.issued for r in results)


async def test_the_per_guest_cap_holds(coupons, issuer) -> None:
    """One guest may not farm the same offer."""
    await _offer(coupons, max_per_guest=1)
    await issuer.issue("bar-pepe", offer_code="RECOVER20", guest_id=GUEST_A)

    again = await issuer.issue(
        "bar-pepe", offer_code="RECOVER20", guest_id=GUEST_A
    )
    other = await issuer.issue(
        "bar-pepe", offer_code="RECOVER20", guest_id=GUEST_B
    )

    assert again.issued is False
    assert again.reason == "per_guest_limit"
    assert other.issued is True


async def test_a_voided_coupon_gives_the_allowance_back(coupons, issuer) -> None:
    """Withdrawing a mistaken issuance has to actually undo it."""
    await _offer(coupons, max_per_guest=1)
    first = await issuer.issue(
        "bar-pepe", offer_code="RECOVER20", guest_id=GUEST_A
    )
    coupon = await coupons.get_coupon_by_code("bar-pepe", first.coupon_code)
    await coupons.void("bar-pepe", coupon.coupon_id, reason="issued in error")

    again = await issuer.issue(
        "bar-pepe", offer_code="RECOVER20", guest_id=GUEST_A
    )

    assert again.issued is True


# ---------------------------------------------------------------------------
# The races
# ---------------------------------------------------------------------------


async def test_concurrent_issuers_cannot_overspend_a_budget(
    coupons, issuer
) -> None:
    """Ten reviews land together with one coupon left; one wins.

    Note this case alone is a *weak* detector of a missing lock: with a budget
    of one the first transaction commits almost immediately, and READ
    COMMITTED then shows the increment to everyone else, so it passes even
    without the ``FOR UPDATE``. Verified by deleting the lock and watching it
    stay green. :func:`test_a_burst_never_exceeds_a_larger_budget` is the one
    that actually fails — this one guards the behaviour, that one guards the
    mechanism.
    """
    await _offer(coupons, max_coupons=1)

    results = await asyncio.gather(
        *(issuer.issue("bar-pepe", offer_code="RECOVER20") for _ in range(10))
    )

    assert sum(r.issued for r in results) == 1
    assert sum(r.reason == "budget_exhausted" for r in results) == 9
    assert len(await coupons.list_coupons("bar-pepe")) == 1


async def test_a_burst_never_exceeds_a_larger_budget(coupons, issuer) -> None:
    """The real guard on the lock.

    A budget of three keeps the window open long enough that several issuers
    reach the check before anyone commits. Without the ``FOR UPDATE`` they all
    read the same ``issued_count`` and the tenant hands out a dozen coupons
    against an allowance of three — confirmed by removing the lock, which
    fails exactly here.
    """
    await _offer(coupons, max_coupons=3)

    results = await asyncio.gather(
        *(issuer.issue("bar-pepe", offer_code="RECOVER20") for _ in range(12))
    )

    assert sum(r.issued for r in results) == 3
    assert len(await coupons.list_coupons("bar-pepe")) == 3


async def test_concurrent_issuers_cannot_exceed_the_per_guest_cap(
    coupons, issuer
) -> None:
    """Protected only because the budget row is locked first.

    The per-guest check is a COUNT, and a COUNT locks nothing on its own.
    Taking the budget lock first serialises every issuance of the offer, which
    is what makes this hold. Like the budget-of-one case above this is a weak
    detector — the first commit lands fast enough that READ COMMITTED usually
    saves it — so treat it as a statement of intent, with
    :func:`test_a_burst_never_exceeds_a_larger_budget` as the mechanism's real
    guard.
    """
    await _offer(coupons, max_per_guest=1, max_coupons=0)

    results = await asyncio.gather(
        *(
            issuer.issue(
                "bar-pepe", offer_code="RECOVER20", guest_id=GUEST_A
            )
            for _ in range(10)
        )
    )

    assert sum(r.issued for r in results) == 1


# ---------------------------------------------------------------------------
# Budget periods
# ---------------------------------------------------------------------------


def test_period_start_places_the_day() -> None:
    """Monthly and weekly periods, plus the fixed epoch for ``total``."""
    assert period_start("month", date(2026, 5, 17)) == date(2026, 5, 1)
    assert period_start("week", date(2026, 5, 17)) == date(2026, 5, 11)
    assert period_start("total", date(2026, 5, 17)) == date(1970, 1, 1)


async def test_a_new_period_starts_itself(coupons, issuer) -> None:
    """No scheduler: last month's counter does not limit this month.

    The row for a new period appears the first time someone earns a coupon in
    it, which is what makes "50 a month" work without a cron job that can fail
    silently overnight.
    """
    offer = await _offer(coupons, budget_period="month", max_coupons=1)
    # Fill last month's allowance directly.
    last_month = period_start("month") - timedelta(days=1)
    async with coupons.acquire() as conn:
        await conn.execute(
            f"INSERT INTO {coupons.table('coupon_budgets')} "
            "(tenant_id, offer_id, period_start, max_coupons, issued_count) "
            "VALUES ($1, $2, $3, 1, 1)",
            "bar-pepe",
            as_uuid(offer.offer_id),
            last_month.replace(day=1),
        )

    result = await issuer.issue("bar-pepe", offer_code="RECOVER20")

    assert result.issued is True


async def test_this_periods_budget_still_binds(coupons, issuer) -> None:
    """A period that resets must still stop at its own cap."""
    await _offer(coupons, budget_period="month", max_coupons=2)

    results = [
        await issuer.issue("bar-pepe", offer_code="RECOVER20")
        for _ in range(3)
    ]

    assert [r.issued for r in results] == [True, True, False]


# ---------------------------------------------------------------------------
# Codes and isolation
# ---------------------------------------------------------------------------


async def test_a_code_collision_is_retried(coupons) -> None:
    """A repeated code must produce a different one, not a 500.

    The generator is forced to collide once; the bounded retry is what turns
    that into an ordinary second attempt.
    """
    await _offer(coupons)
    codes = iter(["RECOVER20-AAAAAA", "RECOVER20-AAAAAA", "RECOVER20-BBBBBB"])
    issuer = CouponIssuer(coupons, code_generator=lambda _: next(codes))

    first = await issuer.issue("bar-pepe", offer_code="RECOVER20")
    second = await issuer.issue("bar-pepe", offer_code="RECOVER20")

    assert first.coupon_code == "RECOVER20-AAAAAA"
    assert second.coupon_code == "RECOVER20-BBBBBB"


async def test_an_unmintable_code_is_refused_not_raised(coupons) -> None:
    """Even total collision exhaustion stays a decision."""
    await _offer(coupons)
    issuer = CouponIssuer(coupons, code_generator=lambda _: "RECOVER20-SAME")
    await issuer.issue("bar-pepe", offer_code="RECOVER20")

    second = await issuer.issue("bar-pepe", offer_code="RECOVER20")

    assert second.issued is False
    assert second.reason == "code_collision"


async def test_codes_use_an_unambiguous_alphabet() -> None:
    """Someone reads this down a phone line into a till."""
    from parrot_saas.coupons.issuer import CODE_ALPHABET, generate_code

    assert not set("O0I1") & set(CODE_ALPHABET)
    suffix = generate_code("X").split("-")[1]
    assert set(suffix) <= set(CODE_ALPHABET)


async def test_offers_and_coupons_are_tenant_scoped(coupons, issuer) -> None:
    """Another tenant's offer code is not this tenant's offer."""
    await _offer(coupons)

    theirs = await issuer.issue("hotel-x", offer_code="RECOVER20")

    assert theirs.issued is False
    assert theirs.reason == "unknown_offer"
    assert await coupons.list_coupons("hotel-x") == []
