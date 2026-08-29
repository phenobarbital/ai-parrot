"""The shared-plane deployer: seeding a tenant into a usable state.

The two properties worth protecting are both about *not* doing damage:

* **Seeding is additive.** A tenant that edited its own rules and then had
  ``apply`` run again — a retry, a re-provision, an operator clicking twice —
  must not have its configuration replaced by the defaults.
* **Destroy releases, it does not delete.** Tearing down a deployment must not
  take the tenant's reviews and coupons with it. "Stop serving this tenant"
  and "erase their history" are very different acts and only one of them is
  recoverable.
"""
from __future__ import annotations

import pytest

from parrot_saas.provisioning.models import DeploymentStatus
from parrot_saas.provisioning.shared import DEFAULT_OFFER, SharedDeployer
from parrot_saas.rules.builder import DEFAULT_ELIGIBILITY_RULES
from parrot_saas.tenancy.context import TenantContext


@pytest.fixture
def tenant() -> TenantContext:
    """The tenant being provisioned."""
    return TenantContext(tenant_id="bar-pepe", name="Bar Pepe")


class _Rule:
    def __init__(self, name: str) -> None:
        self.name = name


class _Rules:
    """Stand-in for ``RuleRepository``."""

    def __init__(self, existing=(), *, fail=None) -> None:
        self.rules = [_Rule(name) for name in existing]
        self.fail = fail
        self.created: list = []

    async def list_rules(self, tenant_id, **kw):
        return list(self.rules)

    async def create(self, tenant_id, payload):
        from parrot_saas.rules.repository import RuleAlreadyExists

        if self.fail is not None:
            raise self.fail
        if any(rule.name == payload.name for rule in self.rules):
            raise RuleAlreadyExists(payload.name)
        self.rules.append(_Rule(payload.name))
        self.created.append((tenant_id, payload.name))
        return payload


class _Coupons:
    """Stand-in for ``CouponRepository``."""

    def __init__(self, existing=(), *, fail=None) -> None:
        self.codes = list(existing)
        self.fail = fail
        self.created: list = []

    async def get_offer_by_code(self, tenant_id, code):
        return object() if code in self.codes else None

    async def create_offer(self, tenant_id, payload):
        from parrot_saas.coupons.repository import OfferAlreadyExists

        if self.fail is not None:
            raise self.fail
        if payload.code in self.codes:
            raise OfferAlreadyExists(payload.code)
        self.codes.append(payload.code)
        self.created.append((tenant_id, payload.code))
        return payload


class _Runtimes:
    """Stand-in for ``TenantRuntimeCache``."""

    def __init__(self, *, fail=None) -> None:
        self.warmed: list = []
        self.invalidated: list = []
        self.fail = fail

    async def get(self, tenant):
        if self.fail is not None:
            raise self.fail
        self.warmed.append(tenant.tenant_id)
        return object()

    async def invalidate(self, tenant_id):
        self.invalidated.append(tenant_id)


def _deployer(**kw) -> SharedDeployer:
    kw.setdefault("rules", _Rules())
    kw.setdefault("coupons", _Coupons())
    kw.setdefault("runtimes", _Runtimes())
    return SharedDeployer(**kw)


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_seeds_the_offer_and_the_rules(tenant):
    """A fresh tenant comes out able to answer a review with a coupon."""
    rules, coupons, runtimes = _Rules(), _Coupons(), _Runtimes()
    deployer = _deployer(rules=rules, coupons=coupons, runtimes=runtimes)

    result = await deployer.apply(tenant)

    assert result.success is True
    assert result.status == DeploymentStatus.READY.value
    assert coupons.created == [("bar-pepe", DEFAULT_OFFER["code"])]
    assert [name for _, name in rules.created] == [
        spec["name"] for spec in DEFAULT_ELIGIBILITY_RULES
    ]
    assert runtimes.warmed == ["bar-pepe"]


@pytest.mark.asyncio
async def test_the_seeded_rule_names_the_seeded_offer(tenant):
    """Seeding one without the other is a silent dead end.

    A rule naming ``RECOVER20`` with no such offer produces a guest who is
    judged eligible and then refused with ``unknown_offer`` — a flow that
    looks configured and gives nobody anything.
    """
    named = {
        spec["result"]["offer_code"]
        for spec in DEFAULT_ELIGIBILITY_RULES
        if spec["result"].get("offer_code")
    }

    assert DEFAULT_OFFER["code"] in named


