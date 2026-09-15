import itertools

import pytest

from parrot.flows.dev_loop.task_scheduler import TaskRef
from parrot.flows.dev_loop.sdd_coder import ChunkAssigner, RosterConfig, RosterProbe, RosterSeat, available_seats


def _roster(n):
    seats = [
        RosterSeat(label="q", backend="nova"),
        RosterSeat(label="g", backend="nvidia"),
        RosterSeat(label="c", backend="codex"),
        RosterSeat(label="h", kind="native"),
    ]
    return RosterConfig(seats=seats[:n])


def _wave(n):
    return [TaskRef(id=f"TASK-{i:04d}", status="pending") for i in range(n)]


@pytest.mark.parametrize("tasks,seats", list(itertools.product(range(1, 21), range(1, 5))))
def test_assign_distinct_seats_per_chunk(tasks, seats):
    chunks = ChunkAssigner(_roster(seats).seats).assign(_wave(tasks), {})
    for ch in chunks:
        labels = [t.seat_label for t in ch.tasks]
        assert len(labels) == len(set(labels)) and len(labels) <= seats


def test_assign_rotates_start_between_chunks():
    chunks = ChunkAssigner(_roster(4).seats).assign(_wave(5), {})
    assert chunks[1].tasks[0].seat_label == _roster(4).seats[1].label


def test_assign_single_seat_is_serial():
    assert all(len(c.tasks) == 1 for c in ChunkAssigner(_roster(1).seats).assign(_wave(6), {}))


def test_retry_seat_is_different():
    a = ChunkAssigner(_roster(3).seats)
    assert a.retry_seat("q", {"q"}).label != "q"
    assert a.retry_seat("q", {"q", "g", "c"}) is None


async def test_probe_drops_seat_without_key():
    probe = RosterProbe(config_getter=lambda k, fallback=None: None, which=lambda b: None)
    res = await probe.probe(_roster(4))
    by = {r.label: r for r in res}
    assert not by["q"].available and "BEDROCK_MANTLE_API_KEY" in by["q"].reason
    assert not by["c"].available and by["h"].available


async def test_probe_codex_requires_binary():
    probe = RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: None)
    res = await probe.probe(RosterConfig(seats=[RosterSeat(label="c", backend="codex")]))
    assert not res[0].available and "not found" in res[0].reason


async def test_probe_native_always_available():
    probe = RosterProbe(config_getter=lambda k, fallback=None: None, which=lambda b: None)
    res = await probe.probe(RosterConfig(seats=[RosterSeat(label="h", kind="native")]))
    assert res[0].available


async def test_probe_switches_to_fallback_model():
    async def smoke(seat, model):
        return model == "fb"

    probe = RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: "/bin/x", smoke=smoke)
    seat = RosterSeat(label="c", backend="codex", model="primary", fallback_model="fb")
    res = (await probe.probe(RosterConfig(seats=[seat])))[0]
    assert res.available and res.fallback_used and res.model_used == "fb"
    assert available_seats(RosterConfig(seats=[seat]), [res])[0].model == "fb"


async def test_probe_never_raises():
    async def smoke(seat, model):
        raise RuntimeError("boom")

    probe = RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: "/bin/x", smoke=smoke)
    res = (await probe.probe(_roster(1)))[0]
    assert not res.available and "boom" in res.reason
