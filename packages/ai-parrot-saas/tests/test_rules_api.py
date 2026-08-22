"""The rules API over HTTP, end to end against Postgres.

Includes the authorization split, because "an operator may read the rules but
not change them" is a policy claim that has to be exercised rather than
asserted in a comment.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import web
from asyncdb import AsyncDB

from parrot_saas.handlers.setup import setup_saas_api
from parrot_saas.handlers.tenants import APP_TENANT_REPOSITORY, APP_TENANT_RUNTIMES
from parrot_saas.tenancy.middleware import TENANT_HEADER

pytestmark = pytest.mark.integration

CONTROL = "/api/v1/saas/control/tenants"
RULES = "/api/v1/saas/rules"
HDR = {TENANT_HEADER: "bar-pepe"}

POLICY_DIR = Path(__file__).resolve().parents[3] / "policies"

RULE = {
    "name": "recover_detractor",
    "priority": 100,
    "conditions": {"ctx.rating": {"lte": 2}, "ctx.consent_marketing": True},
    "result": {"offer_code": "RECOVER20", "reason": "detractor_recovery"},
}


class _PDP:
    """Minimal stand-in holding a real ``PolicyEvaluator``."""

    def __init__(self, evaluator) -> None:
        self._evaluator = evaluator


def _evaluator():
    """A PolicyEvaluator loaded from the repository's policy directory."""
    from navigator_auth.abac.policies.evaluator import PolicyEvaluator, PolicyLoader

    evaluator = PolicyEvaluator(cache_ttl_seconds=1)
    evaluator.load_policies(PolicyLoader.load_from_directory(POLICY_DIR))
    return evaluator


@pytest.fixture
async def client_factory(
    aiohttp_client, test_dsn: str, unique_schema: str, secret_store
):
    """Build a wired app whose requests carry a chosen set of user groups."""

    async def _build(*groups: str, with_pdp: bool = False):
        @web.middleware
        async def _fake_session(request, handler):
            request["session"] = {
                "session": {"username": "someone", "groups": list(groups)}
            }
            return await handler(request)

        app = web.Application()
        app.middlewares.append(_fake_session)
        setup_saas_api(
            app,
            dsn=test_dsn,
            schema=unique_schema,
            secret_store=secret_store,
            require_auth=False,
        )
        if with_pdp:
            app["abac"] = _PDP(_evaluator())
        http = await aiohttp_client(app)
        await http.post(
            CONTROL,
            json={
                "tenant_id": "bar-pepe",
                "name": "Bar Pepe",
                "timezone": "Europe/Madrid",
            },
        )
        return http

    try:
        yield _build
    finally:
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


@pytest.fixture
async def client(client_factory):
    """A wired app with no policy engine (authorization tested separately)."""
    return await client_factory("tenant_admin")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def test_create_and_list(client) -> None:
    """A created rule appears in the listing, with the vocabulary alongside."""
    created = await client.post(RULES, json=RULE, headers=HDR)

    assert created.status == 201
    body = await (await client.get(RULES, headers=HDR)).json()
    assert body["count"] == 1
    assert body["rules"][0]["name"] == "recover_detractor"
    assert any(
        v["field"] == "ctx.rating" for v in body["vocabulary"]
    ), "the listing ships the vocabulary so clients need not hard-code it"


async def test_a_duplicate_name_is_409_not_400(client) -> None:
    """``BaseView.error()`` would degrade this to a 400."""
    await client.post(RULES, json=RULE, headers=HDR)

    resp = await client.post(RULES, json=RULE, headers=HDR)

    assert resp.status == 409
    assert (await resp.json())["error"] == "rule_exists"


async def test_patch_and_delete(client) -> None:
    """Amend in place, then remove."""
    created = await (await client.post(RULES, json=RULE, headers=HDR)).json()

    patched = await client.patch(
        f"{RULES}/{created['rule_id']}", json={"priority": 5}, headers=HDR
    )
    deleted = await client.delete(f"{RULES}/{created['rule_id']}", headers=HDR)

    assert (await patched.json())["priority"] == 5
    assert deleted.status == 204
    assert (await (await client.get(RULES, headers=HDR)).json())["count"] == 0


async def test_an_unknown_rule_is_404(client) -> None:
    """Including a malformed id, which must not surface a driver error."""
    assert (await client.patch(f"{RULES}/nope", json={}, headers=HDR)).status == 404
    assert (await client.delete(f"{RULES}/nope", headers=HDR)).status == 404


# ---------------------------------------------------------------------------
# Validation at write time
# ---------------------------------------------------------------------------


