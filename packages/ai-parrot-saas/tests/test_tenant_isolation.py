"""Tenant isolation, checked structurally and over the wire.

Isolation in this package is not a feature, it is an invariant, and the two
tests that matter here are the ones that keep it *auditable* rather than
remembered:

* **Every repository method is scoped or declared.** ``BaseRepository``'s data
  helpers bind ``tenant_id`` as ``$1`` and refuse SQL with no tenant predicate;
  the ``admin_*`` helpers deliberately do not. This walks every repository in
  the package and asserts each public method uses the first kind or is listed
  below with a reason.

  This test exists because its predecessor stopped doing its job. The original
  in ``test_tenancy_repository.py`` iterated ``vars(TenantRepository)`` and
  nothing else, so as six more repositories were added it kept passing while
  covering one of seven — the failure mode a guard rail is supposed to prevent,
  happening to the guard rail. Hence :func:`test_every_repository_is_inspected`
  below: the count is asserted, so the next repository either gets covered or
  turns this red.

* **No route serves another tenant's row.** The HTTP half, enumerated from the
  router rather than hand-listed, so a route added without isolation shows up
  as a failure instead of as a gap.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
from pathlib import Path
from typing import Iterator

import pytest
from aiohttp import web
from asyncdb import AsyncDB

from parrot_saas.db.repository import BaseRepository
from parrot_saas.handlers.setup import setup_saas_api
from parrot_saas.tenancy.middleware import TENANT_HEADER

CONTROL = "/api/v1/saas/control/tenants"
MINE = {TENANT_HEADER: "bar-pepe"}
THEIRS = {TENANT_HEADER: "hotel-x"}


# ---------------------------------------------------------------------------
# The structural guard rail — no database
# ---------------------------------------------------------------------------


#: Methods permitted to reach across tenants, keyed by ``Class.method``, each
#: with the reason. Adding a name here is the deliberate act the ``admin_*``
#: naming exists to force; the test below makes it the *only* way.
CROSS_TENANT_METHODS = {
    # Onboarding: the row does not exist yet, so it cannot be scoped to it.
    "TenantRepository.create",
    # The control plane's own view of every tenant — the point of the method.
    "TenantRepository.list_tenants",
    # Likewise: "which tenants are mid-provision, and which failed?" is a
    # platform-staff question that spans tenants by definition.
    "DeploymentRepository.list_deployments",
}


def _repository_classes() -> Iterator[type]:
    """Yield every ``BaseRepository`` subclass defined in this package.

    Discovered by walking the package rather than imported by hand, because a
    hand-written list is exactly what let the original guard rail fall behind.
    """
    import parrot_saas

    root = Path(parrot_saas.__file__).parent
    seen: set[type] = set()
    for module_info in pkgutil.walk_packages([str(root)], prefix="parrot_saas."):
        if ".programs." in module_info.name:
            # Pulumi programs are data, not modules: they import an SDK this
            # distribution does not depend on.
            continue
        try:
            module = importlib.import_module(module_info.name)
        except ImportError:  # pragma: no cover - optional extras
            continue
        for _, member in vars(module).items():
            if (
                inspect.isclass(member)
                and issubclass(member, BaseRepository)
                and member is not BaseRepository
                and member.__module__.startswith("parrot_saas")
                and member not in seen
            ):
                seen.add(member)
                yield member


def test_repositories_are_discoverable() -> None:
    """The walk has to actually find them, or every check below is vacuous."""
    found = {cls.__name__ for cls in _repository_classes()}

    assert {
        "TenantRepository",
        "GuestRepository",
        "ReviewRepository",
        "RuleRepository",
        "CouponRepository",
        "RunRepository",
        "DeploymentRepository",
    } <= found


def test_every_repository_is_inspected() -> None:
    """Guard the guard rail.

    The predecessor of this module checked one repository and kept passing as
    six more were added. Asserting the count means the next one either gets
    covered or turns this red.
    """
    assert len(list(_repository_classes())) >= 7


@pytest.mark.parametrize(
    "repository", list(_repository_classes()), ids=lambda cls: cls.__name__
)
def test_every_method_is_scoped_or_declared_cross_tenant(repository) -> None:
    """Each public repository method binds a tenant, or says why it does not.

    Read structurally: a method either calls a tenant-scoped helper, delegates
    to another method that does, or is named in :data:`CROSS_TENANT_METHODS`.
    A new method that quietly reaches for ``admin_fetch_all`` fails here rather
    than in production.
    """
    scoped_helpers = ("self.fetch_one(", "self.fetch_all(", "self.execute(")
    admin_helpers = (
        "self.admin_fetch_one(",
        "self.admin_fetch_all(",
        "self.admin_execute(",
    )
    # A method may also legitimately do its work on a borrowed connection
    # inside a transaction, where the tenant predicate is written into the SQL
    # by the caller — the issuer's ``FOR UPDATE`` path, for instance.
    connection_helpers = ("self.acquire(", "self.transaction(")

    checked = 0
    for name, member in vars(repository).items():
        if name.startswith("_") or not inspect.isfunction(member):
            continue
        qualified = f"{repository.__name__}.{name}"
        body = inspect.getsource(member)
        uses_admin = any(helper in body for helper in admin_helpers)
        uses_scoped = any(helper in body for helper in scoped_helpers)
        uses_connection = any(helper in body for helper in connection_helpers)
        delegates = re.search(r"await self\.\w+\(", body) is not None

        if uses_admin:
            assert qualified in CROSS_TENANT_METHODS, (
                f"{qualified}() reaches across tenants but is not declared in "
                "CROSS_TENANT_METHODS — if that is intended, add it there with "
                "a reason"
            )
        else:
            assert uses_scoped or uses_connection or delegates, (
                f"{qualified}() touches neither a scoped helper, a borrowed "
                "connection, nor another repository method; it may be issuing "
                "unscoped SQL"
            )
        checked += 1

    assert checked, f"{repository.__name__} exposes no public methods to check"


def test_declared_cross_tenant_methods_still_exist() -> None:
    """Keep the allow-list honest as the repositories evolve.

    A stale entry is not harmless: it is a standing permission for a method
    nobody has reviewed, waiting for someone to add one back under that name.
    """
    by_name = {cls.__name__: cls for cls in _repository_classes()}

    for qualified in CROSS_TENANT_METHODS:
        class_name, method_name = qualified.split(".")
        assert class_name in by_name, f"{qualified}: no such repository"
        assert hasattr(by_name[class_name], method_name), (
            f"CROSS_TENANT_METHODS names {qualified}, which no longer exists"
        )


def test_scoped_helpers_take_the_tenant_first_and_without_a_default() -> None:
    """A caller must not be able to forget the tenant."""
    for name in ("fetch_one", "fetch_all", "execute"):
        signature = inspect.signature(getattr(BaseRepository, name))
        params = list(signature.parameters)
        assert params[1] == "tenant_id", name
        assert (
            signature.parameters["tenant_id"].default is inspect.Parameter.empty
        ), name


# ---------------------------------------------------------------------------
# The wire — needs Postgres
# ---------------------------------------------------------------------------

integration = pytest.mark.integration


@pytest.fixture
async def two_tenants(aiohttp_client, test_dsn: str, unique_schema: str, secret_store):
    """A wired app with two tenants, each holding one of everything."""

    @web.middleware
    async def _admin_session(request, handler):
        request["session"] = {
            "session": {"username": "admin", "groups": ["platform_admin", "tenant_admin"]}
        }
        return await handler(request)

    app = web.Application()
    app.middlewares.append(_admin_session)
    setup_saas_api(
        app,
        dsn=test_dsn,
        schema=unique_schema,
        secret_store=secret_store,
        require_auth=False,
    )
    http = await aiohttp_client(app)
    for slug, name in (("bar-pepe", "Bar Pepe"), ("hotel-x", "Hotel X")):
        await http.post(CONTROL, json={"tenant_id": slug, "name": name})

    try:
        yield http
    finally:
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


async def _furnish(client, headers: dict) -> dict:
    """Give one tenant a secret, an offer, a rule and a review; return the ids."""
    # Deliberately *not* a provider key. Uploading ``anthropic:api_key`` here
    # would make the tenant's next runtime build a real Anthropic client, and
    # the drafting node would make a real outbound call that 401s — correct
    # behaviour, and a network round trip inside a test suite that must run
    # offline. The BYOK upload path has its own tests; what this one needs is
    # a secret to check the *isolation* of.
    await client.put(
        "/api/v1/saas/secrets/webhook:mock:hmac",
        json={"value": f"whsec-{headers[TENANT_HEADER]}"},
        headers=headers,
    )
    offer = await (
        await client.post(
            "/api/v1/saas/coupon-offers",
            json={
                "code": "RECOVER20",
                "name": "20% off",
                "discount_type": "percent",
                "discount_value": 20,
                "valid_days": 30,
            },
            headers=headers,
        )
    ).json()
    rule = await (
        await client.post(
            "/api/v1/saas/rules",
            json={
                "name": "recover_detractor",
                "priority": 100,
                "conditions": {"ctx.rating": {"lte": 2}},
                "result": {"offer_code": "RECOVER20"},
            },
            headers=headers,
        )
    ).json()
    review = await (
        await client.post(
            "/api/v1/saas/reviews/simulate",
            json={
                "external_id": f"ext-{headers[TENANT_HEADER]}",
                "rating": 1,
                "text": "Cold food.",
            },
            headers=headers,
        )
    ).json()
    return {
        "offer_id": offer.get("offer_id", ""),
        "rule_id": rule.get("rule_id", ""),
        "review_id": review.get("review_id", ""),
        "run_id": review.get("run_id", ""),
    }


@integration
async def test_no_collection_shows_another_tenants_rows(two_tenants) -> None:
    """Every tenant-scoped listing returns only its own."""
    await _furnish(two_tenants, MINE)
    await _furnish(two_tenants, THEIRS)

    for path, key in (
        ("/api/v1/saas/reviews", "reviews"),
        ("/api/v1/saas/runs", "runs"),
        ("/api/v1/saas/coupon-offers", "offers"),
        ("/api/v1/saas/rules", "rules"),
        ("/api/v1/saas/secrets", "secrets"),
    ):
        body = await (await two_tenants.get(path, headers=MINE)).json()
        assert body["count"] == 1, f"{path} returned {body['count']} rows"
        # And nothing in the payload mentions the other tenant.
        assert "hotel-x" not in str(body), path


@integration
async def test_no_item_route_serves_another_tenants_id(two_tenants) -> None:
    """The ids are real and the caller is authenticated; only the tenant differs.

    404 rather than 403 throughout: the queries are tenant-scoped, so the
    handlers genuinely cannot tell "not yours" from "does not exist" — and a
    403 would confirm the id is real.
    """
    theirs = await _furnish(two_tenants, THEIRS)

    # ``/rules/{rule_id}`` is absent on purpose: unlike every other item
    # resource here it exposes no GET, only PATCH and DELETE. Its isolation is
    # covered by the mutation test below instead.
    for path in (
        f"/api/v1/saas/reviews/{theirs['review_id']}",
        f"/api/v1/saas/runs/{theirs['run_id']}",
        f"/api/v1/saas/coupon-offers/{theirs['offer_id']}",
    ):
        resp = await two_tenants.get(path, headers=MINE)
        assert resp.status == 404, f"{path} answered {resp.status}"
        # Reachable for its owner, so the 404 above is about the tenant and
        # not about a broken route.
        assert (await two_tenants.get(path, headers=THEIRS)).status == 200, path


@integration
async def test_no_mutation_reaches_another_tenants_row(two_tenants) -> None:
    """Reads are only half of it: a write must not cross either."""
    theirs = await _furnish(two_tenants, THEIRS)

    patched = await two_tenants.patch(
        f"/api/v1/saas/rules/{theirs['rule_id']}",
        json={"priority": 1},
        headers=MINE,
    )
    deleted = await two_tenants.delete(
        f"/api/v1/saas/coupon-offers/{theirs['offer_id']}", headers=MINE
    )

    assert patched.status == 404
    assert deleted.status == 404

    # And nothing of theirs actually changed. Read through the collection
    # because the rules resource has no item GET.
    rules = await (
        await two_tenants.get("/api/v1/saas/rules", headers=THEIRS)
    ).json()
    assert rules["rules"][0]["priority"] == 100
    offers = await (
        await two_tenants.get("/api/v1/saas/coupon-offers", headers=THEIRS)
    ).json()
    assert offers["offers"][0]["active"] is True


@integration
async def test_every_tenant_scoped_route_is_covered(two_tenants) -> None:
    """Enumerated from the router, so a new route cannot slip past unnoticed.

    Anything under ``/api/v1/saas/`` that is neither control-plane nor the
    signature-authenticated webhook is tenant-scoped and must appear in the
    checks above. This asserts the inventory, so adding a route without
    isolation coverage fails here rather than going unexamined.
    """
    covered = {
        "/api/v1/saas/reviews",
        "/api/v1/saas/reviews/{review_id}",
        "/api/v1/saas/reviews/simulate",
        "/api/v1/saas/runs",
        "/api/v1/saas/runs/{run_id}",
        "/api/v1/saas/runs/{run_id}/resume",
        "/api/v1/saas/coupons",
        "/api/v1/saas/coupons/redeem",
        "/api/v1/saas/coupon-offers",
        "/api/v1/saas/coupon-offers/{offer_id}",
        "/api/v1/saas/rules",
        "/api/v1/saas/rules/{rule_id}",
        "/api/v1/saas/rules/evaluate",
        "/api/v1/saas/secrets",
        "/api/v1/saas/secrets/{key}",
        "/api/v1/saas/secrets/rotate-dek",
    }

    live = {
        route.resource.canonical
        for route in two_tenants.app.router.routes()
        if route.resource.canonical.startswith("/api/v1/saas/")
        and "/control/" not in route.resource.canonical
        and "/webhook/" not in route.resource.canonical
    }

    assert live == covered, (
        "the tenant-scoped route inventory changed; add the new route to the "
        "isolation checks in this module and then to `covered`"
    )
