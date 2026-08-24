"""Issuing a coupon: the one place in the flow where a race costs money.

Two reviews arriving at the same instant, one coupon left in the budget. Get
the locking wrong and the tenant gives away more than they agreed to — quietly,
because nothing errors and both guests get a code.

So issuance runs inside a single transaction on its own connection, and the
**order of the checks is load-bearing**:

1. read the offer;
2. **lock the budget row** for the current period;
3. check the budget;
4. check the per-guest cap;
5. insert the coupon and increment the counter.

Step 2 comes before step 4 deliberately. The per-guest cap is a ``COUNT``, and
a ``COUNT`` locks nothing — two concurrent issuances for the same guest would
both pass it. Locking the budget first serialises *all* issuance of that offer,
which protects the guest count as a side effect. Reordering these two lines
would leave both caps leaky in a way no single-threaded test can see.

An exhausted budget is a **decision, not an error**: it returns
``CouponIssued(issued=False, reason="budget_exhausted")`` so the flow's
``coupon_issue → close`` edge closes the run normally. Raising here would make
every sold-out offer look like an incident.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from navconfig.logging import logging

from ..flows.community_manager.models import CouponIssued
from .models import BudgetPeriod, CouponOffer
from .repository import CouponRepository, as_uuid

logger = logging.getLogger("parrot_saas.coupons.issuer")

#: Alphabet for the human-facing part of a code.
#:
#: No ``O``/``0`` and no ``I``/``1``: someone reads this down a phone line and
#: types it into a till. Ambiguity here is a support call, not a typo.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

#: Characters of randomness after the offer code. 32^6 ≈ 10^9 per offer.
CODE_LENGTH = 6

#: How many times to retry a code collision before giving up.
CODE_ATTEMPTS = 5


def period_start(period: str, today: Optional[date] = None) -> date:
    """Return the first day of the budget period containing ``today``.

    Args:
        period: A :class:`BudgetPeriod` value.
        today: The day to place. Defaults to today in UTC.

    Returns:
        The period's first day. ``total`` collapses to a fixed epoch so every
        period lookup can use the same unique constraint rather than needing a
        nullable column and a second index.
    """
    day = today or datetime.now(timezone.utc).date()
    if period == BudgetPeriod.MONTH.value:
        return day.replace(day=1)
    if period == BudgetPeriod.WEEK.value:
        return day - timedelta(days=day.weekday())
    return date(1970, 1, 1)


def generate_code(offer_code: str) -> str:
    """Build a coupon code a person can read aloud.

    Args:
        offer_code: The offer's code, used as a human-meaningful prefix.

    Returns:
        Something like ``RECOVER20-7KQF9M``.
    """
    suffix = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return f"{offer_code}-{suffix}"


class CouponIssuer:
    """Issues coupons against a tenant's offers and budgets.

    Args:
        repository: Repository whose pool the transaction is taken from.
        code_generator: Override for :func:`generate_code`, so a test can force
            a collision.
    """

    def __init__(
        self,
        repository: CouponRepository,
        *,
        code_generator: Optional[Any] = None,
    ) -> None:
        self._repository = repository
        self._generate = code_generator or generate_code

    async def issue(
        self,
        tenant_id: str,
        *,
        offer_code: str,
        guest_id: str = "",
        review_id: str = "",
    ) -> CouponIssued:
        """Issue a coupon, or explain why none was issued.

        The signature matches what ``CouponIssueNode`` calls.

        Args:
            tenant_id: Owning tenant.
            offer_code: The code an eligibility rule's result named.
            guest_id: Who it is for, when known.
            review_id: The review that earned it, when there was one.

        Returns:
            A :class:`CouponIssued` — ``issued=False`` with a reason is a
            normal outcome, not a failure.
        """
        repo = self._repository
        offer = await repo.get_offer_by_code(tenant_id, offer_code)
        if offer is None:
            return CouponIssued(
                issued=False, offer_code=offer_code, reason="unknown_offer"
            )
        if not offer.active:
            return CouponIssued(
                issued=False, offer_code=offer.code, reason="offer_inactive"
            )

        async with repo.transaction() as conn:
            budget = await self._lock_budget(conn, tenant_id, offer)
            if budget is not None and _exhausted(budget):
                logger.info(
                    "tenant %s has spent its %s budget for %s",
                    tenant_id,
                    offer.budget_period,
                    offer.code,
                )
                return CouponIssued(
                    issued=False,
                    offer_code=offer.code,
                    reason="budget_exhausted",
                )

            # Safe here only because the budget row above is already locked,
            # which serialises every issuance of this offer.
            if offer.max_per_guest > 0 and guest_id:
                held = await self._count_for_guest(
                    conn, tenant_id, offer.offer_id, guest_id
                )
                if held >= offer.max_per_guest:
                    return CouponIssued(
                        issued=False,
                        offer_code=offer.code,
                        reason="per_guest_limit",
                    )

            expires_at = _utcnow() + timedelta(days=offer.valid_days)
            coupon = await self._insert_coupon(
                conn, tenant_id, offer, guest_id, review_id, expires_at
            )
            if coupon is None:
                return CouponIssued(
                    issued=False,
                    offer_code=offer.code,
                    reason="code_collision",
                )

            await conn.execute(
                f"UPDATE {repo.table('coupon_budgets')} "
                "SET issued_count = issued_count + 1 "
                "WHERE tenant_id = $1 AND offer_id = $2 AND period_start = $3",
                tenant_id,
                as_uuid(offer.offer_id),
                period_start(offer.budget_period),
            )
            await conn.execute(
                f"INSERT INTO {repo.table('coupon_events')} "
                "(tenant_id, coupon_id, event, detail) "
                "VALUES ($1, $2, 'issued', $3::jsonb)",
                tenant_id,
                coupon["coupon_id"],
                _json({"offer_code": offer.code, "review_id": review_id}),
            )

        logger.info(
            "tenant %s issued %s to guest %s",
            tenant_id,
            coupon["code"],
            guest_id or "(anonymous)",
        )
        return CouponIssued(
            issued=True,
            coupon_code=coupon["code"],
            offer_code=offer.code,
            reason="issued",
            expires_at=expires_at,
        )

    async def _lock_budget(
        self, conn: Any, tenant_id: str, offer: CouponOffer
    ) -> Optional[dict]:
        """Create this period's counter if needed, then lock it.

        The upsert is what makes budget periods reset without a scheduler: the
        row for a new month appears the first time someone earns a coupon in
        it. ``ON CONFLICT DO NOTHING`` because two issuers may race to create
        it, and the loser simply locks what the winner made.
        """
        repo = self._repository
        start = period_start(offer.budget_period)
        offer_key = as_uuid(offer.offer_id)

        await conn.execute(
            f"INSERT INTO {repo.table('coupon_budgets')} "
            "(tenant_id, offer_id, period_start, max_coupons) "
            "VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (tenant_id, offer_id, period_start) DO NOTHING",
            tenant_id,
            offer_key,
            start,
            offer.max_coupons,
        )
        return await conn.fetch_one(
            f"SELECT budget_id, max_coupons, issued_count "
            f"FROM {repo.table('coupon_budgets')} "
            "WHERE tenant_id = $1 AND offer_id = $2 AND period_start = $3 "
            "FOR UPDATE",
            tenant_id,
            offer_key,
            start,
        )

    async def _count_for_guest(
        self, conn: Any, tenant_id: str, offer_id: str, guest_id: str
    ) -> int:
        """How many of this offer the guest already holds, inside the txn."""
        guest = as_uuid(guest_id)
        if guest is None:
            return 0
        row = await conn.fetch_one(
            f"SELECT count(*) AS n FROM {self._repository.table('coupons')} "
            "WHERE tenant_id = $1 AND offer_id = $2 AND guest_id = $3 "
            "  AND status <> 'void'",
            tenant_id,
            as_uuid(offer_id),
            guest,
        )
        return int(row["n"]) if row else 0

    async def _insert_coupon(
        self,
        conn: Any,
        tenant_id: str,
        offer: CouponOffer,
        guest_id: str,
        review_id: str,
        expires_at: datetime,
    ) -> Optional[dict]:
        """Insert a coupon, retrying a code collision a bounded number of times.

        ``ON CONFLICT DO NOTHING`` rather than catching a unique violation:
        inside a transaction an unhandled constraint error aborts the whole
        thing, so the retry would have nothing left to retry into.
        """
        repo = self._repository
        for attempt in range(CODE_ATTEMPTS):
            row = await conn.fetch_one(
                f"INSERT INTO {repo.table('coupons')} "
                "(tenant_id, offer_id, code, guest_id, review_id, expires_at) "
                "VALUES ($1, $2, $3, $4, $5, $6) "
                "ON CONFLICT (tenant_id, code) DO NOTHING "
                "RETURNING coupon_id, code",
                tenant_id,
                as_uuid(offer.offer_id),
                self._generate(offer.code),
                as_uuid(guest_id),
                as_uuid(review_id),
                expires_at,
            )
            if row is not None:
                return dict(row)
            logger.warning(
                "coupon code collision for offer %s (attempt %d)",
                offer.code,
                attempt + 1,
            )
        logger.error(
            "could not mint a unique code for offer %s after %d attempts",
            offer.code,
            CODE_ATTEMPTS,
        )
        return None


def _exhausted(budget: Any) -> bool:
    """Whether a locked budget row has nothing left.

    ``max_coupons == 0`` means unlimited — arithmetic rather than a null
    branch, so the check reads the same everywhere.
    """
    maximum = int(budget["max_coupons"])
    return maximum > 0 and int(budget["issued_count"]) >= maximum


def _json(payload: dict) -> str:
    """Serialise a jsonb parameter."""
    import json

    return json.dumps(payload)


def _utcnow() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


__all__ = (
    "CODE_ALPHABET",
    "CODE_ATTEMPTS",
    "CODE_LENGTH",
    "CouponIssuer",
    "generate_code",
    "period_start",
)
