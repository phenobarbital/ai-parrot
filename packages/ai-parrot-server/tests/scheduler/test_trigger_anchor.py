"""Cross-worker trigger anchoring for fire claims (FEAT-676, ledger aa813ccc1927).

Each manager builds its own trigger at its own instant — exactly what two gunicorn workers do when they
load the same DB row or ``@schedule`` job — and the fire times (hence the Redis claim keys) must match.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from parrot.scheduler import SchedulerManager
from parrot.scheduler.coordination import INTERVAL_ANCHOR, RedisFireCoordinator


def _fire_times(trigger, now: datetime, count: int = 4) -> List[datetime]:
    """Return the next ``count`` fire times APScheduler would compute from ``now``."""
    times: List[datetime] = []
    previous = None
    for _ in range(count):
        fire = trigger.get_next_fire_time(previous, now)
        times.append(fire)
        previous = fire
        now = fire
    return times


async def _build_independent_triggers(schedule_type: str, config: dict, **kwargs):
    """Build one trigger per manager, at different instants, like two workers would."""
    worker_a = SchedulerManager(registered_name="anchor-worker-a")
    worker_b = SchedulerManager(registered_name="anchor-worker-b")
    trigger_a = worker_a._create_trigger(schedule_type, config, **kwargs)
    await asyncio.sleep(0.05)
    trigger_b = worker_b._create_trigger(schedule_type, config, **kwargs)
    return trigger_a, trigger_b


async def test_interval_triggers_built_independently_share_fire_times() -> None:
    """AC1: independently built interval triggers produce one shared fire-time grid."""
    trigger_a, trigger_b = await _build_independent_triggers("interval", {"minutes": 5})
    now = datetime.now(timezone.utc)
    times_a = _fire_times(trigger_a, now)
    times_b = _fire_times(trigger_b, now)
    assert times_a == times_b
    for fire in times_a:
        assert fire >= now
        assert (fire - INTERVAL_ANCHOR) % timedelta(minutes=5) == timedelta(0)


async def test_independent_interval_triggers_claim_once(scheduler_redis, scheduler_namespace) -> None:
    """AC2: each worker claims its own computed due time; exactly one claim wins."""
    trigger_a, trigger_b = await _build_independent_triggers("interval", {"seconds": 30})
    now = datetime.now(timezone.utc)
    run_time_a = trigger_a.get_next_fire_time(None, now)
    run_time_b = trigger_b.get_next_fire_time(None, now)
    prefix = f"parrot:scheduler:{scheduler_namespace}:"
    coordinator_a = RedisFireCoordinator(scheduler_redis, prefix=prefix, worker_id="worker-a")
    coordinator_b = RedisFireCoordinator(scheduler_redis, prefix=prefix, worker_id="worker-b")
    wins = await asyncio.gather(
        coordinator_a.claim("auto_service_tick", run_time_a),
        coordinator_b.claim("auto_service_tick", run_time_b),
    )
    assert sorted(wins) == [False, True]


class _SetNxRedis:
    """Dict-backed double for Redis ``SET NX EX`` so AC2 also runs where Redis is unreachable."""

    def __init__(self) -> None:
        self.store: dict = {}

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        """Store ``value`` unless ``nx`` and the key already exists."""
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


async def test_independent_interval_triggers_claim_once_without_redis() -> None:
    """AC2 (offline): the claim keys of independently built triggers collide, so only one worker runs."""
    trigger_a, trigger_b = await _build_independent_triggers("interval", {"minutes": 1})
    now = datetime.now(timezone.utc)
    client = _SetNxRedis()
    coordinator_a = RedisFireCoordinator(client, prefix="parrot:scheduler:anchor:", worker_id="worker-a")
    coordinator_b = RedisFireCoordinator(client, prefix="parrot:scheduler:anchor:", worker_id="worker-b")
    wins = [
        await coordinator_a.claim("auto_service_tick", trigger_a.get_next_fire_time(None, now)),
        await coordinator_b.claim("auto_service_tick", trigger_b.get_next_fire_time(None, now)),
    ]
    assert wins == [True, False]
    assert len(client.store) == 1


async def test_once_without_run_date_uses_anchor() -> None:
    """AC3: a persisted ``once`` schedule without run_date fires at the shared anchor on every worker."""
    anchor = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=1)
    trigger_a, trigger_b = await _build_independent_triggers("once", {}, anchor=anchor)
    assert trigger_a.run_date == trigger_b.run_date == anchor


async def test_once_explicit_run_date_wins_over_anchor() -> None:
    """An explicit run_date keeps precedence over the creation anchor."""
    manager = SchedulerManager(registered_name="anchor-worker-c")
    when = datetime(2030, 1, 1, 8, 0, tzinfo=timezone.utc)
    trigger = manager._create_trigger("once", {"run_date": when}, anchor=datetime(2029, 1, 1, tzinfo=timezone.utc))
    assert trigger.run_date == when


@pytest.mark.parametrize("config", [{"hours": 1}, {"days": 1}, {"weeks": 1, "minutes": 7}])
async def test_interval_anchor_is_epoch_utc(config: dict) -> None:
    """Every interval trigger is anchored at the UTC epoch, whatever its components."""
    manager = SchedulerManager(registered_name="anchor-worker-d")
    trigger = manager._create_trigger("interval", config)
    assert trigger.start_date == INTERVAL_ANCHOR
