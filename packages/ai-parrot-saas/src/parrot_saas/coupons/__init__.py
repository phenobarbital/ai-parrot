"""Coupon offers, budgets, issuance and redemption.

Exports are resolved lazily (PEP 562), matching the parent package.
"""
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from .issuer import CouponIssuer, generate_code, period_start
    from .models import (
        BudgetPeriod,
        Coupon,
        CouponBudget,
        CouponEvent,
        CouponOffer,
        CouponOfferCreate,
        CouponOfferUpdate,
        CouponStatus,
        DiscountType,
    )
    from .delivery import CouponDelivery, DeliveryReceipt
    from .repository import (
        CouponRepository,
        GuestCouponHistory,
        OfferAlreadyExists,
        RedemptionError,
    )

__all__ = (
    "BudgetPeriod",
    "Coupon",
    "CouponBudget",
    "CouponDelivery",
    "CouponEvent",
    "CouponIssuer",
    "CouponOffer",
    "CouponOfferCreate",
    "CouponOfferUpdate",
    "CouponRepository",
    "CouponStatus",
    "DeliveryReceipt",
    "DiscountType",
    "GuestCouponHistory",
    "OfferAlreadyExists",
    "RedemptionError",
    "generate_code",
    "period_start",
)

_LAZY_EXPORTS = {
    "CouponIssuer": ("parrot_saas.coupons.issuer", "CouponIssuer"),
    "generate_code": ("parrot_saas.coupons.issuer", "generate_code"),
    "period_start": ("parrot_saas.coupons.issuer", "period_start"),
    "BudgetPeriod": ("parrot_saas.coupons.models", "BudgetPeriod"),
    "Coupon": ("parrot_saas.coupons.models", "Coupon"),
    "CouponBudget": ("parrot_saas.coupons.models", "CouponBudget"),
    "CouponEvent": ("parrot_saas.coupons.models", "CouponEvent"),
    "CouponOffer": ("parrot_saas.coupons.models", "CouponOffer"),
    "CouponOfferCreate": ("parrot_saas.coupons.models", "CouponOfferCreate"),
    "CouponOfferUpdate": ("parrot_saas.coupons.models", "CouponOfferUpdate"),
    "CouponStatus": ("parrot_saas.coupons.models", "CouponStatus"),
    "DiscountType": ("parrot_saas.coupons.models", "DiscountType"),
    "CouponRepository": ("parrot_saas.coupons.repository", "CouponRepository"),
    "OfferAlreadyExists": ("parrot_saas.coupons.repository", "OfferAlreadyExists"),
    "RedemptionError": ("parrot_saas.coupons.repository", "RedemptionError"),
    "GuestCouponHistory": (
        "parrot_saas.coupons.repository",
        "GuestCouponHistory",
    ),
    "CouponDelivery": ("parrot_saas.coupons.delivery", "CouponDelivery"),
    "DeliveryReceipt": ("parrot_saas.coupons.delivery", "DeliveryReceipt"),
}


def __getattr__(name: str) -> Any:
    """Resolve lazily-exported names on first access (PEP 562).

    Args:
        name: Attribute being looked up on the package.

    Returns:
        The resolved object.

    Raises:
        AttributeError: If ``name`` is not a known lazy export.
    """
    try:
        module_path, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None
    from importlib import import_module

    return getattr(import_module(module_path), attr)


def __dir__() -> list[str]:
    """Expose lazy exports to ``dir()`` and tab-completion."""
    return sorted(__all__)
