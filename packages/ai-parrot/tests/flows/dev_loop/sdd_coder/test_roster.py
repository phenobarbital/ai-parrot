import itertools

import pytest

from parrot.flows.dev_loop.task_scheduler import TaskRef
from parrot.flows.dev_loop.sdd_coder import ChunkAssigner, RosterConfig, RosterProbe, RosterSeat, available_seats
from parrot.knowledge.wiki.ledger.coder_suspensions import ModelKey


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
    # An explicit model is required here (FEAT-559): an empty `model` is now excluded
    # as `model_identity_required` *before* any smoke call, which this test is not about.
    seat = RosterSeat(label="q", backend="nova", model="m")
    res = (await probe.probe(RosterConfig(seats=[seat])))[0]
    assert not res.available and "boom" in res.reason


def test_assign_exclusive_tasks_run_alone_and_first():
    wave = _wave(4)
    wave[2] = TaskRef(id="TASK-0002", status="pending", parallel=False)
    chunks = ChunkAssigner(_roster(4).seats).assign(wave, {})
    assert [[t.task_id for t in c.tasks] for c in chunks] == [["TASK-0002"], ["TASK-0000", "TASK-0001", "TASK-0003"]]


async def test_identity_and_fallback_gate():
    """Excluded primary/fallback IDs and their aliases cause zero calls; an independently
    healthy configured fallback remains eligible."""
    call_count = 0

    async def smoke(seat, model):
        nonlocal call_count
        call_count += 1
        return model == "fb"  # Primary is excluded (never called here); fallback succeeds.

    probe = RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: "/bin/x", smoke=smoke)
    seat = RosterSeat(label="c", backend="codex", model="primary", fallback_model="fb")

    # Exclude primary, fallback should still be probed
    excluded = {ModelKey(backend="codex", model="primary")}
    res = (await probe.probe(RosterConfig(seats=[seat]), excluded=excluded))[0]

    # Primary was excluded, so 0 calls for primary; fallback should be called once
    assert call_count == 1, f"Expected 1 call (fallback only), got {call_count}"
    assert res.available and res.fallback_used and res.model_used == "fb"


async def test_empty_model_is_not_probed():
    """Empty model ID is excluded before a paid call (model_identity_required)."""
    call_count = 0

    async def smoke(seat, model):
        nonlocal call_count
        call_count += 1
        return True

    probe = RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: "/bin/x", smoke=smoke)
    seat = RosterSeat(label="c", backend="codex", model="", fallback_model="fb")

    res = (await probe.probe(RosterConfig(seats=[seat])))[0]

    # Empty model should be excluded, fallback should be probed
    assert call_count == 1, f"Expected 1 call (fallback only), got {call_count}"
    assert res.available and res.fallback_used and res.model_used == "fb"


async def test_failed_primary_is_reported_with_successful_fallback():
    """A failed primary is reported even when fallback succeeds (structured metadata)."""
    call_count = 0

    async def smoke(seat, model):
        nonlocal call_count
        call_count += 1
        if model == "primary":
            return False  # Primary fails
        return True  # Fallback succeeds

    probe = RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: "/bin/x", smoke=smoke)
    seat = RosterSeat(label="c", backend="codex", model="primary", fallback_model="fb")

    res = (await probe.probe(RosterConfig(seats=[seat])))[0]

    # Both primary and fallback should be called
    assert call_count == 2, f"Expected 2 calls, got {call_count}"
    assert res.available
    assert res.fallback_used
    assert res.model_used == "fb"
    # Primary failure metadata should be captured, even though a clean `False`
    # return (not a raised exception) legitimately leaves `probe_exception_class` empty.
    assert res.probe_uid  # Should have a UID from primary probe
    assert res.probe_exception_class == ""


async def test_one_model_failure_does_not_ban_same_backend():
    """One model failure does not ban other models of the same backend."""
    call_count = 0

    async def smoke(seat, model):
        nonlocal call_count
        call_count += 1
        return model != "bad_model"  # Only bad_model fails

    probe = RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: "/bin/x", smoke=smoke)
    seats = [
        RosterSeat(label="c1", backend="codex", model="bad_model"),
        RosterSeat(label="c2", backend="codex", model="good_model"),
    ]

    res = await probe.probe(RosterConfig(seats=seats))

    # Both seats should be probed
    assert call_count == 2, f"Expected 2 calls, got {call_count}"
    assert not res[0].available  # bad_model failed
    assert res[1].available  # good_model succeeded


async def test_excluded_native_seat():
    """Native seats with excluded model are not probed."""
    call_count = 0

    async def smoke(seat, model):
        nonlocal call_count
        call_count += 1
        return True

    probe = RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: "/bin/x", smoke=smoke)
    seat = RosterSeat(label="h", kind="native", model="haiku")

    # Exclude native/haiku
    excluded = {ModelKey(backend="native", model="haiku")}
    res = (await probe.probe(RosterConfig(seats=[seat]), excluded=excluded))[0]

    # Should not call smoke for excluded native seat
    assert call_count == 0, f"Expected 0 calls for excluded native, got {call_count}"
    assert not res.available and "excluded" in res.reason


async def test_smoke_timeout_generates_typed_failure():
    """A smoke timeout generates typed failure evidence."""
    import asyncio

    async def slow_smoke(seat, model):
        await asyncio.sleep(10)  # Will timeout
        return True

    probe = RosterProbe(
        config_getter=lambda k, fallback=None: "x",
        which=lambda b: "/bin/x",
        smoke=slow_smoke,
        smoke_timeout_s=1,  # 1 second timeout
    )
    seat = RosterSeat(label="c", backend="codex", model="test_model")

    res = (await probe.probe(RosterConfig(seats=[seat])))[0]

    assert not res.available
    assert "timed out" in res.reason.lower() or "timeout" in res.reason.lower()
    assert res.probe_exception_class in ("asyncio.TimeoutError", "TimeoutError")
