"""Coupon offers, budgets, issued coupons and their audit trail."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Bounds on an offer code. Uppercase and short because a guest reads it aloud.
CODE_MAX_LENGTH = 32


class DiscountType(str, Enum):
    """How an offer's value is expressed."""

    PERCENT = "percent"
    AMOUNT = "amount"
    FREEBIE = "freebie"


class BudgetPeriod(str, Enum):
    """How often an offer's budget resets.

    Reset is **lazy**: the issuer computes the current period and upserts its
    counter row, so a new period begins the first time someone earns a coupon
    in it. No scheduler, no cron job that can fail silently overnight.
    """

    TOTAL = "total"
    MONTH = "month"
    WEEK = "week"


class CouponStatus(str, Enum):
    """Where an issued coupon is in its life.

    ``VOID`` exists so a mistaken issuance can be withdrawn without deleting
    the row — money is involved, and the trail has to survive the correction.
    """

    ISSUED = "issued"
    DELIVERED = "delivered"
    REDEEMED = "redeemed"
    EXPIRED = "expired"
    VOID = "void"


#: Statuses a coupon can still be redeemed from.
REDEEMABLE_STATUSES = (CouponStatus.ISSUED.value, CouponStatus.DELIVERED.value)


class CouponOffer(BaseModel):
    """What a tenant is willing to give away.

    Attributes:
        offer_id: Surrogate key.
        tenant_id: Owning tenant.
        code: What an eligibility rule's ``result.offer_code`` names. This is
            where the rules engine and the coupon domain meet.
        name: Short label shown to staff.
        description: Longer description.
        discount_type: How ``discount_value`` is read.
        discount_value: The number behind the offer.
        currency: ISO code, meaningful for ``amount`` discounts.
        valid_days: How long an issued coupon stays redeemable.
        max_per_guest: How many of this offer one guest may ever hold.
        budget_period: How often :attr:`max_coupons` resets.
        max_coupons: Cap per period. ``0`` means unlimited — chosen over
            ``None`` so the check is arithmetic rather than a null branch.
        active: Inactive offers issue nothing but keep honouring coupons
            already out there.
        terms: Small print.
        created_at: Row creation time.
        updated_at: Last modification time.
    """

    model_config = ConfigDict(use_enum_values=True, validate_default=True)

    offer_id: str = ""
    tenant_id: str = ""
    code: str = ""
    name: str = ""
    description: str = ""
    discount_type: DiscountType = DiscountType.PERCENT
    discount_value: float = 0.0
    currency: str = "EUR"
    valid_days: int = 30
    max_per_guest: int = 1
    budget_period: BudgetPeriod = BudgetPeriod.TOTAL
    max_coupons: int = 0
    active: bool = True
    terms: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "CouponOffer":
        """Build an offer from a database row.

        ``discount_value`` arrives as a ``Decimal`` from a numeric column;
        floats are what the API and the delivery templates want.
        """
        data = dict(row)
        if data.get("offer_id") is not None:
            data["offer_id"] = str(data["offer_id"])
        if isinstance(data.get("discount_value"), Decimal):
            data["discount_value"] = float(data["discount_value"])
        return cls(**data)


class CouponOfferCreate(BaseModel):
    """Payload accepted to create an offer."""

    model_config = ConfigDict(
        use_enum_values=True, validate_default=True, extra="forbid"
    )

    code: str = Field(..., min_length=1, max_length=CODE_MAX_LENGTH)
    name: str = ""
    description: str = ""
    discount_type: DiscountType = DiscountType.PERCENT
    discount_value: float = Field(default=0.0, ge=0)
    currency: str = "EUR"
    valid_days: int = Field(default=30, ge=1, le=3650)
    max_per_guest: int = Field(default=1, ge=0, le=1000)
    budget_period: BudgetPeriod = BudgetPeriod.TOTAL
    max_coupons: int = Field(default=0, ge=0)
    active: bool = True
    terms: str = ""

    @field_validator("code")
    @classmethod
    def _normalise_code(cls, value: str) -> str:
        """Offer codes are uppercase and unspaced.

        Normalised rather than rejected: a rule referring to ``recover20``
        and an offer stored as ``RECOVER20`` would never meet, and the
        mismatch would look like an eligibility bug.
        """
        value = value.strip().upper().replace(" ", "")
        if not value:
            raise ValueError("an offer needs a code")
        return value