async def test_an_unknown_field_is_refused_with_its_name(client) -> None:
    """A typo becomes a 400 now, not a rule that never fires."""
    bad = {**RULE, "conditions": {"ctx.ratingg": {"lte": 2}}}

    resp = await client.post(RULES, json=bad, headers=HDR)

    assert resp.status == 400
    body = await resp.json()
    assert body["error"] == "invalid_rule"
    assert body["field"] == "ctx.ratingg"


async def test_an_unknown_operator_is_refused(client) -> None:
    """Caught by constructing the rule, not by a hand-kept operator list."""
    bad = {**RULE, "conditions": {"ctx.rating": {"roughly": 2}}}

    assert (await client.post(RULES, json=bad, headers=HDR)).status == 400


async def test_an_unknown_payload_field_is_refused(client) -> None:
    """Silence is worse than a 400 here.

    A caller posting ``rule_type: "ComputedRule"`` believes they are creating
    one. Ignoring the field would hand them a ConditionRule without a word —
    safe, but not honest.
    """
    bad = {**RULE, "rule_type": "ComputedRule"}

    resp = await client.post(RULES, json=bad, headers=HDR)

    assert resp.status == 400
    body = await resp.json()
    assert any("rule_type" in d["field"] for d in body["details"])


async def test_a_patch_that_would_break_the_rule_is_refused(client) -> None:
    """The *merged* rule is validated, not just the patch."""
    created = await (await client.post(RULES, json=RULE, headers=HDR)).json()

    resp = await client.patch(
        f"{RULES}/{created['rule_id']}",
        json={"conditions": {"ctx.nonsense": True}},
        headers=HDR,
    )

    assert resp.status == 400
    unchanged = await (await client.get(RULES, headers=HDR)).json()
    assert unchanged["rules"][0]["conditions"] == RULE["conditions"]


async def test_a_priority_out_of_range_is_refused(client) -> None:
    """Bounded so an exclusion can sit below the defaults without silliness."""
    resp = await client.post(
        RULES, json={**RULE, "priority": 10**9}, headers=HDR
    )

    assert resp.status == 400
    assert (await resp.json())["error"] == "validation_error"


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


async def test_dry_run_explains_a_match(client) -> None:
    """The endpoint that turns "my rule doesn't work" into self-service."""
    await client.post(RULES, json=RULE, headers=HDR)

    resp = await client.post(
        f"{RULES}/evaluate",
        json={"context": {"rating": 1, "consent_marketing": True}},
        headers=HDR,
    )

    body = await resp.json()
    assert body["matched"] is True
    assert body["offer"]["offer_code"] == "RECOVER20"
    assert body["rule"] == "recover_detractor"
    assert body["inspected"][0]["matched"] is True
    assert body["evaluated_context"]["ctx.rating"] == 1


async def test_dry_run_explains_a_miss(client) -> None:
    """A non-match is an answer, and the trail says which rules were tried."""
    await client.post(RULES, json=RULE, headers=HDR)

    resp = await client.post(
        f"{RULES}/evaluate", json={"context": {"rating": 5}}, headers=HDR
    )

    body = await resp.json()
    assert body["matched"] is False
    assert body["offer"] is None
    assert [i["matched"] for i in body["inspected"]] == [False]


async def test_dry_run_shows_the_defaults_it_filled_in(client) -> None:
    """A tenant should see the whole context a rule was judged against."""
    resp = await client.post(f"{RULES}/evaluate", json={}, headers=HDR)

    context = (await resp.json())["evaluated_context"]
    assert context["ctx.consent_marketing"] is False
    assert context["ctx.last_coupon_days_ago"] == 3650


async def test_dry_run_reflects_an_unsaved_edit_immediately(client) -> None:
    """It compiles from the rows, not from the cached runtime.

    A tenant testing a change must see the change, not whatever the runtime
    happened to compile half an hour ago.
    """
    created = await (await client.post(RULES, json=RULE, headers=HDR)).json()
    await client.patch(
        f"{RULES}/{created['rule_id']}",
        json={"conditions": {"ctx.rating": {"lte": 1}}},
        headers=HDR,
    )

    resp = await client.post(
        f"{RULES}/evaluate", json={"context": {"rating": 2}}, headers=HDR
    )

    assert (await resp.json())["matched"] is False


async def test_dry_run_stores_nothing(client) -> None:
    """It is read-only in every sense."""
    await client.post(RULES, json=RULE, headers=HDR)

    await client.post(
        f"{RULES}/evaluate", json={"context": {"rating": 1}}, headers=HDR
    )

    assert (await (await client.get(RULES, headers=HDR)).json())["count"] == 1


