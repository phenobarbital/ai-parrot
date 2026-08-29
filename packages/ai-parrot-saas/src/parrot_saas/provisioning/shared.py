"""The deployer for a tenant that runs on the shared plane.

There is no infrastructure to build — the tenant is a row and a set of
predicates — so what "provisioning" means here is making the tenant *usable*:
a coupon offer its rules can name, the default eligibility ruleset, and a
warmed runtime so the first review does not pay for a cold start.

It implements the same port as the Pulumi deployer on purpose. The control
plane then has one code path, one status machine and one set of tests for both
tenancy modes, and the difference between them stays where it belongs — in
what gets built, not in how the platform asks for it.

**Seeding is additive and never overwrites.** A tenant that already edited its
rules and then had ``apply`` run again — a retry, a re-provision, an operator
clicking twice — must not have its own configuration replaced by the defaults.
Every seed is "create if absent", and an existing row is left exactly as it is.
"""
from __future__ import annotations

from typing import Any, Optional

from navconfig.logging import logging

from ..tenancy.context import TenantContext
from .base import TenantDeployer
from .models import DeploymentResult, DeploymentStatus

logger = logging.getLogger("parrot_saas.provisioning.shared")

#: The offer the default ``recover_detractor`` rule names. Seeding the rule
#: without the offer would produce a tenant whose first detractor is judged
#: eligible and then refused with ``unknown_offer`` — a silent dead end.
DEFAULT_OFFER = {
    "code": "RECOVER20",
    "name": "20% off your next visit",
    "description": "A goodwill gesture for a guest we let down.",
    "discount_type": "percent",
    "discount_value": 20.0,
    "valid_days": 30,
    "max_per_guest": 1,
    "budget_period": "month",
    # Not unlimited. A brand-new tenant with an uncapped offer and an
    # automated flow issuing it is the shape of an expensive accident, so the
    # default is a number they can raise deliberately.
    "max_coupons": 50,
    "terms": "One coupon per guest. Not valid with other offers.",
}


