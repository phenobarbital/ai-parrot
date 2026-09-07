"""Rule persistence and the navrules storage adapter, against Postgres."""
from __future__ import annotations

from typing import AsyncIterator

import pytest
from asyncdb import AsyncDB

from parrot_saas.db.schema import ensure_schema
from parrot_saas.rules.builder import DEFAULT_ELIGIBILITY_RULES, build_ruleset
from parrot_saas.rules.models import RuleCreate, RuleUpdate
from parrot_saas.rules.repository import (
    PostgresRuleStorage,
    RuleAlreadyExists,
    RuleRepository,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def rules(test_dsn: str, unique_schema: str) -> AsyncIterator[RuleRepository]:
    """A rule repository on a throwaway schema with two tenants."""
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

    repository = RuleRepository(test_dsn, schema=unique_schema)
    try:
        yield repository
    finally:
        await repository.aclose()
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


def _create(name: str = "recover", priority: int = 100, **overrides) -> RuleCreate:
    """Build a creation payload."""
    payload = {
        "name": name,
        "priority": priority,
        "conditions": {"ctx.rating": {"lte": 2}},
        "result": {"offer_code": "RECOVER20", "reason": "detractor_recovery"},
    }
    payload.update(overrides)
    return RuleCreate(**payload)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def test_create_and_get(rules) -> None:
    """A stored rule round-trips, jsonb columns included."""
    created = await rules.create("bar-pepe", _create())

    found = await rules.get("bar-pepe", created.rule_id)

    assert found.name == "recover"
    assert found.conditions == {"ctx.rating": {"lte": 2}}
    assert found.result["offer_code"] == "RECOVER20"
    assert found.enabled is True


async def test_a_duplicate_name_is_refused(rules) -> None:
    """Names identify a rule in a listing, so they have to be unique."""
    await rules.create("bar-pepe", _create())

    with pytest.raises(RuleAlreadyExists):
        await rules.create("bar-pepe", _create())


async def test_the_same_name_is_free_for_another_tenant(rules) -> None:
    """Uniqueness is scoped, like everything else here."""
    await rules.create("bar-pepe", _create())

    theirs = await rules.create("hotel-x", _create())

    assert theirs.tenant_id == "hotel-x"


async def test_update_applies_only_given_fields(rules) -> None:
    """A partial patch leaves the rest of the rule alone."""
    created = await rules.create("bar-pepe", _create())

    updated = await rules.update(
        "bar-pepe", created.rule_id, RuleUpdate(priority=5)
    )

    assert updated.priority == 5
    assert updated.conditions == {"ctx.rating": {"lte": 2}}
    assert updated.name == "recover"


async def test_update_replaces_a_jsonb_document(rules) -> None:
    """Conditions are replaced wholesale, not merged key by key."""
    created = await rules.create("bar-pepe", _create())

    updated = await rules.update(
        "bar-pepe",
        created.rule_id,
        RuleUpdate(conditions={"ctx.rating": {"lte": 1}}),
    )

    assert updated.conditions == {"ctx.rating": {"lte": 1}}


async def test_an_empty_patch_is_a_noop(rules) -> None:
    """PATCH with nothing must not blank the row."""
    created = await rules.create("bar-pepe", _create())

    updated = await rules.update("bar-pepe", created.rule_id, RuleUpdate())

    assert updated.name == "recover"
    assert updated.priority == 100


async def test_delete(rules) -> None:
    """Removing a rule reports whether there was one."""
    created = await rules.create("bar-pepe", _create())

    assert await rules.delete("bar-pepe", created.rule_id) is True
    assert await rules.delete("bar-pepe", created.rule_id) is False


async def test_a_malformed_id_reads_as_a_miss(rules) -> None:
    """These ids come from URL paths; a bad one is a 404, not a 500."""
    assert await rules.get("bar-pepe", "not-a-uuid") is None
    assert await rules.update("bar-pepe", "../etc", RuleUpdate(priority=1)) is None
    assert await rules.delete("bar-pepe", "nope") is False


# ---------------------------------------------------------------------------
# Ordering and isolation
# ---------------------------------------------------------------------------


async def test_rules_come_back_in_evaluation_order(rules) -> None:
    """Highest priority first — the order FIRST_MATCH depends on."""
    await rules.create("bar-pepe", _create("low", priority=1))
    await rules.create("bar-pepe", _create("high", priority=100))
    await rules.create("bar-pepe", _create("middle", priority=50))

    listed = await rules.list_rules("bar-pepe")

    assert [r.name for r in listed] == ["high", "middle", "low"]


async def test_equal_priorities_come_back_in_a_stable_order(rules) -> None:
    """``compile()`` sorts stably, so the SQL order decides ties.

    Without ``rule_id`` as a second key the winner between two equal-priority
    offers would be whatever order Postgres happened to return.
    """
    for name in ("a", "b", "c", "d"):
        await rules.create("bar-pepe", _create(name, priority=50))

    runs = {
        tuple(r.name for r in await rules.list_rules("bar-pepe"))
        for _ in range(5)
    }

    assert len(runs) == 1


async def test_disabled_rules_are_listed_but_not_loaded(rules) -> None:
    """A tenant still wants to see a rule they switched off."""
    await rules.create("bar-pepe", _create("on"))
    await rules.create("bar-pepe", _create("off", enabled=False))

    listed = await rules.list_rules("bar-pepe")
    loaded = await rules.list_rules("bar-pepe", enabled_only=True)

    assert {r.name for r in listed} == {"on", "off"}
    assert {r.name for r in loaded} == {"on"}


async def test_a_tenant_cannot_read_another_tenants_rules(rules) -> None:
    """The isolation the whole BaseRepository design exists to enforce."""
    created = await rules.create("bar-pepe", _create())

    assert await rules.get("hotel-x", created.rule_id) is None
    assert await rules.list_rules("hotel-x") == []


async def test_rulesets_are_separate(rules) -> None:
    """The column exists so a second vertical flow needs no migration."""
    await rules.create("bar-pepe", _create("coupon"))
    await rules.create("bar-pepe", _create("other", ruleset="escalation"))

    assert [r.name for r in await rules.list_rules("bar-pepe")] == ["coupon"]
    assert [
        r.name for r in await rules.list_rules("bar-pepe", ruleset="escalation")
    ] == ["other"]


# ---------------------------------------------------------------------------
# Seeding and the navrules adapter
# ---------------------------------------------------------------------------


async def test_seeding_is_idempotent(rules) -> None:
    """Re-provisioning a tenant must not duplicate its ruleset."""
    first = await rules.seed("bar-pepe", DEFAULT_ELIGIBILITY_RULES)
    second = await rules.seed("bar-pepe", DEFAULT_ELIGIBILITY_RULES)

    assert first == len(DEFAULT_ELIGIBILITY_RULES)
    assert second == 0
    assert len(await rules.list_rules("bar-pepe")) == len(DEFAULT_ELIGIBILITY_RULES)


async def test_the_storage_yields_specs_navrules_accepts(rules) -> None:
    """Asserted by building the RuleSet, not by comparing dicts.

    Comparing shapes would pass while navrules rejected the result; building
    is the only check that means anything.
    """
    await rules.seed("bar-pepe", DEFAULT_ELIGIBILITY_RULES)

    specs = await PostgresRuleStorage(rules, "bar-pepe").load()
    ruleset = build_ruleset(specs)

    assert len(ruleset) == len(DEFAULT_ELIGIBILITY_RULES)
    assert ruleset.is_rust_compilable
    assert ruleset.rules[0].name == "recover_detractor"


async def test_the_storage_emits_the_rule_type_as_a_constant(rules) -> None:
    """``rule_type`` is not a column, so no SQL can set it to something else."""
    await rules.create("bar-pepe", _create())

    specs = await PostgresRuleStorage(rules, "bar-pepe").load()

    assert all(spec["rule_type"] == "ConditionRule" for spec in specs)


async def test_the_storage_is_bound_to_one_tenant(rules) -> None:
    """``AbstractStorage.load()`` takes no arguments; the scope is the object."""
    await rules.create("bar-pepe", _create())

    assert await PostgresRuleStorage(rules, "hotel-x").load() == []


async def test_the_storage_skips_disabled_rules(rules) -> None:
    """What the runtime compiles is what is switched on."""
    await rules.create("bar-pepe", _create("on"))
    await rules.create("bar-pepe", _create("off", enabled=False))

    specs = await PostgresRuleStorage(rules, "bar-pepe").load()

    assert [s["name"] for s in specs] == ["on"]