class CouponOfferUpdate(BaseModel):
    """Partial amendment. Absent fields are left alone.

    ``code`` is absent deliberately: coupons already issued reference this
    offer, and eligibility rules name it by code. Renaming it in place would
    silently detach both.
    """

    model_config = ConfigDict(
        use_enum_values=True, validate_default=True, extra="forbid"
    )

    name: Optional[str] = None
    description: Optional[str] = None
    discount_type: Optional[DiscountType] = None
    discount_value: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = None
    valid_days: Optional[int] = Field(default=None, ge=1, le=3650)
    max_per_guest: Optional[int] = Field(default=None, ge=0, le=1000)
    budget_period: Optional[BudgetPeriod] = None
    max_coupons: Optional[int] = Field(default=None, ge=0)
    active: Optional[bool] = None
    terms: Optional[str] = None

    def changes(self) -> dict[str, Any]:
        """Return only the fields the caller actually supplied."""
        return self.model_dump(exclude_none=True)


class CouponBudget(BaseModel):
    """One offer's issuance counter for one period."""

    model_config = ConfigDict(validate_default=True)

    budget_id: str = ""
    tenant_id: str = ""
    offer_id: str = ""
    period_start: Optional[date] = None
    max_coupons: int = 0
    issued_count: int = 0

    @property
    def exhausted(self) -> bool:
        """Whether this period's allowance is spent.

        ``max_coupons == 0`` means unlimited, so it is never exhausted.
        """
        return self.max_coupons > 0 and self.issued_count >= self.max_coupons

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "CouponBudget":
        """Build a budget from a database row."""
        data = dict(row)
        for key in ("budget_id", "offer_id"):
            if data.get(key) is not None:
                data[key] = str(data[key])
        return cls(**data)


class Coupon(BaseModel):
    """A coupon in a guest's hands.

    Attributes:
        coupon_id: Surrogate key.
        tenant_id: Owning tenant.
        offer_id: The offer it was issued against.
        code: The redeemable code, unique per tenant.
        guest_id: Who holds it, when known.
        review_id: The review that earned it, when there was one.
        status: Where it is in its life.
        issued_at: When it was created.
        expires_at: After which it can no longer be redeemed.
        delivered_at: When it reached the guest.
        redeemed_at: When it was spent.
        redeemed_by: Who accepted it, for the audit trail.
    """

    model_config = ConfigDict(use_enum_values=True, validate_default=True)

    coupon_id: str = ""
    tenant_id: str = ""
    offer_id: str = ""
    code: str = ""
    guest_id: str = ""
    review_id: str = ""
    status: CouponStatus = CouponStatus.ISSUED
    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    redeemed_at: Optional[datetime] = None
    redeemed_by: str = ""

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Coupon":
        """Build a coupon from a database row."""
        data = dict(row)
        for key in ("coupon_id", "offer_id", "guest_id", "review_id"):
            data[key] = str(data[key]) if data.get(key) is not None else ""
        return cls(**data)


class CouponEvent(BaseModel):
    """One entry in a coupon's append-only trail."""

    model_config = ConfigDict(validate_default=True)

    event_id: str = ""
    tenant_id: str = ""
    coupon_id: str = ""
    event: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    actor: str = ""
    created_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "CouponEvent":
        """Build an event from a database row."""
        import json

        data = dict(row)
        for key in ("event_id", "coupon_id"):
            if data.get(key) is not None:
                data[key] = str(data[key])
        detail = data.get("detail")
        if isinstance(detail, str):
            data["detail"] = json.loads(detail or "{}")
        elif detail is None:
            data["detail"] = {}
        return cls(**data)


__all__ = (
    "CODE_MAX_LENGTH",
    "REDEEMABLE_STATUSES",
    "BudgetPeriod",
    "Coupon",
    "CouponBudget",
    "CouponEvent",
    "CouponOffer",
    "CouponOfferCreate",
    "CouponOfferUpdate",
    "CouponStatus",
    "DiscountType",
)