class SharedDeployer(TenantDeployer):
    """Prepares a tenant to be served by the shared plane.

    Args:
        rules: Rule repository, for seeding the default eligibility ruleset.
        coupons: Coupon repository, for seeding the default offer.
        runtimes: Runtime cache, warmed so the first review is not a cold
            start — and, more usefully, so a configuration problem surfaces
            during provisioning rather than under the first real guest.
        seed: Whether to seed defaults at all. A deployment that provisions
            tenants from its own templates turns this off.
    """

    name = "shared"

    def __init__(
        self,
        *,
        rules: Optional[Any] = None,
        coupons: Optional[Any] = None,
        runtimes: Optional[Any] = None,
        seed: bool = True,
    ) -> None:
        self._rules = rules
        self._coupons = coupons
        self._runtimes = runtimes
        self._seed = seed

    async def plan(self, tenant: TenantContext) -> DeploymentResult:
        """Report what applying would seed, without writing anything."""
        missing = await self._missing(tenant.tenant_id)
        return DeploymentResult(
            tenant_id=tenant.tenant_id,
            operation="plan",
            success=True,
            status=DeploymentStatus.PENDING,
            summary={"create": len(missing)},
            outputs={"plane": "shared", "would_create": missing},
            detail=(
                "nothing to seed; this tenant is already configured"
                if not missing
                else f"would seed: {', '.join(missing)}"
            ),
        )

    async def apply(self, tenant: TenantContext) -> DeploymentResult:
        """Seed the tenant's defaults and warm its runtime.

        Idempotent: a second apply creates nothing and reports ``ready``.
        """
        created: list[str] = []
        problems: list[str] = []

        if self._seed:
            created.extend(await self._seed_offer(tenant, problems))
            created.extend(await self._seed_rules(tenant, problems))

        warmed = await self._warm(tenant, problems)

        # A seeding failure is a real failure: a tenant left without the offer
        # its rules name looks provisioned and answers no one with a coupon.
        success = not problems
        return DeploymentResult(
            tenant_id=tenant.tenant_id,
            operation="apply",
            success=success,
            status=DeploymentStatus.READY if success else DeploymentStatus.FAILED,
            summary={"create": len(created)},
            outputs={"plane": "shared", "seeded": created, "runtime_warmed": warmed},
            detail=(
                f"seeded {len(created)} default(s)"
                if success
                else "; ".join(problems)
            ),
        )

    async def destroy(self, tenant: TenantContext) -> DeploymentResult:
        """Release what the shared plane holds for this tenant.

        Only the live runtime, which is the only thing here that is
        *infrastructure*. The tenant's reviews, coupons and rules are its
        data: deleting them is what suspending or deleting the tenant means,
        and doing it from a deployer would turn "stop serving this tenant" into
        "destroy their history" — a very different, unrecoverable act.
        """
        if self._runtimes is not None:
            await self._runtimes.invalidate(tenant.tenant_id)
        return DeploymentResult(
            tenant_id=tenant.tenant_id,
            operation="destroy",
            success=True,
            status=DeploymentStatus.DESTROYED,
            detail=(
                "released the tenant's runtime; its data is untouched and is "
                "removed by deleting the tenant, not by destroying its "
                "deployment"
            ),
        )

    async def status(self, tenant: TenantContext) -> DeploymentResult:
        """Report whether the tenant is configured enough to be served."""
        missing = await self._missing(tenant.tenant_id)
        ready = not missing
        return DeploymentResult(
            tenant_id=tenant.tenant_id,
            operation="status",
            success=True,
            status=DeploymentStatus.READY if ready else DeploymentStatus.PENDING,
            outputs={"plane": "shared", "missing": missing},
            detail="ready" if ready else f"not yet seeded: {', '.join(missing)}",
        )

    # -- seeding -----------------------------------------------------------

    async def _missing(self, tenant_id: str) -> list[str]:
        """Return the names of the defaults this tenant does not yet have."""
        missing: list[str] = []
        if self._coupons is not None:
            try:
                offer = await self._coupons.get_offer_by_code(
                    tenant_id, DEFAULT_OFFER["code"]
                )
                if offer is None:
                    missing.append(f"offer:{DEFAULT_OFFER['code']}")
            except Exception as exc:  # noqa: BLE001 - reported, not raised
                logger.warning("could not read offers for %s: %s", tenant_id, exc)
        if self._rules is not None:
            try:
                existing = {rule.name for rule in await self._rules.list_rules(tenant_id)}
                from ..rules.builder import DEFAULT_ELIGIBILITY_RULES

                missing.extend(
                    f"rule:{spec['name']}"
                    for spec in DEFAULT_ELIGIBILITY_RULES
                    if spec["name"] not in existing
                )
            except Exception as exc:  # noqa: BLE001 - reported, not raised
                logger.warning("could not read rules for %s: %s", tenant_id, exc)
        return missing

    async def _seed_offer(
        self, tenant: TenantContext, problems: list[str]
    ) -> list[str]:
        """Create the default offer, unless the tenant already has one."""
        if self._coupons is None:
            return []
        from ..coupons.models import CouponOfferCreate
        from ..coupons.repository import OfferAlreadyExists

        try:
            await self._coupons.create_offer(
                tenant.tenant_id, CouponOfferCreate(**DEFAULT_OFFER)
            )
        except OfferAlreadyExists:
            # The tenant's own offer wins. Replacing it would silently reset a
            # discount they had deliberately changed.
            return []
        except Exception as exc:  # noqa: BLE001 - surfaced as a failed apply
            problems.append(f"could not seed the default offer: {exc}")
            return []
        return [f"offer:{DEFAULT_OFFER['code']}"]

    async def _seed_rules(
        self, tenant: TenantContext, problems: list[str]
    ) -> list[str]:
        """Create the default eligibility rules the tenant is missing."""
        if self._rules is None:
            return []
        from ..rules.builder import DEFAULT_ELIGIBILITY_RULES
        from ..rules.models import RuleCreate
        from ..rules.repository import RuleAlreadyExists

        created: list[str] = []
        for spec in DEFAULT_ELIGIBILITY_RULES:
            try:
                await self._rules.create(tenant.tenant_id, RuleCreate(**spec))
            except RuleAlreadyExists:
                continue
            except Exception as exc:  # noqa: BLE001 - surfaced as a failure
                problems.append(f"could not seed rule {spec['name']!r}: {exc}")
                continue
            created.append(f"rule:{spec['name']}")
        return created

    async def _warm(self, tenant: TenantContext, problems: list[str]) -> bool:
        """Build the tenant's runtime now rather than under the first guest.

        A failure here is reported but does not fail the apply. The runtime
        builder is deliberately tolerant — a tenant with no API key yet still
        gets a runtime, with the flow's deterministic fallbacks — so the only
        way this raises is a genuine outage, and refusing to provision a tenant
        because a dependency blinked would be the wrong trade.
        """
        if self._runtimes is None:
            return False
        try:
            await self._runtimes.get(tenant)
        except Exception as exc:  # noqa: BLE001 - warned, not fatal
            logger.warning(
                "could not warm the runtime for %s: %s", tenant.tenant_id, exc
            )
            return False
        return True


__all__ = ("DEFAULT_OFFER", "SharedDeployer")