@pytest.mark.asyncio
async def test_apply_is_idempotent(tenant):
    """A second apply creates nothing and still reports ready."""
    rules, coupons = _Rules(), _Coupons()
    deployer = _deployer(rules=rules, coupons=coupons)

    await deployer.apply(tenant)
    created_after_first = len(rules.created) + len(coupons.created)
    second = await deployer.apply(tenant)

    assert second.success is True
    assert second.status == DeploymentStatus.READY.value
    assert len(rules.created) + len(coupons.created) == created_after_first
    assert second.summary["create"] == 0


@pytest.mark.asyncio
async def test_a_tenants_own_configuration_is_never_replaced(tenant):
    """The most damaging thing a re-provision could do."""
    rules = _Rules(existing=["recover_detractor"])
    coupons = _Coupons(existing=[DEFAULT_OFFER["code"]])
    deployer = _deployer(rules=rules, coupons=coupons)

    result = await deployer.apply(tenant)

    assert result.success is True
    assert coupons.created == []
    assert all(name != "recover_detractor" for _, name in rules.created)


@pytest.mark.asyncio
async def test_a_seeding_failure_fails_the_apply(tenant):
    """A tenant without the offer its rules name is not provisioned."""
    deployer = _deployer(coupons=_Coupons(fail=RuntimeError("db down")))

    result = await deployer.apply(tenant)

    assert result.success is False
    assert result.status == DeploymentStatus.FAILED.value
    assert "db down" in result.detail


@pytest.mark.asyncio
async def test_a_cold_runtime_does_not_fail_the_apply(tenant):
    """The builder is tolerant by design; a blink must not block onboarding."""
    deployer = _deployer(runtimes=_Runtimes(fail=RuntimeError("redis down")))

    result = await deployer.apply(tenant)

    assert result.success is True
    assert result.outputs["runtime_warmed"] is False


# ---------------------------------------------------------------------------
# Plan, status, destroy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_writes_nothing(tenant):
    """A plan that seeded would not be a plan."""
    rules, coupons = _Rules(), _Coupons()
    deployer = _deployer(rules=rules, coupons=coupons)

    result = await deployer.plan(tenant)

    assert result.success is True
    assert result.summary["create"] == 1 + len(DEFAULT_ELIGIBILITY_RULES)
    assert rules.created == []
    assert coupons.created == []


@pytest.mark.asyncio
async def test_status_reports_pending_until_seeded(tenant):
    """The control plane's "is this tenant usable yet?"."""
    rules, coupons = _Rules(), _Coupons()
    deployer = _deployer(rules=rules, coupons=coupons)

    before = await deployer.status(tenant)
    await deployer.apply(tenant)
    after = await deployer.status(tenant)

    assert before.status == DeploymentStatus.PENDING.value
    assert before.outputs["missing"]
    assert after.status == DeploymentStatus.READY.value
    assert after.outputs["missing"] == []


@pytest.mark.asyncio
async def test_destroy_releases_the_runtime_and_keeps_the_data(tenant):
    """Tearing down a deployment is not deleting a tenant."""
    rules = _Rules(existing=["recover_detractor"])
    coupons = _Coupons(existing=[DEFAULT_OFFER["code"]])
    runtimes = _Runtimes()
    deployer = _deployer(rules=rules, coupons=coupons, runtimes=runtimes)

    result = await deployer.destroy(tenant)

    assert result.success is True
    assert result.status == DeploymentStatus.DESTROYED.value
    assert runtimes.invalidated == ["bar-pepe"]
    # Nothing was removed.
    assert coupons.codes == [DEFAULT_OFFER["code"]]
    assert [rule.name for rule in rules.rules] == ["recover_detractor"]


@pytest.mark.asyncio
async def test_a_deployer_with_no_repositories_still_works(tenant):
    """The graph has to be runnable with nothing wired, here as everywhere."""
    result = await SharedDeployer().apply(tenant)

    assert result.success is True
    assert result.status == DeploymentStatus.READY.value
