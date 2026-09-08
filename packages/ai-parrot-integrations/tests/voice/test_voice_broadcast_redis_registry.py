"""Redis-backed broadcast registry tests (FEAT-537 TASK-2953).

Two layers:

1. **The whole TASK-2952 contract suite, re-run against Redis.** Every
   ``async def test_*`` in ``test_voice_broadcast_registry`` is re-bound here
   with a Redis ``registry`` fixture, so the two implementations are held to
   one set of semantics rather than two similar-looking ones. A divergence in
   the Lua shows up as a named contract test failing, not as a subtle
   production bug.
2. **Cross-instance tests** that only Redis can express: two registries on
   separate connections racing admissions and ownership, and stop visibility
   across processes.

Skipped with an explicit NOT VERIFIED reason when no Redis is reachable.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import uuid
from typing import Any, AsyncIterator, Callable, Dict, List

import pytest

from parrot.integrations.liveavatar.broadcast import (
    MAX_VIEWERS,
    BroadcastDescriptor,
    ParticipantPrincipal,
    errors,
)

from . import test_voice_broadcast_registry as contract

REDIS_URL = os.environ.get("PARROT_TEST_REDIS_URL", "redis://localhost:6379/3")

TENANT = contract.TENANT
AGENT = contract.AGENT
BROADCAST = contract.BROADCAST


def _new_registry(prefix: str, clock: Callable[[], float]) -> Any:
    """Build a Redis registry bound to an isolated key prefix and a fake clock."""
    from parrot.integrations.liveavatar.broadcast.redis_registry import (
        RedisBroadcastRegistry,
    )

    return RedisBroadcastRegistry.from_url(REDIS_URL, key_prefix=prefix, clock=clock)


@pytest.fixture
def clock() -> contract.FakeClock:
    return contract.FakeClock()


@pytest.fixture
async def registry(clock: contract.FakeClock) -> AsyncIterator[Any]:
    """Redis registry on a unique prefix; skips when Redis is unreachable.

    Named ``registry`` on purpose: it shadows the in-memory fixture for every
    contract test re-bound in this module.
    """
    prefix = f"t537:{uuid.uuid4().hex[:12]}"
    reg = _new_registry(prefix, clock)
    try:
        await reg.ping()
    except Exception as exc:  # noqa: BLE001 — any driver error means "no Redis"
        await reg.aclose()
        pytest.skip(f"Redis not reachable at {REDIS_URL} — NOT VERIFIED: {exc}")
    try:
        yield reg
    finally:
        await reg.purge_all_for_tests()
        await reg.aclose()


# ── Re-bind the whole TASK-2952 contract suite against Redis ───────────────


def _contract_tests() -> Dict[str, Any]:
    """Collect every async test function from the in-memory contract module."""
    return {
        name: obj
        for name, obj in vars(contract).items()
        if name.startswith("test_") and inspect.iscoroutinefunction(obj)
    }


def _rebind(name: str, func: Any) -> Any:
    """Wrap a contract test so pytest injects *this* module's fixtures."""

    async def _runner(registry: Any, clock: contract.FakeClock) -> None:
        parameters = inspect.signature(func).parameters
        kwargs: Dict[str, Any] = {}
        if "registry" in parameters:
            kwargs["registry"] = registry
        if "clock" in parameters:
            kwargs["clock"] = clock
        await func(**kwargs)

    _runner.__name__ = f"test_redis_contract_{name[len('test_'):]}"
    _runner.__doc__ = f"Redis parity for the in-memory contract test {name!r}."
    return _runner


for _name, _func in _contract_tests().items():
    _bound = _rebind(_name, _func)
    globals()[_bound.__name__] = _bound
del _name, _func, _bound


# ── Cross-instance behaviour (Redis-only) ──────────────────────────────────


def _principal(user: str) -> ParticipantPrincipal:
    return ParticipantPrincipal(
        user_id=user, tenant_id=TENANT, agent_id=AGENT, display_name=user
    )


def _descriptor() -> BroadcastDescriptor:
    return BroadcastDescriptor(
        broadcast_id=BROADCAST,
        tenant_id=TENANT,
        agent_id=AGENT,
        creator_user_id="creator",
    )


@pytest.fixture
async def two_registries(
    registry: Any, clock: contract.FakeClock
) -> AsyncIterator[tuple[Any, Any]]:
    """A second registry object on its own connection, sharing the key space."""
    peer = _new_registry(registry._prefix, clock)  # noqa: SLF001 — same key space
    try:
        yield registry, peer
    finally:
        await peer.aclose()


async def test_two_instances_never_admit_eleventh(
    two_registries: tuple[Any, Any],
) -> None:
    first, second = two_registries
    await first.create(_descriptor())

    async def _join(reg: Any, index: int) -> Any:
        return await reg.reserve_viewer(
            TENANT, BROADCAST, _principal(f"user-{index}"), f"identity-{index}"
        )

    results = await asyncio.gather(
        *(
            _join(first if index % 2 == 0 else second, index)
            for index in range(MAX_VIEWERS + 2)
        ),
        return_exceptions=True,
    )
    admitted = [r for r in results if not isinstance(r, BaseException)]
    rejected = [r for r in results if isinstance(r, errors.ViewerLimitReached)]
    assert len(admitted) == MAX_VIEWERS
    assert len(rejected) == 2

    # Both connections agree, and exactly one moderator was elected.
    leases_a = await first.list_leases(TENANT, BROADCAST)
    leases_b = await second.list_leases(TENANT, BROADCAST)
    assert len(leases_a) == len(leases_b) == MAX_VIEWERS
    assert sum(1 for a in admitted if a.is_first) == 1

    descriptor = await second.get(TENANT, BROADCAST)
    assert descriptor is not None
    first_admission = next(a for a in admitted if a.is_first)
    assert descriptor.moderator_lease_id == first_admission.lease.lease_id


