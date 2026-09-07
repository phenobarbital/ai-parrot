"""Persistence for coupon offers, issued coupons and their trail.

Issuance itself does **not** live here — it needs a transaction spanning
several statements and is its own object, :mod:`parrot_saas.coupons.issuer`.
What is here is everything that reads cleanly as one statement, redemption
included: redemption *is* one statement, and that is what makes it safe.
"""
from __future__ import annotations

import json
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from ..db.repository import BaseRepository
from .models import (
    REDEEMABLE_STATUSES,
    Coupon,
    CouponEvent,
    CouponOffer,
    CouponOfferCreate,
    CouponOfferUpdate,
    CouponStatus,
)

_OFFER_COLUMNS = (
    "offer_id, tenant_id, code, name, description, discount_type, "
    "discount_value, currency, valid_days, max_per_guest, budget_period, "
    "max_coupons, active, terms, created_at, updated_at"
)

_COUPON_COLUMNS = (
    "coupon_id, tenant_id, offer_id, code, guest_id, review_id, status, "
    "issued_at, expires_at, delivered_at, redeemed_at, redeemed_by"
)

_EVENT_COLUMNS = (
    "event_id, tenant_id, coupon_id, event, detail, actor, created_at"
)


@dataclass(frozen=True, slots=True)
class GuestCouponHistory:
    """What a guest has already been given, for anti-abuse rules.

    Deliberately raw facts rather than rule vocabulary: the mapping onto
    ``ctx.coupons_issued_90d`` and ``ctx.last_coupon_days_ago`` belongs to the
    eligibility node, so the coupon package does not have to know what the
    rules engine calls things.

    Attributes:
        issued_in_window: Coupons issued inside the requested window, across
            every offer. Voided ones are excluded — withdrawing a mistaken
            issuance has to give the guest their allowance back.
        last_issued_at: When they were last given one, or ``None`` for never.
        window_days: The window that was counted, echoed back so a caller
            cannot misreport which period the count covers.
    """

    issued_in_window: int = 0
    last_issued_at: Optional[datetime] = None
    window_days: int = 90

    def days_since_last(self, *, never: int) -> int:
        """Days since the last coupon, or ``never`` when there was none.

        Args:
            never: Value standing for "no coupon has ever been issued". The
                caller supplies it because the sentinel is the rules engine's
                vocabulary, not this package's.

        Returns:
            Whole days elapsed, floored at zero so a clock skew cannot produce
            a negative that no rule would be written to expect.
        """
        if self.last_issued_at is None:
            return never
        last = self.last_issued_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - last).days)


class OfferAlreadyExists(ValueError):
    """An offer with that code already exists for this tenant."""


class RedemptionError(RuntimeError):
    """A coupon could not be redeemed, with a discriminated reason.

    Attributes:
        reason: One of ``unknown_coupon``, ``already_redeemed``, ``expired``,
            ``void``. The distinction matters: this is read out at a counter
            with the customer standing there, and "it didn't work" is useless.
    """

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def as_uuid(value: Any) -> Optional[_uuid.UUID]:
    """Convert a surrogate key to a UUID, or ``None`` if it is not one.

    asyncpg infers the parameter type from a ``$n::uuid`` cast and rejects a
    ``str``, so the conversion happens here; that also turns a malformed id
    from a URL into a clean miss rather than a driver error.
    """
    if isinstance(value, _uuid.UUID):
        return value
    if not value:
        return None
    try:
        return _uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