async def test_dry_run_uses_the_tenants_timezone(client) -> None:
    """A weekend rule must fire on the venue's Saturday, not UTC's."""
    await client.post(
        RULES,
        json={
            "name": "weekend",
            "priority": 10,
            "conditions": {"env.is_weekend": True},
            "result": {"offer_code": "WKND"},
        },
        headers=HDR,
    )

    # 21:30 UTC on Saturday is 23:30 Saturday in Madrid — still the weekend.
    resp = await client.post(
        f"{RULES}/evaluate",
        json={"context": {}, "now": "2026-05-02T21:30:00Z"},
        headers=HDR,
    )

    assert (await resp.json())["matched"] is True


async def test_dry_run_refuses_a_bad_context(client) -> None:
    """A list is not a context."""
    resp = await client.post(
        f"{RULES}/evaluate", json={"context": [1, 2]}, headers=HDR
    )

    assert resp.status == 400


# ---------------------------------------------------------------------------
# Isolation and runtime invalidation
# ---------------------------------------------------------------------------


async def test_rules_are_scoped_to_the_asking_tenant(client) -> None:
    """Two tenants, two rulesets, no crossover."""
    await client.post(CONTROL, json={"tenant_id": "hotel-x", "name": "Hotel X"})
    await client.post(RULES, json=RULE, headers=HDR)

    theirs = await (
        await client.get(RULES, headers={TENANT_HEADER: "hotel-x"})
    ).json()

    assert theirs["count"] == 0


async def _warm_runtime(client):
    """Build and cache the fixture tenant's runtime."""
    repo = client.app[APP_TENANT_REPOSITORY]
    cache = client.app[APP_TENANT_RUNTIMES]
    tenant = await repo.get("bar-pepe")
    await cache.get(tenant.to_context())
    assert "bar-pepe" in cache
    return cache


async def test_creating_a_rule_invalidates_the_cached_runtime(client) -> None:
    """A live runtime holds the ruleset compiled from the previous rules."""
    cache = await _warm_runtime(client)

    await client.post(RULES, json=RULE, headers=HDR)

    assert "bar-pepe" not in cache


async def test_deleting_a_rule_invalidates_the_cached_runtime(client) -> None:
    """Switching an offer off must take effect, not wait for a TTL."""
    created = await (await client.post(RULES, json=RULE, headers=HDR)).json()
    cache = await _warm_runtime(client)

    await client.delete(f"{RULES}/{created['rule_id']}", headers=HDR)

    assert "bar-pepe" not in cache


async def test_the_runtime_carries_the_compiled_ruleset(client) -> None:
    """The payoff: a rule written over HTTP reaches the flow's runtime."""
    await client.post(RULES, json=RULE, headers=HDR)
    repo = client.app[APP_TENANT_REPOSITORY]
    cache = client.app[APP_TENANT_RUNTIMES]

    runtime = await cache.get((await repo.get("bar-pepe")).to_context())

    assert runtime.ruleset is not None
    assert len(runtime.ruleset) == 1
    assert runtime.ruleset.rules[0].name == "recover_detractor"


async def test_a_disabled_rule_is_not_compiled_into_the_runtime(client) -> None:
    """What the flow evaluates is what the tenant switched on."""
    created = await (await client.post(RULES, json=RULE, headers=HDR)).json()
    await client.patch(
        f"{RULES}/{created['rule_id']}", json={"enabled": False}, headers=HDR
    )
    repo = client.app[APP_TENANT_REPOSITORY]
    cache = client.app[APP_TENANT_RUNTIMES]

    runtime = await cache.get((await repo.get("bar-pepe")).to_context())

    assert len(runtime.ruleset) == 0


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


async def test_an_operator_may_read_but_not_write(client_factory) -> None:
    """Answer "why did this guest get an offer?" without being able to change
    who gets one."""
    operator = await client_factory("tenant_operator", with_pdp=True)

    listing = await operator.get(RULES, headers=HDR)
    dry_run = await operator.post(
        f"{RULES}/evaluate", json={"context": {}}, headers=HDR
    )
    write = await operator.post(RULES, json=RULE, headers=HDR)
    delete = await operator.delete(f"{RULES}/nope", headers=HDR)

    assert listing.status == 200
    assert dry_run.status == 200
    assert write.status == 403
    assert delete.status == 403


async def test_an_admin_may_write(client_factory) -> None:
    """The shipped policy grants rule management to tenant admins."""
    admin = await client_factory("tenant_admin", with_pdp=True)

    assert (await admin.post(RULES, json=RULE, headers=HDR)).status == 201


async def test_a_stranger_may_not_even_read(client_factory) -> None:
    """Deny by default: no policy matched means no access."""
    nobody = await client_factory(with_pdp=True)

    assert (await nobody.get(RULES, headers=HDR)).status == 403