async def test_owner_claim_race_single_winner(
    two_registries: tuple[Any, Any],
) -> None:
    first, second = two_registries
    await first.create(_descriptor())

    outcomes = await asyncio.gather(
        *(
            (first if index % 2 == 0 else second).claim_owner(
                TENANT, BROADCAST, f"worker-{index}"
            )
            for index in range(6)
        )
    )
    winners = [epoch for claimed, epoch in outcomes if claimed]
    assert len(winners) == 1

    descriptor = await second.get(TENANT, BROADCAST)
    assert descriptor is not None
    assert descriptor.owner_epoch == winners[0]
    assert descriptor.owner_worker_id is not None


async def test_stop_requested_on_a_is_visible_on_b(
    two_registries: tuple[Any, Any],
) -> None:
    first, second = two_registries
    await first.create(_descriptor())
    admission = await first.reserve_viewer(
        TENANT, BROADCAST, _principal("moderator"), "identity-moderator"
    )
    assert await second.stop_requested(TENANT, BROADCAST) is False
    await first.request_stop(TENANT, BROADCAST, admission.lease.lease_id)
    assert await second.stop_requested(TENANT, BROADCAST) is True


async def test_floor_barrier_is_visible_across_instances(
    two_registries: tuple[Any, Any],
) -> None:
    first, second = two_registries
    await first.create(_descriptor())
    moderator = await first.reserve_viewer(
        TENANT, BROADCAST, _principal("moderator"), "identity-moderator"
    )
    await first.confirm_viewer(TENANT, BROADCAST, moderator.lease.lease_id)
    guest = await second.reserve_viewer(
        TENANT, BROADCAST, _principal("guest"), "identity-guest"
    )
    await second.confirm_viewer(TENANT, BROADCAST, guest.lease.lease_id)

    current = await first.get(TENANT, BROADCAST)
    assert current is not None
    switching = await first.grant_floor(
        TENANT,
        BROADCAST,
        moderator.lease.lease_id,
        guest.lease.lease_id,
        current.version,
    )
    # The producer acknowledging the barrier may live on the other worker.
    granted = await second.commit_floor(
        TENANT, BROADCAST, guest.lease.lease_id, switching.floor_epoch
    )
    assert granted.speaker_lease_id == guest.lease.lease_id

    seen_by_first = await first.get(TENANT, BROADCAST)
    assert seen_by_first is not None
    assert seen_by_first.speaker_lease_id == guest.lease.lease_id


async def test_conflicting_grants_across_instances_install_one_speaker(
    two_registries: tuple[Any, Any],
) -> None:
    first, second = two_registries
    await first.create(_descriptor())
    moderator = await first.reserve_viewer(
        TENANT, BROADCAST, _principal("moderator"), "identity-moderator"
    )
    await first.confirm_viewer(TENANT, BROADCAST, moderator.lease.lease_id)
    guests = []
    for name in ("a", "b"):
        admission = await second.reserve_viewer(
            TENANT, BROADCAST, _principal(f"guest-{name}"), f"identity-{name}"
        )
        await second.confirm_viewer(TENANT, BROADCAST, admission.lease.lease_id)
        guests.append(admission)

    current = await first.get(TENANT, BROADCAST)
    assert current is not None
    results = await asyncio.gather(
        first.grant_floor(
            TENANT,
            BROADCAST,
            moderator.lease.lease_id,
            guests[0].lease.lease_id,
            current.version,
        ),
        second.grant_floor(
            TENANT,
            BROADCAST,
            moderator.lease.lease_id,
            guests[1].lease.lease_id,
            current.version,
        ),
        return_exceptions=True,
    )
    assert len([r for r in results if not isinstance(r, BaseException)]) == 1
    assert len([r for r in results if isinstance(r, errors.StaleVersion)]) == 1

    descriptor = await first.get(TENANT, BROADCAST)
    assert descriptor is not None
    assert descriptor.speaker_lease_id is None


# ── Secret hygiene (AC3) ───────────────────────────────────────────────────


async def test_no_secret_like_values_in_redis(registry: Any) -> None:
    await registry.create(_descriptor())
    moderator = await registry.reserve_viewer(
        TENANT, BROADCAST, _principal("moderator"), "identity-moderator"
    )
    await registry.confirm_viewer(TENANT, BROADCAST, moderator.lease.lease_id)
    await registry.claim_owner(TENANT, BROADCAST, "worker-a")
    await registry.raise_hand(TENANT, BROADCAST, moderator.lease.lease_id)

    client = registry._redis  # noqa: SLF001 — deliberate whitebox scan
    forbidden = ("token", "secret", "ws_url", "api_key", "password", "credential")
    scanned: List[str] = []
    async for key in client.scan_iter(match=f"{registry._prefix}:*", count=200):  # noqa: SLF001
        scanned.append(key)
        kind = await client.type(key)
        if kind == "string":
            blob = await client.get(key)
        elif kind == "hash":
            blob = str(await client.hgetall(key))
        elif kind == "zset":
            blob = str(await client.zrange(key, 0, -1, withscores=True))
        elif kind == "set":
            blob = str(await client.smembers(key))
        else:  # pragma: no cover — no other type is written
            blob = ""
        lowered = f"{key}{blob}".lower()
        # ``credential_expires_at`` is a timestamp field name, not a credential.
        lowered = lowered.replace("credential_expires_at", "cred_exp_at")
        offending = [fragment for fragment in forbidden if fragment in lowered]
        assert offending == [], f"{key} contains {offending}"
    assert scanned, "expected the registry to have written keys"