class CouponRepository(BaseRepository):
    """Offers, coupons and events."""

    # -- offers ------------------------------------------------------------

    async def create_offer(
        self, tenant_id: str, payload: CouponOfferCreate
    ) -> CouponOffer:
        """Store a new offer.

        Raises:
            OfferAlreadyExists: If the code is taken for this tenant.
        """
        row = await self.fetch_one(
            tenant_id,
            f"INSERT INTO {self.table('coupon_offers')} "
            "(tenant_id, code, name, description, discount_type, "
            " discount_value, currency, valid_days, max_per_guest, "
            " budget_period, max_coupons, active, terms) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13) "
            "ON CONFLICT (tenant_id, code) DO NOTHING "
            f"RETURNING {_OFFER_COLUMNS}",
            payload.code,
            payload.name,
            payload.description,
            payload.discount_type,
            payload.discount_value,
            payload.currency,
            payload.valid_days,
            payload.max_per_guest,
            payload.budget_period,
            payload.max_coupons,
            payload.active,
            payload.terms,
        )
        if row is None:
            raise OfferAlreadyExists(
                f"tenant {tenant_id!r} already has an offer coded "
                f"{payload.code!r}"
            )
        return CouponOffer.from_row(row)

    async def get_offer(
        self, tenant_id: str, offer_id: str
    ) -> Optional[CouponOffer]:
        """Return one offer by surrogate key."""
        key = as_uuid(offer_id)
        if key is None:
            return None
        row = await self.fetch_one(
            tenant_id,
            f"SELECT {_OFFER_COLUMNS} FROM {self.table('coupon_offers')} "
            "WHERE tenant_id = $1 AND offer_id = $2",
            key,
        )
        return CouponOffer.from_row(row) if row else None

    async def get_offer_by_code(
        self, tenant_id: str, code: str
    ) -> Optional[CouponOffer]:
        """Return one offer by the code an eligibility rule names."""
        row = await self.fetch_one(
            tenant_id,
            f"SELECT {_OFFER_COLUMNS} FROM {self.table('coupon_offers')} "
            "WHERE tenant_id = $1 AND code = $2",
            (code or "").strip().upper(),
        )
        return CouponOffer.from_row(row) if row else None

    async def list_offers(
        self, tenant_id: str, *, active_only: bool = False
    ) -> Sequence[CouponOffer]:
        """List a tenant's offers."""
        rows = await self.fetch_all(
            tenant_id,
            f"SELECT {_OFFER_COLUMNS} FROM {self.table('coupon_offers')} "
            "WHERE tenant_id = $1 AND ($2::boolean IS NOT TRUE OR active) "
            "ORDER BY code",
            active_only,
        )
        return [CouponOffer.from_row(row) for row in rows]

    async def update_offer(
        self, tenant_id: str, offer_id: str, patch: CouponOfferUpdate
    ) -> Optional[CouponOffer]:
        """Apply a partial amendment to an offer."""
        key = as_uuid(offer_id)
        if key is None:
            return None
        changes = patch.changes()
        if not changes:
            return await self.get_offer(tenant_id, offer_id)

        assignments = [
            f"{field} = ${index}"
            for index, field in enumerate(changes, start=3)
        ]
        row = await self.fetch_one(
            tenant_id,
            f"UPDATE {self.table('coupon_offers')} "
            f"SET {', '.join(assignments)}, updated_at = now() "
            "WHERE tenant_id = $1 AND offer_id = $2 "
            f"RETURNING {_OFFER_COLUMNS}",
            key,
            *changes.values(),
        )
        return CouponOffer.from_row(row) if row else None

    async def deactivate_offer(
        self, tenant_id: str, offer_id: str
    ) -> Optional[CouponOffer]:
        """Retire an offer without deleting it.

        Coupons already in guests' hands reference this row and must stay
        redeemable, so retirement is a flag rather than a ``DELETE``.
        """
        return await self.update_offer(
            tenant_id, offer_id, CouponOfferUpdate(active=False)
        )

    # -- coupons -----------------------------------------------------------

    async def get_coupon(
        self, tenant_id: str, coupon_id: str
    ) -> Optional[Coupon]:
        """Return one coupon by surrogate key."""
        key = as_uuid(coupon_id)
        if key is None:
            return None
        row = await self.fetch_one(
            tenant_id,
            f"SELECT {_COUPON_COLUMNS} FROM {self.table('coupons')} "
            "WHERE tenant_id = $1 AND coupon_id = $2",
            key,
        )
        return Coupon.from_row(row) if row else None

    async def get_coupon_by_code(
        self, tenant_id: str, code: str
    ) -> Optional[Coupon]:
        """Return one coupon by its redeemable code."""
        row = await self.fetch_one(
            tenant_id,
            f"SELECT {_COUPON_COLUMNS} FROM {self.table('coupons')} "
            "WHERE tenant_id = $1 AND code = $2",
            (code or "").strip().upper(),
        )
        return Coupon.from_row(row) if row else None

    async def list_coupons(
        self,
        tenant_id: str,
        *,
        status: Optional[str] = None,
        guest_id: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Coupon]:
        """List a tenant's coupons, newest first."""
        rows = await self.fetch_all(
            tenant_id,
            f"SELECT {_COUPON_COLUMNS} FROM {self.table('coupons')} "
            "WHERE tenant_id = $1 "
            "  AND ($2::text IS NULL OR status = $2) "
            "  AND ($3::uuid IS NULL OR guest_id = $3) "
            "ORDER BY issued_at DESC, coupon_id "
            "LIMIT $4 OFFSET $5",
            status,
            as_uuid(guest_id),
            limit,
            offset,
        )
        return [Coupon.from_row(row) for row in rows]

    async def count_for_guest(
        self, tenant_id: str, offer_id: str, guest_id: str
    ) -> int:
        """How many of one offer a guest already holds.

        Voided coupons do not count: withdrawing a mistaken issuance has to
        actually give the guest their allowance back.
        """
        key, guest = as_uuid(offer_id), as_uuid(guest_id)
        if key is None or guest is None:
            return 0
        row = await self.fetch_one(
            tenant_id,
            f"SELECT count(*) AS n FROM {self.table('coupons')} "
            "WHERE tenant_id = $1 AND offer_id = $2 AND guest_id = $3 "
            "  AND status <> 'void'",
            key,
            guest,
        )
        return int(row["n"]) if row else 0

    async def guest_history(
        self, tenant_id: str, guest_id: str, *, window_days: int = 90
    ) -> GuestCouponHistory:
        """Summarise what one guest has already received.

        Counts across **every** offer, which is what makes it useful to an
        anti-abuse rule: :meth:`count_for_guest` is per-offer and unbounded in
        time, so a guest could collect one of each offer on every review and
        never trip it. The issuer's ``max_per_guest`` check is per-offer and
        transactional; this is the cross-offer, time-boxed view a tenant
        writes ``ctx.coupons_issued_90d`` against.

        Args:
            tenant_id: Owning tenant.
            guest_id: The guest. An unknown or malformed id yields an empty
                history rather than an error — an anonymous review simply has
                no coupon record.
            window_days: How far back to count.

        Returns:
            The guest's coupon history.
        """
        guest = as_uuid(guest_id)
        if guest is None:
            return GuestCouponHistory(window_days=window_days)
        row = await self.fetch_one(
            tenant_id,
            "SELECT count(*) FILTER ("
            "    WHERE issued_at >= now() - make_interval(days => $3)"
            ") AS issued_in_window, "
            "max(issued_at) AS last_issued_at "
            f"FROM {self.table('coupons')} "
            "WHERE tenant_id = $1 AND guest_id = $2 AND status <> 'void'",
            guest,
            int(window_days),
        )
        if row is None:
            return GuestCouponHistory(window_days=window_days)
        return GuestCouponHistory(
            issued_in_window=int(row["issued_in_window"] or 0),
            last_issued_at=row["last_issued_at"],
            window_days=window_days,
        )

    async def mark_delivered(
        self, tenant_id: str, coupon_id: str
    ) -> Optional[Coupon]:
        """Record that a coupon reached the guest.

        Only from ``issued``: a redeemed coupon must not be dragged back to
        ``delivered`` by a retried notification.
        """
        key = as_uuid(coupon_id)
        if key is None:
            return None
        row = await self.fetch_one(
            tenant_id,
            f"UPDATE {self.table('coupons')} "
            "SET status = 'delivered', delivered_at = now() "
            "WHERE tenant_id = $1 AND coupon_id = $2 AND status = 'issued' "
            f"RETURNING {_COUPON_COLUMNS}",
            key,
        )
        return Coupon.from_row(row) if row else None

    async def redeem(
        self, tenant_id: str, code: str, *, redeemed_by: str = ""
    ) -> Coupon:
        """Spend a coupon, exactly once.

        One statement, so two tills scanning the same code at the same moment
        produce exactly one winner: the ``WHERE`` clause carries the state
        check, and whichever transaction commits second matches no rows.

        Args:
            tenant_id: Owning tenant.
            code: The redeemable code.
            redeemed_by: Who accepted it, for the trail.

        Returns:
            The redeemed coupon.

        Raises:
            RedemptionError: With a reason a person can act on.
        """
        normalised = (code or "").strip().upper()
        row = await self.fetch_one(
            tenant_id,
            f"UPDATE {self.table('coupons')} "
            "SET status = 'redeemed', redeemed_at = now(), redeemed_by = $3 "
            "WHERE tenant_id = $1 AND code = $2 "
            f"  AND status IN ('{REDEEMABLE_STATUSES[0]}', "
            f"                 '{REDEEMABLE_STATUSES[1]}') "
            "  AND expires_at > now() "
            f"RETURNING {_COUPON_COLUMNS}",
            normalised,
            redeemed_by,
        )
        if row is not None:
            coupon = Coupon.from_row(row)
            await self.record_event(
                tenant_id,
                coupon.coupon_id,
                "redeemed",
                actor=redeemed_by,
                detail={"code": coupon.code},
            )
            return coupon

        # Zero rows updated. A second read, purely to say *why* — a bare
        # refusal at a counter with the customer waiting is worthless.
        raise await self._explain_refusal(tenant_id, normalised)

    async def _explain_refusal(
        self, tenant_id: str, code: str
    ) -> RedemptionError:
        """Turn a failed redemption into a reason someone can act on."""
        existing = await self.get_coupon_by_code(tenant_id, code)
        if existing is None:
            return RedemptionError(
                "unknown_coupon", f"no coupon with code {code!r}"
            )
        if existing.status == CouponStatus.REDEEMED.value:
            when = existing.redeemed_at.isoformat() if existing.redeemed_at else "?"
            return RedemptionError(
                "already_redeemed", f"coupon {code!r} was redeemed at {when}"
            )
        if existing.status == CouponStatus.VOID.value:
            return RedemptionError("void", f"coupon {code!r} was withdrawn")
        if existing.expires_at and existing.expires_at <= _utcnow():
            return RedemptionError(
                "expired",
                f"coupon {code!r} expired on "
                f"{existing.expires_at.date().isoformat()}",
            )
        return RedemptionError(  # pragma: no cover - lost to a concurrent write
            "not_redeemable", f"coupon {code!r} is not redeemable"
        )

    async def void(
        self, tenant_id: str, coupon_id: str, *, reason: str = ""
    ) -> Optional[Coupon]:
        """Withdraw a coupon that should not have been issued."""
        key = as_uuid(coupon_id)
        if key is None:
            return None
        row = await self.fetch_one(
            tenant_id,
            f"UPDATE {self.table('coupons')} SET status = 'void' "
            "WHERE tenant_id = $1 AND coupon_id = $2 AND status <> 'redeemed' "
            f"RETURNING {_COUPON_COLUMNS}",
            key,
        )
        if row is None:
            return None
        coupon = Coupon.from_row(row)
        await self.record_event(
            tenant_id, coupon.coupon_id, "voided", detail={"reason": reason}
        )
        return coupon

    # -- events ------------------------------------------------------------

    async def record_event(
        self,
        tenant_id: str,
        coupon_id: str,
        event: str,
        *,
        detail: Optional[dict] = None,
        actor: str = "",
    ) -> None:
        """Append to a coupon's trail."""
        key = as_uuid(coupon_id)
        if key is None:
            return
        await self.execute(
            tenant_id,
            f"INSERT INTO {self.table('coupon_events')} "
            "(tenant_id, coupon_id, event, detail, actor) "
            "VALUES ($1, $2, $3, $4::jsonb, $5)",
            key,
            event,
            json.dumps(detail or {}),
            actor,
        )

    async def list_events(
        self, tenant_id: str, coupon_id: str
    ) -> Sequence[CouponEvent]:
        """Return a coupon's trail, oldest first."""
        key = as_uuid(coupon_id)
        if key is None:
            return []
        rows = await self.fetch_all(
            tenant_id,
            f"SELECT {_EVENT_COLUMNS} FROM {self.table('coupon_events')} "
            "WHERE tenant_id = $1 AND coupon_id = $2 "
            "ORDER BY created_at, event_id",
            key,
        )
        return [CouponEvent.from_row(row) for row in rows]


def _utcnow() -> datetime:
    """Return an aware UTC timestamp."""
    from datetime import timezone

    return datetime.now(timezone.utc)


__all__ = (
    "CouponRepository",
    "GuestCouponHistory",
    "OfferAlreadyExists",
    "RedemptionError",
    "as_uuid",
)
