"""Redeeming a coupon: exactly once, with a reason when it cannot be."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
from asyncdb import AsyncDB

from parrot_saas.coupons.issuer import CouponIssuer
from parrot_saas.coupons.models import CouponOfferCreate, CouponStatus
from parrot_saas.coupons.repository import (
    CouponRepository,
    RedemptionError,
    as_uuid,
)
from parrot_saas.db.schema import ensure_schema

pytestmark = pytest.mark.integration


@pytest.fixture
async def coupons(
    test_dsn: str, unique_schema: str
) -> AsyncIterator[CouponRepository]:
    """A coupon repository with two tenants and a wide pool."""
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


@pytest.fixture
async def code(coupons) -> str:
    """One issued coupon, ready to redeem."""
    await coupons.create_offer(
        "bar-pepe", CouponOfferCreate(code="RECOVER20", discount_value=20)
    )
    result = await CouponIssuer(coupons).issue(
        "bar-pepe", offer_code="RECOVER20"
    )
    return result.coupon_code


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


async def test_redeeming_marks_the_coupon_spent(coupons, code) -> None:
    """Status, timestamp and who accepted it."""
    coupon = await coupons.redeem("bar-pepe", code, redeemed_by="till-3")

    assert coupon.status == CouponStatus.REDEEMED.value
    assert coupon.redeemed_by == "till-3"
    assert coupon.redeemed_at is not None


async def test_redemption_is_recorded_in_the_trail(coupons, code) -> None:
    """Money left the business; the trail says on whose authority."""
    coupon = await coupons.redeem("bar-pepe", code, redeemed_by="till-3")

    events = await coupons.list_events("bar-pepe", coupon.coupon_id)
    assert [e.event for e in events] == ["issued", "redeemed"]
    assert events[-1].actor == "till-3"


async def test_a_delivered_coupon_is_redeemable(coupons, code) -> None:
    """Delivery is a step on the way, not a state that blocks spending."""
    coupon = await coupons.get_coupon_by_code("bar-pepe", code)
    await coupons.mark_delivered("bar-pepe", coupon.coupon_id)

    redeemed = await coupons.redeem("bar-pepe", code)

    assert redeemed.status == CouponStatus.REDEEMED.value


async def test_the_code_is_matched_case_insensitively(coupons, code) -> None:
    """It is typed in by hand at a counter."""
    redeemed = await coupons.redeem("bar-pepe", f"  {code.lower()}  ")

    assert redeemed.status == CouponStatus.REDEEMED.value


# ---------------------------------------------------------------------------
# Exactly once
# ---------------------------------------------------------------------------


async def test_a_coupon_cannot_be_redeemed_twice(coupons, code) -> None:
    """The second attempt says so rather than silently succeeding."""
    await coupons.redeem("bar-pepe", code)

    with pytest.raises(RedemptionError) as exc:
        await coupons.redeem("bar-pepe", code)

    assert exc.value.reason == "already_redeemed"


async def test_two_tills_scanning_at_once_produce_one_winner(
    coupons, code
) -> None:
    """One statement carries the state check, so the loser matches no rows.

    This is what stops the same code being honoured at two counters in the
    same second.
    """
    results = await asyncio.gather(
        *(coupons.redeem("bar-pepe", code, redeemed_by=f"till-{i}") for i in range(8)),
        return_exceptions=True,
    )

    winners = [r for r in results if not isinstance(r, BaseException)]
    losers = [r for r in results if isinstance(r, RedemptionError)]
    assert len(winners) == 1
    assert len(losers) == 7
    assert all(loser.reason == "already_redeemed" for loser in losers)


# ---------------------------------------------------------------------------
# Discriminated refusals
# ---------------------------------------------------------------------------


async def test_an_unknown_code_says_so(coupons) -> None:
    """A typo at the counter is not the same problem as an expired coupon."""
    with pytest.raises(RedemptionError) as exc:
        await coupons.redeem("bar-pepe", "NOPE-123456")

    assert exc.value.reason == "unknown_coupon"


async def test_an_expired_coupon_says_when(coupons, code) -> None:
    """The date is what lets staff decide whether to honour it anyway."""
    coupon = await coupons.get_coupon_by_code("bar-pepe", code)
    async with coupons.acquire() as conn:
        await conn.execute(
            f"UPDATE {coupons.table('coupons')} SET expires_at = $2 "
            "WHERE coupon_id = $1",
            as_uuid(coupon.coupon_id),
            datetime.now(timezone.utc) - timedelta(days=1),
        )

    with pytest.raises(RedemptionError) as exc:
        await coupons.redeem("bar-pepe", code)

    assert exc.value.reason == "expired"


async def test_a_voided_coupon_says_so(coupons, code) -> None:
    """Withdrawn is a different conversation from expired."""
    coupon = await coupons.get_coupon_by_code("bar-pepe", code)
    await coupons.void("bar-pepe", coupon.coupon_id, reason="issued in error")

    with pytest.raises(RedemptionError) as exc:
        await coupons.redeem("bar-pepe", code)

    assert exc.value.reason == "void"


async def test_a_redeemed_coupon_cannot_be_voided(coupons, code) -> None:
    """The money is already gone; voiding it would falsify the ledger."""
    coupon = await coupons.get_coupon_by_code("bar-pepe", code)
    await coupons.redeem("bar-pepe", code)

    assert await coupons.void("bar-pepe", coupon.coupon_id) is None


async def test_delivery_cannot_drag_a_redeemed_coupon_backwards(
    coupons, code
) -> None:
    """A retried notification must not rewrite a spent coupon."""
    coupon = await coupons.get_coupon_by_code("bar-pepe", code)
    await coupons.redeem("bar-pepe", code)

    assert await coupons.mark_delivered("bar-pepe", coupon.coupon_id) is None


async def test_another_tenant_cannot_redeem_this_coupon(coupons, code) -> None:
    """Codes are unique per tenant, so they must not cross."""
    with pytest.raises(RedemptionError) as exc:
        await coupons.redeem("hotel-x", code)

    assert exc.value.reason == "unknown_coupon"
